"""
backend/router.py
Routing engine — OSRM integration, route scoring, dead zone extraction.
"""

import math
from typing import Optional

import httpx

from config import (
    DEAD_ZONE_THRESHOLD, STRONG_THRESHOLD,
    PREFETCH_TRIGGER_MIN_SCORE, PERSONA_CONFIG,
)
from scorer import score_segment_online, haversine_km


# ──────────────────────────────────────────────────────────────────────────────
# OSRM ROUTE FETCHING
# ──────────────────────────────────────────────────────────────────────────────

async def get_osrm_routes(
    origin_lat: float, origin_lon: float,
    dest_lat: float, dest_lon: float,
    n: int = 3,
) -> list:
    """
    Call local OSRM Docker for candidate routes.
    Returns list of OSRM route objects with geometry and annotations.
    """
    url = (
        f"http://localhost:5000/route/v1/driving/"
        f"{origin_lon},{origin_lat};{dest_lon},{dest_lat}"
        f"?alternatives={n - 1}&geometries=geojson"
        f"&annotations=nodes&overview=full"
    )
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=10.0)
        data = resp.json()
        return data.get("routes", [])
    except Exception:
        # Fallback: generate synthetic route
        return _generate_fallback_routes(origin_lat, origin_lon, dest_lat, dest_lon, n)


def _generate_fallback_routes(
    origin_lat: float, origin_lon: float,
    dest_lat: float, dest_lon: float,
    n: int = 3,
) -> list:
    """Generate synthetic routes when OSRM is unavailable."""
    import numpy as np

    routes = []
    for i in range(n):
        # Generate waypoints along a slightly different path
        n_points = 20
        offset = i * 0.005  # Slight offset for each alternative

        lats = np.linspace(origin_lat, dest_lat, n_points)
        lons = np.linspace(origin_lon, dest_lon, n_points)

        # Add some curvature
        mid = n_points // 2
        lats[mid] += offset
        lons[mid] += offset * 0.5

        coordinates = [[float(lon), float(lat)] for lon, lat in zip(lons, lats)]

        dist = haversine_km(origin_lat, origin_lon, dest_lat, dest_lon) * 1000
        duration = dist / 10  # ~36 km/h average

        routes.append({
            "geometry": {
                "type": "LineString",
                "coordinates": coordinates,
            },
            "distance": dist * (1 + i * 0.15),
            "duration": duration * (1 + i * 0.1),
            "legs": [{
                "annotation": {
                    "nodes": list(range(n_points))
                }
            }],
        })

    return routes


# ──────────────────────────────────────────────────────────────────────────────
# ROUTE SCORING
# ──────────────────────────────────────────────────────────────────────────────

def map_route_to_segments(
    route: dict,
    segment_dict: dict,
    carrier: str = "composite",
) -> list:
    """
    Map an OSRM route geometry to scored segments.
    Uses nearest-segment matching based on great-circle distance.
    Optimized to avoid O(N*M) by using a bounding box pre-filter.
    """
    coords = route.get("geometry", {}).get("coordinates", [])
    if not coords:
        return []

    # Defensive Patch: Reject Null Island / out-of-bounds coordinates
    valid_coords = [c for c in coords if 12.834 <= c[1] <= 13.139 and 77.469 <= c[0] <= 77.748]
    if not valid_coords:
        return []
    coords = valid_coords

    scored_segs = []
    seen_ways = set()
    
    # Pre-filter segment_dict by bounding box of the route to avoid O(N*M)
    lats = [c[1] for c in coords]
    lons = [c[0] for c in coords]
    min_lat, max_lat = min(lats) - 0.01, max(lats) + 0.01
    min_lon, max_lon = min(lons) - 0.01, max(lons) + 0.01
    
    candidate_segments = {
        wid: seg for wid, seg in segment_dict.items()
        if min_lat <= seg.get("midpoint_lat", 0) <= max_lat and min_lon <= seg.get("midpoint_lon", 0) <= max_lon
    }

    for coord in coords:
        lon, lat = coord[0], coord[1]

        best_way_id = None
        best_dist = float("inf")

        for way_id, seg in candidate_segments.items():
            seg_lat = seg.get("midpoint_lat", seg.get("segment_lat", 0))
            seg_lon = seg.get("midpoint_lon", seg.get("segment_lon", 0))

            # Proper great-circle distance
            d = haversine_km(lat, lon, seg_lat, seg_lon)
            if d < best_dist and d < 0.5:  # 500m threshold
                best_dist = d
                best_way_id = way_id

        if best_way_id and best_way_id not in seen_ways:
            seen_ways.add(best_way_id)
            scored_segs.append(best_way_id)

    return scored_segs



