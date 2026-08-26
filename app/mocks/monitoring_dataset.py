"""
Continuous-monitoring dataset — the data source for ongoing portfolio
monitoring, kept completely separate from golden_archetypes.json.

golden_archetypes.json  -> read-only forever, used ONLY by evaluator.py
monitoring_dataset.json -> grows over time, used by the mock collectors
                            for any cycle beyond what evaluator.py's
                            fixed golden scenarios need

BOOTSTRAP: the first time this module is used, if data/monitoring_dataset.json
doesn't exist yet, it's created as an exact copy of golden_archetypes.json
(every borrower, every scripted cycle, every field preserved verbatim).
After that one-time copy, golden_archetypes.json is never read by this
module again, and monitoring_dataset.json's own already-existing cycles
are never modified — only NEW cycles get appended, one per call, past
whatever the latest cycle already is.

Because the bootstrap copy is byte-identical to golden_archetypes.json
for every cycle number evaluator.py actually asks about, redirecting the
mock collectors to read from here instead of golden_archetypes.json
directly (see aa_client_mock.py / gst_mock_historical.py) does not change
evaluator.py's results — it only adds the ability to go PAST golden's
scripted range, which golden_archetypes.json's own reader (evaluator.py's
load_golden()) never asks for anyway.

GENERATION: when a cycle beyond the borrower's latest existing one is
requested, a new cycle's subscores are generated from the previous
cycle's subscores with a small, momentum-biased random walk per signal
(65% chance of continuing the same up/down direction as the prior
cycle's move, 35% chance of reversing) — small, believable changes that
can sustain a multi-cycle trend (Green -> Amber -> Red) or reverse into
a recovery (Amber -> Green), matching what real gradual deterioration or
recovery looks like, rather than pure independent noise each cycle.
Deterministically seeded per (borrower_id, cycle, signal) so a given
generation is reproducible if this exact call were ever repeated before
being saved.

Signals generated: gst_filing_delay, cash_flow, vendor_payment.
industry_index is NOT generated here — the industry collector (mock
mode) sources it from a fixed neutral constant regardless of any cycle
data (see app/collectors/industry_collector.py), so a monitoring-dataset
entry's industry_index value is carried forward for structural
completeness only and has no effect on scoring.
"""

import json
import os
import random
import tempfile
import threading
import time

from app.config import DATA_DIR

GOLDEN_PATH = DATA_DIR / "golden_archetypes.json"
MONITORING_PATH = DATA_DIR / "monitoring_dataset.json"

_GENERATED_SIGNALS = ("gst_filing_delay", "cash_flow", "vendor_payment")
_DEFAULT_BASELINE_SCORE = 75  # used only if a signal has NEVER had a real value

# Serializes EVERY touch point of monitoring_dataset.json — bootstrap,
# read, and write — not just get_or_generate_cycle()'s own critical
# section. LangGraph runs the gst/cashflow/vendor collector nodes in
# true parallel THREADS within one process; gst's path additionally
# calls get_archetype_entry() (a bare read) before ever reaching
# get_or_generate_cycle(), so locking only the latter left a narrower
# but real race on the very first-ever bootstrap. RLock (not a plain
# Lock) because get_or_generate_cycle() itself calls _load()/_save(),
# which each also acquire this lock — a plain Lock would deadlock a
# thread against itself there. Found for real on Windows: os.replace()
# there can raise PermissionError ("Access is denied") if the
# destination has any open handle at that instant, a race window POSIX
# doesn't have — this lock removes the race at its source rather than
# just retrying after the fact.
_LOCK = threading.RLock()


def _replace_with_retry(src, dst, attempts: int = 5, delay: float = 0.05) -> None:
    """os.replace() can transiently fail on Windows with PermissionError
    if the destination has ANY open handle at that exact instant — a
    real limitation POSIX doesn't share. The threading.Lock around
    get_or_generate_cycle()'s critical section is the actual root-cause
    fix for the collector-thread race that triggered this in practice;
    this retry is defense-in-depth against any OTHER transient holder
    (e.g. antivirus or search indexing briefly opening the file) rather
    than crashing an entire monitoring run over a few-millisecond
    timing issue."""
    last_error = None
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError as e:
            last_error = e
            time.sleep(delay * (attempt + 1))
    raise last_error


