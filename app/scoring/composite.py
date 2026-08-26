"""
Day 7 — Weighted composite score.

Ported from scripts/golden_archetypes.py's composite_only(), now importing
its weights/thresholds from the shared app/scoring/constants.py instead of
a local hardcoded copy.

Day 8 addition (Option A — see NOTES_day1-3.md): a hardcoded placeholder
signal (currently just industry_index — a constant that can never fail or
vary) is not real evidence, so it must not count toward
MIN_SIGNALS_REQUIRED. It still participates in the weighted average once
enough REAL signals are available, since excluding its value entirely
would just be a different way of pretending it doesn't exist. The
distinction matters specifically for the Data Availability Check: a
constant that can never go missing must not be able to mask a cycle that
genuinely doesn't have enough real data.
"""

from app.scoring.constants import WEIGHTS, MIN_SIGNALS_REQUIRED, PLACEHOLDER_SIGNALS


def calculate_composite(subscores: dict):
    """Returns the weighted, re-normalized composite score, or None if
    fewer than MIN_SIGNALS_REQUIRED *real* (non-placeholder) signals are
    available this cycle — the Data Availability Check."""
    available = {k: v for k, v in subscores.items() if v is not None}

    real_available = {k: v for k, v in available.items() if k not in PLACEHOLDER_SIGNALS}
    if len(real_available) < MIN_SIGNALS_REQUIRED:
        return None

    total_w = sum(WEIGHTS[k] for k in available)
    return round(sum(subscores[k] * WEIGHTS[k] for k in available) / total_w, 1)