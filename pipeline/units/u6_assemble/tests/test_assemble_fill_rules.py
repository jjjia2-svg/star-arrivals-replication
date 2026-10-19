"""Red tests for the outcome fill rules: the R7 three forms + NA rate C2.

Rules:
  (1) years with output -> take the OUTPUT value directly;
  (2) employed (authority = table B) and no output -> sum-type (fwci_frac/pub_count family) records a true 0,
      mean-type (fwci_mean family) records NA;
  (3) non-employed years with no output (including years after complete exit) -> all outcomes NA; never fill 0.
C2: fwci_frac NA rate >20% -> HUMAN_REVIEW (not a silent WARN); the U5 MNAR double flag also goes into diag.
"""
from __future__ import annotations

import json

import pyarrow.parquet as pq
import pytest

from m7b_assemble import assemble as asm

SUM_COLS = ("fwci_frac", "fwci_frac_ex_star", "pub_count", "pub_count_ex_star")
MEAN_COLS = ("fwci_mean", "fwci_mean_ex_star")


def _run(tmp_path, inputs, config):
    return asm.assemble_frames(inputs, out_root=tmp_path / "u6", config=config)


def _rows(tmp_path, p_level, incumbent):
    p = tmp_path / "u6" / "frame" / "_frozen" / f"analysis_frame_{p_level}.parquet"
    return {r["year"]: r for r in pq.read_table(p).to_pylist()
            if r["incumbent_person_id"] == incumbent}


def test_fill_type_constants_cover_all_outcomes():
    assert set(asm.SUM_TYPE_COLS) == set(SUM_COLS)
    assert set(asm.MEAN_TYPE_COLS) == set(MEAN_COLS)


def test_output_year_taken_as_is(tmp_path, zenou_inputs, u6_config):
    """Form (1): OUTPUT has a row -> all outcomes taken directly (including years still publishing after leaving the department: real publications)."""
    _run(tmp_path, zenou_inputs, u6_config)
    r = _rows(tmp_path, "p01", "P_I1")[2016]
    assert r["fwci_frac"] == pytest.approx(1.0)
    assert r["fwci_mean"] == pytest.approx(1.0)
    assert r["pub_count_ex_star"] == pytest.approx(1.0)


def test_indept_zero_output_year_sum_zero_mean_na(tmp_path, zenou_inputs,
                                                  u6_config):
    """Form (2): I1 is employed 2000-2026 and has no OUTPUT row in 2014 -> sum-type 0 / mean-type NA."""
    _run(tmp_path, zenou_inputs, u6_config)
    r = _rows(tmp_path, "p01", "P_I1")[2014]
    for c in SUM_COLS:
        assert r[c] == pytest.approx(0.0), f"{c}: employed with zero output = a true 0"
    for c in MEAN_COLS:
        assert r[c] is None, f"{c}: a mean over 0 papers = NA, never filled with 0"


def test_exited_years_all_na_never_zero(tmp_path, zenou_inputs, u6_config):
    """Form (3) (the R7 core): I2 is employed 2010-2018 and has no publication afterwards (complete exit) ->
    all outcomes NA for 2019-2021; never recorded as 0, and no '0-filled' control column is fabricated."""
    _run(tmp_path, zenou_inputs, u6_config)
    rows = _rows(tmp_path, "p01", "P_I2")
    for y in (2019, 2020, 2021):
        for c in SUM_COLS + MEAN_COLS:
            assert rows[y][c] is None, f"year {y}.{c} after exit must be NA (R7)"
    frame_cols = set(rows[2019].keys())
    assert not any("zero" in c or "_alt" in c for c in frame_cols), \
        "no '0-filled' control column is fabricated (no pile of alternative columns)"


