"""M7a-T6 evidence assembly — roster (table B) / wayback supply → the six-source input of truth_dates (step 15, S8-5).

In plain words: truth_dates.select_truth_date takes a {source: year} dict, but nothing assembled "each star's evidence" into this
input. This layer does the assembly: table B human_verified year_start → official_roster tier; wayback on-roll snapshots
→ wayback tier; orcid/arc = later increments (not scraped, explicitly None). The six source names follow RED.arrival.source_priority
verbatim; a seventh source is never invented.
"""
import pytest

from common._redlines import RED


def _priority():
    return list(RED["arrival"]["source_priority"])


# ---- roster (table B) → official_roster tier -------------------------------------

def test_roster_evidence_takes_human_verified_year():
    """Zenou case: 1995 (low / unchecked, polluted back-fill) vs 2016 (high / manually checked) → official_roster tier = 2016."""
    from m7a_star.evidence_assembly import roster_arrival_evidence
    rows = [
        {"year_start": 1995, "confidence": "low", "human_verified": False},
        {"year_start": 2016, "confidence": "high", "human_verified": True},
    ]
    assert roster_arrival_evidence(rows) == 2016


def test_roster_evidence_requires_human_verified():
    """None manually checked → None (a strong tier must have a manual-check anchor; an unchecked roster year never passes as literature-grade evidence;
    official_roster = table B human_verified year_start)."""
    from m7a_star.evidence_assembly import roster_arrival_evidence
    rows = [
        {"year_start": 2005, "confidence": "high", "human_verified": False},
        {"year_start": 2011, "confidence": "low", "human_verified": False},
    ]
    assert roster_arrival_evidence(rows) is None


def test_roster_evidence_all_null_year_is_none():
    """Manually checked but year_start all empty (the UNSW batch) → None (no true date → no strong tier, explicit fallback)."""
    from m7a_star.evidence_assembly import roster_arrival_evidence
    rows = [{"year_start": None, "confidence": "high", "human_verified": True}]
    assert roster_arrival_evidence(rows) is None


def test_roster_evidence_same_tiebreak_as_pick_arrival_year():
    """Several manually checked rows → the same tie-break as run_u4.pick_arrival_year (one implementation prevents the rule drifting, lesson B5):
    high confidence first, then the earliest year."""
    from m7a_star.evidence_assembly import roster_arrival_evidence
    from run_u4 import pick_arrival_year
    rows = [
        {"year_start": 2015, "confidence": "high", "human_verified": True},
        {"year_start": 2012, "confidence": "high", "human_verified": True},
        {"year_start": 2010, "confidence": "low", "human_verified": True},
    ]
    assert roster_arrival_evidence(rows) == pick_arrival_year(rows) == 2012


# ---- wayback on-roll snapshot → wayback tier ------------------------------------------

def test_wayback_evidence_earliest_snapshot_year():
    """Snapshot years in which the person is on the department-page list {2007, 2009} → take the earliest, 2007 (earliest on-roll = upper-bound anchor of arrival)."""
    from m7a_star.evidence_assembly import wayback_arrival_evidence
    hits = [{"snapshot_year": 2009}, {"snapshot_year": 2007}]
    assert wayback_arrival_evidence(hits) == 2007


def test_wayback_evidence_empty_is_none():
    """No on-roll snapshot → None (no evidence, nothing forged)."""
    from m7a_star.evidence_assembly import wayback_arrival_evidence
    assert wayback_arrival_evidence([]) is None


def test_wayback_evidence_null_year_raises():
    """On-roll row missing snapshot_year → raise loudly (the parser output is broken; never skip silently)."""
    from m7a_star.evidence_assembly import wayback_arrival_evidence
    with pytest.raises(ValueError):
        wayback_arrival_evidence([{"snapshot_year": None}])


# ---- assembly: supply from each tier → select_truth_date input ---------------------------------

def test_assemble_evidence_buckets_by_signed_source_names():
    """roster 2016 + wayback 2015 → {official_roster: 2016, wayback: 2015};
    fed to select_truth_date, which takes wayback (2015) by the fixed priority. orcid/arc not scraped → absent."""
    from m7a_star.evidence_assembly import assemble_arrival_evidence
    from m7a_star.truth_dates import select_truth_date
    ev = assemble_arrival_evidence(
        roster_rows=[{"year_start": 2016, "confidence": "high", "human_verified": True}],
        wayback_rows=[{"snapshot_year": 2015}],
    )
    assert ev == {"official_roster": 2016, "wayback": 2015}
    hit = select_truth_date(ev, _priority())
    assert hit["arrival_source"] == "wayback"
    assert hit["arrival_year"] == 2015
    assert hit["arrival_evidence_strength"] == "strong"


def test_assemble_evidence_orcid_arc_increment_slots():
    """orcid/arc later increments: a tier is included only when a year is given explicitly, and the names follow the fixed six sources (orcid_employment/arc)."""
    from m7a_star.evidence_assembly import assemble_arrival_evidence
    from m7a_star.truth_dates import select_truth_date
    ev = assemble_arrival_evidence(orcid_employment_year=2016, arc_year=2017)
    assert ev == {"orcid_employment": 2016, "arc": 2017}
    # orcid_employment has the highest priority → it is the one hit
    assert select_truth_date(ev, _priority())["arrival_source"] == "orcid_employment"


def test_assemble_evidence_nothing_supplied_is_empty():
    """No evidence at all → {} → select_truth_date returns None (the caller falls back to the modal_shift inferred tier)."""
    from m7a_star.evidence_assembly import assemble_arrival_evidence
    from m7a_star.truth_dates import select_truth_date
    ev = assemble_arrival_evidence()
    assert ev == {}
    assert select_truth_date(ev, _priority()) is None
