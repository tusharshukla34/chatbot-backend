import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(text: str) -> bool:
    return bool(EMAIL_RE.match(text.strip()))


def clean_phone(text: str) -> str:
    cleaned = text.strip().replace(" ", "").replace("-", "").replace("+", "")
    # strip a leading 91 country code if present, so we always store a plain 10-digit number
    if cleaned.startswith("91") and len(cleaned) == 12:
        cleaned = cleaned[2:]
    return cleaned


def is_valid_phone(text: str) -> bool:
    cleaned = clean_phone(text)
    return cleaned.isdigit() and len(cleaned) == 10 and cleaned[0] in "6789"