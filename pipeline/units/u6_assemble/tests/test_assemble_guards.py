"""assemble guard red tests: HIGH-1 carry without recomputation / determinism / sidecar / tally / provenance.

Coverage: T21 (carry only, no recomputation) / T22 (import-graph guard) / T24+T20 (GROUPS_ABC
membership table, 6 columns) / T25 (atomic + idempotent + byte-level across two runs) / T26 (sidecar pk_sha256 x2) /
T27 (provenance header) / T29 (tally strict six keys) / T17b governance (pop-min violations are not silently dropped,
they are counted for manual review; see the conflict point in the assemble docstring).
"""
from __future__ import annotations

import inspect
import json

import pyarrow.parquet as pq
import pytest

from common.schema import GROUPS_ABC, TALLY, assert_matches_schema
from m7b_assemble import assemble as asm
from m7b_assemble import groups_io


def _run(tmp_path, inputs, config, sub="u6"):
    return asm.assemble_frames(inputs, out_root=tmp_path / sub, config=config)


# --- T21/HIGH-1: frame columns == frozen inputs row by row (carried, not recomputed) -----------------------------
def test_assemble_only_relabels_never_recomputes(tmp_path, zenou_inputs,
                                                 u6_config):
    _run(tmp_path, zenou_inputs, u6_config)
    rows = pq.read_table(tmp_path / "u6" / "frame" / "_frozen"
                         / "analysis_frame_p01.parquet").to_pylist()
    dose_by_triple = {(d["incumbent_person_id"], d["star_person_id"],
                       d["event_id"]): d for d in zenou_inputs.dose["p01"]}
    out_by_iy = {(o["incumbent_person_id"], o["year"]): o
                 for o in zenou_inputs.output["p01"]}
    for r in rows:
        d = dose_by_triple[(r["incumbent_person_id"], r["star_person_id"],
                            r["event_id"])]
        assert r["dose_coupling"] == pytest.approx(d["coupling_share"])
        o = out_by_iy.get((r["incumbent_person_id"], r["year"]))
        if o is not None:
            assert r["fwci_frac"] == pytest.approx(o["fwci_frac"])


def test_assemble_module_does_not_import_upstream_compute():
    """T22/HIGH-1: does not import compute entry points such as m4_dose/m5b_aggregate/identity.dose."""
    src = inspect.getsource(asm)
    for banned in ("m4_dose", "m5b_aggregate", "m5_output", "identity.dose",
                   "aggregate_via_u0", "run_dose"):
        assert banned not in src, f"assemble source contains upstream compute symbol {banned!r}"


# --- T24/T20: GROUPS_ABC = incumbent membership table (6 columns, no group; C rows carry control fields) ---------
def test_groups_abc_is_membership_table_no_group_col(tmp_path, zenou_inputs,
                                                     u6_config):
    _run(tmp_path, zenou_inputs, u6_config)
    for lev in ("p01", "p05"):
        rows = pq.read_table(tmp_path / "u6" / "frame" / "_frozen"
                             / f"groups_ABC_{lev}.parquet").to_pylist()
        assert rows, "treated member rows must be present"
        for r in rows:
            assert_matches_schema(r.keys(), GROUPS_ABC, label="groups")
            assert "group" not in r
            if not r["treated"]:
                assert r["control_star_person_id"] is not None
                assert r["matched_treated_event_id"] is not None
            else:
                assert r["control_star_person_id"] is None
                assert r["matched_treated_event_id"] is None


def test_groups_c_row_contradiction_raises(mk):
    """C -> treated=False contradiction raises (T24 consistency)."""
    c_row = {"incumbent_person_id": "P_C", "star_person_id": "P_CTRL",
             "event_id": "E1", "treated": True,
             "control_star_person_id": "P_CTRL",
             "matched_treated_event_id": "E1"}
    with pytest.raises(groups_io.GroupsConsistencyError):
        groups_io.build_groups_membership([], [c_row])


