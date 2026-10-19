# -*- coding: utf-8 -*-
"""N14: R1 jobs go only through pipeline/aws/r1/r1kit.py; the October launcher refuses them."""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
OCT = REPO / "pipeline" / "aws" / "cal2026-10"


def test_no_r1_file_names_the_october_launcher():
    files = [*sorted((REPO / "config" / "r1").rglob("*.json")), *sorted((REPO / "pipeline" / "aws" / "r1").iterdir())]
    hits = [f.relative_to(REPO).as_posix() for f in files if f.is_file() and "aws/cal2026-10/" in f.read_text(errors="replace")]
    assert hits == []


@pytest.mark.parametrize("payload_name, custody_name, extra", [
    ("p", "cal2026-10", ["--tag", "sar-r1-j0"]),                    # an R1 tag
    ("p", "cal2026-10r1", []),                                      # an R1 custody dir
    ("cal2026-10r1_payload", "cal2026-10", [])])                    # an R1 payload dir
def test_run_cloud_refuses_an_r1_job(tmp_path, payload_name, custody_name, extra):
    payload = tmp_path / payload_name
    payload.mkdir()
    custody = tmp_path / "data" / custody_name / "cloud"
    env = dict(os.environ, PATH="/usr/bin:/bin")                    # no aws anywhere
    r = subprocess.run(["bash", str(OCT / "run_cloud.sh"), "--payload", str(payload), "--custody", str(custody),
                        "--dry-run", *extra], env=env, capture_output=True, text=True)
    assert r.returncode == 64 and "R1 rule" in r.stderr
    assert not custody.exists()                                     # refused before any mkdir


def test_cloudkit_refuses_an_r1_custody_dir(tmp_path):
    r = subprocess.run([sys.executable, str(OCT / "cloudkit.py"), "record", "--custody",
                        str(tmp_path / "data" / "cal2026-10r1" / "cloud")], capture_output=True, text=True)
    assert r.returncode == 64 and "R1 rule" in r.stderr
