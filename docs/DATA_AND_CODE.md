# Data and R code

[Home](../README.md) · [How the data were obtained](DATA_WORKFLOW.md)

The paper uses the final data in [data/report/](../data/report/README.md): 377 star arrivals, with 173 in economics, 97 in chemistry and 107 in mathematics and statistics. An incumbent is a researcher already at the department or connected to the star through the coauthor network before arrival. The three panels below answer different questions about these researchers.

## Choose a dataset and its R script

All links below point to the final report data. CSV files are text tables; Parquet files store tables in a compact format and usually need to be downloaded before opening.

| Paper panel | Economics | Chemistry | Mathematics and statistics | R script |
|---|---|---|---|---|
| 1. Incumbents' research output | [CSV](../data/report/frames/p1_frame_econ.csv) | [CSV](../data/report/frames/p1_frame_chemistry.csv) | [CSV](../data/report/frames/p1_frame_math_stats.csv) | [run_p1.R](../analysis/estimation/run_p1.R) |
| 2. First collaboration with the star | [CSV](../data/report/frames/p2_becoming_econ.csv) | [CSV](../data/report/frames/p2_becoming_chemistry.csv) | [CSV](../data/report/frames/p2_becoming_math_stats.csv) | [run_p2.R](../analysis/estimation/run_p2.R) |
| 3. First collaboration between incumbents | [Parquet](../data/report/frames/p3_afar_pos_econ.parquet) | [Parquet](../data/report/frames/p3_afar_pos_chemistry.parquet) | [Parquet](../data/report/frames/p3_afar_pos_math_stats.parquet) | [run_p3_tp.R](../analysis/estimation/run_p3_tp.R) |

**Panel 3 in the paper uses the `p3_afar_pos_*` files.** These contain same-topic pairs whose members both have positive research-topic similarity to the star and are outside the star's pre-arrival coauthor network: neither is a direct coauthor of the star or connected through one intermediate coauthor. The broader `p3_slim_*` samples and the other `p3_afar_*` cuts remain available for comparison. The [sample builder](../analysis/robustness/p3_afar_cuts/build_afar_cut.py) records the positive-dose and median-dose cuts.

## What a row means

- **Panel 1:** one incumbent, one star-arrival event and one calendar year. The same person can appear in several events.
- **Panel 2:** one incumbent-star relation in one calendar year while it is observed for first collaboration.
- **Panel 3:** one incumbent pair, one star-arrival event and one calendar year while the pair is observed for first collaboration.

The main columns are:

| Column | Meaning |
|---|---|
| `incumbent_person_id` or `pid` | The incumbent's identifier in Panels 1 and 2. |
| `event_id` or `ev` | The star-arrival event identifier. |
| `year` | Calendar year. Panel 2 also has `tau`, the year relative to arrival. |
| `post` | Whether the year is at or after arrival. Panel 3 stores this indicator as `D`. |
| `fwci_frac` | Panel 1's citation-weighted fractional publication output. The R script uses `log(1 + fwci_frac)`. |
| `dose_topic` | Research-topic similarity to the star, measured before arrival. Panel 1 uses `dose_topic × post` as its exposure variable. |
| `channel` | Department only (`dept_only`), coauthor network (`network`), or both (`both`). Panel 1's `union` result uses the combined sample. |
| `y` | Panel 2: first collaboration with the star. Panel 3: first collaboration between incumbents on a paper without the event star. The indicator is 1 when that outcome occurs and 0 in other observed years. |
| `grp` | Panel 3's identifier for a pair within an arrival event. The file uses these compact group identifiers. |

Panel 3 observation ends at the first collaboration between the pair, including a paper with the star. Such a paper ends observation but is not counted in `y`.

The [R guide](../analysis/estimation/README.md) gives the full filters and settings. The [data index](../data/report/README.md) explains the roster and event files and the public copy's removed personal columns.

## Follow the output

The [main run list](../config/r1/cells/M.tsv) links every input file to its R script, run label and recorded output filename. The [event-clustered run list](../config/r1/cells/M_evcl.tsv) covers versions that calculate uncertainty by arrival event.

| Report result | Recorded output in [expected/](../data/report/expected/) |
|---|---|
| Panel 1 | `P1_econ_fnfix.json`, `P1_fnfix_chemistry.json`, `P1_fnfix_math_stats.json`; the `channels.union` entries give the combined-sample results. |
| Panel 2 | `P2_econ_fnfix.json`, `P2_fnfix_chemistry.json`, `P2_fnfix_math_stats.json`. |
| Panel 3 | `P3pos_econ_A_far.json`, `P3pos_chemistry_A_far.json`, `P3pos_math_stats_A_far.json`. The run labels begin `P3cut_pos_`; the runner saves them under these recorded filenames. |

[Paper-number files](../data/report/paper_numbers/) contain the values used in the paper's tables and figures. [The exhibit guide](../README.md#exhibits-and-the-programs-that-produce-them) maps them to each exhibit. Earlier August and October datasets remain in their existing folders; the [version index](../data/README.md) identifies them.

## Run the analysis

Follow the [installation and replication instructions](../README.md#run-the-replication), including the memory requirements. The entry point is `bash analysis/run_all.sh`. It reads the final analysis data, re-estimates 23 of the 27 recorded estimates, and verifies the other four against their saved AWS records. It writes new results under `output/estimates/` and a comparison table at `output/compare_report.md`. Those output files are created by a run and are not included in the repository.

Reading the data, R code and recorded results requires no AWS run. Rebuilding the data is a separate process described in the [data workflow](DATA_WORKFLOW.md).
