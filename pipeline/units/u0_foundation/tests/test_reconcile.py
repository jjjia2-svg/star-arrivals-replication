"""Tests for U0 reconcile.py (T16-T18).

Exit code on imbalance: TALLY_IMBALANCE=15.
  T16 expected = kept + failed + skipped: if the arithmetic arm is unbalanced -> exit(TALLY_IMBALANCE=15) and print the gap.
  T17 op_id set arm (op_ids_expected vs op_ids_seen) unbalanced -> HALT.
  T18 deduct exactly once (no repeated deduction); diff_tolerance=None -> raise on None.

In plain words: reconciliation = count the books before a fetch finishes and confirm that everything
that should have been fetched is accounted for, instead of silently dropping data as the earlier
UQ/Sydney run did.
Three arms (if any one is unbalanced -> HALT, exit code 15):
  Arm 1 arithmetic: expected == kept + failed + skipped.
  Arm 2 op_id set: the expected op_id set == the op_id set actually seen (a missing and an extra op_id both blow up).
  Arm 3 refetch precondition: anything classed as transient/failed must already be in the refetch queue
       before it is let through (a failure cannot vanish; it must be queued for refetch).
Rules:
  - any unbalanced arm -> print the gap (which item / which op_id is missing) + exit(15); never pass silently.
  - deduct exactly once: one entry is settled once and not deducted again (a repeated deduction would fake a balance).
  - diff_tolerance = an unset red-line placeholder (redlines.reconcile.diff_tolerance: null);
    on None it must raise and never pick an "allowed difference" by itself.

These tests are local only: no network, no fetching (reconcile is pure counting + HALT; the tally is written to a temp dir).
"""
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common.reconcile import reconcile_fetch  # noqa: E402
from common._redlines import RedlineUnsigned  # noqa: E402
from identity.exit_codes import TALLY_IMBALANCE  # noqa: E402


def _balanced_kwargs(tmp_path):
    """Baseline inputs with all three arms balanced (each test changes one dimension to unbalance one arm)."""
    return dict(
        expected=3,
        kept=2,
        failed=1,
        skipped=0,
        op_ids_expected={"op_a", "op_b", "op_c"},
        op_ids_seen={"op_a", "op_b", "op_c"},
        stage="m1_fetch",
        tally_path=tmp_path / "tally.json",
        refetch_queue={"op_c"},  # the 1 failed entry is already in the refetch queue
    )


# --- baseline: all three arms balanced -> no HALT (a balanced book is not killed by mistake) ---

def test_balanced_three_arms_does_not_halt(tmp_path):
    # all three arms balanced: arithmetic 3==2+1+0, op_id sets equal, failed already in refetch -> returns normally (no exit)
    result = reconcile_fetch(diff_tolerance=0, **_balanced_kwargs(tmp_path))
    # a balanced book returns a tally with balanced=True (no SystemExit)
    assert result["balanced"] is True


# --- T16: arithmetic arm unbalanced -> exit(TALLY_IMBALANCE=15) ---

def test_arithmetic_arm_imbalance_halts_with_code_15(tmp_path):
    kw = _balanced_kwargs(tmp_path)
    kw["expected"] = 5  # 5 != 2+1+0 = 3 -> arithmetic arm unbalanced
    with pytest.raises(SystemExit) as exc:
        reconcile_fetch(diff_tolerance=0, **kw)
    assert exc.value.code == TALLY_IMBALANCE
    assert TALLY_IMBALANCE == 15


def test_arithmetic_imbalance_prints_gap(tmp_path, capsys):
    kw = _balanced_kwargs(tmp_path)
    kw["expected"] = 5  # gap = 5 - 3 = 2
    with pytest.raises(SystemExit):
        reconcile_fetch(diff_tolerance=0, **kw)
    captured = capsys.readouterr()  # read once only (a second read would find the buffer cleared)
    out = captured.out + captured.err
    # the gap must be printed (including the stage name, so a person can see which stage lost how much)
    assert "m1_fetch" in out


