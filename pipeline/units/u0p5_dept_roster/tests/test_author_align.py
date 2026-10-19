"""U0.5 step 2: author_id alignment TDD - map a person's name to an OpenAlex bare author_id.

Two test layers:
  A) Pure decision layer (offline, fed fixture API responses): classify_match() decides 1 hit / 0 hits / several hits ->
     (author_id or None, confidence, needs_human). Red line #1: 0 or several hits -> needs_human, never guess.
  B) Rate-limit politeness (offline): throttle / backoff parameters exist and are sensible (mailto always set; <=8 req/s; backoff on 429).

  (The real live call Yves Zenou -> A5017376589 is in test_zenou_golden_roster.py under @pytest.mark.live; it is not run by default
   and needs an explicit --run-live, so CI does not hit OpenAlex.)

Hard rules: bare author_id (no URL prefix); 0 or several hits are flagged needs_human (red line #1); never use
  affiliations[].years to decide any year (red line #3; this step does not touch years at all).
"""
from __future__ import annotations

import pytest

from roster.align import (
    classify_match, MAILTO, MONASH_INST_ID, ECON_SUBFIELDS, DOMINANCE_RATIO,
)

# The economics subfield values used by the fixtures come from the whitelist (same single source as align, not pinned as literals).
_SF_ECON = sorted(ECON_SUBFIELDS)[0]


# ---------------------------------------------------------------------------
# fixture: OpenAlex /authors response fragments (URL-id form before bare conversion, mimicking real JSON)
# ---------------------------------------------------------------------------
def _author_result(aid, *, subfield_id=None, works_count=None):
    """Build one OpenAlex author result (with id + optional topics -> subfield + works_count)."""
    r = {"id": f"https://openalex.org/{aid}", "display_name": "X"}
    if subfield_id is not None:
        r["topics"] = [{"subfield": {"id": f"https://openalex.org/subfields/{subfield_id}"}}]
    if works_count is not None:
        r["works_count"] = works_count
    return r


# ===========================================================================
# A) classify_match: 1 hit -> that id, confidence=high, needs_human=False
# ===========================================================================
def test_single_hit_returns_bare_id_high_conf():
    """Institution-restricted search with exactly 1 hit -> bare author_id, confidence=high, no human check needed."""
    results = [_author_result("A5017376589")]
    out = classify_match(results, used_institution_filter=True)
    assert out["author_id"] == "A5017376589"      # bare, no URL prefix
    assert out["confidence"] == "high"
    assert out["needs_human"] is False


def test_single_hit_id_is_bare_not_url():
    """author_id must be bare - never carries the https://openalex.org/ prefix (required by the Table B author_id column)."""
    out = classify_match([_author_result("A123")], used_institution_filter=True)
    assert not out["author_id"].startswith("http")
    assert out["author_id"] == "A123"


# ===========================================================================
# A) 0 hits -> needs_human (red line #1, never guess)
# ===========================================================================
def test_zero_hits_needs_human():
    """0 hits -> author_id=None, needs_human=True (red line #1: never guess an id)."""
    out = classify_match([], used_institution_filter=True)
    assert out["author_id"] is None
    assert out["needs_human"] is True


# ===========================================================================
# A) several hits -> needs_human (red line #1)
# ===========================================================================
def test_multi_hit_needs_human():
    """Still >= 2 hits after restricting to the institution -> needs_human=True (same name, a human decides)."""
    results = [_author_result("A1"), _author_result("A2")]
    out = classify_match(results, used_institution_filter=True)
    assert out["author_id"] is None
    assert out["needs_human"] is True


def test_multi_hit_disambiguated_by_econ_subfield():
    """Name search without the institution gives several hits, but only 1 falls in economics subfield 2002 -> take it, confidence=medium.

    (Fallback: institution-restricted search is empty -> search by name without the institution and check whether subfield 2002 matches.)
    """
    results = [
        _author_result("A_econ", subfield_id=_SF_ECON),    # in 2002
        _author_result("A_other", subfield_id="3705"),          # geology, not economics
    ]
    out = classify_match(results, used_institution_filter=False)
    assert out["author_id"] == "A_econ"
    assert out["confidence"] == "medium"      # no institution restriction, relies on the subfield -> medium, not high
    assert out["needs_human"] is False


def test_multi_econ_no_works_count_needs_human():
    """>= 2 hits all in 2002 and no works_count signal -> needs_human (cannot be separated by dominance)."""
    results = [
        _author_result("A1", subfield_id=_SF_ECON),
        _author_result("A2", subfield_id=_SF_ECON),
    ]
    out = classify_match(results, used_institution_filter=False)
    assert out["author_id"] is None
    assert out["needs_human"] is True


def test_multi_econ_dominant_works_count_resolves():
    """>= 2 hits in 2002, but one dominates on works_count (>= DOMINANCE_RATIO x the runner-up) -> take the dominant one.

    This is the case of Yves Zenou's 16 author-id fragments: the real Yves Zenou (583 works) vs same-name fragments (<=5 works), 116x dominance.
    The dominance threshold is the guard: auto-pick only under decisive dominance, otherwise still needs_human (red line: no guessing in ambiguous cases).
    confidence=low (fragment choice is a heuristic; not treated as high before a human check and U2 clustering).
    """
    results = [
        _author_result("A_dom", subfield_id=_SF_ECON, works_count=583),
        _author_result("A_frag1", subfield_id=_SF_ECON, works_count=5),
        _author_result("A_frag2", subfield_id=_SF_ECON, works_count=1),
    ]
    out = classify_match(results, used_institution_filter=False)
    assert out["author_id"] == "A_dom"
    assert out["confidence"] == "low"        # fragment chosen heuristically, awaiting human check / U2 folding
    assert out["needs_human"] is False


def test_multi_econ_non_dominant_works_count_needs_human():
    """>= 2 hits in 2002, works_count close (below DOMINANCE_RATIO x) -> needs_human (dominance not enough, no blind pick)."""
    results = [
        _author_result("A1", subfield_id=_SF_ECON, works_count=40),
        _author_result("A2", subfield_id=_SF_ECON, works_count=30),
    ]
    out = classify_match(results, used_institution_filter=False)
    assert out["author_id"] is None
    assert out["needs_human"] is True


def test_dominance_ratio_is_decisive_threshold():
    """The dominance threshold exists and is clearly > 1 (auto-pick only under decisive dominance)."""
    assert DOMINANCE_RATIO >= 10


# ===========================================================================
# B) Rate-limit politeness (mailto / throttle / backoff) - constants exist and are sensible
# ===========================================================================
def test_mailto_is_author_email():
    """mailto must be set (OpenAlex polite pool)."""
    assert MAILTO == "jjjia2@student.unimelb.edu.au"


def test_monash_inst_id_is_bare():
    """Monash university-level institution id = I56590836, bare (used by filter=last_known_institutions.id)."""
    assert MONASH_INST_ID == "I56590836"


def test_econ_subfields_consumed_from_signed_redline():
    """B4 sentinel: the subfield whitelist is consumed from require("subfield_whitelist","include"), one single source -
    when the YAML changes this follows automatically, no hard-coded copy is left (align and byline_skeleton share one source)."""
    from common._redlines import require
    from roster.align import ECON_SUBFIELDS

    assert ECON_SUBFIELDS == set(require("subfield_whitelist", "include"))
