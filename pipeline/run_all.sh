#!/usr/bin/env bash
# pipeline/run_all.sh — the UPSTREAM half of the replication package: snapshot -> frozen frames.
#
# `analysis/run_all.sh` reproduces every number the thesis reports FROM the frozen frames. This
# script reproduces the frozen frames themselves, by re-running the ported builders through their
# launchers and then proving, artifact by artifact, that what they produce equals what is shipped
# (CSV byte-identical, parquet content-equal — the D1 criterion; see pipeline/README.md).
#
#   bash pipeline/run_all.sh                       # the verifiable subset. ~75 s.
#   bash pipeline/run_all.sh --stage frames        # one layer: fwci | rosters | stars | frames | all
#   bash pipeline/run_all.sh --with-ssd            # + the stages that read the mounted data disk
#   bash pipeline/run_all.sh --expensive           # + the 37-minute full-snapshot FWCI scan
#   bash pipeline/run_all.sh --list                # every stage: what runs, what it needs, and why
#   bash pipeline/run_all.sh --no-proof            # skip the acceptance gate (stages only)
#
# WHAT THIS NEEDS, PLAINLY. This layer rebuilds the frames from upstream inputs the package does NOT
# ship, so it is not self-contained and no flag makes it so. Measured, by running it:
#
#   * 14 of the 15 default stages need the read-only legacy trees (`legacy_v2_output` /
#     `legacy_thesis` in config/paths.yaml). Without them 14 fail; only `fwci/build` survives, and
#     only because Task 8 repointed its one input at this repository's frozen copy.
#   * 3 of the 15 additionally need the mounted data disk (`ssd_root`): `rosters/econ-audit`,
#     `stars/u4aug` and `fwci/build`.
#   * NOTHING in the default set is repo-only.
#
# Each stage declares what it needs in pipeline/lib/stages.py::REQUIRES, `--list` prints it, and the
# check below says up front which of the two roots is missing. The claim is verified by measurement
# in tests/test_pipeline_rebuild.py, which re-runs the default plan with each root pointed at an
# empty directory and requires exactly the declared stages to fail.
#
# THREE THINGS ARE OFF UNLESS YOU ASK, and each prints its cost before it starts:
#   * the 17-hour U1 snapshot fetch      — not a stage here at all. It has no launcher and cannot be
#                                          started from this script; see pipeline/NOT_REPRODUCIBLE.md.
#   * the 37-minute FWCI snapshot scan   — `--expensive`. 510,372,821 records, 665.7 GB read.
#   * every AWS step                     — documentation only, in pipeline/aws/. Never executed from
#                                          here, by anything, under any flag.
# Stages that call the LIVE OpenAlex API are off under every flag: a fresh call today returns
# DIFFERENT data (that is the address back-fill defect the fn-fix exists to correct), so running one
# would not reproduce the 2026 artifacts, it would replace them with today's.
#
# The stage list is NOT written here. It is read from each launcher's own `STAGES` object through
# `pipeline/lib/stages.py`, so this script cannot drift from what the launchers actually declare.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"; cd "$REPO"
PY="$REPO/setup/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
export PYTHONHASHSEED=0
# This builder reconstructs the October and August versions.
export SAR_PATHS_CONFIG="${SAR_PATHS_CONFIG:-$REPO/config/paths_october.yaml}"

STAGE=all; WITH_SSD=0; EXPENSIVE=0; PROOF=1; LIST=0; SCRATCH_OUTSIDE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --stage) STAGE="${2:-}"; shift 2 ;;
    --with-ssd) WITH_SSD=1; shift ;;
    --expensive) EXPENSIVE=1; WITH_SSD=1; shift ;;
    --no-proof) PROOF=0; shift ;;
    --list) LIST=1; shift ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1 (try --help)"; exit 64 ;;
  esac
done
case "$STAGE" in fwci|rosters|stars|frames|all) ;; *)
  echo "--stage must be one of fwci rosters stars frames all (got '$STAGE')"; exit 64 ;; esac

if [ "$LIST" = 1 ]; then
  echo "== every stage in the pipeline layer =="
  echo "   CLASS   'default' runs with no flags; 'ssd' needs --with-ssd and a mounted data disk;"
  echo "           'long' needs --expensive; 'api' calls the live OpenAlex API and never runs here."
  echo "   NEEDS   what the stage requires BEYOND this repository - 'legacy' = the read-only legacy"
  echo "           trees, 'disk' = the mounted data disk. Not one stage is repo-only."
  "$PY" -m pipeline.lib.stages
  exit 0
fi

