#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cal2026-10/econ_gold/run_econ_gold.py — economics through the chemistry/mathematics gold chain
(union frame -> y rebuild -> panels 2/3) via the three `_econ` clones beside this file. Repo-
authored launcher (declared in `pipeline.lib.paths.LAUNCHERS`), 2026-09-22; edits no ported file
and no frozen artifact; launches nothing on AWS.

    export SAR_OUT_ROOT=/private/tmp/<empty dir>          # scratch, NEVER under ~/Documents
    setup/.venv/bin/python pipeline/frames/cal2026-10/econ_gold/run_econ_gold.py --control --execute

THE CONTROL (mandatory before any new-input run). Old inputs -> the frozen 2026-09-13 verified-
pool cells, which are exactly "the frozen economics P1/P2 frames minus the 162 network-route
persons not on the 920 roster" (`data/robustness_2026-09-13_verified_pool/`):
  R0  estimator positive control: run_p1.R / run_p2.R on the frozen verified-pool frames must be
      compare_json-EQUAL to the frozen P1ver_econ / P2ver_econ — else the channel is VOID.
  S   shadow: the 2026-08-28 caliber's 116 economics events; the 920 verified roster as BOTH the
      dept-channel roster and the network pool; NO in-post filter on the network route; the
      frozen `network_frame_fnfix.csv` (79 old + 38 new prodlib events, minus A5044432173's event = the
      rows of the frozen P1 frame's network+both channels) pool-filtered and adapted to the gold
      shape; the U2 person map; U1 = u1_edges_full_2026-07-05 (the gold chain's edge/works/FWCI-
      pop tables); supplement = stars11 + fnfix + 133 + the works-by-author patch reshaped (the
      four sources the legacy economics P2 builder read); stars excluded = the 116 event stars.
      The persons the pool filter drops must be exactly the verified-pool build's 162.
  G   the three clones, each in its own subprocess, staged and run the way run_frames.py stages
      the originals (run dir, hard-linked script, $SAR_STAGE_ROOT, GOLDVAR=fnfix, the repo's unit
      modules pre-imported and origin-asserted).
  P   the outputs restored to the economics id shapes (econ_gold_stage.restore_p1/p2).
  E   run_p1.R / run_p2.R on them with the frozen labels; compare_json against P1ver/P2ver.
  X   row-level accounting against the verified-pool frames whatever E said.
  F   verdict: CHAIN_PROVEN only if R0, the pool check and E are all EQUAL; otherwise NOT_EQUAL —
      STOP, nothing is tuned, the accounting is the product. Report and accounting are written to
      data/cal2026-10/econ_gold_control/ (small files only; frames stay in scratch).

ASSUMPTIONS written down (every one measured or asserted by the code):
  A1  every economics frame id is `P_` + an author id, and every U2 person id is `P_` + one of its
      member author ids (487,688/487,688 measured) — so stripping/restoring `P_` is lossless.
  A2  no economics star has two events, so star:year <-> star:school is a bijection (asserted).
  A3  the frozen network frame carries no CR (asserted); its 704 A5044432173-event rows are the only rows
      whose event is not in the 116-event table (reported, not assumed).
  A4  y for economics is REDEFINED by this chain: 20_rebuild_y_gold recomputes every row's y from
      u1_edges_full edges x works (n_auth = distinct authors on the edge table) through
      compute_fwci with the full-snapshot expected table, whereas the frozen frame's y came from
      04_rebuild_y (econ_units_2026-08-09.parquet: frac_credit carried from the July U5/U6
      production, plus the API works-by-author patch for the 101 supplemented persons, work meta
      from u1_full_11school). The ex-star columns use the event stars here versus the U4
      star_set `is_star_1pct` there; neither y_ex_star nor pub_count_ex_star feeds an estimate.
  A5  the network frame's new-event rows keep prodlib's dose_topic; the frozen frame carries the
      2026-08-13 builder's recomputation for them (`dose_override_new_rows`). Old-79 rows are
      verbatim in both.
  A6  age_gap for dept-only rows is robust_first_pub (GAP=10) of both persons from the dose
      source here, versus U3 first_pub_year / star_set academic_age there; the |gap|>60 guard
      drops such new relations here, R drops them at estimation there.
  A7  the R drivers use only incumbent_person_id / event_id as factor labels, fwci_frac,
      dose_topic, post, age_gap (P1) and pid / event_id / post / y (P2); ids are compared after
      the exact inverse mapping, so an EQUAL verdict is not an artefact of relabelling.

The `--cal` run (new inputs: the 1,008-row roster, the October event table, piece A's prodlib
frame, the October supplement and exclusions) is NOT IMPLEMENTED in this version: `--cal` is
refused unconditionally (see main()), and it would be refused anyway until
data/cal2026-10/econ_gold_control/control_report.json records verdict CHAIN_PROVEN.

CONTROL RESULT (review, 2026-09-22, run end to end on this machine; 167 s; report and row-level
accounting frozen in data/cal2026-10/econ_gold_control/): verdict **NOT_EQUAL**.
  R0 EQUAL / EQUAL (estimator channel valid); pool filter drops exactly the 162 verified-pool
  persons; A5044432173's 704 rows are the only rows outside the 116-event table. The chain's frames
  are NOT the frozen ones: P1 103,356 -> 102,795 rows (51 dept-only relations lost to the
  |age_gap|>60 guard, A6), 70,640 rows modified (y 41,822 rows incl. 13,345 value->NA; dose_topic
  39,479 numeric diffs, 2,750 ->NA; age_gap 22,979 diffs, max 128 years); P2 first ties 349 -> 339.
  Estimates: P1 union ATE -0.368 (SE .062, placebo p .012) -> -0.245 (SE .058, placebo p .428),
  obs 81,592 -> 67,827; network -0.516 -> -0.455; dept -0.368 -> -0.300; P2 +0.305 -> +0.290.
  These are the definitional differences A4-A6 made concrete, not a bug in the clones (their
  diffs against the pinned originals are wiring only, DIFF.md, asserted by
  tests/test_cal2026_10_piece_b.py). Row order is identical once the removed rows are dropped.
  Determinism (three runs, the last two with the child interpreters hash-seeded): the P2 frame,
  the pairs panel and every report are byte-identical run to run; the P1 frame is NOT — 4,804 of
  102,795 lines differ between two seeded runs, only in fwci_frac / fwci_frac_ex_star, at most
  3 ULP. That is the pinned union/y builders' own accumulation-order hazard (NOT_REPRODUCIBLE.md
  entry 10, pipeline/frames/README.md §5: chem/math P1 frames are pinned NOT BYTE-EQUAL for the
  same reason); the estimates compare_json-EQUAL across all three runs. A frozen economics P1
  frame from this chain would therefore be content-equal, never byte-pinned.

