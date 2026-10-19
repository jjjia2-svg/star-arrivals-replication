#!/usr/bin/env python3
"""72_restake_fnfix_stars.py — fix-up candidate stars: recompute the thresholds using the **true arrival year**, with works judged paper by paper as not the person's own removed

The ranking machinery reuses run_screening._POOL_SQL verbatim (same as 50_restake). Three fields:
  chemistry/maths-stats: candidate subfield = modal (same as the pool)
  economics: candidate subfield forced to 2002 (U4 roster-based rule, same as script 60_)
Input: data/fnfix_candidates_restake.csv (columns: author_id,name,field,school,arrival_true)
      verify/fnfix_work_level_calls.csv (optional; columns author_id,work_id,is_mine — works judged false are removed)
Output: data/fnfix_restake_2026-08-15.csv (before/after comparison: stock/cell/pct/pass_p10)
"""
import csv, os, sys
from collections import defaultdict
from pathlib import Path
import duckdb

# --- M3 port: repo path resolution (legacy hard-coded the author's machine) — config/paths.yaml ---
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents if p.name == "stars").parents[1]
if str(_sar_repo) not in _sar_sys.path:
    _sar_sys.path.append(str(_sar_repo))
from pipeline.lib.paths import (derived_root as _sar_derived_root,  # noqa: E402,F401
                                snapshot_root as _sar_snapshot_root,
                                ssd_root as _sar_ssd_root,
                                legacy_thesis as _sar_legacy_thesis,
                                require_readable as _sar_rd,
                                require_writable as _sar_rw,
                                output_target as _sar_out,
                                deferred_output_target as _sar_lazyout)
ROOT = str(_sar_rd(_sar_legacy_thesis()))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SSD = Path(str(_sar_rd(_sar_derived_root() / "u1_edges_full_2026-07-05")))
SCREEN = f"{ROOT}/v2_output/multidisc_2026-07-24/code/star_screening"
sys.path.insert(0, SCREEN)
import screening_lib as L                # noqa
from run_screening import _POOL_SQL      # noqa
ECON_SF = "2002"

cands = list(csv.DictReader(open(f"{BASE}/data/fnfix_candidates_restake.csv")))
calls_p = f"{BASE}/verify/fnfix_work_level_calls.csv"
drop = set()
if os.path.exists(calls_p):
    drop = {(r["author_id"], r["work_id"]) for r in csv.DictReader(open(calls_p))
            if r["is_mine"].strip().lower() == "false"}
print(f"[in] {len(cands)} candidates; {len(drop)} works dropped one by one", flush=True)

con = duckdb.connect(); con.execute("PRAGMA threads=6"); con.execute("PRAGMA memory_limit='12GB'")
os.makedirs(f"{BASE}/data/_duck_tmp", exist_ok=True)
con.execute(f"PRAGMA temp_directory='{BASE}/data/_duck_tmp'")
con.create_function("cbin", lambda a: L.cohort_bin(int(a)), ["INTEGER"], "VARCHAR")
ep = SSD.as_posix()
con.execute(f"""CREATE TEMP TABLE aw_raw AS
    SELECT e.author_id aid, e.work_id wid, w.publication_year yr, w.cited_by_count c, w.subfield_id sf
    FROM read_parquet('{ep}/authorship_edges/**/*.parquet') e
    JOIN read_parquet('{ep}/works/**/*.parquet') w ON e.work_id = w.work_id
    WHERE w.publication_year IS NOT NULL""")
print("[aw]", con.execute("SELECT count(*) FROM aw_raw").fetchone()[0], "rows", flush=True)


