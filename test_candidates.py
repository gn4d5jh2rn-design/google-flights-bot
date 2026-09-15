import os
import requests
from datetime import date

API_KEY = os.environ["SERPAPI_API_KEY"]

outbound = date(2026, 11, 12)
return_date = date(2026, 11, 18)

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

def valid(flight):
    layovers = flight.get("layovers") or []

    if len(layovers) > 1:
        return False

    if any(x.get("duration", 9999) > 180 for x in layovers):
        return False

    return True


# Initial outbound search
data = requests.get(
    "https://serpapi.com/search.json",
    params=params,
    timeout=120,
).json()

outbounds = data.get("best_flights", []) + data.get("other_flights", [])

outbounds = [
    f for f in outbounds
    if valid(f) and f.get("departure_token")
]

outbounds.sort(key=lambda x: x.get("price", 999999))

print("Valid outbound candidates:", len(outbounds))

complete_trips = []

# Test only first 3 candidates for now
for n, outbound_flight in enumerate(outbounds[:3], 1):

    print("\n==============================")
    print("OUTBOUND CANDIDATE", n)
    print("==============================")

    print("Starting price: €" + str(outbound_flight.get("price")))
    print("Layovers:", outbound_flight.get("layovers"))

    airlines = []
    for segment in outbound_flight.get("flights", []):
        airline = segment.get("airline")
        if airline and airline not in airlines:
            airlines.append(airline)

    print("Airline(s):", ", ".join(airlines))

    return_params = params.copy()
    return_params["departure_token"] = outbound_flight["departure_token"]

    return_data = requests.get(
        "https://serpapi.com/search.json",
        params=return_params,
        timeout=120,
    ).json()

    returns = (
        return_data.get("best_flights", [])
        + return_data.get("other_flights", [])
    )

    valid_returns = [f for f in returns if valid(f)]
    valid_returns.sort(key=lambda x: x.get("price", 999999))

    if not valid_returns:
        print("No valid return.")
        continue

    best_return = valid_returns[0]

    print("Best valid round-trip price: €" + str(best_return.get("price")))
    print("Return layovers:", best_return.get("layovers"))

    complete_trips.append({
        "price": best_return.get("price"),
        "airlines": ", ".join(airlines),
        "outbound_layovers": outbound_flight.get("layovers"),
        "return_layovers": best_return.get("layovers"),
    })


complete_trips.sort(key=lambda x: x["price"])

print("\n==============================")
print("RANKING")
print("==============================")

for i, trip in enumerate(complete_trips, 1):
    print(
        f"#{i} €{trip['price']} - {trip['airlines']} "
        f"- outbound {trip['outbound_layovers']} "
        f"- return {trip['return_layovers']}"
    )

print("\nAPI searches used by this script:", 1 + min(3, len(outbounds)))
