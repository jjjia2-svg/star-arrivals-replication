#!/usr/bin/env python3
"""50_leftbehind_build.py — panel for "will left-behind colleagues in the same direction band together?"

Question: after a star arrives, do the people in the same field who did **not** end up collaborating
with the star and were **not** lifted by them collaborate more with each other, to counter it?

Two legs, following the post-treatment-grouping (bad control) design:

  Leg 1 (frozen before treatment; can be read causally): the grouping uses only variables fixed before arrival
      same direction    = both persons have dose_topic >= the field's median positive dose (dose frozen the year before arrival)
      out of the star's reach = both are dept_only channel (in the department, but not inside the star's two-hop network before arrival)
      comparison group  = both are in the network channel (within two hops before arrival = inside the star's circle)
  Leg 2 (post-hoc grouping; descriptive only, with three safeguards against post-hoc grouping):
      N-N = neither co-authored with the star within the window ("left-behind people")
      B-* = at least one is connected with the star

Common conditions: neither co-authored with the star before arrival (being-related pairs already dropped);
the pair itself did not co-author before the window (the original panel-3 risk-set rule);
outcome y = the pair's first co-authored paper, with papers that include the star not counted (rule identical to the main panel 3).

Output: data/lb_counts.csv + data/pairs_slim_lb_{field}_{cell}.parquet
"""
import os, json, csv
import duckdb

# --- M3 port: repo path resolution (legacy hard-coded the author's machine) — config/paths.yaml ---
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents if p.name == "frames").parents[1]
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
V = str(_sar_rd(_sar_legacy_thesis()) / "v2_output")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G = f"{V}/multidisc_gold_2026-08-10/data/fnfix"
E = f"{V}/econ_fnfix_2026-08-15/data"
FIELDS = {
    "econ": dict(pairs=f"{E}/pairs_unified.csv", frame=f"{E}/analysis_frame_econ920_unified_fullsnap_2026-08-13.csv",
                 p2=f"{E}/becoming_unified.csv", rel=f"{E}/relationships.csv"),
    "chemistry": dict(pairs=f"{G}/panels23_chemistry_gold/pairs_none.parquet",
                      frame=f"{G}/analysis_frame_chemistry_new_gold_2026-08-10.csv",
                      p2=f"{G}/panels23_chemistry_gold/becoming_none.csv", rel=None),
    "math_stats": dict(pairs=f"{G}/panels23_math_stats_gold/pairs_none.parquet",
                       frame=f"{G}/analysis_frame_math_stats_new_gold_2026-08-10.csv",
                       p2=f"{G}/panels23_math_stats_gold/becoming_none.csv", rel=None),
}
con = duckdb.connect(); con.execute("PRAGMA threads=6"); con.execute("PRAGMA memory_limit='14GB'")
con.execute(f"PRAGMA temp_directory='{BASE}/data/_duck_tmp'")
rows, manifest = [], {}

