#!/bin/bash
# pipeline/aws/cal2026-10/driver.sh — the instance-side driver TEMPLATE for the October batch.
# Shipped inside the payload (so payload.md5 covers its bytes, as the 08-30 batch did) and started
# by run_cloud.sh as `nohup bash driver.sh > driver.out 2>&1 < /dev/null &` in ~/work.
#
# It reads three files the payload carries, nothing hand-typed here:
#   driver.env         MARKER=... PAR=... THREADS=...          (written by cloudkit.py prep)
#   jobs_serial.txt    name<TAB>outdir<TAB>command   one per line, run ONE AT A TIME under
#                      /usr/bin/time -v (the P3 econ full pair panel peaks near 300 GiB of 495)
#   jobs_parallel.txt  name<TAB>outdir<TAB>command   run PAR-wide with THREADS-capped BLAS/OMP/
#                      data.table/polars pools (restart.sh 2026-08-30: 12 R processes x ~198
#                      threads = 3,871 threads on 64 vCPU made every run 2.7x slower)
# Contract (cloudkit.py custody re-counts it):
#   * md5sum -c payload.md5 first; its lines go to md5check.log AND driver.log (the instance's own
#     evidence that it saw the shipped bytes); any FAILED line -> FAIL marker, nothing runs;
#   * every unit appends exactly one `SERIAL <name> rc=<n>` / `PAR <unit> rc=<n>` line to
#     progress.log; stdout -> logs/<unit>.log; time -v -> timev/<name>.txt (serial cells);
#   * RESULT.txt gets ALL_DONE_MARKER_<MARKER> only if EVERY expected unit reported rc=0 — the
#     08-30 restart.sh wrote its marker unconditionally after xargs and two OOM-killed units
#     (rc=137) went unnoticed until the raw files were counted (maps.json check:aws #5).
# Test hooks (never set on the instance): SAR_WORK (work dir, default ~/work), TIME_BIN
# (default /usr/bin/time), MD5SUM (default md5sum). Everything else is relative to the work dir.
set -uo pipefail
WORK="${SAR_WORK:-$HOME/work}"
cd "$WORK" || { echo "no work dir $WORK"; exit 1; }
export R_LIBS_USER="${R_LIBS_USER:-$HOME/Rlib}"
TIME_BIN="${TIME_BIN:-/usr/bin/time}"
MD5="${MD5SUM:-md5sum}"
. ./driver.env
D="$WORK/driver.log"
P="$WORK/progress.log"
now() { date -u +%FT%TZ; }
echo "[driver] start $(now) marker=$MARKER par=$PAR threads=$THREADS host=$(hostname)" | tee -a "$D"

"$MD5" -c payload.md5 > md5check.log 2>&1; MD5RC=$?
cat md5check.log | tee -a "$D"
if [ "$MD5RC" != "0" ]; then
  echo "FAIL_MARKER_$MARKER" > RESULT.txt
  echo "MD5_FAIL $(now)" | tee -a "$D"
  exit 1
fi
echo "MD5_OK $(now)" | tee -a "$D"
mkdir -p out out_perm out_null out_predate out_predate_control logs timev units
: > "$P"

# ---- serial phase: one memory-heavy cell at a time --------------------------------------------
NSER=0
set -f                                   # the command line is word-split, never globbed
while IFS="$(printf '\t')" read -r name outdir cmd || [ -n "${name:-}" ]; do
  [ -z "${name:-}" ] && continue
  case "$name" in \#*) continue ;; esac
  NSER=$((NSER + 1))
  echo "[serial] $name start $(now)" | tee -a "$D"
  # stdin off the job list: inside `while read ... done < jobs_serial.txt` a child that reads
  # stdin would swallow the remaining lines (2026-09-22 review; the fake Rscript in the test reads it)
  # shellcheck disable=SC2086
  SAR_OUT="$outdir" "$TIME_BIN" -v $cmd > "logs/$name.log" 2> "timev/$name.txt" < /dev/null
  rc=$?
  echo "SERIAL $name rc=$rc $(now)" | tee -a "$D" >> "$P"
done < jobs_serial.txt
set +f

# ---- parallel phase: thread-capped units -------------------------------------------------------
export OMP_NUM_THREADS="$THREADS" OPENBLAS_NUM_THREADS="$THREADS" MKL_NUM_THREADS="$THREADS" \
       R_DATATABLE_NUM_THREADS="$THREADS" POLARS_MAX_THREADS="$THREADS"
NPAR=0
rm -f units/u*.sh
while IFS="$(printf '\t')" read -r name outdir cmd || [ -n "${name:-}" ]; do
  [ -z "${name:-}" ] && continue
  case "$name" in \#*) continue ;; esac
  NPAR=$((NPAR + 1))
  u="units/u$(printf %03d "$NPAR")_$name.sh"
  {
    echo '#!/bin/bash'
    echo "cd \"$WORK\""
    echo "export R_LIBS_USER=\"$R_LIBS_USER\" SAR_OUT=\"$outdir\""
    echo "export OMP_NUM_THREADS=$THREADS OPENBLAS_NUM_THREADS=$THREADS MKL_NUM_THREADS=$THREADS R_DATATABLE_NUM_THREADS=$THREADS POLARS_MAX_THREADS=$THREADS"
    echo "exec $cmd"
  } > "$u"
  chmod +x "$u"
done < jobs_parallel.txt
if [ "$NPAR" -gt 0 ]; then
  echo "[parallel] $NPAR units, xargs -P $PAR, $THREADS threads each, start $(now)" | tee -a "$D"
  export SAR_PROGRESS="$P"
  find units -name 'u*.sh' | sort | xargs -P "$PAR" -I{} bash -c \
    'u="{}"; b=$(basename "$u" .sh); "$u" > "logs/$b.log" 2>&1; rc=$?; echo "PAR $b rc=$rc $(date -u +%FT%TZ)" >> "$SAR_PROGRESS"; exit 0'
  echo "[parallel] end $(now)" | tee -a "$D"
fi

# ---- verdict: every expected unit reported, and every one exited 0 ------------------------------
EXPECTED=$((NSER + NPAR))
REPORTED=$(grep -c -E '^(SERIAL|PAR) ' "$P")
NBAD=$(grep -c -E '^(SERIAL|PAR) \S+ rc=[1-9]' "$P")
if [ "$MD5RC" = "0" ] && [ "$NBAD" = "0" ] && [ "$REPORTED" = "$EXPECTED" ]; then
  echo "ALL_DONE_MARKER_$MARKER" > RESULT.txt
else
  echo "FAIL_MARKER_$MARKER" > RESULT.txt
fi
echo "[driver] end $(now) units=$REPORTED/$EXPECTED failed=$NBAD result=$(cat RESULT.txt)" | tee -a "$D"
