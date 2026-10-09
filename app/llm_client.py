import json
import logging
import re
from typing import Any, Dict, List, Optional

from groq import Groq
from app.config import GROQ_API_KEY, GROQ_MODEL
from app.prompts import (
    ABUSIVE_OR_OFFTOPIC_PROMPT,
    COURSE_INTEREST_CHECK_PROMPT,
    COURSE_INTEREST_REPLY_PROMPT,
    GENERAL_ASSISTANT_PROMPT,
    GREETING_REPLY_PROMPT,
    GROUNDED_QA_PROMPT,
    HANDOFF_REPLY_PROMPT,
    INTENT_CLASSIFICATION_PROMPT,
    LOCALIZE_PROMPT,
    MIRROR_LANGUAGE_PROMPT,
    NAME_CLASSIFY_PROMPT,
    NAME_REQUEST_REPLY_PROMPT,
    SUBPROGRAM_FALLBACK_PROMPT,
    SYSTEM_GUARDRAIL,
)

logger = logging.getLogger("course_chatbot.llm")

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


def _parse_json(text: str) -> Dict[str, Any]:
    cleaned = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    return json.loads(cleaned)


def clean_gender_slashes(text: str) -> str:
    """Removes gendered words 'sakta', 'sakti', 'sakta/sakti', etc. in favor of gender-neutral phrasing."""
    if not text:
        return text
    # 1. Replace compound self-referential / assistance phrases ("kaise madad kar sakta/sakti hoon")
    text = re.sub(r"\b(?:kaise\s+)?(?:madad|help)\s+kar\s+sakt[ai](?:/sakt[ai])?\s+hoon\b", "kaise help karoon", text, flags=re.IGNORECASE)
    text = re.sub(r"\bmadad\s+kar\s+sakt[ai](?:/sakt[ai])?\s+hoon\b", "madad karoon", text, flags=re.IGNORECASE)
    text = re.sub(r"\bhelp\s+kar\s+sakt[ai](?:/sakt[ai])?\s+hoon\b", "help karoon", text, flags=re.IGNORECASE)
    text = re.sub(r"\bkar\s+sakt[ai](?:/sakt[ai])?\s+hoon\b", "karoon", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsakt[ai]/sakt[ai]\s+hoon\b", "hoon", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsakt[ai]/sakt[ai]\b", "sakte", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsakta/ti\b", "sakte", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsakta\s+ya\s+sakti\b", "sakte", text, flags=re.IGNORECASE)

    # 2. Self-referential "sakta hoon" or "sakti hoon" -> "karoon"
    text = re.sub(r"\bkar\s+sakta\s+hoon\b", "karoon", text, flags=re.IGNORECASE)
    text = re.sub(r"\bkar\s+sakti\s+hoon\b", "karoon", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsakta\s+hoon\b", "sakoon", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsakti\s+hoon\b", "sakoon", text, flags=re.IGNORECASE)

    # 3. Any remaining lone 'sakta' or 'sakti' (male/female singular) -> gender-neutral 'sakte'
    text = re.sub(r"\bsakta\b", "sakte", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsakti\b", "sakte", text, flags=re.IGNORECASE)
    text = re.sub(r"[ ]{2,}", " ", text)
    return text.strip()


def _safe_chat_call(messages: List[Dict[str, str]], temperature: float = 0.3) -> str:
    """Helper to call Groq chat completion with timeout and exception safety."""
    if not client:
        logger.warning("Groq client is not initialized (GROQ_API_KEY missing).")
        return ""
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=temperature,
            timeout=8.0,
        )
        raw_text = response.choices[0].message.content.strip()
        return clean_gender_slashes(raw_text)
    except Exception as e:
        logger.error(f"Groq API call error: {e}")
        return ""


