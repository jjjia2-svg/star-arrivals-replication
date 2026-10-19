#!/usr/bin/env python3
"""R1 J0-MEAS.3e dossiers (job kind 'dossier'; runs on AWS). No ranking here.

Who gets a dossier:
  * every ACCEPT row of add_list_r1.json with no prior per-paper check. A row counts as checked when
    it has both R1 rounds (paper_checks/round1 + round2: 'r1_rounds'), or when RK4's two-round
    mark+check cleaning (wf_acd28146) covered it: one of its ids is in a request of the replayed
    rk4in/requests.json whose sweep key has an entry in papers/cleaning_final.json ('rk4_two_round').
    RK4's `cleaning` flag alone is not a check (it is also set for a bare id merge). The rest: 'no_check'.
  * the named targets of j0_dossier_targets.json (ids and reason codes, no names), always, whatever
    their prior check: h8_A5087235620, h10, u2_A5001177483, u2_A5008470795. A u2_* target takes every id of its U2
    person (u2_person_map_11school), so the ids nobody checked are listed too.
What a dossier holds: the person's works up to Y = arrival - 1 on the 11-school extraction (the
table rk6b ranks on), each with title, citations, subfield and whether an earlier check already
excluded it (round1/round2/extra files, the 10-11 adjudication, RK4's exclusions and min_year cut).
Y comes from the add list, or for the 187 from RK6a's ranks_11_A.csv.
Writes out/dossiers/<pid>.json, out/targets.csv, out/summary.json (counts, codes and ids only) and
RESULT.txt (OK / DOSSIER_FAIL when a target has no single Y). Runs only on an R1 instance
($SAR_HOST), from the copy /work/dossier_pack.py (under pipeline/ the in-place guard would stop it).
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import pathlib
import re
import sys

AWS_HOSTS = ("ec2-r1-test", "ec2-r1")
TARGETS_SCHEMA = "sar.r1.dossier_targets.v1"
REASONS = ("h8_A5087235620", "h10", "u2_A5001177483", "u2_A5008470795")
U2_REASONS = {"u2_A5001177483", "u2_A5008470795"}
CHECKS = ("two_round", "identity", "material", "coverage")
NAMED_KEYS = {"person_id", "reason", "check", "ids", "flag_wids"}
#: where the replayed derivation (recder) may sit under the pulled folder
DERIVED_PREFIXES = ("", "rk1", "derived/rk1")
U2_MAP_DIR = "u2_person_map_11school_2026-07-16/person_map"   # require_readable() guards directories only
WID = re.compile(r"W\d+")
AID = re.compile(r"A\d{6,}")


def check_named(obj) -> list:
    """The committed target list: ids and codes only. Anything else (a name, a note) is refused."""
    if not isinstance(obj, dict) or obj.get("schema") != TARGETS_SCHEMA or not isinstance(obj.get("targets"), list):
        raise SystemExit(f"j0_dossier_targets.json refused: schema is not {TARGETS_SCHEMA}")
    errs, seen = [], set()
    for t in obj["targets"]:
        pid = t.get("person_id", "")
        extra = sorted(set(t) - NAMED_KEYS)
        if extra:
            errs.append(f"{pid}: unknown keys {extra} (ids and codes only, no name or note)")
        if not AID.fullmatch(str(pid)):
            errs.append(f"{pid!r}: not an OpenAlex author id")
        if t.get("reason") not in REASONS or t.get("check") not in CHECKS:
            errs.append(f"{pid}: reason {t.get('reason')!r} / check {t.get('check')!r}")
        bad = [x for x in t.get("ids", []) if not AID.fullmatch(str(x))] + \
              [w for w in t.get("flag_wids", []) if not WID.fullmatch(str(w))]
        if bad:
            errs.append(f"{pid}: malformed ids {bad[:5]}")
        if (pid, t.get("reason")) in seen:
            errs.append(f"{pid}: listed twice for {t.get('reason')}")
        seen.add((pid, t.get("reason")))
    if errs:
        raise SystemExit("j0_dossier_targets.json refused:\n  " + "\n  ".join(errs))
    return obj["targets"]


def load_named(p) -> list:
    return check_named(json.loads(pathlib.Path(p).read_text(encoding="utf-8")))


def _derived_file(derived_dir, rel) -> pathlib.Path:
    d = pathlib.Path(derived_dir)
    hits = [d / pre / rel for pre in DERIVED_PREFIXES if (d / pre / rel).is_file()]
    if len(hits) != 1:
        raise SystemExit(f"derived {rel}: {len(hits)} copies under the pulled recder folder (need exactly 1)")
    return hits[0]


def cleaning_keys(obj) -> set:
    """Sweep keys ('field|...') with an entry in RK4's cleaning_final.json: a dict keyed by sweep key, a
    list of entries carrying 'key', or either under the workflow's 'result'. Any other layout stops."""
    if isinstance(obj, dict):
        keys = {k for k in obj if "|" in k}
        if keys:
            return keys
        if "result" in obj:
            return cleaning_keys(obj["result"])
        lists = [v for v in obj.values() if isinstance(v, list)]
        return cleaning_keys(lists[0]) if len(lists) == 1 else set()
    if isinstance(obj, list):
        return {x["key"] for x in obj if isinstance(x, dict) and "|" in str(x.get("key", ""))}
    return set()


