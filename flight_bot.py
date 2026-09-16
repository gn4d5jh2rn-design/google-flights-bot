import json
import os
import time
from datetime import date, datetime, timedelta

import requests


API_KEY = os.environ["SERPAPI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

URL = "https://serpapi.com/search.json"

ORIGIN = "AMS"
DESTINATION = "HKG"

ECONOMY_MAX_LAYOVER = 180
BUSINESS_MAX_LAYOVER = 300

STATE_FILE = ".flight_state.json"

# The six-month rolling horizon can touch seven calendar months:
# e.g. 16 Sep -> 16 Mar.
MONTH_OFFSETS = 7

# Hard SerpApi budget:
# 3 Explore
# Economy: 1 detailed + max 3 return-token searches
# Direct:  1 detailed + max 1 return-token search
# Business: 1 detailed + max 1 return-token search
# TOTAL MAX = 11
MAX_SEARCHES_PER_RUN = 11


def price_key(item):
    price = item.get("price")
    if isinstance(price, (int, float)):
        return price
    return float("inf")


def serpapi(params):
    params = params.copy()
    params["api_key"] = API_KEY

    for attempt in range(3):
        try:
            response = requests.get(URL, params=params, timeout=120)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            if attempt == 2:
                raise
            print(f"Connection failed: {exc}")
            print("Retrying in 10 seconds...")
            time.sleep(10)


def get_account_status():
    response = requests.get(
        "https://serpapi.com/account.json",
        params={"api_key": API_KEY},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def add_months(value, months):
    month_index = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(month_index, 12)
    return year, month_zero + 1


def horizon_month_keys(today):
    keys = []
    for offset in range(MONTH_OFFSETS):
        year, month = add_months(today, offset)
        keys.append(f"{year:04d}-{month:02d}")
    return keys


def load_state():
    empty = {
        "route": f"{ORIGIN}-{DESTINATION}",
        "next_month_offset": 0,
        "scanned_months": [],
        "economy": [],
        "direct": [],
        "business": [],
    }

    if not os.path.exists(STATE_FILE):
        return empty

    try:
        with open(STATE_FILE, "r") as handle:
            state = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return empty

    # Never mix results from an old route if ORIGIN/DESTINATION changes.
    if state.get("route") != f"{ORIGIN}-{DESTINATION}":
        return empty

    for key in ("scanned_months", "economy", "direct", "business"):
        state.setdefault(key, [])

    state.setdefault("next_month_offset", 0)
    return state


def save_state(state):
    state["route"] = f"{ORIGIN}-{DESTINATION}"

    with open(STATE_FILE, "w") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)


def explore(travel_class, stops, month):
    return serpapi({
        "engine": "google_travel_explore",
        "departure_id": ORIGIN,
        "arrival_id": DESTINATION,
        "month": str(month),
        "travel_duration": "2",
        "travel_class": str(travel_class),
        "adults": "1",
        "stops": str(stops),
        "currency": "EUR",
        "hl": "en",
        "gl": "nl",
    })


def valid_layover(flight, max_minutes):
    layovers = flight.get("layovers") or []

    if len(layovers) > 1:
        return False

    return all(
        layover.get("duration", 9999) <= max_minutes
        for layover in layovers
    )


def layover_text(flight):
    layovers = flight.get("layovers") or []

    if not layovers:
        return "Direct"

    layover = layovers[0]
    minutes = layover.get("duration")
    airport = layover.get("id", "?")

    if minutes is None:
        return f"{airport} — unknown duration"

    hours, mins = divmod(minutes, 60)

    if hours and mins:
        duration = f"{hours}h {mins}m"
    elif hours:
        duration = f"{hours}h"
    else:
        duration = f"{mins}m"

    return f"{airport} — {duration}"


def airlines_text(flight):
    airlines = []

    for segment in flight.get("flights", []):
        airline = segment.get("airline")
        if airline and airline not in airlines:
            airlines.append(airline)

    return ", ".join(airlines) or "Unknown airline"


def detailed_search(
    outbound_date,
    return_date,
    travel_class,
    stops,
):
    return serpapi({
        "engine": "google_flights",
        "departure_id": ORIGIN,
        "arrival_id": DESTINATION,
        "outbound_date": outbound_date,
        "return_date": return_date,
        "travel_class": str(travel_class),
        "stops": str(stops),
        "adults": "1",
        "currency": "EUR",
        "hl": "en",
        "gl": "nl",
        "deep_search": "true",
    })


def verify_outbound(
    base_data,
    outbound_date,
    return_date,
    travel_class,
    stops,
    max_layover,
    token_limit,
):
    outbounds = (
        base_data.get("best_flights", [])
        + base_data.get("other_flights", [])
    )

    valid_outbounds = [
        flight
        for flight in outbounds
        if valid_layover(flight, max_layover)
        and flight.get("departure_token")
    ]

    valid_outbounds.sort(key=price_key)

    complete_trips = []

    for outbound in valid_outbounds[:token_limit]:
        params = {
            "engine": "google_flights",
            "departure_id": ORIGIN,
            "arrival_id": DESTINATION,
            "outbound_date": outbound_date,
            "return_date": return_date,
            "travel_class": str(travel_class),
            "stops": str(stops),
            "adults": "1",
            "currency": "EUR",
            "hl": "en",
            "gl": "nl",
            "deep_search": "true",
            "departure_token": outbound["departure_token"],
        }

        return_data = serpapi(params)

        returns = (
            return_data.get("best_flights", [])
            + return_data.get("other_flights", [])
        )

        valid_returns = [
            flight
            for flight in returns
            if valid_layover(flight, max_layover)
        ]

        valid_returns.sort(key=price_key)

        if not valid_returns:
            continue

        return_flight = valid_returns[0]

        complete_trips.append({
            "price": return_flight.get("price"),
            "outbound_airlines": airlines_text(outbound),
            "return_airlines": airlines_text(return_flight),
            "outbound_layover": layover_text(outbound),
            "return_layover": layover_text(return_flight),
            "outbound_date": outbound_date,
            "return_date": return_date,
            "verified_at": datetime.utcnow().isoformat(timespec="seconds"),
        })

    complete_trips.sort(key=price_key)
    return complete_trips


def find_economy(explore_data):
    outbound_date = explore_data["start_date"]
    return_date = explore_data["end_date"]

    base = detailed_search(
        outbound_date,
        return_date,
        travel_class=1,
        stops=2,
    )

    # Three Economy return verifications:
    # 1 Explore + 1 detailed + 3 tokens = max 5 Economy searches.
    trips = verify_outbound(
        base,
        outbound_date,
        return_date,
        travel_class=1,
        stops=2,
        max_layover=ECONOMY_MAX_LAYOVER,
        token_limit=3,
    )

    return trips


def find_direct(explore_data):
    outbound_date = explore_data["start_date"]
    return_date = explore_data["end_date"]

    base = detailed_search(
        outbound_date,
        return_date,
        travel_class=1,
        stops=1,
    )

    trips = verify_outbound(
        base,
        outbound_date,
        return_date,
        travel_class=1,
        stops=1,
        max_layover=0,
        token_limit=1,
    )

    return trips[0] if trips else None


def find_business(explore_data):
    outbound_date = explore_data["start_date"]
    return_date = explore_data["end_date"]

    base = detailed_search(
        outbound_date,
        return_date,
        travel_class=3,
        stops=2,
    )

    trips = verify_outbound(
        base,
        outbound_date,
        return_date,
        travel_class=3,
        stops=2,
        max_layover=BUSINESS_MAX_LAYOVER,
        token_limit=1,
    )

    return trips[0] if trips else None


def trip_identity(trip):
    return (
        trip.get("outbound_date"),
        trip.get("return_date"),
        trip.get("outbound_airlines"),
        trip.get("return_airlines"),
        trip.get("outbound_layover"),
        trip.get("return_layover"),
    )


def merge_trips(existing, new_trips):
    merged = {}

    for trip in existing + new_trips:
        if not isinstance(trip, dict):
            continue

        identity = trip_identity(trip)

        # If the same itinerary was seen again, retain the newest observation.
        previous = merged.get(identity)

        if previous is None:
            merged[identity] = trip
            continue

        previous_time = previous.get("verified_at", "")
        new_time = trip.get("verified_at", "")

        if new_time >= previous_time:
            merged[identity] = trip

    return list(merged.values())


def trip_inside_horizon(trip, today):
    try:
        outbound = date.fromisoformat(trip["outbound_date"])
    except (KeyError, TypeError, ValueError):
        return False

    # Google Explore defines the flexible window as the next six months.
    # 183 days is used as the rolling retention boundary.
    horizon_end = today + timedelta(days=183)

    return today <= outbound <= horizon_end


def purge_state(state, today):
    valid_months = set(horizon_month_keys(today))

    state["scanned_months"] = [
        month
        for month in state.get("scanned_months", [])
        if month in valid_months
    ]

    for category in ("economy", "direct", "business"):
        state[category] = [
            trip
            for trip in state.get(category, [])
            if trip_inside_horizon(trip, today)
        ]


def best_economy(state):
    trips = list(state.get("economy", []))
    trips.sort(key=price_key)
    return trips[:3]


def best_direct(state):
    trips = list(state.get("direct", []))
    trips.sort(key=price_key)
    return trips[0] if trips else None


def best_business(state):
    trips = list(state.get("business", []))
    trips.sort(key=price_key)
    return trips[0] if trips else None


def print_trip(number, trip):
    print(f"\n#{number} — €{trip['price']}")
    print(
        f"Dates: {trip['outbound_date']} → "
        f"{trip['return_date']}"
    )
    print(
        f"Outbound: {trip['outbound_airlines']} | "
        f"{trip['outbound_layover']}"
    )
    print(
        f"Return: {trip['return_airlines']} | "
        f"{trip['return_layover']}"
    )


def format_trip(title, trip):
    if not trip:
        return f"{title}\nNo qualifying flight found."

    return (
        f"{title}\n"
        f"💶 €{trip['price']}\n"
        f"📅 {trip['outbound_date']} → {trip['return_date']}\n"
        f"🛫 {ORIGIN} → {DESTINATION}: {trip['outbound_airlines']}\n"
        f"   ↳ {trip['outbound_layover']}\n"
        f"🛬 {DESTINATION} → {ORIGIN}: {trip['return_airlines']}\n"
        f"   ↳ {trip['return_layover']}"
    )


def format_renewal_date(value):
    if not value:
        return "Unknown"

    try:
        clean = str(value)[:10]
        return datetime.strptime(clean, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return str(value)


def build_telegram_message(
    economy,
    direct,
    business,
    searches_used,
    searches_limit,
    renewal_date,
    scanned_months,
    total_months,
    searched_month,
):
    sections = [
        "✈️ FLIGHT TRACKER",
        f"{ORIGIN} ↔ {DESTINATION} | 1-week trips | next 6 months",
        (
            f"📆 Coverage: {scanned_months}/{total_months} calendar months "
            f"scanned | refreshed {searched_month}"
        ),
        "",
        "🟢 ECONOMY — BEST VERIFIED ACROSS SCANNED MONTHS",
    ]

    if economy:
        for number, trip in enumerate(economy, 1):
            sections.append(format_trip(f"#{number}", trip))
    else:
        sections.append("No qualifying Economy flights found.")

    sections.extend([
        "",
        "🔵 BEST ECONOMY DIRECT",
        format_trip("Nonstop", direct),
        "",
        "🟣 CHEAPEST BUSINESS",
        format_trip("Business", business),
        "",
        (
            f"🔎 SerpApi: {searches_used}/{searches_limit} "
            f"searches used"
        ),
        f"♻️ Resets: {format_renewal_date(renewal_date)}",
    ])

    return "\n\n".join(sections)


def send_telegram(message):
    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    response = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "disable_web_page_preview": True,
        },
        timeout=30,
    )

    response.raise_for_status()
    return response.json()


