#!/usr/bin/env python3
"""RK6b (EC2 only): own-discipline ranking for every candidate, after two gates.

Same machine as the recovered RK1 script (r1/recovered/rk1/payload/rk1.py): the repo's production
ranking (restake_equiv._stats + run_screening._POOL_SQL) on an aw table built with
run_caliber.restake_with_adds' SQL. Order - each gate stops the run (RESULT.txt = GATE_FAIL):
  G1   control: the 187 October stars, production calls, on their production extraction (econ: the
       11-school table; chemistry/maths: the 07-05 table) equal October to 4 dp, as in RK1.
  GEQ  every request, pass A on the 11-school table, equals RK6a's ranks_11_A.csv row field by field,
       so this script ranks exactly as rk1.py did.
  OWN  the own-discipline ranking under the author's signed ruling (rulings_p1.json), on the pass-B
       cleaned table (prior cleaning + paper checks + id merges).
  C    the all-field rank on the same pass-B cleaned table (flips pct_C / in_C), for people a web check
       found to work in the discipline although OpenAlex labels their papers otherwise (P2 sign-off, 2026-10-12).
Writes ranks_A.csv, ranks_own.csv, ranks_C.csv, flips.csv, rk6b_report.json, summary.json, RESULT.txt.
Env: RK_REPO, RK_IN, RK_OUT, SAR_SSD_ROOT. Runs only on an R1 instance ($SAR_HOST), from the copy
/work/rk6b_rank.py: under pipeline/ it would trip paths.refuse_unstaged_in_place_run().
"""
from __future__ import annotations

import collections
import csv
import json
import os
import pathlib
import sys
import time

AWS_HOSTS = ("ec2-r1-test", "ec2-r1")
#: the paper-pinned own-field codes (analysis/paper/ledger_new_2026_10.py:43)
FIELD_CODE = {"econ": "20", "chemistry": "16", "math_stats": "26"}
#: econ may be narrowed to subfield 2002 (pipeline/contracts/redlines.yaml:94-99) if the author so rules
ALLOWED_CODES = {"econ": {"20", "2002"}, "chemistry": {"16"}, "math_stats": {"26"}}
SCOPES = ("star_only", "star_and_pool")
AGE_BASES = ("all", "own")
COMPARE = ("stock", "cell", "cell_n", "aage", "pct", "pass_p10", "note")
RFP_SRC = "FROM (SELECT DISTINCT aid, yr FROM aw WHERE yr <= {Y}))"


def load_rulings(p) -> dict:
    r = json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
    own = r.get("own_field") or {}
    codes = own.get("field_code") or {}
    errs = []
    if r.get("schema") != "sar.r1.rulings_p1.v1":
        errs.append("schema")
    if not str(r.get("decided", "")).strip():
        errs.append("decided is empty: the author has not signed")
    if own.get("scope") not in SCOPES:
        errs.append(f"scope {own.get('scope')!r}")
    if own.get("age_basis") not in AGE_BASES:
        errs.append(f"age_basis {own.get('age_basis')!r}")
    if set(codes) != set(ALLOWED_CODES) or any(codes[f] not in ALLOWED_CODES[f] for f in ALLOWED_CODES):
        errs.append(f"field_code {codes!r} is not an allowed choice")
    if errs:
        raise SystemExit("rulings_p1.json refused: " + "; ".join(errs))
    return own


def own_pred(code, col="sf") -> str:
    leaf = f"regexp_replace(CAST({col} AS VARCHAR), '^.*/', '')"
    return f"({col} IS NOT NULL AND length({leaf}) = 4 AND {leaf} LIKE '{code}%')"


def own_pool_sql(pool_sql, age_basis) -> str:
    if age_basis == "own":
        return pool_sql
    if pool_sql.count(RFP_SRC) != 1:
        raise RuntimeError("_POOL_SQL changed: its first-publication subquery is not where RK6b expects it")
    return pool_sql.replace(RFP_SRC, RFP_SRC.replace("FROM aw ", "FROM aw_all "))


def build_aw(con, table, drops, adds) -> None:
    """run_caliber.restake_with_adds (run_caliber.py:162-172), the same SQL, into `table`."""
    con.execute("CREATE OR REPLACE TEMP TABLE dropt(aid VARCHAR, wid VARCHAR)")
    if drops:
        con.executemany("INSERT INTO dropt VALUES (?,?)", sorted(drops))
    con.execute("CREATE OR REPLACE TEMP TABLE addt(aid VARCHAR, wid VARCHAR)")
    if adds:
        con.executemany("INSERT INTO addt VALUES (?,?)", sorted(set(adds)))
    con.execute(f"""CREATE OR REPLACE TEMP TABLE {table} AS
        SELECT aid, yr, c, sf FROM aw_raw r
        WHERE NOT EXISTS (SELECT 1 FROM dropt d WHERE d.aid=r.aid AND d.wid=r.wid)
        UNION ALL
        SELECT DISTINCT a.aid, w.yr, w.c, w.sf
        FROM addt a JOIN (SELECT DISTINCT wid, yr, c, sf FROM aw_raw) w ON w.wid = a.wid
        WHERE NOT EXISTS (SELECT 1 FROM aw_raw r WHERE r.aid=a.aid AND r.wid=a.wid)""")