def score_route(
    segment_ids: list,
    segment_dict: dict,
    carrier: str,
    weather_multipliers: dict,
    active_conditions: Optional[list[dict]] = None,
) -> dict:
    """
    Compute all route-level metrics from scored segments.
    Returns connectivity score, worst window, dead zones, budget.
    """
    scored_segs = []
    condition_hits = {}
    segment_duration_total = 0.0
    traffic_delay_seconds = 0.0

    for way_id in segment_ids:
        seg = segment_dict.get(way_id, {})

        # Get base score for the requested carrier
        if carrier == "composite":
            base_score = float(seg.get("composite_score", 50))
        else:
            base_score = float(seg.get(f"{carrier}_score", seg.get("composite_score", 50)))

        # Apply online scoring
        raw_band = seg.get("dominant_band", 2)
        try:
            dominant_band = int(raw_band)
        except ValueError:
            from config import BAND_NAMES
            rev_bands = {v: k for k, v in BAND_NAMES.items()}
            dominant_band = rev_bands.get(str(raw_band).upper(), 2)
        seg_lat = float(seg.get("midpoint_lat", 12.97))
        seg_lon = float(seg.get("midpoint_lon", 77.59))
        seg_length = float(seg.get("segment_length", 100))
        seg_duration = float(
            seg.get("traversal_time_seconds", seg.get("traversal_time_secs", 10))
        )

        score, matched_conditions, connectivity_penalty, eta_penalty = score_segment_online(
            base_score, seg_lat, seg_lon,
            dominant_band, weather_multipliers, active_conditions=active_conditions,
            way_id=way_id,
        )

        for condition in matched_conditions:
            _record_condition_hit(condition_hits, condition, seg_length, seg_duration)

        segment_duration_total += seg_duration
        traffic_delay_seconds += seg_duration * eta_penalty

        scored_segs.append({
            "way_id": way_id,
            "score": score,
            "length": seg_length,
            "duration": seg_duration,
            "lat": seg_lat,
            "lon": seg_lon,
            "dominant_band": dominant_band,
            "connectivity_penalty": connectivity_penalty,
            "traffic_eta_penalty": eta_penalty,
            "active_condition_ids": [condition["id"] for condition in matched_conditions],
        })

    if not scored_segs:
        return _empty_route_score()

    # ── Connectivity score (length-weighted average) ──
    total_len = sum(s["length"] for s in scored_segs)
    connectivity_score = sum(s["score"] * s["length"] for s in scored_segs) / max(total_len, 1)

    # ── Worst window (500m sliding) ──
    worst_window_score = _compute_worst_window(scored_segs, window_m=500)

    # ── Dead zones ──
    dead_zones = _extract_dead_zones(scored_segs)

    # ── Connectivity budget ──
    strong_len = sum(s["length"] for s in scored_segs if s["score"] >= STRONG_THRESHOLD)
    dead_len   = sum(s["length"] for s in scored_segs if s["score"] < DEAD_ZONE_THRESHOLD)
    weak_len   = total_len - strong_len - dead_len

    budget = {
        "strong_pct": round(100 * strong_len / max(total_len, 1), 1),
        "weak_pct":   round(100 * weak_len / max(total_len, 1), 1),
        "dead_pct":   round(100 * dead_len / max(total_len, 1), 1),
        "strong_seconds": round(
            sum(s["duration"] for s in scored_segs if s["score"] >= STRONG_THRESHOLD), 1
        ),
        "weak_seconds": round(
            sum(s["duration"] for s in scored_segs
                if DEAD_ZONE_THRESHOLD <= s["score"] < STRONG_THRESHOLD), 1
        ),
        "dead_seconds": round(
            sum(s["duration"] for s in scored_segs if s["score"] < DEAD_ZONE_THRESHOLD), 1
        ),
    }

    signal_profile = _build_signal_profile(scored_segs, total_len)

    # ── Dominant band for route & Handoffs ──
    band_counts = {}
    handoff_count = 0
    prev_band = None
    
    for s in scored_segs:
        b = s["dominant_band"]
        band_counts[b] = band_counts.get(b, 0) + s["length"]
        if prev_band is not None and b != prev_band:
            handoff_count += 1
        prev_band = b
        
    route_dominant_band = max(band_counts, key=band_counts.get) if band_counts else 2

    serialized_conditions = _serialize_condition_hits(condition_hits)

    return {
        "connectivity_score": round(connectivity_score, 2),
        "worst_window_score": round(worst_window_score, 2),
        "dead_zones": dead_zones,
        "dead_zone_count": len(dead_zones),
        "connectivity_budget": budget,
        "dominant_band": route_dominant_band,
        "handoff_count": handoff_count,
        "active_conditions": serialized_conditions,
        "event_warnings": [
            f"{condition['reason']} near {condition['label']}"
            for condition in serialized_conditions
            if condition.get("type") == "venue_event"
        ],
        "signal_profile": signal_profile,
        "traffic_delay_seconds": round(traffic_delay_seconds, 1),
        "traffic_delay_ratio": round(traffic_delay_seconds / max(segment_duration_total, 1.0), 4),
        "scored_segments": scored_segs,
    }


