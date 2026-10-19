"""assemble frame red tests: 15-column schema / row sources / D1 two files / dose-join / age_gap broadcast.

Coverage: T1 (schema exact, final 15 columns) / T2 (G1 no group) / T3 (D1 two files,
same schema, same codepath) / T4 (#16 primary dose only) / T5 (boundary -> low_confidence) /
T6 (H5 degree fan-out raise) / T7 (age_gap 3->4-tuple broadcast) / T8 (C3 treated row source) /
T9 (C3 year window ±5 + C1 pre-period) / T10 (post) / T11 (frozen_at == t−1) /
T12 (output join key) / T13 (D1 ex_star two files do not fail fast) / T14 (pub_count taken directly;
the B6-PUBFRAC-LOG bridge was retired after the rename) / T23 (PK unique / no fan-out).
"""
from __future__ import annotations

import inspect

import pyarrow.parquet as pq
import pytest

from common.schema import ANALYSIS_FRAME
from m7b_assemble import assemble as asm


def _run(tmp_path, inputs, config):
    return asm.assemble_frames(inputs, out_root=tmp_path / "u6", config=config)


def _frame_rows(tmp_path, p_level):
    p = tmp_path / "u6" / "frame" / "_frozen" / f"analysis_frame_{p_level}.parquet"
    return pq.read_table(p).to_pylist()


# --- T1/T2: exactly 15 columns + G1 regression guard for the deleted group ----------------------------------
def test_analysis_frame_schema_exact_15_cols(tmp_path, zenou_inputs, u6_config):
    _run(tmp_path, zenou_inputs, u6_config)
    rows = _frame_rows(tmp_path, "p01")
    assert rows, "the frame must not be empty"
    assert set(ANALYSIS_FRAME) == {
        "incumbent_person_id", "year", "star_person_id", "event_id", "treated",
        "post", "dose_coupling", "dose_low_confidence", "age_gap", "fwci_frac",
        "pub_count", "fwci_frac_ex_star", "pub_count_ex_star", "fwci_mean",
        "fwci_mean_ex_star",
    }, "the 15 final columns registered in u0 §2.5"
    for r in rows:
        assert set(r) == set(ANALYSIS_FRAME)
        for banned in ("group", "star_works_count", "same_cohort_field_near",
                       "degree"):
            assert banned not in r


def test_no_group_column_anywhere():
    """G1 core regression red test: the source has no reference to assign_group / same_cohort_field_near."""
    src = inspect.getsource(asm)
    assert "assign_group" not in src
    assert "same_cohort_field_near" not in src


# --- T3/D1: two files with the same schema and codepath, neither a long table nor a row dimension -------------------------
def test_two_files_p01_p05_same_schema_same_codepath(tmp_path, zenou_inputs,
                                                     u6_config, monkeypatch):
    calls = []
    real = asm._assemble_one

    def spy(p_level, *a, **kw):
        calls.append(p_level)
        return real(p_level, *a, **kw)

    monkeypatch.setattr(asm, "_assemble_one", spy)
    _run(tmp_path, zenou_inputs, u6_config)
    assert calls == ["p01", "p05"], "both files are generated at once by the same function body"

    s01 = pq.read_table(tmp_path / "u6" / "frame" / "_frozen"
                        / "analysis_frame_p01.parquet").schema
    s05 = pq.read_table(tmp_path / "u6" / "frame" / "_frozen"
                        / "analysis_frame_p05.parquet").schema
    assert s01.serialize().to_pybytes() == s05.serialize().to_pybytes(), \
        "the two tables' schemas are byte-identical"
    assert "star_p_level" not in s01.names, "not a long table (no p-level column)"


