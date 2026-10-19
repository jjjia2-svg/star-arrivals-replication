# -*- coding: utf-8 -*-
"""star_screening/run_screening — chemistry + maths (incl. statistics) star-candidate screening, end to end (Wave1b).

Screens only, decides nothing: produces a shortlist of candidates to verify + tier statistics + an estimate of the four-gate verification workload. The event table is finalised manually.

Rules (copied from the economics rules, see the header of screening_lib.py):
  (1) Star measure = cumulative raw citation stock (full counting) frozen at the year before arrival (t−1).
  (2) cell = per-person modal subfield × academic-age bin × year; naive-rank percentile within the cell.
  (3) Academic age = arrival year − robust first-publication year; drop age<2 (seniority gate).
  (4) First-publication-year contamination guard: the robust first-publication year drops lone old papers, and first_pub_flag marks anomalies for manual review.
  (5) Pure overseas-poach pre-screen: no Australian (AU) institutional affiliation in works_affil in the 3 years before arrival (arrival-3..arrival-1) → True.

★Three screening-layer choices (not identification decisions; to be reviewed manually — see the report notes):
  (D1) Candidate subfield = per-person modal subfield (consistent with the global pool), **not** forced to the single 2002 as in economics —
       chemistry/maths are multi-subfield fields with no single code to force. This is the most faithful generalisation.
  (D2) The top-10% estimation gate has no fixed pct_10 → reuse floor=30 as the estimation gate.
  (D3) No person_map (the multidisc snapshot has no U2 built) → candidates use bare author_id stocks, persons are not folded (recorded as is).

Hard rules: SSD and economics outputs are read-only; all new outputs land in this directory; numbers go in the report; no online verification (that is Wave1c's job).
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
import screening_lib as L

# --- Paths (SSD read-only) ---------------------------------------------------------
# --- M3 port: repo path resolution (the legacy script hard-coded a local machine path) — config/paths.yaml ---
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
BASE = _sar_lazyout(Path(str(_sar_legacy_thesis()) + "/"
            "v2_output/multidisc_2026-07-24"))
SSD = Path(str(_sar_rd(_sar_derived_root() / "u1_edges_full_2026-07-05")))
ROSTER = BASE / "data" / "roster_silver_chem_mathstats_11school.parquet"
OUT_CSV = BASE / "data" / "star_candidates_chem_mathstats.csv"
OUT_REPORT = BASE / "reports" / "star_screening_report.json"
SCRATCH = Path("/private/tmp/removed-session-directory/"
               "duckdb_tmp")

CSV_COLS = ["field", "school", "author_id", "display_name", "arrival_year", "stock_frozen",
            "cell", "pct", "pass_p10", "pass_p05", "pass_p01", "academic_age",
            "first_pub_year", "first_pub_flag", "foreign_prescreen", "notes"]


def _con():
    con = duckdb.connect()
    con.execute("PRAGMA threads=6")
    con.execute("PRAGMA disable_progress_bar")
    con.execute("PRAGMA memory_limit='16GB'")
    (SCRATCH / "duck_tmp").mkdir(parents=True, exist_ok=True)
    con.execute(f"PRAGMA temp_directory='{SCRATCH / 'duck_tmp'}'")
    con.create_function("cbin", lambda a: L.cohort_bin(int(a)), ["INTEGER"], "VARCHAR")
    return con


def load_candidates():
    """Silver roster → candidate arrival events (dedup: earliest spell of the same person at the same school, year_start∈[2005,2023])."""
    rows = pq.read_table(str(ROSTER)).to_pylist()
    return L.dedup_candidate_arrivals(rows)


def build_aw(con):
    """Whole-database authorship_edges × works → aw (aid, yr, cited, subfield). Rows missing pub_year are dropped (logged)."""
    ep = SSD.as_posix()
    n_null_c = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{ep}/authorship_edges/**/*.parquet') e "
        f"JOIN read_parquet('{ep}/works/**/*.parquet') w ON e.work_id=w.work_id "
        f"WHERE w.cited_by_count IS NULL").fetchone()[0]
    if n_null_c:
        raise ValueError(f"build_aw: {n_null_c} works counted in the stock lack cited_by_count (missing != 0) — clean up first")
    n_dropped = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{ep}/authorship_edges/**/*.parquet') e "
        f"JOIN read_parquet('{ep}/works/**/*.parquet') w ON e.work_id=w.work_id "
        f"WHERE w.publication_year IS NULL").fetchone()[0]
    con.execute(
        f"CREATE TEMP TABLE aw AS SELECT e.author_id aid, w.publication_year yr, "
        f"w.cited_by_count c, w.subfield_id sf "
        f"FROM read_parquet('{ep}/authorship_edges/**/*.parquet') e "
        f"JOIN read_parquet('{ep}/works/**/*.parquet') w ON e.work_id=w.work_id "
        f"WHERE w.publication_year IS NOT NULL")
    return int(n_dropped)


# Whole-pool ranking (aligned line for line with the structure of run_u4._STAR_CELL_SQL; no OV/FPOV/SOV override —
#   candidates are real authors, using their own modal subfield, consistent with the pool; not forced to a single field).
_POOL_SQL = """
CREATE OR REPLACE TEMP TABLE poolY AS
WITH agg0 AS (SELECT aid, SUM(c) stock FROM aw WHERE yr <= {Y} GROUP BY aid),
rfp AS (SELECT aid, MIN(yr) FILTER (WHERE nxt IS NULL OR nxt - yr <= {GAP}) fp
        FROM (SELECT aid, yr, LEAD(yr) OVER (PARTITION BY aid ORDER BY yr) nxt
              FROM (SELECT DISTINCT aid, yr FROM aw WHERE yr <= {Y}))
        GROUP BY aid),
