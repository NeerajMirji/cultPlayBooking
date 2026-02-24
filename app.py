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

# UTF-8 encoding is critical for Windows to handle emojis in logs
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

# Credentials - Ensure these are set in your .env or GitHub Secrets
API_KEY = os.environ.get("CULT_API_KEY", "")
ST_COOKIE = os.environ.get("CULT_ST_COOKIE", "")
AT_COOKIE = os.environ.get("CULT_AT_COOKIE", "")
GITHUB_TOKEN = os.environ.get("SECRET_ACCESS_TOKEN")
GITHUB_REPOSITORY = os.environ.get("REPOSITORY_NAME")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Initial session setup
session.cookies.update({"st": ST_COOKIE, "at": AT_COOKIE})

HEADERS = {
    "apiKey": API_KEY,
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)",
}

# Config
SLOT_ID_MAP = {
    1106: {"8:00": "4", "7:00": "3"}, 
    1107: {"8:00": "4", "7:00": "3"}
}
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
    """Background thread that handles Telegram API calls without blocking main logic."""
    while True:
        message = notification_queue.get()
        if message is None: break
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: continue
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=15)
        except Exception as e:
            logger.error(f"Telegram Delivery Failed: {e}")
        finally:
            notification_queue.task_done()

def update_github_secret(name, value):
    """Syncs new cookies back to GitHub to prevent session expiry."""
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPOSITORY)
        repo.create_secret(name, value)
        notify(f"🔐 GitHub Sync Success: {name}")
    except Exception as e:
        logger.error(f"GitHub Sync Error: {e}")

# ------------------------------------------------------
# 3. CORE ENGINE
# ------------------------------------------------------
def reset_session():
    """Forcibly closes the current session and opens a fresh TCP connection."""
    global session
    try:
        session.close()
    except: pass
    session = requests.Session()
    session.cookies.update({"st": ST_COOKIE, "at": AT_COOKIE})
    logger.info("🔄 Session object recreated. Fresh TCP handshake initialized.")

def check_session_health(is_heartbeat=False):
    """Verifies session and resets connection if timeout/error occurs."""
    url = f"https://www.cult.fit/api/v2/fitso/web/sport?sportId={BOOKING_PREFERENCES['sport_id']}"
    try:
        r = session.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            msg = "💓 Heartbeat: ACTIVE" if is_heartbeat else "✅ Health Check: ACTIVE"
            notify(msg)
            return True
        notify(f"🚨 SESSION DEAD (Status {r.status_code})")
        return False
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
        logger.warning(f"⚠️ Connection issue detected: {type(e).__name__}. Resetting...")
        reset_session()
        notify(f"🔄 Connection Recovered: Session reset after network timeout.")
        return False

def book(center_id, slot_id, ts, time_str):
    """Attempts booking with a retry mechanism and aggressive timeouts."""
    global ST_COOKIE, AT_COOKIE
    payload = {
        "centerId": center_id, 
        "slotId": str(slot_id), 
        "workoutId": BOOKING_PREFERENCES['sport_id'], 
        "bookingTimestamp": ts
    }
    url = "https://www.cult.fit/api/v2/fitso/web/class/book"
    
    # 
    for attempt in range(2):
        try:
            logger.info(f"Booking Attempt {attempt+1}: Center {center_id} for {time_str}...")
            # timeout=(connect_timeout, read_timeout)
            r = session.post(url, json=payload, headers=HEADERS, timeout=(5, 20))
            
            try:
                data = r.json()
                title = data.get("header", {}).get("title", "")
            except: title = ""

            if r.status_code == 200 and ("Booked" in title or "confirmed" in title.lower()):
                new_st, new_at = session.cookies.get('st'), session.cookies.get('at')
                if new_st and new_at and (new_st != ST_COOKIE or new_at != AT_COOKIE):
                    update_github_secret("CULT_ST_COOKIE", new_st)
                    update_github_secret("CULT_AT_COOKIE", new_at)
                    ST_COOKIE, AT_COOKIE = new_st, new_at
                notify(f"🎉 SUCCESS! Booked {center_id} @ {time_str}")
                return True
            
            logger.warning(f"Booking Fail (Status {r.status_code}): {r.text}")
            if attempt == 0: continue 
            
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
            logger.warning(f"⚠️ Booking network error: {e}")
            if attempt == 0:
                reset_session() # Fix connection before immediate retry
                time.sleep(0.2)
                continue
    return False

# ------------------------------------------------------
# 4. MAIN EXECUTION FLOW
# ------------------------------------------------------
if __name__ == "__main__":
    threading.Thread(target=notification_worker, daemon=True).start()
    
    notify("🚀 Script Online. Target: 9:00 PM Booking window.")

    TARGET_HOUR, TARGET_MIN = 21, 0
    now = datetime.now(IST)
    target_time = now.replace(hour=TARGET_HOUR, minute=TARGET_MIN, second=0, microsecond=0)

    if now < target_time:
        pre_flight_time = target_time - timedelta(seconds=60)
        
        # 
        # 1. WARM-UP LOOP (Every 10 mins)
        while datetime.now(IST) < pre_flight_time:
            check_session_health(is_heartbeat=True)
            
            sleep_until = min(datetime.now(IST) + timedelta(minutes=10), pre_flight_time)
            sleep_duration = (sleep_until - datetime.now(IST)).total_seconds()
            if sleep_duration > 0:
                time.sleep(sleep_duration)

        # 2. PROACTIVE PRE-FLIGHT REFRESH (8:59 PM)
        notify("🔄 PRE-FLIGHT: Refreshing connection for 9:00 PM race...")
        reset_session()
        
        if not check_session_health():
            notify("🚨 WARNING: Pre-flight check failed! Proceeding anyway...")

        # 3. PRECISION WAIT
        logger.info("Standing by. Shifting to high-precision polling.")
        while datetime.now(IST) < target_time:
            remaining = (target_time - datetime.now(IST)).total_seconds()
            if remaining > 1: time.sleep(0.1)
            else: continue

    # 4. BOOKING RACE
    target_date = datetime.now(IST) + timedelta(days=4)
    notify(f"⚡ RACING: Starting booking calls at {datetime.now(IST).strftime('%H:%M:%S.%f')}")

    for timing in BOOKING_PREFERENCES["preferred_timings"]:
        for center in BOOKING_PREFERENCES["centers"]:
            time_key = f"{timing['hour']}:00"
            slot_id = SLOT_ID_MAP.get(center, {}).get(time_key)
            if not slot_id: continue

            dt = target_date.replace(hour=timing['hour'], minute=timing['minute'], second=0, microsecond=0)
            ts = int(dt.astimezone(timezone.utc).timestamp() * 1000)

            if book(center, slot_id, ts, time_key):
                notify("✅ Finished. Slot Secured.")
                time.sleep(10) # Ensure Telegram notifications flush
                exit(0)

    notify("⚠️ Window Closed. No slots booked.")
    time.sleep(10)
