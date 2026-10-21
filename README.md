# Star Arrivals and Their Colleagues

Code and data for **Star Arrivals and Their Colleagues: Evidence from Australian Academia**, by Jia Jia, The University of Melbourne (2026).

The study follows 377 star arrivals: economics 173, chemistry 97 and mathematics and statistics 107. It examines colleagues' research output, their first papers with the star, and first collaborations between colleagues.

**The final report data are in [`data/report/`](data/report/README.md).** The default command below uses this version.

## Find the results

| What you need | Where to look |
|---|---|
| Numbers reported in the paper | [Result ledgers](data/report/paper_numbers/) |
| Analysis datasets | [Panel data](data/report/frames/) |
| Recorded estimates used to check a run | [Reference results](data/report/expected/) |
| Code that estimates the results | [Estimation programs](analysis/estimation/README.md) |

## Run the replication

**Check your machine first.** The default run was tested on Linux x86_64 with 256 GiB of RAM. It took about 28 minutes and used up to **152.5 GiB of memory**. See the [resource requirements](data/report/custody/RESOURCES.md) before running it on a smaller machine.

Install Python 3.12, R 4.5.1 and `uv`, then run these commands from the repository root. Setup and the first R run need an internet connection; see [environment setup](setup/README.md) for details.

```bash
bash setup/install_py.sh
Rscript setup/install_r.R
bash analysis/run_all.sh
```

The default run re-estimates 23 of the 27 headline estimates and checks the other 4 against their recorded AWS runs. It prints `ALL_EQUAL` when all results match. In `output/compare_report.md`, expect **23 `EQUAL`** rows and **4 `VERIFIED_NOT_RERUN`** rows. Run logs are saved in `output/logs/`.

Re-running the four large estimates requires a second R environment and sufficient memory; see the [estimation guide](analysis/estimation/README.md). Rebuilding the data from raw sources or generating the manuscript also needs inputs not distributed here; see the detailed guide below.

## About this package

Version 1.0 was released on 19 October 2026. The [original published snapshot](https://github.com/jjjia2-svg/star-arrivals-replication/tree/ffa951e5c4950090b0aa6e6a14391a562cc270ab) remains available.

[Citation](CITATION.cff) · [Code licence](LICENSE) · [Data licence](LICENSE-DATA.md) · [AI use](docs/AI_USAGE.md)

Contact: Jia Jia, jjjia2@student.unimelb.edu.au.

---

<details>
<summary><strong>Full replication guide: data, methods, earlier versions and tests</strong></summary>

# Replication package: Star Arrivals and Their Colleagues

Replication package for the report **"Star Arrivals and Their Colleagues: Evidence from Australian
Academia"** by Jia Jia (ECON90072 Economics Research Report, Master of Economics, The University of
Melbourne, 2026). Package version 1.0, released 2026-10-19. It reproduces the report as
submitted.

## Overview

The report asks what happens to the researchers already in a university department when a highly
cited researcher (a "star") joins it. It uses 377 star arrivals from 1999 to 2024 at eleven
Australian universities: economics 173, chemistry 97 and mathematics and statistics 107. Three
panels measure three outcomes:

- **Panel 1**: the incumbents' own output (field-weighted publication counts);
- **Panel 2**: whether incumbents begin to coauthor with the star;
- **Panel 3**: whether pairs of same-topic incumbents outside the star's coauthor network begin to
  coauthor with each other.

Every estimate uses the difference-in-differences estimator of de Chaisemartin and D'Haultfoeuille
for treatments that start at different times, as implemented in the R package `DIDmultiplegtDYN`
(see References).

**One command.** From the repository root, `bash analysis/run_all.sh` checks the shipped data,
re-estimates 23 of the 27 headline estimates from the shipped panels, checks the other 4 against
their recorded runs, and prints `ALL_EQUAL` when every result equals its recorded value exactly.
The 4 checked cells are Panel 3 for economics and chemistry (main and event-clustered). Their
recorded memory use is in the [cell resource table](data/report/custody/RESOURCES.md). The default
run measurements are listed below.

