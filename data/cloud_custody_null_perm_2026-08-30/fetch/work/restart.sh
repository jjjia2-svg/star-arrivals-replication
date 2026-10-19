#!/bin/bash
# Thread-capped restart. The first attempt ran 12 R processes that each spawned ~198 threads
# (3,871 threads on 64 vCPU, measured), which made every run 2.7x slower than solo. Capping the
# per-process thread pools keeps total threads near the core count.
set -u
cd ~/work
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4 R_DATATABLE_NUM_THREADS=4
export SAR_OUT=out
mkdir -p out out_null logs jobs
rm -f jobs/t*.sh
i=0
while IFS= read -r line; do
  [ -z "$line" ] && continue
  i=$((i+1)); f=jobs/t$(printf %03d $i).sh
  { echo '#!/bin/bash'
    echo 'cd ~/work'
    echo 'export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4 R_DATATABLE_NUM_THREADS=4'
    echo 'export SAR_OUT=out'
    echo "$line"; } > "$f"
  chmod +x "$f"
done < jobs_todo.txt
echo "QUEUED $i units $(date -u +%FT%TZ)" >> ~/work/progress2.log
# 14 processes x 27.7 GB measured peak = 388 GB of 495 GB; 14 x 4 threads = 56 of 64 vCPU.
ls jobs/t*.sh | xargs -P 14 -I{} bash -c 'b=$(basename {} .sh); {} > logs/$b.log 2>&1; echo "$b rc=$? $(date -u +%FT%TZ)" >> ~/work/progress2.log'
echo "ALL_DONE_MARKER $(date -u +%FT%TZ)" | tee ~/RESULT.txt