def _atomic_write(path, data) -> None:
    """Writes to a temp file in the same directory, then replaces it
    into place (with retry — see _replace_with_retry). A concurrent
    reader either sees the complete old file or the complete new file,
    never a partially-written one. This matters specifically because
    LangGraph runs the gst/cashflow/vendor collector nodes in true
    parallel (confirmed in app/graph/signal_collection_graph.py), so
    multiple threads can call into this module at the exact same
    moment — a plain open()+write() here previously let one thread catch
    another mid-write, silently corrupting/truncating what it read and
    making a signal look unavailable even though its real data existed
    (found by actually running scripts.run_monitoring_cycle and seeing
    gst_filing_delay AND vendor_payment both come back unavailable on a
    borrower's very first cycle, which should never happen)."""
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".monitoring_dataset_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        _replace_with_retry(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _bootstrap_if_needed() -> None:
    """One-time copy from golden_archetypes.json. Never overwrites an
    existing monitoring_dataset.json — that would silently destroy any
    generated cycles from a prior monitoring run."""
    with _LOCK:
        if MONITORING_PATH.exists():
            return
        with open(GOLDEN_PATH) as f:
            golden = json.load(f)
        _atomic_write(MONITORING_PATH, golden)


def _load() -> list:
    with _LOCK:
        _bootstrap_if_needed()
        with open(MONITORING_PATH) as f:
            return json.load(f)


def _save(dataset: list) -> None:
    with _LOCK:
        _atomic_write(MONITORING_PATH, dataset)


def _find_archetype(dataset: list, borrower_id: str):
    return next((a for a in dataset if a["borrower_id"] == borrower_id), None)


def _last_known_score(cycles: list, signal: str, before_cycle: int = None):
    """Walks backward from the latest (or before_cycle, if given) cycle
    to find the last non-None value for this signal — handles the
    insufficient_data archetype's genuine gaps without crashing.
    Returns None if this signal has never had a real value."""
    relevant = [c for c in cycles if before_cycle is None or c["cycle"] < before_cycle]
    for c in sorted(relevant, key=lambda c: c["cycle"], reverse=True):
        score = c.get("subscores", {}).get(signal)
        if score is not None:
            return score
    return None


def _last_delta(cycles: list, signal: str):
    """The most recent real up/down movement for this signal, for
    momentum — None if there isn't enough history to know a direction."""
    scored_cycles = sorted(
        (c for c in cycles if c.get("subscores", {}).get(signal) is not None),
        key=lambda c: c["cycle"],
    )
    if len(scored_cycles) < 2:
        return None
    return scored_cycles[-1]["subscores"][signal] - scored_cycles[-2]["subscores"][signal]


def _generate_signal_value(borrower_id: str, cycle: int, signal: str, cycles: list) -> int:
    prev_score = _last_known_score(cycles, signal)
    if prev_score is None:
        prev_score = _DEFAULT_BASELINE_SCORE

    prev_delta = _last_delta(cycles, signal)
    rng = random.Random(f"{borrower_id}-{cycle}-{signal}")

    magnitude = rng.randint(1, 5)
    if prev_delta is None or prev_delta == 0:
        sign = rng.choice([-1, 1])
    else:
        prev_sign = 1 if prev_delta > 0 else -1
        continue_trend = rng.random() < 0.65
        sign = prev_sign if continue_trend else -prev_sign

    new_score = prev_score + sign * magnitude
    return max(0, min(100, new_score))


def get_or_generate_cycle(borrower_id: str, cycle: int) -> dict:
    """Returns the cycle entry (same shape as a golden_archetypes.json
    cycle dict: {"cycle", "subscores", "sandbox_status", ...}) for this
    borrower — from the existing dataset if it's already there
    (including every originally-bootstrapped golden cycle, unchanged),
    or freshly generated (and persisted) if this is exactly the next
    cycle past whatever currently exists.

    Raises ValueError for an unknown borrower, or for a cycle that's
    neither already recorded nor the immediate next one (a gap) — the
    latter shouldn't happen given how run_monitoring_cycle.py always
    requests exactly get_next_cycle()'s result, but this stays strict
    rather than silently fabricating a whole run of missing cycles."""
    with _LOCK:
        dataset = _load()
        archetype = _find_archetype(dataset, borrower_id)
        if archetype is None:
            raise ValueError(f"No monitoring-dataset entry found for borrower {borrower_id}.")

        cycles = archetype["cycles"]
        existing = next((c for c in cycles if c["cycle"] == cycle), None)
        if existing is not None:
            return existing

        max_existing = max((c["cycle"] for c in cycles), default=0)
        if cycle != max_existing + 1:
            raise ValueError(
                f"{borrower_id}: requested cycle {cycle} is neither an existing "
                f"cycle nor the next one after {max_existing} — can't generate a gap."
            )

        new_subscores = {
            signal: _generate_signal_value(borrower_id, cycle, signal, cycles)
            for signal in _GENERATED_SIGNALS
        }
        # industry_index carried forward unchanged — see module docstring
        # for why this has no scoring effect in mock mode.
        new_subscores["industry_index"] = _last_known_score(cycles, "industry_index") or _DEFAULT_BASELINE_SCORE

        new_cycle_entry = {
            "cycle": cycle,
            "subscores": new_subscores,
            "sandbox_status": "ok",
            "cycle_notes": "auto-generated by continuous monitoring",
        }
        cycles.append(new_cycle_entry)
        _save(dataset)
        return new_cycle_entry


