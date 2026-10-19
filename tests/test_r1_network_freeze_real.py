# -*- coding: utf-8 -*-
"""R1 V3-NET oracle on real October data (big host, batch B4; replaces the J0 'v3net_oracle' row).

Runs only in the big-host test mode (marker ssd) on an R1 instance, after the J0 B0 stage products are
restored. The batch names its inputs in a JSON spec ($SAR_V3NET_ORACLE, schema sar.r1.v3net_oracle_spec.v1;
paths are instance paths the batch writes, never typed here) and the report directory in
$SAR_V3NET_ORACLE_OUT. network_freeze.oracle() does the work:

  (a) chemistry / math_stats: prodlib re-run on the October shadow config through observe_prodlib;
      classify(graph_from_prodlib_config(cfg)) == the observed (degree, frozen) for EVERY pair, and the
      per-event counts == build_report pairs.per_event;
  (b) economics: the same for the all-events econ prodlib run (the run_controls E config);
  (c) the October econ network frame after filters (c)+(d), split as econ920_m's network_freeze step splits
      it and each part classified on its builder's graph (econ920_m.freeze_graphs): 'econ' = the July rows
      (11-school edges + the shadow's concatenated econ supplement + the U2 map; the agreement matrix with
      U5's degree2_bridge_frozen when the dose table carries it), 'econ_fnfix' = the 2026-08-15 prodlib rows
      of the fn-fix events (that run's frozen config: its snapshot copy, person map and supplement),
      'econ_regenerated' = A5091326353's regenerated rows (the regeneration config): 'none' == 0 in every part
      (t-big-04: the 08-15 rows on the July graph left two relations UNEXPLAINED);
  (d) what V3-NET would remove from October, per field (the 3o counts), written to the report.

summary.json holds counts and ids only. A failure here STOPs J1a's use of V3-NET.
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
import network_freeze as nf                          # noqa: E402


@pytest.fixture(scope="module")
def summary():
    if os.environ.get("SAR_HOST", "").strip() not in ("ec2-r1-test", "ec2-r1"):
        pytest.fail("the V3-NET oracle runs only on an R1 instance ($SAR_HOST)")
    spec_p, out = os.environ.get("SAR_V3NET_ORACLE", ""), os.environ.get("SAR_V3NET_ORACLE_OUT", "")
    if not spec_p or not out:
        pytest.fail("batch B4 must set $SAR_V3NET_ORACLE (the input spec) and $SAR_V3NET_ORACLE_OUT")
    spec = json.loads(pathlib.Path(spec_p).read_text(encoding="utf-8"))
    return nf.oracle(spec, pathlib.Path(out))


def test_classify_equals_the_observed_prodlib_for_every_pair(summary):
    obs = summary["observe"]
    assert {"chemistry", "math_stats", "econ"} <= set(obs), sorted(obs)
    for label, r in obs.items():
        assert r["pairs_observed"] > 0, label
        assert r["pair_mismatches"] == 0, (label, r["pair_mismatch_ids"])
        assert r["per_event_mismatches"] == 0, (label, r["per_event_mismatch_ids"])
        assert r["none"] == 0, label


ECON_PARTS = ("econ", "econ_fnfix", "econ_regenerated")


def test_october_econ_frame_has_no_unexplained_relation(summary):
    frames = summary["frames"]
    assert {"econ", "econ_fnfix"} <= set(frames), sorted(frames)     # October's net1 holds 08-15 prodlib rows
    for label in (x for x in ECON_PARTS if x in frames):
        r = frames[label]
        assert r["stop"] is None, (label, r["stop"], r.get("stop_ids"))
        assert r["relations_by_class"]["none"] == 0, label
    r = frames["econ"]
    if r["u5"]["flags"] == "present":
        assert r["u5"]["matrix"], "U5 dose table carries the flag but no relation matched"


def test_removal_counts_are_written_per_field(summary):
    labels = ("chemistry", "math_stats") + tuple(x for x in ECON_PARTS if x in summary["frames"])
    assert "econ" in labels
    for field in labels:
        r = summary["frames"][field]
        assert r["stop"] is None, (field, r["stop"], r.get("stop_ids"))
        assert set(r["relations_by_class"]) == set(nf.CLASSES)
        assert r["rows_dropped"] == r["rows_by_class"]["deg2_unfrozen"]
    assert summary["result"] == "OK", summary["result"]
    assert (pathlib.Path(os.environ["SAR_V3NET_ORACLE_OUT"]) / "summary.json").is_file()