def build_own_aw(con, code, scope, cand_ids) -> None:
    """`aw` for one field: star_and_pool keeps own-field rows for everyone; star_only removes only the
    candidates' other-field rows. `aw_all` (the cleaned table) feeds the age when age_basis = all."""
    pred = own_pred(code)
    con.execute("CREATE OR REPLACE TEMP TABLE aw_all AS SELECT * FROM aw_clean")
    if scope == "star_and_pool":
        con.execute(f"CREATE OR REPLACE TEMP TABLE aw AS SELECT * FROM aw_clean WHERE {pred}")
    elif scope == "star_only":
        con.execute("CREATE OR REPLACE TEMP TABLE candt(aid VARCHAR)")
        con.executemany("INSERT INTO candt VALUES (?)", [(a,) for a in sorted(cand_ids)])
        con.execute(f"CREATE OR REPLACE TEMP TABLE aw AS SELECT * FROM aw_clean WHERE NOT (aid IN (SELECT aid FROM candt) AND NOT {pred})")
    else:
        raise ValueError(f"unknown scope {scope!r}")


def use_clean_all_fields(con) -> None:
    """Pass C: `aw` = the pass-B cleaned table with every field. The all-field rank of people whose
    pre-arrival papers carry other fields' labels but whose research a web check found mainly in the
    discipline (P2 sign-off 2026-10-12: verified cases are included directly), on the same cleaning as the own-field rank."""
    con.execute("CREATE OR REPLACE TEMP TABLE aw AS SELECT * FROM aw_clean")


def rank(con, cands, label, re_, L, pool_sql, ovr_all) -> list:
    """rk1.py's rank(): production _stats in rounds, so no author id appears twice in one call."""
    res, todo, rnd = [], list(cands), 0
    while todo:
        rnd += 1
        seen, this, later = set(), [], []
        for c in todo:
            (later if c["author_id"] in seen else this).append(c)
            seen.add(c["author_id"])
        econ_ids = {c["author_id"] for c in this if c["field"] == "econ"}
        out = re_._stats(con, this, f"{label} r{rnd}", L, pool_sql, overrides={k: v for k, v in ovr_all.items() if k not in econ_ids})
        for c in this:
            o = out[c["author_id"]]
            res.append({"key": c["key"], "author_id": c["author_id"], "field": c["field"], "arrival_true": c["arrival_true"],
                        "Y": int(c["arrival_true"]) - 1, "stock": o["stock"], "cell": o["cell"], "cell_n": o["cell_n"],
                        "aage": o["aage"], "pct": o["pct"], "pass_p10": o["pass_p10"], "note": o["note"]})
        todo = later
    return res


def pass_b_cleaning(con, reqs, drops) -> tuple:
    """rk1.py's pass-B extras (with its T:2675 edit): request exclusions, min_year cuts, id merges."""
    extra_drops, extra_adds = set(), set()
    for r in reqs:
        for a in r["ids"]:
            for w in r.get("exclude_wids", []):
                extra_drops.add((a, w))
        if r.get("min_year"):
            ids = ",".join(f"'{a}'" for a in r["ids"])
            for a, w in con.execute(f"SELECT aid, wid FROM aw_raw WHERE aid IN ({ids}) AND yr < {int(r['min_year'])}").fetchall():
                extra_drops.add((a, w))
        if len(r["ids"]) > 1:
            sec = ",".join(f"'{a}'" for a in r["ids"][1:])
            for s, w in con.execute(f"SELECT DISTINCT aid, wid FROM aw_raw WHERE aid IN ({sec})").fetchall():
                if (s, w) not in extra_drops and (s, w) not in drops:
                    extra_adds.add((r["ids"][0], w))
    return extra_drops, extra_adds


def control_gate(rows, ctrl, ext) -> list:
    exp = {(c["author_id"], int(c["arrival_true"])): c["expected_pct"] for c in ctrl if c["ext"] == ext}
    fails = []
    for x in rows:
        e = exp.get((x["author_id"], int(x["arrival_true"])), "missing")
        ok = (x["pct"] is None and e is None) or (x["pct"] is not None and isinstance(e, float) and abs(x["pct"] - e) < 5e-5)
        if not ok:
            fails.append(("G1", ext, x["author_id"], x["arrival_true"], e, x["pct"]))
    if len(rows) != len(exp):
        fails.append(("G1", ext, "count", len(rows), len(exp)))
    return fails


