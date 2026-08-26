"""
Deterministic course matching. This is intentionally NOT done by the LLM —
the LLM only writes a short intro sentence. Match reasons are generated here
too, from the same scoring logic, so they're always accurate (never hallucinated).
"""
from typing import List, Dict, Any
from app.course_store import course_store
from app.config import COURSE_PAGE_BASE_URL

QUALIFICATION_RANK = {
    "10th pass": 1,
    "12th pass": 2,
    "12th pass / graduate": 2,
    "graduate": 3,
    "graduate (cs/it preferred)": 3,
}


def _qualification_rank(text: str) -> int:
    t = (text or "").strip().lower()
    for key, rank in QUALIFICATION_RANK.items():
        if key in t:
            return rank
    return 0


def score_course(row: Dict[str, Any], profile: Dict[str, Any]) -> int:
    score = 0
    student_interests = set(i.strip().lower() for i in profile.get("interests", []) if i)
    course_tags = set(row.get("_tags", []))
    score += len(student_interests & course_tags) * 3

    student_rank = _qualification_rank(profile.get("education_level", ""))
    course_rank = _qualification_rank(row.get("min_qualification", ""))
    if course_rank and student_rank:
        if student_rank < course_rank:
            score -= 10
        elif student_rank == course_rank:
            score += 2
        else:
            score += 1

    mode_pref = (profile.get("mode_preference") or "").strip().lower()
    course_mode = (row.get("mode") or "").strip().lower()
    if mode_pref and course_mode and (mode_pref == course_mode or course_mode == "hybrid"):
        score += 2

    if row.get("prerequisite_course") and not profile.get("completed_courses"):
        score -= 3

    return score


def _match_reasons(row: Dict[str, Any], profile: Dict[str, Any]) -> List[str]:
    """Short, factual bullet points explaining why this course was suggested."""
    reasons = []
    student_interests = set(i.strip().lower() for i in profile.get("interests", []) if i)
    course_tags = set(row.get("_tags", []))
    overlap = student_interests & course_tags
    if overlap:
        matched = ", ".join(sorted(overlap)[:3])
        reasons.append(f"Matches your interest in {matched}")

    student_rank = _qualification_rank(profile.get("education_level", ""))
    course_rank = _qualification_rank(row.get("min_qualification", ""))
    if course_rank and student_rank and student_rank >= course_rank:
        reasons.append(f"You meet the eligibility requirement ({row.get('min_qualification', '')})")

    mode_pref = (profile.get("mode_preference") or "").strip().lower()
    course_mode = (row.get("mode") or "").strip().lower()
    if mode_pref and course_mode:
        if mode_pref == course_mode:
            reasons.append(f"Offered in your preferred {course_mode} mode")
        elif course_mode == "hybrid":
            reasons.append(f"Hybrid mode — includes {mode_pref} learning")

    return reasons[:2]


def _trim_for_frontend(course: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    trimmed = {
        "title": course.get("course_title", ""),
        "description": course.get("description", ""),
        "duration": course.get("duration", ""),
        "mode": course.get("mode", ""),
        "career_outcomes": course.get("career_outcomes", ""),
        "match_reasons": _match_reasons(course, profile),
    }
    if COURSE_PAGE_BASE_URL and course.get("urlslug"):
        trimmed["link"] = f"{COURSE_PAGE_BASE_URL.rstrip('/')}/{course['urlslug']}"
    else:
        trimmed["link"] = course.get("urlslug", "")
    return trimmed


def match_courses(profile: Dict[str, Any], top_n: int = 3) -> List[Dict[str, Any]]:
    """
    Only returns courses that genuinely overlap with the student's stated
    interests. If nothing overlaps, returns an empty list rather than
    forcing irrelevant courses on the student.
    """
    rows = course_store.all_courses()
    student_interests = set(i.strip().lower() for i in profile.get("interests", []) if i)

    scored = []
    for row in rows:
        course_tags = set(row.get("_tags", []))
        has_interest_overlap = bool(student_interests & course_tags)
        if not has_interest_overlap:
            continue  # skip courses with zero relevance to stated interests
        scored.append((score_course(row, profile), row))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = [r for s, r in scored if s > 0]
    top_results = results[:top_n]
    return [_trim_for_frontend(course, profile) for course in top_results]