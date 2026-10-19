#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""caliber_2026-10/restake_econ11.py — the economics re-rank on the extraction the July machine used.

Finding (2026-09-22, run 2 of run_caliber.py): the 2026-07-22 economics stars were ranked on the
11-school extraction `u1_full_11school_2026-07-16`; the multidisc machine's table
`u1_edges_full_2026-07-05` holds only a fraction of their works (e.g. A5046163960: 35 vs 131
authorship rows), so re-ranking them there reports `not_in_pool` / understated stocks. This
driver runs the SAME ranking machine (`_POOL_SQL` of run_screening.py, via restake_equiv) on the
11-school tables for economics only.

Phases
  C   control: the 35 July event stars that carry a machine percentile in
      derived/u4_star_set_p10_80ev_2026-07-22/star_set/star_set.parquet — with no drops, the
      percentile must equal the July value (4 dp) for the machine to count as the same machine.
  R   the 17 rechecked economics stars (A5091326353 on his correct id): drops = every call on
      record (historical + 2026-10), adds = the 2026-08-13 split-id adds; before/after
      percentile and pass flags at 10% and 5%.
Outputs data/cal2026-10/restake_econ11_control_2026-10.csv, restake_econ11_2026-10.csv,
        restake_econ11_report_2026-10.json.
