#!/usr/bin/env bash
# pipeline/aws/cal2026-10/prep_t5_batch.sh — assemble and DRY-RUN the SECOND October cloud batch:
# T5 event-timing permutation inference for Panels 1 and 2 (2026-09-23). REPO-AUTHORED.
#
# WHY A SECOND BATCH. analysis/robustness/inference/run_all_perm.sh (T5) re-estimates each headline
# cell 500 times with the arrival years permuted across events — 9 cells x 500 draws, ~2.5-4 h at six
# local workers, which this machine cannot spare beside the running batteries (author 2026-09-16:
# heavy re-estimation goes straight to AWS). The Panel 3 (dose>0) permutations already ride in the
# first October batch (cloudkit.py group `perm`); this batch carries the Panel 1 and Panel 2 cells —
# exactly the units run_all_perm.sh would run, as PARALLEL units of the cloud driver.
#
# WHAT IS ASSEMBLED (nothing retyped: every value is read from the file that owns it)
#   cells   the six `p1`/`p2` rows of run_all_perm.sh's CELLS table (mode label frame ref); the
#           frames come from --frames (default data/frames, the October canon) and the reference
#           JSONs from --refs (default analysis/expected — the October golds run_all_perm.sh names);
#   units   per cell the identity control `0 0` first (perm 0 must reproduce the reference JSON,
#           asserted inside run_perm.R — the batch's CONTROL; rc != 0 if it does not, and the driver
#           then refuses ALL_DONE), then B permutations in chunks of CHUNK; B and CHUNK are read
#           from run_all_perm.sh (B=${SAR_PERM_B:-500}, CHUNK=50; SAR_PERM_B overrides here exactly
#           as it does there);
#   seed    config/seeds.yaml `permutation_seed`, asserted equal to run_all_perm.sh's SEED (draw i
#           uses set.seed(seed + i) inside run_perm.R, so every chunk reproduces in isolation);
#   command Rscript run_perm.R <mode> <label> <frame> <ref> <seed> <from> <to>  (basenames — the
#           payload is flat) with SAR_OUT=out_perm: the unit grammar of run_all_perm.sh's xargs line.
# Then `cloudkit.py prep --groups ''` (no P3 group) with one --extra-parallel per unit, and
# `run_cloud.sh --dry-run`, which verifies payload.md5 locally, prints the plan and the A6 estimate
# and exits before anything is armed. THIS SCRIPT NEVER LAUNCHES. Launching is a separate command:
#     bash pipeline/aws/cal2026-10/run_cloud.sh --payload <payload> --custody <custody>
#
#   bash prep_t5_batch.sh [--payload DIR] [--custody DIR] [--frames DIR] [--refs DIR]
#                         [--parallel N] [--threads N] [--force] [--skip-dry-run]
#   defaults: --payload /private/tmp/cal2026-10_payload_t5   --custody data/cal2026-10/cloud_t5
#             --frames data/frames   --refs analysis/expected   --parallel 12   --threads 4
# Test hook (never set for a real batch): SAR_SEEDS_YAML (default config/seeds.yaml).
# Tests: tests/test_aws_cal2026_10_t5.py (grammar equality with run_all_perm.sh, dry run, driver).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"; cd "$REPO"
PY="$REPO/setup/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
PERM_SH=analysis/robustness/inference/run_all_perm.sh
SEEDS="${SAR_SEEDS_YAML:-config/seeds.yaml}"

PAYLOAD=/private/tmp/cal2026-10_payload_t5; CUSTODY=data/cal2026-10/cloud_t5
FRAMES=data/frames; REFS=analysis/expected; PAR=12; THREADS=4; FORCE=""; DRY=1
usage() { sed -n '2,36p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-2}"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --payload) PAYLOAD="$2"; shift 2 ;;
    --custody) CUSTODY="$2"; shift 2 ;;
    --frames) FRAMES="$2"; shift 2 ;;
    --refs) REFS="$2"; shift 2 ;;
    --parallel) PAR="$2"; shift 2 ;;
    --threads) THREADS="$2"; shift 2 ;;
    --force) FORCE="--force"; shift ;;
    --skip-dry-run) DRY=0; shift ;;
    -h|--help) usage 0 ;;
    *) echo "unknown argument: $1" >&2; usage 2 ;;
  esac
