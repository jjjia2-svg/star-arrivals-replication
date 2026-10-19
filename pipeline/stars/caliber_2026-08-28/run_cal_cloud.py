#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""caliber_2026-08-28/run_cal_cloud.py — Task-5 driver: the LOCAL half of the four cloud-only
estimation cells (`tools/compare_all.py` CLOUD_ONLY; T4 registry) on the caliber frames.
Repo-authored launcher (declared in `pipeline.lib.paths.LAUNCHERS`); it runs NO ported code and
NO aws command — per `pipeline/aws/` discipline the money-spending commands are typed by the
operator, recorded into `data/cal2026-08-28/cloud/`, and this driver proves custody around them.

    python3 ".../run_cal_cloud.py" --preflight   # before any upload: hash everything, write the
                                                 # shipping bundle + cost estimate
    python3 ".../run_cal_cloud.py" --verify      # after the fetch: custody chain end to end
    python3 ".../run_cal_cloud.py" --freeze      # results into estimates/, doc extended,
                                                 # MANIFEST regenerated (pure addition asserted)

Phases:
  P  preflight — the 4 cal payloads are sha256-verified against data/cal2026-08-28/MANIFEST.sha256
     AND against Task 4's registered_for_t5 registry (three-way identity, BEFORE upload); the two
     verbatim R drivers are hashed; `cloud/payload.md5` (what the instance itself will `md5sum -c`
     before the driver may start), `cloud/bootstrap.sh`, `cloud/driver.sh`, `cloud/userdata.txt`
     are written from this file (evidence copies = the exact bytes shipped); the cost estimate is
     computed from the M1 runbook's measured timings and printed. custody_preflight.json frozen.
  V  verify — with `cloud/fetch/` + `cloud/launch_record.json` in place: the payload the instance
     saw is tied to the pre-upload hashes (local frames re-hashed == payload.md5 == the instance's
     own `md5sum -c` OK lines tee'd into driver.log — the verify_cloud_custody pattern with the
     remote evidence kept this time), RESULT.txt carries the ALL_DONE marker, all four JOBn_EXIT=0,
     every fetched JSON parses with status OK and the right label, and the evcl cells' point
     estimates match their main-spec cells (same panel, other cluster — the frozen chain's own
     invariant). custody_2026-08-28.json written: per cell payload-hash-before, result-hash-after,
     instance id, timestamps, billed minutes, actual cost.
  F  freeze — the four JSONs byte-copied into data/cal2026-08-28/estimates/, the Task-5 section
     appended to docs/reviews/2026-08-28_cal_vs_frozen_estimates.md with the SAME extractor and
     flag machinery as Task 4 (rows_for/flags_for imported, not re-implemented), the cal MANIFEST
     regenerated with a pure-addition assertion (every pre-existing entry byte-unchanged).

A cell that errored on the instance is salvage-then-report territory (the M1 rule: an instance
that dies with its logs on it teaches nothing) — this driver never patches remotely and freezes
NOTHING unless every custody check passes."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import run_cal_estimates as rce                  # noqa: E402  (rows_for/flags_for/_f/sha/manifest)

CAL_DIR = REPO / "data" / "cal2026-08-28"
FRAMES = CAL_DIR / "frames"
EST_OUT = CAL_DIR / "estimates"
CLOUD = CAL_DIR / "cloud"
FETCH = CLOUD / "fetch"
EXPECTED = REPO / "analysis" / "expected"
DATA_EST = REPO / "data" / "estimates"
EST_DRV = REPO / "analysis" / "estimation"
DOC_OUT = REPO / "docs" / "reviews" / "2026-08-28_cal_vs_frozen_estimates.md"
RUN_REPORT = EST_OUT / "estimates_run_report_2026-08-28.json"
PRE_P = CLOUD / "custody_preflight.json"
LAUNCH_P = CLOUD / "launch_record.json"
CUSTODY_P = CLOUD / "custody_2026-08-28.json"
MARKER = "2026_08_28C"

