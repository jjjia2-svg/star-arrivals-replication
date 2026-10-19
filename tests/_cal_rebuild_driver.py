#!/usr/bin/env python3
"""The T7 acceptance rebuild, under the 2026-08-28 caliber — run in a SUBPROCESS by
tests/test_pipeline_rebuild.py's `cal_run` fixture.

Since the freeze the canonical frames in `data/frames/` are the caliber rebuild, so the frames
acceptance proof must rebuild THROUGH the caliber arrangement: the shadow legacy tree (cal event
tables + supplement + econ surgery staged at the exact fnfix paths the verbatim ported builders
resolve — `frames_stage.build_shadow`, the T3 design) and the same launcher stages the T3 driver
ran, in the same dependency order. This helper is exactly that orchestration — phases S/G/E/A of
`pipeline/stars/caliber_2026-08-28/run_cal_frames.py`, whose stage runners it IMPORTS rather than
re-implements — minus T3's controls/accounting/freeze phases (the controls and the row-level
accounting were run and frozen by T3; the freeze is what produced the canon this proof compares
against). It writes NOTHING into the repository: every stage lands in the single-use scratch root
passed as argv[1], and the comparisons are the caller's business.

The p1-gold stage is run TWICE per field: the acceptance suite's H1 characterisation needs to show
the builder disagrees with ITSELF (float accumulation order), not merely with the frozen frame.

Usage: python3 tests/_cal_rebuild_driver.py <empty scratch root> <result JSON path>
Result JSON: {stage_key: {"run_dir": str, "produced": {abs path: sha256}, "secs": float,
"started_ns": int}} — the fixture wraps these into the suite's `Rebuild` provenance objects.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "pipeline/stars/caliber_2026-08-28"))

import frames_stage as fs                     # noqa: E402
import run_cal_frames as rcf                  # noqa: E402

GOLD = rcf.GOLD
ECON = rcf.ECON
PY = sys.executable

RESULT: dict[str, dict] = {}


def record(key: str, started_ns: int, st: dict) -> None:
    RESULT[key] = {"run_dir": str(st["run_dir"]), "produced": st["produced"],
                   "secs": st["secs"], "started_ns": started_ns}


def stage(key: str, name: str, scratch: pathlib.Path, args=(), execute=False, shadow=None) -> dict:
    started_ns = time.time_ns()
    st = rcf.run_stage(name, scratch, tuple(args), execute=execute, shadow=shadow)
    record(key, started_ns, st)
    return st


def make_slim(field: str, src: pathlib.Path, out_dir: pathlib.Path) -> None:
    """make_slim in a subprocess; produced-set parsed from ITS OK-report (the T7-final NEW-2
    evidence path), exactly as the pre-freeze suite did."""
    out_dir.mkdir(parents=True, exist_ok=False)
    ev = out_dir / f"p3_slim_ev_{field}.parquet"
    noev = out_dir / f"p3_slim_{field}.parquet"
    started_ns, t0 = time.time_ns(), time.time()
    proc = subprocess.run([PY, str(REPO / "pipeline/frames/make_slim.py"), field, str(src),
                           str(ev), "--noev", str(noev)], cwd=REPO, capture_output=True, text=True)
    assert proc.returncode == 0, f"make_slim {field}:\n{(proc.stdout + proc.stderr)[-4000:]}"
    produced = {p: s for p, s in
                re.findall(r"^\s+OK\s+(/.+?)\s+\(\d[\d,]* B, sha256 ([0-9a-f]{64})\)$",
                           proc.stdout, re.M)}
    assert set(produced) == {str(ev.resolve()), str(noev.resolve())}, sorted(produced)
    stats = eval(proc.stdout.strip().splitlines()[-1], {"__builtins__": {}}, {})  # noqa: S307
    RESULT[f"slim_{field}"] = {"run_dir": str(out_dir), "produced": produced,
                               "secs": round(time.time() - t0, 1), "started_ns": started_ns,
                               "stats": stats}


def main() -> int:
    root = pathlib.Path(sys.argv[1])
    out_json = pathlib.Path(sys.argv[2])
    assert root.is_dir() and not any(root.iterdir()), f"scratch root must be empty: {root}"

    # ---- S: the shadow legacy tree (cal tables + supplement + econ surgery) ------------------
    shadow_root = root / "shadow"
    sh, surgery = fs.build_shadow(shadow_root)
    # 2026-09-23: the frozen-link inputs are recorded (rel -> sha256 of the linked legacy bytes) so the
    # fixture can compare them with the 08-28 staging manifest — a mutated legacy input is reported,
    # never silently rebuilt over (pipeline/NOT_REPRODUCIBLE.md, INCIDENT entry / index row 17).
    RESULT["_shadow"] = {"entries": len(sh.entries), "surgery": surgery,
                         "frozen": {e["rel"]: e["sha256"] for e in sh.entries
                                    if e["origin"].startswith("frozen:")}}

    # ---- G: chemistry / math_stats (prodlib -> union-gold -> p1-gold x2 -> p2-gold -> slim) --
    for field in rcf.FIELDS_GOLD:
        report: dict = {}
        out = rcf.run_prodlib(field, root / f"prodlib_{field}", shadow_root, report)
        sh.install(f"{GOLD}/runs/fnfix/{field}/data/analysis_frame_p01_52ev_topicdose_2026-07-21.csv",
                   out, f"t7-cal:prodlib {field}")
        st = stage(f"union_{field}", "union-gold", root / f"union_{field}",
                   ("--field", field), execute=True, shadow=shadow_root)
        for name in (f"analysis_frame_{field}_2026-08-10.csv", "relationships.csv",
                     "build_report.json", "funnel.json"):
            sh.install(f"{GOLD}/data/fnfix/union_frame_{field}/{name}",
                       st["run_dir"] / f"data/fnfix/union_frame_{field}/{name}",
                       f"t7-cal:union-gold {field}")
        st = stage(f"p1_{field}_a", "p1-gold", root / f"p1_{field}_a",
                   ("--field", field), execute=True, shadow=shadow_root)
        stage(f"p1_{field}_b", "p1-gold", root / f"p1_{field}_b",
              ("--field", field), execute=True, shadow=shadow_root)
        sh.install(f"{GOLD}/data/fnfix/analysis_frame_{field}_new_gold_2026-08-10.csv",
                   st["run_dir"] / f"data/fnfix/analysis_frame_{field}_new_gold_2026-08-10.csv",
                   f"t7-cal:p1-gold {field}")
        st = stage(f"p2_{field}", "p2-gold", root / f"p2_{field}",
                   ("--field", field, "--panel3", "full"), execute=True, shadow=shadow_root)
        for name in ("becoming_none.csv", "pairs_none.parquet", "pairs_slim_none.parquet"):
            sh.install(f"{GOLD}/data/fnfix/panels23_{field}_gold/{name}",
                       st["run_dir"] / f"data/fnfix/panels23_{field}_gold/{name}",
                       f"t7-cal:p2-gold {field}")
        make_slim(field, sh.path(f"{GOLD}/data/fnfix/panels23_{field}_gold/pairs_none.parquet"),
                  root / f"slim_{field}")

    # ---- E: economics (ledger -> p1-econ -> split -> p2-econ -> slim) ------------------------
    stage("ledger", "ledger", root / "ledger", shadow=shadow_root)
    st = stage("p1_econ", "p1-econ", root / "p1_econ", execute=True, shadow=shadow_root)
    sh.install(f"{ECON}/data/analysis_frame_econ920_unified_fullsnap_2026-08-13.csv",
               st["run_dir"] / "data/analysis_frame_econ920_unified_fullsnap_2026-08-13.csv",
               "t7-cal:p1-econ")
    stage("split", "split", root / "split", shadow=shadow_root)
    st = stage("p2_econ", "p2-econ", root / "p2_econ", execute=True, shadow=shadow_root)
    for name in ("becoming_unified.csv", "pairs_unified.csv"):
        sh.install(f"{ECON}/data/{name}", st["run_dir"] / f"data/{name}", "t7-cal:p2-econ")
    make_slim("econ", sh.path(f"{ECON}/data/pairs_unified.csv"), root / "slim_econ")

    # ---- A: the A_far build over all three disciplines ---------------------------------------
    stage("afar", "afar", root / "afar", shadow=shadow_root)

    out_json.write_text(json.dumps(RESULT, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"CAL_REBUILD_DONE {len(RESULT)} entries -> {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
