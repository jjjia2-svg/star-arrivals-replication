#!/bin/bash
# driver.sh — event-level clustering robustness: the two P3 cells run in order (chemistry, then economics); payload.md5 does not include this file (lesson of 08-13); marker constant 2026_08_16E
set -uo pipefail
cd ~
export R_LIBS_USER="$HOME/Rlib"
echo "[driver] start $(date -u +%FT%TZ)" | tee -a ~/driver.log
md5sum -c payload.md5 || { echo "FAIL_MARKER_2026_08_16E" > ~/RESULT.txt; echo MD5_FAIL | tee -a ~/driver.log; exit 1; }
mkdir -p out
/usr/bin/time -v Rscript run_p3_evcl.R "P3evcl_chemistry" pairs_slim_ev_chemistry.parquet > log_chem.txt 2> timev_chem.txt
echo "JOB1_EXIT=$?" | tee -a ~/driver.log
/usr/bin/time -v Rscript run_p3_evcl.R "P3evcl_econ"      pairs_slim_ev_econ.parquet      > log_econ.txt 2> timev_econ.txt
J2=$?
echo "JOB2_EXIT=$J2" | tee -a ~/driver.log
if grep -q "JOB1_EXIT=0" ~/driver.log && [ "$J2" = "0" ]; then echo "ALL_DONE_MARKER_2026_08_16E" > ~/RESULT.txt; else echo "FAIL_MARKER_2026_08_16E" > ~/RESULT.txt; fi
echo "[driver] end $(date -u +%FT%TZ)" | tee -a ~/driver.log
