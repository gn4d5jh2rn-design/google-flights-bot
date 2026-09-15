import os
import requests
from datetime import date, timedelta

API_KEY = os.environ["SERPAPI_API_KEY"]

# Test one 7-day trip roughly 3 months from today
outbound = date.today() + timedelta(days=90)
return_date = outbound + timedelta(days=7)

params = {
    "engine": "google_flights",
    "departure_id": "AMS",
    "arrival_id": "HKG",
    "outbound_date": str(outbound),
    "return_date": str(return_date),
    "travel_class": "1",
    "stops": "2",
    "currency": "EUR",
    "hl": "en",
    "gl": "nl",
    "deep_search": "true",
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
print("Route: AMS -> HKG")
print("Outbound:", outbound)
print("Return:", return_date)

if "error" in data:
    print("ERROR:", data["error"])

print("\nTop-level fields:")
print(list(data.keys()))

best_flights = data.get("best_flights", [])
other_flights = data.get("other_flights", [])

print(f"\nBest flights: {len(best_flights)}")
print(f"Other flights: {len(other_flights)}")

for i, flight in enumerate(best_flights[:5], 1):
    print(f"\n--- BEST FLIGHT {i} ---")
    print("Price:", flight.get("price"))
    print("Total duration:", flight.get("total_duration"))
    print("Layovers:", flight.get("layovers"))
    print("Flights:")
    
    for segment in flight.get("flights", []):
        print({
            "departure": segment.get("departure_airport"),
            "arrival": segment.get("arrival_airport"),
            "duration": segment.get("duration"),
            "airline": segment.get("airline"),
            "flight_number": segment.get("flight_number"),
        })

print("\nPrice insights:")
print(data.get("price_insights"))