# --- T4/#16: dose_coupling comes only from the primary dose coupling_share -----------------------
def test_dose_coupling_from_main_dose_only(tmp_path, zenou_inputs, u6_config):
    """The secondary dose (topic_cos/embed_cos = abstract/topic text similarity) is an endogenous contamination source (#16)
    and never enters dose_coupling. The fixture has topic_cos=0.1, a value different from coupling_share, so the two can be told apart."""
    _run(tmp_path, zenou_inputs, u6_config)
    rows = _frame_rows(tmp_path, "p01")
    by_pk = {(r["incumbent_person_id"], r["event_id"]) for r in rows
             if abs(r["dose_coupling"] - 0.1) < 1e-9
             and r["incumbent_person_id"] != "P_I4"}
    assert not by_pk, "dose_coupling holds topic_cos values -> secondary dose leak"
    got = {round(r["dose_coupling"], 6) for r in rows
           if r["incumbent_person_id"] == "P_I1"}
    assert got == {0.4}
    src = inspect.getsource(asm)
    assert "topic_cos" not in src and "embed_cos" not in src, \
        "assemble source must not read secondary-dose columns"


def test_dose_low_confidence_maps_boundary_sensitive(tmp_path, zenou_inputs,
                                                     u6_config):
    zenou_inputs.dose["p01"][0]["boundary_sensitive"] = True
    _run(tmp_path, zenou_inputs, u6_config)
    rows = [r for r in _frame_rows(tmp_path, "p01")
            if r["incumbent_person_id"] == "P_I1"]
    assert all(r["dose_low_confidence"] is True for r in rows)


# --- T6/H5: the same (i,star,event) with two degree rows in dose -> raise -----------------------
def test_pairwise_dose_unique_per_triple_else_raise(tmp_path, zenou_inputs,
                                                    u6_config, mk):
    zenou_inputs.dose["p01"].append(
        mk.dose("P_I1", "P_Z", "AZ1:2016", coupling_share=0.4, degree=2))
    with pytest.raises(asm.FrameAssemblyError, match="degree"):
        _run(tmp_path, zenou_inputs, u6_config)


# --- T7: age_gap 3->4-tuple year broadcast (constant, non-null); no same-generation / event_time column -------------
def test_age_gap_broadcast_3to4_constant_per_year(tmp_path, zenou_inputs,
                                                  u6_config):
    _run(tmp_path, zenou_inputs, u6_config)
    rows = [r for r in _frame_rows(tmp_path, "p01")
            if r["incumbent_person_id"] == "P_I1"]
    assert len(rows) == 11
    vals = {round(r["age_gap"], 6) for r in rows}
    # Star first publication = 2016-1-24 = 1991; I1 first publication 2000 -> age_gap = 1991-2000 = -9
    assert vals == {-9.0}, \
        "age_gap = star_first_pub − ego_first_pub (identity/cohort direction), constant across years"
    assert "event_time" not in rows[0] and "same_cohort" not in rows[0], \
        "same-generation flag / event_time = derived in the regression layer (#7: arrival year frozen), not stored as a column"


# --- T8/C3: treated row PK set == dose distinct triples ---------------------------
@pytest.mark.depends_on_u345
def test_treated_rows_from_pairwise_dose_distinct_triples(tmp_path, zenou_inputs,
                                                          u6_config):
    _run(tmp_path, zenou_inputs, u6_config)
    for lev in ("p01", "p05"):
        rows = _frame_rows(tmp_path, lev)
        got = {(r["incumbent_person_id"], r["star_person_id"], r["event_id"])
               for r in rows if r["treated"]}
        want = {(d["incumbent_person_id"], d["star_person_id"], d["event_id"])
                for d in zenou_inputs.dose[lev]}
        assert got == want, f"{lev}: treated triples must exactly equal the distinct dose triples"


# --- T9/C3+C1: year window = arrival±5, including the pre-period; years outside the window write no rows ---------------
def test_year_rows_span_event_window_with_pre_period(tmp_path, zenou_inputs,
                                                     u6_config):
    _run(tmp_path, zenou_inputs, u6_config)
    rows = [r for r in _frame_rows(tmp_path, "p01")
            if r["incumbent_person_id"] == "P_I1"]
    years = sorted(r["year"] for r in rows)
    assert years == list(range(2011, 2022)), "arrival 2016 ± 5 = [2011,2021]"
    pre = [r for r in rows if r["year"] < 2016]
    assert len(pre) == 5, "pre-period rows must be present (used for the C1 anticipation test)"
    # A year with no output inside the window -> mean-type NA (not 0): I1 has no 2011 output but is employed -> fwci_mean=NA
    r2011 = next(r for r in rows if r["year"] == 2011)
    assert r2011["fwci_mean"] is None


