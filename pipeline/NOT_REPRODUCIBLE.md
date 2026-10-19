# What this layer cannot re-run, and why

The `pipeline/` layer reproduces what can be reproduced and says plainly what cannot. This file is
the register. Every entry gives **what it is**, **why it cannot re-run**, **its hash or identifying
counts**, and **what a replicator can check instead**, with each check marked `[package]` (it runs
from this repository alone) or `[private records]` (it needs the author's read-only working trees, the
15 GB snapshot extraction on the data disk, or the verification originals).

> **Public copy.** Person names in code, tests and documentation are replaced by OpenAlex author ids.
> The 15 GB extraction and the verification originals (names, staff-page and ORCID links,
> free-text notes) are not in this package; contact the author to request access. Hashes of files that were changed for the public copy are the sha256 of the published
> file; the private originals map to them through `HASH_CROSSWALK.md` at the repository root.
>
> **Heavy computation runs on AWS.** The U1 snapshot fetch (about 17 hours), the large Panel 3 cells
> and every step of the final rerun behind the report ran on EC2. `pipeline/aws/` holds the runbooks of
> the earlier runs (they print the instance type, region, image, commands, cost and measured runtime
> and launch nothing); `pipeline/aws/r1/` holds the scripts of the final rerun, whose records are
> listed in the section "The final rerun" below.

## Categories

* **DEAD CODE** — legacy code that never produced the output it declares. Not ported.
* **LOST PRODUCER** — a surviving artifact whose builder does not exist in any tree.
* **LOST INPUT** — surviving code whose input no longer exists, so the code can never run again.
* **HUMAN STEP** — an artifact produced by a verification step (sources read one by one and a verdict
  written for each row), not by code.
* **TOO EXPENSIVE / NEEDS HARDWARE** — code that exists and runs, but is deliberately not executed
  by default. The gate prints the cost.
* **NOT BYTE-REPRODUCIBLE** — code that produces the right content but cannot produce the same bytes
  twice. Reported, never tuned away.
* **RECOVERED** — a producer that is missing from every surviving tree but was found in the author's
  recorded command history and now rebuilds its artifact.

A missing producer was searched for both on disk and in the author's recorded command history. Where
that history does not cover the relevant dates, the entry says the search was **void**, not negative.

## Index