| layer | command | what it reproduces | runs from this package? |
|---|---|---|---|
| analysis (default) | `bash analysis/run_all.sh` | the 27 headline estimates, from the panels in `data/report/frames/` | **yes** (23 re-estimated, 4 checked) |
| large cells (opt-in) | `RUN_CLOUD_CELLS=1 bash analysis/run_all.sh` | also re-runs the 4 large cells | yes, on a large machine with the second R stack (see below) |
| paper (opt-in) | `RUN_PAPER=1 bash analysis/run_all.sh` | the numbers, tables and figures, checked against the manuscript | no: needs the author's manuscript and working trees; the printed numbers ship in `data/report/paper_numbers/` |
| pipeline | `bash pipeline/run_all.sh` | the panels of the October 2026 version, from the rosters, the star screening and OpenAlex | no: needs the 15 GB OpenAlex extraction and the author's working trees |

The report's panels were built on AWS by the scripts in `pipeline/aws/r1/`. Their outputs and run
records are in `data/report/`.

**Earlier versions** stay in the package as checks; the same code reads them:

- **October 2026** (184 events: economics 113, chemistry 38, mathematics and statistics 33):
  `data/frames/`, `data/cal2026-10/` and `analysis/expected/`. Run it from the repository root with
  `SAR_PATHS_CONFIG=$PWD/config/paths_october.yaml bash analysis/run_all.sh` (29 recorded
  estimates: 25 re-run, 4 custody-checked).
- **August 2026** (187 events): frozen under `data/cal2026-08-28/` (frames, estimates and cloud
  records), checked by the tests.

`data/README.md` lists every data folder and the version it belongs to.

## Data availability and provenance

### Statement about rights

- I certify that the author of the report has legitimate access to and permission to use the data
  used in the report.
- I certify that the author has documented permission to redistribute the data contained in this
  package: derived tables built from public sources, and public-domain files (see the licences
  below). Staff pages, handbooks and other source documents are not redistributed.

### Summary of availability

- All data that the default command reads are in this package.
- Some data cannot be made public: the 15 GB OpenAlex extraction (it can be rebuilt from the public
  snapshot), the verification originals (names, staff-page and profile links, free-text notes), the
  OpenAlex API pages and the AI-assisted roster collection records. See "What is not shipped".

### Sources

| source | what it provides | licence or terms | in this package |
|---|---|---|---|
| **OpenAlex** full snapshot, release of 26 June 2026 (accessed July 2026) | works, authors, affiliations, citations, topics | CC0 1.0 | derived tables only |
| OpenAlex API, pages fetched on 13 August, 23 September and 16 October 2026 for some authors | works and affiliations missing from the snapshot | CC0 1.0 | derived tables only; the pages are not shipped |
| **Staff lists**: department pages archived by the Internet Archive (Wayback Machine) and the Australian Web Archive, university handbooks and annual reports, the Australian Mathematical Society Gazette, ORCID records and CVs | who worked in each department, and when | the documents belong to their publishers | OpenAlex author ids, years and codes only |
| Natural Earth 1:50m land polygons (downloaded 1 October 2026) | the land drawn in Figure 1 | public domain | `data/report/paper_inputs/basemap/` (byte copy) |
| NOAA ETOPO5 global relief (read 23 September 2026) | a 1-degree land mask used by the Figure 1 checks | public domain | the derived mask only |
| Australian Bureau of Statistics, *Research and Experimental Development, Higher Education Organisations, Australia, 2024* (accessed 11 September 2026) | two figures quoted in the introduction | CC BY 4.0 | the quoted figures, `data/report/paper_inputs/external_stats_2026-09-11.json` |
| Australian Research Council grant records | a cross-check of a few arrival dates | ARC website terms | not included |

### What is shipped

