import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.browse_resolver import (
    resolve_subprogram,
    resolve_subprogram_rules,
    is_handoff_request,
    is_abusive,
    is_general_question,
)
from app.validators import clean_phone, is_valid_phone, clean_email, is_valid_email, clean_name
from app.session_store import get_session, save_session


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_subprogram_rule_matching_all_categories():
    """Verify all catalog subprograms resolve correctly via rule engine."""
    ai_subs = [
        "AI Engineering, MLOps & Development",
        "AI, IoT & Intelligent Systems",
        "Artificial Intelligence with Gen AI",
    ]
    assert resolve_subprogram_rules(ai_subs, "gen ai") == "Artificial Intelligence with Gen AI"
    assert resolve_subprogram_rules(ai_subs, "mlops") == "AI Engineering, MLOps & Development"
    assert resolve_subprogram_rules(ai_subs, "iot") == "AI, IoT & Intelligent Systems"

    cyber_subs = ["Cyber Security & Ethical Hacking", "DevOps & Cloud"]
    assert resolve_subprogram_rules(cyber_subs, "ethical hacking") == "Cyber Security & Ethical Hacking"
    assert resolve_subprogram_rules(cyber_subs, "cloud") == "DevOps & Cloud"
    assert resolve_subprogram_rules(cyber_subs, "aws") == "DevOps & Cloud"

    data_subs = ["Data Analytics"]
    assert resolve_subprogram_rules(data_subs, "data analyst") == "Data Analytics"
    assert resolve_subprogram_rules(data_subs, "power bi") == "Data Analytics"

    web_subs = ["Python", "Java", "MERNSTACK"]
    assert resolve_subprogram_rules(web_subs, "python") == "Python"
    assert resolve_subprogram_rules(web_subs, "react") == "MERNSTACK"
    assert resolve_subprogram_rules(web_subs, "springboot") == "Java"


def test_robust_phone_cleaning_and_validation():
    """Verify normalization of various Indian phone formats."""
    assert clean_phone("+91 98765-43210") == "9876543210"
    assert is_valid_phone("+91 98765-43210") is True

    assert clean_phone("09876543210") == "9876543210"
    assert is_valid_phone("09876543210") is True

    assert clean_phone("98765 43210") == "9876543210"
    assert is_valid_phone("98765 43210") is True

    # Word numbers
    words_num = "nine eight seven six five four three two one zero"
    assert clean_phone(words_num) == "9876543210"
    assert is_valid_phone(words_num) is True

    # Invalid numbers
    assert is_valid_phone("12345") is False
    assert is_valid_phone("1234567890") is False  # Indian numbers start with 6,7,8,9


def test_robust_email_cleaning_and_validation():
    """Verify email normalization and validation."""
    assert clean_email("  Aman.Kumar@Example.Com  ") == "aman.kumar@example.com"
    assert is_valid_email("  Aman.Kumar@Example.Com  ") is True
    assert clean_email("<aman@cybrom.com>") == "aman@cybrom.com"
    assert is_valid_email("invalid-email") is False


def test_name_cleaning():
    """Verify name cleaning from conversational sentences."""
    assert clean_name("My name is Rohit Sharma") == "Rohit Sharma"
    assert clean_name("mera naam Pooja hai") == "Pooja"
    assert clean_name("Aman Gupta 🚀") == "Aman Gupta"


def test_intent_detection_flags():
    """Verify intent helper triggers."""
    assert is_handoff_request("mujhe counselor se baat karni hai") is True
    assert is_handoff_request("please call me") is True
    assert is_general_question("python kya hota hai?") is True
    assert is_general_question("fees kitni hai") is True
    assert is_abusive("you idiot fool") is True


def test_step_and_step_label_in_response(client):
    """Verify /chat responses contain step numbers and step labels."""
    sess_id = "test_step_sync_1"
    resp = client.post("/chat", json={"session_id": sess_id, "message": "Hi"})
    assert resp.status_code == 200
    data = resp.json()
    assert "step" in data
    assert "step_label" in data
    assert data["step"] == 1


def test_interruption_preserves_pending_state(client):
    """Asking a question mid-conversation must answer and retain pending lead capture stage."""
    sess_id = "test_interrupt_flow_1"
    # Initiate chat
    client.post("/chat", json={"session_id": sess_id, "message": "Hi"})

    # Send a question about fees instead of answering name
    resp = client.post("/chat", json={"session_id": sess_id, "message": "fees kitni hai course ki?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["step"] == 1
    # Check that session is still at first_name stage
    sess = get_session(sess_id)
    assert sess["lead_stage"] == "first_name"
    assert sess["lead_captured"] is False


def test_subprogram_selection_advances_to_courses_without_interruption_loop(client):
    """Verify selecting a 5-word subprogram (e.g. Artificial Intelligence with Gen AI) moves to step 4 without looping."""
    sess_id = "test_subprog_no_loop_1"
    # Seed session at subprogram stage
    sess = get_session(sess_id)
    sess["lead_captured"] = True
    sess["browse_stage"] = "subprogram"
    sess["selected_program"] = "AI-ML"
    save_session(sess_id, sess)

    resp = client.post("/chat", json={"session_id": sess_id, "message": "Artificial Intelligence with Gen AI"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["step"] == 4
    assert data["step_label"] == "Matches"
    assert len(data.get("suggested_courses", [])) >= 1
    # Check that it did NOT repeat the subprogram question
    assert "Which AI-ML track interests you" not in data["reply"]