WHAT THIS MEANS (not decided here). The intended design
routes the economics union channel through a clone of the legacy `00_build_frame_econ920.py`
and the PORTED `04_rebuild_y.py` / `10_panels23_econ920.py`, i.e. the chain that produced the
frozen economics frames; that chain has a control that can pass (it is the 2026-08-28 caliber's
own mechanism). This file instead pushes economics through the chemistry/mathematics gold chain
because the July-only artifacts the intended chain reads (u4_aug star_set, U3 first_pub,
econ_units_2026-08-09, u5_ship output table) were listed as unavailable when the piece was
written. Doing so changes the OUTCOME definition for economics (y from u1_edges_full edges x
works with type exclusion, 30 percent NA units; dose_topic recomputed; age_gap from
robust_first_pub) — an identification-layer change no piece may make on its own. Two ways out:
(i) follow the intended chain (the mirror now shows u3_panel_11school and
the legacy econ_fnfix star_set present; u1_full_11school and u5_ship were still syncing at
review time) with this file's pool filter + Piece A's in-post stage as the only new steps; or
(ii) accept the gold chain for all three fields as a deliberate re-definition, in which case
the control target is not the frozen economics cells and this NOT_EQUAL is the expected record,
not a failure. Until one is picked, nothing downstream of this file may run.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import pathlib
import runpy
import shutil
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[3]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))

from pipeline.lib.paths import (OUT_ROOT_ENV, STAGE_ROOT_ENV, PathUnresolved,  # noqa: E402
                                derived_root, staged_run, require_readable)
sys.path.insert(0, str(HERE))
import econ_gold_stage as eg  # noqa: E402
from econ_gold_stage import fs  # noqa: E402

