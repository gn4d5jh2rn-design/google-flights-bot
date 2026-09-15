import os
import time
import requests

API_KEY = os.environ["SERPAPI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

URL = "https://serpapi.com/search.json"

ORIGIN = "AMS"
DESTINATION = "HKG"

ECONOMY_MAX_LAYOVER = 180
BUSINESS_MAX_LAYOVER = 300


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

def get_account_status():
    response = requests.get(
        "https://serpapi.com/account.json",
        params={"api_key": API_KEY},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()

def explore(travel_class, stops):
    return serpapi({
        "engine": "google_travel_explore",
        "departure_id": ORIGIN,
        "arrival_id": DESTINATION,
        "month": "0",
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

    valid_outbounds.sort(
        key=lambda x: x.get("price", 999999)
    )

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

        valid_returns.sort(
            key=lambda x: x.get("price", 999999)
        )

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
        })

    complete_trips.sort(
        key=lambda x: x.get("price", 999999)
    )

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

    # Verify three outbound candidates.
    # Search budget is reserved for strict Direct verification.
    trips = verify_outbound(
        base,
        outbound_date,
        return_date,
        travel_class=1,
        stops=2,
        max_layover=ECONOMY_MAX_LAYOVER,
        token_limit=3,
    )

    return trips[:4]


def find_business(explore_data):
    outbound_date = explore_data["start_date"]
    return_date = explore_data["end_date"]

    base = detailed_search(
        outbound_date,
        return_date,
        travel_class=3,
        stops=2,
    )

    # Verify the cheapest qualifying Business outbound candidate.
    trips = verify_outbound(
        base,
        outbound_date,
        return_date,
        travel_class=3,
        stops=2,
        max_layover=BUSINESS_MAX_LAYOVER,
        token_limit=1,
    )

    return trips[:1]


def find_direct(explore_data):
    outbound_date = explore_data["start_date"]
    return_date = explore_data["end_date"]

    # Detailed nonstop search.
    base = detailed_search(
        outbound_date,
        return_date,
        travel_class=1,
        stops=1,
    )

    # Verify the cheapest outbound candidate through its departure token.
    # With stops=1, both the selected outbound and returned itinerary
    # must be nonstop.
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

    # SerpApi normally returns YYYY-MM-DD or an ISO timestamp.
    try:
        from datetime import datetime
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
):
    sections = [
        "✈️ FLIGHT TRACKER",
        f"{ORIGIN} ↔ {DESTINATION} | 1-week trips | next 6 months",
        "",
        "🟢 ECONOMY — BEST 4",
    ]

    if economy:
        for number, trip in enumerate(economy, 1):
            sections.append(
                format_trip(f"#{number}", trip)
            )
    else:
        sections.append("No qualifying Economy flights found.")

    sections.extend([
        "",
        "🔵 BEST ECONOMY DIRECT",
        format_trip("Nonstop", direct),
        "",
        "🟣 CHEAPEST BUSINESS",
        format_trip(
            "Business",
            business[0] if business else None,
        ),
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
        f"https://api.telegram.org/"
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

    # A full run currently needs at most 11 searches.
    # Keep an additional 2-search safety buffer.
    if searches_left < 13:
        print(
            "Not enough SerpApi searches remaining "
            "for a complete run. Skipping."
        )
        return
    
    print(f"{ORIGIN} ↔ {DESTINATION} flight search")
    print("======================")

    # 3 flexible-date discovery searches
    economy_explore = explore(
        travel_class=1,
        stops=2,
    )

    direct_explore = explore(
        travel_class=1,
        stops=1,
    )

    business_explore = explore(
        travel_class=3,
        stops=2,
    )

    # Economy:
    # 1 detailed search + up to 3 token searches
    economy = find_economy(economy_explore)

    # Direct:
    # 1 detailed nonstop search + up to 1 token search
    direct = find_direct(direct_explore)

    # Business:
    # 1 detailed search + up to 1 token search
    business = find_business(business_explore)

    print("\n======================")
    print("ECONOMY — TOP 4")
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
        print_trip(1, business[0])
    else:
        print("No qualifying Business flight found.")

    print("\nMaximum SerpApi searches this run: 11")

    # Refresh account status after the searches so the Telegram
    # message shows the actual quota remaining after this run.
    final_account = get_account_status()

    final_used = final_account.get("this_month_usage", searches_used)
    final_limit = final_account.get("searches_per_month", searches_limit)
    final_renewal = final_account.get(
        "plan_renewal_date",
        renewal_date,
    )

    message = build_telegram_message(
        economy=economy,
        direct=direct,
        business=business,
        searches_used=final_used,
        searches_limit=final_limit,
        renewal_date=final_renewal,
    )

    print("\nTelegram message:")
    print("=================")
    print(message)

    send_telegram(message)
    print("\nTelegram report sent successfully.")


if __name__ == "__main__":
    main()
