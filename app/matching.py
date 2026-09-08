"""
Pure browse-style course discovery — no scoring, no eligibility filtering.
Students pick Program -> (Subprogram, if it has one) -> exact Course.
Groq is never called here; free-text interpretation happens in main.py/llm_client.py.
"""
from typing import List, Dict, Any
from app.course_store import course_store
from app.config import COURSE_PAGE_BASE_URL


def _trim_course(course: Dict[str, Any]) -> Dict[str, Any]:
    all_modules = course.get("_modules_list", [])
    trimmed = {
        "title": course.get("course_title", ""),
        "modules_preview": all_modules[:5],
        "total_modules": len(all_modules),
        "duration": course.get("duration", "") or "Contact us for details",
        "mode": course.get("mode", "") or "Contact us for details",
        "match_reasons": [],
    }
    if COURSE_PAGE_BASE_URL and course.get("urlslug"):
        trimmed["link"] = f"{COURSE_PAGE_BASE_URL.rstrip('/')}/{course['urlslug']}"
    else:
        trimmed["link"] = ""
    return trimmed


def get_programs() -> List[str]:
    rows = course_store.all_courses()
    seen, programs = set(), []
    for r in rows:
        p = r.get("program", "")
        if p and p not in seen:
            seen.add(p)
            programs.append(p)
    return programs


def get_subprograms(program: str) -> List[str]:
    rows = course_store.all_courses()
    seen, subs = set(), []
    for r in rows:
        if r.get("program") == program:
            s = (r.get("subprogram") or "").strip()
            if s and s not in seen:
                seen.add(s)
                subs.append(s)
    return subs


def get_courses_by_program(program: str) -> List[Dict[str, Any]]:
    rows = course_store.all_courses()
    matched = [r for r in rows if r.get("program") == program]
    return [_trim_course(r) for r in matched]


def get_courses_by_subprogram(program: str, subprogram: str) -> List[Dict[str, Any]]:
    rows = course_store.all_courses()
    matched = [
        r for r in rows
        if r.get("program") == program
        and (r.get("subprogram") or "").strip().lower() == subprogram.strip().lower()
    ]
    return [_trim_course(r) for r in matched]