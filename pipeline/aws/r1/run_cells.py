#!/usr/bin/env python3
"""R1 estimation-cell runner (F25; JP / J0 / J1a). Runs on an R1 instance only.

  run_cells.py --cells T.tsv --stack rmac|rcloud --repo DIR --frames DIR --gold-dir DIR --out DIR
               [--par N] [--threads T] [--compare] [--require-equal]

Each cell of the stack (TSV columns label, driver, frame, ref, out_name, stack) runs as
`Rscript <repo>/<driver> <label> <frames>/<frame> [<gold-dir>/<ref>]` under that stack's pinned R and library
(SAR_RSCRIPT_<STACK>, SAR_RLIB_<STACK>, set by the boot from the env layers), in a fresh work dir with
SAR_OUT=<workdir>/out. The result is copied to <out>/estimates/<out_name> (the gold's file name) and, with
--compare, compared with <gold-dir>/<out_name> by analysis.lib.compare_json. Writes
<out>/cells_report_<stack>.json. Returns 1 if a cell fails, or (with --require-equal) differs.
Each cell's report carries inputs = {frame, ref (null when '-'), driver}: {name, sha256, md5} of the bytes as they
were just before the R call (gate 1 custody and the R1 custody spec read them; a missing file gives null hashes).
The drivers catch estimator errors and still exit 0 with status FAILED / FAILED_* / EMPTY somewhere in their JSON
(top level, a channel, pair_cluster/event_cluster, predate.aux_status). Such a cell is a FAIL (estimate_failed lists
where), its JSON is kept under <out>/failed/ for diagnosis and never published under estimates/, and the stage
returns 1, so no done marker is written and a resume cannot reuse it (FIX-JP 3, JP review).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

HOSTS = ("ec2-r1-test", "ec2-r1")
TIME_BIN = "/usr/bin/time"


def _cells(path, stack) -> list:
    with open(path, encoding="utf-8", newline="") as fh:
        return [r for r in csv.DictReader(fh, delimiter="\t") if r["stack"] == stack]


def input_record(path, name) -> dict:
    """{name, sha256, md5} of one cell input, read in one pass; null hashes when the file is absent."""
    path = pathlib.Path(path)
    if not path.is_file():
        return {"name": name, "sha256": None, "md5": None}
    sha, md5 = hashlib.sha256(), hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            sha.update(chunk)
            md5.update(chunk)
    return {"name": name, "sha256": sha.hexdigest(), "md5": md5.hexdigest()}


def _failed_value(v) -> bool:
    return isinstance(v, str) and (v == "FAILED" or v.startswith("FAILED_") or v == "EMPTY")


def failed_statuses(obj, path="") -> list:
    """Every status a driver wrote as failed, at any depth, as 'key.path=VALUE' (keys 'status' and '*_status')."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{path}.{k}" if path else str(k)
            if (str(k) == "status" or str(k).endswith("_status")) and _failed_value(v):
                out.append(f"{key}={v}")
            else:
                out += failed_statuses(v, key)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += failed_statuses(v, f"{path}[{i}]")
    return out


