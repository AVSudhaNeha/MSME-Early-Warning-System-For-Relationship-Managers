"""
Day 14 — Live Setu AA data pull.

Setu Account Aggregator sandbox integration using the V2 API.

Flow:
1. Generate access token
2. GET /v2/consents/{consentId}?expanded=true
3. POST /v2/sessions
4. GET /v2/sessions/{sessionId}
5. Poll while session status is PENDING

aa_client_live.py uses these functions to fetch real Setu FI data
and map it into the format expected by the scoring collectors.
"""

import time

import requests

from app.config import (
    SETU_AA_BASE_URL,
    SETU_AA_CLIENT_ID,
    SETU_AA_CLIENT_SECRET,
    SETU_AA_PRODUCT_INSTANCE_ID,
)
from app.clients.aa_client_base import AAConnectionError


_TIMEOUT = 15

# Token endpoint already confirmed working through the Setu/Postman flow.
_TOKEN_URL = "https://orgservice-prod.setu.co/v1/users/login"


# ============================================================
# HELPER — ERROR MESSAGE
# ============================================================

def _response_error(prefix: str, response: requests.Response) -> str:
    """
    Build a useful Setu API error message.

    requests.raise_for_status() alone only gives messages such as
    '400 Bad Request'. This helper also preserves Setu's response body,
    which is important when debugging invalid dataRange, consentId,
    sessionId, etc.
    """

    try:
        body = response.json()
    except ValueError:
        body = response.text

    return (
        f"{prefix}: HTTP {response.status_code} "
        f"{response.reason}. Setu response: {body}"
    )


# ============================================================
# STEP 0 — GET ACCESS TOKEN
# ============================================================

