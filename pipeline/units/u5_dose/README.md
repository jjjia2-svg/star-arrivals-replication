# U5 dose - units/u5_dose

> Status: **steps 1-6 are all done** (io_load / M4 dose / M5b aggregation / quality / run_u5 orchestration /
> Zenou acceptance + the two-university real-data shipment `derived/u5_ship_2026-07-10/`).

## 1. What this unit does
Turns U4's star_set/events/paper_contrib into two things:
**dose** (M4: the main dose = the shared-reference bibliographic coupling of two people up to t-1, the year before
the star's arrival; for degree-2, both bridge edges are frozen at t-1, and if either edge falls after arrival the
main dose of that channel = 0; the secondary doses topic/embed serve only as robustness checks and never enter
the main dose) + **output aggregation OUTPUT** (M5b: drops first-order co-authorships with the star, over the full
history; 12 keys in with/without-exclusion versions + quality; two same-source named tables for 1% and 5%).
All dose inputs are frozen before arrival to avoid endogeneity.

## 2. Inputs (io_load synthetic path / io_real real-data path, the same pure functions)
U0 `common/*`+`identity/{dose,output_rule}` (called, not rewritten); U1 `authorship_edges/refs_edges
(2 columns, no year, so truncation must join works)/works/work_text`; U2 `person_map`; U4 10c frozen anchors
`star_set (14 columns keyed by author_id, folded via person_map)/events (t_minus_1 read directly; the
star_person_id column holds author_id, the adaptation layer folds it to person)/paper_contrib (grain
work×incumbent×person - **deduplicated to (work,incumbent) before aggregation**, as specified by the U4
producer)`. The four-tuple in the star_set+events artifact headers == the pinned 10c values, otherwise HALT.
Stars whose fragments lack a mapping are counted + WARN; edges / pc cells with a missing year are dropped and
counted (as in U4). The caveat#4 domain assertion = **the shape of the fwci column's domain** (fwci non-NA => article/review;
NA rows may have any type - this matches what the 10c frozen files actually contain).

## 3. Outputs (written under the out_root given by the caller; production = `$DATA_ROOT/u5_ship_2026-07-10/`)
- `dose_p01/`,`dose_p05/`: `_frozen/dose.parquet` (PAIRWISE_DOSE, 11 columns, PK=(incumbent,
  star,event_id,degree), canonical-sort, two-phase COMMIT) + `_frozen/work_embeddings.parquet`
  (0 rows in embed-deferred mode) + `posting_by_year/` + `tally.json` + `diag.json`.
- `output/`: `_frozen/output_star1pct.parquet` + `_frozen/output_star5pct.parquet`
  (12-key OUTPUT, PK=(incumbent_person_id,year), same-source assertion across the two tables) + `tally.json` +
  `output_diag.json` (n_excluded / NA rate / MNAR flag / missing-year accounting - diagnostics kept apart from the
  main table).
- `_ledger/u5_dose/events.jsonl` (idempotency key includes stars_set_hash) + `_reports/run_summary_u5.json`.

## 4. How to run
Tests: `cd units/u5_dose && PYTHONHASHSEED=0 python -m pytest tests/ -q` (fully synthetic, everything in tmp).
Real data: `PYTHONHASHSEED=0 python run_u5.py --out-root <new directory> --duckdb-db <persistent .db>`
(io_real uses DuckDB to extract a bounded subgraph out of core; for degree-2 use a persistent .db, never :memory:).
The three dose keys are fixed (cosine/0.0/0.0 in redlines.yaml). **embed is deferred**: no embed model
name/seed value is fixed -> embed_cos is all NA + diag embed_deferred=true (vectors are never fabricated).
**The degree2 cap has no fixed value** -> this run takes a never-binding upper bound = len(person_map)+1 (zero
effect; the binding value is still open).

## 5. TDD (75 -> **147 tests all green**, deterministic over two consecutive runs)
Steps 1-2: 75 tests (#1-#30) + steps 3-6: 72 tests: M5b exclusion set #31-35/#48b (shipping-set definition:
flag and poach, single source, first order does not walk, full-history exclusion) + aggregation #36-40c (calls u0
only, 12 keys, dedup grain, missing-year accounting, fwci domain shape) + quality #41 series (hand-computed
values, numerator excludes stars, no winsor, NA=NA, MNAR) + run_m5b #42-47 (two same-source named tables,
single-source exclusion, deduction exactly once, idempotency key includes the star hash, two runs byte-identical,
diagnostic sidecar, provenance non-empty) + io_real (contract gate, 10c binding, subgraph = pure filter,
missing-year edge accounting) + run_u5 (nine-key config, pins tampering HALT, rule_version consistency gate) +
M4 extensions (embed deferred, incumbent pool restricted to endpoints, not bridges) + Zenou golden standard
#49-52. On the u0 side, 13 reconcile exclusion-guard tests were added (monotone / deduction-once / single-source /
apply-once + same-source tables).

## 6. Reproducibility
`_DETERMINISTIC_PARQUET_KW` + canonical-sort by the full PK -> byte-level SHA identical across two runs;
the provenance four-tuple goes into manifest_header (bound to the 10c anchors); the idempotency key includes
stars_set_hash; the ledger is append-only; PYTHONHASHSEED=0; every DuckDB extraction uses a full ORDER BY for a
deterministic order.

## 7. Status / open items
- ✅ Steps 1-6 all green + two-university real-data shipment (u5_ship_2026-07-10).
- ⚠️ Not yet fixed: the binding values of degree2_cap_k / degree2_incumbent_cap_per_star (never binding in this
  run); the three embed model keys (embed_model_name/seed/batch - once fixed, run the embed version to fill in
  embed_cos).
- ⚠️ Upstream to-do: `shared/ids.canonical_subfield_id` is not yet in upstream -> topic_vec is implemented locally
  for now; the sourced reference for the topic-id usage note is still to be added (notes side); the
  fwci_baseline artifact header's stars_set_hash is an empty string (a small engineering loose end on the U4 side;
  U5 does not read that table and is unaffected).
