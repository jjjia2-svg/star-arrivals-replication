# How the data were obtained

[Home](../README.md) · [Data and R code](DATA_AND_CODE.md)

The work combined publication records from OpenAlex with staff lists and public career records. Python scripts collected and prepared the data; R scripts estimated the results. The final analysis datasets are already included in [data/report/frames/](../data/report/frames/).

The route was: **publication and staff records → matched researchers and department histories → star arrivals → yearly analysis datasets → R estimates**.

## 1. Obtain publication records

The source was the OpenAlex snapshot dated 26 June 2026, accessed in July 2026. It supplied publications, authors, affiliations, citations and research topics. Additional OpenAlex API pages were fetched for selected authors on 13 August, 23 September and 16 October 2026 to fill gaps in works and affiliations.

The [snapshot retrieval record](../pipeline/aws/launch_u1_fetch.sh) gives the historical download commands, snapshot checks and extraction steps. The [extraction driver](../pipeline/run_smoke_m1.py) and [driver guide](../pipeline/drivers/README.md) show how the narrow working tables were produced. The [scan manifest](../data/fwci/scan_manifest.json) records the completed scan.

These are records of the data actually used. Downloading today's snapshot or calling the live API again can return different records. The approximately 15 GB extraction and saved API pages are not distributed here; rebuilding from this stage needs those inputs or a reconstruction from the matching source snapshot.

## 2. Establish who worked in each department

Staff lists came from archived department pages, university handbooks and annual reports, the Australian Mathematical Society Gazette, ORCID records and CVs. These sources supplied employment histories and supported checks of arrival dates. Collection used AI assistance, documented in [AI use](AI_USAGE.md).

The [historical-page collection tools](../pipeline/units/u0p5_hist_raw/README.md), [roster matching tools](../pipeline/units/u0p5_dept_roster/README.md) and [roster assembly guide](../pipeline/rosters/README.md) record this work. Collection and verification also involved recorded decisions that cannot be recreated by running a script alone.

Final roster and event records are in [data/report/cal/](../data/report/cal/) and related [roster inputs](../data/report/raw_verified/). The [report data index](../data/report/README.md) explains the verification flags and codes. Names, personal evidence links and free-text verification notes are not included in the public copy. An OpenAlex author identifier can still be looked up publicly.

## 3. Match researchers and identify star arrivals

The [identity-matching unit](../pipeline/units/u2_resolve/README.md) links publication records to researchers. The final build applies the recorded identity decisions, ranks candidate stars and forms the arrival-event tables through [calls_lib.py](../pipeline/aws/r1/calls_lib.py), [rank_r1.py](../pipeline/aws/r1/rank_r1.py), [restake_r1.py](../pipeline/aws/r1/restake_r1.py) and [events_r1.py](../pipeline/aws/r1/events_r1.py).

The resulting [event counts](../data/report/cal/counts.json) are 173 for economics, 97 for chemistry and 107 for mathematics and statistics. The [final run configuration](../config/r1/M.json) records the settings. No new ranking or matching decision is needed to use the published analysis data.

## 4. Build the yearly analysis datasets

The final builders are [econ920_m.py](../pipeline/aws/r1/econ920_m.py) for economics and [chemmath_m.py](../pipeline/aws/r1/chemmath_m.py) for chemistry and mathematics and statistics. They combine the event tables, rosters, publication records and coauthor links. The [field citation benchmarks](../pipeline/fwci/README.md) support the output measure.

The builders produce research-output observations, first collaborations with the star and first collaborations between incumbents. [The Panel 3 builder](../pipeline/frames/cal2026-10/run_cal_afar.py) and [sample-cut code](../analysis/robustness/p3_afar_cuts/build_afar_cut.py) construct its restricted pair samples. The final R1 build reuses these construction steps with its final inputs; a date in a script's path does not by itself identify the data version.

[promote_r1.py](../pipeline/aws/r1/promote_r1.py) and [final_stage.py](../pipeline/aws/r1/final_stage.py) package the outputs. The [final-run guide](../pipeline/aws/r1/README.md) identifies the scripts and saved records. The delivered analysis tables are in [frames/](../data/report/frames/), and the final report's event and build records are in [cal/](../data/report/cal/).

## 5. Estimate and check the results

The [data and R code guide](DATA_AND_CODE.md) maps each paper panel to its dataset and R script. [analysis/run_all.sh](../analysis/run_all.sh) uses these prepared tables and compares its outputs with [recorded estimates](../data/report/expected/). The [paper-number files](../data/report/paper_numbers/) retain the values printed in the report.

## What can be used from this repository?

| Task | Available here? |
|---|---|
| Read the final analysis data, code and saved results | Yes. No computation is needed. |
| Run the default analysis from the final datasets | Yes, with the documented software and memory. It re-estimates 23 results and verifies four saved large runs. |
| Rebuild everything from the original sources | Not from this repository alone. The snapshot extraction, verification originals and some author working files are required. |
| Generate the manuscript's figures and tables through the paper stage | Requires manuscript and working files not included here; the printed numbers are included. |

The [input-availability register](../pipeline/NOT_REPRODUCIBLE.md) lists the gaps and what can be checked instead. Requests for the retained restricted inputs can be sent to the [author](../README.md#about-this-package). The construction scripts are published for inspection; this guide does not launch a data build or AWS job.

## Links in the earlier guides

Earlier technical guides remain unchanged. In the frame guide, use [section 5: the recorded rebuild discrepancy](../pipeline/frames/README.md#5-the-one-thing-that-does-not-match); its original short jump omits the section number. For the ABS figures quoted in the introduction, the [saved source record](../data/report/paper_inputs/external_stats_2026-09-11.json) retains the values and source details. The original ABS link and alternative official pages returned temporary service errors during the link check; their live availability could not be confirmed.
