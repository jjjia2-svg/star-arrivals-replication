"""Red test: preflight_env_check wired into the real u3 entry point build_panel (item #1 before expanding to more universities).

Origin: audit finding A11, fix suggestion "call before run_m1_full/run_u3/run_u4 starts";
ENVIRONMENT_GATE_FAIL=30 is the exit code of a failed gate.
The real u3 entry point is m3_panel.panel.build_panel (the run_u3.py CLI is a stub still to be wired in U6;
production driver runners call build_panel directly).

Pinned behaviour: build_panel passes the environment gate as its first step; if it fails -> SystemExit(30) and nothing is written to disk
(except the gate's own audit record preflight_result.json, which U0 preflight always writes in both cases).
"""
from __future__ import annotations

import json

import pytest

pa = pytest.importorskip("pyarrow")

from identity.exit_codes import ENVIRONMENT_GATE_FAIL


def test_build_panel_env_gate_fail_exit30_nothing_else_written(monkeypatch, tmp_path):
    """Health check fails (pyarrow pin drift) -> SystemExit(30); the upstream assertion, table reads and writes are not reached."""
    from common import preflight as PF
    from m3_panel import panel as P

    monkeypatch.setattr(PF, "PYARROW_LOCK", "999.999.999")
    data_root = tmp_path / "data"          # Deliberately empty: the gate runs before the upstream assertion, so this step must not be reached
    out_dir = tmp_path / "u3_out"
    with pytest.raises(SystemExit) as ei:
        P.build_panel(data_root, out_dir, econ_dept_ids=set(), registry_by_id={})
    assert ei.value.code == ENVIRONMENT_GATE_FAIL, "A failed environment gate must exit 30"

    written = sorted(p.relative_to(out_dir).as_posix()
                     for p in out_dir.rglob("*") if p.is_file())
    assert written == ["preflight_result.json"], (
        f"When the health check fails, only the gate's audit record may be written; actually written: {written}"
    )
    payload = json.loads((out_dir / "preflight_result.json").read_text("utf-8"))
    assert payload["passed"] is False
    assert payload["exit_code"] == ENVIRONMENT_GATE_FAIL


def test_build_panel_env_gate_runs_before_upstream_assert(tmp_path):
    """Green side: environment OK -> the gate passes and writes the passed=True audit record, and only then comes the upstream-presence assertion (exit 2)."""
    from m3_panel import panel as P

    data_root = tmp_path / "data"          # Empty upstream -> after the gate passes, exit(2) is expected (upstream missing)
    out_dir = tmp_path / "u3_out"
    with pytest.raises(SystemExit) as ei:
        P.build_panel(data_root, out_dir, econ_dept_ids=set(), registry_by_id={})
    assert ei.value.code == 2, "Only after the gate passes comes the upstream presence assertion (exit 2); the order must not be reversed"
    payload = json.loads((out_dir / "preflight_result.json").read_text("utf-8"))
    assert payload["gate"] == "environment"
    assert payload["passed"] is True
