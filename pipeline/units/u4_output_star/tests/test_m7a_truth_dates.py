"""M7a-T6 truth_dates — six-source priority selection of arrival-date evidence + evidence strength (S8-5).

In plain words: a star's "which year arrived in Australia" may have evidence from several sources (ORCID employment history / ARC funding / web archive /
department roster / modal-institution switch / first appearance in papers). Take the most reliable one by the fixed priority; literature-grade sources = strong,
inference-grade = modal_shift. No evidence returns empty (the caller then produces no strong tier).

Fixed rules: RED.arrival.source_priority fixes the six-source order; strength has a two-value domain strong/modal_shift
(mapping: the first 4 literature-grade → strong, the last 2 inference-grade → modal_shift). Never trust affiliations.years.
"""
import pytest

from common._redlines import RED


def _priority():
    return list(RED["arrival"]["source_priority"])


def test_picks_highest_priority_source():
    """wayback (higher priority) vs official_roster (lower) both have evidence → take wayback."""
    from m7a_star.truth_dates import select_truth_date
    r = select_truth_date({"official_roster": 2016, "wayback": 2015}, _priority())
    assert r["arrival_source"] == "wayback"
    assert r["arrival_year"] == 2015


def test_strong_strength_for_documentary_source():
    """Literature-grade source (official_roster) → strong."""
    from m7a_star.truth_dates import select_truth_date
    r = select_truth_date({"official_roster": 2016}, _priority())
    assert r["arrival_evidence_strength"] == "strong"


def test_modal_shift_strength_for_inferred_source():
    """Inference-grade source (modal_inst_shift) → modal_shift."""
    from m7a_star.truth_dates import select_truth_date
    r = select_truth_date({"modal_inst_shift": 2016}, _priority())
    assert r["arrival_evidence_strength"] == "modal_shift"


def test_no_evidence_returns_none():
    """No evidence at all → None (the caller then produces no strong tier and takes the fallback)."""
    from m7a_star.truth_dates import select_truth_date
    assert select_truth_date({}, _priority()) is None


def test_unknown_source_raises():
    """Evidence contains an unknown source outside the six fixed sources → raise (the gap fails loudly, not silently ignored)."""
    from m7a_star.truth_dates import select_truth_date
    with pytest.raises(ValueError):
        select_truth_date({"linkedin": 2016}, _priority())