#: cell -> (driver under analysis/estimation/, payload basename under data/cal2026-08-28/frames/,
#:          where the OLD frozen gold lives). Order = the run order on the instance (cheap cell
#: first, per the M1 drivers: a broken environment fails in ~2 minutes, not after the econ cell).
CLOUD_CELLS: tuple[tuple[str, str, str, str], ...] = (
    ("P3_fnfix_chemistry", "run_p3.R",      "p3_slim_chemistry.parquet",    "analysis/expected"),
    ("P3_econ_fnfix",      "run_p3.R",      "p3_slim_econ.parquet",         "analysis/expected"),
    ("P3evcl_chemistry",   "run_p3_evcl.R", "p3_slim_ev_chemistry.parquet", "data/estimates"),
    ("P3evcl_econ",        "run_p3_evcl.R", "p3_slim_ev_econ.parquet",      "data/estimates"),
)
#: evcl cell -> its main-spec cell: point estimates must match (same panel, other cluster) — the
#: frozen chain's own invariant (data/estimates/P3evcl_econ.json ate == expected/P3_econ_fnfix.json
#: ate to the JSON's 8 digits), asserted on the NEW results too.
EVCL_REF = {"P3evcl_chemistry": "P3_fnfix_chemistry", "P3evcl_econ": "P3_econ_fnfix"}

#: M1 measured timings (pipeline/aws/README.md) — the cost estimate's basis.
M1_WALL_MIN = {"P3_fnfix_chemistry": 1.8, "P3_econ_fnfix": 5.6,
               "P3evcl_chemistry": 2.2, "P3evcl_econ": 6.9}
M1_OVERHEAD_MIN = 14.0            # boot + bootstrap + scp + fetch/terminate (08-16: ~10.5 + tail)
ON_DEMAND_USD_H = 4.032           # r6i.16xlarge us-east-1 on-demand (runbook; re-checked 08-28)

BOOTSTRAP_SH = """#!/bin/bash
# bootstrap.sh — cal2026-08-28 T5: r2u CRAN binaries + rustup source build of R polars — the
# recipe of pipeline/aws/logs/p3_main_2026-08-16/bootstrap.sh verbatim, plus a versions.txt
# record (M1 gap: no version string was written to any cloud log; closed for the cal run).
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y -qq wget ca-certificates curl build-essential time >/dev/null
wget -qO- https://raw.githubusercontent.com/eddelbuettel/r2u/master/inst/scripts/add_cranapt_noble.sh | sudo bash
sudo apt-get install -y -qq r-cran-data.table r-cran-didmultiplegtdyn r-cran-jsonlite >/dev/null
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal >/dev/null
source "$HOME/.cargo/env"
export R_LIBS_USER="$HOME/Rlib"; mkdir -p "$R_LIBS_USER"
echo "R_LIBS_USER=$HOME/Rlib" >> ~/.Renviron
Rscript -e 'install.packages("polars", repos="https://rpolars.r-universe.dev", lib=Sys.getenv("R_LIBS_USER"))'
Rscript -e 'library(polars); library(DIDmultiplegtDYN); library(data.table); library(jsonlite); cat("PKG_OK\\n")'
{ Rscript -e 'cat("R", as.character(getRversion()), "DIDmultiplegtDYN", as.character(packageVersion("DIDmultiplegtDYN")), "polars", as.character(packageVersion("polars")), "data.table", as.character(packageVersion("data.table")), "jsonlite", as.character(packageVersion("jsonlite")), "\\n")'; apt-cache policy r-cran-didmultiplegtdyn | sed -n 1,3p; uname -a; } > ~/versions.txt
cat ~/versions.txt

# memory sentinel (M1 recipe)
( while true; do echo "$(date -u +%FT%TZ) $(free -g | sed -n 2p)" >> ~/mem.log; sleep 30; done ) &
echo $! > ~/mem_pid.txt

# environment ready; the driver is triggered separately, after payload md5 verification
echo BOOTSTRAP_DONE | tee ~/bootstrap_ready.txt
"""

