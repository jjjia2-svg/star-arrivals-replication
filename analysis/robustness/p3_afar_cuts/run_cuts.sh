#!/usr/bin/env bash
# analysis/robustness/p3_afar_cuts/run_cuts.sh — the Panel 3 (A_far) topic-cut grid + the pos-cell
# date-shift test, one entry point. REPO-AUTHORED, added 2026-09-23 for the October caliber.
#
# PROVENANCE. The frozen data/robustness_afar_cuts_2026-08-30/ was produced on 2026-08-30 (session
# f071d8a9) by inline commands never committed (build_afar_cut.py's docstring already names a
# "run_cuts.sh" that only ever lived in /tmp):
#   frames    setup/.venv/bin/python analysis/robustness/p3_afar_cuts/build_afar_cut.py <field> <cut> output/afar_cuts
#   estimates /tmp/run_cuts.sh (06:49:45Z):
#             export SAR_OUT=output/afar_cuts/est
#             for F in ...; do for C in med pos abs04 p75; do
#               Rscript analysis/estimation/run_p3_tp.R P3cut_${C}_${F} output/afar_cuts/p3_afar_${C}_${F}.parquet
#   predate   /tmp/pos_predate.sh (07:21:04Z):
#             export SAR_OUT=output/afar_cuts/predate
#             for F in econ chemistry math_stats; do for S in 0 2; do
#               Rscript analysis/robustness/predate/run_predate.R p3tp P3pos_s${S}_${F} output/afar_cuts/p3_afar_pos_${F}.parquet $S
#   grid      an inline python snippet (06:57:48Z, columns reproduced in step D below)
# This file is those commands line for line with only paths changed, plus the controls:
#   * the frames are built with EXPLICIT October sources (data/frames p1/p2 + pairs_none_<field>.parquet,
#     econ pairs = output/cal_intermediates/cal2026-10/pairs_unified.csv) through build_afar_cut.build(...,
#     sources=...) — the same call the October golds' producer (pipeline/stars/caliber_2026-10/
#     run_cal_estimates.py build_cuts) used; the CLI's default SOURCES still point at the 08-28 pair tables;
#   * pos/med frames must be content-equal to data/frames; pos/med cells must be compare_json-EQUAL to
#     analysis/expected/P3{pos,med}_<field>_A_far.json; the shift-0 predate control runs under the gold's
#     own label (P3cut_pos_<field>, as analysis/run_all.sh does) and must be EQUAL to the P3pos gold.
#     (The frozen run labelled its control P3pos_s0_<field>, which differs from the gold on `label` only.)
#   * the predate cells read the CANONICAL data/frames/p3_afar_pos_<field>.parquet.
# Any control that is not EQUAL stops the battery (exit 3); nothing is patched.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"; cd "$REPO"
PY="$REPO/setup/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
OUTDIR="${SAR_AFAR_CUTS_OUTDIR:-data/cal2026-10/robustness/afar_cuts}"
PAIRS_ECON="${SAR_PAIRS_ECON:-output/cal_intermediates/cal2026-10/pairs_unified.csv}"
D=data/frames; X=analysis/expected
FR="$OUTDIR/frames"; EST="$OUTDIR/estimates"; PD="$OUTDIR/predate"
mkdir -p "$FR" "$EST" "$PD/control"
LOG="$OUTDIR/runlog.log"; : > "$LOG"
ck() { "$PY" -m analysis.lib.compare_json "$1" "$2" >> "$LOG" 2>&1 \
         && echo "CONTROL EQUAL: $(basename "$1" .json) vs $(basename "$2")" | tee -a "$LOG" \
         || { echo "CONTROL NOT EQUAL: $1 vs $2 — see $LOG"; exit 3; }; }
cell() { local lab="$1" fr="$2"; echo "== $lab" | tee -a "$LOG"
         SAR_OUT="$EST" Rscript analysis/estimation/run_p3_tp.R "$lab" "$fr" >> "$LOG" 2>&1 \
           || { echo "FAILED: $lab — see $LOG"; exit 2; }; }
pdcell() { local out="$1" lab="$2" fr="$3" s="$4"; echo "== $lab (shift $s)" | tee -a "$LOG"
         SAR_OUT="$out" Rscript analysis/robustness/predate/run_predate.R p3tp "$lab" "$fr" "$s" >> "$LOG" 2>&1 \
           || { echo "FAILED: $lab — see $LOG"; exit 2; }; }
