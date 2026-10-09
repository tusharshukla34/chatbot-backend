"""
Rule-based matching and LLM-fallback resolver for programs and subprograms.
Dynamically keeps keywords in sync with courses_data.xlsx.
"""

import json
import logging
import re
from typing import Dict, List, Optional

from app.course_store import course_store
from app.prompts import SUBPROGRAM_FALLBACK_PROMPT

logger = logging.getLogger("course_chatbot.browse_resolver")

REAL_PROGRAMS = ["Fullstack Web", "Cyber Security", "Data Programs", "AI-ML", "Digital Marketing"]

PROGRAM_KEYWORDS: Dict[str, List[str]] = {
    "Fullstack Web": [
        "web", "fullstack", "full stack", "coding", "developer", "frontend",
        "backend", "programming", "software engineering", "software developer"
    ],
    "Cyber Security": [
        "cyber", "security", "hacking", "hacker", "ethical hacking", "network security",
        "infosec", "cybersecurity"
    ],
    "Data Programs": [
        "data", "analytics", "analyst", "data science", "data analytics", "power bi",
        "tableau", "business analyst"
    ],
    "AI-ML": [
        "ai", "ml", "machine learning", "artificial intelligence", "genai", "gen ai",
        "deep learning", "llm", "prompt engineering", "neural"
    ],
    "Digital Marketing": [
        "marketing", "seo", "digital marketing", "social media", "ads", "content marketing",
        "performance marketing", "growth"
    ],
}

# Base curated keywords for all known catalog subprograms
BASE_SUBPROGRAM_KEYWORDS: Dict[str, List[str]] = {
    "Python": ["python", "py", "django", "flask"],
    "Java": ["java", "spring", "springboot", "core java"],
    "MERNSTACK": ["mern", "mongo", "react", "node", "express", "mernstack", "fullstack mern"],
    "Web": ["web", "html", "css", "javascript", "js", "frontend", "web dev"],
    "AI Engineering, MLOps & Development": [
        "mlops", "ai engineering", "model deployment", "machine learning ops", "ml ops", "engineering"
    ],
    "AI, IoT & Intelligent Systems": [
        "iot", "intelligent systems", "internet of things", "embedded", "smart devices", "sensor"
    ],
    "Artificial Intelligence with Gen AI": [
        "gen ai", "genai", "generative ai", "llm", "chatgpt", "generative", "artificial intelligence with gen ai"
    ],
    "Cyber Security & Ethical Hacking": [
        "ethical hacking", "hacking", "cyber", "penetration testing", "pen test", "ceh", "security"
    ],
    "DevOps & Cloud": [
        "devops", "cloud", "aws", "docker", "kubernetes", "ci/cd", "azure", "linux", "cloud computing"
    ],
    "Data Analytics": [
        "data analytics", "data analyst", "power bi", "tableau", "sql", "excel", "analytics", "bi", "data analysis"
    ],
}


def build_dynamic_subprogram_keywords() -> Dict[str, List[str]]:
    """Builds and expands subprogram keywords dynamically from active catalog rows."""
    keywords_map = {k: list(v) for k, v in BASE_SUBPROGRAM_KEYWORDS.items()}
    try:
        courses = course_store.all_courses()
        for r in courses:
            sub = (r.get("subprogram") or "").strip()
            if sub and sub not in keywords_map:
                keywords_map[sub] = []

            if sub:
                # Add normalized tokens from the title and interest tags
                tokens = [w.lower() for w in re.split(r"[,/&\s]+", sub) if len(w) > 2]
                for tok in tokens:
                    if tok not in keywords_map[sub]:
                        keywords_map[sub].append(tok)

                tags = r.get("_tags", [])
                for t in tags:
                    if t and t not in keywords_map[sub]:
                        keywords_map[sub].append(t)
    except Exception as e:
        logger.warning(f"Could not dynamically expand keywords from course store: {e}")

    return keywords_map


SUBPROGRAM_KEYWORDS = build_dynamic_subprogram_keywords()

GREETING_WORDS = {
    "hi", "hii", "hiii", "hello", "hey", "heya", "yo", "hola", "namaste",
    "good morning", "good evening", "good afternoon", "kaise ho", "kaisa hai"
}

QUESTION_TRIGGERS = [
    "what", "how", "why", "explain", "write", "code", "give me", "tell me about",
    "kaise", "kya", "konsi", "matlab", "kyu", "kaun", "batao", "seekhni", "seekhna",
    "fees", "fee", "cost", "price", "placement", "package", "duration", "kitne din",
    "months", "syllabus", "eligibility", "kitna time", "job guarantee", "certificate"
]

