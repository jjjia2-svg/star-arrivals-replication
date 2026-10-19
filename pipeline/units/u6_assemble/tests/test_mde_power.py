"""m7d power/MDE + g_treated + run_manifest tests (written test-first).

Covers: T44 (fixed power values + tampering still raises) / T45 (sole-producer PK) /
T46 (no re-join in the m7d source) / T47 (generation strata do not collapse to a binary, frozen at the
arrival year, not time-varying with calendar year) /
T48 (named contrasts) / T49 (bool-column projection, does not read a hallucinated events_p file) /
T50 (report CIs, do not chase significance stars) / T51 (G_treated dedup key = events.dept_id) /
T52 (counted from the data, nothing hardcoded) / T53 (seal provenance-quad check) /
T54 (config_sha order invariance) / T55 (PK sha keys for both frames) /
T56 (expected_source_types 3-value vocabulary) / T57 (same input -> byte-identical) /
T58 (run_power does not HALT).
"""
from __future__ import annotations

import inspect
import json

import pytest

from m7d_power import g_treated as gt
from m7d_power import mde
from m7d_power import run_manifest as rm


# --- T44/D6/#17 ---------------------------------------------------------------
def test_compute_mde_uses_signed_power_params(monkeypatch):
    params = mde.signed_power_params()
    assert params["target_power"] == 0.80
    assert params["alpha"] == 0.05
    assert params["cluster_unit"] == "department"
    assert params["icc"] == "self_estimated"
    assert set(params["inference_triple"]) == {
        "wild_cluster_bootstrap", "randomization_inference", "ferman_pinto"}
    # Tamper with RED["power"] (set it to empty) -> still raises (the anti-bypass guard is kept)
    from common import _redlines

    monkeypatch.setitem(_redlines.RED, "power", None)
    with pytest.raises(Exception):
        mde.signed_power_params()


# --- T47: generation strata (same / cross generation), not collapsed to a binary, no group column, not time-varying ---
def test_count_design_cells_by_generation_frozen_not_binary():
    from common._redlines import RED

    assert RED["generation"]["gen_pk_includes_year"] is False, \
        "#7: the generation key is frozen at the arrival year, never time-varying with the panel year"
    rows = [
        {"incumbent_person_id": "P_A", "year": y, "star_person_id": "P_S",
         "event_id": "E1", "treated": True, "post": y >= 2016,
         "age_gap": -3.0, "fwci_frac": 1.0} for y in (2015, 2016)
    ] + [
        {"incumbent_person_id": "P_B", "year": y, "star_person_id": "P_S",
         "event_id": "E1", "treated": True, "post": y >= 2016,
         "age_gap": -9.0, "fwci_frac": 2.0} for y in (2015, 2016)
    ]
    strata = mde.generation_strata(rows, same_gen_max_gap=5)
    assert {r["incumbent_person_id"] for r in strata["same_gen"]} == {"P_A"}, \
        "|age_gap|≤5 = 同代 (#15)"
    assert {r["incumbent_person_id"] for r in strata["cross_gen"]} == {"P_B"}
    src = inspect.getsource(mde)
    assert '["group"]' not in src, "G1: strata use age_gap+treated, not the deleted group column"


def test_mde_reports_specific_contrasts(zenou_inputs, tmp_path, u6_config):
    """T48: the output contains the named contrasts "same vs cross generation" and "treated vs not-yet-treated"."""
    from m7b_assemble import assemble as asm
    import pyarrow.parquet as pq

    asm.assemble_frames(zenou_inputs, out_root=tmp_path / "u6", config=u6_config)
    rows = pq.read_table(tmp_path / "u6" / "frame" / "_frozen"
                         / "analysis_frame_p01.parquet").to_pylist()
    dept_of_event = {e["event_id"]: e["dept_id"] for e in zenou_inputs.events}
    rep, txt = mde.compute_mde_report(rows, dept_of_event, p_label="1pct")
    assert "same_gen_vs_cross_gen" in rep["contrasts"]
    assert "treated_pre_vs_post" in rep["contrasts"]
    assert "同代" in txt and "跨代" in txt


def test_report_states_no_stars(zenou_inputs, tmp_path, u6_config):
    """T50: the mde txt contains "report CIs, do not chase significance stars" + every assumption is auditable (power/alpha/cluster)."""
    from m7b_assemble import assemble as asm
    import pyarrow.parquet as pq

    asm.assemble_frames(zenou_inputs, out_root=tmp_path / "u6", config=u6_config)
    rows = pq.read_table(tmp_path / "u6" / "frame" / "_frozen"
                         / "analysis_frame_p01.parquet").to_pylist()
    _, txt = mde.compute_mde_report(rows, {"AZ1:2016": "I56590836",
                                           "AS5:2019": "I31746571"},
                                    p_label="1pct")
    assert "报 CI 不追星号" in txt
    assert "0.8" in txt and "0.05" in txt and "department" in txt
    assert "wild_cluster_bootstrap" in txt


