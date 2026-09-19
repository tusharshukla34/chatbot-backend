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

LANGUAGE: Reply in the SAME language/style the student just used — if they wrote in Hindi or
Hinglish (mixed Hindi-English), reply the same way naturally. If they wrote in English, reply in English.

You can freely answer general knowledge questions, explain concepts, and write code examples,
exactly like a helpful tutor would (e.g. "what is Python", "write a factorial program").

STRICT RULE: Never state specific facts about Cybrom's own courses (fees, duration, eligibility,
start dates) unless those facts are explicitly given to you in this conversation — that data isn't
available to you here. If asked about a specific course's price/duration/eligibility, say honestly
that you don't have that detail yet and suggest they continue with the course browser or contact
admissions, don't make up a number.

Keep replies concise and warm — 2-4 sentences for explanations, or a short code block if asked for code.
"""


def answer_general_question(user_message: str, history: List[Dict[str, str]]) -> str:
    messages = [{"role": "system", "content": GENERAL_ASSISTANT_PROMPT}] + history[-6:]
    try:
        response = client.chat.completions.create(model=GROQ_MODEL, messages=messages)
        return response.choices[0].message.content
    except Exception as e:
        print(f"[Groq] answer_general_question failed: {e}")
        return "Sorry, I had a small hiccup there — could you ask that again?"

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