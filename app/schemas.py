import re
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


def _clean_gender(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"\bmadad\s+kar\s+sakta/sakti\s+hoon\b", "madad karoon", text, flags=re.IGNORECASE)
    text = re.sub(r"\bmadad\s+kar\s+sakti/sakta\s+hoon\b", "madad karoon", text, flags=re.IGNORECASE)
    text = re.sub(r"\bhelp\s+kar\s+sakta/sakti\s+hoon\b", "help karoon", text, flags=re.IGNORECASE)
    text = re.sub(r"\bhelp\s+kar\s+sakti/sakta\s+hoon\b", "help karoon", text, flags=re.IGNORECASE)
    text = re.sub(r"\bkar\s+sakta/sakti\s+hoon\b", "karoon", text, flags=re.IGNORECASE)
    text = re.sub(r"\bkar\s+sakti/sakta\s+hoon\b", "karoon", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsakta/sakti\s+hoon\b", "hoon", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsakta/sakti\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsakti/sakta\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsakta/ti\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsakta\s+ya\s+sakti\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bkar\s+sakta/sakti\b", "karoon", text, flags=re.IGNORECASE)
    text = re.sub(r"[ ]{2,}", " ", text)
    return text.strip()


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128, description="Unique session identifier")
    message: str = Field(..., max_length=1000, description="User message text capped at 1000 chars")


class ChatResponse(BaseModel):
    reply: str
    suggested_courses: List[dict] = []
    quick_replies: List[str] = []
    step: int = 1
    step_label: str = "Level"

    @field_validator("reply")
    @classmethod
    def sanitize_reply(cls, v: str) -> str:
        return _clean_gender(v)


class MarkInterestRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    course_title: str = Field(..., min_length=1, max_length=255)


class CallbackRequestSchema(BaseModel):
    session_id: str
    first_name: Optional[str] = None
    whatsapp_number: Optional[str] = None
    email: Optional[str] = None
    reason: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    database: str
    session_store: str
    offline_queue_pending: int