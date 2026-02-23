import os
import time
import requests
import logging
from datetime import datetime, timedelta, timezone
import pytz
from dotenv import load_dotenv
from github import Github
import threading
import queue

# ------------------------------------------------------
# 1. SETUP & LOGGING CONFIGURATION
# ------------------------------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("cult_booking.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")
notification_queue = queue.Queue()
session = requests.Session()

# Credentials
API_KEY = os.environ.get("CULT_API_KEY", "")
ST_COOKIE = os.environ.get("CULT_ST_COOKIE", "")
AT_COOKIE = os.environ.get("CULT_AT_COOKIE", "")
GITHUB_TOKEN = os.environ.get("SECRET_ACCESS_TOKEN")
GITHUB_REPOSITORY = os.environ.get("REPOSITORY_NAME")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Load initial state
session.cookies.update({"st": ST_COOKIE, "at": AT_COOKIE})

HEADERS = {
    "apiKey": API_KEY,
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)",
}

# Config
SLOT_ID_MAP = {1106: {"8:00": "4", "7:00": "3"}, 1107: {"8:00": "4", "7:00": "3"}}
BOOKING_PREFERENCES = {
    "centers": [1106, 1107],
    "preferred_timings": [{"hour": 8, "minute": 0}, {"hour": 7, "minute": 0}],
    "sport_id": 350
}

# ------------------------------------------------------
# 2. ASYNC NOTIFICATION ENGINE
# ------------------------------------------------------
def notify(msg: str):
    """Logs locally and pushes to the background queue immediately."""
    logger.info(msg)
    notification_queue.put(msg)

def notification_worker():
    """Background thread that handles Telegram API calls."""
    while True:
        message = notification_queue.get()
        if message is None: break
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: continue
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            # Increased timeout for Telegram to 15s to handle network jitters
            requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=15)
        except Exception as e:
            logger.error(f"Telegram Delivery Failed: {e}")
        finally:
            notification_queue.task_done()

def update_github_secret(name, value):
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPOSITORY)
        repo.create_secret(name, value)
        notify(f"🔐 GitHub Updated: {name}")
    except Exception as e:
        logger.error(f"GitHub Sync Error: {e}")

# ------------------------------------------------------
# 3. CORE LOGIC
# ------------------------------------------------------
def check_session_health(is_heartbeat=False):
    url = f"https://www.cult.fit/api/v2/fitso/web/sport?sportId={BOOKING_PREFERENCES['sport_id']}"
    try:
        r = session.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            msg = "💓 Session Heartbeat: ACTIVE" if is_heartbeat else "✅ Session Health: ACTIVE"
            notify(msg)
            return True
        notify(f"🚨 SESSION DEAD (Status {r.status_code})")
    except Exception as e:
        notify(f"⚠️ Health Check Error: {type(e).__name__}")
    return False

def book(center_id, slot_id, ts, time_str):
    global ST_COOKIE, AT_COOKIE
    payload = {"centerId": center_id, "slotId": str(slot_id), "workoutId": BOOKING_PREFERENCES['sport_id'], "bookingTimestamp": ts}
    url = "https://www.cult.fit/api/v2/fitso/web/class/book"
    
    for attempt in range(2):
        try:
            logger.info(f"Booking Attempt {attempt+1}: Center {center_id} for {time_str}...")
            # (connect timeout, read timeout)
            r = session.post(url, json=payload, headers=HEADERS, timeout=(5, 20))
            
            try:
                title = r.json().get("header", {}).get("title", "")
            except: title = ""

            if r.status_code == 200 and ("Booked" in title or "confirmed" in title.lower()):
                new_st, new_at = session.cookies.get('st'), session.cookies.get('at')
                if new_st and new_at and (new_st != ST_COOKIE or new_at != AT_COOKIE):
                    update_github_secret("CULT_ST_COOKIE", new_st)
                    update_github_secret("CULT_AT_COOKIE", new_at)
                    ST_COOKIE, AT_COOKIE = new_st, new_at
                notify(f"🎉 SUCCESS! Booked {center_id} @ {time_str}")
                return True
            
            logger.warning(f"Booking Fail (Attempt {attempt+1}): {r.text}")
            if attempt == 0: continue # Try one more time immediately
            
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
            logger.warning(f"⚠️ Network error on attempt {attempt+1}: {e}")
            if attempt == 0:
                time.sleep(0.5)
                continue
    return False

# ------------------------------------------------------
# 4. EXECUTION
# ------------------------------------------------------
if __name__ == "__main__":
    # Start the async notification thread
    threading.Thread(target=notification_worker, daemon=True).start()
    
    notify("🚀 Script Online. Target: 9:00 PM Booking.")

    TARGET_HOUR, TARGET_MIN = 21, 0
    now = datetime.now(IST)
    target_time = now.replace(hour=TARGET_HOUR, minute=TARGET_MIN, second=0, microsecond=0)

    if now < target_time:
        pre_flight_time = target_time - timedelta(seconds=60)
        
        # 10-Minute Keep-Alive Loop
        notify(f"⏲️ Starting 10-min heartbeats until {pre_flight_time.strftime('%H:%M:%S')}")
        while datetime.now(IST) < pre_flight_time:
            check_session_health(is_heartbeat=True)
            
            # Wait 10 mins OR until pre-flight time
            sleep_until = min(datetime.now(IST) + timedelta(minutes=10), pre_flight_time)
            sleep_duration = (sleep_until - datetime.now(IST)).total_seconds()
            if sleep_duration > 0:
                time.sleep(sleep_duration)

        # Pre-Flight Refresh
        notify("🔄 PRE-FLIGHT: Re-initializing connection for fresh TCP...")
        session.close()
        session = requests.Session()
        session.cookies.update({"st": ST_COOKIE, "at": AT_COOKIE})
        
        if not check_session_health():
            notify("🚨 WARNING: Pre-flight health check failed!")

        # Precision Wait
        logger.info("Standing by. Precision wait active.")
        while datetime.now(IST) < target_time:
            remaining = (target_time - datetime.now(IST)).total_seconds()
            if remaining > 1: time.sleep(0.1)
            else: continue

    # Booking Race
    target_date = datetime.now(IST) + timedelta(days=4)
    notify(f"⚡ RACING: Booking started at {datetime.now(IST).strftime('%H:%M:%S.%f')}")

    for timing in BOOKING_PREFERENCES["preferred_timings"]:
        for center in BOOKING_PREFERENCES["centers"]:
            time_key = f"{timing['hour']}:00"
            slot_id = SLOT_ID_MAP.get(center, {}).get(time_key)
            if not slot_id: continue

            dt = target_date.replace(hour=timing['hour'], minute=timing['minute'], second=0, microsecond=0)
            ts = int(dt.astimezone(timezone.utc).timestamp() * 1000)

            if book(center, slot_id, ts, time_key):
                notify("✅ Finished. Slot Secured.")
                time.sleep(10) # Wait for async queue to flush
                exit(0)

    notify("⚠️ Window Closed. No slots booked.")
    time.sleep(10) # Final flush
