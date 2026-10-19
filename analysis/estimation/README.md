# analysis/estimation

R drivers that run the de Chaisemartin and D'Haultfoeuille estimator
(`DIDmultiplegtDYN::did_multiplegt_dyn`) on the frozen panels. Each driver writes `<label>.json` to
`$SAR_OUT` (default `out/`; `analysis/run_all.sh` sets `SAR_OUT=output/estimates`). Each driver is a
copy of the program that produced the recorded estimates; its only code edit is that it reads its
output folder from `$SAR_OUT`. In this public copy the comments of `run_p1.R`, `run_p1_evcl.R`,
`run_p2.R`, `run_p2_evcl.R` and `run_p3_tp.R` are translated into English; `run_p3.R` and
`run_p3_evcl.R` are byte-identical, because custody records pin their bytes (below). The results must
equal the recorded estimates exactly (`python3 -m analysis.lib.compare_json new.json recorded.json`,
ignoring `secs` and `file`).

Usage: `Rscript analysis/estimation/<driver>.R <label> <panel.csv|.parquet> [recorded.json for the *_evcl drivers]`.
The label must equal the recorded file's stem (it is written into the JSON's `label` field, which the
comparison checks).

## The cell lists and the two R stacks

`analysis/run_all.sh` takes its cells from tab-separated lists in `config/r1/cells/`. Each row names
the cell (`label`), its `driver`, its panel (`frame`, under the data version's `frames/`), the recorded
estimate an `_evcl` driver checks itself against (`ref`), the recorded file it is compared with
(`out_name`) and the R stack it needs (`stack`):

| list | data version | cells |
|---|---|---|
| `M.tsv` + `M_evcl.tsv` | the report (`data/report/`) | 27: 23 `rmac`, 4 `rcloud` |
| `oct29.tsv` | October 2026 (`data/frames/`) | 29: 25 `rmac`, 4 `rcloud` |
| `fig4_M.tsv` | the report | the samples behind Figure 4's counts (`analysis/robustness/figure4/run_save_sample.R`) |

- **`rmac`**, the default stack: R 4.5.1 with `DIDmultiplegtDYN` 2.3.3 (`setup/renv.lock`,
  `setup/R_VERSIONS.txt`). Every `rmac` cell runs in the default run. Install with
  `Rscript setup/install_r.R`.
- **`rcloud`**, the second stack: R 4.6.1 with `DIDmultiplegtDYN` 2.4.0, `data.table` 1.18.6.1,
  `fixest` 0.14.2, `jsonlite` 2.0.0 and `polars` 1.10.0.9000 (`config/r1/expected_versions.txt`). The
  4 `rcloud` cells are Panel 3 for economics and chemistry, main and event-clustered. Their measured
  peaks are in the [cell resource table](../../data/report/custody/RESOURCES.md); allow additional
  memory for the operating system. The default run checks their custody records instead (below).

**Installing the second stack** (Linux x86_64; the report's runs used Ubuntu 24.04). Install R 4.6.1
(for example the Posit build under `/opt/R/4.6.1`). Then, from the repository root, install the build
tools, the system libraries in `config/r1/r_runtime_apt.txt` and the Rust toolchain. `polars` is built
from source at the commit the lockfile pins, which needs the toolchain `nightly-2026-02-19`; the R
build ignores the package's own `rust-toolchain.toml`, so set `RUSTUP_TOOLCHAIN` (as
`pipeline/aws/r1/build_env.sh` does):

```
sudo apt-get install -y build-essential curl cmake pkg-config perl \
  $(sed -e 's/#.*//' config/r1/r_runtime_apt.txt)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
export PATH="$HOME/.cargo/bin:$PATH"
rustup toolchain install nightly-2026-02-19 --profile minimal
export RUSTUP_TOOLCHAIN=nightly-2026-02-19 RGL_USE_NULL=TRUE
```

Then install `jsonlite` into a new library and run the stack installer, which installs the exact
versions from the dated package snapshot the report used:

```
LIB=/opt/sar-env/rlib-rcloud; SNAP=https://p3m.dev/cran/__linux__/noble/2026-09-22
mkdir -p "$LIB"
/opt/R/4.6.1/bin/Rscript --no-init-file -e "install.packages('jsonlite', lib='$LIB', repos='$SNAP')"
/opt/R/4.6.1/bin/Rscript --no-init-file pipeline/aws/r1/install_stack.R rcloud "$LIB" "$SNAP" "$PWD"
```

It exits 1 and prints `UNPINNABLE` for any package whose version does not match. Then:

```
export SAR_RSCRIPT_RCLOUD=/opt/R/4.6.1/bin/Rscript SAR_RLIB_RCLOUD=/opt/sar-env/rlib-rcloud
RUN_CLOUD_CELLS=1 bash analysis/run_all.sh
```

The run uses that `Rscript` and package library for the 4 cells, with the same thread settings as the
AWS runs (`R_DATATABLE_NUM_THREADS`, `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `POLARS_MAX_THREADS`).
Without the two variables it stops.

## The drivers

| driver | args | recorded estimates | specification |
|---|---|---|---|
| `run_p1.R` | `<label> frames/p1_frame_{econ,chemistry,math_stats}.csv` | `P1_econ_fnfix.json`, `P1_fnfix_chemistry.json`, `P1_fnfix_math_stats.json` | effects=6, placebo=4, cluster=person_id, group=person×event, y=log1p(fwci_frac), D=dose_topic×post, filter \|age_gap\|<=60; channels union/network/dept. The October version also has two economics sub-sample cells (`_old79`, `_new37`) |
| `run_p2.R` | `<label> frames/p2_becoming_{econ,chemistry,math_stats}.csv` | `P2_econ_fnfix.json`, `P2_fnfix_chemistry.json`, `P2_fnfix_math_stats.json` | effects=5, placebo=4, cluster=person_id, group=person×star-relation, D=post(0/1) |
| `run_p3.R` | `<label> frames/p3_slim_{econ,chemistry,math_stats}.parquet [frac]` | `P3_econ_fnfix.json`, `P3_fnfix_chemistry.json`, `P3_fnfix_math_stats.json` | effects=5, placebo=4, cluster=grp (pair×event, the estimator's default), group=pair×event, D=post(0/1) |
| `run_p1_evcl.R` | `<label> frames/p1_frame_<field>.csv <recorded P1 cell>` | `P1evcl_{econ,chemistry,math_stats}.json` | `run_p1.R` with standard errors clustered by event (event_num) instead of person; checks that its point estimates equal the recorded person-clustered cell (only the SE differs) |
| `run_p2_evcl.R` | `<label> frames/p2_becoming_<field>.csv <recorded P2 cell>` | `P2evcl_{econ,chemistry,math_stats}.json` | `run_p2.R` clustered by event, checked the same way |
| `run_p3_evcl.R` | `<label> frames/p3_slim_ev_<field>.parquet [<recorded P3 cell>]` | `P3evcl_{econ,chemistry,math_stats}.json` | `run_p3.R` with an event cluster on top of the pair×event grouping, checked the same way |
| `run_p3_tp.R` | `<label> frames/p3_afar[_pos\|_med]_<field>.parquet` | `P3lb_<field>_A_far.json`, `P3pos_<field>_A_far.json`, `P3med_<field>_A_far.json` | Panel 3 on pairs of same-topic incumbents who were both outside the star's two-hop coauthor network before the arrival; `pos` (dose above zero) is the report's Panel 3, `med` (dose at or above the median) and `lb` are comparison cells. Reports pair-cluster and event-cluster SEs in one JSON. Run with the label `P3cut_<pos\|med>_<field>`; `analysis/run_all.sh` renames the output to the recorded file name |

**`run_p3_tp.R` provenance.** The driver is the version that produced the recorded `P3lb_*` files.
A later copy in the author's tree adds JSON keys (`status`, `p_joint_placebo`, `placebos`,
`n_event_clusters`) that the recorded files do not have; it was not used.

## The large cells: custody instead of a re-run

`run_p3.R` and `run_p3_evcl.R` on the economics and chemistry pair panels need far more memory than
a laptop has. Those 4 cells ran on AWS, and the default run checks their chain of custody with
`tools/verify_cloud_custody.py`:

1. the panels and the two drivers in this package are byte-identical (md5) to what the cells ran on;
2. the results fetched back from those runs equal the recorded estimates exactly (`compare_json`).

| data version | custody records | check |
|---|---|---|
| the report | `data/report/custody/` | `tools/verify_cloud_custody.py --custody data/report/custody --spec data/report/custody/custody_r1.json` |
| October 2026 | `data/cal2026-10/cloud/` | `tools/verify_cloud_custody.py --custody data/cal2026-10/cloud` |
| August 2026 | `data/cal2026-08-28/cloud/` | `tools/verify_cloud_custody.py` (no `--custody`) |

Each prints `CUSTODY_OK`. **`run_p3.R` and `run_p3_evcl.R` are never edited**: the custody records
pin their bytes, so any change, even to a comment, breaks the check.

The earlier August 2026 runs of these cells, before the August event set was fixed, are kept in
`pipeline/aws/logs/p3_main_2026-08-16/` and `pipeline/aws/logs/p3_evcl_2026-08-16/` (payload
manifests, drivers, logs and results, pinned in `data/MANIFEST.sha256`). They are not checked
against the current data.
