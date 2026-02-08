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
        # Explicitly set encoding to utf-8 to handle emojis
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
# 2. UTILITIES
# ------------------------------------------------------
def notify(msg: str):
    """Logs the message locally and queues it for Telegram."""
    logger.info(msg)
    notification_queue.put(msg)

def notification_worker():
    while True:
        message = notification_queue.get()
        if message is None: break
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: continue
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=5)
        except Exception as e:
            logger.error(f"Telegram failed: {e}")
        finally: notification_queue.task_done()

def update_github_secret(name, value):
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPOSITORY)
        repo.create_secret(name, value)
        notify(f"🔐 Secret Updated: {name}")
    except Exception as e:
        logger.error(f"GitHub Secret Sync Error: {e}")

# ------------------------------------------------------
# 3. CORE ENGINE
# ------------------------------------------------------
def check_session_health():
    url = f"https://www.cult.fit/api/v2/fitso/web/sport?sportId={BOOKING_PREFERENCES['sport_id']}"
    try:
        r = session.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            notify("✅ Session Health: ACTIVE")
            return True
        notify(f"🚨 Session Health: DEAD (Status {r.status_code})")
    except Exception as e:
        logger.error(f"Health Check Exception: {e}")
    return False

def book(center_id, slot_id, ts, time_str):
    payload = {"centerId": center_id, "slotId": str(slot_id), "workoutId": BOOKING_PREFERENCES['sport_id'], "bookingTimestamp": ts}
    url = "https://www.cult.fit/api/v2/fitso/web/class/book"
    
    logger.info(f"Attempting Center {center_id} for {time_str}...")
    r = session.post(url, json=payload, headers=HEADERS, timeout=10)
    
    try:
        title = r.json().get("header", {}).get("title", "")
    except: title = ""

    if r.status_code == 200 and ("Booked" in title or "confirmed" in title.lower()):
        new_st, new_at = session.cookies.get('st'), session.cookies.get('at')
        if new_st != ST_COOKIE or new_at != AT_COOKIE:
            update_github_secret("CULT_ST_COOKIE", new_st)
            update_github_secret("CULT_AT_COOKIE", new_at)
        notify(f"🎉 SUCCESS! Booked {center_id} @ {time_str}")
        return True
    
    logger.warning(f"Booking fail for {center_id}: {r.text}")
    return False

# ------------------------------------------------------
# 4. EXECUTION
# ------------------------------------------------------
if __name__ == "__main__":
    threading.Thread(target=notification_worker, daemon=True).start()
    logger.info("🚀 Script Online (Cron Start)")
    notify("🚀 Cult Booking Script Online (Cron Triggered)")

    TARGET_HOUR, TARGET_MIN = 21, 0
    now = datetime.now(IST)
    target_time = now.replace(hour=TARGET_HOUR, minute=TARGET_MIN, second=0, microsecond=0)

    if now < target_time:
        # Health check at 8:15 PM (45 mins before)
        health_time = target_time - timedelta(minutes=45)
        
        if now < health_time:
            logger.info(f"Waiting until 8:15 PM for Health Check...")
            time.sleep((health_time - now).total_seconds())
        
        check_session_health()

        # Wait for 9:00 PM
        logger.info("Standing by for 9:00 PM booking window...")
        while datetime.now(IST) < target_time:
            remaining = (target_time - datetime.now(IST)).total_seconds()
            if remaining > 1: time.sleep(0.5)
            else: continue

    # Booking Logic
    target_date = datetime.now(IST) + timedelta(days=4)
    notify(f"⚡ Booking Started at {datetime.now(IST).strftime('%H:%M:%S.%f')}")

    for timing in BOOKING_PREFERENCES["preferred_timings"]:
        for center in BOOKING_PREFERENCES["centers"]:
            time_key = f"{timing['hour']}:00"
            slot_id = SLOT_ID_MAP.get(center, {}).get(time_key)
            if not slot_id: continue

            dt = target_date.replace(hour=timing['hour'], minute=timing['minute'], second=0, microsecond=0)
            ts = int(dt.astimezone(timezone.utc).timestamp() * 1000)

            if book(center, slot_id, ts, time_key):
                notify("✅ Booking Successful.")
                exit(0)

    notify("⚠️ Window closed. No slots secured.")