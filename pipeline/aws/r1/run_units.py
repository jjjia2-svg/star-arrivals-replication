#!/usr/bin/env python3
"""R1 unit executor (P3e F19, unit W1-ROB). Runs on an R1 instance only. Standard library only.

  run_units.py --units units.tsv --group G --plan plan.json --root DIR --repo DIR --out DIR
               [--prior DIR ...] [--config config/r1/robustness_r1.json] [--reuse DIR]

Runs the units of one group of rob_jobs_r1.py's TSV. PAR and threads come from W1-PARPLAN's plan.json
({joblist_sha256, groups: [{group, threads, par, pred_gib}], verdict}); a plan whose joblist_sha256 is not
the sha256 of this TSV, a plan verdict STOP, a group missing from the plan, or par*threads > 64 is refused
(exit 2) before anything runs. A plan group with `width`, `budget_gib` and per-unit predictions (units[].pred_gib)
is run packed: at most `width` units at once, a unit starting only while the predicted GiB of the running units
stays within the budget (a unit runs alone if nothing else is running); a unit of the group without a
prediction is refused (PLAN_UNIT_MISSING).

Each unit runs `cmd` with cwd = --repo and SAR_OUT = <root>/<outdir>. Leading K=V tokens are environment
assignments; the program `Rscript` is the unit's R stack (SAR_RSCRIPT_<STACK>, R_LIBS=SAR_RLIB_<STACK>; stack
per kind from the config's `stacks`), `python3` is this interpreter. Every unit gets OMP/OPENBLAS/MKL/
R_DATATABLE/POLARS thread variables = the plan's threads, and runs under /usr/bin/time -v when present.
Control units (kind control) run in-process: compare whole|union_channel, content_equal, filter_noop.

Statuses and exit code:
  OK               rc 0 and, for a JSON-writing driver, no failure status in the JSON
  ESTIMATE_FAILED  rc 0 but the JSON says status FAILED / FAILED_* / EMPTY (top level, predate.aux_status,
                   channels.union, pair_cluster/event_cluster): recorded, the batch continues
  FAIL             rc != 0, or no output JSON: the group finishes, then exit 1
  OOM              rc 137 / signal 9 / 'Killed': no further unit starts, exit 4
  EQUAL/MISMATCH   a control; MISMATCH skips the units that need it (SKIPPED_CONTROL), then exit 3
  SKIPPED          the unit it needs failed (or is unknown); counts as FAIL
  NOT_STARTED      left over after an OOM
Kind post units run one at a time, in TSV order, after the other units of the group.
--reuse DIR (an earlier launch's kept logs/, root/<outdir>/, reads/ and provenance.json): a run_perm.R unit that
launch finished, run with the same command on the same inputs, driver and env pins, is copied in, not rerun (status
OK, detail REUSED); every other unit runs as usual. The producer's sandbox read logs go to <out>/reuse_reads/.
Writes <out>/units_report_<group>.json and <out>/logs/<name>.log (+ .timev).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import glob
import hashlib
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import time

HOSTS = ("ec2-r1-test", "ec2-r1")
TIME_BIN = "/usr/bin/time"
VCPU = 64
THREAD_VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "R_DATATABLE_NUM_THREADS",
               "POLARS_MAX_THREADS")
JSONLESS = ("run_perm.R", "run_null.R")          # these write CSV slices, not a <label>.json
LABEL_AT_3 = ("run_p1_variant.R", "run_predate.R")  # Rscript <drv> <mode> <label> ...
PERM_HEADER = "label,mode,perm,seed_used,n_events,n_treated_events,status,ate,se,t,p_joint_effects,p_joint_placebo,secs"
PERM_DRIVER = "analysis/robustness/inference/run_perm.R"
READ_LOST = "__LOST__"   # sandbox.LOST: the watcher could not record every read
SUCCESS = {"OK", "EQUAL"}


class Refused(SystemExit):
    def __init__(self, msg):
        print(f"RUN_UNITS_REFUSED {msg}", flush=True)
        super().__init__(2)


def sha256_file(p) -> str:
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def read_units(path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))


def load_plan(plan_path, tsv_path, group) -> dict:
    plan = json.loads(pathlib.Path(plan_path).read_text(encoding="utf-8"))
    if plan.get("joblist_sha256") != sha256_file(tsv_path):
        raise Refused(f"PLAN_DIGEST_MISMATCH plan {plan.get('joblist_sha256')} != units {sha256_file(tsv_path)}")
    if str(plan.get("verdict", "OK")).upper() == "STOP":
        raise Refused("PLAN_STOP the parallel plan says STOP")
    g = [x for x in plan.get("groups", []) if x.get("group") == group]
    if len(g) != 1:
        raise Refused(f"PLAN_GROUP_MISSING {group}")
    par, threads = int(g[0]["par"]), int(g[0]["threads"])
    preds, budget = None, None
    if g[0].get("width") and g[0].get("units"):          # packed: the group's width, each unit's prediction
        par, budget = int(g[0]["width"]), float(g[0].get("budget_gib") or plan.get("budget_gib"))
        preds = {u["name"]: float(u["pred_gib"]) for u in g[0]["units"]}
    if par < 1 or threads < 1 or par * threads > VCPU:
        raise Refused(f"PLAN_THREADS_OVER group {group}: par {par} x threads {threads} > {VCPU}")
    return {"par": par, "threads": threads, "pred_gib": g[0].get("pred_gib"), "budget_gib": budget, "preds": preds}


# ---------------------------------------------------------------------------------------------
# result classification
# ---------------------------------------------------------------------------------------------

def _bad(v) -> bool:
    return isinstance(v, str) and (v == "FAILED" or v.startswith("FAILED_") or v == "EMPTY")


def failed_status(j: dict) -> str | None:
    """The failure status a driver wrote into its JSON (rc 0), or None."""
    if not isinstance(j, dict):
        return "NOT_A_JSON_OBJECT"
    if _bad(j.get("status")):
        return str(j["status"])
    pd = j.get("predate")
    if isinstance(pd, dict) and _bad(pd.get("aux_status")):
        return f"aux_status {pd['aux_status']}"
    ch = j.get("channels")
    if isinstance(ch, dict) and isinstance(ch.get("union"), dict) and _bad(ch["union"].get("status")):
        return f"union {ch['union']['status']}"
    for k in ("pair_cluster", "event_cluster"):
        if isinstance(j.get(k), dict) and _bad(j[k].get("status")):
            return f"{k} {j[k]['status']}"
    return None


def result_json(argv: list[str], outdir: pathlib.Path) -> pathlib.Path | None:
    """<SAR_OUT>/<label>.json for a JSON-writing R driver; None for CSV drivers and python units."""
    if not argv or pathlib.Path(argv[0]).name != "Rscript" or len(argv) < 3:
        return None
    drv = pathlib.Path(argv[1]).name
    if drv in JSONLESS:
        return None
    i = 3 if drv in LABEL_AT_3 else 2
    return outdir / f"{argv[i]}.json" if len(argv) > i else None


# ---------------------------------------------------------------------------------------------
# controls
# ---------------------------------------------------------------------------------------------

def _repo_imports(repo):
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))


def run_control(cmd: str, repo) -> tuple[str, str]:
    """(EQUAL|MISMATCH, detail)."""
    _repo_imports(repo)
    toks = shlex.split(cmd)
    try:
        if toks[0] == "compare":
            from analysis.lib.compare_json import compare  # noqa: PLC0415
            mode, new, ref = toks[1], pathlib.Path(toks[2]), pathlib.Path(toks[3])
            jn = json.loads(new.read_text(encoding="utf-8"))
            jr = json.loads(ref.read_text(encoding="utf-8"))
            if mode == "union_channel":
                jr["channels"] = {"union": jr["channels"]["union"]}
            elif mode != "whole":
                return "MISMATCH", f"unknown compare mode {mode}"
            d = compare(jn, jr)
            return ("EQUAL", "") if not d else ("MISMATCH", str(d[0])[:300])
        if toks[0] == "content_equal":
            from tools.content_equal import content_equal  # noqa: PLC0415
            pairs = toks[1:]
            if not pairs or len(pairs) % 2:
                return "MISMATCH", "content_equal needs pairs"
            for a, b in zip(pairs[::2], pairs[1::2]):
                r = content_equal(a, b)
                if not r.equal:
                    return "MISMATCH", f"{a} vs {b}: {getattr(r, 'detail', '')}"[:300]
            return "EQUAL", ""
        if toks[0] == "filter_noop":
            rep = json.loads(pathlib.Path(toks[1]).read_text(encoding="utf-8"))
            for k, v in rep["frames"].items():
                if isinstance(v, str):
                    return "MISMATCH", f"{k}: {v}"
                if isinstance(v, dict):
                    if "byte_identical_to_input" in v and v["byte_identical_to_input"] is not True:
                        return "MISMATCH", f"{k} not byte-identical with the full event tables"
                    if v.get("rows_out") != v.get("rows_in") or v.get("events_out") != v.get("events_in"):
                        return "MISMATCH", f"{k} lost rows with the full event tables"
            return "EQUAL", ""
    except Exception as e:  # noqa: BLE001 - a control that cannot be evaluated is a mismatch, never a pass
        return "MISMATCH", f"{type(e).__name__}: {e}"[:300]
    return "MISMATCH", f"unknown control {toks[0]}"


# ---------------------------------------------------------------------------------------------
# one unit
# ---------------------------------------------------------------------------------------------

def _split_cmd(cmd: str) -> tuple[dict, list[str]]:
    toks, env = shlex.split(cmd), {}
    while toks and re.match(r"^[A-Z_][A-Z0-9_]*=", toks[0]):
        k, v = toks.pop(0).split("=", 1)
        env[k] = v
    return env, toks


def run_unit(u: dict, *, root, repo, out, threads, stacks) -> dict:
    t0 = time.time()
    if u["kind"] == "control":
        st, detail = run_control(u["cmd"], repo)
        return {"status": st, "rc": None, "detail": detail, "secs": round(time.time() - t0, 2), "peak_gib": None}
    env_add, argv = _split_cmd(u["cmd"])
    orig = list(argv)
    if not argv:
        return {"status": "FAIL", "rc": None, "detail": "empty command", "secs": 0.0, "peak_gib": None}
    env = dict(os.environ)
    env.update(env_add)
    outdir = pathlib.Path(root) / u["outdir"]
    outdir.mkdir(parents=True, exist_ok=True)
    env["SAR_OUT"] = str(outdir)
    for k in THREAD_VARS:
        env[k] = str(threads)
    if argv[0] == "Rscript":
        stack = stacks.get(u["kind"], stacks.get("default", "rmac"))
        rs, rl = os.environ.get(f"SAR_RSCRIPT_{stack.upper()}"), os.environ.get(f"SAR_RLIB_{stack.upper()}")
        if not rs:
            return {"status": "FAIL", "rc": None, "detail": f"NO_R_STACK {stack}", "secs": 0.0, "peak_gib": None}
        argv = [rs] + argv[1:]
        if rl:
            env["R_LIBS"] = rl
        env["R_PROFILE_USER"] = "/dev/null"
        env["PATH"] = f"{os.path.dirname(rs)}:{env.get('PATH', '')}"
    elif argv[0] in ("python3", "python"):
        argv = [os.environ.get("PY") or sys.executable] + argv[1:]
    logs = pathlib.Path(out) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log, tv = logs / f"{u['name']}.log", logs / f"{u['name']}.timev"
    tv.unlink(missing_ok=True)                 # a stale 'signal 9' from an earlier attempt is not this run's
    timed = os.access(TIME_BIN, os.X_OK)
    pre = [TIME_BIN, "-v", "-o", str(tv)] if timed else []
    with open(log, "w", encoding="utf-8") as fh:
        rc = subprocess.run(pre + argv, cwd=str(repo), env=env, stdout=fh, stderr=subprocess.STDOUT).returncode
    secs = round(time.time() - t0, 1)
    tvt = tv.read_text(encoding="utf-8", errors="replace") if tv.is_file() else ""
    lgt = log.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"Maximum resident set size \(kbytes\): (\d+)", tvt)
    peak = round(int(m.group(1)) / 1024 / 1024, 2) if m else None
    rec = {"rc": rc, "secs": secs, "peak_gib": peak, "detail": ""}
    if rc == 137 or rc == -9 or "signal 9" in tvt or (rc != 0 and re.search(r"\bKilled\b", lgt + tvt)):
        return {**rec, "status": "OOM", "detail": "killed (rc 137 / signal 9): out of memory"}
    if rc != 0:
        return {**rec, "status": "FAIL", "detail": f"rc {rc}"}
    rj = result_json(orig, outdir)           # orig[0] is the literal program token of the TSV
    if rj is None:
        return {**rec, "status": "OK"}
    if not rj.is_file():
        return {**rec, "status": "FAIL", "detail": f"NO_OUTPUT {rj}"}
    try:
        fs = failed_status(json.loads(rj.read_text(encoding="utf-8")))
    except json.JSONDecodeError as e:
        return {**rec, "status": "FAIL", "detail": f"BAD_JSON {rj}: {e}"}
    if fs:
        return {**rec, "status": "ESTIMATE_FAILED", "detail": fs}
    return {**rec, "status": "OK"}


def load_provenance(reuse) -> dict:
    """<reuse>/provenance.json (written from the producer's own disk): refused unless its read logs are there,
    unchanged, and recorded every read."""
    p = pathlib.Path(reuse) / "provenance.json"
    if not p.is_file():
        raise Refused(f"REUSE_NO_PROVENANCE {p}")
    prov = json.loads(p.read_text(encoding="utf-8"))
    if prov.get("schema") != "sar.r1.reuse_provenance.v1" or not prov.get("reads") or not prov.get("producer"):
        raise Refused(f"REUSE_BAD_PROVENANCE {p}")
    for rel, sha in prov["reads"].items():
        f = pathlib.Path(reuse) / rel
        if not f.is_file() or sha256_file(f) != sha:
            raise Refused(f"REUSE_READS_CHANGED {rel}")
        if any(ln.partition("\t")[2] == READ_LOST for ln in f.read_text(encoding="utf-8").splitlines()):
            raise Refused(f"REUSE_READS_LOST {rel}")
    return prov


def kept_perm_unit(u: dict, reuse, prov: dict, repo, digest) -> dict | None:
    """The files of a run_perm.R unit an earlier launch finished (under `reuse`), or None.

    Same run = provenance names this exact command and output dir, and the kept files, the driver, the env pins
    and every input path of the command hash as they did on the producer's disk (digest(path) = sha256 or None).
    Finished = time -v says exit 0, the log has the driver's start line for this mode, label, range and seed and
    its completion line, and the CSV has the header and one row per permutation, in order, with this unit's
    label, mode and seeds (seed + i; none for the identity row 0)."""
    _, argv = _split_cmd(u["cmd"])
    if u["kind"] == "control" or len(argv) != 9 or argv[0] != "Rscript" or argv[1] != PERM_DRIVER:
        return None
    mode, lab = argv[2], argv[3]
    try:
        seed, p0, p1 = int(argv[6]), int(argv[7]), int(argv[8])
    except ValueError:
        return None
    pu = (prov.get("units") or {}).get(u["name"]) or {}
    if pu.get("cmd") != u["cmd"] or pu.get("outdir") != u["outdir"]:
        return None
    reuse, repo = pathlib.Path(reuse), pathlib.Path(repo)
    rel = {"log": f"logs/{u['name']}.log", "timev": f"logs/{u['name']}.timev",
           "csv": str(pathlib.Path("root") / u["outdir"] / f"{lab}_perm_{p0}_{p1}.csv")}
    files, pins = pu.get("files") or {}, prov.get("repo_sha256") or {}
    if any(r not in files or digest(reuse / r) != files[r] for r in rel.values()):
        return None
    if not {PERM_DRIVER, "config/r1/env_pins.json"} <= set(pins) or any(digest(repo / r) != s for r, s in pins.items()):
        return None
    ins = prov.get("inputs_sha256") or {}
    if any(a not in ins or digest(a) != ins[a] for a in argv[2:] if a.startswith("/")):
        return None
    log, tv, csv_f = reuse / rel["log"], reuse / rel["timev"], reuse / rel["csv"]
    tvt = tv.read_text(encoding="utf-8", errors="replace")
    lgt = log.read_text(encoding="utf-8", errors="replace")
    if not re.search(r"^\s*Exit status: 0\s*$", tvt, re.M):
        return None
    if f"===== permutation {mode} {lab} events=" not in lgt or f" perms={p0}..{p1} seed={seed} =====" not in lgt \
            or f"[{lab}] {p0}..{p1} 完成 -> " not in lgt:
        return None
    lines = csv_f.read_text(encoding="utf-8").splitlines()
    want = list(range(p0, p1 + 1))
    if not lines or lines[0] != PERM_HEADER or len(lines) - 1 != len(want):
        return None
    for i, ln in zip(want, lines[1:]):
        r = ln.split(",")
        if len(r) != 13 or r[:4] != [lab, mode, str(i), "" if i == 0 else str(seed + i)]:
            return None
    m = re.search(r"Maximum resident set size \(kbytes\): (\d+)", tvt)
    return {"csv": csv_f, "log": log, "timev": tv, "peak_gib": round(int(m.group(1)) / 1024 / 1024, 2) if m else None}


def reuse_unit(u: dict, kept: dict, *, root, out) -> dict:
    """Copy a finished unit's CSV, log and time record into this run's layout."""
    dest = pathlib.Path(root) / u["outdir"]
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(kept["csv"], dest / kept["csv"].name)
    logs = pathlib.Path(out) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    for k in ("log", "timev"):
        shutil.copy2(kept[k], logs / kept[k].name)
    return {"status": "OK", "rc": 0, "secs": 0.0, "peak_gib": kept["peak_gib"], "detail": f"REUSED {kept['csv'].name}"}


# ---------------------------------------------------------------------------------------------
# scheduling
# ---------------------------------------------------------------------------------------------

def prior_status(name: str, prior_dirs) -> str | None:
    for d in prior_dirs:
        pats = [os.path.join(d, "units_report_*.json"), os.path.join(d, "*", "units_report_*.json")]
        for f in sorted(set(sum((glob.glob(p) for p in pats), []))):
            try:
                j = json.loads(pathlib.Path(f).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if name in j.get("units", {}):
                return j["units"][name]["status"]
    return None


def execute(units: list[dict], *, par, threads, root, repo, out, stacks, prior_dirs=(), budget_gib=None,
            preds=None, reuse=None, prov=None) -> tuple[dict, int]:
    names = {u["name"] for u in units}
    by = {u["name"]: u for u in units}
    res: dict[str, dict] = {}
    oom = False
    seen: dict[str, str | None] = {}

    def digest(p):
        p = str(p)
        if p not in seen:
            seen[p] = sha256_file(p) if os.path.isfile(p) else None
        return seen[p]

    for u in units if reuse else ():
        kept = kept_perm_unit(u, reuse, prov, repo, digest)
        if kept:
            res[u["name"]] = reuse_unit(u, kept, root=root, out=out)
    todo = [u for u in units if u["name"] not in res]

    def dep_state(u):
        dep = u.get("needs_control", "")
        if not dep:
            return "ok", ""
        if dep in names:
            if dep not in res:
                return "wait", ""
            st = res[dep]["status"]
            if st in SUCCESS:
                return "ok", ""
            return ("control" if st == "MISMATCH" else "bad"), f"{dep} {st}"
        st = prior_status(dep, prior_dirs)
        if st is None:
            return "bad", f"NEEDS_UNKNOWN {dep}"
        if st in SUCCESS:
            return "ok", ""
        return ("control" if st == "MISMATCH" else "bad"), f"{dep} {st} (earlier group)"

    def go(phase_units, width):
        nonlocal oom
        pending = list(phase_units)
        running: dict[cf.Future, dict] = {}
        with cf.ThreadPoolExecutor(max(1, width)) as ex:
            while pending or running:
                if not oom:
                    for u in list(pending):
                        if len(running) >= width:
                            break
                        st, why = dep_state(u)
                        if st == "wait":
                            continue
                        if preds is not None and st == "ok" and running and \
                                sum(preds[r["name"]] for r in running.values()) + preds[u["name"]] > budget_gib + 1e-9:
                            continue                     # over the memory budget: a lighter unit may fit
                        pending.remove(u)
                        if st != "ok":
                            res[u["name"]] = {"status": "SKIPPED_CONTROL" if st == "control" else "SKIPPED",
                                              "rc": None, "detail": why, "secs": 0.0, "peak_gib": None}
                            continue
                        running[ex.submit(run_unit, u, root=root, repo=repo, out=out, threads=threads,
                                          stacks=stacks)] = u
                if not running:
                    if pending:   # OOM, or a need that can never be met in this phase
                        for u in pending:
                            res[u["name"]] = {"status": "NOT_STARTED" if oom else "SKIPPED", "rc": None,
                                              "detail": "after OOM" if oom else f"needs {u['needs_control']} not run",
                                              "secs": 0.0, "peak_gib": None}
                    break
                done, _ = cf.wait(list(running), return_when=cf.FIRST_COMPLETED)
                for f in done:
                    u = running.pop(f)
                    try:
                        res[u["name"]] = f.result()
                    except Exception as e:  # noqa: BLE001 - an executor error is a FAIL with its message
                        res[u["name"]] = {"status": "FAIL", "rc": None, "detail": f"{type(e).__name__}: {e}"[:300],
                                          "secs": 0.0, "peak_gib": None}
                    if res[u["name"]]["status"] == "OOM":
                        oom = True

    go([u for u in todo if u["kind"] != "post"], par)
    if not oom:
        go([u for u in todo if u["kind"] == "post"], 1)
    else:
        for u in units:
            if u["name"] not in res:
                res[u["name"]] = {"status": "NOT_STARTED", "rc": None, "detail": "after OOM", "secs": 0.0,
                                  "peak_gib": None}
    for n, r in res.items():
        r["kind"], r["outdir"] = by[n]["kind"], by[n]["outdir"]
    sts = [r["status"] for r in res.values()]
    if oom:
        code = 4
    elif "MISMATCH" in sts:
        code = 3
    elif any(s in ("FAIL", "SKIPPED") for s in sts):
        code = 1
    else:
        code = 0
    return res, code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 unit executor")
    for k in ("--units", "--group", "--plan", "--root", "--repo", "--out"):
        ap.add_argument(k, required=True)
    ap.add_argument("--prior", action="append", default=[], help="dir(s) holding earlier units_report_*.json")
    ap.add_argument("--config", default=None, help="robustness_r1.json (default <repo>/config/r1/robustness_r1.json)")
    ap.add_argument("--reuse", default=None, help="an earlier launch's kept logs/ and root/: its finished perm units are copied")
    a = ap.parse_args(argv)
    if os.environ.get("SAR_HOST", "").strip() not in HOSTS:
        raise SystemExit("R1 rule: run_units.py runs only on an R1 instance ($SAR_HOST)")
    plan = load_plan(a.plan, a.units, a.group)
    units = [u for u in read_units(a.units) if u["group"] == a.group]
    if not units:
        raise Refused(f"NO_UNITS group {a.group}")
    if plan["preds"] is not None and any(u["name"] not in plan["preds"] for u in units):
        raise Refused(f"PLAN_UNIT_MISSING group {a.group}: "
                      f"{sorted(u['name'] for u in units if u['name'] not in plan['preds'])[:5]}")
    cfgp = pathlib.Path(a.config) if a.config else pathlib.Path(a.repo) / "config" / "r1" / "robustness_r1.json"
    stacks = json.loads(cfgp.read_text(encoding="utf-8"))["stacks"]
    prov = load_provenance(a.reuse) if a.reuse else None
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    res, code = execute(units, par=plan["par"], threads=plan["threads"], root=a.root, repo=a.repo, out=out,
                        stacks=stacks, prior_dirs=a.prior, budget_gib=plan["budget_gib"], preds=plan["preds"],
                        reuse=a.reuse, prov=prov)
    reused = sorted(n for n, r in res.items() if r["detail"].startswith("REUSED"))
    if reused:                                  # the producer's read evidence, for this job's sandbox_check
        (out / "reuse_reads").mkdir(exist_ok=True)
        for rel in prov["reads"]:
            shutil.copy2(pathlib.Path(a.reuse) / rel, out / "reuse_reads" / f"{prov['producer']['job']}_{pathlib.Path(rel).name}")
    counts: dict[str, int] = {}
    for r in res.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    rep = {"schema": "sar.r1.units_report.v1", "group": a.group, "units_tsv_sha256": sha256_file(a.units),
           "plan": plan, "root": str(a.root), "exit": code, "counts": counts, "secs": round(time.time() - t0, 1),
           "units": {u["name"]: res[u["name"]] for u in units},
           "reused": reused, "reuse_producer": prov["producer"] if prov else None}
    (out / f"units_report_{a.group}.json").write_text(json.dumps(rep, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for u in units:
        r = res[u["name"]]
        print(f"{u['name']:<40} {r['status']:<16} {r.get('secs')}s {r.get('detail') or ''}")
    print(f"RUN_UNITS group={a.group} exit={code} {counts}")
    return code


if __name__ == "__main__":
    sys.exit(main())
