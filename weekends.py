import os
import requests
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText

# --- CONFIG ---
ORIGINS = ["BCN", "GRO"]
EUROPE_CODES = {
    "AL","AD","AT","BY","BE","BA","BG","HR","CY","CZ","DK","EE","FI","FR",
    "DE","GR","HU","IS","IE","IT","LV","LI","LT","LU","MT","MD","MC","ME",
    "NL","MK","NO","PL","PT","RO","RU","SM","RS","SK","SI","ES","SE","CH",
    "UA","GB","VA"
}
EUROPE_PRICE = 50
WORLD_PRICE = 150
WEEKEND_GAP = 14  # días entre fines de semana
NUM_WEEKENDS = 12  # cuántos fines de semana hacia adelante

GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_PASSWORD = os.environ.get("GMAIL_PASSWORD")

# --- FUNCIONES AUXILIARES ---

def get_weekends(start_date):
    weekends = []
    current = start_date
    for _ in range(NUM_WEEKENDS):
        friday = current + timedelta((4-current.weekday()) % 7)
        monday = friday + timedelta(days=3)
        weekends.append((friday, monday))
        current = friday + timedelta(days=WEEKEND_GAP)
    return weekends

def filter_flights(flights):
    filtered = []
    for f in flights:
        price = f.get("price", 9999)
        country = f.get("country", "")
        if country in EUROPE_CODES or country=="MA":
            if price <= EUROPE_PRICE:
                filtered.append(f)
        else:
            if price <= WORLD_PRICE:
                filtered.append(f)
    return filtered

def fetch_ryanair(origin, dep_date, ret_date):
    # Endpoint interno no oficial de Ryanair (ejemplo)
    url = f"https://www.ryanair.com/api/farefinder/3/oneWayFares?departure={origin}&arrival=anywhere&dateOut={dep_date.strftime('%Y-%m-%d')}"
    try:
        r = requests.get(url, timeout=15)
        data = r.json()
        flights = []
        for item in data.get("fares", []):
            flights.append({
                "origin": origin,
                "destination": item.get("route", "UNKNOWN"),
                "dep": dep_date.strftime("%Y-%m-%d"),
                "ret": ret_date.strftime("%Y-%m-%d"),
                "price": item.get("price", 999),
                "country": item.get("country", "UNKNOWN"),
                "link": item.get("link", "")
            })
        return flights
    except:
        return []

# --- FUNCION PRINCIPAL ---

def main():
    start_date = datetime.today()
    weekends = get_weekends(start_date)
    all_flights = []
    for friday, monday in weekends:
        for origin in ORIGINS:
            flights = fetch_ryanair(origin, friday, monday)
            flights = filter_flights(flights)
            all_flights.extend(flights)

    if all_flights:
        send_email(all_flights)
    else:
        print("No flights found today.")

def send_email(flights):
    body = "Vuelos económicos de fin de semana:\n\n"
    for f in flights:
        body += f"{f['origin']} → {f['destination']} | {f['dep']} - {f['ret']} | {f['price']}€\n{f['link']}\n\n"

    msg = MIMEText(body)
    msg['Subject'] = "Alertas vuelos fin de semana"
    msg['From'] = GMAIL_USER
    msg['To'] = GMAIL_USER

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.send_message(msg)

if __name__ == "__main__":
    main()
