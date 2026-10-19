# U0.5 - Department Roster (Monash + UNSW vertical slice)

> Producer of `econ_dept_ids` / table A `ECON_DEPT_REGISTRY` / table B `DEPT_ROSTER_PANEL`.
> Slice = each university's economics department end to end (Chrome scrape of the roster -> author_id alignment -> write table B -> gold standard).
> Status: **Monash + UNSW both build and run live**; the other 9 universities + Wayback history + table A are still to come.

## 0. UNSW slice (extension, reuses the Monash units - nothing rewritten)

UNSW School of Economics: 53 current staff (Chrome scrape of `unsw.edu.au/business/our-people`, filtered to Economics).
**Differences from Monash (extension points, not a fresh start)**:
- `parse.parse_unsw_lines` / `parse_one_unsw` - the UNSW pipe-delimited format is the same as Monash, but it has **no years** (year is all None; red line #3: never invent one) and its flags are `visiting/emeritus/postdoc` (Monash has adjunct/emeritus).
- `align._build_url` / `search_author` gain an `inst_id` parameter (default Monash, for compatibility); the UNSW institution-restricted search uses `UNSW_INST_ID`.
- `align.UNSW_INST_ID = "I31746571"` - the university-level OpenAlex id of UNSW Sydney; **checked live against ROR `03r8z3t63`: `country_code=AU` / `type=education`**. **[manual check]** Confirm table A `unsw_econ.openalex_inst_id` by hand before hard-coding it (red-line neighbourhood).
- `table_b.to_table_b_row(dept_key=...)` gains a `dept_key` parameter (default monash_econ, for compatibility).
- `run_u0p5.build_unsw_roster_rows` / `main_unsw` - write `dept_roster_panel_unsw.parquet` + `summary_unsw.json`.

**Live run result** (`python3 -m roster.run_u0p5 unsw`): 53 table B rows, `dept_key=unsw_econ`, year all None, evidence=official_roster; **33 matched to an author_id (26 high + 7 medium), 20 needs_human (low confidence / shared names, author_id=None, go to needs_author - red line #1: never guess)**; visiting=3 / emeritus=1 / postdoc=5. The 20 needs_human (including A5054240727/A5006435210/A5070527085/A5103238089 etc.) must all be checked by hand.

How to run: `PYTHONPATH="../u0_foundation/src:src" python3 -m roster.run_u0p5 unsw` (needs `$OPENALEX_API_KEY`).

---

## Monash slice

## 1. What it does

Turns the 92-person current roster scraped in the browser from Monash Pure Profiles into **code**: parse into structured records -> align to an OpenAlex bare `author_id` -> write table B (`DEPT_ROSTER_PANEL`) -> check the Yves Zenou gold standard.

## 2. Inputs

- `tests/fixtures/monash_econ_pure_raw_2026-06-29.txt` - the raw archive of the 92 Monash staff scraped with Chrome (pipe-delimited; the only input evidence, kept so the run can be reproduced).
- OpenAlex `/authors` API (`$OPENALEX_API_KEY`, free key; mailto polite pool).
- Reuses U0: `common.schema` (table B schema + `assert_matches_schema`), `identity.golden` (`MONASH_CANONICAL_ID`).

## 3. Outputs

- `<SAR_DERIVED_ROOT>/u0p5_roster/dept_roster_panel_monash.parquet` - table B, 8 columns, deterministic parquet (92 rows).
- `summary_monash.json` in the same directory - statistics + the `needs_author` list + the Zenou note (reproduction evidence).
- **Data stays on the SSD, not in git.**

Table B, 8 columns: `dept_key / author_id(bare) / display_name / year_start / year_end / evidence / confidence / human_verified`.

## 4. How to run

```bash
# 单元目录下，登录 shell (带 $OPENALEX_API_KEY)
PYTHONPATH="../u0_foundation/src:src" python3 -m roster.run_u0p5
```

## 5. Test list

```bash
python3 -m pytest tests/              # 50 测，离线（live 默认 skip）
python3 -m pytest tests/ --run-live   # 含 Zenou live 对到 A5017376589
```

- `test_parse_roster.py` (12) - parses the 92 people / Zenou included / adjunct=11, emeritus=2, center=17 / a missing year is None without crashing.
- `test_author_align.py` (12) - adjudication of 1/0/many hits; needs_human (red line #1); convergence by works_count dominance; mailto/subfield constants.
- `test_table_b.py` (13) - table B schema guard / bare id / evidence=official_roster / equal deterministic sha.
- `test_zenou_golden_roster.py` (formerly test_zenou_slice.py, renamed to fix a name clash when collecting the full suite; 8, including 1 live) - Zenou -> A5017376589 / in table B / dept_key=monash_econ / 1995 != arrival year / note: arrival pending U1.
- `test_run_u0p5.py` (5) - the driver keeps one row per person with none lost / summary counts / needs_author.

## 6. Reproducibility

- The input archive and the parser are deterministic; table B is a deterministic parquet (same content gives an equal byte-level sha, verified).
- The author_id alignment hits the live OpenAlex (which changes) -> the live result is stored in `summary_monash.json` as snapshot evidence.

## 7. Boundaries / red lines (this unit does not decide them)

- **author_id is bare** (the raw author_id, not person_id); folding 16 fragments into one person is **U2**'s job, U0.5 anchors only the main raw fragment.
- 0 or several hits with no decisive dominance -> `needs_human`, **never guess** (red line #1). In this slice 22 people are needs_human.
- **The arrival year is not in this table**; `year_start/year_end` is the Pure publication interval and is never taken as the arrival year (red line #3). Yves Zenou's 2016 arrival is a hint, to be checked by U1 with works + the modal-institution method.
- **Whether adjunct / emeritus count as "on staff" is not decided by the code**: they are only scraped and flagged (the summary gives counts); inclusion or exclusion is a manual choice.
- The `works_count` dominance threshold (`DOMINANCE_RATIO=20`; Yves Zenou measured 116x) is an alignment heuristic with a provisional threshold; it anchors automatically only on decisive dominance, with confidence=low.

---

## 8. Historical roster byline track - steps 0-2 (35 tests, all passing)

> In one plain sentence: from the byline strings of the full U1 `works_affil`, pick out the (paper, author) pairs that print the economics departments of the two universities, join the publication year, and produce **candidate** evidence points of the form "this person had a byline in this department in this year". The candidate layer is not authoritative: everything stays pending and needs a human check before it ranks with the official roster; the year is the byline year and **never the arrival year** (red line #3).

- Code: `src/roster/byline.py` (config / matching / precondition gate / step 1 / step 2) + `run_u0p5.main_byline_steps_0_2` (a thin assembling runner, CLI: `python3 -m roster.run_u0p5 byline`).
- Tests: `test_hist_phrases_config.py`(3) / `test_hist_step0_gate.py`(8) / `test_hist_step1_hits.py`(19) / `test_hist_step2_year.py`(6) + 2 added to `test_table_a.py`.
- **Matching design (grounded in real-data evidence, measured on 403,107 candidate strings)**:
  - Binding is at the level of a **single byline string** (a row-level institution_id would wrongly bind the other university's economics department of a jointly appointed author);
  - A university token must appear within a ±80-character window of the phrase (blocks mixed journal strings: a Piraeus economics department plus a distant UNSW in the same string, 232 rows);
  - If both universities' tokens are in the same window -> bind to the **nearest university**;
  - The UNSW abbreviation is **case-sensitive and whole-word** (the substring 'unsw' matches New Br**unsw**ick, confirmed on 2,518 Rutgers rows); a bare "New South Wales" is a state name and is not a token (it would bind to the University of Sydney / Macquarie);
  - Monash `exclude: Malaysia` (the Malaysia campus is outside the Australian 11-university scope; 139 rows / 31 authors).
- The only authoritative source of the phrases = table A `dept_name_variants`; the config is frozen in `multiplex_pipeline/config/econ_dept_phrases/<dept_key>.yaml` (its SHA goes into the summary).
- Outputs (SSD `derived/u0p5_roster/byline_2026-07-05/`): `byline_dept_hits` / `byline_year_evidence` (every year point carries `source_work_ids` for traceability, test #4) + sidecars `byline_unbound` (department name cannot be bound to a university -> human check) / `byline_year_mismatch` (join fails -> human check).
- **Stamped-string label (found in a smoke test)**: archive sources (RePEc-style) stamp the "current unit" onto historical papers (`Monash University - Department of Economics` pulled Yves Zenou back to 1998; the true arrival is 2016) -> hits get a mechanical label `match_style ∈ {printed, stamped}` and year points carry an `n_printed_style` count; **whether a year point supported only by stamping counts as present is an open usage choice**.
- HALT semantics: 25 upstream missing/flattened; 26 table A row missing / not human-checked; 28 full-run hits 0; 29 year source broken - the sidecar is written first, then HALT.
- Note on write parameters: **the new `byline_*` tables use `store_schema=False`; tables A/B keep the old u0p5 write parameters** (the old bytes are already on disk, deliberately not synchronised - think it through before touching table A/B).
- **Steps 3-6 done**: `byline_skeleton.py` + `run_u0p5.main_byline_steps_3_6` (CLI `skeleton`) - subfield-share label (G5 "2002" is kept) -> person_map folds to people -> the **person level** applies `roster.dept_membership_min=2` (a split-up heavy hitter is not wrongly filtered out) -> raw ids are joined into a [min,max] interval (for a leaver year_end = last byline year; a missing year is logged as a gap and no row is invented). **Two definitions in parallel** (the stamping usage is still open): skeleton_all 601 rows / skeleton_printed_only 542 rows + stats for all candidates (those below the threshold are visible too). Yves Zenou: all=[1998,2025] vs printed=[2011,2025]; 458/542 rows are not in the current official roster = the recovered pool of leavers.
- **Step 7 done**: `byline_merge.py` + `run_u0p5.main_byline_step_7` (CLI `merge`) - merged-table preview `dept_roster_panel_merged_{all,printed_only}` (746/687 rows; **the official table B is never touched**, promoted only once a human has chosen the stamping definition) + trusted set (mechanical filter, 145 under both definitions) + human-review queue `human_review_queue.{parquet,csv}` with 108 rows (P1 stars + first-order 21 [star anchor limited to Yves Zenou in this batch] / P2 stamping-only above the threshold 34 / P3 below the threshold 53) + reconciliation (86 both / 54 official-only / **515 skeleton-only = the leaver pool**).
- The Wayback and ARC supplementary evidence channels are not written yet (parallel track).
