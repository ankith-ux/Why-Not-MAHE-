# save as download_graph.py and run it
import osmnx as ox
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"

print("Downloading Bangalore OSMnx graph...")
G = ox.graph_from_place("Bengaluru, Karnataka, India", network_type='drive')
DATA_DIR.mkdir(parents=True, exist_ok=True)
graph_out = DATA_DIR / "bangalore_graph.graphml"
ox.save_graphml(G, graph_out)
print(f"Done. Nodes: {len(G.nodes)}, Edges: {len(G.edges)}")
print(f"Saved → {graph_out}")