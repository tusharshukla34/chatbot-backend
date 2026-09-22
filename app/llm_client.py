import json
import re
from typing import Dict, Any, List
from groq import Groq
from app.config import GROQ_API_KEY, GROQ_MODEL

client = Groq(api_key=GROQ_API_KEY)

INTERPRET_PROGRAM_PROMPT = """A student typed a free-text answer describing what they're interested in.
Map it to EXACTLY ONE of these program names if it clearly fits, otherwise respond with NONE:
Fullstack Web, Cyber Security, Data Programs, AI-ML, Digital Marketing

Respond with ONLY the program name (exact spelling above) or the word NONE. No other text.
"""

FOLLOWUP_SYSTEM_PROMPT = """You are a friendly course-counseling assistant for an ed-tech institute.
You are given a list of real courses currently being discussed, with their real details
(title, duration, mode, module list). Only state facts given below — never invent syllabus
details, fees, dates, or eligibility not given here. If asked something not covered, say so honestly.
Write in plain conversational sentences, no markdown tables or pipe symbols.
Respond in plain natural language (NOT JSON) — just your reply text.
"""

GENERAL_ASSISTANT_PROMPT = """You are a friendly, knowledgeable assistant for Cybrom, an ed-tech institute.

LANGUAGE: Reply in warm, natural Hindi-English mixed style (Hinglish) by default, the way a
friendly Indian ed-tech counselor would speak — mixing Hindi and English words naturally. If the
student writes in clear, formal English and seems to prefer that, you can respond in plain English instead.

You can freely answer general knowledge questions, explain concepts, and write code examples,
exactly like a helpful tutor would (e.g. "what is Python", "write a factorial program").

STRICT RULE: Never state specific facts about Cybrom's own courses (fees, duration, eligibility,
start dates) unless those facts are explicitly given to you in this conversation — that data isn't
available to you here. If asked about a specific course's price/duration/eligibility, say honestly
that you don't have that detail yet and suggest they continue with the course browser or contact
admissions, don't make up a number.

Keep replies concise and warm — 2-4 sentences for explanations, or a short code block if asked for code.
"""

MIRROR_LANGUAGE_PROMPT = """Rewrite the following message in warm, natural Hindi-English mixed
style (Hinglish) — the way a friendly Indian ed-tech counselor would casually speak, mixing Hindi
and English words naturally (like "Aapka naam kya hai?" or "Kaise madad kar sakta hoon aapki?").
Keep the exact same meaning and information, and keep any names/numbers/emails exactly as given.
Respond with ONLY the rewritten message in Hinglish, nothing else.
"""

GREETING_REPLY_PROMPT = """A student just greeted you (said hi/hello). Reply with a short, warm
greeting in Hinglish, asking what they'd like help with today — courses, career guidance, or
anything else. Keep it to 1 sentence. Respond with ONLY the greeting message.
"""

COURSE_INTEREST_REPLY_PROMPT = """The student just said they're interested in courses. Reply
warmly in Hinglish, something like "Haan, main aapko courses bata sakta hoon, uske pehle aapka
naam bata dijiye" — telling them you'll help with courses, but first need their name. Keep it to
1 short sentence. Respond with ONLY the reply message.
"""

COURSE_INTEREST_CHECK_PROMPT = """A student sent a message. Decide if they are expressing interest
in learning about courses, career guidance, or what the institute offers — even if phrased
differently (e.g. "mujhe course jaanna hai", "guide me", "what do you teach", "career advice chahiye").

Respond with ONLY the word YES or NO, nothing else.
"""

NAME_REQUEST_REPLY_PROMPT = """The student just replied with something that isn't actually their
name (e.g. an affirmation like "ha"/"yes"/"ok", a filler word, or something unrelated). Acknowledge
what they said naturally and warmly in Hinglish (e.g. if they said "ha", respond like you're
confirming you'll help them), then ask for their name so you can assist them. Keep it to 1-2 short
sentences. Respond with ONLY the reply message.
"""

LOCALIZE_PROMPT = """Default language: warm, natural Hindi-English mixed style (Hinglish), like a
friendly Indian ed-tech counselor speaking casually.

If the student's last message is a clear, proper English sentence (not just a single English word
or a short greeting), reply in plain English instead. Otherwise, always default to Hinglish.

Rewrite the given message accordingly. Keep the EXACT same meaning, and keep any names, course
titles, numbers, or emails exactly as given — do not translate proper nouns. Respond with ONLY the
rewritten message, nothing else.
"""

