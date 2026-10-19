"""Build the Panel 3 "leftbehind" A_far cell — the paper's Panel 3 — from the legacy
50_leftbehind_build.py (do the left-behind same-topic colleagues band together?).

A_far = same topic (both persons' dose_topic >= the discipline's positive-dose median, fixed before the run)
        AND neither person could reach the star before the star's arrival (neither is inside the star's pre-arrival two-hop network)
The legacy script builds five cells (A_far/A_near/B_nn/B_any/T_all); the paper uses only A_far,
so only that cell is ported here. Every panel-building SQL statement is byte-for-byte the legacy
50_leftbehind_build.py's; the post-build summary query is reduced to the four counts returned and
the temp_directory PRAGMA is omitted. The other changes are where inputs are read from
(SOURCES(paths)) and where the output parquet is written (out_dir).
"""
import sys, pathlib
import duckdb

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from analysis.lib.paths import load_paths


def SOURCES(p):
    # Since the 2026-08-28 freeze the canonical frames are the caliber rebuild, so the pair tables
    # must be the CAL pair tables — mixing the legacy (pre-caliber) pairs with the cal frames would
    # build a panel that matches neither canon. Chemistry/math-stats cal pair tables are shipped in
    # data/cal2026-08-28/frames/. The econ cal pairs_unified.csv (663 MB) is NOT shipped: it is
    # regenerated in ~24 s by the caliber chain (pipeline/stars/caliber_2026-08-28/run_cal_frames.py,
    # stage p2-econ; sha256 pinned in data/cal2026-08-28/frames/frames_run_report_2026-08-28.json)
    # — place it at output/cal_intermediates/pairs_unified.csv to run the econ cell; consumers skip
    # when it is absent.
    cal = p["repo_root"] / "data" / "cal2026-08-28" / "frames"; fr = p["frames"]
    return {
      "econ":       {"pairs": p["repo_root"] / "output/cal_intermediates/pairs_unified.csv",  "frame": fr / "p1_frame_econ.csv",       "p2": fr / "p2_becoming_econ.csv"},
      "chemistry":  {"pairs": cal / "pairs_none_chemistry.parquet",                           "frame": fr / "p1_frame_chemistry.csv",  "p2": fr / "p2_becoming_chemistry.csv"},
      "math_stats": {"pairs": cal / "pairs_none_math_stats.parquet",                          "frame": fr / "p1_frame_math_stats.csv", "p2": fr / "p2_becoming_math_stats.csv"},
    }


def _con():
    con = duckdb.connect(); con.execute("PRAGMA threads=6"); con.execute("PRAGMA memory_limit='14GB'"); return con


def build_afar(field: str, out_dir: pathlib.Path | None = None) -> dict:
    p = load_paths()
    src = SOURCES(p)[field]
    pairs, frame, p2 = str(src["pairs"]), str(src["frame"]), str(src["p2"])
    rd = "read_csv_auto" if pairs.endswith(".csv") else "read_parquet"
    con = _con()

    # dose table from the P1 frame (event x incumbent, max dose_topic; person id stripped of the P_ prefix)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE dose AS
        SELECT event_id, regexp_replace(incumbent_person_id,'^P_','') AS pid, max(dose_topic) AS dose
        FROM read_csv_auto('{frame}') WHERE dose_topic IS NOT NULL GROUP BY 1,2""")
    # Channel (fixed before the run): the Panel 2 table carries channel
    con.execute(f"""CREATE OR REPLACE TEMP TABLE ch AS
        SELECT event_id, regexp_replace(pid,'^P_','') AS pid,
               max(CASE WHEN channel IN ('network','both') THEN 1 ELSE 0 END) AS in_net,
               max(CASE WHEN y=1 AND tau<0 THEN 1 ELSE 0 END) AS pre_tie,
               max(CASE WHEN y=1 THEN 1 ELSE 0 END) AS any_tie
        FROM read_csv_auto('{p2}') GROUP BY 1,2""")
    med = con.execute("SELECT quantile_cont(dose,0.5) FROM dose WHERE dose>0").fetchone()[0]
    con.execute(f"""CREATE OR REPLACE TEMP TABLE pa AS
        SELECT DISTINCT pr.event_id, pr.i_id, pr.j_id,
               least(di.dose,dj.dose) AS dmin,
               ci.in_net AS net_i, cj.in_net AS net_j, ci.any_tie AS any_i, cj.any_tie AS any_j
        FROM {rd}('{pairs}') pr
        JOIN dose di ON di.event_id=pr.event_id AND di.pid=pr.i_id
        JOIN dose dj ON dj.event_id=pr.event_id AND dj.pid=pr.j_id
        JOIN ch ci ON ci.event_id=pr.event_id AND ci.pid=pr.i_id AND ci.pre_tie=0
        JOIN ch cj ON cj.event_id=pr.event_id AND cj.pid=pr.j_id AND cj.pre_tie=0""")
    TOPIC = f"dmin >= {med}"            # Same topic (fixed before the run)
    cond = f"{TOPIC} AND net_i=0 AND net_j=0"   # A_far: same topic + neither person within reach of the star's circle

    out_dir = pathlib.Path(out_dir) if out_dir is not None else p["output"] / "afar"
    out_dir.mkdir(parents=True, exist_ok=True)
    f_out = out_dir / f"p3_afar_{field}.parquet"
    con.execute(f"""COPY (
        WITH keep AS (SELECT event_id,i_id,j_id FROM pa WHERE {cond})
        SELECT CAST(DENSE_RANK() OVER (ORDER BY p.i_id||'_'||p.j_id||'@'||p.event_id)-1 AS INTEGER) AS grp,
               CAST(DENSE_RANK() OVER (ORDER BY p.event_id) AS INTEGER) AS ev,
               CAST(p.year AS INTEGER) AS year, CAST(p.y_any AS TINYINT) AS y, CAST(p.post AS TINYINT) AS D
        FROM {rd}('{pairs}') p JOIN keep k
          ON k.event_id=p.event_id AND k.i_id=p.i_id AND k.j_id=p.j_id
    ) TO '{f_out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")
    n, g, t, e = con.execute(f"""SELECT count(*), count(DISTINCT grp), sum(y), count(DISTINCT ev)
        FROM read_parquet('{f_out}')""").fetchone()
    return {"cut": round(float(med), 4), "rows": n, "pairs": g, "ties": int(t or 0), "events": e}


if __name__ == "__main__":
    field = sys.argv[1]
    out = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else None
    print(build_afar(field, out_dir=out))
