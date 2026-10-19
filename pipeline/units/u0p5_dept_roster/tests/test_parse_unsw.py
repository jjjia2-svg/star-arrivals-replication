"""U0.5 UNSW parsing TDD - parse_unsw_lines turns the raw archive of the current 53 people of the UNSW School of Economics scraped by Chrome
into structured records. The fixture = the real archive
(unsw_econ_our-people_raw_2026-06-29.txt), not synthetic data.

How the UNSW format differs from Monash (task 2):
  - pipe format `display_name | title_raw [| flag:visiting/emeritus/postdoc]`;
  - **the UNSW page gives no years** -> year_start / year_end all None (red line #3: years are filled in from Wayback/bylines, never guessed);
  - the flag marks are visiting / emeritus / postdoc (Monash has adjunct / emeritus).

Red-test assertions:
  - exactly 53 people parsed (comments/statistics lines do not count);
  - visiting=3 / emeritus=1 / postdoc=5 flags are correct;
  - every person has year_start / year_end == None (the UNSW page has no years, never guess);
  - people with a bracketed role (such as the "(Associate Director)" type) have a clean display_name;
  - a 3-part line like "Aust. Laureate Fellow (ARC) | Professor" does not crash and "Professor" is not taken as a year/center.

Hard rules: TDD red first, then green; reuse the Monash unit (extend parse, do not rewrite); whether a flag counts as "on staff" = [a human decision],
  the parsing layer only captures + flags and does not decide inclusion/exclusion; UNSW has no years, so they stay None.
"""
from __future__ import annotations

import pathlib

import pytest

from roster.parse import parse_unsw_lines

_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "unsw_econ_our-people_raw_2026-06-29.txt"

_SKIP_NO_FIXTURE = ("archived staff-page fixture not in the public package "
                    "(it holds real names; kept in the private archive)")


@pytest.fixture(scope="module")
def raw_text() -> str:
    if not _FIXTURE.is_file():
        pytest.skip(_SKIP_NO_FIXTURE)
    return _FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parsed(raw_text):
    return parse_unsw_lines(raw_text)


# ===========================================================================
# Count: exactly 53 people
# ===========================================================================
def test_parses_exactly_53_people(parsed):
    """Exactly 53 people (UNSW current = "Showing 53 out of 53 results"; comment/statistics lines do not count)."""
    assert len(parsed) == 53


def test_every_record_has_full_field_set(parsed):
    """Each record has exactly this set of fields (the UNSW intermediate-form schema).

    Reuses the Monash 8-field base (year_start/year_end/is_emeritus/center kept as columns for alignment),
    and adds the UNSW-specific is_visiting / is_postdoc. More or fewer counts as parsing drift.
    """
    expected = {
        "display_name", "email", "title_raw",
        "year_start", "year_end",
        "is_visiting", "is_emeritus", "is_postdoc",
        "is_adjunct", "center",
    }
    for rec in parsed:
        assert set(rec.keys()) == expected, f"field set mismatch: {rec}"


# ===========================================================================
# UNSW has no years -> all None (red line #3: never guess)
# ===========================================================================
def test_all_years_are_none(parsed):
    """The UNSW page gives no years -> every person has year_start / year_end == None (never fill in placeholder numbers)."""
    for rec in parsed:
        assert rec["year_start"] is None, f"{rec['display_name']} year_start should be None"
        assert rec["year_end"] is None, f"{rec['display_name']} year_end should be None"


# ===========================================================================
# Flags are correct (counted from the real archive)
# ===========================================================================
def test_visiting_count_and_members(parsed):
    """visiting=3: Person S / Person Q1 / Person Q2 (flag:visiting)."""
    visiting = [r["display_name"] for r in parsed if r["is_visiting"]]
    assert len(visiting) == 3
    assert "Person S" in visiting
    assert "Person Q1" in visiting
    assert "Person Q2" in visiting


def test_emeritus_count_and_member(parsed):
    """emeritus=1: Person Q3 (Emeritus Professor + flag:emeritus)."""
    emeriti = [r["display_name"] for r in parsed if r["is_emeritus"]]
    assert len(emeriti) == 1
    assert "Person Q3" in emeriti


def test_postdoc_count_and_members(parsed):
    """postdoc=5: 5 people."""
    postdocs = [r["display_name"] for r in parsed if r["is_postdoc"]]
    assert len(postdocs) == 5
    for n in ("Person T", "Person U", "Person V",
              "Person W", "Person X"):
        assert n in postdocs, f"{n} should be flagged postdoc"


def test_emeritus_detected_from_title_text_too(parsed):
    """The emeritus flag must recognise the title text ("Emeritus Professor") - Person Q3's title contains Emeritus."""
    w = next(r for r in parsed if r["display_name"] == "Person Q3")
    assert w["is_emeritus"] is True
    assert "Emeritus" in w["title_raw"]


def test_visiting_detected_from_title_text_too(parsed):
    """The visiting flag must recognise the title text ("Visiting ...") - Person Q1's title contains Visiting."""
    k = next(r for r in parsed if r["display_name"] == "Person Q1")
    assert k["is_visiting"] is True
    assert "Visiting" in k["title_raw"]


def test_non_flagged_person_all_flags_false(parsed):
    """A regular on-staff professor (Person Q4) has all three flags False."""
    h = next(r for r in parsed if r["display_name"] == "Person Q4")
    assert h["is_visiting"] is False
    assert h["is_emeritus"] is False
    assert h["is_postdoc"] is False


# ===========================================================================
# display_name is clean (bracketed role / 3-part lines do not pollute it)
# ===========================================================================
def test_display_name_clean_with_parenthetical_role(parsed):
    """For people with a bracketed role display_name stays clean (the role stays in title_raw, not in display_name).

    <First> <Last> ... | Professor  and  <First> <Middle> <Last> | Associate Professor (Associate Director).
    """
    names = {r["display_name"] for r in parsed}
    assert "Person Y" in names
    assoc_director = next(r for r in parsed if r["display_name"] == "Person Y")
    assert "Associate Director" in assoc_director["title_raw"]   # the role is in the title, not in the name


def test_three_segment_line_does_not_crash(parsed):
    """A 3-part line (Person Q5 | Aust. Laureate Fellow (ARC) | Professor) does not crash.

    The 3rd part "Professor" is not a year/center/flag -> it does not enter the structured fields and is not taken as a year; title_raw = the 2nd part.
    """
    laureate = next(r for r in parsed if r["display_name"] == "Person Q5")
    assert laureate["year_start"] is None and laureate["year_end"] is None
    assert "Laureate" in laureate["title_raw"]
    assert laureate["center"] is None


def test_no_comment_or_stats_lines_as_people(parsed):
    """Comment lines (#...) / separator lines never enter the list (display_name contains none of '#' / '===' / 'PAGE')."""
    for r in parsed:
        assert not r["display_name"].startswith("#")
        assert "===" not in r["display_name"]
        assert "PAGE" not in r["display_name"]
        assert r["display_name"].strip() == r["display_name"]  # no leading or trailing whitespace


def test_postdoc_titles_vary_but_all_flagged(parsed):
    """The postdoc title text varies ("Postdoctoral Fellow" / "Post-Doc Fellow") but all are matched through flag:postdoc."""
    pd_a = next(r for r in parsed if r["display_name"] == "Person U")    # "Post-Doc Fellow"
    pd_b = next(r for r in parsed if r["display_name"] == "Person T")    # "Postdoctoral Fellow"
    assert pd_a["is_postdoc"] is True
    assert pd_b["is_postdoc"] is True
