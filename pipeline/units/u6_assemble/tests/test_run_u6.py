"""run_u6 thin CLI tests (written test-first): synthetic end-to-end + exit-code mapping + idempotent resume."""
from __future__ import annotations

import json

import pytest

import run_u6
from conftest import make_inputs


def test_run_all_end_to_end_synthetic(tmp_path, zenou_world, u6_config):
    rep = run_u6.run_all(make_inputs(zenou_world), out_root=tmp_path / "ship",
                         config=u6_config)
    assert rep["skipped"] is False
    assert rep["gates_verdict"] in ("WARN", "HUMAN_REVIEW")
    assert (tmp_path / "ship" / "run_manifest.lock").is_file()
    assert (tmp_path / "ship" / "_reports" / "run_summary_u6.json").is_file()


def test_run_all_resume_skips_when_done(tmp_path, zenou_world, u6_config):
    run_u6.run_all(make_inputs(zenou_world), out_root=tmp_path / "ship",
                   config=u6_config)
    rep2 = run_u6.run_all(make_inputs(zenou_world), out_root=tmp_path / "ship",
                          config=u6_config)
    assert rep2["skipped"] is True, "second run with the same anchor and config -> resume skip"
    cfg2 = dict(u6_config, stars_set_hash="ssh_2",
                source_snapshot_merkle="snap:bbb")
    world2 = zenou_world
    world2["upstream_provenance"]["u4"]["stars_set_hash"] = "ssh_2"
    world2["upstream_provenance"]["u5"]["stars_set_hash"] = "ssh_2"
    world2["upstream_provenance"]["u4"]["source_snapshot_merkle"] = "snap:bbb"
    world2["upstream_provenance"]["u5"]["source_snapshot_merkle"] = "snap:bbb"
    rep3 = run_u6.run_all(make_inputs(world2), out_root=tmp_path / "ship",
                          config=cfg2)
    assert rep3["skipped"] is False, "upstream anchor changed -> idempotency key flips, no false skip"


def test_exit_code_mapping_distinguishable():
    from common.manifest import ProvenanceMismatch
    from m7b_assemble.assemble import FrameAssemblyError
    from m7c_gates.golden_gate import GoldenStructuralFail
    from m7c_gates.reconcile_gate import TallyImbalance

    codes = {run_u6.exit_code_for(ProvenanceMismatch("x")),
             run_u6.exit_code_for(FrameAssemblyError("x")),
             run_u6.exit_code_for(TallyImbalance("x")),
             run_u6.exit_code_for(GoldenStructuralFail("x"))}
    assert len(codes) == 4, "the four kinds of HALT exit codes must be pairwise distinct (named constants)"


def test_pins_dual_anchor_shared_keys_consistent():
    """The three keys shared by the two anchors (merkle/stars_set_hash/rule_version) must have the same pinned values."""
    for k in ("source_snapshot_merkle", "stars_set_hash", "rule_version"):
        assert run_u6.PINNED_U4_10C[k] == run_u6.PINNED_U5_SHIP[k]
    assert run_u6.PINNED_U4_10C["config_sha"] \
        != run_u6.PINNED_U5_SHIP["config_sha"], "config_sha differs between units (expected)"
