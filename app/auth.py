"""
Authentication + session + role layer — ADDITIVE ONLY.

This module answers exactly one question the rest of the system didn't
previously answer: "who is this HTTP request from, really?" It does NOT
answer "is this user allowed to see borrower X" — that question already
has a correct, working answer in app.query.authorization_gate, and this
module never touches it.

Design constraints (per the add-only login/dashboard request):
  - Reuses data/users.json exactly as-is for identity, role, and
    portfolio (RM <-> borrower assignments). Does not modify it, does
    not duplicate its portfolio mapping anywhere.
  - The only NEW data file is data/credentials.json (password hashes),
    keyed by the SAME user ids already in users.json (CO001, RM001,
    RM002). There is no second/competing user table.
  - Two roles are exposed to the new dashboard/login layer:
        ADMIN -> users.json role == "credit_officer" (portfolio "ALL")
        RM    -> users.json role == "relationship_manager"
    These are just a friendlier name for the two roles that already
    existed in users.json and already drove check_authorization()'s
    "ALL" vs "list" branching -- no new role concept is introduced,
    only a display-level alias used by the dashboard layer.
  - Sessions are a brand-new, minimal, in-memory session-token store
    (no prior session mechanism existed in this project -- confirmed by
    inspection: main.py previously trusted a raw X-User-Id header with
    no login at all). A session's ONLY job is to hand the already-
    authenticated user_id to the existing authorization/router
    pipeline, exactly as app.query.router.route_query() already expects
    to receive it.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from typing import Optional

from app.config import DATA_DIR

USERS_PATH = DATA_DIR / "users.json"
CREDENTIALS_PATH = DATA_DIR / "credentials.json"

ADMIN_ROLE = "credit_officer"       # existing role string from users.json
RM_ROLE = "relationship_manager"    # existing role string from users.json

SESSION_COOKIE_NAME = "msme_session"

# In-memory session store: token -> {"user_id": str}
# A fresh, minimal session mechanism (none existed before). Intentionally
# process-local: this is a single-process demo/dev server (uvicorn), and
# nothing elsewhere in the project persists session state either.
_SESSIONS: dict[str, dict] = {}


def _load_users() -> dict:
    users = json.loads(USERS_PATH.read_text())
    return {u["id"]: u for u in users}


def _load_credentials() -> dict:
    credentials_json = os.getenv("CREDENTIALS_JSON")
    if credentials_json:
        raw = json.loads(credentials_json)
        return {k: v for k, v in raw.items() if not k.startswith("_")}
    if not CREDENTIALS_PATH.exists():
        return {}
    raw = json.loads(CREDENTIALS_PATH.read_text())
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def dashboard_role(user: dict) -> Optional[str]:
    """Maps an existing users.json role to the two dashboard roles the
    new login layer cares about. Returns None for any role that isn't
    one of the two (there are only two today, but this stays defensive
    rather than assuming)."""
    role = user.get("role")
    if role == ADMIN_ROLE:
        return "ADMIN"
    if role == RM_ROLE:
        return "RM"
    return None


def authenticate(user_id: str, password: str) -> Optional[dict]:
    """Checks user_id/password against data/credentials.json + the
    existing data/users.json. Returns the user's public profile dict
    (no password) on success, or None on any failure -- unknown user,
    no credentials configured for that user, or wrong password all
    fail the same way, so a login error never reveals which part was
    wrong."""
    users = _load_users()
    user = users.get(user_id)
    if user is None:
        return None

    creds = _load_credentials()
    entry = creds.get(user_id)
    if entry is None:
        return None

    if _hash_password(password) != entry.get("password_sha256"):
        return None

    role = dashboard_role(user)
    if role is None:
        return None

    return {
        "id": user["id"],
        "name": user["name"],
        "role": role,                 # "ADMIN" | "RM"
        "underlying_role": user["role"],
        "portfolio": user.get("portfolio"),
    }


def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    _SESSIONS[token] = {"user_id": user_id}
    return token


def get_session_user(token: Optional[str]) -> Optional[dict]:
    """Resolves a session token back to the same kind of profile dict
    authenticate() returns. Re-reads users.json each call (same
    no-caching approach main.py already uses for records.json) so a
    portfolio change on disk is reflected without restarting sessions."""
    if not token:
        return None
    session = _SESSIONS.get(token)
    if session is None:
        return None

    users = _load_users()
    user = users.get(session["user_id"])
    if user is None:
        return None

    role = dashboard_role(user)
    if role is None:
        return None

    return {
        "id": user["id"],
        "name": user["name"],
        "role": role,
        "underlying_role": user["role"],
        "portfolio": user.get("portfolio"),
    }


def destroy_session(token: Optional[str]) -> None:
    if token:
        _SESSIONS.pop(token, None)