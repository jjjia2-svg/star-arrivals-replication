# -*- coding: utf-8 -*-
"""pipeline/frames/cal2026-10/run_cal_afar.py — the October Panel 3 sweep. Pins: the input plan
(what the legacy afar script reads, at the legacy names), the counts-by-spec definition recovered
on 2026-09-23 (must reproduce data/frames/p3_afar_counts_by_spec.csv from the frozen cut frames),
and the frozen 08-28 control report (every product EQUAL to data/frames/)."""
from __future__ import annotations

import csv
import importlib.util
import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("rca", REPO / "pipeline/frames/cal2026-10/run_cal_afar.py")
m = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(m)   # type: ignore[union-attr]
FR = REPO / "data/frames"


def test_input_plan_names_exactly_what_the_legacy_script_reads(tmp_path):
    legacy = (REPO / "pipeline/frames/p3_topicpair_2026-08-17/code/50_leftbehind_build.py").read_text(encoding="utf-8")
    dirs = {}
    for f in m.FIELDS:
        d = tmp_path / f; d.mkdir(); dirs[f] = d
        for name in (["pairs_unified.csv", "p1_frame_econ.csv", "p2_becoming_econ.csv", "relationships.csv"] if f == "econ"
                     else [f"pairs_none_{f}.parquet", f"p1_frame_{f}.csv", f"p2_becoming_{f}.csv"]):
            (d / name).write_bytes(b"x")
    sh = m.fs08.Shadow(tmp_path / "shadow/v2_output")
    staged = m.stage_inputs(sh, dirs)
    assert len(staged) == 10
    for rel in staged:
        assert rel.split("/")[-1] in legacy, rel      # every staged basename is one the legacy script opens


def test_counts_by_spec_definition_reproduces_the_frozen_table():
    exp = list(csv.DictReader(open(FR / "p3_afar_counts_by_spec.csv", newline="", encoding="utf-8")))
    for e in exp:
        r = m.counts_row(e["field"], e["spec"], float(e["cut"]), FR / f"p3_afar_{e['spec']}_{e['field']}.parquet")
        got = {k: str(v) for k, v in r.items()}
        assert got == dict(e), (e["field"], e["spec"])


def test_frozen_0828_control_report_is_all_equal():
    r = json.loads((REPO / "data/cal2026-10/afar_control_0828_report_2026-09-23.json").read_text(encoding="utf-8"))
    assert r["mode"].startswith("control") and r["stops"] == []
    for name, v in r["control"].items():
        assert v == "EQUAL" or (isinstance(v, dict) and v["equal"]), name
    assert len([k for k in r["control"] if k.endswith(".parquet")]) == 9
    assert all(r["cuts"][f"med_vs_lb_{f}"] == "EQUAL" for f in m.FIELDS)
