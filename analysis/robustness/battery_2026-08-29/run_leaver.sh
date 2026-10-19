#!/usr/bin/env bash
# analysis/robustness/battery_2026-08-29/run_leaver.sh — T7 leaver check (post-departure empty
# years filled back in as zeros), the entry point that the 2026-08-31 freeze never had.
# Runs the verbatim battery driver in `full` mode with variant fill0leave for the three fields
# into $SAR_OUT (default output/leaver_rerun), after a faithfulness control (variant none must
# be compare_json-EQUAL to the frozen gold). With --verify it then compares each rerun cell to
# the frozen data/robustness_2026-08-31/P1leave_<field>.json (EQUAL = the freeze reproduces).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"; cd "$REPO"
PY="$REPO/setup/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
DRV=analysis/robustness/battery_2026-08-29/run_p1_variant.R
D=data/frames; X=analysis/expected; FROZEN=data/robustness_2026-08-31
OUTDIR="${SAR_OUT:-output/leaver_rerun}"; mkdir -p "$OUTDIR/control"
LOG="$OUTDIR/runlog.log"; : > "$LOG"
run() { local out="$1" lab="$2" frame="$3" var="$4"
        echo "== $lab ($var)" | tee -a "$LOG"
        SAR_OUT="$out" Rscript "$DRV" full "$lab" "$frame" "$var" >> "$LOG" 2>&1 \
          || { echo "FAILED: $lab — see $LOG"; exit 2; }; }
run "$OUTDIR/control" P1_econ_fnfix "$D/p1_frame_econ.csv" none
"$PY" -m analysis.lib.compare_json "$OUTDIR/control/P1_econ_fnfix.json" "$X/P1_econ_fnfix.json" >> "$LOG" 2>&1 \
  && echo "CONTROL EQUAL: full/none vs P1_econ_fnfix" | tee -a "$LOG" \
  || { echo "CONTROL NOT EQUAL — see $LOG"; exit 3; }
run "$OUTDIR" P1leave_econ       "$D/p1_frame_econ.csv"       fill0leave
run "$OUTDIR" P1leave_chemistry  "$D/p1_frame_chemistry.csv"  fill0leave
run "$OUTDIR" P1leave_math_stats "$D/p1_frame_math_stats.csv" fill0leave
if [ "${1:-}" = "--verify" ]; then
  n_ok=0
  for f in econ chemistry math_stats; do
    if "$PY" -m analysis.lib.compare_json "$OUTDIR/P1leave_$f.json" "$FROZEN/P1leave_$f.json" >> "$LOG" 2>&1; then
      echo "VERIFY EQUAL: P1leave_$f vs frozen 2026-08-31" | tee -a "$LOG"; n_ok=$((n_ok+1))
    else echo "VERIFY NOT EQUAL: P1leave_$f — see $LOG" | tee -a "$LOG"; fi
  done
  echo "LEAVER_VERIFY $n_ok/3" | tee -a "$LOG"
fi
