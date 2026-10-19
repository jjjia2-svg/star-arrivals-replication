#!/usr/bin/env bash
# analysis/robustness/predate/run_all_predate.sh — Batch 2 date-shift (anticipation) test,
# one entry point. Three shift-0 faithfulness controls first (each must be compare_json-EQUAL
# to its frozen gold in analysis/expected/ — proving the driver's prep is the verbatim prep),
# then the seven locally-runnable shifted cells (arrival moved two years earlier), then a
# sha256 MANIFEST over data/predate_2026-08-28/. The P3 econ/chemistry FULL pair panels are
# 512GB cloud cells and are NOT run here (pending author approval, ~$3).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"; cd "$REPO"
PY="$REPO/setup/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
R=analysis/robustness/predate/run_predate.R
D=data/frames; X=analysis/expected
OUTDIR="${SAR_PREDATE_OUTDIR:-data/predate_2026-08-28}"   # 2026-09-23: output-dir override only (default = the frozen 2026-08-28 run); the MANIFEST below follows it
mkdir -p "$OUTDIR/control"
LOG="$OUTDIR/runlog_2026-08-28.log"; : > "$LOG"
run() { local out="$1" md="$2" lab="$3"; shift 3
        echo "== $lab" | tee -a "$LOG"
        SAR_OUT="$out" Rscript "$R" "$md" "$lab" "$@" >> "$LOG" 2>&1 \
          || { echo "FAILED: $lab — see $LOG"; exit 2; }; }
ck()  { "$PY" -m analysis.lib.compare_json "$OUTDIR/control/$1.json" "$X/$1.json" >> "$LOG" 2>&1 \
          && echo "CONTROL EQUAL: $1" | tee -a "$LOG" \
          || { echo "CONTROL NOT EQUAL: $1 — see $LOG"; exit 3; }; }

# shift-0 controls — the driver must reproduce the frozen golds exactly
run "$OUTDIR/control" p3tp P3lb_econ_A_far     "$D/p3_afar_econ.parquet"       0
ck  P3lb_econ_A_far
run "$OUTDIR/control" p2   P2_econ_fnfix       "$D/p2_becoming_econ.csv"       0
ck  P2_econ_fnfix
run "$OUTDIR/control" p3   P3_fnfix_math_stats "$D/p3_slim_math_stats.parquet" 0 "$D/p3_slim_ev_math_stats.parquet"
ck  P3_fnfix_math_stats
echo "CONTROLS_EQUAL 3/3" | tee -a "$LOG"

# the date-shift cells (D' = 1{year >= arrival - 2})
run "$OUTDIR" p2   P2pd2_econ             "$D/p2_becoming_econ.csv"        2
run "$OUTDIR" p2   P2pd2_chemistry        "$D/p2_becoming_chemistry.csv"   2
run "$OUTDIR" p2   P2pd2_math_stats       "$D/p2_becoming_math_stats.csv"  2
run "$OUTDIR" p3tp P3pd2_econ_A_far       "$D/p3_afar_econ.parquet"        2
run "$OUTDIR" p3tp P3pd2_chemistry_A_far  "$D/p3_afar_chemistry.parquet"   2
run "$OUTDIR" p3tp P3pd2_math_stats_A_far "$D/p3_afar_math_stats.parquet"  2
run "$OUTDIR" p3   P3pd2_math_stats_full  "$D/p3_slim_math_stats.parquet"  2 "$D/p3_slim_ev_math_stats.parquet"

echo "PREDATE_OK" >> "$LOG"
"$PY" - "$OUTDIR" <<'PYEOF'
import hashlib, pathlib, sys
root = pathlib.Path(sys.argv[1])          # was the literal "data/predate_2026-08-28"; now $OUTDIR (same default)
lines = [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.as_posix()}"
         for f in sorted(root.rglob("*")) if f.is_file() and f.name != "MANIFEST.sha256"]
(root / "MANIFEST.sha256").write_text("\n".join(lines) + "\n")
print(f"MANIFEST written: {len(lines)} files")
PYEOF
echo "PREDATE_OK"
