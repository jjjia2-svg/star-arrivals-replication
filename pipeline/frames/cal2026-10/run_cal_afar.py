#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cal2026-10/run_cal_afar.py — the Panel 3 sweep of the October caliber: the verbatim `afar`
stage (legacy 50_leftbehind_build.py + 60_lb_tau.py through pipeline/frames/run_frames.py, exactly
as the 2026-08-28 driver's phase A ran it) over the October pair tables, then the pos / med cuts
(analysis/robustness/p3_afar_cuts/build_afar_cut.py, explicit sources) and the counts-by-spec
table the paper ledger reads (data/frames/p3_afar_counts_by_spec.csv had no builder in the
repository; its columns are the legacy lb_counts.csv columns, but the rates are the paper's raw
rates — rate_pre_pp = 100 x mean(y) over event time tau -6..-1, rate_post_pp = 100 x mean(y) over
tau 0..5 restricted to observable calendar years <= 2024 (analysis/paper/ledger_p3afar.py YEAR_CAP /
POST_TAUS; tau = year - the event's first D=1 year) — recovered by matching the frozen table on all
six rows (2026-09-23) and written down here. NB ledger_p3afar.py reports that column under the key
`rate_post_pp_allyears`; the value is the observable-years rate.)

Inputs, per discipline (a directory each; the October frames dirs by default):
  econ        pairs_unified.csv, p1_frame_econ.csv (the union P1 frame), p2_becoming_econ.csv,
              relationships.csv        — staged at the legacy econ_fnfix_2026-08-15/data/ names
  chemistry / math_stats
              pairs_none_<f>.parquet, p1_frame_<f>.csv, p2_becoming_<f>.csv
                                       — staged at the legacy multidisc_gold_2026-08-10 gold names
The shadow holds nothing else: the legacy scripts read only those files (V-rooted paths) and
write under their own BASE/data, which run_frames.py puts in the scratch run dir.

Outputs (--out): p3_afar_{f}.parquet (the lb A_far cell), p3_afar_{pos,med}_{f}.parquet,
p3_afar_counts.csv (= lb_counts.csv), p3_afar_tau_profile.csv (= lb_tau_profile.csv),
p3_afar_counts_by_spec.csv, afar_run_report.json (every input sha256, every output sha256).

--control  runs the same sweep on the 2026-08-28 inputs (chemistry/mathematics pair tables from
           data/cal2026-08-28/frames/, P1/P2 from data/frames/, economics from --econ-dir, which
           must hold the 08-28 pairs_unified.csv) and compares every output with the frozen
           canon in data/frames/: parquets content-equal (tools/content_equal.py), csv rows equal
           for the fields run. A field whose inputs are absent is skipped and reported, never
           silently passed.

    SAR_OUT_ROOT=/private/tmp/sar_afar setup/.venv/bin/python pipeline/frames/cal2026-10/run_cal_afar.py \
        --execute --econ-dir <dir> --out data/cal2026-10/frames [--control]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import sys
import time

import duckdb

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "pipeline/stars/caliber_2026-08-28"))
import frames_stage as fs08                                   # noqa: E402
import run_cal_frames as rcf                                  # noqa: E402
from pipeline.lib.paths import OUT_ROOT_ENV                   # noqa: E402
from tools.content_equal import content_equal                 # noqa: E402

_spec = importlib.util.spec_from_file_location("afar_cut", REPO / "analysis/robustness/p3_afar_cuts/build_afar_cut.py")
afar_cut = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(afar_cut)   # type: ignore[union-attr]

GOLD, ECON = rcf.GOLD, rcf.ECON
FIELDS = ("econ", "chemistry", "math_stats")
YEAR_CAP, POST_TAUS = 2024, (0, 5)     # = analysis/paper/ledger_p3afar.py (observable years; arrival .. +5)
FRAMES = REPO / "data" / "frames"
CAL10 = REPO / "data" / "cal2026-10"
REPORT: dict = {"generated": None, "inputs": {}, "stages": {}, "cuts": {}, "control": {}, "stops": []}
STOPS: list[str] = []


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def log(msg: str) -> None:
    print(f"[run_cal_afar] {msg}", flush=True)


def stop(msg: str) -> None:
    STOPS.append(msg); log("STOP: " + msg)


def stage_inputs(sh: fs08.Shadow, dirs: dict[str, pathlib.Path]) -> dict:
    """Install every input the legacy afar script reads, at the legacy name it reads it from."""
    plan = {
        "econ": [(f"{ECON}/data/pairs_unified.csv", "pairs_unified.csv"),
                 (f"{ECON}/data/analysis_frame_econ920_unified_fullsnap_2026-08-13.csv", "p1_frame_econ.csv"),
                 (f"{ECON}/data/becoming_unified.csv", "p2_becoming_econ.csv"),
                 (f"{ECON}/data/relationships.csv", "relationships.csv")],
    }
    for f in ("chemistry", "math_stats"):
        plan[f] = [(f"{GOLD}/data/fnfix/panels23_{f}_gold/pairs_none.parquet", f"pairs_none_{f}.parquet"),
                   (f"{GOLD}/data/fnfix/analysis_frame_{f}_new_gold_2026-08-10.csv", f"p1_frame_{f}.csv"),
                   (f"{GOLD}/data/fnfix/panels23_{f}_gold/becoming_none.csv", f"p2_becoming_{f}.csv")]
    staged = {}
    for f, items in plan.items():
        for rel, name in items:
            src = dirs[f] / name
            if not src.exists():
                raise FileNotFoundError(f"{f}: {src} (needed at {rel})")
            sh.install(rel, src, f"cal2026-10 afar input: {f} {name}")
            staged[rel] = {"from": str(src), "sha256": sh.entries[-1]["sha256"]}
    return staged


