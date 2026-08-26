"""
AA Client Factory.

Provides the AA client used by collectors.

AA_MOCK_MODE=true
    -> MockAAClient

AA_MOCK_MODE=false
    -> LiveAAClient (real Setu Account Aggregator)
"""

from app.config import AA_MOCK_MODE
from app.clients.aa_client_base import AAClient
from app.clients.aa_client_mock import MockAAClient
from app.clients.aa_client_live import LiveAAClient


def get_aa_client() -> AAClient:
    """
    Return the configured Account Aggregator client.

    Mock mode is used for synthetic/golden evaluation.
    Live mode uses the real Setu AA integration.
    """

    if AA_MOCK_MODE:
        return MockAAClient()

    return LiveAAClient()