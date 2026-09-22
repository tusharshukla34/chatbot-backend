import secrets
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from app.schemas import ChatRequest, ChatResponse, MarkInterestRequest
from app.session_store import get_session, append_message
from app.validators import is_valid_email, is_valid_phone, clean_phone
from app.db import save_lead, save_course_interest, update_selected_course, get_connection
from app.whatsapp_notify import send_lead_notification, send_recommendation_notification, send_selection_notification
from app.config import ADMIN_USERNAME, ADMIN_PASSWORD, ALLOWED_ORIGINS
from app.matching import get_programs, get_subprograms, get_courses_by_program, get_courses_by_subprogram
from app.browse_resolver import resolve_program_exact, resolve_subprogram, REAL_PROGRAMS, is_general_question, is_greeting
from app.llm_client import (
    interpret_program_from_text, general_followup, answer_general_question,
    mirror_language, greeting_reply, course_interest_reply, detect_course_interest,
    name_request_reply, localize_reply, is_actually_a_name,
)

app = FastAPI(title="Course Advisor Chatbot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBasic()

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@app.get("/admin/leads")
def admin_leads(username: str = Depends(verify_admin)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM leads ORDER BY id DESC")
    leads = cur.fetchall()
    cur.execute("SELECT * FROM course_interest ORDER BY id DESC")
    interests = cur.fetchall()
    cur.close()
    conn.close()
    return {
        "leads": [dict(row) for row in leads],
        "course_interest": [dict(row) for row in interests],
    }


def get_pending_prompt(session: dict) -> tuple:
    """Returns (question_text, quick_replies) for whatever the bot is currently waiting on."""
    if not session["lead_captured"]:
        stage = session["lead_stage"]
        if stage == "first_name":
            return "By the way, could you share your name?", []
        if stage == "whatsapp":
            return "And what's your WhatsApp number?", []
        if stage == "email":
            return "And your email address?", []

    stage = session["browse_stage"]
    if stage == "education":
        return "What's your current education level?", ["10th pass", "12th pass", "Graduate", "Something else"]
    if stage == "program":
        return "Which area are you interested in?", REAL_PROGRAMS + ["Something else"]
    if stage == "subprogram":
        subs = get_subprograms(session["selected_program"])
        return f"Which {session['selected_program']} track interests you?", subs + ["Something else"]
    if stage == "course":
        titles = [c["title"] for c in session["shown_courses"]]
        return "Which course would you like to know more about?", titles + ["Still deciding"]
    return "Anything else you'd like to know?", []


def handle_lead_capture(req: ChatRequest, session: dict) -> ChatResponse:

    NON_NAME_WORDS = {
        "hi", "hii", "hiii", "hello", "hey", "heya", "yo", "hola", "hell",
        "ok", "okay", "sure", "yes", "no", "test", "namaste",
        "ha", "haa", "haan", "yeah", "yep", "acha", "achha", "theek", "thik", "hmm", "hm",
    }

    text = req.message.strip()
    stage = session["lead_stage"]

    if stage == "first_name":
        cleaned = text.strip()
        fast_invalid = (
            len(cleaned) < 2
            or cleaned.lower() in NON_NAME_WORDS
            or not cleaned.replace(" ", "").isalpha()
        )
        is_invalid = fast_invalid or (not fast_invalid and not is_actually_a_name(cleaned))

        if is_invalid:
            session["name_attempts"] += 1
            if session["name_attempts"] >= 3:
                session["lead_data"]["first_name"] = "Student"
                session["lead_stage"] = "whatsapp"
                base_reply = "No problem, let's continue! What's your WhatsApp number? (with country code if outside India)"
                reply = localize_reply(base_reply, text)
                append_message(req.session_id, "assistant", reply)
                return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[])

            reply = name_request_reply(text)
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[])

        session["lead_data"]["first_name"] = cleaned
        session["lead_stage"] = "whatsapp"
        base_reply = f"Nice to meet you, {cleaned}! What's your WhatsApp number? (with country code if outside India)"
        reply = mirror_language(base_reply, text)
        append_message(req.session_id, "assistant", reply)
        return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[])

    if stage == "whatsapp":
        if not is_valid_phone(text):
            base_reply = "That doesn't look like a valid number — could you enter a 10-digit WhatsApp number?"
            reply = mirror_language(base_reply, text)
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[])
        session["lead_data"]["whatsapp_number"] = clean_phone(text)
        session["lead_stage"] = "email"
        base_reply = "Great, thank you! And what's your email address?"
        reply = mirror_language(base_reply, text)
        append_message(req.session_id, "assistant", reply)
        return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[])

    if stage == "email":
        if not is_valid_email(text):
            base_reply = "That doesn't look like a valid email — could you double check and re-enter it?"
            reply = mirror_language(base_reply, text)
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[])
        session["lead_data"]["email"] = text.strip()
        session["lead_stage"] = "done"
        session["lead_captured"] = True

        from app.config import TEST_MODE
        first_name_to_save = f"[TEST] {session['lead_data']['first_name']}" if TEST_MODE else session["lead_data"]["first_name"]
        save_lead(
            session_id=req.session_id,
            first_name=first_name_to_save,
            whatsapp_number=session["lead_data"]["whatsapp_number"],
            email=session["lead_data"]["email"],
        )

        send_lead_notification(
            first_name=session["lead_data"]["first_name"],
            whatsapp_number=session["lead_data"]["whatsapp_number"],
            email=session["lead_data"]["email"],
        )

        name = session["lead_data"]["first_name"]
        base_reply = f"Perfect, all set {name}! What's your current education level?"
        reply = mirror_language(base_reply, text)
        append_message(req.session_id, "assistant", reply)
        quick_replies = ["10th pass", "12th pass", "Graduate", "Something else"]
        return ChatResponse(reply=reply, suggested_courses=[], quick_replies=quick_replies)


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    append_message(req.session_id, "user", req.message)
    session = get_session(req.session_id)
    text = req.message.strip()

    is_very_first_message = (
        not session["lead_captured"]
        and session["lead_stage"] == "first_name"
        and not session["lead_data"]["first_name"]
    )
    if is_very_first_message:
        if is_greeting(text):
            reply = greeting_reply()
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[])
        if detect_course_interest(text):
            reply = course_interest_reply()
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[])

    if is_general_question(text):
        answer = answer_general_question(text, session["history"])
        pending_question, quick_replies = get_pending_prompt(session)
        localized_question = localize_reply(pending_question, text)
        reply = f"{answer}\n\n{localized_question}"
        append_message(req.session_id, "assistant", reply)
        return ChatResponse(reply=reply, suggested_courses=[], quick_replies=quick_replies)

    if not session["lead_captured"]:
        return handle_lead_capture(req, session)

    stage = session["browse_stage"]

    # ---- Step 1: education level ----
    if stage == "education":
        if len(text) < 2:
            base_reply = "Could you tell me your education level?"
            reply = localize_reply(base_reply, text)
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[],
                                 quick_replies=["10th pass", "12th pass", "Graduate", "Something else"])
        session["profile"]["education_level"] = text
        session["browse_stage"] = "program"
        base_reply = "Great! Which area are you interested in?"
        reply = localize_reply(base_reply, text)
        append_message(req.session_id, "assistant", reply)
        return ChatResponse(reply=reply, suggested_courses=[], quick_replies=REAL_PROGRAMS + ["Something else"])

    # ---- Step 2: program selection ----
    if stage == "program":
        program = resolve_program_exact(text)
        if not program:
            program = interpret_program_from_text(text)
        if not program:
            base_reply = "I couldn't quite match that. Could you pick one of these areas?"
            reply = localize_reply(base_reply, text)
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=REAL_PROGRAMS + ["Something else"])

        session["selected_program"] = program
        subs = get_subprograms(program)

        if subs:
            session["browse_stage"] = "subprogram"
            base_reply = f"{program} has a few tracks — which one interests you?"
            reply = localize_reply(base_reply, text)
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=subs + ["Something else"])

        courses = get_courses_by_program(program)
        session["shown_courses"] = courses
        session["browse_stage"] = "course"

        lead = session["lead_data"]
        row_id = save_course_interest(
            session_id=req.session_id, first_name=lead["first_name"],
            whatsapp_number=lead["whatsapp_number"], email=lead["email"],
            recommended_courses=", ".join(c["title"] for c in courses),
        )
        session["course_interest_id"] = row_id
        send_recommendation_notification(
            first_name=lead["first_name"], whatsapp_number=lead["whatsapp_number"],
            email=lead["email"], recommended_courses=", ".join(c["title"] for c in courses),
        )

        base_reply = f"Here are all our {program} courses — tap one to see details!"
        reply = localize_reply(base_reply, text)
        append_message(req.session_id, "assistant", reply)
        quick_replies = [c["title"] for c in courses] + ["Still deciding"]
        return ChatResponse(reply=reply, suggested_courses=courses, quick_replies=quick_replies)

    # ---- Step 3: subprogram selection ----
    if stage == "subprogram":
        program = session["selected_program"]
        subs = get_subprograms(program)
        subprogram = resolve_subprogram(subs, text)
        if not subprogram:
            base_reply = "Please pick one of the tracks shown, or tell me which interests you."
            reply = localize_reply(base_reply, text)
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=subs + ["Something else"])

        session["selected_subprogram"] = subprogram
        courses = get_courses_by_subprogram(program, subprogram)
        session["shown_courses"] = courses
        session["browse_stage"] = "course"

        lead = session["lead_data"]
        row_id = save_course_interest(
            session_id=req.session_id, first_name=lead["first_name"],
            whatsapp_number=lead["whatsapp_number"], email=lead["email"],
            recommended_courses=", ".join(c["title"] for c in courses),
        )
        session["course_interest_id"] = row_id
        send_recommendation_notification(
            first_name=lead["first_name"], whatsapp_number=lead["whatsapp_number"],
            email=lead["email"], recommended_courses=", ".join(c["title"] for c in courses),
        )

        base_reply = f"Here are our {subprogram} courses — tap one to see details!"
        reply = localize_reply(base_reply, text)
        append_message(req.session_id, "assistant", reply)
        quick_replies = [c["title"] for c in courses] + ["Still deciding"]
        return ChatResponse(reply=reply, suggested_courses=courses, quick_replies=quick_replies)

    # ---- Step 4: exact course selection ----
    if stage == "course":
        titles = [c["title"] for c in session["shown_courses"]]

        if text == "Still deciding":
            base_reply = "No worries, take your time! Let me know if you have any questions about these courses."
            reply = localize_reply(base_reply, text)
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=titles + ["Still deciding"])

        if text in titles:
            session["selected_course"] = text
            session["browse_stage"] = "post_selection"
            lead = session["lead_data"]
            if session["course_interest_id"]:
                update_selected_course(session["course_interest_id"], text)
            send_selection_notification(
                first_name=lead["first_name"], whatsapp_number=lead["whatsapp_number"],
                email=lead["email"], selected_course=text,
            )
            base_reply = f"Great choice! I've noted your interest in {text}. Our team will reach out with next steps. Anything else you'd like to know?"
            reply = localize_reply(base_reply, text)
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[])

        reply = general_followup(session["history"], session["shown_courses"])
        append_message(req.session_id, "assistant", reply)
        return ChatResponse(reply=reply, suggested_courses=[], quick_replies=titles + ["Still deciding"])

    # ---- Step 5: after a final selection ----
    reply = general_followup(session["history"], session["shown_courses"])
    append_message(req.session_id, "assistant", reply)
    return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[])


@app.post("/mark-interest")
def mark_interest(req: MarkInterestRequest):
    session = get_session(req.session_id)
    lead = session["lead_data"]
    if session.get("course_interest_id"):
        update_selected_course(session["course_interest_id"], req.course_title)
    send_selection_notification(
        first_name=lead.get("first_name", ""), whatsapp_number=lead.get("whatsapp_number", ""),
        email=lead.get("email", ""), selected_course=req.course_title,
    )
    session["selected_course"] = req.course_title
    return {"status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok"}