def stats(label):
    by_Y = defaultdict(list)
    for c in cands: by_Y[int(c["arrival_true"]) - 1].append(c)
    out = {}
    for i, Y in enumerate(sorted(by_Y), 1):
        con.execute(_POOL_SQL.format(Y=Y, GAP=L.ROBUST_FIRST_PUB_MAX_GAP))
        ids = ",".join(f"'{c['author_id']}'" for c in by_Y[Y])
        got = {r[0]: r for r in con.execute(
            f"SELECT aid, stock, subfield, age_bin, aage, rnk, cell_n FROM poolY WHERE aid IN ({ids})").fetchall()}
        need = [c["author_id"] for c in by_Y[Y] if c["field"] == "econ" and c["author_id"] in got
                and str(got[c["author_id"]][2]).rsplit("/", 1)[-1] != ECON_SF]
        if need:
            idn = ",".join(f"'{a}'" for a in need)
            for r in con.execute(f"""
                WITH me AS (SELECT aid, stock, age_bin, aage FROM poolY WHERE aid IN ({idn})),
                cell AS (SELECT age_bin, stock FROM poolY WHERE subfield='{ECON_SF}')
                SELECT me.aid, me.stock, '{ECON_SF}', me.age_bin, me.aage,
                       1 + (SELECT count(*) FROM cell c WHERE c.age_bin=me.age_bin AND c.stock>me.stock) rnk,
                       (SELECT count(*) FROM cell c WHERE c.age_bin=me.age_bin) + 1 cell_n
                FROM me""").fetchall():
                got[r[0]] = r
        for c in by_Y[Y]:
            r = got.get(c["author_id"])
            if not r:
                out[c["author_id"]] = {"stock": None, "cell": None, "aage": None, "rnk": None, "cell_n": None,
                                       "pct": None, "estimable": False, "pass_p10": False, "note": "not_in_pool"}
                continue
            _, stock, sub, ab, aage, rnk, cn = r
            pct = round(1 - rnk / cn, 4)
            out[c["author_id"]] = {"stock": int(stock), "cell": f"{str(sub).rsplit('/',1)[-1]}|{ab}", "aage": int(aage),
                                   "rnk": int(rnk), "cell_n": int(cn), "pct": pct,
                                   "estimable": cn >= L.CELL_MIN_N["floor"],
                                   "pass_p10": (pct >= 1 - L.P10) and cn >= L.CELL_MIN_N["floor"], "note": ""}
        print(f"  [{label}] Y={Y} ({i}/{len(by_Y)})", end="\r", flush=True)
    print(f"  [{label}] pool built, {len(by_Y)} years            ", flush=True)
    return out


con.execute("CREATE OR REPLACE TEMP TABLE aw AS SELECT aid, yr, c, sf FROM aw_raw")
before = stats("before")
con.execute("CREATE TEMP TABLE dropt(aid VARCHAR, wid VARCHAR)")
if drop: con.executemany("INSERT INTO dropt VALUES (?,?)", sorted(drop))
con.execute("""CREATE OR REPLACE TEMP TABLE aw AS
    SELECT aid, yr, c, sf FROM aw_raw r WHERE NOT EXISTS (SELECT 1 FROM dropt d WHERE d.aid=r.aid AND d.wid=r.wid)""")
after = stats("after") if drop else before

out = f"{BASE}/data/fnfix_restake_2026-08-15.csv"
with open(out, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["author_id", "name", "field", "school", "arrival_true", "before_stock", "before_cell", "before_pct",
                "before_pass", "after_stock", "after_cell", "after_cell_n", "after_pct", "after_pass", "note", "aage"])
    for c in cands:
        b, a = before[c["author_id"]], after[c["author_id"]]
        w.writerow([c["author_id"], c["name"], c["field"], c["school"], c["arrival_true"], b["stock"], b["cell"], b["pct"],
                    b["pass_p10"], a["stock"], a["cell"], a["cell_n"], a["pct"], a["pass_p10"], a["note"] or b["note"], a["aage"]])
        print(f"  {c['author_id']} {c['name'][:26]:26s} {c['field'][:4]} arr={c['arrival_true']} "
              f"before {b['stock']} pct {b['pct']} → after {a['stock']} pct {a['pct']} pass={a['pass_p10']} {a['note']}")
print("→", out)
