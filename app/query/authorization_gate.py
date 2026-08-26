"""
Day 21 — Authorization Gate.

Checks whether the requesting user is allowed to see/act on a given
borrower, using data/users.json's existing portfolio structure as the
sole source of truth (RM001's and RM002's portfolios are deliberately
disjoint — RM002's own users.json entry says as much: "used to test the
Authorization Gate"). credit_officer role has portfolio "ALL".

This must run BEFORE Response Synthesis ever sees any borrower-specific
data — the Router (Day 22) calls this right after Entity Resolution and
stops the pipeline on a deny, rather than resolving+authorizing lazily
after a handler has already touched the data.
"""

import json

from app.config import DATA_DIR

USERS_PATH = DATA_DIR / "users.json"


def _load_users() -> dict:
    users = json.loads(USERS_PATH.read_text())
    return {u["id"]: u for u in users}


def check_authorization(user_id: str, borrower_id: str) -> dict:
    """Returns {"authorized": bool, "reason": str}. Unknown user_id or
    borrower_id both fail closed (authorized=False), not open."""
    users = _load_users()
    user = users.get(user_id)

    if user is None:
        return {"authorized": False, "reason": f"unknown user_id '{user_id}'"}

    portfolio = user.get("portfolio")

    if portfolio == "ALL":
        return {"authorized": True, "reason": f"{user['role']} has full portfolio visibility"}

    if isinstance(portfolio, list) and borrower_id in portfolio:
        return {"authorized": True, "reason": f"{borrower_id} is in {user['name']}'s portfolio"}

    return {
        "authorized": False,
        "reason": f"{borrower_id} is not in {user.get('name', user_id)}'s portfolio",
    }


def check_rm_portfolio_authorization(user_id: str, target_rm_id: str) -> dict:
    """Separate from check_authorization() above (which is per-borrower)
    — this governs the NEW RM-portfolio-level queries ("how many Red
    borrowers does RM002 manage"): a regular RM can see their OWN
    portfolio's stats, and credit_officer (portfolio == "ALL") can see
    anyone's, but one RM asking about a DIFFERENT RM's portfolio is
    denied — that's competitive/managerial information, not something
    every RM should see about every other RM by default. Unknown user_id
    fails closed, same as check_authorization()."""
    users = _load_users()
    user = users.get(user_id)

    if user is None:
        return {"authorized": False, "reason": f"unknown user_id '{user_id}'"}

    if user.get("portfolio") == "ALL":
        return {"authorized": True, "reason": f"{user['role']} has full portfolio visibility"}

    if user_id == target_rm_id:
        return {"authorized": True, "reason": "viewing own portfolio"}

    return {
        "authorized": False,
        "reason": f"{user.get('name', user_id)} cannot view {target_rm_id}'s portfolio",
    }


if __name__ == "__main__":
    r1 = check_authorization("RM001", "MSME-1001")  # in Meera's portfolio
    print("RM001 -> MSME-1001:", r1)
    assert r1["authorized"] is True

    r2 = check_authorization("RM001", "MSME-1009")  # in Arjun's portfolio, not Meera's
    print("RM001 -> MSME-1009:", r2)
    assert r2["authorized"] is False

    r3 = check_authorization("CO001", "MSME-1009")  # credit officer, ALL
    print("CO001 -> MSME-1009:", r3)
    assert r3["authorized"] is True

    r4 = check_authorization("UNKNOWN-USER", "MSME-1001")
    print("unknown user:", r4)
    assert r4["authorized"] is False

    print("Authorization gate smoke test passed.")

    r5 = check_rm_portfolio_authorization("RM001", "RM001")  # own portfolio
    print("RM001 -> own portfolio:", r5)
    assert r5["authorized"] is True

    r6 = check_rm_portfolio_authorization("RM001", "RM002")  # someone else's
    print("RM001 -> RM002's portfolio:", r6)
    assert r6["authorized"] is False

    r7 = check_rm_portfolio_authorization("CO001", "RM002")  # credit officer, any RM
    print("CO001 -> RM002's portfolio:", r7)
    assert r7["authorized"] is True

    print("RM-portfolio authorization smoke test passed.")