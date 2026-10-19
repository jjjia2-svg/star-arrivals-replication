#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_nocentre.py — the ± research-centre roster check on the CANON event set (T6-1).

Old design (2026-08-10, `v2_output/multidisc_gold_2026-08-10/results/{final,incfel}/out`):
chemistry and math_stats estimated twice, once on the population WITH the research-centre
academic staff merged into the department rosters (the author's 2026-08-10 decision that research
centres count as departments — the canon population; +134 chemistry / +28 math people) and once WITHOUT them (the incfel
roster, the same frozen artifact the old run used). The old check covered P1, P2 and the
math_stats full P3 (chemistry P3 needs the cloud); economics has no ± variant — its centres
were already inside the department rosters by the same ruling, no separate centre supplement
exists.

This launcher re-runs that comparison on the canon caliber (38/33 events) with the caliber
staging machinery: `frames_stage.build_shadow` builds the exact cal shadow, then the ONE
substitution — the roster link `multidisc_gold_2026-08-10/data/fnfix/roster_gold_{field}.parquet`
re-pointed at the frozen INCFEL roster (`.../data/incfel/roster_gold_{field}.parquet`) — and
the ported builders run over it unchanged (prodlib -> union-gold -> p1-gold -> p2-gold ->
make_slim), exactly as `run_cal_frames.py` drives them.

CONTROL FIRST: the same launcher with the unchanged (fnfix = centre-inclusive) roster must
reproduce the canon frames — relationships.csv and becoming byte-identical, the P1 frames
equal up to the documented H1 characterisation (fwci columns only, <=8 ULP), and the verbatim
run_p1.R on the control frames compare_json-EQUAL to the frozen golds. A control that fails
STOPS the run.

    export SAR_OUT_ROOT=/private/tmp/<empty dir>
    setup/.venv/bin/python analysis/robustness/sensitivity/run_nocentre.py --execute

Results -> data/robustness_2026-08-29_b/nocentre/ (estimates + report; frames stay in scratch,
regenerable by this launcher).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
CAL = REPO / "pipeline/stars/caliber_2026-08-28"
for p in (str(REPO), str(CAL)):
    if p not in sys.path:
        sys.path.insert(0, p)

from pipeline.lib.paths import OUT_ROOT_ENV, PathUnresolved  # noqa: E402
import frames_stage as fs                                    # noqa: E402
import run_cal_frames as rcf                                 # noqa: E402

GOLD = "multidisc_gold_2026-08-10"
FIELDS = ("chemistry", "math_stats")
OUT = REPO / os.environ.get("SAR_ROBUST_OUTDIR", "data/robustness_2026-08-29_b/nocentre")  # 2026-09-23: env override, old value default
REPORT: dict = {}


def characterise(frozen: pathlib.Path, rebuilt: pathlib.Path, allowed: tuple[str, ...]) -> dict:
    """Same-line-count comparison; only `allowed` float columns may differ, each within 8 ULP
    (the H1 characterisation of the ported union builder, run_cal_frames.union_characterise)."""
    fa = open(frozen, newline="", encoding="utf-8").readlines()
    fb = open(rebuilt, newline="", encoding="utf-8").readlines()
    if len(fa) != len(fb):
        return {"ok": False, "reason": f"line counts differ {len(fa)} vs {len(fb)}"}
    cols = next(csv.reader([fa[0]]))
    n, worst, badcols = 0, 0, set()
    for a, b in zip(fa[1:], fb[1:]):
        if a == b:
            continue
        n += 1
        ca, cb = next(csv.reader([a])), next(csv.reader([b]))
        for j, (x, y) in enumerate(zip(ca, cb)):
            if x != y:
                if cols[j] not in allowed:
                    badcols.add(cols[j])
                else:
                    try:
                        worst = max(worst, fs.ulps(float(x), float(y)))
                    except ValueError:
                        badcols.add(cols[j])
    return {"ok": not badcols and worst <= 8, "differing_lines": n, "worst_ulp": worst,
            "unexpected_columns": sorted(badcols)}