- `data/report/`: the data behind the report as submitted. `data/report/README.md` describes each
  folder:
  - `frames/`: the analysis panels (Panels 1, 2 and 3 for each discipline);
  - `expected/`: the 27 recorded headline estimates every run is compared with;
  - `cal/`: the event tables and their counts (`cal/counts.json`), the rosters, the per-discipline
    panel builds, the star ranking, and the robustness results with their cloud run records;
  - `cal_intermediates/`: the economics pair table, shipped xz-compressed
    (`pairs_unified.csv.xz`, listed in `PACKED.tsv`) and unpacked by stage 1;
  - `raw_verified/`, `paper_inputs/`: rosters and the inputs of the figures;
  - `custody/`: the records of the 4 large cells;
  - `paper_numbers/`: the numbers printed in the report (the dated ledgers of the final run).

  Several files keep their October 2026 names (for example `cal/events_econ_cal2026-10.csv`), so the
  same code reads both versions.
- **Rosters.** The staff lists were collected from the sources above and matched to OpenAlex
  authors, with AI assistance (see `docs/AI_USAGE.md`). 879 of the 2,640 economics roster rows are
  marked `human_verified`, counted directly from that column in the shipped report roster. The
  rosters are published as OpenAlex author ids, years and fixed English codes only.
- `data/fwci/`: the field-weighted citation benchmarks computed from the OpenAlex snapshot, with the
  scan manifests (510,372,821 works read, 2,446 shards, 0 bad lines).
- The earlier versions and their robustness results (see `data/README.md`).
- Every frozen file is pinned by sha256 in a `MANIFEST.sha256`. Files that were changed for this
  public copy (personal columns removed, names replaced, paths made relative, renamed) are listed
  with their private and published sha256 in `HASH_CROSSWALK.md`.
- Three manifests of the October version carry lines that `tools/verify_manifest.py` cannot verify:
  `data/cal2026-10/_invalid_run2/MANIFEST.sha256` (a voided run whose products were moved after they
  were recorded) and the two `products_MANIFEST.sha256` of the no-centre variant frames under
  `data/cal2026-10/robustness/nocentre/` (six large variant frames were never committed).
  `HASH_CROSSWALK.md` lists every such line.

### What is not shipped

- **The 15 GB OpenAlex extraction** (the narrow tables of works, authors and affiliations the panels
  are built from) and **the verification originals** (archived staff pages, per-person evidence,
  the AI-assisted collection records and the row-by-row verification records). Both contain personal
  information or can be used to recover it. Examiners and data editors can request access from the author (address below).
- The OpenAlex API pages and the star-origin readings behind Figure 1 (their outputs are shipped).
- The AWS run records other than the custody records shipped in `data/report/`.
- The author's manuscript sources (needed only by the opt-in paper stage).

`pipeline/NOT_REPRODUCIBLE.md` lists, record by record, what reads each of these and what is shipped
instead.

### Privacy

Removing names does not make the data anonymous: an OpenAlex author id can be looked up in the
public OpenAlex API, and stars and their arrival years are part of the research design. The project
used only public career and publication information; no human-subjects data were collected.

## Computational requirements

### Software

- **R 4.5.1** with `DIDmultiplegtDYN` 2.3.3, `polars` 1.10.0.9000, `data.table` 1.17.8, `jsonlite`
  2.0.0, `fixest` 0.14.0 and `yaml` 2.3.10 (`setup/R_VERSIONS.txt`; full lockfile `setup/renv.lock`).
  This stack re-estimates the 23 cells of the default run. Install it with `Rscript setup/install_r.R`,
  which installs `DIDmultiplegtDYN` 2.3.3 from the vendored tarball in `setup/vendor/`, or with
  `renv::restore(lockfile = "setup/renv.lock")`. `polars` for R is a development build; see
  `setup/README.md`. **The first R run needs the network:** it downloads renv 1.2.4 and creates the
  project library; later runs work offline.
- **A second R stack, only for `RUN_CLOUD_CELLS=1`:** R 4.6.1 with `DIDmultiplegtDYN` 2.4.0,
  `polars` 1.10.0.9000, `data.table` 1.18.6.1, `jsonlite` 2.0.0 and `fixest` 0.14.2
  (`config/r1/expected_versions.txt`). The 4 large cells were estimated with this stack.
  `analysis/estimation/README.md` says how to install it.
