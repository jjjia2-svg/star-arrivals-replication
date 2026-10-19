#!/usr/bin/env python3
"""00c_prep_final_population.py — final population = incfel department roster ∪ academic tier of the centre rosters

Rules:
  · Research centres count as part of the department (economics precedent: Melbourne Institute/CHE/CoPS)
  · The population definition matches economics (includes research fellows) = the incfel yardstick
  · Criterion = a centre's academic staff would be counted as colleagues of that department
Edge centres, handled by the criterion above (each one logged):
  · uwa_plantenergy dropped — the collector notes the CI is a plant biologist, in a different discipline from chemistry in the same school, so not a chemistry colleague
  · deakin_chiral kept — chemistry direction (chirality and molecular technology), but not a standalone centre site; flagged weak_provenance
  · Rosters whose snapshot year != event year (GAP flag) are still kept; the in-post spell covers [min(event year, snapshot year), max(...)] and is logged

Output: data/final/roster_gold_{chemistry,math_stats}.parquet + prep_final_report.json
"""
import csv
import json
import os
import re
from collections import Counter, defaultdict

import duckdb
import pandas as pd

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
G = f"{ROOT}/v2_output/multidisc_gold_2026-08-10"
CEN = f"{ROOT}/v2_output/multidisc_roster_econ_grade_2026-08-09/collect/_centres_2026-08-10/openalex_match_centres_all.csv"
OUT = f"{G}/data/final"
os.makedirs(OUT, exist_ok=True)

# centre -> (dept_key, school, field)
CENTRE_MAP = {
    "exciton_melbourne": ("melbourne_chem", "melbourne", "chemistry"),
    "exciton_monash": ("monash_chem", "monash", "chemistry"),
    "exciton_unsw": ("unsw_chem", "unsw", "chemistry"),
    "exciton_sydney": ("sydney_chem", "sydney", "chemistry"),
    "monash_cgc": ("monash_chem", "monash", "chemistry"),
    "monash_wsc": ("monash_chem", "monash", "chemistry"),
    "monash_biospec": ("monash_chem", "monash", "chemistry"),
    "adelaide_can": ("adelaide_chem", "adelaide", "chemistry"),
    "adelaide_ipas": ("adelaide_chem", "adelaide", "chemistry"),
    "adelaide_cnbp": ("adelaide_chem", "adelaide", "chemistry"),
    "sydney_kcpc": ("sydney_chem", "sydney", "chemistry"),
    "melbourne_bio21": ("melbourne_chem", "melbourne", "chemistry"),
    "unsw_camd": ("unsw_chem", "unsw", "chemistry"),
    "deakin_chiral": ("deakin_chem", "deakin", "chemistry"),
    "acems_melbourne": ("melbourne_mathstats", "melbourne", "math_stats"),
    "acems_monash": ("monash_mathstats", "monash", "math_stats"),
    "acems_unsw": ("unsw_mathstats", "unsw", "math_stats"),
    "mascos_unsw": ("unsw_mathstats", "unsw", "math_stats"),
    "mascos_uq": ("uq_mathstats", "uq", "math_stats"),
    "uwa_cmsc": ("uwa_mathstats", "uwa", "math_stats"),
    "uq_carm": ("uq_mathstats", "uq", "math_stats"),
    "uwa_plantenergy": None,     # dropped: plant biology, not a chemistry colleague
}

# incfel academic-tier yardstick (the same one as in 00b; the regex is copied, not the semantics)
KEEP = re.compile(r"\bfellow", re.I)
KEEP_BARE = re.compile(r"^(dr\.?|prof\.?|professor|a/?prof\.?)$", re.I)
DROP = re.compile(r"administrat|laborator|lab assistant|teaching assistant|honours|visitor|visiting|"
                  r"technician|technical|workshop|secretar|reception|^m(r|s|rs|iss)\.?$|"
                  r"research staff|research officer|student|casual", re.I)

def academic(title):
    parts = [p.strip() for p in re.split(r"[;|]", str(title or "")) if p.strip()]
    if not parts:
        return False, "无职称"
    if any(KEEP.search(p) for p in parts):
        return True, "fellow系"
    if any(DROP.search(p) for p in parts):
        return False, "非学术"
    if any(KEEP_BARE.match(p) for p in parts):
        return True, "仅Dr/Prof"
    return False, "其他"

