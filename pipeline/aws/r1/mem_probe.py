#!/usr/bin/env python3
"""R1 memory probe (J0-MEAS.3k; J1a stage `mem_probe`, read by N8 to choose PAR). Runs on an R1 instance only.

  mem_probe.py --frames DIR --repo DIR --stack rcloud --threads 4 --seed 20260830 --out DIR
               [--fields econ,chemistry,math_stats] [--time-bin /usr/bin/time]

Per field it records
  * the row counts of the P3 frames, read from the parquet footer (pyarrow ParquetFile.metadata.num_rows,
    no scan): p3_afar_pos_<f> (required; missing = the field FAILs), and, when present, p3_slim_<f>,
    p3_slim_ev_<f>, p3_slim_<f>_dosebin3, p3_slim_<f>_p05, pairs_none_<f> (absent ones are listed);
  * the peak RSS and wall time (from `/usr/bin/time -v`) of one parallel unit of each kind J1b runs, on
    p3_afar_pos_<f>, in the October cloudkit grammar (cloudkit.parallel_jobs, chunk (1,1)):
      Rscript <repo>/analysis/robustness/inference/run_perm.R p3tp PROBE_<f> <frame> <stub_ref> <seed> 1 1
      Rscript <repo>/analysis/robustness/null_sim/run_null.R NULLPROBE_<f> <frame> <seed> 1 1 out_null
    under the stack's pinned R (SAR_RSCRIPT_<STACK>, SAR_RLIB_<STACK>) with the October thread setting
    (driver.sh: OMP/OPENBLAS/MKL/R_DATATABLE/POLARS threads = --threads). Units run one at a time, so each
    peak and wall is the unit's own.

run_perm.R reads its reference JSON unconditionally but uses it only at perm 0, which the probe never runs;
the probe hands it a stub written under --out ({"pair_cluster":{"ate":0},"event_cluster":{"se":0}}), so no
October gold is read. Output: <out>/mem_report.json (schema sar.r1.mem_probe.v1) and <out>/summary.json
(counts and GiB only). Returns 1 if a field's p3_afar_pos frame is missing or a unit fails.
Measurement only: no frame or estimate reads these files; N8 uses them to schedule, not to compute.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import time

HOSTS = ("ec2-r1-test", "ec2-r1")
FIELDS = ("econ", "chemistry", "math_stats")
STUB_REF = {"pair_cluster": {"ate": 0}, "event_cluster": {"se": 0}}
PERM_R = "analysis/robustness/inference/run_perm.R"
NULL_R = "analysis/robustness/null_sim/run_null.R"
THREAD_VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "R_DATATABLE_NUM_THREADS",
               "POLARS_MAX_THREADS")


class FrameMissing(Exception):
    pass


def frame_names(f: str) -> dict:
    return {"p3_afar_pos": f"p3_afar_pos_{f}.parquet", "p3_slim": f"p3_slim_{f}.parquet",
            "p3_slim_ev": f"p3_slim_ev_{f}.parquet", "p3_slim_dosebin3": f"p3_slim_{f}_dosebin3.parquet",
            "p3_slim_p05": f"p3_slim_{f}_p05.parquet", "pairs": f"pairs_none_{f}.parquet"}


def frame_rows(frames, f: str):
    """({key: rows or None}, [absent keys]); FrameMissing when p3_afar_pos_<f> is absent."""
    import pyarrow.parquet as pq  # noqa: PLC0415
    rows, absent = {}, []
    for key, name in frame_names(f).items():
        p = pathlib.Path(frames) / name
        if p.is_file():
            rows[key] = pq.ParquetFile(p).metadata.num_rows
        elif key == "p3_afar_pos":
            raise FrameMissing(f"{p} is missing")
        else:
            rows[key] = None
            absent.append(key)
    return rows, absent


def unit_argv(f: str, *, rscript, repo, frames, ref, seed) -> dict:
    """The perm and null unit commands, cloudkit.parallel_jobs' chunk (1,1) with probe label/ref/paths."""
    repo, frame = pathlib.Path(repo), str(pathlib.Path(frames) / f"p3_afar_pos_{f}.parquet")
    return {"perm": [str(rscript), str(repo / PERM_R), "p3tp", f"PROBE_{f}", frame, str(ref), str(seed), "1", "1"],
            "null": [str(rscript), str(repo / NULL_R), f"NULLPROBE_{f}", frame, str(seed), "1", "1", "out_null"]}


def _wall_seconds(s: str) -> float:
    total = 0.0
    for part in s.split(":"):
        total = total * 60 + float(part)
    return round(total, 2)


def parse_time_v(text: str):
    """(peak_gib, wall_s) from GNU time -v output; None for a value it does not print."""
    m = re.search(r"Maximum resident set size \(kbytes\): (\d+)", text)
    w = re.search(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): ([\d:.]+)", text)
    return (round(int(m.group(1)) / 1024 / 1024, 3) if m else None,
            _wall_seconds(w.group(1)) if w else None)


