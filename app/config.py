"""Configuration — environment variables and paths.

TODO: Add any new environment variables your agent needs here.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"  # your policy / knowledge documents live here

AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
AZURE_CHAT_DEPLOYMENT = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o-mini")
AZURE_EMBED_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBED_DEPLOYMENT", "text-embedding-3-small")

# GSTIN verification (sandbox.co.in) — already confirmed working
SANDBOX_API_KEY = os.getenv("SANDBOX_API_KEY")
SANDBOX_API_SECRET = os.getenv("SANDBOX_API_SECRET")
SANDBOX_AUTH_URL = os.getenv("SANDBOX_AUTH_URL", "https://test-api.sandbox.co.in/authenticate")
SANDBOX_GST_SEARCH_URL = os.getenv(
    "SANDBOX_GST_SEARCH_URL", "https://api.sandbox.co.in/gst/compliance/public/gstin/search"
)

# Industry Index — Day 26. Kept mock (INDUSTRY_INDEX_MOCK_MODE=true) by
# default so nothing about existing golden-trace evaluation changes
# unless this is deliberately flipped. Live mode needs a data.gov.in
# account (free, but not zero-signup) and a resource_id that actually has
# an API enabled — not every dataset on the catalog does. See
# app/collectors/industry_collector.py's docstring before flipping this.
#
# CORRECTED (was briefly changed to 50.0, then reverted — see below):
# this value is NOT a direct 0-100 score. industry_collector.py returns
# it as "industry_growth", which app/scoring/normalizers.py's
# normalize_industry() then feeds through score = 50 + (growth * 1.5)
# before it ever becomes a subscore. That means DEFAULT_INDUSTRY_INDEX
# is a GROWTH-RATE PERCENTAGE, and 0.0 already produces the correct
# neutral score of exactly 50 via that formula — it was never acting as
# a worst-case "0" score, despite looking that way at a glance. Setting
# this to 50.0 (a plausible-looking "neutral score" value) was a real
# mistake made during golden-eval reconciliation: it fed 50.0 through as
# a GROWTH RATE, producing 50 + 75 = 125, clamped to 100 — the maximum
# possible score, not neutral, which silently inflated every borrower's
# composite. Caught by directly checking the actual post-normalization
# subscore rather than trusting an aggregate composite-delta inference.
# Leave this at 0.0 unless you're also changing normalize_industry()'s
# formula to match.
DEFAULT_INDUSTRY_INDEX = float(os.getenv("DEFAULT_INDUSTRY_INDEX", "0"))
INDUSTRY_INDEX_MOCK_MODE = os.getenv("INDUSTRY_INDEX_MOCK_MODE", "true").lower() != "false"
DATA_GOV_IN_API_KEY = os.getenv("DATA_GOV_IN_API_KEY")
DATA_GOV_IN_IIP_RESOURCE_ID = os.getenv("DATA_GOV_IN_IIP_RESOURCE_ID")
DATA_GOV_IN_BASE_URL = os.getenv("DATA_GOV_IN_BASE_URL", "https://api.data.gov.in/resource")

# Account Aggregator — Setu. Keep AA_MOCK_MODE=true until a real consent
# flow has been confirmed end-to-end (see LiveAAClient stub for what's left).
AA_MOCK_MODE = os.getenv("AA_MOCK_MODE", "true").lower() != "false"
SETU_AA_BASE_URL = os.getenv("SETU_AA_BASE_URL", "https://fiu-sandbox.setu.co")
SETU_AA_CLIENT_ID = os.getenv("SETU_AA_CLIENT_ID")
SETU_AA_CLIENT_SECRET = os.getenv("SETU_AA_CLIENT_SECRET")
SETU_AA_PRODUCT_INSTANCE_ID = os.getenv("SETU_AA_PRODUCT_INSTANCE_ID")