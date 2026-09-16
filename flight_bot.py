import asyncio
import os
import time
from datetime import date, datetime

import requests
from gflights import Client, SearchFilters


# ============================================================
# CONFIG
# ============================================================

API_KEY = os.environ["SERPAPI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

SERPAPI_URL = "https://serpapi.com/search.json"

ORIGIN = "AMS"
DESTINATION = "HKG"

TRIP_DURATION_DAYS = 6
SEARCH_MONTHS = 6

ECONOMY_MAX_LAYOVER = 180
BUSINESS_MAX_LAYOVER = 300

# Absolute hard cap for one workflow run.
MAX_SERPAPI_SEARCHES = 11

# Keep two searches in reserve before starting a run.
SERPAPI_SAFETY_BUFFER = 2


# ============================================================
# SERPAPI BUDGET
# ============================================================

serpapi_searches_this_run = 0


def serpapi(params):
    global serpapi_searches_this_run

    if serpapi_searches_this_run >= MAX_SERPAPI_SEARCHES:
        raise RuntimeError("SerpApi search budget exhausted.")

    request_params = params.copy()
    request_params["api_key"] = API_KEY

    for attempt in range(3):
        try:
            response = requests.get(
                SERPAPI_URL,
                params=request_params,
                timeout=120,
            )
            response.raise_for_status()

            # Count only a successful SerpApi search.
            serpapi_searches_this_run += 1

            print(
                f"SerpApi search "
                f"{serpapi_searches_this_run}/{MAX_SERPAPI_SEARCHES}"
            )

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


# ============================================================
# FREE GOOGLE FLIGHTS DATE DISCOVERY
# ============================================================

async def discover_dates(travel_class):
    client = Client(
        currency="EUR",
        lang="en",
        country="NL",
    )

    filters = SearchFilters(
        travel_class=travel_class,
        stops="one-stop",
    )

    results = await client.cheapest_dates(
        origin=ORIGIN,
        destination=DESTINATION,
        date=date.today().isoformat(),
        months=SEARCH_MONTHS,
        trip_duration_days=TRIP_DURATION_DAYS,
        filters=filters,
    )

    # gflights normally already orders these by price,
    # but explicitly sort so the bot does not depend on that.
    return sorted(
        results,
        key=lambda item: item.price
        if item.price is not None
        else float("inf"),
    )


async def discover_all_dates():
    economy, business = await asyncio.gather(
        discover_dates("economy"),
        discover_dates("business"),
    )
    return economy, business



# ============================================================
# FREE ITINERARY PRE-FILTER
# ============================================================

def valid_gflights_result(flight, max_layover):
    data = flight.to_dict()

    if data.get("stops", 0) > 1:
        return False

    layovers = data.get("layovers") or []

    if len(layovers) > 1:
        return False

    if not layovers:
        return True

    minutes = layovers[0].get("connection_minutes")

    return (
        isinstance(minutes, (int, float))
        and minutes <= max_layover
    )


async def free_search_one(
    client,
    semaphore,
    candidate,
    filters,
    max_layover,
):
    async with semaphore:
        try:
            results = await client.search(
                origin=ORIGIN,
                destination=DESTINATION,
                date=candidate.departure_date,
                return_date=candidate.return_date,
                filters=filters,
            )
        except Exception as exc:
            print(
                f"FREE search failed "
                f"{candidate.departure_date} → "
                f"{candidate.return_date}: {exc}"
            )
            return None

    valid = [
        flight
        for flight in results
        if valid_gflights_result(
            flight,
            max_layover,
        )
        and isinstance(flight.price, (int, float))
    ]

    if not valid:
        print(
            f"FREE rejected "
            f"{candidate.departure_date} → "
            f"{candidate.return_date} "
            f"(headline €{candidate.price})"
        )
        return None

    best = min(valid, key=lambda flight: flight.price)

    data = best.to_dict()
    layovers = data.get("layovers") or []

    if layovers:
        connection = layovers[0]["connection_minutes"]
        airport = layovers[0].get(
            "arrival_airport",
            "?",
        )
        hours, mins = divmod(
            int(connection),
            60,
        )
        layover = f"{airport} {hours}h{mins:02d}"
    else:
        layover = "Direct"

    print(
        f"FREE valid "
        f"{candidate.departure_date} → "
        f"{candidate.return_date}: "
        f"€{best.price} {best.airline} "
        f"{layover}"
    )

    return {
        "candidate": candidate,
        "free_price": best.price,
        "free_airline": best.airline,
        "free_layover": layover,
    }


async def free_prefilter(
    candidates,
    travel_class,
    max_layover,
):
    """
    Search candidate dates for FREE with gflights.

    Dates are processed by headline-price tier.

    Once the cheapest valid itinerary found is cheaper
    than the next unsearched date tier, more expensive
    headline dates cannot beat it, so free scanning stops.
    """

    client = Client(
        currency="EUR",
        lang="en",
        country="NL",
    )

    filters = SearchFilters(
        travel_class=travel_class,
        stops="one-stop",
    )

    semaphore = asyncio.Semaphore(6)

    by_price = {}

    for candidate in candidates:
        if not isinstance(
            candidate.price,
            (int, float),
        ):
            continue

        by_price.setdefault(
            candidate.price,
            [],
        ).append(candidate)

    price_tiers = sorted(by_price)

    viable = []
    best_valid_price = None

    for index, headline_price in enumerate(
        price_tiers
    ):
        tier = by_price[headline_price]

        print()
        print(
            f"FREE scanning €{headline_price} tier "
            f"({len(tier)} date windows)..."
        )

        results = await asyncio.gather(
            *[
                free_search_one(
                    client=client,
                    semaphore=semaphore,
                    candidate=candidate,
                    filters=filters,
                    max_layover=max_layover,
                )
                for candidate in tier
            ]
        )

        for result in results:
            if result is None:
                continue

            viable.append(result)

            if (
                best_valid_price is None
                or result["free_price"]
                < best_valid_price
            ):
                best_valid_price = result[
                    "free_price"
                ]

        next_price = (
            price_tiers[index + 1]
            if index + 1 < len(price_tiers)
            else None
        )

        if (
            best_valid_price is not None
            and (
                next_price is None
                or next_price >= best_valid_price
            )
        ):
            print(
                f"FREE stopping point reached: "
                f"best valid €{best_valid_price}; "
                f"next headline tier "
                f"{'none' if next_price is None else '€' + str(next_price)}."
            )
            break

    viable.sort(
        key=lambda item: (
            item["free_price"],
            item["candidate"].departure_date,
        )
    )

    print()
    print(
        f"FREE pre-filter produced "
        f"{len(viable)} viable candidates."
    )

    for i, item in enumerate(
        viable[:10],
        1,
    ):
        candidate = item["candidate"]

        print(
            f"  #{i}: "
            f"{candidate.departure_date} → "
            f"{candidate.return_date} | "
            f"€{item['free_price']} | "
            f"{item['free_airline']} | "
            f"{item['free_layover']}"
        )

    return viable


async def free_prefilter_all(
    economy_dates,
    business_dates,
):
    print()
    print("==============================")
    print("FREE PRE-FILTER — ECONOMY")
    print("==============================")

    economy = await free_prefilter(
        candidates=economy_dates,
        travel_class="economy",
        max_layover=ECONOMY_MAX_LAYOVER,
    )

    print()
    print("==============================")
    print("FREE PRE-FILTER — BUSINESS")
    print("==============================")

    business = await free_prefilter(
        candidates=business_dates,
        travel_class="business",
        max_layover=BUSINESS_MAX_LAYOVER,
    )

    return economy, business



# ============================================================
# FLIGHT HELPERS
# ============================================================

def price_key(item):
    price = item.get("price")

    if isinstance(price, (int, float)):
        return price

    return float("inf")


def valid_layover(flight, max_minutes):
    layovers = flight.get("layovers") or []

    # Direct is valid.
    if not layovers:
        return True

    # Maximum one stop.
    if len(layovers) > 1:
        return False

    duration = layovers[0].get("duration")

    return (
        isinstance(duration, (int, float))
        and duration <= max_minutes
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

    hours, mins = divmod(int(minutes), 60)

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


# ============================================================
# SERPAPI EXACT-DATE VERIFICATION
# ============================================================

def detailed_search(
    outbound_date,
    return_date,
    travel_class,
    max_layover,
):
    return serpapi({
        "engine": "google_flights",
        "departure_id": ORIGIN,
        "arrival_id": DESTINATION,
        "outbound_date": outbound_date,
        "return_date": return_date,
        "travel_class": str(travel_class),
        "stops": "2",
        "layover_duration": f"0,{max_layover}",
        "sort_by": "2",
        "adults": "1",
        "currency": "EUR",
        "hl": "en",
        "gl": "nl",
        "deep_search": "true",
    })


def return_search(
    outbound_date,
    return_date,
    travel_class,
    max_layover,
    departure_token,
):
    return serpapi({
        "engine": "google_flights",
        "departure_id": ORIGIN,
        "arrival_id": DESTINATION,
        "outbound_date": outbound_date,
        "return_date": return_date,
        "travel_class": str(travel_class),
        "stops": "2",
        "layover_duration": f"0,{max_layover}",
        "sort_by": "2",
        "adults": "1",
        "currency": "EUR",
        "hl": "en",
        "gl": "nl",
        "deep_search": "true",
        "departure_token": departure_token,
    })


def verify_date(
    candidate_info,
    travel_class,
    max_layover,
):
    candidate = candidate_info["candidate"]

    outbound_date = candidate.departure_date
    return_date = candidate.return_date

    print(
        f"\nSERP verifying "
        f"{outbound_date} → {return_date} | "
        f"FREE €{candidate_info['free_price']} "
        f"{candidate_info['free_airline']}"
    )

    base = detailed_search(
        outbound_date=outbound_date,
        return_date=return_date,
        travel_class=travel_class,
        max_layover=max_layover,
    )

    outbounds = (
        base.get("best_flights", [])
        + base.get("other_flights", [])
    )

    valid_outbounds = [
        flight
        for flight in outbounds
        if flight.get("departure_token")
        and valid_layover(
            flight,
            max_layover,
        )
        and isinstance(
            flight.get("price"),
            (int, float),
        )
    ]

    valid_outbounds.sort(key=price_key)

    if not valid_outbounds:
        print(
            "SerpApi found no valid outbound."
        )
        return None

    # Cheapest qualifying outbound. Its displayed price
    # is Google's starting round-trip price for selecting
    # this outbound.
    outbound = valid_outbounds[0]

    data = return_search(
        outbound_date=outbound_date,
        return_date=return_date,
        travel_class=travel_class,
        max_layover=max_layover,
        departure_token=outbound[
            "departure_token"
        ],
    )

    returns = (
        data.get("best_flights", [])
        + data.get("other_flights", [])
    )

    valid_returns = [
        flight
        for flight in returns
        if valid_layover(
            flight,
            max_layover,
        )
        and isinstance(
            flight.get("price"),
            (int, float),
        )
    ]

    valid_returns.sort(key=price_key)

    if not valid_returns:
        print(
            "SerpApi found no valid return."
        )
        return None

    return_flight = valid_returns[0]

    trip = {
        "price": return_flight["price"],
        "outbound_date": outbound_date,
        "return_date": return_date,
        "outbound_airlines": airlines_text(
            outbound
        ),
        "return_airlines": airlines_text(
            return_flight
        ),
        "outbound_layover": layover_text(
            outbound
        ),
        "return_layover": layover_text(
            return_flight
        ),
    }

    print(
        f"VERIFIED: €{trip['price']} | "
        f"{trip['outbound_airlines']} | "
        f"{trip['outbound_layover']} / "
        f"{trip['return_layover']}"
    )

    return trip


# ============================================================
# FIND CHEAPEST VALID ROUND TRIP
# ============================================================

def find_best(
    candidates,
    travel_class,
    max_layover,
    reserved_searches=0,
):
    """
    Candidates are ALREADY ranked using free gflights
    itinerary searches.

    SerpApi is used only for final round-trip validation.
    Each candidate costs exactly two searches.
    """

    best = None

    for candidate_info in candidates:
        searches_available = (
            MAX_SERPAPI_SEARCHES
            - serpapi_searches_this_run
            - reserved_searches
        )

        if searches_available < 2:
            print(
                "Protected SerpApi budget reached."
            )
            break

        # If we already have an authoritative verified
        # price and the next FREE itinerary is not cheaper,
        # there is no reason to spend another paid search.
        if (
            best is not None
            and candidate_info["free_price"]
            >= best["price"]
        ):
            print(
                f"Stopping SerpApi verification: "
                f"next FREE candidate "
                f"€{candidate_info['free_price']} "
                f"cannot beat verified "
                f"€{best['price']}."
            )
            break

        trip = verify_date(
            candidate_info=candidate_info,
            travel_class=travel_class,
            max_layover=max_layover,
        )

        if (
            trip is not None
            and (
                best is None
                or trip["price"] < best["price"]
            )
        ):
            best = trip

            print(
                f"New VERIFIED best: "
                f"€{best['price']} "
                f"{best['outbound_date']} → "
                f"{best['return_date']}"
            )

    return best


# ============================================================
# TELEGRAM
# ============================================================

def format_trip(title, trip):
    if not trip:
        return (
            f"{title}\n"
            "No qualifying flight could be verified "
            "within this run's search budget."
        )

    return (
        f"{title}\n"
        f"💶 €{trip['price']}\n"
        f"📅 {trip['outbound_date']} → "
        f"{trip['return_date']}\n"
        f"🛫 {ORIGIN} → {DESTINATION}: "
        f"{trip['outbound_airlines']}\n"
        f"   ↳ {trip['outbound_layover']}\n"
        f"🛬 {DESTINATION} → {ORIGIN}: "
        f"{trip['return_airlines']}\n"
        f"   ↳ {trip['return_layover']}"
    )


def format_renewal_date(value):
    if not value:
        return "Unknown"

    try:
        clean = str(value)[:10]
        return datetime.strptime(
            clean,
            "%Y-%m-%d",
        ).strftime("%d/%m/%Y")
    except ValueError:
        return str(value)


def build_telegram_message(
    economy,
    business,
    searches_used,
    searches_limit,
    renewal_date,
    economy_windows,
    business_windows,
):
    sections = [
        "✈️ FLIGHT TRACKER",
        (
            f"{ORIGIN} ↔ {DESTINATION} | "
            f"7-day trips | "
            f"next {SEARCH_MONTHS} months"
        ),
        (
            f"📆 Free scan: "
            f"{economy_windows} Economy + "
            f"{business_windows} Business date windows"
        ),
        "",
        "🟢 CHEAPEST ECONOMY",
        format_trip("Economy", economy),
        "",
        (
            f"Rule: direct or max 1 stop | "
            f"connection ≤ {ECONOMY_MAX_LAYOVER // 60}h"
        ),
        "",
        "🟣 CHEAPEST BUSINESS",
        format_trip("Business", business),
        "",
        (
            f"Rule: direct or max 1 stop | "
            f"connection ≤ {BUSINESS_MAX_LAYOVER // 60}h"
        ),
        "",
        (
            f"🔎 SerpApi: {searches_used}/"
            f"{searches_limit} searches used"
        ),
        (
            f"🧮 This run: "
            f"{serpapi_searches_this_run}/"
            f"{MAX_SERPAPI_SEARCHES}"
        ),
        f"♻️ Resets: {format_renewal_date(renewal_date)}",
    ]

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


# ============================================================
# MAIN
# ============================================================

def main():
    print(f"{ORIGIN} ↔ {DESTINATION} flight search")
    print("================================")

    account = get_account_status()

    searches_used = account.get("this_month_usage", 0)
    searches_limit = account.get("searches_per_month", 250)
    searches_left = account.get("plan_searches_left", 0)
    renewal_date = account.get("plan_renewal_date")

    print(
        f"SerpApi before run: "
        f"{searches_used}/{searches_limit}"
    )
    print(f"Remaining: {searches_left}")

    if (
        searches_left
        < MAX_SERPAPI_SEARCHES + SERPAPI_SAFETY_BUFFER
    ):
        print(
            "Not enough SerpApi searches remaining "
            "for a complete run. Skipping."
        )
        return

    print("\nFREE six-month date discovery...")

    economy_dates, business_dates = asyncio.run(
        discover_all_dates()
    )

    print(
        f"Economy windows discovered: "
        f"{len(economy_dates)}"
    )
    print(
        f"Business windows discovered: "
        f"{len(business_dates)}"
    )

    if economy_dates:
        economy_chronological = sorted(
            economy_dates,
            key=lambda x: x.departure_date,
        )
        print(
            "Economy coverage: "
            f"{economy_chronological[0].departure_date} → "
            f"{economy_chronological[-1].departure_date}"
        )

    if business_dates:
        business_chronological = sorted(
            business_dates,
            key=lambda x: x.departure_date,
        )
        print(
            "Business coverage: "
            f"{business_chronological[0].departure_date} → "
            f"{business_chronological[-1].departure_date}"
        )

    if economy_dates:
        print(
            f"Cheapest Economy headline: "
            f"€{economy_dates[0].price}"
        )

    if business_dates:
        print(
            f"Cheapest Business headline: "
            f"€{business_dates[0].price}"
        )

    # Reserve two searches so Business always gets at least
    # one exact-date search + one return-token verification.
    print("\nRunning FREE itinerary pre-filter...")

    economy_candidates, business_candidates = asyncio.run(
        free_prefilter_all(
            economy_dates=economy_dates,
            business_dates=business_dates,
        )
    )

    print("\n==============================")
    print("VERIFYING ECONOMY")
    print("==============================")

    economy = find_best(
        candidates=economy_dates,
        travel_class=1,
        max_layover=ECONOMY_MAX_LAYOVER,
        reserved_searches=4,
    )

    print("\n==============================")
    print("VERIFYING BUSINESS")
    print("==============================")

    business = find_best(
        candidates=business_dates,
        travel_class=3,
        max_layover=BUSINESS_MAX_LAYOVER,
        reserved_searches=0,
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

    message = build_telegram_message(
        economy=economy,
        business=business,
        searches_used=final_used,
        searches_limit=final_limit,
        renewal_date=final_renewal,
        economy_windows=len(economy_dates),
        business_windows=len(business_dates),
    )

    print("\n==============================")
    print("TELEGRAM MESSAGE")
    print("==============================")
    print(message)

    send_telegram(message)

    print("\nTelegram report sent successfully.")


if __name__ == "__main__":
    main()
