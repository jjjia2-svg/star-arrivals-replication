#!/usr/bin/env bash
# analysis/robustness/sensitivity/run_p3pos_sensitivity.sh — Panel 3 event-level checks on the
# CURRENT specification (dose > 0), 2026-09-10.
#
# The frozen departure A/B and double-star cells in data/robustness_2026-08-29_b/ were built on
# the retired median cut (86/33/31 A_far events). This re-stages the SAME builders — the SAME
# code, selected by `--spec pos` — on the paper's Panel 3 frames since 2026-08-30,
# data/frames/p3_afar_pos_{econ,chemistry,math_stats}.parquet (108/38/32 events), and freezes
# under data/robustness_2026-09-10_p3pos/. Only the Panel 3 A_far cells are estimated here: the
# P1/P2 variants do not depend on the cut, so the builders' P1/P2 output must come out
# byte-identical to the 2026-08-29 run — that identity is CHECKED below and is this batch's
# spec-independence control, on top of each builder's own controls (map content-equality proof
# against the frozen pos frame, no-op byte-identity of the line surgery).
#
#   0. afar_event_map.py --spec pos     proven ev -> event_id maps for the pos frames. The econ
#                                       map needs pairs_unified.csv (643 MB, not shipped): it is
#                                       used from output/cal_intermediates/ when that is a real
#                                       file, regenerated through the caliber shadow when the
#                                       data disk is mounted, and otherwise NOT built — nothing is
#                                       inferred in its place, and the econ cells are then
#                                       recorded as NOT RUN, never silently skipped.
#   1. build_departure.py --spec pos    star-departure A/B (econ only) + cells
#                                       P3depA_pos_econ_A_far / P3depB_pos_econ_A_far
#   2. build_doublestar.py --spec pos   double-star overlap drops, fields whose pos map exists +
#                                       cells P3ds_pos_{field}_A_far
#   3. spec-independence control        P1/P2 staged sha256 == the 2026-08-29 build reports
#   4. MANIFEST                         tools/write_manifest.py over data/robustness_2026-09-10_p3pos/
# Estimation is by the VERBATIM analysis/estimation/run_p3_tp.R only. Local, no AWS.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"; cd "$REPO"
PY="$REPO/setup/.venv/bin/python"; [ -x "$PY" ] || { echo "setup/.venv missing (run bash setup/install_py.sh)"; exit 1; }
E=analysis/estimation
S=analysis/robustness/sensitivity
B=data/robustness_2026-09-10_p3pos
OLD=data/robustness_2026-08-29_b
export POLARS_MAX_THREADS=4
DEP_STAGE=/private/tmp/sar_departure_2026-09-10_pos
DS_STAGE=/private/tmp/sar_doublestar_2026-09-10_pos
PAIRS_ECON=output/cal_intermediates/pairs_unified.csv
mkdir -p "$B"

echo "== 0. A_far event maps on the pos frames (content-equality proofs against p3_afar_pos_*)"
MAP_ARGS=(--spec pos)
SSD_DERIVED="$("$PY" -c 'import os,pathlib; from analysis.lib.paths import load_paths; r=os.environ.get("SAR_SSD_ROOT") or str(load_paths()["ssd_root"]); print(pathlib.Path(r)/"derived")')"
if [ -f "$PAIRS_ECON" ]; then                      # -f follows symlinks: a dangling link is NOT a file
  echo "   econ pairs: using $PAIRS_ECON"; MAP_ARGS+=(--pairs-econ "$PAIRS_ECON")
elif [ -d "$SSD_DERIVED" ]; then
  echo "   econ pairs: regenerating through the caliber shadow (data disk mounted at $SSD_DERIVED)"; MAP_ARGS+=(--regen-econ)
else
  echo "   econ pairs: $PAIRS_ECON is not a file and the data disk is not mounted ($SSD_DERIVED absent)"
  echo "   -> the econ pos map is NOT built; econ cells will be recorded as NOT RUN"
fi
"$PY" $S/afar_event_map.py "${MAP_ARGS[@]}"
ECON_MAP=$B/afar_event_map/afar_event_map_econ.csv

