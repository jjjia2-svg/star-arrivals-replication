#!/bin/bash
# driver.sh — the two fnfix P3 cells run in order (chemistry, then economics), one DONE marker per task; payload.md5 does not include this file (lesson of 08-13)
set -uo pipefail
cd ~
export R_LIBS_USER="$HOME/Rlib"
echo "[driver] start $(date -u +%FT%TZ)" | tee -a ~/driver.log
md5sum -c payload.md5 || { echo "FAIL_MARKER_2026_08_16" > ~/RESULT.txt; echo MD5_FAIL | tee -a ~/driver.log; exit 1; }
mkdir -p out
/usr/bin/time -v Rscript run_p3.R "P3_fnfix_chemistry" pairs_slim_chem_fnfix.parquet > log_chem.txt 2> timev_chem.txt
echo "JOB1_EXIT=$?" | tee -a ~/driver.log
/usr/bin/time -v Rscript run_p3.R "P3_econ_fnfix"      pairs_slim_econ_fnfix.parquet > log_econ.txt 2> timev_econ.txt
J2=$?
echo "JOB2_EXIT=$J2" | tee -a ~/driver.log
if grep -q "JOB1_EXIT=0" ~/driver.log && [ "$J2" = "0" ]; then echo "ALL_DONE_MARKER_2026_08_16" > ~/RESULT.txt; else echo "FAIL_MARKER_2026_08_16" > ~/RESULT.txt; fi
echo "[driver] end $(date -u +%FT%TZ)" | tee -a ~/driver.log
