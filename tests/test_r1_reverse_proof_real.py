# -*- coding: utf-8 -*-
"""R1 J0-MEAS.3j / S10 reverse proof on real data (big host, batch B4; N2's real-data test, not a J0 stage).

Runs only in the big-host test mode (marker ssd) on an R1 instance whose data_sync holds both u1 tables
(u1_edges_full_2026-07-05, u1_full_11school_2026-07-16) and the legacy trees (the test_big job). Every
location comes from the paths config in force ($SAR_PATHS_CONFIG = config/r1/paths_aws.yaml on the
instance): the two tables under <ssd_root>/derived, the person map under legacy_thesis, and the October
reference = the tracked data/cal2026-10/frames_<field>/ (paths key `cal`). The work directory is
$SAR_REVPROOF_OUT when the batch sets it, else a pytest tmp dir on the instance root disk.

reverse_proof_s10.prove() does the work: (1) cut the 11-school table to the 07-05 works and check the
premise (cut == 07-05 by content); (2) run W2-CHEMM's driver in mode b0 with N2's shadow pointing at the
cut; (3) the products must equal October's under the October acceptance rules; (4) with the full 11-school
table the roster channel (dept_only, both) must equal October's except the union builder's age-gap guard;
on a premise failure a wiring run on a re-materialised 07-05 copy must reproduce October instead.
J1a with chemmath_edges on is launched only after this test is green (F30 pre-J1a check).
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

import pytest

pytestmark = pytest.mark.ssd

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import reverse_proof_s10 as rp                       # noqa: E402

OK_VERDICTS = ("REVERSE_PROOF_OK", "PREMISE_FAIL+WIRING_OK")


@pytest.fixture(scope="module")
def proof(tmp_path_factory):
    if os.environ.get("SAR_HOST", "").strip() not in rp.HOSTS:
        pytest.fail("the S10 reverse proof runs only on an R1 instance ($SAR_HOST)")
    if os.environ.get("SAR_PATHS_CONFIG", "").strip() in ("", str(REPO / "config" / "paths_october.yaml")):
        pytest.fail("the big-host job must set $SAR_PATHS_CONFIG (config/r1/paths_aws.yaml); "
                    "config/paths_october.yaml is only the test default")
    out_env = os.environ.get("SAR_REVPROOF_OUT", "").strip()
    out = pathlib.Path(out_env) if out_env else tmp_path_factory.mktemp("revproof_s10")
    out.mkdir(parents=True, exist_ok=True)
    extra = json.loads(os.environ.get("SAR_REVPROOF_DRIVER_EXTRA", "[]") or "[]")
    return out, rp.prove_from_config(out, driver_extra=extra)


@pytest.fixture(scope="module")
def summary(proof):
    return proof[1]


def test_cut_and_premise_are_recorded(summary):
    cut = summary["cut"]
    assert cut["works_W"] > 0
    for sub in rp.PREMISE_SUBTABLES:
        assert sub in cut["subtables"] and sub in summary["premise"]["subtables"], sub
    assert summary["premise"]["verdict"] in ("PREMISE_OK", "PREMISE_FAIL")
    if summary["premise"]["verdict"] == "PREMISE_FAIL":
        assert summary["compare"]["wiring"] is not None, "a premise failure must carry the wiring run"


def test_products_equal_october_under_the_october_rules(summary):
    label = "cut" if summary["premise"]["ok"] else "wiring"
    cmp = summary["compare"][label]
    bad = {f: {k: v["status"] for k, v in r["files"].items() if not v["ok"]}
           for f, r in cmp["fields"].items() if not r["ok"]}
    assert cmp["ok"], (label, bad)
    for f, r in cmp["fields"].items():
        assert set(r["files"]) == {n.format(f=f) for n in rp.PRODUCTS}, f


def test_roster_channel_unchanged_on_the_full_table(summary):
    rc = summary["roster_channel"]
    bad = {f: (r["n_unexplained"], r["unexplained"][:10], r["guard_count_exceeded"])
           for f, r in rc["fields"].items() if not r["ok"]}
    assert rc["ok"], bad


def test_verdict(proof):
    out, summary = proof
    assert summary["verdict"] in OK_VERDICTS, (summary["verdict"], summary["failures"])
    assert json.loads((out / rp.SUMMARY_NAME).read_text(encoding="utf-8")) == summary
    assert (out / "RESULT.txt").read_text(encoding="utf-8").strip() == f"RESULT {summary['verdict']}"
