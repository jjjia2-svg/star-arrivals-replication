"""End-point Zenou gold standard + full-chain smoke test - U6 is the end-point gate tier (final end-to-end check).

Covers: T59 (m7b material-complete smoke: recognised as a star / Monash not Sydney / arrival window / folded to one person) /
T60 (m7c: 12 fields, one by one) / T61 (frame has no works_count column, xfail strict) /
T62 (full-chain smoke m7b->m7c->m7d: the four ends have equal pk_sha, G_treated >= 1, MDE run on real values).
"""
from __future__ import annotations

import json

import pyarrow.parquet as pq
import pytest

from m7b_assemble import assemble as asm
from m7c_gates import golden_gate as gg
from m7c_gates import run_gates as rgates
from m7d_power import run_power as rp


@pytest.fixture
def built(tmp_path, zenou_inputs, u6_config):
    rep = asm.assemble_frames(zenou_inputs, out_root=tmp_path / "u6",
                              config=u6_config)
    return tmp_path / "u6", rep, zenou_inputs, u6_config


# --- T59: m7b material-complete smoke ------------------------------------------
@pytest.mark.depends_on_u345
def test_zenou_end_to_end_material_ready(built):
    out_root, rep, inputs, _ = built
    rows = pq.read_table(out_root / "frame" / "_frozen"
                         / "analysis_frame_p01.parquet").to_pylist()
    z_rows = [r for r in rows if r["star_person_id"] == "P_Z"]
    assert z_rows, "the Zenou event row must be in the frame (recognised as an is_star_1pct star)"
    ev = {e["event_id"]: e for e in inputs.events}["AZ1:2016"]
    assert ev["dept_id"] == "I56590836", "Monash, not Sydney"
    assert ev["arrival_year"] in (2015, 2016, 2017), "arrival 2016±1"
    years = sorted({r["year"] for r in z_rows})
    assert years == list(range(2011, 2022)), "event row window = 2011-2021 (arrival±5)"
    assert all(r["post"] == (r["year"] >= 2016) for r in z_rows)
    # Frozen at t-1: dose frozen_at is reconciled in assemble against events.t_minus_1
    # a namesake is not wrongly merged + 16 IDs fold to a single person
    pm_z = {r["author_id"] for r in inputs.person_map
            if r["person_id"] == "P_Z"}
    assert len(pm_z) >= 2, "Zenou's several author fragments fold into a single person via person_map"
    assert "ANAMESAKE" not in pm_z, "a different person with the same name must not be merged into the Zenou cluster"


# --- T60: m7c end-point structure gate, 12 fields one by one ----------------------
def test_zenou_golden_structural_12_fields(built):
    from identity.golden import classify_golden

    out_root, _, inputs, _ = built
    mat = gg.build_zenou_material(star_set=inputs.star_set,
                                  events=inputs.events,
                                  person_map=inputs.person_map,
                                  panel=inputs.panel)
    # one independent assertion per field (each failure points straight at the regression)
    assert mat["found"] is True                                   # ① found by search
    assert mat["resolved_single_person"] is True                  # ② folded to one person
    assert mat["is_star_at_p01"] is True                          # ③ recognised as a star
    assert mat["institution_canonical_observed"] == "I56590836"   # ④Monash
    assert mat["institution_canonical_observed"] != "I129604602"  # ⑤ not Sydney
    assert mat["cluster_pure_econ_network"] is True               # ⑥ namesake excluded
    assert mat["armi_folded_to_monash"] is True                   # ⑦ ARMI folded into Monash
    assert mat["caulfield_folded_to_none"] is True                # ⑧ no phantom
    assert mat["rejected_1998_backfill"] is True                  # ⑨ the 1998 backfill is rejected
    assert mat["arrival_year_observed"] != 1998                   # ⑩ not 1998
    assert 2015 <= mat["arrival_year_observed"] <= 2017           # ⑪ arrival 2016±1
    assert mat["read_affiliations_years"] is False                # ⑫ never trusts affil.years
    res = classify_golden(mat)
    assert res["structural_pass"] is True, f"flips={res['flips']}"
    assert res["observed_in_range"] is True


# --- T61: frame has no works_count column (xfail strict records the gap) ----------
@pytest.mark.xfail(reason="B-NEW-2: works_count has no producer; the classify_golden observed value"
                          "is summed year by year from the panel; the frame has no such column (to be settled after the B6-GOLDEN merge)",
                   strict=True)
def test_zenou_works_count_in_frame(built):
    out_root, _, _, _ = built
    rows = pq.read_table(out_root / "frame" / "_frozen"
                         / "analysis_frame_p01.parquet").to_pylist()
    assert "star_works_count" in rows[0]


# --- T62: full-chain smoke m7b->m7c->m7d ------------------------------------------
@pytest.mark.depends_on_u345
def test_full_pipeline_smoke_to_u6(built):
    out_root, rep, inputs, cfg = built
    gates_res = rgates.run_gates(out_root, inputs, config=cfg)
    assert gates_res["verdict"] != "HALT"
    power_rep = rp.run_power(out_root, inputs, config=cfg,
                             gates_result=gates_res)
    doc = json.loads((out_root / "run_manifest.lock").read_text())
    det = doc["deterministic_artifacts"]
    # four ends have equal pk_sha: m7b written to disk == sidecar == read by m7c == seal record
    for lev in ("p01", "p05"):
        sc = json.loads((out_root / "frame"
                         / f"analysis_frame_{lev}._manifest.json").read_text())
        assert det[f"analysis_frame_{lev}_pk_sha256"] == sc["pk_sha256"] \
            == rep["pk_sha256"][lev] == gates_res[lev]["pk_sha256"]
    assert det["G_treated_1pct"] >= 1, "counted from the single events⨝star_set join"
    assert det["golden_structural_pass"] is True
    # MDE run on real values (power 0.80/alpha 0.05, not placeholders)
    txt = (out_root / "_reports" / "mde_1pct.txt").read_text()
    assert "0.8" in txt and "0.05" in txt
    # reporting fields present (a missing item must be an explicit MISSING, never silently empty)
    assert set(doc["reporting"]) >= {"5a", "5b", "5c", "9", "18"}
    assert doc["expected_source_types"]["analysis_frame_p01"] == "derived"
