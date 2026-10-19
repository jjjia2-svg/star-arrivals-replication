"""m7c frame_gate red tests: HIGH-1 re-join drift / exact schema / PK coverage / property.

Coverage: T30 (rejoin drift HALT) / T31 (extra group/degree column raises) /
T32 (two-way PK coverage) / T33 (source has no M4-M6 re-join) / T34 (p01/p05 consistency) +
(f) derived-class monotonicity fwci_frac_ex_star <= fwci_frac.
"""
from __future__ import annotations

import inspect
import json

import pytest

from m7b_assemble import assemble as asm
from m7c_gates import frame_gate as fg


@pytest.fixture
def built(tmp_path, zenou_inputs, u6_config):
    rep = asm.assemble_frames(zenou_inputs, out_root=tmp_path / "u6",
                              config=u6_config)
    return tmp_path / "u6", rep, zenou_inputs


def test_frame_gate_passes_on_clean_build(built):
    out_root, rep, inputs = built
    res = fg.run_frame_gate(out_root, p_levels=("p01", "p05"))
    assert res["verdict"] == "PASS"
    assert res["p01"]["schema_exact"] is True
    assert res["p01"]["pk_coverage"] == "ok"


def test_rejoin_drift_halts(built):
    """T30/HIGH-1: sidecar and frozen artifact PK differ -> FrameRejoinDrift."""
    out_root, rep, _ = built
    sc_path = out_root / "frame" / "analysis_frame_p01._manifest.json"
    sc = json.loads(sc_path.read_text())
    sc["pk_sha256"] = "0" * 64
    sc_path.write_text(json.dumps(sc))
    with pytest.raises(fg.FrameRejoinDrift):
        fg.run_frame_gate(out_root, p_levels=("p01", "p05"))


def test_frame_schema_exact_rejects_group_and_degree(built):
    """T31: the frame has an extra group or degree column -> raise (assert_matches_schema requires exact equality)."""
    import pyarrow.parquet as pq
    import pyarrow as pa

    out_root, _, _ = built
    p = out_root / "frame" / "_frozen" / "analysis_frame_p01.parquet"
    t = pq.read_table(p)
    t2 = t.append_column("group", pa.array(["A"] * t.num_rows))
    pq.write_table(t2, p)
    with pytest.raises(Exception, match="group|schema|SchemaMismatch"):
        fg.run_frame_gate(out_root, p_levels=("p01",), sidecar_check=False)


def test_pk_coverage_no_orphan_no_missing(built):
    """T32: frame PK set == the expected PK set derived from groups x window (orphans and missing rows are both caught)."""
    import pyarrow.parquet as pq

    out_root, _, _ = built
    p = out_root / "frame" / "_frozen" / "analysis_frame_p01.parquet"
    t = pq.read_table(p)
    pq.write_table(t.slice(0, t.num_rows - 1), p)   # Delete one row -> missing row
    # The sidecar would blow up first (rejoin drift); turn off the sidecar check to test the coverage arm in isolation
    with pytest.raises(fg.FramePKCoverageError):
        fg.run_frame_gate(out_root, p_levels=("p01",), sidecar_check=False)


def test_no_m4m6_rejoin_in_source():
    """T33 property: the frame_gate source has no M4-M6 join pattern."""
    src = inspect.getsource(fg)
    for banned in ("m4_dose", "m5b_aggregate", "aggregate_via_u0"):
        assert banned not in src


def test_gframe_checks_both_p01_p05_consistency(built):
    """T34/D1: run the full suite on each of p01/p05 + the two files have byte-identical schema."""
    out_root, _, _ = built
    res = fg.run_frame_gate(out_root, p_levels=("p01", "p05"))
    assert res["two_files_schema_identical"] is True
    assert set(res) >= {"p01", "p05"}


def test_ex_star_monotone_le_full(built):
    """(f) derived-class monotonicity: fwci_frac_ex_star <= fwci_frac (rows where both are non-null)."""
    out_root, _, _ = built
    res = fg.run_frame_gate(out_root, p_levels=("p01", "p05"))
    assert res["p01"]["ex_star_monotone"] == "ok"


def test_redline_cols_present(built):
    """(c) red-line columns present: dose_coupling/treated/post/age_gap."""
    out_root, _, _ = built
    res = fg.run_frame_gate(out_root, p_levels=("p01",))
    assert res["p01"]["redline_cols_present"] is True
