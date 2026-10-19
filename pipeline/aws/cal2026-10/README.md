# `pipeline/aws/cal2026-10/` — the runnable launcher for the October estimation cells

The two scripts one level up (`launch_p3_dcdh.sh`, `launch_u1_fetch.sh`) print their runbook and
exit. This directory is the first one in the repository that can actually rent the machine
(since 2026-09-16 heavy re-estimation goes straight to AWS; the plan of 2026-09-22, §5 and the
"AWS launcher" row of its table, names it `pipeline/aws/run_cloud_2026-10.sh`; it lives
here so its four files stay together). Nothing here runs from `pipeline/run_all.sh` or
`analysis/run_all.sh`; `run_cloud.sh` is the only file that spends money, and only when you type it.

| file | role |
|---|---|
| `cloudkit.py` | the local half (no `aws`, no R): `prep` assembles the payload + `payload.md5` + the two job lists + the preflight record and cost estimate; `check-md5` is the instance's own step run locally; `record` writes `launch_record.json` and prints the cost line; `custody` writes `custody_cal2026-10.json` and exits 1 on any broken link |
| `bootstrap.sh` | the 2026-08-28 environment recipe (r2u + rustup source build of R polars) plus `r-cran-fixest`; PKG_OK asserts every package; logs under `~/work` |
| `driver.sh` | the instance-side template: `md5sum -c payload.md5` first, then the serial cells one at a time under `/usr/bin/time -v`, then the thread-capped parallel units; `ALL_DONE` only when every unit reported `rc=0` |
| `run_cloud.sh` | launch → ssh → bootstrap → ship + md5 on the instance → driver → poll → fetch whatever happened → terminate → record; resumable state markers; EXIT trap salvages and terminates |
| `prep_t5_batch.sh` | the SECOND batch (2026-09-23): assembles the Panel 1 / Panel 2 timing-permutation units of `analysis/robustness/inference/run_all_perm.sh` as parallel units (`cloudkit.py prep --groups '' --extra-parallel …`) and ends with `run_cloud.sh --dry-run`; it never launches |

## The batch (what `prep` writes into `jobs_serial.txt` / `jobs_parallel.txt`)

Serial, in this order (cheap first): `P3_fnfix_chemistry`, `P3_econ_fnfix` (`run_p3.R`);
`P3evcl_chemistry`, `P3evcl_econ` (`run_p3_evcl.R`); the predate shift-0 CONTROLS
(`run_predate.R p3 <main label> ... 0` into `out_predate_control/`, must be compare_json-EQUAL to
the main cell of the same batch); `P3pd2_chemistry_full`, `P3pd2_econ_full` (`run_predate.R p3 ... 2`
— the full-panel date-shift cells `analysis/robustness/predate/README.md` lists as NOT RUN).
Parallel: per field on `p3_afar_pos_<f>.parquet`, `run_perm.R p3tp` identity unit `0 0` (the
CONTROL asserted inside the driver) + 500 permutations, and `run_null.R` 200 simulations — the
2026-08-30 grammar (`data/cloud_custody_null_perm_2026-08-30/fetch/work/jobs.txt`), seed base
20260830, econ chunks of 5, other fields 50. Extra full-panel cells (D7: top-5% events, three-bin
dose) go in with `--extra-serial 'NAME|OUTDIR|Rscript run_p3.R NAME frame.parquet' --extra-file
path/to/frame.parquet`.

Every assumption (cell table, chunking, parallelism 12 × 4 threads, the cost basis, the fixest
apt name) is numbered A1–A7 in `cloudkit.py`'s docstring.

## Running it (when the October frames exist)

```bash
PY=setup/.venv/bin/python; K=pipeline/aws/cal2026-10
$PY $K/cloudkit.py prep --frames data/cal2026-10/frames --pos-frames data/cal2026-10/frames \
    --refs data/cal2026-10/estimates --out /private/tmp/cal2026-10_payload \
    --custody data/cal2026-10/cloud
bash $K/run_cloud.sh --payload /private/tmp/cal2026-10_payload --custody data/cal2026-10/cloud --dry-run
bash $K/run_cloud.sh --payload /private/tmp/cal2026-10_payload --custody data/cal2026-10/cloud
$PY tools/verify_cloud_custody.py --custody data/cal2026-10/cloud      # -> CUSTODY_OK
```

`--dry-run` verifies the payload's md5 list locally, prints the instance spec, the fuse, the
cost estimate and the two `aws` commands as text, and exits before anything is armed. A real run
that is interrupted leaves `data/cal2026-10/cloud/state/`; `--resume` continues against the same
instance, a fresh `--custody` dir starts over. The EXIT trap means the script never returns with
the instance still running; the user-data `shutdown -h +600` fuse is the backstop.

