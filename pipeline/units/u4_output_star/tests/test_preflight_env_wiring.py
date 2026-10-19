"""Pre-expansion checklist item 1, red test: preflight_env_check wired into the u4 shipping orchestrator run_u4_full.

Origin: the A11 review recommended "call it before run_m1_full/run_u3/run_u4 start";
the failure exit code is ENVIRONMENT_GATE_FAIL=30, and the wiring is part of the pre-expansion checklist.

Pinned behaviour: run_u4_full passes the environment gate first (before the input-table preflight); fail → SystemExit(30)
and nothing written to disk (except the gate's own audit record _manifest/preflight_result.json — the U0 preflight pattern always writes it).
"""
from __future__ import annotations

import json

import pytest

pa = pytest.importorskip("pyarrow")

from identity.exit_codes import ENVIRONMENT_GATE_FAIL


def test_run_u4_full_env_gate_fail_exit30_nothing_else_written(monkeypatch, tmp_path):
    """Health check fails (pyarrow pinned-version drift) → SystemExit(30); the input preflight / adjudication loading does not run at all."""
    from common import preflight as PF
    import run_u4 as R

    monkeypatch.setattr(PF, "PYARROW_LOCK", "999.999.999")
    derived = tmp_path / "derived"      # deliberately empty — the gate comes before the input-table preflight
    out = tmp_path / "u4_out"
    with pytest.raises(SystemExit) as ei:
        R.run_u4_full(derived, out, frozen_dir=tmp_path / "frozen")
    assert ei.value.code == ENVIRONMENT_GATE_FAIL, "a failed environment gate must exit 30"

    written = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    assert written == ["_manifest/preflight_result.json"], (
        f"when the health check fails only the gate's audit record may be written, actually written: {written}"
    )
    payload = json.loads((out / "_manifest" / "preflight_result.json").read_text("utf-8"))
    assert payload["passed"] is False
    assert payload["exit_code"] == ENVIRONMENT_GATE_FAIL


def test_run_u4_full_env_gate_runs_before_input_preflight(tmp_path):
    """Green side: environment fine → the gate passes and writes passed=True, and only then does the input-table preflight run (missing table → ValueError)."""
    import run_u4 as R

    derived = tmp_path / "derived"      # empty → after the gate passes, expect ValueError (required input table absent)
    out = tmp_path / "u4_out"
    with pytest.raises(ValueError, match="required input tables missing"):
        R.run_u4_full(derived, out, frozen_dir=tmp_path / "frozen")
    payload = json.loads((out / "_manifest" / "preflight_result.json").read_text("utf-8"))
    assert payload["gate"] == "environment"
    assert payload["passed"] is True
