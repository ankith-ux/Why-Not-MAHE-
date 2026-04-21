"""
backend/cache.py
Redis caching wrapper for the Connectivity Intelligence Platform.
Provides route caching with TTL-based expiration.
"""

import json
import hashlib
import time
from typing import Optional

try:
    import redis
except ImportError:  # Optional in local/dev environments
    redis = None

# Redis connection (lazy init for environments without Redis)
_redis_client = None
ROUTE_CACHE = {}
WEATHER_CACHE = {}


def get_redis() -> Optional[object]:
    """Get Redis client, return None if unavailable."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if redis is None:
        return None
    try:
        _redis_client = redis.Redis(
            host="localhost", port=6379,
            decode_responses=True,
            socket_connect_timeout=2,
        )
        _redis_client.ping()
        return _redis_client
    except (redis.ConnectionError, redis.TimeoutError):
        _redis_client = None
        return None


def route_cache_key(origin_lat: float, origin_lon: float,
                    dest_lat: float, dest_lon: float) -> str:
    """
    Generate a deterministic cache key for a route query.
    Round to 4 decimal places (~11m precision) to allow cache hits
    for nearby origins/destinations.
    """
    key = (f"{round(origin_lat, 4)}_{round(origin_lon, 4)}_"
           f"{round(dest_lat, 4)}_{round(dest_lon, 4)}")
    return f"bangalore:route:{hashlib.md5(key.encode()).hexdigest()}"


def cache_routes(key: str, routes: list, ttl: int = 600) -> bool:
    """Cache scored routes with TTL (default 10 minutes)."""
    ROUTE_CACHE[key] = {
        "routes": routes,
        "expires_at": time.time() + ttl,
    }

    r = get_redis()
    if r is None:
        return True
    try:
        r.setex(key, ttl, json.dumps(routes))
        return True
    except redis.RedisError:
        return True


def get_cached_routes(key: str) -> Optional[list]:
    """Retrieve cached routes. Returns None on miss or Redis unavailable."""
    cached = ROUTE_CACHE.get(key)
    if cached is not None:
        if cached["expires_at"] > time.time():
            return cached["routes"]
        ROUTE_CACHE.pop(key, None)

    r = get_redis()
    if r is None:
        return None
    try:
        data = r.get(key)
        return json.loads(data) if data else None
    except (redis.RedisError, json.JSONDecodeError):
        return None


def cache_weather(weather_data: dict, ttl: int = 300) -> bool:
    """Cache weather data (5 minute TTL)."""
    WEATHER_CACHE["bangalore:weather"] = {
        "data": weather_data,
        "expires_at": time.time() + ttl,
    }

    r = get_redis()
    if r is None:
        return True
    try:
        r.setex("bangalore:weather", ttl, json.dumps(weather_data))
        return True
    except redis.RedisError:
        return True


def get_cached_weather() -> Optional[dict]:
    """Get cached weather data."""
    cached = WEATHER_CACHE.get("bangalore:weather")
    if cached is not None:
        if cached["expires_at"] > time.time():
            return cached["data"]
        WEATHER_CACHE.pop("bangalore:weather", None)

    r = get_redis()
    if r is None:
        return None
    try:
        data = r.get("bangalore:weather")
        return json.loads(data) if data else None
    except (redis.RedisError, json.JSONDecodeError):
        return None


# ──────────────────────────────────────────────────────────────────────────────
# TELEMETRY CACHE
# ──────────────────────────────────────────────────────────────────────────────

TELEMETRY_OVERRIDES = {}

def cache_telemetry_override(way_id: str, score: float, ttl: int = 3600) -> bool:
    """Cache a live telemetry override for a segment (default 1 hour TTL)."""
    # In-memory cache for fast O(1) routing lookups
    TELEMETRY_OVERRIDES[way_id] = score

    # Redis cache for cross-worker persistence
    r = get_redis()
    if r is None:
        return False
    try:
        r.setex(f"bangalore:telemetry:{way_id}", ttl, json.dumps({"score": score}))
        return True
    except redis.RedisError:
        return False

def get_telemetry_override(way_id: str) -> Optional[float]:
    """Get live telemetry override. Prioritizes in-memory cache."""
    if way_id in TELEMETRY_OVERRIDES:
        return TELEMETRY_OVERRIDES[way_id]
        
    r = get_redis()
    if r is None:
        return None
    try:
        data = r.get(f"bangalore:telemetry:{way_id}")
        if data:
            parsed = json.loads(data)
            score = parsed.get("score")
            # Populate in-memory cache
            TELEMETRY_OVERRIDES[way_id] = score
            return score
        return None
    except (redis.RedisError, json.JSONDecodeError):
        return None
