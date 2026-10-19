#!/bin/bash
# The overlapped 98-event complement of the double-star split, econ Panel 1 (2026-09-12).
# Builds the frame (build_doublestar_complement.py), estimates with the VERBATIM driver, freezes
# the estimate under data/robustness_2026-09-12_dscomp/ and pins a MANIFEST.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"; cd "$REPO"
PY="$REPO/setup/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
STAGE="${SAR_ROBUST_STAGE:-/private/tmp/sar_dscomp_2026-09-12}"                      # 2026-09-23: env overrides, old values default
OUTDIR="${SAR_ROBUST_OUTDIR:-data/robustness_2026-09-12_dscomp}"; export SAR_ROBUST_OUTDIR="$OUTDIR"
export POLARS_MAX_THREADS=4
"$PY" analysis/robustness/sensitivity/build_doublestar_complement.py --stage "$STAGE"
export SAR_OUT="$REPO/$OUTDIR/estimates"; mkdir -p "$SAR_OUT"
Rscript analysis/estimation/run_p1.R P1dsC_econ "$STAGE/p1_dsC_econ.csv"
unset SAR_OUT
"$PY" tools/write_manifest.py "$OUTDIR"