SSD_ROOT="$("$PY" -c 'from analysis.lib.paths import load_paths; print(load_paths()["ssd_root"])')"
# MILESTONE REVIEW, replicator-experience MAJOR: the banner used to resolve `legacy_v2_output`
# while every stage resolves `legacy_thesis()/"v2_output"`. The two are independent keys, so a
# false PRESENT and a false MISSING were both demonstrated. Ask the SAME resolver the stages ask.
LEGACY_ROOT="$("$PY" -c 'from pipeline.lib.paths import legacy_thesis; print(legacy_thesis() / "v2_output")')"
CLASSES=default
if [ "$WITH_SSD" = 1 ]; then
  if [ -d "$SSD_ROOT" ]; then
    CLASSES="default,ssd"
    # MILESTONE REVIEW, process MAJOR: the documented `--with-ssd` run FAILED as written, because
    # the ssd stages write GBs of scratch into <repo>/output, and on a checkout inside a
    # cloud-synced folder the sync client raced the writes into conflict copies the launcher then
    # refused. Set SAR_SYNCED_CHECKOUT=1 on such a checkout and the heavy stages default to a
    # scratch root outside the synced tree. $SAR_OUT_ROOT still wins if the operator sets one.
    if [ -z "${SAR_OUT_ROOT:-}" ] && [ "${SAR_SYNCED_CHECKOUT:-0}" = 1 ]; then
      SCRATCH_OUTSIDE=1                 # one FRESH root per stage: $SAR_OUT_ROOT is single-use
      echo "NOTE: this checkout is inside a cloud-synced folder, so the data-disk stages write their"
      echo "      scratch OUTSIDE it, one fresh root per stage under \${TMPDIR:-/tmp}."
      echo "      (set \$SAR_OUT_ROOT yourself to choose one. See pipeline/NOT_REPRODUCIBLE.md.)"
    fi
    echo "COST: --with-ssd adds the stages that read the data disk at"
    echo "      $SSD_ROOT"
    echo "      They are free and take minutes (the largest reads ~24 GB of edge tables and asks"
    echo "      DuckDB for up to 12 GB of RAM). No cloud, no money."
  else
    echo "--with-ssd was given but the data disk is NOT mounted at $SSD_ROOT."
    echo "Those stages will be SKIPPED and the frames they rebuild will NOT be verified in this run."
  fi
fi
if [ "$EXPENSIVE" = 1 ]; then
  if [ -d "$SSD_ROOT" ]; then
    CLASSES="$CLASSES,long"
    echo
    echo "COST: --expensive adds the full-snapshot FWCI scan:"
    "$PY" pipeline/fwci/run_fwci.py --list | sed -n '/OFF BY DEFAULT/,/^ *->/p' | sed 's/^/      /'
    echo "      Its output is already frozen and sha256-pinned in data/fwci/, so re-running it"
    echo "      proves nothing this package has not already checked from the surviving artifact."
    echo
  else
    echo "--expensive was given but the data disk is not mounted; the scan cannot run."
  fi
fi

# What the selected plan needs, said BEFORE anything runs rather than discovered as 14 failures.
echo
echo "== this layer is not self-contained; what the selected stages need =="
[ -d "$LEGACY_ROOT" ] \
  && echo "  PRESENT  legacy tree  $LEGACY_ROOT" \
  || echo "  MISSING  legacy tree  $LEGACY_ROOT
           14 of the 15 default stages read it and will FAIL. This package does not ship the
           upstream intermediates they consume; see pipeline/MANIFEST_intermediates.md."
[ -d "$SSD_ROOT" ] \
  && echo "  PRESENT  data disk    $SSD_ROOT" \
  || echo "  MISSING  data disk    $SSD_ROOT
           rosters/econ-audit, stars/u4aug and fwci/build read it and will FAIL."
echo

mkdir -p output/logs

# Step 0, exactly as analysis/run_all.sh has had since M1: the frozen inputs must verify before
# anything claims to reproduce them. The milestone review found this layer had no such step, so its
# acceptance proof could report on a redirected `frames:` directory (acceptance-honesty MAJOR).
"$PY" tools/verify_manifest.py > output/logs/pipeline_manifest.log 2>&1 \
  || { echo "MANIFEST_FAIL - the frozen data does not match data/MANIFEST.sha256; see output/logs/pipeline_manifest.log"; exit 1; }
echo "inputs verified (data/MANIFEST.sha256)"