def classify_intent(text: str) -> str:
    """Classifies user intent using fast rules and LLM fallback."""
    from app.browse_resolver import (
        is_greeting, is_handoff_request, is_complaint, is_abusive, is_general_question,
        is_exit_or_refusal
    )

    t = text.strip()
    if is_exit_or_refusal(t):
        return "disengagement_exit"
    if is_abusive(t):
        return "abusive"
    if is_handoff_request(t):
        return "handoff_request"
    if is_complaint(t):
        return "complaint_frustration"
    if is_greeting(t):
        return "greeting"

    # Fast check for direct catalog entities (program names, tracks, course titles)
    from app.matching import get_programs
    from app.course_store import course_store

    t_clean = t.lower()
    if t_clean in [p.lower() for p in get_programs()]:
        return "flow_answer"

    all_courses_data = course_store.all_courses()
    all_subs = {(r.get("subprogram") or "").strip().lower() for r in all_courses_data if r.get("subprogram")}
    if t_clean in all_subs:
        return "flow_answer"

    all_titles = {(r.get("course_title") or "").strip().lower() for r in all_courses_data if r.get("course_title")}
    if t_clean in all_titles:
        return "flow_answer"

    # Use LLM classification
    messages = [
        {"role": "system", "content": INTENT_CLASSIFICATION_PROMPT},
        {"role": "user", "content": t[:500]},
    ]
    raw = _safe_chat_call(messages, temperature=0.0)
    try:
        data = _parse_json(raw)
        intent = data.get("intent", "flow_answer")
        valid_intents = {
            "disengagement_exit", "greeting", "flow_answer", "course_question",
            "general_tech_question", "handoff_request", "complaint_frustration",
            "abusive", "off_topic"
        }
        return intent if intent in valid_intents else "flow_answer"
    except Exception:
        return "general_tech_question" if is_general_question(t) else "flow_answer"


def fallback_resolve_subprogram_llm(available_subs: List[str], text: str) -> Optional[str]:
    """Queries Groq with constrained JSON schema to match subprogram when rules fail."""
    prompt = SUBPROGRAM_FALLBACK_PROMPT.format(
        allowed_subprograms="\n".join(f"- {s}" for s in available_subs),
        student_input=text[:200],
    )
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": text[:200]},
    ]
    raw = _safe_chat_call(messages, temperature=0.0)
    try:
        data = _parse_json(raw)
        matched = data.get("subprogram", "").strip()
        for s in available_subs:
            if matched.lower() == s.lower():
                return s
    except Exception as e:
        logger.warning(f"Could not parse LLM subprogram response '{raw}': {e}")
    return None


def answer_grounded_interruption(
    user_question: str,
    catalog_courses: List[Dict[str, Any]],
    pending_prompt: str,
) -> str:
    """Answers a mid-conversation question grounded in real catalog facts and returns to pending step."""
    courses_info = "\n".join(
        f"- {c.get('title', c.get('course_title', ''))}: Duration={c.get('duration', 'Contact us')}, "
        f"Mode={c.get('mode', 'Contact us')}, Modules={', '.join(c.get('modules_preview', []))}"
        for c in catalog_courses[:10]
    )
    if not courses_info:
        courses_info = "Specific course details will be shown in the next step."

    prompt = GROUNDED_QA_PROMPT.format(
        courses_context=courses_info,
        pending_step_prompt=pending_prompt,
    )
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_question[:500]},
    ]
    answer = _safe_chat_call(messages, temperature=0.3)
    if answer:
        return answer
    return f"Main aapko zaroor guide karunga. {pending_prompt}"


def is_actually_a_name(text: str) -> bool:
    """Validates whether student input is an actual human name."""
    messages = [
        {"role": "system", "content": NAME_CLASSIFY_PROMPT},
        {"role": "user", "content": text[:100]},
    ]
    raw = _safe_chat_call(messages, temperature=0.0)
    try:
        data = _parse_json(raw)
        return bool(data.get("is_name", True))
    except Exception:
        # Fallback to true if alphabetic
        return text.replace(" ", "").isalpha()


def localize_reply(message: str, student_text: str) -> str:
    """Rewrites message in Roman Hinglish (or plain English if student wrote English)."""
    messages = [
        {"role": "system", "content": LOCALIZE_PROMPT},
        {"role": "user", "content": f"Student's message: {student_text[:300]}\n\nMessage to rewrite: {message}"},
    ]
    rewritten = _safe_chat_call(messages, temperature=0.3)
    return rewritten or message


def name_request_reply(student_text: str) -> str:
    """Warmly re-prompts for name when student provided an affirmation or unrelated reply."""
    messages = [
        {"role": "system", "content": NAME_REQUEST_REPLY_PROMPT},
        {"role": "user", "content": student_text[:200]},
    ]
    reply = _safe_chat_call(messages, temperature=0.4)
    return reply or "Theek hai, main aapki poori madad karunga! Pehle aapka shubh naam bata dijiye?"


