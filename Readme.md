<div align="center">

  <h1>🏸 Cult.fit Auto-Booking Bot 🏸</h1>

  <p>
    <strong>A simple, powerful Python script to automatically book your favorite Cult.fit Play sessions.</strong>
  </p>

  <p>
    <img alt="Python" src="https://img.shields.io/badge/Python-3.10+-blue?style=for-the-badge&logo=python">
    <img alt="GitHub Actions" src="https://img.shields.io/badge/GitHub_Actions-2088FF?style=for-the-badge&logo=github-actions&logoColor=white">
  </p>
</div>

This bot runs automatically on a schedule using GitHub Actions, waits for the booking window to open (e.g., 10 PM IST), and instantly books a slot based on your ordered preferences. It even sends you status updates on Telegram!

---

## ⭐ Features

- **🎯 Priority-Based Booking**: Books slots according to your preferred time order (e.g., tries for 8 PM before 9 AM).
- **🗓️ Future Date Targeting**: Specifically targets bookings for a set number of days in the future (e.g., 4 days from today).
- **🤖 Fully Automated**: Runs on a schedule using GitHub Actions. Set it and forget it!
- **📢 Telegram Notifications**: Get real-time alerts when the script starts, finds a slot, and confirms a booking.
- **⚙️ Easy Configuration**: All preferences and secrets are managed in one place.
- **🔁 Multi-Center Support**: Automatically cycles through your list of preferred centers.

## 🚀 Getting Started

Follow these steps to get your personal booking bot up and running.

### 1. Fork the Repository

First, **fork this repository** to your own GitHub account. This allows GitHub Actions to run on your copy.
p
### 2. Configure Your Preferences

Open `app.py` and edit the `BOOKING_PREFERENCES` dictionary to match your needs.

```python
BOOKING_PREFERENCES = {
    "centers":,  # Your preferred center IDs
    "preferred_timings": [     # List timings in order of preference
        {"hour": 20, "minute": 0},  # 8:00 PM
        {"hour": 9, "minute": 0}    # 9:00 AM
    ],
    "sport_id": 350            # 350 for Badminton, 351 for Pickleball
}
```

### 3. Add Your Secrets

The script needs your Cult.fit API keys and Telegram details to work. Add these as **repository secrets** in your forked repo.

Go to `Settings` > `Secrets and variables` > `Actions` and add the following:

| Secret Name          | Description                                    |
| -------------------- | ---------------------------------------------- |
| `CULT_API_KEY`       | Your Cult.fit API key.                         |
| `CULT_ST_COOKIE`     | The `st` authentication cookie.                |
| `CULT_AT_COOKIE`     | The `at` authentication cookie.                |
| `TELEGRAM_BOT_TOKEN` | Your Telegram bot's token.                     |
| `TELEGRAM_CHAT_ID`   | The chat ID to which notifications are sent.   |

> **💡 How to get Cult.fit credentials?**
> 1. Log in to `cult.fit` in a desktop web browser.
> 2. Open Developer Tools (`F12` or `Cmd+Opt+I`).
> 3. Go to the **Network** tab.
> 4. Refresh the page or click on a schedule. Find any request to the Cult API (e.g., a `schedule` request).
> 5. In the **Headers** tab of that request, find and copy the `apiKey`.
> 6. In the same request headers, scroll down to `Cookie` and copy the values for the `st` and `at` cookies.

### 4. Enable GitHub Actions

Go to the **Actions** tab in your forked repository. If you see a prompt to enable workflows, click "I understand my workflows, go ahead and enable them."

## ⚙️ How It Works

The workflow is defined in `.github/workflows/cult_booking.yml`.

1.  **Scheduled Trigger**: A `cron` job triggers the workflow at a set time (e.g., daily at 9:55 PM IST).
2.  **Manual Trigger**: You can also run it manually anytime using the `workflow_dispatch` button in the Actions tab.
3.  **Execution**:
    - The script starts and waits until exactly 10:00 PM IST.
    - It calculates the target booking date (e.g., 4 days from now).
    - It iterates through your preferred centers.
    - For each center, it fetches the schedule and looks for an available slot that matches your sport and time preferences, respecting the order you defined.
    - If a match is found, it attempts to book it immediately.
    - On success, it sends a confirmation to your Telegram and exits.
    - If no slots are found, it notifies you and finishes.

### Changing the Schedule

To change when the script runs, edit the `cron` expression in `.github/workflows/cult_booking.yml`. The time is in **UTC**.

```yaml
on:
  schedule:
    # Runs at 16:25 UTC, which is 9:55 PM IST.
    - cron: '25 16 * * *'
```

---

Happy booking! 🎉

