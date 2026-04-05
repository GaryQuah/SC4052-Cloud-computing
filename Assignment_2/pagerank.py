import networkx as nx
import os

# Nodes: 10000 Edges: 78323
script_dir = os.path.dirname(os.path.abspath(__file__))
file_path = os.path.join(script_dir, "web-Google_10k.txt")

G = nx.read_edgelist(file_path, create_using=nx.DiGraph(), nodetype=int)

# Sanity check
print("Number of nodes:", G.number_of_nodes())
print("Number of edges:", G.number_of_edges())

p = 0.15 

# Compute PageRank
pr = nx.pagerank(G, alpha=1 - p, tol=0.000001)

scores = list(pr.items())

# sort descending by score
scores.sort(key=lambda x: x[1], reverse=True)

for i in range(10):
    print("Page", scores[i][0], ":", round(scores[i][1], 6))

    