import os
import requests
from datetime import date, datetime, timedelta
import smtplib
from email.mime.text import MIMEText
import time

# ============================
# CONFIGURACIÓN
# ============================

ORIGINS = ["BCN", "GRO"]

EUROPE_CODES = {
    "AL","AD","AT","BY","BE","BA","BG","HR","CY","CZ","DK","EE","FI","FR",
    "DE","GR","HU","IE","IT","LV","LI","LT","LU","MT","MD","MC","ME",
    "NL","MK","NO","PL","PT","RO","SM","RS","SK","SI","ES","SE","CH",
    "UA","GB","VA","XK", "DZ", "MA"
}
#NO EN LA LISTA: "IS": Islandia, "RU": Rusia, "TR" Turquía
#"AL": Albania, "AD": Andorra, "AT": Austria, "BY": Bielorrusia, "BE": Bélgica, "BA": Bosnia y Herzegovina, "BG": Bulgaria, "HR": Croacia, "CY": Chipre, "CZ": República Checa, "DK": Dinamarca, "EE": Estonia, "FI": Finlandia, "FR": Francia, "DE": Alemania, "GR": Grecia, "HU": Hungría, "IE": Irlanda, "IT": Italia, "LV": Letonia, "LI": Liechtenstein, "LT": Lituania, "LU": Luxemburgo, "MT": Malta, "MD": Moldavia, "MC": Mónaco, "ME": Montenegro, "NL": Países Bajos, "MK": Macedonia del Norte, "NO": Noruega, "PL": Polonia, "PT": Portugal, "RO": Rumanía, "SM": San Marino, "RS": Serbia, "SK": Eslovaquia, "SI": Eslovenia, "ES": España, "SE": Suecia, "CH": Suiza, "UA": Ucrania, "GB": Reino Unido, "VA": Ciudad del Vaticano, "XK" Kosovo
#Extra Europa: "DZ": Argelia, "MA": Marruecos 

EUROPE_PRICE = 50.0
WORLD_PRICE = 150.0

INTERVAL_DAYS = 14
MAX_WEEKENDS_PER_RUN = 1  # controla consumo API

AMADEUS_CLIENT_ID = os.environ.get("AMADEUS_CLIENT_ID")
AMADEUS_CLIENT_SECRET = os.environ.get("AMADEUS_CLIENT_SECRET")

GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_PASSWORD = os.environ.get("GMAIL_PASSWORD")

AUTH_URL = "https://test.api.amadeus.com/v1/security/oauth2/token"
SEARCH_URL = "https://test.api.amadeus.com/v2/shopping/flight-offers"


# ============================
# HERRAMIENTAS
# ============================

def get_token():
    data = {
        "grant_type": "client_credentials",
        "client_id": AMADEUS_CLIENT_ID,
        "client_secret": AMADEUS_CLIENT_SECRET
    }
    r = requests.post(AUTH_URL, data=data)
    r.raise_for_status()
    return r.json()["access_token"]


def next_friday_from(d):
    days = (4 - d.weekday()) % 7
    return d if days == 0 else d + timedelta(days=days)


def generate_weekends(start_date):
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    d = next_friday_from(start_date)
    weekends = []
    for _ in range(MAX_WEEKENDS_PER_RUN):
        weekends.append((d, d + timedelta(days=3)))
        d = d + timedelta(days=INTERVAL_DAYS)
    return weekends


def normalize_price(p):
    try:
        return float(p)
    except:
        return 99999.0


def search_amadeus(origin, dep, ret, token):
    params = {
        "originLocationCode": origin,
        "destinationLocationCode": "ANY",
        "departureDate": dep.strftime("%Y-%m-%d"),
        "returnDate": ret.strftime("%Y-%m-%d"),
        "adults": "1",
        "currencyCode": "EUR",
        "max": "20"
    }
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(SEARCH_URL, params=params, headers=headers, timeout=20)
    if r.status_code == 429:
        print("RATE LIMIT — demasiadas llamadas hoy")
        return []
    r.raise_for_status()
    return r.json().get("data", [])


def extract_data(offer):
    price = normalize_price(offer["price"]["total"])

    try:
        last_seg = offer["itineraries"][-1]["segments"][-1]
        dest = last_seg["arrival"]["iataCode"]
        country = last_seg["arrival"].get("countryCode")
    except:
        dest, country = None, None

    # calcular duración total
    total_minutes = 0
    try:
        for itin in offer["itineraries"]:
            for seg in itin["segments"]:
                dur = seg.get("duration", "")
                # dur ejemplo: "PT2H30M"
                h, m = 0, 0
                if "H" in dur:
                    h = int(dur.split("H")[0].replace("PT",""))
                    rest = dur.split("H")[1]
                    if "M" in rest:
                        m = int(rest.replace("M",""))
                elif "M" in dur:
                    m = int(dur.replace("PT","").replace("M",""))
                total_minutes += h*60 + m
    except:
        total_minutes = 0

    link = offer.get("self", {}).get("href")

    return price, dest, country, total_minutes, link


def is_europe_or_ma(code):
    if not code:
        return False
    return code in EUROPE_CODES


# ============================
# EMAIL
# ============================

def send_email(results):
    body = "Ofertas encontradas:\n\n"
    for r in results:
        body += f"{r['origin']} → {r['dest']} | {r['dep']} → {r['ret']} | {r['price']}€\n{r['link']}\n\n"

    msg = MIMEText(body)
    msg["Subject"] = "Ofertas de Fin de Semana"
    msg["From"] = GMAIL_USER
    msg["To"] = GMAIL_USER

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(GMAIL_USER, GMAIL_PASSWORD)
        s.send_message(msg)


# ============================
# MAIN
# ============================

def main():
    start = os.environ.get("START_DATE", date.today().strftime("%Y-%m-%d"))
    weekends = generate_weekends(start)

    try:
        token = get_token()
    except Exception as e:
        print("Error al obtener token de Amadeus:", e)
        return

    found = []

    for dep, ret in weekends:
        for origin in ORIGINS:
            offers = search_amadeus(origin, dep, ret, token)
            for off in offers:
                price, dest, country, duration, link = extract_data(off)
                if duration < 60:  # mínimo 1 hora
                    continue

                if is_europe_or_ma(country):
                    if price > EUROPE_PRICE:
                        continue
                else:
                    if price > WORLD_PRICE:
                        continue

                found.append({
                    "origin": origin,
                    "dest": dest,
                    "country": country,
                    "dep": dep.strftime("%Y-%m-%d"),
                    "ret": ret.strftime("%Y-%m-%d"),
                    "price": price,
                    "link": link
                })

            time.sleep(0.4)  # para evitar rate limits

    if found:
        found.sort(key=lambda x: x["price"])
        send_email(found)
        print("Envio email con", len(found), "ofertas.")
    else:
        print("No flights found today.")


if __name__ == "__main__":
    main()