def get_access_token() -> str:
    """
    Generate a fresh Setu access token using Bridge credentials.

    Equivalent to the Get Token request already tested successfully
    through Postman.
    """

    if not SETU_AA_CLIENT_ID:
        raise AAConnectionError(
            "SETU_AA_CLIENT_ID is missing from .env"
        )

    if not SETU_AA_CLIENT_SECRET:
        raise AAConnectionError(
            "SETU_AA_CLIENT_SECRET is missing from .env"
        )

    try:
        response = requests.post(
            _TOKEN_URL,
            headers={
                "client": "bridge",
                "Content-Type": "application/json",
            },
            json={
                "clientID": SETU_AA_CLIENT_ID,
                "grant_type": "client_credentials",
                "secret": SETU_AA_CLIENT_SECRET,
            },
            timeout=_TIMEOUT,
        )

    except requests.RequestException as exc:
        raise AAConnectionError(
            f"Setu token request failed: {exc}"
        ) from exc

    if not response.ok:
        raise AAConnectionError(
            _response_error(
                "Setu token generation failed",
                response,
            )
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise AAConnectionError(
            "Setu token response was not valid JSON."
        ) from exc

    access_token = data.get("access_token")

    if not access_token:
        raise AAConnectionError(
            "Setu token response did not contain access_token."
        )

    return access_token


# ============================================================
# AUTH HEADERS
# ============================================================

def _headers() -> dict:
    """
    Build headers required by Setu AA V2 APIs.

    Required:
        Authorization: Bearer <access_token>
        x-product-instance-id: <product-instance-id>
        Content-Type: application/json
    """

    if not SETU_AA_PRODUCT_INSTANCE_ID:
        raise AAConnectionError(
            "SETU_AA_PRODUCT_INSTANCE_ID is missing from .env"
        )

    token = get_access_token()

    return {
        "Authorization": f"Bearer {token}",
        "x-product-instance-id": SETU_AA_PRODUCT_INSTANCE_ID,
        "Content-Type": "application/json",
    }


# ============================================================
# STEP 1 — GET CONSENT
# ============================================================

def get_consent_status(consent_id: str) -> dict:
    """
    Fetch an existing Setu consent.

    Endpoint:
        GET /v2/consents/{consentId}?expanded=true

    expanded=true is requested because LiveAAClient needs the
    consent's detailed information, particularly the approved
    FI data range when Setu makes it available.

    An approved consent should have status ACTIVE.
    """

    if not SETU_AA_BASE_URL:
        raise AAConnectionError(
            "SETU_AA_BASE_URL is not configured."
        )

    if not consent_id:
        raise AAConnectionError(
            "consent_id cannot be empty."
        )

    url = (
        f"{SETU_AA_BASE_URL}/v2/consents/"
        f"{consent_id}"
    )

    try:
        response = requests.get(
            url,
            headers=_headers(),
            params={
                "expanded": "true",
            },
            timeout=_TIMEOUT,
        )

    except requests.RequestException as exc:
        raise AAConnectionError(
            f"Get Consent request failed: {exc}"
        ) from exc

    if not response.ok:
        raise AAConnectionError(
            _response_error(
                "Get Consent failed",
                response,
            )
        )

    try:
        return response.json()
    except ValueError as exc:
        raise AAConnectionError(
            "Get Consent returned invalid JSON."
        ) from exc


# ============================================================
# STEP 2 — CREATE FI DATA SESSION
# ============================================================

def create_data_session(
    consent_id: str,
    data_range: dict,
    fmt: str = "json",
) -> dict:
    """
    Start an FI data fetch.

    Endpoint:
        POST /v2/sessions

    Example:

        {
            "from": "2022-12-01T00:00:00.000Z",
            "to": "2023-08-12T00:00:00.000Z"
        }

    data_range should fall within the range approved by the
    corresponding consent.
    """

    if not SETU_AA_BASE_URL:
        raise AAConnectionError(
            "SETU_AA_BASE_URL is not configured."
        )

    if not consent_id:
        raise AAConnectionError(
            "consent_id cannot be empty."
        )

    if fmt not in {"json", "xml"}:
        raise ValueError(
            "fmt must be either 'json' or 'xml'"
        )

    if not isinstance(data_range, dict):
        raise ValueError(
            "data_range must be a dictionary."
        )

    if not data_range.get("from"):
        raise ValueError(
            "data_range must contain 'from'."
        )

    if not data_range.get("to"):
        raise ValueError(
            "data_range must contain 'to'."
        )

    url = f"{SETU_AA_BASE_URL}/v2/sessions"

    payload = {
        "consentId": consent_id,
        "dataRange": {
            "from": data_range["from"],
            "to": data_range["to"],
        },
        "format": fmt,
    }

    try:
        response = requests.post(
            url,
            headers=_headers(),
            json=payload,
            timeout=_TIMEOUT,
        )

    except requests.RequestException as exc:
        raise AAConnectionError(
            f"Create Data Session request failed: {exc}"
        ) from exc

    if not response.ok:
        raise AAConnectionError(
            _response_error(
                "Create Data Session failed",
                response,
            )
        )

    try:
        return response.json()
    except ValueError as exc:
        raise AAConnectionError(
            "Create Data Session returned invalid JSON."
        ) from exc


# ============================================================
# STEP 3 — GET FI DATA
# ============================================================

def fetch_fi_data(session_id: str) -> dict:
    """
    Fetch FI data for an existing Setu session.

    Endpoint:
        GET /v2/sessions/{sessionId}

    Possible statuses include:
        PENDING
        ACTIVE
        PARTIAL
        COMPLETED
        FAILED
        EXPIRED
    """

    if not SETU_AA_BASE_URL:
        raise AAConnectionError(
            "SETU_AA_BASE_URL is not configured."
        )

    if not session_id:
        raise AAConnectionError(
            "session_id cannot be empty."
        )

    url = (
        f"{SETU_AA_BASE_URL}/v2/sessions/"
        f"{session_id}"
    )

    try:
        response = requests.get(
            url,
            headers=_headers(),
            timeout=_TIMEOUT,
        )

    except requests.RequestException as exc:
        raise AAConnectionError(
            f"Fetch FI data request failed: {exc}"
        ) from exc

    if not response.ok:
        raise AAConnectionError(
            _response_error(
                "Fetch FI data failed",
                response,
            )
        )

    try:
        return response.json()
    except ValueError as exc:
        raise AAConnectionError(
            "Fetch FI data returned invalid JSON."
        ) from exc


# ============================================================
# STEP 3B — POLL UNTIL DATA IS READY
# ============================================================

def fetch_fi_data_with_retry(
    session_id: str,
    max_attempts: int = 6,
    delay_seconds: float = 5.0,
) -> dict:
    """
    Poll an existing Setu FI session.

    PENDING:
        Retry.

    ACTIVE:
        Retry because the session is still processing.

    PARTIAL / COMPLETED:
        Return immediately because FI data may be available.

    FAILED / EXPIRED:
        Return immediately so LiveAAClient can treat the session
        as unavailable.
    """

    result = {}

    for attempt in range(
        1,
        max_attempts + 1,
    ):

        result = fetch_fi_data(
            session_id
        )

        status = result.get("status")

        print(
            f"  attempt {attempt}/{max_attempts}: "
            f"status = {status}"
        )

        if status in {
            "PARTIAL",
            "COMPLETED",
            "FAILED",
            "EXPIRED",
        }:
            return result

        if status not in {
            "PENDING",
            "ACTIVE",
        }:
            # Unknown status: don't repeatedly hit Setu.
            return result

        if attempt < max_attempts:

            print(
                f"  waiting "
                f"{delay_seconds:.0f}s "
                f"before retry..."
            )

            time.sleep(
                delay_seconds
            )

    return result