"""Red tests for the U2 real-data scale smoke gate (thin preflight-gate pattern).

Background:
  - Need: U2 gets a "real-data scale smoke" gate.
  - Evidence: the old build_manual_required_queue did a quadratic full scan (each row x 14 million edges x 2;
    on real data it was under 1% done after 3.4 h) - the third case of "fixtures cannot catch it, real data exposes it";
    rule: before any new code runs on real data, do a small real-data trial first.
  - Form: follow the existing preflight pattern with a thin gate = a pure decision (dependency injection, easy to test)
    + a thin shell (read the real on-disk size -> decide -> atomically write the result json -> nonzero exit code HALT).

Behavior:
  - Pure decision scale_gate_decision: observed size vs the expected range declared by the operator (bounds are injected by the caller,
    the code hard-codes no thresholds - same injection pattern as disk_gate_decision); empty bounds = a fake gate, rejected.
  - Thin shell preflight_u2_scale_check: read the row count from the U1 input table's parquet metadata (footer, no full scan)
    -> decide -> atomically write preflight_scale_result.json -> exit 0 on pass / SCALE_GATE_FAIL (=31) on fail.
  - run_resolve wiring: when scale_bounds is passed -> the gate runs BEFORE the full U1 tables are read; on fail -> SystemExit(31)
    and person_map is not written at all. When not passed (fixture/TDD) -> behavior unchanged.
Neutral on definitions: an engineering scale sanity check; no identification choices.
"""
from __future__ import annotations

import json

import pytest

pa = pytest.importorskip("pyarrow")

from identity.exit_codes import SCALE_GATE_FAIL


# ---------------------------------------------------------------------------
# Pure decision (dependency injection, no disk access)
# ---------------------------------------------------------------------------
def test_decision_within_bounds_passes():
    from m2_resolve.scale_gate import scale_gate_decision

    d = scale_gate_decision(
        observed={"authors": 162_623, "authorship_edges": 14_000_000},
        bounds={"authors": (100_000, 2_000_000), "authorship_edges": (1, 200_000_000)},
    )
    assert d["passed"] is True
    assert d["fails"] == []


def test_decision_out_of_band_fails_with_named_key():
    from m2_resolve.scale_gate import scale_gate_decision

    d = scale_gate_decision(
        observed={"authors": 3, "authorship_edges": 14_000_000},
        bounds={"authors": (100_000, 2_000_000), "authorship_edges": (1, 200_000_000)},
    )
    assert d["passed"] is False
    assert any("authors" in f for f in d["fails"]), "A failing key must be named (diagnosable)"


def test_decision_missing_observed_key_fails():
    """Declared in bounds but no observed value can be read from disk -> fail (a missing table / missing reading must never silently pass)."""
    from m2_resolve.scale_gate import scale_gate_decision

    d = scale_gate_decision(observed={}, bounds={"authors": (1, 10)})
    assert d["passed"] is False


def test_decision_empty_bounds_rejected():
    """Empty bounds = a fake gate that checks nothing -> ValueError (audit theme: false security is more dangerous than no guard)."""
    from m2_resolve.scale_gate import scale_gate_decision

    with pytest.raises(ValueError):
        scale_gate_decision(observed={"authors": 5}, bounds={})


# ---------------------------------------------------------------------------
# Thin shell: read real on-disk parquet metadata -> decide -> atomically write result + return code
# ---------------------------------------------------------------------------
def _mini_u1(tmp_path, n_authors=6):
    from common.schema import AUTHORS, CANONICAL_ID_MAP
    from m1_ingest._writer_util import write_rows_parquet

    edges = tmp_path / "derived" / "u1_edges"
    authors = [{"author_id": f"A{i}", "display_name": f"N{i}", "orcid": None}
               for i in range(n_authors)]
    write_rows_parquet(authors, edges / "authors" / "data.parquet",
                       schema=AUTHORS, pk_cols=["author_id"], label="authors")
    cmap = [{"raw_id": "Z_OLD", "canonical_id": "Z_NEW", "id_type": "author",
             "is_deleted": False}]
    write_rows_parquet(cmap, edges / "canonical_id_map" / "data.parquet",
                       schema=CANONICAL_ID_MAP, pk_cols=["raw_id"], label="canonical_id_map")
    return tmp_path


def test_shell_pass_writes_result_and_returns_zero(tmp_path):
    from m2_resolve.scale_gate import preflight_u2_scale_check

    root = _mini_u1(tmp_path)
    result_path = tmp_path / "preflight_scale_result.json"
    rc = preflight_u2_scale_check(
        root, bounds={"authors": (1, 100)}, result_path=result_path,
    )
    assert rc == 0
    payload = json.loads(result_path.read_text("utf-8"))
    assert payload["gate"] == "u2_scale"
    assert payload["passed"] is True
    assert payload["observed"]["authors"] == 6, "Observed values must come from real parquet metadata reads"


def test_shell_fail_writes_result_and_returns_scale_code(tmp_path):
    from m2_resolve.scale_gate import preflight_u2_scale_check

    root = _mini_u1(tmp_path)
    result_path = tmp_path / "preflight_scale_result.json"
    rc = preflight_u2_scale_check(
        root, bounds={"authors": (100_000, 2_000_000)},   # 6 rows << lower bound -> fail
        result_path=result_path,
    )
    assert rc == SCALE_GATE_FAIL
    payload = json.loads(result_path.read_text("utf-8"))
    assert payload["passed"] is False
    assert payload["exit_code"] == SCALE_GATE_FAIL


# ---------------------------------------------------------------------------
# run_resolve wiring: the gate runs before the full read; on fail -> exit 31 + person_map is not written at all
# ---------------------------------------------------------------------------
def test_run_resolve_scale_bounds_violation_halts_before_output(tmp_path):
    from m2_resolve.resolve import run_resolve

    root = _mini_u1(tmp_path)
    out_dir = tmp_path / "derived" / "u2_resolve"
    with pytest.raises(SystemExit) as ei:
        run_resolve(root, out_dir, scale_bounds={"authors": (100_000, 2_000_000)})
    assert ei.value.code == SCALE_GATE_FAIL
    assert not (out_dir / "person_map" / "data.parquet").exists(), (
        "Scale gate fails → person_map is not written at all"
    )
    assert (out_dir / "preflight_scale_result.json").exists(), "The gate's own audit record must be written (preflight pattern)"


def test_run_resolve_scale_bounds_ok_proceeds(tmp_path):
    from m2_resolve.resolve import run_resolve

    root = _mini_u1(tmp_path)
    out_dir = tmp_path / "derived" / "u2_resolve"
    run_resolve(root, out_dir, scale_bounds={"authors": (1, 100)})
    assert (out_dir / "person_map" / "data.parquet").exists()
    payload = json.loads((out_dir / "preflight_scale_result.json").read_text("utf-8"))
    assert payload["passed"] is True


def test_run_resolve_without_bounds_unchanged(tmp_path):
    """scale_bounds not passed (existing fixture/TDD path) -> behavior unchanged, no result file produced."""
    from m2_resolve.resolve import run_resolve

    root = _mini_u1(tmp_path)
    out_dir = tmp_path / "derived" / "u2_resolve"
    run_resolve(root, out_dir)
    assert (out_dir / "person_map" / "data.parquet").exists()
    assert not (out_dir / "preflight_scale_result.json").exists()