- **Python 3.12** with the locked environment in `setup/uv.lock` (`duckdb` 1.5.4, `pyarrow` 24.0.0,
  `pandas` 3.0.2 and others). Install it with `bash setup/install_py.sh`, which needs
  [uv](https://docs.astral.sh/uv/) and creates `setup/.venv/`. `setup/requirements.txt` holds the
  same lock for pip.
- `bash`, `xz` and standard Unix tools.

### Random seeds

`config/seeds.yaml` records every seed:

- **42**: `set.seed(42)` in `run_p1.R`, `run_p2.R`, `run_p1_evcl.R` and `run_p2_evcl.R`. `run_p3.R`
  uses it only for its optional subsample (`frac` below 1); `run_p3_evcl.R` and `run_p3_tp.R` set no
  seed.
- **0**: `PYTHONHASHSEED=0`, exported by `analysis/run_all.sh`.
- **20260829**: the permutation inference of Panels 1 and 2 (`analysis/robustness/inference/run_perm.R`;
  permutation i uses `set.seed(20260829 + i)`).
- **20260817**: the first no-effect simulation of Panel 3 (August 2026, 3 draws,
  `data/paper_inputs/NULL_*_A_far.json`); its script is not shipped.

The report's Panel 3 permutations and no-effect simulations use the seed base 20260830 (draw i uses
`set.seed(20260830 + i)`), set in `config/r1/robustness_r1.json` with the other robustness settings.

### Hardware, runtime and storage

The results were computed and checked on Linux x86_64.

| default run measurement | value |
|---|---|
| Wall time | 28 minutes (1,667 s) on an AWS r6i.8xlarge (32 vCPUs, 256 GiB) |
| Peak resident memory | 152.5 GiB |

Both were measured on 2026-10-19 by the end-to-end test of this release, which exports the package, sets it up as
a reader would and runs `bash analysis/run_all.sh` (`run_all.secs` and `run_all.peak_gib` in its summary).
The supplied canon has 303,181,052 bytes of packed files; restoring the pairs CSV adds
481,997,636 bytes while retaining its 4,804,448-byte `.xz` copy. Earlier data versions, software
environments and run outputs need additional disk. The e2e export reports the final package size
in `bytes_public`; `docs/public/release_metrics.json` records the supplied canon sizes.

The [cell resource table](data/report/custody/RESOURCES.md) lists the recorded wall time and peak
resident memory for all 27 headline cells, including the maximum for the 4 large cells. It compares
each peak with 16, 32 and 64 GiB; an operating system and concurrent processes need additional memory.
The accompanying `resources.json` pins the source reports and contains the same numeric values.

### Steps that ran on AWS

For the report's data, every step that needs large data or a large machine ran on AWS. This package
does not re-run those steps by default; what they produced is shipped with records that can be checked
in seconds.

| job kind | settled jobs | instance type | instance hours | USD |
|---|---:|---|---:|---:|
| `j1a` | 21 | r6i.16xlarge | 12.2081 | 49.7583 |
| `j1b` | 7 | r6i.16xlarge | 25.9916 | 105.9375 |
| `final` | 14 | m6i.2xlarge | 4.5082 | 1.8793 |

These totals include retries through final-14. All job kinds and separate adjustments total
USD 199.4336 in settled instance charges; storage and transfers are excluded.
See `pipeline/aws/r1/README.md` and `docs/public/release_metrics.json`.

`pipeline/aws/r1/README.md` describes these jobs. The earlier AWS runs (the OpenAlex extraction and
the cloud cells of the October and August versions) are in `pipeline/aws/README.md`.

For the 4 large cells, `tools/verify_cloud_custody.py --custody data/report/custody --spec
data/report/custody/custody_r1.json` (run by stage 2) checks that the panels and R drivers in this
package are byte-identical (md5) to what the cells ran on, and that the results fetched back equal
the recorded estimates in `data/report/expected/`. It prints `CUSTODY_OK`; in
`output/compare_report.md` these cells appear as `VERIFIED_NOT_RERUN`.

