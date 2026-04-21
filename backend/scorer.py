"""
backend/scorer.py
Online scoring module — weather attenuation and congestion penalties.
Applied at request time on top of precomputed GNN scores.
"""

import math
from datetime import datetime, timedelta
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

import httpx

from config import (
    CONGESTION_ZONES, VENUES, LOCAL_TIMEZONE,
)
from weather import classify_weather, get_band_multipliers, simulate_weather

# Map dominant_band encoding to weather multiplier key
BAND_TO_WEATHER_KEY = {
    0: "5G_NR",     # 5G NR
    1: "LTE_2300",  # LTE high band
    2: "LTE_900_700",  # LTE low band
    3: "LTE_900_700",  # GSM fallback
}

LOCAL_TZ = ZoneInfo(LOCAL_TIMEZONE)


async def get_weather_multipliers(
    lat: float = 12.9716,
    lon: float = 77.5946,
    scenario_name: Optional[str] = None,
) -> Tuple[dict, bool, float, dict]:
    """
    Fetch current weather from OpenMeteo or simulate a named scenario override.
    Returns (multipliers_dict, storm_active, precipitation_mm, metadata).

    Called ONCE per route request session (SPEC_SDD.md §4.7).
    """
    normalized_scenario = (scenario_name or "").strip().lower()
    if normalized_scenario and normalized_scenario != "live":
        simulation = simulate_weather(normalized_scenario)
        conditions = simulation["weather_conditions"]
        return (
            conditions["multipliers_applied"],
            bool(conditions["storm_active"]),
            float(conditions["precipitation_mm_hr"]),
            {
                "source": "simulation",
                "scenario": simulation["scenario"],
                "condition": conditions["condition"],
            },
        )

    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&current=precipitation,weathercode&timezone=Asia/Kolkata"
    )

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=5.0)
        data = resp.json().get("current", {})
        precip = data.get("precipitation", 0)
        code = data.get("weathercode", 0)

        # WMO thunderstorm codes
        storm = code in [95, 96, 99]
        condition = classify_weather(precipitation_mm_hr=precip, storm_active=storm)
        return (
            get_band_multipliers(precipitation_mm_hr=precip, storm_active=storm),
            storm,
            precip,
            {
                "source": "live",
                "scenario": "live",
                "condition": condition,
            },
        )

    except Exception:
        # Default to clear weather if API fails
        return (
            get_band_multipliers(precipitation_mm_hr=0.0, storm_active=False),
            False,
            0.0,
            {
                "source": "fallback",
                "scenario": "live",
                "condition": "clear",
            },
        )


def get_weather_multiplier_for_band(
    weather_multipliers: dict, dominant_band: int
) -> float:
    """Get weather multiplier for a specific frequency band."""
    band_key = BAND_TO_WEATHER_KEY.get(dominant_band, "LTE_900")
    return weather_multipliers.get(band_key, 1.0)


# ──────────────────────────────────────────────────────────────────────────────
# CONGESTION SCORING (SPEC_SDD.md §4.5)
# ──────────────────────────────────────────────────────────────────────────────

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def resolve_request_time(timestamp: Optional[str | datetime] = None) -> datetime:
    """
    Normalize frontend-provided timestamps into Bangalore local time.
    Accepts ISO strings, UTC `Z` strings, or datetime objects.
    """
    dt = None

    if isinstance(timestamp, datetime):
        dt = timestamp
    elif timestamp:
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            dt = None

    if dt is None:
        dt = datetime.now(LOCAL_TZ)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)

    return dt.astimezone(LOCAL_TZ)


def _decimal_hour(dt: datetime) -> float:
    return dt.hour + (dt.minute / 60.0) + (dt.second / 3600.0)


def _with_decimal_hour(dt: datetime, decimal_hour: float) -> datetime:
    hours = int(decimal_hour)
    minutes = int(round((decimal_hour - hours) * 60))
    if minutes == 60:
        hours += 1
        minutes = 0
    day_offset, hour_value = divmod(hours, 24)
    target_dt = dt + timedelta(days=day_offset)
    return target_dt.replace(hour=hour_value, minute=minutes, second=0, microsecond=0)


def _resolve_active_window(local_dt: datetime, window: dict) -> Optional[tuple[datetime, datetime]]:
    days = window.get("days", [0, 1, 2, 3, 4, 5, 6])
    start_hour = float(window.get("start_hour", 0))
    end_hour = float(window.get("end_hour", 24))
    now_hour = _decimal_hour(local_dt)

    if start_hour <= end_hour:
        if local_dt.weekday() not in days or not (start_hour <= now_hour < end_hour):
            return None
        return (
            _with_decimal_hour(local_dt, start_hour),
            _with_decimal_hour(local_dt, end_hour),
        )

    previous_day = local_dt - timedelta(days=1)
    if now_hour >= start_hour and local_dt.weekday() in days:
        return (
            _with_decimal_hour(local_dt, start_hour),
            _with_decimal_hour(local_dt + timedelta(days=1), end_hour),
        )

    if now_hour < end_hour and previous_day.weekday() in days:
        return (
            _with_decimal_hour(previous_day, start_hour),
            _with_decimal_hour(local_dt, end_hour),
        )

    return None


def _parse_config_datetime(value: Optional[str | datetime]) -> Optional[datetime]:
    if value is None:
        return None

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)

    return dt.astimezone(LOCAL_TZ)


