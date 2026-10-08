import uuid
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.session_store import get_session
from app.db import get_all_leads


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_complete_end_to_end_conversational_flow(client, monkeypatch):
    """
    Simulates a full student conversion flow:
    Greeting -> Name -> WhatsApp (+91) -> Email -> Education -> Program -> Subprogram -> Course -> Interest
    """
    # Mock LLM calls to keep integration test fast and deterministic
    import app.llm_client
    monkeypatch.setattr(app.llm_client, "is_actually_a_name", lambda text: True)
    monkeypatch.setattr(app.llm_client, "greeting_reply", lambda: "Hello! Cybrom Course Advisor mein aapka swagat hai.")
    monkeypatch.setattr(app.llm_client, "localize_reply", lambda msg, text: msg)
    monkeypatch.setattr(app.llm_client, "mirror_language", lambda msg, text: msg)
    monkeypatch.setattr(app.llm_client, "interpret_program_from_text", lambda text: "Fullstack Web")

    sess_id = f"e2e_student_{uuid.uuid4().hex[:8]}"

    # 1. Greeting
    r1 = client.post("/chat", json={"session_id": sess_id, "message": "Hi counselor!"})
    assert r1.status_code == 200
    assert r1.json()["step"] == 1

    # 2. Name
    r2 = client.post("/chat", json={"session_id": sess_id, "message": "Rohit Verma"})
    assert r2.status_code == 200
    assert r2.json()["step"] == 1
    assert "WhatsApp" in r2.json()["reply"] or "number" in r2.json()["reply"]

    # 3. WhatsApp (+91 with spaces)
    r3 = client.post("/chat", json={"session_id": sess_id, "message": "+91 98765 43210"})
    assert r3.status_code == 200
    assert r3.json()["step"] == 1
    assert "email" in r3.json()["reply"].lower()

    # 4. Email
    r4 = client.post("/chat", json={"session_id": sess_id, "message": "rohit.verma@example.com"})
    assert r4.status_code == 200
    assert r4.json()["step"] == 1
    assert "education level" in r4.json()["reply"].lower()
    assert "Graduate" in r4.json()["quick_replies"]

    # Check lead was recorded
    session_data = get_session(sess_id)
    assert session_data["lead_captured"] is True
    assert session_data["lead_data"]["whatsapp_number"] == "9876543210"
    assert session_data["lead_data"]["email"] == "rohit.verma@example.com"

    # 5. Education Level
    r5 = client.post("/chat", json={"session_id": sess_id, "message": "Graduate"})
    assert r5.status_code == 200
    assert r5.json()["step"] == 2
    assert "Fullstack Web" in r5.json()["quick_replies"]

    # 6. Program Selection
    r6 = client.post("/chat", json={"session_id": sess_id, "message": "Fullstack Web"})
    assert r6.status_code == 200
    assert r6.json()["step"] == 3
    assert "Python" in r6.json()["quick_replies"]

    # 7. Subprogram Selection
    r7 = client.post("/chat", json={"session_id": sess_id, "message": "Python"})
    assert r7.status_code == 200
    assert r7.json()["step"] == 4
    assert len(r7.json()["suggested_courses"]) > 0

    # 8. Exact Course Selection
    first_course_title = r7.json()["suggested_courses"][0]["title"]
    r8 = client.post("/chat", json={"session_id": sess_id, "message": first_course_title})
    assert r8.status_code == 200
    assert r8.json()["step"] == 4

    # 9. Mark Interest CTA Click
    r9 = client.post("/mark-interest", json={"session_id": sess_id, "course_title": first_course_title})
    assert r9.status_code == 200
    assert r9.json()["status"] == "ok"

    # Verify session finished cleanly
    final_session = get_session(sess_id)
    assert final_session["browse_stage"] == "post_selection"
    assert final_session["selected_course"] == first_course_title
