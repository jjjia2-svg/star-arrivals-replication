#!/usr/bin/env python3
"""00b_prep_roster_variants.py — split the roster into tiers by rank_tag + add the 2 new events

Defect fixed: the first frame build treated **all** 1,550 rows of the gold parquet as the population,
without filtering by rank_tag. That table is the full manually verified table and holds three tiers:
    include   652 rows / 627 people   — full-time, lecturer level and above (what the eligibility gate requires)
    ambiguous 451 rows / 448 people   — cannot be classified; the normalize script says explicitly "to be reviewed manually, not decided in code"
    exclude   447 rows / 440 people   — postdocs/students/emeriti/part-time/visiting/technical/administrative (to be dropped by the gate)
The first build also put exclude into the population -> the population did not match the economics
rules, so the frame had to be rebuilt.

This script produces two population tiers; all other inputs are untouched:
    inc     = include                     <- main specification (aligned with the eligibility gate)
    incamb  = include ∪ ambiguous         <- robustness (membership of ambiguous left to a manual decision)

Merges the rosters of the two newly collected events (A5109260299@Monash 2006 / A5100398634@Sydney 2018):
  - same yardstick as the 41 events: rank_tag from the same classify(); where there is no manually
    verified year range, both start and end year are the snapshot year
  - only rows with an author_id are kept
  - the 5 ids already corrected by the manual cross-check (human_xcheck column) use the corrected id

Run: python3 00b_prep_roster_variants.py
"""
import csv
import json
import os
from collections import Counter, defaultdict

import duckdb

# --- M3 port: repo path resolution (legacy hard-coded the author's machine) — config/paths.yaml ---
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents if p.name == "rosters").parents[1]
if str(_sar_repo) not in _sar_sys.path:
    _sar_sys.path.append(str(_sar_repo))
from pipeline.lib.paths import (derived_root as _sar_derived_root,  # noqa: E402,F401
                                snapshot_root as _sar_snapshot_root,
                                ssd_root as _sar_ssd_root,
                                legacy_thesis as _sar_legacy_thesis,
                                require_readable as _sar_rd,
                                require_writable as _sar_rw,
                                output_target as _sar_out,
                                deferred_output_target as _sar_lazyout,
                                staged_run_dir as _sar_staged)
ROOT = str(_sar_staged(_sar_legacy_thesis()))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLD_ROSTER = f"{ROOT}/v2_output/multidisc_roster_econ_grade_2026-08-09/roster_clean_chemmath_verified.parquet"
COLLECT = f"{ROOT}/v2_output/multidisc_roster_econ_grade_2026-08-09/collect"
OUT = f"{BASE}/data"

NEW_EVENTS = {
    "A5109260299:monash": {"dept_key": "monash_chem", "school": "monash", "field": "chemistry"},
    "A5100398634:sydney": {"dept_key": "sydney_chem", "school": "sydney", "field": "chemistry"},
}
VARIANTS = {"inc": {"include"}, "incamb": {"include", "ambiguous"}}

con = duckdb.connect()
rep = {"date": "2026-08-10", "variants": {}, "new_events": {}}

# ---------- 1. Read the two newly collected events and turn them into roster spells (start/end year = snapshot year, same rule as the 41 events) ----------
new_rows = []
for ev, meta in NEW_EVENTS.items():
    p = f"{COLLECT}/{ev}/openalex_match_{ev}.csv"
    rows = list(csv.DictReader(open(p)))
    kept, tags = [], Counter()
    for r in rows:
        tags[r["rank_tag"]] += 1
        aid = (r.get("author_id") or "").strip()
        if not aid or aid.startswith("api_error"):
            continue
        y = int(str(r["snapshot_ts"])[:4])
        kept.append({"dept_key": meta["dept_key"], "school": meta["school"],
                     "author_id": aid, "year_start": y, "year_end": y,
                     "field": meta["field"], "rank_tag": r["rank_tag"],
                     "event_keys": ev, "src": "collect_2026-08-10"})
    # the same person in several snapshots -> merge into one spell
    merged = {}
    for r in kept:
        k = (r["dept_key"], r["author_id"], r["rank_tag"])
        if k in merged:
            merged[k]["year_start"] = min(merged[k]["year_start"], r["year_start"])
            merged[k]["year_end"] = max(merged[k]["year_end"], r["year_end"])
        else:
            merged[k] = r
    new_rows += list(merged.values())
    rep["new_events"][ev] = {"rows_collected": len(rows), "rank_tags": dict(tags),
                             "with_author_id": len(kept), "spells_after_merge": len(merged)}
    print(f"[new] {ev}: collected {len(rows)} rows {dict(tags)} → with id {len(kept)} → spells {len(merged)}")