def as_cell(v) -> str:
    return "" if v is None else str(v)


def geq_gate(rows_a, rk6a, reqs, skipped=()) -> list:
    """Every RK6a request row must reappear unchanged, except people RK6b deliberately skipped (an id
    dispute in the paper checks) or re-ranked under corrected ids."""
    corrected = {q["key"] for q in reqs if q.get("id_corrected")}
    skipped = set(skipped)
    mine = {r["key"]: r for r in rows_a}
    fails = []
    for key, theirs in rk6a.items():
        parts = key.split("|")                          # field|person|Y<year>; a key without a person is never skipped
        if key.startswith("CONTROL|") or key in corrected or (len(parts) > 1 and parts[1] in skipped):
            continue
        r = mine.get(key)
        if r is None:
            fails.append(("GEQ", key, "missing in RK6b"))
            continue
        if r["author_id"] != theirs["author_id"]:
            fails.append(("GEQ", key, "author_id", theirs["author_id"], r["author_id"]))
            continue
        for f in COMPARE:
            if as_cell(r[f]) != theirs[f]:
                fails.append(("GEQ", key, f, theirs[f], as_cell(r[f])))
    fails += [("GEQ", k, "not in RK6a") for k in mine if k not in rk6a and k not in corrected]
    return fails


def make_flips(reqs, rows_a, rows_own, oct_in, oct_p05, verdict, p05, rows_c=None) -> list:
    A, O, C = {r["key"]: r for r in rows_a}, {r["key"]: r for r in rows_own}, {r["key"]: r for r in rows_c or []}
    out = []
    for q in reqs:
        a, o, c, arr = A.get(q["key"]), O.get(q["key"]), C.get(q["key"]), int(q["Y"]) + 1
        g0 = "G0" in q["src"].split("|")
        in_a = verdict(a, arr) if a else None
        in_o = verdict(o, arr) if o else None
        ref = (q["person"] in oct_in) if g0 else in_a
        flip = "unranked" if (in_o is None or ref is None) else ("none" if ref == in_o else ("in->out" if ref else "out->in"))
        out.append({"person_id": q["person"], "key": q["key"], "field": q["field"], "status": q["status"], "src": q["src"],
                    "arrival": arr, "pct_A": a["pct"] if a else None, "in_A": in_a,
                    "pct_own": o["pct"] if o else None, "cell_own": o["cell"] if o else None,
                    "cell_n_own": o["cell_n"] if o else None, "aage_own": o["aage"] if o else None,
                    "stock_own": o["stock"] if o else None, "in_own": in_o, "p05_own": p05(o, arr) if o else None,
                    "october_event": (q["person"] in oct_in) if g0 else None,
                    "october_p05": (q["person"] in oct_p05) if g0 else None,
                    "flip": flip, "flip_vs": "october" if g0 else "unfiltered",
                    "pct_C": c["pct"] if c else None, "in_C": verdict(c, arr) if c else None})
    return out


def october_sets(repo) -> tuple:
    cal = pathlib.Path(repo) / "data" / "cal2026-10"
    main_set, p05_set = set(), set()
    for field, col in (("econ", "star_id"), ("chemistry", "author_id"), ("math_stats", "author_id")):
        for suffix, target in (("", main_set), ("_p05", p05_set)):
            with open(cal / f"events_{field}_cal2026-10{suffix}.csv", encoding="utf-8", newline="") as fh:
                target.update(r[col] for r in csv.DictReader(fh))
    return main_set, p05_set


def write_rows(p, rows) -> None:
    if not rows:
        return
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def read_pairs(p) -> set:
    with open(p, encoding="utf-8", newline="") as f:
        return {(r["aid"], r["wid"]) for r in csv.DictReader(f)}


def setup_import_paths(repo) -> None:
    """Both caliber layers carry a run_caliber.py; only the 2026-10 one has pass_p05 (rk6b-01 crashed in
    make_flips), so the 2026-10 layer goes first, then 08-28 (caliber, cleaned_works, restake_equiv), then the repo."""
    repo = pathlib.Path(repo)
    for p in (repo, repo / "pipeline/stars/caliber_2026-08-28", repo / "pipeline/stars/caliber_2026-10"):
        while str(p) in sys.path:
            sys.path.remove(str(p))
        sys.path.insert(0, str(p))