def _empty_route_score() -> dict:
    return {
        "connectivity_score": 50.0,
        "worst_window_score": 50.0,
        "dead_zones": [],
        "dead_zone_count": 0,
        "connectivity_budget": {
            "strong_pct": 0, "weak_pct": 100, "dead_pct": 0,
            "strong_seconds": 0, "weak_seconds": 0, "dead_seconds": 0,
        },
        "dominant_band": 2,
        "handoff_count": 0,
        "active_conditions": [],
        "event_warnings": [],
        "signal_profile": [],
        "traffic_delay_seconds": 0.0,
        "traffic_delay_ratio": 0.0,
        "scored_segments": [],
    }


def _record_condition_hit(condition_hits: dict, condition: dict,
                          segment_length: float, segment_duration: float):
    record = condition_hits.setdefault(condition["id"], {
        "id": condition["id"],
        "label": condition.get("label"),
        "type": condition.get("type"),
        "reason": condition.get("reason"),
        "eta_penalty": float(condition.get("eta_penalty", 0.0)),
        "connectivity_penalty": float(condition.get("connectivity_penalty", 0.0)),
        "active_from": condition.get("active_from"),
        "active_until": condition.get("active_until"),
        "severity": float(condition.get("severity", 1.0)),
        "event_name": condition.get("event_name"),
        "impacted_length_meters": 0.0,
        "impacted_duration_seconds": 0.0,
    })
    record["impacted_length_meters"] += segment_length
    record["impacted_duration_seconds"] += segment_duration
    record["eta_penalty"] = max(record["eta_penalty"], float(condition.get("eta_penalty", 0.0)))
    record["connectivity_penalty"] = max(
        record["connectivity_penalty"],
        float(condition.get("connectivity_penalty", 0.0)),
    )
    record["severity"] = max(record["severity"], float(condition.get("severity", 1.0)))


def _serialize_condition_hits(condition_hits: dict) -> list[dict]:
    conditions = []

    for condition in condition_hits.values():
        conditions.append({
            **condition,
            "impacted_length_meters": round(condition["impacted_length_meters"], 1),
            "impacted_duration_seconds": round(condition["impacted_duration_seconds"], 1),
            "eta_penalty": round(condition["eta_penalty"], 4),
            "connectivity_penalty": round(condition["connectivity_penalty"], 4),
            "severity": round(condition["severity"], 2),
        })

    return sorted(
        conditions,
        key=lambda condition: condition["impacted_duration_seconds"],
        reverse=True,
    )


def _estimate_expected_bandwidth_mbps(score: float, dominant_band: int) -> float:
    band_peak_mbps = {
        0: 220.0,   # 5G NR
        1: 80.0,    # LTE 2300
        2: 30.0,    # LTE 900
        3: 1.5,     # GSM fallback
    }

    peak = band_peak_mbps.get(dominant_band, 30.0)
    quality = max(0.0, min(score, 100.0)) / 100.0
    bandwidth = peak * (quality ** 1.85)

    if score < DEAD_ZONE_THRESHOLD:
        bandwidth *= 0.25

    return round(max(0.1, bandwidth), 1)