# --- T17: op_id set arm unbalanced -> HALT ---

def test_op_id_arm_missing_seen_halts(tmp_path):
    kw = _balanced_kwargs(tmp_path)
    # 3 op_ids expected, only 2 seen (op_c is missing) -> set arm unbalanced
    kw["op_ids_seen"] = {"op_a", "op_b"}
    # also make the arithmetic + refetch consistent, to isolate "only the op_id arm is unbalanced"
    kw["expected"] = 2
    kw["kept"] = 2
    kw["failed"] = 0
    kw["refetch_queue"] = set()
    with pytest.raises(SystemExit) as exc:
        reconcile_fetch(diff_tolerance=0, **kw)
    assert exc.value.code == TALLY_IMBALANCE


def test_op_id_arm_extra_seen_halts(tmp_path):
    kw = _balanced_kwargs(tmp_path)
    # an op_id outside the expected set (op_z) was seen -> set arm unbalanced (an extra one must blow up too)
    kw["op_ids_seen"] = {"op_a", "op_b", "op_c", "op_z"}
    with pytest.raises(SystemExit) as exc:
        reconcile_fetch(diff_tolerance=0, **kw)
    assert exc.value.code == TALLY_IMBALANCE


def test_op_id_imbalance_prints_missing_ids(tmp_path, capsys):
    kw = _balanced_kwargs(tmp_path)
    kw["op_ids_seen"] = {"op_a", "op_b"}  # op_c missing
    kw["expected"] = 2
    kw["kept"] = 2
    kw["failed"] = 0
    kw["refetch_queue"] = set()
    with pytest.raises(SystemExit):
        reconcile_fetch(diff_tolerance=0, **kw)
    captured = capsys.readouterr()  # read once only (a second read would find the buffer cleared)
    out = captured.out + captured.err
    assert "op_c" in out  # print the missing op_id so a person can locate it


# --- T18a: refetch precondition arm - a transient failure must already be in the refetch queue ---

def test_failed_not_in_refetch_queue_halts(tmp_path):
    kw = _balanced_kwargs(tmp_path)
    # 1 failed entry but the refetch queue is empty -> the failure is unaccounted for -> HALT (a failure must not vanish)
    kw["refetch_queue"] = set()
    with pytest.raises(SystemExit) as exc:
        reconcile_fetch(diff_tolerance=0, **kw)
    assert exc.value.code == TALLY_IMBALANCE


# --- T18b: deduct exactly once ---

def test_deduction_happens_exactly_once(tmp_path):
    # deduct exactly once: op_c appears once in the refetch queue and is settled once, so the book balances;
    # a repeated deduction (twice) would give failed(1) - 2 < 0 and break the balance, so assert that "exactly once" balances the book.
    kw = _balanced_kwargs(tmp_path)
    result = reconcile_fetch(diff_tolerance=0, **kw)
    assert result["balanced"] is True
    # the failed count is kept as is (settling is "exactly once" logically and does not subtract the failed count repeatedly through zero)
    assert result["failed"] == 1


# --- T18c: diff_tolerance=None -> raise (an unset red-line placeholder gets no default) ---

def test_diff_tolerance_none_raises(tmp_path):
    # diff_tolerance unset (None) -> raise on None, never pick an "allowed difference" by itself
    kw = _balanced_kwargs(tmp_path)
    with pytest.raises(RedlineUnsigned):
        reconcile_fetch(diff_tolerance=None, **kw)


def test_diff_tolerance_none_raises_even_when_balanced(tmp_path):
    # even when all three arms already balance, diff_tolerance=None must raise first (the placeholder rule takes precedence; do not pass)
    kw = _balanced_kwargs(tmp_path)
    with pytest.raises(RedlineUnsigned):
        reconcile_fetch(diff_tolerance=None, **kw)
