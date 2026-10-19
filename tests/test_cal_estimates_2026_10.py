# -*- coding: utf-8 -*-
"""cal2026-10 local estimation driver (pipeline/stars/caliber_2026-10/run_cal_estimates.py): the
inventory it runs and the frozen CONTROL run (data/cal2026-10/estimates_control_0828/), which must
reproduce the 2026-08-28 golds cell for cell before the driver is trusted on the October frames.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
DRIVER = REPO / "pipeline/stars/caliber_2026-10/run_cal_estimates.py"
CTL = REPO / "data/cal2026-10/estimates_control_0828"
EXPECTED = REPO / "analysis/expected"

_spec = importlib.util.spec_from_file_location("rce_2026_10", DRIVER)
rce = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(rce)   # type: ignore[union-attr]


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_inventory_is_the_0828_local_cells_plus_the_six_pos_med_cuts():
    names = [c.name for c in rce.LOCAL_CELLS]
    assert len(names) == len(set(names)) == 25
    cuts = {n for n in names if n.startswith(("P3pos_", "P3med_"))}
    assert cuts == {f"P3{s}_{f}_A_far" for s in ("pos", "med") for f in ("econ", "chemistry", "math_stats")}
    assert set(rce.R_LABEL) == cuts and all(v.startswith("P3cut_") for v in rce.R_LABEL.values())


def test_every_gold_the_driver_compares_against_exists():
    for c in rce.LOCAL_CELLS:
        assert rce.gold_0828(c.name).exists(), c.name                        # the 08-28 control reference
        assert (EXPECTED / f"{c.name}.json").exists(), c.name                # the October gold (promotion 2026-09-23)
    # the 08-28 alias `new37 -> new38` is stale (commit a22a27e renamed the gold) and must not survive
    assert "P1_econ_fnfix_new37" not in rce.FROZEN_NAME


@pytest.fixture(scope="module")
def report():
    p = CTL / "run_report.json"
    if not p.exists():
        pytest.skip("control run not frozen")
    return json.loads(p.read_text(encoding="utf-8"))


def test_control_run_reproduces_every_0828_gold(report):
    eq = report["equal_to_0828_gold"]
    assert eq and all(v == "EQUAL" for v in eq.values()), {k: v for k, v in eq.items() if v != "EQUAL"}
    assert len(eq) == 23
    assert set(report["skipped_cells_no_econ_pairs"]) == {"P3pos_econ_A_far", "P3med_econ_A_far"}
    assert report["determinism"]["compare"] == "EQUAL"
    assert all(r["status"] == "OK" for r in report["cells"])


def test_control_cell_files_equal_their_golds_byte_for_byte_on_content(report):
    from analysis.lib.compare_json import compare
    for name in report["equal_to_0828_gold"]:
        got = json.loads((CTL / f"{name}.json").read_text(encoding="utf-8"))
        exp = json.loads(rce.gold_0828(name).read_text(encoding="utf-8"))   # the frozen 08-28 run, not analysis/expected (October since the promotion)
        assert not compare(got, exp), name


def test_cal_manifest_covers_the_control_files(report):
    man = {ln.split("  ", 1)[1].strip(): ln.split("  ", 1)[0] for ln in (REPO / "data/cal2026-10/MANIFEST.sha256").read_text().splitlines() if ln.strip()}
    for p in CTL.iterdir():
        rel = p.relative_to(REPO).as_posix()
        assert rel in man and man[rel] == _sha(p), rel
