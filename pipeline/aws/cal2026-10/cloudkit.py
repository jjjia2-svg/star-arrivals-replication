#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pipeline/aws/cal2026-10/cloudkit.py — the LOCAL, money-free half of the October (cal2026-10)
cloud batch. REPO-AUTHORED (declared in tests/test_verbatim_pipeline.py::REPO_AUTHORED). It runs no
ported code, no R, and no `aws` command; `run_cloud.sh` beside it is the only file that spends money.

    $PY cloudkit.py prep      --frames DIR --pos-frames DIR --refs DIR --out PAYLOAD --custody CUSTODY
                              [--groups p3main,p3evcl,predate,perm,null] [--extra-serial ...]
                              [--extra-parallel ...] [--extra-file ...] [--parallel 12] [--threads 4]
                              [--no-predate-control]
    $PY cloudkit.py check-md5 PAYLOAD               # what the instance does: md5sum -c payload.md5
    $PY cloudkit.py record    --custody CUSTODY     # launch_record.json + the cost line
    $PY cloudkit.py custody   --custody CUSTODY --payload PAYLOAD [--gold-dir DIR]
                                                     # custody_cal2026-10.json (both ends of the wire)

WHAT THE BATCH IS (plan of 2026-09-22, §5 "on AWS"; since 2026-09-16 heavy re-estimation goes
straight to AWS). One r6i.16xlarge, one payload, one driver, in two phases:
  serial   (memory-bound, one at a time — the econ full pair panel peaks near 300 GiB of 495):
           P3_fnfix_chemistry, P3_econ_fnfix           run_p3.R       (the Panel-3 mains)
           P3evcl_chemistry,   P3evcl_econ             run_p3_evcl.R  (event-clustered SEs)
           P3_fnfix_chemistry, P3_econ_fnfix @shift 0  run_predate.R p3 -> out_predate_control/
                                                        (the CONTROL: must be compare_json-EQUAL to
                                                        the main cell run in the same batch)
           P3pd2_chemistry_full, P3pd2_econ_full @2    run_predate.R p3 -> out_predate/
                                                        (the full-panel date-shift cells that were
                                                        never run: predate/README.md "NOT RUN")
  parallel (thread-capped xargs, the 2026-08-30 restart.sh recipe): per field econ/chemistry/
           math_stats on the dose>0 pair panels p3_afar_pos_<f>.parquet —
           run_perm.R p3tp identity unit `0 0` (the CONTROL: perm 0 must reproduce the reference
           JSON, asserted inside run_perm.R) + the 500 timing permutations, and
           run_null.R the 200 risk-set-depletion simulations (no reference exists by design).
Extra serial cells (D7: the top-5% event subset and the three-bin dose variant of the full-panel
P3 cells) are passed as `--extra-serial 'NAME|OUTDIR|Rscript run_p3.R NAME file.parquet'` with
their frames via `--extra-file`; nothing about them is hard-coded here because their frames do not
exist yet.
Extra PARALLEL units (2026-09-23, the T5 batch: the Panel 1 / Panel 2 timing permutations that
run_all_perm.sh runs locally, assembled by prep_t5_batch.sh beside this file) use the same grammar,
`--extra-parallel 'NAME|OUTDIR|COMMAND'`, and are appended to jobs_parallel.txt AFTER the group
units (thread-capped, PAR-wide, one `PAR <unit> rc=` line each). An explicit `--groups ''` selects
NO group, so a batch may consist of extra units alone; omitting --groups still means every group.

