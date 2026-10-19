#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_nocentre_afar_pos.py — the ± research-centre check for Panel 3 on the CURRENT specification
(dose > 0, `pos`), chemistry and math_stats. 2026-09-10, local, $0.

WHAT IS MISSING AND WHY
    run_nocentre.py (T6-1, 2026-08-29) rebuilt the chemistry / math_stats frames with ONE
    substitution — the roster link re-pointed at the frozen INCFEL roster, i.e. the population
    WITHOUT the research-centre academic staff (−134 chem / −28 math people) — and estimated the
    P1, P2 and P3-full-math cells on them (frozen in data/robustness_2026-08-29_b/nocentre/). It
    never estimated the paper's Panel 3 cell, and the paper's Panel 3 since 2026-08-30 is the A_far
    `pos` cut (both incumbents share at least one subfield with the star, dose > 0; frames
    data/frames/p3_afar_pos_{field}.parquet, golds analysis/expected/P3pos_{field}_A_far.json).
    Economics has no ± variant by design (run_nocentre.py:10-12): its centres were already inside
    the department rosters by the 2026-08-10 ruling. Nothing is invented for it.

WHAT THIS DOES (nothing new is coded for the build or the estimate)
    1. `run_nocentre.build_variant` verbatim — the caliber staging machinery (`frames_stage.build_shadow`
       + the ported builders prodlib -> union-gold -> p1-gold -> p2-gold -> make_slim) — first with
       the unchanged (with-centre) roster, then with the incfel roster.
    2. `build_afar_cut.build(field, "pos", <scratch>, sources=...)` on each build's p1 frame /
       becoming / pairs_none — `SOURCES` re-pointed by the explicit `sources` parameter added on
       2026-09-10; no SQL copied.
    3. the VERBATIM analysis/estimation/run_p3_tp.R, output dir from $SAR_OUT.

CONTROL FIRST — any failure STOPS before a variant cell is estimated:
    (a) the with-centre build reproduces canon: relationships.csv and becoming byte-identical,
        the P1 frames within the documented H1 characterisation (fwci columns only, <= 8 ULP) —
        run_nocentre's own checks, unchanged;
    (b) the with-centre build's `pos` A_far frame is CONTENT-EQUAL to the frozen
        data/frames/p3_afar_pos_{field}.parquet (every column, rows compared sorted by (grp, year)
        — the afar_event_map.py proof), so the re-pointed SOURCES are proven faithful;
    (c) run_p3_tp.R on that control frame, run under the gold's own label P3cut_pos_{field}
        (analysis/run_all.sh:82-85), is compare_json-EQUAL to analysis/expected/P3pos_{field}_A_far.json;
    (d) the no-centre build is the 2026-08-29 variant: its byte-stable relationships.csv and
        becoming_none.csv must match the sha256 frozen in nocentre_run_report.json (the P1nc/P2nc
        cells frozen there were estimated on exactly those files); the P1 frame and the parquets
        are compared informationally only (fwci ULP noise / parquet not byte-stable, deviation D1).

WRITES (never into the frozen data/robustness_2026-08-29_b/ tree)
    data/robustness_2026-09-10_p3pos/nocentre/estimates/P3nc_pos_{field}_A_far.json      the two cells
    data/robustness_2026-09-10_p3pos/nocentre/estimates_control/P3cut_pos_{field}.json   control (c)
    data/robustness_2026-09-10_p3pos/nocentre/nocentre_afar_pos_report.json              every control verdict,
                                                                                         counts, sha256
    Frames stay in $SAR_OUT_ROOT (scratch, regenerable by this launcher in ~4 min with the data disk).

    export SAR_OUT_ROOT=/private/tmp/<empty dir>
    setup/.venv/bin/python analysis/robustness/sensitivity/run_nocentre_afar_pos.py --execute
    (entry point with the MANIFEST step: run_nocentre_afar_pos.sh)
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import run_nocentre as rn                                      # noqa: E402  (its main() is NOT run)
import frames_stage as fs                                      # noqa: E402  (on sys.path via rn)
from pipeline.lib.paths import OUT_ROOT_ENV, PathUnresolved    # noqa: E402
from analysis.robustness.p3_afar_cuts import build_afar_cut    # noqa: E402

