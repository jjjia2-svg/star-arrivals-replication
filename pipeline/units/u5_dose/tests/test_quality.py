"""quality fill — field-normalised ratio, person-year aggregation (#3+4; #41 series).

Definition:
  - quality = fractional-credit-weighted mean of per-paper FWCI (divide-then-average, #7);
    per-paper fwci = actual / expected is computed by U4 (paper_contrib.fwci), and this step only takes the weighted average;
  - star co-authored works are dropped on the numerator side only (RED output_quality.quality_numerator_drop_star_coauthored=true,
    #3+4) — the flag still comes from the exclusion set (#2/C1);
  - note: no winsorisation at all (not trimmed, recorded as is — the p99 winsorisation is retired,
    and quality aggregation must not introduce any cap step);
  - NA is not treated as 0; all NA (or zero papers left after dropping stars) person-year = NA (None);
  - leave-star on the denominator side is forbidden (#41d source guard: no import / no recomputation of expected / fwci_baseline);
  - FWCI NA rate > mnar_missing_threshold -> mnar_robustness_required=true + WARN (#41c).
"""
from __future__ import annotations

import pathlib

import pytest

from m5b_aggregate import aggregate as agg
from m5b_aggregate import quality as qual


def _fill(mk, pc, exclude=frozenset()):
    wids = {r["work_id"] for r in pc}
    works = [mk.work(w, 2010) for w in sorted(wids)]
    rows, stats = agg.aggregate_via_u0(pc, works, exclude_works=frozenset(exclude))
    contribs = agg.to_contribs(pc, exclude_works=frozenset(exclude))[0]
    filled = qual.fill_quality(rows, contribs)
    return {(r["incumbent_person_id"], r["year"]): r for r in filled}


# ---------------------------------------------------------------------------
# #41b hand-computed values + divide-then-average + no winsorisation
# ---------------------------------------------------------------------------
def test_quality_is_fwci_field_normalized_ratio(mk):
    """#41b: quality = sum(frac*fwci)/sum(frac), per-paper weighted mean — matches the hand-computed fixture.

    papers: (frac=0.5, fwci=2.0) + (frac=1.0, fwci=1.0)
    -> quality = (0.5*2 + 1*1) / (0.5+1) = 2.0/1.5 = 1.3333...
    (expected = mean definition is already inside the U4 fwci; this step is never a recomputation of the 32-bucket denominator).
    """
    pc = [mk.pc("W1", "P_I", "P_I", 2010, frac_credit=0.5, fwci=2.0),
          mk.pc("W2", "P_I", "P_I", 2010, frac_credit=1.0, fwci=1.0)]
    r = _fill(mk, pc)[("P_I", 2010)]
    assert r["quality"] == pytest.approx(2.0 / 1.5)


def test_quality_numerator_drops_star_coauthored(mk):
    """#3+4: stars are dropped on the numerator side only (RED quality_numerator_drop_star_coauthored=true):
    star co-authored papers do not enter the numerator/weights of quality."""
    pc = [mk.pc("W1", "P_I", "P_I", 2010, frac_credit=0.5, fwci=2.0),
          mk.pc("W2", "P_I", "P_I", 2010, frac_credit=1.0, fwci=1.0),
          mk.pc("W_STAR", "P_I", "P_I", 2010, frac_credit=1.0, fwci=10.0)]
    r = _fill(mk, pc, exclude=frozenset({"W_STAR"}))[("P_I", 2010)]
    assert r["quality"] == pytest.approx(2.0 / 1.5)   # W_STAR does not enter
    # it would enter if not dropped
    r2 = _fill(mk, pc)[("P_I", 2010)]
    assert r2["quality"] == pytest.approx((0.5 * 2 + 1 * 1 + 1 * 10) / 2.5)


def test_no_winsor_extreme_value_kept_raw(mk):
    """No winsorisation at all — an extreme fwci enters the weighted mean at its raw value, uncapped."""
    pc = [mk.pc("W1", "P_I", "P_I", 2010, frac_credit=1.0, fwci=1000.0),
          mk.pc("W2", "P_I", "P_I", 2010, frac_credit=1.0, fwci=0.0)]
    r = _fill(mk, pc)[("P_I", 2010)]
    assert r["quality"] == pytest.approx(500.0)       # if it were capped it would not be 500


