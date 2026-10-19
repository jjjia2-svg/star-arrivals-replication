#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_p3_full_variants.py — the two D7 variants of the FULL Panel 3 pair panel (the cloud cells
P3_econ_fnfix / P3_fnfix_chemistry and the local P3_fnfix_math_stats), built from the pair tables
at frame-build time, where pairs still carry event ids:

  p05      the same panel restricted to the events whose star passes the top-5% cut
           (data/cal2026-10/events_{field}_cal2026-10_p05.csv): rows of other events dropped,
           then pipeline/frames/make_slim.py's verbatim grp/ev/year/y/D projection;
  dosebin3 the three-bin dose analogue of run_p1_variant.R's `dosebin3` (2026-09-22) for pairs:
           each pair's dose is the smaller of its two incumbents' similarity doses with the star
           (dmin, exactly analysis/robustness/p3_afar/build_afar.py's pair dose from the Panel 1
           frame), the cut points are the 1/3 and 2/3 quantiles of the positive pair doses (one
           dose per pair = i x j x event), pairs with no dose or a zero dose stay at 0, and the
           treatment column becomes D = bin x post (0/1/2/3), so run_p3.R estimates the effect
           per tercile step. Everything else is the verbatim slim.

Controls (--control): the 08-28 inputs with the FULL event tables must reproduce data/frames/
p3_slim_{field}.parquet content-equal for the p05 path (the filter is then a no-op), and the
dosebin path run with --bins 1 (one bin: D = 1 x post) must reproduce it too.

    build_p3_full_variants.py --field chemistry --pairs data/cal2026-10/frames_chemistry/pairs_none_chemistry.parquet \
        --frame data/cal2026-10/frames_chemistry/p1_frame_chemistry.csv --events-dir data/cal2026-10 --out DIR --stage DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

import duckdb

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))
from pipeline.frames.make_slim import make_slim, content_equal   # noqa: E402
from filter_frames import event_ids                              # noqa: E402


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def filtered_pairs(field: str, pairs: pathlib.Path, keep: set[str], out: pathlib.Path) -> dict:
    """The pair table restricted to `keep` events, in the format make_slim reads for the field."""
    con = duckdb.connect()
    rd = "read_csv_auto" if pairs.suffix == ".csv" else "read_parquet"
    con.execute("CREATE TABLE keep (event_id VARCHAR)")
    con.executemany("INSERT INTO keep VALUES (?)", [(k,) for k in sorted(keep)])
    n_in = con.execute(f"SELECT count(*) FROM {rd}('{pairs}')").fetchone()[0]
    ev_in = con.execute(f"SELECT count(DISTINCT event_id) FROM {rd}('{pairs}')").fetchone()[0]
    fmt = "(FORMAT CSV, HEADER)" if field == "econ" else "(FORMAT PARQUET, COMPRESSION ZSTD)"
    con.execute(f"COPY (SELECT p.* FROM {rd}('{pairs}') p JOIN keep USING (event_id)) TO '{out}' {fmt}")
    rd2 = "read_csv_auto" if out.suffix == ".csv" else "read_parquet"
    n_out, ev_out = con.execute(f"SELECT count(*), count(DISTINCT event_id) FROM {rd2}('{out}')").fetchone()
    con.close()
    return {"rows_in": n_in, "events_in": ev_in, "rows_out": n_out, "events_out": ev_out}