def build_variant(root: pathlib.Path, nocentre: bool) -> dict[str, pathlib.Path]:
    """One full chem/math frames build over a shadow; returns the produced files."""
    shadow_root = root / "shadow"
    sh, _surgery = fs.build_shadow(shadow_root)
    v2 = fs.real_v2()
    if nocentre:
        for field in FIELDS:
            rel = f"{GOLD}/data/fnfix/roster_gold_{field}.parquet"
            src = v2 / GOLD / "data/incfel" / f"roster_gold_{field}.parquet"
            sh.link_frozen(rel, src)
            sh.entries[-1]["origin"] = f"VARIANT:incfel (no-centre) roster <- {src}"
    produced: dict[str, pathlib.Path] = {}
    for field in FIELDS:
        out = rcf.run_prodlib(field, root / f"prodlib_{field}", shadow_root, REPORT)
        sh.install(f"{GOLD}/runs/fnfix/{field}/data/analysis_frame_p01_52ev_topicdose_2026-07-21.csv",
                   out, f"stage:prodlib {field}")
        st = rcf.run_stage("union-gold", root / f"union_{field}", ("--field", field),
                           execute=True, shadow=shadow_root)
        for name in (f"analysis_frame_{field}_2026-08-10.csv", "relationships.csv",
                     "build_report.json", "funnel.json"):
            sh.install(f"{GOLD}/data/fnfix/union_frame_{field}/{name}",
                       st["run_dir"] / f"data/fnfix/union_frame_{field}/{name}",
                       f"stage:union-gold {field}")
        produced[f"relationships_{field}"] = \
            sh.path(f"{GOLD}/data/fnfix/union_frame_{field}/relationships.csv")
        st = rcf.run_stage("p1-gold", root / f"p1_{field}", ("--field", field),
                           execute=True, shadow=shadow_root)
        sh.install(f"{GOLD}/data/fnfix/analysis_frame_{field}_new_gold_2026-08-10.csv",
                   st["run_dir"] / f"data/fnfix/analysis_frame_{field}_new_gold_2026-08-10.csv",
                   f"stage:p1-gold {field}")
        produced[f"p1_{field}"] = \
            sh.path(f"{GOLD}/data/fnfix/analysis_frame_{field}_new_gold_2026-08-10.csv")
        st = rcf.run_stage("p2-gold", root / f"p2_{field}", ("--field", field, "--panel3", "full"),
                           execute=True, shadow=shadow_root)
        for name in ("becoming_none.csv", "pairs_none.parquet"):
            sh.install(f"{GOLD}/data/fnfix/panels23_{field}_gold/{name}",
                       st["run_dir"] / f"data/fnfix/panels23_{field}_gold/{name}",
                       f"stage:p2-gold {field}")
        produced[f"p2_{field}"] = sh.path(f"{GOLD}/data/fnfix/panels23_{field}_gold/becoming_none.csv")
        produced[f"pairs_{field}"] = sh.path(f"{GOLD}/data/fnfix/panels23_{field}_gold/pairs_none.parquet")
    slim = rcf.run_make_slim("math_stats", produced["pairs_math_stats"], root / "slim_math")
    produced["slim_math_stats"] = slim["noev"]
    produced["slim_ev_math_stats"] = slim["ev"]
    REPORT.setdefault("slim_stats", {})["nocentre" if nocentre else "control"] = slim["stats"]
    (root / "staging_manifest.json").write_text(
        json.dumps({"entries": sh.manifest()}, indent=1), encoding="utf-8")
    return produced


def estimate(label: str, driver: str, frame: pathlib.Path, out_dir: pathlib.Path,
             extra: tuple[str, ...] = ()) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "SAR_OUT": str(out_dir), "POLARS_MAX_THREADS": "4"}
    proc = subprocess.run(["Rscript", str(REPO / "analysis/estimation" / driver), label,
                           str(frame), *extra], cwd=REPO, capture_output=True, text=True, env=env)
    assert proc.returncode == 0, f"{label}: {proc.stdout[-800:]}{proc.stderr[-800:]}"
    print("   " + [l for l in proc.stdout.splitlines() if "ATE=" in l or "FAIL" in l][-1]
          if any("ATE=" in l or "FAIL" in l for l in proc.stdout.splitlines()) else proc.stdout[-200:])
    return out_dir / f"{label}.json"


