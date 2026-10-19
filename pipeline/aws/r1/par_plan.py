#!/usr/bin/env python3
"""R1 parallel-width planner (N8; the first J1b stage, after restore_j1a and rob_jobs). Runs on an R1 instance only.

  par_plan.py --jobs UNITS.tsv --frames DIR --calib mem_report.json [--calib-cells cells_report_rcloud.json] --out DIR

Reads the unit TSV that rob_jobs_r1.write_tsv() wrote (columns group, name, kind, frame, threads, est_min, ...),
counts each unit's parent frame from metadata only (parquet footer num_rows; CSV = streamed newline count - 1),
predicts each unit's peak memory, and chooses per group how many units run at once (PAR):

  * coefficient(kind) = max measured peak_gib per million rows of that kind x margin 1.25, from J1a's
    mem_probe report (sar.r1.mem_probe.v1: the perm unit calibrates perm_p3tp, the null unit null; rows =
    p3_afar_pos) and, when given, J1a's cells_report_rcloud.json (full-panel run_p3/run_p3_evcl cells
    calibrate p3full, run_p3_tp cells p3tp; rows from the frame named in the cell's inputs). Without a
    measurement: 25 GiB per million rows, 32 for null and p3full. calib_used records which one applied.
  * rows = the parent frame's rows (D7 / cut units are filters of it, so this is an upper bound); nocentre
    units 1.2 x the parent (a different roster can hold more pairs). A unit without a frame ('-') is
    predicted at MIN_GIB. A parent frame that is not there is a STOP (FRAME_MISSING), never a guess.
  * per group: threads = the largest unit threads, pred_gib = the largest unit prediction,
    par = min(units, vcpu // threads, floor(budget / pred)) (the width if every unit were the heaviest);
    width = min(units, vcpu // threads) and budget_gib = 450: run_units packs the group's units by their own
    predictions (groups[].units[].pred_gib), at most `width` at once and their predicted GiB within the budget,
    so light units run beside heavy ones (j1b-01: one width per group made J1b 926 min).
  * a unit predicted above 450 GiB (MEMORY) or asking for more threads than vCPUs (THREADS) stops its group;
    the group is left out of plan.json and the verdict is STOP (exit 3), which fails J1b before any unit runs.
  * wall time per group, as run_units.execute runs it (M review #12): a simulation of that packing (TSV order,
    first fit; a unit waits for a needs_control unit of its group), plus every kind-post unit one at a time
    (sum of their est_min). A group of one prediction gives ceil(n / par) x est_min, as before. The launch overhead -
    J1b's stages outside run_units (verify_inputs, config, restore_j1a, sandbox, rob_jobs, par_plan,
    afar_event_map, fig4_m, fig4_counts, sandbox_check: OVERHEAD_MIN, --overhead-min) - counts against each
    launch: when the groups' cumulative wall exceeds 540 - overhead min the plan sets split_after = the last
    group of the first launch, and J1b runs as two launches joined by --resume-from (P3b R11). If two launches
    cannot hold it (one group alone above 540 min, or more than two launches): STOP (WALL).

Writes <out>/plan.json (schema sar.r1.par_plan.v1, read by run_units.py, which refuses a plan whose
joblist_sha256 differs from the TSV it regenerates) and <out>/report_par_plan.json (counts only).
Scheduling only: no estimate or frame reads these files.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import json
import math
import os
import pathlib
import re

HOSTS = ("ec2-r1-test", "ec2-r1")
KINDS = ("p1", "p2", "p3tp", "perm_p1", "perm_p2", "perm_p3tp", "null", "p3full", "build", "control", "post")
DEFAULT_GIB_PER_M = 25.0
HEAVY_GIB_PER_M = {"null": 32.0, "p3full": 32.0}
MARGIN = 1.25
MIN_GIB = 1.0
NOCENTRE_FACTOR = 1.2
VCPU, BUDGET_GIB, WALL_BUDGET_MIN = 64, 450.0, 540
#: est_min of config/r1/stages/j1b.json's stages that are not a run_units group (tests/test_r1_par_plan.py sums them)
OVERHEAD_MIN = 83
PROBE_KIND = {"perm": "perm_p3tp", "null": "null"}
DRIVER_KIND = {"run_p3.R": "p3full", "run_p3_evcl.R": "p3full", "run_p3_tp.R": "p3tp"}
NOCENTRE = re.compile(r"^P\d+nc(_|$)|nocentre", re.IGNORECASE)


def rows_of(path) -> int:
    """Rows of a frame without reading its data: parquet footer num_rows, or a CSV's newline count - 1."""
    path = pathlib.Path(path)
    if path.suffix == ".parquet":
        import pyarrow.parquet as pq  # noqa: PLC0415
        return int(pq.ParquetFile(path).metadata.num_rows)
    if path.suffix == ".csv":
        lines, last = 0, b"\n"
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                lines += chunk.count(b"\n")
                last = chunk[-1:]
        if last != b"\n":
            lines += 1
        return max(lines - 1, 0)
    raise ValueError(f"{path}: not a .parquet or .csv frame")


