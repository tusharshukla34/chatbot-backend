import re
from typing import Optional

EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

WORD_TO_DIGIT = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ek": "1", "do": "2", "teen": "3", "char": "4", "panch": "5",
    "chhe": "6", "saat": "7", "aath": "8", "nau": "9", "shunya": "0"
}


def clean_email(text: str) -> str:
    """Cleans email by stripping whitespaces, punctuation, and downcasing."""
    cleaned = text.strip().lower()
    # Remove accidental surrounding quotes or braces
    cleaned = cleaned.strip("\"'<>[],;()")
    return cleaned


def is_valid_email(text: str) -> bool:
    """Checks validity of an email string."""
    cleaned = clean_email(text)
    return bool(EMAIL_RE.match(cleaned))


def clean_phone(text: str) -> str:
    """
    Robust phone normalizer:
    - Replaces number words with digits (e.g. "nine eight..." -> "98...")
    - Extracts 10-12 digit sequence from mixed text (e.g., "my whatsapp is +91 98765-43210")
    - Strips +91, 91, or leading 0 to return pure 10-digit Indian mobile number.
    """
    raw = text.lower().strip()

    # Convert word digits to numeric digits
    for word, digit in WORD_TO_DIGIT.items():
        raw = re.sub(rf"\b{word}\b", digit, raw)

    # Strip non-digits
    digits_only = re.sub(r"\D", "", raw)

    # If user provided 12 digits starting with 91 (country code)
    if len(digits_only) == 12 and digits_only.startswith("91"):
        digits_only = digits_only[2:]
    # If user entered 11 digits with leading 0 (trunk code)
    elif len(digits_only) == 11 and digits_only.startswith("0"):
        digits_only = digits_only[1:]
    # If longer text contained extraneous digits, search for 10-digit sequence starting with 6, 7, 8, 9
    elif len(digits_only) > 10:
        match = re.search(r"[6-9]\d{9}", digits_only)
        if match:
            return match.group(0)

    return digits_only


def is_valid_phone(text: str) -> bool:
    """Returns True if the normalized phone number is a valid 10-digit Indian mobile number."""
    cleaned = clean_phone(text)
    return len(cleaned) == 10 and cleaned.isdigit() and cleaned[0] in "6789"


def clean_name(text: str) -> str:
    """
    Strips conversational prefixes like 'My name is', 'Mera naam', emojis,
    and returns a clean, capitalized name string.
    """
    raw = text.strip()
    # Strip emojis and punctuation
    raw = re.sub(r"[^\w\s]", "", raw)

    # Strip conversational prefixes
    patterns = [
        r"^(my\s+name\s+is\s+)",
        r"^(mera\s+naam\s+hai\s+)",
        r"^(mera\s+naam\s+)",
        r"^(naam\s+hai\s+)",
        r"^(i\s+am\s+)",
        r"^(this\s+is\s+)",
        r"^(myself\s+)",
    ]
    for pat in patterns:
        raw = re.sub(pat, "", raw, flags=re.IGNORECASE)

    # Strip conversational trailing words like 'hai', 'hoon'
    raw = re.sub(r"\s+(hai|hoon|hu|h)$", "", raw.strip(), flags=re.IGNORECASE)

    raw = raw.strip()
    # Title-case valid alphabetic name
    if raw.replace(" ", "").isalpha():
        return raw.title()
    return raw