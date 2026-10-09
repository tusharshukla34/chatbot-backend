import csv
import io
import logging
import secrets
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    ALLOWED_ORIGINS,
    LEAD_CAPTURE_TIMING,
    TEST_MODE,
)
from app.db import (
    get_all_callbacks,
    get_all_course_interests,
    get_all_leads,
    get_offline_queue_count,
    init_db,
    is_db_healthy,
    save_callback_request,
    save_course_interest,
    save_lead,
    update_selected_course,
)
from app.course_store import course_store
from app.logging_config import setup_structured_logging
from app.matching import (
    get_courses_by_program,
    get_courses_by_subprogram,
    get_programs,
    get_subprograms,
)
from app.browse_resolver import (
    REAL_PROGRAMS,
    is_abusive,
    is_complaint,
    is_general_question,
    is_greeting,
    is_handoff_request,
    resolve_program_exact,
    resolve_subprogram,
)
from app.llm_client import (
    abusive_or_offtopic_reply,
    answer_general_question,
    answer_grounded_interruption,
    classify_intent,
    course_interest_reply,
    detect_course_interest,
    general_followup,
    greeting_reply,
    handoff_reply,
    interpret_program_from_text,
    is_actually_a_name,
    localize_reply,
    mirror_language,
    name_request_reply,
)
from app.schemas import (
    CallbackRequestSchema,
    ChatRequest,
    ChatResponse,
    HealthResponse,
    MarkInterestRequest,
)
from app.security import (
    check_rate_limit,
    constant_time_auth,
    mask_email,
    mask_phone,
)
from app.session_store import (
    append_message,
    get_session,
    get_session_store_status,
    save_session,
)
from app.validators import clean_email, clean_name, clean_phone, is_valid_email, is_valid_phone
from app.whatsapp_notify import (
    send_handoff_notification,
    send_lead_notification,
    send_recommendation_notification,
    send_selection_notification,
)

