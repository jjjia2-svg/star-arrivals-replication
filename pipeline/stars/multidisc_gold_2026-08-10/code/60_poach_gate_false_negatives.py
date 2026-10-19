#!/usr/bin/env python3
"""60_poach_gate_false_negatives.py — mining false negatives of the "overseas-poach gate" in three fields

Cause: a review found A5086383420 (Monash 2019) missed. Checked: the person passes the citation gate (99.86th percentile) and the age gate,
but U4 judged is_foreign_poach=False — because OpenAlex backfilled the post-2019 Monash address onto works of
2016–2018 (even 2003), so "a clean AU record already exists in the 3 years before arrival" → judged a local move. This is a **data-source
defect that wrongly kills a real overseas poach**. Such false negatives cannot be identified in bulk by rule; candidates can only be checked one by one.

This script does step one: rerun the citation gate + age gate over **everyone on the rosters** of the three fields (reusing line for line
the ranking machinery of U4/run_screening), and list "passes the gates but is not in the existing event table" = the suspect pool,
handed downstream for a person-by-person check of the arrival year and the overseas origin.
Economics: candidate subfield forced to 2002 (U4 roster-based rule); chemistry/maths = modal subfield (screening rule).
Candidate arrival year = the earliest year_start on the roster (consistent with U4; may be changed after a web check).

Output: data/poach_fn_suspects_{econ,chemistry,math_stats}.csv
"""
import csv, json, os, sys
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
from run_screening import _POOL_SQL      # noqa  <- ranking machinery reused verbatim (modal subfield version)

con = duckdb.connect(); con.execute("PRAGMA threads=8"); con.execute("PRAGMA memory_limit='12GB'")
os.makedirs(f"{BASE}/data/_duck_tmp", exist_ok=True)
con.execute(f"PRAGMA temp_directory='{BASE}/data/_duck_tmp'")
con.create_function("cbin", lambda a: L.cohort_bin(int(a)), ["INTEGER"], "VARCHAR")
ep = SSD.as_posix()
con.execute(f"""CREATE TEMP TABLE aw AS
    SELECT e.author_id aid, w.publication_year yr, w.cited_by_count c, w.subfield_id sf
    FROM read_parquet('{ep}/authorship_edges/**/*.parquet') e
    JOIN read_parquet('{ep}/works/**/*.parquet') w ON e.work_id = w.work_id
    WHERE w.publication_year IS NOT NULL""")
print("[aw]", con.execute("SELECT count(*) FROM aw").fetchone()[0], "rows", flush=True)

# ---------- candidates: the rosters of the three fields ----------
ROSTERS = {
  "econ": ("v2_output/econ_roster_verify_2026-08-09/roster_clean_11school_verified.parquet", None),
  "chemistry": ("v2_output/multidisc_gold_2026-08-10/data/final/roster_gold_chemistry.parquet", None),
  "math_stats": ("v2_output/multidisc_gold_2026-08-10/data/final/roster_gold_math_stats.parquet", None),
}
EVENTS = {
  "econ": {r["star_id"] for r in csv.DictReader(open(f"{ROOT}/v2_output/frame_dept_2026-07-31/event_ledger_79_2026-07-27.csv"))},
  "chemistry": {r["author_id"] for r in csv.DictReader(open(f"{BASE}/data/events_chemistry_final_2026-08-13.csv"))},
  "math_stats": {r["author_id"] for r in csv.DictReader(open(f"{BASE}/data/events_math_stats_final_2026-08-13.csv"))},
}
ECON_SF = "2002"   # U4 roster-based rule; the subfield column in the pool holds bare codes

def econ_pool_sql(Y):
    """U4 rule: candidate subfield forced to 2002; pool = whole-pool modal subfield; the rest same as _POOL_SQL"""
    return _POOL_SQL.format(Y=Y, GAP=L.ROBUST_FIRST_PUB_MAX_GAP)

for field, (rp, _) in ROSTERS.items():
    cand = con.execute(f"""SELECT author_id, min(year_start) arr, string_agg(DISTINCT dept_key, ';') depts
        FROM read_parquet('{ROOT}/{rp}') WHERE author_id IS NOT NULL GROUP BY 1""").fetchall()
    by_Y = defaultdict(list)
    for aid, arr, depts in cand:
        by_Y[int(arr) - 1].append((aid, int(arr), depts))
    out = []
    for i, Y in enumerate(sorted(by_Y), 1):
        if Y < 1990: continue
        con.execute(econ_pool_sql(Y))
        ids = ",".join(f"'{a}'" for a, _, _ in by_Y[Y])
        got = {r[0]: r for r in con.execute(
            f"SELECT aid, stock, subfield, age_bin, aage, rnk, cell_n FROM poolY WHERE aid IN ({ids})").fetchall()}
        # Economics: candidate subfield forced to 2002 → if modal≠2002, re-rank within the 2002 cell; simplification: recompute the rank using the 2002 cell
        if field == "econ":
            need = [a for a, _, _ in by_Y[Y] if a in got and got[a][2] != ECON_SF]
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
        for aid, arr, depts in by_Y[Y]:
            r = got.get(aid)
            if not r: continue
            _, stock, sub, ab, aage, rnk, cn = r
            pct = 1 - rnk / cn
            out.append({"author_id": aid, "field": field, "depts": depts, "arrival_roster": arr,
                        "stock": int(stock), "subfield": str(sub).rsplit("/",1)[-1], "age_bin": ab,
                        "academic_age": int(aage), "cell_n": int(cn), "pct": round(pct, 4),
                        "pass_p10": (pct >= 0.90 and cn >= 30 and aage >= 2),
                        "in_events": aid in EVENTS[field]})
        print(f"  [{field}] Y={Y} ({i}/{len(by_Y)})", end="\r", flush=True)
    sus = [o for o in out if o["pass_p10"] and not o["in_events"]]
    sus.sort(key=lambda o: -o["pct"])
    p = f"{BASE}/data/poach_fn_suspects_{field}.csv"
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(sus[0])) if sus else None
        if w: w.writeheader(); w.writerows(sus)
    print(f"\n[{field}] on roster {len(cand)} people → pass gates ① and ② but not in the event table: {len(sus)} people → {os.path.basename(p)}")