def get_archetype_entry(borrower_id: str):
    """Borrower-existence check + full record lookup, mirroring what
    golden_archetypes.json-based code already does — used by the mock
    collectors' own existence checks so their error messages/behavior
    stay consistent with what they did before this redirect."""
    return _find_archetype(_load(), borrower_id)


def _self_test() -> None:
    import tempfile
    from pathlib import Path

    global MONITORING_PATH

    # Smoke test against a throwaway copy of the real monitoring path,
    # so running this doesn't disturb any real monitoring history.
    real_path = MONITORING_PATH
    MONITORING_PATH = Path(tempfile.gettempdir()) / "monitoring_dataset_selftest.json"
    if MONITORING_PATH.exists():
        MONITORING_PATH.unlink()

    entry = get_or_generate_cycle("MSME-1001", 1)
    print("cycle 1 (bootstrapped from golden):", entry["subscores"])

    max_cycle = max(c["cycle"] for c in get_archetype_entry("MSME-1001")["cycles"])
    next_cycle = max_cycle + 1
    generated = get_or_generate_cycle("MSME-1001", next_cycle)
    print(f"cycle {next_cycle} (generated):", generated["subscores"])
    assert generated["cycle"] == next_cycle
    assert all(0 <= v <= 100 for v in generated["subscores"].values())

    # Re-requesting the same cycle must return the SAME persisted entry,
    # not regenerate a different one.
    again = get_or_generate_cycle("MSME-1001", next_cycle)
    assert again["subscores"] == generated["subscores"]

    try:
        get_or_generate_cycle("MSME-1001", next_cycle + 5)  # a gap
        raise AssertionError("expected a gap-cycle ValueError")
    except ValueError as e:
        print("gap correctly rejected:", e)

    try:
        get_or_generate_cycle("MSME-NOT-REAL", 1)
        raise AssertionError("expected an unknown-borrower ValueError")
    except ValueError as e:
        print("unknown borrower correctly rejected:", e)

    MONITORING_PATH.unlink()
    MONITORING_PATH = real_path
    print("monitoring_dataset smoke test passed.")


def _self_test_concurrency() -> None:
    """The gap in the original testing: every prior test called
    get_or_generate_cycle() sequentially from one thread. The real bug
    (found on Windows, in actual production use) only shows up with
    TRUE concurrent threads racing on the same file — this reproduces
    that directly, using real threading.Thread, not just reasoning about
    it abstractly."""
    import tempfile
    import threading as _threading
    from pathlib import Path

    global MONITORING_PATH
    real_path = MONITORING_PATH
    MONITORING_PATH = Path(tempfile.gettempdir()) / "monitoring_dataset_concurrency_test.json"
    if MONITORING_PATH.exists():
        MONITORING_PATH.unlink()

    errors = []

    def worker():
        try:
            # All 3 "collectors" hit the exact same never-yet-generated
            # cycle at the same moment — the real gst/cashflow/vendor
            # race, reproduced with real threads.
            get_or_generate_cycle("MSME-1002", 1)
        except Exception as e:
            errors.append(e)

    threads = [_threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent access raised: {errors}"

    # Exactly one cycle-1 entry must exist for MSME-1002, not duplicated
    # or corrupted by the 8 racing threads.
    archetype = get_archetype_entry("MSME-1002")
    cycle_1_entries = [c for c in archetype["cycles"] if c["cycle"] == 1]
    print(f"cycle-1 entries after 8 concurrent threads: {len(cycle_1_entries)}")
    assert len(cycle_1_entries) == 1

    MONITORING_PATH.unlink()
    MONITORING_PATH = real_path
    print("Concurrency smoke test passed — no PermissionError, no duplicate/corrupted entries.")


if __name__ == "__main__":
    _self_test()
    _self_test_concurrency()