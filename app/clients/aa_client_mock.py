import json
import random
from datetime import date, timedelta

from app.clients.aa_client_base import AAClient, AAConnectionError
from app.config import DATA_DIR
from app.mocks.monitoring_dataset import get_or_generate_cycle


ARCHETYPES_PATH = DATA_DIR / "golden_archetypes.json"

BASE_BALANCE_RANGE = (150000, 900000)


def _load_archetypes():
    """
    Load borrower archetypes from golden_archetypes.json.

    Still used ONLY for the borrower-existence check in __init__ and the
    __main__ self-test below — actual per-cycle data now comes from
    app.mocks.monitoring_dataset (see fetch_aa_data), not from here
    directly. See that module's docstring for why redirecting the cycle
    DATA doesn't change evaluator.py's results.
    """

    with open(ARCHETYPES_PATH, "r", encoding="utf-8") as file:
        data = json.load(file)

    return {
        archetype["borrower_id"]: archetype
        for archetype in data
    }


class MockAAClient(AAClient):

    def __init__(self):
        self._archetypes = _load_archetypes()

    def fetch_aa_data(self, borrower_id: str, cycle: int) -> dict:

        archetype = self._archetypes.get(borrower_id)

        if archetype is None:
            raise ValueError(
                f"No archetype found for borrower {borrower_id}"
            )

        cycle_data = get_or_generate_cycle(borrower_id, cycle)

        # Simulate AA sandbox outage
        if (
            cycle_data.get("sandbox_status")
            == "outage_cached_fallback"
        ):
            raise AAConnectionError(
                f"Simulated AA sandbox timeout for "
                f"{borrower_id}, cycle {cycle}"
            )

        subscores = cycle_data["subscores"]

        cash_flow_score = subscores.get("cash_flow")
        vendor_score = subscores.get("vendor_payment")

        if cash_flow_score is None:
            raise AAConnectionError(
                f"Cash flow data unavailable for "
                f"{borrower_id}, cycle {cycle}"
            )

        # Deterministic random values — per borrower+cycle, for transaction noise
        rng = random.Random(
            f"{borrower_id}-{cycle}"
        )

        # Stable per-borrower baseline — deliberately seeded by borrower_id
        # ONLY (not cycle), so it stays constant across all of a borrower's
        # cycles. This represents "what healthy looks like" for this MSME.
        baseline_rng = random.Random(borrower_id)

        base_balance = baseline_rng.uniform(
            *BASE_BALANCE_RANGE
        )

        current_balance = round(
            base_balance
            * (cash_flow_score / 100),
            2,
        )

        # avg_monthly_balance is derived from the STABLE baseline, not from
        # current_balance. If it were derived from current_balance (as an
        # earlier version of this file did), the ratio between the two would
        # always land near 100% regardless of how distressed the borrower
        # actually is — which would make ratio-based cash-flow normalization
        # silently useless. A real average balance moves slowly; it doesn't
        # instantly track a single bad month.
        avg_monthly_balance = round(
            base_balance
            * rng.uniform(0.97, 1.03),
            2,
        )

        transactions = self._mock_transactions(
            rng,
            vendor_score,
            cycle,
        )

        return {
            "borrower_id": borrower_id,
            "cycle": cycle,
            "fi_type": "DEPOSIT",

            "summary": {
                "current_balance": current_balance,
                "avg_monthly_balance": avg_monthly_balance,
                "currency": "INR",
            },

            "recent_transactions": transactions,

            "source": "mock",
        }

    @staticmethod
    def _mock_transactions(
        rng,
        vendor_score,
        cycle,
    ):

        if vendor_score is None:
            return None  # signal genuinely unavailable this cycle — NOT "zero transactions"

        # Was 8 — far too coarse. With only 8 transactions, the late/on-
        # time ratio can only land on 9 possible values (0/8, 1/8, ... 8/8),
        # i.e. ~12.5 points of resolution. That silently collapsed
        # golden_archetypes.json's fine-grained per-cycle targets (e.g.
        # 90, 88, 91, 89 for the steady archetype) into the SAME rounded
        # late-transaction-count every cycle, which is why vendor_payment
        # gate status came out flat ("stable_or_improving" every cycle)
        # even for archetypes whose golden trace expects small real
        # dips. 50 gives 2-point resolution — enough to actually
        # reproduce the small cycle-to-cycle deltas the archetypes are
        # scripted with, instead of quantizing them away. This is a real
        # precision bug in the mock's data generation, not a mismatch
        # between two legitimately different designs — found and
        # confirmed by tracing exact golden vs. actual subscores for
        # MSME-1001 (golden 90/88/91/89, actual a flat 88 every cycle).
        number_of_transactions = 50

        late_fraction = max(
            0.0,
            min(
                1.0,
                (100 - vendor_score) / 100,
            ),
        )

        number_of_late_transactions = round(
            number_of_transactions
            * late_fraction
        )

        cycle_start = (
            date(2026, 1, 1)
            + timedelta(
                days=30 * (cycle - 1)
            )
        )

        transactions = []

        for index in range(
            number_of_transactions
        ):

            is_late = (
                index
                < number_of_late_transactions
            )

            transaction = {

                "date": (
                    cycle_start
                    + timedelta(
                        days=index * 3
                    )
                ).isoformat(),

                "type": "DEBIT",

                "narration": (
                    "VENDOR PAYMENT (delayed)"
                    if is_late
                    else "VENDOR PAYMENT"
                ),

                "amount": round(
                    rng.uniform(
                        5000,
                        80000,
                    ),
                    2,
                ),

                "on_time": not is_late,
            }

            transactions.append(
                transaction
            )

        return transactions


if __name__ == "__main__":

    client = MockAAClient()

    archetypes = _load_archetypes()

    for borrower_id, archetype in archetypes.items():

        for cycle_info in archetype["cycles"]:

            cycle = cycle_info["cycle"]

            try:

                result = client.fetch_aa_data(
                    borrower_id,
                    cycle,
                )

                balance = (
                    result["summary"]
                    ["current_balance"]
                )

                late_transactions = sum(
                    1
                    for transaction
                    in result[
                        "recent_transactions"
                    ]
                    if not transaction[
                        "on_time"
                    ]
                )

                print(
                    f"{borrower_id} "
                    f"cycle {cycle}: "
                    f"balance = "
                    f"Rs.{balance:,.2f}, "
                    f"late transactions = "
                    f"{late_transactions}"
                )

            except AAConnectionError as error:

                print(
                    f"{borrower_id} "
                    f"cycle {cycle}: "
                    f"AAConnectionError -> "
                    f"{error}"
                )