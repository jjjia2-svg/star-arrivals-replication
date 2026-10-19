"""U0.5 UNSW vertical slice TDD - align restricted to the UNSW institution + write Table B unsw_econ + driver assembly.

Reuses the units already built for Monash (the general logic of align.classify_match / table_b.to_table_b_row / write_table_b /
run_u0p5.build_roster_rows) and only checks the places that "extend support to UNSW":

  A) align - the UNSW university-level inst_id constant exists + is bare; _build_url accepts an inst_id parameter (the institution can be swapped).
  B) table_b - to_table_b_row accepts a dept_key parameter and writes unsw_econ rows; year=None is written directly without a crash.
  C) run - build_unsw_roster_rows: 53 people, one row each, none lost; dept_key all unsw_econ; year all None;
     needs_human goes into needs_author; summary carries visiting/emeritus/postdoc counts.

Hard rules: bare author_id; 0 or several hits -> needs_human (red line #1); UNSW has no years, so None (red line #3);
  schema guarded verbatim; reuse, no rewrite.
"""
from __future__ import annotations

import pathlib

import pytest

from common.schema import DEPT_ROSTER_PANEL, assert_matches_schema
from roster.parse import parse_unsw_lines
from roster.align import UNSW_INST_ID, _build_url, MAILTO
from roster.table_b import to_table_b_row
from roster.run_u0p5 import build_unsw_roster_rows, UNSW_DEPT_KEY

_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "unsw_econ_our-people_raw_2026-06-29.txt"

_SKIP_NO_FIXTURE = ("archived staff-page fixture not in the public package "
                    "(it holds real names; kept in the private archive)")


@pytest.fixture(scope="module")
def parsed():
    if not _FIXTURE.is_file():
        pytest.skip(_SKIP_NO_FIXTURE)
    return parse_unsw_lines(_FIXTURE.read_text(encoding="utf-8"))


# ===========================================================================
# A) align - UNSW institution id constant + a URL with a swappable institution
# ===========================================================================
def test_unsw_inst_id_is_bare_i31746571():
    """UNSW university-level institution id = I31746571 (checked live via ROR 03r8z3t63: country=AU/type=education), bare."""
    assert UNSW_INST_ID == "I31746571"
    assert not UNSW_INST_ID.startswith("http")


def test_build_url_accepts_inst_id_param():
    """_build_url accepts an inst_id parameter (the institution can be swapped) -> the UNSW institution-restricted search carries the UNSW id, not Monash."""
    url = _build_url("A5008470795", use_institution_filter=True, inst_id=UNSW_INST_ID)
    assert f"last_known_institutions.id:{UNSW_INST_ID}" in url
    assert "I56590836" not in url           # never carries the Monash id
    assert f"mailto={MAILTO}" in url


def test_build_url_default_inst_id_still_monash():
    """inst_id not passed -> still defaults to Monash (backward compatible, the Monash slice is not broken)."""
    url = _build_url("Yves Zenou", use_institution_filter=True)
    assert "last_known_institutions.id:I56590836" in url


# ===========================================================================
# B) table_b - dept_key parameter -> unsw_econ rows; year=None written directly
# ===========================================================================
_HIT = {"author_id": "A123", "confidence": "high", "needs_human": False}
_NEEDS_HUMAN = {"author_id": None, "confidence": None, "needs_human": True}


def _unsw_parsed(name):
    return {
        "display_name": name, "email": None, "title_raw": "Professor",
        "year_start": None, "year_end": None,
        "is_visiting": False, "is_emeritus": False, "is_postdoc": False,
        "is_adjunct": False, "center": None,
    }


def test_table_b_row_dept_key_unsw():
    """to_table_b_row(dept_key="unsw_econ") -> dept_key=unsw_econ + the 8-column schema."""
    row = to_table_b_row(_unsw_parsed("A5008470795"), _HIT, dept_key=UNSW_DEPT_KEY)
    assert row["dept_key"] == "unsw_econ"
    assert_matches_schema(row.keys(), DEPT_ROSTER_PANEL, label="dept_roster_panel")


def test_table_b_row_default_dept_key_still_monash():
    """dept_key not passed -> still defaults to monash_econ (backward compatible)."""
    row = to_table_b_row(_unsw_parsed("X"), _HIT)
    assert row["dept_key"] == "monash_econ"


