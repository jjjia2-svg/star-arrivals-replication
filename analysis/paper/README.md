# analysis/paper

Generators for the numbers, tables and figures of the report. They read frozen inputs only and write
only to `output/paper/` (not tracked). `RUN_PAPER=1 bash analysis/run_all.sh` runs them in dependency
order and then the checker `tools/check_paper.py`.

**Author-only in version 1.0.** Several generators read the author's working trees or records that
are not shipped (list below), so this stage does not run from the package alone. The numbers the
report prints are shipped instead: the dated ledgers of the final run, `data_numbers_<date>*.json`,
in `data/report/paper_numbers/`.

## The printed exhibits

Numbering as in the submitted report. Figures 5 to 7 and Tables 1 to 3 are drawn in the submitted
layout with `--tree base_2026_10_11`; without the flag the generators draw an earlier manuscript's
layout.

| exhibit | generator | reads | printed numbers |
|---|---|---|---|
| Figure 1, where the stars worked before they arrived | `fig_star_origins.py` (drawing in `fig_star_origins_dots.py`) | `paper_inputs/star_origins_2026-10/`, `paper_inputs/basemap/` | inputs only (no dated ledger) |
| Figure 2, who is exposed to an arrival | `fig_hops.py` | `gaps_zenou.json` | `data_numbers_<date>_gaps_zenou.json` |
| Table 1, the three panels | `draft_2026_09_13_tables.py` | the main, Panel 1-2, Panel 3 and robustness ledgers | `data_numbers_<date>.json` |
| Figure 3, which two years each Panel 1 coefficient compares | `fig_compare_years.py` | `data_numbers_carried.json` (`events_by_school_econ`) | `data_numbers_<date>.json` |
| Figure 4, the comparison relations in each year | `fig_comparison_pools.py` | `data_numbers_carried.json` | `data_numbers_<date>.json` |
| Table 2, main estimates | `draft_2026_09_13_tables.py` | as Table 1 | `data_numbers_<date>_p1p2.json`, `data_numbers_<date>_p3afar.json` |
| Figure 5, Panel 1 | `fig_p1.py --tree base_2026_10_11` | `data_numbers_p1p2.json` | `data_numbers_<date>_p1p2.json` |
| Figure 6, Panel 2 | `fig_p2.py --tree base_2026_10_11` | `data_numbers_p1p2.json` | `data_numbers_<date>_p1p2.json` |
| Figure 7, Panel 3 | `ledger_p3afar.py --tree base_2026_10_11` (drawing in `fig_p3_afar.py`) | the Panel 3 frames and estimates | `data_numbers_<date>_p3afar.json` |
| Table 3, robustness | `draft_2026_09_13_tables.py` | as Table 1 | `data_numbers_<date>_robustness.json` |

`draft_2026_09_13_tables.py` reads the dated ledgers in the manuscript tree by default; with
`--paper-dir output/paper` it reads this run's ledgers instead. A note sentence whose claim the
numbers no longer support is flagged in `NOTE_CHECKS.json` and never reworded.

## The ledgers and other generators

| generator | output (`output/paper/`) | what it covers |
|---|---|---|
| `ledger_main.py` | `data_numbers_main.json` | the counts, shares and quantiles of the data section, from the frames and the event tables |
| `ledger_carried.py` | `data_numbers_carried.json` | counts carried from the panel builds (events by school, roster and missing-outcome counts); run before Figures 3 and 4 |
| `ledger_p1p2.py` | `data_numbers_p1p2.json` | Panels 1 and 2: estimates, joint placebo tests, raw rates |
| `ledger_p3afar.py` | `data_numbers_p3afar.json`, `fig_p3_afar.pdf` | Panel 3: estimates, raw rates, joint tests, the speed bracket |
| `ledger_robustness.py` | `data_numbers_robustness.json` | the robustness results read from the frozen robustness folders |
| `ledger_funnel.py` | `data_numbers_funnel.json` | the counts of the sample funnel (snapshot works, benchmark cells, pair pools), read from frozen manifests |
| `gaps_zenou.py` | `gaps_zenou.json` | the worked example of one economics arrival |
| `gaps_zero_dose.py` | `gaps_zero_dose.json` | the shares of relations with a dose of exactly zero |
| `gaps_switchers.R`, `gaps_switchers_p1p2.R` | `gaps_switchers*.json` | switcher counts and average doses (re-runs the Panel 1 and 2 estimation; run from the repository root so renv activates) |
| `gaps_toy.R` | `gaps_toy.json` | the five-relation worked example of the estimator |
| `tables_main.py`, `tables_p1p2.py`, `tables_p3afar.py`, `tables_robustness.py` | `tab_*.tex` | the tables of the earlier manuscript layout |
| `fig_exposure_population.py`, `fig_dose_distribution.py` | `fig_*.pdf` | two figures of the earlier manuscript layout |
| `_fig34_style.py`, `_fig567_style.py` | — | shared drawing rules of Figures 3 to 7. The font is TeX Gyre Pagella from the pinned TeX layer; without it the generators stop (`STOP fig34`, exit 2). `--test-font-fallback` draws in DejaVu Serif, for tests only |

Figures 3 to 7 are data-driven ports of the author's own drawing scripts, which are kept privately
with their md5 (not shipped).

## Generators that need the author's trees or unshipped records

- `ledger_carried.py`, `ledger_funnel.py` and `ledger_p3afar.py` read frozen outputs in the author's
  working tree (`$SAR_LEGACY_V2_OUTPUT`).
- `tables_main.py` uses the manuscript's own table as its template, and `draft_2026_09_13_tables.py`
  reads the manuscript's dated ledgers by default (`$SAR_LEGACY_THESIS`).
- `ledger_robustness.py` reads the departure-verification ledger (names and quoted evidence; not
  shipped).
- `gaps_zenou.py`, on the report's data, also reads a signed input list of the final rerun that names
  persons (`flips_r1.json`, not shipped).
- `tools/check_paper.py` reads the manuscript text.

## The checker

`tools/check_paper.py` checks the manuscript against everything generated here: every key of the
manuscript's dated ledgers must be generated and equal; generated tables must be byte-identical;
figures must exist; and a table of in-text claims compares each printed number with its ledger
value. It writes `output/paper_check.md` (one PASS or FAIL line per check) and exits 1 while any
check fails. TeX comments are stripped before matching, so stale wording in a comment cannot pass a
check.

Numbers that define the design rather than result from it are not checked: event windows, the 0.05
pass threshold, the star percentile cut-offs, the estimator's arguments (6 effects and 4 placebos
in Panel 1, 5 effects in Panels 2 and 3), numbers quoted from the literature, and layout constants.
`sec23_number_audit.tsv` lists every number printed in Sections 2 and 3 as pinned, design constant
or needing a key. A printed count that a run can change is never exempt; if it has no key in the
manuscript's ledgers, its key goes into `output/paper/data_numbers_r1_counts.json`.
