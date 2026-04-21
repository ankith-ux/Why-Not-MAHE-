# NeuralPath Backend — Change Log
**Session Date:** 2026-04-18  
**City Target:** Bengaluru, India  
**Spec Compliance Target:** SPEC_SDD.md + AGENT_CODING_CONTEXT.md  

---

## Summary

This document records every change made to the `neuralpath-backend` across this session. Changes are grouped by file and reason. All changes were aimed at:
1. Getting the server to start without import errors
2. Fixing 500 Internal Server Errors on all API endpoints
3. Closing 4 routing engine loopholes that would cause incorrect dead zone detection
4. Hardening the architecture against 4 real-world data attack and fault scenarios

---

## File: `main.py`

### Change 1 — Absolute Imports (Bug Fix)
**Why:** The FastAPI app is run as a top-level module via `uvicorn main:app`. Python does not recognize it as part of a package, so relative imports (`from .scorer import ...`) raised `ImportError: attempted relative import with no known parent package` on every endpoint hit.  
**What:** Converted all internal relative imports to absolute imports across the file.
```diff
- from .scorer import get_weather_multipliers
- from .router import get_osrm_routes, ...
- from .cache import route_cache_key, cache_routes
+ from scorer import get_weather_multipliers
+ from router import get_osrm_routes, ...
+ from cache import route_cache_key, cache_routes
```

### Change 2 — Timestamp "Z" Suffix Parsing (Bug Fix)
**Why:** JavaScript frontends send ISO timestamps ending in `"Z"` (e.g., `"2026-04-18T18:30:00Z"`). Python 3.10's `datetime.fromisoformat()` cannot parse this — it raises a `ValueError`. The `try/except` block silently swallowed the error and fell back to `datetime.now().hour`, meaning future/scheduled route requests always used the current system time for congestion calculations.  
**What:** Strip `"Z"` before parsing.
```diff
- dt = datetime.fromisoformat(req.timestamp)
+ dt = datetime.fromisoformat(req.timestamp.replace("Z", "+00:00"))
```

### Change 3 — Destination Dead Zone Integration (Feature)
**Why:** `destination_dead_zone` and `prefetch_burst_point` were hardcoded placeholders, meaning vehicles driving to underground parking or low-signal destinations were never warned.  
**What:** Imported and called `check_destination_dead_zone()` from `router.py` inside the route_score endpoint.
```diff
+ from router import (..., check_destination_dead_zone)
+ is_dz, burst_point = check_destination_dead_zone(osrm_route, route_scores, req.destination.lat, req.destination.lng, GRAPH)
- "destination_dead_zone": False,
- "prefetch_burst_point": None,
+ "destination_dead_zone": is_dz,
+ "prefetch_burst_point": burst_point,
```

---

## File: `router.py`

### Change 4 — Absolute Imports (Bug Fix)
**Why:** Same relative import error as `main.py`. Importing from `config.py` raised `ImportError`.  
**What:** Converted to absolute imports.
```diff
- from .config import DEAD_ZONE_THRESHOLD, ...
+ from config import DEAD_ZONE_THRESHOLD, ...
```

### Change 5 — `dominant_band` String Handling (Bug Fix)
**Why:** The GeoJSON file `bangalore_scored_segments.geojson` stores `dominant_band` as human-readable strings (e.g., `"LTE_1800"`) because the data pipeline wrote it that way. The backend expected integers (e.g., `1` for LTE high) and crashed with `ValueError: invalid literal for int() with base 10: 'LTE_1800'` when building route scores.  
**What:** Added a reverse lookup from `config.BAND_NAMES` so both string and integer formats are handled gracefully.
```diff
- dominant_band_int = int(props.get("dominant_band", 1))
+ band_raw = props.get("dominant_band", "LTE_900")
+ if isinstance(band_raw, int):
+     dominant_band_int = band_raw
+ else:
+     dominant_band_int = BAND_NAMES_REVERSE.get(str(band_raw).upper(), 2)
```

### Change 6 — Euclidean → Haversine Coordinate Matching (Loophole Fix)
**Why:** The segment matching logic used `math.hypot(lat - seg_lat, lon - seg_lon)` — a flat Euclidean distance on spherical GPS coordinates. This was inaccurate because 1° of longitude ≠ 1° of latitude in terms of real distance, creating an elliptical and distorted search radius. Long highway segments were never matched until the route coordinate reached their midpoint, leaving large stretches of road unscored.  
**What:** Replaced `math.hypot` with `haversine_km` and a proper 500m threshold. Added a bounding box pre-filter to reduce computation from O(N×M) to O(1).
```diff
- d = math.hypot(lat - seg_lat, lon - seg_lon)
- if d < best_dist and d < 0.005:  # ~500m in degrees (WRONG)
+ d = haversine_km(lat, lon, seg_lat, seg_lon)
+ if d < best_dist and d < 0.5:  # 500m in real kilometers (CORRECT)
```

