#!/usr/bin/env bash
# analysis/run_all.sh - re-run the report's headline estimates and compare each with its recorded value.
#
# The data are the canon that the paths config in force selects: config/paths.yaml, or the file that
# $SAR_PATHS_CONFIG names (absolute, or relative to the directory the run starts in; see
# analysis/lib/canon.py). A canon is either the October 2026 version (data/frames, data/cal2026-10,
# analysis/expected and three more roots) or a canon tree: one directory that holds CANON.json and one
# folder per canon key. The run first prints the canon's name and its event counts.
#
# Stages (always run in this order):
#   1       inputs. October: data/MANIFEST.sha256 and analysis/expected/MANIFEST.sha256 must verify. A canon
#           tree: the files listed in <canon>/PACKED.tsv are restored from their xz copies (sha256 checked),
#           then every line of the MANIFEST.sha256 in each of the six canon key folders (cal, frames,
#           expected, raw_verified, paper_inputs, cal_intermediates) must verify, and
#           tools/r1_canon.py check <canon> must pass.
#   2       estimation. <output>/estimates is emptied first, so no earlier result is ever compared. Then
#           each row of the canon's cell lists (config/r1/cells: oct29.tsv for October, M.tsv and
#           M_evcl.tsv for a canon tree) runs as `Rscript <driver> <label> <frames>/<frame>
#           [<expected>/<ref>]`, and its result is saved under the row's out_name. Rows of stack rmac use
#           the Rscript on PATH. Rows of stack rcloud (the large Panel 3 cells) are not re-run: their
#           custody record is checked instead (VERIFIED_NOT_RERUN). RUN_CLOUD_CELLS=1 re-runs them too,
#           under the second R stack that $SAR_RSCRIPT_RCLOUD (its Rscript) and $SAR_RLIB_RCLOUD (its
#           package library) name; without both the run stops before it starts. Last,
#           tools/compare_all.py compares every result with its recorded estimate.
#   3est    the paper generators that estimate (the four gaps_* scripts), then a seal
#           <output>/paper/3est.seal.json: the sha256 of their outputs, of the frames, recorded estimates
#           and cal files they read, and of the canon
#   3light  stops on a canon, frames, expected or output root on a data disk (exit 5) and on a missing,
#           stale or other-canon seal (exit 4); then every other paper generator in the default order,
#           plus fig_compare_years.py and fig_comparison_pools.py (after ledger_carried.py), and the
#           base_2026_10_11 tree of tables_robustness.py, draft_2026_09_13_tables.py, ledger_p3afar.py,
#           fig_p1.py and fig_p2.py in place of their default tree (on a canon tree only the base tree can
#           be printed; the last three draw its Figures 7, 5 and 6)
#   4check  tools/check_paper.py, which checks the manuscript text against the generated ledgers
#
# Usage:
#   bash analysis/run_all.sh                 stages 1 and 2
#   RUN_PAPER=1 bash analysis/run_all.sh     stages 1 and 2, then the paper stage: for the October version
#                                            every paper generator in the default order and
#                                            tools/check_paper.py; for a canon tree stages 3est, 3light
#                                            and 4check (the same as --stages 1,2,3est,3light,4check)
#   bash analysis/run_all.sh --stages LIST   only the named stages (comma-separated), in the order above;
#                                            RUN_PAPER does not apply here
#
# What this needs. Stages 1 and 2 need only this repository: the frames and the recorded estimates are
# shipped. The paper stages (RUN_PAPER=1, 3est, 3light, 4check) also read the author's manuscript sources
# and frozen intermediate outputs, which this package does not ship (the paths config keys legacy_thesis
# and legacy_v2_output); asked for without them, the run stops before stage 1.
#
# Exit codes: 1 an input or a result differs from its record; 2 usage, or a cell failed; 3 the manuscript
# check wrote no summary; 4 a missing manuscript tree, or a seal problem; 5 a data disk; 6 no paths config
# file, or no valid canon or cell list; 7 RUN_CLOUD_CELLS=1 without the second R stack.
set -euo pipefail
# SAR_PATHS_CONFIG may be relative to the directory the run starts in; the helpers need it absolute
_CFG="${SAR_PATHS_CONFIG:-}"; _CFG="${_CFG#"${_CFG%%[![:space:]]*}"}"; _CFG="${_CFG%"${_CFG##*[![:space:]]}"}"
case "$_CFG" in ""|/*|"~"*) ;; *) export SAR_PATHS_CONFIG="$PWD/$_CFG" ;; esac
REPO="$(cd "$(dirname "$0")/.." && pwd)"; cd "$REPO"
usage() {
  cat >&2 <<'USAGE'
usage: bash analysis/run_all.sh [--stages LIST]
  no arguments   stages 1 and 2 (inputs, estimation); RUN_PAPER=1 adds the paper stage
                 (on a canon tree as stages 3est, 3light and 4check)
  --stages LIST  comma-separated names from 1, 2, 3est, 3light, 4check; they run in that order
environment:
  RUN_CLOUD_CELLS=1  also re-run the large cells, with SAR_RSCRIPT_RCLOUD and SAR_RLIB_RCLOUD set
  SAR_PATHS_CONFIG   the path of another paths config (another canon), absolute or relative to
                     the directory the run starts in
USAGE
}
STAGED=0; STAGES=""
while [ $# -gt 0 ]; do
  case "$1" in
    --stages)   [ $# -ge 2 ] || { usage; exit 2; }; STAGES="$2"; STAGED=1; shift 2 ;;
    --stages=*) STAGES="${1#--stages=}"; STAGED=1; shift ;;
    -h|--help)  usage; exit 0 ;;
    *)          echo "unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done
WANT=" 1 2 "
if [ "$STAGED" = 1 ]; then
  WANT=" "
  [ -n "$STAGES" ] || { echo "--stages needs a list" >&2; usage; exit 2; }
  IFS=',' read -r -a _LIST <<< "$STAGES"
  [ "${#_LIST[@]}" -gt 0 ] || { usage; exit 2; }
  for S in "${_LIST[@]}"; do
    case "$S" in
      1|2|3est|3light|4check) WANT="$WANT$S " ;;
      *) echo "unknown stage: '$S'" >&2; usage; exit 2 ;;
    esac
  done
  case "$STAGES" in *,) echo "unknown stage: ''" >&2; usage; exit 2 ;; esac
fi
has() { [[ "$WANT" == *" $1 "* ]]; }
RUN_PAPER="${RUN_PAPER:-0}"; RUN_CLOUD_CELLS="${RUN_CLOUD_CELLS:-0}"
for _V in RUN_PAPER RUN_CLOUD_CELLS; do
  case "${!_V}" in 0|1) ;; *) echo "$_V must be 0 or 1, not '${!_V}'" >&2; usage; exit 2 ;; esac
done
PAPER=0   # 1 = a paper stage runs
if [ "$STAGED" = 0 ]; then PAPER="$RUN_PAPER"; elif has 3est || has 3light || has 4check; then PAPER=1; fi
if [ "$RUN_CLOUD_CELLS" = 1 ] && has 2; then
  _WHY=""
  if [ -z "${SAR_RSCRIPT_RCLOUD:-}" ] || [ -z "${SAR_RLIB_RCLOUD:-}" ]; then _WHY="a variable is unset"
  elif [ ! -f "$SAR_RSCRIPT_RCLOUD" ] || [ ! -x "$SAR_RSCRIPT_RCLOUD" ]; then _WHY="SAR_RSCRIPT_RCLOUD is not an executable file"
  elif [ ! -d "$SAR_RLIB_RCLOUD" ]; then _WHY="SAR_RLIB_RCLOUD is not a directory"; fi
  if [ -n "$_WHY" ]; then
    echo "RCLOUD_STACK_MISSING ($_WHY). RUN_CLOUD_CELLS=1 re-runs the large cells under the second R stack:" \
         "set SAR_RSCRIPT_RCLOUD to its Rscript and SAR_RLIB_RCLOUD to its package library." >&2
    exit 7
  fi
fi
# Use the locked Python environment built by setup/install_py.sh when it exists (pipeline/run_all.sh does
# the same); a bare python3 may resolve to other package versions.
PY="$REPO/setup/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
export PYTHONHASHSEED=0
mkdir -p output/logs
# the canon in force: D frames root, X expected root, CAL cal root, O output root, CANON canon root,
# CANON_NAME (october | M); a mixed or malformed paths config stops here
_ENV="$("$PY" analysis/lib/run_all_stages.py env)" || {
  if [ $? = 3 ]; then
    echo "PATHS_CONFIG_ERROR - SAR_PATHS_CONFIG names no paths config file (see the message above); give its path," \
         "for example SAR_PATHS_CONFIG=\$PWD/config/paths_october.yaml"
  else
    echo "CANON_ERROR - the paths config in force selects no valid canon"
  fi
  exit 6; }
eval "$_ENV"
export SAR_OUT="$O/estimates"   # where the drivers write their results
"$PY" analysis/lib/run_all_stages.py describe || { echo "CANON_ERROR - the canon in force has no valid event counts"; exit 6; }
if [ "$STAGED" = 0 ] && [ "$RUN_PAPER" = 1 ] && [ "$CANON_NAME" = M ]; then
  # A canon tree has no October-form paper stage (the robustness tables' default tree reads cells it does not
  # hold), so RUN_PAPER=1 runs the staged form there: the same as --stages 1,2,3est,3light,4check
  STAGED=1; WANT=" 1 2 3est 3light 4check "
fi
[ "$STAGED" = 0 ] || echo "== stages:$WANT=="
REPO_P="$(pwd -P)"
# a path as the stage 2 commands spell it: relative to the repository when it lies inside it
rel() { case "$1" in "$REPO_P"/*) printf '%s\n' "${1#"$REPO_P"/}" ;; *) printf '%s\n' "$1" ;; esac; }
SEAL="$O/paper/3est.seal.json"
REPORT=output/paper_check.md; [ "$STAGED" = 0 ] || REPORT="$O/paper_check.md"   # where tools/check_paper.py writes
EST3=" paper_gaps_zenou paper_gaps_switchers paper_gaps_toy paper_gaps_sw_p1p2 "   # the paper stage's estimating generators
SWAPPED=" paper_tables_rob paper_draft_tables paper_ledger_p3afar paper_fig_p1 paper_fig_p2 "   # staged mode runs their base_2026_10_11 tree instead
PHASE=all   # all = no flag; 3est / 3light filter the paper block below
want() {
  case "$PHASE" in
    3est)   [[ "$EST3" == *" $1 "* ]] ;;
    3light) [[ "$EST3" != *" $1 "* && "$SWAPPED" != *" $1 "* ]] ;;
    *)      return 0 ;;
  esac
}
# KEEP_GOING=1: a failed step does not stop the run; the run goes on and exits 2 at the end, naming each one
FAILED_STEPS=""
run() { want "$1" || return 0; local name="$1" log="output/logs/$1.log"; shift; echo "== $*"
  "$@" > "$log" 2>&1 || { echo "FAILED, see $log"; [ "${KEEP_GOING:-}" = 1 ] || exit 2; FAILED_STEPS="$FAILED_STEPS $name"; }; }
staged() { [ "$PHASE" = 3light ] || return 0; run "$@"; }   # staged mode only (never in the no-flag sequence)

echo
echo "== environment =="
"$PY" - <<'PYVER'
import sys
print(f"  interpreter  {sys.executable}")
print(f"  python       {sys.version.split()[0]}")
for mod in ("duckdb", "pyarrow", "pandas"):
    try:
        print(f"  {mod:<12} {__import__(mod).__version__}")
    except Exception as exc:                                    # noqa: BLE001
        print(f"  {mod:<12} NOT INSTALLED ({exc.__class__.__name__})")
PYVER
command -v Rscript >/dev/null && echo "  Rscript      $(Rscript -e 'cat(as.character(getRversion()))' 2>/dev/null)" \
                             || echo "  Rscript      NOT ON PATH - the estimation stage cannot run"

echo
echo "== what the stages need =="
THESIS="$("$PY" -c 'from analysis.lib.paths import load_paths; print(load_paths()["legacy_thesis"])')"
V2="$("$PY" -c 'from analysis.lib.paths import load_paths; print(load_paths()["legacy_v2_output"])')"
echo "  stages 1-2 (inputs, estimation)  need only this repository: the frames and recorded estimates are shipped"
if [ "$PAPER" = 1 ]; then
  if [ -d "$THESIS/thesis_report" ]; then
    echo "  PRESENT  manuscript tree  $THESIS/thesis_report   (the paper stage checks the manuscript)"
  else
    echo "  MISSING  manuscript tree  $THESIS/thesis_report
           a paper stage was asked for, but it cannot run: this package does not ship the manuscript
           sources. Point the paths config key legacy_thesis at the author's tree, or run stages 1-2 only."
    exit 4
  fi
  if [ -d "$V2" ]; then
    echo "  PRESENT  intermediates    $V2   (several paper generators read it)"
  else
    echo "  MISSING  intermediates    $V2
           a paper stage was asked for, but it cannot run without the author's frozen intermediate
           outputs. Point the paths config key legacy_v2_output at them, or run stages 1-2 only."
    exit 4
  fi
else
  echo "  paper stage                      not run: it is opt-in (RUN_PAPER=1, or --stages 3est,3light,4check)"
  echo "                                   and needs the author's manuscript tree, which this package does not ship"
fi
echo

stage_1() {
if [ "$CANON_NAME" = M ]; then
  "$PY" analysis/lib/run_all_stages.py unpack > output/logs/unpack.log || { echo "UNPACK_FAIL - see output/logs/unpack.log"; exit 1; }
  "$PY" analysis/lib/run_all_stages.py verify-manifests > output/logs/manifest.log || { echo "MANIFEST_FAIL - see output/logs/manifest.log"; exit 1; }
  "$PY" tools/r1_canon.py check "$CANON" > output/logs/canon_check.log || { echo "CANON_FAIL - see output/logs/canon_check.log"; exit 1; }
else
"$PY" tools/verify_manifest.py > output/logs/manifest.log || { echo "MANIFEST_FAIL - see output/logs/manifest.log"; exit 1; }
"$PY" tools/verify_manifest.py analysis/expected/MANIFEST.sha256 > output/logs/expected_manifest.log || { echo "MANIFEST_FAIL - see output/logs/expected_manifest.log"; exit 1; }
fi
echo "inputs verified"
}

# The second R stack, set up the way pipeline/aws/r1/run_cells.py ran the large cells: that stack's package
# library only, no R profile, 32 threads.
Rscript_rcloud() {
  ( export R_LIBS="$SAR_RLIB_RCLOUD" R_PROFILE_USER=/dev/null R_DATATABLE_NUM_THREADS=32 OMP_NUM_THREADS=32 \
           OPENBLAS_NUM_THREADS=32 POLARS_MAX_THREADS=32 PATH="$(dirname "$SAR_RSCRIPT_RCLOUD"):$PATH"
    exec "$SAR_RSCRIPT_RCLOUD" "$@" )
}

stage_2() {
local cells d x label driver frame ref out_name stack
local -a args
cells="$("$PY" analysis/lib/run_all_stages.py cells)" || { echo "CANON_ERROR - the canon's cell lists cannot be read"; exit 6; }
rm -rf -- "$SAR_OUT"; mkdir -p -- "$SAR_OUT"   # a result left by an earlier run is never compared
d="$(rel "$D")"; x="$(rel "$X")"
while IFS=$'\t' read -r label driver frame ref out_name stack <&3; do
  [ "$label" != label ] || continue                                  # the header line
  args=("$driver" "$label" "$d/$frame"); [ "$ref" = - ] || args+=("$x/$ref")
  if [ "$stack" = rmac ]; then
    run "${out_name%.json}" Rscript "${args[@]}"
  elif [ "$RUN_CLOUD_CELLS" = 1 ]; then
    run "${out_name%.json}" Rscript_rcloud "${args[@]}"
  else
    echo "== $label: a large cell, not re-run here (its custody record is checked below; RUN_CLOUD_CELLS=1 re-runs it)"
    continue
  fi
  # a driver names its result after the label; the recorded estimate it is compared with is out_name
  [ "$label.json" = "$out_name" ] || mv -- "$SAR_OUT/$label.json" "$SAR_OUT/$out_name"
done 3<<< "$cells"
"$PY" tools/compare_all.py
}

paper_block() {
echo "== paper =="
PP=analysis/paper
run paper_ledger_p3afar  "$PY" $PP/ledger_p3afar.py
staged paper_ledger_p3afar_base "$PY" $PP/ledger_p3afar.py --tree base_2026_10_11   # same ledger; draws Figure 7 in the base tree's form
run paper_tables_p3afar  "$PY" $PP/tables_p3afar.py
run paper_ledger_main    "$PY" $PP/ledger_main.py
run paper_ledger_carried "$PY" $PP/ledger_carried.py
staged paper_fig_compare_years    "$PY" $PP/fig_compare_years.py      # Figure 3; reads data_numbers_carried.json
staged paper_fig_comparison_pools "$PY" $PP/fig_comparison_pools.py   # Figure 4
run paper_gaps_zenou     "$PY" $PP/gaps_zenou.py
run paper_gaps_zero_dose "$PY" $PP/gaps_zero_dose.py
run paper_gaps_switchers Rscript $PP/gaps_switchers.R
run paper_gaps_toy       Rscript $PP/gaps_toy.R
run paper_ledger_funnel  "$PY" $PP/ledger_funnel.py
run paper_fig_exposure   "$PY" $PP/fig_exposure_population.py
run paper_fig_dose       "$PY" $PP/fig_dose_distribution.py
run paper_fig_hops       "$PY" $PP/fig_hops.py
run paper_fig_origins    "$PY" $PP/fig_star_origins.py   # appendix world map; pinned inputs only (data/paper_inputs/star_origins_2026-10, basemap)
run paper_tables_main    "$PY" $PP/tables_main.py
run paper_gaps_sw_p1p2   Rscript $PP/gaps_switchers_p1p2.R
run paper_ledger_p1p2    "$PY" $PP/ledger_p1p2.py
run paper_tables_p1p2    "$PY" $PP/tables_p1p2.py
run paper_fig_p1         "$PY" $PP/fig_p1.py
staged paper_fig_p1_base "$PY" $PP/fig_p1.py --tree base_2026_10_11   # Figure 5 in the base tree's form
run paper_fig_p2         "$PY" $PP/fig_p2.py
staged paper_fig_p2_base "$PY" $PP/fig_p2.py --tree base_2026_10_11   # Figure 6 in the base tree's form
run paper_ledger_rob     "$PY" $PP/ledger_robustness.py
run paper_tables_rob     "$PY" $PP/tables_robustness.py
staged paper_tables_rob_base "$PY" $PP/tables_robustness.py --tree base_2026_10_11
# the 2026-09-13 draft's three tables (Tables 1-3 of the compiled manuscript). The no-flag run reads the
# dated manuscript ledgers data_numbers_2026-10-23*.json (frozen copies of the ledgers above; section A of
# the check compares those copies with this run's output/paper). Staged 3light reads this run's own
# $O/paper ledgers (--paper-dir; written earlier in this block), so a run's tables carry its own numbers
run paper_draft_tables   "$PY" $PP/draft_2026_09_13_tables.py --out-dir output/paper/draft_2026_09_13
staged paper_draft_tables_base "$PY" $PP/draft_2026_09_13_tables.py --tree base_2026_10_11 --paper-dir "$O/paper" --out-dir "$O/paper/draft_2026_09_13"
}

check_block() {
run paper_check          "$PY" tools/check_paper.py
grep -E "^[0-9]+ checks:" "$REPORT" || { echo "PAPER_CHECK_SUMMARY_MISSING"; exit 3; }
}

stage_3est() {
mkdir -p "$O/paper"
rm -f "$SEAL"
PHASE=3est; paper_block; PHASE=all
"$PY" analysis/lib/run_all_stages.py seal --out "$SEAL" \
  --outputs "$O/paper/gaps_zenou.json" "$O/paper/gaps_switchers.json" "$O/paper/gaps_toy.json" "$O/paper/gaps_switchers_p1p2.json" \
  --inputs "$D/p1_frame_econ.csv" "$D/p1_frame_chemistry.csv" "$D/p1_frame_math_stats.csv" \
           "$D/p2_becoming_econ.csv" "$D/p2_becoming_chemistry.csv" "$D/p2_becoming_math_stats.csv" "$D/relationships_econ.csv" \
           "$X/P1_econ_fnfix.json" "$X/P1_fnfix_chemistry.json" "$X/P1_fnfix_math_stats.json" \
           "$X/P2_econ_fnfix.json" "$X/P2_fnfix_chemistry.json" "$X/P2_fnfix_math_stats.json" \
           "$CAL/frames_econ/build_report_econ920_2026-10.json" "$CAL/frames_econ/star_set_econ_cal2026-10.parquet" \
  > output/logs/3est_seal.log || { rc=$?; echo "SEAL_FAIL - see output/logs/3est_seal.log"; exit $rc; }
echo "3est sealed: $SEAL"
}

stage_3light() {
"$PY" analysis/lib/run_all_stages.py check-no-ssd > output/logs/3light_no_ssd.log || { rc=$?; echo "DATA_DISK - see output/logs/3light_no_ssd.log"; exit $rc; }
"$PY" analysis/lib/run_all_stages.py check-seal "$SEAL" \
  --require "$O/paper/gaps_zenou.json" "$O/paper/gaps_switchers.json" "$O/paper/gaps_toy.json" "$O/paper/gaps_switchers_p1p2.json" \
  > output/logs/3light_seal.log || { rc=$?; echo "SEAL_FAIL - run stage 3est on this canon first; see output/logs/3light_seal.log"; exit $rc; }
PHASE=3light; paper_block; PHASE=all
}

stage_4check() { check_block; }

for S in 1 2 3est 3light 4check; do
  if has "$S"; then "stage_$S"; fi
done
if [ "$STAGED" = 0 ]; then
  if [ "$RUN_PAPER" = 1 ]; then
    paper_block
    check_block
  else
    echo
    echo "stages 1-2 done; the comparison is in $(rel "$O")/compare_report.md. The paper stage did not run:"
    echo "it is opt-in (RUN_PAPER=1) and needs the author's manuscript tree."
  fi
fi
[ -z "$FAILED_STEPS" ] || { echo "FAILED_STEPS${FAILED_STEPS}"; exit 2; }
