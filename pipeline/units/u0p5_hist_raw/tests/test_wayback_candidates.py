"""Wayback candidate-row assembly TDD — 147 (department, person) year-by-year archives -> table-B-shaped candidate rows.

Rules: evidence=wayback_snapshot / confidence=medium / human_verified=False;
if matched attach the author_id, if not leave None (red test #15: never miss a person and never invent an id);
years = the snapshot-year interval, missing years not filled; written to a candidate-layer file, never to the official table B.
"""


def _person(dept="monash_econ", name="Person N", years=(2006, 2009)):
    return {"dept_key": dept, "display_name": name, "years": sorted(years)}


def test_candidate_rows_shape_and_semantics():
    from common.schema import DEPT_ROSTER_PANEL
    from histraw.wayback_candidates import build_wayback_candidate_rows

    rows = build_wayback_candidate_rows(
        [_person(), _person(name="Ghost Person", years=(2000, 2003))],
        name_to_author_id={"Person N": "A5PN"})
    assert len(rows) == 2
    for r in rows:
        assert set(r.keys()) == set(DEPT_ROSTER_PANEL.keys())
        assert r["evidence"] == "wayback_snapshot"
        assert r["confidence"] == "medium"
        assert r["human_verified"] is False
    by = {r["display_name"]: r for r in rows}
    assert by["Person N"]["author_id"] == "A5PN"
    assert by["Person N"]["year_start"] == 2006 and by["Person N"]["year_end"] == 2009
    assert by["Ghost Person"]["author_id"] is None, "an unmatched id stays None, no id is made up (red test #15)"


def test_write_candidates_never_official_filename(tmp_path):
    from histraw.wayback_candidates import build_wayback_candidate_rows, write_wayback_candidates

    rows = build_wayback_candidate_rows([_person()], name_to_author_id={})
    p1 = write_wayback_candidates(rows, tmp_path / "o1")
    p2 = write_wayback_candidates(rows, tmp_path / "o2")
    assert p1.name == "wayback_roster_candidates.parquet"
    assert p1.name not in ("dept_roster_panel_monash.parquet", "dept_roster_panel_unsw.parquet")
    assert p1.read_bytes() == p2.read_bytes()


def test_write_candidates_total_order_same_name_none_id(tmp_path):
    """Review L1: same-name same-department rows with a None id have a flat key -> the sort key adds year_end as a tie-breaker, so the bytes do not depend on input order."""
    from histraw.wayback_candidates import build_wayback_candidate_rows, write_wayback_candidates

    r1 = _person(name="Same Name", years=(2000, 2003))
    r2 = _person(name="Same Name", years=(2000, 2005))
    a = build_wayback_candidate_rows([r1, r2], name_to_author_id={})
    b = build_wayback_candidate_rows([r2, r1], name_to_author_id={})
    p1 = write_wayback_candidates(a, tmp_path / "o1")
    p2 = write_wayback_candidates(b, tmp_path / "o2")
    assert p1.read_bytes() == p2.read_bytes()
