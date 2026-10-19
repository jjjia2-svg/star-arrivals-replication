"""U0.5 step 1, parsing TDD - parse_roster_lines turns the raw archive of 92 Monash people scraped by Chrome
into structured records. The fixture = the real archive (monash_econ_pure_raw_2026-06-29.txt), not synthetic data.

Red-test assertions (task 1):
  - exactly 92 people parsed (comments/blank lines/statistics lines do not count);
  - Yves Zenou is included (golden test 1: can be found);
  - ADJUNCT / Emeritus / Impact Labs flags are correct (counted from the real archive: adjunct=11, emeritus=2, center=19);
  - people with missing years (15 "(no years)") get year_start/year_end=None, no crash.

Schema of each record (this unit's intermediate form, not Table B):
  {display_name, email, title_raw, year_start, year_end, is_adjunct, is_emeritus, center}
  (email column: the real archive has no email, all None - the column is kept for the planned field set).

Hard rules: TDD red first, then green; whether a flag counts as "on staff" = [a human decision]; the parsing layer only captures + flags and does not decide inclusion/exclusion.
"""
from __future__ import annotations

import pathlib

import pytest

from roster.parse import parse_roster_lines

_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "monash_econ_pure_raw_2026-06-29.txt"

_SKIP_NO_FIXTURE = ("archived staff-page fixture not in the public package "
                    "(it holds real names; kept in the private archive)")


@pytest.fixture(scope="module")
def raw_text() -> str:
    if not _FIXTURE.is_file():
        pytest.skip(_SKIP_NO_FIXTURE)
    return _FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parsed(raw_text):
    return parse_roster_lines(raw_text)


# ===========================================================================
# Count: exactly 92 people
# ===========================================================================
def test_parses_exactly_92_people(parsed):
    """Exactly 92 people (Pure Profiles=92; comments/statistics/pagination title lines never count)."""
    assert len(parsed) == 92


def test_every_record_has_full_field_set(parsed):
    """Each record has exactly 8 fields (intermediate-form schema); more or fewer counts as parsing drift."""
    expected = {
        "display_name", "email", "title_raw",
        "year_start", "year_end", "is_adjunct", "is_emeritus", "center",
    }
    for rec in parsed:
        assert set(rec.keys()) == expected, f"field set mismatch: {rec}"


# ===========================================================================
# Yves Zenou is included (golden test 1)
# ===========================================================================
def test_zenou_present(parsed):
    """Golden test 1: Yves Zenou is in the parsed list, with a clean name (the trailing ★GOLDEN note does not pollute display_name)."""
    names = {r["display_name"] for r in parsed}
    assert "Yves Zenou" in names


def test_zenou_years_clean(parsed):
    """The Yves Zenou row has a trailing note tag - parsing must take only the year interval and not treat the ★ note as year/center.

    Red line #3: 1995 is a Pure publication year, not an arrival year - the parsing layer reads year_start=1995 as is, but it is never treated as an arrival
    (arrival is recorded in the arrival slice, not in this table).
    """
    z = next(r for r in parsed if r["display_name"] == "Yves Zenou")
    assert z["year_start"] == 1995
    assert z["year_end"] == 2026
    assert z["center"] is None          # the Yves Zenou row has no Impact Labs
    assert z["is_adjunct"] is False
    assert z["is_emeritus"] is False


# ===========================================================================
# Flags are correct (counted from the real archive)
# ===========================================================================
def test_adjunct_count(parsed):
    """adjunct=11 (number of flag:adjunct rows in the real archive; the archive footnote says about 10, which is an estimate, the actual count is 11)."""
    assert sum(1 for r in parsed if r["is_adjunct"]) == 11


def test_emeritus_count(parsed):
    """emeritus=2 (Person R1 + 1 other)."""
    emeriti = [r["display_name"] for r in parsed if r["is_emeritus"]]
    assert len(emeriti) == 2
    assert "Person R1" in emeriti
    assert "Person O" in emeriti


def test_center_impact_labs_count(parsed):
    """Impact Labs center=17 (number of PERSON rows in the real archive; 2 other 'Impact Labs' mentions are in comment/statistics lines and do not count; the footnote estimates about 16)."""
    centered = [r for r in parsed if r["center"] == "Impact Labs"]
    assert len(centered) == 17


def test_adjunct_detected_from_title_text(parsed):
    """The adjunct flag must recognise the title text (e.g. "ADJUNCT PROFESSOR") - Person R2 is an adjunct."""
    g = next(r for r in parsed if r["display_name"] == "Person R2")
    assert g["is_adjunct"] is True
    assert "ADJUNCT" in g["title_raw"]


# ===========================================================================
# Missing years do not crash (15 "(no years)")
# ===========================================================================
def test_missing_years_become_none_not_crash(parsed):
    """People with missing years (15) get year_start/year_end=None - parsing does not crash and does not fill in placeholder numbers."""
    no_year = [r for r in parsed if r["year_start"] is None]
    assert len(no_year) == 15
    for r in no_year:
        assert r["year_end"] is None
        # Person P is the first "(no years)" person - a sample check that the name is parsed correctly.
    names = {r["display_name"] for r in no_year}
    assert "Person P" in names
    assert "Person Q" in names


def test_year_pair_parsed_as_ints(parsed):
    """For people with years, year_start/year_end are int (not strings)."""
    person_r = next(r for r in parsed if r["display_name"] == "Person R")
    assert person_r["year_start"] == 2023
    assert person_r["year_end"] == 2025
    assert isinstance(person_r["year_start"], int)


def test_emeritus_year_one_sided_ok(parsed):
    """Person O = Emeritus + (no years) -> no crash, year=None, is_emeritus=True."""
    gus = next(r for r in parsed if r["display_name"] == "Person O")
    assert gus["is_emeritus"] is True
    assert gus["year_start"] is None
    assert gus["year_end"] is None


# ===========================================================================
# Comment/statistics/pagination lines are not treated as people
# ===========================================================================
def test_no_comment_or_stats_lines_as_people(parsed):
    """Comment lines (#...) / pagination titles / statistics lines never enter the list (display_name contains none of '#' / 'PAGE' / the Chinese word for "statistics")."""
    for r in parsed:
        assert not r["display_name"].startswith("#")
        assert "PAGE" not in r["display_name"]
        assert "===" not in r["display_name"]
        assert r["display_name"].strip() == r["display_name"]  # no leading or trailing whitespace