def test_post_from_event_arrival_year(tmp_path, zenou_inputs, u6_config):
    _run(tmp_path, zenou_inputs, u6_config)
    rows = {r["year"]: r for r in _frame_rows(tmp_path, "p01")
            if r["incumbent_person_id"] == "P_I1"}
    assert rows[2016]["post"] is True and rows[2017]["post"] is True
    assert rows[2015]["post"] is False, "post = year >= arrival_year, no timing is invented"


# --- T11: dose.frozen_at_year must == events.t_minus_1 -------------------------
@pytest.mark.depends_on_u345
def test_frozen_at_year_equals_t_minus_1(tmp_path, zenou_inputs, u6_config):
    zenou_inputs.dose["p01"][0]["frozen_at_year"] = 2013     # ≠ t−1 (2015)
    with pytest.raises(asm.FrameAssemblyError, match="frozen_at|t_minus_1"):
        _run(tmp_path, zenou_inputs, u6_config)


# --- T12/T14: OUTPUT left-join on (incumbent,year); pub_count taken directly under the same name ---------
def test_output_join_key_is_incumbent_year_no_failfast(tmp_path, zenou_inputs,
                                                       u6_config):
    _run(tmp_path, zenou_inputs, u6_config)
    rows = {r["year"]: r for r in _frame_rows(tmp_path, "p01")
            if r["incumbent_person_id"] == "P_I1"}
    assert rows[2013]["fwci_frac"] == pytest.approx(1.0), "years with output take the OUTPUT value directly"
    assert rows[2013]["pub_count"] == pytest.approx(1.0), \
        "pub_count takes the OUTPUT column of the same name directly (after the rename there is no bridge and no raise)"
    src = inspect.getsource(asm)
    assert "pub_frac" not in src, "the old name pub_frac is retired (renamed to pub_count)"


# --- T13/D1: ex_star takes the star-excluded version for the p-level; both files are produced normally -------------------
def test_ex_star_two_file_no_failfast(tmp_path, zenou_inputs, u6_config):
    _run(tmp_path, zenou_inputs, u6_config)
    r01 = {r["year"]: r for r in _frame_rows(tmp_path, "p01")
           if r["incumbent_person_id"] == "P_I3"}
    assert not r01, "I3 is only in the p05 dose -> the p01 frame must not have its rows"
    r05 = {r["year"]: r for r in _frame_rows(tmp_path, "p05")
           if r["incumbent_person_id"] == "P_I3"}
    assert r05[2019]["fwci_frac_ex_star"] == pytest.approx(0.7), \
        "the p05 file takes the star-excluded version of output_star5pct"


# --- T23: PK unique + the OUTPUT join does not fan out ----------------------------------------
def test_analysis_frame_pk_unique_no_fanout(tmp_path, zenou_inputs, u6_config):
    _run(tmp_path, zenou_inputs, u6_config)
    for lev in ("p01", "p05"):
        rows = _frame_rows(tmp_path, lev)
        pks = [(r["incumbent_person_id"], r["year"], r["star_person_id"],
                r["event_id"]) for r in rows]
        assert len(pks) == len(set(pks)), f"{lev}: frame PK must be unique"
        n_triples = len({(p[0], p[2], p[3]) for p in pks})
        assert len(rows) == n_triples * 11, \
            "row count = triples × 11 years (OUTPUT per-(i,year) does not fan out)"


# --- Star flag guard: the dose event star must carry the matching p flag (C2 projection consistency) --------------------
def test_dose_star_flag_must_match_p_level(tmp_path, zenou_inputs, u6_config, mk):
    zenou_inputs.dose["p01"].append(
        mk.dose("P_I1", "P_S5", "AS5:2019", frozen_at_year=2018))
    with pytest.raises(asm.FrameAssemblyError, match="is_star_1pct"):
        _run(tmp_path, zenou_inputs, u6_config)


