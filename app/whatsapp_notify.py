import requests
from app.config import CALLMEBOT_PHONE, CALLMEBOT_APIKEY

CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"


from app.config import TEST_MODE

def _send(message: str):
    if TEST_MODE:
        print("[WhatsApp] Skipped — TEST_MODE is on")
        return
    if not CALLMEBOT_PHONE or not CALLMEBOT_APIKEY:
        print("[WhatsApp] Skipped — CALLMEBOT_PHONE or CALLMEBOT_APIKEY not set in .env")
        return
    try:
        params = {"phone": CALLMEBOT_PHONE, "text": message, "apikey": CALLMEBOT_APIKEY}
        response = requests.get(CALLMEBOT_URL, params=params, timeout=10)
        if response.status_code == 200:
            print("[WhatsApp] Notification sent")
        else:
            print(f"[WhatsApp] Failed ({response.status_code}): {response.text}")
    except requests.RequestException as e:
        print(f"[WhatsApp] Error sending notification: {e}")


def send_recommendation_notification(first_name: str, whatsapp_number: str, email: str, recommended_courses: str):
    message = (
        f"📚 Courses Recommended\n"
        f"Name: {first_name}\n"
        f"WhatsApp: {whatsapp_number}\n"
        f"Email: {email}\n"
        f"Recommended: {recommended_courses}"
    )
    _send(message)


def send_selection_notification(first_name: str, whatsapp_number: str, email: str, selected_course: str):
    message = (
        f"✅ Course Selected!\n"
        f"Name: {first_name}\n"
        f"WhatsApp: {whatsapp_number}\n"
        f"Email: {email}\n"
        f"Chose: {selected_course}"
    )
    _send(message)