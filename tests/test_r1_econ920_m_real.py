# -*- coding: utf-8 -*-
"""R1 F11 switch-off proof (W2-ECONM; big host, batch B4; replaces the J0 'econ920_null' row).

pipeline/aws/r1/econ920_m.py run on OCTOBER's plan - the October event tables, REGEN = {A5091326353}, removed_old
= October's three dropped events, October's patch supplement, every R1 hook off (config B0: no V3-NET,
no dose post-step, agg_missing 'report', no new stars, no re-dates) - must reproduce October's
economics frames: p1_frame_econ.csv by the gate-1 rule for economics (econ920_lib.characterise_frame:
byte-equal or differing only in the four y columns 04 overwrites, <= 8 ULP), p2_becoming_econ.csv and
p1_events_ledger_econ.csv byte for byte, the two slims content-equal, pairs_unified.csv equal to the
sha October's build report pins, and no old-event person-year without an outcome source. October's
run_econ920.py and econ920_lib.py are imported, never edited.

It runs the four controls and the G-DOSE population measurement first, in the same root, exactly as
the M stage does (about 10 minutes with the R cells of c2 / c3).
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

pytestmark = [pytest.mark.ssd, pytest.mark.legacy]

REPO = pathlib.Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "pipeline" / "aws" / "r1"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import econ920_m as em            # noqa: E402
import gates                      # noqa: E402

OCT = REPO / "data" / "cal2026-10" / "frames_econ"


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    root = tmp_path_factory.mktemp("econ920_null_root")
    out = tmp_path_factory.mktemp("econ920_null_out")
    rep = em.run_october_plan(root, out)
    return out, rep


def test_october_plan_reproduces_the_october_frames(run):
    out, rep = run
    fe = out / "frames_econ"
    p1 = gates.rule_h1_econ(OCT / "p1_frame_econ.csv", fe / "p1_frame_econ.csv")
    assert p1["ok"], p1["verdict"]
    for name in ("p2_becoming_econ.csv", "p1_events_ledger_econ.csv"):
        assert gates.rule_byte(OCT / name, fe / name)["ok"], name
    for name in ("p3_slim_econ.parquet", "p3_slim_ev_econ.parquet"):
        r = gates.rule_content(OCT / name, fe / name)
        assert r["ok"], (name, r)
    oct_report = json.loads((OCT / "build_report_econ920_2026-10.json").read_text(encoding="utf-8"))
    pin = oct_report["october"]["pairs_unified"]
    assert rep["m"]["pairs_unified"] == {"sha256": pin["sha256"], "bytes": pin["bytes"]}


def test_october_plan_is_october(run):
    _out, rep = run
    oct_report = json.loads((OCT / "build_report_econ920_2026-10.json").read_text(encoding="utf-8"))
    plan = rep["plan"]
    assert plan["regen"] == {"A5091326353:2009": "corrected"}
    assert plan["removed_old"] == sorted(oct_report["preconditions"]["events"]["removed_old_events"])
    assert plan["removed_new_stars"] == ["A5044432173"] and plan["new_stars"] == [] and plan["unstar"] == []
    assert plan["ledger_redates"] == {} and plan["ledger_appends"] == []
    m = rep["m"]
    assert m["network_freeze"] is None and m["incumbent_stars"]["rows_dropped"] == 0
    assert m["dose_exclusion"] == {"mode": "off", "called": False}
    assert not any(e["origin"].startswith("r1:S6") for e in m["staging_manifest"])
    assert m["g_row_proof"]["closed"]


def test_october_plan_leaves_no_old_event_row_without_an_outcome(run):
    out, rep = run
    body = json.loads((out / "report_agg_missing.json").read_text(encoding="utf-8"))
    assert body["code"] == "OK" and body["mode"] == "report"
    assert body["classes"]["old_event_rows_blocking"]["rows"] == 0
    assert body["ids"] == body["persons"]
    g_oct = json.loads((OCT / "g_econ_rebuild_econ.json").read_text(encoding="utf-8"))
    g_new = json.loads((out / "frames_econ" / "g_econ_rebuild_econ.json").read_text(encoding="utf-8"))
    assert g_new["C_PC_fnfix_newevent_rows"]["rows_agg_missing_NA"] == \
        g_oct["C_PC_fnfix_newevent_rows"]["rows_agg_missing_NA"]           # the prodlib rows October wrote NA
    assert g_new["PASS"] == g_oct["PASS"]
