"""U0 foundation: preflight. Two pre-start gates for environment/disk (G6 disk gate + environment gate).

Build checklist section D; tests T36/T37 (written test-first).
Identification-neutral: purely local checks, no data fetching, no network. Identification thresholds / exit codes come from the identity layer and are not hard-coded here.

Two gates (if either fails -> return a classified non-zero code + atomically write preflight_result.json, and the pipeline does not start):
  - G6 hard disk inequality (failing it is a HALT, returns CAPACITY_GATE_FAIL=16):
      peak_spill + data_root_used + tmp_used  (summed if all three are on the same physical disk)  <  that disk's free space
  - Environment gate (work starts only if all pass):
      1. OpenAlex key readable (env OPENALEX_API_KEY or the session key file)
      2. pyarrow.__version__ == the version pinned in env_lock (precondition for byte-deterministic freezes)
      3. SHA of redlines.yaml == SHA of the _redlines.RED literal (guards against YAML/code drift)
      4. rapidfuzz present (reverse_validate needs it; if missing it errors, no degraded mode)

Design: each gate is split into a "pure predicate (dependency-injected, easy to test)" and a "thin wrapper (reads real machine state -> calls the pure predicate -> atomically writes the result)".
"""
from __future__ import annotations

import os
import pathlib
from typing import Any

from common import atomic_io
from common import _redlines
from identity.exit_codes import CAPACITY_GATE_FAIL, ENVIRONMENT_GATE_FAIL

# --- environment-lock constants (the architecture standard's requirements.txt pins versions; environment gate, item 2) ---
# pyarrow==24 -> the installed package reports "24.0.0"; byte-deterministic freezes require the exact same version.
PYARROW_LOCK: str = "24.0.0"

# Data root (the path contains spaces; quote it in bash calls). It is read from the real disk in the thin wrapper; the pure predicates never touch it.
# --- Repo path resolution via config/paths.yaml (the legacy code hard-coded a machine-specific path) ---
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents if p.name == "units").parents[1]
if str(_sar_repo) not in _sar_sys.path:
    _sar_sys.path.append(str(_sar_repo))
from pipeline.lib.paths import derived_root as _sar_derived_root  # noqa: E402
DATA_ROOT: str = str(_sar_derived_root()) + "/"


# =============================================================================
# G6 disk gate: pure predicate (already passing; do not change)
# =============================================================================

def disk_gate_decision(
    *,
    peak_spill_bytes: int,
    data_root_used_bytes: int,
    tmp_used_bytes: int,
    free_bytes: int,
    same_physical_disk: bool,
) -> bool:
    """Pure predicate of the G6 disk gate. Returns True = enough space, gate passed / False = not enough, must HALT.

    G6 inequality: the gate passes only if need < available.
    same_physical_disk=True  -> the three needs are summed (data root, /tmp and peak spill all land on one physical disk);
    same_physical_disk=False -> only peak spill + data-root usage count against the data disk (/tmp is on another volume and does not compete).
    """
    if same_physical_disk:
        demand_bytes = peak_spill_bytes + data_root_used_bytes + tmp_used_bytes
    else:
        demand_bytes = peak_spill_bytes + data_root_used_bytes
    return demand_bytes < free_bytes


# =============================================================================
# Environment gate: four pure predicates (dependency-injected, never read the real machine; real values are read in the thin wrapper)
# =============================================================================

def env_gate_openalex_key(
    *,
    env_value: str | None,
    session_key_file: pathlib.Path | str | None,
) -> bool:
    """1. OpenAlex key readable: the env has a non-empty value, or the session key file exists and is non-empty -> True.

    env_value: the value of os.environ.get("OPENALEX_API_KEY") (injected by the thin wrapper).
    session_key_file: path of the fallback session key file (read when the env value is missing).
    A non-blank string from either source counts as readable; neither -> False (the pipeline does not start).
    """
    if env_value is not None and env_value.strip():
        return True
    if session_key_file is not None:
        p = pathlib.Path(session_key_file)
        if p.exists():
            try:
                content = p.read_text(encoding="utf-8")
            except OSError:
                return False
            if content.strip():
                return True
    return False


