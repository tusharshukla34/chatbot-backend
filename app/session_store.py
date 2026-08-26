from typing import Dict, Any
from app.config import MAX_HISTORY_MESSAGES

_sessions: Dict[str, Dict[str, Any]] = {}



def get_session(session_id: str) -> Dict[str, Any]:
    if session_id not in _sessions:
        _sessions[session_id] = {
            "history": [],
            "profile": {"education_level": "", "interests": [], "mode_preference": "", "completed_courses": []},
            "has_recommended": False,
            "last_matches": [],
            "lead_captured": False,
            "lead_stage": "first_name",
            "lead_data": {"first_name": "", "whatsapp_number": "", "email": ""},
            "course_interest_id": None,
            "awaiting_selection": False,
            "selection_finalized": False,
        }
    return _sessions[session_id]


def append_message(session_id: str, role: str, content: str):
    s = get_session(session_id)
    s["history"].append({"role": role, "content": content})
    if len(s["history"]) > MAX_HISTORY_MESSAGES:
        s["history"] = s["history"][-MAX_HISTORY_MESSAGES:]


def update_profile(session_id: str, new_profile: Dict[str, Any]):
    s = get_session(session_id)
    for key in ("education_level", "mode_preference"):
        if new_profile.get(key):
            s["profile"][key] = new_profile[key]
    for key in ("interests", "completed_courses"):
        vals = new_profile.get(key)
        if vals:
            existing = set(s["profile"].get(key, []))
            existing.update(vals)
            s["profile"][key] = list(existing)