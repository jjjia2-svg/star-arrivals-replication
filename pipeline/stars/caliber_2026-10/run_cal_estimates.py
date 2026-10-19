#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""caliber_2026-10/run_cal_estimates.py — every locally runnable estimation cell on the October
frames, plus the pos/med Panel 3 cuts and the old-vs-new comparison. Repo-authored launcher; runs
NO ported python — the VERBATIM R drivers in analysis/estimation/ through their own contract
(argv + $SAR_OUT), exactly as analysis/run_all.sh does, and the pos/med cut builder
analysis/robustness/p3_afar_cuts/build_afar_cut.py with explicit sources.

    export SAR_OUT_ROOT=/private/tmp/<empty dir>
    setup/.venv/bin/python pipeline/stars/caliber_2026-10/run_cal_estimates.py --execute [--control]

Phases
  V  the frames a cell consumes are hashed (recorded; under --control they are the 2026-08-28
     frozen frames and every cell must be compare_json-EQUAL to analysis/expected — the positive
     control of this driver and of the R environment).
  A  Panel 3 cuts: build_afar_cut.build(field, "pos"/"med", sources = the frames of this run);
     `med` also serves as p3_afar_<field>.parquet (the former A_far stage; build_afar_cut's
     docstring: a run at med reproduces the canonical frame exactly).
  R  the 28 local cells sequentially (19 of the 08-28 inventory + 3 P3lb + 6 P3pos/P3med), the
     evcl cells' third argument = this run's own person/pair-cluster JSON; P1_econ_fnfix run
     twice in separate dirs (determinism). Errors STOP; nothing is patched.
  C  old (analysis/expected) vs new comparison: ATE/SE/p/N/events per variant, flags for sign
     changes, p crossing .05/.01, |dATE| > 20 %, CI zero-crossing changes.
  F  freeze into <cal>/estimates/ (result JSONs + determinism re-run + run report) and
     <cal>/cuts_report.json; MANIFEST.sha256 of <cal> regenerated (pure addition).
The four cloud cells (P3_econ_fnfix, P3_fnfix_chemistry, P3evcl_econ, P3evcl_chemistry) are the
AWS launcher's (pipeline/aws/cal2026-10/), never run here.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))
from analysis.lib.compare_json import compare          # noqa: E402
from pipeline.lib.paths import OUT_ROOT_ENV, PathUnresolved  # noqa: E402

# the 08-28 driver's extraction/flag helpers, reused unchanged
_spec = importlib.util.spec_from_file_location("rce_0828", REPO / "pipeline/stars/caliber_2026-08-28/run_cal_estimates.py")
rce = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(rce)   # type: ignore[union-attr]
_spec2 = importlib.util.spec_from_file_location("afar_cut", REPO / "analysis/robustness/p3_afar_cuts/build_afar_cut.py")
afar_cut = importlib.util.module_from_spec(_spec2); _spec2.loader.exec_module(afar_cut)   # type: ignore[union-attr]

CAL_DIR = REPO / "data" / "cal2026-10"
EXPECTED = REPO / "analysis" / "expected"
EST_DRV = REPO / "analysis" / "estimation"
CELL_TIMEOUT_S = 1860
FIELDS = ("econ", "chemistry", "math_stats")
Cell = rce.Cell

LOCAL_CELLS: tuple = tuple(rce.LOCAL_CELLS) + tuple(
    Cell(f"P3{spec}_{f}_A_far", "run_p3_tp.R", f"p3_afar_{spec}_{f}.parquet", None)
    for f in ("math_stats", "chemistry", "econ") for spec in ("pos", "med"))
#: the 08-28 driver's `new37 -> new38` alias is stale: commit a22a27e renamed the gold to
#: P1_econ_fnfix_new37.json. Keep an alias only while its target still exists.
FROZEN_NAME = {k: v for k, v in rce.FROZEN_NAME.items() if (EXPECTED / (v + ".json")).exists()}
GOLD_0828 = REPO / "data" / "cal2026-08-28" / "estimates"
CUTS_0830 = REPO / "data" / "robustness_afar_cuts_2026-08-30" / "estimates"


def gold_0828(cell: str) -> pathlib.Path:
    """The frozen 2026-08-28 gold of a cell (pos/med cuts: the 2026-08-30 respecification run)."""
    m = re.fullmatch(r"P3(pos|med)_(econ|chemistry|math_stats)_A_far", cell)
    if m:
        return CUTS_0830 / f"P3cut_{m.group(1)}_{m.group(2)}.json"
    return GOLD_0828 / (FROZEN_NAME.get(cell, cell) + ".json")
