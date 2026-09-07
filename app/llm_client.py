import json
import re
from typing import Dict, Any, List
from groq import Groq
from app.config import GROQ_API_KEY, GROQ_MODEL

client = Groq(api_key=GROQ_API_KEY)

EXTRACT_SYSTEM_PROMPT = """You are a friendly course-counseling assistant for an ed-tech institute's website.
Chat naturally with the student, asking one question at a time, and extract a structured profile.

Fields to fill as you learn them (leave blank/empty if unknown):
- education_level: e.g. "10th pass", "12th pass", "Graduate"
- interests: list of keywords (e.g. ["coding","design"])
- completed_courses: list of any courses already done, else []

Set "ready_for_recommendation": true only once you know BOTH education_level AND at least one interest.
Ask about whichever of these is still missing, one at a time.

Respond ONLY with raw JSON, no markdown fences, in exactly this shape:
{"reply": "...", "profile": {"education_level": "", "interests": [], "completed_courses": []}, "ready_for_recommendation": false}
"""

RECOMMEND_SYSTEM_PROMPT = """You are the same friendly course-counseling assistant. You've been given real
matched courses below in a raw data format.

Write ONE short, warm intro sentence (max 2 sentences) introducing the recommendations — do NOT list
out each course's details, since those will be shown separately as cards. Just something like:
"Based on what you shared, here are a few courses that could be a great fit for you!"

Only reference facts given to you below — never invent anything.

Respond ONLY with raw JSON: {"reply": "..."}
"""

FOLLOWUP_SYSTEM_PROMPT = """You are a friendly course-counseling assistant for an ed-tech institute.
You are given PREVIOUSLY SHOWN COURSES below with their real details (title, duration, mode, outcomes,
description) — these are the exact facts you're allowed to use.

STRICT RULES:
- Only state facts given in PREVIOUSLY SHOWN COURSES below. Never invent new technology names, syllabus
  details, fees, dates, or eligibility not given there.
- If the student rules a course out (e.g. "I don't like Java"), remove it from consideration.
- If the student asks for something not in the given details, say so honestly instead of guessing.
- Write in plain conversational sentences, no markdown tables or pipe symbols.

Respond ONLY with raw JSON in exactly this shape:
{"reply": "...", "relevant_course_titles": ["Exact Title 1", "Exact Title 2"]}

"relevant_course_titles" must be an exact-spelling subset of the course titles given below — the ones
still being discussed/recommended after this message. If the student ruled one out, leave it out. If
nothing changed, return the same full list as before. If the topic moved away from courses entirely,
return the same list unchanged (don't clear it just because of an unrelated question).
"""


def general_followup(history: List[Dict[str, str]], previously_shown_courses: List[Dict[str, Any]]) -> Dict[str, Any]:
    catalog = "\n".join(
        f"- {c['title']} | duration: {c['duration']} | mode: {c['mode']} "
        f"| modules: {', '.join(c.get('modules_preview', []))}"
        for c in previously_shown_courses
    )
    context_msg = {
        "role": "user",
        "content": f"PREVIOUSLY SHOWN COURSES (with details):\n{catalog}",
    }
    messages = [{"role": "system", "content": FOLLOWUP_SYSTEM_PROMPT}] + history + [context_msg]
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        response_format={"type": "json_object"},
    )
    text = response.choices[0].message.content
    previously_shown_titles = [c["title"] for c in previously_shown_courses]
    try:
        return _parse_json(text)
    except (json.JSONDecodeError, ValueError):
        return {"reply": text, "relevant_course_titles": previously_shown_titles}
    
def no_match_reply(interests: List[str]) -> str:
    interest_text = ", ".join(interests) if interests else "that"
    return (
        f"I'm sorry, we don't currently have a course matching your interest in {interest_text}. "
        f"Could you tell me about any other subjects or areas you'd be open to exploring?"
    )


def _parse_json(text: str) -> Dict[str, Any]:
    cleaned = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    return json.loads(cleaned)

def extract_and_reply(history: List[Dict[str, str]]) -> Dict[str, Any]:
    messages = [{"role": "system", "content": EXTRACT_SYSTEM_PROMPT}] + history
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content
        try:
            return _parse_json(text)
        except (json.JSONDecodeError, ValueError):
            return {"reply": "Could you tell me a bit more about what you're looking for?",
                     "profile": {}, "ready_for_recommendation": False}
    except Exception as e:
        print(f"[Groq] extract_and_reply failed: {e}")
        return {"reply": "Sorry, I had a small hiccup — could you repeat that?",
                 "profile": {}, "ready_for_recommendation": False}


def _fallback_recommendation_text(matched_courses: List[Dict[str, Any]]) -> str:
    intro = "Based on what you shared, here are a few courses that could be a great fit for you!"
    lines = [intro]
    for c in matched_courses:
        modules = ", ".join(c.get("modules_preview", [])[:3])
        lines.append(f"\n{c['title']} — {c['duration']}, {c['mode']} mode. Covers {modules}.")
    return "\n".join(lines)


def phrase_recommendation(history: List[Dict[str, str]], matched_courses: List[Dict[str, Any]]) -> str:
    catalog = "\n".join(
        f"- {c['title']} | duration: {c['duration']} | mode: {c['mode']} "
        f"| modules: {', '.join(c.get('modules_preview', []))}"
        for c in matched_courses
    )
    messages = (
        [{"role": "system", "content": RECOMMEND_SYSTEM_PROMPT}]
        + history
        + [{"role": "user", "content": f"MATCHED COURSES:\n{catalog}\n\nReply to the student using only this."}]
    )
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content
        try:
            return _parse_json(text).get("reply", text)
        except (json.JSONDecodeError, ValueError):
            return text
    except Exception as e:
        print(f"[Groq] phrase_recommendation failed, using fallback: {e}")
        return _fallback_recommendation_text(matched_courses)