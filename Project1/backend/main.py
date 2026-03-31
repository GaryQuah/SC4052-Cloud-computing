import os
import json
import re
import networkx as nx
from fastapi import FastAPI, Body
from pydantic import BaseModel
from typing import Optional
from openai import OpenAI
import dotenv
from fastapi.middleware.cors import CORSMiddleware
import logging

# Setup
dotenv.load_dotenv()
groqKey = os.getenv("GROQ_API_KEY")

client = OpenAI(
    api_key=groqKey,
    base_url="https://api.groq.com/openai/v1"
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data/meetings")
CACHE_FILE = os.path.join(os.path.dirname(__file__), "data/cache.json")

os.makedirs(DATA_DIR, exist_ok=True)

# Models
class HistoryMessage(BaseModel):
    role: str
    content: str

class QueryRequest(BaseModel):
    query: str
    history: list[HistoryMessage] = []

class NotesBody(BaseModel):
    notes: str

# Global state
meetings_db = []
G = nx.DiGraph()

# Helpers
def get_next_meeting_id():
    if not meetings_db:
        return 1
    return max(m["id"] for m in meetings_db) + 1


def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"meetings_db": meetings_db}, f, indent=2)
    print("[CACHE] Saved")


def load_cache():
    global meetings_db, G
    if not os.path.exists(CACHE_FILE):
        print("[CACHE] No cache found")
        return
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    meetings_db = data.get("meetings_db", [])
    print(f"[CACHE] Loaded {len(meetings_db)} meetings")
    rebuild_graph()


@app.on_event("startup")
def startup():
    load_cache()
    print("[BOOT] Ready")


def rebuild_graph():
    G.clear()
    for m in meetings_db:
        for t in m["triples"]:
            subj, obj, rel = t["subject"], t["object"], t["relation"]
            if G.has_edge(subj, obj):
                if rel not in G[subj][obj]["relations"]:
                    G[subj][obj]["relations"].append(rel)
                if m["id"] not in G[subj][obj]["meeting_ids"]:
                    G[subj][obj]["meeting_ids"].append(m["id"])
            else:
                G.add_edge(subj, obj, relations=[rel], meeting_ids=[m["id"]])
    print(f"[GRAPH] nodes={G.number_of_nodes()} edges={G.number_of_edges()}")


# LLM extraction
RELATION_VOCAB = """
Allowed relation types (use ONLY these):
  assigned_to, owns, depends_on, discussed_in, decided,
  action_item, has_status, scheduled_for, involves,
  reported_by, has_priority, related_to
"""

def extract_triples(text: str, meeting_id: int) -> list[dict]:
    print(f"[LLM] Extracting triples for meeting {meeting_id}...")
    res = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": f"""You are an information-extraction assistant for meeting notes.

{RELATION_VOCAB}

Rules:
1. Return ONLY a JSON object — no prose, no markdown fences.
2. Use the EXACT relation types listed above.
3. Normalise entity names: always use full names ("Alice Johnson" not "Alice").
4. Subjects and objects must be noun phrases (no verbs, no sentences).
5. Do NOT invent information not present in the notes.

Output format:
{{"triples":[{{"subject":"<noun>","relation":"<relation>","object":"<noun>"}}]}}

Meeting notes (meeting_id={meeting_id}):
{text}"""}],
        temperature=0
    )
    content = re.sub(r"```(?:json)?", "", res.choices[0].message.content.strip()).strip().rstrip("`")
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        print(f"[LLM] Parse failed. Raw: {content[:200]}")
        return []
    triples = json.loads(match.group(0)).get("triples", [])
    print(f"[LLM] Extracted {len(triples)} triples")
    return triples


def extract_title(text: str) -> str:
    res = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": f"""Summarise what this meeting is about in one short phrase (max 10 words).
Return ONLY the phrase, no punctuation, no quotes.

Meeting notes:
{text}"""}],
        temperature=0
    )
    return res.choices[0].message.content.strip()[:120]


# Retrieval
def retrieve_meeting_ids(query: str) -> list[int]:
    """
    1. Ask LLM to extract seed entities from the query.
    2. Fuzzy-match seeds against graph nodes.
    3. Personalised PageRank from seed nodes → score every meeting.
    4. Fallback: keyword scan over triples if no seeds matched.
    """
    # Step 1: LLM entity extraction
    res = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": f"""Extract the key named entities (people, projects, teams, topics) from this query.