PY = sys.executable
GOLD = eg.GOLD
CLONES = {
    "union": ("10_build_union_frame_gold_econ.py", ("--field", "econ"),
              ("identity.dose", "identity.first_pub", "common._redlines")),
    "y": ("20_rebuild_y_gold_econ.py", ("--field", "econ"), ()),
    "panels": ("30_build_panels23_gold_econ.py", ("--field", "econ", "--panel3", "slim"), ()),
}
OUTPUTS = {
    "union": (f"data/fnfix/union_frame_econ/analysis_frame_econ_2026-08-10.csv",
              "data/fnfix/union_frame_econ/relationships.csv",
              "data/fnfix/union_frame_econ/build_report.json",
              "data/fnfix/union_frame_econ/funnel.json"),
    "y": ("data/fnfix/analysis_frame_econ_new_gold_2026-08-10.csv",
          "data/fnfix/analysis_frame_econ_machineold_gold_2026-08-10.csv",
          "data/fnfix/g_yrebuild_econ.json"),
    "panels": ("data/fnfix/panels23_econ_gold/becoming_none.csv",
               "data/fnfix/panels23_econ_gold/pairs_slim_none.parquet",
               "data/fnfix/panels23_econ_gold/panels23_report.json"),
}
V2 = fs.real_v2()
RV = REPO / "data" / "raw_verified"
VP = REPO / "data" / "robustness_2026-09-13_verified_pool"
EST = REPO / "analysis" / "estimation"
PRODUCTS = REPO / "data" / "cal2026-10" / "econ_gold_control"

CONTROL = {
    "events": RV / "events_econ_cal2026-08-28.csv",
    "roster": RV / "roster_econ_verified.parquet",
    "network_frame": V2 / "econ_fnfix_2026-08-15/data/network_frame_fnfix.csv",
    "supplements": (V2 / "netbase_supplement_2026-07-23/edges_supplement_stars11.jsonl",
                    V2 / "econ_fnfix_2026-08-15/data/edges_supplement_fnfix.jsonl",
                    V2 / "netbase_supplement_2026-07-23/edges_supplement_133.jsonl"),
    "patch": V2 / "econ_final_2026-08-13/patch/works_by_author.jsonl",
    "pmap": derived_root() / "u2_person_map_11school_2026-07-16/person_map/data.parquet",
    "ref_p1_frame": VP / "frames/p1_frame_econ_verified.csv",
    "ref_p2_frame": VP / "frames/p2_becoming_econ_verified.csv",
    "ref_p1_json": VP / "estimates/P1ver_econ.json",
    "ref_p2_json": VP / "estimates/P2ver_econ.json",
    "ref_excluded": VP / "excluded_persons.csv",
}

STOPS: list[str] = []
REPORT: dict = {}


def stop(msg: str) -> None:
    STOPS.append(msg)
    print(f"\n*** STOP: {msg}", flush=True)


def log(msg: str) -> None:
    print(f"[run_econ_gold] {msg}", flush=True)


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------------------------
# one clone, in-process (the `--stage` entry; the orchestrator runs it in a subprocess)
# ---------------------------------------------------------------------------------------------

