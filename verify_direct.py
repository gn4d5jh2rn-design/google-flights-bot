import os
import requests

API_KEY = os.environ["SERPAPI_API_KEY"]
URL = "https://serpapi.com/search.json"

OUTBOUND_DATE = "2026-09-26"
RETURN_DATE = "2026-10-04"
MAX_LAYOVER = 180


def valid(flight):
    layovers = flight.get("layovers") or []

    if len(layovers) > 1:
        return False

    if any(x.get("duration", 9999) > MAX_LAYOVER for x in layovers):
        return False

    return True


def describe_layover(flight):
    layovers = flight.get("layovers") or []

    if not layovers:
        return "Direct"

    layover = layovers[0]

    return (
        f"{layover.get('id', '?')} "
        f"{layover.get('duration', '?')} min"
    )


params = {
    "engine": "google_flights",
    "departure_id": "AMS",
    "arrival_id": "HKG",
    "outbound_date": OUTBOUND_DATE,
    "return_date": RETURN_DATE,
    "travel_class": "1",
    "stops": "1",
    "currency": "EUR",
    "hl": "en",
    "gl": "nl",
    "deep_search": "true",
    "api_key": API_KEY,
}

print("Searching Direct Economy detailed results...")

data = requests.get(
    URL,
    params=params,
    timeout=120,
).json()

outbounds = (
    data.get("best_flights", [])
    + data.get("other_flights", [])
)

valid_outbounds = [
    f for f in outbounds
    if valid(f) and f.get("departure_token")
]

valid_outbounds.sort(
    key=lambda x: x.get("price", 999999)
)

print(
    f"Found {len(valid_outbounds)} valid outbound candidates "
    f"with layovers <= {MAX_LAYOVER} min."
)

complete_trips = []

# Follow the first 4 valid outbound candidates.
for number, outbound in enumerate(valid_outbounds[:2], 1):

    airlines = []

    for segment in outbound.get("flights", []):
        airline = segment.get("airline")

        if airline and airline not in airlines:
            airlines.append(airline)

    print("\n--------------------------------")
    print(f"OUTBOUND CANDIDATE {number}")
    print("--------------------------------")
    print("Starting price:", f"€{outbound.get('price')}")
    print("Airline(s):", ", ".join(airlines))
    print("Outbound:", describe_layover(outbound))

    return_params = params.copy()
    return_params["departure_token"] = outbound["departure_token"]

    return_data = requests.get(
        URL,
        params=return_params,
        timeout=120,
    ).json()

    returns = (
        return_data.get("best_flights", [])
        + return_data.get("other_flights", [])
    )

    valid_returns = [
        f for f in returns
        if valid(f)
    ]

    valid_returns.sort(
        key=lambda x: x.get("price", 999999)
    )

    if not valid_returns:
        print("No valid return <= 180 min layover.")
        continue

    best_return = valid_returns[0]

    return_airlines = []

    for segment in best_return.get("flights", []):
        airline = segment.get("airline")

        if airline and airline not in return_airlines:
            return_airlines.append(airline)

    trip = {
        "price": best_return.get("price"),
        "outbound_airlines": ", ".join(airlines),
        "return_airlines": ", ".join(return_airlines),
        "outbound_layover": describe_layover(outbound),
        "return_layover": describe_layover(best_return),
    }

    complete_trips.append(trip)

    print("Complete round-trip:", f"€{trip['price']}")
    print("Return airline(s):", trip["return_airlines"])
    print("Return:", trip["return_layover"])


complete_trips.sort(
    key=lambda x: x["price"]
)

print("\n================================")
print("FINAL DIRECT ECONOMY RANKING")
print("================================")

for number, trip in enumerate(complete_trips, 1):

    print(f"\n#{number} — €{trip['price']}")

    print(
        "Outbound:",
        trip["outbound_airlines"],
        "|",
        trip["outbound_layover"],
    )

    print(
        "Return:",
        trip["return_airlines"],
        "|",
        trip["return_layover"],
    )


print(
    "\nAPI searches used:",
    1 + min(2, len(valid_outbounds))
)
