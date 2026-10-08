import logging
import re
import secrets
import time
from collections import defaultdict
from typing import Dict, List, Optional
from fastapi import HTTPException, Request, status

from app.config import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    RATE_LIMIT_PER_MINUTE,
)

logger = logging.getLogger("course_chatbot.security")

# Sliding-window rate limit store: key -> list of epoch timestamps
_rate_limits: Dict[str, List[float]] = defaultdict(list)


def check_rate_limit(request: Request, session_id: Optional[str] = None):
    """
    Enforces sliding-window rate limiting per IP address and per session_id.
    Raises HTTPException 429 if the client exceeds the limit.
    """
    now = time.time()
    window = 60.0
    limit = RATE_LIMIT_PER_MINUTE

    client_ip = request.client.host if request.client else "unknown"
    keys = [f"ip:{client_ip}"]
    if session_id:
        keys.append(f"sess:{session_id}")

    for key in keys:
        timestamps = _rate_limits[key]
        # Prune timestamps older than window
        _rate_limits[key] = [t for t in timestamps if now - t < window]
        if len(_rate_limits[key]) >= limit:
            logger.warning(f"Rate limit exceeded for {key}")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please wait a moment before sending another message.",
            )
        _rate_limits[key].append(now)


def mask_phone(phone: str) -> str:
    """Masks phone number for PII compliance (e.g. 98****3210)."""
    p = str(phone).strip()
    if len(p) >= 10:
        return f"{p[:2]}****{p[-4:]}"
    return "****"


def mask_email(email: str) -> str:
    """Masks email address for PII compliance (e.g. r****@domain.com)."""
    e = str(email).strip()
    if "@" in e:
        name, domain = e.split("@", 1)
        masked_name = name[0] + "****" if len(name) > 1 else "*"
        return f"{masked_name}@{domain}"
    return "****"


def mask_pii_in_text(text: str) -> str:
    """Applies regex masking to phone numbers and emails found in strings."""
    # Mask emails
    text = re.sub(
        r"([a-zA-Z0-9_.+-])[a-zA-Z0-9_.+-]*@([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)",
        r"\1****@\2",
        text,
    )
    # Mask Indian 10-digit phone numbers
    text = re.sub(r"\b([6-9]\d{1})\d{4}(\d{4})\b", r"\1****\2", text)
    return text


def constant_time_auth(user: str, secret: str) -> bool:
    """Constant-time comparison against configured admin credentials."""
    u_ok = secrets.compare_digest(user, ADMIN_USERNAME)
    p_ok = secrets.compare_digest(secret, ADMIN_PASSWORD)
    return bool(u_ok and p_ok)