for field, p in FIELDS.items():
    rd = "read_csv_auto" if p["pairs"].endswith(".csv") else "read_parquet"
    print(f"\n===== {field} =====", flush=True)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE dose AS
        SELECT event_id, regexp_replace(incumbent_person_id,'^P_','') AS pid, max(dose_topic) AS dose
        FROM read_csv_auto('{p["frame"]}') WHERE dose_topic IS NOT NULL GROUP BY 1,2""")
    # Channel (frozen before treatment): the panel-2 table carries channel; economics also has relationships.csv — check that the two agree
    con.execute(f"""CREATE OR REPLACE TEMP TABLE ch AS
        SELECT event_id, regexp_replace(pid,'^P_','') AS pid,
               max(CASE WHEN channel IN ('network','both') THEN 1 ELSE 0 END) AS in_net,
               max(CASE WHEN y=1 AND tau<0 THEN 1 ELSE 0 END) AS pre_tie,
               max(CASE WHEN y=1 THEN 1 ELSE 0 END) AS any_tie
        FROM read_csv_auto('{p["p2"]}') GROUP BY 1,2""")
    med = con.execute("SELECT quantile_cont(dose,0.5) FROM dose WHERE dose>0").fetchone()[0]
    con.execute(f"""CREATE OR REPLACE TEMP TABLE pa AS
        SELECT DISTINCT pr.event_id, pr.i_id, pr.j_id,
               least(di.dose,dj.dose) AS dmin,
               ci.in_net AS net_i, cj.in_net AS net_j, ci.any_tie AS any_i, cj.any_tie AS any_j
        FROM {rd}('{p["pairs"]}') pr
        JOIN dose di ON di.event_id=pr.event_id AND di.pid=pr.i_id
        JOIN dose dj ON dj.event_id=pr.event_id AND dj.pid=pr.j_id
        JOIN ch ci ON ci.event_id=pr.event_id AND ci.pid=pr.i_id AND ci.pre_tie=0
        JOIN ch cj ON cj.event_id=pr.event_id AND cj.pid=pr.j_id AND cj.pre_tie=0""")
    TOPIC = f"dmin >= {med}"            # same direction (frozen before treatment)
    CELLS = {
        # Leg 1: frozen before treatment
        "A_far":  f"{TOPIC} AND net_i=0 AND net_j=0",       # same direction + both outside the star's circle
        "A_near": f"{TOPIC} AND net_i=1 AND net_j=1",       # same direction + both within the star's two hops
        # Leg 2: post-hoc grouping (descriptive)
        "B_nn":   f"{TOPIC} AND any_i=0 AND any_j=0",       # same direction + neither connected with the star (left-behind people)
        "B_any":  f"{TOPIC} AND (any_i=1 OR any_j=1)",      # same direction + at least one connected with the star
        # Reference: all same-direction pairs (already run; rebuilt for a like-for-like comparison)
        "T_all":  f"{TOPIC}",
    }
    for cell, cond in CELLS.items():
        f_out = f"{BASE}/data/pairs_slim_lb_{field}_{cell}.parquet"
        con.execute(f"""COPY (
            WITH keep AS (SELECT event_id,i_id,j_id FROM pa WHERE {cond})
            SELECT CAST(DENSE_RANK() OVER (ORDER BY p.i_id||'_'||p.j_id||'@'||p.event_id)-1 AS INTEGER) AS grp,
                   CAST(DENSE_RANK() OVER (ORDER BY p.event_id) AS INTEGER) AS ev,
                   CAST(p.year AS INTEGER) AS year, CAST(p.y_any AS TINYINT) AS y, CAST(p.post AS TINYINT) AS D
            FROM {rd}('{p["pairs"]}') p JOIN keep k
              ON k.event_id=p.event_id AND k.i_id=p.i_id AND k.j_id=p.j_id
        ) TO '{f_out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")
        s = con.execute(f"""SELECT count(*), count(DISTINCT grp), sum(y), count(DISTINCT ev),
            sum(CASE WHEN D=0 THEN 1 ELSE 0 END), sum(CASE WHEN D=0 THEN y ELSE 0 END),
            sum(CASE WHEN D=1 THEN 1 ELSE 0 END), sum(CASE WHEN D=1 THEN y ELSE 0 END)
            FROM read_parquet('{f_out}')""").fetchone()
        rate_pre = 100.0*s[5]/s[4] if s[4] else None
        rate_post = 100.0*s[7]/s[6] if s[6] else None
        rows.append(dict(field=field, cell=cell, cut=round(float(med),4), rows=s[0], pairs=s[1],
                         ties=int(s[2] or 0), events=s[3], rate_pre_pp=rate_pre, rate_post_pp=rate_post,
                         diff_pp=(rate_post-rate_pre) if (rate_pre is not None and rate_post is not None) else None))
        manifest[f"{field}|{cell}"] = dict(file=f_out, rows=s[0], pairs=s[1], ties=int(s[2] or 0), mb=round(os.path.getsize(f_out)/1e6,1))
        print(f"  [{cell:6s}] rows {s[0]:>9,} pairs {s[1]:>7,} first ties {int(s[2] or 0):>5,} events {s[3]:>3} | "
              f"raw rate pre {rate_pre:.4f}pp → post {rate_post:.4f}pp ({rate_post-rate_pre:+.4f})", flush=True)

with open(f"{BASE}/data/lb_counts.csv","w",newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
json.dump(manifest, open(f"{BASE}/data/lb_manifest.json","w"), indent=1)
print("\n→ data/lb_counts.csv, data/lb_manifest.json")
