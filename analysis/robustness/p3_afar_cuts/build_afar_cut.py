"""build_afar_cut.py — rebuild the Panel 3 A_far cell at ALTERNATIVE topic cuts.

WHY THIS EXISTS
---------------
UNTIL 2026-08-30 the paper's Panel 3 kept pairs whose minimum similarity dose was at
or above the discipline's MEDIAN POSITIVE dose; since 2026-08-30 the paper's cell is
`pos` (dose > 0) and `med` is the robustness/control cell. A design-history search on 2026-08-30 found no
recorded argument for that cut: what was argued in 2026-08 was a per-discipline
quantile versus a single absolute number, never "median versus any positive
overlap", and the author never commented on it. The 2026-08-17 grid that did span
cuts was run WITHOUT the network condition, so no A_far estimate exists at any cut
other than the median. This script fills that hole.

WHAT IS AND IS NOT COPIED
-------------------------
Every panel-building SQL statement is byte-for-byte ../p3_afar/build_afar.py's,
which is itself byte-for-byte the legacy 50_leftbehind_build.py's. The ONLY change
is that the topic threshold is a parameter instead of the hard-coded median, and
that `pos` compares with `>` rather than `>=`. Sources, joins, exclusions, the
DENSE_RANK id construction and the output schema are untouched, so a run at
cut_spec="med" must reproduce the canonical frame exactly — that is the control,
and run_cuts.sh checks it before trusting anything else.

CUTS
----
  pos    dmin > 0            both incumbents share at least one subfield with the star — THE PAPER'S
                             Panel 3 since 2026-08-30 (golds analysis/expected/P3pos_*_A_far.json)
  med    dmin >= q50(dose>0) the former specification, kept as the control: it must reproduce
                             the frozen `afar`-stage frames exactly (golds P3med_* == P3lb_*)
  abs04  dmin >= 0.4
  p75    dmin >= q75(dose>0)

REGISTRATION (2026-09-10): the `pos` and `med` frames this script writes are frozen in
data/frames/ (data/MANIFEST.sha256) as DERIVED frames — produced by this analysis script,
not by a frames-layer stage — and their six golds are in analysis/expected/ (see
tests/test_afar_cuts_2026_08_30.py). abs04 and p75 remain robustness-grid cells only.
"""
import sys, json, pathlib
import duckdb

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from analysis.lib.paths import load_paths
from analysis.robustness.p3_afar.build_afar import SOURCES, _con

CUTS = ("pos", "med", "abs04", "p75")
# The medians the canonical frames were built with (data/frames/p3_afar_counts.csv, 2026-08-28).
# FULL PRECISION, not the 4-dp values printed in p3_afar_counts.csv: rounding math_stats to
# 0.0897 admits 24 extra pairs (2,794 vs the frozen 2,770), because its dose distribution is
# dense right at the threshold. Measured 2026-08-30 on the caliber frames.
PIN_CANON = {"econ":       0.33404650205120173,
             "chemistry":  0.338776171207428,
             "math_stats": 0.08974236053931156}


def _threshold(con, spec):
    """(sql_predicate, numeric_cut_or_None) for the dmin column."""
    if spec == "pos":
        return "dmin > 0", 0.0
    if spec == "abs04":
        return "dmin >= 0.4", 0.4
    if spec.startswith("fixed:"):
        # A PINNED cut. The canonical builder recomputes the median at build time, so the
        # threshold moves whenever the dose table moves: the 2026-08-28 caliber change shifted
        # econ .3332 -> .3340, chem .3427 -> .3388, math .0885 -> .0897, silently changing which
        # pairs are in the panel. Pinning removes that. PIN_CANON below reproduces the frozen
        # frames exactly (verified 2026-08-30), so pinning is a no-op today and a guarantee later.
        v = float(spec.split(":", 1)[1])
        return f"dmin >= {v}", v
    q = 0.75 if spec == "p75" else 0.5
    v = con.execute(f"SELECT quantile_cont(dose,{q}) FROM dose WHERE dose>0").fetchone()[0]
    return f"dmin >= {v}", float(v)


