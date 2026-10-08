import time
import uuid
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.notifiers import BaseNotifier, NotificationDispatcher


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_notifier_interface():
    """Verify that pluggable notifier interface can be instantiated and dispatched."""
    class MockCustomNotifier(BaseNotifier):
        def __init__(self):
            self.sent_events = []

        def send(self, event_type, message, metadata=None):
            self.sent_events.append((event_type, message))
            return True

    mock_notifier = MockCustomNotifier()
    custom_disp = NotificationDispatcher()
    custom_disp.notifiers = [mock_notifier]

    custom_disp.dispatch("test_event", "Hello test notification", force=True)
    time.sleep(0.3)

    found = any(e[0] == "test_event" for e in mock_notifier.sent_events)
    assert found is True


def test_all_chat_responses_have_valid_step_numbers(client):
    """Verify step integers are always 1..4 across chat turns on a fresh session."""
    sess_id = f"test_p3_fresh_{uuid.uuid4().hex[:8]}"

    # Turn 1: Greeting
    r1 = client.post("/chat", json={"session_id": sess_id, "message": "Hi"})
    assert r1.status_code == 200
    assert r1.json()["step"] == 1

    # Turn 2: Name
    r2 = client.post("/chat", json={"session_id": sess_id, "message": "Karan Malhotra"})
    assert r2.status_code == 200
    assert r2.json()["step"] == 1

    # Turn 3: WhatsApp
    r3 = client.post("/chat", json={"session_id": sess_id, "message": "9876543210"})
    assert r3.status_code == 200
    assert r3.json()["step"] == 1

    # Turn 4: Email
    r4 = client.post("/chat", json={"session_id": sess_id, "message": "karan@example.com"})
    assert r4.status_code == 200
    assert r4.json()["step"] == 1

    # Turn 5: Education
    r5 = client.post("/chat", json={"session_id": sess_id, "message": "Graduate"})
    assert r5.status_code == 200
    assert r5.json()["step"] == 2
    assert "Fullstack Web" in r5.json()["quick_replies"]

    # Turn 6: Program
    r6 = client.post("/chat", json={"session_id": sess_id, "message": "Fullstack Web"})
    assert r6.status_code == 200
    assert r6.json()["step"] == 3
