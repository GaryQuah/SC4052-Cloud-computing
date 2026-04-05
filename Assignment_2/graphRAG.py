import networkx as nx
import os
import matplotlib.pyplot as plt

script_dir = os.path.dirname(os.path.abspath(__file__))
triples_file_path = os.path.join(script_dir, "triples.txt")

edges = []
relations = {}

with open(triples_file_path, 'r', encoding='utf-8') as f:
    for line in f:
        parts = line.strip().split(',')
        if len(parts) == 3:
            subject = parts[0].strip()
            relation = parts[1].strip()
            obj = parts[2].strip()
            edges.append((subject, obj))
            relations[(subject, obj)] = relation

print(f"Edges: {edges}")
print(f"\nRelations: {relations}")

G = nx.DiGraph()
G.add_edges_from(edges)

query = "Marie Curie and radium"
keywords = query.lower().split()

personalization = {}

# Count keyword matches for each node
for node in G.nodes():
    count = 0
    node_lower = node.lower()
    for k in keywords:
        if k in node_lower:
            count += 1
    personalization[node] = count

# Normalize to sum to 1
total = sum(personalization.values())
for node in personalization:
    personalization[node] = personalization[node] / total

alpha = 0.85
pr_scores = nx.pagerank(G, alpha=alpha, personalization=personalization, tol=1e-6)

top_k = 5
top_nodes = sorted(pr_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

print("\nTop relevant nodes:")
for node, score in top_nodes:
    print(f"{node} : {score:.5f}")

result = []

# Add the relations with the top nodes
for node, _ in top_nodes:
    for obj in G.successors(node):
        if (node, obj) in relations:
            relation = relations[(node, obj)]
            result.append((node, relation, obj))

for subject, relation, object in result:
    print(f"{subject},{relation},{object}")

# Visualization of nodes
plt.figure(figsize=(12, 10))
pos = nx.spring_layout(G, seed=42)

node_colors = ['orange' if node in [n for n, _ in top_nodes] else 'lightblue' for node in G.nodes()]

nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=700)
nx.draw_networkx_edges(G, pos, arrowsize=30, edge_color='gray')

# Draw labels for nodes
nx.draw_networkx_labels(G, pos, font_size=10, font_color='black')

edge_labels = {}
for s, o in G.edges():
    if (s, o) in relations:
        edge_labels[(s, o)] = relations[(s, o)]

nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_color='red', font_size=9)

plt.title("Knowledge Graph with Top Nodes and Relations")
plt.show()