**Cloud records.** The EC2 instance ids, security-group ids and key-pair names in these records
belong to instances that no longer exist and are kept as part of the custody chain. Public IPv4
addresses and private host names were replaced by `<ip>` and `<host>` in this copy.

## Instructions to replicators

1. Install the environments: `bash setup/install_py.sh` and `Rscript setup/install_r.R`.
2. From the repository root, run:

   ```
   bash analysis/run_all.sh
   ```

   It first prints the data version and its event counts.

   - **Stage 1, inputs:** the compressed pair table is unpacked and its sha256 checked against
     `data/report/PACKED.tsv`. Then every line of the `MANIFEST.sha256` in each of the six data
     folders of `data/report/` (`cal`, `frames`, `expected`, `raw_verified`, `paper_inputs`,
     `cal_intermediates`) must verify, and `tools/r1_canon.py check` must accept the canon. A changed
     or missing file stops the run.
   - **Stage 2, estimation:** each row of `config/r1/cells/M.tsv` and `config/r1/cells/M_evcl.tsv`
     marked `rmac` (23 cells) is re-estimated from `data/report/frames/` with the drivers in
     `analysis/estimation/`, and `tools/compare_all.py` compares each result with
     `data/report/expected/`. The 4 rows marked `rcloud` are custody-checked as above. The run
     prints `ALL_EQUAL`.
3. Read `output/compare_report.md`: every row must be `EQUAL` or `VERIFIED_NOT_RERUN`. Logs are in
   `output/logs/`. `output/` is not tracked.

**Re-running the 4 large cells.** Choose memory above the recorded peaks in the
[cell resource table](data/report/custody/RESOURCES.md), with room for the operating system. Install
the second R stack, set `SAR_RSCRIPT_RCLOUD` (its `Rscript`) and `SAR_RLIB_RCLOUD` (its package library), and run
`RUN_CLOUD_CELLS=1 bash analysis/run_all.sh`. Without the two variables the run stops.

**Paper stage (opt-in).** `RUN_PAPER=1 bash analysis/run_all.sh` runs the generators in
`analysis/paper/` and then `tools/check_paper.py`, which checks the numbers, tables and figures
against the manuscript. On `data/report/` it runs as `--stages 1,2,3est,3light,4check`: the four
generators that estimate, then the others, then the check. It needs two trees this package does
not ship: the manuscript (`$SAR_LEGACY_THESIS`) and the author's frozen intermediate outputs
(`$SAR_LEGACY_V2_OUTPUT`). Without them it stops before stage 1 and names the missing tree. The
numbers the report prints are in `data/report/paper_numbers/`.

**Paths.** `config/paths.yaml` is the only file that knows where things are; it selects
`data/report/`. `config/paths_october.yaml` selects the October version. Paths inside the repository
are relative. The four external roots take environment variables: `$SAR_LEGACY_THESIS`,
`$SAR_LEGACY_V2_OUTPUT`, `$SAR_LEGACY_MULTIPLEX` (the original data-collection code the pipeline was
ported from) and `$SAR_SSD_ROOT` (the OpenAlex extraction; its last path component must be
`openalex_pipeline`).

**Pipeline layer.** `pipeline/` holds the code that built the panels: roster assembly, star
screening, arrival-event gates, field-weighted citation benchmarks and panel builders, and the AWS
scripts of the final rerun (`pipeline/aws/r1/`). It is published so the construction can be read and
audited, but it is not self-contained: 14 of the 15 default stages of `bash pipeline/run_all.sh`
read the author's working trees (2 of them also the extraction), and the 15th, the FWCI build, reads
only the extraction. `bash pipeline/run_all.sh --list` shows what each stage needs.

**Robustness results** are shipped as computed on AWS and are not re-run: `data/report/cal/robustness/`,
with their cloud records in `data/report/cal/cloud/` and `data/report/cal/cloud_t5/`. The scripts are
in `analysis/robustness/`; the README in each directory says what it needs.

**Run logs.** Run logs that a custody record pins by hash are byte copies. Some keep the drivers'
original progress lines in Chinese; translating them would break the custody check.