def _build_signal_profile(scored_segs: list, total_len: float) -> list:
    if not scored_segs:
        return []

    cumulative_len = 0.0
    profile = []

    for seg in scored_segs:
        progress_start = cumulative_len / max(total_len, 1.0)
        cumulative_len += seg["length"]
        progress_end = cumulative_len / max(total_len, 1.0)

        profile.append({
            "lat": round(seg["lat"], 6),
            "lng": round(seg["lon"], 6),
            "score": round(seg["score"], 1),
            "dominant_band": seg["dominant_band"],
            "expected_bandwidth_mbps": _estimate_expected_bandwidth_mbps(
                seg["score"],
                seg["dominant_band"],
            ),
            "traffic_eta_penalty": round(seg.get("traffic_eta_penalty", 0.0), 4),
            "progress_start": round(progress_start, 4),
            "progress_end": round(min(progress_end, 1.0), 4),
        })

    return profile


def _compute_worst_window(scored_segs: list, window_m: float = 500) -> float:
    """Compute worst 500m sliding window average score."""
    if not scored_segs:
        return 0.0

    n = len(scored_segs)
    worst = 100.0

    for i in range(n):
        window_len = 0.0
        window_score_sum = 0.0
        for j in range(i, n):
            seg_len = scored_segs[j]["length"]
            seg_score = scored_segs[j]["score"]
            window_len += seg_len
            window_score_sum += seg_score * seg_len
            if window_len >= window_m:
                avg = window_score_sum / max(window_len, 0.1)
                worst = min(worst, avg)
                break

    return worst


def _extract_dead_zones(scored_segs: list) -> list:
    """
    Extract contiguous dead zones with pre-fetch trigger coordinates.
    """
    dead_zones = []
    in_dead_zone = False
    dz_start = None
    dz_segs = []
    last_strong_seg = None

    for seg in scored_segs:
        if seg["score"] >= PREFETCH_TRIGGER_MIN_SCORE:
            last_strong_seg = seg

        if seg["score"] < DEAD_ZONE_THRESHOLD:
            if not in_dead_zone:
                in_dead_zone = True
                dz_start = seg
                dz_segs = []
            dz_segs.append(seg)
        else:
            if in_dead_zone:
                # Dead zone ended — record it
                dz_end = dz_segs[-1]
                total_length = sum(s["length"] for s in dz_segs)
                total_duration = sum(s["duration"] for s in dz_segs)

                dead_zones.append({
                    "start_coord": [dz_start["lat"], dz_start["lon"]],
                    "end_coord": [dz_end["lat"], dz_end["lon"]],
                    "length_meters": round(total_length, 1),
                    "duration_seconds": round(total_duration, 1),
                    "prefetch_mb_required": round((total_duration * 5) / 8, 1),
                    "prefetch_trigger_coord": (
                        [last_strong_seg["lat"], last_strong_seg["lon"]]
                        if last_strong_seg else ([scored_segs[0]["lat"], scored_segs[0]["lon"]] if scored_segs else None)
                    ),
                })
                in_dead_zone = False
                dz_segs = []

    # Handle dead zone at end of route
    if in_dead_zone and dz_segs:
        dz_end = dz_segs[-1]
        total_length = sum(s["length"] for s in dz_segs)
        total_duration = sum(s["duration"] for s in dz_segs)
        dead_zones.append({
            "start_coord": [dz_start["lat"], dz_start["lon"]],
            "end_coord": [dz_end["lat"], dz_end["lon"]],
            "length_meters": round(total_length, 1),
            "duration_seconds": round(total_duration, 1),
            "prefetch_mb_required": round((total_duration * 5) / 8, 1),
            "prefetch_trigger_coord": (
                [last_strong_seg["lat"], last_strong_seg["lon"]]
                if last_strong_seg else ([scored_segs[0]["lat"], scored_segs[0]["lon"]] if scored_segs else None)
            ),
        })

    return dead_zones


# ──────────────────────────────────────────────────────────────────────────────
# BLENDED RANKING
# ──────────────────────────────────────────────────────────────────────────────

def compute_blended_rank(
    eta_seconds: float,
    connectivity_score: float,
    alpha: float,
    max_eta: float = 3600,
    handoff_count: int = 0,
) -> float:
    """
    edge_weight = α × norm_travel_time + (1-α) × (1 - norm_connectivity) + handoff_penalty
    Lower is better.
    """
    norm_time = min(eta_seconds / max_eta, 1.0)
    norm_conn = connectivity_score / 100.0
    handoff_penalty = handoff_count * 0.02
    return round(alpha * norm_time + (1 - alpha) * (1 - norm_conn) + handoff_penalty, 4)


def rerank_routes(routes: list, alpha: float) -> list:
    """Re-rank routes with a new alpha value. No recomputation needed."""
    for route in routes:
        route["blended_rank_score"] = compute_blended_rank(
            route.get("eta_seconds", 1800),
            route.get("connectivity_score", 50),
            alpha,
            handoff_count=route.get("handoff_count", 0),
        )

    return sorted(routes, key=lambda r: r["blended_rank_score"])


