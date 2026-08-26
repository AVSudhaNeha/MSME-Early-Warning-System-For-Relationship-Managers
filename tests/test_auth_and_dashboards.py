"""
Tests for the NEW login / session / role-based dashboard layer only.

These are additive tests (per the "add only minimal new tests"
requirement) -- they never touch, replace, or re-derive expected values
for any existing scoring/monitoring/RAG/evaluation behavior.

Where a test needs to exercise an admin-only action (Run Monitoring /
Advance Cycle), it patches scripts.run_monitoring_cycle's real entry
point with a stand-in result. That's deliberate: this test file's job
is to prove the NEW routing/role-gating layer calls that entry point
and enforces ADMIN-only access to it -- not to re-run (and mutate on
disk, or make live network calls) the already-existing monitoring
pipeline, which is out of scope for this change per the "do not modify
existing monitoring logic" requirement.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
import scripts.run_monitoring_cycle  # noqa: F401 (imported so patch() can resolve it)

ADMIN_ID = "CO001"
ADMIN_PASSWORD = "admin123"

RM1_ID = "RM001"
RM1_PASSWORD = "rm001pass"

RM2_ID = "RM002"
RM2_PASSWORD = "rm002pass"


@pytest.fixture
def client():
    return TestClient(app)


def _login(client, user_id, password):
    return client.post("/api/login", json={"user_id": user_id, "password": password})


# ------------------------------------------------------------------
# Login
# ------------------------------------------------------------------

def test_login_valid_admin_succeeds(client):
    res = _login(client, ADMIN_ID, ADMIN_PASSWORD)
    assert res.status_code == 200
    body = res.json()
    assert body["user"]["id"] == ADMIN_ID
    assert body["user"]["role"] == "ADMIN"
    assert "msme_session" in res.cookies


def test_login_valid_rm_succeeds(client):
    res = _login(client, RM1_ID, RM1_PASSWORD)
    assert res.status_code == 200
    body = res.json()
    assert body["user"]["id"] == RM1_ID
    assert body["user"]["role"] == "RM"


def test_login_invalid_password_denied(client):
    res = _login(client, RM1_ID, "wrong-password")
    assert res.status_code == 401


def test_login_unknown_user_denied(client):
    res = _login(client, "NOT-A-REAL-USER", "whatever")
    assert res.status_code == 401


# ------------------------------------------------------------------
# Roles / session
# ------------------------------------------------------------------

def test_session_requires_login(client):
    res = client.get("/api/session")
    assert res.status_code == 401


def test_session_reflects_admin_role_after_login(client):
    _login(client, ADMIN_ID, ADMIN_PASSWORD)
    res = client.get("/api/session")
    assert res.status_code == 200
    assert res.json()["user"]["role"] == "ADMIN"


def test_session_reflects_rm_role_after_login(client):
    _login(client, RM1_ID, RM1_PASSWORD)
    res = client.get("/api/session")
    assert res.status_code == 200
    assert res.json()["user"]["role"] == "RM"


# ------------------------------------------------------------------
# RM portfolio isolation (existing Authorization Gate, exercised through
# the existing, UNCHANGED X-User-Id-header endpoints -- this just proves
# the new login layer hands it the right identity)
# ------------------------------------------------------------------

def test_rm_can_access_own_borrower(client):
    _login(client, RM1_ID, RM1_PASSWORD)
    res = client.get("/api/borrowers/MSME-1001", headers={"X-User-Id": RM1_ID})
    assert res.status_code == 200
    assert res.json()["id"] == "MSME-1001"


def test_rm_denied_other_rm_borrower(client):
    _login(client, RM1_ID, RM1_PASSWORD)
    # MSME-1004 belongs to RM002, not RM001 (data/users.json / rm_lookup)
    res = client.get("/api/borrowers/MSME-1004", headers={"X-User-Id": RM1_ID})
    assert res.status_code == 403


def test_admin_sees_full_portfolio(client):
    _login(client, ADMIN_ID, ADMIN_PASSWORD)
    res = client.get("/api/borrowers", headers={"X-User-Id": ADMIN_ID})
    assert res.status_code == 200
    assert len(res.json()["borrowers"]) == 9  # all borrowers in records.json


def test_rm_sees_only_own_portfolio(client):
    _login(client, RM1_ID, RM1_PASSWORD)
    res = client.get("/api/borrowers", headers={"X-User-Id": RM1_ID})
    assert res.status_code == 200
    ids = {b["id"] for b in res.json()["borrowers"]}
    assert ids == {"MSME-1001", "MSME-1002", "MSME-1003", "MSME-1006", "MSME-1008"}


# ------------------------------------------------------------------
# Admin-only actions: Run Monitoring / Advance Cycle
# ------------------------------------------------------------------

def test_run_monitoring_requires_login(client):
    res = client.post("/api/monitoring/run")
    assert res.status_code == 401


def test_rm_denied_run_monitoring(client):
    _login(client, RM1_ID, RM1_PASSWORD)
    res = client.post("/api/monitoring/run")
    assert res.status_code == 403


def test_admin_allowed_run_monitoring(client):
    _login(client, ADMIN_ID, ADMIN_PASSWORD)
    fake_result = {"borrowers_processed": 9, "completed": 9, "failed": 0, "results": []}
    with patch(
        "scripts.run_monitoring_cycle.run_portfolio_monitoring_cycle",
        return_value=fake_result,
    ):
        res = client.post("/api/monitoring/run")
    assert res.status_code == 200
    assert res.json() == fake_result


def test_rm_denied_advance_cycle(client):
    _login(client, RM1_ID, RM1_PASSWORD)
    res = client.post("/api/cycle/advance")
    assert res.status_code == 403


def test_admin_allowed_advance_cycle(client):
    _login(client, ADMIN_ID, ADMIN_PASSWORD)
    fake_result = {"borrowers_processed": 9, "completed": 9, "failed": 0, "results": []}
    with patch(
        "scripts.run_monitoring_cycle.run_portfolio_monitoring_cycle",
        return_value=fake_result,
    ):
        res = client.post("/api/cycle/advance")
    assert res.status_code == 200
    body = res.json()
    assert "current_cycle" in body
    assert body["monitoring_result"] == fake_result


def test_cycle_current_requires_login(client):
    res = client.get("/api/cycle/current")
    assert res.status_code == 401


def test_cycle_current_available_to_rm_read_only(client):
    # RMs can see the derived cycle number (read-only), just not trigger it.
    _login(client, RM1_ID, RM1_PASSWORD)
    res = client.get("/api/cycle/current")
    assert res.status_code == 200
    assert isinstance(res.json()["current_cycle"], int)


# ------------------------------------------------------------------
# Logout
# ------------------------------------------------------------------

def test_logout_clears_session(client):
    _login(client, RM1_ID, RM1_PASSWORD)
    assert client.get("/api/session").status_code == 200

    res = client.post("/api/logout")
    assert res.status_code == 200

    assert client.get("/api/session").status_code == 401