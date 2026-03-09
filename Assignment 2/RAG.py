import networkx as nx
import os
import random
from collections import defaultdict
import matplotlib.pyplot as plt


# Triple class representing <subject, relation, object>
class Triple:
    def __init__(self, subject, relation, obj):
        self.subject = subject.strip()
        self.relation = relation.strip()
        self.obj = obj.strip()


# Load triples from file
def load_triples(file_path):
    triples = []

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split(",")
            triple = Triple(parts[0], parts[1], parts[2])
            triples.append(triple)

    return triples


# Create graph from triples
def create_graph(triples):
    graph = nx.DiGraph()

    for triple in triples:
        graph.add_edge(triple.subject, triple.obj, relation=triple.relation)

    return graph


# Personalized PageRank
def run_pagerank(graph, query_nodes, alpha=0.85):

    weights = {node: 0 for node in graph.nodes()}

    for node in query_nodes:
        if node in graph:
            weights[node] = 1 / len(query_nodes)

    scores = nx.pagerank(graph, alpha=alpha, personalization=weights)

    return scores


def get_top_nodes(scores, k):

    def get_score(item):
        #returns page rank score for sorting as key
        return item[1]

    # Convert dictionary to list of (node, score)
    items = list(scores.items())

    # Sort items by score (highest first)
    items.sort(key=get_score, reverse=True)

    return items[:k]


# Random Surfer
def random_surfer(graph, query_nodes, steps=10000, alpha=0.85):

    visits = {}

    current = random.choice(query_nodes)

    for i in range(steps):
        if current in visits:
            visits[current] += 1
        else:
            visits[current] = 1

        neighbors = list(graph.successors(current))

        # Follow link
        if neighbors and random.random() < alpha:
            current = random.choice(neighbors)

        # Teleport to query node
        else:
            current = random.choice(query_nodes)

    return visits


# Load triples from text file
script_dir = os.path.dirname(os.path.abspath(__file__))
file_path = os.path.join(script_dir, "triples.txt")

triples = load_triples(file_path)

graph = create_graph(triples)

query_nodes = ["Marie Curie", "Nobel Prize"]

# Run PageRank
scores = run_pagerank(graph, query_nodes)

top_nodes = get_top_nodes(scores, 10)

print("\nTop relevant nodes (PageRank):")
for node, score in top_nodes:
    print(f"{node}: {score:.5f}")


# Run random surfer simulation
visits = random_surfer(graph, query_nodes)

print("\nRandom Surfer Visit Counts:")
for node, count in sorted(visits.items(), key=lambda x: x[1], reverse=True):
    print(node, count)


# Plot
plt.figure(figsize=(12, 8))

pos = nx.spring_layout(graph, seed=42)

nx.draw_networkx_nodes(graph, pos,  node_color="skyblue")
nx.draw_networkx_edges(graph, pos, arrowstyle='-|>', arrowsize=20, edge_color="gray")
nx.draw_networkx_labels(graph, pos)

edge_labels = nx.get_edge_attributes(graph, "relation")
nx.draw_networkx_edge_labels(graph, pos, edge_labels=edge_labels, font_color="red")

plt.title("Knowledge Graph with PageRank Importance")
plt.axis("off")

plt.tight_layout()

plt.savefig(os.path.join(script_dir, "graph.png"), dpi=300)

plt.show()