def compare_equal(new: pathlib.Path, gold: pathlib.Path) -> bool:
    proc = subprocess.run([sys.executable, "-m", "analysis.lib.compare_json", str(new), str(gold)],
                          cwd=REPO, capture_output=True, text=True)
    return proc.returncode == 0 and "EQUAL" in proc.stdout and "NOT" not in proc.stdout


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--execute", action="store_true",
                    help="required: SSD-scanning builder runs (minutes, data disk)")
    args = ap.parse_args(argv)
    if not args.execute:
        print("Drives the chem/math frame builders four times against the data disk (minutes). "
              "Re-run with --execute.", file=sys.stderr)
        return 2
    out_root = os.environ.get(OUT_ROOT_ENV, "").strip()
    if not out_root:
        raise PathUnresolved(f"set ${OUT_ROOT_ENV} to an empty absolute dir under /private/tmp")
    root = pathlib.Path(out_root)
    if root.exists() and any(root.iterdir()):
        raise PathUnresolved(f"${OUT_ROOT_ENV} must be empty: {root}")
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # ---- control: unchanged roster must reproduce the canon frames end-to-end ---------------
    print("== control build (fnfix roster = with centres)")
    ctl = build_variant(root / "control", nocentre=False)
    checks: dict = {}
    for field in FIELDS:
        checks[f"relationships_{field}"] = (
            "BYTE_EQUAL" if fs.sha(ctl[f"relationships_{field}"]) ==
            fs.sha(REPO / f"data/cal2026-08-28/frames/relationships_{field}.csv") else "NOT_EQUAL")
        checks[f"becoming_{field}"] = (
            "BYTE_EQUAL" if fs.sha(ctl[f"p2_{field}"]) ==
            fs.sha(REPO / f"data/frames/p2_becoming_{field}.csv") else "NOT_EQUAL")
        ch = characterise(REPO / f"data/frames/p1_frame_{field}.csv", ctl[f"p1_{field}"],
                          ("fwci_frac", "fwci_frac_ex_star", "fwci_mean", "fwci_mean_ex_star"))
        checks[f"p1_frame_{field}"] = ch
    REPORT["control_checks"] = checks
    hard_fail = [k for k, v in checks.items()
                 if (v == "NOT_EQUAL") or (isinstance(v, dict) and not v["ok"])]
    assert not hard_fail, f"control did NOT reproduce the canon frames: {hard_fail} — STOP"
    print("   control frames reproduce canon:",
          {k: (v if isinstance(v, str) else f"H1 ok worst_ulp={v['worst_ulp']}")
           for k, v in checks.items()})
    est_ctl = OUT / "estimates_control"
    gold = {"chemistry": "P1_fnfix_chemistry", "math_stats": "P1_fnfix_math_stats"}
    for field in FIELDS:
        j = estimate(f"{gold[field]}", "run_p1.R", ctl[f"p1_{field}"], est_ctl)
        eq = compare_equal(j, REPO / f"analysis/expected/{gold[field]}.json")
        REPORT.setdefault("control_estimates", {})[gold[field]] = "EQUAL" if eq else "NOT_EQUAL"
        assert eq, f"control estimate {gold[field]} is NOT compare_json-EQUAL to the gold — STOP"
    print("   control estimates EQUAL to frozen golds: 2/2")

    # ---- the no-centre variant ---------------------------------------------------------------
    print("== no-centre build (incfel roster)")
    var = build_variant(root / "nocentre", nocentre=True)
    est = OUT / "estimates"
    cells = []
    for field in FIELDS:
        cells.append(estimate(f"P1nc_{field}", "run_p1.R", var[f"p1_{field}"], est))
        cells.append(estimate(f"P2nc_{field}", "run_p2.R", var[f"p2_{field}"], est))
    cells.append(estimate("P3nc_math_stats_full", "run_p3.R", var["slim_math_stats"], est))
    REPORT["variant_frames_sha256"] = {k: fs.sha(v) for k, v in sorted(var.items())}
    REPORT["secs"] = round(time.time() - t0, 1)
    (OUT / "nocentre_run_report.json").write_text(
        json.dumps(REPORT, indent=1, default=str) + "\n", encoding="utf-8")
    print(f"NOCENTRE_OK ({REPORT['secs']} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