FIELDS = rn.FIELDS                                             # ("chemistry", "math_stats")
OUT = REPO / os.environ.get("SAR_ROBUST_OUTDIR_P3POS", "data/robustness_2026-09-10_p3pos/nocentre")  # 2026-09-23: env override, old value default
FROZEN_OLD = REPO / "data/robustness_2026-08-29_b"
OLD_REPORT = FROZEN_OLD / "nocentre/nocentre_run_report.json"
FROZEN_POS = "data/frames/p3_afar_pos_{field}.parquet"
GOLD = "analysis/expected/P3pos_{field}_A_far.json"
GOLD_LABEL = "P3cut_pos_{field}"            # the gold's own label (run_all.sh renames the file, not the label)
CELL_LABEL = "P3nc_pos_{field}_A_far"
FRAME_COLS = ["grp", "ev", "year", "y", "D"]
#: the variant files whose bytes are stable run to run (the control demands BYTE_EQUAL for them)
BYTE_STABLE = ("relationships_{field}", "p2_{field}")


def sources_of(produced: dict, field: str) -> dict:
    """The three inputs build_afar_cut.build needs, from a build_variant() result."""
    return {"pairs": produced[f"pairs_{field}"], "frame": produced[f"p1_{field}"],
            "p2": produced[f"p2_{field}"]}


