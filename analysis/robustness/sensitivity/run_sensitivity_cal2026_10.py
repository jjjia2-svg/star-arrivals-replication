#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_sensitivity_cal2026_10.py — GROUP `sensitivity` on the October canon (cal2026-10), 2026-09-23.

The three §3-promised sensitivity checks, re-run on the PROMOTED October frames (data/frames: econ
113 / chemistry 38 / math_stats 33 events; golds analysis/expected/) by the SAME builders and the
VERBATIM analysis/estimation drivers, controls first:

  controls    the verbatim drivers on the UNCHANGED October frames, under the golds' own labels, must
              be compare_json-EQUAL to analysis/expected: P1 x3 (run_p1.R), P2 x3 (run_p2.R), Panel 3
              pos A_far x3 (run_p3_tp.R, label P3cut_pos_<field> = the gold's label). The double-star
              P3-full-math cell gets its own control: make_slim + run_p3.R on the UNFILTERED pairs table
              that builder reads (data/cal2026-08-28/frames/pairs_none_math_stats.parquet, a frame path
              this script may not change) vs the October gold P3_fnfix_math_stats — plus the positive
              control on the October pairs table (data/frames/pairs_none_math_stats.parquet).
  departure   D6: build_departure_187.py (the 187-event ledger) per field on the October frames and the
              proven October pos maps -> P1dep{A,B}_<f>, P2dep{A,B}_<f>, P3dep{A,B}_pos_<f>_A_far.
  doublestar  build_doublestar.py --spec pos (October econ ledger, the chem/math event tables — byte-equal
              to October's —, the October pos maps) -> P1ds_<f>, P2ds_<f>, P3ds_pos_<f>_A_far;
              P3ds_math_stats_full only when its control is EQUAL; the 2026-09-12 complement
              (run_doublestar_complement.sh) attempted exactly as written.
  nocentre    run_nocentre.py and run_nocentre_afar_pos.sh as written (output overrides only); each runs
              its own with-centre control build first and STOPS itself when that control fails.

A control that is NOT EQUAL stops its cells and is recorded; nothing is "fixed". Products:
data/cal2026-10/robustness/{sensitivity_controls,departure,doublestar,nocentre}/ each with a
MANIFEST.sha256 (tools/write_manifest.py: sha256, two spaces, repo-relative path) and the group report
data/cal2026-10/robustness/sensitivity_report.json (every input hash, every control verdict, every
cell's status and headline numbers). Scratch: /private/tmp/sar_rob_sensitivity/. R parallelism:
BATTERY_JOBS (default 2) plus a cooperative machine-wide cap (SAR_R_CAP, default 6) on R driver
processes, because sibling batteries run at the same time.

    setup/.venv/bin/python analysis/robustness/sensitivity/run_sensitivity_cal2026_10.py --execute [--skip-nocentre]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
PY = sys.executable
E = REPO / "analysis/estimation"
FIELDS = ("econ", "chemistry", "math_stats")
ROB = REPO / "data/cal2026-10/robustness"
CTL, DEP, DS, NC = ROB / "sensitivity_controls", ROB / "departure", ROB / "doublestar", ROB / "nocentre"
MAPDIR = ROB / "afar_event_map_pos"
SCRATCH = pathlib.Path("/private/tmp/sar_rob_sensitivity")
FRAMES = REPO / "data/frames"
LEDGER = REPO / "data/departure_verification_2026-09-10/departure_verified_2026-09-10.csv"   # not shipped
PAIRS_0828_MATH = REPO / "data/cal2026-08-28/frames/pairs_none_math_stats.parquet"
PAIRS_OCT_MATH = FRAMES / "pairs_none_math_stats.parquet"
OLD_DS = REPO / "data/robustness_2026-08-29_b/doublestar"
REPORT_PATH = ROB / "sensitivity_report.json"
JOBS = int(os.environ.get("BATTERY_JOBS", "2"))
RCAP = int(os.environ.get("SAR_R_CAP", "6"))
GOLD_P1 = {"econ": "P1_econ_fnfix", "chemistry": "P1_fnfix_chemistry", "math_stats": "P1_fnfix_math_stats"}
GOLD_P2 = {"econ": "P2_econ_fnfix", "chemistry": "P2_fnfix_chemistry", "math_stats": "P2_fnfix_math_stats"}
T0 = time.time()
REPORT: dict = {}


# ----------------------------------------------------------------------------------------------
def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def rel(p: pathlib.Path) -> str:
    p = pathlib.Path(p)
    return p.relative_to(REPO).as_posix() if p.is_relative_to(REPO) else str(p)


def log(msg: str) -> None:
    print(f"[{time.time() - T0:7.1f}s] {msg}", flush=True)


def freeze_report(status: str = "RUNNING") -> None:
    REPORT["status"] = status
    REPORT["secs"] = round(time.time() - T0, 1)
    REPORT_PATH.write_text(json.dumps(REPORT, indent=1, default=str) + "\n", encoding="utf-8")


def run_logged(cmd: list[str], logfile: pathlib.Path, env: dict | None = None, cwd=REPO) -> dict:
    logfile.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    proc = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True,
                          env={**os.environ, **(env or {})})
    logfile.write_text(f"$ {' '.join(str(c) for c in cmd)}\n[env] "
                       f"{json.dumps(env or {})}\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}\n"
                       f"--- rc={proc.returncode} secs={time.time() - t0:.1f} ---\n", encoding="utf-8")
    return {"rc": proc.returncode, "secs": round(time.time() - t0, 1), "stdout": proc.stdout,
            "stderr": proc.stderr, "log": rel(logfile)}


def r_driver_processes() -> int:
    """Count R driver processes machine-wide (`.../bin/exec/R --no-echo --no-restore --file=...`)."""
    try:
        out = subprocess.run(["ps", "-axo", "command"], capture_output=True, text=True).stdout
    except Exception:
        return 0
    return sum(1 for ln in out.splitlines() if "/bin/exec/R " in ln and "--file=" in ln)


_SLOT_LOCK = threading.Lock()


def wait_for_slot(label: str, max_wait: int = 1800) -> float:
    """Cooperative cap: wait (up to max_wait s) while the machine already runs >= RCAP R drivers.
    Serialised: the caller launches its driver while still holding the lock (see estimate), so two
    workers cannot both read the same count and overshoot the cap together."""
    waited = 0.0
    _SLOT_LOCK.acquire()
    while r_driver_processes() >= RCAP and waited < max_wait:
        time.sleep(15); waited += 15
    if waited:
        log(f"   {label}: waited {waited:.0f}s for an R slot (machine at cap {RCAP})")
    return waited


def _launched() -> None:
    """Release the slot lock once the launched driver is visible to `ps` (at most ~3 s)."""
    for _ in range(6):
        time.sleep(0.5)
    _SLOT_LOCK.release()


def compare(new: pathlib.Path, gold: pathlib.Path) -> dict:
    proc = subprocess.run([PY, "-m", "analysis.lib.compare_json", str(new), str(gold)],
                          cwd=REPO, capture_output=True, text=True)
    eq = proc.returncode == 0 and proc.stdout.strip().startswith("EQUAL")
    return {"verdict": "EQUAL" if eq else "NOT_EQUAL", "gold": rel(gold), "gold_sha256": sha(gold),
            "diff_head": [] if eq else proc.stdout.strip().splitlines()[:12]}


def headline(j: dict) -> dict:
    """The numbers a reader cites, per driver output shape."""
    panel = j.get("panel")
    if panel == "P1_output":
        ch = {}
        for name, c in j["channels"].items():
            ch[name] = {k: c.get(k) for k in ("status", "obs", "rels", "events", "ate", "se", "lb", "ub",
                                              "p_joint_effects", "p_joint_placebo")}
        return {"rows_raw": j.get("rows_raw"), "rows_kept": j.get("rows_kept"), "channels": ch}
    if panel == "P3_topicpair":
        h = {k: j.get(k) for k in ("rows", "grps", "events", "first_ties")}
        for cl in ("pair_cluster", "event_cluster"):
            c = j.get(cl, {})
            h[cl] = {k: c.get(k) for k in ("status", "ate", "se", "lb", "ub", "p_joint_effects")}
        return h
    return {k: j.get(k) for k in ("status", "rows", "rels", "grps", "persons", "events", "first_ties",
                                  "ate", "se", "lb", "ub", "p_joint_effects", "p_joint_placebo")}


def cell_status(j: dict) -> str:
    panel = j.get("panel")
    if panel == "P1_output":
        st = {c.get("status") for c in j["channels"].values()}
        return "OK" if st == {"OK"} else "FAILED:" + ",".join(sorted(s for s in st if s != "OK"))
    if panel == "P3_topicpair":
        bad = [cl for cl in ("pair_cluster", "event_cluster") if "ate" not in j.get(cl, {})]
        return "OK" if not bad else "FAILED:" + ",".join(bad)
    return str(j.get("status", "UNKNOWN"))


def estimate(label: str, driver: str, frame: pathlib.Path, out_dir: pathlib.Path,
             log_dir: pathlib.Path, extra: tuple[str, ...] = ()) -> dict:
    """One verbatim driver run; output <out_dir>/<label>.json (SAR_OUT), log <log_dir>/<label>.log."""
    out_dir.mkdir(parents=True, exist_ok=True)
    waited = wait_for_slot(label)
    threading.Timer(0.0, _launched).start()          # releases the slot lock ~3 s after this launch
    r = run_logged(["Rscript", str(E / driver), label, str(frame), *extra], log_dir / f"{label}.log",
                   env={"SAR_OUT": str(out_dir), "POLARS_MAX_THREADS": "4"})
    res = {"label": label, "driver": rel(E / driver), "frame": rel(frame), "frame_sha256": sha(frame),
           "rc": r["rc"], "secs": r["secs"], "log": r["log"], "waited_for_slot_secs": waited}
    js = out_dir / f"{label}.json"
    if r["rc"] == 0 and js.is_file():
        j = json.loads(js.read_text(encoding="utf-8"))
        res.update({"json": rel(js), "json_sha256": sha(js), "status": cell_status(j), "headline": headline(j)})
        line = [ln for ln in r["stdout"].splitlines() if "ATE=" in ln or "FAIL" in ln]
        log(f"   {label}: {res['status']} ({r['secs']}s) " + (line[-1].strip()[:110] if line else ""))
    else:
        res.update({"status": "DRIVER_ERROR", "stderr_tail": r["stderr"][-600:]})
        log(f"   {label}: DRIVER_ERROR rc={r['rc']} — see {r['log']}")
    return res


def run_cells(cells: list[dict], out_dir: pathlib.Path, log_dir: pathlib.Path) -> dict:
    with ThreadPoolExecutor(max_workers=JOBS) as ex:
        futs = [ex.submit(estimate, c["label"], c["driver"], c["frame"], out_dir, log_dir, c.get("extra", ()))
                for c in cells]
        return {f.result()["label"]: f.result() for f in futs}


def line_count(p: pathlib.Path) -> int:
    with open(p, "rb") as fh:
        return sum(1 for _ in fh)


# ----------------------------------------------------------------------------------------------
def phase_inputs() -> None:
    log("== inputs: sha256 of every input, frames checked against data/MANIFEST.sha256")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    inputs: list[pathlib.Path] = []
    for f in FIELDS:
        inputs += [FRAMES / f"p1_frame_{f}.csv", FRAMES / f"p2_becoming_{f}.csv", FRAMES / f"p3_afar_pos_{f}.parquet",
                   REPO / f"data/cal2026-10/events_{f}_cal2026-10.csv", MAPDIR / f"afar_event_map_{f}.csv"]
    inputs += [FRAMES / "p1_events_ledger_econ.csv", FRAMES / "p3_slim_math_stats.parquet", PAIRS_0828_MATH,
               PAIRS_OCT_MATH, MAPDIR / "afar_event_map_report.json", LEDGER,
               REPO / "data/cal2026-08-28/events_chemistry_cal.csv", REPO / "data/cal2026-08-28/events_math_stats_cal.csv",
               REPO / "data/cal2026-08-28/frames/p1_events_ledger_econ.csv",
               OLD_DS / "doublestar_drops.csv", OLD_DS / "doublestar_build_report.json",
               REPO / "data/robustness_2026-08-29_b/nocentre/nocentre_run_report.json",
               E / "run_p1.R", E / "run_p2.R", E / "run_p3_tp.R", E / "run_p3.R", REPO / "pipeline/frames/make_slim.py",
               HERE / "build_departure_187.py", HERE / "build_departure.py", HERE / "build_doublestar.py",
               HERE / "build_doublestar_complement.py", HERE / "run_doublestar_complement.sh",
               HERE / "run_nocentre.py", HERE / "run_nocentre_afar_pos.py", HERE / "run_nocentre_afar_pos.sh",
               REPO / "pipeline/stars/caliber_2026-08-28/frames_stage.py",
               REPO / "pipeline/stars/caliber_2026-08-28/run_cal_frames.py",
               REPO / "analysis/robustness/p3_afar_cuts/build_afar_cut.py", REPO / "analysis/lib/compare_json.py",
               pathlib.Path(__file__)]
    for g in list(GOLD_P1.values()) + list(GOLD_P2.values()) + [f"P3pos_{f}_A_far" for f in FIELDS] + ["P3_fnfix_math_stats"]:
        inputs.append(REPO / "analysis/expected" / f"{g}.json")
    man = {ln.split("  ", 1)[1]: ln.split("  ", 1)[0]
           for ln in (REPO / "data/MANIFEST.sha256").read_text(encoding="utf-8").splitlines() if "  " in ln}
    hashes, in_manifest = {}, {}
    for p in inputs:
        if not p.is_file():
            hashes[rel(p)] = "ABSENT"; continue
        hashes[rel(p)] = sha(p)
        if rel(p).startswith("data/frames/"):
            in_manifest[rel(p)] = man.get(rel(p)) == hashes[rel(p)]
    REPORT["inputs"] = {"git_head": head, "sha256": hashes, "frames_match_data_MANIFEST": in_manifest,
                        "r_version": subprocess.run(["Rscript", "-e", "cat(as.character(getRversion()))"],
                                                    capture_output=True, text=True).stdout.strip()}
    bad = [k for k, v in in_manifest.items() if not v]
    assert not bad, f"frames not the promoted canon (sha differs from data/MANIFEST.sha256): {bad}"
    log(f"   {len(hashes)} inputs hashed; {len(in_manifest)} data/frames inputs match data/MANIFEST.sha256")


def phase_controls() -> bool:
    log("== controls: verbatim drivers on the unchanged October frames vs analysis/expected")
    out, logs = CTL / "estimates_control", CTL / "logs"
    cells = []
    for f in FIELDS:
        cells.append({"label": GOLD_P1[f], "driver": "run_p1.R", "frame": FRAMES / f"p1_frame_{f}.csv", "gold": GOLD_P1[f]})
        cells.append({"label": GOLD_P2[f], "driver": "run_p2.R", "frame": FRAMES / f"p2_becoming_{f}.csv", "gold": GOLD_P2[f]})
        cells.append({"label": f"P3cut_pos_{f}", "driver": "run_p3_tp.R", "frame": FRAMES / f"p3_afar_pos_{f}.parquet",
                      "gold": f"P3pos_{f}_A_far"})
    res = run_cells(cells, out, logs)
    ctl = {}
    for c in cells:
        r = res[c["label"]]
        cmp = compare(out / f"{c['label']}.json", REPO / "analysis/expected" / f"{c['gold']}.json") \
            if r.get("json") else {"verdict": "NOT_RUN", "gold": f"analysis/expected/{c['gold']}.json"}
        ctl[c["label"]] = {**r, "compare": cmp}
        log(f"   control {c['label']} vs {c['gold']}: {cmp['verdict']}")
    REPORT["controls"] = {"frame_controls": ctl}

    # the double-star P3-full-math control: make_slim + run_p3.R on the UNFILTERED pairs the builder reads
    log("   P3-full-math controls: make_slim + run_p3.R on the unfiltered pairs tables vs P3_fnfix_math_stats")
    p3 = {}
    for tag, pairs in (("pairs_0828", PAIRS_0828_MATH), ("pairs_oct", PAIRS_OCT_MATH)):
        st = SCRATCH / "p3full_ctl" / tag; st.mkdir(parents=True, exist_ok=True)
        ev, noev = st / "p3_slim_ev_math_stats.parquet", st / "p3_slim_math_stats.parquet"
        ms = run_logged([PY, REPO / "pipeline/frames/make_slim.py", "math_stats", pairs, ev, "--noev", noev],
                        logs / f"make_slim_{tag}.log")
        assert ms["rc"] == 0, ms["stderr"][-800:]
        cell = estimate("P3_fnfix_math_stats", "run_p3.R", noev, out / f"p3full_{tag}", logs / f"p3full_{tag}")
        cmp = compare(out / f"p3full_{tag}" / "P3_fnfix_math_stats.json", REPO / "analysis/expected/P3_fnfix_math_stats.json") \
            if cell.get("json") else {"verdict": "NOT_RUN"}
        p3[tag] = {"pairs": rel(pairs), "pairs_sha256": sha(pairs), "make_slim_stdout_tail": ms["stdout"].strip()[-400:],
                   "slim_sha256": sha(noev), "cell": cell, "compare": cmp}
        log(f"   control P3 full math on {tag} vs P3_fnfix_math_stats: {cmp['verdict']}")
    REPORT["controls"]["p3_full_math_controls"] = p3
    REPORT["controls"]["p3_full_math_reading"] = (
        "build_doublestar.py re-slims the --pairs-none-math table this run passes, October's "
        "data/cal2026-08-28/frames/pairs_none_math_stats.parquet; pairs_0828 is that table unfiltered, pairs_oct the October table data/frames/"
        "pairs_none_math_stats.parquet — the P3ds_math_stats_full cell runs only if pairs_0828 is EQUAL")
    ok = all(v["compare"]["verdict"] == "EQUAL" for v in ctl.values())
    REPORT["controls"]["frame_controls_all_equal"] = ok
    freeze_report()
    return ok


def phase_departure() -> None:
    log("== departure A/B (D6, the 187-event ledger) on the October frames")
    logs, est = DEP / "logs", DEP / "estimates"
    ledger = pd.read_csv(LEDGER, dtype=str).fillna("")
    dep: dict = {"ledger": rel(LEDGER), "ledger_sha256": sha(LEDGER), "ledger_rows": int(len(ledger)),
                 "builder": rel(HERE / "build_departure_187.py"), "fields": {}}
    for f in FIELDS:
        stage = SCRATCH / f"dep_{f}"
        if stage.exists():
            shutil.rmtree(stage)
        b = run_logged([PY, HERE / "build_departure_187.py", "--field", f, "--frames-dir", "data/frames",
                        "--map", rel(MAPDIR / f"afar_event_map_{f}.csv"), "--out", rel(DEP), "--stage", stage],
                       logs / f"build_{f}.log")
        assert b["rc"] == 0, b["stderr"][-1200:]
        rep = json.loads((DEP / f"departure187_build_report_{f}.json").read_text(encoding="utf-8"))
        # ledger <-> October frame reconciliation (econ: the ledger is keyed on the 2026-08-28 116 events)
        d = ledger[ledger.discipline == f]
        keyed = d.event_id if f == "econ" else (d.star_author_id + ":" + d.school)
        frame_events = set(pd.read_csv(FRAMES / f"p1_frame_{f}.csv", usecols=["event_id"]).event_id)
        not_in_frame = d[~keyed.isin(frame_events)]
        not_in_ledger = sorted(frame_events - set(keyed))
        dep["fields"][f] = {
            "build_report": rel(DEP / f"departure187_build_report_{f}.json"),
            "events_in_frame": rep["events_in_frame"], "ledger_rows": int(len(d)), "verdicts": rep["verdicts"],
            "rule_A_drops_events": len(rep["A_dropped_in_frame"]), "rule_B_recodes_events": len(rep["B_recoded_in_frame"]),
            "rule_A_dropped_event_ids": rep["A_dropped_in_frame"], "rule_B_recode_years": rep["B_recoded_in_frame"],
            "unparseable_departure_years": rep["unparseable_departure_years"],
            "ledger_rows_not_in_october_frame": [{"event_id": k, "verdict": v, "departure_year": y}
                                                 for k, v, y in zip(keyed[~keyed.isin(frame_events)], not_in_frame.verdict,
                                                                    not_in_frame.departure_year)],
            "october_events_without_ledger_row": not_in_ledger,
            "noop_control": rep["noop_control"], "frames_accounting": rep["frames"], "afar": rep["afar"],
            "staged_sha256": rep["staged_sha256"]}
        log(f"   {f}: rule A drops {len(rep['A_dropped_in_frame'])} events, rule B recodes "
            f"{len(rep['B_recoded_in_frame'])} events; noop {rep['noop_control']}; A_far dropped "
            f"{rep['afar']['A_dropped_in_afar']} / recoded {rep['afar']['B_recoded_in_afar']}; "
            f"ledger rows not in frame {len(not_in_frame)}, frame events without ledger row {not_in_ledger}")
    REPORT["departure"] = dep
    freeze_report()
    cells = []
    for f in FIELDS:
        st = SCRATCH / f"dep_{f}"
        for v in ("A", "B"):
            cells += [{"label": f"P1dep{v}_{f}", "driver": "run_p1.R", "frame": st / f"p1_dep_{v}_{f}.csv"},
                      {"label": f"P2dep{v}_{f}", "driver": "run_p2.R", "frame": st / f"p2_dep_{v}_{f}.csv"},
                      {"label": f"P3dep{v}_pos_{f}_A_far", "driver": "run_p3_tp.R", "frame": st / f"p3_afar_dep_{v}_{f}.parquet"}]
    dep["cells"] = run_cells(cells, est, logs)
    freeze_report()


def phase_doublestar(p3full_ok: bool) -> None:
    log("== double-star overlap drops (--spec pos) on the October frames")
    logs, est = DS / "logs", DS / "estimates"
    stage = SCRATCH / "ds"
    if stage.exists():
        shutil.rmtree(stage)
    env = {"SAR_ROBUST_OUTDIR": rel(DS), "SAR_AFAR_MAP_DIR": rel(MAPDIR)}
    b = run_logged([PY, HERE / "build_doublestar.py", "--spec", "pos", "--stage", stage, "--fields", ",".join(FIELDS),
                    "--events-dir", REPO / "data/cal2026-10", "--frames-dir", FRAMES, "--pairs-none-math", PAIRS_0828_MATH],
                   logs / "build_doublestar.log", env=env)
    assert b["rc"] == 0, b["stderr"][-1200:]
    rep = json.loads((DS / "doublestar_build_report.json").read_text(encoding="utf-8"))
    drops = pd.read_csv(DS / "doublestar_drops.csv")
    old = pd.read_csv(OLD_DS / "doublestar_drops.csv")
    vs_old = {}
    for f in FIELDS:
        n = drops[drops.field == f]; o = old[old.field == f]
        nd, od = set(n[n.dropped].event_id), set(o[o.dropped].event_id)
        vs_old[f] = {"events_oct": int(len(n)), "events_0829": int(len(o)), "dropped_oct": len(nd), "dropped_0829": len(od),
                     "drop_table_identical_to_2026-08-29": bool(set(n.event_id) == set(o.event_id) and nd == od),
                     "dropped_only_0829": sorted(od - nd), "dropped_only_oct": sorted(nd - od)}
    ds: dict = {"builder": rel(HERE / "build_doublestar.py"), "env_overrides": env, "rule": rep["rule"],
                "counts": {f: {k: rep[f][k] for k in ("events", "dropped", "kept", "same_year_pair_events_kept")} for f in FIELDS},
                "afar": {f: rep[f]["afar"] for f in FIELDS}, "p3_full_math_build": rep["math_stats"].get("p3_full"),
                "drop_table_vs_2026-08-29": vs_old, "staged_sha256": rep["staged_sha256"],
                "event_tables": {"econ": "data/frames/p1_events_ledger_econ.csv (October, 113)",
                                 "chemistry": "data/cal2026-10/events_chemistry_cal2026-10.csv (builder --events-dir; byte-equal to data/cal2026-08-28/events_chemistry_cal.csv)",
                                 "math_stats": "data/cal2026-10/events_math_stats_cal2026-10.csv (builder --events-dir; byte-equal to data/cal2026-08-28/events_math_stats_cal.csv)"}}
    for f in ("chemistry", "math_stats"):
        ds["event_tables"][f + "_byte_equal_check"] = sha(REPO / f"data/cal2026-08-28/events_{f}_cal.csv") == \
            sha(REPO / f"data/cal2026-10/events_{f}_cal2026-10.csv")
    for f in FIELDS:
        log(f"   {f}: {rep[f]['dropped']} of {rep[f]['events']} events dropped, {rep[f]['kept']} kept "
            f"(same-year kept {rep[f]['same_year_pair_events_kept']}); vs 2026-08-29: "
            f"{'identical' if vs_old[f]['drop_table_identical_to_2026-08-29'] else 'differs'}")
    REPORT["doublestar"] = ds
    freeze_report()
    cells = []
    for f in FIELDS:
        cells += [{"label": f"P1ds_{f}", "driver": "run_p1.R", "frame": stage / f"p1_ds_{f}.csv"},
                  {"label": f"P2ds_{f}", "driver": "run_p2.R", "frame": stage / f"p2_ds_{f}.csv"},
                  {"label": f"P3ds_pos_{f}_A_far", "driver": "run_p3_tp.R", "frame": stage / f"p3_afar_ds_{f}.parquet"}]
    if p3full_ok:
        cells.append({"label": "P3ds_math_stats_full", "driver": "run_p3.R", "frame": stage / "p3_slim_ds_math_stats.parquet"})
    ds["cells"] = run_cells(cells, est, logs)
    if not p3full_ok:
        ds["cells"]["P3ds_math_stats_full"] = {
            "label": "P3ds_math_stats_full", "driver": rel(E / "run_p3.R"), "status": "STOPPED_CONTROL_NOT_EQUAL",
            "reason": "build_doublestar.py re-slims the --pairs-none-math table passed here, "
                      "data/cal2026-08-28/frames/pairs_none_math_stats.parquet (October's value); its unfiltered re-slim is NOT compare_json-EQUAL to the "
                      "October gold P3_fnfix_math_stats (controls.p3_full_math_controls.pairs_0828) — the cell would be a "
                      "mixed-caliber number, so it was not estimated. The staged re-slim stays in scratch.",
            "staged_frame_sha256": rep["staged_sha256"].get("p3_slim_ds_math_stats.parquet")}
        log("   P3ds_math_stats_full: STOPPED (control on the builder's 08-28 pairs table NOT EQUAL to the October gold)")
    freeze_report()

    # the 2026-09-12 complement, exactly as run_doublestar_complement.sh runs it (output overrides only)
    log("   complement (run_doublestar_complement.sh as written, output/stage overrides)")
    cst = SCRATCH / "dscomp"
    if cst.exists():
        shutil.rmtree(cst)
    c = run_logged(["bash", HERE / "run_doublestar_complement.sh"], logs / "run_doublestar_complement.log",
                   env={"SAR_ROBUST_STAGE": str(cst), "SAR_ROBUST_OUTDIR": rel(DS / "complement")})
    comp: dict = {"entry_point": rel(HERE / "run_doublestar_complement.sh"), "rc": c["rc"], "log": c["log"]}
    if c["rc"] == 0 and (DS / "complement/estimates/P1dsC_econ.json").is_file():
        j = json.loads((DS / "complement/estimates/P1dsC_econ.json").read_text(encoding="utf-8"))
        comp.update({"status": cell_status(j), "headline": headline(j), "json": rel(DS / "complement/estimates/P1dsC_econ.json")})
    else:
        err = [ln for ln in (c["stderr"] + c["stdout"]).splitlines() if "AssertionError" in ln or "assert" in ln.lower()]
        comp.update({"status": "STOPPED_PIN_2026-08-29",
                     "reason": "build_doublestar_complement.py is pinned to the 2026-08-29 econ drop table (18 kept / 98 "
                               "dropped of 116 events) and its row accounting against data/robustness_2026-08-29_b; the "
                               "October econ ledger has 113 events, so the pin fails by construction. Re-pinning the script "
                               "is a change beyond an output override — left for a separate decision.",
                     "october_econ_counts": ds["counts"]["econ"], "error_tail": err[-3:] or c["stderr"].strip().splitlines()[-3:]})
        (DS / "complement").mkdir(parents=True, exist_ok=True)
        (DS / "complement/NOT_RUN.md").write_text(
            "# double-star complement (P1dsC_econ) on the October canon — NOT RUN\n\n" + comp["reason"] + "\n\n"
            f"October econ drop table: {json.dumps(ds['counts']['econ'])} (2026-08-29: 98 dropped / 18 kept of 116).\n"
            f"Log: {c['log']}\n", encoding="utf-8")
        log(f"   complement: STOPPED (script pinned to the 2026-08-29 drop table; rc={c['rc']})")
    ds["complement"] = comp
    freeze_report()


def _forensic_nocentre(root: pathlib.Path) -> dict:
    """What the with-centre control build produced vs the October frames and vs the 2026-08-28 frames."""
    shadow = root / "control/shadow"
    G = "multidisc_gold_2026-08-10"

    def find(tail: str) -> pathlib.Path:
        # the shadow nests the legacy layout (<shadow>/v2_output/<GOLD>/...): locate by suffix, not by a fixed prefix
        hits = [p for p in shadow.rglob(pathlib.Path(tail).name) if p.as_posix().endswith(tail)] if shadow.is_dir() else []
        return hits[0] if hits else shadow / tail

    out = {}
    for f in ("chemistry", "math_stats"):
        relp = find(f"{G}/data/fnfix/union_frame_{f}/relationships.csv")
        p1 = find(f"{G}/data/fnfix/analysis_frame_{f}_new_gold_2026-08-10.csv")
        p2 = find(f"{G}/data/fnfix/panels23_{f}_gold/becoming_none.csv")
        row = {}
        for name, built, oct_, old in (
                ("relationships", relp, None, REPO / f"data/cal2026-08-28/frames/relationships_{f}.csv"),
                ("p1_frame", p1, FRAMES / f"p1_frame_{f}.csv", REPO / f"data/cal2026-08-28/frames/p1_frame_{f}.csv"),
                ("becoming", p2, FRAMES / f"p2_becoming_{f}.csv", REPO / f"data/cal2026-08-28/frames/p2_becoming_{f}.csv")):
            if not built.is_file():
                row[name] = "NOT_BUILT"; continue
            r = {"built_lines": line_count(built), "built_sha256": sha(built)}
            if oct_ is not None:
                r["october_lines"] = line_count(oct_)
                r["vs_october"] = "BYTE_EQUAL" if sha(built) == sha(oct_) else "NOT_EQUAL"
            r["lines_2026-08-28"] = line_count(old)
            r["vs_2026-08-28"] = "BYTE_EQUAL" if sha(built) == sha(old) else "NOT_EQUAL"
            row[name] = r
        out[f] = row
    return out


def phase_nocentre() -> None:
    log("== ± research-centre rosters: run_nocentre.py (P1/P2 chem+math) and run_nocentre_afar_pos.sh (P3 pos), as written")
    logs = NC / "logs"
    nc: dict = {"design_note": "both launchers rebuild the chemistry/math_stats frames through the 2026-08-28 caliber staging "
                               "machinery (pipeline/stars/caliber_2026-08-28) and compare their with-centre control build to "
                               "data/frames (now the October canon) before any variant cell; a control that fails STOPS them"}
    # (i) run_nocentre.py — P1/P2 chem/math (+ P3 full math), as run_all_sensitivity.sh step 3 runs it
    root1 = SCRATCH / "nc_p1p2"
    if root1.exists():
        shutil.rmtree(root1)
    root1.mkdir(parents=True)
    r1 = run_logged([PY, HERE / "run_nocentre.py", "--execute"], logs / "run_nocentre.log",
                    env={"SAR_OUT_ROOT": str(root1), "SAR_ROBUST_OUTDIR": rel(NC), "POLARS_MAX_THREADS": "4"})
    stop = [ln for ln in (r1["stderr"] + r1["stdout"]).splitlines() if "STOP" in ln or "AssertionError" in ln or "Error" in ln]
    nc["run_nocentre"] = {"entry_point": rel(HERE / "run_nocentre.py"), "env": {"SAR_OUT_ROOT": str(root1), "SAR_ROBUST_OUTDIR": rel(NC)},
                          "rc": r1["rc"], "secs": r1["secs"], "log": r1["log"],
                          "status": "OK" if r1["rc"] == 0 else "STOPPED_CONTROL_NOT_EQUAL",
                          "stop_lines": stop[-4:], "control_build_forensics": _forensic_nocentre(root1)}
    if r1["rc"] == 0 and (NC / "nocentre_run_report.json").is_file():
        rep = json.loads((NC / "nocentre_run_report.json").read_text(encoding="utf-8"))
        nc["run_nocentre"]["control_checks"] = rep.get("control_checks"); nc["run_nocentre"]["control_estimates"] = rep.get("control_estimates")
        cells = {}
        for js in sorted((NC / "estimates").glob("*.json")):
            j = json.loads(js.read_text(encoding="utf-8"))
            cells[js.stem] = {"json": rel(js), "json_sha256": sha(js), "status": cell_status(j), "headline": headline(j)}
        nc["run_nocentre"]["cells"] = cells
    log(f"   run_nocentre.py: rc={r1['rc']} -> {nc['run_nocentre']['status']}")
    freeze_report()
    # (ii) run_nocentre_afar_pos.sh — P3 pos chem/math
    root2 = SCRATCH / "nc_p3pos"
    if root2.exists():
        shutil.rmtree(root2)
    r2 = run_logged(["bash", HERE / "run_nocentre_afar_pos.sh"], logs / "run_nocentre_afar_pos.log",
                    env={"SAR_OUT_ROOT": str(root2), "SAR_ROBUST_OUTDIR_P3POS": rel(NC / "p3pos"),
                         "SAR_ROBUST_MANIFEST_DIR": rel(NC), "POLARS_MAX_THREADS": "4"})
    rep2 = NC / "p3pos/nocentre_afar_pos_report.json"
    entry = {"entry_point": rel(HERE / "run_nocentre_afar_pos.sh"), "rc": r2["rc"], "secs": r2["secs"], "log": r2["log"],
             "env": {"SAR_OUT_ROOT": str(root2), "SAR_ROBUST_OUTDIR_P3POS": rel(NC / "p3pos"), "SAR_ROBUST_MANIFEST_DIR": rel(NC)}}
    if rep2.is_file():
        j = json.loads(rep2.read_text(encoding="utf-8"))
        entry.update({"report": rel(rep2), "report_status": j.get("status"), "control_checks": j.get("control_checks"),
                      "failed": j.get("failed")})
        entry["status"] = "OK" if j.get("status") == "OK" else "STOPPED_CONTROL_NOT_EQUAL"
        if j.get("status") == "OK":
            entry["control_estimates"] = j.get("control_estimates"); entry["variant_afar_pos"] = j.get("variant_afar_pos")
            cells = {}
            for js in sorted((NC / "p3pos/estimates").glob("*.json")):
                jj = json.loads(js.read_text(encoding="utf-8"))
                cells[js.stem] = {"json": rel(js), "json_sha256": sha(js), "status": cell_status(jj), "headline": headline(jj)}
            entry["cells"] = cells
    else:
        entry["status"] = "STOPPED_PRECONDITION" if r2["rc"] != 0 else "UNKNOWN"
        entry["stop_lines"] = (r2["stderr"] + r2["stdout"]).strip().splitlines()[-4:]
    entry["control_build_forensics"] = _forensic_nocentre(root2)
    nc["run_nocentre_afar_pos"] = entry
    log(f"   run_nocentre_afar_pos.sh: rc={r2['rc']} -> {entry['status']}")
    # the 2026-09-10 P3nc_pos cells' with-centre control is the October gold iff the 08-28 P3pos estimates are EQUAL to it
    same = {}
    for f in ("chemistry", "math_stats"):
        a = REPO / f"data/cal2026-10/estimates_control_0828/P3pos_{f}_A_far.json"
        same[f] = compare(a, REPO / f"analysis/expected/P3pos_{f}_A_far.json")["verdict"] if a.is_file() else "ABSENT"
    nc["note_p3pos_chem_math_unchanged_by_october"] = {
        "P3pos_<field>_A_far on the 2026-08-28 frames vs the October gold": same,
        "reading": "the October D2 filter removes network-only persons, who were never Panel 3 pairs, so the chem/math "
                   "pos A_far frames and golds are unchanged; the frozen 2026-09-10 P3nc_pos cells "
                   "(data/robustness_2026-09-10_p3pos/nocentre/) therefore still sit next to the October Panel 3 gold, "
                   "but they are NOT re-frozen here"}
    if all(v.get("status", "").startswith("STOPPED") for v in (nc["run_nocentre"], nc["run_nocentre_afar_pos"])):
        NC.mkdir(parents=True, exist_ok=True)
        (NC / "NOT_RUN.md").write_text(
            "# ± research-centre check on the October canon — NOT RUN (controls NOT EQUAL)\n\n"
            "run_nocentre.py and run_nocentre_afar_pos.sh rebuild the chemistry/math_stats frames through the "
            "2026-08-28 caliber staging machinery and require their with-centre control build to reproduce data/frames "
            "(becoming byte-identical, P1 within the H1 ULP characterisation). data/frames is now the October canon "
            "(D2 in-post filter: chemistry union 50,193 -> 30,635 rows, math_stats 24,211 -> 19,910), so the control "
            "fails and both launchers stop themselves before any variant cell. Rule: a failing control is recorded, not "
            "fixed. Completing this check on October needs the no-centre (incfel) roster substitution inside the "
            "October chain (pipeline/frames/cal2026-10/run_cal_frames_chemmath.py) — a new builder, not an override.\n\n"
            f"Forensics of the control builds: sensitivity_report.json -> nocentre.*.control_build_forensics; logs in {rel(logs)}/.\n",
            encoding="utf-8")
    REPORT["nocentre"] = nc
    freeze_report()


def phase_manifests() -> None:
    log("== MANIFESTs (tools/write_manifest.py, repo-relative paths) + verification")
    mans = {}
    for d in (CTL, DEP, DS, NC):
        if not d.is_dir():
            continue
        w = subprocess.run([PY, REPO / "tools/write_manifest.py", d], cwd=REPO, capture_output=True, text=True)
        v = subprocess.run([PY, REPO / "tools/verify_manifest.py", d / "MANIFEST.sha256"], cwd=REPO, capture_output=True, text=True)
        mans[rel(d)] = {"write": w.stdout.strip(), "verify": v.stdout.strip().splitlines()[-1] if v.stdout.strip() else v.stderr[-200:]}
        assert "MANIFEST_OK" in mans[rel(d)]["verify"], mans[rel(d)]
        log(f"   {rel(d)}: {mans[rel(d)]['write']} — {mans[rel(d)]['verify']}")
    REPORT["manifests"] = mans


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--execute", action="store_true", help="required: ~40 R cells + two SSD frame builds (minutes)")
    ap.add_argument("--skip-nocentre", action="store_true", help="skip the ± centre launchers (they need the data disk)")
    args = ap.parse_args(argv)
    if not args.execute:
        print(__doc__); return 2
    SCRATCH.mkdir(parents=True, exist_ok=True)
    for d in (CTL, DEP, DS, NC):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
    REPORT.update({"group": "sensitivity", "caliber": "cal2026-10", "generated": time.strftime("%Y-%m-%d %H:%M"),
                   "runner": rel(pathlib.Path(__file__)), "scratch": str(SCRATCH), "battery_jobs": JOBS, "r_cap": RCAP,
                   "design": "the author's design record of 2026-09-22 (private archive) (D6 departure ledger of 187 events; "
                             "the ± centre and double-star checks re-run unchanged)",
                   "script_edits": ["build_departure.py: $SAR_AFAR_MAP_DIR (proven-map dir; default the spec's freeze root)",
                                    "build_doublestar.py: $SAR_ROBUST_OUTDIR (default <freeze root>/doublestar)",
                                    "build_doublestar_complement.py + run_doublestar_complement.sh: $SAR_ROBUST_OUTDIR, $SAR_ROBUST_STAGE (defaults unchanged)",
                                    "run_nocentre.py: $SAR_ROBUST_OUTDIR (default data/robustness_2026-08-29_b/nocentre)",
                                    "run_nocentre_afar_pos.py: $SAR_ROBUST_OUTDIR_P3POS; run_nocentre_afar_pos.sh: $SAR_ROBUST_MANIFEST_DIR (defaults unchanged)",
                                    "build_doublestar.py (2026-10-16, R1 F3): --events-dir/--frames-dir/--pairs-none-math, "
                                    "passed here with October's values",
                                    "no estimation line, control or frame path changed"]})
    phase_inputs()
    ok = phase_controls()
    p3full_ok = REPORT["controls"]["p3_full_math_controls"]["pairs_0828"]["compare"]["verdict"] == "EQUAL"
    if ok:
        phase_departure()
        phase_doublestar(p3full_ok)
    else:
        bad = [k for k, v in REPORT["controls"]["frame_controls"].items() if v["compare"]["verdict"] != "EQUAL"]
        for name, d in (("departure", DEP), ("doublestar", DS)):
            REPORT[name] = {"status": "STOPPED_CONTROL_NOT_EQUAL", "failed_controls": bad}
            (d / "NOT_RUN.md").write_text(f"# {name} — NOT RUN: frame controls NOT EQUAL: {bad}\n", encoding="utf-8")
        log(f"   departure + doublestar STOPPED: frame controls not EQUAL: {bad}")
    if args.skip_nocentre:
        REPORT["nocentre"] = {"status": "SKIPPED (--skip-nocentre)"}
    else:
        phase_nocentre()
    phase_manifests()
    stops = []
    for name in ("departure", "doublestar", "nocentre"):
        sec = REPORT.get(name, {})
        if str(sec.get("status", "")).startswith("STOPPED"):
            stops.append(name)
        for k, v in sec.get("cells", {}).items() if isinstance(sec.get("cells"), dict) else []:
            if str(v.get("status", "")) != "OK":
                stops.append(f"{name}:{k}")
        for k in ("run_nocentre", "run_nocentre_afar_pos", "complement"):
            if isinstance(sec.get(k), dict) and str(sec[k].get("status", "")).startswith("STOPPED"):
                stops.append(f"{name}:{k}")
    freeze_report("DONE" if not stops else "DONE_WITH_STOPS")
    log(f"SENSITIVITY_CAL2026_10_{'OK' if not stops else 'WITH_STOPS'} ({REPORT['secs']} s) stops={stops}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
