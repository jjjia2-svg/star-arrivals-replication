# -*- coding: utf-8 -*-
"""econ920/fetch_patch_supplement.py — the October API patch rows for the roster additions
04_rebuild_y.py had no aggregate for. Pins: the row shape equals the frozen 2026-08-13 patch's,
every row belongs to a declared person, the request log carries no key, and the report's
snapshot-overlap measure is recorded."""
from __future__ import annotations

import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
D = REPO / "data/cal2026-10/patch_supplement_2026-10"
KEYS = ["author_id", "work_id", "publication_year", "fwci", "cited_by_count", "subfield_id", "n_authors", "author_ids"]


@pytest.fixture(scope="module")
def rep():
    p = D / "patch_supplement_report_2026-10.json"
    if not p.exists():
        pytest.skip("patch supplement not fetched")
    return json.loads(p.read_text(encoding="utf-8"))


def test_rows_have_the_frozen_patch_shape_and_belong_to_the_declared_persons(rep):
    rows = [json.loads(ln) for ln in (D / "works_by_author_supplement_2026-10.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(rows) == rep["rows"] > 0
    for r in rows:
        assert list(r) == KEYS, r
        assert r["author_id"] in rep["persons"] and r["work_id"].startswith("W")
        assert r["n_authors"] == len(r["author_ids"]) and r["author_id"] in r["author_ids"]
        assert r["subfield_id"] is None or r["subfield_id"].isdigit()


def test_persons_are_exactly_the_blocking_persons_of_the_econ_report(rep):
    j = json.loads((REPO / "data/cal2026-10/frames_econ/build_report_econ920_2026-10.json").read_text(encoding="utf-8"))
    blocking = j["october"]["chain"]["p1_econ"].get("agg_missing", {}).get("old_event_rows_blocking", {}).get("persons")
    if blocking is None:      # after the re-run with the supplement 04 passes and the list is gone
        pytest.skip("econ report no longer records blocking persons")
    assert sorted("P_" + p for p in rep["persons"]) == sorted(blocking)


def test_request_log_has_no_api_key(rep):
    logged = (D / "api_request_log_patch_supplement_2026-10.jsonl").read_text(encoding="utf-8")
    assert "api_key" not in logged and logged.count("\n") >= len(rep["persons"])
    for aid, v in rep["per_author"].items():
        assert v["works"] >= v["with_year"] > 0 and v["snapshot_overlap"]["measured"] is True