def run_unit(kind, argv, *, wd: pathlib.Path, env, time_bin) -> dict:
    shutil.rmtree(wd, ignore_errors=True)
    wd.mkdir(parents=True)
    env = dict(env, SAR_OUT=str(wd / "out_perm"))
    t0 = time.time()
    with open(wd / "unit.log", "w", encoding="utf-8") as log, open(wd / "timev.txt", "w", encoding="utf-8") as tv:
        rc = subprocess.run([str(time_bin), "-v", *argv], cwd=wd, env=env, stdout=log, stderr=tv,
                            stdin=subprocess.DEVNULL).returncode
    secs = round(time.time() - t0, 1)
    peak, wall = parse_time_v((wd / "timev.txt").read_text(encoding="utf-8", errors="replace"))
    lab = argv[3] if kind == "perm" else argv[2]
    res = wd / ("out_perm" if kind == "perm" else "out_null") / f"{lab}_{kind}_1_1.csv"
    ok = rc == 0 and res.is_file() and peak is not None
    return {"rc": rc, "status": "OK" if ok else "FAIL", "peak_gib": peak,
            "wall_s": wall if wall is not None else secs, "argv": argv}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 memory probe (J0-MEAS.3k)")
    for k in ("--frames", "--repo", "--stack", "--out"):
        ap.add_argument(k, required=True)
    ap.add_argument("--threads", type=int, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--fields", default=",".join(FIELDS))
    ap.add_argument("--time-bin", default="/usr/bin/time")
    a = ap.parse_args(argv)
    if os.environ.get("SAR_HOST", "").strip() not in HOSTS:
        raise SystemExit("R1 rule: mem_probe.py runs only on an R1 instance ($SAR_HOST)")
    fields = [f for f in a.fields.split(",") if f]
    if not fields or set(fields) - set(FIELDS):
        raise SystemExit(f"--fields must be a subset of {FIELDS}")
    out, repo = pathlib.Path(a.out), pathlib.Path(a.repo)
    real_out, real_repo = out.resolve(), repo.resolve()
    if real_out.is_relative_to(real_repo / "analysis" / "expected") or real_out.is_relative_to(real_repo / "data"):
        raise SystemExit(f"--out {out} lies inside the repo's golds or data; give a work dir")
    rscript = os.environ.get(f"SAR_RSCRIPT_{a.stack.upper()}")
    rlib = os.environ.get(f"SAR_RLIB_{a.stack.upper()}")
    if not rscript or not rlib:
        raise SystemExit(f"no {a.stack} R stack on this instance (env layer missing)")
    if not os.access(a.time_bin, os.X_OK):
        raise SystemExit(f"{a.time_bin} is not executable; the probe needs GNU time -v")
    out.mkdir(parents=True, exist_ok=True)
    ref = out / "stub_ref.json"
    ref.write_text(json.dumps(STUB_REF) + "\n", encoding="utf-8")
    env = dict(os.environ, R_LIBS=rlib, R_PROFILE_USER="/dev/null",
               PATH=f"{os.path.dirname(rscript)}:{os.environ.get('PATH', '')}",
               **{v: str(a.threads) for v in THREAD_VARS})
    report = {"schema": "sar.r1.mem_probe.v1", "stack": a.stack, "threads": a.threads, "seed": a.seed,
              "fields": {}}
    for f in fields:
        try:
            rows, absent = frame_rows(a.frames, f)
        except FrameMissing as e:
            report["fields"][f] = {"status": "FAIL", "error": str(e), "rows": {}, "absent": [], "units": {}}
            continue
        cmds = unit_argv(f, rscript=rscript, repo=repo, frames=a.frames, ref=ref, seed=a.seed)
        units = {k: run_unit(k, cmd, wd=out / "work" / f"{k}_{f}", env=env, time_bin=a.time_bin)
                 for k, cmd in cmds.items()}
        report["fields"][f] = {"status": "OK" if all(u["status"] == "OK" for u in units.values()) else "FAIL",
                               "rows": rows, "absent": absent, "units": units}
    report["status"] = "OK" if all(v["status"] == "OK" for v in report["fields"].values()) else "FAIL"
    (out / "mem_report.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    units = [u for v in report["fields"].values() for u in v["units"].values()]
    peaks = [u["peak_gib"] for u in units if u["peak_gib"] is not None]
    summary = {"schema": "sar.r1.mem_probe_summary.v1", "status": report["status"], "fields": len(fields),
               "fields_failed": sum(v["status"] != "OK" for v in report["fields"].values()),
               "units_run": len(units), "units_failed": sum(u["status"] != "OK" for u in units),
               "peak_gib_max": max(peaks) if peaks else None}
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(f"mem_probe {report['status']}: {summary['units_run']} units, {summary['units_failed']} failed, "
          f"peak {summary['peak_gib_max']} GiB")
    return 0 if report["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