def dosebin_slim(field: str, pairs: pathlib.Path, frame: pathlib.Path, out: pathlib.Path, bins: int) -> dict:
    con = duckdb.connect()
    rd = "read_csv_auto" if pairs.suffix == ".csv" else "read_parquet"
    con.execute(f"""CREATE TEMP TABLE dose AS
        SELECT event_id, regexp_replace(incumbent_person_id,'^P_','') AS pid, max(dose_topic) AS dose
        FROM read_csv_auto('{frame}') WHERE dose_topic IS NOT NULL GROUP BY 1,2""")
    con.execute(f"""CREATE TEMP TABLE pd AS
        SELECT DISTINCT pr.event_id, pr.i_id, pr.j_id, least(di.dose, dj.dose) AS dmin
        FROM (SELECT DISTINCT event_id, i_id, j_id FROM {rd}('{pairs}')) pr
        LEFT JOIN dose di ON di.event_id=pr.event_id AND di.pid=pr.i_id
        LEFT JOIN dose dj ON dj.event_id=pr.event_id AND dj.pid=pr.j_id""")
    if bins == 1:
        cuts = []
        con.execute("CREATE TEMP TABLE pb AS SELECT event_id, i_id, j_id, 1 AS bin FROM pd")
    else:
        qs = [k / bins for k in range(1, bins)]
        cuts = [con.execute(f"SELECT quantile_cont(dmin, {q}) FROM pd WHERE dmin > 0").fetchone()[0] for q in qs]
        case = "CASE WHEN dmin IS NULL OR dmin <= 0 THEN 0 " + " ".join(
            f"WHEN dmin <= {c} THEN {i + 1}" for i, c in enumerate(cuts)) + f" ELSE {bins} END"
        con.execute(f"CREATE TEMP TABLE pb AS SELECT event_id, i_id, j_id, {case} AS bin FROM pd")
    n_by_bin = dict(con.execute("SELECT bin, count(*) FROM pb GROUP BY 1 ORDER BY 1").fetchall())
    # the verbatim slim projection (pipeline/frames/make_slim.py), with D = bin x post
    if field == "econ":
        sql = f"""SELECT CAST(DENSE_RANK() OVER (ORDER BY r.i_id || '_' || r.j_id || '@' || r.event_id) - 1 AS INTEGER) AS grp,
                         CAST(DENSE_RANK() OVER (ORDER BY r.event_id) AS INTEGER) AS ev,
                         CAST(r.year AS INTEGER) AS year, CAST(r.y_any AS TINYINT) AS y, CAST(b.bin * r.post AS TINYINT) AS D
                  FROM {rd}('{pairs}') r JOIN pb b USING (i_id, j_id, event_id)"""
    else:
        sql = f"""WITH p AS (SELECT DISTINCT i_id, j_id, event_id FROM {rd}('{pairs}')),
                       g AS (SELECT row_number() OVER (ORDER BY event_id, i_id, j_id) AS grp,
                                    dense_rank() OVER (ORDER BY event_id) AS ev, i_id, j_id, event_id FROM p)
                  SELECT CAST(g.grp AS INTEGER) AS grp, CAST(g.ev AS INTEGER) AS ev,
                         CAST(r.year AS INTEGER) AS year, CAST(r.y_any AS TINYINT) AS y, CAST(b.bin * r.post AS TINYINT) AS D
                  FROM {rd}('{pairs}') r JOIN g USING (i_id, j_id, event_id) JOIN pb b USING (i_id, j_id, event_id)"""
    con.execute(f"COPY ({sql}) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    n, g, t, e, dmax = con.execute(f"SELECT count(*), count(DISTINCT grp), sum(y), count(DISTINCT ev), max(D) FROM read_parquet('{out}')").fetchone()
    con.close()
    return {"bins": bins, "cuts": cuts, "pairs_by_bin": {int(k): int(v) for k, v in n_by_bin.items()},
            "rows": n, "pairs": g, "ties": int(t), "events": e, "max_D": int(dmax), "sha256": sha(out)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--field", required=True, choices=["econ", "chemistry", "math_stats"])
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--frame", required=True, help="Panel 1 frame (dose_topic per incumbent x event)")
    ap.add_argument("--events-dir", default=str(REPO / "data/cal2026-10"))
    ap.add_argument("--suffix", default="_p05", help="event-table suffix; '' = full tables (control)")
    ap.add_argument("--events-file", default=None, help="explicit event table instead of <events-dir>/events_<field>_cal2026-10<suffix>.csv (the 08-28 control)")
    ap.add_argument("--bins", type=int, default=3)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stage", required=True)
    ap.add_argument("--control", action="store_true", help="compare both products with data/frames/p3_slim_<field>.parquet")
    a = ap.parse_args(argv)
    f, pairs, frame = a.field, pathlib.Path(a.pairs), pathlib.Path(a.frame)
    out, stage = pathlib.Path(a.out), pathlib.Path(a.stage)
    out.mkdir(parents=True, exist_ok=True); stage.mkdir(parents=True, exist_ok=True)
    rep = {"field": f, "inputs": {"pairs": str(pairs), "pairs_sha256": sha(pairs), "frame": str(frame), "frame_sha256": sha(frame),
                                  "events": f"events_{f}_cal2026-10{a.suffix}.csv"}, "suffix": a.suffix}
    if a.events_file:
        import csv
        with open(a.events_file, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        keep = {r["event_id"] for r in rows} if f == "econ" else {f"{r['author_id']}:{r['school']}" for r in rows}
        rep["inputs"]["events"] = str(a.events_file)
    else:
        keep = event_ids(pathlib.Path(a.events_dir), f, a.suffix)
    rep["events_kept"] = len(keep)
    fp = stage / (f"pairs_{f}{a.suffix or '_all'}.csv" if f == "econ" else f"pairs_{f}{a.suffix or '_all'}.parquet")
    rep["p05_filter"] = filtered_pairs(f, pairs, keep, fp)
    tag = a.suffix.lstrip("_") or "all"
    slim = out / f"p3_slim_{f}_{tag}.parquet"
    st = make_slim(f, fp, slim)
    rep["p05_slim"] = {k: v for k, v in st.items() if k != "produced"} | {"file": slim.name, "sha256": sha(slim)}
    dose_out = out / f"p3_slim_{f}_dosebin{a.bins}.parquet"
    rep["dosebin"] = dosebin_slim(f, pairs, frame, dose_out, a.bins) | {"file": dose_out.name}
    if a.control:
        ref = REPO / "data/frames" / f"p3_slim_{f}.parquet"
        rep["control"] = {"p05_all_events_vs_frozen_slim": content_equal(slim, ref),
                          "dosebin_vs_frozen_slim": content_equal(dose_out, ref) if a.bins == 1 else "n/a (--bins 1 is the control)"}
    (out / f"p3_full_variants_report_{f}.json").write_text(json.dumps(rep, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("events_kept", "p05_filter", "dosebin", "control") if k in rep}, indent=0, default=str)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
