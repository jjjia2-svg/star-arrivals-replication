#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_nocentre_cal2026_10.py — the ± research-centre check (T6-1) on the OCTOBER canon, chemistry
and math_stats. 2026-09-23, local, $0.

WHAT IT IS
    run_nocentre.py's design (read its docstring): the chemistry / math_stats frames rebuilt with ONE
    substitution — the roster link `multidisc_gold_2026-08-10/data/fnfix/roster_gold_<field>.parquet`
    re-pointed at the frozen INCFEL roster (no research-centre academic staff; the rule that research centres
    count as part of the department put +134 chemistry / +28 math people INTO the canon rosters) — and the cells
    estimated on them. The 2026-08-29 / 2026-09-10 launchers stage the 2026-08-28 chain and cannot
    reproduce the October frames (their with-centre control fails since the promotion, recorded in
    data/cal2026-10/robustness/sensitivity_report.json -> nocentre). This launcher makes the same
    substitution INSIDE the October chain: pipeline/frames/cal2026-10/run_cal_frames_chemmath.py
    --roster-variant incfel (the October shadow's roster link AND the D2 in-post spells read the one
    incfel file; prodlib's pool / in-dept index, the union builder's dept channel / row fill and the
    D2 filter all see it), products to --products-dir (never under data/).

CONTROLS FIRST — any failure STOPs before a variant cell is estimated
    C1  the driver with the UNCHANGED roster and --no-freeze: its own phase-C control (the no-D2 chain
        reproduces the 2026-08-28 frozen products; P1/P2_fnfix on them EQUAL to the 08-28 golds) AND
        its October products equal the frozen data/cal2026-10/frames_<field>/ (relationships / p2
        BYTE_EQUAL, union report equal modulo paths + the H1 advisory example, p1 within H1, pairs /
        slims content-equal), accounting closed, stops = [].
    C2  the VARIANT driver run's own phase-C control (same machine control, inside the same run).
    C3  the verbatim estimation drivers on the CANON October frames (data/frames) under the golds' own
        labels compare_json-EQUAL to analysis/expected: P1_fnfix_<f> (run_p1.R), P2_fnfix_<f>
        (run_p2.R), P3_fnfix_math_stats (make_slim on data/frames/pairs_none_math_stats.parquet +
        run_p3.R), P3cut_pos_<f> (build_afar_cut.py `pos` with explicit sources = the canon
        pairs_none / p1 / p2, its frame content-equal to data/frames/p3_afar_pos_<f>.parquet, then
        run_p3_tp.R) vs P3pos_<f>_A_far.

THE VARIANT
    driver --roster-variant incfel --products-dir <scratch>/products: population change recorded by
    the driver's variant accounting (frozen October canon vs variant; causes: person not in the
    variant roster / no variant spell at the arrival, per channel; channel both<->network/dept_only;
    in-post row fill; H1), then the cells, verbatim drivers:
        P1nc_<f>              run_p1.R    on the variant p1_frame_<f>.csv
        P2nc_<f>              run_p2.R    on the variant p2_becoming_<f>.csv
        P3nc_math_stats_full  run_p3.R    on the variant p3_slim_math_stats.parquet (make_slim, in the driver)
        P3nc_pos_<f>_A_far    run_p3_tp.R on build_afar_cut `pos` over the variant pairs_none / p1 / p2
    (labels as run_nocentre.py / run_nocentre_afar_pos.py name them). Economics has no ± variant by
    design (run_nocentre.py:10-12).

