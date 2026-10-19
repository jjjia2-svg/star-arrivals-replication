# -*- coding: utf-8 -*-
"""analysis/paper/ledger_new_2026_10.py — the two 2026-09-21 numbers (one-hop share, subfield
support). Pure-helper tests; the DuckDB pass over the extraction tables is exercised by the control
run recorded in the author's private build log (prodlib hop1 EQUAL for chemistry and mathematics)."""
from __future__ import annotations

import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ledger_new", REPO / "analysis/paper/ledger_new_2026_10.py")
m = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(m)   # type: ignore[union-attr]


def test_field_codes_are_the_openalex_field_prefixes():
    assert m.FIELD_CODE == {"econ": "20", "chemistry": "16", "math_stats": "26"}


def test_supplements_are_exactly_what_stage_py_feeds_prodlib():
    stage = (REPO / "pipeline/frames/cal2026-10/stage.py").read_text(encoding="utf-8")
    for field, rels in m.SUPPLEMENTS.items():
        for rel in rels:
            assert (REPO / rel).exists(), rel
            assert pathlib.Path(rel).name in stage, (field, rel)


def test_config_renders_the_derived_placeholder_and_econ_has_a_person_map():
    d = pathlib.Path("/X/derived")
    c = m.config("econ", d)
    assert c["edges_glob"].startswith("/X/derived/u1_full_11school_2026-07-16/") and c["person_map"].startswith("/X/derived/u2_person_map")
    for f in ("chemistry", "math_stats"):
        c = m.config(f, d)
        assert c["edges_glob"].startswith("/X/derived/u1_edges_full_2026-07-05/") and c["person_map"] is None


def test_arrival_years_key_by_the_frame_event_id_form():
    ev = REPO / "data/cal2026-10"
    e = m.arrival_years(ev, "econ"); c = m.arrival_years(ev, "chemistry"); s = m.arrival_years(ev, "math_stats")
    assert len(e) == 113 and len(c) == 38 and len(s) == 33
    assert all(":" in k and k.split(":")[1].isdigit() for k in e)
    assert all(":" in k and not k.split(":")[1].isdigit() for k in c)
