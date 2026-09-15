import os
import requests
import json

API_KEY = os.environ["SERPAPI_API_KEY"]

params = {
    "engine": "google_travel_explore",
    "departure_id": "AMS",
    "arrival_id": "HKG",
    "travel_duration": "2",
    "month": "0",
    "stops": "2",
    "travel_class": "1",
    "adults": "1",
    "currency": "EUR",
    "hl": "en",
    "gl": "nl",
    "api_key": API_KEY,
}

for attempt in range(3):
    try:
        response = requests.get(
            "https://serpapi.com/search.json",
            params=params,
            timeout=120,
        )
        response.raise_for_status()
        break
    except requests.RequestException as e:
        if attempt == 2:
            raise
        print(f"Connection failed ({e}). Retrying in 10 seconds...")
        import time
        time.sleep(10)

data = response.json()

print("Status:", data.get("search_metadata", {}).get("status"))

if "error" in data:
    print("ERROR:", data["error"])

print("\nTop-level keys:")
print(list(data.keys()))

print("\nFULL RESPONSE:")
print(json.dumps(data, indent=2))
