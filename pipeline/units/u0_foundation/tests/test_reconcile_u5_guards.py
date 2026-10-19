"""Four reconcile exclusion-guard functions + the two-tables-same-source assertion (interface contract, added for U5 M5b).

The contract fixed these signatures long ago but u0 never implemented them. The first real
consumer is U5 (Task 11, checks #44/#44b), so they live in common/reconcile.py ("the contract is
the code"). No identification choices are involved: these are engineering reconciliation assertions only.
"""
from __future__ import annotations

import pytest

from common.reconcile import (
    ExclusionGuardError,
    apply_exclusion_once,
    assert_deduction_applied_once,
    assert_invariant_monotone,
    assert_single_source_exclusion,
    assert_two_tables_same_source,
)


# ---------------------------------------------------------------------------
# assert_invariant_monotone(after, before, *, label) - monotone: clean <= full
# ---------------------------------------------------------------------------
def test_monotone_ok_when_after_le_before():
    assert_invariant_monotone(3, 5, label="t")      # does not raise
    assert_invariant_monotone(5, 5, label="t")      # equality is allowed


def test_monotone_raises_when_after_gt_before():
    with pytest.raises(ExclusionGuardError, match="monotone"):
        assert_invariant_monotone(6, 5, label="t")


# ---------------------------------------------------------------------------
# assert_deduction_applied_once(*, before, after, exclude_set, label)
#   before - after must be exactly len(exclude_set) - deducting too much (fan-out double deduction) or too little both blow up
# ---------------------------------------------------------------------------
def test_deduction_once_ok():
    assert_deduction_applied_once(before=10, after=8,
                                  exclude_set={"W1", "W2"}, label="t")


def test_deduction_twice_caught():
    # the old double-deduction bug: excluding 2 but losing 4 -> blows up
    with pytest.raises(ExclusionGuardError, match="exactly once"):
        assert_deduction_applied_once(before=10, after=6,
                                      exclude_set={"W1", "W2"}, label="t")


def test_deduction_not_applied_caught():
    with pytest.raises(ExclusionGuardError):
        assert_deduction_applied_once(before=10, after=10,
                                      exclude_set={"W1"}, label="t")


def test_deduction_kwonly_signature():
    # contract: all keyword-only - positional arguments must raise TypeError
    with pytest.raises(TypeError):
        assert_deduction_applied_once(10, 8, {"W1", "W2"}, "t")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# assert_single_source_exclusion(exclude_set, derived_from_set, *, label)
#   Note: the second argument is the positional derived_from_set (as in the interface contract)
# ---------------------------------------------------------------------------
def test_single_source_ok_positional_second_arg():
    assert_single_source_exclusion({"W1"}, {"W1"}, label="m5b_p01")


def test_single_source_mismatch_raises():
    with pytest.raises(ExclusionGuardError, match="single source"):
        assert_single_source_exclusion({"W1", "W9"}, {"W1"}, label="m5b_p01")


# ---------------------------------------------------------------------------
# apply_exclusion_once(count, exclude_set, *, label) -> int - idempotent deduction
# ---------------------------------------------------------------------------
def test_apply_exclusion_once_returns_deducted():
    assert apply_exclusion_once(10, {"a", "b"}, label="t") == 8


def test_apply_exclusion_once_negative_raises():
    with pytest.raises(ExclusionGuardError):
        apply_exclusion_once(1, {"a", "b"}, label="t")


# ---------------------------------------------------------------------------
# assert_two_tables_same_source(table_a, table_b, *, pk_cols, invariant_cols, label)
#   two tables from the same source: equal PK sets + shared columns unaffected by exclusion are equal row by row (consumed by U5 #44b)
# ---------------------------------------------------------------------------
def _rows(vals):
    return [{"incumbent_person_id": p, "year": y, "pub_count": c, "fwci_frac_ex_star": x}
            for p, y, c, x in vals]


def test_two_tables_same_source_ok():
    a = _rows([("P1", 2010, 3, 1.0), ("P2", 2011, 2, 2.0)])
    b = _rows([("P1", 2010, 3, 0.5), ("P2", 2011, 2, 1.5)])  # the ex_star columns may differ
    assert_two_tables_same_source(
        a, b, pk_cols=("incumbent_person_id", "year"),
        invariant_cols=("pub_count",), label="output",
    )


def test_two_tables_pk_set_mismatch_raises():
    a = _rows([("P1", 2010, 3, 1.0)])
    b = _rows([("P1", 2011, 3, 1.0)])
    with pytest.raises(ExclusionGuardError, match="same source"):
        assert_two_tables_same_source(
            a, b, pk_cols=("incumbent_person_id", "year"),
            invariant_cols=("pub_count",), label="output",
        )


def test_two_tables_invariant_col_mismatch_raises():
    # columns unaffected by exclusion (such as pub_count) must have the same value row by row in both tables - a difference means they were not generated from one source
    a = _rows([("P1", 2010, 3, 1.0)])
    b = _rows([("P1", 2010, 4, 1.0)])
    with pytest.raises(ExclusionGuardError, match="same source"):
        assert_two_tables_same_source(
            a, b, pk_cols=("incumbent_person_id", "year"),
            invariant_cols=("pub_count",), label="output",
        )
