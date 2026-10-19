#!/usr/bin/env bash
# analysis/robustness/sensitivity/run_nocentre_afar_pos.sh — the ± research-centre check for Panel 3
# on the CURRENT specification (dose > 0), chemistry + math_stats. 2026-09-10, local, $0.
#
# The frozen ± centre cells (data/robustness_2026-08-29_b/nocentre/) cover P1, P2 and the P3 FULL
# math panel only; the paper's Panel 3 since 2026-08-30 is the A_far `pos` cut. This entry point
# runs run_nocentre_afar_pos.py — run_nocentre.build_variant verbatim (control build first, then the
# incfel = no-centre roster), build_afar_cut.py `pos` with its SOURCES re-pointed at each build's
# frames (explicit `sources=` parameter), the verbatim run_p3_tp.R — and then rewrites the MANIFEST
# over the WHOLE of data/robustness_2026-09-10_p3pos/ (the directory also holds today's departure
# and double-star cells; run this only when no other job is writing there).
# Controls (each STOPS the run): with-centre build reproduces canon (relationships + becoming
# byte-identical, P1 within H1); its pos A_far frame CONTENT-EQUAL to data/frames/p3_afar_pos_*;
# run_p3_tp.R on it compare_json-EQUAL to analysis/expected/P3pos_*_A_far.json; the no-centre
# relationships/becoming sha256 equal to the 2026-08-29 run's frozen values.
# Needs the data disk (the builders scan <ssd_root>/derived) and the legacy tree. Economics has no
# ± variant by design. Never writes into data/robustness_2026-08-29_b/.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"; cd "$REPO"
PY="$REPO/setup/.venv/bin/python"; [ -x "$PY" ] || { echo "setup/.venv missing (run bash setup/install_py.sh)"; exit 1; }
B="${SAR_ROBUST_MANIFEST_DIR:-data/robustness_2026-09-10_p3pos}"   # 2026-09-23: env override (pair with SAR_ROBUST_OUTDIR_P3POS for the .py), old value default
export SAR_OUT_ROOT="${SAR_OUT_ROOT:-/private/tmp/sar_nocentre_afar_pos_2026-09-10}"
case "$SAR_OUT_ROOT" in /private/tmp/*) ;; *) echo "SAR_OUT_ROOT must be a scratch dir under /private/tmp: $SAR_OUT_ROOT"; exit 1;; esac
mkdir -p "$SAR_OUT_ROOT"
[ -z "$(ls -A "$SAR_OUT_ROOT")" ] || { echo "SAR_OUT_ROOT must be empty: $SAR_OUT_ROOT"; exit 1; }

echo "== 0. preconditions (data disk, legacy tree)"
SSD_DERIVED="$("$PY" -c 'import os,pathlib; from analysis.lib.paths import load_paths; r=os.environ.get("SAR_SSD_ROOT") or str(load_paths()["ssd_root"]); print(pathlib.Path(r)/"derived")')"
[ -d "$SSD_DERIVED" ] || { echo "data disk not mounted ($SSD_DERIVED absent): the incfel-roster rebuild scans it — NOT RUN"; exit 1; }
LEGACY="$("$PY" -c 'from analysis.lib.paths import load_paths; print(load_paths()["legacy_v2_output"])')"
[ -d "$LEGACY" ] || { echo "legacy tree absent ($LEGACY): frames_stage.build_shadow links it — NOT RUN"; exit 1; }

echo "== 1. control build -> control pos cut + estimate -> no-centre build -> pos cells (scratch: $SAR_OUT_ROOT)"
"$PY" analysis/robustness/sensitivity/run_nocentre_afar_pos.py --execute

echo "== 2. MANIFEST over the whole directory"
"$PY" tools/write_manifest.py "$B"
"$PY" tools/verify_manifest.py "$B/MANIFEST.sha256"
echo "NOCENTRE_AFAR_POS_OK"
