from typing import Optional
from app.notifiers import dispatcher


def send_lead_notification(first_name: str, whatsapp_number: str, email: str):
    message = (
        f"🎓 New Lead Captured\n"
        f"Name: {first_name}\n"
        f"WhatsApp: {whatsapp_number}\n"
        f"Email: {email}"
    )
    dispatcher.dispatch(
        "lead_captured",
        message,
        {"first_name": first_name, "whatsapp_number": whatsapp_number, "email": email},
    )


def send_recommendation_notification(first_name: str, whatsapp_number: str, email: str, recommended_courses: str):
    message = (
        f"📚 Courses Shown\n"
        f"Name: {first_name}\n"
        f"WhatsApp: {whatsapp_number}\n"
        f"Email: {email}\n"
        f"Courses: {recommended_courses}"
    )
    dispatcher.dispatch(
        "recommendation_shown",
        {
            "first_name": first_name,
            "whatsapp_number": whatsapp_number,
            "email": email,
            "recommended_courses": recommended_courses,
        },
    )


def send_selection_notification(first_name: str, whatsapp_number: str, email: str, selected_course: str):
    message = (
        f"✅ Course Selected!\n"
        f"Name: {first_name}\n"
        f"WhatsApp: {whatsapp_number}\n"
        f"Email: {email}\n"
        f"Chose: {selected_course}"
    )
    dispatcher.dispatch(
        "course_selected",
        {
            "first_name": first_name,
            "whatsapp_number": whatsapp_number,
            "email": email,
            "selected_course": selected_course,
        },
    )


def send_handoff_notification(first_name: str, whatsapp_number: str, email: str, reason: str = ""):
    message = (
        f"🚨 Counselor Call Requested!\n"
        f"Name: {first_name or 'Prospective Student'}\n"
        f"WhatsApp: {whatsapp_number or 'Not provided yet'}\n"
        f"Email: {email or 'Not provided yet'}\n"
        f"Reason: {reason or 'Requested human counselor'}"
    )
    dispatcher.dispatch(
        "counselor_callback",
        message,
        {"first_name": first_name, "whatsapp_number": whatsapp_number, "email": email, "reason": reason},
    )