DRIVER_SH = f"""#!/bin/bash
# driver.sh — cal2026-08-28 T5: the four cloud cells in sequence (chem main, econ main, chem
# evcl, econ evcl — cheap cell first, the M1 pattern); payload.md5 does not include this file
# (08-13 lesson); marker constant {MARKER}. The md5 verification output is tee'd into driver.log
# so the custody chain keeps the INSTANCE's own evidence, not only the refusal behaviour.
set -uo pipefail
cd ~
export R_LIBS_USER="$HOME/Rlib"
echo "[driver] start $(date -u +%FT%TZ)" | tee -a ~/driver.log
md5sum -c payload.md5 2>&1 | tee -a ~/driver.log || {{ echo "FAIL_MARKER_{MARKER}" > ~/RESULT.txt; echo MD5_FAIL | tee -a ~/driver.log; exit 1; }}
mkdir -p out
/usr/bin/time -v Rscript run_p3.R      "P3_fnfix_chemistry" p3_slim_chemistry.parquet    > log_chem.txt   2> timev_chem.txt
echo "JOB1_EXIT=$?" | tee -a ~/driver.log
/usr/bin/time -v Rscript run_p3.R      "P3_econ_fnfix"      p3_slim_econ.parquet         > log_econ.txt   2> timev_econ.txt
echo "JOB2_EXIT=$?" | tee -a ~/driver.log
/usr/bin/time -v Rscript run_p3_evcl.R "P3evcl_chemistry"   p3_slim_ev_chemistry.parquet > log_evchem.txt 2> timev_evchem.txt
echo "JOB3_EXIT=$?" | tee -a ~/driver.log
/usr/bin/time -v Rscript run_p3_evcl.R "P3evcl_econ"        p3_slim_ev_econ.parquet      > log_evecon.txt 2> timev_evecon.txt
J4=$?
echo "JOB4_EXIT=$J4" | tee -a ~/driver.log
if grep -q "JOB1_EXIT=0" ~/driver.log && grep -q "JOB2_EXIT=0" ~/driver.log && grep -q "JOB3_EXIT=0" ~/driver.log && [ "$J4" = "0" ]; then echo "ALL_DONE_MARKER_{MARKER}" > ~/RESULT.txt; else echo "FAIL_MARKER_{MARKER}" > ~/RESULT.txt; fi
echo "[driver] end $(date -u +%FT%TZ)" | tee -a ~/driver.log
"""

USERDATA = "#!/bin/bash\nshutdown -h +600\n"     # the ten-hour hard fuse (runbook rule)


def log(msg: str) -> None:
    print(f"[run_cal_cloud] {msg}", flush=True)


def fail(msg: str) -> "NoReturn":                # noqa: F821
    print(f"\n*** CUSTODY STOP: {msg}", flush=True)
    raise SystemExit(1)


