#!/usr/bin/env python3
"""R1 robustness post-processing and small build steps (P3e F19, unit W1-ROB).

Every subcommand takes --repo (the checkout whose analysis/ and tools/ code it calls) and is one unit of
rob_jobs_r1.py's list (kind build or post). The October inline snippets that had no file become functions
here, each proven byte-equal to its committed October product by tests/test_r1_robustness.py:

  loeo-rank       run_all_battery.sh's ranked-LOEO heredoc        -> battery/loeo_ranked.csv
  cut-grid        run_cuts.sh step D                               -> afar_cuts/afar_cut_grid.csv
  perm-summary    split <label>_perm_<a>_<b>.csv into raw/ + control/ (perm 0_0), then
                  analysis/robustness/inference/summarize_perm.py  -> <dest>/perm_summary.{csv,json}
  null-merge      analysis/robustness/null_sim/merge_null.merge    -> cloud/null/NULLpos_<field>.json
  build-cuts      run_cuts.sh build(): build_afar_cut.build(field, spec, out, sources=...) -> cuts_build.json
  filter-p05      threshold_p05/filter_frames.py, report renamed to its October name
  copy-cuts       J1a's P3pos/P3med JSONs (label P3cut_<spec>_<field>) -> afar_cuts/estimates/P3cut_*.json
  nocentre-report the cells and population block ledger_robustness.py reads from nocentre_report.json
  manifest        tools/write_manifest.py over every top directory of the robustness root
  report          rob_custody.json (sha256 of every product + the units reports) and rob_report.json
  canon-pack      (run_robustness_r1.sh, after the post group) the J1b part of canon M in October's cal layout:
                  $STAGE_OUT/canon/{robustness,cloud,cloud_t5} + per batch custody_cal2026-10.json (M review #9)
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import sys

FIELDS = ("econ", "chemistry", "math_stats")


def stop(msg: str) -> "NoReturn":  # noqa: F821
    print(f"ROB_POST_STOP {msg}", flush=True)
    raise SystemExit(2)


def _load(repo, rel: str, name: str):
    p = pathlib.Path(repo) / rel
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha(p) -> str:
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------------------------
# loeo-rank (run_all_battery.sh heredoc, line for line; paths passed in)
# ---------------------------------------------------------------------------------------------

def loeo_rank(loeo_dir, ledger_csv, canon_json, out_csv, frame_csv=None) -> list[dict]:
    canon = json.load(open(canon_json, encoding="utf-8"))["channels"]["union"]
    led = {r["event_id"]: r for r in csv.DictReader(open(ledger_csv, encoding="utf-8"))}
    rows = []
    for f in sorted(glob.glob(f"{loeo_dir}/P1loeo_*.json")):
        j = json.load(open(f, encoding="utf-8")); u = j["channels"]["union"]; ev = j["loeo_event"]
        plc3 = next((p["est"] for p in u.get("placebos", []) if p["k"] == -3), None)
        L = led.get(ev, {})
        rows.append({"event_id": ev, "star_id": L.get("star_id", ""),
                     "school": L.get("school", ""), "arrival_year": L.get("arrival_year", ""),
                     "ate": u["ate"], "se": u["se"],
                     "p_joint_placebo": u["p_joint_placebo"], "p_joint_effects": u["p_joint_effects"],
                     "delta_ate_vs_canon": u["ate"] - canon["ate"],
                     "delta_p_placebo_vs_canon": u["p_joint_placebo"] - canon["p_joint_placebo"],
                     "placebo_k_minus3_est": plc3, "obs": u["obs"], "events": u["events"]})
    if frame_csv is not None:          # R1: one removal per event of THIS frame, no more, no less
        with open(frame_csv, newline="", encoding="utf-8") as fh:
            want = {r["event_id"] for r in csv.DictReader(fh)}
        got = [r["event_id"] for r in rows]
        if sorted(got) != sorted(want) or len(set(got)) != len(got):
            stop(f"LOEO_COVERAGE {len(got)} removals vs {len(want)} frame events "
                 f"(missing {sorted(want - set(got))[:5]}, extra {sorted(set(got) - want)[:5]})")
    rows.sort(key=lambda r: -r["p_joint_placebo"])
    for i, r in enumerate(rows): r["rank_by_placebo_p"] = i + 1
    cols = ["rank_by_placebo_p", "event_id", "star_id", "school", "arrival_year", "ate", "se",
            "p_joint_placebo", "p_joint_effects", "delta_ate_vs_canon",
            "delta_p_placebo_vs_canon", "placebo_k_minus3_est", "obs", "events"]
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow({k: r[k] for k in cols})
    print(f"canon union: ate={canon['ate']:.6f} p_placebo={canon['p_joint_placebo']:.6f}")
    print("top 10 removals by placebo p:")
    for r in rows[:10]:
        print(f"  {r['rank_by_placebo_p']:>3} {r['event_id']:<18} {r['school']:<12} "
              f"p={r['p_joint_placebo']:.4f} ate={r['ate']:+.4f}")
    return rows


# ---------------------------------------------------------------------------------------------
# cut-grid (run_cuts.sh step D, line for line)
# ---------------------------------------------------------------------------------------------

def cut_grid(est, fr, build, grid) -> list[dict]:
    import duckdb  # noqa: PLC0415
    est, fr, build, grid = (pathlib.Path(a) for a in (est, fr, build, grid))
    cuts = json.loads(build.read_text())["cuts"]
    rows = []
    for fld in ("econ", "chemistry", "math_stats"):
        for c in ("pos", "med", "abs04", "p75"):
            d = json.load(open(est / f"P3cut_{c}_{fld}.json")); pc, ec = d["pair_cluster"], d["event_cluster"]
            pq = (fr / f"p3_afar_{c}_{fld}.parquet").as_posix()
            n, g = duckdb.sql(f"SELECT count(*), count(DISTINCT grp) FROM read_parquet('{pq}')").fetchone()
            rows.append(dict(field=fld, cut_spec=c, cut=repr(cuts[f"{c}_{fld}"]["cut_full"]), obs=n, pairs=g,
                             ate_pp=round(pc["ate"] * 100, 4), se_pair_pp=round(pc["se"] * 100, 4),
                             se_event_pp=round((ec.get("se") or 0) * 100, 4),
                             ci_lo_pp=round(pc["lb"] * 100, 4), ci_hi_pp=round(pc["ub"] * 100, 4),
                             p_joint_effects=pc["p_joint_effects"]))
    with open(grid, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    for r in rows:
        print(f"  {r['field']:<11}{r['cut_spec']:<7}cut={r['cut']:<22} pairs={r['pairs']:>7,}  ate={r['ate_pp']:>+8.4f} pp (SE {r['se_pair_pp']:.4f}) p={r['p_joint_effects']:.4g}")
    print(f"grid written: {grid} ({len(rows)} rows)")
    return rows


# ---------------------------------------------------------------------------------------------
# perm-summary / null-merge
# ---------------------------------------------------------------------------------------------

def perm_complete(files, labels, B) -> dict:
    """M review #11: a permutation batch is complete before it is summarised. For every expected label: exactly one
    <label>_perm_0_0.csv and one perm-0 (identity) row; draw indices - OK and FAILED rows alike, run_perm.R writes one
    row per index and a FAILED draw is reported, never dropped (summarize_perm's rule) - exactly 1..B, none twice;
    and no row of another label. October's summarize_perm checks only 1..len(draws), so a run missing its last
    slices (or every draw of a label) would be summarised with a smaller B. STOP PERM_INCOMPLETE otherwise."""
    labels, B = list(labels), int(B)
    if not labels or B < 1:
        stop(f"PERM_INCOMPLETE bad expectation labels {labels} B {B}")
    draws = {lab: [] for lab in labels}
    ctl_files, ctl_rows, other = dict.fromkeys(labels, 0), dict.fromkeys(labels, 0), set()
    for f in map(pathlib.Path, files):
        if f.name.endswith("_perm_0_0.csv") and f.name[:-len("_perm_0_0.csv")] in ctl_files:
            ctl_files[f.name[:-len("_perm_0_0.csv")]] += 1
        with open(f, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["label"] not in draws:
                    other.add(r["label"])
                elif int(r["perm"]) == 0:
                    ctl_rows[r["label"]] += 1
                else:
                    draws[r["label"]].append(int(r["perm"]))
    want, problems = set(range(1, B + 1)), []
    for lab in labels:
        got = draws[lab]
        missing = sorted(want - set(got))
        dup = sorted({x for x in got if got.count(x) > 1}) if len(got) != len(set(got)) else []
        extra = sorted(set(got) - want)
        if missing or dup or extra or ctl_files[lab] != 1 or ctl_rows[lab] != 1:
            problems.append(f"{lab} missing {missing[:5]}{'...' if len(missing) > 5 else ''} ({len(missing)}) "
                            f"dup {dup[:5]} extra {extra[:5]} control files {ctl_files[lab]} identity rows {ctl_rows[lab]}")
    if problems or other:
        stop(f"PERM_INCOMPLETE {problems} extra-labels {sorted(other)}")
    return {"labels": labels, "B": B, "draws": {lab: len(v) for lab, v in draws.items()}}


def perm_summary(repo, units_out, dest, labels=None, B=None) -> dict:
    """units_out holds every <label>_perm_<a>_<b>.csv a perm unit wrote (October: fetch/out_perm). The
    identity units (0_0) go to dest/control, the draws to dest/raw (October's layout), then
    summarize_perm.main(dest) writes dest/perm_summary.{csv,json}. With labels and B (M: rob_jobs passes the
    configured labels and robustness_r1.json perm.B) the batch must be complete first (perm_complete), before
    anything is written; without them October's replay is unchanged."""
    src, dst = pathlib.Path(units_out), pathlib.Path(dest)
    files = sorted(src.glob("*_perm_*.csv"))
    if not files:
        stop(f"PERM_NO_SLICES {src}")
    if labels is not None or B is not None:
        if labels is None or B is None:
            stop("PERM_INCOMPLETE --labels and --B go together")
        perm_complete(files, labels, B)
    for sub in ("raw", "control"):
        shutil.rmtree(dst / sub, ignore_errors=True)
        (dst / sub).mkdir(parents=True)
    n = {"raw": 0, "control": 0}
    for f in files:
        sub = "control" if f.name.endswith("_perm_0_0.csv") else "raw"
        shutil.copyfile(f, dst / sub / f.name)
        n[sub] += 1
    sp = _load(repo, "analysis/robustness/inference/summarize_perm.py", "summarize_perm")
    sp.main(str(dst))
    return n


def null_merge(repo, slices, label, nsim, out) -> dict:
    mn = _load(repo, "analysis/robustness/null_sim/merge_null.py", "merge_null")
    d = mn.merge(pathlib.Path(slices), label, int(nsim))
    dst = pathlib.Path(out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(d, indent=1))                       # as merge_null.py's __main__
    m = d["null_mean"]
    print(f"{label}: nsim={d['nsim']} slices={d['n_slices']} "
          f"dCDH_null={m['dcdh_ate_pp']:+.4f} pp  (used {d['n_used']['dcdh_ate_pp']}) -> {dst}")
    return d


# ---------------------------------------------------------------------------------------------
# build steps
# ---------------------------------------------------------------------------------------------

def build_cuts(repo, *, frames, pairs_econ, pairs_dir, specs, fields, out, report) -> dict:
    """run_cuts.sh build(): build_afar_cut.build with explicit sources. `frames`/`pairs_dir` may hold
    '{field}' (the nocentre variant products live in frames_<field>/)."""
    ac = _load(repo, "analysis/robustness/p3_afar_cuts/build_afar_cut.py", "afar_cut")
    out, repf = pathlib.Path(out), pathlib.Path(report)
    out.mkdir(parents=True, exist_ok=True)
    rep = json.loads(repf.read_text()) if repf.exists() else {"sources": {}, "cuts": {}, "control_content_equal": {}}
    for f in fields:
        fdir = pathlib.Path(frames.format(field=f))
        if f == "econ":
            if not pairs_econ:
                stop("CUT_INPUT_MISSING --pairs-econ (econ pairs_unified.csv)")
            pairs = pathlib.Path(pairs_econ)
        else:
            pairs = pathlib.Path(pairs_dir.format(field=f)) / f"pairs_none_{f}.parquet"
        src = {"pairs": pairs, "frame": fdir / f"p1_frame_{f}.csv", "p2": fdir / f"p2_becoming_{f}.csv"}
        miss = [str(v) for v in src.values() if not v.is_file()]
        if miss:
            stop(f"CUT_INPUT_MISSING {miss}")
        rep["sources"][f] = {k: str(v) for k, v in src.items()}
        for spec in specs:
            r = ac.build(f, spec, out, sources=src)
            if "skipped" in r:
                stop(f"CUT_SKIPPED {spec}/{f}: {r['skipped']}")
            rep["cuts"][f"{spec}_{f}"] = r
            print(f"cut {spec}/{f}: rows={r['rows']} pairs={r['pairs']} ties={r['ties']} events={r['events']} cut={r['cut_full']}")
    repf.parent.mkdir(parents=True, exist_ok=True)
    repf.write_text(json.dumps(rep, indent=1, default=str))
    return rep


def filter_p05(repo, *, frames, events_dir, map_dir, suffix, frames_out, report) -> dict:
    ff = _load(repo, "analysis/robustness/threshold_p05/filter_frames.py", "filter_frames")
    rc = ff.main(["--frames", str(frames), "--events-dir", str(events_dir), "--suffix", suffix,
                  "--map-dir", str(map_dir), "--out", str(frames_out)])
    if rc != 0:
        stop(f"FILTER_RC {rc}")
    rep = json.loads((pathlib.Path(frames_out) / "filter_report.json").read_text(encoding="utf-8"))
    no_map = [k for k, v in rep["frames"].items() if isinstance(v, str)]
    if no_map:
        stop(f"FILTER_NO_MAP {no_map}: every field needs its proven afar_event_map in {map_dir}")
    pathlib.Path(report).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pathlib.Path(frames_out) / "filter_report.json", report)
    return rep


def copy_cuts(repo, *, refs, out) -> list[str]:
    cfg = json.loads((pathlib.Path(repo) / "config/r1/robustness_r1.json").read_text(encoding="utf-8"))["golds"]
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    done = []
    for f in FIELDS:
        for spec, key in (("pos", "P3pos"), ("med", "P3med")):
            src = pathlib.Path(refs) / f"{cfg[key].format(field=f)}.json"
            if not src.is_file():
                stop(f"CUT_REF_MISSING {src}")
            lab = json.loads(src.read_text(encoding="utf-8")).get("label")
            if lab != f"P3cut_{spec}_{f}":
                stop(f"CUT_REF_LABEL {src}: label {lab!r} != P3cut_{spec}_{f}")
            shutil.copyfile(src, out / f"P3cut_{spec}_{f}.json")
            done.append(f"P3cut_{spec}_{f}")
    return done


# ---------------------------------------------------------------------------------------------
# nocentre-report
# ---------------------------------------------------------------------------------------------

def p1_population(frame_csv) -> dict:
    """Relations = distinct (incumbent_person_id, event_id) of a Panel 1 frame; persons = incumbents.
    (October's nocentre report: relations_variant 2361 / persons_variant 330 == its p1_frame relations_new /
    persons_new for chemistry.)"""
    rels, persons, events = set(), set(), set()
    with open(frame_csv, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rels.add((r["incumbent_person_id"], r["event_id"]))
            persons.add(r["incumbent_person_id"])
            events.add(r["event_id"])
    return {"relations": rels, "persons": persons, "events": events}


def _cell_status(j) -> str:
    if j.get("status") not in (None, "OK"):
        return str(j["status"])
    ch = j.get("channels")
    if isinstance(ch, dict) and ch.get("union", {}).get("status") not in (None, "OK"):
        return f"union {ch['union']['status']}"
    for k in ("pair_cluster", "event_cluster"):
        if isinstance(j.get(k), dict) and j[k].get("status") not in (None, "OK"):
            return f"{k} {j[k]['status']}"
    return "OK"


def nocentre_report(repo, *, rob, canon_frames, variant, fields, out) -> dict:
    repo, rob = pathlib.Path(repo).resolve(), pathlib.Path(rob).resolve()
    rep = {"group": "nocentre (R1 M)", "design": "chemistry/math_stats frames rebuilt on the incfel roster "
           "(chemmath_m.py --roster-variant incfel); cells by the verbatim drivers", "population": {},
           "cells": {}, "stops": []}
    for f in fields:
        c = p1_population(pathlib.Path(canon_frames) / f"p1_frame_{f}.csv")
        v = p1_population(pathlib.Path(variant) / f"frames_{f}" / f"p1_frame_{f}.csv")
        rep["population"][f] = {"relationships": {
            "relations_canon": len(c["relations"]), "relations_variant": len(v["relations"]),
            "persons_canon": len(c["persons"]), "persons_variant": len(v["persons"]),
            "persons_removed": len(c["persons"] - v["persons"]), "persons_added": len(v["persons"] - c["persons"]),
            "events_canon": len(c["events"]), "events_variant": len(v["events"])}}
        for lab in (f"P1nc_{f}", f"P2nc_{f}", f"P3nc_pos_{f}_A_far"):
            p = rob / "nocentre" / "estimates" / f"{lab}.json"
            if not p.is_file():
                rep["cells"][lab] = {"status": "MISSING"}
                rep["stops"].append(f"{lab} missing")
                continue
            st = _cell_status(json.loads(p.read_text(encoding="utf-8")))
            rel = p.relative_to(repo).as_posix() if p.is_relative_to(repo) else str(p)
            rep["cells"][lab] = {"label": lab, "status": st, "json": rel, "json_sha256": sha(p)}
            if st != "OK":
                rep["stops"].append(f"{lab} {st}")
    rep["status"] = "DONE" if not rep["stops"] else "WITH_STOPS"
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(out).write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
    return rep


# ---------------------------------------------------------------------------------------------
# manifest / report
# ---------------------------------------------------------------------------------------------

def manifest(repo, root) -> list[str]:
    wm = _load(repo, "tools/write_manifest.py", "write_manifest")
    done = []
    for d in sorted(p for p in pathlib.Path(root).iterdir() if p.is_dir()):
        n = wm.write(d)
        done.append(f"{d.name}:{n}")
    print("MANIFESTS", " ".join(done))
    return done


def report(repo, *, root, units_out, out, summary) -> dict:
    repo, root = pathlib.Path(repo).resolve(), pathlib.Path(root).resolve()
    reports = sorted(set(glob.glob(os.path.join(units_out, "units_report_*.json")) +
                         glob.glob(os.path.join(units_out, "*", "units_report_*.json"))))
    groups, est_failed, problems = {}, {}, []
    for f in reports:
        j = json.loads(pathlib.Path(f).read_text(encoding="utf-8"))
        groups[j["group"]] = {"report": f, "sha256": sha(f), "exit": j["exit"], "counts": j["counts"]}
        for n, u in j["units"].items():
            if u["status"] == "ESTIMATE_FAILED":
                est_failed[n] = u.get("detail", "")
            elif u["status"] not in ("OK", "EQUAL"):
                problems.append(f"{j['group']}/{n} {u['status']} {u.get('detail', '')}".strip())
    skip = {pathlib.Path(out).name, pathlib.Path(summary).name}
    files = {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*"))
             if p.is_file() and not (p.parent == root and p.name in skip)}
    cust = {"schema": "sar.r1.rob_custody.v1",
            "root": root.relative_to(repo).as_posix() if root.is_relative_to(repo) else str(root),
            "files": files, "units_reports": groups,
            "manifests": sorted(k for k in files if k.endswith("MANIFEST.sha256"))}
    pathlib.Path(out).write_text(json.dumps(cust, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    summ = {"schema": "sar.r1.rob_report.v1", "groups": {g: v["counts"] for g, v in groups.items()},
            "estimate_failed": est_failed, "problems": problems, "files": len(files)}
    pathlib.Path(summary).write_text(json.dumps(summ, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"ROB_REPORT files={len(files)} groups={sorted(groups)} estimate_failed={sorted(est_failed)} problems={len(problems)}")
    return cust


# ---------------------------------------------------------------------------------------------
# canon-pack (M review #9)
# ---------------------------------------------------------------------------------------------

CANON_BATCHES = ("cloud", "cloud_t5")
CANON_CUSTODY = "custody_cal2026-10.json"


def canon_rows(repo) -> list[dict]:
    """analysis/lib/canon_reads.tsv's product rows under cal/robustness, cal/cloud and cal/cloud_t5: the files of
    canon M that J1b produces (rel relative to the cal key, fnmatch wildcards allowed)."""
    rows, header = [], None
    for ln in (pathlib.Path(repo) / "analysis" / "lib" / "canon_reads.tsv").read_text(encoding="utf-8").splitlines():
        if not ln.strip() or ln.startswith("#"):
            continue
        cells = ln.split("\t")
        if header is None:
            header = cells
            continue
        r = dict(zip(header, cells))
        if r.get("key") == "cal" and r.get("kind") == "product" and r["rel"].split("/")[0] in ("robustness", *CANON_BATCHES):
            rows.append(r)
    return rows


def canon_pack(repo, *, root, out) -> dict:
    """The J1b products in October's cal-relative layout, as canon_layout.json's rows cal/robustness, cal/cloud and
    cal/cloud_t5 take them from work:prod/rob_post/canon/: <root> minus cloud/ and cloud_t5/ -> <out>/robustness,
    <root>/cloud -> <out>/cloud, <root>/cloud_t5 -> <out>/cloud_t5. Per batch, October's custody record name
    custody_cal2026-10.json {ok, problems, fetch_sha256}: fetch_sha256 = rob_custody.json's sha256 of every file
    under <batch>/fetch/, keyed relative to fetch/ as October's (the key the paper ledgers' custody_pinned uses),
    each re-checked on the copied bytes. Never overwrites; STOPs on a missing source, a fetch file rob_custody.json
    does not pin or whose bytes differ, or a canon_reads product row with no file."""
    root, out = pathlib.Path(root).resolve(), pathlib.Path(out)
    if out.exists() and any(out.iterdir()):
        stop(f"CANON_OUT_EXISTS {out}")
    cust_p = root / "rob_custody.json"
    if not cust_p.is_file():
        stop(f"CANON_NO_CUSTODY {cust_p} (the report unit runs first)")
    pinned = json.loads(cust_p.read_text(encoding="utf-8"))["files"]
    for b in CANON_BATCHES:
        if not (root / b).is_dir():
            stop(f"CANON_SOURCE_MISSING {root / b}")
    out.mkdir(parents=True, exist_ok=True)
    shutil.copytree(root, out / "robustness", copy_function=shutil.copyfile,
                    ignore=lambda d, names: [n for n in names if n in CANON_BATCHES and pathlib.Path(d).resolve() == root])
    rec = {}
    for b in CANON_BATCHES:
        shutil.copytree(root / b, out / b, copy_function=shutil.copyfile)
        pre, fetch_dir = f"{b}/fetch/", out / b / "fetch"
        fetch = {k[len(pre):]: v for k, v in sorted(pinned.items()) if k.startswith(pre)}
        on_disk = sorted(p.relative_to(fetch_dir).as_posix() for p in fetch_dir.rglob("*") if p.is_file()) \
            if fetch_dir.is_dir() else []
        problems = [f"{b}/fetch/{k} not in rob_custody.json" for k in on_disk if k not in fetch]
        problems += [f"{b}/fetch/{k} differs from rob_custody.json" for k, v in fetch.items()
                     if not (fetch_dir / k).is_file() or sha(fetch_dir / k) != v]
        if problems:
            stop(f"CANON_CUSTODY {problems[:10]}")
        body = {"schema": "sar.r1.rob_canon_custody.v1", "task": f"r1 J1b robustness batch {b} - custody (rob_post canon-pack)",
                "ok": True, "problems": [], "batch": b, "source": "rob_custody.json (sha256 of every file under fetch/)",
                "fetch_sha256": fetch}
        (out / b / CANON_CUSTODY).write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        rec[b] = len(fetch)
    missing = sorted(r["rel"] for r in canon_rows(repo) if not glob.glob(str(out / r["rel"])))
    if missing:
        stop(f"CANON_PRODUCT_MISSING {missing[:10]}")
    print(f"CANON_PACK_OK {out} custody {rec}")
    return rec


# ---------------------------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 robustness post steps")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def sp(name, *req, opt=()):
        p = sub.add_parser(name)
        p.add_argument("--repo", required=True)
        for k in req:
            p.add_argument(k, required=True)
        for k in opt:
            p.add_argument(k, default=None)
        return p

    sp("loeo-rank", "--loeo", "--ledger", "--canon", "--out", opt=("--frame",))
    sp("cut-grid", "--est", "--frames", "--build", "--out")
    sp("perm-summary", "--units-out", "--dest", opt=("--labels", "--B"))
    sp("null-merge", "--slices", "--label", "--nsim", "--out")
    sp("build-cuts", "--frames", "--pairs-dir", "--specs", "--fields", "--out", "--report", opt=("--pairs-econ",))
    sp("filter-p05", "--frames", "--events-dir", "--map-dir", "--suffix", "--frames-out", "--report")
    sp("copy-cuts", "--refs", "--out")
    sp("nocentre-report", "--rob", "--canon-frames", "--variant", "--fields", "--out")
    sp("manifest", "--root")
    sp("report", "--root", "--units-out", "--out", "--summary")
    sp("canon-pack", "--root", "--out")
    a = ap.parse_args(argv)
    if a.cmd == "loeo-rank":
        loeo_rank(a.loeo, a.ledger, a.canon, a.out, a.frame)
    elif a.cmd == "cut-grid":
        cut_grid(a.est, a.frames, a.build, a.out)
    elif a.cmd == "perm-summary":
        perm_summary(a.repo, a.units_out, a.dest, labels=a.labels.split(",") if a.labels else None,
                     B=int(a.B) if a.B else None)
    elif a.cmd == "null-merge":
        null_merge(a.repo, a.slices, a.label, a.nsim, a.out)
    elif a.cmd == "build-cuts":
        build_cuts(a.repo, frames=a.frames, pairs_econ=a.pairs_econ, pairs_dir=a.pairs_dir,
                   specs=a.specs.split(","), fields=a.fields.split(","), out=a.out, report=a.report)
    elif a.cmd == "filter-p05":
        filter_p05(a.repo, frames=a.frames, events_dir=a.events_dir, map_dir=a.map_dir, suffix=a.suffix,
                   frames_out=a.frames_out, report=a.report)
    elif a.cmd == "copy-cuts":
        copy_cuts(a.repo, refs=a.refs, out=a.out)
    elif a.cmd == "nocentre-report":
        r = nocentre_report(a.repo, rob=a.rob, canon_frames=a.canon_frames, variant=a.variant,
                            fields=a.fields.split(","), out=a.out)
        if r["stops"]:
            print(f"NOCENTRE_REPORT WITH_STOPS {r['stops']}")
    elif a.cmd == "manifest":
        manifest(a.repo, a.root)
    elif a.cmd == "report":
        report(a.repo, root=a.root, units_out=a.units_out, out=a.out, summary=a.summary)
    elif a.cmd == "canon-pack":
        canon_pack(a.repo, root=a.root, out=a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