PLAN_ARGS=(--plan "$CLASSES"); [ "$STAGE" = all ] || PLAN_ARGS+=(--layer "$STAGE")
PLAN="$("$PY" -m pipeline.lib.stages "${PLAN_ARGS[@]}")" || { echo "STAGE_PLAN_FAILED"; exit 1; }
[ -n "$PLAN" ] || { echo "no stages selected for --stage $STAGE at class(es) $CLASSES"; exit 65; }

OK=0; FAILED=0; SUMMARY=()
while IFS=$'\t' read -r layer launcher stage klass rest; do
  [ -n "${layer:-}" ] || continue
  # shellcheck disable=SC2206
  extra=($rest)
  label="$layer/$stage${rest:+ ${rest//$'\t'/ }}"
  log="output/logs/pipeline_$(echo "$layer-$stage${rest:+-${rest//$'\t'/-}}" | tr -c 'A-Za-z0-9._-' '-').log"
  cmd=("$PY" "$launcher" "$stage")
  [ "$klass" = default ] || cmd+=(--execute)
  [ ${#extra[@]} -eq 0 ] || cmd+=(-- "${extra[@]}")
  needs="$("$PY" -c "import sys; from pipeline.lib.stages import requires, needs_label; print(needs_label(requires(sys.argv[1], sys.argv[2])))" "$layer" "$stage")"
  echo "== $label   [needs $needs]"
  t0=$SECONDS
  if [ "$SCRATCH_OUTSIDE" = 1 ]; then
    SAR_OUT_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/sar_scratch_$(echo "$layer-$stage" | tr -c 'A-Za-z0-9' '-').XXXXXX")"
    export SAR_OUT_ROOT
  fi
  if "${cmd[@]}" > "$log" 2>&1; then
    OK=$((OK + 1)); SUMMARY+=("  OK      $label  ($((SECONDS - t0))s)")
  else
    rc=$?
    FAILED=$((FAILED + 1)); SUMMARY+=("  FAILED  $label  (exit $rc, see $log)")
    echo "FAILED (exit $rc) — see $log"; tail -5 "$log" | sed 's/^/    /'
  fi
done <<< "$PLAN"

PROOF_LINE=""
if [ "$PROOF" = 1 ] && [ "$FAILED" = 0 ]; then
  echo "== acceptance proof (tests/test_pipeline_rebuild.py)"
  # the proof drives the stages itself and chooses its own scratch; a leftover $SAR_OUT_ROOT from
  # the loop above (single-use, and by then full) would make every roster comparison fail.
  unset SAR_OUT_ROOT
  # The stages above prove the builders RUN. This proves what they produce equals what is shipped,
  # with the provenance guards that make "this is a rebuild" checkable rather than assumed.
  if "$PY" -m pytest -q tests/test_pipeline_rebuild.py > output/logs/pipeline_proof.log 2>&1; then
    PROOF_LINE="  OK      acceptance proof  ($(tail -1 output/logs/pipeline_proof.log))"
  else
    PROOF_LINE="  FAILED  acceptance proof  (see output/logs/pipeline_proof.log)"
    FAILED=$((FAILED + 1))
    tail -15 output/logs/pipeline_proof.log | sed 's/^/    /'
  fi
elif [ "$PROOF" = 1 ]; then
  PROOF_LINE="  SKIPPED acceptance proof  (a stage failed; fix that first)"
fi

echo
echo "== pipeline summary (--stage $STAGE, classes $CLASSES) =="
printf '%s\n' "${SUMMARY[@]}"
[ -z "$PROOF_LINE" ] || echo "$PROOF_LINE"
# NIT-6: computed for the SELECTED layer, so `--stage rosters` no longer lists other layers as OFF.
OFF_ARGS=(); [ "$STAGE" = all ] || OFF_ARGS=(--layer "$STAGE")
# `${a[@]}` on an empty array is an unbound-variable error under `set -u`; this is the portable idiom
OFF="$("$PY" -m pipeline.lib.stages ${OFF_ARGS[@]+"${OFF_ARGS[@]}"} | awk -v c="$CLASSES" 'BEGIN{split(c,k,",");for(i in k)on[k[i]]=1}
       $3!="default" && !($3 in on){print "  OFF     "$1"/"$2"  ("$3", "$4")"}')"
[ -z "$OFF" ] || { echo "$OFF"; echo "  (--list explains each class; the 17h U1 fetch and every AWS step are not stages here at all)"; }
echo
if [ "$FAILED" = 0 ]; then echo "PIPELINE_OK — $OK stage(s) ran, 0 failed"; exit 0; fi
echo "PIPELINE_FAILED — $OK stage(s) ran, $FAILED failed"; exit 2
