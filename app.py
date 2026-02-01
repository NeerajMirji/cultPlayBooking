import os
import time
import requests
from datetime import datetime, timedelta, timezone
import pytz
from dotenv import load_dotenv
from github import Github
import threading
import queue

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

# --- V2 BOOKING PREFERENCES ---
SLOT_ID_MAP = {
    946: {  # Fitso Silpa Park Badminton
        "8:00": "4",
        "7:00": "3"
    },
    1107: { # Placeholder, needs verification
        "8:00": "4", 
        "7:00": "3" 
    }
}

BOOKING_PREFERENCES = {
    "centers": [946, 1107],
    "preferred_timings": [
        {"hour": 8, "minute": 0},
        {"hour": 7, "minute": 0}
    ],
    "sport_id": 351,  # Badminton
    "enabled": True
}

IST = pytz.timezone("Asia/Kolkata")
notification_queue = queue.Queue()

# ------------------------------------------------------
# NOTIFICATION WORKER THREAD
# ------------------------------------------------------
def notification_worker():
    """Processes notification messages from a queue in the background."""
    while True:
        message = notification_queue.get()
        if message is None:
            break

        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            print("[WARN] Telegram not configured. Skipping notification.")
            continue
        
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=5)
        except Exception as e:
            print(f"[ERROR] Notification failed: {e}")
        finally:
            notification_queue.task_done()

def notify(msg: str):
    """Adds a message to the notification queue to be sent in the background."""
    notification_queue.put(msg)

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
# BOOKING
# ------------------------------------------------------
def book(center_id, slot_id, workout_id, ts, time_str):
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
        title = ""

    if r.status_code == 200 and ("Booked" in title or "confirmed" in title.lower()):
        new_st = r.cookies.get('st')
        new_at = r.cookies.get('at')

        msg = (
            "🎉 BOOKING SUCCESSFUL!\n\n"
            f"Center: {center_id}\n"
            f"Time: {time_str}\n"
            f"Slot ID: {slot_id}"
        )
        
        if new_st and new_at:
            notify("❗ New cookies found! Attempting to update GitHub Secrets...")
            update_github_secret("CULT_ST_COOKIE", new_st)
            update_github_secret("CULT_AT_COOKIE", new_at)
        
        notify(msg)
        print(msg)
        return True
    else:
        notify(f"❌ Booking failed for center {center_id} at time {time_str}. Response: {r.text}")
        return False

# ------------------------------------------------------
# MAIN LOGIC
# ------------------------------------------------------
if __name__ == "__main__":
    # Start the background notification worker thread
    notification_thread = threading.Thread(target=notification_worker, daemon=True)
    notification_thread.start()

    print("🚀 Cult Booking Script Triggered")
    notify("🚀 Cult Booking Script Triggered")

    TARGET_HOUR = 16
    TARGET_MINUTE = 0
    TARGET_SECOND = 0
    
    now = datetime.now(IST)
    target_time = now.replace(hour=TARGET_HOUR, minute=TARGET_MINUTE, second=TARGET_SECOND, microsecond=0)

    if datetime.now(IST) < target_time:
        notify(f"⏰ Script triggered. Waiting until exactly {target_time.strftime('%H:%M:%S')} IST...")
        
        while True:
            now = datetime.now(IST)
            if now >= target_time:
                break

            time_to_target = (target_time - now).total_seconds()

            if time_to_target > 60:
                sleep_duration = 10
            elif time_to_target > 1:
                sleep_duration = 1
            else:
                continue
            
            print(f"[DEBUG] Current IST: {now.strftime('%H:%M:%S')}. Waiting for {target_time.strftime('%H:%M:%S')}. Sleeping for {sleep_duration}s")
            time.sleep(sleep_duration)

    # --- V2 BOOKING LOGIC ---

    target_booking_date = datetime.now(IST) + timedelta(days=3)
    
    notify(f"🚀 Booking started at {datetime.now(IST).strftime('%H:%M:%S.%f')} IST!")

    for pref_timing in BOOKING_PREFERENCES["preferred_timings"]:
        for center in BOOKING_PREFERENCES["centers"]:
            
            time_key = f"{pref_timing['hour']}:00"

            slot_id = SLOT_ID_MAP.get(center, {}).get(time_key)

            if not slot_id:
                print(f"[WARN] No slot_id mapping for Center {center} at {time_key}. Skipping.")
                continue

            print(f"\n[INFO] Attempting direct booking for Center {center} at {time_key}")

            booking_dt_ist = target_booking_date.replace(
                hour=pref_timing['hour'], 
                minute=pref_timing['minute'], 
                second=0, 
                microsecond=0
            )
            
            booking_timestamp_ms = int(booking_dt_ist.astimezone(timezone.utc).timestamp() * 1000)

            booking_succeeded = book(
                center_id=center,
                slot_id=slot_id,
                workout_id=BOOKING_PREFERENCES["sport_id"],
                ts=booking_timestamp_ms,
                time_str=time_key
            )

            if booking_succeeded:
                notify("✅ Main thread finished after successful booking.")
                exit(0)

    notify("⚠️ Script finished. No preferred slots were successfully booked.")
    print("⚠️ Script finished. No preferred slots were successfully booked.")