def _run_frames_module():
    spec = importlib.util.spec_from_file_location("sar_run_frames", REPO / "pipeline/frames/run_frames.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod                 # its @dataclass needs the module registered first
    spec.loader.exec_module(mod)
    return mod


def stage_main(name: str, root: pathlib.Path, shadow: pathlib.Path) -> int:
    script, argv, extra_units = CLONES[name]
    os.environ["SAR_LEGACY_THESIS"] = str(shadow)
    stage_root = root / "frames" / name          # a "frames" ancestor: the ported preamble's anchor
    if stage_root.exists():
        shutil.rmtree(stage_root)
    run_dir = stage_root / GOLD
    (run_dir / "code").mkdir(parents=True)
    for rel in ("data/_duck_tmp", "data/fnfix"):
        (run_dir / rel).mkdir(parents=True, exist_ok=True)
    src = HERE / script
    target = run_dir / "code" / script
    os.link(src, target)
    assert sha(target) == sha(src)
    print(f"[stage {name}] staged {src.relative_to(REPO)} (sha256 {sha(target)})", flush=True)
    if name == "union":                          # the signed-star loop reads BASE/../data/events_econ_gold_2026-08-10.csv
        s = shadow / "v2_output" / eg.STAGED["ledger_signed_loop"]
        d = run_dir / "data" / s.name
        os.link(s, d)
        print(f"[stage {name}] input {d.relative_to(run_dir)} <- shadow ({sha(d)})", flush=True)
    rf = _run_frames_module()
    for line in rf._preimport_units(extra_units):
        print(f"[stage {name}] unit module {line}", flush=True)
    os.environ.setdefault("PYTHONHASHSEED", "0")
    os.environ[STAGE_ROOT_ENV] = str(stage_root.resolve())
    os.environ["GOLDVAR"] = "fnfix"
    sys.argv = [str(target), *argv]
    t0 = time.time()
    try:
        with staged_run(target):
            runpy.run_path(str(target), run_name="__main__")
    except SystemExit as exc:
        if int(exc.code or 0):
            print(f"[stage {name}] exit {exc.code}", flush=True)
            return int(exc.code)
    print(f"[stage {name}] finished in {time.time() - t0:.1f} s; outputs:", flush=True)
    rc = 0
    for rel in OUTPUTS[name]:
        f = run_dir / rel
        if f.is_file():
            print(f"    OK   {f}  ({f.stat().st_size:,} B, sha256 {sha(f)})", flush=True)
        else:
            print(f"    MISSING {f}", flush=True)
            rc = 3
    return rc


def run_stage(name: str, root: pathlib.Path, shadow: pathlib.Path) -> dict:
    cmd = [PY, str(pathlib.Path(__file__).resolve()), "--stage", name, "--root", str(root),
           "--shadow", str(shadow)]
    env = {**os.environ}
    env.pop("SAR_LEGACY_THESIS", None)
    # hash randomisation is fixed at interpreter start: setting it inside the child (as the ported
    # run_frames.py does in-process) is too late, so it is set here, on the child's environment
    env.setdefault("PYTHONHASHSEED", "0")
    t0 = time.time()
    logf = root / "logs" / f"stage_{name}.log"
    logf.parent.mkdir(parents=True, exist_ok=True)
    with open(logf, "wb") as lf:
        proc = subprocess.run(cmd, cwd=REPO, env=env, stdout=lf, stderr=subprocess.STDOUT)
    tail = logf.read_bytes()[-3000:].decode("utf-8", "replace")
    if proc.returncode != 0:
        raise RuntimeError(f"stage {name} failed ({proc.returncode}):\n{tail}")
    run_dir = root / "frames" / name / GOLD
    produced = {rel: sha(run_dir / rel) for rel in OUTPUTS[name]}
    log(f"stage {name} finished in {time.time() - t0:.1f} s ({len(produced)} outputs)")
    return {"run_dir": run_dir, "produced": produced, "secs": round(time.time() - t0, 1),
            "log": str(logf)}


# ---------------------------------------------------------------------------------------------
# R cells
# ---------------------------------------------------------------------------------------------

def r_cell(driver: str, label: str, frame: pathlib.Path, out_dir: pathlib.Path) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, SAR_OUT=str(out_dir), PYTHONHASHSEED="0")
    logf = out_dir / f"{label}.log"
    t0 = time.time()
    with open(logf, "wb") as lf:
        r = subprocess.run(["Rscript", str(EST / driver), label, str(frame)], cwd=REPO, env=env,
                           stdout=lf, stderr=subprocess.STDOUT, timeout=3600)
    produced = out_dir / f"{label}.json"
    if r.returncode != 0 or not produced.is_file():
        raise RuntimeError(f"{driver} {label} failed ({r.returncode}):\n"
                           + logf.read_bytes()[-2000:].decode("utf-8", "replace"))
    log(f"R {driver} {label}: {time.time() - t0:.1f} s")
    return produced


def compare(new: pathlib.Path, ref: pathlib.Path) -> tuple[str, list[str]]:
    from analysis.lib.compare_json import compare as _cmp             # noqa: PLC0415
    d = _cmp(json.load(open(new)), json.load(open(ref)))
    return ("EQUAL" if not d else "DIFF"), d


# ---------------------------------------------------------------------------------------------
# the control
# ---------------------------------------------------------------------------------------------

