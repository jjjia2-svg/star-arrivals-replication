"""cutoff.filter_works_until — red tests for the single t-1 truncation helper (#6/#6b).

Freeze at t-1 = use only data up to the year before the star's arrival year (prevents post-arrival convergence contamination, #16).
H4 = refs_edges itself has no publication_year, so the year used for truncation must come from a join with works —
     rows passed in without a year -> the precondition assertion raises, never silently keeping everything.
"""
from __future__ import annotations

import pytest

from m4_dose import cutoff


def test_cutoff_inclusive_boundary(mk):
    """#6: works 2014/2015/2016, t_minus_1=2015 -> includes 2014+2015, excludes 2016 (inclusive <=)."""
    rows = [
        mk.edge("W1", "A1", 2014),
        mk.edge("W2", "A1", 2015),
        mk.edge("W3", "A1", 2016),
    ]
    out = cutoff.filter_works_until(rows, 2015)
    assert sorted(r["work_id"] for r in out) == ["W1", "W2"]
    assert all(r["publication_year"] <= 2015 for r in out)


def test_refs_cutoff_year_from_works_not_refs_edges(mk):
    """#6b (H4): input has only the 2 refs_edges columns (no publication_year) -> the precondition assertion raises.

    The year for refs truncation must come from a join with works.parquet (refs_edges has no year);
    forgetting the join and feeding refs rows straight into truncation -> blow up loudly, neither silent nor untruncated.
    """
    refs_rows = [mk.ref("W1", "W_ref_1"), mk.ref("W2", "W_ref_2")]
    with pytest.raises(cutoff.CutoffYearMissing):
        cutoff.filter_works_until(refs_rows, 2015)


def test_cutoff_none_year_raises():
    """A row with publication_year=None -> raise (a missing year is neither silently dropped nor silently kept)."""
    rows = [{"work_id": "W1", "publication_year": None}]
    with pytest.raises(cutoff.CutoffYearMissing):
        cutoff.filter_works_until(rows, 2015)


def test_cutoff_rejects_none_t_minus_1(mk):
    """t_minus_1=None -> ValueError (B-EVENTS-T1: a missing freeze point = upstream events did not provide it, fail loud)."""
    rows = [mk.edge("W1", "A1", 2014)]
    with pytest.raises(ValueError):
        cutoff.filter_works_until(rows, None)


def test_cutoff_empty_rows_ok():
    """Empty input -> empty output (legal; no raise) — downstream coverage/coupling handle empty sets themselves."""
    assert cutoff.filter_works_until([], 2015) == []
