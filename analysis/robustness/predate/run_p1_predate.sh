#!/usr/bin/env bash
# analysis/robustness/predate/run_p1_predate.sh — Panel 1 date-shift (anticipation) test, one entry
# point. REPO-AUTHORED, added 2026-09-23 for the October caliber (cal2026-10).
#
# PROVENANCE. The frozen data/predate_p1_2026-08-30/ was produced on 2026-08-30 (session
# f071d8a9, 07:36:34Z) by an inline heredoc, /tmp/p1_predate_all.sh, never committed:
#     OUT=data/predate_p1_2026-08-30; mkdir -p "$OUT/control"
#     declare -A GOLD=( [econ]=P1_econ_fnfix [chemistry]=P1_fnfix_chemistry [math_stats]=P1_fnfix_math_stats )
#     for F in math_stats chemistry econ; do G=${GOLD[$F]}
#       SAR_OUT="$OUT/control" Rscript analysis/robustness/predate/run_predate.R p1 "$G" data/frames/p1_frame_${F}.csv 0
#       $PY -m analysis.lib.compare_json "$OUT/control/$G.json" "analysis/expected/$G.json"
#       SAR_OUT="$OUT" Rscript analysis/robustness/predate/run_predate.R p1 P1pd2_${F} data/frames/p1_frame_${F}.csv 2
#     done
# This file is that script line for line, with two changes: (1) the output directory comes from
# $SAR_PREDATE_P1_OUTDIR (default: the October product dir); (2) the gold-label map is a `case`
# instead of `declare -A`, which /bin/bash 3.2 (macOS) does not support — under 3.2 every field
# resolved to the last label, which is why the frozen control/P1_fnfix_math_stats.json carries the
# econ frame (file=p1_frame_econ.csv); the 07:38:49Z re-run fixed chemistry and econ only.
# The estimation command, its arguments and the driver (run_predate.R, mode p1) are unchanged.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"; cd "$REPO"
PY="$REPO/setup/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
OUT="${SAR_PREDATE_P1_OUTDIR:-data/cal2026-10/robustness/predate_p1}"; mkdir -p "$OUT/control"
LOG="$OUT/runlog.log"; : > "$LOG"
gold() { case "$1" in econ) echo P1_econ_fnfix;; chemistry) echo P1_fnfix_chemistry;; math_stats) echo P1_fnfix_math_stats;; esac; }
for F in math_stats chemistry econ; do
  G=$(gold "$F")
  echo "=== $F shift=0 (control) ===" | tee -a "$LOG"
  SAR_OUT="$OUT/control" Rscript analysis/robustness/predate/run_predate.R p1 "$G" data/frames/p1_frame_${F}.csv 0 >> "$LOG" 2>&1 \
    || { echo "FAILED: control $G — see $LOG"; exit 2; }
  "$PY" -m analysis.lib.compare_json "$OUT/control/$G.json" "analysis/expected/$G.json" >> "$LOG" 2>&1 \
    && echo "CONTROL EQUAL: $G" | tee -a "$LOG" \
    || { echo "CONTROL NOT EQUAL: $G — see $LOG"; exit 3; }
  echo "=== $F shift=2 ===" | tee -a "$LOG"
  SAR_OUT="$OUT" Rscript analysis/robustness/predate/run_predate.R p1 P1pd2_${F} data/frames/p1_frame_${F}.csv 2 >> "$LOG" 2>&1 \
    || { echo "FAILED: P1pd2_${F} — see $LOG"; exit 2; }
done
echo "P1_PREDATE_OK" | tee -a "$LOG"
