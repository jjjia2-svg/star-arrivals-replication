#!/usr/bin/env bash
# analysis/robustness/inference/run_all_perm.sh — T5 permutation inference, one entry point.
# Nine identity controls first (perm 0 must reproduce the frozen golds, checked in-driver
# against analysis/expected/), then B=500 timing permutations per headline cell (chunks of 50,
# parallel), then the permutation p-value summary and a sha256 MANIFEST over
# data/robustness_2026-08-29_b/perm/. Seed: config/seeds.yaml `permutation_seed` (20260829);
# permutation i draws with set.seed(seed + i), so every chunk is reproducible in isolation.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"; cd "$REPO"
PY="$REPO/setup/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
R=analysis/robustness/inference/run_perm.R
D=data/frames; X=analysis/expected
OUTDIR=data/robustness_2026-08-29_b/perm
SEED=20260829
B=${SAR_PERM_B:-500}
CHUNK=50
JOBS=${SAR_PERM_JOBS:-6}
mkdir -p "$OUTDIR/raw" "$OUTDIR/control"
LOG="$OUTDIR/runlog_perm.log"; : > "$LOG"
export POLARS_MAX_THREADS=2

# cell table: mode label frame ref
CELLS=(
  "p1   P1_econ_fnfix         $D/p1_frame_econ.csv            $X/P1_econ_fnfix.json"
  "p1   P1_fnfix_chemistry    $D/p1_frame_chemistry.csv       $X/P1_fnfix_chemistry.json"
  "p1   P1_fnfix_math_stats   $D/p1_frame_math_stats.csv      $X/P1_fnfix_math_stats.json"
  "p2   P2_econ_fnfix         $D/p2_becoming_econ.csv         $X/P2_econ_fnfix.json"
  "p2   P2_fnfix_chemistry    $D/p2_becoming_chemistry.csv    $X/P2_fnfix_chemistry.json"
  "p2   P2_fnfix_math_stats   $D/p2_becoming_math_stats.csv   $X/P2_fnfix_math_stats.json"
  "p3tp P3lb_econ_A_far       $D/p3_afar_econ.parquet         $X/P3lb_econ_A_far.json"
  "p3tp P3lb_chemistry_A_far  $D/p3_afar_chemistry.parquet    $X/P3lb_chemistry_A_far.json"
  "p3tp P3lb_math_stats_A_far $D/p3_afar_math_stats.parquet   $X/P3lb_math_stats_A_far.json"
)

echo "== identity controls (perm 0)" | tee -a "$LOG"
for c in "${CELLS[@]}"; do
  read -r MODE LAB FR REF <<< "$c"
  SAR_OUT="$OUTDIR/control" Rscript "$R" "$MODE" "$LAB" "$FR" "$REF" "$SEED" 0 0 >> "$LOG" 2>&1 \
    || { echo "CONTROL FAILED: $LAB — see $LOG"; exit 2; }
  echo "CONTROL EQUAL: $LAB" | tee -a "$LOG"
done
echo "CONTROLS_EQUAL 9/9" | tee -a "$LOG"

echo "== permutations B=$B chunk=$CHUNK jobs=$JOBS" | tee -a "$LOG"
JOBLIST="$OUTDIR/raw/_joblist.txt"; : > "$JOBLIST"
for c in "${CELLS[@]}"; do
  read -r MODE LAB FR REF <<< "$c"
  i=1
  while [ "$i" -le "$B" ]; do
    j=$(( i + CHUNK - 1 )); [ "$j" -gt "$B" ] && j=$B
    echo "$MODE $LAB $FR $REF $SEED $i $j" >> "$JOBLIST"
    i=$(( j + 1 ))
  done
done
export PERM_OUTDIR="$OUTDIR" PERM_R="$R"
xargs -P "$JOBS" -L1 bash -c '
  set -e
  SAR_OUT="$PERM_OUTDIR/raw" Rscript "$PERM_R" "$1" "$2" "$3" "$4" "$5" "$6" "$7" \
    > "$PERM_OUTDIR/raw/_${2}_${6}_${7}.log" 2>&1
' _ < "$JOBLIST"
echo "PERM_RUNS_DONE" | tee -a "$LOG"

"$PY" analysis/robustness/inference/summarize_perm.py "$OUTDIR" | tee -a "$LOG"

"$PY" - <<'PYEOF'
import hashlib, pathlib
root = pathlib.Path("data/robustness_2026-08-29_b/perm")
lines = [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.as_posix()}"
         for f in sorted(root.rglob("*")) if f.is_file() and f.name != "MANIFEST.sha256"]
(root / "MANIFEST.sha256").write_text("\n".join(lines) + "\n")
print(f"MANIFEST written: {len(lines)} files")
PYEOF
echo "PERM_OK"