def load_rk4(derived_dir) -> tuple:
    """(RK4 requests, the sweep keys RK4's two-round cleaning covered)."""
    reqs = json.loads(_derived_file(derived_dir, "rk4in/requests.json").read_text(encoding="utf-8"))
    if not isinstance(reqs, list) or not all(isinstance(r, dict) and "key" in r for r in reqs):
        raise SystemExit("derived rk4in/requests.json: not a list of requests with a sweep key")
    keys = cleaning_keys(json.loads(_derived_file(derived_dir, "papers/cleaning_final.json").read_text(encoding="utf-8")))
    if not keys:
        raise SystemExit("derived papers/cleaning_final.json: no sweep keys found (unknown layout)")
    return reqs, keys


def _ids(row) -> list:
    pid = row["person_id"]
    return [pid] + [i for i in str(row.get("all_ids") or "").split("|") if i and i != pid]


def _rounds(paper_checks_dir) -> set:
    d = pathlib.Path(paper_checks_dir)
    return {p.stem for p in (d / "round1").glob("A*.json")} & {p.stem for p in (d / "round2").glob("A*.json")}


def _prior(pid, ids, rounds, rk4_ids) -> str:
    if pid in rounds:
        return "r1_rounds"
    return "rk4_two_round" if set(ids) & rk4_ids else "no_check"


def _rk4_checked_ids(reqs, keys) -> set:
    return {a for r in reqs if r["key"] in keys for a in r.get("ids") or []}


def classify(add_rows, paper_checks_dir, derived_dir) -> dict:
    """person_id -> r1_rounds / rk4_two_round / no_check, for every ACCEPT row."""
    reqs, keys = load_rk4(derived_dir)
    rounds, rk4_ids = _rounds(paper_checks_dir), _rk4_checked_ids(reqs, keys)
    return {r["person_id"]: _prior(r["person_id"], _ids(r), rounds, rk4_ids) for r in add_rows if r["verdict"] == "ACCEPT"}


def _read(p) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def prior_exclusions(paper_checks_dir, pid) -> set:
    """Works an earlier check already excluded for this person: (round 1 | round 2 missed) - round 2
    wrongly excluded, as load_paper_checks merges them, plus the extra file and the adjudications."""
    d = pathlib.Path(paper_checks_dir)
    r1, r2, x = _read(d / "round1" / f"{pid}.json"), _read(d / "round2" / f"{pid}.json"), _read(d / "extra" / f"{pid}.json")
    out = (set(r1.get("exclude_wids", [])) | set(r2.get("missed_wids", []))) - set(r2.get("wrongly_excluded_wids", []))
    out |= set(x.get("exclude_wids", []))
    for p in sorted(d.glob("adjudication_*.json")):
        out |= {w["wid"] for w in _read(p).get("works", []) if w.get("person_id") == pid and w.get("final") == "exclude"}
    return out


