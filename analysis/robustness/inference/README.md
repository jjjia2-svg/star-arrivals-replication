# analysis/robustness/inference — T5 event-level permutation (randomization) inference

**Why.** Chemistry has 38 arrival events and math_stats 33. The estimator's conventional
cluster-robust SEs (persons for P1/P2, pairs or events for P3) lean on asymptotics that are
shaky with this few treatment-level units — the treatment varies at the EVENT level. The
standard few-cluster remedy for a timing design is randomization inference on treatment
timing: hold every panel, outcome, dose, roster and pair set fixed; reassign the observed
arrival YEARS across the observed events (a uniform random permutation of the arrival-year
labels — the multiset of arrival years and the event count are preserved exactly);
re-estimate; and ask how often scrambled timing produces an effect as large as the observed
one. Economics (116 events) is included as a benchmark.

**The interface.** Each verbatim driver consumes the arrival year only through the treatment
column: P1 `D = dose_topic * 1{year >= arrival_e}`, P2 `D = 1{year >= arrival_e}`, P3 A_far
`D = 1{year >= arrival_ev}`. `run_perm.R` proves the reconstruction row-for-row (stopifnot)
before any draw, then rebuilds D from the permuted arrivals by the same rule. Prep is a
line-for-line copy of the verbatim driver's (P1: union channel, the headline cell; P3 A_far:
one estimation per draw, event-clustered — the point estimate is identical under pair
clustering, see `analysis/estimation/README.md` on the `_evcl` drivers).

**Controls.** Permutation 0 is the identity and must reproduce the frozen gold in
`analysis/expected/` (ate and se to the gold's 8-decimal rounding, asserted in-driver);
`run_all_perm.sh` runs all nine controls before any permutation.

**Cells (9).** P1 union, P2, P3 A_far x {econ, chemistry, math_stats}. B = 500 permutations
per cell (`SAR_PERM_B` overrides), seed `config/seeds.yaml: permutation_seed` (20260829),
draw i uses `set.seed(seed + i)` so any chunk reproduces in isolation.

**P-values.** `summarize_perm.py`:
`p_perm = (1 + #{|stat_b| >= |stat_obs|}) / (B_ok + 1)` for `stat` = ATE and t = ATE/SE;
failed draws are counted and excluded from B_ok, never silently dropped. The conventional
asymptotic p (2*(1-Phi(|t|)) from the frozen SE) is printed beside them.

**Run.** `bash analysis/robustness/inference/run_all_perm.sh` (~2.5-4 h wall at 6 workers,
local, $0). Outputs: `data/robustness_2026-08-29_b/perm/` — `control/` (9 identity runs),
`raw/` (per-chunk CSVs + logs), `perm_summary.{csv,json}`, `runlog_perm.log`, MANIFEST.

**Reading it.** A permuted arrival can fall outside an event's ±5-year frame window, making
that event never-treated (or always-treated) in-sample under that draw; that is part of the
randomization distribution (the `n_treated_events` column tracks it). The test's null is a
sharp "timing doesn't matter"; it does not repair the P1 economics placebo violation — it
answers only whether the few-event conventional p-values overstate significance.
