"""
backend/explainer.py
Natural language explanation generator for segment connectivity scores.
Rule-based — deterministic and fast (no LLM dependency).
"""

from datetime import datetime

from config import BAND_NAMES
from scorer import (
    haversine_km,
    get_active_conditions,
    get_matching_conditions,
    resolve_request_time,
)


def explain_segment(
    props: dict,
    congestion_active: bool = False,
    weather_active: bool = False,
    precipitation_mm: float = 0.0,
) -> dict:
    """
    Generate a natural language explanation for a scored segment.

    Args:
        props: Segment properties from the scored GeoJSON
        congestion_active: Whether time-of-day congestion is currently active
        weather_active: Whether precipitation attenuation is currently active
        precipitation_mm: Current precipitation in mm/hr

    Returns:
        dict with explanation text and supporting data
    """
    factors = []
    score = float(props.get("composite_score", 50))

    # ── Terrain shadow ──
    if props.get("terrain_shadow"):
        factors.append(
            "Terrain elevation blocks line-of-sight to nearest tower"
        )

    # ── Sky view factor ──
    svf = float(props.get("svf", 1.0))
    if svf < 0.3:
        factors.append(
            "Dense building cluster severely restricts sky view and signal path"
        )
    elif svf < 0.5:
        factors.append(
            "Moderate building obstruction reduces direct signal path"
        )

    # ── Congestion ──
    if congestion_active:
        factors.append(
            "Network congestion active — peak hour user density exceeds capacity"
        )

    # ── Weather ──
    if weather_active:
        if precipitation_mm > 10:
            factors.append(
                f"Heavy rain ({precipitation_mm:.1f} mm/hr) significantly "
                "attenuating high-band signal quality"
            )
        else:
            factors.append(
                "Precipitation attenuation reducing high-band signal quality"
            )

    # ── Score-based fallback ──
    if not factors:
        if score > 70:
            factors.append(
                "Open terrain with strong line-of-sight to multiple towers"
            )
        elif score > 40:
            factors.append(
                "Moderate coverage — no significant obstructions identified"
            )
        else:
            factors.append(
                "Weak coverage area — limited tower density and possible obstructions"
            )

    # ── Get band name ──
    dominant_band_raw = props.get("dominant_band", 2)
    try:
        dominant_band_enc = int(dominant_band_raw)
    except (TypeError, ValueError):
        reverse_bands = {v: k for k, v in BAND_NAMES.items()}
        dominant_band_enc = reverse_bands.get(str(dominant_band_raw).upper(), 2)
    dominant_band_name = BAND_NAMES.get(dominant_band_enc, "LTE_900")

    # ── Compute nearest tower distance (approximate from confidence) ──
    confidence = float(props.get("confidence", 0.5))
    nearest_tower_dist_m = int(max(200, (1 - confidence) * 2000))

    explanation_text = ". ".join(factors) + "."

    return {
        "explanation": explanation_text,
        "rsrp_dbm": round(-140 + score * 0.96, 1),  # Approximate RSRP from score
        "confidence": round(confidence, 3),
        "dominant_band": dominant_band_name,
        "nearest_tower_distance_m": nearest_tower_dist_m,
        "nearest_tower_type": "LTE" if dominant_band_enc < 3 else "GSM",
        "svf": round(svf, 3),
        "terrain_shadow": bool(props.get("terrain_shadow", False)),
    }


def check_congestion_active(lat: float, lon: float, current_hour: int) -> bool:
    """Check if any rush-hour or venue condition is active at the given location."""
    request_time = resolve_request_time(datetime.now())
    if current_hour is not None and current_hour != request_time.hour:
        request_time = request_time.replace(
            hour=current_hour,
            minute=0,
            second=0,
            microsecond=0,
        )

    matched_conditions = get_matching_conditions(
        lat,
        lon,
        get_active_conditions(request_time),
    )
    return any(
        condition.get("type") in {"rush_hour", "venue_event"}
        for condition in matched_conditions
    )
