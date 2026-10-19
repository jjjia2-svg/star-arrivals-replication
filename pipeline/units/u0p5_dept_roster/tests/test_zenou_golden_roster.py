"""U0.5 step 4, Yves Zenou golden slice - the roster side must pass (hard requirement).

Slice assertions (the roster-layer part):
  ① Yves Zenou is in the parsed roster (can be found) -> the parser in step ① is already tested, here the real archive is reused end to end.
  ② Yves Zenou -> A5017376589 (author_id alignment):
       - offline: feed a fixture single-hit response -> classify gives A5017376589.
       - LIVE (@pytest.mark.live, runs only with --run-live): a real OpenAlex institution-restricted search -> A5017376589.
  ③ dept_key=monash_econ + in Table B (the Table B row carries Yves Zenou + the department key).
  ④ arrival_year is not in this table; never use Pure's 1995 or affiliations.years as arrival ->
       the Table B year_start=1995 is only the start of the Pure publication interval, with the note 'arrival 2016 to be verified by U1 works + modal-institution method (red line #3)'.

Hard rules: author_id maps to A5017376589 (bare); Table B has no arrival column; 1995 != arrival;
  institution = Monash I56590836 (not Sydney/Stockholm or other parallel institutions, U0 golden anchor MONASH_CANONICAL_ID).
"""
from __future__ import annotations

import os
import pathlib

import pytest

from identity.golden import MONASH_CANONICAL_ID
from roster.parse import parse_roster_lines
from roster.align import classify_match, search_author, MONASH_INST_ID
from roster.table_b import to_table_b_row, DEPT_KEY
from roster.golden import zenou_slice_note, ZENOU_AUTHOR_ID, ZENOU_NAME

_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "monash_econ_pure_raw_2026-06-29.txt"

_SKIP_NO_FIXTURE = ("archived staff-page fixture not in the public package "
                    "(it holds real names; kept in the private archive)")


@pytest.fixture(scope="module")
def parsed():
    if not _FIXTURE.is_file():
        pytest.skip(_SKIP_NO_FIXTURE)
    return parse_roster_lines(_FIXTURE.read_text(encoding="utf-8"))


# ===========================================================================
# Anchor constants
# ===========================================================================
def test_zenou_anchor_constants():
    """Ground-truth anchor for Yves Zenou: A5017376589 + name; Monash canonical = I56590836 (= the U0 golden anchor)."""
    assert ZENOU_AUTHOR_ID == "A5017376589"
    assert ZENOU_NAME == "Yves Zenou"
    assert MONASH_CANONICAL_ID == "I56590836"
    assert MONASH_INST_ID == MONASH_CANONICAL_ID   # the university-level institution id matches the golden anchor


# ===========================================================================
# ① can be found (end to end: real archive -> parser)
# ===========================================================================
def test_zenou_found_in_parsed_roster(parsed):
    z = [r for r in parsed if r["display_name"] == ZENOU_NAME]
    assert len(z) == 1, "Yves Zenou must appear exactly once in the parsed list (gold standard 1: findable)"


# ===========================================================================
# ② author_id -> A5017376589 (offline classify; institution-restricted single hit)
# ===========================================================================
def test_zenou_aligns_to_a5017376589_offline():
    """Feed an institution-restricted single-hit response -> classify gives bare A5017376589 (golden test ②)."""
    results = [{"id": "https://openalex.org/A5017376589", "display_name": "Yves Zenou"}]
    out = classify_match(results, used_institution_filter=True)
    assert out["author_id"] == ZENOU_AUTHOR_ID
    assert out["needs_human"] is False


# ===========================================================================
# ③ dept_key=monash_econ + in Table B
# ===========================================================================
def test_zenou_row_in_table_b(parsed):
    """Yves Zenou is written to Table B: dept_key=monash_econ + author_id=A5017376589 + the right name."""
    z_parsed = next(r for r in parsed if r["display_name"] == ZENOU_NAME)
    verdict = {"author_id": ZENOU_AUTHOR_ID, "confidence": "high", "needs_human": False}
    row = to_table_b_row(z_parsed, verdict)
    assert row["dept_key"] == DEPT_KEY == "monash_econ"
    assert row["author_id"] == ZENOU_AUTHOR_ID
    assert row["display_name"] == ZENOU_NAME


# ===========================================================================
# ④ arrival_year is not in this table; 1995/affiliations.years is never used as arrival
# ===========================================================================
def test_table_b_has_no_arrival_column(parsed):
    """The Table B schema has no arrival column - arrival is never written into this table (red line #3)."""
    z_parsed = next(r for r in parsed if r["display_name"] == ZENOU_NAME)
    verdict = {"author_id": ZENOU_AUTHOR_ID, "confidence": "high", "needs_human": False}
    row = to_table_b_row(z_parsed, verdict)
    for k in row.keys():
        assert "arrival" not in k.lower()


def test_zenou_year_start_is_pub_1995_not_arrival(parsed):
    """Yves Zenou's year_start=1995 is the start of the Pure publication interval, not the arrival (arrival=2016 is judged separately)."""
    z_parsed = next(r for r in parsed if r["display_name"] == ZENOU_NAME)
    assert z_parsed["year_start"] == 1995          # start of the Pure interval
    verdict = {"author_id": ZENOU_AUTHOR_ID, "confidence": "high", "needs_human": False}
    row = to_table_b_row(z_parsed, verdict)
    assert row["year_start"] == 1995
    # 1995 is never equal to the arrival 2016:
    assert row["year_start"] != 2016


def test_zenou_slice_note_flags_arrival_pending():
    """The slice note must state: arrival 2016 is to be verified by U1 works + the modal-institution method (red line #3); never use 1995/affiliations.years."""
    note = zenou_slice_note()
    assert note["arrival_year_authoritative"] is False     # this table gives no authoritative arrival
    assert note["arrival_year_hint"] == 2016               # only a hint, to be verified
    assert note["arrival_pending_unit"] == "U1"            # to be verified by U1 works + the modal-institution method
    assert note["never_use_pure_year_as_arrival"] is True
    assert note["never_use_affiliations_years"] is True    # red line #3
    assert note["pure_year_start"] == 1995                 # states clearly that 1995 is a Pure publication year


# ===========================================================================
# ② LIVE: real OpenAlex -> Yves Zenou must map to A5017376589 (runs only with --run-live)
# ===========================================================================
@pytest.mark.live
def test_zenou_aligns_to_a5017376589_LIVE():
    """Real OpenAlex institution-restricted search for Yves Zenou -> must map to A5017376589 (golden test ②, truly live)."""
    api_key = os.environ.get("OPENALEX_API_KEY")
    verdict = search_author(ZENOU_NAME, api_key=api_key)
    assert verdict["author_id"] == ZENOU_AUTHOR_ID, (
        f"Yves Zenou must map to {ZENOU_AUTHOR_ID}, got {verdict}"
    )
    assert verdict["needs_human"] is False
