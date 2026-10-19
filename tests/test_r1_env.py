# -*- coding: utf-8 -*-
"""V3-ENV: expected versions, versions_check (fake R/TeX binaries), boot restore rendering, build_env guards."""
from __future__ import annotations

import json
import os
import pathlib
import re
import stat
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
KIT = REPO / "pipeline" / "aws" / "r1"
sys.path.insert(0, str(KIT))
import r1kit            # noqa: E402
import versions_check as vc   # noqa: E402

EXP = (REPO / "config" / "r1" / "expected_versions.txt").read_text(encoding="utf-8")
PINS = {l: {"key": f"r1/env/{l}-{'0' * 16}.tar.gz", "sha256": "e" * 64, "bytes": 1} for l in r1kit.ENV_LAYERS}


def _rows(layer):
    return {n: v for lay, n, v in vc.parse_expected(EXP) if lay == layer}


def test_rmac_rows_equal_r_versions_txt():
    want = dict(ln.split("==", 1) for ln in (REPO / "setup" / "R_VERSIONS.txt").read_text().splitlines() if "==" in ln)
    rmac = _rows("rmac")
    assert rmac.pop("R") == re.search(r"R version (\S+)", want.pop("R")).group(1)
    for k in ("remotes", "renv"):
        want.pop(k)
    assert rmac == want


def test_rcloud_rows_equal_the_october_cloud_stack_except_polars():
    line = (REPO / "data" / "cal2026-10" / "cloud" / "fetch" / "versions.txt").read_text().splitlines()[0].split()
    oct_ = dict(zip(line[0::2], line[1::2]))
    rc = _rows("rcloud")
    assert oct_.pop("polars") == "1.9000.9000.9000" and rc.pop("polars") == _rows("rmac")["polars"]
    assert rc == oct_