Cost line printed at the end and stored in `launch_record.json`:
`(terminate_time_utc − launch_time_utc) × $4.032/h`. Preflight estimate for the full batch
(`cost_estimate` in `custody_preflight.json`): ~2 h ≈ $9 — the 08-28 four cells (~$2.3) + the
two predate cells and their controls (~$1.7) + the 08-30-sized permutation/null phase (~$5).

## The second batch: T5 permutations for Panels 1 and 2 (`prep_t5_batch.sh`, 2026-09-23)

`run_all_perm.sh` (T5 randomization inference) is 9 cells × 500 timing permutations — too heavy
for the local machine beside the running batteries. Its three Panel 3 cells are the `perm` group of
the first batch; its six Panel 1 / Panel 2 cells go up as a second batch of PARALLEL units:

```bash
bash pipeline/aws/cal2026-10/prep_t5_batch.sh          # prep + dry-run; never launches
bash pipeline/aws/cal2026-10/run_cloud.sh --payload /private/tmp/cal2026-10_payload_t5 \
     --custody data/cal2026-10/cloud_t5                # the deliberate launch, typed separately
```

The script reads the six `p1`/`p2` rows of `run_all_perm.sh`'s CELLS table, B (500) and CHUNK (50)
from that file, and the seed from `config/seeds.yaml` (`permutation_seed`, asserted equal to the
battery's SEED); per cell it emits the identity unit `0 0` first (perm 0 must reproduce the
reference gold — asserted inside `run_perm.R`, so a drifted gold fails the unit and the driver
refuses ALL_DONE) then ten chunks of 50: 66 units of
`Rscript run_perm.R <mode> <label> <frame> <ref> <seed> <from> <to>` into `out_perm/`. Frames come
from `data/frames` (the October canon), the reference JSONs from `analysis/expected` (the October
golds, shipped via `--extra-file`). For this, `cloudkit.py prep` gained
`--extra-parallel 'NAME|OUTDIR|COMMAND'` (the `--extra-serial` grammar, appended to
`jobs_parallel.txt` after the group units) and an explicit `--groups ''` meaning no group; an
omitted `--groups` still means every group. The A6 estimate applies its fixed 81-minute
parallel-phase basis (the 08-30 batch) to any batch that has parallel units. Controls:
`tests/test_aws_cal2026_10_t5.py` — the unit table equals the battery's token for token, the dry
run completes with no `aws` on PATH and leaves no instance id, the driver and custody handle an
extra-only payload, a seed disagreement stops the prep.

## Controls (`tests/test_aws_cal2026_10.py`, no AWS needed)

* `prep` on the 2026-08-28 frames reproduces `data/cal2026-08-28/cloud/payload.md5` line for line
  and the four `Rscript` invocations of `data/cal2026-08-28/cloud/driver.sh` token for token.
* `prep` on today's pos frames reproduces the 2026-08-30 shipped md5s of `p3_afar_pos_*.parquet`,
  `P3cut_pos_*.json`, `run_perm.R` and `run_null.R` exactly, and the 08-30 unit grammar (every
  full chunk of the 08-30 `jobs.txt` is generated; every econ permutation 0..500 exactly once).
* `driver.sh` runs end to end on a fake `Rscript`/`time`: ALL_DONE when every unit exits 0; FAIL
  with the unit's `rc=` line when one does not (the 08-30 unconditional-marker defect).
* `run_cloud.sh --dry-run` exits 0 on a good payload and 1 on a corrupted one; no `aws` runs.
* `record` + `custody` on a synthetic run, then `verify_cloud_custody.py --custody` → CUSTODY_OK,
  and CUSTODY_FAIL after one payload byte changes; the default invocation is unchanged.
* (2026-09-22 review) `run_cloud.sh` END TO END on fake `aws`/`ssh`/`scp` binaries with the
  payload and custody dirs under a path containing a space (this checkout's path has one): the
  whole sequence runs, exit 0, CUSTODY_OK, exactly one `run-instances` and one
  `terminate-instances`; a second invocation without `--resume` is refused. The first version
  passed the ssh options as one unquoted string and word-split on the space (ssh took
  `.../known_hosts` as the host), so no ssh call could have reached the instance from here.
* (2026-09-22 review) every `pgrep -f` probe is bracketed (`[b]ash driver.sh`): procps pgrep
  matches the invoking shell's own command line, so the plain pattern reported the driver as
  already running and never started it (a nine-hour idle instance). And the serial cells get
  `< /dev/null`: inside `while read … < jobs_serial.txt` a child that reads stdin swallows the
  rest of the job list (the fake Rscript reads stdin; on the old driver 1 of 8 cells ran).
