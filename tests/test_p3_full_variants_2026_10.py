# -*- coding: utf-8 -*-
"""analysis/robustness/threshold_p05/build_p3_full_variants.py — the D7 variants of the full Panel 3
pair panel. Pins the frozen 08-28 controls (all-events filter and one-bin dose both content-equal
to data/frames/p3_slim_<field>.parquet) and the shape of the October products."""
from __future__ import annotations

import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
V = REPO / "data/cal2026-10/frames_variants"
FIELDS = ("chemistry", "math_stats", "econ")


@pytest.mark.parametrize("field", FIELDS)
def test_control_0828_reproduces_the_frozen_slim(field):
    p = V / f"p3_full_variants_control_0828_{field}.json"
    if not p.exists():
        pytest.skip(f"{field}: control not frozen yet")
    r = json.loads(p.read_text(encoding="utf-8"))
    assert r["suffix"] == "" and r["dosebin"]["bins"] == 1
    assert r["control"]["p05_all_events_vs_frozen_slim"] is True
    assert r["control"]["dosebin_vs_frozen_slim"] is True
    assert r["p05_filter"]["rows_in"] == r["p05_filter"]["rows_out"]


@pytest.mark.parametrize("field", FIELDS)
def test_october_products_have_the_declared_shape(field):
    p = V / f"p3_full_variants_report_{field}.json"
    if not p.exists():
        pytest.skip(f"{field}: October variants not built yet")
    r = json.loads(p.read_text(encoding="utf-8"))
    p05 = {"econ": 79, "chemistry": 31, "math_stats": 22}[field]
    assert r["events_kept"] == p05 and r["p05_filter"]["events_out"] <= p05
    d = r["dosebin"]
    assert d["bins"] == 3 and len(d["cuts"]) == 2 and d["cuts"][0] < d["cuts"][1] and d["max_D"] == 3
    assert sum(d["pairs_by_bin"].values()) == d["pairs"]
    assert (V / d["file"]).exists() and (V / r["p05_slim"]["file"]).exists()
