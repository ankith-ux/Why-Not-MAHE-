# NeuralPath — Cellular Network-Aware Routing

> **MIT-MAHE Hackathon · Harman Automotive Track · Team Why Not?**
> Signal-intelligent navigation for connected vehicles in Bengaluru.

NeuralPath scores every road segment in Bangalore by its expected cellular signal quality — accounting for building obstructions, terrain shadowing, carrier-specific tower density, weather attenuation, and time-of-day congestion — then uses those scores to recommend routes that minimise dead zone exposure without ignoring travel time.

---

## What It Does

Standard routing engines (OSRM, Google Maps) optimise for time and distance. They have no awareness of where a vehicle will lose connectivity. NeuralPath adds a third axis: **signal reliability**.

Given an origin, destination, carrier, and persona, it returns:

- Up to 3 ranked candidate routes with per-segment signal scores
- Dead zone locations with durations and pre-fetch trigger coordinates
- A connectivity budget (% strong / weak / dead by distance and time)
- A carrier-specific heatmap of Bangalore at H3 resolution 8
- Per-segment explanations (terrain shadow, building obstruction, congestion, weather)
- Fleet-level route diversification to minimise collective dead-zone risk

---

## Repository Structure

```
neuralpath-backend/          # FastAPI backend (online inference)
│
├── main.py                  # FastAPI app, all API endpoints
├── router.py                # OSRM integration, segment matching, dead zone detection
├── scorer.py                # Weather multipliers, congestion/venue penalties
├── cache.py                 # Redis wrapper (routes, weather, telemetry)
├── fleet.py                 # Fleet diversification engine
├── explainer.py             # Rule-based segment explanation generator
├── config.py                # All constants — zones, personas, thresholds, bands
└── docker-compose.yml       # OSRM + Redis containers

data-pipeline/               # Offline preprocessing (run once before demo)
│
├── filter_towers.py         # OpenCelliD CSV → 4 carrier Parquet files
├── download_graph.py        # OSMnx graph download → bangalore_graph.graphml
├── download_building.py     # Overpass API → bangalore_buildings.geojson
├── compute_features.py      # 13-dim feature vector per road segment → Parquet
├── gnn_pipeline.py          # GraphSAGE training + GeoJSON export
├── find_segment.py          # Nearest OSM edge lookup utility
│
└── cv/
    ├── cv_demo.py           # Mapillary + SegFormer SVF comparison pipeline
    └── cv_visualise.py      # Matplotlib visualisation of segmentation results
```

---

## System Architecture

```
OFFLINE (run before demo)
─────────────────────────────────────────────────────────────
OpenCelliD (MCC 404/405) ──┐
OOKLA Speedtest Q4 2024 ───┤
CellMapper RSRP points ────┼──► compute_features.py ──► features_real.parquet
SRTM DEM (30 m elevation) ─┤         ↓
OSM buildings (Overpass) ──┤    gnn_pipeline.py
OSMnx road graph ──────────┘    (GraphSAGE 2-layer)
                                     ↓
                           bangalore_scored_segments.geojson

ONLINE (at request time)
─────────────────────────────────────────────────────────────
POST /api/route/score
  → OpenMeteo weather (once per session)
  → Redis cache check
  → OSRM Docker (3 candidate routes)
  → Segment score lookup (O(1) in-memory dict)
  → Weather × congestion × venue × persona multipliers
  → Dead zone detection + pre-fetch trigger placement
  → Alpha-blended route ranking
  → Redis cache write (10 min TTL)
  → Response

CV MODULE (offline, produces demo artifact)
─────────────────────────────────────────────────────────────
Mapillary API (3 images, 26th Main Rd Jayanagar)
  → SegFormer-B2 semantic segmentation (ADE20K)
  → Sky pixel fraction = camera SVF
  → Hata obstruction correction
  → Compare vs geometric SVF (OSM buildings only)
  → cv_demo_segment.json  (error: 7 dB → 2 dB)
```

---

## Data Sources

