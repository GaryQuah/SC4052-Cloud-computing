import os
import json
import re
import networkx as nx
from openai import OpenAI
import dotenv
import logging
from typing import Optional

# Setup
dotenv.load_dotenv()
groqKey = os.getenv("GROQ_API_KEY")

client = OpenAI(
    api_key=groqKey,
    base_url="https://api.groq.com/openai/v1"
)

logging.basicConfig(level=logging.INFO)

DATA_DIR  = os.path.join(os.path.dirname(__file__), "data/meetings")
CACHE_FILE = os.path.join(os.path.dirname(__file__), "data/cache.json")

# Global var
meetings_db: list[dict] = []
meeting_graphs: dict[int, nx.DiGraph] = {}  

def get_next_meeting_id() -> int:
    existing_ids = []
    for filename in os.listdir(DATA_DIR):
        if filename.startswith("meeting_") and filename.endswith(".txt"):
            try:
                existing_ids.append(int(filename.split("_")[1].split(".")[0]))
            except (ValueError, IndexError):
                continue
    return max(existing_ids) + 1 if existing_ids else 1

# write to json file the meetings_db
def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"meetings_db": meetings_db}, f, indent=2)
    print("[CACHE] Saved")

# Build a graph based on the data in cache.json, saves tokens from caching rather than getting LLM to rebuild db on startup / reload
# If cache is missing, empty, or corrupt, automatically rebuild from disk
def load_cache():
    global meetings_db
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Validate cache against disk — drop any meeting whose .txt file no longer exists
            loaded = data.get("meetings_db", [])
            valid = [
                m for m in loaded
                if os.path.exists(os.path.join(DATA_DIR, f"meeting_{m['id']}.txt"))
            ]
            dropped = len(loaded) - len(valid)
            if dropped:
                logging.warning(f"[CACHE] Dropped {dropped} meeting(s) whose .txt files no longer exist")

            meetings_db = valid
            print(f"[CACHE] Loaded {len(meetings_db)} meetings")
            rebuild_graphs()

            # Persist the cleaned cache back to disk if anything was dropped
            if dropped:
                save_cache()

            return

        except (json.JSONDecodeError, OSError) as e:
            logging.warning(f"[CACHE] Could not read cache ({e}) — rebuilding from disk")

    # Cache missing, empty, or corrupt — rebuild from disk
    print("[CACHE] Rebuilding from disk...")
    meetings_db = []
    meeting_graphs.clear()

    for file in sorted(f for f in os.listdir(DATA_DIR) if f.endswith(".txt")):
        try:
            meeting_id = int(file.split("_")[1].split(".")[0])
        except (ValueError, IndexError):
            continue
        with open(os.path.join(DATA_DIR, file), encoding="utf-8", errors="ignore") as f:
            text = f.read()

        triples = extract_triples(text, meeting_id)
        if not triples:
            logging.warning(f"[CACHE] Meeting {meeting_id} produced no triples — graph queries will return no context")

        meetings_db.append({
            "id": meeting_id,
            "title": extract_title(text),
            "summary": text,
            "triples": triples,
        })

    rebuild_graphs()
    save_cache()
    print(f"[CACHE] Rebuilt and saved {len(meetings_db)} meetings")

# Create a nx.graph from the meeting triples, merging multiple relations between the same nodes into a list 
def build_meeting_graph(m: dict) -> nx.DiGraph:
    G = nx.DiGraph()
    for t in m["triples"]:
        subj, obj, rel = t["subject"], t["object"], t["relation"]
        if G.has_edge(subj, obj):
            if rel not in G[subj][obj]["relations"]:
                G[subj][obj]["relations"].append(rel)
        else:
            G.add_edge(subj, obj, relations=[rel])
    return G

#  Rebuild graphs
def rebuild_graphs():
    meeting_graphs.clear()
    for m in meetings_db:
        meeting_graphs[m["id"]] = build_meeting_graph(m)
    print(f"[GRAPH] Built {len(meeting_graphs)} meeting graphs")
    for mid, G in meeting_graphs.items():
        print(f"  Meeting {mid}: nodes={G.number_of_nodes()} edges={G.number_of_edges()}")

# Get LLM to extract triples, need to adjust prompt to ensure better triple extraction.
def extract_triples(text: str, meeting_id: int) -> list[dict]:
    print(f"[LLM] Extracting triples for meeting {meeting_id}...")
    res = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": f"""You are an information-extraction assistant for meeting notes.
