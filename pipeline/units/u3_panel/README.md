# U3 Panel (units/u3_panel)

> Status: **building (TDD in progress)** - T0 scaffolding done; the first red tests are being built.
> Code is isolated in this unit; data products go to the 4TB SSD (not into git).

## 1. What this unit does

Rebuilds the U2 `person_map` (disambiguated people) + U1 `works_affil` (each paper's listed institutions) into a researcher-by-year
unbalanced panel `panel.parquet` (for each person-year: which canonical university, how many papers that year, whether the modal primary
affiliation falls in an Australian economics department) + per-work institution detail `affil_timeline.parquet`. **It computes only "the modal institution of the year = primary affiliation"
and never decides arrival, stars, or disambiguation.** U3 does not touch the identification layer.

## 2. Inputs (frozen parquet, read-only; no API calls)

- U2 `person_map.parquet` - takes the two columns `{author_id, person_id}`
- U1 `works_affil.parquet` (institution + raw_affil) / `authorship_edges.parquet` (year) /
  `work_first_pub.parquet` (true first-publication year #9 + full_history flag) / `canonical_id_map.parquet`
  (rows of both author and inst kinds) / `institutions.parquet` (folded inst dict)
- Injected: `econ_dept_ids` (produced by U0.5) + `registry_by_id` (U0 `build_registry_by_id`)
- Contract schemas: `PANEL` / `AFFIL_TIMELINE` (U0 `common/schema.py`)

## 3. Outputs (written to the SSD under `derived/u3_panel/`)

- `panel.parquet` - PANEL, 8 columns, PK `(person_id, year)`, **unbalanced (no row for a missing year)**
- `affil_timeline.parquet` - AFFIL_TIMELINE, 9 keys, PK `(person_id, year, work_id, raw_inst_id, raw_affil_slot)`
- `_reports/*.csv` (audits of orphans / missing years / null-inst / coverage-domain misses / threshold exclusions) + `_ledger/u3_panel/{tally.json, events.jsonl}`

## 4. How to run

`python -m units.u3_panel.run_u3 --data-root <SSD>/derived --out-dir <SSD>/derived/u3_panel`
(needs duckdb/pyarrow/polars; a Monash+UNSW slice smoke run comes before the full run).

## 5. TDD red-test list

**49 tests** (guards 7 / join+folding 12 / modal+assembly+handshake 14 / reconciliation+determinism 8 / Yves Zenou golden test 7).
Includes the Yves Zenou panel assertions (1998 modal ≠ Monash / ARMI→Monash has no separate row / Caulfield filtered / null-id does not lose people /
unbalanced missing years not padded / never reads affiliations.years) + the #9 single-rule threshold + the #9→#7 true-first-publication-year handshake.

## 6. Reproducibility

Pinned U1 `write_rows_parquet` (3-key deterministic kw) + PK dedup→canonical-sort + raw_affil_slot →
the same input gives a byte-identical sha256; upstream product shas are anchored in the manifest (resume rebuilds if upstream changes); seed-independent (pure counting).

## 7. Known pitfalls / boundaries

- **Never pad a missing year with 0, never drop a person** (red line of the unbalanced panel).
- **Never read `affiliations[].years`** (the trap: Yves Zenou's arrival backfilled with fake 1998/2024 data).
- **`in_au_econ_dept_modal_hint` is non-authoritative** - membership authority = U0.5 table B; downstream must not use the `_modal_hint` suffix as a criterion.
- **Known contamination pattern of the hint column (seen in the real panel for Yves Zenou; mechanism traced)**: in 2003/05/06 the
  modal for Yves Zenou was judged Monash, because of ① **CEPR parse explosion** - the single raw string "Centre for Economic Policy Research
  (CEPR), London" was parsed by OpenAlex into 5 inst ids (including Monash I56590836), so one paper casts 5 institution votes; ② **archive-stamp backfill** - raw "Monash University - Department of Economics"
  (the pure-separator form that the printed_only rule judges "stamped") is stamped back onto old 2003 papers. The printed true affiliations of the same years
  = Southampton/GAINS/IUI (consistent with the real CV, no evidence of a real visit). **The U4 arrival decision must never use a single works-level
  parsed-inst vote** (modal is last in source_priority; the roster and manual review come first).
- ~~BLOCKER-DATA~~ (cleared): the four real tables are complete (full U1 run + U2 person_map),
  and the real panel is built at `derived/u3_panel_2026-07-06/` (2,018,410 rows × 122,089 people).