done

# ---- the grammar, read from the battery this batch mirrors ---------------------------------------
B_DEFAULT="$(sed -n 's/^B=\${SAR_PERM_B:-\([0-9][0-9]*\)}.*/\1/p' "$PERM_SH")"
CHUNK="$(sed -n 's/^CHUNK=\([0-9][0-9]*\).*/\1/p' "$PERM_SH")"
SEED_SH="$(sed -n 's/^SEED=\([0-9][0-9]*\).*/\1/p' "$PERM_SH")"
SEED="$(awk '/^permutation_seed:/ {print $2}' "$SEEDS")"
[ -n "$B_DEFAULT" ] && [ -n "$CHUNK" ] && [ -n "$SEED_SH" ] \
  || { echo "cannot read B / CHUNK / SEED from $PERM_SH" >&2; exit 1; }
[ -n "$SEED" ] || { echo "permutation_seed missing from $SEEDS" >&2; exit 1; }
[ "$SEED" = "$SEED_SH" ] || { echo "SEED DISAGREEMENT: $SEEDS permutation_seed=$SEED but $PERM_SH SEED=$SEED_SH — resolve before shipping" >&2; exit 1; }
B="${SAR_PERM_B:-$B_DEFAULT}"
# the p1/p2 rows of the CELLS table, verbatim: mode label $D/frame $X/ref
CELLS="$(awk '/^CELLS=\(/ {f=1; next} f && /^\)/ {f=0} f && /^ *"p[12] /' "$PERM_SH" | tr -d '"')"
NCELLS="$(printf '%s\n' "$CELLS" | grep -c . || true)"
[ "$NCELLS" -gt 0 ] || { echo "no p1/p2 rows found in the CELLS table of $PERM_SH" >&2; exit 1; }

ARGS=(); NUNITS=0; REFS_SEEN=" "
while read -r MODE LAB FR REF; do
  [ -n "${MODE:-}" ] || continue
  FRB="${FR##*/}"; REFB="${REF##*/}"
  [ -f "$FRAMES/$FRB" ] || { echo "frame $FRAMES/$FRB missing" >&2; exit 1; }
  [ -f "$REFS/$REFB" ] || { echo "reference $REFS/$REFB missing" >&2; exit 1; }
  case "$REFS_SEEN" in *" $REFB "*) ;; *) ARGS+=(--extra-file "$REFS/$REFB"); REFS_SEEN="$REFS_SEEN$REFB " ;; esac
  a=0; b=0
  while :; do        # (0,0) the identity control, then (1,CHUNK), (CHUNK+1,2*CHUNK), ... up to B
    ARGS+=(--extra-parallel "${LAB}_perm_${a}_${b}|out_perm|Rscript run_perm.R $MODE $LAB $FRB $REFB $SEED $a $b")
    NUNITS=$((NUNITS + 1))
    [ "$b" -lt "$B" ] || break
    a=$((b + 1)); b=$((a + CHUNK - 1)); [ "$b" -le "$B" ] || b=$B
  done
done <<EOF
$CELLS
EOF

echo "== T5 batch: $NCELLS P1/P2 cells x (1 identity control + chunks of $CHUNK up to B=$B) = $NUNITS parallel units; seed $SEED (config/seeds.yaml == run_all_perm.sh); frames $FRAMES; refs $REFS"
"$PY" "$HERE/cloudkit.py" prep --frames "$FRAMES" --groups '' --out "$PAYLOAD" --custody "$CUSTODY" \
      --perm-seed "$SEED" --parallel "$PAR" --threads "$THREADS" $FORCE "${ARGS[@]}"

if [ "$DRY" = 1 ]; then
  echo "== dry run (verifies payload.md5 locally, prints the plan; nothing is armed)"
  bash "$HERE/run_cloud.sh" --payload "$PAYLOAD" --custody "$CUSTODY" --dry-run
fi
echo "== T5 batch PREPARED, NOT LAUNCHED: payload $PAYLOAD ($NUNITS parallel units, 0 serial cells), custody $CUSTODY"
echo "   launching is a separate, deliberate command: run_cloud.sh --payload \"$PAYLOAD\" --custody \"$CUSTODY\" (no --dry-run)"
