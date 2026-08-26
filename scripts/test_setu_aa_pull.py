"""
Day 14 — Option B smoke test.

Proves the real Setu AA sandbox pull works end-to-end against an
already-APPROVED consentId, BEFORE anything is wired into the scoring
engine. Mirrors how the real GST call was verified standalone before
being trusted anywhere near the pipeline (see gst_collector.py).

Usage:
    python -m scripts.test_setu_aa_pull <consent_id>
    python -m scripts.test_setu_aa_pull <consent_id> --session-id <session_id>

The --session-id form skips Steps 1-2 and polls Step 3 directly against
an already-created session (e.g. one printed by a prior run of this
script) — useful when Step 2 already succeeded and you're just waiting
on the mock FIP.

Deliberately does NOT catch AAConnectionError — the point of this script
is to surface exactly what's wrong (wrong base URL, wrong API generation,
expired consent, bad credentials, etc.), not hide it behind a generic
failure message.
"""

import json
import sys
from datetime import datetime, timedelta, timezone

from app.clients.setu_aa_client import (
    get_consent_status,
    create_data_session,
    fetch_fi_data_with_retry,
)


def _run_step3(session_id: str) -> None:
    print(f"--- Step 3: Fetch FI data ({session_id}) ---")
    fi_data = fetch_fi_data_with_retry(session_id)
    print(json.dumps(fi_data, indent=2))

    combined_status = fi_data.get("status")
    print(f"\nCombined session status: {combined_status}")
    if combined_status == "PENDING":
        print(
            "Still PENDING after all retry attempts. Re-run this script "
            f"with '--session-id {session_id}' again in a minute or two — "
            "no need to redo Steps 1-2."
        )


def main(consent_id: str, existing_session_id: str | None = None) -> None:
    if existing_session_id:
        _run_step3(existing_session_id)
        return

    print(f"--- Step 1: Get Consent ({consent_id}) ---")
    consent = get_consent_status(consent_id)
    print(json.dumps(consent, indent=2))

    status = consent.get("status")
    if status != "ACTIVE":
        print(
            f"\nConsent status is '{status}', not ACTIVE — stopping here. "
            "Approve the consent via its webview `url` first, then re-run."
        )
        return
    print("\nConsent is ACTIVE.\n")

    now = datetime.now(timezone.utc)
    data_range = {
        "from": (now - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "to": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }

    print("--- Step 2: Create Data Session ---")
    session = create_data_session(consent_id, data_range)
    print(json.dumps(session, indent=2))

    # Field name for the session id has been observed as either "id" or
    # "sessionId" across Setu's docs pages — handle both defensively.
    session_id = session.get("id") or session.get("sessionId")
    if not session_id:
        print("\nNo session id in response — can't continue to Step 3.")
        return
    print(f"\nSession created: {session_id}\n")

    _run_step3(session_id)


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 2 and args[0] not in ("--session-id",):
        consent_id_arg = args[0]
        session_id_arg = None
    elif len(args) == 3 and args[1] == "--session-id":
        consent_id_arg = args[0]
        session_id_arg = args[2]
    else:
        print(
            "Usage:\n"
            "  python -m scripts.test_setu_aa_pull <consent_id>\n"
            "  python -m scripts.test_setu_aa_pull <consent_id> --session-id <session_id>"
        )
        sys.exit(1)
    main(consent_id_arg, session_id_arg)