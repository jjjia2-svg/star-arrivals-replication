# Environment setup

**Python**: run `bash setup/install_py.sh` (creates `setup/.venv/` from `setup/uv.lock`, pinning `duckdb==1.5.4` and `pyarrow==24.0.0`; then `source setup/.venv/bin/activate`). `setup/requirements.txt` is exported from the same lock for tools that want a plain pip file.

**R**: the PRIMARY install path is `Rscript setup/install_r.R` — it installs the packages listed in `setup/R_VERSIONS.txt` (data.table/jsonlite/fixest/yaml at their recorded CRAN versions, polars from r-universe, and DIDmultiplegtDYN 2.3.3 from the vendored tarball at `setup/vendor/DIDmultiplegtDYN_2.3.3.tar.gz`, sha256 `7de10aca30867f28553c2d428d0fe29f42ecbb23db488f018c2a39ce3dcd0041`, since CRAN now ships 2.4.0). `renv::restore(lockfile = "setup/renv.lock")` is a secondary alternative — see the caveat below on where it actually fetches DIDmultiplegtDYN from.

Versions in R_VERSIONS.txt and requirements.txt were measured on the machine that produced the results (macOS arm64, 2026-08-23); cloud instances (P3 main, U1) are documented in pipeline/aws/ (M3). The local DIDmultiplegtDYN 2.3.3 binary was built under R 4.5.2 and runs under R 4.5.1 (every driver log prints that warning; all cells reproduce EQUAL).

**Note on DIDmultiplegtDYN and `renv::restore`**: `setup/renv.lock` records DIDmultiplegtDYN 2.3.3 with `Source: Repository` / `Repository: CRAN`, because that is what the vendored tarball's own embedded DESCRIPTION says — the lockfile has no way to record "installed from setup/vendor/". So `renv::restore()` does not use the vendored tarball at all: it fetches DIDmultiplegtDYN 2.3.3 from CRAN's Archive (https://cran.r-project.org/src/contrib/Archive/DIDmultiplegtDYN/) rather than from the vendored tarball; if that archive entry ever disappears, install from `setup/vendor/` instead (`install_r.R` does this). Not verified end-to-end on a clean machine (2026-08-23).

**Note on polars (R)**: polars is not on CRAN; the recorded version `1.10.0.9000` is a development build installed from r-universe/multiverse (`https://community.r-multiverse.org`, `https://rpolars.r-universe.dev`). `renv::snapshot` recorded it with `Source: GitHub` and a `RemoteSha`/`RemoteRepo`/`RemoteUsername` (pola-rs/r-polars) rather than a `Repository` field, because r-universe mirrors the GitHub source — there is no CRAN-style repository to point at. `renv::restore` will attempt to reinstall from that GitHub remote; if that fails offline, install polars manually from r-universe as `install_r.R` does and re-check the version against R_VERSIONS.txt.

**Note on renv/settings.json and external libraries**: the R packages on this Mac live outside renv's private project library (system framework library + user library), and renv only sees them when they are listed as external libraries — that is what let `renv::snapshot(type="explicit")` record DIDmultiplegtDYN/polars/data.table/jsonlite/fixest/yaml. Until 2026-08-23 `renv/settings.json` hard-coded those two absolute machine paths; it now stores `"external.libraries": []` and `.Rprofile` instead sets `options(renv.config.external.libraries = .libPaths())` before `renv/activate.R`, i.e. whatever libraries the machine already has. Nothing machine-specific is tracked, and on a machine with an empty project library the packages are still found. `renv::restore` installs into the project's own private library regardless (deferred to M5, see below).

**Note on where the lockfile lives**: `setup/renv.lock` is not at the repo root, so `renv::status()` and `renv::restore()` must be given `lockfile = "setup/renv.lock"` explicitly; without it renv reports that the project contains no lockfile.

**Which interpreter to use**: every command in this repository's docs means `setup/.venv/bin/python`
(or `python3` after `source setup/.venv/bin/activate`). This matters: until 2026-08-26 the locked
environment and whatever `python3` happened to be on the author's PATH resolved to *different*
package versions, and only the ambient one passed the whole suite — see the note below.

**Lock exercise status**: `renv::restore()` from `setup/renv.lock` has not been exercised yet
(planned for the M5 clean-environment rerun). The Python lock was re-exercised on **2026-08-26**
(`uv sync --frozen`, then root pytest + `pipeline/units` + `analysis/run_all.sh` from
`setup/.venv`). The earlier "exercised on 2026-08-23" claim was **stale and, for the tree as it
then stood, false** — M3 Task 7's review found that no green result in this repository had ever
been produced by the locked environment:

* `pyproject.toml` declared `pandas>=2.2`, a floor, which resolved to **3.0.5**. The frozen roster
  parquets were written by pandas **3.0.2** and carry `"pandas_version": "3.0.2"` in their own
  metadata, so from `setup/.venv` two byte-identity assertions in
  `tests/test_pipeline_rebuild.py` failed on exactly two bytes (offsets 77,129 and 80,433) while
  the content gate stayed EQUAL.
* `rapidfuzz` was in no lock file at all, yet the ported U4 preflight gate hard-requires it
  (`pipeline/units/u0_foundation/src/common/preflight.py`, check ④, "error if missing, no downgrade"), so
  `uv sync --frozen` produced an environment in which 54 of the 2,001 ported unit tests exited
  `ENVIRONMENT_GATE_FAIL=30`.

Both are now pinned (`pandas==3.0.2`, `rapidfuzz==3.14.5`) and the lock re-exported. Nothing else
in the resolution moved.
