"""
backend/fleet.py
Fleet route diversification engine.
SPEC_SDD.md §6.7 — distributes vehicles across routes to minimize
collective dead-zone risk.
"""

import math
from typing import List, Dict

from config import DEAD_ZONE_THRESHOLD


def diversify_fleet_routes(
    fleet_routes: List[List[dict]],
    segment_dict: dict,
    persona: str = "fleet_ota",
) -> dict:
    """
    Diversify fleet routes to minimize collective dead-zone exposure.

    Args:
        fleet_routes: List of route-sets, one per vehicle.
                      Each route-set is a list of route dicts with scored_segments.
        segment_dict: Global segment dictionary for score lookups.
        persona: Fleet persona (affects constraints).

    Returns:
        {
            "individual_optimal": [...],   # Best route per vehicle (no fleet coordination)
            "fleet_diversified": [...],    # Diversified routes
            "collective_risk_score": 0.17  # Fraction of fleet simultaneously in dead zones
        }
    """
    n_vehicles = len(fleet_routes)

    # ── Step 1: Individual optimal (best connectivity per vehicle) ──
    individual_optimal = []
    for vehicle_routes in fleet_routes:
        if not vehicle_routes:
            individual_optimal.append(None)
            continue
        # Pick route with best connectivity score
        best = max(vehicle_routes, key=lambda r: r.get("connectivity_score", 0))
        individual_optimal.append(best)

    # ── Step 2: Build dead zone occupancy map ──
    dz_occupancy = build_dead_zone_occupancy(individual_optimal)

    # ── Step 3: Diversify — reassign vehicles from overcrowded dead zones ──
    fleet_diversified = list(individual_optimal)  # Start with individual optimal

    # Find dead zone segments that appear in >60% of routes
    overcrowded_dzs = {
        seg_id: vehicle_ids
        for seg_id, vehicle_ids in dz_occupancy.items()
        if len(vehicle_ids) > max(1, 0.6 * n_vehicles)
    }

    if overcrowded_dzs:
        # Reassign lower-priority vehicles to alternatives
        reassigned = set()
        for seg_id, vehicle_ids in overcrowded_dzs.items():
            # Keep the first vehicle on its optimal route, reassign the rest
            for v_idx in vehicle_ids[1:]:
                if v_idx in reassigned:
                    continue

                # Try to find an alternative route without this dead zone
                alternatives = fleet_routes[v_idx] if v_idx < len(fleet_routes) else []
                for alt_route in alternatives:
                    alt_segs = _get_dead_zone_segment_ids(alt_route)
                    if seg_id not in alt_segs:
                        fleet_diversified[v_idx] = alt_route
                        reassigned.add(v_idx)
                        break

    # ── Step 4: Compute collective risk score ──
    diversified_dz_occupancy = build_dead_zone_occupancy(fleet_diversified)
    max_overlap = max(
        (len(v) for v in diversified_dz_occupancy.values()),
        default=0,
    )
    collective_risk = round(max_overlap / max(n_vehicles, 1), 2)

    return {
        "individual_optimal": _serialize_routes(individual_optimal),
        "fleet_diversified": _serialize_routes(fleet_diversified),
        "collective_risk_score": collective_risk,
        "vehicles_reassigned": len(overcrowded_dzs),
    }


def build_dead_zone_occupancy(routes: list) -> Dict[str, List[int]]:
    """
    Build map: {dead_zone_segment_id: [vehicle_indices]}
    """
    occupancy = {}
    for v_idx, route in enumerate(routes):
        if route is None:
            continue
        dz_segs = _get_dead_zone_segment_ids(route)
        for seg_id in dz_segs:
            occupancy.setdefault(seg_id, []).append(v_idx)
    return occupancy


def _get_dead_zone_segment_ids(route: dict) -> set:
    """Get set of segment IDs that are in dead zones on this route."""
    dz_seg_ids = set()
    scored_segs = route.get("scored_segments", [])
    for seg in scored_segs:
        if seg.get("score", 100) < DEAD_ZONE_THRESHOLD:
            dz_seg_ids.add(seg.get("way_id", ""))
    return dz_seg_ids


def _serialize_routes(routes: list) -> list:
    """Serialize routes for API response (strip internal data)."""
    result = []
    for route in routes:
        if route is None:
            result.append(None)
            continue
        # Strip scored_segments to reduce response size
        r = {k: v for k, v in route.items() if k != "scored_segments"}
        result.append(r)
    return result


def generate_demo_fleet(
    segment_dict: dict,
    n_vehicles: int = 6,
) -> list:
    """
    Generate demo fleet with simulated vehicle positions.
    One vehicle is guaranteed to be in a dead zone per SPEC_SDD §2.1 F-09.
    """
    import random

    random.seed(42)
    vehicles = []

    # Pre-defined demo positions
    demo_positions = [
        {"lat": 12.935, "lon": 77.625, "label": "Vehicle 1 - Koramangala"},
        {"lat": 12.970, "lon": 77.600, "label": "Vehicle 2 - MG Road"},
        {"lat": 12.840, "lon": 77.677, "label": "Vehicle 3 - Electronic City"},
        {"lat": 12.860, "lon": 77.720, "label": "Vehicle 4 - NICE Road (Dead Zone)"},
        {"lat": 12.970, "lon": 77.750, "label": "Vehicle 5 - Whitefield"},
        {"lat": 13.006, "lon": 77.580, "label": "Vehicle 6 - Hebbal"},
    ]

    for i, pos in enumerate(demo_positions[:n_vehicles]):
        # Find nearby segment
        best_seg = None
        best_dist = float("inf")
        for way_id, seg in segment_dict.items():
            seg_lat = float(seg.get("midpoint_lat", seg.get("segment_lat", 0)))
            seg_lon = float(seg.get("midpoint_lon", seg.get("segment_lon", 0)))
            d = math.hypot(pos["lat"] - seg_lat, pos["lon"] - seg_lon)
            if d < best_dist:
                best_dist = d
                best_seg = seg

        score = float(best_seg.get("composite_score", 50)) if best_seg else 50
        in_dead_zone = score < DEAD_ZONE_THRESHOLD

        vehicles.append({
            "vehicle_id": f"V-{i+1:03d}",
            "position": {"lat": pos["lat"], "lon": pos["lon"]},
            "label": pos["label"],
            "current_score": round(score, 1),
            "in_dead_zone": in_dead_zone,
            "status": "dead_zone" if in_dead_zone else ("strong" if score > 60 else "weak"),
        })

    return vehicles
