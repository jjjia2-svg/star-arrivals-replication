"""A11 tests: the `preflight_env_check` thin wrapper of the preflight environment gate.

Problem (review A11, `preflight.py:116`): the four pure decisions of the byte-determinism environment gate
(`environment_gate_decision` / `env_gate_pyarrow_version` etc.) were referenced only by tests;
no production wrapper read the real machine state, so a change of machine or an AWS version
drift would continue silently instead of HALT.

Fix (same pattern as `preflight_disk_check` in the same file): add the `preflight_env_check`
wrapper. It reads `pyarrow.__version__`, the OpenAlex key in `os.environ`, whether rapidfuzz
can be imported and the redlines sha -> calls `environment_gate_decision` -> atomically writes
preflight_result.json + HALTs with a non-zero code.

The wrapper takes injected probes (to test the failure paths): an injected probe value overrides
the real read; without injection it reads the real machine.
"""
import json
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common.preflight import (  # noqa: E402
    PYARROW_LOCK,
    preflight_env_check,
)
from identity.exit_codes import ENVIRONMENT_GATE_FAIL  # noqa: E402


def test_env_check_all_pass_returns_zero(tmp_path):
    # all four pass (good values injected; the redlines sha comes from the real file and matches on this machine) -> rc 0, result written with passed=True
    result_path = tmp_path / "preflight_result.json"
    rc = preflight_env_check(
        result_path=result_path,
        openalex_env_value="key-abc123",
        installed_pyarrow_version=PYARROW_LOCK,
        rapidfuzz_import_ok=True,
    )
    assert rc == 0
    assert result_path.exists(), "the environment gate must write preflight_result.json atomically"
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["gate"] == "environment"
    assert payload["passed"] is True
    assert payload["exit_code"] == 0
    assert payload["fails"] == []


def test_env_check_pyarrow_mismatch_halts_with_env_code(tmp_path):
    # pyarrow version drift (new machine / AWS) -> non-zero HALT (== ENVIRONMENT_GATE_FAIL), result written with passed=False
    result_path = tmp_path / "preflight_result.json"
    rc = preflight_env_check(
        result_path=result_path,
        openalex_env_value="key-abc123",
        installed_pyarrow_version="13.0.0",   # != pinned version 24.0.0
        rapidfuzz_import_ok=True,
    )
    assert rc != 0, "version drift must give a non-zero exit code, not continue silently"
    assert rc == ENVIRONMENT_GATE_FAIL
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["gate"] == "environment"
    assert payload["passed"] is False
    assert payload["exit_code"] == ENVIRONMENT_GATE_FAIL
    assert "pyarrow_version" in payload["fails"]


def test_env_check_openalex_missing_halts(tmp_path):
    # OpenAlex key missing (empty env + no session key file) -> HALT, fails contains openalex_key
    result_path = tmp_path / "preflight_result.json"
    rc = preflight_env_check(
        result_path=result_path,
        openalex_env_value=None,
        session_key_file=None,
        installed_pyarrow_version=PYARROW_LOCK,
        rapidfuzz_import_ok=True,
    )
    assert rc == ENVIRONMENT_GATE_FAIL
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert "openalex_key" in payload["fails"]


def test_env_check_rapidfuzz_absent_halts(tmp_path):
    # rapidfuzz missing -> HALT (reverse_validate depends on it; error, no degraded mode)
    result_path = tmp_path / "preflight_result.json"
    rc = preflight_env_check(
        result_path=result_path,
        openalex_env_value="key-abc123",
        installed_pyarrow_version=PYARROW_LOCK,
        rapidfuzz_import_ok=False,
    )
    assert rc == ENVIRONMENT_GATE_FAIL
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert "rapidfuzz" in payload["fails"]


def test_env_check_reads_real_machine_state_when_not_injected(tmp_path):
    # no probes injected -> the wrapper reads the real machine state (pyarrow.__version__ / os.environ / rapidfuzz import).
    # The environment differs by machine, so only assert: a distinguishable exit code is returned and a well-formed result is written (the real-read path does not crash).
    result_path = tmp_path / "preflight_result.json"
    rc = preflight_env_check(result_path=result_path)
    assert rc in (0, ENVIRONMENT_GATE_FAIL)
    assert result_path.exists()
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["gate"] == "environment"
    assert isinstance(payload["fails"], list)
    # the pyarrow version actually read must be recorded in the result (so an audit can reproduce "which version it was")
    assert "pyarrow_version_seen" in payload
    assert payload["pyarrow_version_lock"] == PYARROW_LOCK