# --- T49: the two percentile projections come from the STAR_SET bool columns, not from a hallucinated per-percentile p file ---
def test_two_pctiles_projected_from_star_set_bool_cols():
    for mod in (gt, mde):
        src = inspect.getsource(mod)
        assert "events_p0" not in src, "must not read the nonexistent file names events_p0.01/p0.05"
    src = inspect.getsource(gt)
    assert "is_star_1pct" in src and "is_star_5pct" in src


# --- T51/T52: G_treated -------------------------------------------------------
def test_count_g_treated_dedup_by_dept_id(mk):
    events = [mk.event("A1:2016", "A1", 2016, dept_id="I_M"),
              mk.event("A2:2018", "A2", 2018, dept_id="I_M"),
              mk.event("A3:2019", "A3", 2019, dept_id="I_U")]
    stars = [mk.star("A1", is_star_1pct=True, is_star_5pct=True),
             mk.star("A2", is_star_1pct=False, is_star_5pct=True),
             mk.star("A3", is_star_1pct=False, is_star_5pct=True)]
    g = gt.count_g_treated(events, stars)
    assert g == {"p01": 1, "p05": 2}, \
        "dedup key = events.dept_id (count departments, not person-instances); split p by the bool column"


def test_g_treated_from_data_not_preset(mk):
    events = [mk.event("A1:2016", "A1", 2016, dept_id="I_M")]
    stars = [mk.star("A1", is_star_1pct=True, is_star_5pct=True)]
    assert gt.count_g_treated(events, stars) == {"p01": 1, "p05": 1}
    events.append(mk.event("A9:2019", "A9", 2019, dept_id="I_NEW"))
    stars.append(mk.star("A9", is_star_1pct=True, is_star_5pct=True))
    assert gt.count_g_treated(events, stars) == {"p01": 2, "p05": 2}, \
        "change the fixture -> G_treated changes with it (counted, not hardcoded)"


# --- T53-T57: run_manifest sealing -----------------------------------------------
def _mk_manifest_kw(tmp_path):
    return dict(
        deterministic={
            "source_snapshot_merkle": "snap:aaa", "config_sha": "c",
            "rule_version": "rv", "stars_set_hash": "s",
            "env_lock_sha": "e", "stage_shas": {"m7b": "x"},
            "analysis_frame_p01_pk_sha256": "p1", "analysis_frame_p05_pk_sha256": "p5",
            "G_treated_1pct": 1, "G_treated_5pct": 2,
            "golden_structural_pass": True,
            "provenance_quad": {"u4": {"config_sha": "c4"},
                                "u5": {"config_sha": "c5"}},
        },
        tolerance={
            "mde_1pct": "see _reports/mde_1pct.txt", "mde_5pct": "…",
            "golden_works_count_observed": 583,
            "golden_arrival_year_observed": 2016,
            "golden_observed_in_range": True, "golden_anchored_release": None,
            "golden_topics_version": None, "boundary_sensitive_flip_count": 0,
            "na_rate_fwci_frac": {"p01": 0.5, "p05": 0.5},
            "lee_bounds_required": True,
        },
        reporting={"5a": "n", "5b": "snap", "5c": "MISSING — author follow-up",
                   "9": "env", "18": "ver"},
        expected_source_types={
            "analysis_frame_p01": "derived", "analysis_frame_p05": "derived",
            "star_set": "derived", "events": "derived", "dose_p01": "derived",
            "dose_p05": "derived", "output": "derived",
            "source_snapshot_merkle": "a-priori",
        },
    )


def test_run_manifest_records_both_frame_pk_sha(tmp_path):
    """T55."""
    p = tmp_path / "run_manifest.lock"
    rm.seal_run_manifest(p, **_mk_manifest_kw(tmp_path))
    doc = json.loads(p.read_text())
    det = doc["deterministic_artifacts"]
    assert det["analysis_frame_p01_pk_sha256"] == "p1"
    assert det["analysis_frame_p05_pk_sha256"] == "p5"
    assert doc["tolerance_artifacts"]["na_rate_fwci_frac"]["p01"] == 0.5
    assert doc["tolerance_artifacts"]["lee_bounds_required"] is True