def _add(calib: dict, kind: str, peak, rows, source: str) -> None:
    if peak is None or not rows:
        return
    per_m = float(peak) / (rows / 1e6)
    if kind not in calib or per_m > calib[kind]["gib_per_m_measured"]:
        calib[kind] = {"gib_per_m_measured": per_m, "peak_gib": float(peak), "rows": int(rows), "source": source}


def calibrate(mem_report=None, cells_report=None, *, frames=None, rows_fn=None) -> dict:
    """{kind: {gib_per_m_measured, peak_gib, rows, source}}: the largest measured GiB per million rows per kind."""
    calib: dict = {}
    if mem_report is not None:
        if mem_report.get("schema") != "sar.r1.mem_probe.v1":
            raise ValueError(f"--calib: schema {mem_report.get('schema')!r}, expected sar.r1.mem_probe.v1")
        for field, rec in sorted(mem_report.get("fields", {}).items()):
            rows = (rec.get("rows") or {}).get("p3_afar_pos")
            for unit, kind in PROBE_KIND.items():
                u = (rec.get("units") or {}).get(unit) or {}
                if u.get("status") == "OK":
                    _add(calib, kind, u.get("peak_gib"), rows, f"mem_probe:{field}:{unit}")
    if cells_report is not None:
        rows_fn = rows_fn or rows_of
        for label, rec in sorted(cells_report.items()):
            ins = rec.get("inputs") or {}
            kind = DRIVER_KIND.get(pathlib.PurePosixPath((ins.get("driver") or {}).get("name") or "").name)
            frame = (ins.get("frame") or {}).get("name")
            if kind is None or not frame or rec.get("status") == "FAIL" or frames is None:
                continue
            p = pathlib.Path(frames) / frame
            if p.is_file():
                _add(calib, kind, rec.get("peak_gib"), rows_fn(p), f"cells_rcloud:{label}")
    return calib


def coefficient(kind: str, calib: dict, margin: float = MARGIN):
    """(GiB per million rows, source): measured x margin when calibrated, else the default."""
    if kind in calib:
        return calib[kind]["gib_per_m_measured"] * margin, calib[kind]["source"]
    return HEAVY_GIB_PER_M.get(kind, DEFAULT_GIB_PER_M), "default"


def predict_gib(kind: str, rows: int, calib: dict, margin: float = MARGIN) -> float:
    coef, _ = coefficient(kind, calib, margin)
    return max(coef * rows / 1e6, MIN_GIB)


def load_jobs(path):
    """(units, sha256 of the TSV bytes)."""
    raw = pathlib.Path(path).read_bytes()
    units = list(csv.DictReader(raw.decode("utf-8").splitlines(), delimiter="\t"))
    for u in units:
        for col in ("group", "name", "kind", "frame", "threads", "est_min"):
            if col not in u or u[col] is None:
                raise ValueError(f"{path}: unit {u.get('name')!r} lacks column {col}")
        if u["kind"] not in KINDS:
            raise ValueError(f"{path}: unit {u['name']!r} has unknown kind {u['kind']!r}")
    return units, hashlib.sha256(raw).hexdigest()


def _no_frame(frame) -> bool:
    return frame in (None, "", "-")


