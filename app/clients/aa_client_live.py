"""
Live Setu Account Aggregator client.

Connects the application's AA abstraction to the real Setu
Account Aggregator integration in:

    app/clients/setu_aa_client.py

Responsibilities:
1. Map borrower_id -> Setu consentId.
2. Verify consent is ACTIVE.
3. Read the dataRange approved by that consent.
4. Create a Setu FI session.
5. Poll until FI data is available.
6. Extract transactions.
7. Convert Setu data into the common format expected by collectors.

IMPORTANT:
Setu bank transactions do not contain invoice due dates.
Therefore vendor-payment timeliness cannot currently be determined
from AA data alone.
"""

import json

from app.clients.aa_client_base import (
    AAClient,
    AAConnectionError,
)
from app.clients.setu_aa_client import (
    get_consent_status,
    create_data_session,
    fetch_fi_data_with_retry,
)
from app.config import DATA_DIR


# ============================================================
# CONSENT MAP
# ============================================================

CONSENT_MAP_PATH = DATA_DIR / "consent_map.json"


def _load_consent_map() -> dict:
    """
    Load:

        borrower_id -> Setu consentId

    from data/consent_map.json.

    Keys beginning with "_" are comments/examples and are ignored.
    """

    if not CONSENT_MAP_PATH.exists():
        return {}

    try:
        with open(
            CONSENT_MAP_PATH,
            "r",
            encoding="utf-8",
        ) as file:
            raw = json.load(file)

    except (OSError, json.JSONDecodeError) as exc:
        raise AAConnectionError(
            f"Could not read {CONSENT_MAP_PATH}: {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise AAConnectionError(
            f"{CONSENT_MAP_PATH.name} must contain a JSON object."
        )

    return {
        key: value
        for key, value in raw.items()
        if not key.startswith("_")
    }


# ============================================================
# TRANSACTION EXTRACTION
# ============================================================

def _extract_transactions(fi_response: dict) -> list:
    """
    Recursively search Setu's FI response for transaction lists.

    A transaction is identified by:
        txnId
        type

    This avoids depending on one exact FIP nesting structure.
    """

    found = []

    def walk(node):

        if isinstance(node, list):

            if (
                node
                and all(
                    isinstance(item, dict)
                    and "txnId" in item
                    and "type" in item
                    for item in node
                )
            ):
                found.extend(node)

            else:
                for item in node:
                    walk(item)

        elif isinstance(node, dict):

            for value in node.values():
                walk(value)

    walk(fi_response)

    return found


# ============================================================
# TRANSACTION MAPPING
# ============================================================

def _map_transaction(raw: dict) -> dict:
    """
    Convert a Setu transaction into our simplified format.

    There is deliberately NO on_time field.

    AA data tells us when a transaction occurred, but does not
    provide the vendor invoice due date required to determine
    whether the payment was late.
    """

    date = raw.get("valueDate")

    if not date:
        timestamp = (
            raw.get("transactionTimestamp")
            or ""
        )
        date = timestamp[:10]

    current_balance = raw.get(
        "currentBalance"
    )

    if current_balance is not None:
        current_balance = float(
            current_balance
        )

    return {
        "date": date,
        "type": raw.get(
            "type",
            "",
        ),
        "narration": raw.get(
            "narration",
            "",
        ),
        "amount": float(
            raw.get("amount", 0)
            or 0
        ),
        "current_balance": (
            current_balance
        ),
        "txn_id": raw.get(
            "txnId"
        ),
        "reference": raw.get(
            "reference"
        ),
    }


# ============================================================
# LIVE AA CLIENT
# ============================================================