def test_table_b_row_year_none_passthrough():
    """UNSW year=None is written straight into Table B (year_start/year_end=None, no placeholder)."""
    row = to_table_b_row(_unsw_parsed("A5008470795"), _HIT, dept_key=UNSW_DEPT_KEY)
    assert row["year_start"] is None
    assert row["year_end"] is None
    assert row["evidence"] == "official_roster"
    assert row["human_verified"] is False


def test_table_b_row_needs_human_none_id():
    """needs_human -> author_id=None + confidence=low (red line #1)."""
    row = to_table_b_row(_unsw_parsed("Nobody"), _NEEDS_HUMAN, dept_key=UNSW_DEPT_KEY)
    assert row["author_id"] is None
    assert row["confidence"] == "low"


# ===========================================================================
# C) run - build_unsw_roster_rows assembly (stub aligner, offline)
# ===========================================================================
def _stub_aligner_factory(name_to_verdict):
    def _align(display_name, *, api_key=None):
        return dict(name_to_verdict.get(
            display_name, {"author_id": None, "confidence": None, "needs_human": True}
        ))
    return _align


def test_unsw_dept_key_constant():
    assert UNSW_DEPT_KEY == "unsw_econ"


def test_build_unsw_rows_one_per_person(parsed):
    """Number of rows is exactly == number of parsed records (53, one per person, none lost)."""
    stub = _stub_aligner_factory({})
    rows, summary = build_unsw_roster_rows(parsed, aligner=stub)
    assert len(rows) == len(parsed) == 53


def test_build_unsw_rows_all_dept_key_unsw(parsed):
    """Every row has dept_key=unsw_econ (written to the right department)."""
    stub = _stub_aligner_factory({})
    rows, _ = build_unsw_roster_rows(parsed, aligner=stub)
    assert all(r["dept_key"] == "unsw_econ" for r in rows)


def test_build_unsw_rows_all_years_none(parsed):
    """Every row has year_start/year_end=None (UNSW has no years, red line #3: never guess)."""
    stub = _stub_aligner_factory({})
    rows, _ = build_unsw_roster_rows(parsed, aligner=stub)
    for r in rows:
        assert r["year_start"] is None and r["year_end"] is None


def test_unsw_summary_counts(parsed):
    """summary: parsed_count=53; matched + needs_human == 53; flag counts are right."""
    verdicts = {
        "A5008470795": {"author_id": "A_ph1", "confidence": "high", "needs_human": False},
        "A5054240727": {"author_id": "A_ph2", "confidence": "high", "needs_human": False},
    }
    stub = _stub_aligner_factory(verdicts)
    rows, summary = build_unsw_roster_rows(parsed, aligner=stub)
    assert summary["dept_key"] == "unsw_econ"
    assert summary["parsed_count"] == 53
    assert summary["author_id_matched"] == 2
    assert summary["needs_human_count"] == 51
    assert summary["author_id_matched"] + summary["needs_human_count"] == 53
    assert len(summary["needs_author"]) == 51
    assert summary["visiting_count"] == 3
    assert summary["emeritus_count"] == 1
    assert summary["postdoc_count"] == 5


def test_unsw_needs_human_rows_have_none_id(parsed):
    """A needs_human person has author_id=None and their name is in needs_author."""
    stub = _stub_aligner_factory({})
    rows, summary = build_unsw_roster_rows(parsed, aligner=stub)
    for r in rows:
        assert r["author_id"] is None
    assert set(summary["needs_author"]) == {r["display_name"] for r in parsed}


def test_unsw_rows_write_to_table_b_roundtrip(parsed, tmp_path):
    """Rows produced by build_unsw_roster_rows can be written by write_table_b and read back (the schema guard passes)."""
    import pyarrow.parquet as pq
    from roster.table_b import write_table_b

    stub = _stub_aligner_factory({
        "A5008470795": {"author_id": "A_ph1", "confidence": "high", "needs_human": False},
    })
    rows, _ = build_unsw_roster_rows(parsed, aligner=stub)
    target = tmp_path / "dept_roster_panel_unsw.parquet"
    write_table_b(rows, target)
    tbl = pq.read_table(str(target))
    assert tbl.num_rows == 53
    assert set(tbl.column_names) == set(DEPT_ROSTER_PANEL.keys())
    d = {r["display_name"]: r for r in tbl.to_pylist()}
    assert d["A5008470795"]["author_id"] == "A_ph1"
    assert d["A5008470795"]["dept_key"] == "unsw_econ"
