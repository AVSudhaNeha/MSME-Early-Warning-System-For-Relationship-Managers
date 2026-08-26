"""
Day 26 — Industry Index Collector, now with a real data source path.

MOCK MODE (default — INDUSTRY_INDEX_MOCK_MODE=true in .env): unchanged
behavior from the original stub. A config-driven constant, explicitly
excluded from the Data Availability Check via PLACEHOLDER_SIGNALS. This
stays the default so nothing about the existing golden-trace evaluation
changes unless you deliberately flip the switch.

LIVE MODE (INDUSTRY_INDEX_MOCK_MODE=false): calls data.gov.in's IIP
(Index of Industrial Production) API — the one real, free option of the
three the proposal named (RBI DBIE has no clean programmatic API; NSE
sector indices actively block non-browser scraping).

IMPORTANT — two things I cannot fabricate, both required before this
actually works:

1. DATA_GOV_IN_API_KEY and DATA_GOV_IN_IIP_RESOURCE_ID in .env, from
   your own data.gov.in account. Not every IIP dataset on the catalog
   has a working API — some pages explicitly say "Request API" instead
   of having one live. Confirm yours does before flipping mock mode off.

2. data/industry_sector_map.json — maps this project's 4 sectors
   (auto_ancillary, food_processing, textiles, logistics) to whatever
   category/item values actually appear in YOUR resource's records. I
   don't know those real field values without a real API response in
   front of me. This file ships with placeholder values you MUST replace
   — run this module directly with mock mode off once, inspect the raw
   response it prints, and fill in the real field/category names both
   here and in _fetch_real_iip()'s "filters[item]" param key below
   (that param name is ALSO a guess pending your resource's real schema).

IIP is published monthly, ~6 weeks after the reference month — this
value will change roughly once a month at most, not every scoring cycle.
That's expected, not a bug in this collector.
"""

import json

import requests

from app.config import (
    DATA_DIR,
    DEFAULT_INDUSTRY_INDEX,
    INDUSTRY_INDEX_MOCK_MODE,
    DATA_GOV_IN_API_KEY,
    DATA_GOV_IN_IIP_RESOURCE_ID,
    DATA_GOV_IN_BASE_URL,
)

SECTOR_MAP_PATH = DATA_DIR / "industry_sector_map.json"
_TIMEOUT = 15


def _load_sector_map() -> dict:
    if not SECTOR_MAP_PATH.exists():
        return {}
    with open(SECTOR_MAP_PATH) as f:
        raw = json.load(f)
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def _borrower_sector(borrower_id: str) -> str:
    records = json.loads((DATA_DIR / "records.json").read_text())
    rec = next((r for r in records if r["id"] == borrower_id), None)
    if rec is None:
        raise ValueError(f"No record found for {borrower_id}")
    return rec["sector"]


def _fetch_real_iip(iip_category: str) -> dict:
    if not (DATA_GOV_IN_API_KEY and DATA_GOV_IN_IIP_RESOURCE_ID):
        raise RuntimeError(
            "DATA_GOV_IN_API_KEY / DATA_GOV_IN_IIP_RESOURCE_ID missing from "
            ".env — get these from your own data.gov.in account first."
        )
    url = f"{DATA_GOV_IN_BASE_URL}/{DATA_GOV_IN_IIP_RESOURCE_ID}"
    params = {
        "api-key": DATA_GOV_IN_API_KEY,
        "format": "json",
        "filters[item]": iip_category,  # GUESS — confirm field name against your resource's real schema
        "limit": 1,
        "sort[month]": "desc",
    }
    resp = requests.get(url, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def collect_industry_signal(borrower_id: str, cycle: int) -> dict:
    if INDUSTRY_INDEX_MOCK_MODE:
        return {
            "industry_growth": DEFAULT_INDUSTRY_INDEX,
            "source": "configured_placeholder",
            "available": False,
        }

    sector = _borrower_sector(borrower_id)
    sector_map = _load_sector_map()
    iip_category = sector_map.get(sector)
    if not iip_category:
        raise ValueError(
            f"No IIP category mapped for sector '{sector}' in "
            f"{SECTOR_MAP_PATH.name} — fill this in from your resource's "
            "real field values before using live mode."
        )

    raw_response = _fetch_real_iip(iip_category)
    records = raw_response.get("records", [])
    if not records:
        raise ValueError(
            f"data.gov.in returned no records for category '{iip_category}' "
            "— check the filter field name/value against your resource's "
            "actual schema (this collector guesses 'filters[item]', which "
            "may not match your resource)."
        )

    latest = records[0]
    # Field name for the index value itself is ALSO a guess — inspect a
    # real response (see module docstring) and adjust if it differs.
    index_value = latest.get("index_value") or latest.get("index")
    if index_value is None:
        raise ValueError(
            f"Couldn't find an index value field in this record: {latest} "
            "— adjust the field name this function looks for."
        )

    return {
        "industry_growth": float(index_value),
        "source": "data.gov.in_iip",
        "available": True,
        "raw_period": latest.get("month") or latest.get("date"),
    }


if __name__ == "__main__":
    print("INDUSTRY_INDEX_MOCK_MODE:", INDUSTRY_INDEX_MOCK_MODE)
    result = collect_industry_signal("MSME-1001", 1)
    print(result)
    if INDUSTRY_INDEX_MOCK_MODE:
        assert result["available"] is False
        print("Mock-mode smoke test passed (unchanged from pre-Day-26 behavior).")
    else:
        print(
            "Live mode ran without raising — but eyeball the raw_period and "
            "industry_growth values above against a real data.gov.in "
            "response before trusting them; the field names this collector "
            "guesses may not match your specific resource."
        )