def sha256(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def md5(p: pathlib.Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def utcnow() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _jload(p: pathlib.Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------
# P — preflight
# ---------------------------------------------------------------------------------------------

def preflight() -> None:
    man = rce.cal_manifest()
    registry = {r["cell"]: r for r in _jload(RUN_REPORT)["registered_for_t5"]}
    if set(registry) != {c for c, *_ in CLOUD_CELLS}:
        fail(f"T4 registry cells {sorted(registry)} != this driver's {sorted(c for c, *_ in CLOUD_CELLS)}")
    CLOUD.mkdir(exist_ok=True)
    payloads, drivers = {}, {}
    for cell, driver, payload, _gold in CLOUD_CELLS:
        p = FRAMES / payload
        rel = f"data/cal2026-08-28/frames/{payload}"
        got = sha256(p)
        if man.get(rel) != got:
            fail(f"{rel}: on-disk sha256 {got[:12]}… != cal MANIFEST {man.get(rel, '?')[:12]}…")
        reg = registry[cell]
        if reg["payload"] != rel or reg["payload_sha"] != got:
            fail(f"{cell}: T4 registry says {reg['payload']} {reg['payload_sha'][:12]}…, "
                 f"disk says {rel} {got[:12]}…")
        payloads[payload] = {"cell": cell, "sha256_before": got, "md5_before": md5(p),
                             "bytes": p.stat().st_size}
        d = EST_DRV / driver
        drivers[driver] = {"sha256": sha256(d), "md5": md5(d)}
    (CLOUD / "payload.md5").write_text(
        "".join(f"{v['md5_before']}  {name}\n" for name, v in payloads.items())
        + "".join(f"{v['md5']}  {name}\n" for name, v in drivers.items()),
        encoding="utf-8")
    (CLOUD / "bootstrap.sh").write_text(BOOTSTRAP_SH, encoding="utf-8")
    (CLOUD / "driver.sh").write_text(DRIVER_SH, encoding="utf-8")
    (CLOUD / "userdata.txt").write_text(USERDATA, encoding="utf-8")
    est_min = M1_OVERHEAD_MIN + sum(M1_WALL_MIN.values())
    est = {"basis": "pipeline/aws/README.md measured timings (M1, 2026-08-16) + runbook overhead",
           "cells_min": M1_WALL_MIN, "overhead_min": M1_OVERHEAD_MIN,
           "wall_min_projected": round(est_min, 1),
           "on_demand_usd_per_h": ON_DEMAND_USD_H,
           "cost_usd_projected_on_demand": round(est_min / 60 * ON_DEMAND_USD_H, 2)}
    pre = {"task": "T5 cloud cells cal2026-08-28 — preflight (BEFORE upload)",
           "generated_utc": utcnow(),
           "authority": "plan Task 5 + author approval 2026-08-27 (~$5-10) + T4 registry",
           "payloads": payloads, "r_drivers": drivers,
           "payload_md5_sha256": sha256(CLOUD / "payload.md5"),
           "bootstrap_sha256": sha256(CLOUD / "bootstrap.sh"),
           "driver_sh_sha256": sha256(CLOUD / "driver.sh"),
           "cost_estimate": est}
    PRE_P.write_text(json.dumps(pre, indent=1) + "\n", encoding="utf-8")
    log(f"preflight OK: 4 payloads three-way sha-verified (disk == cal MANIFEST == T4 registry); "
        f"bundle written to {CLOUD.relative_to(REPO)}")
    log(f"cost estimate: ~{est['wall_min_projected']:.0f} min on-demand @ "
        f"${ON_DEMAND_USD_H}/h ≈ ${est['cost_usd_projected_on_demand']:.2f} "
        f"(budget ~$5-10 approved; STOP line $15)")


# ---------------------------------------------------------------------------------------------
# V — verify (the custody chain, both ends of the wire)
# ---------------------------------------------------------------------------------------------

def verify() -> None:
    for p in (PRE_P, LAUNCH_P, FETCH):
        if not p.exists():
            fail(f"{p.relative_to(REPO)} missing — run the launch/fetch steps first")
    pre, launch = _jload(PRE_P), _jload(LAUNCH_P)
    driver_log = (FETCH / "driver.log").read_text(encoding="utf-8")
    result = (FETCH / "RESULT.txt").read_text(encoding="utf-8").strip()

    # 1. pre-upload hashes still true of the frames on disk (nothing moved under us)
    for name, v in pre["payloads"].items():
        p = FRAMES / name
        if sha256(p) != v["sha256_before"] or md5(p) != v["md5_before"]:
            fail(f"{name}: the frame on disk no longer matches the pre-upload hash")
    # 2. the instance's own evidence: md5sum -c OK for every payload + driver, tee'd to driver.log
    remote_ok = dict(re.findall(r"^(\S+): (OK)$", driver_log, re.M))
    want_names = list(pre["payloads"]) + list(pre["r_drivers"])
    missing = [n for n in want_names if remote_ok.get(n) != "OK"]
    if missing:
        fail(f"driver.log carries no 'OK' md5 line for {missing} — the instance did not prove "
             f"it saw the shipped bytes")
    # 3. run outcome markers
    if result != f"ALL_DONE_MARKER_{MARKER}":
        fail(f"RESULT.txt says {result!r}, not ALL_DONE_MARKER_{MARKER}")
    jobs = dict(re.findall(r"^JOB(\d)_EXIT=(\d+)", driver_log, re.M))
    if sorted(jobs) != ["1", "2", "3", "4"] or set(jobs.values()) != {"0"}:
        fail(f"driver.log JOB exits {jobs} — expected four zeros")
    # 4. fetched JSONs: parse, status OK, right label; hash AFTER
    cells = {}
    for i, (cell, driver, payload, _gold) in enumerate(CLOUD_CELLS, 1):
        src = FETCH / f"{cell}.json"
        if not src.is_file():
            fail(f"fetch/{cell}.json missing")
        j = _jload(src)
        if j.get("status") != "OK" or j.get("label") != cell:
            fail(f"{cell}: status={j.get('status')!r} label={j.get('label')!r}")
        tv = _timev(FETCH / f"timev_{_TV[cell]}.txt")
        cells[cell] = {"payload": payload,
                       "payload_sha256_before": pre["payloads"][payload]["sha256_before"],
                       "payload_md5_before": pre["payloads"][payload]["md5_before"],
                       "remote_md5_line": f"{payload}: OK",
                       "result_sha256_after": sha256(src),
                       "job_exit": int(jobs[str(i)]), "driver": driver,
                       "secs_r": j.get("secs"), **tv}
    # 5. the evcl point estimates match their main cells (same panel, other cluster)
    for ev, main in EVCL_REF.items():
        je, jm = _jload(FETCH / f"{ev}.json"), _jload(FETCH / f"{main}.json")
        if abs(je["ate"] - jm["ate"]) >= 1e-8:
            fail(f"{ev} ate {je['ate']} != {main} ate {jm['ate']} — the cluster choice moved a "
                 f"point estimate")
        ee = [x["est"] for x in je["effects"]]
        em = [x["est"] for x in jm["effects"]]
        if len(ee) != len(em) or any(abs(a - b) >= 1e-8 for a, b in zip(ee, em)):
            fail(f"{ev} effects differ from {main} — the cluster choice moved a point estimate")
    # 6. timestamps + cost
    t0 = datetime.datetime.strptime(launch["launch_time_utc"], "%Y-%m-%dT%H:%M:%SZ")
    t1 = datetime.datetime.strptime(launch["terminate_time_utc"], "%Y-%m-%dT%H:%M:%SZ")
    billed_min = (t1 - t0).total_seconds() / 60
    cost = round(billed_min / 60 * launch["rate_usd_per_h"], 2)
    custody = {"task": "T5 cloud cells cal2026-08-28 — custody chain",
               "verified_utc": utcnow(),
               "instance": {k: launch[k] for k in
                            ("instance_id", "instance_type", "region", "az", "market",
                             "image_id", "launch_time_utc", "terminate_time_utc",
                             "termination_state", "rate_usd_per_h")},
               "billed_minutes": round(billed_min, 1), "cost_usd_actual": cost,
               "cost_estimate_preflight": pre["cost_estimate"],
               "r_drivers": pre["r_drivers"],
               "payload_md5_sha256": pre["payload_md5_sha256"],
               "versions_remote": (FETCH / "versions.txt").read_text(encoding="utf-8").strip()
               if (FETCH / "versions.txt").is_file() else "MISSING",
               "cells": cells,
               "result_marker": result,
               "fetch_sha256": {f.name: sha256(f) for f in sorted(FETCH.iterdir())
                                if f.is_file()}}
    CUSTODY_P.write_text(json.dumps(custody, indent=1) + "\n", encoding="utf-8")
    log(f"custody chain VERIFIED end to end: 4 payloads (pre-upload sha == instance md5 OK), "
        f"ALL_DONE marker, 4/4 JOB exits 0, evcl point estimates MATCH their mains")
    log(f"instance {launch['instance_id']} billed {billed_min:.1f} min ≈ ${cost:.2f} "
        f"({launch['market']}, ${launch['rate_usd_per_h']}/h); custody log: "
        f"{CUSTODY_P.relative_to(REPO)}")


#: cell -> the timev/log suffix driver.sh uses
_TV = {"P3_fnfix_chemistry": "chem", "P3_econ_fnfix": "econ",
       "P3evcl_chemistry": "evchem", "P3evcl_econ": "evecon"}


def _timev(p: pathlib.Path) -> dict:
    if not p.is_file():
        return {}
    t = p.read_text(encoding="utf-8", errors="replace")
    out = {}
    m = re.search(r"Elapsed \(wall clock\) time.*: ([\d:.]+)", t)
    if m:
        out["wall_clock"] = m.group(1)
    m = re.search(r"Maximum resident set size \(kbytes\): (\d+)", t)
    if m:
        out["peak_rss_gib"] = round(int(m.group(1)) / 1024 / 1024, 1)
    return out


# ---------------------------------------------------------------------------------------------
# F — freeze (results into estimates/, doc extended, MANIFEST pure addition)
# ---------------------------------------------------------------------------------------------

def freeze() -> None:
    if not CUSTODY_P.is_file():
        fail("custody_2026-08-28.json missing — run --verify first")
    man_before = rce.cal_manifest()
    for cell, *_ in CLOUD_CELLS:
        dst = EST_OUT / f"{cell}.json"
        if dst.exists():
            fail(f"{dst.relative_to(REPO)} already exists — T5 must be a pure addition")
        dst.write_bytes((FETCH / f"{cell}.json").read_bytes())
    _extend_doc()
    manifest = "".join(
        f"{sha256(f)}  data/cal2026-08-28/{f.relative_to(CAL_DIR).as_posix()}\n"
        for f in sorted(CAL_DIR.rglob("*"))
        if f.is_file() and f.name != "MANIFEST.sha256")
    (CAL_DIR / "MANIFEST.sha256").write_text(manifest, encoding="utf-8")
    man_after = rce.cal_manifest()
    changed = {r for r, h in man_before.items() if man_after.get(r) != h}
    if changed:
        fail(f"MANIFEST regeneration CHANGED {len(changed)} pre-existing entries "
             f"(e.g. {sorted(changed)[:3]}) — not a pure addition")
    log(f"froze 4 cloud results into {EST_OUT.relative_to(REPO)}; MANIFEST "
        f"{len(man_before)} -> {len(man_after)} entries, pure addition asserted; doc extended")


def _extend_doc() -> None:
    text = DOC_OUT.read_text(encoding="utf-8")
    if "## Task 5 — the four cloud cells" in text:
        fail("the comparison doc already carries a Task-5 section")
    custody = _jload(CUSTODY_P)
    comparison = []
    for cell, _driver, _payload, gold_dir in CLOUD_CELLS:
        old = _jload(REPO / gold_dir / f"{cell}.json")
        new = _jload(EST_OUT / f"{cell}.json")
        old_rows = {r["variant"]: r for r in rce.rows_for(cell, old)}
        new_rows = {r["variant"]: r for r in rce.rows_for(cell, new)}
        for var in old_rows:
            o, n = old_rows[var], new_rows[var]
            comparison.append({"cell": cell, "variant": var, "old": o, "new": n,
                               "flags": rce.flags_for(o, n)})
    _f = rce._f
    L = []
    add = L.append
    add("## Task 5 — the four cloud cells (r6i.16xlarge, 2026-08-28), old vs new")
    add("")
    add("> GENERATED by `pipeline/stars/caliber_2026-08-28/run_cal_cloud.py --freeze` with the")
    add("> SAME extractor and flag machinery as the local table above (`rows_for`/`flags_for`")
    add("> imported from `run_cal_estimates.py`). Old = the frozen golds (`analysis/expected/`")
    add("> for the P3 mains; `data/estimates/` for the evcl robustness — the M1 arrangement).")
    add("> New = the EC2 results fetched in `data/cal2026-08-28/cloud/fetch/` and frozen into")
    add("> `data/cal2026-08-28/estimates/`. Custody chain: `cloud/custody_2026-08-28.json`.")
    add("")
    inst = custody["instance"]
    add(f"* custody: instance `{inst['instance_id']}` ({inst['instance_type']}, {inst['az']}, "
        f"{inst['market']}), launched {inst['launch_time_utc']}, terminated "
        f"{inst['terminate_time_utc']} (state `{inst['termination_state']}`), billed "
        f"{custody['billed_minutes']} min ≈ ${custody['cost_usd_actual']:.2f} at "
        f"${inst['rate_usd_per_h']}/h.")
    add(f"* estimator on the instance (recorded this time — the M1 register gap): "
        f"`{custody['versions_remote'].splitlines()[0]}`.")
    add("* evcl point estimates match their main cells to the JSON's 8 digits (same panel, "
        "other cluster) — the frozen chain's own invariant, asserted on the new results.")
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
    add("### Per-effect coefficients (k = years since arrival)")
    add("")
    for r in comparison:
        eo = {e["k"]: e for e in r["old"].get("effects", [])}
        en = {e["k"]: e for e in r["new"].get("effects", [])}
        if not eo and not en:
            continue
        add(f"#### {r['cell']} / {r['variant']}")
        add("")
        add("| k | est old | est new | se old | se new | n old→new |")
        add("|---|---|---|---|---|---|")
        for k in sorted(set(eo) | set(en)):
            o_, n_ = eo.get(k, {}), en.get(k, {})
            add(f"| {k} | {_f(o_.get('est'))} | {_f(n_.get('est'))} | "
                f"{_f(o_.get('se'))} | {_f(n_.get('se'))} | "
                f"{_f(o_.get('n'), '')}→{_f(n_.get('n'), '')} |")
        add("")
    flagged = [r for r in comparison if r["flags"]]
    add(f"With Task 5 the comparison covers all 23 frozen expected cells: 19 local (above) + "
        f"4 cloud ({len(comparison)} variant rows here, {len(flagged)} flagged).")
    add("")
    DOC_OUT.write_text(text + "\n".join(L) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--preflight", action="store_true")
    g.add_argument("--verify", action="store_true")
    g.add_argument("--freeze", action="store_true")
    args = ap.parse_args(argv)
    if args.preflight:
        preflight()
    elif args.verify:
        verify()
    else:
        freeze()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