def env_gate_pyarrow_version(*, installed_version: str | None) -> bool:
    """2. pyarrow version pinned: installed_version must == PYARROW_LOCK.

    installed_version: pyarrow.__version__ (injected by the thin wrapper; pass None if pyarrow is not installed).
    Any inequality (including None) -> False (byte-deterministic freezes would not hold; the pipeline does not start).
    """
    return installed_version == PYARROW_LOCK


def env_gate_redlines_sha(path: pathlib.Path | str | None = None) -> bool:
    """3. SHA of redlines.yaml == SHA of the _redlines.RED literal.

    Reuses _redlines.red_matches_yaml (the same check as test_redlines): guards against the YAML being edited
    while the RED imported by the code was not updated (or vice versa) -> threshold definitions drifting from the literal. Passes only if they agree.
    """
    return _redlines.red_matches_yaml(path)


def env_gate_rapidfuzz_present(*, import_ok: bool) -> bool:
    """4. rapidfuzz present: importable -> True.

    import_ok: whether `import rapidfuzz` succeeded in the thin wrapper (an injected boolean).
    rapidfuzz missing -> False (a hard dependency of reverse_validate; if missing it errors, no degraded mode; environment gate, item 4).
    """
    return bool(import_ok)


def environment_gate_decision(
    *,
    openalex_ok: bool,
    pyarrow_ok: bool,
    redlines_sha_ok: bool,
    rapidfuzz_ok: bool,
) -> dict[str, Any]:
    """Aggregate pure predicate of the environment gate: passed=True only if all four pass; any failure is listed in fails.

    Returns {passed:bool, fails:list[str]} (fails uses stable names for diagnostic printing).
    """
    checks = [
        ("openalex_key", openalex_ok),
        ("pyarrow_version", pyarrow_ok),
        ("redlines_sha", redlines_sha_ok),
        ("rapidfuzz", rapidfuzz_ok),
    ]
    fails = [name for name, ok in checks if not ok]
    return {"passed": len(fails) == 0, "fails": fails}


# =============================================================================
# Thin wrapper: read the real disk/environment -> pure predicate -> atomically write preflight_result.json + return code
# =============================================================================

def _write_preflight_result(result_path: pathlib.Path | str, payload: dict[str, Any]) -> None:
    """Atomically write preflight_result.json (through the G7 atomic write; a crash leaves no half file)."""
    import json

    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8")
    atomic_io.atomic_write_bytes(result_path, blob)


def preflight_disk_check(
    *,
    peak_spill_bytes: int,
    data_root_used_bytes: int,
    tmp_used_bytes: int,
    free_bytes: int,
    same_physical_disk: bool,
    result_path: pathlib.Path | str,
) -> int:
    """Thin wrapper of the G6 disk gate: call the pure predicate -> on failure atomically write preflight_result.json + return CAPACITY_GATE_FAIL.

    Returns the exit code (int): gate passed -> 0; gate failed -> CAPACITY_GATE_FAIL(=16).
    Either way one preflight_result.json (passed + exit_code) is written, for reproduction/audit.

    Note: this wrapper only receives already measured byte counts (the peak-spill estimate and the real-disk du/statvfs are supplied by the calling script);
        this function makes no network calls and fetches no data; preflight reads only local state.
        Reading the real disk (shutil.disk_usage / os.statvfs) is left to the upper-level ops script, so it can be injected in tests.
    """
    passed = disk_gate_decision(
        peak_spill_bytes=peak_spill_bytes,
        data_root_used_bytes=data_root_used_bytes,
        tmp_used_bytes=tmp_used_bytes,
        free_bytes=free_bytes,
        same_physical_disk=same_physical_disk,
    )
    exit_code = 0 if passed else CAPACITY_GATE_FAIL
    payload = {
        "gate": "disk",
        "passed": passed,
        "exit_code": exit_code,
        "demand_inputs": {
            "peak_spill_bytes": peak_spill_bytes,
            "data_root_used_bytes": data_root_used_bytes,
            "tmp_used_bytes": tmp_used_bytes,
            "same_physical_disk": same_physical_disk,
        },
        "free_bytes": free_bytes,
    }
    _write_preflight_result(result_path, payload)
    return exit_code


# --- environment-gate thin wrapper: real-machine probes (can be overridden by dependency injection, to test failure paths) ---

# Sentinel: distinguishes "not injected" (-> the thin wrapper reads real machine state) from "an explicitly injected value (including None/False)" (-> use the injected value).
_AUTO: object = object()


