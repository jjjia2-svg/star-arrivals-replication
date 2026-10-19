"""m7c run_gates orchestration tests: the safest verdict wins + NA propagates to HUMAN_REVIEW + the reports are written to disk.

Covers: T41 (NA > 20% -> global HUMAN_REVIEW, not overridden by PASS) /
T43 (any HALT -> global HALT; exit codes map to named exceptions).
"""
from __future__ import annotations

import json

import pytest

from m7b_assemble import assemble as asm
from m7c_gates import run_gates as rgates


@pytest.fixture
def built(tmp_path, zenou_inputs, u6_config):
    asm.assemble_frames(zenou_inputs, out_root=tmp_path / "u6", config=u6_config)
    return tmp_path / "u6", zenou_inputs, u6_config


def test_combine_verdicts_safest_wins():
    assert rgates.combine_verdicts(["PASS", "WARN"]) == "WARN"
    assert rgates.combine_verdicts(["PASS", "HUMAN_REVIEW", "WARN"]) \
        == "HUMAN_REVIEW"
    assert rgates.combine_verdicts(["HALT", "HUMAN_REVIEW"]) == "HALT"
    assert rgates.combine_verdicts(["PASS", "PASS"]) == "PASS"


def test_run_gates_writes_reports_and_verdict(built):
    out_root, inputs, cfg = built
    res = rgates.run_gates(out_root, inputs, config=cfg)
    reports = out_root / "_reports"
    for name in ("u6_gate_frame.json", "u6_gate_provenance.json",
                 "u6_gate_golden.json", "u6_gate_attrition.json",
                 "u6_gate_reconcile.json", "u6_gates_summary.json"):
        assert (reports / name).is_file(), f"missing report {name}"
    assert res["verdict"] in ("PASS", "WARN", "HUMAN_REVIEW")


def test_na_human_review_propagates_to_global_verdict(built):
    """T41: frame NA > 20% (the synthetic world really is > 20%) -> the global verdict is raised to HUMAN_REVIEW."""
    out_root, inputs, cfg = built
    diag = json.loads((out_root / "_reports" / "output_diag.json").read_text())
    assert any(diag[lev]["na_rate_fwci_frac"] > 0.20 for lev in ("p01", "p05")), \
        "fixture precondition: the synthetic world's NA rate should exceed the threshold"
    res = rgates.run_gates(out_root, inputs, config=cfg)
    assert res["verdict"] == "HUMAN_REVIEW", "NA > 20% must not be masked by PASS/WARN"


def test_run_gates_safest_verdict_wins_halt(built, monkeypatch):
    """T43: if any gate HALTs (exception), run_gates lets the named exception propagate (the exit code is mapped
    at the CLI layer; the exception types are distinguishable - test the type, not the bare code value)."""
    out_root, inputs, cfg = built
    hdr_path = (out_root / "frame" / "_frozen" / "manifest_header.json")
    hdr = json.loads(hdr_path.read_text())
    hdr["stars_set_hash"] = "TAMPERED"
    hdr_path.write_text(json.dumps(hdr))

    from common.manifest import ProvenanceMismatch

    with pytest.raises(ProvenanceMismatch):
        rgates.run_gates(out_root, inputs, config=cfg)
    # On HALT the reports of the gates already run must still be written to disk first (never silently lost)
    assert (out_root / "_reports" / "u6_gates_summary.json").is_file()


def test_gate_exceptions_are_distinguishable():
    """Exit-code mapping by named exception: the four gate exception types are pairwise distinguishable (type level; no assertion on specific code values)."""
    from common.manifest import ProvenanceMismatch
    from m7c_gates.frame_gate import FrameRejoinDrift, FramePKCoverageError
    from m7c_gates.golden_gate import GoldenStructuralFail
    from m7c_gates.reconcile_gate import TallyImbalance

    kinds = {ProvenanceMismatch, FrameRejoinDrift, FramePKCoverageError,
             GoldenStructuralFail, TallyImbalance}
    assert len(kinds) == 5
    for k in kinds:
        assert hasattr(k, "exit_code"), f"{k.__name__} must carry a named exit_code"