logger = logging.getLogger("course_chatbot.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_structured_logging()
    logger.info("Initializing Course Advisor Chatbot service...")
    try:
        init_db()
    except Exception as e:
        logger.warning(f"Startup database initialization error: {e}")
    yield
    logger.info("Course Advisor Chatbot service shutting down...")


app = FastAPI(title="Course Advisor Chatbot", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBasic()


def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if not constant_time_auth(credentials.username, credentials.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@app.get("/admin/leads")
def admin_leads(page: int = 1, limit: int = 50, username: str = Depends(verify_admin)):
    all_l = get_all_leads()
    all_i = get_all_course_interests()
    all_c = get_all_callbacks()

    start_idx = max(0, (page - 1) * limit)
    end_idx = start_idx + limit

    return {
        "page": page,
        "limit": limit,
        "total_leads": len(all_l),
        "leads": all_l[start_idx:end_idx],
        "course_interest": all_i[start_idx:end_idx],
        "callbacks": all_c[start_idx:end_idx],
    }


@app.get("/admin/leads/export")
def export_leads_csv(username: str = Depends(verify_admin)):
    all_l = get_all_leads()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Session ID", "First Name", "WhatsApp Number", "Email", "Consent", "Created At"])
    for row in all_l:
        writer.writerow([
            row.get("id", ""),
            row.get("session_id", ""),
            row.get("first_name", ""),
            row.get("whatsapp_number", ""),
            row.get("email", ""),
            row.get("consent", True),
            row.get("created_at", ""),
        ])
    output.seek(0)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=cybrom_leads.csv"},
    )


@app.get("/admin/stats")
def admin_stats(username: str = Depends(verify_admin)):
    all_l = get_all_leads()
    all_i = get_all_course_interests()
    all_c = get_all_callbacks()

    daily_leads = defaultdict(int)
    for l in all_l:
        created = l.get("created_at", "")
        day = created[:10] if len(created) >= 10 else "Unknown"
        daily_leads[day] += 1

    selected_counts = defaultdict(int)
    for i in all_i:
        c_sel = i.get("selected_course")
        if c_sel:
            selected_counts[c_sel] += 1

    return {
        "total_leads": len(all_l),
        "total_course_interests": len(all_i),
        "total_callbacks_requested": len(all_c),
        "daily_leads": dict(daily_leads),
        "top_selected_courses": sorted(selected_counts.items(), key=lambda x: x[1], reverse=True)[:10],
    }


@app.get("/health", response_model=HealthResponse)
def health():
    db_ok = is_db_healthy()
    store_status = get_session_store_status()
    queue_pending = get_offline_queue_count()
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "session_store": store_status,
        "offline_queue_pending": queue_pending,
    }


def get_pending_prompt(session: Dict[str, Any]) -> Tuple[str, List[str], int, str]:
    if LEAD_CAPTURE_TIMING == "early" and not session.get("lead_captured", False):
        stage = session.get("lead_stage", "first_name")
        if stage == "first_name":
            return "By the way, could you share your name?", [], 1, "Level"
        if stage == "whatsapp":
            return "And what's your WhatsApp number?", [], 1, "Level"
        if stage == "email":
            return "And your email address?", [], 1, "Level"

    b_stage = session.get("browse_stage", "education")
    if b_stage == "education":
        return "What's your current education level?", ["10th pass", "12th pass", "Graduate", "Something else"], 1, "Level"
    if b_stage == "program":
        return "Which area are you interested in?", REAL_PROGRAMS + ["Something else"], 2, "Interest"
    if b_stage == "subprogram":
        subs = get_subprograms(session.get("selected_program", ""))
        return f"Which {session.get('selected_program', '')} track interests you?", subs + ["Something else"], 3, "Mode"
    if b_stage == "course":
        titles = [c.get("title", "") for c in session.get("shown_courses", [])]
        return "Which course would you like to know more about?", titles + ["Still deciding"], 4, "Matches"
    if b_stage == "post_selection":
        sel = session.get("selected_course", "your selected course")
        return (
            f"Aur koi sawaal hai {sel} ya Cybrom ke baare mein?",
            ["Fee & Batch details", "Placement assistance", "Talk to counselor", "Explore other courses"],
            4,
            "Matches",
        )

    return "Anything else you'd like to know?", [], 4, "Matches"


def expresses_alternative_or_dislike(text: str) -> bool:
    """Detects if student expresses dislike of a topic, wants alternatives, or asks for a different domain."""
    t = text.strip().lower()
    dislike_keywords = [
        "nahi pasand", "pasand nahi", "not interested", "dont like", "don't like",
        "nahi karni", "nahi karna", "nahi chahiye", "kuch aur", "koi aur",
        "no python", "without python", "without coding", "non coding", "non-coding",
        "bina coding", "maths weak", "alternative", "other options", "dusra option",
        "dusre course", "different course", "change track", "switch", "kuch dusra"
    ]
    return any(k in t for k in dislike_keywords)


def find_subprogram_in_catalog(text: str) -> Optional[Tuple[str, str]]:
    """Matches text against any known track/subprogram in the catalog."""
    t = text.strip().lower()
    aliases = {
        "mern": ("Fullstack Web", "MERNSTACK"),
        "mernstack": ("Fullstack Web", "MERNSTACK"),
        "react": ("Fullstack Web", "MERNSTACK"),
        "node": ("Fullstack Web", "MERNSTACK"),
        "java": ("Fullstack Web", "Java"),
        "springboot": ("Fullstack Web", "Java"),
        "ethical hacking": ("Cyber Security", "Cyber Security & Ethical Hacking"),
        "cyber": ("Cyber Security", "Cyber Security & Ethical Hacking"),
        "cyber security": ("Cyber Security", "Cyber Security & Ethical Hacking"),
        "cybersecurity": ("Cyber Security", "Cyber Security & Ethical Hacking"),
        "devops": ("Cyber Security", "DevOps & Cloud"),
        "cloud": ("Cyber Security", "DevOps & Cloud"),
        "aws": ("Cyber Security", "DevOps & Cloud"),
        "data analytics": ("Data Programs", "Data Analytics"),
        "data analyst": ("Data Programs", "Data Analytics"),
        "power bi": ("Data Programs", "Data Analytics"),
        "powerbi": ("Data Programs", "Data Analytics"),
        "sql": ("Data Programs", "Data Analytics"),
    }
    for alias, result in aliases.items():
        if alias in t:
            return result

    all_courses = course_store.all_courses()
    for c in all_courses:
        p = c.get("program", "")
        s = (c.get("subprogram") or "").strip()
        if s and (t == s.lower() or t in s.lower() or (len(t) > 3 and t in s.lower())):
            return p, s
    return None


def is_answering_current_flow(session: Dict[str, Any], text: str) -> bool:
    """Returns True if user text directly fulfills the pending step and shouldn't be hijacked as an interruption."""
    t = text.strip()
    if not t or is_general_question(t):
        return False

    # Lead capture check (early timing)
    if LEAD_CAPTURE_TIMING == "early" and not session.get("lead_captured", False):
        stage = session.get("lead_stage", "first_name")
        if stage == "whatsapp" and is_valid_phone(t):
            return True
        if stage == "email" and is_valid_email(clean_email(t)):
            return True
        if stage == "first_name":
            cleaned = clean_name(t)
            if len(cleaned) >= 2 and cleaned.replace(" ", "").isalpha() and len(cleaned.split()) <= 4:
                return True
        return False

    # Browse stages check
    b_stage = session.get("browse_stage", "education")
    if b_stage == "education":
        return len(t) >= 2 and len(t.split()) <= 4 and not is_general_question(t)
    if b_stage == "program":
        if t.lower() in ["something else", "other"]:
            return True
        return bool(resolve_program_exact(t) or interpret_program_from_text(t))
    if b_stage == "subprogram":
        prog = session.get("selected_program", "")
        subs = get_subprograms(prog)
        if t.lower() in ["something else", "all", "all courses", "show all"]:
            return True
        return bool(resolve_subprogram(subs, t))
    if b_stage in ["course", "post_selection"]:
        shown = session.get("shown_courses", [])
        titles = [c.get("title", "").strip().lower() for c in shown]
        if t.lower() == "still deciding" or t.lower() in titles:
            return True
        if expresses_alternative_or_dislike(t):
            return True
        if find_subprogram_in_catalog(t) or resolve_program_exact(t) or interpret_program_from_text(t):
            return True

    return False


def handle_lead_capture(req: ChatRequest, session: Dict[str, Any]) -> ChatResponse:
    NON_NAME_WORDS = {
        "hi", "hii", "hiii", "hello", "hey", "heya", "yo", "hola", "hell",
        "ok", "okay", "sure", "yes", "no", "test", "namaste",
        "ha", "haa", "haan", "yeah", "yep", "acha", "achha", "theek", "thik", "hmm", "hm",
    }

    text = req.message.strip()
    stage = session["lead_stage"]

    if stage == "first_name":
        cleaned = clean_name(text)
        fast_invalid = (
            len(cleaned) < 2
            or cleaned.lower() in NON_NAME_WORDS
            or not cleaned.replace(" ", "").isalpha()
        )
        is_invalid = fast_invalid or (not fast_invalid and not is_actually_a_name(cleaned))

        if is_invalid:
            session["name_attempts"] = session.get("name_attempts", 0) + 1
            if session["name_attempts"] >= 3:
                session["lead_data"]["first_name"] = "Student"
                session["lead_stage"] = "whatsapp"
                save_session(req.session_id, session)
                base_reply = "No problem, let's continue! What's your WhatsApp number? (with country code if outside India)"
                reply = localize_reply(base_reply, text)
                append_message(req.session_id, "assistant", reply)
                return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[], step=1, step_label="Level")

            save_session(req.session_id, session)
            reply = name_request_reply(text)
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[], step=1, step_label="Level")

        session["lead_data"]["first_name"] = cleaned
        session["lead_stage"] = "whatsapp"
        save_session(req.session_id, session)
        base_reply = f"Nice to meet you, {cleaned}! What's your WhatsApp number? (with country code if outside India)"
        reply = mirror_language(base_reply, text)
        append_message(req.session_id, "assistant", reply)
        return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[], step=1, step_label="Level")

    if stage == "whatsapp":
        if not is_valid_phone(text):
            base_reply = "That doesn't look like a valid number — could you enter a 10-digit WhatsApp number?"
            reply = mirror_language(base_reply, text)
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[], step=1, step_label="Level")

        session["lead_data"]["whatsapp_number"] = clean_phone(text)
        session["lead_stage"] = "email"
        save_session(req.session_id, session)
        base_reply = "Great, thank you! And what's your email address?"
        reply = mirror_language(base_reply, text)
        append_message(req.session_id, "assistant", reply)
        return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[], step=1, step_label="Level")

    if stage == "email":
        cleaned_mail = clean_email(text)
        if not is_valid_email(cleaned_mail):
            base_reply = "That doesn't look like a valid email — could you double check and re-enter it?"
            reply = mirror_language(base_reply, text)
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[], step=1, step_label="Level")

        session["lead_data"]["email"] = cleaned_mail
        session["lead_stage"] = "done"
        session["lead_captured"] = True

        first_name_to_save = (
            f"[TEST] {session['lead_data']['first_name']}" if TEST_MODE else session["lead_data"]["first_name"]
        )
        save_lead(
            session_id=req.session_id,
            first_name=first_name_to_save,
            whatsapp_number=session["lead_data"]["whatsapp_number"],
            email=session["lead_data"]["email"],
            consent=True,
        )

        send_lead_notification(
            first_name=session["lead_data"]["first_name"],
            whatsapp_number=session["lead_data"]["whatsapp_number"],
            email=session["lead_data"]["email"],
        )

        logger.info(
            f"Lead successfully saved: session={req.session_id}, phone={mask_phone(session['lead_data']['whatsapp_number'])}, email={mask_email(session['lead_data']['email'])}"
        )

        save_session(req.session_id, session)
        name = session["lead_data"]["first_name"]
        base_reply = f"Perfect, all set {name}! What's your current education level?"
        reply = mirror_language(base_reply, text)
        append_message(req.session_id, "assistant", reply)
        quick_replies = ["10th pass", "12th pass", "Graduate", "Something else"]
        return ChatResponse(reply=reply, suggested_courses=[], quick_replies=quick_replies, step=1, step_label="Level")

    return ChatResponse(reply="Let's continue!", step=1, step_label="Level")


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request):
    check_rate_limit(request, req.session_id)

    raw_text = req.message.strip()[:1000]
    session = get_session(req.session_id)
    append_message(req.session_id, "user", raw_text)
    session.setdefault("history", []).append({"role": "user", "content": raw_text})

    is_very_first_message = (
        not session.get("lead_captured", False)
        and session.get("lead_stage") == "first_name"
        and not session["lead_data"].get("first_name")
        and len(session.get("history", [])) <= 1
    )

    if is_very_first_message:
        if is_greeting(raw_text):
            reply = greeting_reply()
            append_message(req.session_id, "assistant", reply)
            save_session(req.session_id, session)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[], step=1, step_label="Level")
        if detect_course_interest(raw_text):
            reply = course_interest_reply()
            append_message(req.session_id, "assistant", reply)
            save_session(req.session_id, session)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[], step=1, step_label="Level")

    intent = classify_intent(raw_text)

    # 1. Abusive or Off-topic
    if intent in ["abusive", "off_topic"]:
        base_warn = abusive_or_offtopic_reply()
        pending_p, q_replies, step_num, step_lbl = get_pending_prompt(session)
        reply = f"{base_warn}\n\n{pending_p}"
        append_message(req.session_id, "assistant", reply)
        save_session(req.session_id, session)
        return ChatResponse(reply=reply, quick_replies=q_replies, step=step_num, step_label=step_lbl)

    # 2. Human Handoff / Complaint
    if intent in ["handoff_request", "complaint_frustration"]:
        lead = session.get("lead_data", {})
        save_callback_request(
            session_id=req.session_id,
            first_name=lead.get("first_name", ""),
            whatsapp_number=lead.get("whatsapp_number", ""),
            email=lead.get("email", ""),
            reason=raw_text,
        )
        send_handoff_notification(
            first_name=lead.get("first_name", ""),
            whatsapp_number=lead.get("whatsapp_number", ""),
            email=lead.get("email", ""),
            reason=raw_text,
        )
        reply = handoff_reply()
        pending_p, q_replies, step_num, step_lbl = get_pending_prompt(session)
        combined = f"{reply}\n\n{pending_p}"
        append_message(req.session_id, "assistant", combined)
        save_session(req.session_id, session)
        return ChatResponse(reply=combined, quick_replies=q_replies, step=step_num, step_label=step_lbl)

    # 3. Interruption Handling (only if not directly answering the pending flow step)
    if not is_answering_current_flow(session, raw_text) and session.get("browse_stage") != "post_selection":
        if intent in ["course_question", "general_tech_question"] or is_general_question(raw_text):
            pending_p, q_replies, step_num, step_lbl = get_pending_prompt(session)
            if intent == "general_tech_question":
                ans = answer_general_question(raw_text, session.get("history", []))
                loc_p = localize_reply(pending_p, raw_text)
                reply = f"{ans}\n\n{loc_p}"
            else:
                shown = session.get("shown_courses", [])
                reply = answer_grounded_interruption(raw_text, shown, pending_p)

            append_message(req.session_id, "assistant", reply)
            save_session(req.session_id, session)
            return ChatResponse(reply=reply, quick_replies=q_replies, step=step_num, step_label=step_lbl)

    # 4. Lead Capture Phase (Early timing)
    if LEAD_CAPTURE_TIMING == "early" and not session.get("lead_captured", False):
        return handle_lead_capture(req, session)

    # 5. Course Browse Stages
    stage = session.get("browse_stage", "education")

    # Step 1: Education Level
    if stage == "education":
        if len(raw_text) < 2:
            base_reply = "Could you tell me your education level?"
            reply = localize_reply(base_reply, raw_text)
            append_message(req.session_id, "assistant", reply)
            save_session(req.session_id, session)
            return ChatResponse(
                reply=reply,
                quick_replies=["10th pass", "12th pass", "Graduate", "Something else"],
                step=1,
                step_label="Level",
            )
        session["profile"]["education_level"] = raw_text
        session["browse_stage"] = "program"
        save_session(req.session_id, session)
        base_reply = "Great! Which area are you interested in?"
        reply = localize_reply(base_reply, raw_text)
        append_message(req.session_id, "assistant", reply)
        return ChatResponse(reply=reply, quick_replies=REAL_PROGRAMS + ["Something else"], step=2, step_label="Interest")

    # Step 2: Program Selection
    if stage == "program":
        program = resolve_program_exact(raw_text)
        if not program:
            program = interpret_program_from_text(raw_text)
        if not program:
            base_reply = "I couldn't quite match that. Could you pick one of these areas?"
            reply = localize_reply(base_reply, raw_text)
            append_message(req.session_id, "assistant", reply)
            save_session(req.session_id, session)
            return ChatResponse(reply=reply, quick_replies=REAL_PROGRAMS + ["Something else"], step=2, step_label="Interest")

        session["selected_program"] = program
        subs = get_subprograms(program)

        if subs:
            session["browse_stage"] = "subprogram"
            save_session(req.session_id, session)
            base_reply = f"{program} has a few tracks — which one interests you?"
            reply = localize_reply(base_reply, raw_text)
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, quick_replies=subs + ["Something else"], step=3, step_label="Mode")

        courses = get_courses_by_program(program)
        session["shown_courses"] = courses
        session["browse_stage"] = "course"

        lead = session.get("lead_data", {})
        row_id = save_course_interest(
            session_id=req.session_id,
            first_name=lead.get("first_name", "Student"),
            whatsapp_number=lead.get("whatsapp_number", ""),
            email=lead.get("email", ""),
            recommended_courses=", ".join(c.get("title", "") for c in courses),
        )
        session["course_interest_id"] = row_id
        save_session(req.session_id, session)

        send_recommendation_notification(
            first_name=lead.get("first_name", "Student"),
            whatsapp_number=lead.get("whatsapp_number", ""),
            email=lead.get("email", ""),
            recommended_courses=", ".join(c.get("title", "") for c in courses),
        )

        base_reply = f"Here are all our {program} courses — tap one to see details!"
        reply = localize_reply(base_reply, raw_text)
        append_message(req.session_id, "assistant", reply)
        quick_replies = [c.get("title", "") for c in courses] + ["Still deciding"]
        return ChatResponse(
            reply=reply, suggested_courses=courses, quick_replies=quick_replies, step=4, step_label="Matches"
        )

    # Step 3: Subprogram Selection
    if stage == "subprogram":
        program = session.get("selected_program", "")
        subs = get_subprograms(program)

        if raw_text.strip().lower() in ["something else", "all", "all courses", "show all"]:
            courses = get_courses_by_program(program)
            session["shown_courses"] = courses
            session["browse_stage"] = "course"

            lead = session.get("lead_data", {})
            row_id = save_course_interest(
                session_id=req.session_id,
                first_name=lead.get("first_name", "Student"),
                whatsapp_number=lead.get("whatsapp_number", ""),
                email=lead.get("email", ""),
                recommended_courses=", ".join(c.get("title", "") for c in courses),
            )
            session["course_interest_id"] = row_id
            save_session(req.session_id, session)

            send_recommendation_notification(
                first_name=lead.get("first_name", "Student"),
                whatsapp_number=lead.get("whatsapp_number", ""),
                email=lead.get("email", ""),
                recommended_courses=", ".join(c.get("title", "") for c in courses),
            )

            base_reply = f"Here are all our {program} courses — tap one to see details!"
            reply = localize_reply(base_reply, raw_text)
            append_message(req.session_id, "assistant", reply)
            quick_replies = [c.get("title", "") for c in courses] + ["Still deciding"]
            return ChatResponse(
                reply=reply, suggested_courses=courses, quick_replies=quick_replies, step=4, step_label="Matches"
            )

        subprogram = resolve_subprogram(subs, raw_text)
        if not subprogram:
            # Check if user mentioned another program or track from another domain
            switch_prog = resolve_program_exact(raw_text) or interpret_program_from_text(raw_text)
            if switch_prog and switch_prog.lower() != program.lower():
                session["selected_program"] = switch_prog
                new_subs = get_subprograms(switch_prog)
                if new_subs:
                    session["browse_stage"] = "subprogram"
                    save_session(req.session_id, session)
                    base_reply = f"Bilkul! Chaliye {switch_prog} explore karte hain. Isme ye popular tracks hain — kaunsa aapko interest karta hai?"
                    reply = localize_reply(base_reply, raw_text)
                    append_message(req.session_id, "assistant", reply)
                    return ChatResponse(reply=reply, quick_replies=new_subs + ["Something else"], step=3, step_label="Mode")
                else:
                    courses = get_courses_by_program(switch_prog)
                    session["shown_courses"] = courses
                    session["browse_stage"] = "course"
                    save_session(req.session_id, session)
                    base_reply = f"Bilkul! Yeh rahe hamare {switch_prog} courses — ek pe tap karke details dekhein!"
                    reply = localize_reply(base_reply, raw_text)
                    append_message(req.session_id, "assistant", reply)
                    quick_replies = [c.get("title", "") for c in courses] + ["Still deciding"]
                    return ChatResponse(
                        reply=reply,
                        suggested_courses=courses,
                        quick_replies=quick_replies,
                        step=4,
                        step_label="Matches",
                    )

            cat_match = find_subprogram_in_catalog(raw_text)
            if cat_match:
                cat_prog, cat_sub = cat_match
                session["selected_program"] = cat_prog
                session["selected_subprogram"] = cat_sub
                courses = get_courses_by_subprogram(cat_prog, cat_sub)
                session["shown_courses"] = courses
                session["browse_stage"] = "course"
                save_session(req.session_id, session)
                base_reply = f"Zaroor! Yeh rahe hamare {cat_sub} ({cat_prog}) courses — ek pe tap karke syllabus check karein!"
                reply = localize_reply(base_reply, raw_text)
                append_message(req.session_id, "assistant", reply)
                quick_replies = [c.get("title", "") for c in courses] + ["Still deciding"]
                return ChatResponse(
                    reply=reply,
                    suggested_courses=courses,
                    quick_replies=quick_replies,
                    step=4,
                    step_label="Matches",
                )

            base_reply = "Please pick one of the tracks shown, or tell me which interests you."
            reply = localize_reply(base_reply, raw_text)
            append_message(req.session_id, "assistant", reply)
            save_session(req.session_id, session)
            return ChatResponse(reply=reply, quick_replies=subs + ["Something else"], step=3, step_label="Mode")

        session["selected_subprogram"] = subprogram
        courses = get_courses_by_subprogram(program, subprogram)
        session["shown_courses"] = courses
        session["browse_stage"] = "course"

        lead = session.get("lead_data", {})
        row_id = save_course_interest(
            session_id=req.session_id,
            first_name=lead.get("first_name", "Student"),
            whatsapp_number=lead.get("whatsapp_number", ""),
            email=lead.get("email", ""),
            recommended_courses=", ".join(c.get("title", "") for c in courses),
        )
        session["course_interest_id"] = row_id
        save_session(req.session_id, session)

        send_recommendation_notification(
            first_name=lead.get("first_name", "Student"),
            whatsapp_number=lead.get("whatsapp_number", ""),
            email=lead.get("email", ""),
            recommended_courses=", ".join(c.get("title", "") for c in courses),
        )

        base_reply = f"Here are our {subprogram} courses — tap one to see details!"
        reply = localize_reply(base_reply, raw_text)
        append_message(req.session_id, "assistant", reply)
        quick_replies = [c.get("title", "") for c in courses] + ["Still deciding"]
        return ChatResponse(
            reply=reply, suggested_courses=courses, quick_replies=quick_replies, step=4, step_label="Matches"
        )

    # Step 4: Exact Course Selection & Discussion
    if stage in ["course", "post_selection"]:
        titles = [c.get("title", "") for c in session.get("shown_courses", [])]

        if raw_text == "Still deciding":
            base_reply = "No worries, take your time! Let me know if you have any questions about these courses."
            reply = localize_reply(base_reply, raw_text)
            append_message(req.session_id, "assistant", reply)
            save_session(req.session_id, session)
            return ChatResponse(reply=reply, quick_replies=titles + ["Still deciding"], step=4, step_label="Matches")

        if raw_text in titles:
            session["selected_course"] = raw_text
            session["browse_stage"] = "post_selection"
            lead = session.get("lead_data", {})
            if session.get("course_interest_id"):
                update_selected_course(session["course_interest_id"], raw_text, session_id=req.session_id)
            save_session(req.session_id, session)

            send_selection_notification(
                first_name=lead.get("first_name", "Student"),
                whatsapp_number=lead.get("whatsapp_number", ""),
                email=lead.get("email", ""),
                selected_course=raw_text,
            )
            base_reply = f"Great choice! I've noted your interest in {raw_text}. Our team will reach out with next steps. Anything else you'd like to know?"
            reply = localize_reply(base_reply, raw_text)
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[], step=4, step_label="Matches")

        # Check if student is asking to switch to another program or track
        # A. Direct program match (e.g. "Fullstack Web", "Web Development", "Cyber Security", "cyber", "Digital Marketing")
        switch_prog = resolve_program_exact(raw_text) or interpret_program_from_text(raw_text)
        current_prog = session.get("selected_program", "")
        if switch_prog:
            if switch_prog.lower() != current_prog.lower():
                session["selected_program"] = switch_prog
                subs = get_subprograms(switch_prog)
                if subs:
                    session["browse_stage"] = "subprogram"
                    save_session(req.session_id, session)
                    base_reply = f"Bilkul! Chaliye {switch_prog} explore karte hain. Isme ye popular tracks hain — kaunsa aapko interest karta hai?"
                    reply = localize_reply(base_reply, raw_text)
                    append_message(req.session_id, "assistant", reply)
                    return ChatResponse(reply=reply, quick_replies=subs + ["Something else"], step=3, step_label="Mode")
                else:
                    courses = get_courses_by_program(switch_prog)
                    session["shown_courses"] = courses
                    session["browse_stage"] = "course"
                    save_session(req.session_id, session)
                    base_reply = f"Bilkul! Yeh rahe hamare {switch_prog} courses — ek pe tap karke details dekhein!"
                    reply = localize_reply(base_reply, raw_text)
                    append_message(req.session_id, "assistant", reply)
                    quick_replies = [c.get("title", "") for c in courses] + ["Still deciding"]
                    return ChatResponse(
                        reply=reply,
                        suggested_courses=courses,
                        quick_replies=quick_replies,
                        step=4,
                        step_label="Matches",
                    )
            else:
                # Same program re-mentioned: re-show its subprograms or courses
                subs = get_subprograms(switch_prog)
                if subs:
                    session["browse_stage"] = "subprogram"
                    save_session(req.session_id, session)
                    base_reply = f"Hamare paas {switch_prog} mein ye tracks hain — kaunsa aapko pasand aayega?"
                    reply = localize_reply(base_reply, raw_text)
                    append_message(req.session_id, "assistant", reply)
                    return ChatResponse(reply=reply, quick_replies=subs + ["Something else"], step=3, step_label="Mode")

        # B. Direct track/subprogram match (e.g. "MERN", "Ethical Hacking", "Data Analytics")
        cat_match = find_subprogram_in_catalog(raw_text)
        if cat_match:
            cat_prog, cat_sub = cat_match
            if cat_sub.lower() != session.get("selected_subprogram", "").lower():
                session["selected_program"] = cat_prog
                session["selected_subprogram"] = cat_sub
                courses = get_courses_by_subprogram(cat_prog, cat_sub)
                session["shown_courses"] = courses
                session["browse_stage"] = "course"
                save_session(req.session_id, session)
                base_reply = f"Zaroor! Yeh rahe hamare {cat_sub} ({cat_prog}) courses — ek pe tap karke syllabus check karein!"
                reply = localize_reply(base_reply, raw_text)
                append_message(req.session_id, "assistant", reply)
                quick_replies = [c.get("title", "") for c in courses] + ["Still deciding"]
                return ChatResponse(
                    reply=reply,
                    suggested_courses=courses,
                    quick_replies=quick_replies,
                    step=4,
                    step_label="Matches",
                )

        # Check if student wants to explore other courses or tracks from scratch
        if raw_text.strip().lower() in [
            "explore other courses", "explore other tracks", "change course",
            "kuch aur dikhao", "dusre courses", "change program", "other courses"
        ]:
            session["browse_stage"] = "program"
            session.pop("selected_course", None)
            save_session(req.session_id, session)
            base_reply = "Bilkul! Aap kaunse program ya area ke courses dekhna chahenge?"
            reply = localize_reply(base_reply, raw_text)
            append_message(req.session_id, "assistant", reply)
            return ChatResponse(
                reply=reply,
                quick_replies=REAL_PROGRAMS + ["Something else"],
                step=2,
                step_label="Interest",
            )

        # C. Consultative discussion / dislike / questions / identity
        is_alt = expresses_alternative_or_dislike(raw_text)
        reply = general_followup(
            history=session.get("history", []),
            shown_courses=session.get("shown_courses", []),
            user_message=raw_text,
            selected_program=session.get("selected_program", ""),
            selected_subprogram=session.get("selected_subprogram", ""),
            selected_course=session.get("selected_course", ""),
        )
        append_message(req.session_id, "assistant", reply)
        save_session(req.session_id, session)

        if is_alt:
            quick_replies = [
                "Fullstack Web (MERN)",
                "Data Analytics",
                "Cyber Security",
                "Digital Marketing",
                "Something else",
            ]
        elif stage == "post_selection":
            quick_replies = [
                "Fee & Batch details",
                "Placement assistance",
                "Talk to counselor",
                "Explore other courses",
            ]
        else:
            quick_replies = titles + ["Still deciding"]

        return ChatResponse(reply=reply, quick_replies=quick_replies, step=4, step_label="Matches")

    reply = general_followup(
        history=session.get("history", []),
        shown_courses=session.get("shown_courses", []),
        user_message=raw_text,
        selected_program=session.get("selected_program", ""),
        selected_subprogram=session.get("selected_subprogram", ""),
        selected_course=session.get("selected_course", ""),
    )
    append_message(req.session_id, "assistant", reply)
    save_session(req.session_id, session)
    return ChatResponse(reply=reply, suggested_courses=[], quick_replies=[], step=4, step_label="Matches")


@app.post("/mark-interest")
def mark_interest(req: MarkInterestRequest, request: Request):
    check_rate_limit(request, req.session_id)
    session = get_session(req.session_id)
    lead = session.get("lead_data", {})
    row_id = session.get("course_interest_id")
    update_selected_course(row_id, req.course_title, session_id=req.session_id)
    send_selection_notification(
        first_name=lead.get("first_name", "Student"),
        whatsapp_number=lead.get("whatsapp_number", ""),
        email=lead.get("email", ""),
        selected_course=req.course_title,
    )
    session["selected_course"] = req.course_title
    save_session(req.session_id, session)
    return {"status": "ok"}