## Exhibits and the programs that produce them

Numbering as in the submitted report. The generators are in `analysis/paper/` and write only to
`output/paper/`; `analysis/paper/README.md` says which ones read the author's trees. The numbers
each exhibit prints are in the dated ledgers in `data/report/paper_numbers/`
(`data_numbers_2026-10-24*.json`). The date is a ledger label; the release date is 2026-10-19.

| exhibit | content | produced by | ledger and keys under `paper_numbers/` |
|---|---|---|---|
| Figure 1 | origins of the stars | `fig_star_origins.py` | `data_numbers_2026-10-24.json`: `econ_events`, `chem_events`, `math_events` give the dot totals; locations are in `paper_inputs/star_origins_2026-10/` |
| Figure 2 | exposure around an arrival | `fig_hops.py` | `data_numbers_2026-10-24_gaps_zenou.json`: `roster`, `network`, `network_only`, `union`, `outside_network` |
| Table 1 | the three panels | `draft_2026_09_13_tables.py` | `data_numbers_2026-10-24.json`: `*_relations`, `*_persons`, `*_events`, `panel_rows` |
| Figure 3 | years compared by each coefficient | `fig_compare_years.py` | `data_numbers_2026-10-24.json`: `events_by_school_econ`; year arrows are design constants |
| Table 2 | main estimates | `draft_2026_09_13_tables.py` | `data_numbers_2026-10-24_p1p2.json`: `p1_*`, `p2_*`; `data_numbers_2026-10-24_p3afar.json`: `econ`, `chemistry`, `math_stats` |
| Figure 4 | Panel 1 coefficients | `fig_p1.py` | `data_numbers_2026-10-24_p1p2.json`: `p1_*.horizons`, `p1_*.placebos` |
| Figure 5 | Panel 2 coefficients | `fig_p2.py` | `data_numbers_2026-10-24_p1p2.json`: `p2_*.horizons_pp` |
| Figure 6 | Panel 3 coefficients | `ledger_p3afar.py`, `fig_p3_afar.py` | `data_numbers_2026-10-24_p3afar.json`: `*.horizons_pp` |
| Table 3 | robustness checks | `draft_2026_09_13_tables.py` | `data_numbers_2026-10-24_robustness.json`: `p1_variants`, `p1_pretrend_by_channel`, `p1_date_shift`, `p2_date_shift`, `p3_date_shift`, `p3_cut_grid`, `no_centre_roster`, `d7` |

The headline estimates come from the drivers in `analysis/estimation/`:

| driver | cells (recorded estimates in `data/report/expected/`) |
|---|---|
| `run_p1.R` | Panel 1 for each discipline (`P1_*`) |
| `run_p2.R` | Panel 2 for each discipline (`P2_*`) |
| `run_p3.R` | Panel 3 on all pairs (`P3_*`; economics and chemistry are large cells) |
| `run_p1_evcl.R`, `run_p2_evcl.R`, `run_p3_evcl.R` | the same cells with standard errors clustered by event (`P*evcl_*`; Panel 3 economics and chemistry are large cells) |
| `run_p3_tp.R` | Panel 3 on same-topic pairs outside the star's network: the report's Panel 3 (`P3pos_*`) and its comparison cells (`P3med_*`, `P3lb_*`) |

`analysis/estimation/README.md` gives the specification of each driver and the R stack of each cell.

## Tests

Run the tests from a Git clone of the public repository. The public history starts with
exported files; private pre-R1 Git objects are not shipped. The current-file provenance
checks still run; only the separate historical-object check skips when those objects are absent.

The R1 pipeline code is retained as a record. Its signed inputs and run records under
`data/cal2026-10r1/`, manuscript fixtures under `tests/fixtures/r1_paper/`, manuscript tools,
October manuscript ledgers and private departure-verification inputs are not shipped.
An exact test prerequisite registry in `sar_f0_plugin.py` skips a test only when its named
restricted input is absent, with that path in the reason. Restoring the input enables the test.
AWS-only tools retain their host guards: their dependent tests require `SAR_HOST=ec2-r1-test`
or `ec2-r1`. Portable toy tests and tests of the guards themselves remain active.

