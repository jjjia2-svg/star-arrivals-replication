#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cal2026-10/run_cal_frames_chemmath.py — the October caliber's CHEMISTRY and MATHEMATICS frames:
control chain first (must reproduce the 2026-08-28 frozen products), then the October chain with
the D2 in-post stage, products under data/cal2026-10/frames_<field>/. Repo-authored launcher
(declared in `pipeline.lib.paths.LAUNCHERS`); it runs the pinned prodlib trio verbatim (in process,
inside a staged_run mark — `stage.run_prodlib`), the ported gold builders through
`pipeline/frames/run_frames.py` subprocesses (union-gold, p1-gold, p2-gold, exactly phase G of
`pipeline/stars/caliber_2026-08-28/run_cal_frames.py`), `pipeline/frames/make_slim.py`, and the
VERBATIM R estimation drivers on the control products. It edits no ported file, no legacy file, no
frozen artifact, no gold (analysis/expected is read only), and it does not run the A_far build
(that build spans all three fields; the final driver runs it) and nothing on AWS.

    export SAR_OUT_ROOT=/private/tmp/<empty dir>          # never under a cloud-synced folder
    export SAR_R1_CONFIG=$PWD/config/r1/B0.json           # the run config (R1 F3); unset = STOP
    setup/.venv/bin/python pipeline/frames/cal2026-10/run_cal_frames_chemmath.py --execute \
        --october-ref DIR
    # review rerun (every phase, nothing written under data/): add --no-freeze

