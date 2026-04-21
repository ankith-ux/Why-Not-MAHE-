# download_buildings.py
import requests
import json
import geopandas as gpd
from shapely.geometry import shape

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Bangalore bounding box
QUERY = """
[out:json][timeout:300];
(
  way["building"](12.834,77.469,13.139,77.748);
  relation["building"](12.834,77.469,13.139,77.748);
);
out body;
>;
out skel qt;
"""

print("Querying OSM buildings (this takes 3-8 minutes)...")
resp = requests.post(OVERPASS_URL, data={'data': QUERY}, timeout=400)
try:
    data = resp.json()
except requests.exceptions.JSONDecodeError as e:
    print(f"Failed to parse JSON. Status Code: {resp.status_code}")
    print(f"Response: {resp.text[:500]}")
    raise e

print(f"Got {len(data['elements'])} elements, parsing...")

# Build node coordinate lookup
nodes = {}
for el in data['elements']:
    if el['type'] == 'node':
        nodes[el['id']] = (el['lon'], el['lat'])

# Build building polygons
buildings = []
for el in data['elements']:
    if el['type'] == 'way' and 'building' in el.get('tags', {}):
        coords = [nodes[nid] for nid in el.get('nodes', []) if nid in nodes]
        if len(coords) >= 4:
            try:
                raw_height = el['tags'].get('height')
                if raw_height:
                    height = float("".join(c for c in str(raw_height) if c.isdigit() or c == '.'))
                else:
                    levels = el['tags'].get('building:levels', 3)
                    height = float("".join(c for c in str(levels) if c.isdigit() or c == '.')) * 3.0
            except ValueError:
                height = 10.0

            buildings.append({
                'geometry': {'type': 'Polygon', 'coordinates': [coords]},
                'height':   height,
                'osm_id':   el['id']
            })

print(f"Parsed {len(buildings)} building polygons")

# Save as GeoJSON
with open("bangalore_buildings.geojson", "w") as f:
    json.dump({
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": b['geometry'],
                "properties": {"height": b['height'], "osm_id": b['osm_id']}
            }
            for b in buildings
        ]
    }, f)

print("Saved → bangalore_buildings.geojson")