def build(field: str, cut_spec: str, out_dir: pathlib.Path, sources: dict | None = None) -> dict:
    """`sources` (2026-09-10): an explicit {"pairs", "frame", "p2"} triple that REPLACES
    SOURCES(p)[field] — the ± research-centre check (sensitivity/run_nocentre_afar_pos.py) builds
    the pos cell from VARIANT frames staged in scratch. None (the default, the only caller path
    before 2026-09-10) is the canon path, unchanged; nothing else in this function reads it."""
    assert cut_spec in CUTS or cut_spec.startswith("fixed:"), cut_spec
    if sources is None:
        src = SOURCES(load_paths())[field]
    else:
        assert set(sources) >= {"pairs", "frame", "p2"}, sorted(sources)
        src = sources
    pairs, frame, p2 = str(src["pairs"]), str(src["frame"]), str(src["p2"])
    if not pathlib.Path(pairs).exists():
        return {"field": field, "cut_spec": cut_spec, "skipped": f"pairs table absent: {pairs}"}
    rd = "read_csv_auto" if pairs.endswith(".csv") else "read_parquet"
    con = _con()

    # ---- verbatim from build_afar.py ----
    con.execute(f"""CREATE OR REPLACE TEMP TABLE dose AS
        SELECT event_id, regexp_replace(incumbent_person_id,'^P_','') AS pid, max(dose_topic) AS dose
        FROM read_csv_auto('{frame}') WHERE dose_topic IS NOT NULL GROUP BY 1,2""")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE ch AS
        SELECT event_id, regexp_replace(pid,'^P_','') AS pid,
               max(CASE WHEN channel IN ('network','both') THEN 1 ELSE 0 END) AS in_net,
               max(CASE WHEN y=1 AND tau<0 THEN 1 ELSE 0 END) AS pre_tie,
               max(CASE WHEN y=1 THEN 1 ELSE 0 END) AS any_tie
        FROM read_csv_auto('{p2}') GROUP BY 1,2""")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE pa AS
        SELECT DISTINCT pr.event_id, pr.i_id, pr.j_id,
               least(di.dose,dj.dose) AS dmin,
               ci.in_net AS net_i, cj.in_net AS net_j, ci.any_tie AS any_i, cj.any_tie AS any_j
        FROM {rd}('{pairs}') pr
        JOIN dose di ON di.event_id=pr.event_id AND di.pid=pr.i_id
        JOIN dose dj ON dj.event_id=pr.event_id AND dj.pid=pr.j_id
        JOIN ch ci ON ci.event_id=pr.event_id AND ci.pid=pr.i_id AND ci.pre_tie=0
        JOIN ch cj ON cj.event_id=pr.event_id AND cj.pid=pr.j_id AND cj.pre_tie=0""")
    # ---- the one parameterised line ----
    TOPIC, cut_val = _threshold(con, cut_spec)
    cond = f"{TOPIC} AND net_i=0 AND net_j=0"   # A_far: same topic + neither person within reach of the star's circle

    out_dir = pathlib.Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    f_out = out_dir / f"p3_afar_{cut_spec}_{field}.parquet"
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
    return {"field": field, "cut_spec": cut_spec, "cut": round(cut_val, 4) if cut_val is not None else None,
            "cut_full": cut_val,   # full precision (2026-09-23: data/frames/p3_afar_counts_by_spec.csv carries it)
            "rows": n, "pairs": g, "ties": int(t or 0), "events": e, "frame": str(f_out)}


if __name__ == "__main__":
    field, cut_spec = sys.argv[1], sys.argv[2]
    out = pathlib.Path(sys.argv[3]) if len(sys.argv) > 3 else load_paths()["output"] / "afar_cuts"
    print(json.dumps(build(field, cut_spec, out), ensure_ascii=False))