echo "== 1. departure A/B on the pos frame (econ only)"
if [ -f "$ECON_MAP" ]; then
  rm -f "$B/departure/NOT_RUN.md"
  "$PY" $S/build_departure.py --spec pos --stage "$DEP_STAGE"
  export SAR_OUT=$B/departure/estimates
  Rscript $E/run_p3_tp.R P3depA_pos_econ_A_far "$DEP_STAGE/p3_afar_dep_A.parquet"
  Rscript $E/run_p3_tp.R P3depB_pos_econ_A_far "$DEP_STAGE/p3_afar_dep_B.parquet"
  unset SAR_OUT
else
  mkdir -p "$B/departure"
  cat > "$B/departure/NOT_RUN.md" <<'MD'
# departure A/B on the dose>0 frame — NOT RUN

The departure check is economics-only, and the economics pos frame has no proven
ev -> event_id map: `afar_event_map.py --spec pos` needs `pairs_unified.csv` (643 MB, not
shipped), which is regenerated through the caliber shadow by the `p2-econ` stage — and that
stage reads `<ssd_root>/derived/u1_full_11school_2026-07-16/authorship_edges` from the data
disk. On the day of this batch `output/cal_intermediates/pairs_unified.csv` was a dangling
symlink into a deleted 2026-08-30 scratch root and the data disk was not mounted. No map was
inferred from the median-cut map (the pos frame has 108 events, the median frame 86; the
DENSE_RANK codes differ), so no cell was estimated.

To complete: mount the data disk (or point $SAR_SSD_ROOT at a copy) and re-run
`bash analysis/robustness/sensitivity/run_p3pos_sensitivity.sh` — it regenerates the pairs,
proves the econ map, builds A/B and estimates P3depA_pos_econ_A_far / P3depB_pos_econ_A_far.
MD
  echo "   NOT RUN (no proven econ pos map) — $B/departure/NOT_RUN.md written"
fi

echo "== 2. double-star overlap drops on the pos frames (fields whose proven map exists)"
FIELDS=""
for F in econ chemistry math_stats; do
  [ -f "$B/afar_event_map/afar_event_map_$F.csv" ] && FIELDS="$FIELDS,$F"
done
FIELDS="${FIELDS#,}"; echo "   fields with a proven pos map: $FIELDS"
"$PY" $S/build_doublestar.py --spec pos --stage "$DS_STAGE" --fields "$FIELDS" --events-dir data/cal2026-10 --frames-dir data/frames --pairs-none-math data/cal2026-08-28/frames/pairs_none_math_stats.parquet
export SAR_OUT=$B/doublestar/estimates
for F in ${FIELDS//,/ }; do
  Rscript $E/run_p3_tp.R "P3ds_pos_${F}_A_far" "$DS_STAGE/p3_afar_ds_$F.parquet"
done
unset SAR_OUT

echo "== 3. spec-independence control: P1/P2 (and P3 math full) staged files == the 2026-08-29 run"
"$PY" - "$B" "$OLD" <<'PYEOF'
import json, pathlib, sys
new_root, old_root = map(pathlib.Path, sys.argv[1:3])
checked, bad = 0, []
for part, rep in (("departure", "departure_build_report.json"), ("doublestar", "doublestar_build_report.json")):
    n = new_root / part / rep
    if not n.is_file():
        print(f"   {part}: no pos build report (NOT RUN) — nothing to compare"); continue
    new = json.load(n.open())["staged_sha256"]; old = json.load((old_root / part / rep).open())["staged_sha256"]
    for name, h in new.items():
        if name.startswith("p3_afar_"):
            continue                       # the A_far variants are the point of this batch: they differ by design
        checked += 1
        if old.get(name) != h:
            bad.append((part, name, old.get(name), h))
    print(f"   {part}: {sum(1 for k in new if not k.startswith('p3_afar_'))} cut-independent staged files compared")
assert not bad, f"spec-independence control FAILED: {bad}"
print(f"SPEC_INDEPENDENCE_OK ({checked} files byte-identical to the 2026-08-29 stage)")
PYEOF

echo "== 4. MANIFEST"
"$PY" tools/write_manifest.py "$B"
"$PY" tools/verify_manifest.py "$B/MANIFEST.sha256"
echo "P3POS_SENSITIVITY_OK"
