"""U2 real-data scale smoke gate (thin-gate pattern, as in preflight).

Where the design comes from:
  - Open item: add a "real-data scale smoke" gate to U2.
  - Incident behind it: the quadratic full scan in build_manual_required_queue was under 1% done after 3.4 h on real data
    (fixtures could not show it, real data did; the third such case); the lessons from the same batch were ledger memory and stragglers.
  - Shape = the existing u0 common/preflight.py pattern: a "pure decision (dependency-injected, easy to test)" plus a
    "thin shell (read real disk state -> pure decision -> atomically write the result json -> HALT with a non-zero code)".

Convention: this gate hard-codes no threshold. The expected ranges (bounds) are declared by the operator from a pre-run estimate
(the same injection pattern as disk_gate_decision: the code only judges, it does not set values). Empty bounds would be a fake gate that
checks nothing, so it raises ValueError (a false sense of safety is worse than no guard). Engineering gate; no identification convention.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Mapping

from common import atomic_io
from identity.exit_codes import SCALE_GATE_FAIL

# U1 input tables the thin shell can read (what U2 actually consumes, same source as resolve.load_u1): table name -> u1_edges subdirectory.
_U1_TABLES = ("authors", "canonical_id_map", "authorship_edges", "works_affil")


def scale_gate_decision(
    *,
    observed: Mapping[str, int],
    bounds: Mapping[str, tuple],
) -> dict[str, Any]:
    """Pure decision: for every declared key, the observed row count must fall in the closed interval [lo, hi]; passed=True only if all do.

    observed: {table name: rows actually read} (injected by the thin shell; tests can feed it directly).
    bounds:   {table name: (lo, hi)} - expected ranges declared by the operator (pre-run estimate, e.g. the two-school measurement scaled to 11 schools).
              Empty dict -> ValueError (a fake gate must not exist); a declared key with no observed value fails that key (never silently passes).
    Returns {passed: bool, fails: list[str]} (fails names which key fails and how, so it is diagnosable).
    """
    if not bounds:
        raise ValueError(
            "U2 scale gate: empty bounds = a fake gate that checks nothing — the operator must declare the expected ranges "
            "(following the preflight injection pattern; the code does not pick thresholds for people)"
        )
    fails: list[str] = []
    for name, (lo, hi) in sorted(bounds.items()):
        got = observed.get(name)
        if got is None:
            fails.append(f"{name}: 观测值缺失 (盘上读不到该表行数, 不许静默当过)")
        elif not (lo <= got <= hi):
            fails.append(f"{name}: 行数 {got} 越出申报区间 [{lo}, {hi}]")
    return {"passed": not fails, "fails": fails}


def _observe_u1_row_counts(data_root) -> dict[str, int]:
    """Read the parquet metadata row counts of <data_root>/derived/u1_edges/<table>/ (footer read, no full scan).

    Counts both a single-file data.parquet and bucketed bucket=*/part-*; a missing table directory is left out of observed
    (the pure decision fails it as "observation missing"; it is not masked here).
    """
    import pyarrow.parquet as pq

    root = pathlib.Path(data_root) / "derived" / "u1_edges"
    observed: dict[str, int] = {}
    for name in _U1_TABLES:
        d = root / name
        if not d.exists():
            continue
        files = sorted(d.rglob("*.parquet"))
        files = [f for f in files if f.name != "data_SAMPLE.parquet"]  # Hard rule: never read SAMPLE
        if not files:
            continue
        observed[name] = sum(pq.ParquetFile(str(f)).metadata.num_rows for f in files)
    return observed


def preflight_u2_scale_check(
    data_root,
    *,
    bounds: Mapping[str, tuple],
    result_path: pathlib.Path | str,
) -> int:
    """Thin shell (same pattern as preflight_disk_check/preflight_env_check): read the real on-disk scale -> pure decision ->
    atomically write the result json -> exit 0 on pass / SCALE_GATE_FAIL (=31) on fail.

    In both cases a result json (gate/passed/exit_code/fails/observed/bounds) is written atomically,
    so the run can be audited and reproduced. No network, no full data scan (only parquet footer metadata).
    """
    observed = _observe_u1_row_counts(data_root)
    decision = scale_gate_decision(observed=observed, bounds=bounds)
    exit_code = 0 if decision["passed"] else SCALE_GATE_FAIL
    payload = {
        "gate": "u2_scale",
        "passed": decision["passed"],
        "exit_code": exit_code,
        "fails": decision["fails"],
        "observed": observed,
        "bounds": {k: list(v) for k, v in sorted(bounds.items())},
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8")
    rp = pathlib.Path(result_path)
    rp.parent.mkdir(parents=True, exist_ok=True)
    atomic_io.atomic_write_bytes(rp, blob)
    return exit_code
