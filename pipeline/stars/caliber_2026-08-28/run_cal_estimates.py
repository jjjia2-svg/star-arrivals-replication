#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""caliber_2026-08-28/run_cal_estimates.py — Task-4 driver: every locally runnable estimation
cell on the caliber frames (data/cal2026-08-28/frames/), plus the old-vs-new comparison table.
Repo-authored launcher (declared in `pipeline.lib.paths.LAUNCHERS`); it runs NO ported python —
it drives the VERBATIM R estimation drivers in `analysis/estimation/` through their own contract
(argv + $SAR_OUT), exactly as `analysis/run_all.sh` does for the frozen frames.

    export SAR_OUT_ROOT=/private/tmp/<empty dir>       # scratch, NEVER under ~/Documents
    python3 "pipeline/stars/caliber_2026-08-28/run_cal_estimates.py" --execute

Phases:
  V  verify — each cal frame a cell consumes is hashed against data/cal2026-08-28/MANIFEST.sha256
     (the produced side must estimate the FROZEN cal frames, not whatever sits on disk).
  R  run — the 19 local cells, sequentially, each in a subprocess with $SAR_OUT under the scratch
     root and a per-cell log. The econ P1 cell runs TWICE (separate run dir): the two results
     must be compare_json-EQUAL (determinism under the new frames). The evcl cells' 3rd argument
     is the CAL person/pair-cluster result from this run (the self-check is 'same frame, other
     cluster', so the frozen ref would be the wrong operand). A cell that errors is STOPPED and
     its log reported — never patched; a cell that exceeds ~30 min or OOMs is killed and
     registered for Task 5 with the measurement. Any stop freezes NOTHING.
  C  compare — old (analysis/expected/) vs new (this run) for every cell: ATE/effects, SE, p, N,
     events, switchers; flags for sign changes, p crossing .05/.01, |dATE|>20%. The cal old79
     cell (byte-identical frame, T3) must be compare_json-EQUAL to the frozen gold — a positive
     control on the estimator environment. No interpretation beyond the table.
  F  freeze — data/cal2026-08-28/estimates/ (result JSONs in the expected/ shape + the
     determinism re-run + the run report), MANIFEST regenerated (pure addition), and the
     generated comparison table at docs/reviews/2026-08-28_cal_vs_frozen_estimates.md.

The cell inventory below is PINNED (tests/test_cal_estimates_2026_08_28.py): together with
CLOUD_T5 it partitions the 23 frozen expected cells exactly — no cell unaccounted. The four
cloud cells (econ/chem P3 main + evcl pair panels; tools/compare_all.py CLOUD_ONLY) are Task 5's.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
from typing import NamedTuple

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))

from analysis.lib.compare_json import compare        # noqa: E402
from pipeline.lib.paths import OUT_ROOT_ENV, PathUnresolved  # noqa: E402

CAL_DIR = REPO / "data" / "cal2026-08-28"
FRAMES = CAL_DIR / "frames"
EST_OUT = CAL_DIR / "estimates"
EXPECTED = REPO / "analysis" / "expected"
EST_DRV = REPO / "analysis" / "estimation"
DOC_OUT = REPO / "docs" / "reviews" / "2026-08-28_cal_vs_frozen_estimates.md"
CELL_TIMEOUT_S = 1860                    # the ~30-minute local budget; beyond it -> Task 5


class Cell(NamedTuple):
    name: str        # label given to the R driver == output JSON stem
    driver: str      # file under analysis/estimation/
    frame: str       # file under data/cal2026-08-28/frames/
    ref: str | None  # cal cell whose JSON is the evcl self-check ref (None: no 3rd arg)