Your job is to extract every fact from the notes as subject-relation-object triples.

Rules:
1. Return ONLY a JSON object, no prose, no markdown fences.
2. Extract one triple per sentence where possible, do not merge multiple facts into one triple.
3. Relation types should be short verb phrases that naturally describe the relationship,
   e.g. "assigned_to", "raised_concern_about", "suggested", "approved", "scheduled_for".
4. Normalise entity names: always use full names ("Alice Johnson" not "Alice").
5. Subjects and objects must be noun phrases (no verbs, no sentences).
6. Do NOT invent information not present in the notes.
7. People are the most important entities, every named attendee must appear as a
   subject in multiple triples reflecting their specific contributions and action items.

Output format:
{{"triples":[{{"subject":"<noun>","relation":"<relation>","object":"<noun>"}}]}}

Meeting notes (meeting_id={meeting_id}):
{text}"""}],
        temperature=0
    )
    content = re.sub(r"```(?:json)?", "", res.choices[0].message.content.strip()).strip().rstrip("`")
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        logging.warning(f"[LLM] Failed to extract triples for meeting {meeting_id}. Response:\n{content}")
        return []
    triples = json.loads(match.group(0)).get("triples", [])
    print(f"[LLM] Extracted {len(triples)} triples")
    return triples

# Get LLM to extract title from meeting notes, sometimes LLM misses the actual title and just returns "Meeting notes" or similar,
# so added some rules to ensure it extracts a title rather than just "meeting 1"
def extract_title(text: str) -> str:
    res = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": f"""Summarise what this meeting is about in one short phrase (max 10 words).
Return ONLY the phrase, no punctuation, no quotes.

Meeting notes:
{text}"""}],
        temperature=0
    )
    # return a shorter meeting title if it exceeds 120 characters
    return res.choices[0].message.content.strip()[:120]

# Identify which meeting(s) a user query is about, to determine which graph(s) to run PageRank on
def resolve_target_meetings(query: str) -> list[int]:
    # Get a list of meeting ids from the db based on unique title
    meeting_index = "\n".join(
        f"- Meeting {m['id']}: {m['title']}" for m in meetings_db
    )
    res = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": f"""Given the list of meetings below, identify which meeting id(s) the user query is about.
Return ONLY a JSON array of integer meeting ids, e.g. [1] or [1, 2].
If the query spans all meetings or is not specific to one, return all IDs.

Meetings:
{meeting_index}

Query: {query}"""}],
        temperature=0
    )
    content = re.sub(r"```(?:json)?", "", res.choices[0].message.content.strip()).strip().rstrip("`")
    try:
        ids = json.loads(content)
        if not isinstance(ids, list):
            raise ValueError
        valid = [i for i in ids if isinstance(i, int) and i in meeting_graphs]
        if valid:
            print(f"[RETRIEVE] Resolved target meetings: {valid}")
            return valid
    except Exception:
        pass
    
    # If the llm could not resolve, fallback to querying against all meetings
    all_ids = [m["id"] for m in meetings_db]
    print(f"[RETRIEVE] Could not resolve meetings — querying all: {all_ids}")
    return all_ids

# Run personalised pagerank on individual meetings
def rank_within_meeting(query: str, meeting_id: int) -> list[dict]:
    G = meeting_graphs.get(meeting_id)
    if not G or G.number_of_edges() == 0:
        return []

    # Extract query entities and match to nodes in this graph
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

    nodes = list(G.nodes())
    seed_nodes = {
        node for entity in entities
        for node in nodes
        if entity.lower() in node.lower() or node.lower() in entity.lower()
    }
    print(f"[RETRIEVE, meeting {meeting_id}] Seed nodes: {seed_nodes}")

    if not seed_nodes:
        print(f"[RETRIEVE, meeting {meeting_id}] No seed nodes found — skipping PageRank")
        return []

    # Weight seed nodes higher in PageRank to prioritise triples connected to them when teleport happens (0.15%)
    personalization = {n: (1.0 if n in seed_nodes else 0.0) for n in G.nodes()}
    scores = nx.pagerank(G, personalization=personalization, alpha=0.85)

    top_nodes = sorted(scores, key=scores.get, reverse=True)[:10]
    print(f"[RETRIEVE, meeting {meeting_id}] Top nodes: {top_nodes}")

    context_triples = [
        {
            "subject": u,
            "relation": data["relations"],
            "object": v,
            "meeting_id": meeting_id
        }
        for node in top_nodes
        for u, v, data in G.out_edges(node, data=True)
    ]
    return context_triples

SYSTEM_PROMPT = """You are a precise meeting-notes assistant. Answer questions strictly \
from the provided meeting data — never from general knowledge or inference.

