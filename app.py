import os
import time
import requests
from datetime import datetime
from datetime import timezone, timedelta
import pytz
from dotenv import load_dotenv
from github import Github

# ------------------------------------------------------
# LOAD ENV VARIABLES
# ------------------------------------------------------
load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
API_KEY = os.environ.get("CULT_API_KEY", "")
ST_COOKIE = os.environ.get("CULT_ST_COOKIE", "")
AT_COOKIE = os.environ.get("CULT_AT_COOKIE", "")
GITHUB_TOKEN = os.environ.get("SECRET_ACCESS_TOKEN")
GITHUB_REPOSITORY = os.environ.get("REPOSITORY_NAME")

COOKIES = {"st": ST_COOKIE, "at": AT_COOKIE}
HEADERS = {
    "apiKey": API_KEY,
    "Cookie": "; ".join([f"{k}={v}" for k, v in COOKIES.items()]),
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)",
}


# BOOKING_PREFERENCES = {
#     "centers": [946],                                # add more if needed
#     "preferred_timings": [                           # 8:00 PM and 9:00 AM
#         {"hour": 21, "minute": 00, "second": 0},
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
# GITHUB SECRET UPDATE
# ------------------------------------------------------
def update_github_secret(secret_name: str, secret_value: str):
    """Update a secret in the GitHub repository."""
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        msg = "🔒 GitHub token or repository not configured. Cannot update secrets."
        print(msg)
        notify(msg)
        return

    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPOSITORY)
        repo.create_secret(secret_name, secret_value)
        msg = f"🔐 Successfully updated GitHub secret: {secret_name}"
        print(msg)
        notify(msg)
    except Exception as e:
        msg = f"❌ Failed to update GitHub secret: {secret_name}. Error: {e}"
        print(msg)
        notify(msg)

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
        return False, None, None

    if r.status_code == 200 and ("Booked" in title or "confirmed" in title.lower()):
        # Booking was successful, check for new cookies in the response
        new_st = r.cookies.get('st')
        new_at = r.cookies.get('at')
        return True, new_st, new_at

    return False, None, None


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

    ok, new_st, new_at = book(center_id, slot_details.get("id"), BOOKING_PREFERENCES["sport_id"], ts)

    if ok:
        msg = (
            "🎉 BOOKING SUCCESSFUL!\n\n"
            f"Center: {center_id}\n"
            f"Time: {time_group.get('id')}\n"
            f"Date: {date_group.get('id')}\n"
            f"Class ID: {slot_details.get('id')}"
        )
        
        # If new cookies were returned, update them in GitHub Secrets
        if new_st and new_at:
            notify("❗ New cookies found! Attempting to update GitHub Secrets...")
            update_github_secret("CULT_ST_COOKIE", new_st)
            update_github_secret("CULT_AT_COOKIE", new_at)
        
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
    
    now = datetime.now(IST)
    # Define the target time for today using the current date
    target_time = now.replace(hour=TARGET_HOUR, minute=TARGET_MINUTE, second=TARGET_SECOND, microsecond=0)

    # Only wait if the target time is in the future
    if datetime.now(IST) < target_time:
        notify(f"⏰ Script triggered. Waiting until exactly {target_time.strftime('%H:%M:%S')} IST...")
        
        # ---- PRECISE WAIT LOGIC ----
        while True:
            now = datetime.now(IST)
            if now >= target_time:
                break # Exit loop when target time is reached

            time_to_target = (target_time - now).total_seconds()

            # Sleep for longer intervals when far from the target
            if time_to_target > 60:
                sleep_duration = 10
            # Sleep for 1s intervals when closer
            elif time_to_target > 1:
                sleep_duration = 1
            # For the final second, don't sleep at all.
            # Just loop continuously to catch the exact moment.
            else:
                continue
            
            print(f"[DEBUG] Current IST: {now.strftime('%H:%M:%S')}. Waiting for {target_time.strftime('%H:%M:%S')}. Sleeping for {sleep_duration}s")
            time.sleep(sleep_duration)

    # --- BOOKING LOGIC STARTS HERE ---
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