def detect_course_interest(text: str) -> bool:
    """Detects whether student expressed interest in courses/career guidance."""
    messages = [
        {"role": "system", "content": COURSE_INTEREST_CHECK_PROMPT},
        {"role": "user", "content": text[:200]},
    ]
    raw = _safe_chat_call(messages, temperature=0.0).upper()
    return raw.startswith("YES")


def course_interest_reply() -> str:
    """Warm counselor acknowledgment when user indicates interest in courses."""
    messages = [
        {"role": "system", "content": COURSE_INTEREST_REPLY_PROMPT},
        {"role": "user", "content": "courses"},
    ]
    reply = _safe_chat_call(messages, temperature=0.4)
    return reply or "Haan, main aapko Cybrom ke sabhi top programs guide kar deta hoon! Usse pehle aapka naam bataiye?"


def greeting_reply() -> str:
    """Generates warm initial greeting."""
    messages = [
        {"role": "system", "content": GREETING_REPLY_PROMPT},
        {"role": "user", "content": "hi"},
    ]
    reply = _safe_chat_call(messages, temperature=0.4)
    return reply or "Hello! Cybrom AI mein aapka swagat hai. Aaj kis course ya career guidance mein help chahiye?"


def mirror_language(message: str, student_text: str) -> str:
    """Rewrites message to mirror the student's conversational tone."""
    messages = [
        {"role": "system", "content": MIRROR_LANGUAGE_PROMPT},
        {"role": "user", "content": f"Student wrote: {student_text[:300]}\n\nMessage to rewrite: {message}"},
    ]
    reply = _safe_chat_call(messages, temperature=0.3)
    return reply or message


def answer_general_question(user_message: str, history: List[Dict[str, str]]) -> str:
    """Answers general tech or tutoring questions concisely."""
    messages = [{"role": "system", "content": GENERAL_ASSISTANT_PROMPT}] + history[-6:] + [
        {"role": "user", "content": user_message[:500]}
    ]
    reply = _safe_chat_call(messages, temperature=0.4)
    return reply or "Cybrom admissions team aapse iske baare mein zaroor detail share karegi. Aap batayein, aur kya jaanna chahte hain?"


def interpret_program_from_text(text: str) -> str:
    """Interprets free text into one of the 5 main programs."""
    prompt = """A student typed a free-text answer describing what they want to learn.
Map it to EXACTLY ONE of these program names:
Fullstack Web, Cyber Security, Data Programs, AI-ML, Digital Marketing

Respond with ONLY the program name or NONE. No other text."""
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": text[:200]},
    ]
    raw = _safe_chat_call(messages, temperature=0.0)
    valid = {"Fullstack Web", "Cyber Security", "Data Programs", "AI-ML", "Digital Marketing"}
    return raw if raw in valid else ""