Rules:
- Only use information present in the meeting index or notes provided.
- If the data doesn't contain enough information, say so plainly.
- Cite the meeting ids when stating a fact, e.g. "In meeting 2, ...".
- Never speculate or pad your answer.

Formatting:
- Use blank lines between sections.
- Use dashes for lists.
- No markdown (no **, ##, *)."""

def query_graph(query: str, history: list[dict] | None = None) -> str:
    history = history or []

    print(f"\n[QUERY] {query}")

    if not meetings_db:
        return "There are no meetings loaded yet."

    meeting_index = "\n".join(
        f"- Meeting {m['id']}: {m['title']}" for m in meetings_db
    )

    # Step 1: Determine which meeting(s) this query targets
    target_ids = resolve_target_meetings(query)

    # Step 2: Run PageRank on each target meeting's graph and collect triples.
    # If no seed nodes are found for a meeting, skip it — no fallback to avoid diluting context.
    context_triples = []
    for mid in target_ids:
        triples = rank_within_meeting(query, mid)
        if triples:
            context_triples.extend(triples)

    # Step 3: Collect relevant meeting notes for all targeted meetings
    relevant_notes = {m["id"]: m["summary"] for m in meetings_db if m["id"] in target_ids}

    user_prompt = f"""Available meetings:
{meeting_index}

Knowledge graph context (relevant entities and their relationships):
{json.dumps(context_triples, indent=2)}

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

# Save meeting note uploaded from endpoint to disk, extract triples and add to graph db.
# If no note is provided, reload all meetings from disk to reform graph db
def process_load_meetings(notes: Optional[str] = None):
    global meetings_db

    if notes:
        meeting_id = get_next_meeting_id()
        print(f"[LOAD] Adding meeting {meeting_id}")

        title = extract_title(notes)

        filepath = os.path.join(DATA_DIR, f"meeting_{meeting_id}.txt")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(notes)
            logging.info(f"[LOAD] Saved new meeting to {filepath}")
        except IOError as e:
            logging.error(f"Failed to save meeting file: {e}")

        triples = extract_triples(notes, meeting_id)
        if not triples:
            logging.warning(f"[LOAD] Meeting {meeting_id} produced no triples — graph queries will return no context")

        m = {"id": meeting_id, "title": title, "summary": notes, "triples": triples}
        meetings_db.append(m)
        meeting_graphs[meeting_id] = build_meeting_graph(m)

        save_cache()
        return {"message": f"Meeting {meeting_id} saved", "triples_extracted": len(triples)}

    print("[LOAD] Checking cache...")
    load_cache()
    if meetings_db:
        return {"message": f"Loaded {len(meetings_db)} meetings from cache"}

    print("[LOAD] Cache empty or missing — reloading all from disk...")
    meetings_db = []
    meeting_graphs.clear()

    for file in sorted(f for f in os.listdir(DATA_DIR) if f.endswith(".txt")):
        try:
            meeting_id = int(file.split("_")[1].split(".")[0])
        except (ValueError, IndexError):
            continue
        with open(os.path.join(DATA_DIR, file), encoding="utf-8", errors="ignore") as f:
            text = f.read()

        triples = extract_triples(text, meeting_id)

        meetings_db.append({
            "id": meeting_id,
            "title": extract_title(text),
            "summary": text,
            "triples": triples,
        })

    rebuild_graphs()
    save_cache()
    return {"message": f"Reloaded {len(meetings_db)} meetings"}

# Additional endpoint for debugging in swagger
def get_graph_data():
    return {
        "meeting_count": len(meeting_graphs),
        "meetings": [
            {
                "meeting_id": mid,
                "node_count": G.number_of_nodes(),
                "edge_count": G.number_of_edges(),
                "nodes": list(G.nodes()),
                "edges": [
                    {"from": u, "to": v, "relations": d.get("relations")}
                    for u, v, d in G.edges(data=True)
                ]
            }
            for mid, G in meeting_graphs.items()
        ]
    }