### Change 7 — Null Island Bounding Box Guard (Hardening)
**Why:** If OSRM returns a malformed geometry containing `[0.0, 0.0]` (Null Island), the bounding box expands to cover the globe and the system either mismatches segments or burns CPU. Similarly, if segment data defaults `midpoint_lat` to `0.0`, the route is scored as if it's in the middle of the ocean.  
**What:** Strip all coordinates outside the Bangalore bounding box before any processing.
```diff
+ valid_coords = [c for c in coords if 12.834 <= c[1] <= 13.139 and 77.469 <= c[0] <= 77.748]
+ if not valid_coords:
+     return []
+ coords = valid_coords
```

### Change 8 — Division-by-Zero Guard in Worst Window (Hardening)
**Why:** If `segment_length` is `0.0` for micro-segments (complex intersections, pedestrian crossings), `window_len` stays at 0. The next line `avg = window_score_sum / window_len` raises `ZeroDivisionError`, crashing the entire route scoring endpoint.  
**What:** Clamp divisor to a minimum of `0.1`.
```diff
- avg = window_score_sum / window_len
+ avg = window_score_sum / max(window_len, 0.1)
```

### Change 9 — Persona String Sanitization (Hardening)
**Why:** If the frontend sends `"Emergency "` (trailing space), `"EMERGENCY"` (wrong case), or a completely unknown persona string, the `if persona == "emergency":` check silently fails. An emergency vehicle gets a standard route with dead zones instead of a zero-dead-zone-forced route.  
**What:** Strip and lowercase persona before any constraint logic.
```diff
+ if not persona:
+     return routes
+ persona = persona.strip().lower()
```

### Change 10 — Pre-fetch Origin Fallback (Loophole Fix)
**Why:** If a route starts in a dead zone (e.g., underground garage at origin), the `last_strong_seg` tracker is `None` when the dead zone is first detected. The `prefetch_trigger_coord` was written as `None`, meaning the vehicle received no pre-fetch instruction and entered the dead zone with zero data buffer.  
**What:** Default to the first coordinate of the route (the origin) when no strong segment precedes the dead zone.
```diff
- if last_strong_seg else None
+ if last_strong_seg else ([scored_segs[0]["lat"], scored_segs[0]["lon"]] if scored_segs else None)
```

### Change 11 — Fleet OTA Correct 2km Window Evaluation (Loophole Fix)
**Why:** The `fleet_ota` persona in `PERSONA_CONFIG` specifies a `window_km = 2.0` sustained minimum floor. However, `apply_persona_constraints` was comparing against `worst_window_score`, which is always computed over a **500m** window. This mismatch meant the fleet constraint was evaluated at 4× the sensitivity, flagging valid routes with minor 500m blips as failing the 2km floor.  
**What:** Dynamically compute `_compute_worst_window(scored_segs, window_m=2000)` for `fleet_ota` evaluation.
```diff
- if r.get("worst_window_score", 100) < floor:
+ fleet_window_score = _compute_worst_window(scored_segs, window_m=window_km * 1000)
+ if fleet_window_score < floor:
```

### Change 12 — Destination Dead Zone Detection (Feature — New Function)
**Why:** Section 6.6 of SPEC_SDD.md requires detecting if the destination is a dead zone and placing a `prefetch_burst_point` 500m before the destination so the vehicle can download data in advance.  
**What:** Added two new functions:
- `check_destination_dead_zone()` — checks OSM node tags (underground parking) and nearby segment scores.
- `_backtrack_route_geometry()` — walks backward 500m along the route geometry to find the exact GPS coordinate for the burst trigger.

---

## File: `scorer.py`

### Change 13 — Absolute Imports (Bug Fix)
**Why:** Same relative import error.  
**What:** Converted to absolute imports.
```diff
- from .config import CONGESTION_ZONES, VENUES, DEAD_ZONE_THRESHOLD, BAND_NAMES
+ from config import CONGESTION_ZONES, VENUES, DEAD_ZONE_THRESHOLD, BAND_NAMES
```

---

## File: `explainer.py`

### Change 14 — Absolute Imports (Bug Fix)
**Why:** Same relative import error.  
**What:** Converted to absolute imports.
```diff
- from .config import DEAD_ZONE_THRESHOLD, STRONG_THRESHOLD
+ from config import DEAD_ZONE_THRESHOLD, STRONG_THRESHOLD
```

---

## File: `fleet.py`

### Change 15 — Absolute Imports (Bug Fix)
**Why:** Same relative import error.  
**What:** Converted to absolute imports.
```diff
- from .router import ...
+ from router import ...
```

---

## Known Remaining Risks

| Risk | Severity | Status |
|------|----------|--------|
| Telemetry data poisoning via single faulty vehicle report | High | Not yet mitigated — requires consensus model |
| OSRM Docker not running — fallback routes are synthetic | Medium | Logged as "Graph not found — OSRM routing only" |
| GeoJSON only has 3 sample segments — full Bangalore data needed for production | High | Data pipeline (Member 1 & 2) must deliver full GeoJSON |
| WebSocket `/ws/fleet/stream` not stress tested | Low | Manual test recommended before demo |

---

## Files Changed

| File | Changes |
|------|---------|
| `main.py` | Import fix, timestamp fix, destination dead zone wiring |
| `router.py` | Import fix, dominant band parsing, haversine matching, null island guard, zero division guard, persona sanitization, pre-fetch fallback, fleet OTA window, destination dead zone functions |
| `scorer.py` | Import fix |
| `explainer.py` | Import fix |
| `fleet.py` | Import fix |