--october-ref DIR (required, R1 F3, 2026-10-15): the directory holding October's products at their
repo paths. Every read of an October product in phase P comes from it — the data/frames/ anchors
(hashed against the repo's data/MANIFEST.sha256, which stays in the repo) and the
data/cal2026-10/frames_<field>/ anchors (against the MANIFEST.sha256 inside that copy); a missing
file there is a STOP. J0 passes /work/ref/october (the sandbox's read-only copy, from which the
in-repo products have been moved); an in-place run on this machine passes the repo root, which
reads exactly what the code read before the flag existed. The shadows' event tables and the econ
u4_aug inputs come from the run config's `stage` section (stage.stage_config()).

What the October caliber changes for these two fields (verified at the start of the run, not
assumed — a failed check is a STOP):
  * the October event tables data/cal2026-10/events_{chemistry,math_stats}_cal2026-10.csv are
    BYTE-IDENTICAL to the 2026-08-28 tables (no chemistry / mathematics event moved);
  * the rosters data/raw_verified/roster_gold_<field>.parquet are the legacy files (sha asserted
    by stage.build_shadow);
  * so the ONLY change is D2 (the author's ruling of 2026-09-22): a NETWORK-route incumbent
    must hold a roster spell (roster_gold_<field>: year_start <= arrival <= year_end, ANY
    department of the field's sample — the join is on the person, not on the event's school)
    covering the event's arrival year. `inpost_filter.py` applies it to the prodlib output frame
    BEFORE the union builder (equivalent to a per-event pool restriction because prodlib's
    closure restricts only the incumbent end — stage.py, "Where the D2 filter sits"); the roster
    channel's own school-matched in-post join in the union builder is untouched.

Phases, per field
  P  preconditions: event tables byte-identical to 08-28; frozen-side anchors — every frozen
     operand is hashed against data/MANIFEST.sha256 (data/frames/) or
     data/cal2026-08-28/MANIFEST.sha256 (data/cal2026-08-28/frames/) before any comparison.
  C  the CONTROL chain, no in-post filter, on its own shadow (stage.build_shadow, October
     tables): prodlib (rendered config == frames_stage.prodlib_config(cal=True) key for key;
     frame BYTE_EQUAL to the 08-28 staged prodlib frame — the sha recorded as
     `cal-stage:prodlib <field>` in data/cal2026-08-28/frames/staging_manifest_2026-08-28.json,
     piece A's C2 re-asserted here) -> union-gold -> p1-gold -> p2-gold --panel3 full ->
     make_slim. Acceptance, per file, as the 08-28 freeze and tests/test_pipeline_rebuild.py
     define it:
       relationships_<field>.csv        BYTE_EQUAL to data/cal2026-08-28/frames/
       union_build_report_<field>.json  EQUAL modulo path-valued strings (run-dir paths differ)
       p1_frame_<field>.csv             NOT byte-reproducible by design (pipeline/frames/README.md
                                        §5, NOT_REPRODUCIBLE.md entry 10): same line count, same
                                        header, only fwci_frac / fwci_frac_ex_star may differ,
                                        every difference <= 8 ULP (the M3 bound; measured 1-3);
                                        any other column, or a larger ULP, is a STOP
       p2_becoming_<field>.csv          BYTE_EQUAL to data/frames/
       pairs_none_<field>.parquet       content-equal (D1: tools/content_equal) to
                                        data/cal2026-08-28/frames/
       p3_slim{,_ev}_<field>.parquet    content-equal to data/frames/
     then run_p1.R / run_p2.R (verbatim, their own argv + $SAR_OUT contract) on the control
     p1 frame / becoming panel must be analysis/lib/compare_json-EQUAL to
     analysis/expected/P1_fnfix_<field>.json and P2_fnfix_<field>.json.
  O  the OCTOBER chain on a second shadow: prodlib again (BYTE_EQUAL to the same 08-28 sha —
     the rung is deterministic and the October inputs are the 08-28 inputs) -> inpost_filter
     (spells = roster_gold_<field>, identity person map, bare author_id form: the prodlib frame's
     incumbent_person_id IS the OpenAlex author id for these fields) -> the filtered frame
     installed at the topicdose path the union builder reads -> union-gold -> p1-gold ->
     p2-gold --panel3 full -> make_slim.
  X  row-level accounting of every October product against its 08-28 frozen counterpart (the
     union frame, which has no frozen copy, against this run's CONTROL union frame). Named
     causes, verified per row: `dropped_not_in_post` / `dropped_no_spell` (the filter's class of
     the row's (person, event)) for removed rows; `h1_fwci_ulp` (fwci_frac / fwci_frac_ex_star,
     <= 8 ULP — hazard H1) for modified rows; nothing else. Added rows have no cause and are
     reported as unaccounted (a network alias dropped by D2 could in principle release a
     `dept_only` twin the union builder had suppressed as alias_dup, but both frozen builds
     record v9_drop_alias_dup = 0, and the October value is recorded). Relationships by channel
     (removed relations must all be network-channel: a person in post at the event's school is
     in post at a department of the field, so `both` cannot be dropped — asserted), persons per
     layer, pairs removed iff an endpoint's (person, event) was dropped and no surviving pair's
     rows changed, slims a faithful projection of the October pair table. An accounting that
     does not close freezes NOTHING for that field.
  F  freeze: data/cal2026-10/frames_<field>/ with the data/frames basenames (p1_frame, p2_becoming,
     pairs_none, relationships, union_build_report, p3_slim, p3_slim_ev), the in-post filter's
     own report, build_report_<field>.json (controls, October stages, the in-post per-event /
     per-class counts, the accounting), staging_manifest_<field>.json (both shadows), and a
     MANIFEST.sha256 inside the directory (the per-directory manifest precedent of
     data/cal2026-10/econ_gold_control/; the top-level data/cal2026-10/MANIFEST.sha256 is not
     regenerated here — the final driver's job, it sweeps sibling products this run must not).

Measured 2026-09-23 (the run that froze data/cal2026-10/frames_{chemistry,math_stats}/; 56 s; the
run report is data/cal2026-10/frames_run_report_chemmath_2026-09-23.json; the sentinel is
tests/test_cal2026_10_chemmath.py, which re-derives the D2 class of every relation by SQL)
  controls, both fields: prodlib BYTE_EQUAL to the 08-28 staged frame on both shadows (chemistry
    359f270a…, math_stats ca6d75f1…); relationships.csv and becoming_none.csv BYTE_EQUAL to the
    freeze; union build_report byte-equal; p1 frame within H1 (chemistry 6,394 of 50,193 lines
    differ, worst 4 ULP; math_stats 1,276 of 24,211, worst 2 ULP; fwci_frac / fwci_frac_ex_star
    only); pairs_none / p3_slim / p3_slim_ev content-EQUAL; run_p1.R / run_p2.R on the control
    products compare_json-EQUAL to analysis/expected/P{1,2}_fnfix_{chemistry,math_stats}.json.
  October (D2), chemistry: relations 3,611 -> 1,833 kept / 1,778 dropped_not_in_post / 0
    dropped_no_spell (rows 39,721 -> 20,163; persons 240 lose every event, 217 keep at least one);
    union frame 50,193 -> 30,635 rows; relationships 4,563 -> 2,785 (network 3,153 -> 1,375, both
    458 and dept_only 952 unchanged); persons 486 -> 470; events 38 (none left without network
    rows); p2 becoming 76,087 -> 46,168 rows, first ties 155; pairs 286,998 -> 109,984
    (rows 4,805,989 -> 1,823,689, ties 4,687); every accounting closed with the two named causes
    only (H1 worst 3 ULP).
  October (D2), math_stats: relations 771 -> 380 kept / 391 dropped_not_in_post / 0 no_spell
    (rows 8,481 -> 4,180); union frame 24,211 -> 19,910 rows; relationships 2,201 -> 1,810
    (network 647 -> 256, both 124 and dept_only 1,430 unchanged); persons 498 -> 481; events 33,
    ONE event keeps no network row (A5074032970:monash — its roster channel still supplies rows,
    so the event stays in every frame); p2 becoming 36,824 -> 30,314 rows, first ties 35; pairs
    80,320 -> 55,237 (rows 1,353,396 -> 929,324, ties 1,031); every accounting closed (H1 worst
    3 ULP).
  Both fields: v9_drop_alias_dup 0 -> 0 (no released dept twin, no added row anywhere).

Adversarial review 2026-09-23 (rerun with --no-freeze into a scratch root, 60.7 s, stops = []):
  controls again BYTE_EQUAL/EQUAL on both fields (prodlib 359f270a / ca6d75f1; the four R cells
  EQUAL); the rerun's October relationships / p2_becoming / union_build_report BYTE_EQUAL to the
  frozen data/cal2026-10/frames_<field>/ files, its p1 frame within H1 against the frozen one
  (chemistry 4,167 rows, math_stats 1,266 rows, fwci columns only, worst 4 ULP), pairs_none / slims
  content-EQUAL, and every accounting number identical to the frozen build reports. Independent
  re-derivations by the reviewer: keyed p1/p2 accounting with strict column coverage of the ULP
  measurement (every modified column measured, worst 3 ULP), every kept relationships / p2 line
  byte-identical to the frozen line in frozen order, every October pair row content-present in the
  frozen pair table, no removed pair row without a dropped endpoint. Written down: the October p1
  kept rows are NOT byte-identical to their frozen source (H1, NOT_REPRODUCIBLE.md entry 10); the
  p2 kept rows and the filtered prodlib frame are. The roster the spells come from
  (data/raw_verified/roster_gold_<field>.parquet) is the same file the prodlib pool and the union
  builder's roster channel read (frames_stage.prodlib_config / 10_build_union_frame_gold.py:82),
  which is why dropped_no_spell is 0 by construction; the smaller data/raw_verified/incfel/ variant
  is not the chain's roster (under it 652 chemistry / 50 math_stats classes would differ — record
  only). One defect found: commit 8ff742f edited pipeline/lib/paths.py (LAUNCHERS) without
  refreshing its REPO_AUTHORED pin (the pin test passes at 11cf7a8 and fails at 8ff742f); repinned.

Assumptions written down
  * Two DuckDB-heavy stages at a time at most: every builder stage runs sequentially; only the
    two R cells of a field's control (no DuckDB) run in the background while the October chain
    of the same field runs.
  * The H1 acceptance bound is 8 ULP (frames_stage / cal_accounting's `h1_fwci_ulp` bound); the
    measured worst ULP is recorded in the report so the "±3" characterisation can be checked.
  * The union frame is an intermediate (input of p1-gold / p2-gold); it is not frozen, but its
    sha and line count are recorded and the October one is accounted against the control one.
  * The slims of the October run have no frozen counterpart (grp / ev re-rank); acceptance is
    a faithful projection of the October pair table (cal_accounting.slim_consistency).

2026-09-23 (after the promotion 73777aa; the ± research-centre check T6-1)
  * data/frames IS the October canon since the promotion, and analysis/expected holds the October
    golds. The CONTROL chain (no in-post filter) reproduces the 2026-08-28 products, so its
    references follow them: every control comparison reads data/cal2026-08-28/frames/ (the
    08-28 copies of p1 / p2 / slims / relationships / pairs / union report, anchored in
    data/cal2026-08-28/MANIFEST.sha256) and the control R cells compare to the frozen 08-28 golds
    data/cal2026-08-28/estimates/P{1,2}_fnfix_<field>.json (same manifest). The October
    accounting (phase X) still runs against the 08-28 frozen frames, as written above. Nothing
    else about the default run changed; preconditions record which copy data/frames currently is
    instead of asserting the two copies equal.
  * Union build report, control and review comparisons: G_VAL_advisory.examples[i][5] is the FRESH
    fwci value the union builder's advisory recomputes, i.e. the H1 sum (NOT_REPRODUCIBLE.md, the
    chem/math P1 entry). Measured 2026-09-23: 1 ULP on two math_stats examples (the frozen 08-28
    and October reports carry the other rounding). The comparison accepts a difference ONLY at
    that path and only within the H1 bound (8 ULP), records n / worst ULP
    (`h1_ulp_in_advisory`), and STOPs on anything else — the same characterisation the p1 frame
    already gets, applied to the one more place the same value is printed.
  * Review modes (--no-freeze, or --products-dir with the default roster) compare the October
    chain's products to the frozen data/cal2026-10/frames_<field>/ (relationships / p2 BYTE_EQUAL,
    union report equal modulo paths, p1 within H1, pairs / slims content-equal) and STOP on a
    difference; a freeze run only records that comparison (the frozen copy is about to be
    replaced).
  * --roster-variant incfel (the ± research-centre check, analysis/robustness/sensitivity/
    run_nocentre.py's ONE substitution): after the shadows are built, the OCTOBER shadow's link
    multidisc_gold_2026-08-10/data/fnfix/roster_gold_<field>.parquet is re-pointed at the frozen
    INCFEL roster data/raw_verified/incfel/roster_gold_<field>.parquet (no research-centre staff;
    the same artifact the 2026-08-10 and 2026-08-29 runs used), and the in-post spells are read
    from that same file (sha asserted equal to the link) — prodlib's pool and in-dept index, the
    union builder's dept channel and row fill, and the D2 filter therefore all see one roster.
    The control shadow keeps the canon roster, so phase C is unchanged and remains the machine
    control. The variant prodlib frame is NOT expected to equal the 08-28 staged frame (recorded,
    not a STOP); phase X is replaced by a variant accounting against the frozen October canon
    with named causes only (person not in the variant roster / no variant spell covering the
    arrival, per channel; a `both` relation whose dept spell is gone becomes `network` and vice
    versa; row fill changes where a year's in-post status differs between the two spell sets;
    H1 fwci ULP noise), and phase F writes to --products-dir (required for a variant; never
    under data/). Default behaviour (--roster-variant fnfix) is unchanged.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))
sys.path.insert(0, str(HERE))
import stage                                                            # noqa: E402
import inpost_filter as ipf                                             # noqa: E402
fs08 = stage.fs08
OLD_LAYER = REPO / "pipeline" / "stars" / "caliber_2026-08-28"
if str(OLD_LAYER) not in sys.path:
    sys.path.insert(0, str(OLD_LAYER))
import cal_accounting as ca08                                           # noqa: E402

from analysis.lib.compare_json import compare                           # noqa: E402
from analysis.lib.paths import load_paths                               # noqa: E402
from pipeline.lib.paths import OUT_ROOT_ENV, PathUnresolved             # noqa: E402
from tools.content_equal import content_equal                           # noqa: E402

PY = sys.executable
GOLD = stage.GOLD
FIELDS = stage.FIELDS_GOLD
CAL10, CAL08, RAW = stage.CAL10, stage.CAL08, stage.RAW
FRAMES08 = CAL08 / "frames"
FRAMES = REPO / "data" / "frames"
EXPECTED = REPO / "analysis" / "expected"
EXPECTED08 = CAL08 / "estimates"          # the 08-28 golds of the CONTROL chain (2026-09-23 note)
EST_DRV = REPO / "analysis" / "estimation"
INCFEL = RAW / "incfel"                    # the frozen no-centre rosters (± research-centre check)
ROSTER_VARIANTS = ("fnfix", "incfel")
OUTCOME_COLS = ("fwci_frac", "pub_count", "fwci_frac_ex_star", "pub_count_ex_star",
                "fwci_mean", "fwci_mean_ex_star")
ULP_BOUND = 8
H1_COLS = {"fwci_frac", "fwci_frac_ex_star"}
FWCI_COLS = ("fwci_frac", "fwci_frac_ex_star", "fwci_mean", "fwci_mean_ex_star")
PRODUCTS = ("p1_frame_{f}.csv", "p2_becoming_{f}.csv", "pairs_none_{f}.parquet",
            "relationships_{f}.csv", "union_build_report_{f}.json",
            "p3_slim_{f}.parquet", "p3_slim_ev_{f}.parquet")

STOPS: list[str] = []
REPORT: dict = {}
sha = fs08.sha


def stop(msg: str) -> None:
    STOPS.append(msg)
    print(f"\n*** STOP: {msg}", flush=True)


def log(msg: str) -> None:
    print(f"[run_cal_frames_chemmath] {msg}", flush=True)


def prodlib_rel(field: str) -> str:
    return f"{GOLD}/runs/fnfix/{field}/data/analysis_frame_p01_52ev_topicdose_2026-07-21.csv"


# ---------------------------------------------------------------------------------------------
# stage runners (the 08-28 driver's, unchanged in shape)
# ---------------------------------------------------------------------------------------------

def run_stage(name: str, scratch: pathlib.Path, args: tuple[str, ...], shadow: pathlib.Path) -> dict:
    """One run_frames stage in a subprocess with $SAR_OUT_ROOT=scratch and $SAR_LEGACY_THESIS=shadow;
    returns the run dir and the launcher's produced-report {abs path: sha256}."""
    scratch.mkdir(parents=True, exist_ok=False)
    cmd = [PY, str(REPO / "pipeline/frames/run_frames.py"), name, "--execute", "--", *args]
    env = {**os.environ, OUT_ROOT_ENV: str(scratch), "SAR_LEGACY_THESIS": str(shadow)}
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, env=env)
    out = proc.stdout + proc.stderr
    (scratch / f"{name}.log").write_text(out, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"run_frames.py {name} {args} failed ({proc.returncode}):\n{out[-4000:]}")
    m = re.search(r"run directory -> (.+)", proc.stdout)
    produced = {p: s for p, s in
                re.findall(r"^\s+OK\s+(/.+?)\s+\(\d[\d,]* B, sha256 ([0-9a-f]{64})\)$",
                           proc.stdout, re.M)}
    assert m and produced, f"launcher reported no run dir / outputs:\n{out[-2000:]}"
    secs = round(time.time() - t0, 1)
    log(f"stage {name} {' '.join(args)} finished in {secs} s ({len(produced)} outputs)")
    return {"run_dir": pathlib.Path(m.group(1).strip()), "produced": produced, "secs": secs,
            "stage": name, "args": list(args)}


def run_make_slim(field: str, src: pathlib.Path, out_dir: pathlib.Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=False)
    ev = out_dir / f"p3_slim_ev_{field}.parquet"
    noev = out_dir / f"p3_slim_{field}.parquet"
    t0 = time.time()
    proc = subprocess.run([PY, str(REPO / "pipeline/frames/make_slim.py"), field, str(src),
                           str(ev), "--noev", str(noev)], cwd=REPO, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    stats = eval(proc.stdout.strip().splitlines()[-1], {"__builtins__": {}}, {})  # noqa: S307
    log(f"make_slim {field} finished in {time.time() - t0:.1f} s: {stats}")
    return {"ev": ev, "noev": noev, "stats": stats, "secs": round(time.time() - t0, 1)}


#: the paths file the recorded 08-28 prodlib configs were written with (the Mac roots)
RECORDED_PATHS = REPO / "config" / "paths.yaml"
ROOT_KEYS = ("legacy_v2_output", "legacy_thesis", "ssd_root")


def rebase_recorded_roots(cfg: dict) -> tuple[dict, list[str]]:
    """`cfg` with each string under a recorded root (config/paths.yaml) moved onto this host's
    configured root, and the keys that moved. Nothing moves on the Mac; on EC2 the recorded
    snapshot globs name the Mac disks."""
    old, new = load_paths(RECORDED_PATHS), load_paths()
    pairs = sorted(((str(old[k]), str(new[k])) for k in ROOT_KEYS if str(old[k]) != str(new[k])),
                   key=lambda p: -len(p[0]))
    moved: list[str] = []

    def walk(v, where):
        if isinstance(v, dict):
            return {k: walk(x, f"{where}.{k}" if where else k) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x, f"{where}[{i}]") for i, x in enumerate(v)]
        if isinstance(v, str):
            for a, b in pairs:
                if v == a or v.startswith(a + "/"):
                    moved.append(where)
                    return b + v[len(a):]
        return v

    return walk(cfg, ""), moved


def run_prodlib(field: str, root: pathlib.Path, shadow_root: pathlib.Path, tag: str,
                rec: dict, expect_08_28: bool = True) -> pathlib.Path:
    """prodlib on the cal2026-10 template: config asserted equal to frames_stage.prodlib_config
    (cal=True) key for key, frame asserted BYTE_EQUAL to the 08-28 staged prodlib frame."""
    mirror = root / f"{tag}_prodlib_{field}"
    run_dir = mirror / "runs" / field
    cfg = stage.render_config(field, shadow_root, run_dir)
    ref, rec["config_ref_roots_rebased"] = rebase_recorded_roots(
        fs08.prodlib_config(field, shadow_root, run_dir, cal=True))
    core = lambda c: {k: v for k, v in c.items() if k not in ("label", "_cal2026_10_note")}  # noqa: E731
    rec["config_equal_to_08_28_prodlib_config"] = core(cfg) == core(ref)
    if not rec["config_equal_to_08_28_prodlib_config"]:
        diff = sorted(k for k in set(cfg) | set(ref)
                      if k not in ("label", "_cal2026_10_note") and cfg.get(k) != ref.get(k))
        stop(f"{field} [{tag}]: rendered prodlib config differs from frames_stage.prodlib_config"
             f"(cal=True) in {diff}")
    out = stage.run_prodlib(field, mirror, cfg, rec)
    want = want_prodlib_sha(field)
    got = sha(out)
    rec["prodlib_frame_vs_08_28_staged"] = "BYTE_EQUAL" if got == want else "NOT_EQUAL"
    rec["prodlib_frame_sha256"] = got
    rec["prodlib_frame_sha256_08_28"] = want
    rec["prodlib_frame_lines"] = out.read_bytes().count(b"\n")
    log(f"prodlib {field} [{tag}]: {rec['prodlib_frame_vs_08_28_staged']} ({got[:12]} vs {want[:12]})")
    if not expect_08_28:
        rec["prodlib_frame_vs_08_28_staged"] += " (VARIANT roster: equality not expected, recorded only)"
    elif got != want:
        stop(f"{field} [{tag}]: prodlib frame {got} is not the 08-28 staged prodlib frame {want} — "
             f"the rung would mix machine noise into the D2 accounting")
    return out


def want_prodlib_sha(field: str) -> str:
    sm = json.loads((FRAMES08 / "staging_manifest_2026-08-28.json").read_text("utf-8"))
    want = {e["origin"].split()[-1]: e["sha256"] for e in sm["entries"]
            if e["origin"].startswith("cal-stage:prodlib ")}
    return want[field]


# ---------------------------------------------------------------------------------------------
# the chain (union-gold -> p1-gold -> p2-gold -> make_slim), the 08-28 phase G
# ---------------------------------------------------------------------------------------------

def run_chain(field: str, root: pathlib.Path, sh: fs08.Shadow, tag: str,
              network_frame: pathlib.Path, origin: str) -> dict:
    shadow_root = sh.root.parent
    sh.install(prodlib_rel(field), network_frame, origin)
    stages: dict[str, dict] = {}
    st = run_stage("union-gold", root / f"{tag}_union_{field}", ("--field", field), shadow_root)
    stages["union"] = st
    for name in (f"analysis_frame_{field}_2026-08-10.csv", "relationships.csv",
                 "build_report.json", "funnel.json"):
        sh.install(f"{GOLD}/data/fnfix/union_frame_{field}/{name}",
                   st["run_dir"] / f"data/fnfix/union_frame_{field}/{name}",
                   f"{tag}-stage:union-gold {field}")
    st = run_stage("p1-gold", root / f"{tag}_p1_{field}", ("--field", field), shadow_root)
    stages["p1"] = st
    sh.install(f"{GOLD}/data/fnfix/analysis_frame_{field}_new_gold_2026-08-10.csv",
               st["run_dir"] / f"data/fnfix/analysis_frame_{field}_new_gold_2026-08-10.csv",
               f"{tag}-stage:p1-gold {field}")
    st = run_stage("p2-gold", root / f"{tag}_p2_{field}", ("--field", field, "--panel3", "full"),
                   shadow_root)
    stages["p2"] = st
    for name in ("becoming_none.csv", "pairs_none.parquet", "pairs_slim_none.parquet"):
        sh.install(f"{GOLD}/data/fnfix/panels23_{field}_gold/{name}",
                   st["run_dir"] / f"data/fnfix/panels23_{field}_gold/{name}",
                   f"{tag}-stage:p2-gold {field}")
    stages["slim"] = run_make_slim(field, sh.path(f"{GOLD}/data/fnfix/panels23_{field}_gold/pairs_none.parquet"),
                                   root / f"{tag}_slim_{field}")
    return stages


def products_of(field: str, stages: dict) -> dict[str, pathlib.Path]:
    rd = {k: v["run_dir"] for k, v in stages.items() if "run_dir" in v}
    return {
        "union_frame": rd["union"] / f"data/fnfix/union_frame_{field}/analysis_frame_{field}_2026-08-10.csv",
        f"relationships_{field}.csv": rd["union"] / f"data/fnfix/union_frame_{field}/relationships.csv",
        f"union_build_report_{field}.json": rd["union"] / f"data/fnfix/union_frame_{field}/build_report.json",
        f"p1_frame_{field}.csv": rd["p1"] / f"data/fnfix/analysis_frame_{field}_new_gold_2026-08-10.csv",
        f"p2_becoming_{field}.csv": rd["p2"] / f"data/fnfix/panels23_{field}_gold/becoming_none.csv",
        f"pairs_none_{field}.parquet": rd["p2"] / f"data/fnfix/panels23_{field}_gold/pairs_none.parquet",
        f"p3_slim_ev_{field}.parquet": stages["slim"]["ev"],
        f"p3_slim_{field}.parquet": stages["slim"]["noev"],
    }


# ---------------------------------------------------------------------------------------------
# comparisons
# ---------------------------------------------------------------------------------------------

def h1_characterise(frozen: pathlib.Path, rebuilt: pathlib.Path) -> dict:
    """Same line count, same header, only fwci_frac / fwci_frac_ex_star may differ, every
    difference within ULP_BOUND (run_cal_frames.union_characterise, generalised)."""
    fa = open(frozen, newline="", encoding="utf-8").readlines()
    fb = open(rebuilt, newline="", encoding="utf-8").readlines()
    if len(fa) != len(fb):
        return {"ok": False, "reason": f"line counts differ {len(fa)} vs {len(fb)}"}
    if fa[0] != fb[0]:
        return {"ok": False, "reason": "header differs"}
    cols = next(csv.reader([fa[0]]))
    n, worst, badcols = 0, 0, set()
    for a, b in zip(fa[1:], fb[1:]):
        if a == b:
            continue
        n += 1
        ca, cb = next(csv.reader([a])), next(csv.reader([b]))
        if len(ca) != len(cb):
            badcols.add("<row shape>")
            continue
        for j, (x, y) in enumerate(zip(ca, cb)):
            if x != y:
                if cols[j] not in H1_COLS:
                    badcols.add(cols[j])
                else:
                    try:
                        worst = max(worst, fs08.ulps(float(x), float(y)))
                    except ValueError:
                        badcols.add(cols[j])
    return {"ok": not badcols and worst <= ULP_BOUND, "byte_equal": n == 0, "differing_lines": n,
            "of": len(fa) - 1, "worst_ulp": worst, "ulp_bound": ULP_BOUND,
            "unexpected_columns": sorted(badcols)}


def _mask_paths(o):
    if isinstance(o, dict):
        return {k: _mask_paths(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_mask_paths(v) for v in o]
    if isinstance(o, str) and ("/" in o and (o.startswith("/") or "v2_output" in o)):
        return "<path>"
    return o


#: the ONE place H1 (NOT_REPRODUCIBLE.md, "NOT BYTE-REPRODUCIBLE — the two chem/math P1 levels
#: frames") surfaces inside the union build report: G_VAL_advisory.examples[i] is
#: [pid, event, year, column, old_value, FRESH_value] and the fresh fwci value is the H1 sum.
#: Measured 2026-09-23 (math_stats control build): 1 ULP on examples[0][5] / [1][5]; both frozen
#: reports (08-28 and October) carry the other rounding. Accepted ONLY here, only within ULP_BOUND,
#: and recorded with the worst ULP; any other difference is a STOP.
#: 2026-10-16 (EC2, j0-03/j0-04): the OLD frame values (examples[i][4], fill_examples[i][5]) are what
#: pandas parsed from the old CSV, and its C parser rounds differently on x86-64 Linux and arm64 macOS
#: (2 ULP measured on both); fill_examples[i][6] is the FRESH H1 sum, as examples[i][5]. Same bound,
#: same record; a non-number on either side or any other path still STOPs.
_H1_ADVISORY_RE = re.compile(r"^G_VAL_advisory\.(?:examples\[\d+\]\[[45]\]|fill_examples\[\d+\]\[[56]\]): '([^']*)' != '([^']*)'$")


def json_equal_modulo_paths(a: pathlib.Path, b: pathlib.Path) -> dict:
    ja, jb = json.loads(a.read_text("utf-8")), json.loads(b.read_text("utf-8"))
    byte = a.read_bytes() == b.read_bytes()
    ma, mb = _mask_paths(ja), _mask_paths(jb)
    diffs = compare(ma, mb, ignore=())
    worst, other = 0, []
    for d in diffs:
        m = _H1_ADVISORY_RE.match(d)
        try:
            u = fs08.ulps(float(m.group(1)), float(m.group(2))) if m else None
        except ValueError:
            u = None
        if u is not None and u <= ULP_BOUND:
            worst = max(worst, u)
        else:
            other.append(d)
    return {"byte_equal": byte, "equal_modulo_paths": not diffs,
            "equal_modulo_paths_and_h1_advisory": not other,
            "h1_ulp_in_advisory": {"n": len(diffs) - len(other), "worst_ulp": worst, "ulp_bound": ULP_BOUND},
            "diffs": diffs[:20]}


def anchor_frozen(path: pathlib.Path, manifest: pathlib.Path, rel: str) -> None:
    line = f"{sha(path)}  {rel}"
    assert line in manifest.read_text(encoding="utf-8"), (
        f"{rel} does not match its line in {manifest.relative_to(REPO)} — the frozen operand "
        f"of this comparison is not the shipped artifact")


def control_compare(field: str, prod: dict[str, pathlib.Path]) -> dict:
    """The control chain's products against the 08-28 frozen products (data/cal2026-08-28/frames/,
    the copies that stay 08-28 after the promotion), per-file acceptance."""
    C: dict = {}
    f = field
    rel_frozen = FRAMES08 / f"relationships_{f}.csv"
    C["relationships"] = "BYTE_EQUAL" if sha(prod[f"relationships_{f}.csv"]) == sha(rel_frozen) \
        else "NOT_EQUAL"
    if C["relationships"] != "BYTE_EQUAL":
        stop(f"{f} control: relationships.csv is not byte-equal to the frozen 08-28 one")
    C["union_build_report"] = json_equal_modulo_paths(prod[f"union_build_report_{f}.json"],
                                                      FRAMES08 / f"union_build_report_{f}.json")
    if not C["union_build_report"]["equal_modulo_paths_and_h1_advisory"]:
        stop(f"{f} control: union build_report differs beyond run-dir paths and the H1 advisory "
             f"example: {C['union_build_report']['diffs'][:5]}")
    elif not C["union_build_report"]["equal_modulo_paths"]:
        log(f"{f} control: union build_report equal modulo paths and H1 in G_VAL_advisory examples "
            f"({C['union_build_report']['h1_ulp_in_advisory']})")
    u = prod["union_frame"]
    C["union_frame"] = {"sha256": sha(u), "lines": u.read_bytes().count(b"\n"),
                        "byte_equal_to_08_28_staged": sha(u) == staged_sha(f"{GOLD}/data/fnfix/union_frame_{f}/analysis_frame_{f}_2026-08-10.csv"),
                        "note": "intermediate, not frozen; H1 noise expected (README §8)"}
    ch = h1_characterise(FRAMES08 / f"p1_frame_{f}.csv", prod[f"p1_frame_{f}.csv"])
    C["p1_frame"] = ch
    if not ch["ok"]:
        stop(f"{f} control: p1 frame differs beyond the H1 characterisation: {ch}")
    C["p2_becoming"] = "BYTE_EQUAL" if sha(prod[f"p2_becoming_{f}.csv"]) == \
        sha(FRAMES08 / f"p2_becoming_{f}.csv") else "NOT_EQUAL"
    if C["p2_becoming"] != "BYTE_EQUAL":
        stop(f"{f} control: becoming_none.csv is not byte-equal to the frozen 08-28 p2_becoming_{f}.csv")
    for name, frozen in ((f"pairs_none_{f}.parquet", FRAMES08 / f"pairs_none_{f}.parquet"),
                         (f"p3_slim_{f}.parquet", FRAMES08 / f"p3_slim_{f}.parquet"),
                         (f"p3_slim_ev_{f}.parquet", FRAMES08 / f"p3_slim_ev_{f}.parquet")):
        r = content_equal(prod[name], frozen)
        C[name] = {"content": "EQUAL" if r.equal else "NOT_EQUAL", "rows": (r.rows_a, r.rows_b),
                   "schema_equal": r.schema_equal, "byte_equal": sha(prod[name]) == sha(frozen)}
        if not r.equal:
            stop(f"{f} control: {name} is not content-equal to the frozen one:\n{r.detail[:1500]}")
    return C


def staged_sha(rel: str) -> str | None:
    sm = json.loads((FRAMES08 / "staging_manifest_2026-08-28.json").read_text("utf-8"))
    for e in sm["entries"]:
        if e["rel"] == rel:
            return e["sha256"]
    return None


# ---------------------------------------------------------------------------------------------
# the R cells (control products only)
# ---------------------------------------------------------------------------------------------

def start_r_cell(label: str, driver: str, frame: pathlib.Path, out_dir: pathlib.Path,
                 expected_dir: pathlib.Path = EXPECTED08):
    out_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, SAR_OUT=str(out_dir), PYTHONHASHSEED="0")
    logf = open(out_dir / f"{label}.log", "wb")
    p = subprocess.Popen(["Rscript", str(EST_DRV / driver), label, str(frame)], cwd=REPO, env=env,
                         stdout=logf, stderr=subprocess.STDOUT)
    return {"proc": p, "log": logf, "label": label, "out": out_dir / f"{label}.json",
            "t0": time.time(), "driver": driver, "frame": str(frame),
            "expected": expected_dir / f"{label}.json"}


def finish_r_cell(cell: dict) -> dict:
    rc = cell["proc"].wait()
    cell["log"].close()
    rec = {"cell": cell["label"], "driver": cell["driver"], "frame": cell["frame"],
           "secs": round(time.time() - cell["t0"], 1), "returncode": rc}
    if rc != 0 or not cell["out"].is_file():
        rec["status"] = "CELL_ERROR"
        rec["log_tail"] = pathlib.Path(str(cell["log"].name)).read_bytes()[-1500:].decode("utf-8", "replace")
        stop(f"{cell['label']} errored (rc={rc}) — see {cell['log'].name}")
        return rec
    new = json.loads(cell["out"].read_text("utf-8"))
    exp = json.loads(cell["expected"].read_text("utf-8"))
    diffs = compare(new, exp)
    rec["status"] = "OK"
    rec["expected"] = str(cell["expected"].relative_to(REPO))
    rec["vs_expected"] = "EQUAL" if not diffs else "DIFF"
    rec["diffs"] = diffs[:20]
    rec["json_sha256"] = sha(cell["out"])
    if diffs:
        stop(f"{cell['label']} on the control frame is NOT compare_json-EQUAL to "
             f"{rec['expected']}: {diffs[:3]}")
    log(f"R cell {cell['label']}: {rec['vs_expected']} vs {rec['expected']} ({rec['secs']} s)")
    return rec


# ---------------------------------------------------------------------------------------------
# the October accounting
# ---------------------------------------------------------------------------------------------

def classify_keyed(acc: dict, cls: dict[tuple[str, str], str], pid_ix: int, ev_ix: int,
                   allow_h1: bool, name: str) -> dict:
    """Attribute every removed / added / modified key of a keyed accounting to a named cause."""
    removed = collections.Counter()
    rem_other = []
    for k in acc["removed"]:
        c = cls.get((k[pid_ix], k[ev_ix]))
        if c in ("dropped_not_in_post", "dropped_no_spell"):
            removed[c] += 1
        else:
            rem_other.append(k)
    mod = {"h1_fwci_ulp": 0}
    mod_other, worst = [], 0
    for e in acc["modified"]:
        cols = set(e["cols"])
        if allow_h1 and cols <= H1_COLS and e.get("ulps") and \
                all(u is not None and u <= ULP_BOUND for u in e["ulps"].values()):
            mod["h1_fwci_ulp"] += 1
            worst = max(worst, max(e["ulps"].values()))
        else:
            mod_other.append(e)
    out = {"name": name, "rows_frozen": acc["rows_frozen"], "rows_new": acc["rows_new"],
           "identical": acc["identical"],
           "removed": {**{k: removed.get(k, 0) for k in ("dropped_not_in_post", "dropped_no_spell")},
                       "n_unaccounted": len(rem_other), "unaccounted_sample": rem_other[:12]},
           "added": {"n_unaccounted": len(acc["added"]), "unaccounted_sample": acc["added"][:12]},
           "modified": {**mod, "worst_ulp": worst, "n_unaccounted": len(mod_other),
                        "unaccounted_sample": mod_other[:6]},
           "closed": not (rem_other or acc["added"] or mod_other)}
    return out


def relationships_accounting(frozen: pathlib.Path, new: pathlib.Path, cls: dict) -> dict:
    def load(p):
        with open(p, newline="", encoding="utf-8") as f:
            return {(r["pid"], r["event_id"]): r["channel"] for r in csv.DictReader(f)}
    a, b = load(frozen), load(new)
    by_ch = lambda d: dict(collections.Counter(d.values()))  # noqa: E731
    removed = sorted(set(a) - set(b))
    added = sorted(set(b) - set(a))
    changed = sorted(k for k in a.keys() & b.keys() if a[k] != b[k])
    rem_by_channel = collections.Counter(a[k] for k in removed)
    rem_by_cause = collections.Counter(cls.get(k, "unaccounted") for k in removed)
    dropped_keys = {k for k, c in cls.items() if c != "kept"}
    persons_a, persons_b = {p for p, _ in a}, {p for p, _ in b}
    out = {"relations_frozen": len(a), "relations_new": len(b),
           "by_channel_frozen": by_ch(a), "by_channel_new": by_ch(b),
           "removed": len(removed), "removed_by_channel": dict(rem_by_channel),
           "removed_by_cause": dict(rem_by_cause),
           "removed_not_network_channel": [k for k in removed if a[k] != "network"][:12],
           "dropped_relations_still_present": sorted(dropped_keys & set(b))[:12],
           "added": added[:12], "n_added": len(added),
           "channel_changed": [(k, a[k], b[k]) for k in changed][:12], "n_channel_changed": len(changed),
           "persons_frozen": len(persons_a), "persons_new": len(persons_b),
           "persons_removed": len(persons_a - persons_b), "persons_added": len(persons_b - persons_a),
           "events_frozen": len({e for _, e in a}), "events_new": len({e for _, e in b})}
    out["closed"] = (not added and not changed and rem_by_cause.get("unaccounted", 0) == 0
                     and not out["removed_not_network_channel"]
                     and not out["dropped_relations_still_present"]
                     and len(removed) == len(dropped_keys))
    return out


def pairs_accounting(con, frozen_pn: pathlib.Path, oct_pn: pathlib.Path, cls: dict) -> dict:
    con.execute("DROP TABLE IF EXISTS dropped_t")
    con.execute("CREATE TEMP TABLE dropped_t (pid VARCHAR, event_id VARCHAR)")
    rows = [(p, e) for (p, e), c in cls.items() if c != "kept"]
    if rows:
        con.executemany("INSERT INTO dropped_t VALUES (?, ?)", rows)
    q = f"""
    WITH fp AS (SELECT DISTINCT i_id, j_id, event_id FROM read_parquet('{frozen_pn.as_posix()}')),
         np AS (SELECT DISTINCT i_id, j_id, event_id FROM read_parquet('{oct_pn.as_posix()}')),
         rem AS (SELECT * FROM fp EXCEPT SELECT * FROM np),
         add_ AS (SELECT * FROM np EXCEPT SELECT * FROM fp),
         rem_d AS (SELECT r.* FROM rem r WHERE EXISTS (SELECT 1 FROM dropped_t d
                    WHERE d.event_id = r.event_id AND (d.pid = r.i_id OR d.pid = r.j_id))),
         np_d AS (SELECT n.* FROM np n WHERE EXISTS (SELECT 1 FROM dropped_t d
                    WHERE d.event_id = n.event_id AND (d.pid = n.i_id OR d.pid = n.j_id)))
    SELECT (SELECT count(*) FROM fp), (SELECT count(*) FROM np),
           (SELECT count(*) FROM rem), (SELECT count(*) FROM rem_d),
           (SELECT count(*) FROM add_), (SELECT count(*) FROM np_d),
           (SELECT count(*) FROM read_parquet('{frozen_pn.as_posix()}')),
           (SELECT count(*) FROM read_parquet('{oct_pn.as_posix()}'))"""
    fp, np_, rem, rem_d, add, np_d, rows_f, rows_n = con.execute(q).fetchone()
    q2 = f"""
    WITH fp AS (SELECT * FROM read_parquet('{frozen_pn.as_posix()}')),
         np AS (SELECT * FROM read_parquet('{oct_pn.as_posix()}')),
         common AS (SELECT i_id, j_id, event_id FROM
                    (SELECT DISTINCT i_id, j_id, event_id FROM fp)
                    INTERSECT (SELECT DISTINCT i_id, j_id, event_id FROM np)),
         d1 AS (SELECT f.* FROM fp f JOIN common USING (i_id, j_id, event_id)
                EXCEPT ALL SELECT n.* FROM np n JOIN common USING (i_id, j_id, event_id)),
         d2 AS (SELECT n.* FROM np n JOIN common USING (i_id, j_id, event_id)
                EXCEPT ALL SELECT f.* FROM fp f JOIN common USING (i_id, j_id, event_id))
    SELECT (SELECT count(*) FROM d1), (SELECT count(*) FROM d2)"""
    d1, d2 = con.execute(q2).fetchone()
    out = {"rows_frozen": rows_f, "rows_new": rows_n, "pairs_frozen": fp, "pairs_new": np_,
           "pairs_removed": rem, "pairs_removed_endpoint_dropped": rem_d,
           "pairs_removed_unaccounted": rem - rem_d, "pairs_added": add,
           "surviving_pairs_with_dropped_endpoint": np_d,
           "surviving_pair_rows_changed": d1 + d2}
    out["closed"] = (rem == rem_d and add == 0 and np_d == 0 and d1 + d2 == 0)
    return out


def october_accounting(field: str, ctl: dict[str, pathlib.Path], octo: dict[str, pathlib.Path],
                       filt: dict, oct_stages: dict, con) -> dict:
    f = field
    cls = filt["cls"]
    X: dict = {"filter": {k: filt["report"][k] for k in ("relations_by_class", "rows_by_class",
                                                         "persons_by_class",
                                                         "events_left_with_zero_rows")}}
    # prodlib frame: the filtered frame must be the unfiltered one minus exactly the dropped rows
    w = fs08.strict_removal_walk(filt["input"], filt["output"],
                                 lambda c: cls.get((c[0], c[3]), "kept") != "kept")
    X["prodlib_frame"] = w
    if not (w["closed"] and w["rows_removed"] == sum(
            v for k, v in filt["report"]["rows_by_class"].items() if k != "kept")):
        stop(f"{f}: the in-post filter's output is not the input minus the dropped rows: {w}")
    # union frame (no frozen copy): October vs this run's control
    acc = fs08.keyed_csv_accounting(ctl["union_frame"], octo["union_frame"],
                                    ("incumbent_person_id", "event_id", "year"),
                                    float_cols=FWCI_COLS + ("dose_topic",))
    X["union_frame_vs_control"] = classify_keyed(acc, cls, 0, 1, True, f"union frame {f}")
    if not X["union_frame_vs_control"]["closed"]:
        stop(f"{f}: union-frame accounting did not close: "
             f"{json.dumps(X['union_frame_vs_control'], default=str)[:1200]}")
    # relationships
    X["relationships"] = relationships_accounting(FRAMES08 / f"relationships_{f}.csv",
                                                  octo[f"relationships_{f}.csv"], cls)
    if not X["relationships"]["closed"]:
        stop(f"{f}: relationships accounting did not close: "
             f"{json.dumps(X['relationships'], default=str)[:1200]}")
    # P1 frame vs frozen
    acc = fs08.keyed_csv_accounting(FRAMES08 / f"p1_frame_{f}.csv", octo[f"p1_frame_{f}.csv"],
                                    ("incumbent_person_id", "event_id", "year"), float_cols=FWCI_COLS)
    X["p1_frame"] = classify_keyed(acc, cls, 0, 1, True, f"p1_frame_{f}")
    if not X["p1_frame"]["closed"]:
        stop(f"{f}: P1 accounting did not close: {json.dumps(X['p1_frame'], default=str)[:1200]}")
    hdr, rows = fs08.read_frame_rows(octo[f"p1_frame_{f}.csv"])
    ic = hdr.index("channel")
    X["p1_frame"]["rows_by_channel_new"] = dict(collections.Counter(r[ic] for r in rows))
    X["p1_frame"]["relations_new"] = len({(r[0], r[3]) for r in rows})
    X["p1_frame"]["rows_are_11_per_relation"] = len(rows) == 11 * X["p1_frame"]["relations_new"]
    X["p1_frame"]["events_new"] = len({r[3] for r in rows})
    # P2 becoming vs frozen
    acc = fs08.keyed_csv_accounting(FRAMES08 / f"p2_becoming_{f}.csv", octo[f"p2_becoming_{f}.csv"],
                                    ("pid", "event_id", "year"))
    X["p2_becoming"] = classify_keyed(acc, cls, 0, 1, False, f"p2_becoming_{f}")
    if not X["p2_becoming"]["closed"]:
        stop(f"{f}: P2 accounting did not close: {json.dumps(X['p2_becoming'], default=str)[:1200]}")
    hdr, rows = fs08.read_frame_rows(octo[f"p2_becoming_{f}.csv"])
    ie, ip = hdr.index("event_id"), hdr.index("pid")
    X["p2_becoming"]["events_new"] = len({r[ie] for r in rows})
    X["p2_becoming"]["persons_new"] = len({r[ip] for r in rows})
    X["p2_becoming"]["first_ties_new"] = sum(1 for r in rows if r[hdr.index("y")] == "1")
    # pairs vs frozen
    X["pairs"] = pairs_accounting(con, FRAMES08 / f"pairs_none_{f}.parquet",
                                  octo[f"pairs_none_{f}.parquet"], cls)
    if not X["pairs"]["closed"]:
        stop(f"{f}: pair-layer accounting did not close: {json.dumps(X['pairs'], default=str)[:1200]}")
    # slims: faithful projection of the October pair table
    X["slim"] = ca08.slim_consistency(con, oct_stages["slim"], octo[f"pairs_none_{f}.parquet"], f, stop)
    # union build report: alias-dup release check + by-channel
    rep = json.loads(octo[f"union_build_report_{f}.json"].read_text("utf-8"))
    rep08 = json.loads((FRAMES08 / f"union_build_report_{f}.json").read_text("utf-8"))
    X["union_build_report"] = {
        "relationships_pre_guard_new": {k: v for k, v in rep["relationships_pre_guard"].items()
                                        if not k.endswith("examples")},
        "relationships_pre_guard_08_28": {k: v for k, v in rep08["relationships_pre_guard"].items()
                                          if not k.endswith("examples")},
        "frame_new": rep["frame"], "frame_08_28": rep08["frame"], "GATE": rep["GATE"]}
    if rep["relationships_pre_guard"]["v9_drop_alias_dup"] != rep08["relationships_pre_guard"]["v9_drop_alias_dup"]:
        stop(f"{f}: the union builder's alias_dup count moved "
             f"({rep08['relationships_pre_guard']['v9_drop_alias_dup']} -> "
             f"{rep['relationships_pre_guard']['v9_drop_alias_dup']}) — a released dept twin "
             f"would be an added row the accounting has no cause for")
    return X


# ---------------------------------------------------------------------------------------------
# review modes: the October chain against the frozen October canon (2026-09-23)
# ---------------------------------------------------------------------------------------------

def october_vs_frozen(field: str, octo: dict[str, pathlib.Path], review: bool) -> dict:
    """The October chain's products against data/cal2026-10/frames_<field>/ (the frozen October
    canon), with the freeze's own per-file acceptance: relationships / p2 BYTE_EQUAL, union report
    equal modulo run-dir paths, p1 within H1, pairs / slims content-equal. In a review run
    (--no-freeze / --products-dir) a difference is a STOP; in a freeze run it is recorded."""
    f = field
    fr = CAL10 / f"frames_{f}"
    V: dict = {"frozen_dir": str(fr.relative_to(REPO)),
               "mode": "review (a difference STOPs)" if review else "freeze (recorded only)"}
    V["relationships"] = "BYTE_EQUAL" if sha(octo[f"relationships_{f}.csv"]) == \
        sha(fr / f"relationships_{f}.csv") else "NOT_EQUAL"
    V["union_build_report"] = json_equal_modulo_paths(octo[f"union_build_report_{f}.json"],
                                                      fr / f"union_build_report_{f}.json")
    V["p1_frame"] = h1_characterise(fr / f"p1_frame_{f}.csv", octo[f"p1_frame_{f}.csv"])
    V["p2_becoming"] = "BYTE_EQUAL" if sha(octo[f"p2_becoming_{f}.csv"]) == \
        sha(fr / f"p2_becoming_{f}.csv") else "NOT_EQUAL"
    for name in (f"pairs_none_{f}.parquet", f"p3_slim_{f}.parquet", f"p3_slim_ev_{f}.parquet"):
        r = content_equal(octo[name], fr / name)
        V[name] = {"content": "EQUAL" if r.equal else "NOT_EQUAL", "rows": (r.rows_a, r.rows_b),
                   "schema_equal": r.schema_equal, "byte_equal": sha(octo[name]) == sha(fr / name)}
    bad = [k for k, v in V.items()
           if (v == "NOT_EQUAL") or (isinstance(v, dict) and (
               v.get("ok") is False or v.get("content") == "NOT_EQUAL" or
               v.get("equal_modulo_paths_and_h1_advisory") is False))]
    V["all_equal"] = not bad
    if bad and review:
        stop(f"{f}: the October chain's products differ from the frozen data/cal2026-10/frames_{f}/: {bad}")
    log(f"October products vs frozen data/cal2026-10/frames_{f}/: "
        f"{'ALL EQUAL' if not bad else 'DIFFER ' + str(bad)} (p1 H1 worst_ulp={V['p1_frame'].get('worst_ulp')})")
    return V


# ---------------------------------------------------------------------------------------------
# the roster-variant accounting (--roster-variant incfel): named causes from the spells alone
# ---------------------------------------------------------------------------------------------

def _spells(roster: pathlib.Path, con) -> tuple[dict, dict, dict]:
    """person -> [(ys, ye)], (person, school) -> [(ys, ye)] and the file's facts."""
    rows = con.execute(f"SELECT author_id, school, year_start, year_end "
                       f"FROM read_parquet('{roster.as_posix()}')").fetchall()
    by_p: dict = collections.defaultdict(list)
    by_ps: dict = collections.defaultdict(list)
    for a, sch, ys, ye in rows:
        assert a is not None and ys is not None and ye is not None, (roster.name, a, sch, ys, ye)
        by_p[a].append((int(ys), int(ye)))
        by_ps[(a, sch)].append((int(ys), int(ye)))
    return by_p, by_ps, {"path": str(roster.relative_to(REPO)), "sha256": sha(roster),
                         "rows": len(rows), "persons": len(by_p)}


def _covers(spells, y: int) -> bool:
    return any(a <= y <= b for a, b in spells)


def variant_predict(field: str, canon_rel: pathlib.Path, canon_p1: pathlib.Path,
                    sp_c: dict, sps_c: dict, sp_v: dict, sps_v: dict) -> dict:
    """For every relation of the frozen October canon, its fate under the variant roster, derived
    from the two rosters' spells and the chain's own rules: the network part survives iff some
    variant spell of the PERSON (any school) covers the arrival (D2, joined on the person); the
    dept part iff some variant spell at the EVENT'S school covers the arrival (the union builder's
    join); a `both` relation whose network part is gone is a NEW dept_only relation and meets the
    union builder's |age_gap| > 60 guard. A relation with neither part is dropped, cause
    `person_not_in_variant_roster` or `no_variant_spell_at_arrival`. Dept relations the variant
    could ADD (a variant spell at the school covering an arrival no canon spell covered) are
    listed so an added row has a name too."""
    events: dict[str, tuple[str, int]] = {}
    with open(CAL10 / f"events_{field}_cal2026-10.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            events[f"{r['author_id']}:{r['school']}"] = (r["school"], int(r["arrival_corrected"]))
    with open(canon_rel, newline="", encoding="utf-8") as fh:
        canon = {(r["pid"], r["event_id"]): r["channel"] for r in csv.DictReader(fh)}
    missing = sorted({e for _, e in canon} - set(events))
    assert not missing, f"canon relationships name events outside the October table: {missing[:5]}"
    hdr, rows = fs08.read_frame_rows(canon_p1)
    ip, ie, ig = hdr.index("incumbent_person_id"), hdr.index("event_id"), hdr.index("age_gap")
    gap: dict = {}
    for r in rows:
        gap.setdefault((r[ip], r[ie]), r[ig])
    pred: dict = {}
    cause: dict = {}
    for (pid, ev), ch in canon.items():
        school, arr = events[ev]
        net = ch in ("network", "both") and _covers(sp_v.get(pid, ()), arr)
        dept = ch in ("dept_only", "both") and _covers(sps_v.get((pid, school), ()), arr)
        c = None
        if ch == "both" and dept and not net:
            g = gap.get((pid, ev), "")
            try:
                if g not in ("", None) and abs(float(g)) > 60:
                    dept, c = False, "both_to_dept_only_age_gap_guard"
            except ValueError:
                pass
        if net and dept:
            pred[(pid, ev)] = "both"
        elif net:
            pred[(pid, ev)] = "network"
        elif dept:
            pred[(pid, ev)] = "dept_only"
        else:
            pred[(pid, ev)] = None
            cause[(pid, ev)] = c or ("person_not_in_variant_roster" if pid not in sp_v
                                     else "no_variant_spell_at_arrival")
    pred_add: set = set()
    for (pid, school), sp in sps_v.items():
        for ev, (sch, arr) in events.items():
            if sch == school and (pid, ev) not in canon and _covers(sp, arr) \
                    and not _covers(sps_c.get((pid, school), ()), arr):
                pred_add.add((pid, ev))
    return {"events": events, "canon": canon, "pred": pred, "cause": cause, "pred_add": pred_add}


def classify_variant_keyed(acc: dict, cls: dict, pred: dict, pred_add: set, pid_ix: int, ev_ix: int,
                           yr_ix: int, fill_differs, allow_fill: bool, name: str) -> dict:
    """Attribute every removed / added / modified key of a keyed accounting to a named cause of
    the roster substitution: removed -> the relation's predicted cause; added -> a predicted
    added dept relation; modified -> `channel_changed` (to the predicted channel),
    `h1_fwci_ulp` (fwci columns, <= ULP_BOUND), `in_post_fill_changed` (outcome columns of a
    year whose in-post status differs between the two spell sets); anything else is unaccounted."""
    removed = collections.Counter()
    rem_other = []
    for k in acc["removed"]:
        c = cls.get((k[pid_ix], k[ev_ix]))
        if c and c != "kept":
            removed[c] += 1
        else:
            rem_other.append(k)
    added_pred, add_other = 0, []
    for k in acc["added"]:
        if (k[pid_ix], k[ev_ix]) in pred_add:
            added_pred += 1
        else:
            add_other.append(k)
    mod = collections.Counter()
    mod_other, worst = [], 0
    for e in acc["modified"]:
        k, cols, tags = e["key"], set(e["cols"]), []
        if "channel" in cols and e["new"].get("channel") == pred.get((k[pid_ix], k[ev_ix])):
            cols.discard("channel")
            tags.append("channel_changed")
        ul = e.get("ulps") or {}
        if cols and cols <= H1_COLS and all(ul.get(c) is not None and ul[c] <= ULP_BOUND for c in cols):
            worst = max(worst, max(ul[c] for c in cols))
            cols, tags = set(), tags + ["h1_fwci_ulp"]
        if cols and allow_fill and cols <= set(OUTCOME_COLS) and \
                fill_differs(k[pid_ix], k[ev_ix], int(k[yr_ix])):
            cols, tags = set(), tags + ["in_post_fill_changed"]
        if cols or not tags:
            mod_other.append(e)
        else:
            for t in tags:
                mod[t] += 1
    return {"name": name, "rows_frozen": acc["rows_frozen"], "rows_new": acc["rows_new"],
            "identical": acc["identical"],
            "removed": {**dict(removed), "n_unaccounted": len(rem_other), "unaccounted_sample": rem_other[:12]},
            "added": {"predicted_added_dept_relation": added_pred, "n_unaccounted": len(add_other),
                      "unaccounted_sample": add_other[:12]},
            "modified": {**dict(mod), "worst_ulp": worst, "n_unaccounted": len(mod_other),
                         "unaccounted_sample": mod_other[:6]},
            "closed": not (rem_other or add_other or mod_other)}


def variant_accounting(field: str, octo: dict[str, pathlib.Path], oct_stages: dict,
                       roster_var: pathlib.Path, con) -> dict:
    """The variant products against the frozen October canon data/cal2026-10/frames_<field>/:
    population deltas and a row-level accounting whose only causes are the roster substitution's
    (variant_predict / classify_variant_keyed). Descriptive — records `closed`, never STOPs."""
    f = field
    fr = CAL10 / f"frames_{f}"
    sp_c, sps_c, fact_c = _spells(RAW / f"roster_gold_{f}.parquet", con)
    sp_v, sps_v, fact_v = _spells(roster_var, con)
    X: dict = {"frozen_october_canon": str(fr.relative_to(REPO)),
               "roster": {"canon": fact_c, "variant": fact_v,
                          "persons_only_in_canon": len(set(sp_c) - set(sp_v)),
                          "persons_only_in_variant": len(set(sp_v) - set(sp_c)),
                          "shared_persons_with_different_spells":
                              sum(1 for q in set(sp_c) & set(sp_v) if sorted(sp_c[q]) != sorted(sp_v[q]))}}
    P = variant_predict(f, fr / f"relationships_{f}.csv", fr / f"p1_frame_{f}.csv", sp_c, sps_c, sp_v, sps_v)
    canon, pred, cause, pred_add = P["canon"], P["pred"], P["cause"], P["pred_add"]
    cls = {k: ("kept" if pred[k] else cause[k]) for k in canon}

    def fill_differs(pid: str, ev: str, y: int) -> bool:
        school = P["events"][ev][0]
        a = (_covers(sp_c.get(pid, ()), y), _covers(sps_c.get((pid, school), ()), y))
        b = (_covers(sp_v.get(pid, ()), y), _covers(sps_v.get((pid, school), ()), y))
        return a != b

    # relationships: removed must be predicted dropped, kept must carry the predicted channel
    with open(octo[f"relationships_{f}.csv"], newline="", encoding="utf-8") as fh:
        var = {(r["pid"], r["event_id"]): r["channel"] for r in csv.DictReader(fh)}
    removed = sorted(set(canon) - set(var))
    added = sorted(set(var) - set(canon))
    kept = sorted(set(canon) & set(var))
    by_ch = lambda d: dict(collections.Counter(d.values()))  # noqa: E731
    rem_bad = [k for k in removed if pred[k] is not None]
    surv_bad = [k for k in kept if pred[k] is None]
    ch_bad = [(k, canon[k], var[k], pred[k]) for k in kept if pred[k] is not None and var[k] != pred[k]]
    ch_changed = collections.Counter(f"{canon[k]}->{var[k]}" for k in kept if var[k] != canon[k] and var[k] == pred[k])
    add_pred = [k for k in added if k in pred_add]
    X["relationships"] = {
        "relations_canon": len(canon), "relations_variant": len(var),
        "by_channel_canon": by_ch(canon), "by_channel_variant": by_ch(var),
        "persons_canon": len({q for q, _ in canon}), "persons_variant": len({q for q, _ in var}),
        "persons_removed": len({q for q, _ in canon} - {q for q, _ in var}),
        "persons_added": len({q for q, _ in var} - {q for q, _ in canon}),
        "events_canon": len({e for _, e in canon}), "events_variant": len({e for _, e in var}),
        "removed": len(removed), "removed_by_cause": dict(collections.Counter(cause[k] for k in removed if pred[k] is None)),
        "removed_by_channel": dict(collections.Counter(canon[k] for k in removed)),
        "removed_but_predicted_to_survive": {"n": len(rem_bad), "sample": rem_bad[:12]},
        "survived_but_predicted_dropped": {"n": len(surv_bad), "sample": surv_bad[:12]},
        "channel_changed_as_predicted": dict(ch_changed),
        "channel_not_as_predicted": {"n": len(ch_bad), "sample": ch_bad[:12]},
        "added": len(added), "added_predicted_dept": len(add_pred),
        "added_unpredicted": {"n": len(added) - len(add_pred), "sample": [k for k in added if k not in pred_add][:12]},
        "predicted_added_dept_candidates": len(pred_add)}
    X["relationships"]["closed"] = not (rem_bad or surv_bad or ch_bad or
                                        X["relationships"]["added_unpredicted"]["n"])
    # P1 frame, P2 becoming (keyed), pairs, slims, union report
    acc = fs08.keyed_csv_accounting(fr / f"p1_frame_{f}.csv", octo[f"p1_frame_{f}.csv"],
                                    ("incumbent_person_id", "event_id", "year"), float_cols=FWCI_COLS)
    X["p1_frame"] = classify_variant_keyed(acc, cls, pred, pred_add, 0, 1, 2, fill_differs, True, f"p1_frame_{f}")
    hdr, rows = fs08.read_frame_rows(octo[f"p1_frame_{f}.csv"])
    ic = hdr.index("channel")
    X["p1_frame"]["rows_by_channel_new"] = dict(collections.Counter(r[ic] for r in rows))
    X["p1_frame"]["relations_new"] = len({(r[0], r[3]) for r in rows})
    X["p1_frame"]["persons_new"] = len({r[0] for r in rows})
    X["p1_frame"]["events_new"] = len({r[3] for r in rows})
    acc = fs08.keyed_csv_accounting(fr / f"p2_becoming_{f}.csv", octo[f"p2_becoming_{f}.csv"],
                                    ("pid", "event_id", "year"))
    X["p2_becoming"] = classify_variant_keyed(acc, cls, pred, pred_add, 0, 1, 2, fill_differs, False, f"p2_becoming_{f}")
    hdr, rows = fs08.read_frame_rows(octo[f"p2_becoming_{f}.csv"])
    ie, ip, iy = hdr.index("event_id"), hdr.index("pid"), hdr.index("y")
    X["p2_becoming"].update({"events_new": len({r[ie] for r in rows}), "persons_new": len({r[ip] for r in rows}),
                             "first_ties_new": sum(1 for r in rows if r[iy] == "1")})
    X["pairs"] = pairs_accounting(con, fr / f"pairs_none_{f}.parquet", octo[f"pairs_none_{f}.parquet"], cls)
    X["slim"] = ca08.slim_consistency(con, oct_stages["slim"], octo[f"pairs_none_{f}.parquet"], f, stop)
    rep = json.loads(octo[f"union_build_report_{f}.json"].read_text("utf-8"))
    rep10 = json.loads((fr / f"union_build_report_{f}.json").read_text("utf-8"))
    X["union_build_report"] = {
        "relationships_pre_guard_variant": {k: v for k, v in rep["relationships_pre_guard"].items() if not k.endswith("examples")},
        "relationships_pre_guard_october": {k: v for k, v in rep10["relationships_pre_guard"].items() if not k.endswith("examples")},
        "frame_variant": rep["frame"], "frame_october": rep10["frame"], "GATE": rep["GATE"]}
    X["closed"] = bool(X["relationships"]["closed"] and X["p1_frame"]["closed"] and
                       X["p2_becoming"]["closed"] and X["pairs"]["closed"])
    log(f"variant accounting {f}: relations {len(canon)} -> {len(var)} "
        f"(removed {len(removed)} by cause {X['relationships']['removed_by_cause']}, added {len(added)}), "
        f"p1 rows {X['p1_frame']['rows_frozen']} -> {X['p1_frame']['rows_new']}, "
        f"p2 rows {X['p2_becoming']['rows_frozen']} -> {X['p2_becoming']['rows_new']}, "
        f"pairs {X['pairs']['pairs_frozen']} -> {X['pairs']['pairs_new']}; closed={X['closed']}")
    return X


# ---------------------------------------------------------------------------------------------
# freeze
# ---------------------------------------------------------------------------------------------

def freeze(field: str, octo: dict[str, pathlib.Path], filt: dict, shadows: dict[str, fs08.Shadow],
           field_report: dict, out_root: pathlib.Path = CAL10) -> dict:
    """Phase F. `out_root` (2026-09-23): --products-dir redirects the whole product set (the same
    files, the same per-directory MANIFEST) away from data/; a roster variant never writes to
    data/cal2026-10/frames_<field>/."""
    out = out_root / f"frames_{field}"
    out.mkdir(parents=True, exist_ok=True)
    in_repo = out.is_relative_to(REPO)
    label = out.relative_to(REPO).as_posix() if in_repo else str(out)
    for name in PRODUCTS:
        n = name.format(f=field)
        (out / n).write_bytes(octo[n].read_bytes())
    (out / f"inpost_report_{field}.json").write_text(
        json.dumps(filt["report"], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / f"inpost_relations_{field}.csv").write_text(
        "pid,event_id,class\n" + "".join(f"{p},{e},{c}\n" for (p, e), c in sorted(filt["cls"].items())),
        encoding="utf-8")
    (out / f"staging_manifest_{field}.json").write_text(
        json.dumps({tag: {"root": str(sh.root), "entries": sh.manifest()} for tag, sh in shadows.items()},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    (out / f"build_report_{field}.json").write_text(
        json.dumps(field_report, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    manifest = "".join(f"{sha(p)}  {(label + '/') if in_repo else ''}{p.name}\n"
                       for p in sorted(out.iterdir()) if p.is_file() and p.name != "MANIFEST.sha256")
    (out / "MANIFEST.sha256").write_text(manifest, encoding="utf-8")
    log(f"frozen {manifest.count(chr(10))} files into {label} (+ MANIFEST.sha256)")
    return {"dir": label, "files": manifest.count("\n"),
            "sha256": {ln.split("  ")[1].rsplit("/", 1)[-1]: ln.split("  ")[0]
                       for ln in manifest.splitlines()}}


# ---------------------------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------------------------

def october_ref_files(f: str) -> list[str]:
    """The October products phase P reads for field `f`, as repo paths under --october-ref."""
    return ([f"data/frames/{n}" for n in (f"p1_frame_{f}.csv", f"p2_becoming_{f}.csv",
                                          f"p3_slim_{f}.parquet", f"p3_slim_ev_{f}.parquet")] +
            [f"data/cal2026-10/frames_{f}/{name.format(f=f)}" for name in PRODUCTS] +
            [f"data/cal2026-10/frames_{f}/MANIFEST.sha256"])


def preconditions(ref: pathlib.Path) -> dict:
    """Phase P. Every October product is read from `ref` (--october-ref) at its repo path; the
    08-28 operands, the event tables, the rosters and data/MANIFEST.sha256 from the repo."""
    P: dict = {}
    missing = [rel for f in FIELDS for rel in october_ref_files(f) if not (ref / rel).is_file()]
    if missing:
        stop(f"--october-ref {ref}: October product(s) missing: {missing}")
        return P
    for f in FIELDS:
        a, b = CAL10 / f"events_{f}_cal2026-10.csv", CAL08 / f"events_{f}_cal.csv"
        P[f"events_{f}_byte_identical_to_08_28"] = a.read_bytes() == b.read_bytes()
        if not P[f"events_{f}_byte_identical_to_08_28"]:
            stop(f"October event table for {f} differs from the 08-28 table — this driver's "
                 f"D2-only premise does not hold")
        P[f"roster_gold_{f}_sha256"] = sha(RAW / f"roster_gold_{f}.parquet")
        P[f"roster_gold_{f}_incfel_sha256"] = sha(INCFEL / f"roster_gold_{f}.parquet")
        for name in ("p1_frame", "p2_becoming", "p3_slim", "p3_slim_ev"):
            ext = "csv" if name in ("p1_frame", "p2_becoming") else "parquet"
            anchor_frozen(ref / f"data/frames/{name}_{f}.{ext}", REPO / "data/MANIFEST.sha256",
                          f"data/frames/{name}_{f}.{ext}")
            anchor_frozen(FRAMES08 / f"{name}_{f}.{ext}", CAL08 / "MANIFEST.sha256",
                          f"data/cal2026-08-28/frames/{name}_{f}.{ext}")
        for name in (f"relationships_{f}.csv", f"union_build_report_{f}.json",
                     f"pairs_none_{f}.parquet", "staging_manifest_2026-08-28.json"):
            anchor_frozen(FRAMES08 / name, CAL08 / "MANIFEST.sha256",
                          f"data/cal2026-08-28/frames/{name}")
        for label in (f"P1_fnfix_{f}", f"P2_fnfix_{f}"):
            anchor_frozen(EXPECTED08 / f"{label}.json", CAL08 / "MANIFEST.sha256",
                          f"data/cal2026-08-28/estimates/{label}.json")
        # since the promotion (73777aa) data/frames is the October copy; recorded, not asserted
        fr10 = ref / f"data/cal2026-10/frames_{f}"
        p1, p1_08, p1_10 = ref / f"data/frames/p1_frame_{f}.csv", FRAMES08 / f"p1_frame_{f}.csv", \
            fr10 / f"p1_frame_{f}.csv"
        P[f"data_frames_copy_{f}"] = ("08-28" if sha(p1) == sha(p1_08) else
                                      "october" if sha(p1) == sha(p1_10) else "other")
        for name in PRODUCTS:
            n = name.format(f=f)
            anchor_frozen(fr10 / n, fr10 / "MANIFEST.sha256", f"data/cal2026-10/frames_{f}/{n}")
        P[f"frozen_october_{f}"] = "anchored in its MANIFEST.sha256"
    P["frozen_side_anchors"] = ("data/MANIFEST.sha256 (data/frames), data/cal2026-08-28/MANIFEST.sha256 "
                                "(the 08-28 frames + the 08-28 P1/P2 golds the control R cells compare "
                                "to) and data/cal2026-10/frames_<field>/MANIFEST.sha256 verified for every "
                                "operand; the data/frames and frames_<field> operands read from "
                                "--october-ref")
    return P


def build_shadow(root: pathlib.Path, tag: str, stage_cfg: dict) -> fs08.Shadow:
    sh, rec = stage.build_shadow(root / f"shadow_{tag}", events="cal2026-10", stage_cfg=stage_cfg)
    v2 = stage.legacy_v2()
    gold = sh.root / GOLD / "data"
    comp = {"shortlist": gold.joinpath("shortlist_fnfix.csv").read_bytes() == fs08.cal_shortlist(v2)}
    for f in FIELDS:
        comp[f"fnfixbase_{f}"] = gold.joinpath(f"events_{f}_fnfixbase_2026-08-10.csv").read_bytes() == \
            fs08.cal_fnfixbase(v2, f)
    REPORT.setdefault("shadows", {})[tag] = {"root": str(sh.root), "entries": len(sh.entries),
                                              "events": rec["events"],
                                              "companions_byte_equal_to_08_28": comp}
    for k, ok in comp.items():
        if not ok:
            stop(f"shadow [{tag}]: staged companion {k} differs from the 08-28 derivation")
    return sh


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--execute", action="store_true",
                    help="required: many SSD-scanning builder runs and four R cells (minutes)")
    ap.add_argument("--fields", default=",".join(FIELDS),
                    help="comma-separated subset of chemistry,math_stats (default both)")
    ap.add_argument("--no-freeze", action="store_true",
                    help="review rerun: every phase (controls, October chain, accounting) but phase F "
                         "is skipped, so nothing under data/ is written; the products stay in $SAR_OUT_ROOT")
    ap.add_argument("--roster-variant", default="fnfix", choices=ROSTER_VARIANTS,
                    help="incfel: the ± research-centre check — the OCTOBER shadow's roster link and the "
                         "in-post spells re-pointed at data/raw_verified/incfel/roster_gold_<field>.parquet "
                         "(the control shadow keeps the canon roster); requires --products-dir")
    ap.add_argument("--products-dir", default=None,
                    help="phase F writes frames_<field>/ (the same product set + MANIFEST) under this "
                         "directory instead of data/cal2026-10/; must not be under data/")
    ap.add_argument("--october-ref", required=True, metavar="DIR",
                    help="required: the directory holding October's products at their repo paths "
                         "(data/frames/*, data/cal2026-10/frames_<field>/*); phase P reads every October "
                         "anchor from it (J0: /work/ref/october; in place: the repo root)")
    args = ap.parse_args(argv)
    if not args.execute:
        print("This drives prodlib, the three gold builders (twice per field) and the R cells "
              "against the data disk (minutes). Re-run with --execute.", file=sys.stderr)
        return 2
    fields = tuple(f for f in args.fields.split(",") if f)
    assert set(fields) <= set(FIELDS), fields
    variant = args.roster_variant
    products_dir = pathlib.Path(args.products_dir).resolve() if args.products_dir else None
    if products_dir is not None:
        assert not products_dir.is_relative_to(REPO / "data"), \
            f"--products-dir must not be under data/: {products_dir}"
    if variant != "fnfix" and products_dir is None and not args.no_freeze:
        raise PathUnresolved("--roster-variant needs --products-dir (a variant never freezes under data/)")
    october_ref = pathlib.Path(args.october_ref).resolve()
    if not october_ref.is_dir():
        raise PathUnresolved(f"--october-ref is not a directory: {october_ref}")
    stage_cfg = stage.stage_config()                   # $SAR_R1_CONFIG unset = STOP, before any work
    review = args.no_freeze or products_dir is not None
    out_root = os.environ.get(OUT_ROOT_ENV, "").strip()
    if not out_root:
        raise PathUnresolved(f"set ${OUT_ROOT_ENV} to an empty absolute directory under /private/tmp")
    root = pathlib.Path(out_root)
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise PathUnresolved(f"${OUT_ROOT_ENV} must be empty: {root}")
    REPORT.update({"generated": datetime.datetime.now().isoformat(timespec="seconds"),
                   "authority": "the author's design record of 2026-09-22 (private archive) (D2)",
                   "task": "cal2026-10 chemistry / math_stats frames: control chain + D2 October chain",
                   "scratch_root": str(root), "fields_run": list(fields), "no_freeze": args.no_freeze,
                   "roster_variant": variant, "products_dir": str(products_dir) if products_dir else None,
                   "october_ref": str(october_ref)})
    t_all = time.time()
    log("phase P: preconditions")
    REPORT["preconditions"] = preconditions(october_ref)
    if STOPS:
        return finish(root)
    log("phase S: the two shadows (control / october)")
    sh_ctl = build_shadow(root, "control", stage_cfg)
    sh_oct = build_shadow(root, "october", stage_cfg)
    if STOPS:
        return finish(root)
    if variant != "fnfix":
        REPORT["roster_variant_links"] = {}
        for field in fields:
            rel_r = f"{GOLD}/data/fnfix/roster_gold_{field}.parquet"
            src = INCFEL / f"roster_gold_{field}.parquet"
            canon_sha = sha(sh_oct.path(rel_r))
            sh_oct.link_frozen(rel_r, src)                     # the ONE substitution, October shadow only
            sh_oct.entries[-1]["origin"] = f"VARIANT:{variant} (no-centre) roster <- {src.relative_to(REPO)}"
            REPORT["roster_variant_links"][field] = {
                "shadow_rel": rel_r, "source": str(src.relative_to(REPO)), "canon_sha256": canon_sha,
                "variant_sha256": sha(src), "control_shadow": "keeps the canon roster (unchanged)"}
            log(f"roster variant [{variant}] {field}: {rel_r} <- {src.relative_to(REPO)} "
                f"({canon_sha[:12]} -> {sha(src)[:12]})")
    import duckdb                                                      # noqa: PLC0415
    con = duckdb.connect()
    for field in fields:
        F: dict = REPORT.setdefault("fields", {}).setdefault(field, {})
        t_f = time.time()
        # ---- C: control chain ----------------------------------------------------------------
        log(f"phase C [{field}]: control chain (no in-post filter)")
        F["control"] = {"prodlib": {}}
        ctl_frame = run_prodlib(field, root, sh_ctl.root.parent, "control", F["control"]["prodlib"])
        if STOPS:
            break
        ctl_stages = run_chain(field, root, sh_ctl, "control", ctl_frame,
                               f"control-stage:prodlib {field} (unfiltered)")
        ctl = products_of(field, ctl_stages)
        F["control"]["stages"] = _stage_summary(ctl_stages)
        F["control"]["products_sha256"] = {k: sha(v) for k, v in ctl.items()}
        F["control"]["compare"] = control_compare(field, ctl)
        if STOPS:
            break
        cells = [start_r_cell(f"P1_fnfix_{field}", "run_p1.R", ctl[f"p1_frame_{field}.csv"],
                              root / f"control_r_{field}"),
                 start_r_cell(f"P2_fnfix_{field}", "run_p2.R", ctl[f"p2_becoming_{field}.csv"],
                              root / f"control_r_{field}")]
        log(f"R cells P1_fnfix_{field} / P2_fnfix_{field} started in the background")
        # ---- O: October chain ----------------------------------------------------------------
        log(f"phase O [{field}]: October chain (D2 in-post filter)")
        F["october"] = {"prodlib": {}}
        oct_frame = run_prodlib(field, root, sh_oct.root.parent, "october", F["october"]["prodlib"],
                                expect_08_28=(variant == "fnfix"))
        if STOPS:
            F["control"]["r_cells"] = [finish_r_cell(c) for c in cells]
            break
        roster = (INCFEL if variant == "incfel" else RAW) / f"roster_gold_{field}.parquet"
        assert sha(roster) == sha(sh_oct.path(f"{GOLD}/data/fnfix/roster_gold_{field}.parquet")), (
            "the in-post spells and the October shadow's roster link must be ONE file")
        spells, sources = ipf.spells_from_roster(roster, None, identity=True)
        ipd = root / f"october_inpost_{field}"
        rep = ipf.run(oct_frame, spells, sources, ipd / "frame_inpost.csv", ipd / "inpost_report.json")
        cls = ipf.classify(oct_frame, spells)["cls"]           # same walk run() did; small frame
        filt = {"input": oct_frame, "output": ipd / "frame_inpost.csv", "report": rep, "cls": cls}
        log(f"in-post filter {field}: relations {rep['relations_by_class']}, rows {rep['rows_by_class']}, "
            f"events left with zero network rows {rep['events_left_with_zero_rows']}")
        F["october"]["inpost"] = {k: rep[k] for k in ("relations_by_class", "rows_by_class",
                                                      "persons_by_class", "events_left_with_zero_rows",
                                                      "spells", "input", "output")}
        oct_stages = run_chain(field, root, sh_oct, "october", filt["output"],
                               f"october-stage:inpost_filter {field} (D2, on the prodlib frame "
                               f"{sha(oct_frame)[:12]})")
        octo = products_of(field, oct_stages)
        F["october"]["stages"] = _stage_summary(oct_stages)
        F["october"]["products_sha256"] = {k: sha(v) for k, v in octo.items()}
        F["october"]["union_frame"] = {"sha256": sha(octo["union_frame"]),
                                       "lines": octo["union_frame"].read_bytes().count(b"\n")}
        # ---- X: accounting -------------------------------------------------------------------
        if variant == "fnfix":
            log(f"phase X [{field}]: row-level accounting against the 08-28 frozen frames")
            F["accounting"] = october_accounting(field, ctl, octo, filt, oct_stages, con)
            if (CAL10 / f"frames_{field}" / "MANIFEST.sha256").is_file():
                F["october"]["vs_frozen_cal2026_10"] = october_vs_frozen(field, octo, review)
        else:
            log(f"phase X [{field}]: variant accounting against the frozen October canon")
            F["accounting"] = variant_accounting(field, octo, oct_stages, roster, con)
        F["control"]["r_cells"] = [finish_r_cell(c) for c in cells]
        F["secs"] = round(time.time() - t_f, 1)
        if STOPS:
            break
        # ---- F: freeze -----------------------------------------------------------------------
        if args.no_freeze:
            F["frozen"] = {"skipped": "--no-freeze (review rerun; products left in the scratch root)"}
            log(f"phase F [{field}]: skipped (--no-freeze)")
        else:
            F["frozen"] = freeze(field, octo, filt, {"control": sh_ctl, "october": sh_oct}, F,
                                 out_root=products_dir or CAL10)
    REPORT["total_secs"] = round(time.time() - t_all, 1)
    return finish(root)


def _stage_summary(stages: dict) -> dict:
    return {k: {kk: (str(vv) if isinstance(vv, pathlib.Path) else vv)
                for kk, vv in v.items() if kk != "produced"} for k, v in stages.items()}


def finish(root: pathlib.Path) -> int:
    REPORT["stops"] = STOPS
    name = "frames_run_report_chemmath_FAILED.json" if STOPS else "frames_run_report_chemmath.json"
    (root / name).write_text(json.dumps(REPORT, ensure_ascii=False, indent=1, default=str) + "\n",
                             encoding="utf-8")
    if STOPS:
        log(f"{len(STOPS)} STOP condition(s) — nothing frozen for the stopped field. Report at {root / name}")
        return 1
    log(f"done in {REPORT.get('total_secs')} s; report at {root / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
