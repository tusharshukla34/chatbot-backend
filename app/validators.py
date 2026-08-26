import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?\d{10,13}$")


def is_valid_email(text: str) -> bool:
    return bool(EMAIL_RE.match(text.strip()))


def is_valid_phone(text: str) -> bool:
    cleaned = text.strip().replace(" ", "").replace("-", "")
    return bool(PHONE_RE.match(cleaned))


def clean_phone(text: str) -> str:
    return text.strip().replace(" ", "").replace("-", "")