import requests
from datetime import datetime, timezone
import time
import json
import schedule
import pytz

# ===== TELEGRAM CONFIG =====
TELEGRAM_BOT_TOKEN = "8566918680:AAH8s0WrBq5XagahsA82bK-RR9XnqTW3kQw"
TELEGRAM_CHAT_ID = "902534243"

def send_telegram(message: str):
    """Send a Telegram message. Non-blocking on failure."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        # short timeout so scheduler loop isn't blocked
        requests.post(url, data=payload, timeout=5)
        print("📨 Telegram notification sent.")
    except Exception as e:
        print("❌ Telegram send error:", e)


# ===== USER AUTH HEADERS =====
cookies = {
    "st": "s%3ACFAPP%3A2e5ae204-46ce-48b3-8f43-6a2fd329ea45.N0zkdI3uAxtwk%2BPKTx2td4GSIdUEtmyB2jPdkcfmMF8",
    "at": "s%3ACFAPP%3A317ed54b-3603-4443-9886-5abb7c1ce654.O1k09IotPw4yplHPHStDfRq%2FaK126lowkJDmnyvqwBA"
}

headers = {
    "apiKey": "9d153009-e961-4718-a343-2a36b0a1d1fd",
    "Cookie": "; ".join([f"{k}={v}" for k, v in cookies.items()]),
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)"
}

# ===== USER PREFERENCES =====
BOOKING_PREFERENCES = {
    "centers": [1106, 1107],
    "preferred_timings": [
        {"hour": 8, "minute": 0},
        {"hour": 9, "minute": 0}
    ],
    "sport_id": 350,  # Badminton
    "enabled": True
}

# Global flag to track success
booking_completed = False


# -------- FETCH DATA --------
def get_center_schedule(center_id):
    url = f"https://www.cult.fit/api/v2/fitso/web/schedule?centerId={center_id}"
    response = requests.get(url=url, headers=headers, timeout=7)
    return response.json()


# -------- TIME UTILITIES --------
def convert_utc_to_timestamp(utc_string):
    try:
        dt_str = utc_string.replace(' GMT', '')
        dt = datetime.strptime(dt_str, '%a, %d %b %Y %H:%M:%S')
        timestamp_seconds = int(dt.replace(tzinfo=timezone.utc).timestamp())
        return timestamp_seconds * 1000
    except Exception as e:
        print(f"Error converting timestamp: {e}")
        return None


def parse_time_string(time_str):
    try:
        hour, minute = map(int, time_str.split(':')[:2])
        return hour, minute
    except:
        return None, None


def matches_preferred_timing(time_str):
    hour, minute = parse_time_string(time_str)
    if hour is None:
        return False

    for pref in BOOKING_PREFERENCES["preferred_timings"]:
        if hour == pref["hour"] and minute == pref["minute"]:
            return True
    return False


# -------- DISPLAY SLOTS --------
def display_available_slots(schedule_data, sport_id):
    if "classByDateList" not in schedule_data:
        return None

    available = []

    for date_group in schedule_data["classByDateList"]:
        for time_group in date_group["classByTimeList"]:
            for slot in time_group["classes"]:

                if (
                    slot.get("workoutId") == sport_id
                    and slot.get("availableSeats", 0) > 0
                    and matches_preferred_timing(time_group["id"])
                ):
                    print(
                        f"Found slot: Date={date_group['id']} "
                        f"Time={time_group['id']} Seats={slot['availableSeats']}"
                    )

                    available.append({
                        "class_id": slot["id"],
                        "date": date_group["id"],
                        "time": time_group["id"],
                        "start_time_utc": slot["startDateTimeUTC"],
                        "seats": slot["availableSeats"]
                    })

    return available if available else None


# -------- BOOK SLOT --------
def book_slot(center_id, slot_id, workout_id, booking_timestamp):
    payload = {
        "centerId": center_id,
        "slotId": str(slot_id),
        "workoutId": workout_id,
        "bookingTimestamp": booking_timestamp
    }

    url = "https://www.cult.fit/api/v2/fitso/web/class/book"

    try:
        response = requests.post(url=url, headers=headers, json=payload, timeout=7)
        print(f"Status: {response.status_code}")

        data = response.json()
        title = data.get("header", {}).get("title", "")

        if response.status_code == 200 and ("Booked" in title or "confirmed" in title.lower()):
            msg = f"🎉 Booking successful!\nCenter: {center_id}\nSlot ID: {slot_id}\nTime(ts): {booking_timestamp}"
            print(msg)
            send_telegram(msg)
            return True

        # send a short failure note with title if available
        fail_msg = f"❌ Booking not successful for Center {center_id}. Response title: {title}"
        print(fail_msg)
        send_telegram(fail_msg)
        return False

    except Exception as e:
        err = f"Error booking at center {center_id}: {e}"
        print(err)
        send_telegram(err)
        return False


# -------- MAIN BOOKING JOB --------
def booking_task():
    global booking_completed

    if booking_completed:
        print("Booking already done. Skipping.")
        return

    print("\n---------------------------")
    print("Running booking scheduler…")
    print("---------------------------")

    if not BOOKING_PREFERENCES["enabled"]:
        print("Booking disabled in preferences.")
        send_telegram("⚠️ Booking disabled in preferences.")
        return

    any_slot_found = False

    for center_id in BOOKING_PREFERENCES["centers"]:
        print(f"\nChecking center: {center_id}")

        try:
            schedule_data = get_center_schedule(center_id)
            available = display_available_slots(schedule_data, BOOKING_PREFERENCES["sport_id"])

            if available:
                any_slot_found = True
                # Notify about first found slot for this run
                first = available[0]
                slot_msg = (f"🏸 Slot Available!\nCenter: {center_id}\nDate: {first['date']}\n"
                            f"Time: {first['time']}\nSeats: {first['seats']}\nClassID: {first['class_id']}")
                print(slot_msg)
                send_telegram(slot_msg)

                booking_timestamp = convert_utc_to_timestamp(first["start_time_utc"])

                if booking_timestamp:
                    if book_slot(center_id, first["class_id"], BOOKING_PREFERENCES["sport_id"], booking_timestamp):
                        booking_completed = True
                        return
                else:
                    print("Could not convert start_time_utc to timestamp.")
                    send_telegram(f"⚠️ Could not convert slot time to timestamp for Center {center_id}.")

        except Exception as e:
            err = f"Error checking center {center_id}: {e}"
            print(err)
            send_telegram(err)
            continue

    if not any_slot_found:
        print("No matching slots found today.")
        send_telegram("ℹ️ No matching slots found in this run.")


# -------- SCHEDULER --------
def setup_scheduler():
    ist = pytz.timezone("Asia/Kolkata")

    print("\n🕒 Scheduling booking job daily at 22:00 (10 PM IST)")
    schedule.every().day.at("22:00").do(booking_task)

    now = datetime.now(ist)
    print("Current Time:", now)
    print("Next booking attempt: 10 PM IST\n")
    send_telegram(f"⏰ Scheduler started at {now.strftime('%Y-%m-%d %H:%M:%S %Z')}. Next run: 22:00 IST daily.")


def start_scheduler():
    setup_scheduler()
    print("Scheduler started. Press CTRL+C to stop.\n")

    try:
        while True:
            schedule.run_pending()
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("Scheduler stopped.")
        send_telegram("⛔ Scheduler stopped by user.")


# -------- Manual Run --------
def run_booking_now():
    global booking_completed
    booking_completed = False
    booking_task()


# -------- MAIN --------
if __name__ == "__main__":
    start_scheduler()
