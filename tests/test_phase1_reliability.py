import os
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import is_db_healthy, get_offline_queue_count, save_lead, get_all_leads
from app.session_store import get_session, save_session, get_session_store_status


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health_endpoint_returns_degraded_or_ok(client):
    """Health endpoint must never crash even if PostgreSQL is offline."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"] in ["ok", "degraded"]
    assert "database" in data
    assert "session_store" in data
    assert "offline_queue_pending" in data
    assert isinstance(data["offline_queue_pending"], int)


def test_session_persistence_across_retrieval():
    """Sessions must be reliably saved and retrieved."""
    import uuid
    test_id = f"test_sess_p1_{uuid.uuid4().hex[:8]}"
    sess = get_session(test_id)
    assert sess["lead_stage"] == "first_name"

    sess["lead_data"]["first_name"] = "Anjali"
    sess["lead_stage"] = "whatsapp"
    save_session(test_id, sess)

    # Re-retrieve
    sess_fetched = get_session(test_id)
    assert sess_fetched["lead_data"]["first_name"] == "Anjali"
    assert sess_fetched["lead_stage"] == "whatsapp"



def test_offline_queue_buffering():
    """If DB is unavailable or degraded, save_lead must buffer without throwing."""
    initial_pending = get_offline_queue_count()
    save_lead(
        session_id="test_sess_offline_999",
        first_name="Rohan",
        whatsapp_number="9876543210",
        email="rohan@example.com",
    )
    # Lead must be fetchable via get_all_leads (either in PG or offline queue)
    leads = get_all_leads()
    found = any(l["session_id"] == "test_sess_offline_999" for l in leads)
    assert found is True


def test_no_stray_file():
    """Stray file from previous shell redirect must not exist."""
    assert not os.path.exists("-files \u2022 findstr requirements")
    assert not os.path.exists("-files | findstr requirements")