def unit_rows(unit, rows: dict):
    """(rows, basis) for one unit, or (None, 'missing') when its parent frame was not counted."""
    frame = unit["frame"]
    if _no_frame(frame):
        return 0, "no_frame"
    if frame not in rows:
        return None, "missing"
    if NOCENTRE.search(unit["name"]) or "nocentre" in unit.get("outdir", ""):
        return int(math.ceil(rows[frame] * NOCENTRE_FACTOR)), "nocentre_1.2x_parent"
    return int(rows[frame]), "parent_frame"


def group_wall(recs: list[dict], width: int, budget_gib: float) -> float:
    """A group's wall time as run_units.execute runs it: the non-post units in TSV order, first fit, at most
    `width` at once and their predicted GiB within the budget (a unit runs alone if nothing else is running);
    a unit whose needs_control unit is in the group starts after it; then the kind-post units one at a time."""
    names = {r["name"] for r in recs}
    pending = [r for r in recs if r["kind"] != "post"]
    running: list = []                                   # heap of (end minute, seq, unit)
    done: set = set()
    t, used, seq = 0.0, 0.0, 0
    while pending or running:
        for r in list(pending):
            if len(running) >= width:
                break
            dep = r.get("needs_control") or ""
            if dep in names and dep not in done:
                continue
            if running and used + r["pred_gib"] > budget_gib + 1e-9:
                continue
            heapq.heappush(running, (t + r["est_min"], seq, r))
            seq += 1
            used += r["pred_gib"]
            pending.remove(r)
        if not running:                                  # what is left waits on a unit that never runs here
            break
        t = running[0][0]
        while running and running[0][0] == t:              # run_units sees every unit done by then at once
            _, _, r = heapq.heappop(running)
            used -= r["pred_gib"]
            done.add(r["name"])
    return t + sum(r["est_min"] for r in recs if r["kind"] == "post")


