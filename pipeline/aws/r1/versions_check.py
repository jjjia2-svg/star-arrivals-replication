#!/usr/bin/env python3
"""R1 V3-ENV boot check: the restored environment layers carry exactly the pinned versions (rulings R6-R8).

  versions_check.py --expected config/r1/expected_versions.txt --repo DIR --layers py,rmac,rcloud,tex --out FILE [--opt /opt]

py: the python version and every `name==version` line of setup/requirements.txt; rmac / rcloud: R and each
pinned package, read with that stack's Rscript and library; tex: pdfTeX and TeX Live year from `pdflatex
--version`, and every style file of the `sty` row through kpsewhich. Writes every observed `layer name version`
line to --out, prints `DRIFT <layer> <name> want <v> got <g>` per mismatch and returns 1, else VERSIONS_OK.
Runs only on an R1 instance ($SAR_HOST) unless --opt points away from /opt (tests use fake binaries).
"""
from __future__ import annotations

import argparse
import importlib.metadata as md
import os
import pathlib
import platform
import re
import subprocess
import sys

HOSTS = ("ec2-r1-test", "ec2-r1")
R_EXPR = ('cat("R", as.character(getRversion()), "\\n"); for (p in commandArgs(TRUE)) cat(p, '
          'tryCatch(as.character(packageVersion(p)), error=function(e) "MISSING"), "\\n")')


def parse_expected(text) -> list:
    rows = []
    for line in str(text).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        line = re.sub(r"\s+#.*$", "", line)
        parts = line.split("\t")
        if len(parts) >= 3:
            rows.append((parts[0].strip(), parts[1].strip(), parts[2].strip()))
    return rows


def _marker_true(marker) -> bool:
    """A pip environment marker, with packaging (pinned in the py layer) or, without it, the sys_platform /
    platform_system / os_name forms setup/requirements.txt uses."""
    try:
        from packaging.markers import Marker  # noqa: PLC0415
        return Marker(marker).evaluate()
    except ImportError:
        env = {"sys_platform": sys.platform, "platform_system": platform.system(), "os_name": os.name}
        terms = re.findall(r"(\w+)\s*(==|!=)\s*['\"]([^'\"]*)['\"]", marker)
        vals = [(env.get(k, "") == v) == (op == "==") for k, op, v in terms]
        return any(vals) if " or " in marker else all(vals)


def check_py(rows, repo) -> list:
    drift = []
    for name, want in rows:
        if name == "python":
            got = platform.python_version()
            if got != want:
                drift.append(("python", "python", want, got))
        elif name == "requirements":
            req = pathlib.Path(want)
            req = req if req.is_absolute() else pathlib.Path(repo) / req
            for line in req.read_text(encoding="utf-8").splitlines():
                if not line.strip() or line.startswith(("#", " ", "\t")) or "==" not in line:
                    continue
                spec, _, marker = line.partition(";")
                if marker.strip() and not _marker_true(marker.strip()):
                    continue                                  # e.g. colorama ; sys_platform == 'win32'
                pkg, ver = spec.split("==", 1)
                pkg, ver = re.sub(r"\[.*\]", "", pkg).strip(), ver.split()[0].strip()
                try:
                    got = md.version(pkg)
                except md.PackageNotFoundError:
                    got = "MISSING"
                if got != ver:
                    drift.append(("requirements", pkg, ver, got))
    return drift


def check_r(layer, rows, *, opt, run=subprocess.run):
    want = dict(rows)
    rscript = pathlib.Path(opt) / "R" / want["R"] / "bin" / "Rscript"
    pkgs = [n for n in want if n != "R"]
    env = dict(os.environ, R_LIBS=str(pathlib.Path(opt) / "sar-env" / f"rlib-{layer}"), R_PROFILE_USER="/dev/null")
    try:
        out = run([str(rscript), "--no-init-file", "-e", R_EXPR, "--args", *pkgs], capture_output=True, text=True, env=env).stdout
    except OSError:
        out = ""
    got = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            got[parts[0]] = parts[1]
    drift = [(n, v, got.get(n, "MISSING")) for n, v in want.items() if got.get(n, "MISSING") != v]
    return got, drift


def check_tex(rows, *, opt, run=subprocess.run):
    want = dict(rows)
    tbin = pathlib.Path(opt) / "texlive" / want.get("texlive", "2025") / "bin" / "x86_64-linux"
    got, drift = {}, []
    try:
        first = (run([str(tbin / "pdflatex"), "--version"], capture_output=True, text=True).stdout.splitlines() or [""])[0]
    except OSError:
        first = ""
    m = re.search(r"pdfTeX 3\.141592653-2\.6-(\S+)", first)
    got["pdftex"] = m.group(1) if m else "MISSING"
    m = re.search(r"TeX Live (\d{4})", first)
    got["texlive"] = m.group(1) if m else "MISSING"
    for name in ("texlive", "pdftex"):
        if name in want and got[name] != want[name]:
            drift.append((name, want[name], got[name]))
    for sty in want.get("sty", "").split():
        try:
            path = run([str(tbin / "kpsewhich"), f"{sty}.sty"], capture_output=True, text=True).stdout.strip()
        except OSError:
            path = ""
        got[f"sty:{sty}"] = path or "MISSING"
        if not path:
            drift.append(("sty", sty, "MISSING"))
    return got, drift


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 environment version check")
    ap.add_argument("--expected", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--layers", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--opt", default="/opt")
    a = ap.parse_args(argv)
    if os.environ.get("SAR_HOST", "").strip() not in HOSTS and a.opt == "/opt":
        raise SystemExit("R1 rule: versions_check.py runs only on an R1 instance ($SAR_HOST)")
    exp = parse_expected(pathlib.Path(a.expected).read_text(encoding="utf-8"))
    observed, drifts = [], []
    for layer in [x for x in a.layers.split(",") if x]:
        rows = [(n, v) for lay, n, v in exp if lay == layer]
        if layer == "py":
            for name, pkg, want, got in check_py(rows, a.repo):
                drifts.append((layer, pkg if name == "requirements" else name, want, got))
            observed.append(f"py python {platform.python_version()}")
        elif layer in ("rmac", "rcloud"):
            got, drift = check_r(layer, rows, opt=a.opt)
            observed += [f"{layer} {n} {v}" for n, v in sorted(got.items())]
            drifts += [(layer, n, w, g) for n, w, g in drift]
        elif layer == "tex":
            got, drift = check_tex(rows, opt=a.opt)
            observed += [f"tex {n} {v}" for n, v in sorted(got.items())]
            drifts += [("tex", n, w, g) for n, w, g in drift]
        else:
            raise SystemExit(f"unknown layer {layer}")
    pathlib.Path(a.out).write_text("\n".join(observed) + "\n", encoding="utf-8")
    for layer, name, want, got in drifts:
        print(f"DRIFT {layer} {name} want {want} got {got}")
    if drifts:
        return 1
    print("VERSIONS_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