# --- Incumbent first-publication-year fallback switches from the bare min to the shared robust debut year -------------

def test_first_pub_fallback_robust_drops_polluted_fragment():
    """Must be red: a person missing from the panel takes the U1 work_first_pub fallback; fragment min {1965 (lone contaminated), 2000}
    -> robust drops 1965 (gap 35 > the configured 10) -> 2000; the bare min no longer pulls academic age earlier."""
    fp = asm.first_pub_of_persons(
        [],                                                   # The panel lacks this person
        [{"author_id": "A1", "person_id": "P"},
         {"author_id": "A2", "person_id": "P"}],
        {"A1": 1965, "A2": 2000},
        max_leading_gap=10)
    assert fp["P"] == 2000


def test_first_pub_fallback_robust_keeps_continuous_fragments():
    """Yves Zenou-type negative guard: fragment min {1995, 2000} is contiguous (gap 5 <= 10) -> the earliest year 1995 is kept."""
    fp = asm.first_pub_of_persons(
        [],
        [{"author_id": "A1", "person_id": "P"},
         {"author_id": "A2", "person_id": "P"}],
        {"A1": 1995, "A2": 2000},
        max_leading_gap=10)
    assert fp["P"] == 1995


def test_first_pub_panel_primary_unchanged():
    """Panel has a value -> taken directly (U3 already produced the robust value; U6 neither recomputes nor cleans a second time); the fallback only covers missing persons."""
    fp = asm.first_pub_of_persons(
        [{"person_id": "P", "first_pub_year": 1991},
         {"person_id": "P", "first_pub_year": 1991}],
        [{"author_id": "A1", "person_id": "P"}],
        {"A1": 1965},
        max_leading_gap=10)
    assert fp["P"] == 1991


# --- Fix #4: zero-coupling events dropping out of the frame are made transparent ----
# An event with a star but no incumbent coupling drops out of the analysis frame entirely (row source = dose triples, by mechanism,
# not a bug), but until now nothing counted it, so the real processing size of 4/16 was masked by the nominal 5/20.
# Fix: coverage_groups.json explicitly reports "nominal event count vs in-frame event count + dropped list".
def test_event_coverage_nominal_vs_in_frame_counted(tmp_path, zenou_inputs,
                                                    u6_config, mk):
    """Add one zero-coupling event (AS6:2020, 1%+5% star, no dose row) -> the count and the dropped list must
    appear in coverage_groups.json (nominal != in-frame, never silent)."""
    import json as _json

    zenou_inputs.star_set.append(
        mk.star("AS6", name="No Coupling Star", dept="unsw_econ", arrival=2020,
                academic_age=10, is_star_1pct=True, is_star_5pct=True))
    zenou_inputs.events.append(
        mk.event("AS6:2020", "AS6", 2020, dept_id="I31746571"))
    _run(tmp_path, zenou_inputs, u6_config)
    cov = _json.loads((tmp_path / "u6" / "_reports" / "coverage_groups.json")
                      .read_text())
    # nominal = number of events in the events table whose star flag matches the p-level; in frame = number of events covered by dose triples
    assert cov["events_nominal"] == {"p01": 2, "p05": 3}
    assert cov["events_in_frame"] == {"p01": 1, "p05": 2}
    assert cov["events_dropped_zero_coupling"] == {
        "p01": ["AS6:2020"], "p05": ["AS6:2020"]}


def test_event_coverage_no_drop_all_zero(tmp_path, zenou_inputs, u6_config):
    """The baseline world has no zero-coupling event -> the dropped list is empty and nominal == in-frame (the counts are always present, not
    written only when something goes wrong)."""
    import json as _json

    _run(tmp_path, zenou_inputs, u6_config)
    cov = _json.loads((tmp_path / "u6" / "_reports" / "coverage_groups.json")
                      .read_text())
    assert cov["events_nominal"] == {"p01": 1, "p05": 2}
    assert cov["events_in_frame"] == {"p01": 1, "p05": 2}
    assert cov["events_dropped_zero_coupling"] == {"p01": [], "p05": []}
