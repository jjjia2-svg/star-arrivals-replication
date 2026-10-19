#!/bin/bash
# driver.sh — cal2026-08-28 T5: the four cloud cells in sequence (chem main, econ main, chem
# evcl, econ evcl — cheap cell first, the M1 pattern); payload.md5 does not include this file
# (08-13 lesson); marker constant 2026_08_28C. The md5 verification output is tee'd into driver.log
# so the custody chain keeps the INSTANCE's own evidence, not only the refusal behaviour.
set -uo pipefail
cd ~
export R_LIBS_USER="$HOME/Rlib"
echo "[driver] start $(date -u +%FT%TZ)" | tee -a ~/driver.log
md5sum -c payload.md5 2>&1 | tee -a ~/driver.log || { echo "FAIL_MARKER_2026_08_28C" > ~/RESULT.txt; echo MD5_FAIL | tee -a ~/driver.log; exit 1; }
mkdir -p out
/usr/bin/time -v Rscript run_p3.R      "P3_fnfix_chemistry" p3_slim_chemistry.parquet    > log_chem.txt   2> timev_chem.txt
echo "JOB1_EXIT=$?" | tee -a ~/driver.log
/usr/bin/time -v Rscript run_p3.R      "P3_econ_fnfix"      p3_slim_econ.parquet         > log_econ.txt   2> timev_econ.txt
echo "JOB2_EXIT=$?" | tee -a ~/driver.log
/usr/bin/time -v Rscript run_p3_evcl.R "P3evcl_chemistry"   p3_slim_ev_chemistry.parquet > log_evchem.txt 2> timev_evchem.txt
echo "JOB3_EXIT=$?" | tee -a ~/driver.log
/usr/bin/time -v Rscript run_p3_evcl.R "P3evcl_econ"        p3_slim_ev_econ.parquet      > log_evecon.txt 2> timev_evecon.txt
J4=$?
echo "JOB4_EXIT=$J4" | tee -a ~/driver.log
if grep -q "JOB1_EXIT=0" ~/driver.log && grep -q "JOB2_EXIT=0" ~/driver.log && grep -q "JOB3_EXIT=0" ~/driver.log && [ "$J4" = "0" ]; then echo "ALL_DONE_MARKER_2026_08_28C" > ~/RESULT.txt; else echo "FAIL_MARKER_2026_08_28C" > ~/RESULT.txt; fi
echo "[driver] end $(date -u +%FT%TZ)" | tee -a ~/driver.log
