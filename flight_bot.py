import os
import time
import requests

API_KEY = os.environ["SERPAPI_API_KEY"]
URL = "https://serpapi.com/search.json"


def serpapi(params):
    params = params.copy()
    params["api_key"] = API_KEY

    for attempt in range(3):
        try:
            response = requests.get(URL, params=params, timeout=120)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            if attempt == 2:
                raise
            print(f"Connection failed: {e}")
            print("Retrying in 10 seconds...")
            time.sleep(10)


def explore(travel_class, stops):
    return serpapi({
        "engine": "google_travel_explore",
        "departure_id": "AMS",
        "arrival_id": "HKG",
        "month": "0",
        "travel_duration": "2",
        "travel_class": str(travel_class),
        "adults": "1",
        "stops": str(stops),
        "currency": "EUR",
        "hl": "en",
        "gl": "nl",
    })


def show_candidate(title, data):
    print("\n================================")
    print(title)
    print("================================")

    print(
        "Dates:",
        data.get("start_date"),
        "→",
        data.get("end_date"),
    )

    flights = data.get("flights", [])

    if not flights:
        print("No flights found.")
        return

    for flight in flights:
        print(
            f"€{flight.get('price')} | "
            f"{flight.get('airline')} | "
            f"{flight.get('number_of_stops')} stop(s)"
        )


print("Searching AMS ↔ HKG...\n")

economy = explore(
    travel_class=1,
    stops=2,
)

direct = explore(
    travel_class=1,
    stops=1,
)

business = explore(
    travel_class=3,
    stops=2,
)

show_candidate(
    "ECONOMY — MAX 1 STOP",
    economy,
)

show_candidate(
    "ECONOMY — DIRECT",
    direct,
)

show_candidate(
    "BUSINESS — MAX 1 STOP",
    business,
)

print("\nExplore API searches used: 3")
