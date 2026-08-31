from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.schemas import ChatRequest, ChatResponse
from app.session_store import get_session, append_message, update_profile
from app.llm_client import extract_and_reply, phrase_recommendation, general_followup, no_match_reply
from app.matching import match_courses
from app.validators import is_valid_email, is_valid_phone, clean_phone
from app.db import save_lead, save_course_interest, update_selected_course
from app.whatsapp_notify import send_lead_notification, send_recommendation_notification, send_selection_notification

app = FastAPI(title="Course Advisor Chatbot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.db import get_connection

@app.get("/admin/leads")
def admin_leads():
    conn = get_connection()
    leads = conn.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
    interests = conn.execute("SELECT * FROM course_interest ORDER BY id DESC").fetchall()
    conn.close()
    return {
        "leads": [dict(row) for row in leads],
        "course_interest": [dict(row) for row in interests],
    }


def get_quick_replies(profile: dict) -> list:
    if not profile.get("education_level"):
        return ["10th pass", "12th pass", "Graduate", "Something else"]
    if not profile.get("interests"):
        return ["Web Development", "Cyber Security", "Data Science", "AI/ML", "Digital Marketing", "Something else"]
    if not profile.get("mode_preference"):
        return ["Online", "Offline", "Hybrid", "Something else"]
    return []


def handle_lead_capture(req: ChatRequest, session: dict) -> ChatResponse:
    text = req.message.strip()
    stage = session["lead_stage"]

    if stage == "first_name":
        NON_NAME_WORDS = {
            "hi", "hii", "hiii", "hello", "hey", "heya", "yo", "hola",
            "ok", "okay", "sure", "yes", "no", "test", "namaste"
        }
        cleaned = text.strip()
        if len(cleaned) < 2 or cleaned.lower() in NON_NAME_WORDS or not cleaned.replace(" ", "").isalpha():
            reply = "That doesn't look like a name — could you tell me your actual first name?"
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[])
        session["lead_data"]["first_name"] = cleaned
        session["lead_stage"] = "whatsapp"
        reply = f"Nice to meet you, {cleaned}! What's your WhatsApp number? (with country code if outside India)"
        append_message(req.session_id, "assistant", reply)
        return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[])

    if stage == "whatsapp":
        if not is_valid_phone(text):
            reply = "That doesn't look like a valid number — could you enter a 10-digit WhatsApp number?"
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[])
        session["lead_data"]["whatsapp_number"] = clean_phone(text)
        session["lead_stage"] = "email"
        reply = "Great, thank you! And what's your email address?"
        append_message(req.session_id, "assistant", reply)
        return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[])

    if stage == "email":
        if not is_valid_email(text):
            reply = "That doesn't look like a valid email — could you double check and re-enter it?"
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[])
        session["lead_data"]["email"] = text.strip()
        session["lead_stage"] = "done"
        session["lead_captured"] = True

        save_lead(
            session_id=req.session_id,
            first_name=session["lead_data"]["first_name"],
            whatsapp_number=session["lead_data"]["whatsapp_number"],
            email=session["lead_data"]["email"],
        )
        send_lead_notification(
            first_name=session["lead_data"]["first_name"],
            whatsapp_number=session["lead_data"]["whatsapp_number"],
            email=session["lead_data"]["email"],
        )

        name = session["lead_data"]["first_name"]
        reply = f"Perfect, all set {name}! Now let's find the right course for you — what's your current education level?"
        append_message(req.session_id, "assistant", reply)
        quick_replies = ["10th pass", "12th pass", "Graduate", "Something else"]
        return ChatResponse(reply=reply, suggested_courses=[], quick_replies=quick_replies)


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    append_message(req.session_id, "user", req.message)
    session = get_session(req.session_id)

    if not session["lead_captured"]:
        return handle_lead_capture(req, session)

    if not session["has_recommended"]:
        result = extract_and_reply(session["history"])
        update_profile(req.session_id, result.get("profile", {}))

        if result.get("ready_for_recommendation"):
            matches = match_courses(session["profile"])

            if not matches:
                reply = no_match_reply(session["profile"].get("interests", []))
                append_message(req.session_id, "assistant", reply)
                return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[])

            reply = phrase_recommendation(session["history"], matches)
            session["has_recommended"] = True
            session["last_matches"] = matches
            session["awaiting_selection"] = True
            append_message(req.session_id, "assistant", reply)

            lead = session["lead_data"]
            course_titles = ", ".join(c["title"] for c in matches)
            row_id = save_course_interest(
                session_id=req.session_id,
                first_name=lead["first_name"],
                whatsapp_number=lead["whatsapp_number"],
                email=lead["email"],
                recommended_courses=course_titles,
            )
            session["course_interest_id"] = row_id
            send_recommendation_notification(
                first_name=lead["first_name"],
                whatsapp_number=lead["whatsapp_number"],
                email=lead["email"],
                recommended_courses=course_titles,
            )

            selection_options = [c["title"] for c in matches] + ["Still deciding"]
            return ChatResponse(reply=reply, suggested_courses=matches, quick_replies=selection_options)

        reply = result["reply"]
        append_message(req.session_id, "assistant", reply)
        quick_replies = get_quick_replies(session["profile"])
        return ChatResponse(reply=reply, suggested_courses=[], quick_replies=quick_replies)




    # check if this message is a course selection (button click with exact title, or "Still deciding")
    if session["awaiting_selection"]:
        matched_titles = [c["title"] for c in session["last_matches"]]
        user_text = req.message.strip()

        if user_text == "Still deciding":
            session["awaiting_selection"] = False
            reply = "No worries, take your time! Let me know if you have any questions about these courses."
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[])

        if user_text in matched_titles:
            session["awaiting_selection"] = False
            session["selection_finalized"] = True
            lead = session["lead_data"]
        
            if session["course_interest_id"]:
                update_selected_course(session["course_interest_id"], user_text)
            send_selection_notification(
                first_name=lead["first_name"],
                whatsapp_number=lead["whatsapp_number"],
                email=lead["email"],
                selected_course=user_text,
            )
            reply = f"Great choice! I've noted your interest in {user_text}. Our team will reach out with next steps. Anything else you'd like to know about it?"
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[])

        # normal follow-up conversation
    result = general_followup(session["history"], session["last_matches"])
    reply = result.get("reply", "")
    matched_titles = [c["title"] for c in session["last_matches"]]
    relevant_titles = set(result.get("relevant_course_titles", matched_titles))

    updated_matches = [c for c in session["last_matches"] if c["title"] in relevant_titles]
    session["last_matches"] = updated_matches

    append_message(req.session_id, "assistant", reply)

    # once a final selection is made, stop re-sending course cards on every follow-up
    if session["selection_finalized"]:
        return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[])

    # if we're still waiting on a final selection, re-offer buttons for whatever remains
    if session["awaiting_selection"] and updated_matches:
        selection_options = [c["title"] for c in updated_matches] + ["Still deciding"]
        return ChatResponse(reply=reply, suggested_courses=updated_matches, quick_replies=selection_options)

    return ChatResponse(reply=reply, suggested_courses=updated_matches, quick_replies=[])


@app.get("/health")
def health():
    return {"status": "ok"}