#: run_p3_tp.R names its output after the label; the pos/med golds are keyed P3<spec>_<field>_A_far
#: but the R label must be P3cut_<spec>_<field> (analysis/run_all.sh does the same rename).
R_LABEL = {f"P3{spec}_{f}_A_far": f"P3cut_{spec}_{f}" for f in FIELDS for spec in ("pos", "med")}

STOPS: list[str] = []
REPORT: dict = {"task": "cal2026-10 local estimation"}


def log(msg: str) -> None:
    print(f"[run_cal_estimates 2026-10] {msg}", flush=True)


def stop(msg: str) -> None:
    STOPS.append(msg); print(f"\n*** STOP: {msg}", flush=True)


def _jl(p: pathlib.Path) -> dict:
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_cell(cell, frames: pathlib.Path, run_dir: pathlib.Path, ref_dir: pathlib.Path) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    label = R_LABEL.get(cell.name, cell.name)
    argv = ["Rscript", str(EST_DRV / cell.driver), label, str(frames / cell.frame)]
    if cell.ref is not None:
        argv.append(str(ref_dir / f"{cell.ref}.json"))
    env = dict(os.environ, SAR_OUT=str(run_dir), PYTHONHASHSEED="0")
    logf = run_dir / f"{cell.name}.log"
    t0 = time.time()
    rec = {"cell": cell.name, "driver": cell.driver, "frame": str(frames / cell.frame), "ref": cell.ref}
    log(f"cell {cell.name}: {cell.driver} on {cell.frame}" + (f" (ref {cell.ref})" if cell.ref else ""))
    try:
        with open(logf, "wb") as lf:
            r = subprocess.run(argv, cwd=REPO, env=env, timeout=CELL_TIMEOUT_S, stdout=lf, stderr=subprocess.STDOUT)
    except subprocess.TimeoutExpired:
        rec.update(status="TIMEOUT", secs=round(time.time() - t0, 1)); stop(f"{cell.name} exceeded {CELL_TIMEOUT_S}s"); return rec
    rec["secs"] = round(time.time() - t0, 1)
    tail = logf.read_bytes()[-2000:].decode("utf-8", "replace")
    produced = run_dir / f"{label}.json"
    if r.returncode != 0 or not produced.is_file():
        rec.update(status="CELL_ERROR", returncode=r.returncode, log_tail=tail); stop(f"{cell.name} errored (rc={r.returncode}); log: {logf}"); return rec
    if label != cell.name:
        produced.rename(run_dir / f"{cell.name}.json"); produced = run_dir / f"{cell.name}.json"
    j = json.loads(produced.read_text(encoding="utf-8"))
    bad = rce._not_ok(j)
    if bad:
        rec.update(status="CELL_ERROR", log_tail=tail, detail=bad); stop(f"{cell.name} non-OK ({bad}); log: {logf}"); return rec
    rec.update(status="OK", json_sha=sha(produced))
    return rec