def _merge_ids(paper_checks_dir, pid) -> list:
    d = pathlib.Path(paper_checks_dir)
    r1, r2, x = _read(d / "round1" / f"{pid}.json"), _read(d / "round2" / f"{pid}.json"), _read(d / "extra" / f"{pid}.json")
    drop = set(r2.get("merge_ids_drop", []))
    return [m for m in dict.fromkeys([*r1.get("merge_ids", []), *r2.get("merge_ids_add", []), *x.get("merge_ids", [])])
            if m not in drop]


def targets(add_rows, flip_rows, paper_checks_dir, derived_dir, named) -> list:
    """The dossier list (no database, no writes). ACCEPT rows with no prior check, then every named
    target whatever its check; a named id must be one of the 187 or an add-list row."""
    reqs, keys = load_rk4(derived_dir)
    rounds, rk4_ids = _rounds(paper_checks_dir), _rk4_checked_ids(reqs, keys)
    adds = {r["person_id"]: r for r in add_rows if r["verdict"] == "ACCEPT"}
    flips = {r["person_id"]: r for r in flip_rows}
    out = {}

    def entry(pid, ids, row):
        t = out.get(pid)
        if t is None:
            arr = str(row.get("arrival_year") or "").strip()
            t = out[pid] = {"person_id": pid, "field": row.get("field", ""), "Y": int(arr) - 1 if arr else None,
                            "ids": [], "reasons": [], "checks": [], "prior_check": _prior(pid, ids, rounds, rk4_ids),
                            "flag_wids": []}
        t["ids"] += [i for i in ids if i not in t["ids"]]
        return t

    for pid, r in adds.items():
        if _prior(pid, _ids(r), rounds, rk4_ids) == "no_check":
            t = entry(pid, _ids(r), r)
            t["reasons"].append("accept_no_check")
            t["checks"].append("two_round")
    missing = []
    for n in named:
        pid = n["person_id"]
        row = adds.get(pid) or flips.get(pid)
        if row is None:
            missing.append(pid)
            continue
        t = entry(pid, (_ids(row) if pid in adds else [pid]) + list(n.get("ids", [])), row)
        t["reasons"].append(n["reason"])
        t["checks"].append(n["check"])
        t["flag_wids"] += [w for w in n.get("flag_wids", []) if w not in t["flag_wids"]]
    if missing:
        raise SystemExit(f"named targets in neither flips_r1.json nor the ACCEPT rows: {sorted(missing)}")
    for t in out.values():
        pid = t["person_id"]
        t["ids"] += [m for m in _merge_ids(paper_checks_dir, pid) if m not in t["ids"]]
        mine = [r for r in reqs if set(r.get("ids") or []) & set(t["ids"])]
        excl = prior_exclusions(paper_checks_dir, pid) | {w for r in mine for w in r.get("exclude_wids") or []}
        mins = {int(r["min_year"]) for r in mine if r.get("min_year")}
        t["excluded_wids"] = sorted(excl)
        t["min_year"] = next(iter(mins)) if len(mins) == 1 else None        # a conflict applies none (rk6_requests)
    return sorted(out.values(), key=lambda t: t["person_id"])


def works_for(con, ids, Y, excluded=(), min_year=None) -> list:
    """rk1's works dump for one person: aw_raw joined to work_text titles, yr <= Y, ordered by aid, yr."""
    con.execute("CREATE OR REPLACE TEMP TABLE dids(aid VARCHAR)")
    con.executemany("INSERT INTO dids VALUES (?)", [(a,) for a in dict.fromkeys(ids)])
    rows = con.execute("""SELECT r.wid, r.aid, r.yr, r.c, r.sf, t.title
        FROM (SELECT DISTINCT aid, wid, yr, c, sf FROM aw_raw WHERE aid IN (SELECT aid FROM dids) AND yr <= ?) r
        LEFT JOIN (SELECT work_id, min(title) title FROM work_text GROUP BY work_id) t ON t.work_id = r.wid
        ORDER BY r.aid, r.yr, r.wid""", [int(Y)]).fetchall()
    excluded = set(excluded)
    return [{"wid": w, "aid": a, "yr": int(y), "c": None if c is None else int(c), "sf": None if sf is None else str(sf),
             "title": title, "prior_excluded": w in excluded or (min_year is not None and int(y) < int(min_year))}
            for w, a, y, c, sf, title in rows]


