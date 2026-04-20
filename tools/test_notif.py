import os
import requests
from dotenv import load_dotenv

load_dotenv()

token = os.getenv("TELEGRAM_BOT_TOKEN")
group_id = os.getenv("TELEGRAM_LOG_GROUP_ID")

if not token or not group_id:
    print("Missing credentials")
    exit(1)

url = f"https://api.telegram.org/bot{token}/sendMessage"
payload = {
    "chat_id": group_id,
    "text": "<b>🧪 TEST NOTIFICATION</b>\nIf you see this, credentials are correct.",
    "parse_mode": "HTML"
}

resp = requests.post(url, json=payload)
print(f"Status: {resp.status_code}")
print(f"Response: {resp.text}")
