"""
Deterministic course matching. This is intentionally NOT done by the LLM —
the LLM only writes a short intro sentence. Matching is a two-step process:
1. Filter to courses in the student's chosen program category (if recognized).
2. Rank within that category using real interest-tag overlap.
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

# maps a student's chosen category (button label, lowercased) to the real
# 'program' value in the course data
CATEGORY_TO_PROGRAM = {
    "fullstack web": "Fullstack Web",
    "web development": "Fullstack Web",
    "cyber security": "Cyber Security",
    "data programs": "Data Programs",
    "data science": "Data Programs",
    "data analytics": "Data Programs",
    "ai-ml": "AI-ML",
    "ai/ml": "AI-ML",
    "artificial intelligence": "AI-ML",
    "digital marketing": "Digital Marketing",
}


def _qualification_rank(text: str) -> int:
    t = (text or "").strip().lower()
    for key, rank in QUALIFICATION_RANK.items():
        if key in t:
            return rank
    return 0


def _resolve_target_programs(profile: Dict[str, Any]) -> List[str]:
    """Turn the student's stated interests into real program category names."""
    interests = [i.strip().lower() for i in profile.get("interests", []) if i]
    programs = set()
    for interest in interests:
        if interest in CATEGORY_TO_PROGRAM:
            programs.add(CATEGORY_TO_PROGRAM[interest])
    return list(programs)


def score_course(row: Dict[str, Any], profile: Dict[str, Any]) -> int:
    score = 0

    # tag overlap (secondary refinement within a program)
    student_interests = set(i.strip().lower() for i in profile.get("interests", []) if i)
    course_tags = set(row.get("_tags", []))
    score += len(student_interests & course_tags) * 3

    # education level: only applies if the course actually states one
    student_rank = _qualification_rank(profile.get("education_level", ""))
    course_rank = _qualification_rank(row.get("min_qualification", ""))
    if course_rank and student_rank:
        if student_rank < course_rank:
            score -= 10
        elif student_rank == course_rank:
            score += 2
        else:
            score += 1

    # mode preference: only applies if the course actually states a mode
    mode_pref = (profile.get("mode_preference") or "").strip().lower()
    course_mode = (row.get("mode") or "").strip().lower()
    if mode_pref and course_mode:
        if mode_pref == course_mode or course_mode == "hybrid":
            score += 2

    if row.get("prerequisite_course") and not profile.get("completed_courses"):
        score -= 3

    return score


def _match_reasons(row: Dict[str, Any], profile: Dict[str, Any]) -> List[str]:
    reasons = []
    if row.get("program"):
        reasons.append(f"Part of our {row['program']} track")

    student_interests = set(i.strip().lower() for i in profile.get("interests", []) if i)
    course_tags = set(row.get("_tags", []))
    overlap = student_interests & course_tags
    if overlap:
        matched = ", ".join(sorted(overlap)[:2])
        reasons.append(f"Covers {matched}")

    return reasons[:2]


def _trim_for_frontend(course: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    all_modules = course.get("_modules_list", [])
    trimmed = {
        "title": course.get("course_title", ""),
        "modules_preview": all_modules[:5],
        "total_modules": len(all_modules),
        "duration": course.get("duration", "") or "Contact us for details",
        "mode": course.get("mode", "") or "Contact us for details",
        "match_reasons": _match_reasons(course, profile),
    }
    if COURSE_PAGE_BASE_URL and course.get("urlslug"):
        trimmed["link"] = f"{COURSE_PAGE_BASE_URL.rstrip('/')}/{course['urlslug']}"
    else:
        trimmed["link"] = ""  # institute hasn't provided a base URL yet
    return trimmed


def match_courses(profile: Dict[str, Any], top_n: int = 3) -> List[Dict[str, Any]]:
    rows = course_store.all_courses()
    target_programs = _resolve_target_programs(profile)

    if target_programs:
        candidates = [r for r in rows if r.get("program") in target_programs]
    else:
        candidates = rows

    scored = [(score_course(r, profile), r) for r in candidates]
    scored.sort(key=lambda x: x[0], reverse=True)

    results = [r for s, r in scored if s >= 0]
    if not results:
        results = candidates

    # if the student picked a specific program category, show every real
    # course in that track rather than an arbitrary top-3 slice
    if target_programs:
        top_results = results
    else:
        top_results = results[:top_n]

    return [_trim_for_frontend(course, profile) for course in top_results]