def main() -> int:
    if os.environ.get("SAR_HOST", "").strip() not in AWS_HOSTS:
        raise SystemExit("R1 rule (design v3 §4): rk6b_rank.py runs only on an R1 AWS instance ($SAR_HOST)")
    repo, inp, out = (pathlib.Path(os.environ[k]) for k in ("RK_REPO", "RK_IN", "RK_OUT"))
    setup_import_paths(repo)
    import caliber                                     # noqa: PLC0415
    import run_caliber as rc                           # noqa: PLC0415
    from restake_econ11 import load_aw_raw_11          # noqa: PLC0415
    re_ = rc.restake_equiv
    L, pool_sql = re_._screening_modules()
    out.mkdir(parents=True, exist_ok=True)
    t0, log = time.time(), open(out / "rk6b.log", "a", encoding="utf-8")

    def say(m):
        line = f"[{time.time() - t0:7.0f}s] {m}"
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()
    rul = load_rulings(inp / "rulings_p1.json")
    drops, adds = read_pairs(inp / "drops.csv"), read_pairs(inp / "adds.csv")
    reqs = json.loads((inp / "requests.json").read_text(encoding="utf-8"))
    ctrl = json.loads((inp / "control.json").read_text(encoding="utf-8"))
    with open(inp / "rk6a_ranks_11_A.csv", encoding="utf-8", newline="") as fh:
        rk6a = {r["key"]: r for r in csv.DictReader(fh)}
    skipped = json.loads((inp / "skipped.json").read_text(encoding="utf-8"))
    ovr = rc.cleaned_works.first_pub_overrides()
    cands = [{"key": q["key"], "author_id": q["ids"][0], "field": q["field"], "arrival_true": q["Y"] + 1} for q in reqs]
    report, fails, flips = {"ruling": rul, "requests": len(reqs), "gates": {}}, [], []
    for ext, loader in (("0705", re_.load_aw_raw), ("11", load_aw_raw_11)):
        con = re_.connect(out / f"duck_{ext}")
        con.execute("PRAGMA threads=30")
        con.execute("PRAGMA memory_limit='200GB'")
        say(f"[{ext}] aw_raw {loader(con):,}")
        build_aw(con, "aw", drops, adds)
        cc = [{"key": "CONTROL|" + c["author_id"], "author_id": c["author_id"], "field": c["field"],
               "arrival_true": int(c["arrival_true"])} for c in ctrl if c["ext"] == ext]
        g1 = control_gate(rank(con, cc, f"{ext}-ctrl", re_, L, pool_sql, ovr), ctrl, ext)
        report["gates"][f"G1_{ext}"] = len(g1)
        fails += g1
        say(f"[{ext}] G1 fails {len(g1)}")
        if ext == "11" and not fails:
            rows_a = rank(con, cands, "11-A", re_, L, pool_sql, ovr)
            geq = geq_gate(rows_a, rk6a, reqs, skipped)
            report["gates"]["GEQ"] = len(geq)
            fails += geq
            say(f"[11] GEQ fails {len(geq)}")
            if not fails:
                xd, xa = pass_b_cleaning(con, reqs, drops)
                build_aw(con, "aw_clean", drops | xd, adds | xa)
                use_clean_all_fields(con)
                rows_c = rank(con, cands, "11-C", re_, L, pool_sql, ovr)
                rows_own = []
                for field, code in rul["field_code"].items():
                    fc = [c for c in cands if c["field"] == field]
                    if fc:
                        build_own_aw(con, code, rul["scope"], {c["author_id"] for c in fc})
                        rows_own += rank(con, fc, f"11-own-{field}", re_, L, own_pool_sql(pool_sql, rul["age_basis"]), ovr)
                write_rows(out / "ranks_A.csv", rows_a)
                write_rows(out / "ranks_own.csv", rows_own)
                write_rows(out / "ranks_C.csv", rows_c)
                oct_in, oct_p05 = october_sets(repo)
                flips = make_flips(reqs, rows_a, rows_own, oct_in, oct_p05,
                                   lambda r, arr: caliber.event_verdict(after_pass=r["pass_p10"], aage=r["aage"], arrival_true=arr),
                                   lambda r, arr: bool(rc.pass_p05(r, L)) and caliber.gate_age(r["aage"]) and caliber.in_window(arr),
                                   rows_c=rows_c)
                write_rows(out / "flips.csv", flips)
        con.close()
        if fails:
            break
    result = "OK" if not fails and len(flips) == len(reqs) else "GATE_FAIL"
    report.update({"fails": [list(map(str, f)) for f in fails[:200]], "secs": round(time.time() - t0),
                   "flips": dict(collections.Counter(f"{f['field']}|{f['flip_vs']}|{f['flip']}" for f in flips))})
    (out / "rk6b_report.json").write_text(json.dumps(report, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (out / "summary.json").write_text(json.dumps({"result": result, "gates": report["gates"], "flips": report["flips"],
                                                  "requests": len(reqs)}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "RESULT.txt").write_text(result + "\n", encoding="utf-8")
    say(f"RESULT {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
