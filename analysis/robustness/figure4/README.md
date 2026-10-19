# analysis/robustness/figure4 — comparison-relation counts for Figure 4 (R1 N5)

**What it gives:** for each model, cohort and year, how many relations the dCDH estimator could use
as comparisons — the counts Figure 4 (`figB.py`, key `PINNED`) is waiting for. The counts are made
for the record. The figure draws none of them until the author pins them.

## Files

| file | what it does |
|---|---|
| `run_save_sample.R` | `Rscript run_save_sample.R <label> <frame>` (the `run_cells.py` grammar). The label prefix picks the model: `P1*` = `analysis/estimation/run_p1.R` (union / network / dept), `P2*` = `run_p2.R`, `P3*` = `run_p3_tp.R` (pair and event clustering). Each `# ---- copied from` block is that verbatim driver, line for line. The only change is `, save_sample=TRUE` in each `did_multiplegt_dyn` call. |
| `../../../config/r1/cells/fig4_M.tsv` | the nine J1b cells: P1 and P2 for econ / chemistry / math_stats, and `P3cut_pos_<field>` (Model 3, A_far positive dose), on the M frames, with the same `out_name` as `config/r1/cells/M.tsv` |
| `../../../pipeline/aws/r1/fig4_counts.py` | turns the sample files into `fig4_counts.csv` and `fig4_counts.json` |

## Outputs per cell (in `$SAR_OUT`)

- `<label>.json`: compare_json-EQUAL to the verbatim driver's. `save_sample` is read after the
  estimate and changes nothing.
- `<label>_sample.csv.gz`: `channel, grp_id, year, D, did_sample, did_effect, arrival, zero_dose`.
  These are the rows of `r$save_sample` (the estimation sample, tagged by the package), plus each
  group's `arrival` (first year with post / D > 0) and `zero_dose` (P1: `dose_topic == 0`; NA for
  P2 and P3). P2 and P3 have one channel, written `all`. P3 keeps the pair-cluster run's sample,
  because the event-cluster run tags the same cells (toy test).
- `<label>_switchers.csv`: `channel, kind, k, n, switchers`, taken from the package's Effects and
  Placebos tables.

## The counting rule (author, 2026-10-03; `figB.py`)

A comparison relation in year *t* for cohort *G* is a relation in the estimation sample with:

- a row in *G−1* and a row in *t*;
- D = 0 in *G−1*;
- no switch by *t*.

Never-switchers count. Model 1 splits the pool into zero-dose relations and positive-dose relations
whose star has not arrived yet. Models 2 and 3 have one pool: star not yet arrived.

Effect *k* falls in year *G−1+k*. Placebo *k* falls in year *G−1−k* and uses effect *k*'s pool,
keeping only the relations that also have a row in the placebo year.

The package tags groups, not "used as a control in year *t*". So the pools follow the rule, and
only the switcher counts can be checked against the estimator: groups tagged `did_effect == k` must
equal the Effects table's `Switchers` column. A mismatch fails the stage.
`tests/test_r1_fig4.py::test_rule_parity_with_figB` reproduces `figB.py`'s draft counts.

## Proofs that the option is neutral (no second M run)

1. A toy panel (`tests/test_r1_fig4_r.py`): the package gives the same results with and without
   `save_sample`, and each model's JSON equals the verbatim driver's.
2. In J1b, `fig4_m` runs `run_cells.py --compare --require-equal` against J1a's main JSONs, which
   come from the same commit and the same frames.

Star-departure robustness (F20) is out of scope (since 2026-10-15: the paper prints none).