#: the 19 locally runnable cells, in run order (refs resolve to earlier cells).
LOCAL_CELLS: tuple[Cell, ...] = (
    Cell("P1_econ_fnfix",         "run_p1.R",      "p1_frame_econ.csv",           None),
    Cell("P1_fnfix_chemistry",    "run_p1.R",      "p1_frame_chemistry.csv",      None),
    Cell("P1_fnfix_math_stats",   "run_p1.R",      "p1_frame_math_stats.csv",     None),
    Cell("P1_econ_fnfix_old79",   "run_p1.R",      "p1_frame_econ_old79.csv",     None),
    # honestly named: A5044432173's removal turns the new-events split 38 -> 37 (T3 R-T3-1)
    Cell("P1_econ_fnfix_new37",   "run_p1.R",      "p1_frame_econ_new37.csv",     None),
    Cell("P2_econ_fnfix",         "run_p2.R",      "p2_becoming_econ.csv",        None),
    Cell("P2_fnfix_chemistry",    "run_p2.R",      "p2_becoming_chemistry.csv",   None),
    Cell("P2_fnfix_math_stats",   "run_p2.R",      "p2_becoming_math_stats.csv",  None),
    Cell("P3_fnfix_math_stats",   "run_p3.R",      "p3_slim_math_stats.parquet",  None),
    Cell("P1evcl_econ",           "run_p1_evcl.R", "p1_frame_econ.csv",           "P1_econ_fnfix"),
    Cell("P1evcl_chemistry",      "run_p1_evcl.R", "p1_frame_chemistry.csv",      "P1_fnfix_chemistry"),
    Cell("P1evcl_math_stats",     "run_p1_evcl.R", "p1_frame_math_stats.csv",     "P1_fnfix_math_stats"),
    Cell("P2evcl_econ",           "run_p2_evcl.R", "p2_becoming_econ.csv",        "P2_econ_fnfix"),
    Cell("P2evcl_chemistry",      "run_p2_evcl.R", "p2_becoming_chemistry.csv",   "P2_fnfix_chemistry"),
    Cell("P2evcl_math_stats",     "run_p2_evcl.R", "p2_becoming_math_stats.csv",  "P2_fnfix_math_stats"),
    Cell("P3evcl_math_stats",     "run_p3_evcl.R", "p3_slim_ev_math_stats.parquet",
         "P3_fnfix_math_stats"),
    Cell("P3lb_econ_A_far",       "run_p3_tp.R",   "p3_afar_econ.parquet",        None),
    Cell("P3lb_chemistry_A_far",  "run_p3_tp.R",   "p3_afar_chemistry.parquet",   None),
    Cell("P3lb_math_stats_A_far", "run_p3_tp.R",   "p3_afar_math_stats.parquet",  None),
)

#: cal cell name -> frozen expected stem, where they differ (the honest rename).
FROZEN_NAME: dict[str, str] = {"P1_econ_fnfix_new37": "P1_econ_fnfix_new38"}

#: the four cloud-only estimation cells (tools/compare_all.py CLOUD_ONLY): the pair panels whose
#: dCDH run needed a 495 GB instance for the frozen numbers. Registered for Task 5, with payloads.
CLOUD_T5: tuple[str, ...] = ("P3_econ_fnfix", "P3_fnfix_chemistry",
                             "P3evcl_econ", "P3evcl_chemistry")
CLOUD_PAYLOAD: dict[str, str] = {
    "P3_econ_fnfix":      "p3_slim_econ.parquet",
    "P3_fnfix_chemistry": "p3_slim_chemistry.parquet",
    "P3evcl_econ":        "p3_slim_ev_econ.parquet",
    "P3evcl_chemistry":   "p3_slim_ev_chemistry.parquet",
}

