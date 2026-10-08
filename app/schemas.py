from typing import List, Optional
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128, description="Unique session identifier")
    message: str = Field(..., max_length=1000, description="User message text capped at 1000 chars")


class ChatResponse(BaseModel):
    reply: str
    suggested_courses: List[dict] = []
    quick_replies: List[str] = []
    step: int = 1
    step_label: str = "Level"


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