def _probe_pyarrow_version() -> str | None:
    """Read the real machine's pyarrow.__version__; not installed / read failure -> None (the pure predicate then fails it)."""
    try:
        import pyarrow  # noqa: PLC0415
        return getattr(pyarrow, "__version__", None)
    except Exception:
        return None


def _probe_rapidfuzz_import() -> bool:
    """Whether a real `import rapidfuzz` succeeds (a hard dependency of reverse_validate)."""
    try:
        import rapidfuzz  # noqa: F401,PLC0415
        return True
    except Exception:
        return False


def preflight_env_check(
    *,
    result_path: pathlib.Path | str,
    openalex_env_value: Any = _AUTO,
    session_key_file: Any = _AUTO,
    installed_pyarrow_version: Any = _AUTO,
    rapidfuzz_import_ok: Any = _AUTO,
    redlines_path: pathlib.Path | str | None = None,
) -> int:
    """Environment-gate thin wrapper (same pattern as preflight_disk_check): read real machine state -> four pure predicates ->
    atomically write preflight_result.json -> on failure return the non-zero code ENVIRONMENT_GATE_FAIL.

    Real machine state read (when nothing is injected):
        1. OpenAlex key   : os.environ["OPENALEX_API_KEY"] (falls back to the session key file if missing)
        2. pyarrow version: pyarrow.__version__, must == PYARROW_LOCK (byte-deterministic freezes)
        3. redlines SHA   : the RED literal vs redlines.yaml safe_load agree (guards against code/YAML drift)
        4. rapidfuzz      : whether it can be imported (a hard dependency of reverse_validate; if missing it errors, no degraded mode)

    Dependency injection (for tests): openalex_env_value / session_key_file / installed_pyarrow_version /
        rapidfuzz_import_ok, when given an explicit value, override the matching real probe (including None/False); not given -> read the real machine.

    Returns the exit code (int; like disk_check it does not raise, the calling script does sys.exit):
        all pass -> 0; any failure -> ENVIRONMENT_GATE_FAIL(=30). Either way one atomic
        preflight_result.json (gate/passed/exit_code/fails/checks + the versions really read) is written, for audit and reproduction.

    Note: this wrapper only reads local environment state (env/import/file SHA), makes no network calls and fetches no data.
    """
    # 1. OpenAlex key (env first; falls back to the session key file if missing)
    if openalex_env_value is _AUTO:
        openalex_env_value = os.environ.get("OPENALEX_API_KEY")
    if session_key_file is _AUTO:
        session_key_file = None   # There is no standard session key file path -> the env is the main source
    openalex_ok = env_gate_openalex_key(
        env_value=openalex_env_value, session_key_file=session_key_file
    )

    # 2. pyarrow version pinned
    if installed_pyarrow_version is _AUTO:
        installed_pyarrow_version = _probe_pyarrow_version()
    pyarrow_ok = env_gate_pyarrow_version(installed_version=installed_pyarrow_version)

    # 3. redlines SHA (RED literal vs YAML)
    redlines_sha_ok = env_gate_redlines_sha(redlines_path)

    # 4. rapidfuzz present
    if rapidfuzz_import_ok is _AUTO:
        rapidfuzz_import_ok = _probe_rapidfuzz_import()
    rapidfuzz_ok = env_gate_rapidfuzz_present(import_ok=bool(rapidfuzz_import_ok))

    decision = environment_gate_decision(
        openalex_ok=openalex_ok,
        pyarrow_ok=pyarrow_ok,
        redlines_sha_ok=redlines_sha_ok,
        rapidfuzz_ok=rapidfuzz_ok,
    )
    passed = decision["passed"]
    exit_code = 0 if passed else ENVIRONMENT_GATE_FAIL
    payload = {
        "gate": "environment",
        "passed": passed,
        "exit_code": exit_code,
        "fails": decision["fails"],
        "checks": {
            "openalex_key": openalex_ok,
            "pyarrow_version": pyarrow_ok,
            "redlines_sha": redlines_sha_ok,
            "rapidfuzz": rapidfuzz_ok,
        },
        "pyarrow_version_seen": installed_pyarrow_version,
        "pyarrow_version_lock": PYARROW_LOCK,
    }
    _write_preflight_result(result_path, payload)
    return exit_code
