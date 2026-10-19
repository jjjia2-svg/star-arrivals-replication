"""U0.5 driver TDD - build_roster_rows joins parse + align verdicts into Table B rows + a statistics sidecar.

Tests the pure assembly logic (offline, fed a stub aligner - no real API calls): given 92 parsed records + a name -> verdict
lookup table, build_roster_rows produces (rows, summary). Checks:
  - number of rows == number of parsed records (one row per person, none lost);
  - the summary counts are right (matched / needs_human);
  - a needs_human person has author_id=None and is in the needs_author list;
  - the Yves Zenou hit row has author_id=A5017376589.

Hard rules: one row per person, none silently dropped; needs_human goes into the sidecar; author_id is bare.
"""
from __future__ import annotations

import pathlib

import pytest

from roster.parse import parse_roster_lines
from roster.run_u0p5 import build_roster_rows

_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "monash_econ_pure_raw_2026-06-29.txt"

_SKIP_NO_FIXTURE = ("archived staff-page fixture not in the public package "
                    "(it holds real names; kept in the private archive)")


@pytest.fixture(scope="module")
def parsed():
    if not _FIXTURE.is_file():
        pytest.skip(_SKIP_NO_FIXTURE)
    return parse_roster_lines(_FIXTURE.read_text(encoding="utf-8"))


def _stub_aligner_factory(name_to_verdict):
    """Build a stub aligner: (name) -> verdict (lookup table; missing -> needs_human)."""
    def _align(display_name, *, api_key=None):
        return dict(name_to_verdict.get(
            display_name, {"author_id": None, "confidence": None, "needs_human": True}
        ))
    return _align


def test_build_rows_one_per_person(parsed):
    """Number of rows is exactly == number of parsed records (92, one per person, none lost)."""
    stub = _stub_aligner_factory({})   # all needs_human
    rows, summary = build_roster_rows(parsed, aligner=stub)
    assert len(rows) == len(parsed) == 92


def test_summary_counts_consistent(parsed):
    """summary: matched + needs_human == total; length of the needs_author list == needs_human count."""
    verdicts = {
        "Yves Zenou": {"author_id": "A5017376589", "confidence": "low", "needs_human": False},
        "Person R": {"author_id": "A111", "confidence": "high", "needs_human": False},
    }
    stub = _stub_aligner_factory(verdicts)
    rows, summary = build_roster_rows(parsed, aligner=stub)
    assert summary["parsed_count"] == 92
    assert summary["author_id_matched"] == 2
    assert summary["needs_human_count"] == 90
    assert summary["author_id_matched"] + summary["needs_human_count"] == 92
    assert len(summary["needs_author"]) == 90


def test_zenou_row_matched(parsed):
    """The Yves Zenou hit row has author_id=A5017376589 + zenou_matched=True + the right zenou_id."""
    verdicts = {"Yves Zenou": {"author_id": "A5017376589", "confidence": "low", "needs_human": False}}
    stub = _stub_aligner_factory(verdicts)
    rows, summary = build_roster_rows(parsed, aligner=stub)
    z = next(r for r in rows if r["display_name"] == "Yves Zenou")
    assert z["author_id"] == "A5017376589"
    assert summary["zenou_matched"] is True
    assert summary["zenou_id"] == "A5017376589"


def test_needs_human_rows_have_none_id(parsed):
    """A needs_human person has author_id=None and their name is in the needs_author list."""
    stub = _stub_aligner_factory({})
    rows, summary = build_roster_rows(parsed, aligner=stub)
    for r in rows:
        assert r["author_id"] is None
    assert "Yves Zenou" in summary["needs_author"]
    assert set(summary["needs_author"]) == {r["display_name"] for r in parsed}


def test_adjunct_emeritus_counts_in_summary(parsed):
    """The summary carries adjunct/emeritus counts (captured + flagged as is; whether they are on staff = [a human decision], not decided here)."""
    stub = _stub_aligner_factory({})
    rows, summary = build_roster_rows(parsed, aligner=stub)
    assert summary["adjunct_count"] == 11
    assert summary["emeritus_count"] == 2


# ── A14: the step 7 star-anchor fragment list must be asserted non-empty before building the SQL IN clause (offline) ────────────────
def test_star_frag_in_list_empty_halts_with_zenou_id():
    """A14: empty star_frags = the golden-test star Yves Zenou is not in person_map (the worst missed-person scenario) ->
    HALT clearly with the Yves Zenou id, never build `author_id IN ()` that makes duckdb throw an obscure ParserException."""
    from roster.run_u0p5 import _star_frag_in_list
    from roster.golden import ZENOU_AUTHOR_ID

    with pytest.raises(RuntimeError) as e:
        _star_frag_in_list([])
    assert ZENOU_AUTHOR_ID in str(e.value), "HALT on empty star_frags must carry the Yves Zenou id (gold-standard anchor missing)"


def test_star_frag_in_list_nonempty_builds_sorted_quoted_in_clause():
    """Non-empty -> quoted + sorted fragment list (byte-for-byte identical to the original implementation ",".join(f"'{f}'" for f in sorted(...)))."""
    from roster.run_u0p5 import _star_frag_in_list

    assert _star_frag_in_list(["A2", "A10", "A1"]) == "'A1','A10','A2'"