HANDOFF_TRIGGERS = [
    "counselor", "human", "advisor", "talk to human", "speak to counselor",
    "call me", "callback", "phone pe", "agent", "executive", "connect me",
    "real person", "insan se baat", "direct call", "contact number", "office contact",
    "contact info"
]

COMPLAINT_TRIGGERS = [
    "not working", "bakwas", "useless", "slow", "stupid bot", "bekaar", "bad",
    "worst", "annoying", "galat bata rahe", "problem"
]

ABUSIVE_WORDS = {
    "abuse", "idiot", "fool", "nonsense", "bloody", "fraud", "scam"
}


def is_greeting(text: str) -> bool:
    t = re.sub(r"[^\w\s]", "", text).strip().lower()
    return t in GREETING_WORDS or any(t.startswith(g + " ") for g in GREETING_WORDS)



def is_general_question(text: str) -> bool:
    t = text.strip().lower()
    if t.endswith("?"):
        return True
    return any(trigger in t for trigger in QUESTION_TRIGGERS)


def is_handoff_request(text: str) -> bool:
    t = text.strip().lower()
    return any(trigger in t for trigger in HANDOFF_TRIGGERS)


def is_complaint(text: str) -> bool:
    t = text.strip().lower()
    return any(trigger in t for trigger in COMPLAINT_TRIGGERS)


def is_abusive(text: str) -> bool:
    words = set(re.findall(r"\w+", text.lower()))
    return bool(words.intersection(ABUSIVE_WORDS))


EXIT_TRIGGERS = {
    "exit", "quit", "bye", "goodbye", "alvida", "stop", "close", "band karo",
    "khatam", "khatam karo", "chodo", "chhod do", "rehne do", "rehn do"
}

REFUSAL_PHRASES = [
    "baat nahi karni", "baat nahi krni", "baat nhi karni", "baat nhi krni",
    "nahi karni", "nahi krni", "nhi karni", "nhi krni",
    "nahi karni baat", "nahi krni baat",
    "mujhe baat nahi", "mujhe baat nhi",
    "don't want to talk", "dont want to talk", "not interested to talk",
    "baad me baat", "baad mein baat", "baad me", "baad mein",
    "leave me", "nahi chahiye", "nhi chahiye"
]


def is_exit_or_refusal(text: str) -> bool:
    t = text.strip().lower()
    t_clean = re.sub(r"[^\w\s]", " ", t).strip()
    words = t_clean.split()
    if t_clean in EXIT_TRIGGERS or (len(words) == 1 and words[0] in EXIT_TRIGGERS):
        return True
    return any(p in t_clean for p in REFUSAL_PHRASES)


def resolve_program_exact(text: str) -> Optional[str]:
    """Matches text against known programs via exact name or keyword list with word boundaries."""
    t = text.strip().lower()
    for p in REAL_PROGRAMS:
        if t == p.lower():
            return p
    words = set(re.findall(r"\b\w+\b", t))
    for prog, keywords in PROGRAM_KEYWORDS.items():
        for kw in keywords:
            kw_clean = kw.strip().lower()
            if " " in kw_clean:
                if re.search(r"\b" + re.escape(kw_clean) + r"\b", t):
                    return prog
            else:
                if kw_clean in words:
                    return prog
    return None


def resolve_subprogram_rules(available_subs: List[str], text: str) -> Optional[str]:
    """Fast rule-based matching for subprograms."""
    t = text.strip().lower()
    # 1. Exact match with any available subprogram
    for s in available_subs:
        if t == s.lower():
            return s

    # 2. Match against subprogram keyword dictionary
    current_keywords = build_dynamic_subprogram_keywords()
    for s in available_subs:
        keywords = current_keywords.get(s, [])
        for kw in keywords:
            # Word boundary match or substring for compound phrases
            if kw == t or f" {kw} " in f" {t} " or (len(kw) > 3 and kw in t):
                return s

    # 3. Partial word overlap
    t_words = set(re.findall(r"\w+", t))
    for s in available_subs:
        s_words = set(re.findall(r"\w+", s.lower()))
        # Check if user typed key distinguishing words (excluding generic words like 'and', 'with')
        content_words = s_words - {"and", "with", "the", "for", "systems"}
        if content_words and content_words.issubset(t_words):
            return s

    return None


def resolve_subprogram(available_subs: List[str], text: str) -> Optional[str]:
    """
    Main subprogram resolver: tries fast rules first; falls back to Groq LLM if rules fail.
    """
    matched = resolve_subprogram_rules(available_subs, text)
    if matched:
        return matched

    # LLM fallback
    try:
        from app.llm_client import fallback_resolve_subprogram_llm
        llm_match = fallback_resolve_subprogram_llm(available_subs, text)
        if llm_match in available_subs:
            return llm_match
    except Exception as e:
        logger.warning(f"LLM subprogram fallback failed: {e}")

    return None