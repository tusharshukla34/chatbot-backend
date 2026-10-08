import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.config import ADMIN_PASSWORD, ADMIN_USERNAME
from app.security import mask_phone, mask_email, mask_pii_in_text, constant_time_auth


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_pii_masking():
    """Verify phone and email masking."""
    assert mask_phone("9876543210") == "98****3210"
    assert mask_email("rohit.kumar@cybrom.com") == "r****@cybrom.com"

    text_with_pii = "Contact student Pooja at 9876543210 or pooja@example.com immediately."
    masked = mask_pii_in_text(text_with_pii)
    assert "98****3210" in masked
    assert "p****@example.com" in masked
    assert "pooja@example.com" not in masked


def test_constant_time_admin_auth():
    """Verify constant-time credentials verification."""
    assert constant_time_auth(ADMIN_USERNAME, ADMIN_PASSWORD) is True
    assert constant_time_auth("wrong_user", ADMIN_PASSWORD) is False
    assert constant_time_auth(ADMIN_USERNAME, "wrong_pass") is False


def test_admin_leads_pagination_and_auth(client):
    """Verify admin leads endpoint requires auth and supports pagination."""
    # Unauthorized
    r_unauth = client.get("/admin/leads")
    assert r_unauth.status_code == 401

    # Authorized
    r_auth = client.get("/admin/leads?page=1&limit=2", auth=(ADMIN_USERNAME, ADMIN_PASSWORD))
    assert r_auth.status_code == 200
    data = r_auth.json()
    assert "total_leads" in data
    assert "page" in data
    assert data["page"] == 1
    assert data["limit"] == 2
    assert len(data["leads"]) <= 2


def test_admin_leads_csv_export(client):
    """Verify admin CSV export endpoint."""
    resp = client.get("/admin/leads/export", auth=(ADMIN_USERNAME, ADMIN_PASSWORD))
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "attachment; filename=cybrom_leads.csv" in resp.headers["content-disposition"]
    csv_text = resp.text
    assert "Session ID,First Name,WhatsApp Number,Email" in csv_text


def test_admin_stats_endpoint(client):
    """Verify stats endpoint returns analytics data."""
    resp = client.get("/admin/stats", auth=(ADMIN_USERNAME, ADMIN_PASSWORD))
    assert resp.status_code == 200
    data = resp.json()
    assert "total_leads" in data
    assert "total_course_interests" in data
    assert "daily_leads" in data
    assert "top_selected_courses" in data


def test_rate_limiting_enforcement(client, monkeypatch):
    """Verify rate limiter throws 429 when threshold is exceeded on endpoint."""
    import app.security
    monkeypatch.setattr(app.security, "RATE_LIMIT_PER_MINUTE", 5)

    sess_id = "test_rate_limit_bucket_99"
    status_codes = []
    for _ in range(8):
        r = client.post("/mark-interest", json={"session_id": sess_id, "course_title": "Full Stack Python"})
        status_codes.append(r.status_code)
        if r.status_code == 429:
            break

    assert 429 in status_codes