def content_equal(new: pathlib.Path, frozen: pathlib.Path) -> dict:
    """afar_event_map.py's proof: same columns, same row count, every value equal after sorting
    by (grp, year) — (grp, year) is a key because grp is DENSE_RANK over pair@event."""
    a, b = pd.read_parquet(new), pd.read_parquet(frozen)
    same_cols = list(a.columns) == FRAME_COLS and list(b.columns) == FRAME_COLS
    a = a.sort_values(["grp", "year"]).reset_index(drop=True)
    b = b.sort_values(["grp", "year"]).reset_index(drop=True)
    eq = same_cols and len(a) == len(b) and a.astype("int64").equals(b.astype("int64"))
    return {"verdict": "CONTENT_EQUAL" if eq else "NOT_EQUAL", "rows_rebuilt": int(len(a)),
            "rows_frozen": int(len(b)), "columns_ok": same_cols}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--execute", action="store_true",
                    help="required: two chem/math frame builds against the data disk (minutes)")
    args = ap.parse_args(argv)
    if not args.execute:
        print("Drives the chem/math frame builders twice against the data disk (~4 min), builds the "
              "pos A_far cells and estimates them. Re-run with --execute.", file=sys.stderr)
        return 2
    out_root = os.environ.get(OUT_ROOT_ENV, "").strip()
    if not out_root:
        raise PathUnresolved(f"set ${OUT_ROOT_ENV} to an empty absolute dir under /private/tmp")
    root = pathlib.Path(out_root)
    if not root.is_absolute() or root == REPO or REPO in root.parents:
        raise PathUnresolved(f"${OUT_ROOT_ENV} must be absolute and outside the repository: {root}")
    if root.exists() and any(root.iterdir()):
        raise PathUnresolved(f"${OUT_ROOT_ENV} must be empty: {root}")
    assert FROZEN_OLD not in OUT.parents and OUT != rn.OUT, "would write into the frozen 2026-08-29 tree"
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    report: dict = {"generated": "2026-09-10", "spec": "pos",
                    "predicate": "dmin > 0 AND net_i=0 AND net_j=0  (A_far, build_afar_cut.py `pos`)",
                    "fields": list(FIELDS), "scratch_root": str(root),
                    "estimator": "analysis/estimation/run_p3_tp.R (verbatim)",
                    "control_checks": {}, "control_afar_pos": {}, "control_estimates": {},
                    "variant_afar_pos": {}, "variant_vs_2026-08-29": {}}

    def freeze(**extra):
        report.update(extra)
        report["secs"] = round(time.time() - t0, 1)
        (OUT / "nocentre_afar_pos_report.json").write_text(
            json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8")

    # ---- (a) control build: the unchanged roster must reproduce the canon frames ------------
    print("== control build (fnfix roster = with centres)")
    ctl = rn.build_variant(root / "control", nocentre=False)
    checks: dict = {}
    for field in FIELDS:
        checks[f"relationships_{field}"] = (
            "BYTE_EQUAL" if fs.sha(ctl[f"relationships_{field}"]) ==
            fs.sha(REPO / f"data/cal2026-08-28/frames/relationships_{field}.csv") else "NOT_EQUAL")
        checks[f"becoming_{field}"] = (
            "BYTE_EQUAL" if fs.sha(ctl[f"p2_{field}"]) ==
            fs.sha(REPO / f"data/frames/p2_becoming_{field}.csv") else "NOT_EQUAL")
        checks[f"p1_frame_{field}"] = rn.characterise(
            REPO / f"data/frames/p1_frame_{field}.csv", ctl[f"p1_{field}"],
            ("fwci_frac", "fwci_frac_ex_star", "fwci_mean", "fwci_mean_ex_star"))
    report["control_checks"] = checks
    hard_fail = [k for k, v in checks.items()
                 if (v == "NOT_EQUAL") or (isinstance(v, dict) and not v["ok"])]
    if hard_fail:
        freeze(status="STOP: control build did not reproduce the canon frames", failed=hard_fail)
        raise AssertionError(f"control did NOT reproduce the canon frames: {hard_fail} — STOP")
    print("   control frames reproduce canon:",
          {k: (v if isinstance(v, str) else f"H1 ok worst_ulp={v['worst_ulp']}")
           for k, v in checks.items()})

    # ---- (b) control pos A_far frame CONTENT-EQUAL to the frozen frame ----------------------
    print("== control pos A_far cut (re-pointed SOURCES on the with-centre build)")
    ctl_frames: dict[str, pathlib.Path] = {}
    for field in FIELDS:
        b = build_afar_cut.build(field, "pos", root / "afar_control", sources=sources_of(ctl, field))
        ctl_frames[field] = pathlib.Path(b["frame"])
        ce = content_equal(ctl_frames[field], REPO / FROZEN_POS.format(field=field))
        report["control_afar_pos"][field] = {**b, "frozen": FROZEN_POS.format(field=field), **ce}
        print(f"   {field}: rows={b['rows']:,} pairs={b['pairs']:,} ties={b['ties']:,} "
              f"events={b['events']} -> {ce['verdict']}")
        if ce["verdict"] != "CONTENT_EQUAL":
            freeze(status=f"STOP: control pos frame {field} is NOT content-equal to the frozen frame")
            raise AssertionError(f"control pos A_far frame {field} NOT content-equal — STOP")

    # ---- (c) control estimate compare_json-EQUAL to the gold --------------------------------
    print("== control estimates (verbatim run_p3_tp.R, gold label P3cut_pos_<field>)")
    est_ctl = OUT / "estimates_control"
    for field in FIELDS:
        j = rn.estimate(GOLD_LABEL.format(field=field), "run_p3_tp.R", ctl_frames[field], est_ctl)
        eq = rn.compare_equal(j, REPO / GOLD.format(field=field))
        report["control_estimates"][GOLD_LABEL.format(field=field)] = {
            "gold": GOLD.format(field=field), "verdict": "EQUAL" if eq else "NOT_EQUAL"}
        if not eq:
            freeze(status=f"STOP: control estimate {field} NOT compare_json-EQUAL to the gold")
            raise AssertionError(f"control estimate {field} is NOT compare_json-EQUAL — STOP")
    print(f"   control estimates EQUAL to frozen golds: {len(FIELDS)}/{len(FIELDS)}")

    # ---- (d) the no-centre variant, checked against the 2026-08-29 frozen sha256 -------------
    print("== no-centre build (incfel roster)")
    var = rn.build_variant(root / "nocentre", nocentre=True)
    old = json.loads(OLD_REPORT.read_text(encoding="utf-8"))["variant_frames_sha256"]
    var_sha = {k: fs.sha(v) for k, v in sorted(var.items())}
    vs = {k: ("EQUAL" if old.get(k) == h else "NOT_EQUAL") for k, h in var_sha.items()}
    report["variant_frames_sha256"] = var_sha
    report["variant_vs_2026-08-29"] = {
        "byte_stable_files_must_match": [p.format(field=f) for f in FIELDS for p in BYTE_STABLE],
        "verdicts": vs,
        "note": "p1 frames carry fwci ULP noise (H1) and parquets are not byte-stable (D1): informational"}
    stable_bad = [p.format(field=f) for f in FIELDS for p in BYTE_STABLE
                  if vs[p.format(field=f)] != "EQUAL"]
    if stable_bad:
        freeze(status="STOP: no-centre build is not the 2026-08-29 variant", failed=stable_bad)
        raise AssertionError(f"no-centre relationships/becoming differ from the 2026-08-29 run: "
                             f"{stable_bad} — STOP")
    print("   no-centre frames vs 2026-08-29:", vs)

    print("== no-centre pos A_far cells")
    est = OUT / "estimates"
    for field in FIELDS:
        b = build_afar_cut.build(field, "pos", root / "afar_nocentre", sources=sources_of(var, field))
        frame = pathlib.Path(b["frame"])
        report["variant_afar_pos"][field] = {**b, "sha256": fs.sha(frame),
                                             "inputs_sha256": {k: fs.sha(v) for k, v in
                                                               sources_of(var, field).items()}}
        print(f"   {field}: rows={b['rows']:,} pairs={b['pairs']:,} ties={b['ties']:,} events={b['events']}")
        rn.estimate(CELL_LABEL.format(field=field), "run_p3_tp.R", frame, est)
    freeze(status="OK", build_variant_report=rn.REPORT)
    print(f"NOCENTRE_AFAR_POS_OK ({report['secs']} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
