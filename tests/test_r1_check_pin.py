# -*- coding: utf-8 -*-
"""pipeline/aws/r1/check_pin.py - F1: a rebuilt file must equal its October pin (sha, bytes, one link)."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import check_pin as cp   # noqa: E402


@pytest.fixture
def pinned(tmp_path, monkeypatch):
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    f = tmp_path / "pairs_unified.csv"
    f.write_bytes(b"a,b\n1,2\n")
    rep = tmp_path / "report.json"
    rep.write_text(json.dumps({"october": {"pairs_unified": {"sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
                                                              "bytes": f.stat().st_size}}}))
    return f, rep


def _check(tmp_path, f, rep):
    out = tmp_path / "out"
    rc = cp.main(["--file", str(f), "--report", str(rep), "--key", "october.pairs_unified", "--out", str(out)])
    return rc, json.loads((out / "pin_check.json").read_text())["verdict"]


def test_the_pinned_file_matches(tmp_path, pinned):
    assert _check(tmp_path, *pinned) == (0, "MATCH")


def test_a_wrong_sha_is_refused(tmp_path, pinned):
    f, rep = pinned
    f.write_bytes(b"a,b\n1,3\n")
    assert _check(tmp_path, f, rep) == (1, "SHA_DIFF")


def test_a_hard_linked_or_symlinked_file_is_refused(tmp_path, pinned):
    f, rep = pinned
    os.link(f, tmp_path / "twin.csv")
    assert _check(tmp_path, f, rep) == (1, "HARDLINK")
    (tmp_path / "twin.csv").unlink()
    (tmp_path / "ln.csv").symlink_to(f)
    assert _check(tmp_path, tmp_path / "ln.csv", rep) == (1, "SYMLINK")


def test_the_real_report_carries_the_october_pin():
    rep = json.loads((REPO / "data" / "cal2026-10" / "frames_econ" / "build_report_econ920_2026-10.json").read_text())
    pin = rep["october"]["pairs_unified"]
    assert pin["bytes"] == 236705320 and pin["sha256"].startswith("e5c98b84")


def test_j0_checks_the_pin_right_after_the_econ_build():
    t = json.loads((REPO / "config" / "r1" / "stages" / "j0.json").read_text())
    st = {s["name"]: s for s in t["stages"]}["pairs_pin"]
    assert st["needs"] == ["frames_econ920"] and st["script"] == "pipeline/aws/r1/check_pin.py"
    assert "output/cal_intermediates/cal2026-10/pairs_unified.csv" in st["cmd"] and "october.pairs_unified" in st["cmd"]
