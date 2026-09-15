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

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

def _parse_json(text: str) -> Dict[str, Any]:
    cleaned = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    return json.loads(cleaned)


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