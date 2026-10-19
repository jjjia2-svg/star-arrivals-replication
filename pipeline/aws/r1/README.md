# pipeline/aws/r1 — the AWS scripts of the final rerun

The data behind the report (`data/report/`) were built on AWS by the scripts in this folder: the
event tables and rosters, the panels, the 27 headline estimates, the robustness runs and the final
assembly of the data and the printed numbers. Nothing here runs from `analysis/run_all.sh`, and the
instance scripts refuse to run anywhere but an AWS instance of this project. They are published so
the construction can be read and audited. Their settings are in `config/r1/`.

## What ran, where, for how long, at what cost

| job kind | settled jobs | instance type | instance hours | USD |
|---|---:|---|---:|---:|
| `addlist` | 4 | m6i.large | 0.3045 | 0.0303 |
| `dossier` | 3 | r6i.8xlarge | 0.2905 | 0.5888 |
| `envbuild` | 4 | c6i.4xlarge | 0.8126 | 0.5615 |
| `envbuild_py` | 1 | c6i.4xlarge | 0.0914 | 0.0632 |
| `fielddiag` | 2 | r6i.8xlarge | 0.1675 | 0.3395 |
| `final` | 14 | m6i.2xlarge | 4.5082 | 1.8793 |
| `finalb0` | 5 | m6i.2xlarge | 1.3973 | 0.5517 |
| `j0` | 6 | r6i.16xlarge | 3.5275 | 14.3774 |
| `j1a` | 21 | r6i.16xlarge | 12.2081 | 49.7583 |
| `j1b` | 7 | r6i.16xlarge | 25.9916 | 105.9375 |
| `jp` | 1 | r6i.16xlarge | 0.2589 | 1.0496 |
| `merge` | 4 | m6i.large | 0.3022 | 0.0301 |
| `pin` | 2 | m6i.4xlarge | 1.1042 | 0.8843 |
| `rankdiff` | 1 | m6i.large | 0.0714 | 0.0071 |
| `rec` | 1 | m6i.large | 0.0833 | 0.0083 |
| `recder` | 1 | m6i.large | 0.1919 | 0.0195 |
| `report` | 5 | m6i.large | 0.3755 | 0.0373 |
| `rk6a` | 4 | r6i.8xlarge | 1.4898 | 3.0198 |
| `rk6b` | 6 | r6i.8xlarge | 1.9756 | 4.0044 |
| `rosteraudit` | 2 | m6i.large | 0.1517 | 0.0151 |
| `rosterbase` | 1 | m6i.large | 0.0750 | 0.0074 |
| `rostermatch` | 2 | r6i.8xlarge | 1.4070 | 2.8674 |
| `rostermerge` | 3 | m6i.large | 0.2297 | 0.0229 |
| `test` | 66 | m6i.xlarge | 12.5569 | 2.4658 |
| `test_big` | 6 | r6i.8xlarge | 4.0886 | 8.3771 |

Settled instance charges through final-14: **USD 199.4336**, including USD 2.5300 in separately
recorded adjustments. Hours and charges include retries. Storage and transfer charges are excluded.
The numeric snapshot and source-ledger hash are in `docs/public/release_metrics.json`; the source
spend ledger is not shipped.


## Where the records are

| record | in this package |
|---|---|
| the panels, the recorded estimates, the event tables and rosters | `data/report/` (`frames/`, `expected/`, `cal/`) |
| the custody of the 4 large cells (panel and driver hashes, fetched results) | `data/report/custody/` |
| the robustness results and their cloud runs | `data/report/cal/robustness/`, `data/report/cal/cloud/`, `data/report/cal/cloud_t5/` |
| the numbers the report prints | `data/report/paper_numbers/` |
| instance logs, full stage outputs, the cost ledger | not shipped |

## How the runs were controlled

- One instance at a time. Every launch was booked in a cost ledger before it started and settled
  after the instance was terminated.
- No SSH. Instances never called OpenAlex and never committed, pushed or tagged; they wrote to the
  storage bucket under one prefix only.
- Each job ran from one commit of this repository. The instance scripts were copied to `/work/` and
  run there, never in place.
- Every stage recorded the fingerprints of its inputs and products. A later stage checked them before
  using anything, and every step stopped on a mismatch.

## The files

| files | what they do |
|---|---|
| `r1kit.py` | the launcher (run on the author's machine): payload from a commit, boot script, one instance, watch, results, cost |
| `userdata.sh.tmpl` | the instance boot: time limit, payload checks, environment restore, the job's steps, upload, power off |
| `build_env.sh`, `install_stack.R`, `versions_check.py` | the pinned Python, R (two stacks) and TeX environments, and the version check at boot |
| `run_stages.py` | the multi-stage driver: per-stage status, fingerprints, products and done markers |
| `run_cells.py` | the estimation cells of `config/r1/cells/*.tsv`, each under its R stack, compared with the recorded estimates |
| `calls_lib.py`, `rank_r1.py`, `restake_r1.py`, `verdict_source.py`, `events_r1.py` | the star ranking and the event tables (`cal/counts.json`) |
| `econ920_m.py`, `chemmath_m.py`, `dose_chemmath.py`, `r1_dose_excl.py`, `network_freeze.py`, `edge_table.py`, `patch_assemble.py`, `missing_persons.py` | the panel builds |
| `promote_r1.py` | packs the panels and the 27 recorded estimates |
| `mem_probe.py`, `par_plan.py`, `rob_jobs_r1.py`, `run_units.py`, `rob_post_r1.py`, `run_robustness_r1.sh`, `fig4_counts.py` | the robustness runs, planned by measured memory |
| `restore_upstream.py`, `final_stage.py` | the final assembly: the data of `data/report/`, the paper numbers and their checks |
| `sandbox.py`, `gates.py`, `verify_inputs.py`, `check_pin.py`, `config_check.py`, `run_config.py` | the controls: the October version rebuilt exactly before the rerun, protected inputs, input pins |
| `recover_rk.py`, `rk6_requests.py`, `rk6b_rank.py`, `replay_derivations.py`, `dossier_pack.py` | recovery and review jobs that rebuilt earlier inputs from frozen records |
| `run_tests_r1.py`, `reverse_proof_s10.py`, `v3net_oracle_spec.py` | the test jobs (the repository's tests run on AWS) |
