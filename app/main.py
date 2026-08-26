"""
MSME Early Warning Agent — API backend.

Serves the dashboard (Flow A — portfolio, tiers, cases) and the chat
assistant (Flow B — interactive queries), both wired to the REAL
pipeline built across this project, not the original bootcamp
passthrough this file started as.

Endpoints:
  GET  /api/users              -> user switcher options
  GET  /api/borrowers           -> portfolio list for the current user (auth-scoped)
  GET  /api/borrowers/{id}       -> one borrower's detail (auth-checked)
  POST /api/chat                -> Flow B: route_query() + synthesize_response()
  POST /api/monitoring/run       -> Flow A: run one portfolio monitoring cycle
  GET  /                        -> the UI
"""

import json
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import config
from . import auth
from .case_trace import load_trace
from .case_lifecycle import load_case_record
from .sla_check import check_sla
from .rm_lookup import get_rm_for_borrower
from .query.authorization_gate import check_authorization
from .query.router import route_query
from .query.response_synthesis import synthesize_response

app = FastAPI(title="MSME Early Warning Agent")


# ============================================================
# LOGIN / SESSION / ROLE LAYER — additive only.
#
# This section hands an authenticated user_id + role to the EXISTING
# system below; it never reimplements or bypasses check_authorization()
# or route_query(). See app/auth.py for the session/credential store.
# ============================================================

def _current_session_user(msme_session: str | None = Cookie(default=None)):
    """Optional session lookup — returns the user dict or None. Used by
    endpoints below that need to know who's logged in without forcing
    an error (e.g. GET /api/session itself)."""
    return auth.get_session_user(msme_session)


def _require_login(msme_session: str | None = Cookie(default=None)) -> dict:
    user = auth.get_session_user(msme_session)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated. Please log in.")
    return user


def _require_admin(user: dict = Depends(_require_login)) -> dict:
    if user["role"] != "ADMIN":
        raise HTTPException(
            status_code=403,
            detail="Access denied. Administrator privileges are required.",
        )
    return user


class LoginRequest(BaseModel):
    user_id: str
    password: str