def build_cuts(frames: pathlib.Path, pairs_econ: pathlib.Path, out: pathlib.Path) -> dict:
    """pos and med cuts for the three fields from THIS run's frames; med -> p3_afar_<field>.parquet."""
    rep = {}
    for f in FIELDS:
        pairs = pairs_econ if f == "econ" else frames / f"pairs_none_{f}.parquet"
        src = {"pairs": pairs, "frame": frames / f"p1_frame_{f}.csv", "p2": frames / f"p2_becoming_{f}.csv"}
        for spec in ("pos", "med"):
            rep[f"{spec}_{f}"] = afar_cut.build(f, spec, out, sources=src)
            log(f"cut {spec}/{f}: {json.dumps({k: v for k, v in rep[f'{spec}_{f}'].items() if k in ('rows', 'pairs', 'events', 'ties', 'skipped')})}")
        med = out / f"p3_afar_med_{f}.parquet"
        if med.exists():
            shutil.copyfile(med, out / f"p3_afar_{f}.parquet")
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--control", action="store_true", help="run on the 2026-08-28 frozen frames; every cell must be EQUAL to analysis/expected")
    ap.add_argument("--frames-dir", default=str(CAL_DIR / "frames"))
    ap.add_argument("--pairs-econ", default=str(REPO / "output/cal_intermediates/pairs_unified.csv"))
    ap.add_argument("--refreeze", action="store_true")
    args = ap.parse_args(argv)
    if not args.execute:
        print("Runs ~30 dCDH cells (minutes of R). Re-run with --execute.", file=sys.stderr); return 2
    out_root = pathlib.Path(os.environ.get(OUT_ROOT_ENV, "").strip() or "")
    if not str(out_root) or not out_root.is_absolute():
        raise PathUnresolved(f"set ${OUT_ROOT_ENV} to an empty absolute directory under /private/tmp")
    out_root.mkdir(parents=True, exist_ok=True)
    if any(out_root.iterdir()):
        raise PathUnresolved(f"${OUT_ROOT_ENV} must be empty: {out_root}")
    if shutil.which("Rscript") is None:
        raise PathUnresolved("Rscript is not on PATH")
    frames = pathlib.Path(args.frames_dir)
    if args.control:
        frames = REPO / "data" / "cal2026-08-28" / "frames"
    REPORT.update({"generated": datetime.datetime.now().isoformat(timespec="seconds"), "control": args.control,
                   "frames_dir": str(frames), "authority": "the author's design record of 2026-09-22 (private archive)",
                   "r_env": subprocess.run(["Rscript", "-e", 'cat(as.character(getRversion()), as.character(packageVersion("DIDmultiplegtDYN")), as.character(packageVersion("polars")))'],
                                           capture_output=True, text=True).stdout.strip()})

    # ---- A: cuts ------------------------------------------------------------------------------
    cuts_dir = out_root / "cuts"; cuts_dir.mkdir()
    pairs_econ = pathlib.Path(args.pairs_econ)
    REPORT["cuts"] = build_cuts(frames, pairs_econ, cuts_dir)
    # the cell frames: the run's frames plus the cuts (a staging dir with links)
    fdir = out_root / "frames"; fdir.mkdir()
    for p in sorted(frames.iterdir()):
        if p.is_file():
            os.link(p, fdir / p.name)
    for p in sorted(cuts_dir.iterdir()):
        if p.is_file() and not (fdir / p.name).exists():
            os.link(p, fdir / p.name)
    if args.control:   # under control the frozen afar/pos/med frames are the reference for the cut frames
        for f in FIELDS:
            for name in (f"p3_afar_{f}.parquet", f"p3_afar_pos_{f}.parquet", f"p3_afar_med_{f}.parquet"):
                src = REPO / "data" / "frames" / name
                if src.exists() and (cuts_dir / name).exists():
                    import pyarrow.parquet as pq
                    a, b = pq.read_table(src).to_pandas(), pq.read_table(cuts_dir / name).to_pandas()
                    eq = a.shape == b.shape and a.sort_values(list(a.columns)).reset_index(drop=True).equals(b.sort_values(list(b.columns)).reset_index(drop=True))
                    REPORT["cuts"][f"control_content_equal_{name}"] = bool(eq)
                    if not eq:
                        stop(f"control: cut frame {name} differs from the frozen data/frames copy")
    REPORT["input_hashes"] = {c.frame: sha(fdir / c.frame) for c in LOCAL_CELLS if (fdir / c.frame).exists()}
    missing = [c.frame for c in LOCAL_CELLS if not (fdir / c.frame).exists()]
    cells = LOCAL_CELLS
    if missing and args.control and all(m.endswith("_econ.parquet") and "afar" in m for m in missing):
        # under --control the econ pair table (663 MB, not shipped) may be absent: the two econ cut
        # cells are then skipped and recorded; every other cell still runs
        REPORT["skipped_cells_no_econ_pairs"] = [c.name for c in LOCAL_CELLS if c.frame in missing]
        cells = tuple(c for c in LOCAL_CELLS if c.frame not in missing)
        log(f"control: econ pair table absent -> skipping {REPORT['skipped_cells_no_econ_pairs']}")
    elif missing:
        stop(f"frames missing for cells: {missing}")
    if STOPS:
        (out_root / "run_report_FAILED.json").write_text(json.dumps(REPORT, indent=1, default=str)); return 1

    # ---- R: cells -----------------------------------------------------------------------------
    cells_dir, det_dir = out_root / "cells", out_root / "det"
    recs, t_all = [], time.time()
    for c in cells:
        rec = run_cell(c, fdir, cells_dir, cells_dir); recs.append(rec)
        if rec["status"] != "OK":
            break
        if c.name == "P1_econ_fnfix":
            r2 = run_cell(c, fdir, det_dir, det_dir)
            recs.append({**r2, "cell": "P1_econ_fnfix (determinism re-run)"})
            cmp = compare(_jl(det_dir / f"{c.name}.json"), _jl(cells_dir / f"{c.name}.json"))
            REPORT["determinism"] = {"compare": "EQUAL" if not cmp else "DIFF", "diffs": cmp}
            if cmp:
                stop("P1_econ_fnfix is not deterministic under these frames")
    REPORT["cells"] = recs; REPORT["cells_secs"] = round(time.time() - t_all, 1)
    if STOPS:
        (out_root / "run_report_FAILED.json").write_text(json.dumps(REPORT, indent=1, default=str)); return 1

    # ---- C: compare with the 2026-08-28 golds ------------------------------------------------
    # Since the 2026-09-23 promotion analysis/expected/ holds the OCTOBER golds; the 08-28 golds the
    # control (and the old-vs-new comparison) refer to are the frozen 08-28 run itself.
    cal = {c.name: json.loads((cells_dir / f"{c.name}.json").read_text(encoding="utf-8")) for c in cells}
    comparison, equal = [], {}
    for c in cells:
        exp_p = gold_0828(c.name)
        exp = json.loads(exp_p.read_text(encoding="utf-8"))
        diffs = compare(_jl(cells_dir / f"{c.name}.json"), exp)
        equal[c.name] = "EQUAL" if not diffs else "DIFF"
        o_rows = {r["variant"]: r for r in rce.rows_for(c.name, exp)}
        n_rows = {r["variant"]: r for r in rce.rows_for(c.name, cal[c.name])}
        for var in o_rows:
            o, n = o_rows[var], n_rows.get(var)
            comparison.append({"cell": c.name, "variant": var, "old": o, "new": n, "flags": rce.flags_for(o, n) if n else ["MISSING"]})
    REPORT["equal_to_0828_gold"] = equal
    REPORT["comparison"] = comparison
    n_eq = sum(v == "EQUAL" for v in equal.values())
    log(f"compare: {n_eq}/{len(equal)} cells EQUAL to the 2026-08-28 golds")
    if args.control and n_eq != len(equal):
        stop(f"control: {len(equal) - n_eq} cells differ from analysis/expected: {[k for k, v in equal.items() if v != 'EQUAL']}")

    # ---- F: freeze ----------------------------------------------------------------------------
    dest = CAL_DIR / ("estimates_control_0828" if args.control else "estimates")
    if dest.exists():
        if not args.refreeze:
            stop(f"{dest} exists — pass --refreeze"); (out_root / "run_report_FAILED.json").write_text(json.dumps(REPORT, indent=1, default=str)); return 1
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for c in cells:
        shutil.copyfile(cells_dir / f"{c.name}.json", dest / f"{c.name}.json")
    shutil.copyfile(det_dir / "P1_econ_fnfix.json", dest / "P1_econ_fnfix.determinism_rerun.json")
    if not args.control:
        # the cut frames of this run go beside the assembled frames; a same-named file that is already
        # content-equal (run_cal_afar.py's sweep) keeps its bytes (parquet is not byte-stable, D1)
        from tools.content_equal import content_equal   # noqa: PLC0415
        cdir = CAL_DIR / "frames"
        REPORT["cut_frames_placed"] = {}
        for p in sorted(cuts_dir.iterdir()):
            if p.is_file():
                if (cdir / p.name).exists() and content_equal(p, cdir / p.name).equal:
                    REPORT["cut_frames_placed"][p.name] = "already present, content-equal (kept)"
                else:
                    shutil.copyfile(p, cdir / p.name); REPORT["cut_frames_placed"][p.name] = "written"
    (dest / "run_report.json").write_text(json.dumps(REPORT, indent=1, default=str), encoding="utf-8")
    files = sorted(p for p in CAL_DIR.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256" and "_invalid_run2" not in p.parts)
    (CAL_DIR / "MANIFEST.sha256").write_text("".join(f"{sha(p)}  {p.relative_to(REPO).as_posix()}\n" for p in files), encoding="utf-8")
    log(f"frozen {len(LOCAL_CELLS)} cells into {dest}; STOPS={len(STOPS)}")
    return 0 if not STOPS else 1


if __name__ == "__main__":
    sys.exit(main())
