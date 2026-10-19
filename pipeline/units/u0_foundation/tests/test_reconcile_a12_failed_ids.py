"""A12 tests: reconcile arm 3 using "failed identity inclusion" (failed_ids is contained in refetch_queue).

Problem (review A12, `reconcile.py:124`): arm 3 compared only the COUNT of the refetch queue (`len(queue) < failed`),
not the IDENTITY of the failed op_ids, so a specific failed item could be silently left out of the refetch.

Failure case: failed=1 (the real failure is op_c) but refetch_queue={op_x} (the wrong item was queued and
op_c is absent); arm 3's count check `1 < 1` is false, so the books are judged balanced (a miss). Fix:
pass the set of failed op_ids as an argument and make arm 3 a set-inclusion check
(`failed_ids ⊆ refetch_queue`); a queue with enough entries but the wrong members also HALTs.

Backward compatible: old callers that do not pass failed_ids (=None) fall back to the old count
check, behaviour unchanged.
"""
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common.reconcile import reconcile_fetch  # noqa: E402
from identity.exit_codes import TALLY_IMBALANCE  # noqa: E402


def _base_kwargs(tmp_path):
    """Baseline where arms 1 and 2 balance (arm 3 is the only variable). failed=1 corresponds to op_c."""
    return dict(
        expected=3,
        kept=2,
        failed=1,
        skipped=0,
        op_ids_expected={"op_a", "op_b", "op_c"},
        op_ids_seen={"op_a", "op_b", "op_c"},   # arm 2 balanced
        stage="m1_fetch",
        tally_path=tmp_path / "tally.json",
    )


def test_failed_ids_membership_mismatch_halts_even_when_count_sufficient(tmp_path):
    # Core test: the queue has enough entries (len=1, not < failed=1) but the wrong member (op_c is not queued, op_x was queued instead).
    # The old count check `1 < 1` is false -> silently judged balanced (op_c is never refetched). The new identity check: op_c is not in the queue -> must HALT.
    kw = _base_kwargs(tmp_path)
    kw["refetch_queue"] = {"op_x"}   # count=1 is enough, but the really failed op_c is absent
    kw["failed_ids"] = {"op_c"}      # identity of the real failure
    with pytest.raises(SystemExit) as exc:
        reconcile_fetch(diff_tolerance=0, **kw)
    assert exc.value.code == TALLY_IMBALANCE


def test_failed_ids_membership_mismatch_prints_missing_id(tmp_path, capsys):
    # before HALT the failed op_id that missed the refetch must be printed, so a person can see which one was silently dropped
    kw = _base_kwargs(tmp_path)
    kw["refetch_queue"] = {"op_x"}
    kw["failed_ids"] = {"op_c"}
    with pytest.raises(SystemExit):
        reconcile_fetch(diff_tolerance=0, **kw)
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "op_c" in out   # print the failed op_id that missed the refetch
    assert "m1_fetch" in out


def test_failed_ids_all_queued_passes(tmp_path):
    # all failed identities are already in the refetch queue (failed_ids contained in queue) -> balanced, no HALT
    kw = _base_kwargs(tmp_path)
    kw["refetch_queue"] = {"op_c", "op_extra"}   # op_c is present + the queue may contain extra candidates
    kw["failed_ids"] = {"op_c"}
    result = reconcile_fetch(diff_tolerance=0, **kw)
    assert result["balanced"] is True
    assert result["failed"] == 1


def test_legacy_count_check_still_applies_without_failed_ids(tmp_path):
    # backward compatible: failed_ids not passed -> keep the old count check (empty queue + failed=1 -> len 0 < 1 -> HALT)
    kw = _base_kwargs(tmp_path)
    kw["refetch_queue"] = set()
    with pytest.raises(SystemExit) as exc:
        reconcile_fetch(diff_tolerance=0, **kw)
    assert exc.value.code == TALLY_IMBALANCE