def apply_persona_constraints(routes: list, persona: str) -> list:
    """Apply persona-specific constraints to route ranking."""
    if not persona:
        return routes
    persona = persona.strip().lower()
    config = PERSONA_CONFIG.get(persona, {})

    if persona == "emergency":
        # Force zero-dead-zone route if ETA penalty ≤ 30%
        zero_dz_routes = [r for r in routes if r.get("dead_zone_count", 0) == 0]
        if zero_dz_routes:
            best_eta = min(r.get("eta_seconds", 9999) for r in routes)
            for r in zero_dz_routes:
                if r.get("eta_seconds", 9999) <= best_eta * 1.3:
                    # Move to front
                    routes.remove(r)
                    routes.insert(0, r)
                    r["emergency_preferred"] = True
                    break

        # Flag remaining routes with dead zones
        for r in routes:
            if r.get("dead_zone_count", 0) > 0:
                r["emergency_warning"] = True

    elif persona == "fleet_ota":
        # Check sustained minimum floor
        window_km = config.get("window_km", 2.0)
        floor = config.get("sustained_minimum", 0.40) * 100
        for r in routes:
            scored_segs = r.get("scored_segments", [])
            fleet_window_score = _compute_worst_window(scored_segs, window_m=window_km * 1000)
            if fleet_window_score < floor:
                r["fleet_ota_warning"] = True

    return routes

# ──────────────────────────────────────────────────────────────────────────────
# DESTINATION DEAD ZONE DETECTION
# ──────────────────────────────────────────────────────────────────────────────

def check_destination_dead_zone(
    osrm_route: dict,
    route_scores: dict,
    dest_lat: float,
    dest_lon: float,
    graph=None
):
    """
    Checks if destination is a dead zone.
    Returns (is_dead_zone: bool, prefetch_burst_point_coord: list | None).
    """
    is_dead_zone = False
    
    # 1. Check OSM tags if graph is available
    if graph is not None:
        try:
            import osmnx as ox
            # find nearest node
            node_id = ox.distance.nearest_nodes(graph, X=dest_lon, Y=dest_lat)
            node_data = graph.nodes[node_id]
            amenity = node_data.get("amenity", "")
            parking = node_data.get("parking", "")
            if amenity == "parking" or parking in ["multi-storey", "underground"]:
                is_dead_zone = True
        except Exception:
            pass

    # 2. Check nearest scored segment
    scored_segments = route_scores.get("scored_segments", [])
    if not is_dead_zone and scored_segments:
        # The last segment in the route is usually closest to destination
        last_seg = scored_segments[-1]
        dist_to_dest = haversine_km(last_seg["lat"], last_seg["lon"], dest_lat, dest_lon) * 1000
        if dist_to_dest <= 100 and last_seg["score"] < DEAD_ZONE_THRESHOLD:
            is_dead_zone = True

    burst_point = None
    if is_dead_zone:
        coords = osrm_route.get("geometry", {}).get("coordinates", [])
        burst_point = _backtrack_route_geometry(coords, distance_m=500.0)

    return is_dead_zone, burst_point

def _backtrack_route_geometry(coords: list, distance_m: float):
    """
    Walk backward from the end of the coords list by `distance_m` meters.
    coords is list of [lon, lat].
    Returns [lat, lon] of the burst point.
    """
    if not coords or len(coords) < 2:
        return None
        
    accumulated_dist = 0.0
    # Iterate backwards
    for i in range(len(coords) - 1, 0, -1):
        p1 = coords[i]      # [lon, lat]
        p2 = coords[i-1]    # [lon, lat]
        
        # distance between p1 and p2 in meters
        d = haversine_km(p1[1], p1[0], p2[1], p2[0]) * 1000
        
        if accumulated_dist + d >= distance_m:
            # Interpolate
            remaining = distance_m - accumulated_dist
            fraction = remaining / d if d > 0 else 0
            
            # Interpolate from p1 towards p2
            lon = p1[0] + fraction * (p2[0] - p1[0])
            lat = p1[1] + fraction * (p2[1] - p1[1])
            return [round(lat, 6), round(lon, 6)]
            
        accumulated_dist += d
        
    # If route is shorter than distance_m, return the origin
    return [round(coords[0][1], 6), round(coords[0][0], 6)]
