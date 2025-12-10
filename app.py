import os
import time
import requests
from datetime import datetime
from datetime import timezone
import pytz
from dotenv import load_dotenv

# ------------------------------------------------------
# LOAD ENV VARIABLES
# ------------------------------------------------------
load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
API_KEY = os.environ.get("CULT_API_KEY", "")
ST_COOKIE = os.environ.get("CULT_ST_COOKIE", "")
AT_COOKIE = os.environ.get("CULT_AT_COOKIE", "")

COOKIES = {"st": ST_COOKIE, "at": AT_COOKIE}
HEADERS = {
    "apiKey": API_KEY,
    "Cookie": "; ".join([f"{k}={v}" for k, v in COOKIES.items()]),
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)",
}

# USER PREFS — SAME AS YOUR WORKING CODE
BOOKING_PREFERENCES = {
    "centers": [948],                                # add more if needed
    "preferred_timings": [                           # 8:00 PM and 9:00 AM
        {"hour": 20, "minute": 00, "second": 0},
        {"hour": 9, "minute": 0, "second": 0}
    ],
    "sport_id": 351                                  # Pickleball
}

IST = pytz.timezone("Asia/Kolkata")

# ------------------------------------------------------
# TELEGRAM NOTIFICATION
# ------------------------------------------------------
def notify(msg: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured.")
        return

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=5)
    except:
        pass


# ------------------------------------------------------
# FETCH CENTER SCHEDULE
# ------------------------------------------------------
def get_center_schedule(center_id: int):
    print(f"[INFO] Fetching schedule for center {center_id} ...")
    url = f"https://www.cult.fit/api/v2/fitso/web/schedule?centerId={center_id}"
    r = requests.get(url, headers=HEADERS, timeout=8)
    print(f"[DEBUG] Schedule API Status: {r.status_code}")
    print(f"[DEBUG] Response: {r.text[:500]}")
    return r.json()


# ------------------------------------------------------
# UTILS
# ------------------------------------------------------
def convert_utc_to_timestamp(utc_string):
    try:
        dt_str = utc_string.replace(' GMT', '')
        dt = datetime.strptime(dt_str, '%a, %d %b %Y %H:%M:%S')
        timestamp_seconds = int(dt.replace(tzinfo=timezone.utc).timestamp())
        return timestamp_seconds * 1000
    except Exception as e:
        print(f"Error converting timestamp: {e}")
        return None


def matches_preferred_timing(time_str: str):
    try:
        hour, minute = map(int, time_str.split(':')[:2])
    except:
        return False

    for pref in BOOKING_PREFERENCES["preferred_timings"]:
        if hour == pref["hour"] and minute == pref["minute"]:
            return True
    return False


def find_available_slots(schedule_data, sport_id):
    available = []

    for date_group in schedule_data.get("classByDateList", []):
        for time_group in date_group.get("classByTimeList", []):
            for slot in time_group.get("classes", []):
                if (
                    slot.get("workoutId") == sport_id and
                    slot.get("availableSeats", 0) > 0 and
                    matches_preferred_timing(time_group.get("id", ""))
                ):
                    print(f"[INFO] Slot found {time_group.get('id')} - Seats={slot.get('availableSeats')}")

                    available.append({
                        "class_id": slot.get("id"),
                        "date": date_group.get("id"),
                        "time": time_group.get("id"),
                        "start_utc": slot.get("startDateTimeUTC"),
                        "seats": slot.get("availableSeats")
                    })

    print(f"[INFO] Preferred slots found: {len(available)}")

    return available


# ------------------------------------------------------
# BOOKING
# ------------------------------------------------------
def book(center_id, slot_id, workout_id, ts):
    payload = {
        "centerId": center_id,
        "slotId": str(slot_id),
        "workoutId": workout_id,
        "bookingTimestamp": ts
    }

    print(f"[INFO] Attempting to book slot {slot_id} at center {center_id}")
    url = "https://www.cult.fit/api/v2/fitso/web/class/book"
    r = requests.post(url, json=payload, headers=HEADERS, timeout=10)

    print(f"[DEBUG] Booking Status: {r.status_code}")
    print(f"[DEBUG] Booking Response: {r.text}")

    try:
        title = r.json().get("header", {}).get("title", "")
    except:
        return False

    if r.status_code == 200 and ("Booked" in title or "confirmed" in title.lower()):
        return True

    return False


# ------------------------------------------------------
# MAIN LOGIC
# ------------------------------------------------------
if __name__ == "__main__":
    print("🚀 Cult Booking Script Triggered")
    notify("⏰ GitHub Action Triggered. Waiting until exactly 10:00 PM IST...")

    # ---- WAIT UNTIL EXACTLY 22:00 IST ----
    while True:
        now = datetime.now(IST)
        print("[DEBUG] Current IST:", now.strftime("%H:%M:%S"))
        # Wait until exactly 10 PM IST to start booking
        if now.hour >= 11 and now.minute >= 20:
            break
        time.sleep(0.5)

    notify("🚀 Booking started at 10:00 PM IST!")

    # ---- BOOKING FLOW ----
    for center in BOOKING_PREFERENCES["centers"]:
        print(f"\n========== Checking center {center} ==========")

        try:
            schedule_data = get_center_schedule(center)
            available = find_available_slots(schedule_data, BOOKING_PREFERENCES["sport_id"])

            if not available:
                print("[WARN] No preferred slots in this center.")
                continue

            slot = available[0]  # pick first available slot

            notify(
                f"🏸 Slot Found!\nCenter: {center}\nDate: {slot['date']}\n"
                f"Time: {slot['time']}\nSeats: {slot['seats']}"
            )

            ts = convert_utc_to_timestamp(slot["start_utc"])
            if not ts:
                err_msg = f"⚠️ Could not convert slot time to timestamp for Center {center}."
                print(err_msg)
                notify(err_msg)
                continue
            ok = book(center, slot["class_id"], BOOKING_PREFERENCES["sport_id"], ts)

            if ok:
                msg = (
                    "🎉 BOOKING SUCCESSFUL!\n\n"
                    f"Center: {center}\n"
                    f"Time: {slot['time']}\n"
                    f"Date: {slot['date']}\n"
                    f"Class ID: {slot['class_id']}"
                )
                notify(msg)
                print(msg)
                exit(0)
            else:
                notify(f"❌ Booking failed for center {center}")

        except Exception as e:
            notify(f"⚠️ Error for center {center}: {str(e)}")
            print("Exception:", e)
            continue

    notify("⚠️ No matching slots found or booking failed.")
    print("⚠️ No matching slots found.")
