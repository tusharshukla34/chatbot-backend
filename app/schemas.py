from typing import List
from pydantic import BaseModel


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str
    suggested_courses: List[dict] = []
    quick_replies: List[str] = []