# --- T25: atomic + idempotent, byte-identical across two runs -------------------------------------------
def test_two_run_byte_identical(tmp_path, zenou_world, u6_config):
    from conftest import make_inputs

    r1 = _run(tmp_path, make_inputs(zenou_world), u6_config, sub="run_a")
    r2 = _run(tmp_path, make_inputs(zenou_world), u6_config, sub="run_b")
    for lev in ("p01", "p05"):
        a = (tmp_path / "run_a" / "frame" / "_frozen"
             / f"analysis_frame_{lev}.parquet").read_bytes()
        b = (tmp_path / "run_b" / "frame" / "_frozen"
             / f"analysis_frame_{lev}.parquet").read_bytes()
        assert a == b, f"{lev}: two runs on the same input must be byte-identical (determinism)"
        assert r1["pk_sha256"][lev] == r2["pk_sha256"][lev]


# --- T26: sidecar _manifest.json (row_count + pk_sha256) ×2 -------------------
def test_analysis_frame_sidecar_pk_sha(tmp_path, zenou_inputs, u6_config):
    rep = _run(tmp_path, zenou_inputs, u6_config)
    for lev in ("p01", "p05"):
        sc = json.loads((tmp_path / "u6" / "frame"
                         / f"analysis_frame_{lev}._manifest.json").read_text())
        assert set(sc) == {"row_count", "pk_sha256"}
        assert sc["row_count"] > 0
        assert sc["pk_sha256"] == rep["pk_sha256"][lev]


# --- T27: the frame header provenance 4-tuple is present (for M7c HIGH-7) ---------------------------
def test_analysis_frame_carries_provenance(tmp_path, zenou_inputs, u6_config):
    _run(tmp_path, zenou_inputs, u6_config)
    hdr = json.loads((tmp_path / "u6" / "frame" / "_frozen"
                      / "manifest_header.json").read_text())
    for k in ("source_snapshot_merkle", "config_sha", "rule_version",
              "stars_set_hash"):
        assert hdr.get(k), f"provenance key {k} missing/empty"


# --- T29: tally strict six keys (op_id arm honestly N/A); diagnostics go to a sidecar, not the TALLY ----------
def test_tally_strict_six_keys(tmp_path, zenou_inputs, u6_config):
    _run(tmp_path, zenou_inputs, u6_config)
    for lev in ("p01", "p05"):
        t = json.loads((tmp_path / "u6" / "_ledger" / f"u6_frame_{lev}"
                        / "tally.json").read_text())
        assert_matches_schema(t.keys(), TALLY, label="u6_tally")
        assert t["balanced"] is True
        assert t["expected"] == t["kept"] + t["failed"] + t["skipped"]
        assert t["op_id_arm"] == "N/A", "a derived join has no scraping arm, honestly marked N/A"
        assert "na_rate" not in t, "diagnostic counts go to the sidecar, not mixed into TALLY"


# --- pop-min conflict-point governance: violating treated incumbents are not silently dropped, they are counted for manual review ---------------
def test_treated_pop_min_violation_counted_not_dropped(tmp_path, zenou_inputs,
                                                       u6_config):
    """D5 (population threshold filter) and T8/C3 (treated rows == dose triples) conflict on the shipped U5 pool
    (on disk, an employed person with 1 publication year entered dose). This implementation follows the HIGH-1 carry discipline and drops no row;
    the count goes to the coverage sidecar for a manual decision (see the conflict point in the returned report)."""
    _run(tmp_path, zenou_inputs, u6_config)
    cov = json.loads((tmp_path / "u6" / "_reports" / "coverage_groups.json")
                     .read_text())
    assert cov["n_treated_pop_min_violations"]["p01"] == 1, \
        "I4 has only 1 publication year -> record a violation count (not silently dropped)"
    assert "P_I4" in cov["treated_pop_min_violators"]["p01"]


def test_nt_pool_two_school_recorded_in_coverage(tmp_path, zenou_inputs,
                                                 u6_config):
    """nt-pool empty for both universities -> recorded in the coverage sidecar + a note that CEM is shelved."""
    _run(tmp_path, zenou_inputs, u6_config)
    cov = json.loads((tmp_path / "u6" / "_reports" / "coverage_groups.json")
                     .read_text())
    assert cov["nt_pool_empty"] is True
    assert cov["nt_pool_depts"] == []
    assert cov["cem_matching"] == "skipped_no_pool"
    assert cov["thin_arm_fallback"] == "report_not_yet_treated_only"
