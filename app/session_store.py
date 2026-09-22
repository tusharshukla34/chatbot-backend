from typing import Dict, Any
from app.config import MAX_HISTORY_MESSAGES

_sessions: Dict[str, Dict[str, Any]] = {}


def get_session(session_id: str) -> Dict[str, Any]:
    if session_id not in _sessions:
        _sessions[session_id] = {
            "history": [],
            "profile": {"education_level": ""},
            "lead_captured": False,
            "lead_stage": "first_name",
            "lead_data": {"first_name": "", "whatsapp_number": "", "email": ""},
            "name_attempts": 0,
            "browse_stage": "education",
            "selected_program": "",
            "selected_subprogram": "",
            "shown_courses": [],
            "selected_course": "",
            "course_interest_id": None,
        }
    return _sessions[session_id]


def append_message(session_id: str, role: str, content: str):
    s = get_session(session_id)
    s["history"].append({"role": role, "content": content})
    if len(s["history"]) > MAX_HISTORY_MESSAGES:
        s["history"] = s["history"][-MAX_HISTORY_MESSAGES:]