"""Tests that preflight_env_check is wired into the u1 run_full production entry point.

Background:
  - The environment gate has four checks, but only the pure decision layer and a thin shell existed, with
    no call site in production (the parts were done but not wired). The fix is to call it before
    run_m1_full/run_u3/run_u4 start.
  - A failed gate exits with code ENVIRONMENT_GATE_FAIL=30.

Behaviour pinned:
  - Before a real run (execute=True) the environment gate must pass (pyarrow pinned version / OpenAlex
    key / redlines SHA / rapidfuzz); if it fails -> SystemExit(30) and no data is written
    (preflight_result.json is the gate's own audit record and, following the U0 preflight pattern, is
    always written in both cases; it does not count as a data product).
  - dry_run (execute=False) does not touch the environment gate (it reads no full data and writes nothing,
    so no check is needed).
Definition-neutral: pure engineering wiring, no identification choices.
"""
from __future__ import annotations

import json

import pytest

pa = pytest.importorskip("pyarrow")

from identity.exit_codes import ENVIRONMENT_GATE_FAIL
from identity.golden import MONASH_CANONICAL_ID

_REGISTRY = [{"openalex_id": MONASH_CANONICAL_ID, "type": "education"}]
_ECON_DEPT_IDS = {MONASH_CANONICAL_ID}
_REAL_CREDS = dict(source_snapshot_merkle="MERKLE_T", config_sha="CFG_T",
                   rule_version="rv_t", code_version="cv_t")


def _make_snapshot(tmp_path, n_shards=1):
    snap = tmp_path / "snap"
    shard_dir = snap / "works" / "updated_date=2016-01-01"
    shard_dir.mkdir(parents=True)
    for i in range(n_shards):
        (shard_dir / f"part_{i:03d}.gz").write_bytes(b"")
    return snap


def test_run_full_execute_env_gate_fail_exit30_no_data_written(monkeypatch, tmp_path):
    """Main case: the check fails (pyarrow pinned version drifted) -> SystemExit(30) and no data is written."""
    from common import preflight as PF
    from m1_ingest import run_m1_full as F

    # Force a real environment-gate failure: set the pinned version to a value that cannot match -> env_gate_pyarrow_version must fail.
    monkeypatch.setattr(PF, "PYARROW_LOCK", "999.999.999")
    snap = _make_snapshot(tmp_path)
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as ei:
        F.run_full(snap, out, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
                   execute=True, **_REAL_CREDS)
    assert ei.value.code == ENVIRONMENT_GATE_FAIL, "A failed environment gate must exit 30"

    # No data written: under out_root nothing may exist except the gate's audit record preflight_result.json.
    written = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    assert written == ["_manifest/preflight_result.json"], (
        f"When the health check fails, only the gate's audit record may be written; actually written: {written}"
    )
    payload = json.loads((out / "_manifest" / "preflight_result.json").read_text("utf-8"))
    assert payload["passed"] is False
    assert payload["exit_code"] == ENVIRONMENT_GATE_FAIL


def test_run_full_execute_env_gate_pass_writes_audit_then_runs(monkeypatch, tmp_path):
    """Pass side: the check passes -> preflight_result.json is written (passed=True) and the run continues into run_m1_streaming."""
    from m1_ingest import run_m1_full as F

    captured = {}

    def _spy(_seed, _passc, **kw):
        captured.update(kw)
        return {}

    monkeypatch.setattr(F, "run_m1_streaming", _spy)
    snap = _make_snapshot(tmp_path)
    out = tmp_path / "out"
    res = F.run_full(snap, out, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
                     execute=True, **_REAL_CREDS)
    assert res["executed"] is True
    assert captured, "A passing health check must go on to call run_m1_streaming"
    payload = json.loads((out / "_manifest" / "preflight_result.json").read_text("utf-8"))
    assert payload["gate"] == "environment"
    assert payload["passed"] is True


def test_run_full_dry_run_skips_env_gate(monkeypatch, tmp_path):
    """dry_run does not touch the environment gate (it only produces the plan and writes nothing); the plan is still produced even if the environment is broken."""
    from common import preflight as PF
    from m1_ingest import run_m1_full as F

    monkeypatch.setattr(PF, "PYARROW_LOCK", "999.999.999")   # broken environment
    snap = _make_snapshot(tmp_path, n_shards=2)
    out = tmp_path / "out"
    plan = F.run_full(snap, out, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
                      execute=False)
    assert plan["executed"] is False
    assert plan["work_shard_count"] == 2
    assert not out.exists(), "dry_run does not create out_root (including preflight_result.json)"
