import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText

# ============================
# CONFIGURACIÓN
# ============================

ORIGINS = ["BCN", "GRO"]

EUROPE_CODES = {
    "AL","AD","AT","BY","BE","BA","BG","HR","CY","CZ","DK","EE","FI","FR",
    "DE","GR","HU","IS","IE","IT","LV","LI","LT","LU","MT","MD","MC","ME",
    "NL","MK","NO","PL","PT","RO","RU","SM","RS","SK","SI","ES","SE","CH",
    "UA","GB","VA"
}

EUROPE_PRICE = 50
WORLD_PRICE = 150

WEEKEND_GAP = 14
NUM_WEEKENDS = 12

GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_PASSWORD = os.environ.get("GMAIL_PASSWORD")

HEADERS = {
    "User-Agent": "Mozilla/5.0",
}

# ============================
# FINES DE SEMANA
# ============================

def get_weekends(start_date):
    weekends = []
    current = start_date
    for _ in range(NUM_WEEKENDS):
        friday = current + timedelta((4 - current.weekday()) % 7)
        monday = friday + timedelta(days=3)
        weekends.append((friday, monday))
        current = friday + timedelta(days=WEEKEND_GAP)
    return weekends

# ============================
# FILTRO
# ============================

def normalize_price(p):
    """Convierte precio de dict o string a float."""
    try:
        if isinstance(p, dict):
            return float(p.get("amount", 9999))
        return float(str(p).replace("€", "").replace(",", "."))
    except:
        return 9999.0


def filter_flights(flights):
    filtered = []
    for f in flights:
        price = normalize_price(f.get("price", 9999))
        f["price"] = price  # almacenamos el valor limpio para el email
        country = f.get("country", "")

        if country in EUROPE_CODES or country == "MA":
            if price <= EUROPE_PRICE:
                filtered.append(f)
        else:
            if price <= WORLD_PRICE:
                filtered.append(f)

    return filtered

# ============================
# SCRAPERS
# ============================

# ----- RYANAIR -----

def fetch_ryanair(origin, dep, ret):
    url = (
        "https://www.ryanair.com/api/farfnd/3/oneWayFares"
        f"?departureAirportIataCode={origin}"
        f"&language=en&limit=1000&market=en-gb&offset=0&page=0"
        f"&outboundDepartureDateFrom={dep.strftime('%Y-%m-%d')}"
        f"&outboundDepartureDateTo={dep.strftime('%Y-%m-%d')}"
    )

    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        data = r.json()
    except:
        return []

    flights = []

    for item in data.get("fares", []):
        flights.append({
            "origin": origin,
            "destination": item.get("arrivalAirport", {}).get("iataCode", "UNK"),
            "dep": dep.strftime("%Y-%m-%d"),
            "ret": ret.strftime("%Y-%m-%d"),
            "price": item.get("outbound", {}).get("price", 999),
            "country": item.get("arrivalAirport", {}).get("countryCode", "UNK"),
            "link": "https://www.ryanair.com/",
        })

    return flights

# ----- VUELING -----

def fetch_vueling(origin, dep, ret):
    url = (
        "https://www.vueling.com/en/booking/availability"
        f"?DepartureStation={origin}"
        f"&ArrivalStation=ANY"
        f"&DepartureDate={dep.strftime('%Y-%m-%d')}"
    )

    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
    except:
        return []

    flights = []

    rows = soup.select(".flight-info")

    for row in rows:
        try:
            dest = row.select_one(".destination").get_text(strip=True)
            price = row.select_one(".price").get_text(strip=True).replace("€", "")
            price = float(price)

            flights.append({
                "origin": origin,
                "destination": dest,
                "dep": dep.strftime("%Y-%m-%d"),
                "ret": ret.strftime("%Y-%m-%d"),
                "price": price,
                "country": "ES",  # Vueling mostly EU; no easy country API → fallback
                "link": "https://www.vueling.com/",
            })
        except:
            continue

    return flights

# ----- EASYJET -----

def fetch_easyjet(origin, dep, ret):
    url = (
        f"https://www.easyjet.com/en/cheap-flights/{origin.lower()}"
        f"?dates={dep.strftime('%Y-%m-%d')}"
    )

    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
    except:
        return []

    flights = []

    items = soup.select(".tile--fare")

    for item in items:
        try:
            dest = item.select_one(".fare-destination").get_text(strip=True)
            price = item.select_one(".price").get_text(strip=True)
            price = float(price.replace("€", "").replace(",", ""))

            flights.append({
                "origin": origin,
                "destination": dest,
                "dep": dep.strftime("%Y-%m-%d"),
                "ret": ret.strftime("%Y-%m-%d"),
                "price": price,
                "country": "EU",
                "link": "https://www.easyjet.com/",
            })
        except:
            continue

    return flights

# ----- WIZZ AIR -----

def fetch_wizz(origin, dep, ret):
    url = (
        "https://be.wizzair.com/5.2.1/Api/search/search"
    )

    payload = {
        "flightList": [
            {
                "departureStation": origin,
                "arrivalStation": "",
                "departureDate": dep.strftime("%Y-%m-%d")
            }
        ],
        "adultCount": 1
    }

    try:
        r = requests.post(url, json=payload, headers=HEADERS, timeout=20)
        data = r.json()
    except:
        return []

    flights = []

    for item in data.get("outboundFlights", []):
        flights.append({
            "origin": origin,
            "destination": item.get("arrivalStation", "UNK"),
            "dep": dep.strftime("%Y-%m-%d"),
            "ret": ret.strftime("%Y-%m-%d"),
            "price": item.get("price", 999),
            "country": item.get("isDomestic", "EU"),
            "link": "https://wizzair.com",
        })

    return flights

# ============================
# MAIL
# ============================

def send_email(flights):
    body = "Vuelos baratos de fin de semana:\n\n"
    for f in flights:
        body += (
            f"{f['origin']} → {f['destination']} | "
            f"{f['dep']} - {f['ret']} | {f['price']}€\n{f['link']}\n\n"
        )

    msg = MIMEText(body)
    msg["Subject"] = "Alertas vuelos fin de semana"
    msg["From"] = GMAIL_USER
    msg["To"] = GMAIL_USER

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.send_message(msg)

# ============================
# MAIN
# ============================

def main():
    start_date = datetime.today()
    weekends = get_weekends(start_date)
    all_flights = []

    for dep, ret in weekends:
        for origin in ORIGINS:
            all_flights.extend(fetch_ryanair(origin, dep, ret))
            all_flights.extend(fetch_vueling(origin, dep, ret))
            all_flights.extend(fetch_easyjet(origin, dep, ret))
            all_flights.extend(fetch_wizz(origin, dep, ret))

    filtered = filter_flights(all_flights)

    if filtered:
        send_email(filtered)
        print(f"Email sent with {len(filtered)} flights.")
    else:
        print("No flights found today.")


if __name__ == "__main__":
    main()