def main():
    account = get_account_status()

    searches_used = account.get("this_month_usage", 0)
    searches_limit = account.get("searches_per_month", 250)
    searches_left = account.get("plan_searches_left", 0)
    renewal_date = account.get("plan_renewal_date")

    print(
        f"SerpApi: {searches_used}/{searches_limit} searches used"
    )
    print(f"Remaining: {searches_left}")
    print(f"Renewal: {renewal_date}")

    # Full run remains capped at 11 searches.
    # Keep the same additional 2-search safety buffer.
    if searches_left < MAX_SEARCHES_PER_RUN + 2:
        print(
            "Not enough SerpApi searches remaining "
            "for a complete run. Skipping."
        )
        return

    today = date.today()
    state = load_state()
    purge_state(state, today)

    month_offset = int(
        state.get("next_month_offset", 0)
    ) % MONTH_OFFSETS

    target_year, target_month = add_months(today, month_offset)
    target_month_key = f"{target_year:04d}-{target_month:02d}"

    print(f"{ORIGIN} ↔ {DESTINATION} flight search")
    print("======================")
    print(
        f"Scanning month: {target_month_key} "
        f"(rotation {month_offset + 1}/{MONTH_OFFSETS})"
    )

    # 3 monthly flexible-date discovery searches.
    economy_explore = explore(
        travel_class=1,
        stops=2,
        month=target_month,
    )

    direct_explore = explore(
        travel_class=1,
        stops=1,
        month=target_month,
    )

    business_explore = explore(
        travel_class=3,
        stops=2,
        month=target_month,
    )

    # Economy: 1 detailed + up to 3 token searches.
    economy_new = find_economy(economy_explore)

    # Direct: 1 detailed + up to 1 token search.
    direct_new = find_direct(direct_explore)

    # Business: 1 detailed + up to 1 token search.
    business_new = find_business(business_explore)

    state["economy"] = merge_trips(
        state.get("economy", []),
        economy_new,
    )

    state["direct"] = merge_trips(
        state.get("direct", []),
        [direct_new] if direct_new else [],
    )

    state["business"] = merge_trips(
        state.get("business", []),
        [business_new] if business_new else [],
    )

    if target_month_key not in state["scanned_months"]:
        state["scanned_months"].append(target_month_key)

    state["next_month_offset"] = (
        month_offset + 1
    ) % MONTH_OFFSETS

    purge_state(state, today)
    save_state(state)

    economy = best_economy(state)
    direct = best_direct(state)
    business = best_business(state)

    print("\n======================")
    print("ECONOMY — BEST VERIFIED ACROSS SCANNED MONTHS")
    print("======================")

    for number, trip in enumerate(economy, 1):
        print_trip(number, trip)

    print("\n======================")
    print("BEST ECONOMY DIRECT")
    print("======================")

    if direct:
        print_trip(1, direct)
    else:
        print("No direct flight found.")

    print("\n======================")
    print("CHEAPEST BUSINESS")
    print("======================")

    if business:
        print_trip(1, business)
    else:
        print("No qualifying Business flight found.")

    print(
        f"\nMaximum SerpApi searches this run: "
        f"{MAX_SEARCHES_PER_RUN}"
    )

    final_account = get_account_status()

    final_used = final_account.get(
        "this_month_usage",
        searches_used,
    )

    final_limit = final_account.get(
        "searches_per_month",
        searches_limit,
    )

    final_renewal = final_account.get(
        "plan_renewal_date",
        renewal_date,
    )

    valid_months = horizon_month_keys(today)

    scanned_count = len(
        set(state["scanned_months"]) & set(valid_months)
    )

    message = build_telegram_message(
        economy=economy,
        direct=direct,
        business=business,
        searches_used=final_used,
        searches_limit=final_limit,
        renewal_date=final_renewal,
        scanned_months=scanned_count,
        total_months=len(valid_months),
        searched_month=target_month_key,
    )

    print("\nTelegram message:")
    print("=================")
    print(message)

    send_telegram(message)
    print("\nTelegram report sent successfully.")


if __name__ == "__main__":
    main()
