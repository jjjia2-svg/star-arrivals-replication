# data/fwci

The field-weighted-citation-impact (FWCI) baseline: the denominator every frozen P1 frame's outcome
variable is divided by, plus the run records that reconcile it to the OpenAlex snapshot.

| file | what it is |
|---|---|
| `fwci_baseline_pop_full.parquet` | 543,037 cells `(subfield, year, work type)` with work counts, citation sums, a 32-bucket citation histogram and the paratext subset. Produced by the 37.0-minute full-snapshot scan (510,372,821 records, 2,446 shards, 665.7 GB of compressed works) that `pipeline/fwci/run_fwci.py scan` keeps switched off. |
| `fwci_expected_fullsnapshot_2026-08-09.parquet` | **the expected table the frames use** — 130,061 cells, `expected = citations / works` on `article`/`review` only. 60,504 of its cells are exactly 0 and map to `fwci = NA`, never 0. |
| `fwci_expected_oldpop_2026-08-09.parquet` | the pre-rebuild (seed-subset) denominator, 43,175 cells, kept as the contrast arm that measures how much the old denominator was inflated. |
| `econ_units_2026-08-09.parquet` | 160,437 economics work×person units with the pre-rebuild FWCI attached; the econ frame builder consumes it. **Its producer (`03_econ_anchor_test.py`) is neither ported nor run in Task 4** — it needs the data disk and belongs with the frames (Task 7); registered in `pipeline/NOT_REPRODUCIBLE.md`. |
| `scan_manifest.json`, `gate_a_reconcile.json`, `gate_b_cell_recount.json` | the scan's own record and its two audits (both PASS; gate B is an independent second full pass). |
| `scan_full_2026-08-09.log` | the scan's console log: the only surviving source for the measured 37.0 min, the 13 workers, the 229,785 rec/s and the 665,688,383,258 streamed `gz_bytes`. `pipeline/fwci/run_fwci.py` builds its cost warning from this file plus `scan_manifest.json`, so the warning cannot drift from the record. |
| `g_step1_expected.json`, `g_c_old_vs_new.json` | the expected-table build's record (including the oracle recheck, 130,061/130,061 cells, 0 mismatches) and the old-vs-new denominator comparison. |

These are frozen copies, byte-identical to the legacy sources, all hashed in `data/MANIFEST.sha256`
and copied by `tools/import_frozen.py`. Two consumers read them: `analysis/paper/ledger_funnel.py`
(the paper's snapshot-funnel numbers — `works_snapshot`, `works_benchmarkable`,
`works_articles_reviews`, `benchmark_cells` — which therefore no longer require the author's legacy
tree) and `pipeline/fwci/run_fwci.py` (the scan's cost warning). The expected table is **re-derived and checked** by
`tests/test_pipeline_rebuild.py::test_t4_the_fwci_expected_table_rebuilds_equal_to_the_frozen_one` —
it is stored here as well because the build needs the population table, which the repo would
otherwise be unable to supply without a 36-minute scan of a 696 GB snapshot.

They carry no personal data: every row is an aggregate over a field-year cell, except
`econ_units_2026-08-09.parquet`, which carries pseudonymous OpenAlex work and person ids.

Two of the JSON records name the author's machine (`out_parquet`, `source_new_pop`). That is part of the record they are: they say where the artifact was written and what it was built from, and rewriting them would falsify the provenance. They are frozen data, not code — the repo's own path resolution is in `config/paths.yaml`, and no code here reads those strings.
