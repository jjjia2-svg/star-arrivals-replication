"""M7a-T3 pctile_engine — three-dimension cell percentile engine: cell estimation gate + within-cell percentile.

In plain words: how many people must a "small cell" (same subfield × same age band × same year) have to be worth computing a top-p star ranking?
Top 1% needs 100 people, top 5% needs 30. Too few people → the cell cannot be computed (left empty / NA).

Fixed rules: per-p estimation gate = max(cell_min_n[pct_p], cell_min_n.floor): top 1% → max(100,30)=100;
top 5% → max(20,30)=30. Thresholds are read from RED, not hard-coded; unset → raise.
WARNING: whether the top-5% value is 20 or 30 is contradictory in the original design text → pending manual review.
"""
import pytest

from common._redlines import RED, RedlineUnsigned


def _cmn():
    return RED["star"]["cell_min_n"]


def test_1pct_gate_is_100():
    """A top-1% cell needs >=100 (=max(pct_1=100, floor=30))."""
    from m7a_star.pctile_engine import cell_estimable
    assert cell_estimable(100, 0.01, _cmn()) is True
    assert cell_estimable(99, 0.01, _cmn()) is False


def test_5pct_gate_is_30_gap1_signed():
    """A top-5% cell needs >=30 (=max(pct_5=20, floor=30)); "20 vs 30" pending review."""
    from m7a_star.pctile_engine import cell_estimable
    assert cell_estimable(30, 0.05, _cmn()) is True
    assert cell_estimable(29, 0.05, _cmn()) is False
    assert cell_estimable(25, 0.05, _cmn()) is False   # 20<=25<30: GAP-1 → not enough (the old #23 value 20 is superseded)


def test_gate_uses_max_pct_and_floor():
    """Record the configured values + combination rule: 1% → max(100,30)=100; 5% → max(20,30)=30."""
    from m7a_star.pctile_engine import cell_estimable
    cmn = _cmn()
    assert cmn["pct_1"] == 100 and cmn["pct_5"] == 20 and cmn["floor"] == 30
    assert cell_estimable(50, 0.01, cmn) is False   # 50 < 100
    assert cell_estimable(50, 0.05, cmn) is True    # 50 >= 30


def test_unknown_p_raises():
    """Unknown p (no matching pct key) → raise, no silent fallback."""
    from m7a_star.pctile_engine import cell_estimable
    with pytest.raises(ValueError):
        cell_estimable(100, 0.10, _cmn())


def test_unsigned_cell_min_raises(monkeypatch):
    """cell_min_n value is null (unset) → raise, never quietly default."""
    from m7a_star.pctile_engine import cell_estimable
    monkeypatch.setitem(RED["star"]["cell_min_n"], "floor", None)
    with pytest.raises((RedlineUnsigned, ValueError)):
        cell_estimable(100, 0.05, RED["star"]["cell_min_n"])


# ============ Within-cell percentile: naive rank method ============
# The naive rank method. The old production code used "midpoint rank (strictly lower + 0.5×ties)/n" —
# that rule was withdrawn but the code was never rewritten; the tests in this section are rewritten accordingly.
# Formula: rank = 1 + #{strictly higher than me} (competition rank), percentile = 1 − rank/n; ties share a rank, the whole tie group enters or leaves together.


def test_tie_at_quota_boundary_whole_group_in():
    """Must be red (1): top 2 in a 10-person cell (quota p·n = 0.2×10 = 2), with 3 people tied at rank 2:
    the naive method gives rank=2 ≤ 2 → all 3 **enter** (pct = 1−2/10 = 0.8 ≥ 1−0.2);
    the withdrawn midpoint method gives (6+1.5)/10 = 0.75 < 0.8 → none enter — this test must be red before the formula is changed."""
    from m7a_star.pctile_engine import fractional_percentiles
    pcts = fractional_percentiles([100, 50, 50, 50, 5, 4, 3, 2, 1, 0])
    assert pcts[1] == pcts[2] == pcts[3] == 1 - 2 / 10   # tied people share rank 2
    assert all(p >= 1 - 0.2 for p in pcts[1:4])          # on the quota line → the whole group enters
    assert pcts[0] == 1 - 1 / 10                         # first place rank=1


def test_ties_share_same_percentile():
    """Ties share a rank: [5,5,5,3,3,2,2,2,1,0], the three 5s share rank 1 → 1−1/10 = 0.9.
    (Rewritten for the naive method: the old midpoint value 0.85 is retired.)"""
    from m7a_star.pctile_engine import fractional_percentiles
    pcts = fractional_percentiles([5, 5, 5, 3, 3, 2, 2, 2, 1, 0])
    assert pcts[0] == pcts[1] == pcts[2] == 1 - 1 / 10


def test_no_ties_percentile_is_one_minus_rank_over_n():
    """Must be red (2): no ties: percentile = 1 − rank/n exactly. [10,20,30] → rank 3/2/1.
    (Rewritten for the naive method: the old midpoint value (rank−0.5)/n is retired.)"""
    from m7a_star.pctile_engine import fractional_percentiles
    assert fractional_percentiles([10, 20, 30]) == [1 - 3 / 3, 1 - 2 / 3, 1 - 1 / 3]


def test_single_person_is_zero():
    """A cell with only 1 person → 1 − 1/1 = 0.0 (naive rank method; the old midpoint value 0.5 is retired)."""
    from m7a_star.pctile_engine import fractional_percentiles
    assert fractional_percentiles([42]) == [0.0]


def test_empty_cell_is_empty():
    from m7a_star.pctile_engine import fractional_percentiles
    assert fractional_percentiles([]) == []


def test_percentile_matches_bruteforce_rank_law():
    """Law check: every person's percentile == 1 − (1 + #{strictly higher than me})/n (brute-force recomputed per person, ties included)."""
    from m7a_star.pctile_engine import fractional_percentiles
    values = [1, 7, 7, 3, 9, 2, 2, 5]
    pcts = fractional_percentiles(values)
    n = len(values)
    for v, p in zip(values, pcts):
        assert p == 1 - (1 + sum(1 for u in values if u > v)) / n


def test_top_of_large_cell_exactly_at_1pct_quota():
    """Must be red (4) (engine side): 100 people with no ties: first place rank=1 exactly equals the quota 0.01×100=1 → enters
    (percentile = 1−1/100, exactly on the cut line; the integer-exact boundary of star identification is tested in star_flags)."""
    from m7a_star.pctile_engine import fractional_percentiles
    pcts = fractional_percentiles(list(range(100)))
    assert max(pcts) == 1 - 1 / 100