Two commands; the first does NOT include the second (`pytest.ini` sets `testpaths = tests`):

```
setup/.venv/bin/python -m pytest -q                  # the repository's tests
setup/.venv/bin/python -m pytest -q pipeline/units   # the ported pipeline unit tests (U0-U6)
```

The first runs the integrity checks (manifests, recorded estimates, cloud custody) and the checks on
the ported `pipeline/` code in `tests/test_verbatim_pipeline.py` (the byte manifest
`tests/pipeline_ported.sha256` and the symbolic pins `tests/pipeline_symbolic.sha256`, recorded against
the private original code; the pins of files whose text was changed to remove names were re-minted
from the published code and are listed in `HASH_CROSSWALK.md`).

Source inventory at this release: `1,832` test definitions in
`135` root-suite files and `1,930` definitions in
`183` pipeline-unit files (`docs/public/release_metrics.json`). These are
static source counts, before export exclusions and pytest parametrization, not claimed pass counts.
The e2e summary records the public suites' actual passed, skipped, failed and error counts.

The second command runs the unit tests of the ported pipeline units; it is a separate run because
those units reuse test-module names (`pipeline/README.md`). Tests that need the author's private
trees, or archived staff pages that are not shipped, skip when those are absent.

## References

Data:

- Australian Bureau of Statistics. *Research and Experimental Development, Higher Education
  Organisations, Australia*, reference period 2024, released 8 May 2026.
  https://www.abs.gov.au/statistics/industry/technology-and-innovation/research-and-experimental-development-higher-education-organisations-australia/latest-release
  (accessed 11 September 2026). CC BY 4.0.
- Natural Earth. *1:50m physical vectors, land polygons* (`ne_50m_land.geojson`),
  naturalearthdata.com. GeoJSON copy downloaded on 1 October 2026 from the project's
  `natural-earth-vector` repository (the exact URL is in `data/paper_inputs/basemap/README.md`).
  Public domain.
- NOAA National Geophysical Data Center. *ETOPO5 global relief*, data announcement 88-MGG-02. Read on
  23 September 2026 from the copy distributed with MATLAB R2025b (`topo.mat`). Public domain.
- OpenAlex (OurResearch). Full data snapshot, release of 26 June 2026 (accessed July 2026); and the
  OpenAlex API, https://api.openalex.org (pages fetched on 13 August, 23 September and 16 October
  2026). CC0 1.0.

Software:

- Quispe, A., Ciccia, D., Knau, F., Malezieux, M., Sow, D. and de Chaisemartin, C.
  *DIDmultiplegtDYN: Estimation in Difference-in-Difference Designs with Multiple Groups and Periods*.
  R package version 2.3.3 (CRAN, published 17 March 2026; shipped as
  `setup/vendor/DIDmultiplegtDYN_2.3.3.tar.gz`) and version 2.4.0 (installed from the CRAN snapshot of
  22 September 2026, https://p3m.dev). https://github.com/Credible-Answers/did_multiplegt_dyn

## Licence

- **Code**: MIT License, see `LICENSE`.
- **Derived data** in `data/` and `analysis/expected/`: Creative Commons Attribution 4.0
  International (CC BY 4.0), see `LICENSE-DATA.md`. The upstream OpenAlex data are CC0; the
  Natural Earth and ETOPO5 files are public domain.
- **Third-party software** keeps its own licence, including the vendored
  `setup/vendor/DIDmultiplegtDYN_2.3.3.tar.gz` (MIT). See `THIRD_PARTY.md`.

## Citation

Please cite this package as described in `CITATION.cff`: Jia Jia, *Star Arrivals and Their
Colleagues: Evidence from Australian Academia*, replication package, version 1.0, The University of
Melbourne, 2026.

## AI use

The work used Claude (Anthropic) and Codex (OpenAI), as the report states. See `docs/AI_USAGE.md`.

## Contact

Jia Jia, The University of Melbourne: jjjia2@student.unimelb.edu.au

</details>