class LiveAAClient(AAClient):
    """
    Real Setu-backed implementation of AAClient.
    """

    def fetch_aa_data(
        self,
        borrower_id: str,
        cycle: int,
    ) -> dict:

        # ========================================================
        # STEP 1 — Find borrower consent
        # ========================================================

        consent_map = (
            _load_consent_map()
        )

        consent_id = consent_map.get(
            borrower_id
        )

        if not consent_id:
            raise AAConnectionError(
                f"No Setu consentId mapped for borrower "
                f"'{borrower_id}' in "
                f"{CONSENT_MAP_PATH.name}. "
                f"Live mode only works for borrowers "
                f"with a real approved Setu consent."
            )

        # ========================================================
        # STEP 2 — Fetch and verify consent
        # ========================================================

        consent = get_consent_status(
            consent_id
        )

        consent_status = consent.get(
            "status"
        )

        if consent_status != "ACTIVE":
            raise AAConnectionError(
                f"Consent {consent_id} is not ACTIVE "
                f"(status={consent_status})."
            )

        # ========================================================
        # STEP 3 — Get APPROVED data range
        # ========================================================

        consent_detail = (
            consent.get("detail")
            or {}
        )

        consent_data_range = (
            consent_detail.get(
                "dataRange"
            )
        )

        if not isinstance(
            consent_data_range,
            dict,
        ):
            raise AAConnectionError(
                f"Consent {consent_id} does not "
                f"contain an approved dataRange."
            )

        range_from = (
            consent_data_range.get(
                "from"
            )
        )

        range_to = (
            consent_data_range.get(
                "to"
            )
        )

        if not range_from or not range_to:
            raise AAConnectionError(
                f"Consent {consent_id} contains "
                f"an incomplete dataRange."
            )

        data_range = {
            "from": range_from,
            "to": range_to,
        }

        # ========================================================
        # STEP 4 — Create Setu FI session
        # ========================================================

        session = create_data_session(
            consent_id,
            data_range,
        )

        session_id = (
            session.get("id")
            or session.get(
                "sessionId"
            )
        )

        if not session_id:
            raise AAConnectionError(
                "Create Data Session returned "
                "no session id."
            )

        # ========================================================
        # STEP 5 — Poll FI session
        # ========================================================

        fi_response = (
            fetch_fi_data_with_retry(
                session_id
            )
        )

        status = fi_response.get(
            "status"
        )

        if status not in (
            "PARTIAL",
            "COMPLETED",
        ):
            raise AAConnectionError(
                f"FI session {session_id} "
                f"ended with status={status}; "
                f"no usable data is available."
            )

        # ========================================================
        # STEP 6 — Extract transactions
        # ========================================================

        raw_txns = (
            _extract_transactions(
                fi_response
            )
        )

        if not raw_txns:
            raise AAConnectionError(
                f"No transactions found in "
                f"FI response for session "
                f"{session_id}."
            )

        # ========================================================
        # STEP 7 — Sort newest -> oldest
        # ========================================================

        raw_txns.sort(
            key=lambda transaction: (
                transaction.get(
                    "transactionTimestamp",
                    "",
                )
                or transaction.get(
                    "valueDate",
                    "",
                )
            ),
            reverse=True,
        )

        # ========================================================
        # STEP 8 — Current balance
        # ========================================================

        latest_balance = (
            raw_txns[0].get(
                "currentBalance"
            )
        )

        if latest_balance is not None:
            current_balance = float(
                latest_balance
            )
        else:
            current_balance = 0.0

        # ========================================================
        # STEP 9 — Approximate average balance
        # ========================================================
        #
        # NOTE:
        # This is the mean of transaction-posted balances.
        # It is not a bank-calculated AMB.
        # ========================================================

        balances = []

        for transaction in raw_txns:

            balance = (
                transaction.get(
                    "currentBalance"
                )
            )

            if balance is not None:
                balances.append(
                    float(balance)
                )

        if balances:
            avg_monthly_balance = round(
                sum(balances)
                / len(balances),
                2,
            )
        else:
            avg_monthly_balance = 0.0

        # ========================================================
        # STEP 10 — Preserve real transactions
        # ========================================================

        mapped_transactions = [
            _map_transaction(
                transaction
            )
            for transaction
            in raw_txns
        ]

        # ========================================================
        # STEP 11 — Common AA contract
        # ========================================================

        return {
            "borrower_id": borrower_id,
            "cycle": cycle,
            "fi_type": "DEPOSIT",

            "summary": {
                "current_balance": round(
                    current_balance,
                    2,
                ),
                "avg_monthly_balance": (
                    avg_monthly_balance
                ),
                "currency": "INR",
            },

            # We cannot calculate vendor-payment timeliness
            # from bank transactions alone.
            "recent_transactions": None,

            # Actual Setu transactions remain available for
            # future vendor/invoice matching.
            "raw_transactions": (
                mapped_transactions
            ),

            "source": "live",

            "setu": {
                "consent_id": consent_id,
                "session_id": session_id,
                "session_status": status,
                "data_range": data_range,
            },
        }