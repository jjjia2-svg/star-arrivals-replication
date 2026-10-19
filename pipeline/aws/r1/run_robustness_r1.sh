#!/usr/bin/env bash
# pipeline/aws/r1/run_robustness_r1.sh — the J1b robustness entry (P3e F19, unit W1-ROB). One call per stage:
#
#   bash "$WORK/run_robustness_r1.sh" <jobs|frames|cells|loeo|perm|null|post>
#
# Stage env (run_stages.py): PY, REPO_DIR, COMMIT, WORK, STAGE_OUT. Never runs a pipeline/ script in place:
# rob_jobs_r1.py, run_units.py, rob_post_r1.py (and W2-CHEMM's chemmath_m.py when present) are copied into
# $WORK/bin first. Outputs go under ROB_ROOT=$REPO_DIR/output/r1/robustness in October's relative layout
# (October helpers call DS_DIR.relative_to(REPO), so the root must lie inside the repo).
#   jobs   rob_jobs_r1.py build -> $STAGE_OUT/units.tsv (+ paths_m.yaml = paths_aws.yaml with
#          frames=$J1A/frames and output re-pointed); coverage STOPs here
#   other  run_units.py on that group of $WORK/prod/rob_jobs/units.tsv with W1-PARPLAN's plan; post then packs
#          the canon tree $STAGE_OUT/canon/{robustness,cloud,cloud_t5} (rob_post_r1.py canon-pack)
# Env overrides (tests / a second launch): SAR_J1A (default /work/j1a), SAR_ROB_PLAN
# (default $WORK/prod/par_plan/plan.json).
set -euo pipefail
GROUP="${1:-}"
case "$GROUP" in
  jobs|frames|cells|loeo|perm|null|post) ;;
  *) echo "usage: run_robustness_r1.sh <jobs|frames|cells|loeo|perm|null|post>" >&2; exit 2 ;;
esac
: "${PY:?PY unset}" "${REPO_DIR:?REPO_DIR unset}" "${WORK:?WORK unset}" "${STAGE_OUT:?STAGE_OUT unset}"
ROB_ROOT="$REPO_DIR/output/r1/robustness"
case "$ROB_ROOT" in
  "$REPO_DIR"/*) ;;
  *) echo "ROB_ROOT $ROB_ROOT is not under REPO_DIR" >&2; exit 2 ;;
esac
J1A="${SAR_J1A:-/work/j1a}"
BIN="$WORK/bin"
JOBS="$WORK/prod/rob_jobs"
PLAN="${SAR_ROB_PLAN:-$WORK/prod/par_plan/plan.json}"
CFG="$REPO_DIR/config/r1/robustness_r1.json"
mkdir -p "$BIN" "$ROB_ROOT" "$STAGE_OUT"

for f in rob_jobs_r1.py run_units.py rob_post_r1.py; do
  cp "$REPO_DIR/pipeline/aws/r1/$f" "$BIN/$f"
done
if [ -f "$REPO_DIR/pipeline/aws/r1/chemmath_m.py" ]; then
  cp "$REPO_DIR/pipeline/aws/r1/chemmath_m.py" "$BIN/chemmath_m.py"
fi

if [ "$GROUP" = jobs ]; then
  [ "$STAGE_OUT" = "$JOBS" ] || { echo "the jobs stage must write $JOBS (got $STAGE_OUT)" >&2; exit 2; }
  "$PY" "$BIN/rob_jobs_r1.py" paths-m --base "$REPO_DIR/config/r1/paths_aws.yaml" --frames "$J1A/frames" \
        --output "$WORK/tmp/rob_paths_output" --out "$JOBS/paths_m.yaml"
  "$PY" "$BIN/rob_jobs_r1.py" build --mode m --config "$CFG" --repo "$REPO_DIR" --work "$WORK" --j1a "$J1A" \
        --out "$JOBS"
  exit 0
fi

[ -f "$JOBS/units.tsv" ] || { echo "no unit list $JOBS/units.tsv (the jobs stage runs first)" >&2; exit 2; }
[ -f "$PLAN" ] || { echo "no parallel plan $PLAN (W1-PARPLAN's par_plan stage runs first)" >&2; exit 2; }
if [ "$GROUP" = frames ] && [ "$STAGE_OUT" != "$WORK/prod/rob_frames" ]; then
  echo "the frames stage must write $WORK/prod/rob_frames (rob_jobs_r1.py stage_frames; got $STAGE_OUT)" >&2; exit 2
fi
export SAR_PATHS_CONFIG="$JOBS/paths_m.yaml"
export PY
# an earlier launch's finished units of this group, pulled to /work/reuse/<group> (j1b-03's perm units, 2026-10-17)
REUSE=(); [ -d "/work/reuse/$GROUP" ] && REUSE=(--reuse "/work/reuse/$GROUP")
"$PY" "$BIN/run_units.py" --units "$JOBS/units.tsv" --group "$GROUP" --plan "$PLAN" --root "$ROB_ROOT" \
      --repo "$REPO_DIR" --out "$STAGE_OUT" --prior "$WORK/prod" --config "$CFG" "${REUSE[@]}"
# the reused units' read evidence joins this job's audit (sandbox_check reads every WORK/reads/*.tsv)
for f in "$STAGE_OUT"/reuse_reads/*.tsv; do
  if [ -f "$f" ]; then mkdir -p "$WORK/reads"; cp "$f" "$WORK/reads/reused_$(basename "$f")"; fi
done
# M review #9: the post stage leaves the J1b part of canon M in October's cal layout inside its declared output
# (config/r1/canon_layout.json: cal/{robustness,cloud,cloud_t5} <- work:prod/rob_post/canon/...)
if [ "$GROUP" = post ]; then
  "$PY" "$BIN/rob_post_r1.py" canon-pack --repo "$REPO_DIR" --root "$ROB_ROOT" --out "$STAGE_OUT/canon"
fi
