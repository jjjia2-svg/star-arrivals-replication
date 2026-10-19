#!/usr/bin/env bash
# analysis/robustness/sensitivity/run_all_sensitivity.sh — T6 canon reruns, one entry point.
#
# The three pruned sensitivity checks, old design on the canon event set (econ 116 / chem 38 /
# math 33), in dependency order:
#   0. afar_event_map.py       proven ev -> event_id maps for the A_far frames (the econ map
#                              regenerates pairs_unified.csv through the caliber shadow; SSD)
#   1. build_departure.py      star-departure A/B (2026-08-09 verified ledger, econ) + 6 cells
#   2. build_doublestar.py     double-star overlap drops (§3's own rule) + 10 cells
#   3. run_nocentre.py         ± research-centre rosters (chem/math; control first) + 5 cells
# Estimation is by the VERBATIM analysis/estimation drivers on the variant frames; every
# builder carries its own faithfulness control (map content-equality, no-op byte-identity,
# control build reproducing the canon frames and golds). Finishes with a sha256 MANIFEST over
# the T6 part of data/robustness_2026-08-29_b/.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"; cd "$REPO"
PY="$REPO/setup/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
E=analysis/estimation
S=analysis/robustness/sensitivity
B=data/robustness_2026-08-29_b
export POLARS_MAX_THREADS=4
DEP_STAGE=/private/tmp/sar_departure_2026-08-29
DS_STAGE=/private/tmp/sar_doublestar_2026-08-29
NC_STAGE=/private/tmp/sar_nocentre_2026-08-29

echo "== 0. A_far event maps (with content-equality proofs)"
"$PY" $S/afar_event_map.py --regen-econ

echo "== 1. departure A/B (econ)"
"$PY" $S/build_departure.py --stage "$DEP_STAGE"
export SAR_OUT=$B/departure/estimates
Rscript $E/run_p1.R    P1depA_econ       "$DEP_STAGE/p1_dep_A.csv"
Rscript $E/run_p1.R    P1depB_econ       "$DEP_STAGE/p1_dep_B.csv"
Rscript $E/run_p2.R    P2depA_econ       "$DEP_STAGE/p2_dep_A.csv"
Rscript $E/run_p2.R    P2depB_econ       "$DEP_STAGE/p2_dep_B.csv"
Rscript $E/run_p3_tp.R P3depA_econ_A_far "$DEP_STAGE/p3_afar_dep_A.parquet"
Rscript $E/run_p3_tp.R P3depB_econ_A_far "$DEP_STAGE/p3_afar_dep_B.parquet"

echo "== 2. double-star overlap drops (all three disciplines)"
"$PY" $S/build_doublestar.py --stage "$DS_STAGE" --events-dir data/cal2026-10 --frames-dir data/frames --pairs-none-math data/cal2026-08-28/frames/pairs_none_math_stats.parquet
export SAR_OUT=$B/doublestar/estimates
for F in econ chemistry math_stats; do
  Rscript $E/run_p1.R    "P1ds_$F"        "$DS_STAGE/p1_ds_$F.csv"
  Rscript $E/run_p2.R    "P2ds_$F"        "$DS_STAGE/p2_ds_$F.csv"
  Rscript $E/run_p3_tp.R "P3ds_${F}_A_far" "$DS_STAGE/p3_afar_ds_$F.parquet"
done
Rscript $E/run_p3.R P3ds_math_stats_full "$DS_STAGE/p3_slim_ds_math_stats.parquet"
unset SAR_OUT

echo "== 3. ± centre rosters (chem/math; control build + golds first)"
rm -rf "$NC_STAGE"; mkdir -p "$NC_STAGE"
SAR_OUT_ROOT="$NC_STAGE" "$PY" $S/run_nocentre.py --execute

"$PY" - <<'PYEOF'
import hashlib, pathlib
roots = [pathlib.Path(f"data/robustness_2026-08-29_b/{d}")
         for d in ("afar_event_map", "departure", "doublestar", "nocentre")]
lines = [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.as_posix()}"
         for r in roots for f in sorted(r.rglob("*")) if f.is_file()]
out = pathlib.Path("data/robustness_2026-08-29_b/MANIFEST_t6.sha256")
out.write_text("\n".join(lines) + "\n")
print(f"MANIFEST_t6 written: {len(lines)} files")
PYEOF
echo "SENSITIVITY_OK"