build() {  # $1 = space-separated cut specs; builds all three fields; controls pos/med against data/frames
"$PY" - "$FR" "$PAIRS_ECON" "$OUTDIR/cuts_build.json" $1 <<'PYEOF' 2>&1 | tee -a "$LOG"
import sys, json, pathlib, importlib.util
REPO = pathlib.Path.cwd(); sys.path.insert(0, str(REPO))
sp = importlib.util.spec_from_file_location("afar_cut", REPO / "analysis/robustness/p3_afar_cuts/build_afar_cut.py")
afar_cut = importlib.util.module_from_spec(sp); sp.loader.exec_module(afar_cut)
from tools.content_equal import content_equal
out, pairs_econ, repf, specs = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3]), sys.argv[4:]
frames = REPO / "data/frames"
rep = json.loads(repf.read_text()) if repf.exists() else {"sources": {}, "cuts": {}, "control_content_equal": {}}
for f in ("econ", "chemistry", "math_stats"):
    pairs = pairs_econ if f == "econ" else frames / f"pairs_none_{f}.parquet"      # as run_cal_estimates.build_cuts
    src = {"pairs": pairs, "frame": frames / f"p1_frame_{f}.csv", "p2": frames / f"p2_becoming_{f}.csv"}
    rep["sources"][f] = {k: str(v) for k, v in src.items()}
    for spec in specs:
        r = afar_cut.build(f, spec, out, sources=src)
        assert "skipped" not in r, r
        rep["cuts"][f"{spec}_{f}"] = r
        print(f"cut {spec}/{f}: rows={r['rows']} pairs={r['pairs']} ties={r['ties']} events={r['events']} cut={r['cut_full']}")
        if spec in ("pos", "med"):
            name = f"p3_afar_{spec}_{f}.parquet"
            res = content_equal(out / name, frames / name)
            rep["control_content_equal"][name] = bool(res.equal)
            print(f"  control {name} vs data/frames: {'EQUAL' if res.equal else 'NOT EQUAL: ' + res.detail}")
repf.write_text(json.dumps(rep, indent=1, default=str))
bad = [k for k, v in rep["control_content_equal"].items() if not v]
print("FRAMES_CONTROL", "EQUAL" if not bad else f"NOT_EQUAL {bad}")
sys.exit(3 if bad else 0)
PYEOF
}

# ---- A/B/C controls first ------------------------------------------------------------------------
build "pos med" || { echo "STOP: pos/med frame control failed"; exit 3; }
for F in chemistry math_stats econ; do for C in pos med; do
  cell P3cut_${C}_${F} "$FR/p3_afar_${C}_${F}.parquet"
  ck "$EST/P3cut_${C}_${F}.json" "$X/P3${C}_${F}_A_far.json"
done; done
for F in chemistry math_stats econ; do
  pdcell "$PD/control" P3cut_pos_${F} "$D/p3_afar_pos_${F}.parquet" 0
  ck "$PD/control/P3cut_pos_${F}.json" "$X/P3pos_${F}_A_far.json"
done
echo "CONTROLS_EQUAL 6 cells + 3 predate shift-0 + 6 frames" | tee -a "$LOG"

# ---- the grid cells and the shifted cells --------------------------------------------------------
build "abs04 p75"
for F in chemistry math_stats econ; do for C in abs04 p75; do
  cell P3cut_${C}_${F} "$FR/p3_afar_${C}_${F}.parquet"
done; done
for F in chemistry math_stats econ; do
  pdcell "$PD" P3pos_s2_${F} "$D/p3_afar_pos_${F}.parquet" 2
done

# ---- D. the grid CSV (the frozen snippet's columns; obs/pairs from the frames, cut from the build) ---
"$PY" - "$EST" "$FR" "$OUTDIR/cuts_build.json" "$OUTDIR/afar_cut_grid.csv" <<'PYEOF' 2>&1 | tee -a "$LOG"
import sys, json, csv, pathlib, duckdb
est, fr, build, grid = (pathlib.Path(a) for a in sys.argv[1:5])
cuts = json.loads(build.read_text())["cuts"]
rows = []
for fld in ("econ", "chemistry", "math_stats"):
    for c in ("pos", "med", "abs04", "p75"):
        d = json.load(open(est / f"P3cut_{c}_{fld}.json")); pc, ec = d["pair_cluster"], d["event_cluster"]
        pq = (fr / f"p3_afar_{c}_{fld}.parquet").as_posix()
        n, g = duckdb.sql(f"SELECT count(*), count(DISTINCT grp) FROM read_parquet('{pq}')").fetchone()
        rows.append(dict(field=fld, cut_spec=c, cut=repr(cuts[f"{c}_{fld}"]["cut_full"]), obs=n, pairs=g,
                         ate_pp=round(pc["ate"] * 100, 4), se_pair_pp=round(pc["se"] * 100, 4),
                         se_event_pp=round((ec.get("se") or 0) * 100, 4),   # frozen grid printed 0 here (its dig('se_ev') never matched)
                         ci_lo_pp=round(pc["lb"] * 100, 4), ci_hi_pp=round(pc["ub"] * 100, 4),
                         p_joint_effects=pc["p_joint_effects"]))
with open(grid, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
for r in rows:
    print(f"  {r['field']:<11}{r['cut_spec']:<7}cut={r['cut']:<22} pairs={r['pairs']:>7,}  ate={r['ate_pp']:>+8.4f} pp (SE {r['se_pair_pp']:.4f}) p={r['p_joint_effects']:.4g}")
print(f"grid written: {grid} ({len(rows)} rows)")
PYEOF
echo "AFAR_CUTS_OK" | tee -a "$LOG"