NAME_CLASSIFY_PROMPT = """A student was asked for their name. Decide if their message is actually
a person's name (in any language/script), or if it's something else entirely — a question, a
refusal, a greeting, or unrelated text (e.g. "who are you", "why do you need it", "no thanks").

Respond with ONLY one word: NAME or NOT_NAME.
"""


def _parse_json(text: str) -> Dict[str, Any]:
    cleaned = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    return json.loads(cleaned)


def is_actually_a_name(text: str) -> bool:
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": NAME_CLASSIFY_PROMPT},
                {"role": "user", "content": text},
            ],
        )
        result = response.choices[0].message.content.strip().upper()
        return result.startswith("NAME")
    except Exception as e:
        print(f"[Groq] is_actually_a_name failed: {e}")
        return True  # fail open


def localize_reply(message: str, student_text: str) -> str:
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": LOCALIZE_PROMPT},
                {"role": "user", "content": f"Student's last message: {student_text}\n\nMessage to rewrite: {message}"},
            ],
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[Groq] localize_reply failed: {e}")
        return message


def name_request_reply(student_text: str) -> str:
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": NAME_REQUEST_REPLY_PROMPT},
                {"role": "user", "content": student_text},
            ],
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[Groq] name_request_reply failed: {e}")
        return "Theek hai, main aapki madad karunga — pehle apna naam bata dijiye?"


def detect_course_interest(text: str) -> bool:
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": COURSE_INTEREST_CHECK_PROMPT},
                {"role": "user", "content": text},
            ],
        )
        result = response.choices[0].message.content.strip().upper()
        return result.startswith("YES")
    except Exception as e:
        print(f"[Groq] detect_course_interest failed: {e}")
        return False


def course_interest_reply() -> str:
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "system", "content": COURSE_INTEREST_REPLY_PROMPT}, {"role": "user", "content": "courses"}],
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[Groq] course_interest_reply failed: {e}")
        return "Haan, main aapko courses bata sakta hoon — uske pehle aapka naam bata dijiye?"


def greeting_reply() -> str:
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "system", "content": GREETING_REPLY_PROMPT}, {"role": "user", "content": "hi"}],
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[Groq] greeting_reply failed: {e}")
        return "Hello! Kaise madad kar sakta hoon aapki?"


def mirror_language(message: str, student_text: str) -> str:
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": MIRROR_LANGUAGE_PROMPT},
                {"role": "user", "content": f"Student wrote: {student_text}\n\nMessage to rewrite: {message}"},
            ],
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[Groq] mirror_language failed: {e}")
        return message


def answer_general_question(user_message: str, history: List[Dict[str, str]]) -> str:
    messages = [{"role": "system", "content": GENERAL_ASSISTANT_PROMPT}] + history[-6:]
    try:
        response = client.chat.completions.create(model=GROQ_MODEL, messages=messages)
        return response.choices[0].message.content
    except Exception as e:
        print(f"[Groq] answer_general_question failed: {e}")
        return "Sorry, I had a small hiccup there — could you ask that again?"


def interpret_program_from_text(text: str) -> str:
    """Returns a real program name, or '' if nothing clearly matches."""
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": INTERPRET_PROGRAM_PROMPT},
                {"role": "user", "content": text},
            ],
        )
        result = response.choices[0].message.content.strip()
        valid = {"Fullstack Web", "Cyber Security", "Data Programs", "AI-ML", "Digital Marketing"}
        return result if result in valid else ""
    except Exception as e:
        print(f"[Groq] interpret_program_from_text failed: {e}")
        return ""


def general_followup(history: List[Dict[str, str]], shown_courses: List[Dict[str, Any]]) -> str:
    catalog = "\n".join(
        f"- {c['title']} | duration: {c['duration']} | mode: {c['mode']} "
        f"| modules: {', '.join(c.get('modules_preview', []))}"
        for c in shown_courses
    )
    context_msg = {"role": "user", "content": f"COURSES CURRENTLY SHOWN:\n{catalog}"}
    messages = [{"role": "system", "content": FOLLOWUP_SYSTEM_PROMPT}] + history + [context_msg]
    try:
        response = client.chat.completions.create(model=GROQ_MODEL, messages=messages)
        return response.choices[0].message.content
    except Exception as e:
        print(f"[Groq] general_followup failed: {e}")
        return "Sorry, I had a small hiccup — could you ask that again?"