def test_expected_source_types_complete_and_valid(tmp_path):
    """T56: every value is in the 3-value vocabulary; an illegal value raises; a missing mapping raises."""
    kw = _mk_manifest_kw(tmp_path)
    kw["expected_source_types"]["analysis_frame_p01"] = "guessed"
    with pytest.raises(ValueError, match="vocab"):
        rm.seal_run_manifest(tmp_path / "x.lock", **kw)
    kw2 = _mk_manifest_kw(tmp_path)
    del kw2["expected_source_types"]["analysis_frame_p01"]
    with pytest.raises(ValueError, match="missing"):
        rm.seal_run_manifest(tmp_path / "y.lock", **kw2)


def test_seal_byte_identical_same_inputs(tmp_path):
    """T57: sealing twice on the same input is byte-identical (no timestamp)."""
    p1, p2 = tmp_path / "a.lock", tmp_path / "b.lock"
    rm.seal_run_manifest(p1, **_mk_manifest_kw(tmp_path))
    rm.seal_run_manifest(p2, **_mk_manifest_kw(tmp_path))
    assert p1.read_bytes() == p2.read_bytes()


def test_config_sha_order_invariant(tmp_path):
    """T54: reordering the file list does not change config_sha; changing the contents does."""
    f1, f2 = tmp_path / "a.yaml", tmp_path / "b.yaml"
    f1.write_text("k: 1")
    f2.write_text("k: 2")
    s_ab = rm.config_sha_of([f1, f2])
    s_ba = rm.config_sha_of([f2, f1])
    assert s_ab == s_ba, "sort in dictionary order before feeding merkle; no glob, independent of the input order"
    f2.write_text("k: 3")
    assert rm.config_sha_of([f1, f2]) != s_ab


def test_verify_provenance_quad_halts_on_mismatch(tmp_path):
    """T53: seal provenance checker - artifact header != pins -> raises."""
    from common.manifest import ProvenanceMismatch

    quad = {"source_snapshot_merkle": "snap:aaa", "config_sha": "c",
            "rule_version": "rv", "stars_set_hash": "s"}
    rm.verify_provenance_quad({"events": dict(quad)}, {"events": dict(quad)})
    with pytest.raises(ProvenanceMismatch):
        rm.verify_provenance_quad(
            {"events": dict(quad, config_sha="x")}, {"events": dict(quad)})


# --- T45/T46/T58: run_power read-only properties -------------------------------
def test_load_frame_sole_producer_pk_match(tmp_path, zenou_inputs, u6_config):
    from m7b_assemble import assemble as asm
    from m7d_power import load_frame as lf

    asm.assemble_frames(zenou_inputs, out_root=tmp_path / "u6", config=u6_config)
    rows = lf.load_frame(tmp_path / "u6", "p01")
    assert rows, "loaded successfully"
    sc = tmp_path / "u6" / "frame" / "analysis_frame_p01._manifest.json"
    doc = json.loads(sc.read_text())
    doc["pk_sha256"] = "f" * 64
    sc.write_text(json.dumps(doc))
    with pytest.raises(lf.SoleProducerDrift):
        lf.load_frame(tmp_path / "u6", "p01")


def test_no_rejoin_in_power_source():
    """T46 property: the whole m7d module source has no M4-M6 join."""
    from m7d_power import load_frame, run_power

    for mod in (mde, gt, rm, load_frame, run_power):
        src = inspect.getsource(mod)
        for banned in ("m4_dose", "m5b_aggregate", "aggregate_via_u0",
                       "paper_contrib"):
            assert banned not in src, f"{mod.__name__} contains {banned}"


def test_run_power_never_halts(tmp_path, zenou_inputs, u6_config):
    """T58: a golden observation out of range -> run_power still runs, and the observed value is recorded in the tolerance bucket."""
    from m7b_assemble import assemble as asm
    from m7c_gates import run_gates as rgates
    from m7d_power import run_power as rp

    out_root = tmp_path / "u6"
    asm.assemble_frames(zenou_inputs, out_root=out_root, config=u6_config)
    gates_res = rgates.run_gates(out_root, zenou_inputs, config=u6_config)
    # Deliberately mark the golden observation as out of range -> run_power must still complete (no sys.exit / no raise)
    gates_res["golden"]["observed_in_range"] = False
    rep = rp.run_power(out_root, zenou_inputs, config=u6_config,
                       gates_result=gates_res)
    assert (out_root / "run_manifest.lock").is_file()
    doc = json.loads((out_root / "run_manifest.lock").read_text())
    assert doc["tolerance_artifacts"]["golden_observed_in_range"] is False
    assert (out_root / "_reports" / "mde_1pct.txt").is_file()
    assert (out_root / "_reports" / "mde_5pct.txt").is_file()
    assert rep["G_treated"]["p01"] >= 1