def _exe(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _fake_opt(tmp_path, r_out, tex_banner):
    opt = tmp_path / "opt"
    for ver in ("4.5.1", "4.6.1"):
        _exe(opt / "R" / ver / "bin" / "Rscript", f"cat <<'EOF'\n{r_out[ver]}\nEOF\n")
    tex = opt / "texlive" / "2025" / "bin" / "x86_64-linux"
    _exe(tex / "pdflatex", f"echo '{tex_banner}'\n")
    _exe(tex / "kpsewhich", 'case "$1" in nosuch.sty) exit 1;; *) echo "/opt/x/$1";; esac\n')
    return opt


R_OK = {"4.5.1": "R 4.5.1\nDIDmultiplegtDYN 2.3.3\npolars 1.10.0.9000\ndata.table 1.17.8\njsonlite 2.0.0\nfixest 0.14.0\nyaml 2.3.10",
        "4.6.1": "R 4.6.1\nDIDmultiplegtDYN 2.4.0\npolars 1.10.0.9000\ndata.table 1.18.6.1\njsonlite 2.0.0\nfixest 0.14.2"}
TEX_OK = "pdfTeX 3.141592653-2.6-1.40.28 (TeX Live 2025)"


def _check(tmp_path, opt, layers, exp=EXP):
    e = tmp_path / "exp.txt"
    e.write_text(exp)
    return vc.main(["--expected", str(e), "--repo", str(REPO), "--layers", layers, "--out", str(tmp_path / "v.txt"),
                    "--opt", str(opt)])


def test_versions_check_passes_on_the_pinned_stacks(tmp_path):
    assert _check(tmp_path, _fake_opt(tmp_path, R_OK, TEX_OK), "rmac,rcloud,tex") == 0
    assert "rcloud DIDmultiplegtDYN 2.4.0" in (tmp_path / "v.txt").read_text()


def test_versions_check_names_an_r_drift_and_a_tex_drift(tmp_path, capsys):
    bad = dict(R_OK, **{"4.6.1": R_OK["4.6.1"].replace("2.4.0", "2.4.1")})
    opt = _fake_opt(tmp_path, bad, "pdfTeX 3.141592653-2.6-1.40.29 (TeX Live 2026)")
    assert _check(tmp_path, opt, "rmac,rcloud,tex") == 1
    out = capsys.readouterr().out
    assert "DRIFT rcloud DIDmultiplegtDYN want 2.4.0 got 2.4.1" in out and "DRIFT tex pdftex" in out
    assert "DRIFT tex texlive want 2025 got 2026" in out and "DRIFT rmac" not in out


def test_versions_check_names_a_missing_style_file(tmp_path, capsys):
    exp = EXP.replace("hyperref", "hyperref nosuch")
    assert _check(tmp_path, _fake_opt(tmp_path, R_OK, TEX_OK), "tex", exp) == 1
    assert "DRIFT tex sty want nosuch got MISSING" in capsys.readouterr().out


def test_versions_check_reads_the_python_pins(tmp_path, capsys):
    import importlib.metadata as md
    req = tmp_path / "req.txt"
    req.write_text(f"pytest=={md.version('pytest')}\n    # via x\nyaml-not-a-pin\n")
    assert vc.check_py([("python", vc.platform.python_version()), ("requirements", str(req))], REPO) == []
    req.write_text("pytest==0.0.1\n")
    assert vc.check_py([("requirements", str(req))], REPO) == [("requirements", "pytest", "0.0.1", md.version("pytest"))]


def _ud(job, **kw):
    return r1kit.render_userdata(job, job_id="t-unit-01", commit="c" * 40, repo_dir="/srv/My Dir /Research/repo",
                                 bucket="fake-bucket", base_sha="a" * 64, deadline_epoch=1_800_000_000, **kw)


def test_env_layers_restore_from_pinned_tarballs_before_the_steps(tmp_path):
    job = dict(r1kit.load_job("test"), env_layers=["py", "rmac", "tex"])
    text = _ud(job, env_pins=PINS, expected_text=EXP)
    for layer in ("py", "rmac", "tex"):
        assert f'"$B/{PINS[layer]["key"]}"' in text and f'{"e" * 64}  /work/env/{layer}.tar.gz' in text
    assert "apt-get install -y -q /opt/sar-env/rmac/r-4.5.1_1_amd64.deb" in text
    assert text.index("versions_check.py") < text.index("st RUN") and "VERSIONS_DRIFT" in text
    assert "pip install" not in text
    f = tmp_path / "ud.sh"
    f.write_text(text)
    assert subprocess.run(["bash", "-n", str(f)]).returncode == 0
    assert len(text.encode()) < r1kit.MAX_USERDATA_BYTES


def test_layout_is_exported_to_the_steps():
    job = dict(r1kit.load_job("test"), env_layers=["py", "rmac", "rcloud", "tex"],
               env={"SAR_PATHS_CONFIG": "$REPO_DIR/config/r1/paths_aws.yaml"})
    s = r1kit.render_steps_script(job, job_id="t-unit-01", commit="c" * 40, repo_dir="/srv/a b", bucket="fake-bucket",
                                  layout=r1kit.env_layout(EXP))
    assert "SAR_RSCRIPT_RCLOUD=/opt/R/4.6.1/bin/Rscript" in s and "SAR_RLIB_RMAC=/opt/sar-env/rlib-rmac" in s
    assert "R_PROFILE_USER=/dev/null" in s and "/opt/texlive/2025/bin/x86_64-linux" in s
    assert "export SAR_PATHS_CONFIG='/srv/a b/config/r1/paths_aws.yaml'" in s


def test_a_layer_without_a_pin_or_without_py_is_refused():
    job = dict(r1kit.load_job("test"), env_layers=["py", "tex"])
    with pytest.raises(r1kit.KitError, match="no pin"):
        _ud(job, env_pins={"py": PINS["py"]}, expected_text=EXP)
    with pytest.raises(r1kit.KitError, match="py"):
        r1kit.check_env_layers(["rmac"])


def test_jobs_without_layers_keep_the_pip_venv():
    text = _ud(dict(r1kit.load_job("test"), env_layers=[]))
    assert 'pip install -q -r "$REPO_DIR/setup/requirements.txt"' in text and "versions_check" not in text


def test_data_and_legacy_are_read_only_on_the_instance():
    text = _ud(dict(r1kit.load_job("test"), env_layers=[]))
    assert "chmod -R a-w" in text and "/data/legacy" in text


def test_build_env_refuses_off_aws_and_outside_r1_env(tmp_path):
    sh = str(KIT / "build_env.sh")
    env = {k: v for k, v in os.environ.items() if k != "SAR_HOST"}
    r = subprocess.run(["bash", sh, "--layers", "py", "--repo", str(REPO), "--prefix", "s3://b/r1/env/", "--out", str(tmp_path)],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 2 and "R1 rule" in r.stderr
    r = subprocess.run(["bash", sh, "--layers", "py", "--repo", str(REPO), "--prefix", "s3://b/u1/", "--out", str(tmp_path)],
                       env=dict(env, SAR_HOST="ec2-r1-test"), capture_output=True, text=True)
    assert r.returncode == 2 and "only under" in r.stderr
    assert subprocess.run(["bash", "-n", sh]).returncode == 0


def test_envbuild_runs_as_root():
    """envbuild-01 (2026-10-13): steps run as user ubuntu, and apt-get / /opt need root -> rc 100 at the first apt."""
    step = r1kit.load_job("envbuild")["steps"][0]
    assert step.startswith("sudo -E bash /work/build_env.sh ")


def test_r_layers_install_the_shared_runtime_libraries_at_boot():
    """envbuild-02 (2026-10-13): the P3M rgl binary needs libGLU at load time; every instance that restores an
    R stack installs the same runtime list the builder used (config/r1/r_runtime_apt.txt)."""
    pkgs = [l.split("#")[0].strip() for l in (REPO / "config" / "r1" / "r_runtime_apt.txt").read_text().splitlines()]
    assert "libglu1-mesa-dev" in pkgs and "libicu-dev" in pkgs
    text = _ud(dict(r1kit.load_job("test"), env_layers=["py", "rmac"]), env_pins=PINS, expected_text=EXP)
    assert "config/r1/r_runtime_apt.txt" in text
    assert text.index("r_runtime_apt.txt") < text.index("/opt/sar-env/rmac/r-4.5.1_1_amd64.deb")
    assert "r_runtime_apt.txt" not in _ud(dict(r1kit.load_job("test"), env_layers=["py", "tex"]), env_pins=PINS, expected_text=EXP)
    assert "r_runtime_apt.txt" in (KIT / "build_env.sh").read_text()


def test_polars_builds_with_the_toolchain_its_commit_pins():
    """envbuild-03 (2026-10-13): stable rustc 1.99 cannot compile the locked ethnum 1.5.2; r-polars 916aff7 pins
    nightly-2026-02-19 in src/rust/rust-toolchain.toml, and the R build ignored it (default toolchain)."""
    sh = (KIT / "build_env.sh").read_text()
    assert 'RUST_TOOLCHAIN="nightly-2026-02-19"' in sh and 'RUSTUP_TOOLCHAIN="$RUST_TOOLCHAIN"' in sh
    assert "RUSTUP_HOME=/opt/rust/rustup" in sh and "CARGO_HOME=/opt/rust/cargo" in sh


def test_requirement_markers_are_evaluated_not_reported_missing(tmp_path):
    """Review (P3b, critical): colorama/tzdata are Windows-only pins in setup/requirements.txt."""
    req = tmp_path / "req.txt"
    req.write_text("colorama==0.4.6 ; sys_platform == 'win32'\nnot-installed-anywhere==1.0 ; sys_platform == 'win32'\n")
    assert vc.check_py([("requirements", str(req))], REPO) == []
    assert vc.check_py([("requirements", "setup/requirements.txt")], REPO) == []     # the runner's venv is built from it


PIN_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([0-9][0-9A-Za-z.!+-]*)((?: --hash=sha256:[0-9a-f]{64})+)$")


def _sh_block(sh, name):
    m = re.search(rf"^{name}\(\) \{{[^\n]*\n(.*?)^\}}", sh, re.M | re.S)
    assert m, f"build_env.sh has no {name}() block"
    return m.group(1)


def test_py_layer_carries_the_final_requirements():
    """V3-FINAL.a: PyMuPDF (`fitz`) for count_words.py, check_draft_text.py and red_diff verify comes from a hashed
    extra requirements file inside the py layer, installed after setup/requirements.txt and checked at boot by its
    own expected_versions row (setup/requirements.txt and uv.lock stay the replication package's lock)."""
    sh = (KIT / "build_env.sh").read_text(encoding="utf-8")
    body = _sh_block(sh, "build_py")
    base = body.find('pip install -q -r "$REPO/setup/requirements.txt"')
    final = body.find('/work/venv/bin/pip install -q --require-hashes -r "$REPO/config/r1/requirements_final.txt"')
    pack = body.find("pack py work/venv")
    assert -1 < base < final < pack, (base, final, pack)
    rows = vc.parse_expected(EXP)
    assert ("py", "requirements", "config/r1/requirements_final.txt") in rows
    assert ("py", "requirements", "setup/requirements.txt") in rows
    text = (REPO / "config" / "r1" / "requirements_final.txt").read_text(encoding="utf-8")
    lines = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    bad = [l for l in lines if not PIN_LINE.match(l)]
    assert lines and bad == [], f"every line must be 'name==ver --hash=sha256:<64 hex>': {bad}"
    assert "pymupdf" in {PIN_LINE.match(l).group(1).lower() for l in lines}
    smoke = _sh_block(sh, "smoke")
    assert "smoke_pymupdf" in smoke and "import fitz;print(fitz.VersionBind)" in smoke


def test_versions_check_reads_a_hashed_requirement_line(tmp_path):
    """The hashed form of requirements_final.txt parses as name + version (the hash is not part of the version)."""
    import importlib.metadata as md
    req = tmp_path / "req.txt"
    ver = md.version("pytest")
    req.write_text(f"# comment\npytest=={ver} --hash=sha256:{'0' * 64}\n")
    assert vc.check_py([("requirements", str(req))], REPO) == []
    req.write_text(f"pytest==0.0.1 --hash=sha256:{'0' * 64}\n")
    assert vc.check_py([("requirements", str(req))], REPO) == [("requirements", "pytest", "0.0.1", ver)]


def test_envbuild_py_rebuilds_only_the_py_layer():
    """envbuild_py = envbuild.json with '--layers py' only, so the R and TeX pins stay as they are."""
    full, py = r1kit.load_job("envbuild"), r1kit.load_job("envbuild_py")
    assert py["kind"] == "envbuild_py" and len(py["steps"]) == 1
    assert py["steps"][0] == full["steps"][0].replace("--layers py,rmac,rcloud,tex ", "--layers py ")
    assert "--layers py " in py["steps"][0] and "rmac" not in py["steps"][0]
    assert {k: v for k, v in py.items() if k not in ("kind", "steps")} == \
           {k: v for k, v in full.items() if k not in ("kind", "steps")}
