"""
Single source of truth for scoring constants.

Both scripts/golden_archetypes.py (which SCRIPTS the expected golden-trace
labels) and the real scoring engine (app/scoring/*.py) import from here.
If they each hardcoded their own copies, the two could silently drift
apart over time — and Day 8's "compare real engine output against golden
traces" evaluation would become meaningless the moment they did, since
you'd just be comparing two different rulebooks against each other rather
than checking the engine against a fixed standard.

All values below are PLACEHOLDERS pending real weight-rationale (see
NOTES_day1-3.md) — change them here, once, and both the golden traces and
the real engine pick up the change together next time golden_archetypes.py
is regenerated.
"""

WEIGHTS = {  # gst_registration is a real/synthetic gate field, not weighted
    "gst_filing_delay": 0.20,
    "cash_flow": 0.35,
    "vendor_payment": 0.30,
    "industry_index": 0.15,
}
GREEN_MIN = 70          # composite >= this -> Green          [PLACEHOLDER]
AMBER_MIN = 40          # composite in [AMBER_MIN, GREEN_MIN) -> Amber
CRITICAL_FLOOR = 25     # composite below this -> Red, peer adjustment can't save it
MIN_SIGNALS_REQUIRED = 2        # fewer available signals this cycle -> Insufficient Data
DECLINE_STREAK_FOR_CONFIRM = 2  # consecutive declining periods to confirm a trend

# Signals sourced from a hardcoded/constant placeholder rather than any
# real data source (see app/collectors/industry_collector.py). A constant
# that can never vary and never fail isn't real evidence — it should not
# count toward MIN_SIGNALS_REQUIRED, even though its (neutral) value still
# participates in the weighted composite once real signals clear the bar.
#
# Day 26: this is now DERIVED from config.INDUSTRY_INDEX_MOCK_MODE rather
# than a hardcoded literal set — the moment industry_collector.py is
# genuinely running in live mode, it should stop being excluded here too,
# without a second manual edit to keep in sync. Still defaults to
# excluded (mock mode is the default), so nothing changes unless you
# deliberately flip INDUSTRY_INDEX_MOCK_MODE=false in .env.
from app.config import INDUSTRY_INDEX_MOCK_MODE

PLACEHOLDER_SIGNALS = {"industry_index"} if INDUSTRY_INDEX_MOCK_MODE else set()