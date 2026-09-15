import os
import requests
from datetime import date, timedelta

API_KEY = os.environ["SERPAPI_API_KEY"]

outbound = date.today() + timedelta(days=90)
return_date = outbound + timedelta(days=7)

base_params = {
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

# -------------------------
# 1. Search outbound
# -------------------------

response = requests.get(
    "https://serpapi.com/search.json",
    params=base_params,
    timeout=120,
)

response.raise_for_status()
data = response.json()

print("Status:", data.get("search_metadata", {}).get("status"))
print("Route: AMS -> HKG -> AMS")
print("Outbound:", outbound)
print("Return:", return_date)

all_outbounds = (
    data.get("best_flights", [])
    + data.get("other_flights", [])
)

# Keep only flights with <= 1 stop and <= 180 minute layover
valid_outbounds = []

for flight in all_outbounds:
    layovers = flight.get("layovers") or []

    if len(layovers) > 1:
        continue

    if any(layover.get("duration", 9999) > 180 for layover in layovers):
        continue

    if not flight.get("departure_token"):
        continue

    valid_outbounds.append(flight)

valid_outbounds.sort(key=lambda x: x.get("price", 999999))

print(f"\nValid outbound flights: {len(valid_outbounds)}")

if not valid_outbounds:
    raise RuntimeError("No valid outbound flights found")

selected = valid_outbounds[0]

print("\nSELECTED OUTBOUND")
print("Price:", selected.get("price"))
print("Duration:", selected.get("total_duration"))
print("Layovers:", selected.get("layovers"))

for segment in selected.get("flights", []):
    print(
        segment.get("airline"),
        segment.get("flight_number"),
        segment.get("departure_airport", {}).get("id"),
        "->",
        segment.get("arrival_airport", {}).get("id"),
    )

# -------------------------
# 2. Search return flights
# -------------------------

return_params = base_params.copy()
return_params["departure_token"] = selected["departure_token"]

response = requests.get(
    "https://serpapi.com/search.json",
    params=return_params,
    timeout=120,
)

response.raise_for_status()
return_data = response.json()

print("\nRETURN SEARCH STATUS:")
print(return_data.get("search_metadata", {}).get("status"))

return_flights = (
    return_data.get("best_flights", [])
    + return_data.get("other_flights", [])
)

print(f"\nReturn options found: {len(return_flights)}")

for i, flight in enumerate(return_flights[:10], 1):

    print(f"\n--- RETURN OPTION {i} ---")
    print("Price:", flight.get("price"))
    print("Total duration:", flight.get("total_duration"))
    print("Layovers:", flight.get("layovers"))

    for segment in flight.get("flights", []):
        print({
            "departure": segment.get("departure_airport"),
            "arrival": segment.get("arrival_airport"),
            "duration": segment.get("duration"),
            "airline": segment.get("airline"),
            "flight_number": segment.get("flight_number"),
        })
