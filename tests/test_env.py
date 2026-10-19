import pathlib, re, subprocess
REPO = pathlib.Path(__file__).resolve().parents[1]

def test_python_pins():
    req = (REPO / "setup/requirements.txt").read_text()
    assert "duckdb==1.5.4" in req and "pyarrow==24.0.0" in req
    assert (REPO / "setup/uv.lock").exists() and (REPO / "setup/pyproject.toml").exists()

def test_r_versions_recorded_and_match_installed():
    """The RECORD is always checked; the INSTALLED versions only where R is installed.

    It is two claims — the pins are written down (a property of this repository, always checkable)
    and this machine matches them (a property of the machine). One of the pins,
    `polars==1.10.0.9000`, is an r-universe DEVELOPMENT build that may no longer be obtainable; see
    setup/README.md.
    """
    import shutil as _sh
    import pytest
    txt = (REPO / "setup/R_VERSIONS.txt").read_text()
    want = dict(l.split("==") for l in txt.splitlines() if "==" in l)
    for pkg in ["DIDmultiplegtDYN", "polars", "data.table", "jsonlite", "fixest", "yaml"]:
        assert pkg in want, f"{pkg} has no recorded version in setup/R_VERSIONS.txt"
    assert want["DIDmultiplegtDYN"] == "2.3.3"
    if _sh.which("Rscript") is None:
        pytest.skip("Rscript is not on PATH; the recorded pins are checked, the installed ones "
                    "cannot be. `Rscript setup/install_r.R` installs them.")
    # This repository uses renv, so `Rscript` run from here resolves a PROJECT-LOCAL library. On a
    # fresh clone that library is not restored and the autoloader is still bootstrapping it, so
    # `packageVersion` answers for a half-built library — measured: a hard failure on the first run
    # of the suite and a clean skip on the second. Probe once: if the anchor package cannot be
    # resolved at all, the library is not restored, which is a missing input rather than a version
    # mismatch. On a machine where it IS restored, every pin is asserted exactly as before.
    probe = subprocess.run(["Rscript", "-e",
                            'cat(as.character(packageVersion("DIDmultiplegtDYN")))'],
                           capture_output=True, text=True, cwd=REPO)
    if probe.returncode != 0 or not probe.stdout.strip():
        pytest.skip("the R library for this project is not restored, so `Rscript` cannot report the "
                    "package versions. Run `Rscript setup/install_r.R` (or "
                    "`renv::restore(lockfile='setup/renv.lock')`). The recorded pins ARE checked.")
    mismatched = {}
    for pkg in ["DIDmultiplegtDYN", "polars", "data.table", "jsonlite", "fixest", "yaml"]:
        ver = want[pkg]
        got = subprocess.run(["Rscript", "-e", f'cat(as.character(packageVersion("{pkg}")))'],
                             capture_output=True, text=True).stdout.strip()
        if got != ver:
            mismatched[pkg] = (got or "NOT INSTALLED", ver)
    if mismatched:
        missing = {k: v for k, v in mismatched.items() if v[0] == "NOT INSTALLED"}
        if missing and set(missing) == set(mismatched):
            pytest.skip(f"R is installed but these recorded packages are not: "
                        f"{sorted(missing)}. Run `Rscript setup/install_r.R`. "
                        f"(polars 1.10.0.9000 is an r-universe dev build and may be unobtainable — "
                        f"see setup/README.md.)")
        assert not mismatched, (
            f"installed R package versions differ from setup/R_VERSIONS.txt: {mismatched}. The "
            f"recorded versions are the ones that produced the results; an estimate produced with "
            f"a different DIDmultiplegtDYN is not a reproduction.")

def test_vendor_and_lock_present():
    assert (REPO / "setup/vendor/DIDmultiplegtDYN_2.3.3.tar.gz").stat().st_size > 100_000
    assert (REPO / "setup/renv.lock").exists()