# ---------- 2. Two population tiers ----------
base = con.execute(f"""SELECT dept_key, school, author_id,
    CAST(year_start AS BIGINT) year_start, CAST(year_end AS BIGINT) year_end,
    field, rank_tag FROM read_parquet('{GOLD_ROSTER}')
    WHERE author_id IS NOT NULL AND author_id <> ''""").df()
print(f"[base] full gold table {len(base)} rows / {base.author_id.nunique()} people "
      f"{dict(Counter(base.rank_tag))}")

for var, tags_ok in VARIANTS.items():
    d = f"{OUT}/{var}"
    os.makedirs(d, exist_ok=True)
    sub = base[base.rank_tag.isin(tags_ok)]
    extra = [r for r in new_rows if r["rank_tag"] in tags_ok]
    con.register("base_sub", sub[["dept_key", "school", "author_id", "year_start", "year_end", "field"]])
    import pandas as pd
    ex_df = pd.DataFrame([{k: r[k] for k in ("dept_key", "school", "author_id",
                                             "year_start", "year_end", "field")}
                          for r in extra]) if extra else None
    if ex_df is not None:
        con.register("extra_sub", ex_df)
        sql_all = "SELECT * FROM base_sub UNION ALL SELECT * FROM extra_sub"
    else:
        sql_all = "SELECT * FROM base_sub"
    stats = {}
    for field in ("chemistry", "math_stats"):
        p = f"{d}/roster_gold_{field}.parquet"
        con.execute(f"""COPY (
            SELECT dept_key, school, author_id,
                   min(year_start) year_start, max(year_end) year_end
            FROM ({sql_all}) WHERE field = '{field}'
            GROUP BY dept_key, school, author_id
            ORDER BY author_id) TO '{p}' (FORMAT PARQUET)""")
        n, ppl = con.execute(f"SELECT count(*), count(DISTINCT author_id) "
                             f"FROM read_parquet('{p}')").fetchone()
        stats[field] = {"spells": n, "people": ppl}
        print(f"[{var}] {field}: {n} spells / {ppl} people → {os.path.basename(p)}")
    rep["variants"][var] = {"rank_tags": sorted(tags_ok), "new_event_rows_added": len(extra),
                            **stats}
    if ex_df is not None:
        con.unregister("extra_sub")
    con.unregister("base_sub")

# ---------- 3. Coverage check: headcount in post per event under each tier ----------
cov = defaultdict(dict)
for field in ("chemistry", "math_stats"):
    for e in csv.DictReader(open(f"{OUT}/events_{field}_gold_2026-08-10.csv")):
        eid = f"{e['author_id']}:{e['school']}"
        for var in VARIANTS:
            p = f"{OUT}/{var}/roster_gold_{field}.parquet"
            n = con.execute(f"""SELECT count(DISTINCT author_id) FROM read_parquet('{p}')
                WHERE school = '{e['school']}'
                  AND {int(e['arrival_corrected'])} BETWEEN year_start AND year_end
                  AND author_id <> '{e['author_id']}'""").fetchone()[0]
            cov[eid][var] = n
        cov[eid]["name"] = e["display_name"]
        cov[eid]["field"] = field
        cov[eid]["arrival"] = int(e["arrival_corrected"])
rep["coverage"] = cov
json.dump(rep, open(f"{OUT}/prep_variants_report.json", "w"), ensure_ascii=False, indent=1)

print("\nPeople in post per event (inc = main definition / incamb = including ambiguous)")
for eid, c in sorted(cov.items(), key=lambda kv: kv[1]["inc"]):
    print(f"  inc={c['inc']:4d}  incamb={c['incamb']:4d}   {c['field'][:4]:5s} "
          f"{c['arrival']}  {c['name']}")
print(f"\nPREP2_OK → {OUT}/prep_variants_report.json")