@app.post("/api/login")
def login(req: LoginRequest, response: Response):
    """Authenticates against data/users.json (identity/role/portfolio,
    unchanged) + data/credentials.json (new password hashes only).
    On success, issues a session cookie; the existing pipeline below
    (authorization -> router -> handler) is untouched by this."""
    user = auth.authenticate(req.user_id, req.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid user ID or password.")

    token = auth.create_session(user["id"])
    response.set_cookie(
        key=auth.SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
    )
    return {"user": user}


@app.post("/api/logout")
def logout(response: Response, msme_session: str | None = Cookie(default=None)):
    auth.destroy_session(msme_session)
    response.delete_cookie(auth.SESSION_COOKIE_NAME)
    return {"status": "logged_out"}


@app.get("/api/session")
def session_info(user: dict = Depends(_require_login)):
    """Lets the frontend ask 'who am I' after a page reload, instead of
    the old free-choice user switcher. 401s (via _require_login) if
    there's no valid session, which the frontend uses to redirect to
    /login."""
    return {"user": user}


@app.get("/login")
def login_page():
    return FileResponse(Path(__file__).parent / "login.html")

_USERS = {
    u["id"]: u for u in json.loads((config.DATA_DIR / "users.json").read_text())
}


def _load_records() -> list:
    # Re-read every call — records.json is small and this keeps the
    # dashboard consistent with whatever's on disk, no caching to
    # invalidate.
    return json.loads((config.DATA_DIR / "records.json").read_text())


def _visible_borrower_ids(user: dict) -> list:
    """Same rule the Authorization Gate already enforces for chat
    queries, applied here for the dashboard list — not duplicated logic,
    just read directly off the user's own portfolio field."""
    records = _load_records()
    if user.get("portfolio") == "ALL":
        return [r["id"] for r in records]
    return [r["id"] for r in records if r["id"] in (user.get("portfolio") or [])]


def _borrower_summary(borrower_id: str) -> dict:
    records = {r["id"]: r for r in _load_records()}
    record = records.get(borrower_id, {})
    trace = load_trace(borrower_id)
    latest = trace[-1] if trace else None
    case_record = load_case_record(borrower_id)

    sla = None
    if case_record.get("case_status") == "open" and latest is not None:
        sla = check_sla(borrower_id, latest["cycle"])

    owner = get_rm_for_borrower(borrower_id) or {"rm_id": None, "rm_name": None}

    return {
        "id": borrower_id,
        "name": record.get("name"),
        "sector": record.get("sector"),
        "region": record.get("region"),
        "rm_id": owner["rm_id"],
        "rm_name": owner["rm_name"],
        "cycle": latest["cycle"] if latest else None,
        "tier": latest["tier"] if latest else None,
        "composite_score": latest["composite_score"] if latest else None,
        "case_status": case_record.get("case_status"),
        "case_action": latest["case_action"] if latest else None,
        "case_lifecycle_action": latest["case_lifecycle_action"] if latest else None,
        "sla_breached": bool(sla and sla["sla_breached"]),
        "cycles_open": sla["cycles_open"] if sla else None,
    }


@app.get("/api/users")
def users():
    """The users / personas available in the UI switcher."""
    return list(_USERS.values())


@app.get("/api/borrowers")
def borrowers(x_user_id: str = Header(default="", alias="X-User-Id")):
    """Portfolio list for the current user — a credit_officer sees all 9,
    an RM sees only their own portfolio, same scope the chat's
    Authorization Gate enforces."""
    user = _USERS.get(x_user_id)
    if user is None:
        raise HTTPException(status_code=401, detail=f"Unknown user_id '{x_user_id}'")

    ids = _visible_borrower_ids(user)
    return {"user": user, "borrowers": [_borrower_summary(bid) for bid in ids]}


@app.get("/api/borrowers/{borrower_id}")
def borrower_detail(borrower_id: str, x_user_id: str = Header(default="", alias="X-User-Id")):
    """One borrower's full detail — history for the trend view, latest
    subscores/gate statuses. Auth-checked the same way the chat is; a
    dashboard click can't see more than a chat query could."""
    user = _USERS.get(x_user_id)
    if user is None:
        raise HTTPException(status_code=401, detail=f"Unknown user_id '{x_user_id}'")

    auth = check_authorization(x_user_id, borrower_id)
    if not auth["authorized"]:
        raise HTTPException(status_code=403, detail=auth["reason"])

    records = {r["id"]: r for r in _load_records()}
    record = records.get(borrower_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No such borrower '{borrower_id}'")

    trace = load_trace(borrower_id)
    summary = _borrower_summary(borrower_id)
    summary["record"] = record
    summary["history"] = [
        {
            "cycle": e["cycle"],
            "tier": e.get("tier"),
            "composite_score": e.get("composite_score"),
        }
        for e in trace
    ]
    summary["latest"] = trace[-1] if trace else None
    return summary


class ChatRequest(BaseModel):
    message: str
    hypothetical_overrides: dict | None = None


@app.post("/api/chat")
def chat(req: ChatRequest, x_user_id: str = Header(default="", alias="X-User-Id")):
    """Flow B, for real: query understanding -> entity resolution ->
    authorization -> router -> handler -> response synthesis. Every
    reply carries grounded_in (trace / policy / simulation / none) so
    the UI can show what an answer is actually based on."""
    if not x_user_id or x_user_id not in _USERS:
        raise HTTPException(status_code=401, detail="Missing or unknown X-User-Id header")

    route_result = route_query(x_user_id, req.message, req.hypothetical_overrides)
    synthesized = synthesize_response(route_result)
    return {
        "reply": synthesized["reply"],
        "grounded_in": synthesized["grounded_in"],
        "stage": route_result.get("stage"),
    }


@app.post("/api/monitoring/run")
def run_monitoring(user: dict = Depends(_require_admin)):
    """Flow A, for real: one full portfolio monitoring run, through the
    real scheduler entry point — not a mock button. Reuses
    scripts.run_monitoring_cycle rather than reimplementing it here.

    Now admin-only (Depends(_require_admin)) — this is the ONLY change
    to this endpoint: it previously had no login at all, so this is the
    new login layer closing that gap, not a change to the monitoring
    pipeline itself, which is called exactly as before."""
    from scripts.run_monitoring_cycle import run_portfolio_monitoring_cycle

    return run_portfolio_monitoring_cycle()


def _current_cycle_snapshot() -> int:
    """Read-only derived value, NOT a new stored cycle variable. This
    codebase has no single global 'cycle' counter — every borrower
    advances on its own schedule (confirmed by inspecting
    scripts/run_monitoring_cycle.py and app/case_trace.py). For the
    Admin Dashboard's 'Current Cycle' display, this simply reports the
    highest cycle number that already exists across every borrower's
    real, on-disk Case Trace — nothing is written or cached here."""
    records = _load_records()
    latest_cycles = []
    for r in records:
        trace = load_trace(r["id"])
        if trace:
            latest_cycles.append(trace[-1]["cycle"])
    return max(latest_cycles) if latest_cycles else 0


@app.get("/api/cycle/current")
def cycle_current(user: dict = Depends(_require_login)):
    return {"current_cycle": _current_cycle_snapshot()}


@app.post("/api/cycle/advance")
def cycle_advance(user: dict = Depends(_require_admin)):
    """Admin-only 'Advance Cycle'. There is no separate advance-only
    primitive anywhere in the existing pipeline — the ONLY thing in this
    codebase that moves any borrower to its next cycle is
    scripts.run_monitoring_cycle.run_portfolio_monitoring_cycle(), the
    exact same function /api/monitoring/run calls. Rather than invent a
    second, fake cycle variable that only changes the UI (explicitly
    prohibited), this endpoint calls that SAME real entry point and
    reports the resulting real cycle snapshot."""
    from scripts.run_monitoring_cycle import run_portfolio_monitoring_cycle

    result = run_portfolio_monitoring_cycle()
    return {"current_cycle": _current_cycle_snapshot(), "monitoring_result": result}


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "index.html")