def build_shadow(root: pathlib.Path, inputs: dict, pool: set[str] | None) -> tuple[fs.Shadow, dict]:
    require_readable(V2, "the real legacy v2_output")
    sh = fs.Shadow(root / "shadow" / "v2_output")
    for rel in eg.FROZEN_LINKS:
        sh.link_frozen(rel, V2 / rel)
    assert sha(sh.path(eg.ROSTERLIB_REL)) == fs.PINNED_LEGACY_CODE[eg.ROSTERLIB_REL], (
        "roster_lib.py in the legacy tree no longer matches its pin")
    ev = eg.EventMap(inputs["events"])
    rec: dict = {"events": {"n": len(ev.rows), "table": str(inputs["events"])}}
    blob, st = eg.adapt_network_frame(inputs["network_frame"], ev, pool)
    sh.write(eg.STAGED["network_frame"], blob,
             f"adapted:{inputs['network_frame']} (P_ stripped, star:year->star:school, pool filter)")
    rec["network_frame"] = st
    sh.write(eg.STAGED["roster"], inputs["roster"].read_bytes(), f"copy:{inputs['roster']}")
    sh.write(eg.STAGED["ledger"], ev.gold_ledger(), "derived:gold signed-table shape of the event table")
    sh.write(eg.STAGED["ledger_signed_loop"], ev.gold_ledger(),
             "derived:same table at the name the signed-star loop reads")
    sh.write(eg.STAGED["ledger_base"], ev.gold_base(), "derived:event_id(star:school),arrival_year")
    tmp = root / "stars_excluded_econ.parquet"
    eg.stars_excluded_parquet(ev.stars(), tmp)
    sh.write(eg.STAGED["stars_excluded"], tmp.read_bytes(),
             f"derived:the {len(ev.stars())} event stars of the table (ex-star set; not estimate-bearing)")
    blob, st = eg.supplement_jsonl(list(inputs["supplements"]), inputs.get("patch"))
    sh.write(eg.STAGED["supplement"], blob, "derived:concatenated supplements " + json.dumps(st))
    rec["supplement"] = st
    return sh, rec


