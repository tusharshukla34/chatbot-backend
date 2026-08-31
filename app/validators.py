import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(text: str) -> bool:
    return bool(EMAIL_RE.match(text.strip()))


def clean_phone(text: str) -> str:
    return text.strip().replace(" ", "").replace("-", "").replace("+", "")


def is_valid_phone(text: str) -> bool:
    cleaned = clean_phone(text)
    if not cleaned.isdigit():
        return False
    # Plain 10-digit Indian mobile number (starts 6-9)
    if len(cleaned) == 10 and cleaned[0] in "6789":
        return True
    # With country code 91 + 10-digit number
    if len(cleaned) == 12 and cleaned.startswith("91") and cleaned[2] in "6789":
        return True
    # International numbers with country code: allow 11-13 digits as a general fallback
    if 11 <= len(cleaned) <= 13:
        return True
    return False