sfc AS (SELECT aid, sf, COUNT(*) n FROM aw WHERE yr <= {Y} AND sf IS NOT NULL GROUP BY aid, sf),
sf_modal AS (SELECT aid, sf FROM (SELECT aid, sf,
    ROW_NUMBER() OVER (PARTITION BY aid ORDER BY n DESC, sf) rk FROM sfc) WHERE rk=1),
pool AS (SELECT a.aid, a.stock, m.sf subfield, cbin(CAST({Y}-r.fp AS INTEGER)) age_bin,
                CAST({Y}-r.fp AS INTEGER) aage
         FROM agg0 a JOIN rfp r ON a.aid=r.aid JOIN sf_modal m ON a.aid=m.aid)
SELECT aid, stock, subfield, age_bin, aage,
    RANK() OVER (PARTITION BY subfield, age_bin ORDER BY stock DESC) rnk,
    COUNT(*) OVER (PARTITION BY subfield, age_bin) cell_n
FROM pool
"""


def rank_candidates(con, cands, gap=L.ROBUST_FIRST_PUB_MAX_GAP):
    """Rank the whole pool in batches by Y=arrival-1, and pull out the candidate rows → {(aid,school): row}."""
    by_Y = defaultdict(list)
    for c in cands:
        by_Y[c["arrival_year"] - 1].append(c)
    got = {}
    for i, Y in enumerate(sorted(by_Y)):
        con.execute(_POOL_SQL.format(Y=Y, GAP=gap))
        ids = ",".join("'" + c["author_id"] + "'" for c in by_Y[Y])
        rows = {r[0]: r for r in con.execute(
            f"SELECT aid, stock, subfield, age_bin, aage, rnk, cell_n "
            f"FROM poolY WHERE aid IN ({ids})").fetchall()}
        for c in by_Y[Y]:
            got[(c["author_id"], c["school"])] = rows.get(c["author_id"])
        sys.stderr.write(f"[rank] Y={Y} ({i+1}/{len(by_Y)}) cand={len(by_Y[Y])} matched={len(rows)}\n")
    return got


def naive_first_pub(con, aids):
    """Per candidate, MIN(publication_year) over the whole period (used for the contamination flag; not cut at Y)."""
    if not aids:
        return {}
    idlist = ",".join("'" + a + "'" for a in sorted(aids))
    q = f"SELECT aid, MIN(yr) FROM aw WHERE aid IN ({idlist}) GROUP BY aid"
    return {a: y for a, y in con.execute(q).fetchall()}


def display_names(con, aids):
    if not aids:
        return {}
    idlist = ",".join("'" + a + "'" for a in sorted(aids))
    ap = SSD.as_posix()
    q = (f"SELECT author_id, display_name FROM "
         f"read_parquet('{ap}/authors/**/*.parquet') WHERE author_id IN ({idlist})")
    return {a: n for a, n in con.execute(q).fetchall()}


def foreign_prescreen(con, cands):
    """Whether works_affil in the 3 years before arrival (arrival-3..arrival-1) shows any Australian (AU) institutional affiliation.

    True = no AU affiliation (pure overseas-poach candidate, passes the pre-screen). Returns {(aid,school): (bool, note)}.
    Has works but no AU → True; has AU → False; no affiliation record at all in the window → True + note (cannot confirm presence in Australia).
    """
    ap = SSD.as_posix()
    vals = ",".join(f"('{c['author_id']}','{c['school']}',{c['arrival_year']})" for c in cands)
    q = f"""
    WITH cand(aid, school, arr) AS (VALUES {vals}),
    win AS (
      SELECT c.aid, c.school,
             COUNT(*) FILTER (WHERE i.country_code='AU') n_au,
             COUNT(*) n_rows
      FROM cand c
      JOIN read_parquet('{ap}/authorship_edges/**/*.parquet') e
        ON e.author_id=c.aid AND e.publication_year BETWEEN c.arr-3 AND c.arr-1
      JOIN read_parquet('{ap}/works_affil/**/*.parquet') wa
        ON wa.work_id=e.work_id AND wa.author_id=c.aid
      LEFT JOIN read_parquet('{ap}/institutions/**/*.parquet') i
        ON wa.institution_id=i.institution_id
      GROUP BY c.aid, c.school)
    SELECT aid, school, n_au, n_rows FROM win
    """
    res = {}
    for aid, school, n_au, n_rows in con.execute(q).fetchall():
        if n_au and n_au > 0:
            res[(aid, school)] = (False, "")
        elif n_rows and n_rows > 0:
            res[(aid, school)] = (True, "")            # has affiliation records but no AU → pure overseas
    # candidate with no works_affil rows at all in the window: True + note (cannot confirm presence in Australia; the pre-screen lets it through conservatively)
    for c in cands:
        k = (c["author_id"], c["school"])
        if k not in res:
            res[k] = (True, "no_affil_in_window(无法确认在澳,预筛保守)")
    return res


def screen():
    t0 = time.time()
    con = _con()
    cands = load_candidates()
    n_dropped_pub = build_aw(con)
    sys.stderr.write(f"[aw] built, dropped_null_pubyear={n_dropped_pub}, "
                     f"t={round(time.time()-t0,1)}s\n")

    ranked = rank_candidates(con, cands)
    aids = {c["author_id"] for c in cands}
    naive_fp = naive_first_pub(con, aids)
    names = display_names(con, aids)
    fpre = foreign_prescreen(con, cands)

    out_rows = []
    for c in cands:
        k = (c["author_id"], c["school"])
        r = ranked.get(k)
        fp_pre, fp_note = fpre[k]
        base = {
            "field": c["field"], "school": c["school"], "author_id": c["author_id"],
            "display_name": names.get(c["author_id"], ""), "arrival_year": c["arrival_year"],
            "foreign_prescreen": fp_pre,
        }
        if r is None:
            # not in the pool (no works / no subfield up to t−1): not placed in any cell ≠ placed in a cell of 0 people; cell all None
            out_rows.append({**base, "stock_frozen": None, "cell": None, "pct": None,
                             "pass_p10": None, "pass_p05": None, "pass_p01": None,
                             "academic_age": None, "first_pub_year": None,
                             "first_pub_flag": None,
                             "notes": ";".join(x for x in ["not_in_pool(到任前无作品/无子领域)", fp_note] if x)})
            continue
        _aid, stock, subfield, age_bin, aage, rnk, cell_n = r
        robust_fp = c["arrival_year"] - 1 - int(aage)     # Y - aage
        nfp = naive_fp.get(c["author_id"])
        fpub_flag = L.first_pub_flag(nfp, robust_fp, int(aage))
        flags = L.star_pass_flags(rnk, cell_n, int(aage))
        pct = round(1.0 - rnk / cell_n, 4)
        notes = []
        if not L.age_eligible(int(aage)):
            notes.append(f"age_gate_fail(age={aage}<2)")
        if fpub_flag:
            notes.append(f"first_pub_flag(naive={nfp},robust={robust_fp},age={aage})")
        if fp_note:
            notes.append(fp_note)
        out_rows.append({
            **base,
            "stock_frozen": int(stock),
            "cell": f"{subfield}|{age_bin}|{c['arrival_year']-1}",
            "pct": pct,
            "pass_p10": flags[L.P10], "pass_p05": flags[L.P05], "pass_p01": flags[L.P01],
            "academic_age": int(aage), "first_pub_year": robust_fp,
            "first_pub_flag": fpub_flag, "notes": ";".join(notes),
        })
    con.close()
    return out_rows, n_dropped_pub, round(time.time() - t0, 1)


def write_csv(rows):
    import csv
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    rows_sorted = sorted(rows, key=lambda r: (r["field"], r["school"], r["author_id"]))
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        w.writeheader()
        for r in rows_sorted:
            w.writerow(r)
    return len(rows_sorted)


def build_report(rows, n_dropped_pub, runtime_s):
    def tally(field):
        fr = [r for r in rows if r["field"] == field]
        in_pool = [r for r in fr if r["stock_frozen"] is not None]
        # shortlist = passes the age gate + the overseas pre-screen + this tier
        def shortlist(pkey):
            return [r for r in in_pool if r[pkey] is True and r["foreign_prescreen"] is True]
        sl10 = shortlist("pass_p10")
        by_school = Counter(r["school"] for r in sl10)
        weak = sum(1 for r in sl10 if "no_affil_in_window" in (r["notes"] or ""))
        return {
            "n_candidate_arrivals": len(fr),
            "n_in_pool": len(in_pool),
            "n_not_in_pool": len(fr) - len(in_pool),
            "n_age_gate_fail": sum(1 for r in in_pool
                                   if r["academic_age"] is not None and r["academic_age"] < 2),
            "n_first_pub_flagged": sum(1 for r in in_pool if r["first_pub_flag"]),
            "n_foreign_prescreen_true": sum(1 for r in fr if r["foreign_prescreen"] is True),
            "candidates_pass_p10_and_foreign": len(sl10),
            "candidates_pass_p05_and_foreign": len(shortlist("pass_p05")),
            "candidates_pass_p01_and_foreign": len(shortlist("pass_p01")),
            "shortlist_p10_foreign_signal": {
                "strong_has_affil_no_AU": len(sl10) - weak,
                "weak_no_affil_data_in_window": weak},
            "shortlist_p10_by_school": dict(sorted(by_school.items())),
            # pure star tier without the overseas pre-screen (comparison)
            "n_pass_p10_any": sum(1 for r in in_pool if r["pass_p10"] is True),
            "n_pass_p05_any": sum(1 for r in in_pool if r["pass_p05"] is True),
            "n_pass_p01_any": sum(1 for r in in_pool if r["pass_p01"] is True),
        }
    chem = tally("chemistry")
    math = tally("math_stats")
    # Economics analogue: 84 top-10% candidates → 29 confirmed (survival rate ~34.5%); used to estimate the workload
    ECON_SURVIVAL = 29 / 84
    def est(n):
        return {"shortlist_n": n,
                "econ_analogy_survival_rate": round(ECON_SURVIVAL, 3),
                "expected_confirmed_est": round(n * ECON_SURVIVAL, 1),
                "verify_author_hours_est_3to6h_per_field": "3-6 作者小时/学科 (简报 Q9)"}
    return {
        "task": "C-Wave1b 化学+数学(统计) 明星候选筛选 (只筛不签)",
        "generated": "2026-07-24",
        "runtime_seconds": runtime_s,
        "caliber_source": "照搬经济系已签 (redlines_v4_signed_2026-07-05 + run_u4._STAR_CELL_SQL + 简报Q4)",
        "signed_thresholds": {
            "percentile_primary": L.PERCENTILE_PRIMARY,
            "percentile_robustness": list(L.PERCENTILE_ROBUSTNESS),
            "cell_min_n": L.CELL_MIN_N, "min_academic_age": L.MIN_ACADEMIC_AGE,
            "robust_first_pub_max_gap": L.ROBUST_FIRST_PUB_MAX_GAP, "age_bins": "milojevic",
            "estimable_gates_applied": {"p01": max(L.CELL_MIN_N["pct_1"], L.CELL_MIN_N["floor"]),
                                        "p05": max(L.CELL_MIN_N["pct_5"], L.CELL_MIN_N["floor"]),
                                        "p10": L.CELL_MIN_N["floor"]},
        },
        "screening_decisions_for_author": {
            "D1_subfield": "候选用 per-person modal subfield (与全球池一致), 不像经济系强制归单一 2002 "
                           "— 化学/数学是多子领域 field, 无单一码可强制; 最忠实泛化, author confirmed。",
            "D2_p10_gate": "前10% 无已签 pct_10 估计门 → 复用 floor=30; p05/p01 用已签 max(20,30)/max(100,30)。",
            "D3_no_fold": "多学科快照无 person_map (未建 U2) → 候选用裸 author_id 存量, 不折人 (如实记录)。",
        },
        "n_dropped_null_pub_year": n_dropped_pub,
        "chemistry": chem,
        "math_stats": math,
        "shortlist_totals": {
            "p10_and_foreign": chem["candidates_pass_p10_and_foreign"] + math["candidates_pass_p10_and_foreign"],
            "p05_and_foreign": chem["candidates_pass_p05_and_foreign"] + math["candidates_pass_p05_and_foreign"],
            "p01_and_foreign": chem["candidates_pass_p01_and_foreign"] + math["candidates_pass_p01_and_foreign"],
        },
        "workload_estimate": {
            "chemistry": est(chem["candidates_pass_p10_and_foreign"]),
            "math_stats": est(math["candidates_pass_p10_and_foreign"]),
            "note": "经济系 84 前10%候选→29 坐实 (存活率 34.5%) 当类比锚; 真存活率待 Wave1c 四闸人核。",
        },
        "next_step": "Wave1c 四闸查证 (①在编学科 ②全职非访问 ③到任年 ④纯海外挖角终判) "
                     "对 p10&foreign 短名单逐人核 (1候选=1子agent可并行); 作者逐事件签事件表 (串行红线)。",
    }


def main():
    rows, n_dropped_pub, runtime_s = screen()
    n_written = write_csv(rows)
    report = build_report(rows, n_dropped_pub, runtime_s)
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.stderr.write(f"[done] rows={n_written} csv={OUT_CSV} report={OUT_REPORT} t={runtime_s}s\n")
    print(json.dumps({"n_rows": n_written,
                      "shortlist_totals": report["shortlist_totals"],
                      "chemistry_p10_foreign": report["chemistry"]["candidates_pass_p10_and_foreign"],
                      "math_stats_p10_foreign": report["math_stats"]["candidates_pass_p10_and_foreign"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
