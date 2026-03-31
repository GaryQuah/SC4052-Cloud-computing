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

# -----------------------------
# Setup
# -----------------------------
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

print("[BOOT] Backend starting...")

# -----------------------------
# Models
# -----------------------------
class HistoryMessage(BaseModel):
    role: str
    content: str

class QueryRequest(BaseModel):
    query: str
    history: list[HistoryMessage] = []

class NotesBody(BaseModel):
    notes: str

# -----------------------------
# Global state
# -----------------------------
meetings_db = []
G = nx.DiGraph()

# -----------------------------
# Helpers
# -----------------------------
def get_next_meeting_id():
    if not meetings_db:
        return 1
    return max(m["id"] for m in meetings_db) + 1


def save_cache():
    print("[CACHE] Saving...")
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"meetings_db": meetings_db}, f, indent=2)
    print("[CACHE] Saved")


def load_cache():
    global meetings_db, G
    print("[CACHE] Loading...")
    if not os.path.exists(CACHE_FILE):
        print("[CACHE] No cache")
        return
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    meetings_db = data.get("meetings_db", [])
    print(f"[CACHE] Loaded meetings: {len(meetings_db)}")
    rebuild_graph()


@app.on_event("startup")
def startup():
    print("[BOOT] Startup")
    load_cache()
    print("[BOOT] Ready")


def rebuild_graph():
    """
    Each meeting gets a node labeled "meeting N" with an is_about edge
    pointing to its title string.

      "meeting 1" --is_about--> "Sprint Review and Payment API Issues"
      "meeting 2" --is_about--> "Q3 Roadmap Planning"
    """
    G.clear()
    for m in meetings_db:
        meeting_node = f"meeting {m['id']}"
        about_node = m["title"]
        G.add_node(meeting_node, type="meeting", meeting_id=m["id"])
        G.add_node(about_node, type="topic")
        G.add_edge(meeting_node, about_node, relation="is_about")
    print(f"[GRAPH] Rebuilt | nodes={G.number_of_nodes()} edges={G.number_of_edges()}")


# -----------------------------
# LLM extraction
# -----------------------------
def extract_title(text: str) -> str:
    """
    Ask the LLM for a concise one-line summary of what the meeting is about.
    This becomes both the display title and the graph topic node.
    """
    res = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": f"""Summarise what this meeting is about in one short phrase (max 10 words).
Return ONLY the phrase, no punctuation, no quotes.

Meeting notes:
{text}"""}],
        temperature=0
    )
    return res.choices[0].message.content.strip()[:120]


# -----------------------------
# Retrieval
# -----------------------------
def retrieve_relevant_meetings(query: str) -> list[int]:
    """
    Fuzzy-match query words against topic nodes, run personalised PageRank,
    return meeting IDs ranked by relevance.
    """
    topic_nodes = [n for n, d in G.nodes(data=True) if d.get("type") == "topic"]
    q_words = [w for w in query.lower().split() if len(w) > 2]

    seed_nodes = {
        node for node in topic_nodes
        if any(word in node.lower() for word in q_words)
    }
    print(f"[RETRIEVE] Seed nodes: {seed_nodes}")

    if seed_nodes and G.number_of_edges() > 0:
        personalization = {n: (1.0 if n in seed_nodes else 0.0) for n in G.nodes()}
        scores = nx.pagerank(G, personalization=personalization, alpha=0.85)

        meeting_scores = [
            (m["id"], scores.get(f"meeting {m['id']}", 0.0))
            for m in meetings_db
        ]
        meeting_scores.sort(key=lambda x: x[1], reverse=True)
        ranked = [mid for mid, score in meeting_scores if score > 0]
        print(f"[RETRIEVE] PageRank meeting ranking: {ranked}")
        if ranked:
            return ranked

    # Fallback: keyword scan over titles and summaries
    print("[RETRIEVE] Falling back to keyword scan")
    return [
        m["id"] for m in meetings_db
        if any(word in m["title"].lower() or word in m["summary"].lower() for word in q_words)
    ]


# -----------------------------
# Query
# -----------------------------
SYSTEM_PROMPT = """You are a precise meeting-notes assistant. Your job is to answer questions \
strictly from the provided meeting data — never from general knowledge or inference.

Core rules:
- ONLY use information present in the meeting notes provided to you.
- If the provided data does not contain enough information to answer, say: \
"The meeting notes don't contain enough information to answer that."
- Never speculate or fill gaps with assumed information.
- Keep answers focused and concise. Do not pad with information the user didn't ask for.

Formatting rules:
- Separate every section or paragraph with a blank line (\\n\\n).
- For lists, put each item on its own line starting with a dash, e.g. "- item one\\n- item two".
- Begin each section with a short plain-text label ending in a colon, e.g. "Key Topics:".
- Never return a wall of text — always break content into readable chunks.
- Do not use markdown syntax such as **, ##, or *. Use plain text and newlines only."""


def query_graph(query: str, history: list[dict] = []) -> str:
    print("\n[QUERY] -------------------------")
    print(f"[QUERY] {query}")

    if not meetings_db:
        return "There are no meetings loaded yet."

    meeting_index = "\n".join(
        f"- Meeting {m['id']} is about: {m['title']}"
        for m in meetings_db
    )

    relevant_ids = retrieve_relevant_meetings(query)
    # Use PageRank-ranked meetings if we got matches, otherwise include all
    target_ids = relevant_ids if relevant_ids else [m["id"] for m in meetings_db]
    relevant_notes = {m["id"]: m["summary"] for m in meetings_db if m["id"] in target_ids}

    user_prompt = f"""Available meetings:
{meeting_index}

Relevant meeting notes:
{json.dumps(relevant_notes, indent=2)}

--- QUESTION ---
{query}

Cite the meeting ID when stating a fact (e.g. "In meeting 2, ...").
If a fact appears in multiple meetings, note all of them."""

    res = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, *history, {"role": "user", "content": user_prompt}],
        temperature=0
    )
    return res.choices[0].message.content


# -----------------------------
# Endpoints
# -----------------------------
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
        title = extract_title(summary)
        meetings_db.append({
            "id": meeting_id,
            "title": title,
            "summary": summary,
        })
        rebuild_graph()
        save_cache()
        return {"message": f"Meeting {meeting_id} saved", "title": title}

    print("[LOAD] Reloading all from disk...")
    meetings_db = []
    G.clear()
    files = sorted(f for f in os.listdir(DATA_DIR) if f.endswith(".txt"))
    for i, file in enumerate(files, start=1):
        with open(os.path.join(DATA_DIR, file), encoding="utf-8", errors="ignore") as f:
            text = f.read()
        meetings_db.append({
            "id": i,
            "title": extract_title(text),
            "summary": text,
        })
    rebuild_graph()
    save_cache()
    return {"message": f"Reloaded {len(meetings_db)} meetings"}


@app.get("/graph")
def get_graph():
    return {
        "node_count": G.number_of_nodes(),
        "edge_count": G.number_of_edges(),
        "nodes": list(G.nodes(data=True)),
        "edges": [
            {"from": u, "to": v, "relation": d.get("relation")}
            for u, v, d in G.edges(data=True)
        ]
    }