def test_pre_entry_years_na_not_zero(tmp_path, zenou_inputs, u6_config):
    """A year with no output before joining the department = non-employed -> NA (I2 is employed from 2010, so 2011 is employed within the window;
    I3's panel binding starts in 2012, so 2014 is employed within the p05 window 2014-2024; I2's pre-2016
    employed rows cover form (2), and this test covers I4: the panel has only 2025 -> every year in the window is non-employed -> all NA)."""
    _run(tmp_path, zenou_inputs, u6_config)
    rows = _rows(tmp_path, "p01", "P_I4")
    for y, r in rows.items():
        for c in SUM_COLS + MEAN_COLS:
            assert r[c] is None, \
                f"I4 {y}.{c}: not employed in the window and no output -> NA (late binding has no evidence of employment that year)"


def test_na_rate_over_20pct_triggers_human_review(tmp_path, zenou_inputs,
                                                  u6_config):
    """C2 caveat: fwci_frac NA rate >20% -> output_diag records na_rate +
    na_robustness_required=True + the verdict suggests HUMAN_REVIEW."""
    rep = _run(tmp_path, zenou_inputs, u6_config)
    diag = json.loads((tmp_path / "u6" / "_reports" / "output_diag.json")
                      .read_text())
    for lev in ("p01", "p05"):
        assert "na_rate_fwci_frac" in diag[lev]
        assert diag[lev]["na_rate_fwci_frac"] == pytest.approx(
            rep["na_rate_fwci_frac"][lev])
        if diag[lev]["na_rate_fwci_frac"] > 0.20:
            assert diag[lev]["na_robustness_required"] is True
            assert rep["verdict_hint"][lev] == "HUMAN_REVIEW"
    assert diag["upstream_mnar_flags"]["dose_p01"]["mnar_robustness_required"] \
        is True, "the MNAR double flag passed on from U5 must also go into diag"


def test_na_rate_below_threshold_warn_only(tmp_path, zenou_inputs, u6_config,
                                           mk):
    """<=20% -> a normal WARN in the log (not HUMAN_REVIEW). Build a low-NA world."""
    for lev in ("p01", "p05"):
        zenou_inputs.output[lev] = [
            mk.output(inc, y) for inc in ("P_I1", "P_I2", "P_I4")
            for y in range(2011, 2022)
        ] + ([mk.output("P_I3", y) for y in range(2014, 2025)]
             if lev == "p05" else [])
    rep = _run(tmp_path, zenou_inputs, u6_config)
    assert rep["na_rate_fwci_frac"]["p01"] <= 0.20
    assert rep["verdict_hint"]["p01"] == "WARN"


# ---------------------------------------------------------------------------
# Fix #1: FWCI cannot be computed != 0
# In the real data OUTPUT has years with "papers but the FWCI baseline entirely missing" (fwci_mean=NA), and the upstream nansum
# crushes fwci_frac to 0, mixing them with a true zero citation (fwci_mean=0) and violating the R7/C=NA semantics.
# Frame-layer fix: pub_count>0 AND fwci_mean=NA AND fwci_frac=0 -> fwci_frac recorded as NA;
# the ex_star triple likewise. A true zero citation stays 0 (different semantics, left alone).
# ---------------------------------------------------------------------------
def _swap_output_row(inputs, mk, year, **kw):
    for lev in ("p01", "p05"):
        inputs.output[lev] = [
            o for o in inputs.output[lev]
            if not (o["incumbent_person_id"] == "P_I1" and o["year"] == year)
        ] + [mk.output("P_I1", year, **kw)]


def test_fwci_uncomputable_year_na_not_zero(tmp_path, zenou_inputs, u6_config,
                                            mk):
    """Papers exist (pub_count=2) but FWCI cannot be computed at all -> fwci_frac/ex_star recorded as NA, not 0."""
    _swap_output_row(zenou_inputs, mk, 2013, pub_count=2, pub_count_ex_star=1,
                     fwci_frac=0.0, fwci_frac_ex_star=0.0,
                     fwci_mean=None, fwci_mean_ex_star=None)
    _run(tmp_path, zenou_inputs, u6_config)
    r = _rows(tmp_path, "p01", "P_I1")[2013]
    assert r["fwci_frac"] is None, "years where FWCI cannot be computed were wrongly recorded as 0"
    assert r["fwci_frac_ex_star"] is None
    assert r["pub_count"] == pytest.approx(2.0), "the paper count is real, leave it unchanged"
    assert r["pub_count_ex_star"] == pytest.approx(1.0)
    assert r["fwci_mean"] is None and r["fwci_mean_ex_star"] is None


