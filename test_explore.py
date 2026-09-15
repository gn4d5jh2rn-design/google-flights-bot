import os
import requests
import json

API_KEY = os.environ["SERPAPI_API_KEY"]

params = {
    "engine": "google_travel_explore",
    "departure_id": "AMS",
    "arrival_id": "HKG",
    "travel_duration": "1",
    "currency": "EUR",
    "hl": "en",
    "gl": "nl",
    "api_key": API_KEY,
}

response = requests.get(
    "https://serpapi.com/search.json",
    params=params,
    timeout=120,
)

response.raise_for_status()
data = response.json()

print("Status:", data.get("search_metadata", {}).get("status"))

if "error" in data:
    print("ERROR:", data["error"])

print("\nTop-level keys:")
print(list(data.keys()))

print("\nFULL RESPONSE:")
print(json.dumps(data, indent=2))
