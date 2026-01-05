import os
import time
import requests
from datetime import datetime
from datetime import timezone, timedelta
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


# BOOKING_PREFERENCES = {
#     "centers": [948],                                # add more if needed
#     "preferred_timings": [                           # 8:00 PM and 9:00 AM
#         {"hour": 20, "minute": 00, "second": 0},
#         {"hour": 9, "minute": 0, "second": 0}
#     ],
#     "sport_id": 351                                  # Pickleball
# }

BOOKING_PREFERENCES = {
    "centers": [1106, 1107],
    "preferred_timings": [
        {"hour": 8, "minute": 0},
        {"hour": 9, "minute": 0}
    ],
    "sport_id": 350,  # Badminton
    "enabled": True
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
    #print(f"[DEBUG] Response: {r.text}")
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


def find_and_book_preferred_slot(schedule_data, sport_id: int, target_date_str: str, center_id: int):
    """Iterate through preferred timings and try to book the first one found."""
    for date_group in schedule_data.get("classByDateList", []):
        # Only check for slots on the target date
        if date_group.get("id") != target_date_str:
            continue

        # Iterate through preferences to enforce order
        for pref_timing in BOOKING_PREFERENCES["preferred_timings"]:
            for time_group in date_group.get("classByTimeList", []):
                current_hour, current_minute = map(int, time_group.get("id", "99:99").split(':')[:2])

                # Check if this time_group matches the current preference
                if current_hour == pref_timing["hour"] and current_minute == pref_timing["minute"]:
                    for slot in time_group.get("classes", []):
                        if slot.get("workoutId") == sport_id and slot.get("availableSeats", 0) > 0 and slot.get("state") == "AVAILABLE":
                            print(f"[INFO] Preferred slot found {time_group.get('id')} - Seats={slot.get('availableSeats')}")
                            # Attempt to book this slot immediately
                            return book_slot_from_details(center_id, slot, date_group, time_group)

    print("[INFO] No preferred slots found after checking all preferences.")
    return False



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


def book_slot_from_details(center_id: int, slot_details: dict, date_group: dict, time_group: dict) -> bool:
    """Helper function to encapsulate booking logic for a found slot."""
    notify(
        f"🏸 Slot Found!\nCenter: {center_id}\nDate: {date_group.get('id')}\n"
        f"Time: {time_group.get('id')}\nSeats: {slot_details.get('availableSeats')}"
    )

    ts = convert_utc_to_timestamp(slot_details.get("startDateTimeUTC"))
    if not ts:
        err_msg = f"⚠️ Could not convert slot time to timestamp for Center {center_id}."
        print(err_msg)
        notify(err_msg)
        return False

    ok = book(center_id, slot_details.get("id"), BOOKING_PREFERENCES["sport_id"], ts)

    if ok:
        msg = (
            "🎉 BOOKING SUCCESSFUL!\n\n"
            f"Center: {center_id}\n"
            f"Time: {time_group.get('id')}\n"
            f"Date: {date_group.get('id')}\n"
            f"Class ID: {slot_details.get('id')}"
        )
        notify(msg)
        print(msg)
        return True
    else:
        notify(f"❌ Booking failed for center {center_id} at time {time_group.get('id')}")
        return False
# ------------------------------------------------------
# MAIN LOGIC
# ------------------------------------------------------
if __name__ == "__main__":
    print("🚀 Cult Booking Script Triggered")

    TARGET_HOUR = 21  # 9 PM
    TARGET_MINUTE = 0
    TARGET_SECOND = 0
    
    # Notify with the correct target time
    notify(f"⏰ Script triggered. Waiting until exactly {TARGET_HOUR:02d}:{TARGET_MINUTE:02d} IST...")

    # ---- PRECISE WAIT LOGIC ----
    while True:
        now = datetime.now(IST)
        
        # Check if we are at or past the target time
        if (now.hour > TARGET_HOUR) or \
           (now.hour == TARGET_HOUR and now.minute > TARGET_MINUTE) or \
           (now.hour == TARGET_HOUR and now.minute == TARGET_MINUTE and now.second >= TARGET_SECOND):
            break

        # Calculate remaining time to be more intelligent about sleeping
        time_to_target = (
            datetime(now.year, now.month, now.day, TARGET_HOUR, TARGET_MINUTE, TARGET_SECOND, tzinfo=IST) - now
        ).total_seconds()

        sleep_duration = 1 # Default sleep
        if time_to_target > 60:
            sleep_duration = 10  # Sleep longer if we are far away
        elif time_to_target <= 1 and time_to_target > 0:
            sleep_duration = 0.001 # Sleep for 1ms if very close
        elif time_to_target <= 0:
             break # Go time
        
        print(f"[DEBUG] Current IST: {now.strftime('%H:%M:%S.%f')}. Waiting for {TARGET_HOUR:02d}:{TARGET_MINUTE:02d}. Sleeping for {sleep_duration}s")
        time.sleep(sleep_duration)

    # Calculate the target date which is 4 days from now.
    target_date = datetime.now(IST) + timedelta(days=4)

    # Use the precise start time in the notification
    notify(f"🚀 Booking started at {datetime.now(IST).strftime('%H:%M:%S.%f')} IST!")

    # ---- BOOKING FLOW ----
    for center in BOOKING_PREFERENCES["centers"]:
        print(f"\n========== Checking center {center} ==========")

        try:
            schedule_data = get_center_schedule(center)
            
            # The new function will try to book and will return True on success
            booking_succeeded = find_and_book_preferred_slot(schedule_data, BOOKING_PREFERENCES["sport_id"], target_date.strftime("%Y-%m-%d"), center)
            
            if booking_succeeded:
                exit(0)
        except Exception as e:
            notify(f"⚠️ Error for center {center}: {str(e)}")
            print("Exception:", e)
            continue

    notify("⚠️ Script finished. No preferred slots were successfully booked.")
    print("⚠️ Script finished. No preferred slots were successfully booked.")