OUT_OF_SCOPE: tuple[dict, ...] = (
    {"item": "p3_afar_speed_bracket",
     "reason": "not an estimation cell, and it has no cal counterpart: its pairs_slim_cap_* "
               "inputs have no builder anywhere (pipeline/NOT_REPRODUCIBLE.md entry 9; "
               "registered again in T3) — there is nothing to estimate"},
    {"item": "B0_null_test.R",
     "reason": "the null-simulation robustness driver is not part of this repository "
               "(config/seeds.yaml: 'robustness, not in M0/M1'); no frozen expected cell exists "
               "for it, so it is outside the old-vs-new comparison by construction"},
    {"item": "analysis/robustness/",
     "reason": "holds only p3_afar/build_afar.py — a FRAME builder (its cal output was built and "
               "frozen in Task 3), not an estimation cell; the old79/new37 split cells ARE "
               "estimation cells and sit in the local inventory"},
    {"item": "analysis/paper generators",
     "reason": "a later step: the paper artifacts were regenerated only after the new numbers "
               "were approved (stop point)"},
)

STOPS: list[str] = []
REPORT: dict = {"task": "T4 local estimation under cal2026-08-28"}


def log(msg: str) -> None:
    print(f"[run_cal_estimates] {msg}", flush=True)


def stop(msg: str) -> None:
    STOPS.append(msg)
    print(f"\n*** STOP: {msg}", flush=True)


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def cal_manifest() -> dict[str, str]:
    """data/cal2026-08-28/MANIFEST.sha256 as {repo-relative path: sha256}."""
    out = {}
    for line in (CAL_DIR / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        if line.strip():
            h, rel = line.split("  ", 1)
            out[rel] = h
    return out


# ---------------------------------------------------------------------------------------------
# phase R — one cell in a subprocess
# ---------------------------------------------------------------------------------------------

def run_cell(cell: Cell, run_dir: pathlib.Path, ref_dir: pathlib.Path | None) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    argv = ["Rscript", str(EST_DRV / cell.driver), cell.name, str(FRAMES / cell.frame)]
    if cell.ref is not None:
        argv.append(str((ref_dir or run_dir) / f"{cell.ref}.json"))
    env = dict(os.environ, SAR_OUT=str(run_dir), PYTHONHASHSEED="0")
    logf = run_dir / f"{cell.name}.log"
    t0 = time.time()
    rec = {"cell": cell.name, "driver": cell.driver,
           "frame": f"data/cal2026-08-28/frames/{cell.frame}", "ref": cell.ref}
    log(f"cell {cell.name}: {cell.driver} on {cell.frame}" +
        (f" (ref {cell.ref})" if cell.ref else ""))
    try:
        with open(logf, "wb") as lf:
            r = subprocess.run(argv, cwd=REPO, env=env, timeout=CELL_TIMEOUT_S,
                               stdout=lf, stderr=subprocess.STDOUT)
    except subprocess.TimeoutExpired:
        rec.update(status="TIMEOUT_REGISTER_T5", secs=round(time.time() - t0, 1),
                   measurement=f"killed after {CELL_TIMEOUT_S}s (~30 min local budget)")
        stop(f"{cell.name} exceeded {CELL_TIMEOUT_S}s — killed, register for Task 5")
        return rec
    rec["secs"] = round(time.time() - t0, 1)
    tail = logf.read_bytes()[-2000:].decode("utf-8", "replace")
    produced = run_dir / f"{cell.name}.json"
    if r.returncode != 0 or not produced.is_file():
        oom = "cannot allocate" in tail or r.returncode == -9
        rec.update(status="OOM_REGISTER_T5" if oom else "CELL_ERROR",
                   returncode=r.returncode, log_tail=tail)
        stop(f"{cell.name} {'OOM — register for Task 5' if oom else 'errored'} "
             f"(rc={r.returncode}); log: {logf}")
        return rec
    j = json.loads(produced.read_text(encoding="utf-8"))
    bad = _not_ok(j)
    if bad:
        rec.update(status="CELL_ERROR", log_tail=tail, detail=bad)
        stop(f"{cell.name} produced a non-OK result ({bad}); log: {logf}")
        return rec
    rec.update(status="OK", json_sha=sha(produced))
    return rec


def _not_ok(j: dict) -> str | None:
    if "channels" in j:
        bad = [c for c, v in j["channels"].items() if v.get("status") != "OK"]
        if bad:
            return f"channels {bad}"
    elif "pair_cluster" in j:
        for k in ("pair_cluster", "event_cluster"):
            if j[k].get("ate") is None:
                return f"{k} has no ATE"
    elif j.get("status") != "OK":
        return f"status={j.get('status')!r}"
    pec = j.get("point_estimate_check")           # evcl cells: same frame, other cluster
    if pec is not None:
        vals = list(pec.values()) if isinstance(pec, dict) else [pec]
        if any(v != "MATCH" for v in vals):
            return f"point_estimate_check {pec}"
    return None


# ---------------------------------------------------------------------------------------------
# phase C — extraction, flags, table
# ---------------------------------------------------------------------------------------------

def rows_for(label: str, j: dict) -> list[dict]:
    """One comparison row per estimated variant (P1: channel; A_far: cluster; else: main)."""
    rows = []
    if "channels" in j:
        for ch in ("union", "network", "dept"):
            c = j["channels"][ch]
            rows.append(dict(cell=label, variant=ch, ate=c.get("ate"), se=c.get("se"),
                             lb=c.get("lb"), ub=c.get("ub"), p_je=c.get("p_joint_effects"),
                             p_pl=c.get("p_joint_placebo"), n=c.get("obs"),
                             events=c.get("events"), effects=c.get("effects", [])))
    elif "pair_cluster" in j:
        for tag in ("pair_cluster", "event_cluster"):
            c = j[tag]
            rows.append(dict(cell=label, variant=tag, ate=c.get("ate"), se=c.get("se"),
                             lb=c.get("lb"), ub=c.get("ub"), p_je=c.get("p_joint_effects"),
                             p_pl=None, n=j.get("rows"), events=j.get("events"),
                             effects=c.get("effects", [])))
    else:
        rows.append(dict(cell=label, variant="main", ate=j.get("ate"), se=j.get("se"),
                         lb=j.get("lb"), ub=j.get("ub"), p_je=j.get("p_joint_effects"),
                         p_pl=j.get("p_joint_placebo"), n=j.get("rows"),
                         events=j.get("events", j.get("clusters")),
                         effects=j.get("effects", [])))
    return rows


def flags_for(o: dict, n: dict) -> list[str]:
    fl = []
    ao, an = o.get("ate"), n.get("ate")
    if ao is not None and an is not None:
        if ao * an < 0:
            fl.append("ATE_SIGN_CHANGE")
        if ao != 0 and abs(an - ao) / abs(ao) > 0.20:
            fl.append(f"dATE_{abs(an - ao) / abs(ao) * 100:.0f}%")
    for key, tag in (("p_je", "p_effects"), ("p_pl", "p_placebo")):
        po, pn = o.get(key), n.get(key)
        if po is None or pn is None:
            continue
        for thr in (0.05, 0.01):
            if (po < thr) != (pn < thr):
                fl.append(f"{tag}_crosses_{thr}({po:.4g}->{pn:.4g})")
    if None not in (o.get("lb"), o.get("ub"), n.get("lb"), n.get("ub")):
        sig_o = o["lb"] > 0 or o["ub"] < 0
        sig_n = n["lb"] > 0 or n["ub"] < 0
        if sig_o != sig_n:
            fl.append("ATE_CI_zero_crossing_change")
    eo = {e["k"]: e for e in o.get("effects", [])}
    en = {e["k"]: e for e in n.get("effects", [])}
    ks = sorted(set(eo) & set(en))
    sc = [k for k in ks if eo[k].get("est") is not None and en[k].get("est") is not None
          and eo[k]["est"] * en[k]["est"] < 0]
    if sc:
        fl.append("effect_sign_change_k=" + ",".join(map(str, sc)))
    big = [k for k in ks if eo[k].get("est") and en[k].get("est") is not None
           and abs(en[k]["est"] - eo[k]["est"]) / abs(eo[k]["est"]) > 0.20]
    if big:
        fl.append("effect_dATE>20%_k=" + ",".join(map(str, big)))
    return fl


def build_comparison(cal: dict[str, dict]) -> list[dict]:
    """[{cell, variant, old:{...}, new:{...}, flags:[...]}] for every local cell, in run order."""
    out = []
    for c in LOCAL_CELLS:
        exp = json.loads((EXPECTED / (FROZEN_NAME.get(c.name, c.name) + ".json"))
                         .read_text(encoding="utf-8"))
        old_rows = {r["variant"]: r for r in rows_for(c.name, exp)}
        new_rows = {r["variant"]: r for r in rows_for(c.name, cal[c.name])}
        for var in old_rows:
            o, n = old_rows[var], new_rows[var]
            out.append({"cell": c.name, "variant": var, "old": o, "new": n,
                        "flags": flags_for(o, n)})
    return out


def _f(x, spec=".8g") -> str:
    return "—" if x is None else format(x, spec)


def write_doc(comparison: list[dict], rep: dict) -> None:
    L = []
    add = L.append
    add("# Cal 2026-08-28 vs frozen estimates — every locally run cell, old vs new")
    add("")
    add("> GENERATED by `pipeline/stars/caliber_2026-08-28/run_cal_estimates.py` from")
    add("> `analysis/expected/*.json` (old = the frozen gold standards) and")
    add("> `data/cal2026-08-28/estimates/*.json` (new = this run on the caliber frames).")
    add("> Comparison only — no tuning, no interpretation. Values are the drivers' own JSON")
    add("> units (P3-family ATEs are per-year probabilities: ×100 = percentage points).")
    add("")
    o = next(r for r in comparison if r["cell"] == "P3lb_econ_A_far"
             and r["variant"] == "pair_cluster")
    add("## The headline first: econ A_far (Panel 3, pair-cluster)")
    add("")
    add(f"* old (frozen): ATE {o['old']['ate']:.8f} (SE {o['old']['se']:.8f}) — the paper's "
        f"−0.132 pp/yr (0.049), p_joint_effects {_f(o['old']['p_je'], '.4g')}")
    add(f"* new (cal):    ATE {o['new']['ate']:.8f} (SE {o['new']['se']:.8f}) = "
        f"{o['new']['ate'] * 100:.3f} pp/yr ({o['new']['se'] * 100:.3f}), "
        f"p_joint_effects {_f(o['new']['p_je'], '.4g')}")
    add(f"* flags: {', '.join(o['flags']) if o['flags'] else 'none'}")
    add("")
    add("## ATE-level table (every cell × variant)")
    add("")
    add("`p_je` = joint p over the dynamic effects; `p_pl` = joint placebo p (— where the "
        "driver does not report one). `N` = estimated observations (P1: post-filter non-NA "
        "rows; P2/P3: panel rows). new37's frozen counterpart is `P1_econ_fnfix_new38`.")
    add("")
    add("| cell | variant | ATE old | ATE new | SE old | SE new | p_je old | p_je new | "
        "p_pl old | p_pl new | N old→new | events old→new | flags |")
    add("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in comparison:
        o_, n_ = r["old"], r["new"]
        add(f"| {r['cell']} | {r['variant']} | {_f(o_['ate'])} | {_f(n_['ate'])} | "
            f"{_f(o_['se'])} | {_f(n_['se'])} | {_f(o_['p_je'], '.4g')} | "
            f"{_f(n_['p_je'], '.4g')} | {_f(o_['p_pl'], '.4g')} | {_f(n_['p_pl'], '.4g')} | "
            f"{_f(o_['n'], '')}→{_f(n_['n'], '')} | {_f(o_['events'], '')}→"
            f"{_f(n_['events'], '')} | {', '.join(r['flags']) if r['flags'] else '' } |")
    add("")
    add("## Per-effect coefficients (k = years since arrival)")
    add("")
    for r in comparison:
        eo = {e["k"]: e for e in r["old"].get("effects", [])}
        en = {e["k"]: e for e in r["new"].get("effects", [])}
        if not eo and not en:
            continue
        add(f"### {r['cell']} / {r['variant']}")
        add("")
        has_sw = any("switchers" in e for e in r["old"].get("effects", []))
        head = "| k | est old | est new | se old | se new | n old→new |"
        head += " switchers old→new |" if has_sw else ""
        add(head)
        add("|---|---|---|---|---|---|" + ("---|" if has_sw else ""))
        for k in sorted(set(eo) | set(en)):
            o_, n_ = eo.get(k, {}), en.get(k, {})
            line = (f"| {k} | {_f(o_.get('est'))} | {_f(n_.get('est'))} | "
                    f"{_f(o_.get('se'))} | {_f(n_.get('se'))} | "
                    f"{_f(o_.get('n'), '')}→{_f(n_.get('n'), '')} |")
            if has_sw:
                line += f" {_f(o_.get('switchers'), '')}→{_f(n_.get('switchers'), '')} |"
            add(line)
        add("")
    add("## Mechanical delta — is each move consistent with the event delta? (descriptive)")
    add("")
    add("The caliber's frame delta (T3, row-accounted to zero unaccounted): econ −1 event "
        "(A5044432173:2006 out; P1 −1,012 rows, 88 colleague rows persist; P2 −1,547; "
        "A_far 87→86 events), chemistry +3 events (A5027778630, A5091826237, A5062352558; P1 46,552→50,193 "
        "rows incl. ~450 enrichment/ex_star-rippled person-years; A_far 30→33), math_stats "
        "+2 events (A5017222669, A5090916445; P1 23,232→24,211, ~54 rippled rows; A_far 29→31). "
        "Chem/math also recompose slightly through the moved H5 topic cuts "
        "(econ .3332→.3340, chem .3427→.3388, math .0885→.0897) and the five stars' "
        "network-channel colleague-row removal. Per cell, events old→new below:")
    add("")
    for r in comparison:
        if r["variant"] in ("union", "main", "pair_cluster"):
            add(f"* {r['cell']}: events {_f(r['old']['events'], '')}→"
                f"{_f(r['new']['events'], '')}, N {_f(r['old']['n'], '')}→"
                f"{_f(r['new']['n'], '')}"
                + (f" — flags: {', '.join(r['flags'])}" if r["flags"] else ""))
    add("")
    add("## Determinism + positive control")
    add("")
    d = rep["determinism"]
    add(f"* `P1_econ_fnfix` run twice on the cal frame (separate run dirs): compare_json "
        f"**{d['compare']}** (run1 sha {d['run1_sha'][:12]}…, run2 sha {d['run2_sha'][:12]}…).")
    add(f"* `P1_econ_fnfix_old79` on the byte-identical cal old79 frame vs the frozen gold: "
        f"**{rep['old79_control']['compare']}** — the estimator environment reproduces the "
        f"frozen numbers exactly where the frame did not change.")
    add("")
    add("## Registered for Task 5 (cloud) / out of scope")
    add("")
    for r in rep["registered_for_t5"]:
        add(f"* **{r['cell']}** — {r['reason']} Payload: `{r['payload']}` "
            f"(sha256 {r['payload_sha'][:12]}…).")
    for o_ in rep["out_of_scope"]:
        add(f"* out of scope — **{o_['item']}**: {o_['reason']}")
    add("")
    add(f"Cells run locally: {len(LOCAL_CELLS)} (+1 determinism re-run) · registered for "
        f"Task 5: {len(CLOUD_T5)} · frozen expected cells accounted: "
        f"{len(LOCAL_CELLS) + len(CLOUD_T5)}/23.")
    add("")
    DOC_OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    log(f"comparison table written: {DOC_OUT.relative_to(REPO)} ({len(L)} lines)")


# ---------------------------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--execute", action="store_true",
                    help="required: ~20 sequential dCDH runs (minutes of R)")
    ap.add_argument("--refreeze", action="store_true",
                    help="allow replacing an existing data/cal2026-08-28/estimates/")
    args = ap.parse_args(argv)
    if not args.execute:
        print("This runs every local estimation cell on the cal frames (minutes of R). "
              "Re-run with --execute.", file=sys.stderr)
        return 2
    out_root = os.environ.get(OUT_ROOT_ENV, "").strip()
    if not out_root:
        raise PathUnresolved(f"set ${OUT_ROOT_ENV} to an empty absolute directory under /private/tmp")
    root = pathlib.Path(out_root)
    if not root.is_dir() or any(root.iterdir()):
        raise PathUnresolved(f"${OUT_ROOT_ENV} must be an existing EMPTY directory: {root}")
    if EST_OUT.exists() and not args.refreeze:
        raise PathUnresolved(f"{EST_OUT} already exists — pass --refreeze to replace it")
    if shutil.which("Rscript") is None:
        raise PathUnresolved("Rscript is not on PATH — the estimation cells cannot run")

    REPORT.update({
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "authority": "the author's decision record of 2026-08-28 (private archive)",
        "r_env": subprocess.run(
            ["Rscript", "-e",
             'cat(as.character(getRversion()), as.character(packageVersion("DIDmultiplegtDYN")),'
             ' as.character(packageVersion("polars")), as.character(packageVersion("data.table")),'
             ' as.character(packageVersion("jsonlite")))'],
            capture_output=True, text=True).stdout.strip(),
        "cell_timeout_s": CELL_TIMEOUT_S,
    })

    # ---- V: the frames a cell consumes must be the FROZEN cal frames -------------------------
    man = cal_manifest()
    hashes = {}
    for c in LOCAL_CELLS:
        rel = f"data/cal2026-08-28/frames/{c.frame}"
        if rel not in hashes:
            got = sha(REPO / rel)
            if man.get(rel) != got:
                stop(f"{rel}: on-disk sha {got[:12]}… != MANIFEST {man.get(rel, '?')[:12]}…")
            hashes[rel] = got
    REPORT["input_hashes"] = hashes
    if STOPS:
        return finish(root, ok=False)
    log(f"phase V: {len(hashes)} cal frames hash-verified against MANIFEST.sha256")

    # ---- R: the cells, sequentially; econ P1 twice -------------------------------------------
    cells_dir, det_dir = root / "cells", root / "det"
    recs = []
    t_all = time.time()
    for c in LOCAL_CELLS:
        rec = run_cell(c, cells_dir, cells_dir)
        recs.append(rec)
        if rec["status"] != "OK":
            break
        if c.name == "P1_econ_fnfix":                     # determinism double run, fresh dir
            rec2 = run_cell(c, det_dir, det_dir)
            rec2["cell"] = "P1_econ_fnfix#run2"
            recs.append(rec2)
            if rec2["status"] != "OK":
                break
    REPORT["cells"] = recs
    REPORT["secs_total"] = round(time.time() - t_all, 1)
    if STOPS:
        return finish(root, ok=False)

    # ---- C: determinism, positive control, comparison ----------------------------------------
    run1 = json.loads((cells_dir / "P1_econ_fnfix.json").read_text(encoding="utf-8"))
    run2 = json.loads((det_dir / "P1_econ_fnfix.json").read_text(encoding="utf-8"))
    det_diffs = compare(run1, run2)
    REPORT["determinism"] = {"cell": "P1_econ_fnfix",
                             "run1_sha": sha(cells_dir / "P1_econ_fnfix.json"),
                             "run2_sha": sha(det_dir / "P1_econ_fnfix.json"),
                             "compare": "EQUAL" if not det_diffs else "DIFF",
                             "diffs": det_diffs[:20]}
    if det_diffs:
        stop(f"determinism double run DIFFERS: {det_diffs[:3]}")
    old79 = compare(json.loads((cells_dir / "P1_econ_fnfix_old79.json").read_text("utf-8")),
                    json.loads((EXPECTED / "P1_econ_fnfix_old79.json").read_text("utf-8")))
    REPORT["old79_control"] = {"compare": "EQUAL" if not old79 else "DIFF",
                               "diffs": old79[:20]}
    if old79:
        stop(f"old79 positive control DIFFERS from the frozen gold on a byte-identical frame "
             f"— estimator environment suspect: {old79[:3]}")
    if STOPS:
        return finish(root, ok=False)
    log("determinism EQUAL; old79 positive control EQUAL")

    cal = {c.name: json.loads((cells_dir / f"{c.name}.json").read_text(encoding="utf-8"))
           for c in LOCAL_CELLS}
    comparison = build_comparison(cal)
    REPORT["comparison_rows"] = [
        {k: r[k] for k in ("cell", "variant", "flags")} |
        {"old": {k2: r["old"][k2] for k2 in ("ate", "se", "p_je", "p_pl", "n", "events")},
         "new": {k2: r["new"][k2] for k2 in ("ate", "se", "p_je", "p_pl", "n", "events")}}
        for r in comparison]
    REPORT["registered_for_t5"] = [
        {"cell": name,
         "reason": "cloud-only estimation cell (tools/compare_all.py CLOUD_ONLY): the dCDH run "
                   "on this pair panel exceeded local memory for the frozen numbers (M3: "
                   "r6i.16xlarge, 495 GB) — same footing under the caliber.",
         "payload": f"data/cal2026-08-28/frames/{CLOUD_PAYLOAD[name]}",
         "payload_sha": man[f"data/cal2026-08-28/frames/{CLOUD_PAYLOAD[name]}"]}
        for name in CLOUD_T5]
    REPORT["out_of_scope"] = list(OUT_OF_SCOPE)

    # ---- F: freeze ---------------------------------------------------------------------------
    if EST_OUT.exists():
        shutil.rmtree(EST_OUT)
    (EST_OUT / "determinism").mkdir(parents=True)
    for c in LOCAL_CELLS:
        (EST_OUT / f"{c.name}.json").write_bytes((cells_dir / f"{c.name}.json").read_bytes())
    (EST_OUT / "determinism" / "P1_econ_fnfix_run2.json").write_bytes(
        (det_dir / "P1_econ_fnfix.json").read_bytes())
    (EST_OUT / "estimates_run_report_2026-08-28.json").write_text(
        json.dumps(REPORT, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    write_doc(comparison, REPORT)
    manifest = "".join(
        f"{sha(f)}  data/cal2026-08-28/{f.relative_to(CAL_DIR).as_posix()}\n"
        for f in sorted(CAL_DIR.rglob("*"))
        if f.is_file() and f.name != "MANIFEST.sha256")
    (CAL_DIR / "MANIFEST.sha256").write_text(manifest, encoding="utf-8")
    log(f"frozen {len(LOCAL_CELLS) + 2} files into {EST_OUT.relative_to(REPO)}; MANIFEST "
        f"regenerated ({manifest.count(chr(10))} entries)")
    flagged = [r for r in comparison if r["flags"]]
    log(f"comparison: {len(comparison)} variant rows, {len(flagged)} flagged — see "
        f"{DOC_OUT.name}")
    return finish(root, ok=True)


def finish(root: pathlib.Path, ok: bool) -> int:
    if not ok:
        REPORT["stops"] = STOPS
        p = root / "estimates_run_report_FAILED.json"
        p.write_text(json.dumps(REPORT, ensure_ascii=False, indent=1, default=str),
                     encoding="utf-8")
        log(f"{len(STOPS)} STOP condition(s) — NOTHING frozen. Report at {p}")
        return 1
    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
