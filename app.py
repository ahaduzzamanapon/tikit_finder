import requests
from datetime import datetime, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pushbullet import Pushbullet
import time

# Pushbullet API Key (Replace with your key)
PB_API_KEY = "o.XHEci77Dyj8wqOxo66CqsMPPvJLI4R0b"  # 🔴 Replace this with your actual Pushbullet token
pb = Pushbullet(PB_API_KEY)

SEAT_TYPES = [
    "S_CHAIR", "SHOVAN", "SNIGDHA", "F_SEAT", "F_CHAIR", "AC_S",
    "F_BERTH", "AC_B", "SHULOV", "AC_CHAIR"
]

def fetch_train_data(model: str, api_date: str) -> dict:
    url = "https://railspaapi.shohoz.com/v1.0/web/train-routes"
    payload = {"model": model, "departure_date_time": api_date}
    headers = {'Content-Type': 'application/json'}
    response = requests.post(url, json=payload, headers=headers)
    response.raise_for_status()
    return response.json().get("data")

def get_seat_availability(train_model: str, journey_date: str, from_city: str, to_city: str) -> tuple:
    url = "https://railspaapi.shohoz.com/v1.0/web/bookings/search-trips-v2"
    params = {
        "from_city": from_city,
        "to_city": to_city,
        "date_of_journey": journey_date,
        "seat_class": "SHULOV"
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        trains = response.json().get("data", {}).get("trains", [])

        for train in trains:
            if train.get("train_model") == train_model:
                seat_info = {stype: {"online": 0, "offline": 0, "fare": 0, "vat_amount": 0} for stype in SEAT_TYPES}
                for seat in train.get("seat_types", []):
                    stype = seat["type"]
                    if stype in seat_info:
                        fare = float(seat["fare"])
                        vat_amount = float(seat["vat_amount"])
                        if stype in ["AC_B", "F_BERTH"]:
                            fare += 50
                        seat_info[stype] = {
                            "online": seat["seat_counts"]["online"],
                            "offline": seat["seat_counts"]["offline"],
                            "fare": fare,
                            "vat_amount": vat_amount
                        }
                return (from_city, to_city, seat_info)
        return (from_city, to_city, None)

    except requests.RequestException:
        return (from_city, to_city, None)

def compute_matrix():
    train_model = "797"
    journey_date_str = "04-Jun-2025"
    api_date_format = "2025-06-04"

    train_data = fetch_train_data(train_model, api_date_format)
    if not train_data or not train_data.get("train_name") or not train_data.get("routes"):
        raise Exception("No train info found. Try another train or date.")

    stations = [r['city'] for r in train_data['routes']]
    routes = train_data['routes']
    base_date = datetime.strptime(journey_date_str, "%d-%b-%Y")
    current_date = base_date
    previous_time = None
    station_dates = {}

    for i, stop in enumerate(routes):
        time_str = stop.get("departure_time") or stop.get("arrival_time")
        if time_str and "BST" in time_str:
            try:
                time_clean = time_str.replace(" BST", "").strip()
                hour_min, am_pm = time_clean.split(' ')
                hour, minute = map(int, hour_min.split(':'))
                am_pm = am_pm.lower()
                if am_pm == "pm" and hour != 12: hour += 12
                if am_pm == "am" and hour == 12: hour = 0
                current_time = timedelta(hours=hour, minutes=minute)

                if previous_time is not None and current_time < previous_time:
                    current_date += timedelta(days=1)
                previous_time = current_time
            except:
                pass
        station_dates[stop['city']] = current_date.strftime("%Y-%m-%d")

    fare_matrices = {
        seat_type: {from_city: {} for from_city in stations} for seat_type in SEAT_TYPES
    }

    available_matrix = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(
                get_seat_availability,
                train_model,
                datetime.strptime(station_dates[from_city], "%Y-%m-%d").strftime("%d-%b-%Y"),
                from_city,
                to_city
            )
            for i, from_city in enumerate(stations)
            for j, to_city in enumerate(stations)
            if i < j
        ]

        for future in as_completed(futures):
            from_city, to_city, seat_info = future.result()
            if seat_info:
                seats_available = [
                    seat_type for seat_type, info in seat_info.items()
                    if info["online"] + info["offline"] > 0
                ]
                if seats_available:
                    available_matrix.append({
                        "from": from_city,
                        "to": to_city,
                        "seats": seats_available
                    })

    if available_matrix:
        print("\n✅ Available Seat Routes:\n")
        msg_lines = []
        for entry in available_matrix:
            line = f"{entry['from']} ➡ {entry['to']} : {', '.join(entry['seats'])}"
            print("🟢", line)
            msg_lines.append(line)

        # Send notification to mobile
        message = "\n".join(msg_lines)
        pb.push_note("Train Seat Available!", message)
        time.sleep(300)
        compute_matrix()  # Retry
    else:
        print("❌ No available seats found.")
        time.sleep(300)
        compute_matrix()  # Retry

if __name__ == "__main__":
    compute_matrix()