def cut_sources(f: str, d: pathlib.Path) -> dict:
    if f == "econ":
        return {"pairs": d / "pairs_unified.csv", "frame": d / "p1_frame_econ.csv", "p2": d / "p2_becoming_econ.csv"}
    return {"pairs": d / f"pairs_none_{f}.parquet", "frame": d / f"p1_frame_{f}.csv", "p2": d / f"p2_becoming_{f}.csv"}


def counts_row(field: str, spec: str, cut: float | None, parquet: pathlib.Path) -> dict:
    """One row of p3_afar_counts_by_spec.csv — the legacy lb_counts.csv summary on a cut frame."""
    con = duckdb.connect()
    con.execute(f"""CREATE TEMP TABLE d AS SELECT p.*, p.year - a.arrival AS tau FROM read_parquet('{parquet}') p
        JOIN (SELECT ev, min(year) AS arrival FROM read_parquet('{parquet}') WHERE D=1 GROUP BY ev) a USING (ev)""")
    s = con.execute("SELECT count(*), count(DISTINCT grp), sum(y), count(DISTINCT ev) FROM d").fetchone()
    pre_n, pre_t = con.execute("SELECT count(*), sum(y) FROM d WHERE tau BETWEEN -6 AND -1").fetchone()
    post_n, post_t = con.execute(f"SELECT count(*), sum(y) FROM d WHERE tau BETWEEN {POST_TAUS[0]} AND {POST_TAUS[1]} AND year <= {YEAR_CAP}").fetchone()
    con.close()
    pre = 100.0 * pre_t / pre_n if pre_n else None
    post = 100.0 * post_t / post_n if post_n else None
    return {"field": field, "cell": "A_far", "spec": spec, "cut": cut, "rows": s[0], "pairs": s[1],
            "ties": int(s[2] or 0), "events": s[3],
            "rate_pre_pp": round(pre, 6) if pre is not None else None,
            "rate_post_pp": round(post, 6) if post is not None else None,
            "diff_pp": round(post - pre, 6) if (pre is not None and post is not None) else None}


def write_counts_by_spec(rows: list[dict], out: pathlib.Path) -> None:
    cols = ["field", "cell", "spec", "cut", "rows", "pairs", "ties", "events", "rate_pre_pp", "rate_post_pp", "diff_pp"]
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(rows)