def run_cell(row, *, rscript, rlib, repo, frames, gold, out, threads) -> dict:
    wd = out / "work" / row["label"]
    shutil.rmtree(wd, ignore_errors=True)
    (wd / "out").mkdir(parents=True)
    env = dict(os.environ, SAR_OUT=str(wd / "out"), R_LIBS=rlib, R_PROFILE_USER="/dev/null",
               R_DATATABLE_NUM_THREADS=str(threads), OMP_NUM_THREADS=str(threads), OPENBLAS_NUM_THREADS=str(threads),
               # every estimator loads polars; uncapped it oversubscribes an 8-way rmac pool (FIX-JP 7)
               POLARS_MAX_THREADS=str(threads),
               PATH=f"{os.path.dirname(rscript)}:{os.environ.get('PATH', '')}")
    cmd = [rscript, str(pathlib.Path(repo) / row["driver"]), row["label"], str(pathlib.Path(frames) / row["frame"])]
    if row["ref"] != "-":
        cmd.append(str(pathlib.Path(gold) / row["ref"]))
    inputs = {"frame": input_record(pathlib.Path(frames) / row["frame"], row["frame"]),
              "ref": input_record(pathlib.Path(gold) / row["ref"], row["ref"]) if row["ref"] != "-" else None,
              "driver": input_record(pathlib.Path(repo) / row["driver"], row["driver"])}
    timed = os.access(TIME_BIN, os.X_OK)
    t0 = time.time()
    with open(wd / "cell.log", "w", encoding="utf-8") as log:
        rc = subprocess.run(([TIME_BIN, "-v"] if timed else []) + cmd, cwd=wd, env=env, stdout=log,
                            stderr=subprocess.STDOUT).returncode
    secs = round(time.time() - t0, 1)
    m = re.search(r"Maximum resident set size \(kbytes\): (\d+)", (wd / "cell.log").read_text(encoding="utf-8", errors="replace"))
    peak = round(int(m.group(1)) / 1024 / 1024, 2) if m else None
    res = wd / "out" / f"{row['label']}.json"
    if rc != 0 or not res.is_file():
        return {"rc": rc, "status": "FAIL", "secs": secs, "peak_gib": peak, "first_diff": None, "inputs": inputs}
    try:
        bad = failed_statuses(json.loads(res.read_text(encoding="utf-8")))
    except ValueError as e:
        bad = [f"unreadable result JSON ({e.__class__.__name__})"]
    if bad:
        (out / "failed").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(res, out / "failed" / row["out_name"])
        return {"rc": rc, "status": "FAIL", "secs": secs, "peak_gib": peak, "first_diff": None, "inputs": inputs,
                "estimate_failed": bad}
    (out / "estimates").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(res, out / "estimates" / row["out_name"])
    return {"rc": rc, "status": "RAN", "secs": secs, "peak_gib": peak, "first_diff": None, "inputs": inputs}


def _compare(new, gold_file, repo):
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    from analysis.lib import compare_json  # noqa: PLC0415
    diffs = compare_json.compare(json.loads(pathlib.Path(new).read_text(encoding="utf-8")),
                                 json.loads(pathlib.Path(gold_file).read_text(encoding="utf-8")))
    return ("EQUAL", None) if not diffs else ("DIFF", str(diffs[0])[:300])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 estimation-cell runner")
    for k in ("--cells", "--stack", "--repo", "--frames", "--gold-dir", "--out"):
        ap.add_argument(k, required=True)
    ap.add_argument("--par", type=int, default=1)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--require-equal", action="store_true")
    a = ap.parse_args(argv)
    if os.environ.get("SAR_HOST", "").strip() not in HOSTS:
        raise SystemExit("R1 rule: run_cells.py runs only on an R1 instance ($SAR_HOST)")
    rscript = os.environ.get(f"SAR_RSCRIPT_{a.stack.upper()}")
    rlib = os.environ.get(f"SAR_RLIB_{a.stack.upper()}")
    if not rscript or not rlib:
        raise SystemExit(f"no {a.stack} R stack on this instance (env layer missing)")
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = _cells(a.cells, a.stack)
    with cf.ThreadPoolExecutor(max(1, a.par)) as ex:
        futs = {r["label"]: ex.submit(run_cell, r, rscript=rscript, rlib=rlib, repo=a.repo, frames=a.frames,
                                      gold=a.gold_dir, out=out, threads=a.threads) for r in rows}
        report = {lab: f.result() for lab, f in futs.items()}
    if a.compare:
        for r in rows:
            rep = report[r["label"]]
            if rep["status"] == "RAN":
                rep["status"], rep["first_diff"] = _compare(out / "estimates" / r["out_name"],
                                                            pathlib.Path(a.gold_dir) / r["out_name"], a.repo)
    (out / f"cells_report_{a.stack}.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for lab, rep in report.items():
        print(f"{lab:<28} {rep['status']:<6} {rep['secs']:>8}s peak {rep['peak_gib']}"
              + (f"  estimate failed: {'; '.join(rep['estimate_failed'])}" if rep.get("estimate_failed") else ""))
    bad = any(v["status"] == "FAIL" for v in report.values()) or (
        a.require_equal and any(v["status"] == "DIFF" for v in report.values()))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
