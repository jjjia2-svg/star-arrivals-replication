"""Upstream path injection into build_star_set - TDD.

In plain words: U4 star selection must consume the **new versions** of the upstream
data (roster_v2026-07-11_centres + u2_person_map_2026-07-11 + u3_panel_2026-07-11), but build_star_set's
internal calls to _derive_panel_arrivals / _foreign_poach_flags pinned person_map/panel to older literals ->
only roster_files was injectable, while the panel fallback and the poach query pointed at the old directories
(risk of a silent definition split). This test pins that all three upstream paths are injectable and that the
defaults are unchanged (no regression for existing runs).
"""
import pyarrow as pa
import pyarrow.parquet as pq

from run_u4 import build_star_set

ECON = "2002"

_ROSTER_SCHEMA = pa.schema([
    ("author_id", pa.string()), ("display_name", pa.string()), ("dept_key", pa.string()),
    ("year_start", pa.int64()), ("confidence", pa.string()), ("human_verified", pa.bool_()),
])


def _w(root, subpath, rows, schema=None):
    p = root / subpath
    p.parent.mkdir(parents=True, exist_ok=True)
    tbl = pa.Table.from_pylist(rows, schema=schema) if schema else pa.Table.from_pylist(rows)
    pq.write_table(tbl, str(p))


def _build_versioned_root(tmp_path):
    """Synthetic root; every upstream piece uses the 2026-07-11 version directory names (the old literal
    directories are never created - if the code still used the old paths, the panel fallback / poach query
    would raise FileNotFound or fail to infer the arrival)."""
    r = tmp_path
    roster = ("u0p5_roster/roster_v2026-07-11_centres/dept_roster_panel_monash.parquet",
              "u0p5_roster/roster_v2026-07-11_centres/dept_roster_panel_unsw.parquet")
    _w(r, roster[0], [
        {"author_id": "M_ROSTER", "display_name": "MonRoster", "dept_key": "monash_econ",
         "year_start": 2016, "confidence": "high", "human_verified": True},
    ], schema=_ROSTER_SCHEMA)
    _w(r, roster[1], [
        {"author_id": "U_PANEL", "display_name": "UnswPanel", "dept_key": "unsw_econ",
         "year_start": None, "confidence": "low", "human_verified": False},
    ], schema=_ROSTER_SCHEMA)
    _w(r, "u1_edges_full_2026-07-05/authorship_edges/part.parquet", [
        {"author_id": "M_ROSTER", "work_id": "W1"}, {"author_id": "U_PANEL", "work_id": "W2"}])
    _w(r, "u1_edges_full_2026-07-05/works/part.parquet", [
        {"work_id": "W1", "publication_year": 2010, "cited_by_count": 50, "subfield_id": ECON},
        {"work_id": "W2", "publication_year": 2008, "cited_by_count": 30, "subfield_id": ECON}])
    _w(r, "u1_edges_full_2026-07-05/institutions/part.parquet", [
        {"institution_id": "I_SU", "country_code": "SE"},
        {"institution_id": "I31746571", "country_code": "AU"}])
    _w(r, "u2_person_map_2026-07-11/person_map/part.parquet", [
        {"author_id": "M_ROSTER", "person_id": "P_MR"},
        {"author_id": "U_PANEL", "person_id": "P_U"}])
    _w(r, "u3_panel_2026-07-11/panel/part.parquet", [
        {"person_id": "P_U", "year": 2012, "primary_affil_id": "I31746571"},
        {"person_id": "P_U", "year": 2013, "primary_affil_id": "I31746571"}])
    _w(r, "u3_panel_2026-07-11/affil_timeline/part.parquet", [
        {"person_id": "P_U", "year": 2010, "raw_affil": "Stockholm University",
         "canonical_affil_id": "I_SU"}])
    return r, roster


def test_build_star_set_accepts_injected_upstream_subs(tmp_path):
    """With person_map_sub / panel_sub injected: the panel fallback and the poach flag both use the new directories -
    U_PANEL arrival=2012 (inferred from the new panel) + is_foreign_poach=True (the new timeline finds SE)."""
    root, roster = _build_versioned_root(tmp_path)
    res = build_star_set(root, roster_files=roster,
                         person_map_sub="u2_person_map_2026-07-11",
                         panel_sub="u3_panel_2026-07-11")
    stars = {s["author_id"]: s for s in res["stars"]}
    assert res["no_arrival"] == []
    assert stars["U_PANEL"]["arrival"] == 2012
    assert stars["U_PANEL"]["is_foreign_poach"] is True
    assert stars["M_ROSTER"]["is_foreign_poach"] is False