def control(root: pathlib.Path) -> int:
    REPORT.update({"generated": datetime.datetime.now().isoformat(timespec="seconds"),
                   "task": "cal2026-10 piece B: economics through the gold chain — CONTROL",
                   "inputs": {k: (str(v) if not isinstance(v, tuple) else [str(x) for x in v])
                              for k, v in CONTROL.items()},
                   "inputs_sha256": {k: sha(v) for k, v in CONTROL.items()
                                     if isinstance(v, pathlib.Path) and v.is_file()},
                   "supplement_parts_sha256": {v.name: sha(v) for v in CONTROL["supplements"]}})
    t_all = time.time()
    # ---- R0: estimator positive control -----------------------------------------------------
    log("R0: estimator positive control on the frozen verified-pool frames")
    r0 = root / "r_positive"
    p1 = r_cell("run_p1.R", "P1ver_econ", CONTROL["ref_p1_frame"], r0)
    p2 = r_cell("run_p2.R", "P2ver_econ", CONTROL["ref_p2_frame"], r0)
    v1, d1 = compare(p1, CONTROL["ref_p1_json"])
    v2, d2 = compare(p2, CONTROL["ref_p2_json"])
    REPORT["R0_estimator_positive_control"] = {"P1ver_econ": v1, "P2ver_econ": v2,
                                               "diffs": {"P1": d1[:20], "P2": d2[:20]}}
    log(f"R0: P1 {v1}, P2 {v2}")
    if v1 != "EQUAL" or v2 != "EQUAL":
        stop("estimator positive control failed — the estimation channel is VOID on this machine; "
             "no chain verdict can be read from it")
        return finish(root)

    # ---- S: shadow ----------------------------------------------------------------------------
    log("S: pool + shadow")
    pool, pst = eg.pool_ids(CONTROL["roster"], CONTROL["pmap"])
    REPORT["pool"] = pst
    sh, rec = build_shadow(root, CONTROL, pool)
    REPORT["staging"] = rec
    excluded_ref = sorted(r["person_id"] for r in
                          __import__("csv").DictReader(open(CONTROL["ref_excluded"], encoding="utf-8")))
    dropped = rec["network_frame"]["persons_dropped_not_in_pool"]
    REPORT["pool_check"] = {"persons_dropped_by_pool_filter": len(dropped),
                            "verified_pool_excluded_persons": len(excluded_ref),
                            "equal_sets": dropped == excluded_ref,
                            "only_here": sorted(set(dropped) - set(excluded_ref))[:20],
                            "only_there": sorted(set(excluded_ref) - set(dropped))[:20]}
    log(f"pool filter dropped {len(dropped)} persons; verified-pool build excluded "
        f"{len(excluded_ref)}; equal sets = {dropped == excluded_ref}")
    if dropped != excluded_ref:
        stop("the pool filter does not reproduce the verified-pool build's excluded persons")
    ev_rows_dropped = rec["network_frame"]["events_dropped"]
    log(f"network frame: {rec['network_frame']['rows_in']} rows in, "
        f"{rec['network_frame']['rows_kept']} kept; events dropped {ev_rows_dropped}")

    # ---- G: the three clones ------------------------------------------------------------------
    stages: dict[str, dict] = {}
    shadow = root / "shadow"
    st = run_stage("union", root, shadow)
    stages["union"] = st
    for rel in OUTPUTS["union"]:
        sh.install(f"{GOLD}/{rel}", st["run_dir"] / rel, "stage:union")
    st = run_stage("y", root, shadow)
    stages["y"] = st
    st = run_stage("panels", root, shadow)
    stages["panels"] = st
    REPORT["stages"] = {k: {kk: (str(vv) if isinstance(vv, pathlib.Path) else vv)
                            for kk, vv in v.items()} for k, v in stages.items()}
    for name in ("build_report.json", "funnel.json"):
        REPORT[f"union_{name}"] = json.load(open(stages["union"]["run_dir"] /
                                                  f"data/fnfix/union_frame_econ/{name}"))
    REPORT["y_report"] = json.load(open(stages["y"]["run_dir"] / "data/fnfix/g_yrebuild_econ.json"))
    REPORT["panels_report"] = json.load(open(stages["panels"]["run_dir"] /
                                             "data/fnfix/panels23_econ_gold/panels23_report.json"))
    for k in ("G_D_hand_check",):
        REPORT["y_report"].pop(k, None)

    # ---- P: restore the economics shapes ------------------------------------------------------
    log("P: restore the economics id shapes")
    ev = eg.EventMap(CONTROL["events"])
    prod = root / "products"
    prod.mkdir(exist_ok=True)
    p1_frame = prod / "p1_frame_econ_ctl.csv"
    p1_frame.write_bytes(eg.restore_p1(stages["y"]["run_dir"] / OUTPUTS["y"][0], ev,
                                       rec["network_frame"]["rows_kept"]))
    p2_frame = prod / "p2_becoming_econ_ctl.csv"
    p2_frame.write_bytes(eg.restore_p2(stages["panels"]["run_dir"] / OUTPUTS["panels"][0], ev))
    REPORT["products"] = {"p1_frame": {"path": str(p1_frame), "sha256": sha(p1_frame)},
                          "p2_frame": {"path": str(p2_frame), "sha256": sha(p2_frame)},
                          "frame_bytes_equal_to_verified": {
                              "p1": sha(p1_frame) == sha(CONTROL["ref_p1_frame"]),
                              "p2": sha(p2_frame) == sha(CONTROL["ref_p2_frame"])}}

    # ---- E: estimates -------------------------------------------------------------------------
    log("E: estimation cells on the chain's frames")
    re_ = root / "r_chain"
    p1j = r_cell("run_p1.R", "P1ver_econ", p1_frame, re_)
    p2j = r_cell("run_p2.R", "P2ver_econ", p2_frame, re_)
    v1, d1 = compare(p1j, CONTROL["ref_p1_json"])
    v2, d2 = compare(p2j, CONTROL["ref_p2_json"])
    REPORT["E_estimates"] = {"P1ver_econ": v1, "P2ver_econ": v2,
                             "diffs": {"P1": d1[:60], "P2": d2[:60]},
                             "side_by_side": {"P1": eg.estimate_side_by_side(p1j, CONTROL["ref_p1_json"]),
                                              "P2": eg.estimate_side_by_side(p2j, CONTROL["ref_p2_json"])}}
    log(f"E: P1 {v1} ({len(d1)} diffs), P2 {v2} ({len(d2)} diffs)")

    # ---- X: accounting ------------------------------------------------------------------------
    log("X: row-level accounting against the verified-pool frames")
    acc1 = eg.account_p1(p1_frame, CONTROL["ref_p1_frame"])
    acc2 = eg.account_p2(p2_frame, CONTROL["ref_p2_frame"])
    REPORT["accounting"] = {"P1": acc1, "P2": acc2}
    log(f"X: P1 identical {acc1['identical']} / modified {acc1['modified']} / removed "
        f"{acc1['removed_rows']} / added {acc1['added_rows']}; P2 identical {acc2['identical']} / "
        f"modified {acc2['modified']} / removed {acc2['removed_rows']} / added {acc2['added_rows']}")
    if v1 != "EQUAL" or v2 != "EQUAL":
        stop("the chain's estimates are not EQUAL to the frozen verified-pool cells — STOP, not tuned; "
             "the accounting is the product")
    REPORT["staging_manifest"] = sh.manifest()
    REPORT["total_secs"] = round(time.time() - t_all, 1)
    return finish(root, p1j, p2j, stages)