# ---------------------------------------------------------------------------
# NA discipline (#41 + NA is not treated as 0)
# ---------------------------------------------------------------------------
def test_all_na_person_year_is_na_not_zero(mk):
    """#41: an all-NA person-year -> quality=None (no crash, never filled with 0)."""
    pc = [mk.pc("W1", "P_I", "P_I", 2010, frac_credit=1.0, fwci=None)]
    r = _fill(mk, pc)[("P_I", 2010)]
    assert r["quality"] is None


def test_na_paper_not_counted_as_zero(mk):
    """NA papers enter neither the numerator nor the weights — mixing in NA does not pull the mean down."""
    pc = [mk.pc("W1", "P_I", "P_I", 2010, frac_credit=1.0, fwci=2.0),
          mk.pc("W2", "P_I", "P_I", 2010, frac_credit=9.0, fwci=None)]
    r = _fill(mk, pc)[("P_I", 2010)]
    assert r["quality"] == pytest.approx(2.0)


def test_all_excluded_person_year_is_na(mk):
    """Zero non-NA papers after dropping stars -> quality=None (same discipline as fwci_mean_ex_star)."""
    pc = [mk.pc("W_STAR", "P_I", "P_I", 2010, frac_credit=1.0, fwci=5.0)]
    r = _fill(mk, pc, exclude=frozenset({"W_STAR"}))[("P_I", 2010)]
    assert r["quality"] is None


def test_other_eleven_keys_untouched(mk):
    """fill_quality changes only the quality column; the other 11 keys are untouched value by value."""
    pc = [mk.pc("W1", "P_I", "P_I", 2010, frac_credit=0.5, fwci=2.0)]
    wids = {r["work_id"] for r in pc}
    works = [mk.work(w, 2010) for w in sorted(wids)]
    rows, _ = agg.aggregate_via_u0(pc, works, exclude_works=frozenset())
    before = {k: v for k, v in rows[0].items() if k != "quality"}
    contribs = agg.to_contribs(pc, exclude_works=frozenset())[0]
    filled = qual.fill_quality(rows, contribs)
    after = {k: v for k, v in filled[0].items() if k != "quality"}
    assert before == after


# ---------------------------------------------------------------------------
# #41c MNAR + #41d/#48 source guard + fixed-value guard
# ---------------------------------------------------------------------------
def test_fwci_na_rate_triggers_mnar_flag(mk):
    """#41c: NA rate 30% (>20%) -> flag True + WARN; 15% -> False."""
    pc30 = ([mk.pc(f"W{i}", "P_I", "P_I", 2010, fwci=None) for i in range(3)]
            + [mk.pc(f"V{i}", "P_I", "P_I", 2010, fwci=1.0) for i in range(7)])
    with pytest.warns(UserWarning, match="MNAR"):
        st = qual.fwci_na_stats(pc30, mnar_missing_threshold=0.20)
    assert st["mnar_robustness_required"] is True
    assert st["fwci_na_rate"] == pytest.approx(0.3)

    pc15 = ([mk.pc(f"W{i}", "P_I", "P_I", 2010, fwci=None) for i in range(3)]
            + [mk.pc(f"V{i}", "P_I", "P_I", 2010, fwci=1.0) for i in range(17)])
    st2 = qual.fwci_na_stats(pc15, mnar_missing_threshold=0.20)
    assert st2["mnar_robustness_required"] is False


def test_denominator_leave_star_not_done_source_guard():
    """#41d + #48: none of the M5b source touches the FWCI denominator — it neither imports nor recomputes fwci_baseline/expected."""
    import m5b_aggregate
    pkg_dir = pathlib.Path(m5b_aggregate.__file__).parent
    for py in sorted(pkg_dir.glob("*.py")):
        src = py.read_text(encoding="utf-8").lower()
        assert "fwci_baseline" not in src, f"{py.name} touched the FWCI denominator table"
        assert "expected_citations" not in src, f"{py.name} recomputed the expected denominator"


def test_signed_quality_redlines_present():
    """Fixed-value guard for the quality definition: the two RED output_quality keys must hold their fixed values (red at once if they drift)."""
    from common._redlines import RED
    assert RED["output_quality"]["quality_numerator_drop_star_coauthored"] is True
    assert RED["fwci"]["denominator_leave_star"] is False