def general_followup(
    history: List[Dict[str, str]],
    shown_courses: List[Dict[str, Any]],
    user_message: str = "",
    selected_program: str = "",
    selected_subprogram: str = "",
    selected_course: str = "",
) -> str:
    """Intelligently handles consultative discussion about courses, dislikes, identity, and career options."""
    catalog = "\n".join(
        f"- {c.get('title', '')} | duration: {c.get('duration', 'Contact us')} | mode: {c.get('mode', 'Contact us')} "
        f"| modules: {', '.join(c.get('modules_preview', []))}"
        for c in (shown_courses or [])[:6]
    )

    counselor_prompt = SYSTEM_GUARDRAIL + f"""
You are Cybrom's Senior Admissions Counselor / AI Course Advisor. You are having an intelligent, empathetic, consultative conversation with a prospective student.

CURRENT CONTEXT:
Program: {selected_program or "Technology Courses"}
Track: {selected_subprogram or "Selected Track"}
Selected Course: {selected_course or "Not finalized yet"}
Courses currently shown in this track:
{catalog}

OTHER PROGRAMS AVAILABLE AT CYBROM:
- Fullstack Web Development (MERN Stack: React/Node.js, Java with Spring Boot, Python Full Stack)
- Cyber Security & Ethical Hacking (Ethical Hacking, DevOps & Cloud)
- Data Programs (Data Analytics: Power BI, SQL, Excel - minimal coding; Data Science)
- AI-ML (Generative AI, Agentic AI, MLOps, IoT)
- Digital Marketing (100% Non-coding, SEO, Performance Ads, Content)

COUNSELOR INSTRUCTIONS:
1. IDENTITY & ROLE ("who are you", "tumhara kaam kya hai", "aap kaun ho", "kya karte ho", "what is your job"):
   - Clearly explain that you are Cybrom's AI Course & Career Advisor.
   - Your job is to help students choose the best tech programs, understand curriculum, solve syllabus/career doubts, and connect them with senior counselors for batch timings, fees & admissions.
   - If the student has ALREADY chosen a course ({selected_course}):
     * Warmly acknowledge their chosen course (e.g., "Aapne {selected_course} choose kiya hai! Main iske syllabus, batch timings, placement support ya enrollment details mein aapki help karne ke liye yahan hoon.").
     * DO NOT ask them which course they want to choose again!
2. POST-SELECTION ASSISTANCE:
   - If `selected_course` is already set ({selected_course}):
     * The student has already picked their course! NEVER ask "kaunsa course dekhna hai?" or "which course interests you?".
     * Guide them on next steps: syllabus details, prerequisites, projects, placement assistance, and offer to have the admissions team connect with them.
3. ACTIVE LISTENING & EMPATHY FOR DISLIKES:
   - If the student expresses a dislike or constraint (e.g. "mujhe python nahi pasand", "coding nahi aati", "maths weak hai", "time kam hai", "kuch aur dikhao"):
     * NEVER repeat or push the courses/technologies they just expressed dislike for!
     * Acknowledge their preference warmly and empathetically.
     * Explain their options honestly: If they dislike Python, explain that AI-ML relies heavily on Python, but Cybrom has fantastic alternative career paths like Fullstack Web (MERN / React / Java), Data Analytics (Power BI / SQL / Excel), Cyber Security & Ethical Hacking, or Digital Marketing.
     * End with a friendly question asking which of these alternate paths they'd like to explore.
4. COURSE QUESTIONS & ADVICE:
   - If the student asks about a specific course, syllabus modules, career outcomes, or eligibility, give clear, encouraging guidance using the catalog details above.
   - If asking about specific fees, batch schedules, or placement guarantees, politely clarify that admission counseling customizes fee structures and batch timings, and offer to have a counselor connect with them.
5. TONE & SCRIPT:
   - Always speak in natural, friendly Roman-script Hinglish (English alphabet only, NEVER Devanagari Hindi). If the student wrote in formal English, reply in plain English.
   - Keep answers concise and sharp (2-4 sentences max). Always end with a helpful question or supportive statement.
"""
    hist_msgs = list(history[-8:]) if history else []
    if user_message and (not hist_msgs or hist_msgs[-1].get("content") != user_message):
        hist_msgs.append({"role": "user", "content": user_message[:600]})
    messages = [{"role": "system", "content": counselor_prompt}] + hist_msgs
    reply = _safe_chat_call(messages, temperature=0.4)
    return reply or "Aapke career goals ke hisaab se hum sahi course choose karne mein aapki poori madad karenge. Aap kis direction mein aage badhna chahte hain?"


def handoff_reply() -> str:
    """Generates warm confirmation for counselor callback."""
    messages = [
        {"role": "system", "content": HANDOFF_REPLY_PROMPT},
        {"role": "user", "content": "connect with counselor"},
    ]
    reply = _safe_chat_call(messages, temperature=0.4)
    return reply or "Zaroor! Hamare senior admissions counselor aapse jald hi WhatsApp ya call par connect karenge."


def abusive_or_offtopic_reply() -> str:
    """Generates calm redirection when user input is abusive or off-topic."""
    messages = [
        {"role": "system", "content": ABUSIVE_OR_OFFTOPIC_PROMPT},
        {"role": "user", "content": "help with course"},
    ]
    reply = _safe_chat_call(messages, temperature=0.3)
    return reply or "Main Cybrom ka Course Advisor hoon. Kya aap IT aur tech courses ke baare mein jaanna chahenge?"