ASSUMPTIONS, written down (rule: nothing hand-typed where a table can carry it):
  A1  cell -> driver -> payload-name table CELLS below mirrors data/cal2026-08-28/cloud/driver.sh
      token for token; tests/test_aws_cal2026_10.py proves the generated commands equal the
      four 2026-08-28 Rscript invocations and that payload.md5 on the 2026-08-28 frames reproduces
      data/cal2026-08-28/cloud/payload.md5 line for line (the CONTROL for this file).
  A2  the permutation/null unit grammar is the 2026-08-30 batch's (jobs.txt in
      data/cloud_custody_null_perm_2026-08-30/fetch/work/): seed base 20260830 for both (the pos
      batch; config/seeds.yaml's 20260829/20260817 belong to the 08-29 battery and B0), econ
      chunks of 5 (27.7 GB peak per econ null unit: restart.sh:20 and fetch/memprobe.log of the
      08-30 custody dir), other fields chunks of 50
      (perm) / 50 (null) as in jobs.txt.
  A3  parallelism 12 x 4 threads (restart.sh ran 14 x 4 and two econ null units were OOM-killed
      rc=137 — maps.json check:aws #5); 12 x 27.7 GB = 332 GB of 495 GB.
  A4  the driver emits ALL_DONE only when EVERY unit (serial and parallel) exited 0 — the 08-30
      restart.sh wrote its marker unconditionally after xargs (check:aws #5), so RESULT.txt did
      not certify per-unit success; here progress.log carries one `rc=` line per unit and the
      custody writer re-counts them.
  A5  cost = (terminate - launch) x $4.032/h (r6i.16xlarge us-east-1 on-demand, the 08-28 rate;
      prices change — the launcher prints the line, it does not check the price list).
  A6  time estimate basis: 08-28 measured wall (chem 2.1 / econ 5.6 / evchem 2.5 / evecon 6.9 min,
      custody_2026-08-28.json), predate control = main, shifted = 1.6 x main (one extra effects=2
      run), parallel phase = 81 min (the whole 08-30 batch 10:26-11:47Z including its restart),
      overhead 14 min (boot + bootstrap ~13 min + scp + fetch).
  A7  bootstrap adds r-cran-fixest to the 08-28 recipe (run_null.R needs fixest; the 08-30
      bootstrap.log is apt -qq quiet and does not show how it was installed — r2u carries every
      CRAN package as an Ubuntu binary, so the apt name is the assumption; PKG_OK asserts it).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import re
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))
from analysis.lib.compare_json import compare          # noqa: E402

MARKER = "2026_10C"
RATE_USD_H = 4.032
INSTANCE = {"instance_type": "r6i.16xlarge", "region": "us-east-1",
            "image_id": "ami-052355af2a014bd2c", "market": "on-demand"}
FIELDS = ("econ", "chemistry", "math_stats")

#: the four cloud cells: (label, driver basename, payload parquet) — order = run order on the
#: instance (cheap cell first, the M1 pattern: a broken environment fails in 2 minutes).
P3_MAIN = (("P3_fnfix_chemistry", "run_p3.R", "p3_slim_chemistry.parquet"),
           ("P3_econ_fnfix", "run_p3.R", "p3_slim_econ.parquet"))
P3_EVCL = (("P3evcl_chemistry", "run_p3_evcl.R", "p3_slim_ev_chemistry.parquet"),
           ("P3evcl_econ", "run_p3_evcl.R", "p3_slim_ev_econ.parquet"))
#: predate full-panel cells: field -> (main label, shifted label, slim, slim_ev)
PREDATE = (("chemistry", "P3_fnfix_chemistry", "P3pd2_chemistry_full",
            "p3_slim_chemistry.parquet", "p3_slim_ev_chemistry.parquet"),
           ("econ", "P3_econ_fnfix", "P3pd2_econ_full",
            "p3_slim_econ.parquet", "p3_slim_ev_econ.parquet"))
DRIVERS = {"run_p3.R": "analysis/estimation/run_p3.R",
           "run_p3_evcl.R": "analysis/estimation/run_p3_evcl.R",
           "run_predate.R": "analysis/robustness/predate/run_predate.R",
           "run_perm.R": "analysis/robustness/inference/run_perm.R",
           "run_null.R": "analysis/robustness/null_sim/run_null.R"}
GROUPS = ("p3main", "p3evcl", "predate", "perm", "null")
EVCL_REF = {"P3evcl_chemistry": "P3_fnfix_chemistry", "P3evcl_econ": "P3_econ_fnfix"}
#: A6
WALL_MIN = {"P3_fnfix_chemistry": 2.1, "P3_econ_fnfix": 5.6,
            "P3evcl_chemistry": 2.5, "P3evcl_econ": 6.9}
PREDATE_FACTOR, PARALLEL_PHASE_MIN, OVERHEAD_MIN = 1.6, 81.0, 14.0


def sha256(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def md5(p: pathlib.Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def utcnow() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _jload(p: pathlib.Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _jdump(p: pathlib.Path, obj) -> None:
    p.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def fail(msg: str) -> "NoReturn":                       # noqa: F821
    print(f"\n*** CLOUDKIT STOP: {msg}", flush=True)
    raise SystemExit(1)


def _rel(p: pathlib.Path) -> str:
    p = p.resolve()
    try:
        return p.relative_to(REPO).as_posix()
    except ValueError:
        return p.as_posix()


# ---------------------------------------------------------------------------------------------
# job lists
# ---------------------------------------------------------------------------------------------

def chunks(lo: int, hi: int, size: int) -> list[tuple[int, int]]:
    """Closed ranges [lo, hi] cut into pieces of `size` (the 08-30 grammar: 1-5, 6-10, ...)."""
    out, i = [], lo
    while i <= hi:
        j = min(i + size - 1, hi)
        out.append((i, j))
        i = j + 1
    return out


def serial_jobs(groups: set[str], predate_control: bool, extra: list[str]) -> list[tuple[str, str, str]]:
    """(name, outdir, command) per serial cell; name doubles as the log/timev basename."""
    jobs = []
    if "p3main" in groups:
        jobs += [(lab, "out", f"Rscript {drv} {lab} {pq}") for lab, drv, pq in P3_MAIN]
    if "p3evcl" in groups:
        jobs += [(lab, "out", f"Rscript {drv} {lab} {pq}") for lab, drv, pq in P3_EVCL]
    if "predate" in groups:
        for _f, main_lab, pd_lab, slim, ev in PREDATE:
            if predate_control:
                jobs.append((f"{main_lab}_pd0", "out_predate_control",
                             f"Rscript run_predate.R p3 {main_lab} {slim} 0 {ev}"))
            jobs.append((pd_lab, "out_predate", f"Rscript run_predate.R p3 {pd_lab} {slim} 2 {ev}"))
    jobs += extra_jobs(extra, "--extra-serial")
    names = [j[0] for j in jobs]
    if len(set(names)) != len(names):
        fail(f"duplicate serial job names: {sorted(n for n in names if names.count(n) > 1)}")
    return jobs


def extra_jobs(specs, flag: str) -> list[tuple[str, str, str]]:
    """'NAME|OUTDIR|COMMAND' specs (the --extra-serial / --extra-parallel grammar) -> job tuples."""
    jobs = []
    for spec in specs:
        parts = spec.split("|")
        if len(parts) != 3 or not all(parts):
            fail(f"{flag} needs 'NAME|OUTDIR|COMMAND', got {spec!r}")
        jobs.append((parts[0], parts[1], parts[2]))
    return jobs


def parallel_jobs(groups: set[str], fields, perm_b: int, null_n: int, perm_seed: int,
                  null_seed: int, chunk: dict, extra=()) -> list[tuple[str, str, str]]:
    jobs = []
    for f in fields:
        pq, ref = f"p3_afar_pos_{f}.parquet", f"P3cut_pos_{f}.json"
        if "perm" in groups:
            lab = f"P3cutpos_{f}"
            rng = [(0, 0)] + chunks(1, perm_b, chunk[f"perm_{f}"])
            for a, b in rng:
                jobs.append((f"{lab}_perm_{a}_{b}", "out_perm",
                             f"Rscript run_perm.R p3tp {lab} {pq} {ref} {perm_seed} {a} {b}"))
        if "null" in groups:
            lab = f"NULLpos_{f}"
            for a, b in chunks(1, null_n, chunk[f"null_{f}"]):
                jobs.append((f"{lab}_null_{a}_{b}", "out_null",
                             f"Rscript run_null.R {lab} {pq} {null_seed} {a} {b} out_null"))
    jobs += extra_jobs(extra, "--extra-parallel")
    names = [j[0] for j in jobs]
    if len(set(names)) != len(names):
        fail(f"duplicate parallel job names: {sorted(set(n for n in names if names.count(n) > 1))}")
    return jobs


def write_jobs(p: pathlib.Path, jobs) -> None:
    p.write_text("".join(f"{n}\t{o}\t{c}\n" for n, o, c in jobs), encoding="utf-8")


def read_jobs(p: pathlib.Path) -> list[tuple[str, str, str]]:
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        if ln.strip() and not ln.startswith("#"):
            n, o, c = ln.split("\t")
            out.append((n, o, c))
    return out


def payload_files_for(serial, parallel) -> set[str]:
    """Every payload basename the job commands reference (drivers, frames, reference JSONs)."""
    need = set()
    for _n, _o, cmd in list(serial) + list(parallel):
        toks = cmd.split()
        for t in toks[1:]:
            if t.endswith((".R", ".parquet", ".csv", ".json")):
                need.add(t)
    return need


# ---------------------------------------------------------------------------------------------
# prep
# ---------------------------------------------------------------------------------------------

def estimate_minutes(serial, parallel) -> dict:
    cells = {}
    for name, _o, cmd in serial:
        toks = cmd.split()
        if toks[1] == "run_predate.R":
            main = {pd: m for _f, m, pd, _s, _e in PREDATE}.get(toks[3])
            if main:
                cells[name] = round(WALL_MIN[main] * PREDATE_FACTOR, 1)
            else:
                cells[name] = WALL_MIN.get(toks[3], 5.6)
        else:
            cells[name] = WALL_MIN.get(toks[2], 5.6)     # unknown extra cell: assume econ-main size
    par = PARALLEL_PHASE_MIN if parallel else 0.0
    total = OVERHEAD_MIN + sum(cells.values()) + par
    return {"basis": "A6 in cloudkit.py: 08-28 measured wall per cell, predate x1.6, 08-30 batch "
                     "wall for the parallel phase, 14 min overhead",
            "serial_cells_min": cells, "parallel_phase_min": par, "overhead_min": OVERHEAD_MIN,
            "wall_min_projected": round(total, 1), "on_demand_usd_per_h": RATE_USD_H,
            "cost_usd_projected_on_demand": round(total / 60 * RATE_USD_H, 2)}


def prep(a) -> None:
    # --groups omitted = every group; an explicit '' (or ',,') = no group at all (extra units only)
    groups = set(GROUPS) if a.groups is None else {g for g in a.groups.split(",") if g}
    bad = groups - set(GROUPS)
    if bad:
        fail(f"unknown group(s) {sorted(bad)}; choose from {GROUPS}")
    fields = tuple(a.fields.split(","))
    chunk = {"perm_econ": a.perm_chunk_econ, "perm_chemistry": a.perm_chunk_other,
             "perm_math_stats": a.perm_chunk_other, "null_econ": a.null_chunk_econ,
             "null_chemistry": a.null_chunk_other, "null_math_stats": a.null_chunk_other}
    serial = serial_jobs(groups, not a.no_predate_control, a.extra_serial)
    parallel = parallel_jobs(groups, fields, a.perm_b, a.null_n, a.perm_seed, a.null_seed, chunk,
                             a.extra_parallel)
    if not serial and not parallel:
        fail("nothing to run: no serial and no parallel jobs selected")

    out, cust = pathlib.Path(a.out), pathlib.Path(a.custody)
    if out.exists() and any(out.iterdir()) and not a.force:
        fail(f"{out} is not empty — a payload is frozen bytes; use a fresh dir or --force")
    out.mkdir(parents=True, exist_ok=True)
    cust.mkdir(parents=True, exist_ok=True)

    # resolve every referenced file to a source on disk
    sources: dict[str, pathlib.Path] = {}
    dirs = {"frames": pathlib.Path(a.frames) if a.frames else None,
            "pos": pathlib.Path(a.pos_frames) if a.pos_frames else None,
            "refs": pathlib.Path(a.refs) if a.refs else None}
    extra_files = {pathlib.Path(x).name: pathlib.Path(x) for x in a.extra_file}
    for name in sorted(payload_files_for(serial, parallel)):
        if name in DRIVERS:
            src = REPO / DRIVERS[name]
        elif name in extra_files:
            src = extra_files[name]
        elif name.startswith("p3_afar_pos_"):
            src = (dirs["pos"] or pathlib.Path("/nonexistent")) / name
        elif name.startswith("P3cut_pos_"):
            src = (dirs["refs"] or pathlib.Path("/nonexistent")) / name
        else:
            src = (dirs["frames"] or pathlib.Path("/nonexistent")) / name
        if not src.is_file():
            fail(f"payload file {name} not found at {src} (give --frames/--pos-frames/--refs/"
                 f"--extra-file)")
        sources[name] = src
    for name, src in extra_files.items():          # files shipped but not referenced (allowed)
        sources.setdefault(name, src)

    # copy the bytes; write the driver bundle; hash LAST so payload.md5 covers what ships
    for name, src in sources.items():
        shutil.copyfile(src, out / name)
    shutil.copyfile(HERE / "bootstrap.sh", out / "bootstrap.sh")
    shutil.copyfile(HERE / "driver.sh", out / "driver.sh")
    (out / "driver.env").write_text(
        f"MARKER={MARKER}\nPAR={a.parallel}\nTHREADS={a.threads}\n", encoding="utf-8")
    write_jobs(out / "jobs_serial.txt", serial)
    write_jobs(out / "jobs_parallel.txt", parallel)
    shipped = sorted(p for p in out.iterdir() if p.is_file() and p.name != "payload.md5")
    (out / "payload.md5").write_text("".join(f"{md5(p)}  {p.name}\n" for p in shipped),
                                     encoding="utf-8")

    est = estimate_minutes(serial, parallel)
    pre = {"task": "cal2026-10 cloud batch — preflight (BEFORE upload)",
           "generated_utc": utcnow(), "marker": MARKER, "instance": INSTANCE,
           "groups": sorted(groups), "fields": list(fields),
           "seeds": {"perm": a.perm_seed, "null": a.null_seed},
           "perm_b": a.perm_b, "null_n": a.null_n, "chunks": chunk,
           "parallel": a.parallel, "threads": a.threads,
           "payload_dir": _rel(out),
           "payloads": {p.name: {"source": _rel(sources[p.name]) if p.name in sources else None,
                                 "sha256_before": sha256(p), "md5_before": md5(p),
                                 "bytes": p.stat().st_size} for p in shipped},
           "payload_md5_sha256": sha256(out / "payload.md5"),
           "jobs_serial": [list(j) for j in serial],
           "jobs_parallel_n": len(parallel),
           "cost_estimate": est}
    _jdump(cust / "custody_preflight.json", pre)
    shutil.copyfile(out / "payload.md5", cust / "payload.md5")
    print(f"[cloudkit] payload {out}: {len(shipped)} files, {len(serial)} serial cells, "
          f"{len(parallel)} parallel units; md5 list -> payload.md5")
    print(f"[cloudkit] estimate ~{est['wall_min_projected']:.0f} min @ ${RATE_USD_H}/h "
          f"≈ ${est['cost_usd_projected_on_demand']:.2f} (A6)")
    print(f"[cloudkit] preflight record -> {cust / 'custody_preflight.json'}")


# ---------------------------------------------------------------------------------------------
# check-md5 — the instance's own step, run locally (dry-run) with md5sum -c semantics
# ---------------------------------------------------------------------------------------------

def parse_md5(p: pathlib.Path) -> dict[str, str]:
    want = {}
    for ln in p.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            h, name = ln.split()[0], ln.split()[-1]
            want[name] = h
    return want


def check_md5(a) -> None:
    root = pathlib.Path(a.payload)
    listing = root / "payload.md5"
    if not listing.is_file():
        fail(f"{listing} missing")
    bad = 0
    for name, h in parse_md5(listing).items():
        p = root / name
        if not p.is_file():
            print(f"{name}: FAILED open or read"); bad += 1; continue
        ok = md5(p) == h
        print(f"{name}: {'OK' if ok else 'FAILED'}")
        bad += 0 if ok else 1
    if bad:
        print(f"md5sum: WARNING: {bad} computed checksum(s) did NOT match")
        raise SystemExit(1)


# ---------------------------------------------------------------------------------------------
# record — launch_record.json from the launcher's state files; prints the cost line
# ---------------------------------------------------------------------------------------------

def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8").strip() if p.is_file() else ""


def _iso(s: str) -> datetime.datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1]
    s = s.split(".")[0]
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")


def record(a) -> dict:
    cust = pathlib.Path(a.custody)
    st = cust / "state"
    iid = _read(st / "instance_id")
    if not iid:
        fail(f"{st / 'instance_id'} missing — nothing was launched from {cust}")
    launch = _read(cust / "launch_time_utc.txt")
    term = _read(cust / "terminate_time_utc.txt")
    if not launch or not term:
        fail("launch_time_utc.txt / terminate_time_utc.txt missing — the instance may still be "
             "running: check `aws ec2 describe-instances` before anything else")
    desc = _jload(cust / "describe_launch.json") if (cust / "describe_launch.json").is_file() else {}
    proof = _jload(cust / "termination_proof.json") if (cust / "termination_proof.json").is_file() else {}
    t0, t1 = _iso(launch), _iso(term)
    if t1 < t0:
        fail(f"terminate {term} precedes launch {launch}")
    billed_min = (t1 - t0).total_seconds() / 60
    cost = round(billed_min / 60 * a.rate, 2)
    rec = {"instance_id": iid,
           "instance_type": desc.get("InstanceType", INSTANCE["instance_type"]),
           "region": INSTANCE["region"],
           "az": desc.get("Placement", {}).get("AvailabilityZone", desc.get("Placement", "")),
           "market": INSTANCE["market"],
           "image_id": desc.get("ImageId", INSTANCE["image_id"]),
           "launch_time_utc": launch, "rate_usd_per_h": a.rate,
           "rate_source": "A5 in cloudkit.py: data/cal2026-08-28/cloud/launch_record.json "
                          "(rate_usd_per_h 4.032) and pipeline/aws/launch_p3_dcdh.sh:39 "
                          "($4.03/h); plan 2026-09-22 §5 says $4.03/h",
           "terminate_time_utc": term,
           "termination_state": proof.get("State", {}).get("Name", "UNKNOWN"),
           "billed_minutes": round(billed_min, 1), "cost_usd_actual": cost}
    _jdump(cust / "launch_record.json", rec)
    print(f"COST_LINE instance={iid} launched={launch} terminated={term} "
          f"billed={billed_min:.1f}min x ${a.rate}/h = ${cost:.2f} "
          f"(state={rec['termination_state']})")
    if rec["termination_state"] != "terminated":
        print("*** WARNING: termination_proof.json does not say 'terminated' — confirm in the "
              "console; the 10-hour user-data fuse is the backstop, not the plan")
    return rec


# ---------------------------------------------------------------------------------------------
# custody — both ends of the wire, written down; exit 1 on any broken link
# ---------------------------------------------------------------------------------------------

_TIMEV_WALL = re.compile(r"Elapsed \(wall clock\) time.*: ([\d:.]+)")
_TIMEV_RSS = re.compile(r"Maximum resident set size \(kbytes\): (\d+)")


def timev(p: pathlib.Path) -> dict:
    if not p.is_file():
        return {}
    t = p.read_text(encoding="utf-8", errors="replace")
    out = {}
    m = _TIMEV_WALL.search(t)
    if m:
        out["wall_clock"] = m.group(1)
    m = _TIMEV_RSS.search(t)
    if m:
        out["peak_rss_gib"] = round(int(m.group(1)) / 1024 / 1024, 1)
    return out


def custody(a) -> None:
    cust, pay = pathlib.Path(a.custody), pathlib.Path(a.payload)
    fetch = cust / "fetch"
    problems: list[str] = []
    note = problems.append
    pre_p = cust / "custody_preflight.json"
    if not pre_p.is_file():
        fail("custody_preflight.json missing — run `cloudkit.py prep` first")
    pre = _jload(pre_p)
    if not (cust / "launch_record.json").is_file():
        fail("launch_record.json missing — run `cloudkit.py record` first")
    launch = _jload(cust / "launch_record.json")
    if not fetch.is_dir():
        fail(f"{fetch} missing — nothing was fetched")

    # 1. the payload on disk still carries the pre-upload hashes (nothing moved under us)
    for name, v in pre["payloads"].items():
        p = pay / name
        if not p.is_file():
            note(f"payload {name} vanished from {pay}"); continue
        if sha256(p) != v["sha256_before"] or md5(p) != v["md5_before"]:
            note(f"payload {name} on disk no longer matches the pre-upload hash")

    # 2. the instance's own evidence: an OK md5 line per shipped file (md5check.log, tee'd into
    #    driver.log as well)
    remote_ok: dict[str, str] = {}
    for src in (fetch / "md5check.log", fetch / "driver.log"):
        if src.is_file():
            remote_ok.update(dict(re.findall(r"^(\S+): (OK)$", src.read_text(encoding="utf-8",
                                                                             errors="replace"), re.M)))
    missing = [n for n in pre["payloads"] if remote_ok.get(n) != "OK"]
    if missing:
        note(f"no remote 'OK' md5 line for {missing} — the instance did not prove it saw the "
             f"shipped bytes")

    # 3. run outcome: the marker, and one rc=0 per unit (A4)
    result = _read(fetch / "RESULT.txt")
    if result != f"ALL_DONE_MARKER_{MARKER}":
        note(f"RESULT.txt says {result!r}, not ALL_DONE_MARKER_{MARKER}")
    prog = (fetch / "progress.log").read_text(encoding="utf-8", errors="replace") \
        if (fetch / "progress.log").is_file() else ""
    units = {m.group(2): int(m.group(3))
             for m in re.finditer(r"^(SERIAL|PAR) (\S+) rc=(\d+)", prog, re.M)}
    serial = [tuple(j) for j in pre["jobs_serial"]]
    par_names = [n for n, _o, _c in read_jobs(pay / "jobs_parallel.txt")] \
        if (pay / "jobs_parallel.txt").is_file() else []
    expected = [n for n, _o, _c in serial] + [f"u{i:03d}_{n}" for i, n in enumerate(par_names, 1)]
    absent = [n for n in expected if n not in units]
    nonzero = {n: rc for n, rc in units.items() if rc != 0}
    if absent:
        note(f"{len(absent)} unit(s) have no rc line in progress.log (first: {absent[:5]})")
    if nonzero:
        note(f"{len(nonzero)} unit(s) exited non-zero: {dict(list(nonzero.items())[:8])}")

    # 4. serial results: parse, status OK, label matches; hash after; time -v
    cells = {}
    for name, outdir, cmd in serial:
        toks = cmd.split()
        label = toks[3] if toks[1] == "run_predate.R" else toks[2]
        src = fetch / outdir / f"{label}.json"
        rec = {"outdir": outdir, "command": cmd, "job_exit": units.get(name),
               **timev(fetch / "timev" / f"{name}.txt")}
        if not src.is_file():
            note(f"{name}: {outdir}/{label}.json not fetched")
        else:
            j = _jload(src)
            if j.get("status") != "OK" or j.get("label") != label:
                note(f"{name}: status={j.get('status')!r} label={j.get('label')!r}")
            rec.update({"result": f"{outdir}/{label}.json", "result_sha256_after": sha256(src),
                        "secs_r": j.get("secs")})
        payload_names = [t for t in toks if t in pre["payloads"] and not t.endswith(".R")]
        rec["payloads"] = {t: pre["payloads"][t]["md5_before"] for t in payload_names}
        cells[name] = rec

    # 5. the evcl point estimates match their mains (same panel, other cluster — the 08-28
    #    invariant), and the predate shift-0 control is compare_json-EQUAL to the main cell
    def _res(outdir, label):
        p = fetch / outdir / f"{label}.json"
        return _jload(p) if p.is_file() else None
    for ev, main in EVCL_REF.items():
        je, jm = _res("out", ev), _res("out", main)
        if je is None or jm is None:
            continue
        if abs(je["ate"] - jm["ate"]) >= 1e-8:
            note(f"{ev} ate {je['ate']} != {main} ate {jm['ate']} — the cluster choice moved a point "
                 f"estimate")
    controls = {}
    for _f, main_lab, _pd, _s, _e in PREDATE:
        jc, jm = _res("out_predate_control", main_lab), _res("out", main_lab)
        if jc is None or jm is None:
            continue
        d = compare(jc, jm)
        controls[main_lab] = "EQUAL" if not d else "DIFF: " + "; ".join(d[:5])
        if d:
            note(f"predate shift-0 control {main_lab} is NOT EQUAL to the main cell: {d[:3]}")

    # 6. parallel phase accounting: rows produced per label
    par_summary = {}
    for sub in ("out_perm", "out_null"):
        d = fetch / sub
        if d.is_dir():
            for f in sorted(d.glob("*.csv")):
                lab = f.name.split("_perm_")[0] if "_perm_" in f.name else f.name.split("_null_")[0]
                n = max(0, len(f.read_text(encoding="utf-8", errors="replace").splitlines()) - 1)
                par_summary.setdefault(lab, {"files": 0, "rows": 0})
                par_summary[lab]["files"] += 1
                par_summary[lab]["rows"] += n

    # 7. the verify block for tools/verify_cloud_custody.py --custody
    frame_pairs = [[v["source"], name] for name, v in pre["payloads"].items()
                   if v.get("source") and not name.endswith((".sh", ".txt", ".env"))]
    fetched_pairs = []
    if a.gold_dir:
        gold = pathlib.Path(a.gold_dir)
        for name, rec in cells.items():
            if "result" in rec and (gold / pathlib.Path(rec["result"]).name).is_file():
                fetched_pairs.append([rec["result"], pathlib.Path(rec["result"]).name])
    out = {"task": "cal2026-10 cloud batch — custody chain", "verified_utc": utcnow(),
           "ok": not problems, "problems": problems, "marker": MARKER,
           "instance": {k: launch.get(k) for k in
                        ("instance_id", "instance_type", "region", "az", "market", "image_id",
                         "launch_time_utc", "terminate_time_utc", "termination_state",
                         "rate_usd_per_h")},
           "billed_minutes": launch.get("billed_minutes"),
           "cost_usd_actual": launch.get("cost_usd_actual"),
           "cost_estimate_preflight": pre["cost_estimate"],
           "payload_md5_sha256": pre["payload_md5_sha256"],
           "payloads_before": pre["payloads"],
           "remote_md5_ok": sorted(n for n in pre["payloads"] if remote_ok.get(n) == "OK"),
           "versions_remote": _read(fetch / "versions.txt") or "MISSING",
           "result_marker": result,
           "units": {"expected": len(expected), "reported": len(units), "nonzero": nonzero,
                     "absent": absent},
           "cells": cells, "predate_controls": controls, "parallel_outputs": par_summary,
           "fetch_sha256": {f.relative_to(fetch).as_posix(): sha256(f)
                            for f in sorted(fetch.rglob("*")) if f.is_file()},
           "verify": {"frame_pairs": frame_pairs, "fetched_pairs": fetched_pairs,
                      "gold_dir": _rel(pathlib.Path(a.gold_dir)) if a.gold_dir else None,
                      "require_marker": f"ALL_DONE_MARKER_{MARKER}"}}
    _jdump(cust / "custody_cal2026-10.json", out)
    print(f"[cloudkit] custody -> {cust / 'custody_cal2026-10.json'}: "
          f"{'OK' if not problems else 'PROBLEMS ' + str(len(problems))}")
    for p in problems:
        print(f"  - {p}")
    print(f"[cloudkit] instance {launch.get('instance_id')} billed {launch.get('billed_minutes')} "
          f"min ≈ ${launch.get('cost_usd_actual')}")
    if problems:
        raise SystemExit(1)


# ---------------------------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prep", help="assemble the payload dir + payload.md5 + job lists + preflight")
    p.add_argument("--frames", help="dir with p3_slim_{econ,chemistry}.parquet and _ev twins")
    p.add_argument("--pos-frames", help="dir with p3_afar_pos_{f}.parquet")
    p.add_argument("--refs", help="dir with P3cut_pos_{f}.json (run_perm.R identity references)")
    p.add_argument("--out", required=True, help="payload dir (must be empty unless --force)")
    p.add_argument("--custody", required=True, help="custody dir for custody_preflight.json")
    p.add_argument("--groups", default=None,
                   help=f"subset of {GROUPS} (default: all); '' selects none (extra units only)")
    p.add_argument("--fields", default=",".join(FIELDS))
    p.add_argument("--extra-serial", action="append", default=[],
                   metavar="NAME|OUTDIR|COMMAND", help="extra serial cell (D7 variants)")
    p.add_argument("--extra-parallel", action="append", default=[],
                   metavar="NAME|OUTDIR|COMMAND",
                   help="extra parallel unit, appended to jobs_parallel.txt (T5: P1/P2 permutations)")
    p.add_argument("--extra-file", action="append", default=[], help="extra payload file")
    p.add_argument("--perm-b", type=int, default=500)
    p.add_argument("--null-n", type=int, default=200)
    p.add_argument("--perm-seed", type=int, default=20260830)
    p.add_argument("--null-seed", type=int, default=20260830)
    p.add_argument("--perm-chunk-econ", type=int, default=5)
    p.add_argument("--perm-chunk-other", type=int, default=50)
    p.add_argument("--null-chunk-econ", type=int, default=5)
    p.add_argument("--null-chunk-other", type=int, default=50)
    p.add_argument("--parallel", type=int, default=12, help="xargs -P for the parallel phase (A3)")
    p.add_argument("--threads", type=int, default=4, help="per-process BLAS/OMP/polars threads")
    p.add_argument("--no-predate-control", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=prep)

    p = sub.add_parser("check-md5", help="md5sum -c payload.md5, locally")
    p.add_argument("payload")
    p.set_defaults(fn=check_md5)

    p = sub.add_parser("record", help="launch_record.json + cost line from the state files")
    p.add_argument("--custody", required=True)
    p.add_argument("--rate", type=float, default=RATE_USD_H)
    p.set_defaults(fn=record)

    p = sub.add_parser("custody", help="custody_cal2026-10.json, exit 1 on any broken link")
    p.add_argument("--custody", required=True)
    p.add_argument("--payload", required=True)
    p.add_argument("--gold-dir", default=None,
                   help="frozen golds to name in the verify block (only cells with a gold file)")
    p.set_defaults(fn=custody)

    a = ap.parse_args(argv)
    # an R1 run folder (data/cal2026-10r1/, not shipped) is refused: R1 runs use pipeline/aws/r1/r1kit.py
    hit = [str(v) for v in (getattr(a, k, None) for k in ("out", "custody", "payload")) if v and "cal2026-10r1" in str(v)]
    if hit:
        print("R1 rule: this October launcher refuses R1 jobs; use pipeline/aws/r1/r1kit.py "
              f"(one instance, no SSH, S3 writes under r1/): {hit}", file=sys.stderr)
        return 64
    a.fn(a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