| # | Entry | Category | Check |
|---|---|---|---|
| 1 | `04_gate_c_old_vs_new.py` (FWCI) | DEAD CODE | `[package]` its successor's verdict is frozen at `data/fwci/g_c_old_vs_new.json` |
| 2 | the 840 econ + 2,593 chem/math verification judgements | HUMAN STEP | `[package]` the frozen rosters; `[private records]` the evidence files and the arithmetic that closes over them |
| 3 | the `reject_cause` enrichment of `rejected_persons.csv` | RECOVERED | `[private records]` the byte-for-byte rebuild; `[package]` that the column feeds nothing |
| 4 | the `ev20` / `noA5044701593` incfel copies | RECOVERED | `[private records]` they are byte-copies of the `incfel` rosters |
| 5 | the full-snapshot FWCI scan | TOO EXPENSIVE | `[package]` its own manifest, frozen and sha-pinned |
| 6 | `econ_units_2026-08-09.parquet` | TOO EXPENSIVE | `[package]` frozen, 160,437 rows, sha-pinned |
| 7 | `new_stars_COMBINED_p10_2026-07-22.csv` (the econ p10 shortlist) | LOST INPUT | `[package]` the event arithmetic 79 + 38 = 117 over the pre-caliber ledgers, and 117 − 1 (A5044432173, removed by the 2026-08-28 caliber) = 116 in `data/frames`; `[private records]` the 258-row `star_set` |
| 8 | the star and event identity work (192-person round, per-paper identity calls) | HUMAN STEP | `[package]` the event arithmetic 79→117 / 22→35 / 20→31 and the caliber's 116/38/33 tables |
| 9 | `90_capped_build.py` — 3 of the speed bracket's 9 cells | NOT PORTED | `[private records]` all nine cells; the shipped bracket is on the pre-caliber event set (see entry) |
| 10 | `p1_frame_chemistry.csv`, `p1_frame_math_stats.csv` | NOT BYTE-REPRODUCIBLE | `[private records]` rebuild characterisation; `[package]` the frozen frames' hashes |
| 11 | `roster_v4_proj8` (Monash/UNSW colleague pool) | LOST PRODUCER (search void) | `[private records]` 180 rows, 8 of 10 columns of `roster_v4_2026-07-16` |
| 12 | `dept_roster_panel_adelaide_MERGED_209plus_gapfill.parquet` | LOST PRODUCER (search void) | `[private records]` its own `MANIFEST.json`; exactly 5 events depend on it |
| 13 | `u1_full_11school`, `u2_person_map_11school`, `u3_panel_11school` (the AWS relay) | LOST PRODUCER (cost) | `[private records]` each directory's own summary/provenance JSON |
| 14 | `run_screening.SCRATCH` — a reclaimed DuckDB temp dir | LOST INPUT (inert) | `[package]` it holds no artifact and is unreachable from any runnable stage |
| 15 | the U1 17-hour snapshot fetch | TOO EXPENSIVE (AWS) | `[package]` `data/fwci/scan_manifest.json`; `pipeline/aws/launch_u1_fetch.sh` |
| 16 | the four large Panel 3 cells | TOO EXPENSIVE (AWS) | `[package]` `python3 tools/verify_cloud_custody.py` → `CUSTODY_OK` (with `--custody data/report/custody --spec data/report/custody/custody_r1.json` for the report's data) |
| 17 | two legacy inputs overwritten THROUGH the shadow's hard links (2026-09-23, econ920 chain): `econ_fnfix_2026-08-15/data/edges_supplement_fnfix.jsonl`, `econ_final_2026-08-13/patch/works_by_author.jsonl` | INCIDENT — legacy tree written, restored from pinned bytes | `[package]` `tests/test_shadow_write_through.py` (the `Shadow.write` fix), `data/raw_verified/edges_supplement_econ_fnfix.jsonl` = the pristine supplement (`8d03564c…`); `[private records]` `econ920_lib.assert_pins` — both files are in `LEGACY_PINS` and every econ920 run refuses to start on the wrong bytes |
| 18 | `data/paper_inputs/star_origins_2026-10/affiliation_years.csv` column `n_works` (Figure 1's works tie-break), counted 2026-09-23 on a partial `u1_full_11school_2026-07-16/works_affil` (120 of its 256 bucket files) | INCIDENT — a frozen input read from a partial table | `[package]` `config/r1/star_origins_u1_view_2026-09-23.json` (the files that were read) and the input guard's toy tests in `tests/test_r1_star_origins_m.py`; `[private records]` the October events re-extracted with `--u1-view` give the frozen CSVs byte for byte, and on the complete table only `n_works` moves, upward |
| 19 | the matplotlib render date (`/CreationDate`) in `fig_dose_distribution.pdf`, `fig_exposure_population.pdf`, `fig_hops.pdf`, `fig_p1.pdf`, `fig_p2.pdf`, `fig_p3_afar.pdf` | NOT BYTE-REPRODUCIBLE | the comparison in `pipeline/aws/r1/final_stage.same_file`: byte-equal once the render date and the `startxref` value are masked, every drawn byte compared; `tests/test_r1_final.py` (masking toy PDFs) |

---

## 1. DEAD CODE — `fwci_baseline_fullsnapshot_2026-08-09/code/04_gate_c_old_vs_new.py`

**What it is.** A fourth audit gate in the legacy FWCI scan directory, comparing the old seed-subset
denominator with the new full-snapshot one. 8,623 bytes, sha256
`66d85778b6000e9b80c8b56cc212138f9651d20ae14ebe3c95ec7204d2ff47cf` (private original).

**Why it is dead.** It declares `OUT = BASE / "data" / "gate_c_old_vs_new.json"` and writes it at
line 158. That file does not exist. The script was last edited about 29 minutes *before* the
population table it reads was written. It was superseded an hour later by
`fwci_fullsnapshot_rebuild_2026-08-09/code/02_gate_c_old_vs_new.py`, which asks the same question and
whose output exists and is frozen here.

**Decision.** Not ported.

**Check instead.** `[package]` `data/fwci/g_c_old_vs_new.json`. The fact underneath it: the
pre-rebuild denominator was inflated by a median 1.66× and a weighted 2.20× (economics subfield
2002: 3.52× weighted), which is why the frames carry the full-snapshot denominator.

---

## 2. HUMAN STEP — the 840 economics and 2,593 chem/math verification judgements

**What it is.** Both roster chains end in a one-by-one verification: each row was checked against a
staff page, an ORCID employment record or a Wayback capture, and a verdict was written. Economics:
840 rows, 731 confirmed / 74 rejected / 35 uncertain. Chemistry and math-stats: 2,593 rows, 1,884
confirmed / 616 rejected / 93 uncertain. No code replays these, and both merges are reproducible only
*given* them.

The economics roster built from them is `data/raw_verified/roster_econ_verified.parquet`: 920 spells /
920 people, 11 schools, 1974–2026. In the public copy it keeps 11 columns (`dept_key, school,
author_id, year_start, year_end, year_start_orig, year_end_orig, year_corrected, confidence,
human_verified, verify_source`), with `verify_source` mapped to a fixed English code table; sha256
`ccea616211e42bd1cc56a17660d80aec00b732533369a97566101e5cd51f61c6` (the 16-column private original is
`ccea616211e42bd1cc56a17660d80aec00b732533369a97566101e5cd51f61c6`).

The two economics producers (`build_audit.py`, `merge_roster.py`) are recovered and ported under
`pipeline/rosters/econ_roster_verify_2026-08-09/code/`; see `pipeline/rosters/README.md`. Re-run on
the private evidence, the merge rebuilds the private original (`roster_clean_11school_verified.parquet`
in the author's tree) byte for byte, and the audit builder rebuilds the 994-row audit table and all
22 batch files byte for byte.

**Check instead.**

1. `[package]` **Shape** — 920 rows / 920 distinct `author_id` / 11 schools, and the sha256 against
   `data/MANIFEST.sha256`.
2. `[package]` **Flag distributions** — `verify_source` carries the human-batch code on **766** rows
   and the upstream-prior code on **154**; `human_verified` is False on exactly the **35** uncertain
   rows (885 True); `year_corrected` True on **136**; `confidence` 864 high / 16 medium / 40 low.
3. `[package]` **The analysis layer depends only on the frozen copy** — `analysis/run_all.sh`
   reproduces every economics estimate from it.
4. `[private records]` **The arithmetic closes** — 994 machine rows − 74 rejected = 920; the 840
   verified rows split 731 + 74 + 35, so 731 + 35 = 766 survive this round and 994 − 840 = 154 were
   never sent to it; 766 + 154 = 920.
5. `[private records]` **Row-by-row evidence and the rebuild itself** (`run_rosters.py econ-merge`).

The `incfel` rung of the chem/math ladder (`data/incfel/` of the 2026-08-10 gold build, shipped as
`data/raw_verified/incfel/roster_gold_{chemistry,math_stats}.parquet`: 396 rows / 384 people, sha256
`e48ce86d6c6c868016cb6e724b3862c3d506412257250399fb9d775acd75fb46`, and 552 rows / 545 people, sha256
`46295d2f66ea19e77b9b4d8afcc52c1bce73808dbac61549226d83bc275eabcf`) sits between `inc` (built by
`00b_prep_roster_variants.py`; chemistry 283 rows) and `final` (`00c`; chemistry 533 rows). Its
producer was also recovered: `pipeline/rosters/multidisc_gold_2026-08-10/code/00b2_prep_incfel_variant.py`
rebuilds both content-equal. `[package]` the rule is readable in that file and in `00c` lines 70–84;
`[private records]` running either stage.

## 3. RECOVERED — the `reject_cause` enrichment of `rejected_persons.csv`

**What it is.** One column. The recovered `merge_roster.py` writes `rejected_persons.csv` (a private
file) with 12 columns; the frozen copy has a 13th, `reject_cause`, written 66 seconds later.

**The producer.** An inline heredoc, now ported as
`pipeline/rosters/econ_roster_verify_2026-08-09/code/add_reject_cause.py` (public-copy sha256
`824ea2a3226ec24474436df25af86fd83dd2f1fb07c937820b85026dd6667d80`, private original
`738a6e9c…`; per-line
comments naming departments and one person were removed for the public copy). It maps 74 author ids
to four causes (A wrong department 33 / B wrong id 21 / C not found or no year overlap 9 / D visiting
or adjunct 11). `run_rosters.py econ-merge` runs it as the stage's second step, and on the private
evidence the result is the frozen 13-column file exactly, 13 of 13 columns (64,148 B, sha256
`0c5dd47cd8e3bfe182a2f89b9b0a2aa61f2bc794cddbb50457e3673cb570e303`, private).

**Check instead.** `[private records]` the byte-for-byte rebuild. `[package]` that the column feeds
nothing: the roster parquet is built from `verdict != "rejected"`, not from this file.

## 4. RECOVERED — the `ev20` and `noA5044701593` copies of the incfel rosters

**What they are.** Four parquets under `<gold>/data/{ev20,noA5044701593}/`, byte-identical copies of the
`incfel` rosters, used as the population for two variant runs: **ev20** drops two stars
(A5109260299, A5100398634) and **noA5044701593** drops A5044701593 (a merged-id case; in the legacy
tree the variant's label is a person's name, written here with the author id). The producers are two
recorded variant builders (2026-08-10 21:04:53 and 22:26:35 local) that end in `shutil.copy`.

**Check instead.** `[private records]` that the four files are byte-identical to the two `incfel`
rosters, and that `pipeline/frames/multidisc_gold_2026-08-10/code/30_build_panels23_gold.py`'s `_LSUF`
encodes the two variants. No thesis number, estimate or frozen frame depends on either directory.

---

## 5. TOO EXPENSIVE — the full-snapshot FWCI scan

`pipeline/fwci/fwci_baseline_fullsnapshot_2026-08-09/code/01_scan_full_snapshot.py` is ported and
runnable, and **OFF by default**: a measured **37.0 minutes** with 13 workers over all 2,446 gzip works
shards of the frozen 2026-06-26 OpenAlex snapshot (665.7 GB compressed, 510,372,821 records), plus a
0.76-minute merge. `python3 pipeline/fwci/run_fwci.py scan` prints the cost and exits 2; `--execute`
runs it. It needs the data disk. `orjson` is a hard requirement (`--json-lib stdlib` is ~3× slower).

**Check instead.** `[package]` the output is frozen at `data/fwci/fwci_baseline_pop_full.parquet`
(543,037 cells, sha256 `03ce4144a1ba423737717fc97ce183ef01c337297765ea3f5dc679aaa538dd31`) with its
run record `data/fwci/scan_manifest.json` and both audit verdicts (`gate_a_reconcile.json` PASS 6/6,
`gate_b_cell_recount.json` 6/6 cells exact). The record reconciles the scan shard by shard:
`manifest_record_count == total_lines_read == 510,372,821`, `bad_lines = 0`,
`shard_read_mismatches = 0`.

## 6. TOO EXPENSIVE — `econ_units_2026-08-09.parquet`

**What it is.** 160,437 economics work × person units with the pre-rebuild FWCI attached, sha256
`3950cec3ed2c2b82a2a66b4dc3102c50dd58ada01da897890c8980f4b9b7572e`, frozen at
`data/fwci/econ_units_2026-08-09.parquet`.

**Why it did not run.** Its producer, `03_econ_anchor_test.py`, reads a U5 output on the data disk
and is not ported.

**Check instead.** `[package]` its sha256, row count (160,437) and 10-column schema.

---

## 7. LOST INPUT — `new_stars_COMBINED_p10_2026-07-22.csv` (the econ p10 shortlist)

**What it is.** The 65-row combined star shortlist `step1_freeze_ship_80ev.py` reads through
`common80.DRAFT37_CSV`: the 37-row draft list plus 28 further top-10 % candidates. It is the input to
the batch that produced the econ **79-event** star set.

**Why it cannot re-run.** It was written into a temporary directory the OS reclaimed; its absence was
already recorded on 2026-08-15. The constant stays pointed at a non-existent location (in the public
copy, `/private/tmp/removed-session-directory/star10/…`). The recorded command history does not cover
the day it was written, so the search for it there is **void**, not negative.

**Consequence.** `step1_freeze_ship_80ev.py` can never re-run end to end. Its event rows are frozen as
`data/raw_verified/event_ledger_econ79.csv` (79 rows).

**Check instead.**

* `[package]` `event_ledger_econ79.csv` 79 + `events_econ_new38.csv` 38 = the pre-caliber 117; the
  2026-08-28 caliber removes one event (A5044432173) to give the 116 of `data/frames/p1_events_ledger_econ.csv`.
* `[private records]` 97 of the 258 `star_set` rows carry `percentile IS NULL`: `common80.py` sets
  `percentile=None, cell_n=None, is_star_1pct=True` by design for that batch, because star status came
  from human web verification of a top-10 % shortlist, not from an automatic rank.

## 8. HUMAN STEP — the star and event identity work

No code reproduces any of this. The scripts around it are ported (`71/73/74/76`), but their input is a
human round, so `pipeline/stars/run_stars.py` declares them NOT_RUNNABLE with reasons.

* **The 192-person two-round check.** `61_poach_fn_prescreen_v2.py` reduced 671 suspect rows to
  **192 CHECK** (econ 84 / chemistry 64 / math-stats 44); two human rounds adjudicated those, plus 9
  people the machine had flagged `poach ∧ top-10 %`.
* **The confirmation ledgers** — 35 / 14 / 13 (econ / chemistry / math-stats).
* **The per-paper identity calls** — 385 rows for the fn-fix re-stake and 3,873 rows behind the
  2026-08-10 identity cleanup, plus the star-id adjudication (43), split-id (45) and duplicate-pair
  (5) tables and a 232-file dossier tree. All private.
* **Rulings encoded only as module constants** — in `common80.py`: A5063040920 excluded 2026-07-22
  (later reinstated by the fn-fix), A5072079903 de-duplicated, A5068400819 overridden, A5020228087 and
  A5045410390 dropped on the seniority gate. Arrival years of A5100398634 and A5005527509 fixed by hand;
  A5006982852 and A5109260299 admitted under the research-centre rule.
* **A5044701593** has no adjudication row; the removal is encoded as a config variant (`noA5044701593`) whose
  recorded builder names the id and the reason inline.
* **The nine U4-flagged economics verdicts.** `00_build_candidates_restake_econ_u4flagged9.py`
  read four of them from a temporary task output that the OS has since reclaimed. The content is
  frozen in this package as `data/stage_payloads/u4_star_events.json` (author id, verdict and
  arrival year only), and `run_stars.py` writes it back for the duration of the stage.
* **The OpenAlex caches are part of the evidence.** `_poach_profile_cache.json`,
  `_poach_aff_cache.json` and `_star_works_cache/` hold the API's 2026-08-15 answers. A fresh call
  today returns different data (OpenAlex back-fills current affiliations onto old works), so re-running
  `61` or `75` live is not a reproduction. Both stages are gated off in `run_stars.py`.

**Check instead.** `[package]` the event arithmetic 79→117 / 22→35 / 20→31 (pre-caliber,
`data/raw_verified/`) and the caliber's 116/38/33 tables (`events_*_cal2026-08-28.csv`).

## 9. NOT PORTED — `90_capped_build.py`, and the speed bracket

**What it is.** `p3_afar_speed_bracket.csv` (sha256
`02864602be9b2192644ca9a5976affe6baacb6c911b68fbf5af58c97b1d0fdd0`, 527 bytes, CRLF): for each field
and cell, the pre-arrival slope of the first-tie hazard, the realised post-arrival hazard, two
counterfactuals and the ratio bracket they define. Its producer was recovered
(`pipeline/frames/p3_topicpair_2026-08-17/code/speed_bracket.py`) and rebuilds the CSV byte for byte.

**Why it cannot fully re-run.** Three of the nine cell parquets it reads
(`pairs_slim_cap_{econ,chemistry,math_stats}_ALL.parquet`) are written by `90_capped_build.py`, which
is not ported. **Caliber-stale:** the shipped CSV reflects the pre-caliber A_far event sets (87 / 30 /
29 events versus the caliber's 86 / 33 / 31). The thesis keeps the pre-caliber bracket wholesale —
numerator and denominator both from the 2026-08-22 event set, frozen in
`data/paper_inputs/speed_bracket_precal_2026-08-22.json` and cross-checked by `ledger_p3afar.py` — with
an explicit disclosure in the text; no mixed-caliber ratio is computed.

**Check instead.** `[private records]` all nine cells (the `speed` stage links the capped and several
uncapped inputs from the legacy tree).

## 10. NOT BYTE-REPRODUCIBLE — `p1_frame_chemistry.csv` and `p1_frame_math_stats.csv`

**What they are.** The Panel 1 frames for chemistry and mathematics-and-statistics, 46,552 and 23,232
rows (pre-caliber), written by `20_rebuild_y_gold.py` with `GOLDVAR=fnfix`.

**Why.** `20_rebuild_y_gold.py:152-166` materialises a per-work table from a DuckDB query with no
`ORDER BY` under 8 threads, and line 189 accumulates floating-point sums in that order. Three
independent runs give three different files.

**Check instead.** `[private records]` row count and header identical; only `fwci_frac` and
`fwci_frac_ex_star` ever differ, by at most 3 ULP. Estimating from a rebuilt frame gives estimates
`EQUAL` to the frozen ones (no tolerance) four times out of four. `[package]` the frozen frames'
hashes in `data/MANIFEST.sha256`.

The same value is printed in one more place: the union builder's G-VAL advisory recomputes fwci for a
sample of `both` relations and writes the mismatching examples into `union_build_report_<field>.json`.
Measured on the 2026-09-23 math_stats control build of
`pipeline/frames/cal2026-10/run_cal_frames_chemmath.py`: `G_VAL_advisory.examples[0][5]` and `[1][5]`
= `0.6808816666666666` against `…67` in both frozen reports (`data/cal2026-08-28/frames/` and
`data/cal2026-10/frames_math_stats/`) — 1 ULP, the only two differences in the file. So the union
build report is not byte-reproducible either, on exactly the terms above; the driver measures a
difference at that path in ULP, accepts it only there and only within 8 ULP, records it as
`h1_ulp_in_advisory`, and still stops on any other difference. The frozen reports were not re-frozen.

The first runs on EC2 (2026-10-16, the chemistry and math_stats controls) moved three more printed
values of those reports by 2 ULP: the OLD frame values of an example (`examples[i][4]`,
`fill_examples[i][5]`), as pandas parsed them from the old frame CSV. pandas' C float parser rounds
differently on x86-64 Linux and on arm64 macOS; every frame matched. The rule now covers the parsed OLD
values and the FRESH H1 sums (`examples[i][5]`, `fill_examples[i][6]`), numbers only, within the same
8-ULP bound; every other path still stops.

## 11. LOST PRODUCER — `roster_v4_proj8/dept_roster_panel_{monash,unsw}.parquet`

**What it is.** The Monash/UNSW half of `step1_freeze_ship_80ev.py`'s colleague pool, read through
`common80.ROSTER_V4_PROJ8`.

**Why it cannot re-run.** Every reference to it in the legacy trees reads it; no step that writes it
survives. The recorded command history has no records for 2026-07-15 … 2026-07-21, when it was made,
so that search is void.

**Check instead.** `[private records]` it is an 8-column projection of `u0p5_roster/roster_v4_2026-07-16`
(both 180 rows).

## 12. LOST PRODUCER — `dept_roster_panel_adelaide_MERGED_209plus_gapfill.parquet`

**What it is.** The colleague-pool authority for the 5 Adelaide gap events of the 79, read through
`common80.ADELAIDE_MERGED`.

**Why it cannot re-run.** Nothing in either legacy tree writes it; it was made in the same uncovered
week as entry 11.

**Check instead.** `[private records]` its own `MANIFEST.json`, which documents an ad-hoc Wayback-CDX
crawl with hand-applied employment gates, and that exactly the five `ADELAIDE_GAP_EVENT_IDS` depend
on it.

## 13. LOST PRODUCER (cost) — `u1_full_11school_2026-07-16`, `u2_person_map_11school_2026-07-16`, `u3_panel_11school_2026-07-16`

**What they are.** The base of the chain: the narrow works/edge tables, the person map and the
person-year panel, on the data disk.

**Why they cannot re-run here.** They were produced on the EC2 relay. The cause is cost, not loss: the
producer is the U1 fetch documented in `pipeline/aws/launch_u1_fetch.sh`.

**Check instead.** `[private records]` each directory's own record (the U1 provenance manifest,
`summary_u2_11school.json`, `summary_u3_11school.json` + `preflight_result.json`). `[package]`
`data/fwci/scan_manifest.json` covers the snapshot side: 510,372,821 records, 2,446 shards, 0 bad lines.

## 14. LOST INPUT (inert) — `run_screening.SCRATCH`

**What it is.** The DuckDB temp directory `run_screening._con()` creates, naming a temporary directory
the OS reclaimed long ago (in the public copy, `/private/tmp/removed-session-directory/duckdb_tmp`).

**Why it cannot bite.** `_con()` is reached only from that module's own `main()`, which `run_stars.py`
declares NOT_RUNNABLE. The stages that use the module (`60`, `72`) import `_POOL_SQL` and never call
`_con()`.

**Check instead.** `[package]` `python3 pipeline/stars/run_stars.py --list` lists `run_screening.py`
under "ported scripts with no runnable stage".

## 15. TOO EXPENSIVE (AWS) — the U1 17-hour snapshot fetch

**What it is.** The top of the pipeline: it streams the frozen 2026-06-26 OpenAlex snapshot (2,446
gzip works shards, 510,372,821 records, ~694 GiB compressed) into the ~15.4 GB of narrow tables every
later stage reads.

**Why it does not run here.** 17 h 01 m wall, 20.3 h billed, about $30 on an i4i.4xlarge in us-east-1.
Its output is the 15 GB extraction, which is not in this package. `pipeline/run_all.sh` does not offer
it under any flag.

**Check instead.** `[package]` `data/fwci/scan_manifest.json` (record count, shard count, zero bad
lines). `[package]` `bash pipeline/aws/launch_u1_fetch.sh` prints the full runbook.

## 16. TOO EXPENSIVE (AWS) — the four large Panel 3 cells

**What they are.** `P3_econ_fnfix`, `P3_fnfix_chemistry`, `P3evcl_econ`, `P3evcl_chemistry`: Panel 3
for economics and chemistry, main and event-clustered, on millions of pair-years. Each version of the
data ran them on a large AWS machine. The [cell resource table](../data/report/custody/RESOURCES.md)
lists the measured memory and wall time for each report cell.

**Why they do not run here.** A laptop does not have the memory. `RUN_CLOUD_CELLS=1 bash
analysis/run_all.sh` re-runs them on a large machine with the second R stack
(`analysis/estimation/README.md`).

**Check instead.** `[package]` `python3 tools/verify_cloud_custody.py` → `CUSTODY_OK`: every shipped
input is md5-identical to what the cells ran on, and every fetched JSON equals the recorded estimate.
The custody records are `data/report/custody/` (the report), `data/cal2026-10/cloud/` (October 2026)
and `data/cal2026-08-28/cloud/` (August 2026). `[package]` `pipeline/aws/README.md` and `logs/*/` carry
the launch and terminate timestamps, the `/usr/bin/time -v` output, the memory log and the bootstrap
recipe of the earlier runs.

---

## Recovered producers: identification by content, not by mtime

For completeness, the recovered event selectors and speed-bracket producer:

| ported file | recorded operation | sha256 of the file in this package | rebuild |
|---|---|---|---|
| `pipeline/stars/multidisc_gold_2026-08-10/code/00_select_new_events_econ.py` | 2026-08-15T16:04:57.679Z | `eb75dd9e361836c19da07f3216c8d78d63dd14e2e2a1b560964d2ea2c2d482c3` (unchanged) | `new_events_econ.csv` byte-identical |
| `pipeline/stars/multidisc_gold_2026-08-10/code/00_select_new_events_chemmath.py` | 2026-08-15T12:51:58.422Z | `362e1e0305df68d95d530f6d429e0bcb52c9c264084c87e17ff5fc430fe8f154` (one comment changed; private original `49a5039f…f14ca8`) | `fnfix_new_events.csv` + `_wide_extra.csv` byte-identical |
| `pipeline/frames/p3_topicpair_2026-08-17/code/speed_bracket.py` | 2026-08-17T22:12:52.577Z | `5b9cc970846b40f6ece97f88df3269c11dd47256eaa64827ef7dbb00406b598b` (its two printed messages in English; private original `ea68938c…f09936`) | `p3_afar_speed_bracket.csv` byte-identical |

Two rules live only in these recovered files and are documented in `pipeline/stars/README.md`:
`in_window` was computed per discipline with different bounds (the 2026-08-28 caliber later made the
window uniform), and a hard-coded exclusion (`A5016651378`) in the chem/math selector is unreachable.

## NOT BYTE-REPRODUCIBLE — the render date of six paper figures

**What they are.** `fig_dose_distribution.pdf`, `fig_exposure_population.pdf`, `fig_hops.pdf`,
`fig_p1.pdf`, `fig_p2.pdf` and `fig_p3_afar.pdf`, which the paper generators write into `output/paper`
(`fig_p3_afar.pdf` by `ledger_p3afar.py`, the others by the generator of the same name). None of the six
passes `metadata` to `savefig`.

**Why the bytes move.** The pinned matplotlib stamps `/CreationDate` with the wall clock at render time
unless `SOURCE_DATE_EPOCH` is set, and writes the Info object last with no `/ID`, so a date of another
length also moves the final `startxref` value. For `fig_dose_distribution`, `fig_exposure_population`
and `fig_hops`, two frozen copies of the same generated file are byte-equal once `/CreationDate` is
removed, and their dates differ (2026-09-23 against 2026-10-01; hops 2026-09-24). No single date could
match both.

**Check instead.** `[package]` `pipeline/aws/r1/final_stage.same_file`: for a PDF on both sides, each
`/CreationDate` and `/ModDate` value and the final `startxref` value are masked, provided each key occurs
equally often (0 or 1) on both sides, and every other byte is compared exactly; the paths equal only
after masking are listed in gate 2's `pdf_date_masked`. Every other file keeps the raw byte comparison.
The generators are unchanged (no date is hard-coded to match a reference), so the switch-off proof under
`SOURCE_DATE_EPOCH=0` still holds.

**Not covered here.** The manuscript's `figures/fig_p1.pdf`, `fig_p2.pdf` and `fig_p3_afar.pdf` are the
author's 2026-10-03 restyled versions (Matplotlib 3.10.8, embedded macOS Palatino). `fig_p1.py` / `fig_p2.py` /
`ledger_p3afar.py --tree base_2026_10_11` (the paper stage on the report's data) draw the same words, in the
same order, on the same page size, but in TeX Gyre Pagella and with no `/CreationDate`, so their bytes still
differ from the printed PDFs even after the date mask. Without `--tree` they keep drawing the six files above.

## Blind spots in the mechanism

* **`staged_run_dir()` interior** — closed: the returned path is resolved and judged by the same rules
  as the root.
* **The staged-run exemption** — closed: it is an in-process marker, not an environment variable.
* **Scratch output inside a cloud-synced folder** — mitigated, not closed. On the author's machine the
  sync client left conflict copies inside `output/`. `pipeline/run_all.sh --with-ssd` puts the
  data-disk stages' scratch root outside the checkout when `SAR_SYNCED_CHECKOUT=1` is set; setting
  `$SAR_OUT_ROOT` to a local, non-synced directory avoids the hazard for any launcher.

## INCIDENT — the legacy tree was written through the shadow's hard links (2026-09-23)

**What it is.** `frames_stage.Shadow` hard-links every frozen legacy input into a scratch shadow
(`link_frozen`, `FROZEN_LINKS`) and then writes derived tables into the same shadow (`write`). When a
derived table has the SAME rel as a linked file — the econ920 chain's two concatenations, the fnfix
supplement ⧺ the 126-row star-id supplement and (since 729788a) the 2026-08-13 API patch ⧺ the
190-row roster-addition patch — `write` used `Path.write_bytes` on the link and so truncated the
shared inode: the read-only legacy file itself. Measured on 2026-09-23:

| legacy file | pinned (2026-08-28 staging manifest, 2026-09-22 control reports) | found | what was appended |
|---|---|---|---|
| `econ_fnfix_2026-08-15/data/edges_supplement_fnfix.jsonl` | `8d03564c…`, 4,151 lines (= `data/raw_verified/edges_supplement_econ_fnfix.jsonl`) | `6b0ad80b…`, 4,907 lines | the 126-row supplement **six** times (six October builds on 2026-09-23) |
| `econ_final_2026-08-13/patch/works_by_author.jsonl` | `9ab03809…`, 17,191 lines | `143855d0…`, 17,381 lines | the 190-row October patch supplement once |

**Restored 2026-09-23:** both files were put back to their pinned bytes — `edges_supplement_fnfix.jsonl` from `data/raw_verified/edges_supplement_econ_fnfix.jsonl` (sha256 `8d03564c…`, 4,151 lines; the damaged file started with exactly those bytes), `works_by_author.jsonl` truncated to its first 17,191 lines (sha256 `9ab03809…`; the 190 trailing lines were the October patch rows). Both sha256s re-verified after the write against the 2026-08-28 staging manifest pins. The write into the legacy tree was the repair of damage the shadow's hard links had done, not an edit of legacy content.


**Consequences, measured.** (i) Every product is unchanged: a re-run on a copy-on-write
clone of the legacy tree with the pristine bytes restored reproduces `data/cal2026-10/frames_econ/`
(CSV byte for byte, parquet content-equal, R cells EQUAL) and the four controls stay CLEAR — the
supplement rows only reach persons without snapshot edges and 04 re-derives every y. (ii) The
committed provenance is wrong where it recorded the already-altered file as "frozen": the econ920
staging manifest of f91ecd6 (`47f811a0…`, pristine + 3 copies) and of 729788a (`87eb3275…`,
pristine + 4 copies); the chemistry / math_stats manifests recorded the pristine `8d03564c…`
correctly. (iii) 729788a's union clone read the API patch from the REAL legacy path, which the
shadow build had just overwritten — so its `outcome_src` (api_persons 105 → 107) came through the
corruption, not through the shadow. The fix passes the SHADOW's patch to the clone
(`union_config(patch_a=…)`); the products are the same bytes either way (measured).

**Repair.** `Shadow.write` now unlinks an existing path before writing (the shadow gets its own inode;
`tests/test_shadow_write_through.py`). `econ920_lib.LEGACY_PINS` pins both files, so a run refuses
to start on altered bytes. The two legacy files were restored to their pinned bytes on 2026-09-23 (above);
the verification run in this entry used a copy-on-write clone of the legacy tree with the pristine
bytes swapped in (`$SAR_PATHS_CONFIG` → `legacy_v2_output` = the clone). Any scratch shadow built
before the restoration holds the corrupted inode and must not be reused.

## INCIDENT — Figure 1's works counts were read from a partial table (2026-09-23)

**What it is.** `tools/star_origins_extract_2026-10.py` counts, per author × institution × year, the
distinct works in `works_affil` JOIN `authorship_edges` of both U1 tables (`n_works` in
`data/paper_inputs/star_origins_2026-10/affiliation_years.csv`, the map's works tie-break). On
2026-09-23 the data root was a local mirror of the data disk into which a download of
`u1_full_11school_2026-07-16` had been stopped part-way the day before. Listed read-only on 2026-10-16:
256 bucket directories, **120 complete files** (5,398,503,077 bytes), 20 unfinished downloads and 116
empty directories. The `'**/*.parquet'` glob read the 120 and raised nothing. Every other U1 subtable
the count read was complete. Bucket = sha1 of the row key mod 256, so the missing rows are spread over
all authors.

**Consequences.** `n_works` can be too low wherever a work sits only in the 11-school table and in a
missing bucket; nothing else in the four CSVs depends on the U1 tables. A full rescan on the complete
table gave `n_works` 1 where the frozen row says 0 (A5000292946 × I130343225 × 2008).

**Repair.** The extractor lists its U1 inputs before counting (`u1_sources`): an unfinished download, an
empty bucket directory or a bucket set unlike the sibling subtable's stops the run (`U1_PARTIAL`). The
September input is recorded in `config/r1/star_origins_u1_view_2026-09-23.json`; `--u1-view` reads
exactly those files (sizes checked), which is how the frozen extraction is reproduced. The frozen files
are not changed: they are what October's Figure 1 used. In the final rerun every star's machine origin is
re-extracted on the complete tables: the `star_origins_extract` stage (`config/r1/stages/j1a.json`) runs
without `--from-frozen` / `--u1-view`, so the guard reads every U1 file, and passes the human-origin
overrides keyed by (discipline, star_id, arrival_year), re-dated through the run's `events_decision`.
The missing or ambiguous origins in its name-free report (`report_star_origins.json`) go to a manual
reading step. Pinned by
`tests/test_r1_table_j1a.py::test_star_origins_extract_rescans_every_star_and_merges_the_overrides`.

## October 2026 inputs that are not shipped

Three verification records that October code reads are not shipped
(they carry names, staff-page and profile links, quoted evidence and per-paper adjudications); their
machine-readable outcomes are shipped as identifiers, years and codes. The code that reads them runs
only on the author's machine; each read site says so.

| record (not shipped) | read by | shipped outcome |
|---|---|---|
| `data/star_recheck_2026-09-22/` (17-star per-paper re-check; not shipped) | `pipeline/stars/caliber_2026-10/build_calls.py`, `restake_econ11.py`, `pipeline/frames/cal2026-10/fetch_star_id_supplement.py` | `data/cal2026-10/calls_2026-10.csv`, `star_id_corrections_2026-10.csv`, `recheck_*_2026-10.csv` |
| `data/roster_verify_2026-09-13_network102/` (102-person roster verification; not shipped) | `pipeline/rosters/cal2026-10/merge_network102.py`, `pipeline/frames/cal2026-10/run_controls.py` (control C3) | `data/cal2026-10/roster_econ_verified_2026-10.parquet`, `roster_added_2026-10.csv`, `roster_merge_report_2026-10.json` |
| `data/departure_verification_2026-09-10/` (187-row departure ledger; not shipped) | `pipeline/stars/caliber_2026-10/run_caliber.py`, `analysis/robustness/sensitivity/build_departure_187.py`, `run_sensitivity_cal2026_10.py`, `analysis/paper/ledger_robustness.py` (paper stage) | `data/cal2026-10/robustness/departure/` |

## The final rerun: what is not re-run or not shipped

The report's data (`data/report/`) were built by the final rerun on AWS (`pipeline/aws/r1/`). For each
record below: what reads it, and what this package ships instead.

| record | read by | shipped instead |
|---|---|---|
| the 4 large Panel 3 cells (not re-run by default; measured peaks in `data/report/custody/RESOURCES.md`) | stage 2 of `analysis/run_all.sh` | their custody records, `data/report/custody/`, checked by `tools/verify_cloud_custody.py` (`CUSTODY_OK`); `RUN_CLOUD_CELLS=1` re-runs them |
| the robustness runs (not re-run) | `analysis/paper/ledger_robustness.py` | their results and cloud records, `data/report/cal/robustness/`, `data/report/cal/cloud/`, `data/report/cal/cloud_t5/` |
| the roster collection: the staff lists read by AI agents and their independent checks, and the verification records (not shipped) | the roster merge of the final rerun | the merged rosters as OpenAlex ids, years and codes (`data/report/cal/`, `data/report/raw_verified/`), with `human_verified` per row |
| the OpenAlex API pages fetched on 16 October 2026 for some authors (not shipped) | `pipeline/aws/r1/patch_assemble.py` | the panels and build reports built from them, `data/report/frames/` and `data/report/cal/` |
| the star-origin readings behind Figure 1 (AI-drafted, checked blind; not shipped) | `tools/star_origins_extract_2026-10.py` | the merged origins table, `data/report/paper_inputs/star_origins_2026-10/` |
| the signed inputs of the final rerun, `data/cal2026-10r1/` (per-person rulings and lists; not shipped) | the AWS stages | their products in `data/report/` |
| the paper generators that read the author's trees (`analysis/paper/README.md`) | `RUN_PAPER=1 bash analysis/run_all.sh` | the printed numbers, `data/report/paper_numbers/` |

## What this register does NOT cover

* **Depth.** The ported builders start from their immediate inputs. Full-depth reproduction also needs
  the U1–U6 chain on the data disk (the 15 GB extraction).
* **Third-party reruns.** The frame tiers start from intermediates the package does not ship. The claim
  for this layer is "code, plus hashes, plus a rebuild verified on the author's machine", not "rebuild
  it yourself"; `pipeline/MANIFEST_intermediates.md` says, per artifact, which you are getting.
