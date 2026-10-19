#!/usr/bin/env bash
# analysis/robustness/verified_pool/run_verified_pool.sh — Panel 1 and Panel 2 economics without the
# 162 network-route incumbents who are not on the verified economics roster (REPO-AUTHORED 2026-09-13).
# Controls first: the verbatim drivers on the unfiltered frames must be compare_json-EQUAL to the
# frozen golds. Then the same drivers on the filtered frames written by build_verified_pool.py.
# Writes data/robustness_2026-09-13_verified_pool/{control,estimates}/ and a MANIFEST over the directory.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"; cd "$REPO"
PY="$REPO/setup/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
E=analysis/estimation; X=analysis/expected; D=data/frames
OUT="${SAR_ROBUST_OUTDIR:-data/robustness_2026-09-13_verified_pool}"   # env override (2026-09-23); old value = default
[ -f "$OUT/build_report.json" ] || { echo "run build_verified_pool.py first"; exit 1; }
mkdir -p "$OUT/control" "$OUT/estimates"
LOG="$OUT/runlog_2026-09-13.log"; : > "$LOG"
run() { local out="$1" lab="$2" drv="$3" frame="$4"
        echo "== $lab ($drv on $frame)" | tee -a "$LOG"
        SAR_OUT="$out" Rscript "$E/$drv" "$lab" "$frame" >> "$LOG" 2>&1 || { echo "FAILED: $lab — see $LOG"; exit 2; }; }
same() { "$PY" -m analysis.lib.compare_json "$1" "$2" >> "$LOG" 2>&1 \
           && echo "CONTROL EQUAL: $1" | tee -a "$LOG" || { echo "CONTROL NOT EQUAL: $1 — see $LOG"; exit 3; }; }
run "$OUT/control"   P1_econ_fnfix run_p1.R "$D/p1_frame_econ.csv";     same "$OUT/control/P1_econ_fnfix.json" "$X/P1_econ_fnfix.json"
run "$OUT/control"   P2_econ_fnfix run_p2.R "$D/p2_becoming_econ.csv";  same "$OUT/control/P2_econ_fnfix.json" "$X/P2_econ_fnfix.json"
run "$OUT/estimates" P1ver_econ    run_p1.R "$OUT/frames/p1_frame_econ_verified.csv"
run "$OUT/estimates" P2ver_econ    run_p2.R "$OUT/frames/p2_becoming_econ_verified.csv"
"$PY" tools/write_manifest.py "$OUT" | tee -a "$LOG"
echo "VERIFIED_POOL_DONE" | tee -a "$LOG"
