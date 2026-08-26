"""
GST Collectors — two distinct signals, deliberately separate:

1. collect_gst_registration() — REAL call to sandbox.co.in. Returns current
   status only (Active/Cancelled/etc). Call this once per borrower, not
   once per cycle — registration status doesn't have a meaningful history
   the way filing delay does, and re-hitting a live API per golden-eval
   cycle would make evaluation non-deterministic and pointless (30 identical
   calls returning the same "Active" status).

2. collect_gst_filing_delay() — MOCK, historical, per-cycle. Sourced from
   app/mocks/gst_mock_historical.py until a real GST return-history API is
   integrated. This is the signal that actually varies per cycle and feeds
   the scoring engine.
"""

import requests

from app.config import SANDBOX_API_KEY, SANDBOX_API_SECRET, SANDBOX_AUTH_URL, SANDBOX_GST_SEARCH_URL
from app.mocks.gst_mock_historical import get_mock_filing_delay

_token_cache = {"access_token": None}


def _get_access_token() -> str:
    """JWT access token, valid 24h — cached in-process so we don't
    re-authenticate on every call."""
    if _token_cache["access_token"]:
        return _token_cache["access_token"]

    resp = requests.post(
        SANDBOX_AUTH_URL,
        headers={
            "x-api-key": SANDBOX_API_KEY,
            "x-api-secret": SANDBOX_API_SECRET,
            "x-api-version": "1.0",
        },
        timeout=15,
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    _token_cache["access_token"] = token
    return token


def collect_gst_registration(gstin: str) -> dict:
    """Real sandbox.co.in call. Field names below are mapped from the
    ACTUAL confirmed response shape (data.data.{sts,lgnm,dty,...}), not
    guessed."""
    token = _get_access_token()
    resp = requests.post(
        SANDBOX_GST_SEARCH_URL,
        headers={
            "authorization": token,
            "x-api-key": SANDBOX_API_KEY,
            "x-api-version": "1.0",
        },
        json={"gstin": gstin},
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()["data"]["data"]

    return {
        "gstin": payload["gstin"],
        "legal_name": payload["lgnm"],
        "status": payload["sts"],                    # "Active" / "Cancelled" / "Suspended"
        "registration_type": payload["dty"],          # e.g. "Regular"
        "registration_date": payload["rgdt"],
        "einvoice_enabled": payload.get("einvoiceStatus") == "Yes",
        "source": "sandbox_gst_api",
    }


def collect_gst_filing_delay(borrower_id: str, cycle: int) -> dict:
    """Mock/historical for now (see module docstring)."""
    return get_mock_filing_delay(borrower_id, cycle)