"""Red test for the M0-3 capacity_gate: the capacity gate before fetching (numbers are injected to
test the gate; never reads a real disk or downloads).

What is tested:
  - remote_bytes_from_manifests: sums meta.content_length at the root of each entity's official
    manifest.
  - real_byte_gate: required = remote x margin vs free; too large is refused (ok=False), enough room
    passes (ok=True).
  - snapshot_capacity_gate: calls U0 preflight.disk_gate_decision to judge the derived volume
    and checks the mount / >= min_tb; given official_manifests it adds real_byte_gate;
    it only returns a verdict and does not exit.
  - pre_shard_space_ok: remaining < min_free -> False (HALT), enough -> True.
  - DATA_ROOT uses the U0 preflight constant (.../openalex_pipeline/derived/).
  - capacity_cfg fail (ok=False) -> the caller should raise / skip sync (only the gate verdict is
    asserted here).

Rule: fixtures inject byte counts to test the logic; the real disk read in the preflight thin
shell is left to operations scripts, and tests only inject.
"""
from __future__ import annotations

import pytest

from m0_snapshot import capacity_gate


_GB = 1024 ** 3


# --- remote_bytes_from_manifests: sum meta.content_length at the root of each entity ---

def test_remote_bytes_sums_root_meta_content_length():
    # One manifest view per top-level entity; root meta.content_length = that entity's total bytes.
    manifests = {
        "works": {"meta": {"content_length": 600 * _GB, "record_count": 500}},
        "authors": {"meta": {"content_length": 80 * _GB, "record_count": 90}},
        "institutions": {"meta": {"content_length": 1 * _GB, "record_count": 1}},
    }
    total = capacity_gate.remote_bytes_from_manifests(manifests)
    assert total == (600 + 80 + 1) * _GB


def test_remote_bytes_missing_meta_raises_not_silent_zero():
    # A missing meta.content_length must raise naming the entity, never be silently treated as 0
    # bytes (otherwise the capacity gate is falsely green).
    bad = {"works": {"meta": {"record_count": 500}}}  # no content_length
    with pytest.raises((KeyError, ValueError)):
        capacity_gate.remote_bytes_from_manifests(bad)


# --- real_byte_gate: required = remote × safety_margin vs free ---

def test_real_byte_gate_rejects_when_remote_exceeds_free():
    # remote 600GB x 1.15 = 690GB required > 500GB free -> ok=False.
    manifests = {"works": {"meta": {"content_length": 600 * _GB, "record_count": 1}}}
    out = capacity_gate.real_byte_gate(
        manifests, snapshot_root_free_bytes=500 * _GB, safety_margin=1.15
    )
    assert out["ok"] is False
    assert out["required_gb"] == pytest.approx(600 * 1.15, rel=1e-6)
    assert out["remote_gb"] == pytest.approx(600.0, rel=1e-6)
    assert out["free_gb"] == pytest.approx(500.0, rel=1e-6)


def test_real_byte_gate_passes_when_free_covers_required():
    # remote 600GB x 1.15 = 690GB required < 3600GB free -> ok=True.
    manifests = {"works": {"meta": {"content_length": 600 * _GB, "record_count": 1}}}
    out = capacity_gate.real_byte_gate(
        manifests, snapshot_root_free_bytes=3600 * _GB, safety_margin=1.15
    )
    assert out["ok"] is True


# --- snapshot_capacity_gate: calls U0 preflight.disk_gate_decision + checks mount/min_tb, does not exit ---

def test_snapshot_capacity_gate_derived_disk_decision_consumes_preflight():
    # Derived-volume gate: goes through U0 preflight.disk_gate_decision (passes only if required <
    # free).
    # Here the derived requirement is small, the disk is big, mounted and >= min_tb -> passed=True.
    cfg = {
        "snapshot_root_mounted": True,
        "snapshot_root_free_bytes": 3600 * _GB,
        "snapshot_root_min_tb": 2.0,
        "est_derived_bytes": 50 * _GB,
        "tmp_used_bytes": 0,
        "same_physical_disk": True,
    }
    out = capacity_gate.snapshot_capacity_gate(cfg)
    assert out["passed"] is True
    # Only returns a verdict and must not sys.exit itself (exiting belongs to the U0 preflight thin
    # shell / the caller).
    assert "exit_code" not in out or out["exit_code"] == 0


def test_snapshot_capacity_gate_halts_when_root_not_mounted():
    # SNAPSHOT_ROOT not mounted -> passed=False, listed in fails (no exit).
    cfg = {
        "snapshot_root_mounted": False,
        "snapshot_root_free_bytes": 3600 * _GB,
        "snapshot_root_min_tb": 2.0,
        "est_derived_bytes": 50 * _GB,
        "tmp_used_bytes": 0,
        "same_physical_disk": True,
    }
    out = capacity_gate.snapshot_capacity_gate(cfg)
    assert out["passed"] is False
    assert "snapshot_root_mounted" in out["fails"]


def test_snapshot_capacity_gate_halts_when_below_min_tb():
    # disk capacity < min_tb (1TB < the 2TB threshold) -> passed=False.
    cfg = {
        "snapshot_root_mounted": True,
        "snapshot_root_free_bytes": 1000 * _GB,
        "snapshot_root_total_bytes": 1000 * _GB,
        "snapshot_root_min_tb": 2.0,
        "est_derived_bytes": 50 * _GB,
        "tmp_used_bytes": 0,
        "same_physical_disk": True,
    }
    out = capacity_gate.snapshot_capacity_gate(cfg)
    assert out["passed"] is False
    assert "snapshot_root_min_tb" in out["fails"]


def test_snapshot_capacity_gate_overlays_real_byte_gate_when_manifests_given():
    # With official_manifests the real byte gate is added: remote 600GB x 1.15 > 500GB free -> this
    # arm refuses.
    cfg = {
        "snapshot_root_mounted": True,
        "snapshot_root_free_bytes": 500 * _GB,
        "snapshot_root_min_tb": 0.1,  # not blocked by min_tb
        "est_derived_bytes": 1 * _GB,
        "tmp_used_bytes": 0,
        "same_physical_disk": True,
    }
    manifests = {"works": {"meta": {"content_length": 600 * _GB, "record_count": 1}}}
    out = capacity_gate.snapshot_capacity_gate(cfg, official_manifests=manifests)
    assert out["passed"] is False
    assert "real_byte_gate" in out["fails"]


# --- pre_shard_space_ok: check the remaining space before writing each derived shard ---

def test_pre_shard_space_ok_true_when_enough(tmp_path):
    # free_gb is injected (the thin shell's real disk read is left to operations); remaining 100GB
    # >= threshold 10GB -> True.
    assert capacity_gate.pre_shard_space_ok(
        str(tmp_path), min_free_gb=10.0, free_gb=100.0
    ) is True


def test_pre_shard_space_ok_false_when_below_threshold(tmp_path):
    # remaining 5GB < threshold 10GB -> False (permanent HALT, not treated as transient).
    assert capacity_gate.pre_shard_space_ok(
        str(tmp_path), min_free_gb=10.0, free_gb=5.0
    ) is False


# --- DATA_ROOT uses the U0 constant ---

def test_data_root_matches_u0_preflight_constant():
    from common import preflight as u0_preflight

    assert capacity_gate.DATA_ROOT == u0_preflight.DATA_ROOT
    assert capacity_gate.DATA_ROOT.endswith("openalex_pipeline/derived/")
