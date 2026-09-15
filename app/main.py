from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.schemas import ChatRequest, ChatResponse, MarkInterestRequest
from app.session_store import get_session, append_message
from app.llm_client import interpret_program_from_text, general_followup
from app.matching import get_programs, get_subprograms, get_courses_by_program, get_courses_by_subprogram
from app.browse_resolver import resolve_program_exact, resolve_subprogram, REAL_PROGRAMS
from app.validators import is_valid_email, is_valid_phone, clean_phone
from app.db import save_lead, save_course_interest, update_selected_course, get_connection
from app.whatsapp_notify import send_lead_notification, send_recommendation_notification, send_selection_notification

app = FastAPI(title="Course Advisor Chatbot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/admin/leads")
def admin_leads():
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


def handle_lead_capture(req: ChatRequest, session: dict) -> ChatResponse:
    NON_NAME_WORDS = {
        "hi", "hii", "hiii", "hello", "hey", "heya", "yo", "hola",
        "ok", "okay", "sure", "yes", "no", "test", "namaste"
    }
    text = req.message.strip()
    stage = session["lead_stage"]

    if stage == "first_name":
        cleaned = text.strip()
        if (len(cleaned) < 2
                or cleaned.lower() in NON_NAME_WORDS
                or not cleaned.replace(" ", "").isalpha()):
            reply = "That doesn't look like a name — could you share your name?"
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
        reply = f"Perfect, all set {name}! What's your current education level?"
        append_message(req.session_id, "assistant", reply)
        quick_replies = ["10th pass", "12th pass", "Graduate", "Something else"]
        return ChatResponse(reply=reply, suggested_courses=[], quick_replies=quick_replies)


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    append_message(req.session_id, "user", req.message)
    session = get_session(req.session_id)
    text = req.message.strip()

    if not session["lead_captured"]:
        return handle_lead_capture(req, session)

    stage = session["browse_stage"]

    # ---- Step 1: education level (informational, no filtering applied) ----
    if stage == "education":
        if len(text) < 2:
            reply = "Could you tell me your education level?"
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[],
                                 quick_replies=["10th pass", "12th pass", "Graduate", "Something else"])
        session["profile"]["education_level"] = text
        session["browse_stage"] = "program"
        reply = "Great! Which area are you interested in?"
        append_message(req.session_id, "assistant", reply)
        return ChatResponse(reply=reply, suggested_courses=[], quick_replies=REAL_PROGRAMS + ["Something else"])

    # ---- Step 2: program selection ----
    if stage == "program":
        program = resolve_program_exact(text)
        if not program:
            program = interpret_program_from_text(text)
        if not program:
            reply = "I couldn't quite match that. Could you pick one of these areas?"
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=REAL_PROGRAMS + ["Something else"])

        session["selected_program"] = program
        subs = get_subprograms(program)

        if subs:
            session["browse_stage"] = "subprogram"
            reply = f"{program} has a few tracks — which one interests you?"
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

        reply = f"Here are all our {program} courses — tap one to see details!"
        append_message(req.session_id, "assistant", reply)
        quick_replies = [c["title"] for c in courses] + ["Still deciding"]
        return ChatResponse(reply=reply, suggested_courses=courses, quick_replies=quick_replies)

    # ---- Step 3: subprogram selection (Fullstack Web only) ----
    if stage == "subprogram":
        program = session["selected_program"]
        subs = get_subprograms(program)
        subprogram = resolve_subprogram(subs, text)
        if not subprogram:
            reply = "Please pick one of the tracks shown, or tell me which interests you."
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

        reply = f"Here are our {subprogram} courses — tap one to see details!"
        append_message(req.session_id, "assistant", reply)
        quick_replies = [c["title"] for c in courses] + ["Still deciding"]
        return ChatResponse(reply=reply, suggested_courses=courses, quick_replies=quick_replies)

    # ---- Step 4: exact course selection ----
    if stage == "course":
        titles = [c["title"] for c in session["shown_courses"]]

        if text == "Still deciding":
            reply = "No worries, take your time! Let me know if you have any questions about these courses."
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
            reply = f"Great choice! I've noted your interest in {text}. Our team will reach out with next steps. Anything else you'd like to know?"
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[])

        # free-text question while browsing this course list
        reply = general_followup(session["history"], session["shown_courses"])
        append_message(req.session_id, "assistant", reply)
        return ChatResponse(reply=reply, suggested_courses=[], quick_replies=titles + ["Still deciding"])

    # ---- Step 5: after a final selection, just chat normally ----
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