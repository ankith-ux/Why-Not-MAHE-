"""
backend/config.py
Configuration constants for the Connectivity Intelligence Platform.
All values must match SPEC_SDD.md exactly — they are interface contracts.
"""

# ──────────────────────────────────────────────────────────────────────────────
# BOUNDING BOX
# ──────────────────────────────────────────────────────────────────────────────

BBOX = {"south": 12.834, "north": 13.139, "west": 77.469, "east": 77.748}
LOCAL_TIMEZONE = "Asia/Kolkata"

# ──────────────────────────────────────────────────────────────────────────────
# CONGESTION ZONES (SPEC_SDD.md §4.5)
# ──────────────────────────────────────────────────────────────────────────────

CONGESTION_ZONES = {
    "silk_board": {
        "label": "Silk Board Junction",
        "center": (12.9176, 77.6229),
        "radius_km": 1.2,
        "active_windows": [
            {"label": "Weekday AM Peak", "days": [0, 1, 2, 3, 4], "start_hour": 8, "end_hour": 11},
            {"label": "Weekday PM Peak", "days": [0, 1, 2, 3, 4], "start_hour": 17, "end_hour": 21},
        ],
        "eta_penalty": 0.28,
        "connectivity_penalty": 0.45,
    },
    "whitefield": {
        "label": "Whitefield Tech Corridor",
        "center": (12.9698, 77.7499),
        "radius_km": 2.0,
        "active_windows": [
            {"label": "Weekday AM Peak", "days": [0, 1, 2, 3, 4], "start_hour": 9, "end_hour": 11},
            {"label": "Weekday PM Peak", "days": [0, 1, 2, 3, 4], "start_hour": 18, "end_hour": 21},
        ],
        "eta_penalty": 0.34,
        "connectivity_penalty": 0.50,
    },
    "electronic_city": {
        "label": "Electronic City",
        "center": (12.8399, 77.6770),
        "radius_km": 1.5,
        "active_windows": [
            {"label": "Weekday AM Peak", "days": [0, 1, 2, 3, 4], "start_hour": 8, "end_hour": 10},
            {"label": "Weekday PM Peak", "days": [0, 1, 2, 3, 4], "start_hour": 17, "end_hour": 20},
        ],
        "eta_penalty": 0.26,
        "connectivity_penalty": 0.40,
    },
}

# ──────────────────────────────────────────────────────────────────────────────
# EVENT VENUES (SPEC_SDD.md §4.6)
# ──────────────────────────────────────────────────────────────────────────────

# `active_events` entries can use:
# {
#   "name": "Home Match",
#   "starts_at": "2026-04-24T19:30:00+05:30",
#   "ends_at": "2026-04-24T23:00:00+05:30",
#   "pre_buffer_hours": 2,
#   "post_buffer_hours": 1,
#   "severity": 1.0,
# }
VENUES = {
    "chinnaswamy_stadium": {
        "label": "M. Chinnaswamy Stadium",
        "coords": (12.9792, 77.5993),
        "capacity": 38000,
        "radius_km": 2.0,
        "eta_penalty": 0.55,
        "connectivity_penalty": 0.50,
        "default_pre_buffer_hours": 2.0,
        "default_post_buffer_hours": 1.5,
        "active_events": [],
    },
    "palace_grounds": {
        "label": "Palace Grounds",
        "coords": (13.0057, 77.5800),
        "capacity": 50000,
        "radius_km": 2.5,
        "eta_penalty": 0.42,
        "connectivity_penalty": 0.45,
        "default_pre_buffer_hours": 2.0,
        "default_post_buffer_hours": 1.5,
        "active_events": [],
    },
    "kanteerava_stadium": {
        "label": "Kanteerava Stadium",
        "coords": (12.9766, 77.5993),
        "capacity": 15000,
        "radius_km": 1.5,
        "eta_penalty": 0.35,
        "connectivity_penalty": 0.40,
        "default_pre_buffer_hours": 1.5,
        "default_post_buffer_hours": 1.0,
        "active_events": [],
    },
    "biec": {
        "label": "BIEC",
        "coords": (13.0697, 77.5800),
        "capacity": 30000,
        "radius_km": 2.0,
        "eta_penalty": 0.32,
        "connectivity_penalty": 0.40,
        "default_pre_buffer_hours": 2.0,
        "default_post_buffer_hours": 1.0,
        "active_events": [],
    },
}

# ──────────────────────────────────────────────────────────────────────────────
# PERSONA PRESETS (SPEC_SDD.md §6.4)
# ──────────────────────────────────────────────────────────────────────────────

PERSONA_CONFIG = {
    "emergency": {"alpha": 0.10, "max_dead_zone_m": 300, "hard_floor": True},
    "ride_hailing": {"alpha": 0.70, "hard_floor": False},
    "it_shuttle": {"alpha": 0.50, "hard_floor": False},
    "fleet_ota": {"alpha": 0.40, "sustained_minimum": 0.40, "window_km": 2.0},
}

# ──────────────────────────────────────────────────────────────────────────────
# ROAD SPEEDS (SPEC_SDD.md §4.8)
# ──────────────────────────────────────────────────────────────────────────────

ROAD_SPEEDS_KMH = {
    "motorway": 100, "motorway_link": 100,
    "trunk": 80, "trunk_link": 80,
    "primary": 60, "primary_link": 60,
    "secondary": 40, "secondary_link": 40,
    "tertiary": 35,
    "residential": 30, "unclassified": 30,
    "service": 15,
}

# ──────────────────────────────────────────────────────────────────────────────
# THRESHOLDS
# ──────────────────────────────────────────────────────────────────────────────

DEAD_ZONE_THRESHOLD = 25      # score below this = dead zone
STRONG_THRESHOLD = 60         # score above this = strong signal
PREFETCH_TRIGGER_MIN_SCORE = 70  # last waypoint before dead zone must be > this

# ──────────────────────────────────────────────────────────────────────────────
# BAND MAPPING
# ──────────────────────────────────────────────────────────────────────────────

BAND_NAMES = {0: "5G_NR", 1: "LTE_2300", 2: "LTE_900", 3: "GSM"}

# ──────────────────────────────────────────────────────────────────────────────
# CARRIERS
# ──────────────────────────────────────────────────────────────────────────────

CARRIERS = ["jio", "airtel", "vi", "bsnl", "composite"]