def finish(root: pathlib.Path, p1j=None, p2j=None, stages=None) -> int:
    REPORT["stops"] = STOPS
    REPORT["verdict"] = "CHAIN_PROVEN" if not STOPS else "NOT_EQUAL"
    PRODUCTS.mkdir(parents=True, exist_ok=True)
    (PRODUCTS / "control_report.json").write_text(
        json.dumps(REPORT, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    if "accounting" in REPORT:
        for k in ("P1", "P2"):
            (PRODUCTS / f"accounting_{k}.json").write_text(
                json.dumps(REPORT["accounting"][k], ensure_ascii=False, indent=1, default=str) + "\n",
                encoding="utf-8")
    if p1j is not None:
        est = PRODUCTS / "estimates"
        est.mkdir(exist_ok=True)
        for f in (p1j, p2j):
            shutil.copyfile(f, est / f.name)
        for f in (root / "r_positive").glob("*.json"):
            shutil.copyfile(f, est / f"positive_control_{f.name}")
    if stages is not None:
        keep = PRODUCTS / "union_frame_econ"
        keep.mkdir(exist_ok=True)
        for rel in OUTPUTS["union"][1:]:
            shutil.copyfile(stages["union"]["run_dir"] / rel, keep / pathlib.Path(rel).name)
        shutil.copyfile(stages["y"]["run_dir"] / OUTPUTS["y"][2], keep / "g_yrebuild_econ.json")
        shutil.copyfile(stages["panels"]["run_dir"] / OUTPUTS["panels"][2], keep / "panels23_report.json")
    log(f"verdict {REPORT['verdict']}; report at {PRODUCTS / 'control_report.json'}")
    return 0 if not STOPS else 1


# ---------------------------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--control", action="store_true", help="the mandatory control run (old inputs)")
    ap.add_argument("--cal", action="store_true", help="the new-input run (refused until the control is proven)")
    ap.add_argument("--execute", action="store_true", help="required: SSD scans + R cells (minutes)")
    ap.add_argument("--stage", choices=sorted(CLONES), help=argparse.SUPPRESS)
    ap.add_argument("--root", help=argparse.SUPPRESS)
    ap.add_argument("--shadow", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.stage:
        return stage_main(args.stage, pathlib.Path(args.root), pathlib.Path(args.shadow))
    if not (args.control or args.cal):
        ap.print_help()
        return 2
    if not args.execute:
        print("This scans the data disk three times and runs four R cells (minutes). Re-run with "
              "--execute.", file=sys.stderr)
        return 2
    out_root = os.environ.get(OUT_ROOT_ENV, "").strip()
    if not out_root:
        raise PathUnresolved(f"set ${OUT_ROOT_ENV} to an empty absolute directory under /private/tmp")
    root = pathlib.Path(out_root)
    if not root.is_absolute() or (root.exists() and any(root.iterdir())):
        raise PathUnresolved(f"${OUT_ROOT_ENV} must be an empty absolute directory: {root}")
    root.mkdir(parents=True, exist_ok=True)
    if args.cal:
        rep = PRODUCTS / "control_report.json"
        verdict = json.load(open(rep))["verdict"] if rep.is_file() else "ABSENT"
        if verdict != "CHAIN_PROVEN":
            raise PathUnresolved(f"--cal refused: the control verdict is {verdict}, not CHAIN_PROVEN "
                                 f"({rep}). Run --control first; do not tune.")
        raise PathUnresolved("--cal: the new-input wiring is not enabled in this version (the "
                             "control has not been proven, see README.md)")
    return control(root)


if __name__ == "__main__":
    raise SystemExit(main())
