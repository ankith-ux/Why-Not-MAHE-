# save as download_graph.py and run it
import osmnx as ox
print("Downloading Bangalore OSMnx graph...")
G = ox.graph_from_place("Bengaluru, Karnataka, India", network_type='drive')
ox.save_graphml(G, "bangalore_graph.graphml")
print(f"Done. Nodes: {len(G.nodes)}, Edges: {len(G.edges)}")