# -*- coding: utf-8 -*-
"""R1 F14 switch-off proof on real data (big host, batch B4; J0-MEAS.3j repeats it inside J0):
pipeline/aws/r1/chemmath_m.py --mode b0 (every switch off: the B0 config, the October event tables, the
frozen rosters and the 08-28 stars_excluded list through stage.build_shadow's October defaults, no N2
env, no V3-NET, no dose post-step) reproduces data/cal2026-10/frames_{chemistry,math_stats}/ under
October's acceptance rules:
  relationships_<f>.csv and p2_becoming_<f>.csv   BYTE_EQUAL
  union_build_report_<f>.json                      equal modulo run-dir paths, H1 only at the
                                                   G_VAL_advisory example path (<= 8 ULP)
  p1_frame_<f>.csv                                 within H1 (fwci_frac / fwci_frac_ex_star, <= 8 ULP)
  pairs_none / p3_slim / p3_slim_ev                content-equal (tools/content_equal, D1)

Runs only on an R1 instance (SAR_HOST) with the data disk synced (u1_edges_full_2026-07-05, the legacy
v2_output tree) and SAR_PATHS_CONFIG = config/r1/paths_aws.yaml (the test_big job env). It writes only
under pytest's tmp_path. About 15-30 min on r6i.8xlarge (prodlib + three gold stages + slim, two fields).
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


@pytest.fixture(scope="module")
def b0_run(tmp_path_factory):
    if os.environ.get("SAR_HOST", "").strip() not in ("ec2-r1-test", "ec2-r1"):
        pytest.fail("the chem/maths b0 proof runs only on an R1 instance ($SAR_HOST)")
    import chemmath_m as cm                                              # noqa: PLC0415
    root = tmp_path_factory.mktemp("chemmath_b0")
    out = root / "out"
    rc = cm.main(["--mode", "b0", "--config", str(REPO / "config" / "r1" / "B0.json"),
                  "--october-ref", str(REPO), "--out", str(out), "--scratch", str(root / "scratch")])
    report = json.loads((out / "chemmath_m_run_report.json").read_text(encoding="utf-8"))
    return cm, rc, out, report


def test_b0_mode_reproduces_the_october_chemmath_frames(b0_run):
    cm, rc, out, report = b0_run
    assert rc == 0, report.get("stop")
    assert (out / "RESULT.txt").read_text(encoding="utf-8") == "OK\n"
    assert report["edges"]["edge_shadow"] is False
    for f in cm.FIELDS:
        V = cm.compare_products(f, out / f"frames_{f}", REPO)
        assert V["relationships"] == "BYTE_EQUAL", f
        assert V["p2_becoming"] == "BYTE_EQUAL", f
        u = V["union_build_report"]
        assert u["equal_modulo_paths_and_h1_advisory"], (f, u["diffs"][:5])
        assert u["h1_ulp_in_advisory"]["worst_ulp"] <= 8
        assert V["p1_frame"]["ok"], (f, V["p1_frame"])
        assert set(V["p1_frame"]["unexpected_columns"]) == set()
        for name in (f"pairs_none_{f}.parquet", f"p3_slim_{f}.parquet", f"p3_slim_ev_{f}.parquet"):
            assert V[name]["content"] == "EQUAL", (f, name, V[name])
        assert V["all_equal"], (f, V["differ"])
        # the in-driver comparison said the same before the products were written
        assert report["vs_october"][f]["all_equal"], f


def test_b0_mode_ran_october_steps_only(b0_run):
    _cm, rc, out, report = b0_run
    assert rc == 0
    for f, F in report["fields"].items():
        assert "v3net" not in F and "dose" not in F, f
        assert F["prodlib"]["config_diff_vs_b0"]["keys"] == [], f
        assert F["prodlib"]["events_in_prodlib"] == F["prodlib"]["events_in_table"], f
    g = json.loads((out / "report_gdose_chemmath.json").read_text(encoding="utf-8"))
    assert set(g["fields"]) == {"chemistry", "math_stats"}
    assert (out / "report_coverage_chemmath.json").is_file()            # B0 agg_missing = report: never a STOP


def test_b0_coverage_derives_octobers_agg_missing_allowlist(b0_run):
    """W2-2: the ids config M allowlists are October's own - the b0 run's coverage persons on October's frame,
    whose row count must equal October's y-step agg_missing (11 chemistry, 0 maths). Until W3-MPIN copies them
    into config/r1/M.json the test is an xfail that names them; once copied they must be exactly these."""
    _cm, rc, out, _report = b0_run
    assert rc == 0
    cov = json.loads((out / "report_coverage_chemmath.json").read_text(encoding="utf-8"))
    chem, maths = cov["fields"]["chemistry"], cov["fields"]["math_stats"]
    assert chem["cross_check"]["status"] == "EQUAL" and chem["missing"]["rows"] == 11, chem["cross_check"]
    assert maths["cross_check"]["status"] == "EQUAL" and maths["missing"]["rows"] == 0, maths["cross_check"]
    ids = sorted(chem["missing"]["persons"])
    allow = json.loads((REPO / "config" / "r1" / "M.json").read_text(encoding="utf-8"))["agg_missing_allow"]
    if not allow["chemistry"]["persons"]:
        pytest.xfail(f"pending (W3-MPIN): copy into config/r1/M.json agg_missing_allow.chemistry.persons: {ids}")
    assert sorted(allow["chemistry"]["persons"]) == ids
    assert allow["math_stats"]["persons"] == []
