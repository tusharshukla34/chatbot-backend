"""
Rule-based text matching for the browse flow. No AI involved here —
these are small, well-defined vocabularies (5 programs, a handful of
subprograms), so plain keyword matching is faster and free.
"""
from typing import Optional, List

REAL_PROGRAMS = ["Fullstack Web", "Cyber Security", "Data Programs", "AI-ML", "Digital Marketing"]

PROGRAM_KEYWORDS = {
    "Fullstack Web": ["web", "fullstack", "full stack", "coding", "developer", "frontend", "backend", "programming"],
    "Cyber Security": ["cyber", "security", "hacking", "hacker", "ethical hacking"],
    "Data Programs": ["data", "analytics", "analyst", "data science"],
    "AI-ML": ["ai", "ml", "machine learning", "artificial intelligence", "genai", "gen ai"],
    "Digital Marketing": ["marketing", "seo", "digital marketing", "social media"],
}

SUBPROGRAM_KEYWORDS = {
    "Python": ["python", "py"],
    "Java": ["java"],
    "MERNSTACK": ["mern", "mongo", "react", "node"],
    "Web": ["web", "html", "css", "javascript", "js"],
}


def resolve_program_exact(text: str) -> Optional[str]:
    t = text.strip().lower()
    for p in REAL_PROGRAMS:
        if t == p.lower():
            return p
    for prog, keywords in PROGRAM_KEYWORDS.items():
        for kw in keywords:
            if kw in t:
                return prog
    return None


def resolve_subprogram(available_subs: List[str], text: str) -> Optional[str]:
    t = text.strip().lower()
    for s in available_subs:
        if t == s.lower():
            return s
    for s in available_subs:
        for kw in SUBPROGRAM_KEYWORDS.get(s, []):
            if kw in t:
                return s
    return None