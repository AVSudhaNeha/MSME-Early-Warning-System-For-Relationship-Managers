"""
Onboarding-date-based cycle computation.

Rather than hardcoding an arbitrary "starting cycle" per borrower (which
would need manual upkeep forever and drift out of realism), each
borrower's records.json entry carries a real onboarded_on date. The
current "due" cycle is derived from how much time has elapsed since
then, at a fixed monitoring cadence — closer to how a real banking
system would actually track this, and self-maintaining: run this a year
from now and the numbers are still correct without anyone touching them.

CADENCE_DAYS is a placeholder (30 = monthly), same spirit as every other
[PLACEHOLDER] value already in this project (see constants.py) — a real
deployment would set this from the proposal's actual monitoring
frequency, not this default.
"""

from datetime import date, datetime

CADENCE_DAYS = 30  # [PLACEHOLDER] monthly cadence, pending a real decision


def compute_target_cycle(onboarded_on: str, cadence_days: int = CADENCE_DAYS, today: date = None) -> int:
    """Returns the cycle number that SHOULD be current right now for a
    borrower onboarded on onboarded_on (an ISO date string, "YYYY-MM-DD").
    Cycle 1 starts on the onboarding date itself; one new cycle becomes
    due every cadence_days after that. `today` is injectable for
    testability — defaults to the real current date.

    Never returns less than 1, even for a future onboarding date (a
    borrower can't be behind their own first cycle)."""
    today = today or date.today()
    onboarded = datetime.strptime(onboarded_on, "%Y-%m-%d").date()
    elapsed_days = (today - onboarded).days
    if elapsed_days < 0:
        return 1
    return elapsed_days // cadence_days + 1


if __name__ == "__main__":
    fixed_today = date(2026, 7, 31)

    r1 = compute_target_cycle("2025-02-21", today=fixed_today)
    print("onboarded 2025-02-21, today 2026-07-31 ->", r1)
    assert r1 == 18

    r2 = compute_target_cycle("2026-07-31", today=fixed_today)  # onboarded today
    print("onboarded today ->", r2)
    assert r2 == 1

    r3 = compute_target_cycle("2027-01-01", today=fixed_today)  # future date, defensive
    print("future onboarding date (defensive) ->", r3)
    assert r3 == 1

    print("monitoring_history smoke test passed.")