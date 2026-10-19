"""Tests for the U0 preflight disk and environment gates (G6 + environment gate), T36/T37.

  - Disk gate (G6): peak spill + data-root usage + /tmp usage (summed when on the same physical
    disk) must be < the free space of that disk; otherwise the gate fails (HALT: atomically
    write preflight_result.json and return CAPACITY_GATE_FAIL=16).
  - Environment gate (all four must pass before work starts): (1) the OpenAlex key is readable
    (2) pyarrow.__version__ == the pinned version (3) redlines.yaml SHA == the SHA of the RED
    literal (4) rapidfuzz is present (if missing: error, no degraded mode).

The pure decision functions are easy to test (dependency injection, no real machine state);
real disk/environment reads live in thin wrappers.
"""
import json
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common.preflight import (  # noqa: E402
    PYARROW_LOCK,
    disk_gate_decision,
    env_gate_openalex_key,
    env_gate_pyarrow_version,
    env_gate_rapidfuzz_present,
    env_gate_redlines_sha,
    environment_gate_decision,
    preflight_disk_check,
)
from identity.exit_codes import CAPACITY_GATE_FAIL  # noqa: E402


# =============================================================================
# Disk gate (G6) - pure decision disk_gate_decision (already passing, kept)
# =============================================================================

def test_disk_gate_fails_when_demand_exceeds_free_same_disk():
    # same physical disk: peak_spill(100)+data_root_used(100)+tmp_used(100)=300 > free(250) -> gate fails
    passed = disk_gate_decision(
        peak_spill_bytes=100,
        data_root_used_bytes=100,
        tmp_used_bytes=100,
        free_bytes=250,
        same_physical_disk=True,
    )
    assert passed is False


def test_disk_gate_passes_when_demand_below_free_same_disk():
    # same disk: 100+100+50=250 < free(300) -> gate passes
    passed = disk_gate_decision(
        peak_spill_bytes=100,
        data_root_used_bytes=100,
        tmp_used_bytes=50,
        free_bytes=300,
        same_physical_disk=True,
    )
    assert passed is True


def test_disk_gate_strict_inequality_equal_fails():
    # strict inequality (<): demand == free does not pass (there must be real headroom)
    passed = disk_gate_decision(
        peak_spill_bytes=100,
        data_root_used_bytes=100,
        tmp_used_bytes=100,
        free_bytes=300,
        same_physical_disk=True,
    )
    assert passed is False


def test_disk_gate_different_disk_excludes_tmp():
    # different physical disks: /tmp on another volume does not compete with the data disk -> demand=peak+data_root=200 < free(250) -> gate passes
    passed = disk_gate_decision(
        peak_spill_bytes=100,
        data_root_used_bytes=100,
        tmp_used_bytes=9999,   # on another volume, not counted in the data-disk demand
        free_bytes=250,
        same_physical_disk=False,
    )
    assert passed is True


# =============================================================================
# Environment gate - four pure decisions (dependency injection, no real machine reads)
# =============================================================================

# --- (1) OpenAlex key readable (env or session key file) ---

def test_env_gate_openalex_key_from_env():
    assert env_gate_openalex_key(env_value="abc123", session_key_file=None) is True


def test_env_gate_openalex_key_from_session_file(tmp_path):
    kf = tmp_path / "openalex.key"
    kf.write_text("file-key-xyz\n", encoding="utf-8")
    assert env_gate_openalex_key(env_value=None, session_key_file=kf) is True


def test_env_gate_openalex_key_missing_both_fails():
    assert env_gate_openalex_key(env_value=None, session_key_file=None) is False


def test_env_gate_openalex_key_blank_env_fails():
    # an empty or whitespace-only string is not readable
    assert env_gate_openalex_key(env_value="   ", session_key_file=None) is False


# --- (2) pyarrow.__version__ == the version pinned in env_lock ---

def test_env_gate_pyarrow_version_match():
    assert env_gate_pyarrow_version(installed_version=PYARROW_LOCK) is True


def test_env_gate_pyarrow_version_mismatch_fails():
    assert env_gate_pyarrow_version(installed_version="13.0.0") is False


def test_pyarrow_lock_is_pinned_to_24():
    # the architecture pins pyarrow==24 (precondition for byte-deterministic freeze)
    assert PYARROW_LOCK == "24.0.0"


# --- (3) redlines.yaml SHA == SHA of the RED literal ---

def test_env_gate_redlines_sha_matches_real_files():
    # the real RED and the real YAML agree (same check as test_redlines)
    assert env_gate_redlines_sha() is True


# --- (4) rapidfuzz present (if missing: error, no degraded mode) ---

def test_env_gate_rapidfuzz_present_when_importable():
    assert env_gate_rapidfuzz_present(import_ok=True) is True


def test_env_gate_rapidfuzz_absent_fails():
    # rapidfuzz missing -> gate False (never degrade and pass; reverse_validate depends on it)
    assert env_gate_rapidfuzz_present(import_ok=False) is False


# --- environment gate aggregate: any failure -> overall failure ---

def test_environment_gate_all_pass():
    out = environment_gate_decision(
        openalex_ok=True,
        pyarrow_ok=True,
        redlines_sha_ok=True,
        rapidfuzz_ok=True,
    )
    assert out["passed"] is True
    assert out["fails"] == []


def test_environment_gate_any_fail_blocks():
    out = environment_gate_decision(
        openalex_ok=True,
        pyarrow_ok=True,
        redlines_sha_ok=True,
        rapidfuzz_ok=False,   # rapidfuzz missing
    )
    assert out["passed"] is False
    assert "rapidfuzz" in out["fails"]


def test_environment_gate_multiple_fails_listed():
    out = environment_gate_decision(
        openalex_ok=False,
        pyarrow_ok=False,
        redlines_sha_ok=True,
        rapidfuzz_ok=True,
    )
    assert out["passed"] is False
    assert "openalex_key" in out["fails"]
    assert "pyarrow_version" in out["fails"]


# =============================================================================
# preflight_disk_check thin wrapper - on failure atomically write preflight_result.json + return code
# =============================================================================

def test_preflight_disk_check_fail_writes_result_and_returns_capacity_code(tmp_path):
    # not enough space -> atomically write preflight_result.json + return CAPACITY_GATE_FAIL (=16)
    result_path = tmp_path / "preflight_result.json"
    rc = preflight_disk_check(
        peak_spill_bytes=300,
        data_root_used_bytes=100,
        tmp_used_bytes=100,
        free_bytes=250,
        same_physical_disk=True,
        result_path=result_path,
    )
    assert rc == CAPACITY_GATE_FAIL
    assert rc == 16
    assert result_path.exists(), "a failed disk gate must write preflight_result.json atomically"
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["gate"] == "disk"
    assert payload["passed"] is False
    assert payload["exit_code"] == 16


def test_preflight_disk_check_pass_returns_zero(tmp_path):
    # enough space -> return 0 (gate passes); still write a result (passed=True)
    result_path = tmp_path / "preflight_result.json"
    rc = preflight_disk_check(
        peak_spill_bytes=50,
        data_root_used_bytes=50,
        tmp_used_bytes=50,
        free_bytes=300,
        same_physical_disk=True,
        result_path=result_path,
    )
    assert rc == 0
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["exit_code"] == 0
