import osmnx as ox
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
GRAPH_PATH_CANDIDATES = [
    PROJECT_ROOT / "data" / "bangalore_graph.graphml",
    PROJECT_ROOT / "bangalore_graph.graphml",
]


def _first_existing(candidates):
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]

graph_path = _first_existing(GRAPH_PATH_CANDIDATES)
G = ox.load_graphml(graph_path)

point_lat = 12.9250
point_lon = 77.5938

nearest = ox.distance.nearest_edges(G, X=point_lon, Y=point_lat)
u, v, key = nearest
edge_data = G.edges[u, v, key]
osmid = edge_data.get('osmid', f"{u}_{v}")
way_id = str(osmid[0]) if isinstance(osmid, list) else str(osmid)

print(f"OSM way ID:  {way_id}")
print(f"Road name:   {edge_data.get('name', 'unnamed')}")
print(f"Road type:   {edge_data.get('highway', 'unknown')}")