import os
import requests
from datetime import date, timedelta

API_KEY = os.environ["SERPAPI_API_KEY"]

today = date.today()
six_months_later = today + timedelta(days=183)

params = {
    "engine": "google_flights_deals",
    "departure_id": "AMS",
    "arrival_id": "HKG",
    "outbound_date": f"{today},{six_months_later}",
    "trip_length": "7",
    "travel_class": "1",
    "currency": "EUR",
    "hl": "en",
    "gl": "nl",
    "api_key": API_KEY,
}

response = requests.get(
    "https://serpapi.com/search.json",
    params=params,
    timeout=60,
)

response.raise_for_status()
data = response.json()

print("Status:", data.get("search_metadata", {}).get("status"))

if "error" in data:
    print("ERROR:", data["error"])

print("\nTop-level fields:")
print(list(data.keys()))

deals = data.get("deals", [])

print(f"\nDeals returned: {len(deals)}")

for i, deal in enumerate(deals[:10], 1):
    print(f"\n--- DEAL {i} ---")
    print(deal)