def test_true_zero_cited_year_stays_zero(tmp_path, zenou_inputs, u6_config, mk):
    """True zero citation (fwci_mean=0, baseline computable) -> fwci_frac=0 is kept, no collateral damage."""
    _swap_output_row(zenou_inputs, mk, 2013, pub_count=1, pub_count_ex_star=1,
                     fwci_frac=0.0, fwci_frac_ex_star=0.0,
                     fwci_mean=0.0, fwci_mean_ex_star=0.0)
    _run(tmp_path, zenou_inputs, u6_config)
    r = _rows(tmp_path, "p01", "P_I1")[2013]
    assert r["fwci_frac"] == pytest.approx(0.0), "a true zero citation must not be cleared to NA"
    assert r["fwci_frac_ex_star"] == pytest.approx(0.0)


def test_fwci_uncomputable_only_ex_star_side(tmp_path, zenou_inputs, u6_config,
                                             mk):
    """Full FWCI is computable but the star-excluded side is entirely missing -> only ex_star is recorded as NA, the full column is untouched."""
    _swap_output_row(zenou_inputs, mk, 2013, pub_count=2, pub_count_ex_star=1,
                     fwci_frac=1.5, fwci_frac_ex_star=0.0,
                     fwci_mean=0.75, fwci_mean_ex_star=None)
    _run(tmp_path, zenou_inputs, u6_config)
    r = _rows(tmp_path, "p01", "P_I1")[2013]
    assert r["fwci_frac"] == pytest.approx(1.5)
    assert r["fwci_frac_ex_star"] is None


def test_fwci_uncomputable_counted_in_diag(tmp_path, zenou_inputs, u6_config,
                                           mk):
    """The fix must be auditable: output_diag records n_fwci_uncomputable_to_na (full / ex_star)."""
    _swap_output_row(zenou_inputs, mk, 2013, pub_count=2, pub_count_ex_star=1,
                     fwci_frac=0.0, fwci_frac_ex_star=0.0,
                     fwci_mean=None, fwci_mean_ex_star=None)
    _run(tmp_path, zenou_inputs, u6_config)
    diag = json.loads((tmp_path / "u6" / "_reports" / "output_diag.json")
                      .read_text())
    for lev in ("p01", "p05"):
        assert diag[lev]["n_fwci_uncomputable_to_na"] == 1
        assert diag[lev]["n_fwci_uncomputable_to_na_ex_star"] == 1


# ---------------------------------------------------------------------------
# Fix #3: the roster union must consume human_verified:
# for the same person in the same department, when a human-verified row overlaps an unverified row, the verified row takes priority
# (overlap case end to end: an unverified old row widened the employed interval, and zero-output years outside the interval
# were wrongly filled with 0 instead of NA).
# ---------------------------------------------------------------------------
def test_polluted_unverified_roster_row_no_longer_zero_fills(
        tmp_path, zenou_inputs, u6_config, mk):
    """I2 is human-verified employed 2010-2018; add one contaminating unverified row 2000-2026 (overlapping) -> 2019-2021
    must still be NA (the verified row takes priority), and must not be widened by the union and wrongly filled with 0."""
    for r in zenou_inputs.roster:
        if r["author_id"] == "AI2":
            r["human_verified"] = True
    zenou_inputs.roster.append(
        mk.roster("monash_econ", "AI2", year_start=2000, year_end=2026,
                  evidence="official_roster", human_verified=False))
    _run(tmp_path, zenou_inputs, u6_config)
    rows = _rows(tmp_path, "p01", "P_I2")
    for y in (2019, 2020, 2021):
        for c in SUM_COLS:
            assert rows[y][c] is None, \
                f"{y}.{c}: an interval widened by an unverified contaminating row was wrongly filled with 0 (overlap case)"