WRITES   data/cal2026-10/robustness/nocentre/{estimates, estimates_control, driver_reports,
         variant_frames_<f>, logs}/ + nocentre_report.json (every input sha256, every control verdict,
         the population deltas, every cell's status + headline, old 2026-08-29 headlines beside them),
         then the directory MANIFEST (tools/write_manifest.py). NOT_RUN.md (the 2026-09-23 "not run"
         record) is replaced by the report. The variant FRAMES stay in the scratch products dir
         (regenerable by the driver in ~1 min with the data disk; their sha256 are in the report).
         R parallelism: BATTERY_JOBS (default 2) under a machine-wide cap SAR_R_CAP (default 3).

    setup/.venv/bin/python analysis/robustness/sensitivity/run_nocentre_cal2026_10.py --execute
    scratch: $SAR_NOCENTRE_SCRATCH (default /private/tmp/sar_rob_nocentre)
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
os.environ.setdefault("SAR_R_CAP", "3")                # siblings run R too: <= 3 drivers machine-wide
os.environ.setdefault("BATTERY_JOBS", "2")
from analysis.robustness.sensitivity import run_sensitivity_cal2026_10 as rs   # noqa: E402  (helpers only; its main() is NOT run)
from analysis.robustness.p3_afar_cuts import build_afar_cut                    # noqa: E402
from tools.content_equal import content_equal                                  # noqa: E402

PY = sys.executable
DRIVER = REPO / "pipeline/frames/cal2026-10/run_cal_frames_chemmath.py"
E = REPO / "analysis/estimation"
FIELDS = ("chemistry", "math_stats")
FRAMES = REPO / "data/frames"
CAL10 = REPO / "data/cal2026-10"
EXPECTED = REPO / "analysis/expected"
NC = REPO / "data/cal2026-10/robustness/nocentre"
OLD = REPO / "data/robustness_2026-08-29_b/nocentre/estimates"
SCRATCH = pathlib.Path(os.environ.get("SAR_NOCENTRE_SCRATCH", "/private/tmp/sar_rob_nocentre"))
PRODUCTS = SCRATCH / "products"
GOLD_LABEL = {"P1": "P1_fnfix_{f}", "P2": "P2_fnfix_{f}", "P3pos": "P3cut_pos_{f}"}
REPORT: dict = {}
STOPS: list[str] = []
T0 = time.time()
sha, rel, log = rs.sha, rs.rel, rs.log


def stop(msg: str) -> None:
    STOPS.append(msg)
    log(f"*** STOP: {msg}")


def freeze(status: str) -> None:
    REPORT["status"] = status
    REPORT["stops"] = STOPS
    REPORT["secs"] = round(time.time() - T0, 1)
    NC.mkdir(parents=True, exist_ok=True)
    (NC / "nocentre_report.json").write_text(json.dumps(REPORT, indent=1, default=str) + "\n", encoding="utf-8")


def manifest_ok(d: pathlib.Path) -> bool:
    """Every line of <d>/MANIFEST.sha256 (repo-relative paths) hashes as written."""
    for ln in (d / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        h, relp = ln.split("  ", 1)
        if sha(REPO / relp) != h:
            return False
    return True


# ----------------------------------------------------------------------------------------------
def phase_inputs() -> None:
    log("== inputs")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    files = [DRIVER, REPO / "pipeline/frames/cal2026-10/stage.py", REPO / "pipeline/frames/cal2026-10/inpost_filter.py",
             REPO / "pipeline/frames/make_slim.py", REPO / "analysis/robustness/p3_afar_cuts/build_afar_cut.py",
             E / "run_p1.R", E / "run_p2.R", E / "run_p3.R", E / "run_p3_tp.R"]
    for f in FIELDS:
        files += [REPO / f"data/raw_verified/roster_gold_{f}.parquet", REPO / f"data/raw_verified/incfel/roster_gold_{f}.parquet",
                  FRAMES / f"p1_frame_{f}.csv", FRAMES / f"p2_becoming_{f}.csv", FRAMES / f"pairs_none_{f}.parquet",
                  FRAMES / f"p3_afar_pos_{f}.parquet", EXPECTED / f"P1_fnfix_{f}.json", EXPECTED / f"P2_fnfix_{f}.json",
                  EXPECTED / f"P3pos_{f}_A_far.json"]
    files += [FRAMES / "p3_slim_math_stats.parquet", EXPECTED / "P3_fnfix_math_stats.json"]
    from analysis.lib.paths import load_paths                                   # noqa: PLC0415
    v2 = pathlib.Path(load_paths()["legacy_v2_output"])
    inc_legacy = {f: (sha(v2 / f"multidisc_gold_2026-08-10/data/incfel/roster_gold_{f}.parquet") ==
                      sha(REPO / f"data/raw_verified/incfel/roster_gold_{f}.parquet")) for f in FIELDS}
    REPORT["inputs"] = {
        "git_head": head,
        "sha256": {rel(p): sha(p) for p in files},
        "frozen_october_frames_match_their_MANIFEST": {f: manifest_ok(CAL10 / f"frames_{f}") for f in FIELDS},
        "data_frames_equal_frozen_october": {f: all(sha(FRAMES / n) == sha(CAL10 / f"frames_{f}" / n) for n in
                                                    (f"p1_frame_{f}.csv", f"p2_becoming_{f}.csv", f"pairs_none_{f}.parquet",
                                                     f"p3_slim_{f}.parquet", f"p3_slim_ev_{f}.parquet")) for f in FIELDS},
        "incfel_roster_equals_legacy_2026-08-10_copy": inc_legacy,
        "roster_persons": {}}
    import duckdb                                                               # noqa: PLC0415
    con = duckdb.connect()
    for f in FIELDS:
        c = REPO / f"data/raw_verified/roster_gold_{f}.parquet"; i = REPO / f"data/raw_verified/incfel/roster_gold_{f}.parquet"
        q = f"""WITH c AS (SELECT * FROM read_parquet('{c.as_posix()}')), i AS (SELECT * FROM read_parquet('{i.as_posix()}'))
                SELECT (SELECT count(DISTINCT author_id) FROM c), (SELECT count(DISTINCT author_id) FROM i),
                       (SELECT count(DISTINCT author_id) FROM c WHERE author_id NOT IN (SELECT author_id FROM i)),
                       (SELECT count(DISTINCT author_id) FROM i WHERE author_id NOT IN (SELECT author_id FROM c)),
                       (SELECT count(*) FROM c), (SELECT count(*) FROM i)"""
        pc, pi, oc, oi, rc, ri = con.execute(q).fetchone()
        REPORT["inputs"]["roster_persons"][f] = {"canon": pc, "incfel": pi, "only_canon (research-centre staff)": oc,
                                                 "only_incfel": oi, "rows_canon": rc, "rows_incfel": ri}
    con.close()
    for k, v in (("frozen_october_frames_match_their_MANIFEST", REPORT["inputs"]["frozen_october_frames_match_their_MANIFEST"]),
                 ("data_frames_equal_frozen_october", REPORT["inputs"]["data_frames_equal_frozen_october"]),
                 ("incfel_roster_equals_legacy_2026-08-10_copy", inc_legacy)):
        if not all(v.values()):
            stop(f"inputs: {k} = {v}")


# ----------------------------------------------------------------------------------------------
def run_driver(tag: str, extra: list[str]) -> dict:
    root = SCRATCH / f"driver_{tag}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    cmd = [PY, DRIVER, "--execute", *extra]
    r = rs.run_logged(cmd, NC / "logs" / f"driver_{tag}.log", env={"SAR_OUT_ROOT": str(root), "POLARS_MAX_THREADS": "4"})
    rep_p = root / ("frames_run_report_chemmath.json" if (root / "frames_run_report_chemmath.json").is_file()
                    else "frames_run_report_chemmath_FAILED.json")
    rec = {"cmd": " ".join(str(c) for c in cmd), "env": {"SAR_OUT_ROOT": str(root)}, "rc": r["rc"], "secs": r["secs"],
           "log": r["log"], "scratch_report": str(rep_p)}
    if not rep_p.is_file():
        stop(f"driver [{tag}] wrote no report (rc={r['rc']}) — see {r['log']}")
        return rec
    j = json.loads(rep_p.read_text(encoding="utf-8"))
    dst = NC / "driver_reports" / f"frames_run_report_chemmath_{tag}.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(rep_p.read_bytes())
    rec.update({"report": rel(dst), "report_sha256": sha(dst), "driver_stops": j.get("stops", []),
                "roster_variant": j.get("roster_variant"), "products_dir": j.get("products_dir")})
    if r["rc"] != 0 or j.get("stops"):
        stop(f"driver [{tag}] rc={r['rc']} stops={j.get('stops')}")
    rec["fields"] = {}
    for f, F in j.get("fields", {}).items():
        C = F.get("control", {}).get("compare", {})
        ub = C.get("union_build_report", {})
        fr = {"prodlib_control_vs_08_28": F.get("control", {}).get("prodlib", {}).get("prodlib_frame_vs_08_28_staged"),
              "relationships_vs_08_28": C.get("relationships"),
              "union_build_report_vs_08_28": ("EQUAL_MODULO_PATHS" if ub.get("equal_modulo_paths") else
                                              "EQUAL_MODULO_PATHS_AND_H1_ADVISORY" if ub.get("equal_modulo_paths_and_h1_advisory")
                                              else "NOT_EQUAL"),
              "union_build_report_h1_ulp_in_advisory": ub.get("h1_ulp_in_advisory"),
              "p1_frame_vs_08_28_H1": {k: C.get("p1_frame", {}).get(k) for k in ("ok", "differing_lines", "of", "worst_ulp")},
              "p2_becoming_vs_08_28": C.get("p2_becoming"),
              "parquets_vs_08_28": {k: v.get("content") for k, v in C.items() if k.endswith(".parquet")},
              "r_cells_vs_08_28_golds": {c["cell"]: c.get("vs_expected") for c in F.get("control", {}).get("r_cells", [])},
              "prodlib_october": F.get("october", {}).get("prodlib", {}).get("prodlib_frame_vs_08_28_staged"),
              "prodlib_october_sha256": F.get("october", {}).get("prodlib", {}).get("prodlib_frame_sha256"),
              "inpost": F.get("october", {}).get("inpost", {}).get("relations_by_class"),
              "accounting_closed": F.get("accounting", {}).get("closed",
                                                                  all(v.get("closed", True) for v in F.get("accounting", {}).values()
                                                                      if isinstance(v, dict))),
              "products_sha256": F.get("october", {}).get("products_sha256"), "secs": F.get("secs")}
        V = F.get("october", {}).get("vs_frozen_cal2026_10")
        if V is not None:
            fr["october_vs_frozen_cal2026_10"] = {"all_equal": V.get("all_equal"), "relationships": V.get("relationships"),
                                                  "p2_becoming": V.get("p2_becoming"),
                                                  "p1_frame_H1": {k: V.get("p1_frame", {}).get(k) for k in ("ok", "differing_lines", "worst_ulp")},
                                                  "union_build_report": {k: V.get("union_build_report", {}).get(k) for k in
                                                                         ("byte_equal", "equal_modulo_paths", "equal_modulo_paths_and_h1_advisory")},
                                                  "parquets": {k: v.get("content") for k, v in V.items() if k.endswith(".parquet")}}
        ok = (fr["prodlib_control_vs_08_28"] == "BYTE_EQUAL" and fr["relationships_vs_08_28"] == "BYTE_EQUAL"
              and fr["union_build_report_vs_08_28"] != "NOT_EQUAL" and fr["p1_frame_vs_08_28_H1"]["ok"] is True
              and fr["p2_becoming_vs_08_28"] == "BYTE_EQUAL" and set(fr["parquets_vs_08_28"].values()) == {"EQUAL"}
              and set(fr["r_cells_vs_08_28_golds"].values()) == {"EQUAL"} and len(fr["r_cells_vs_08_28_golds"]) == 2)
        if V is not None:
            ok = ok and V.get("all_equal") is True
        fr["control_ok"] = ok
        if not ok:
            stop(f"driver [{tag}] {f}: control not clean: {json.dumps(fr, default=str)[:600]}")
        rec["fields"][f] = fr
    return rec


def population(field: str, variant_report: pathlib.Path) -> dict:
    j = json.loads(variant_report.read_text(encoding="utf-8"))
    A = j["fields"][field]["accounting"]
    R = A["relationships"]
    return {"frozen_october_canon": A["frozen_october_canon"],
            "roster": A["roster"],
            "relationships": {k: R[k] for k in ("relations_canon", "relations_variant", "by_channel_canon", "by_channel_variant",
                                                "persons_canon", "persons_variant", "persons_removed", "persons_added",
                                                "events_canon", "events_variant", "removed", "removed_by_cause",
                                                "removed_by_channel", "channel_changed_as_predicted", "added",
                                                "added_predicted_dept", "closed")},
            "p1_frame": {k: A["p1_frame"][k] for k in ("rows_frozen", "rows_new", "identical", "removed", "added", "modified",
                                                       "rows_by_channel_new", "relations_new", "persons_new", "events_new", "closed")},
            "p2_becoming": {k: A["p2_becoming"][k] for k in ("rows_frozen", "rows_new", "identical", "removed", "added", "modified",
                                                             "events_new", "persons_new", "first_ties_new", "closed")},
            "pairs": A["pairs"], "slim": A["slim"],
            "union_build_report": {k: A["union_build_report"][k] for k in ("frame_october", "frame_variant")},
            "closed": A["closed"]}


# ----------------------------------------------------------------------------------------------
def pos_cut(field: str, sources: dict, out_dir: pathlib.Path) -> dict:
    b = build_afar_cut.build(field, "pos", out_dir, sources=sources)
    assert "frame" in b, b
    fr = pathlib.Path(b["frame"])
    return {**b, "frame": str(fr), "frame_sha256": sha(fr),
            "inputs_sha256": {k: sha(pathlib.Path(v)) for k, v in sources.items()}}


def phase_estimation_controls() -> bool:
    log("== C3: verbatim drivers on the CANON October frames vs analysis/expected")
    out, logs = NC / "estimates_control", NC / "logs"
    cells, comp = [], {}
    for f in FIELDS:
        cells.append({"label": f"P1_fnfix_{f}", "driver": "run_p1.R", "frame": FRAMES / f"p1_frame_{f}.csv"})
        cells.append({"label": f"P2_fnfix_{f}", "driver": "run_p2.R", "frame": FRAMES / f"p2_becoming_{f}.csv"})
        src = {"pairs": FRAMES / f"pairs_none_{f}.parquet", "frame": FRAMES / f"p1_frame_{f}.csv", "p2": FRAMES / f"p2_becoming_{f}.csv"}
        b = pos_cut(f, src, SCRATCH / "afar_control")
        ce = content_equal(pathlib.Path(b["frame"]), FRAMES / f"p3_afar_pos_{f}.parquet")
        b["vs_frozen_pos_frame"] = {"content": "EQUAL" if ce.equal else "NOT_EQUAL", "rows": (ce.rows_a, ce.rows_b),
                                    "frozen": rel(FRAMES / f"p3_afar_pos_{f}.parquet")}
        comp[f"pos_cut_{f}"] = b
        if not ce.equal:
            stop(f"control pos cut {f} is NOT content-equal to data/frames/p3_afar_pos_{f}.parquet")
        cells.append({"label": f"P3cut_pos_{f}", "driver": "run_p3_tp.R", "frame": pathlib.Path(b["frame"])})
    # P3 full math: make_slim on the October pairs table, then run_p3.R
    sd = SCRATCH / "slim_control"; sd.mkdir(parents=True, exist_ok=True)
    ev, noev = sd / "p3_slim_ev_math_stats.parquet", sd / "p3_slim_math_stats.parquet"
    ms = rs.run_logged([PY, REPO / "pipeline/frames/make_slim.py", "math_stats", FRAMES / "pairs_none_math_stats.parquet", ev, "--noev", noev],
                       logs / "make_slim_control.log")
    ce = content_equal(noev, FRAMES / "p3_slim_math_stats.parquet")
    comp["make_slim_math_stats"] = {"rc": ms["rc"], "stdout_tail": ms["stdout"].strip()[-300:],
                                    "slim_vs_data_frames": {"content": "EQUAL" if ce.equal else "NOT_EQUAL", "rows": (ce.rows_a, ce.rows_b)}}
    if ms["rc"] != 0 or not ce.equal:
        stop("control make_slim on data/frames/pairs_none_math_stats.parquet is not content-equal to data/frames/p3_slim_math_stats.parquet")
    cells.append({"label": "P3_fnfix_math_stats", "driver": "run_p3.R", "frame": noev})
    res = rs.run_cells(cells, out, logs)
    gold = {f"P3cut_pos_{f}": EXPECTED / f"P3pos_{f}_A_far.json" for f in FIELDS}
    for label, r in res.items():
        g = gold.get(label, EXPECTED / f"{label}.json")
        r["compare"] = rs.compare(REPO / r["json"], g) if r.get("json") else {"verdict": "NOT_EQUAL", "gold": rel(g)}
        if r["compare"]["verdict"] != "EQUAL":
            stop(f"estimation control {label} NOT compare_json-EQUAL to {rel(g)}")
    REPORT["controls"]["estimation"] = {"cells": res, "frames": comp,
                                        "all_equal": all(r["compare"]["verdict"] == "EQUAL" for r in res.values())}
    log(f"   estimation controls EQUAL: {sum(r['compare']['verdict'] == 'EQUAL' for r in res.values())}/{len(res)}")
    return REPORT["controls"]["estimation"]["all_equal"]


def phase_variant_cells() -> None:
    log("== variant cells (verbatim drivers on the incfel-roster frames)")
    out, logs = NC / "estimates", NC / "logs"
    cells, frames = [], {}
    for f in FIELDS:
        d = PRODUCTS / f"frames_{f}"
        p1, p2, pairs = d / f"p1_frame_{f}.csv", d / f"p2_becoming_{f}.csv", d / f"pairs_none_{f}.parquet"
        cells.append({"label": f"P1nc_{f}", "driver": "run_p1.R", "frame": p1})
        cells.append({"label": f"P2nc_{f}", "driver": "run_p2.R", "frame": p2})
        b = pos_cut(f, {"pairs": pairs, "frame": p1, "p2": p2}, SCRATCH / "afar_variant")
        frames[f"pos_cut_{f}"] = b
        cells.append({"label": f"P3nc_pos_{f}_A_far", "driver": "run_p3_tp.R", "frame": pathlib.Path(b["frame"])})
    cells.append({"label": "P3nc_math_stats_full", "driver": "run_p3.R", "frame": PRODUCTS / "frames_math_stats/p3_slim_math_stats.parquet"})
    res = rs.run_cells(cells, out, logs)
    for label, r in res.items():
        old = OLD / f"{label}.json"
        r["previous_2026-08-29_headline"] = rs.headline(json.loads(old.read_text(encoding="utf-8"))) if old.is_file() else None
        r["previous_2026-08-29_note"] = ("2026-08-28 caliber, no D2 in-post filter (data/robustness_2026-08-29_b/nocentre)"
                                         if old.is_file() else "no earlier cell (the 2026-09-10 pos launcher STOPped)")
        if r.get("status") != "OK":
            stop(f"variant cell {label}: {r.get('status')}")
    REPORT["cells"] = res
    REPORT["variant_afar_pos_frames"] = frames
    REPORT["variant_frames_sha256"] = {}
    for f in FIELDS:
        d = PRODUCTS / f"frames_{f}"
        REPORT["variant_frames_sha256"][f] = {p.name: sha(p) for p in sorted(d.iterdir()) if p.is_file()}
        vd = NC / f"variant_frames_{f}"; vd.mkdir(parents=True, exist_ok=True)
        for name in (f"build_report_{f}.json", f"inpost_report_{f}.json", f"inpost_relations_{f}.csv",
                     f"staging_manifest_{f}.json", f"union_build_report_{f}.json"):
            (vd / name).write_bytes((d / name).read_bytes())
        (vd / "products_MANIFEST.sha256").write_bytes((d / "MANIFEST.sha256").read_bytes())


# ----------------------------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--execute", action="store_true", help="required: two chem/math frame builds against the data disk + 14 R cells")
    args = ap.parse_args(argv)
    if not args.execute:
        print(__doc__); return 2
    SCRATCH.mkdir(parents=True, exist_ok=True)
    for d in ("estimates", "estimates_control", "driver_reports", "logs"):
        (NC / d).mkdir(parents=True, exist_ok=True)
    for f in FIELDS:
        if (NC / f"variant_frames_{f}").exists():
            shutil.rmtree(NC / f"variant_frames_{f}")
    for p in list((NC / "estimates").glob("*.json")) + list((NC / "estimates_control").glob("*.json")):
        p.unlink()
    REPORT.update({"group": "nocentre", "caliber": "cal2026-10", "generated": time.strftime("%Y-%m-%d %H:%M"),
                   "runner": rel(pathlib.Path(__file__)), "scratch": str(SCRATCH), "products_dir": str(PRODUCTS),
                   "r_cap": int(os.environ["SAR_R_CAP"]), "battery_jobs": int(os.environ["BATTERY_JOBS"]),
                   "design": "analysis/robustness/sensitivity/run_nocentre.py (T6-1: the ONE substitution is the roster; canon "
                             "roster_gold_<f> with research-centre staff merged in vs the frozen INCFEL roster) applied inside the "
                             "October chain: pipeline/frames/cal2026-10/run_cal_frames_chemmath.py --roster-variant incfel",
                   "controls": {}})
    phase_inputs()
    if STOPS:
        freeze("STOPPED_PRECONDITION"); return 1
    log("== C1: driver, unchanged roster, --no-freeze")
    REPORT["driver_runs"] = {"control": run_driver("control", ["--no-freeze"])}
    if STOPS:
        freeze("STOPPED_CONTROL_NOT_EQUAL"); return 1
    log("== variant build: driver --roster-variant incfel --products-dir")
    if PRODUCTS.exists():
        shutil.rmtree(PRODUCTS)
    REPORT["driver_runs"]["variant"] = run_driver("variant", ["--roster-variant", "incfel", "--products-dir", str(PRODUCTS)])
    if STOPS:
        freeze("STOPPED_CONTROL_NOT_EQUAL"); return 1
    vrep = NC / "driver_reports" / "frames_run_report_chemmath_variant.json"
    REPORT["population"] = {f: population(f, vrep) for f in FIELDS}
    for f in FIELDS:
        log(f"   population {f}: roster persons {REPORT['population'][f]['roster']['canon']['persons']} -> "
            f"{REPORT['population'][f]['roster']['variant']['persons']}; relations "
            f"{REPORT['population'][f]['relationships']['relations_canon']} -> {REPORT['population'][f]['relationships']['relations_variant']}; "
            f"p1 rows {REPORT['population'][f]['p1_frame']['rows_frozen']} -> {REPORT['population'][f]['p1_frame']['rows_new']}; "
            f"accounting closed={REPORT['population'][f]['closed']}")
    REPORT["controls"]["driver_control_run"] = REPORT["driver_runs"]["control"]["fields"]
    REPORT["controls"]["driver_variant_run_phase_C"] = {f: {k: v for k, v in d.items() if k not in ("products_sha256",)}
                                                        for f, d in REPORT["driver_runs"]["variant"]["fields"].items()}
    if not phase_estimation_controls():
        freeze("STOPPED_CONTROL_NOT_EQUAL"); return 1
    phase_variant_cells()
    if (NC / "NOT_RUN.md").is_file():
        (NC / "NOT_RUN.md").unlink()
        REPORT["replaced"] = "NOT_RUN.md (2026-09-23, 'controls NOT EQUAL' under the 08-28 launchers) deleted; this report replaces it"
    freeze("DONE" if not STOPS else "DONE_WITH_STOPS")
    log(f"NOCENTRE_CAL2026_10_{'OK' if not STOPS else 'WITH_STOPS'} ({REPORT['secs']} s) stops={STOPS}")
    return 0 if not STOPS else 1


if __name__ == "__main__":
    raise SystemExit(main())