def u2_ids(con, ids) -> list:
    """Every author id of the U2 persons that hold any of `ids` (table pm: author_id, person_id)."""
    con.execute("CREATE OR REPLACE TEMP TABLE dids(aid VARCHAR)")
    con.executemany("INSERT INTO dids VALUES (?)", [(a,) for a in dict.fromkeys(ids)])
    return [r[0] for r in con.execute("""SELECT DISTINCT author_id FROM pm WHERE person_id IN
        (SELECT person_id FROM pm WHERE author_id IN (SELECT aid FROM dids)) ORDER BY author_id""").fetchall()]


def rk6a_years(rk6a_dir) -> tuple:
    """person -> Y from RK6a's request keys (field|person|Y<year>); people with two Y are ambiguous."""
    ys = collections.defaultdict(set)
    p = pathlib.Path(rk6a_dir) / "ranks_11_A.csv"
    if p.is_file():
        with open(p, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                parts = r["key"].split("|")
                if not r["key"].startswith("CONTROL|") and len(parts) == 3 and parts[2].startswith("Y"):
                    ys[parts[1]].add(int(parts[2][1:]))
    return {k: next(iter(v)) for k, v in ys.items() if len(v) == 1}, {k for k, v in ys.items() if len(v) > 1}


def expand(con, tg, rk6a_dir) -> None:
    """Fill in Y (RK6a for the 187), the RK6a request ids, and every U2 id for the u2_* targets."""
    ys, _ambiguous = rk6a_years(rk6a_dir)
    pack = pathlib.Path(rk6a_dir) / "review_pack" / "works"
    for t in tg:
        pf = pack / f"{t['person_id']}.json"
        t["in_rk6a_pack"] = pf.is_file()
        if t["in_rk6a_pack"]:
            t["ids"] += [i for i in _read(pf).get("ids", []) if i not in t["ids"]]
        if t["Y"] is None:
            t["Y"] = ys.get(t["person_id"])
        known = list(t["ids"])
        if set(t["reasons"]) & U2_REASONS:
            t["ids"] += [i for i in u2_ids(con, known) if i not in t["ids"]]
        t["u2_extra_ids"] = [i for i in t["ids"] if i not in known]


def write_dossiers(con, tg, accept_classes, out) -> str:
    out = pathlib.Path(out)
    (out / "dossiers").mkdir(parents=True, exist_ok=True)
    rows, no_y = [], []
    for t in tg:
        if t["Y"] is None:
            no_y.append(t["person_id"])
            continue
        works = works_for(con, t["ids"], t["Y"], t["excluded_wids"], t["min_year"])
        have = {w["wid"] for w in works}
        (out / "dossiers" / f"{t['person_id']}.json").write_text(json.dumps({
            "schema": "sar.r1.dossier.v1", "person_id": t["person_id"], "field": t["field"], "ids": t["ids"],
            "u2_extra_ids": t["u2_extra_ids"], "Y": t["Y"], "reasons": t["reasons"], "checks": t["checks"],
            "prior_check": t["prior_check"], "flag_wids": t["flag_wids"], "works": works},
            indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        rows.append({"person_id": t["person_id"], "reasons": t["reasons"], "checks": t["checks"],
                     "prior_check": t["prior_check"], "Y": t["Y"], "n_ids": len(t["ids"]),
                     "n_u2_extra": len(t["u2_extra_ids"]), "n_works": len(works),
                     "n_prior_excluded": sum(w["prior_excluded"] for w in works),
                     "flag_wids_found": sum(w in have for w in t["flag_wids"]), "in_rk6a_pack": t["in_rk6a_pack"]})
    with open(out / "targets.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["person_id", "field", "Y", "reasons", "checks", "prior_check", "n_ids", "n_works",
                    "n_prior_excluded", "in_rk6a_pack"])
        by = {r["person_id"]: r for r in rows}
        for t in tg:
            r = by.get(t["person_id"], {})
            w.writerow([t["person_id"], t["field"], "" if t["Y"] is None else t["Y"], "|".join(t["reasons"]),
                        "|".join(t["checks"]), t["prior_check"], len(t["ids"]), r.get("n_works", ""),
                        r.get("n_prior_excluded", ""), t["in_rk6a_pack"]])
    result = "DOSSIER_FAIL" if no_y else "OK"
    (out / "summary.json").write_text(json.dumps({
        "result": result, "accept_classes": dict(accept_classes), "targets": len(tg),
        "by_reason": dict(collections.Counter(x for t in tg for x in t["reasons"])),
        "by_check": dict(collections.Counter(x for t in tg for x in t["checks"])),
        "no_y": sorted(no_y), "not_in_rk6a_pack": sorted(t["person_id"] for t in tg if not t["in_rk6a_pack"]),
        "no_works": sorted(r["person_id"] for r in rows if not r["n_works"]), "rows": rows},
        indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "RESULT.txt").write_text(result + "\n", encoding="utf-8")
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 J0-MEAS.3e dossiers")
    for name in ("--repo", "--targets", "--add-list", "--flips", "--paper-checks", "--derived", "--rk6a", "--out"):
        ap.add_argument(name, required=True, type=pathlib.Path)
    a = ap.parse_args(argv)
    if os.environ.get("SAR_HOST", "").strip() not in AWS_HOSTS:
        raise SystemExit("R1 rule (design v3 §4): dossier_pack.py runs only on an R1 AWS instance ($SAR_HOST)")
    named = load_named(a.targets)
    add_rows = json.loads(a.add_list.read_text(encoding="utf-8"))["rows"]
    flip_rows = json.loads(a.flips.read_text(encoding="utf-8"))["rows"]
    accept_classes = collections.Counter(classify(add_rows, a.paper_checks, a.derived).values())
    tg = targets(add_rows, flip_rows, a.paper_checks, a.derived, named)
    sys.path.insert(0, str(a.repo / "pipeline/aws/r1"))
    import rk6b_rank as rk                             # noqa: PLC0415
    rk.setup_import_paths(a.repo)
    import run_caliber as rc                           # noqa: PLC0415
    from restake_econ11 import ELEVEN, load_aw_raw_11  # noqa: PLC0415
    from pipeline.lib.paths import derived_root, require_readable   # noqa: PLC0415
    a.out.mkdir(parents=True, exist_ok=True)
    con = rc.restake_equiv.connect(a.out / "duck_11")
    con.execute("PRAGMA threads=30")
    con.execute("PRAGMA memory_limit='200GB'")
    print(f"aw_raw {load_aw_raw_11(con):,}", flush=True)
    pm = (pathlib.Path(str(require_readable(derived_root() / U2_MAP_DIR))) / "data.parquet").as_posix()
    con.execute(f"CREATE TEMP TABLE pm AS SELECT author_id, person_id FROM read_parquet('{pm}')")
    expand(con, tg, a.rk6a)
    con.execute("CREATE OR REPLACE TEMP TABLE dids(aid VARCHAR)")
    con.executemany("INSERT INTO dids VALUES (?)", [(i,) for i in sorted({i for t in tg for i in t["ids"]})])
    con.execute("CREATE TEMP TABLE tw AS SELECT DISTINCT wid FROM aw_raw WHERE aid IN (SELECT aid FROM dids)")
    wt =pathlib.Path(str(require_readable(derived_root() / ELEVEN / "work_text"))).as_posix()
    con.execute(f"""CREATE TEMP TABLE work_text AS SELECT * FROM (
        SELECT regexp_replace(CAST(work_id AS VARCHAR), '^.*/', '') work_id, title
        FROM read_parquet('{wt}/**/*.parquet')) WHERE work_id IN (SELECT wid FROM tw)""")
    result = write_dossiers(con, tg, accept_classes, a.out)
    con.close()
    print(result)
    return 0 if result == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