"""
from __future__ import annotations

import csv
import datetime
import json
import os
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))
HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from pipeline.lib.paths import derived_root, require_readable   # noqa: E402
import run_caliber as rc                                           # noqa: E402  (this layer's driver)
restake_equiv, cleaned_works = rc.restake_equiv, rc.cleaned_works

CAL = REPO / "data" / "cal2026-10"
JULY_STAR_SET = "u4_star_set_p10_80ev_2026-07-22/star_set/star_set.parquet"
ELEVEN = "u1_full_11school_2026-07-16"


def load_aw_raw_11(con) -> int:
    """72_…py:51-55, the same join, on the 11-school extraction."""
    root = pathlib.Path(str(require_readable(derived_root() / ELEVEN))).as_posix()
    con.execute(f"""CREATE TEMP TABLE aw_raw AS
    SELECT e.author_id aid, e.work_id wid, w.publication_year yr, w.cited_by_count c, w.subfield_id sf
    FROM read_parquet('{root}/authorship_edges/**/*.parquet') e
    JOIN read_parquet('{root}/works/**/*.parquet') w ON e.work_id = w.work_id
    WHERE w.publication_year IS NOT NULL""")
    return con.execute("SELECT count(*) FROM aw_raw").fetchone()[0]


def main(argv=None) -> int:
    import pandas as pd
    out_root = pathlib.Path(os.environ.get("SAR_OUT_ROOT", "").strip() or "")
    if not str(out_root) or not out_root.is_absolute():
        raise SystemExit("set $SAR_OUT_ROOT to an empty absolute directory under /private/tmp")
    out_root.mkdir(parents=True, exist_ok=True)
    report = {"generated": datetime.datetime.now().isoformat(timespec="seconds"), "extraction": ELEVEN}
    july = pd.read_parquet(str(require_readable(derived_root() / "u4_star_set_p10_80ev_2026-07-22" / "star_set") / "star_set.parquet"))
    cands_all, corr = rc.event_star_candidates()
    econ = [c for c in cands_all if c["field"] == "econ"]
    by_id = {c["author_id"]: c for c in econ}
    ctrl_rows = july[july.author_id.isin(by_id) & july.percentile.notna()]
    ctrl = [by_id[a] for a in ctrl_rows.author_id]
    july_pct = dict(zip(ctrl_rows.author_id, ctrl_rows.percentile.round(4)))
    july_cell = dict(zip(ctrl_rows.author_id, ctrl_rows.cell_n))

    t0 = time.time()
    con = restake_equiv.connect(out_root / "duck_tmp")
    n = load_aw_raw_11(con)
    report["aw_raw_rows"] = n
    print(f"[econ11] aw_raw {n:,} rows in {time.time() - t0:.0f} s", flush=True)
    # "fold": the July U4 machine folded alias ids through the U2 person map before summing stock
    # (u4_star_set_*/_reports/stock_fold_report.csv); _POOL_SQL ranks bare author ids. With
    # $SAR_ECON_FOLD=1 every author id in aw_raw, in the candidates and in the call tables is
    # mapped to its canonical person id first ((person, work) pairs de-duplicated).
    fold = os.environ.get("SAR_ECON_FOLD", "0") == "1"
    report["fold_person_map"] = fold
    pm = {}
    if fold:
        pmp = str(require_readable(derived_root() / "u2_person_map_11school_2026-07-16" / "person_map") / "data.parquet")
        pm = dict(con.execute(f"SELECT author_id, person_id FROM read_parquet('{pmp}')").fetchall())
        con.execute(f"CREATE TEMP TABLE pm AS SELECT author_id, person_id FROM read_parquet('{pmp}')")
        con.execute("""CREATE OR REPLACE TEMP TABLE aw_raw AS
            SELECT DISTINCT COALESCE(m.person_id, r.aid) aid, r.wid, r.yr, r.c, r.sf
            FROM aw_raw r LEFT JOIN pm m ON m.author_id = r.aid""")
        n2 = con.execute("SELECT count(*) FROM aw_raw").fetchone()[0]
        report["aw_raw_rows_folded"] = n2
        print(f"[econ11] folded through the person map: {n2:,} (person, work) rows; map {len(pm):,} ids", flush=True)
    f = lambda a: pm.get(a, a)   # noqa: E731

    # ---- C: control, no drops. Two conventions: "aug" = 72's forced subfield 2002 for economics
    # candidates (the 2026-08-15/28 fn-fix machine); "july" = the star's own modal subfield cell
    # (no forcing), which is how the July 2026 star set ranked the old-79 economics stars.
    conv = os.environ.get("SAR_ECON_CONVENTION", "july")
    if conv == "july":
        for c in ctrl:
            c["field"] = "econ_july"          # not "econ" -> _stats skips the ECON_SF re-rank
    report["convention"] = conv
    tag = conv + ("_fold" if fold else "")
    for c in ctrl:
        c["author_id_orig"] = c["author_id"]; c["author_id"] = f(c["author_id"])
    july_pct = {f(k): v for k, v in july_pct.items()}; july_cell = {f(k): v for k, v in july_cell.items()}
    L, pool_sql = restake_equiv._screening_modules()
    con.execute("CREATE OR REPLACE TEMP TABLE aw AS SELECT aid, yr, c, sf FROM aw_raw")
    before = restake_equiv._stats(con, ctrl, "control", L, pool_sql)
    rows = []
    for c in ctrl:
        b = before[c["author_id"]]
        rows.append({"author_id": c["author_id"], "name": c["name"], "arrival_true": c["arrival_true"],
                     "july_pct": july_pct[c["author_id"]], "july_cell_n": july_cell[c["author_id"]],
                     "machine_pct": b["pct"], "machine_cell_n": b["cell_n"], "machine_cell": b["cell"],
                     "aage": b["aage"], "equal_4dp": (b["pct"] is not None and abs(b["pct"] - july_pct[c["author_id"]]) < 5e-5)})
    rc._write_dict_csv(CAL / f"restake_econ11_control_{tag}_2026-10.csv", rows, list(rows[0].keys()))
    n_eq = sum(r["equal_4dp"] for r in rows)
    report["control"] = {"n": len(rows), "equal_4dp": n_eq,
                         "mismatch": [(r["author_id"], r["july_pct"], r["machine_pct"], r["july_cell_n"], r["machine_cell_n"]) for r in rows if not r["equal_4dp"]]}
    print(f"[econ11] control: {n_eq}/{len(rows)} percentiles equal to July (4 dp)", flush=True)

    # ---- R: the 17 rechecked stars ---------------------------------------------------------------
    # the 09-22 re-check targets (data/star_recheck_2026-09-22/, not shipped: restricted deposit)
    targets = [l.split(",")[0] for l in open(REPO / "data/star_recheck_2026-09-22/targets.csv").read().splitlines()[1:]]
    targets = [corr[t]["new_id"] if t in corr else t for t in targets]
    tc = [by_id[t] for t in targets if t in by_id]
    if os.environ.get("SAR_ECON_ALL", "0") == "1":      # rank every economics event star (p05 flags for all)
        tc = econ
        tag += "_all"
    for c in tc:
        c["author_id_orig"] = c.get("author_id_orig", c["author_id"]); c["author_id"] = f(c["author_id_orig"])
    if conv == "july":
        for c in tc:
            c["field"] = "econ_july"
    hist_drops, hist_adds, _ = rc.historical_calls()
    oct_drops, _ = rc.october_calls()
    hist_drops = {(f(a), w) for a, w in hist_drops}; oct_drops = {(f(a), w) for a, w in oct_drops}; hist_adds = {(f(a), w) for a, w in hist_adds}
    res_rows, after = rc.restake_with_adds(con, tc, hist_drops | oct_drops, hist_adds, out_root / "restake_econ11.csv",
                                           overrides=cleaned_works.first_pub_overrides())
    con.close()
    out = []
    for c, row in zip(tc, res_rows):
        a = after[c["author_id"]]
        out.append({"author_id": c["author_id"], "name": c["name"], "school": c["school"], "arrival_true": c["arrival_true"],
                    "before_stock": row[5], "before_pct": row[7], "before_pass_p10": row[8],
                    "after_stock": a["stock"], "after_cell": a["cell"], "after_cell_n": a["cell_n"], "after_pct": a["pct"],
                    "after_pass_p10": a["pass_p10"], "after_pass_p05": rc.pass_p05(a, L), "aage": a["aage"],
                    "gate_age": rc.caliber.gate_age(a["aage"]), "in_window": rc.caliber.in_window(c["arrival_true"]),
                    "event_keep": rc.caliber.event_verdict(after_pass=a["pass_p10"], aage=a["aage"], arrival_true=c["arrival_true"]),
                    "july_pct": july_pct.get(c["author_id"], ""), "note": a["note"]})
        print(f"  {c['author_id']} {c['name'][:26]:26s} before {row[7]} -> after {a['pct']} pass10={a['pass_p10']} keep={out[-1]['event_keep']}", flush=True)
    rc._write_dict_csv(CAL / f"restake_econ11_{tag}_2026-10.csv", out, list(out[0].keys()))
    report["rechecked"] = {r["author_id"]: {"after_pct": r["after_pct"], "keep": r["event_keep"]} for r in out}
    (CAL / f"restake_econ11_report_{tag}_2026-10.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