def _build_zone_condition(zone_id: str, zone: dict, window: dict,
                          starts_at: datetime, ends_at: datetime) -> dict:
    return {
        "id": f"zone:{zone_id}:{window.get('label', 'window').lower().replace(' ', '_')}",
        "slug": zone_id,
        "label": zone.get("label", zone_id.replace("_", " ").title()),
        "type": "rush_hour",
        "reason": window.get("label", "Peak Window"),
        "center": {
            "lat": round(zone["center"][0], 6),
            "lng": round(zone["center"][1], 6),
        },
        "radius_km": float(zone.get("radius_km", 1.0)),
        "eta_penalty": float(zone.get("eta_penalty", 0.0)),
        "connectivity_penalty": float(zone.get("connectivity_penalty", 0.0)),
        "active_from": starts_at.isoformat(),
        "active_until": ends_at.isoformat(),
        "severity": 1.0,
    }


def _build_venue_condition(venue_id: str, venue: dict, event: dict,
                           starts_at: datetime, ends_at: datetime) -> dict:
    severity = max(0.25, min(float(event.get("severity", 1.0)), 1.5))
    eta_penalty = min(0.95, float(venue.get("eta_penalty", 0.0)) * severity)
    connectivity_penalty = min(0.95, float(venue.get("connectivity_penalty", 0.0)) * severity)

    event_name = event.get("name", "Scheduled Event")

    return {
        "id": f"venue:{venue_id}:{event_name.lower().replace(' ', '_')}",
        "slug": venue_id,
        "label": venue.get("label", venue_id.replace("_", " ").title()),
        "type": "venue_event",
        "reason": event_name,
        "center": {
            "lat": round(venue["coords"][0], 6),
            "lng": round(venue["coords"][1], 6),
        },
        "radius_km": float(venue.get("radius_km", 1.0)),
        "eta_penalty": round(eta_penalty, 4),
        "connectivity_penalty": round(connectivity_penalty, 4),
        "active_from": starts_at.isoformat(),
        "active_until": ends_at.isoformat(),
        "severity": round(severity, 2),
        "event_name": event_name,
    }


def get_active_conditions(request_time: Optional[str | datetime] = None) -> list[dict]:
    """
    Resolve the Bangalore hotspot/event conditions active for a given request time.
    """
    local_dt = resolve_request_time(request_time)
    active_conditions = []

    for zone_id, zone in CONGESTION_ZONES.items():
        for window in zone.get("active_windows", []):
            active_window = _resolve_active_window(local_dt, window)
            if not active_window:
                continue

            starts_at, ends_at = active_window
            active_conditions.append(
                _build_zone_condition(zone_id, zone, window, starts_at, ends_at)
            )

    for venue_id, venue in VENUES.items():
        for event in venue.get("active_events", []):
            starts_at = _parse_config_datetime(event.get("starts_at") or event.get("start"))
            ends_at = _parse_config_datetime(event.get("ends_at") or event.get("end"))
            if starts_at is None:
                continue
            if ends_at is None:
                duration_hours = float(event.get("duration_hours", 4.0))
                ends_at = starts_at + timedelta(hours=duration_hours)

            pre_buffer = float(event.get("pre_buffer_hours", venue.get("default_pre_buffer_hours", 2.0)))
            post_buffer = float(event.get("post_buffer_hours", venue.get("default_post_buffer_hours", 1.0)))
            active_from = starts_at - timedelta(hours=pre_buffer)
            active_until = ends_at + timedelta(hours=post_buffer)

            if not (active_from <= local_dt <= active_until):
                continue

            active_conditions.append(
                _build_venue_condition(venue_id, venue, event, active_from, active_until)
            )

    return active_conditions


def get_matching_conditions(seg_lat: float, seg_lon: float,
                            active_conditions: Optional[list[dict]] = None) -> list[dict]:
    matched = []

    for condition in active_conditions or []:
        center = condition.get("center") or {}
        dist = haversine_km(
            seg_lat,
            seg_lon,
            float(center.get("lat", 0.0)),
            float(center.get("lng", 0.0)),
        )
        if dist <= float(condition.get("radius_km", 0.0)):
            matched.append(condition)

    return matched


def combine_penalties(penalties: list[float]) -> float:
    remaining = 1.0
    has_penalty = False

    for penalty in penalties:
        penalty = max(0.0, min(0.95, float(penalty or 0.0)))
        if penalty == 0:
            continue
        has_penalty = True
        remaining *= (1.0 - penalty)

    if not has_penalty:
        return 0.0

    return round(1.0 - remaining, 4)


def score_segment_online(
    base_score: float,
    seg_lat: float,
    seg_lon: float,
    dominant_band: int,
    weather_multipliers: dict,
    active_conditions: Optional[list[dict]] = None,
    way_id: str = None,
) -> tuple[float, list[dict], float, float]:
    """
    Apply all online scoring adjustments to a precomputed base score.
    Order: telemetry override → weather → active-condition penalties → clamp
    """
    matched_conditions = get_matching_conditions(seg_lat, seg_lon, active_conditions)
    connectivity_penalty = combine_penalties([
        condition.get("connectivity_penalty", 0.0)
        for condition in matched_conditions
    ])
    eta_penalty = combine_penalties([
        condition.get("eta_penalty", 0.0)
        for condition in matched_conditions
    ])

    if way_id:
        from cache import get_telemetry_override
        override = get_telemetry_override(way_id)
        if override is not None:
            return (
                max(0.0, min(100.0, round(float(override), 2))),
                matched_conditions,
                connectivity_penalty,
                eta_penalty,
            )

    # Weather attenuation
    wx_mult = get_weather_multiplier_for_band(weather_multipliers, dominant_band)
    score = base_score * wx_mult

    # Time-of-day and event penalties resolved up-front for the request time.
    score *= (1.0 - connectivity_penalty)

    return (
        max(0.0, min(100.0, round(score, 2))),
        matched_conditions,
        connectivity_penalty,
        eta_penalty,
    )