def csv_rows(p: pathlib.Path) -> list[dict]:
    with open(p, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def compare_csv_rows(got: pathlib.Path, exp: pathlib.Path, fields: set[str], key: str = "field") -> dict:
    g = [r for r in csv_rows(got) if r[key] in fields]
    e = [r for r in csv_rows(exp) if r[key] in fields]
    return {"equal": g == e, "rows_got": len(g), "rows_expected": len(e),
            "first_diff": next(({"got": a, "expected": b} for a, b in zip(g, e) if a != b), None) if g != e else None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--execute", action="store_true", help="required")
    ap.add_argument("--control", action="store_true", help="the 2026-08-28 inputs; compare with data/frames/")
    ap.add_argument("--econ-dir", required=True)
    ap.add_argument("--chem-dir", default=str(CAL10 / "frames_chemistry"))
    ap.add_argument("--math-dir", default=str(CAL10 / "frames_math_stats"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--fields", nargs="+", default=list(FIELDS), help="fields to CUT and COMPARE (the legacy afar stage always runs all three)")
    a = ap.parse_args(argv)
    if not a.execute:
        ap.error("--execute is required (nothing runs without it)")
    root = pathlib.Path(os.environ.get(OUT_ROOT_ENV, "")) if os.environ.get(OUT_ROOT_ENV) else None
    if root is None or str(root).startswith(str(pathlib.Path.home() / "Documents")):
        ap.error(f"set ${OUT_ROOT_ENV} to an empty scratch dir outside ~/Documents")
    root.mkdir(parents=True, exist_ok=True)
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    REPORT["generated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    REPORT["mode"] = "control (2026-08-28 inputs)" if a.control else "october (cal2026-10 inputs)"
    if a.control:
        ctl = root / "control_inputs"; ctl.mkdir(exist_ok=True)
        for f in ("chemistry", "math_stats"):
            for name, src in ((f"pairs_none_{f}.parquet", REPO / "data/cal2026-08-28/frames" / f"pairs_none_{f}.parquet"),
                              (f"p1_frame_{f}.csv", FRAMES / f"p1_frame_{f}.csv"), (f"p2_becoming_{f}.csv", FRAMES / f"p2_becoming_{f}.csv")):
                shutil.copyfile(src, ctl / name)
        dirs = {"econ": pathlib.Path(a.econ_dir), "chemistry": ctl, "math_stats": ctl}
    else:
        dirs = {"econ": pathlib.Path(a.econ_dir), "chemistry": pathlib.Path(a.chem_dir), "math_stats": pathlib.Path(a.math_dir)}
    REPORT["input_dirs"] = {k: str(v) for k, v in dirs.items()}

    # ---- S: shadow + the verbatim afar stage ----------------------------------------------------
    shadow_root = root / "shadow"
    sh = fs08.Shadow(shadow_root / "v2_output")
    REPORT["inputs"] = stage_inputs(sh, dirs)
    t0 = time.time()
    st = rcf.run_stage("afar", root / "cal_afar", (), shadow=shadow_root)
    REPORT["stages"]["afar"] = {"run_dir": str(st["run_dir"]), "secs": st["secs"], "produced": st["produced"]}
    rd = st["run_dir"] / "data"
    produced = {"p3_afar_counts.csv": rd / "lb_counts.csv", "p3_afar_tau_profile.csv": rd / "lb_tau_profile.csv"}
    for f in FIELDS:
        produced[f"p3_afar_{f}.parquet"] = rd / f"pairs_slim_lb_{f}_A_far.parquet"
    for name, p in produced.items():
        if not p.exists():
            stop(f"afar stage produced no {p.name}")
    if STOPS:
        (root / "afar_run_report_FAILED.json").write_text(json.dumps(REPORT | {"stops": STOPS}, indent=1, default=str)); return 1

    # ---- C: the pos / med cuts and counts-by-spec ---------------------------------------------
    cuts_dir = root / "cuts"; cuts_dir.mkdir(exist_ok=True)
    rows = []   # spec-major, field order econ / chemistry / math_stats — the frozen table's order
    for spec in ("pos", "med"):
        for f in [x for x in FIELDS if x in a.fields]:
            rep = afar_cut.build(f, spec, cuts_dir, sources=cut_sources(f, dirs[f]))
            REPORT["cuts"][f"{spec}_{f}"] = rep
            if "skipped" in rep:
                stop(f"cut {spec}/{f}: {rep['skipped']}"); continue
            rows.append(counts_row(f, spec, rep.get("cut_full", rep["cut"]), pathlib.Path(rep["frame"])))
    write_counts_by_spec(rows, cuts_dir / "p3_afar_counts_by_spec.csv")
    produced["p3_afar_counts_by_spec.csv"] = cuts_dir / "p3_afar_counts_by_spec.csv"
    for f in a.fields:
        for spec in ("pos", "med"):
            p = cuts_dir / f"p3_afar_{spec}_{f}.parquet"
            if p.exists():
                produced[p.name] = p
    # the med cut must reproduce the lb cell of the same run (build_afar_cut's own control)
    for f in a.fields:
        med, lb = cuts_dir / f"p3_afar_med_{f}.parquet", produced[f"p3_afar_{f}.parquet"]
        if med.exists():
            r = content_equal(med, lb)
            REPORT["cuts"][f"med_vs_lb_{f}"] = "EQUAL" if r.equal else "DIFF"
            if not r.equal:
                stop(f"{f}: med cut is not content-equal to the afar stage's A_far cell")

    # ---- K: control comparisons against data/frames/ -----------------------------------------
    if a.control:
        fields = set(a.fields)
        for f in a.fields:
            for name in (f"p3_afar_{f}.parquet", f"p3_afar_pos_{f}.parquet", f"p3_afar_med_{f}.parquet"):
                if name in produced:
                    r = content_equal(produced[name], FRAMES / name)
                    REPORT["control"][name] = "EQUAL" if r.equal else "DIFF"
                    if not r.equal:
                        stop(f"control: {name} differs from data/frames")
        for name in ("p3_afar_counts.csv", "p3_afar_tau_profile.csv", "p3_afar_counts_by_spec.csv"):
            r = compare_csv_rows(produced[name], FRAMES / name, fields)
            REPORT["control"][name] = r
            if not r["equal"]:
                stop(f"control: {name} rows differ from data/frames for {sorted(fields)}: {r['first_diff']}")

    # ---- F: outputs -----------------------------------------------------------------------------
    REPORT["total_secs"] = round(time.time() - t0, 1)
    REPORT["stops"] = STOPS
    if STOPS:
        (root / "afar_run_report_FAILED.json").write_text(json.dumps(REPORT, indent=1, default=str), encoding="utf-8")
        log(f"{len(STOPS)} STOP(s); nothing written to {out}; report {root / 'afar_run_report_FAILED.json'}"); return 1
    outputs = {}
    for name, p in produced.items():
        dest = out / name; shutil.copyfile(p, dest); outputs[name] = sha(dest)
    REPORT["outputs"] = outputs
    (out / "afar_run_report.json").write_text(json.dumps(REPORT, indent=1, default=str) + "\n", encoding="utf-8")
    log(f"wrote {len(outputs)} files to {out}; afar stage {st['secs']} s; mode = {REPORT['mode']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