def plan(units, rows, calib, *, vcpu=VCPU, budget_gib=BUDGET_GIB, margin=MARGIN, wall_budget_min=WALL_BUDGET_MIN,
         joblist_sha256=None, overhead_min=OVERHEAD_MIN) -> dict:
    order, members = [], {}
    for u in units:
        if u["group"] not in members:
            order.append(u["group"])
            members[u["group"]] = []
        members[u["group"]].append(u)
    groups, stops, used = [], [], {}
    for g in order:
        recs, bad = [], []
        for u in members[g]:
            n_rows, basis = unit_rows(u, rows)
            threads, est = int(u["threads"]), float(u["est_min"])
            if n_rows is None:
                bad.append({"unit": u["name"], "group": g, "kind": u["kind"], "frame": u["frame"],
                            "reason": "FRAME_MISSING", "pred_gib": None})
                continue
            coef, src = coefficient(u["kind"], calib, margin)
            used[u["kind"]] = {"gib_per_m": round(coef, 4), "source": src}
            pred = predict_gib(u["kind"], n_rows, calib, margin)
            rec = {"name": u["name"], "kind": u["kind"], "frame": u["frame"], "rows": n_rows, "basis": basis,
                   "threads": threads, "est_min": est, "pred_gib": round(pred, 3), "source": src,
                   "needs_control": u.get("needs_control") or ""}
            recs.append(rec)
            if pred > budget_gib:
                bad.append({"unit": u["name"], "group": g, "kind": u["kind"], "frame": u["frame"],
                            "reason": "MEMORY", "pred_gib": round(pred, 3)})
            if threads > vcpu or threads < 1:
                bad.append({"unit": u["name"], "group": g, "kind": u["kind"], "frame": u["frame"],
                            "reason": "THREADS", "pred_gib": round(pred, 3), "threads": threads})
        if bad:
            stops.extend(bad)
            continue
        threads = max(r["threads"] for r in recs)
        pred = max(r["pred_gib"] for r in recs)
        est = max(r["est_min"] for r in recs)
        n = len(recs)
        par = max(1, min(n, vcpu // threads, int(budget_gib // pred)))
        width = max(1, min(n, vcpu // threads))
        wall = group_wall(recs, width, budget_gib)
        groups.append({"group": g, "threads": threads, "par": par, "width": width, "budget_gib": budget_gib,
                       "pred_gib": pred, "n_units": n, "est_min": est, "wall_min": wall,
                       "peak_total_gib": round(par * pred, 3), "units": recs})
    total = sum(gr["wall_min"] for gr in groups)
    launches, cur, cum = [], [], 0.0
    for gr in groups:
        if gr["wall_min"] > wall_budget_min:
            stops.append({"unit": None, "group": gr["group"], "kind": None, "frame": None, "reason": "WALL",
                          "pred_gib": None, "wall_min": gr["wall_min"]})
        if cur and cum + gr["wall_min"] > wall_budget_min - overhead_min:
            launches.append(cur)
            cur, cum = [], 0.0
        cur.append(gr["group"])
        cum += gr["wall_min"]
    if cur:
        launches.append(cur)
    if len(launches) > 2:
        stops.append({"unit": None, "group": launches[2][0], "kind": None, "frame": None, "reason": "WALL",
                      "pred_gib": None, "launches_needed": len(launches)})
    split_after = launches[0][-1] if len(launches) == 2 else None
    return {"schema": "sar.r1.par_plan.v1", "joblist_sha256": joblist_sha256, "verdict": "STOP" if stops else "OK",
            "vcpu": vcpu, "budget_gib": budget_gib, "margin": margin, "wall_budget_min": wall_budget_min,
            "overhead_min": overhead_min, "wall_min_total": total, "split_after": split_after, "launches": launches, "stops": stops,
            "calib_used": used, "groups": groups}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 parallel-width planner (N8)")
    for k in ("--jobs", "--frames", "--calib", "--out"):
        ap.add_argument(k, required=True)
    ap.add_argument("--calib-cells", default=None)
    ap.add_argument("--vcpu", type=int, default=VCPU)
    ap.add_argument("--budget-gib", type=float, default=BUDGET_GIB)
    ap.add_argument("--wall-budget-min", type=float, default=WALL_BUDGET_MIN)
    ap.add_argument("--overhead-min", type=float, default=OVERHEAD_MIN,
                    help="minutes of each launch spent outside run_units groups (default: J1b's non-unit stages)")
    a = ap.parse_args(argv)
    if os.environ.get("SAR_HOST", "").strip() not in HOSTS:
        raise SystemExit("R1 rule: par_plan.py runs only on an R1 instance ($SAR_HOST)")
    units, digest = load_jobs(a.jobs)
    frames = pathlib.Path(a.frames)
    rows = {}
    for f in sorted({u["frame"] for u in units if not _no_frame(u["frame"])}):
        if (frames / f).is_file():
            rows[f] = rows_of(frames / f)
    mem = json.loads(pathlib.Path(a.calib).read_text(encoding="utf-8"))
    cells = json.loads(pathlib.Path(a.calib_cells).read_text(encoding="utf-8")) if a.calib_cells else None
    calib = calibrate(mem, cells, frames=frames)
    out = plan(units, rows, calib, vcpu=a.vcpu, budget_gib=a.budget_gib, wall_budget_min=a.wall_budget_min,
               joblist_sha256=digest, overhead_min=a.overhead_min)
    out["inputs"] = {"jobs": str(a.jobs), "frames": str(frames), "calib": str(a.calib), "calib_cells": a.calib_cells,
                     "frame_rows": rows}
    od = pathlib.Path(a.out)
    od.mkdir(parents=True, exist_ok=True)
    (od / "plan.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    report = {"stage": "par_plan", "result": out["verdict"], "n_units": len(units), "n_groups": len(out["groups"]),
              "n_stops": len(out["stops"]), "rows_max": max(rows.values(), default=0),
              "counts": {"wall_min_total": out["wall_min_total"], "launches": len(out["launches"])},
              "codes": sorted({s["reason"] for s in out["stops"]})}
    (od / "report_par_plan.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    for gr in out["groups"]:
        print(f"{gr['group']:<28} n {gr['n_units']:>4}  threads {gr['threads']:>2}  par {gr['par']:>3}  "
              f"pred {gr['pred_gib']:>8.2f} GiB  wall {gr['wall_min']:>6.0f} min")
    for s in out["stops"]:
        print(f"STOP {s['reason']}: group {s['group']} unit {s['unit']} pred {s['pred_gib']}")
    print(f"par_plan {out['verdict']}: {len(out['groups'])} groups, wall {out['wall_min_total']:.0f} min, "
          f"split_after {out['split_after']}")
    return 3 if out["verdict"] == "STOP" else 0


if __name__ == "__main__":
    raise SystemExit(main())
