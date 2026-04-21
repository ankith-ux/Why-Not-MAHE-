import requests
import json
import time

BASE_URL = "http://localhost:8000"

def print_result(name, res):
    print(f"\n=========================================")
    print(f"Testing: {name}")
    print(f"=========================================")
    if res.status_code == 200:
        print("✅ SUCCESS (200 OK)")
        try:
            data_str = json.dumps(res.json(), indent=2)
            if len(data_str) > 1000:
                print(data_str[:1000] + "\n... [Output Truncated]")
            else:
                print(data_str)
        except Exception as e:
            print("Response text:")
            print(res.text[:1000])
    else:
        print(f"❌ FAILED with status {res.status_code}")
        print("Response:", res.text)

def test_health():
    res = requests.get(f"{BASE_URL}/api/health")
    print_result("Health Check (/api/health)", res)
    return res.status_code == 200

def test_route_score():
    payload = {
        "origin": {"lat": 12.9716, "lng": 77.5946},
        "destination": {"lat": 12.9352, "lng": 77.6245},
        "alpha": 0.5,
        "carrier": "composite",
        "persona": "it_shuttle"
    }
    res = requests.post(f"{BASE_URL}/api/route/score", json=payload)
    print_result("Route Score (/api/route/score)", res)
    if res.status_code == 200:
        return res.json().get("route_cache_key")
    return None

def test_route_rerank(cache_key):
    if not cache_key:
        print("\n--- Testing Route Rerank ---")
        print("⏭️ SKIPPED (No cache key available)")
        return
    payload = {
        "route_cache_key": cache_key,
        "alpha": 0.8
    }
    res = requests.post(f"{BASE_URL}/api/route/rerank", json=payload)
    print_result("Route Rerank (/api/route/rerank)", res)

def test_heat_tiles():
    params = {
        "west": 77.50,
        "south": 12.90,
        "east": 77.70,
        "north": 13.00,
        "carrier": "composite"
    }
    res = requests.get(f"{BASE_URL}/api/heat/tiles", params=params)
    print_result("Heat Tiles (/api/heat/tiles)", res)

def test_fleet_routes():
    payload = {
        "routes": [
             {
                 "origin": {"lat": 12.9716, "lng": 77.5946},
                 "destination": {"lat": 12.9352, "lng": 77.6245}
             }
        ],
        "persona": "fleet_ota"
    }
    res = requests.post(f"{BASE_URL}/api/fleet/routes", json=payload)
    print_result("Fleet Routes (/api/fleet/routes)", res)

def test_telemetry_report():
    payload = {
        "osm_way_id": "123456789",
        "signal_score": 10.5,
        "ttl_seconds": 3600
    }
    res = requests.post(f"{BASE_URL}/api/telemetry/report", json=payload)
    print_result("Telemetry Report (/api/telemetry/report)", res)

def main():
    print(f"Starting NeuralPath Backend API Tests...")
    print(f"Target URL: {BASE_URL}")
    print("Make sure the backend is running (e.g. `uvicorn main:app --host 0.0.0.0 --port 8000`)\n")
    
    try:
        # Check if server is running by hitting health endpoint first
        requests.get(f"{BASE_URL}/api/health")
    except requests.ConnectionError:
        print(f"⚠️ ERROR: Could not connect to {BASE_URL}.")
        print("Please start the FastAPI server first!")
        return

    test_health()
    cache_key = test_route_score()
    test_route_rerank(cache_key)
    test_heat_tiles()
    test_fleet_routes()
    test_telemetry_report()
    
    print("\n✅ All test requests completed.")

if __name__ == "__main__":
    main()