| Source | What It Provides | License |
|--------|-----------------|---------|
| [OpenCelliD](https://opencellid.org/) | Cell tower lat/lon, radio type, range — MCC 404 & 405 | CC BY-SA 4.0 |
| [OOKLA Speedtest Open Data](https://github.com/teamookla/ookla-open-data) | H3 tile download speeds Q4 2024 | Speedtest Open Data License |
| [CellMapper](https://www.cellmapper.net/) | Drive-test RSRP measurements | Community |
| [NASA SRTM](https://earthdata.nasa.gov/) | 30 m resolution elevation (SRTMGL1) | Public Domain |
| [OpenStreetMap](https://www.openstreetmap.org/) | Road graph + building polygons via Overpass | ODbL |
| [Mapillary](https://www.mapillary.com/) | Street-level images for CV module | CC BY-SA 4.0 |
| [OpenMeteo](https://open-meteo.com/) | Real-time weather (no API key required) | CC BY 4.0 |

---

## Offline Pipeline — Run Order

> Run these once. The outputs are committed or shared as data artifacts.

```bash
# 1. Download road graph (~5 min)
python3 data-pipeline/download_graph.py

# 2. Download building polygons (~5–8 min)
python3 data-pipeline/download_building.py

# 3. Filter tower CSV dumps from OpenCelliD archive
#    Place 404.csv and 405.csv in the working directory first
python3 data-pipeline/filter_towers.py

# 4. Compute 13-dim feature vectors for all road segments
python3 data-pipeline/compute_features.py

# 5. Train GNN and export scored GeoJSON
python3 data-pipeline/gnn_pipeline.py
#    Outputs: best_model.pt, scaler.pkl, scored_segments.geojson

# 6. (Optional) Run CV demo pipeline
python3 data-pipeline/cv/cv_demo.py
#    Outputs: cv_demo_segment.json, mapillary_*.jpg
```

---

## Backend — Setup & Run

### Prerequisites

- Python 3.10+
- Docker + Docker Compose
- The scored GeoJSON at `data/output/bangalore_scored_segments.geojson`

### Install

```bash
cd neuralpath-backend
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn httpx redis h3
```

### Start infrastructure

```bash
docker-compose up -d
# Starts OSRM on :5000 and Redis on :6379
# OSRM takes ~90 seconds to load the Bangalore graph
```

### Start API server

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Run tests

```bash
python3 test_api.py
```

---

## API Reference

### `POST /api/route/score`

Score and rank candidate routes between two coordinates.

**Request body:**
```json
{
  "origin":      { "lat": 12.9716, "lng": 77.5946 },
  "destination": { "lat": 12.9352, "lng": 77.6245 },
  "alpha":       0.5,
  "carrier":     "airtel",
  "persona":     "emergency",
  "timestamp":   "2026-04-18T18:30:00Z"
}
```

**`alpha`** — trade-off weight: `0.0` = pure connectivity, `1.0` = pure ETA

**`persona`** options: `emergency` · `ride_hailing` · `it_shuttle` · `fleet_ota`

**Response includes:** ranked routes with `connectivity_score`, `worst_window_score`, `dead_zones[]`, `connectivity_budget`, `prefetch_burst_point`, `destination_dead_zone`, `weather_conditions`

---

### `POST /api/route/rerank`

Re-rank a cached route set with a new alpha. Completes in < 100 ms.

```json
{ "route_cache_key": "...", "alpha": 0.8 }
```

---

### `GET /api/heat/tiles`

Return H3 hex tile scores for a bounding box and carrier.

```
GET /api/heat/tiles?west=77.5&south=12.9&east=77.7&north=13.0&carrier=composite
```

---

### `GET /api/segment/{osm_way_id}/explain`

Return a natural language explanation for a segment's score: terrain shadow, building obstruction, congestion, or weather.

---

### `POST /api/fleet/routes`

Score multiple origin-destination pairs and return both individually optimal and fleet-diversified route sets with a collective connectivity risk score.

---

### `POST /api/telemetry/report`

Submit a live vehicle signal report to override a segment's score.

```json
{ "osm_way_id": "123456789", "signal_score": 10.5, "ttl_seconds": 3600 }
```

---

## Key Configuration (`config.py`)

| Constant | Value | Meaning |
|----------|-------|---------|
| `DEAD_ZONE_THRESHOLD` | 25 | Score below this = dead zone |
| `STRONG_THRESHOLD` | 60 | Score above this = strong signal |
| `BBOX` | 12.834–13.139 N, 77.469–77.748 E | Bangalore bounding box |
| `CONGESTION_ZONES` | Silk Board, Whitefield, Electronic City | With radius and peak hour windows |
| `PERSONA_CONFIG` | Emergency α=0.10, Fleet OTA α=0.40 | Alpha presets and hard constraints |

---

## Persona Behaviour

| Persona | Alpha | Hard Constraint |
|---------|-------|-----------------|
| `emergency` | 0.10 | Forces zero-dead-zone route if within 30% longer ETA |
| `fleet_ota` | 0.40 | Evaluates sustained 2 km signal floor, not just 500 m window |
| `it_shuttle` | 0.50 | Alpha blend only, no hard constraint |
| `ride_hailing` | 0.70 | Alpha blend only, ETA-weighted |

---

## Score Colour Scale (Frontend Reference)

| Score | Colour | Meaning |
|-------|--------|---------|
| 80–100 | `#22c55e` green | Strong — multiple towers, clear LoS |
| 60–80 | `#86efac` light green | Good |
| 40–60 | `#facc15` yellow | Moderate |
| 20–40 | `#f97316` orange | Weak |
| 0–20 | `#ef4444` red | Dead zone |

---

## Known Limitations

| Issue | Status |
|-------|--------|
| GeoJSON currently has 3 synthetic segments | Full Bangalore dataset needed from pipeline run |
| Telemetry poisoning via single faulty report | Requires consensus model — not yet implemented |
| OSRM fallback routes are synthetic if Docker is down | Logged; no automatic fallback routing |
| WebSocket `/ws/fleet/stream` not load tested | Manual test before demo recommended |

---

## Assumptions

1. Vehicles have GPS with accurate real-time coordinates
2. Cellular modems support all four Indian carrier bands
3. OSM road data is sufficiently complete for Bangalore routing
4. Building heights default to 10 m when the OSM tag is absent
5. Cell tower heights default to 30 m when not in OpenCelliD
6. OOKLA Q4 2024 data represents current network conditions
7. SRTM 30 m elevation resolution is adequate for terrain LoS
8. OSRM Docker is running and reachable at `localhost:5000`
9. Redis available; system degrades gracefully without it
10. OpenMeteo API is reachable at request time
11. Congestion zone boundaries are fixed for the demo period

---

## License

Data sources are subject to their respective licenses listed above. Code in this repository is released under the MIT License.