rep = {"date": "2026-08-13", "steps": []}
rows = list(csv.DictReader(open(CEN)))
rep["centre_rows_total"] = len(rows)

kept, stat, dropped_centres = [], Counter(), Counter()
for r in rows:
    ck = r["centre_key"]
    m = CENTRE_MAP.get(ck)
    if m is None:
        dropped_centres[ck] += 1
        continue
    aid = (r.get("author_id") or "").strip()
    if not aid or aid.startswith("api_error"):
        stat["无号"] += 1
        continue
    tag = r["rank_tag"]
    if tag == "include":
        ok = True
    elif tag == "ambiguous":
        ok, why = academic(r.get("title"))
        stat[f"amb_{why}"] += 1
    else:
        ok = False
        stat["exclude"] += 1
    if not ok:
        continue
    # in-post spell: covers [min(target event year, snapshot year), max(...)] (GAP rosters are kept and logged)
    m_yr = re.search(r"(\d{4})$", r.get("roster") or "")
    tgt = int(m_yr.group(1)) if m_yr else None
    snap = int(str(r["snapshot_ts"])[:4])
    ys = min(x for x in (tgt, snap) if x is not None)
    ye = max(x for x in (tgt, snap) if x is not None)
    dept, school, field = m
    kept.append({"dept_key": dept, "school": school, "author_id": aid,
                 "year_start": ys, "year_end": ye, "field": field, "src": ck,
                 "gap_flag": (tgt is not None and abs(snap - tgt) >= 1)})
    stat["入选"] += 1
rep["centre_filter"] = dict(stat)
rep["centre_excluded_centres"] = dict(dropped_centres)
print(f"[centre] {len(rows)} rows → selected {len(kept)} ({dict(stat)}); whole centres dropped {dict(dropped_centres)}")

con = duckdb.connect()
cen_df = pd.DataFrame(kept)
con.register("cen", cen_df)
stats = {}
for field in ("chemistry", "math_stats"):
    base = f"{G}/data/incfel/roster_gold_{field}.parquet"
    p = f"{OUT}/roster_gold_{field}.parquet"
    con.execute(f"""COPY (
        SELECT dept_key, school, author_id,
               min(year_start) year_start, max(year_end) year_end
        FROM (
          SELECT dept_key, school, author_id, year_start, year_end
          FROM read_parquet('{base}')
          UNION ALL
          SELECT dept_key, school, author_id, year_start, year_end
          FROM cen WHERE field = '{field}')
        GROUP BY dept_key, school, author_id
        ORDER BY author_id) TO '{p}' (FORMAT PARQUET)""")
    n, ppl = con.execute(f"SELECT count(*), count(DISTINCT author_id) FROM read_parquet('{p}')").fetchone()
    nb, pplb = con.execute(f"SELECT count(*), count(DISTINCT author_id) FROM read_parquet('{base}')").fetchone()
    stats[field] = {"spells": n, "people": ppl, "base_people": pplb, "added_people": ppl - pplb}
    print(f"[final] {field}: incfel {pplb} people → final {ppl} people (+{ppl-pplb})")
rep["rosters"] = stats

# Coverage check: final ledger x final population
cov = []
for field in ("chemistry", "math_stats"):
    for e in csv.DictReader(open(f"{G}/data/events_{field}_final_2026-08-13.csv")):
        arr = int(e["arrival_corrected"])
        n = con.execute(f"""SELECT count(DISTINCT author_id)
            FROM read_parquet('{OUT}/roster_gold_{field}.parquet')
            WHERE school = '{e['school']}' AND {arr} BETWEEN year_start AND year_end
              AND author_id <> '{e['author_id']}'""").fetchone()[0]
        cov.append({"event": f"{e['display_name']}@{e['school']}:{arr}", "field": field, "n": n})
rep["coverage"] = cov
json.dump(rep, open(f"{OUT}/prep_final_report.json", "w"), ensure_ascii=False, indent=1)
print("\nFinal population coverage (people in post per event)")
for c in sorted(cov, key=lambda d: d["n"]):
    print(f"  {c['n']:4d}  {c['field'][:4]:5s} {c['event']}")
print(f"\nFINAL_POP_OK → {OUT}/prep_final_report.json")
