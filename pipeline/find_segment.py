import osmnx as ox

G = ox.load_graphml("bangalore_graph.graphml")

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