Return ONLY a JSON array of strings, e.g. ["Alice Johnson", "Project Phoenix"].
Query: {query}"""}],
        temperature=0
    )
    content = re.sub(r"```(?:json)?", "", res.choices[0].message.content.strip()).strip().rstrip("`")
    try:
        entities = json.loads(content)
        if not isinstance(entities, list):
            raise ValueError
        entities = [str(e) for e in entities]
    except Exception:
        entities = [w for w in query.split() if len(w) > 2]

    print(f"[RETRIEVE] Entities: {entities}")

    # Step 2: Fuzzy-match entities to graph nodes - user might not input same form as in graph
    nodes = list(G.nodes())
    seed_nodes = {
        node for entity in entities
        for node in nodes
        if entity.lower() in node.lower() or node.lower() in entity.lower()
    }
    print(f"[RETRIEVE] Seed nodes: {seed_nodes}")

    # Step 3: Personalised PageRank
    if seed_nodes and G.number_of_edges() > 0:
        personalization = {n: (1.0 if n in seed_nodes else 0.0) for n in G.nodes()}
        scores = nx.pagerank(G, personalization=personalization, alpha=0.85)

        # Collect meeting_ids from high-scoring edges, ranked by score
        meeting_scores: dict[int, float] = {}
        for u, v, data in G.edges(data=True):
            edge_score = scores.get(u, 0) + scores.get(v, 0)
            for mid in data.get("meeting_ids", []):
                meeting_scores[mid] = meeting_scores.get(mid, 0) + edge_score

        ranked = sorted(meeting_scores, key=meeting_scores.get, reverse=True)
        print(f"[RETRIEVE] PageRank ranking: {ranked}")
        if ranked:
            return ranked

    # Step 4: Keyword fallback across triples
    print("[RETRIEVE] Falling back to keyword scan")
    q_words = [w.lower() for w in query.split() if len(w) > 2]
    seen = set()
    results = []
    for m in meetings_db:
        for t in m["triples"]:
            text = f"{t['subject']} {t['relation']} {t['object']}".lower()
            if any(w in text for w in q_words) and m["id"] not in seen:
                seen.add(m["id"])
                results.append(m["id"])
    return results


# Query
SYSTEM_PROMPT = """You are a precise meeting-notes assistant. Answer questions strictly \
from the provided meeting data — never from general knowledge or inference.

Rules:
- Only use information present in the meeting index or notes provided.
- If the data doesn't contain enough information, say so plainly.
- Cite the meeting ID when stating a fact, e.g. "In meeting 2, ...".
- Never speculate or pad your answer.

Formatting:
- Use blank lines between sections.
- Use dashes for lists.
- No markdown (no **, ##, *)."""


def query_graph(query: str, history: list[dict] = []) -> str:
    print(f"\n[QUERY] {query}")

    if not meetings_db:
        return "There are no meetings loaded yet."

    meeting_index = "\n".join(
        f"- Meeting {m['id']}: {m['title']}" for m in meetings_db
    )

    relevant_ids = retrieve_meeting_ids(query)
    target_ids = relevant_ids if relevant_ids else [m["id"] for m in meetings_db]
    relevant_notes = {m["id"]: m["summary"] for m in meetings_db if m["id"] in target_ids}

    user_prompt = f"""Available meetings:
{meeting_index}

Relevant meeting notes:
{json.dumps(relevant_notes, indent=2)}

--- QUESTION ---
{query}"""

    res = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            *history,
            {"role": "user", "content": user_prompt},
        ],
        temperature=0
    )
    return res.choices[0].message.content


# Endpoints
@app.post("/query")
def query(req: QueryRequest):
    history = [{"role": m.role, "content": m.content} for m in req.history]
    return {"answer": query_graph(req.query, history)}


@app.post("/load-meetings")
def load(notes_body: Optional[NotesBody] = Body(None)):
    global meetings_db

    if notes_body and notes_body.notes:
        summary = notes_body.notes
        meeting_id = get_next_meeting_id()
        print(f"[LOAD] Adding meeting {meeting_id}")
        triples = extract_triples(summary, meeting_id)
        meetings_db.append({
            "id": meeting_id,
            "title": extract_title(summary),
            "summary": summary,
            "triples": triples,
        })
        rebuild_graph()
        save_cache()
        return {"message": f"Meeting {meeting_id} saved", "triples_extracted": len(triples)}

    print("[LOAD] Reloading all from disk...")
    meetings_db = []
    G.clear()
    files = sorted(f for f in os.listdir(DATA_DIR) if f.endswith(".txt"))
    for i, file in enumerate(files, start=1):
        with open(os.path.join(DATA_DIR, file), encoding="utf-8", errors="ignore") as f:
            text = f.read()
        triples = extract_triples(text, i)
        meetings_db.append({
            "id": i,
            "title": extract_title(text),
            "summary": text,
            "triples": triples,
        })
    rebuild_graph()
    save_cache()
    return {"message": f"Reloaded {len(meetings_db)} meetings"}


@app.get("/graph")
def get_graph():
    return {
        "node_count": G.number_of_nodes(),
        "edge_count": G.number_of_edges(),
        "nodes": list(G.nodes()),
        "edges": [
            {"from": u, "to": v, "relations": d.get("relations"), "meeting_ids": d.get("meeting_ids")}
            for u, v, d in G.edges(data=True)
        ]
    }