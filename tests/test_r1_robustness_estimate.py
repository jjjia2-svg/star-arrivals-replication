# -*- coding: utf-8 -*-
"""Estimate-marked (big host, N5's launch): the REAL run_p1_variant.R failing on a toy Panel 1 frame flows
through run_units.py as ESTIMATE_FAILED, not as FAIL and not as OK (P3e F19, unit W1-ROB).

The toy frame has one event (one arrival cohort), no not-yet-treated relations and no observed output, so
every dCDH call fails inside the driver's tryCatch and the JSON carries channels.union.status FAILED with
rc 0 - the shape the paper prints as 'cannot be computed'.
"""
from __future__ import annotations

import csv
import json
import os
import pathlib
import sys

import pytest

pytestmark = pytest.mark.estimate

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import rob_jobs_r1 as rj   # noqa: E402
import run_units as ru     # noqa: E402

COLS = ["incumbent_person_id", "year", "star_person_id", "event_id", "treated", "post", "dose_coupling_baseline",
        "dose_topic", "dose_low_confidence", "age_gap", "fwci_frac", "pub_count", "fwci_frac_ex_star",
        "pub_count_ex_star", "fwci_mean", "fwci_mean_ex_star", "channel"]


def test_real_driver_failure_status_flows_through(tmp_path, monkeypatch):
    assert os.environ.get("SAR_RSCRIPT_RMAC"), "the big host must provide the rmac R stack (env layer)"
    monkeypatch.setenv("SAR_HOST", os.environ.get("SAR_HOST") or "ec2-r1-test")
    frame = tmp_path / "p1_frame_toy.csv"
    with open(frame, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(COLS)
        for i in range(3):
            for y in range(2010, 2017):
                post = "true" if y >= 2013 else "false"
                w.writerow([f"P_{i}", y, "P_S", "S:2013", "true", post, 0.0, 0.5, "false", 5.0, "", 0, "", 0, "", "",
                            "both"])
    units = [rj.Unit("cells", "TOYFAIL", "p1", "p1_frame_toy.csv", 2, 1,
                     f"Rscript analysis/robustness/battery_2026-08-29/run_p1_variant.R full TOYFAIL {frame} none",
                     "toy", "")]
    tsv = tmp_path / "units.tsv"
    sha = rj.write_tsv(units, tsv)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"joblist_sha256": sha, "verdict": "OK",
                                "groups": [{"group": "cells", "threads": 2, "par": 1, "pred_gib": 1.0}]}))
    code = ru.main(["--units", str(tsv), "--group", "cells", "--plan", str(plan), "--root", str(tmp_path / "rob"),
                    "--repo", str(REPO), "--out", str(tmp_path / "out")])
    rep = json.loads((tmp_path / "out" / "units_report_cells.json").read_text())["units"]["TOYFAIL"]
    assert rep["rc"] == 0, (tmp_path / "out" / "logs" / "TOYFAIL.log").read_text()[-2000:]
    assert rep["status"] == "ESTIMATE_FAILED" and "union" in rep["detail"]
    assert code == 0
    j = json.loads((tmp_path / "rob" / "toy" / "TOYFAIL.json").read_text())
    assert j["channels"]["union"]["status"] == "FAILED"
