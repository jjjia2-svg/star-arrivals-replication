"""TDD red tests for U0 identity/arrival_rule.py.

Module duty: use per_work_timeline_canonical to decide arrival by "modal institution of the year +
a 2-year sustain window". All thresholds are read from RED['arrival'], nothing hard-coded in the
module; affiliations.years is never trusted.

This file covers three groups:
  A. Public input-structure contract (P-3, T34): list[dict]{work_id,publication_year,canonical_inst_ids},
     sorted by publication_year ascending; canonical_inst_ids have already passed EDUCATION_WHITELIST and
     been folded; a wrong shape raises.
  B. Modal-institution method + 2-year sustain window decide arrival (method=modal_institution /
     sustain_window_years=2).
  C. T33 Yves Zenou golden slice: the full detect_arrival flow never reads affiliations[].years; the
     Monash 1998 backfill is rejected and arrival = 2016 (guards trust_affiliations_years=false + golden items 3 and 4).

Threshold rule: thresholds are read only from RED['arrival'] (method / sustain_window_years /
trust_affiliations_years), nothing hard-coded in the module; any relevant RED key that is None -> raise
(these values are set and should never be None, and trust must really be false).
"""
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from identity import arrival_rule  # noqa: E402

# Golden anchor for Yves Zenou: bare canonical ids, not the name-bearing form.
MONASH = "I56590836"        # Yves Zenou's true arrival institution (canonical education parent)
STOCKHOLM = "I161593684"    # where this person was before arrival (moved in from here)


# ===========================================================================
# A. Public input-structure contract P-3 (T34): guards against a fixture guessing the shape and passing falsely
# ===========================================================================

def _timeline_two_year_monash():
    """Smallest valid timeline: two years at Stockholm, then two sustained years at Monash (ascending)."""
    return [
        {"work_id": "W1", "publication_year": 2014, "canonical_inst_ids": [STOCKHOLM]},
        {"work_id": "W2", "publication_year": 2015, "canonical_inst_ids": [STOCKHOLM]},
        {"work_id": "W3", "publication_year": 2016, "canonical_inst_ids": [MONASH]},
        {"work_id": "W4", "publication_year": 2017, "canonical_inst_ids": [MONASH]},
    ]


def test_input_must_be_ascending_by_publication_year():
    # T34: input not sorted by publication_year ascending -> raise (disordered input is never accepted silently, or the window test goes wrong)
    bad = [
        {"work_id": "W3", "publication_year": 2016, "canonical_inst_ids": [MONASH]},
        {"work_id": "W1", "publication_year": 2014, "canonical_inst_ids": [STOCKHOLM]},
    ]
    with pytest.raises(arrival_rule.ArrivalInputContractError):
        arrival_rule.detect_arrival(bad, truth_dates={})


def test_input_rejects_forbidden_affiliations_years_field():
    # T34 + trust_affiliations_years=false: if an input entry carries a field derived from affiliations[].years -> raise
    # (the public contract never contains affiliations.years; its presence means the rule is contaminated: fail loudly)
    bad = [
        {
            "work_id": "W1",
            "publication_year": 2014,
            "canonical_inst_ids": [STOCKHOLM],
            "affiliations": [{"institution_id": MONASH, "years": [1998]}],  # forbidden field
        },
    ]
    with pytest.raises(arrival_rule.ArrivalInputContractError):
        arrival_rule.detect_arrival(bad, truth_dates={})


def test_input_missing_required_key_raises():
    # T34: missing the required canonical_inst_ids key -> raise
    bad = [{"work_id": "W1", "publication_year": 2014}]
    with pytest.raises(arrival_rule.ArrivalInputContractError):
        arrival_rule.detect_arrival(bad, truth_dates={})


def test_input_canonical_inst_ids_must_be_list():
    # T34: canonical_inst_ids must be list[str]; a scalar -> raise
    bad = [{"work_id": "W1", "publication_year": 2014, "canonical_inst_ids": MONASH}]
    with pytest.raises(arrival_rule.ArrivalInputContractError):
        arrival_rule.detect_arrival(bad, truth_dates={})


def test_input_publication_year_must_be_int():
    # T34: publication_year must be int; a string -> raise
    bad = [{"work_id": "W1", "publication_year": "2014", "canonical_inst_ids": [STOCKHOLM]}]
    with pytest.raises(arrival_rule.ArrivalInputContractError):
        arrival_rule.detect_arrival(bad, truth_dates={})


# ===========================================================================
# B. Modal-institution method + 2-year sustain window
# ===========================================================================

def test_detects_arrival_year_on_sustained_modal_shift():
    # The modal institution switches from Stockholm to Monash and holds for 2 years -> arrival year = first Monash modal year = 2016
    result = arrival_rule.detect_arrival(_timeline_two_year_monash(), truth_dates={})
    assert result["arrival_year"] == 2016
    assert result["arrival_institution"] == MONASH


def test_single_year_blip_not_sustained_no_arrival():
    # Monash appears in only 1 year (sustain window of 2 years not met) -> no arrival (guards sustain_window_years=2)
    timeline = [
        {"work_id": "W1", "publication_year": 2014, "canonical_inst_ids": [STOCKHOLM]},
        {"work_id": "W2", "publication_year": 2015, "canonical_inst_ids": [MONASH]},   # single-year flash
        {"work_id": "W3", "publication_year": 2016, "canonical_inst_ids": [STOCKHOLM]},
        {"work_id": "W4", "publication_year": 2017, "canonical_inst_ids": [STOCKHOLM]},
    ]
    result = arrival_rule.detect_arrival(timeline, truth_dates={})
    assert result["arrival_year"] is None       # sustain window not met, no arrival


def test_per_year_modal_uses_majority_within_year():
    # One person has several works at several institutions in one year -> take that year's modal institution (core of the modal-institution method)
    timeline = [
        {"work_id": "W1", "publication_year": 2015, "canonical_inst_ids": [STOCKHOLM]},
        {"work_id": "W2", "publication_year": 2015, "canonical_inst_ids": [STOCKHOLM]},
        # 2016: Monash appears 2 times, Stockholm 1 time -> the modal institution that year = Monash
        {"work_id": "W3", "publication_year": 2016, "canonical_inst_ids": [MONASH]},
        {"work_id": "W4", "publication_year": 2016, "canonical_inst_ids": [MONASH]},
        {"work_id": "W5", "publication_year": 2016, "canonical_inst_ids": [STOCKHOLM]},
        {"work_id": "W6", "publication_year": 2017, "canonical_inst_ids": [MONASH]},
    ]
    result = arrival_rule.detect_arrival(timeline, truth_dates={})
    assert result["arrival_year"] == 2016
    assert result["arrival_institution"] == MONASH


def test_empty_timeline_no_arrival():
    result = arrival_rule.detect_arrival([], truth_dates={})
    assert result["arrival_year"] is None


# ===========================================================================
# C. T33 Yves Zenou golden slice: never read affiliations.years; reject the 1998 backfill; arrival = 2016
# ===========================================================================

def test_T33_zenou_monash_1998_backfill_rejected_arrival_is_2016():
    """T33 core: even if the external truth_dates carries a Monash 1998 affiliations.years backfill decoy,
    detect_arrival must use only the per-work modal-institution sustain window, return arrival = 2016,
    and explicitly reject 1998.

    Guards: trust_affiliations_years=false (the affiliations.years of Yves Zenou backfills Monash to
    1998, a real false positive); golden item 3 true arrival 2016 / item 4 explicit rejection of 1998.
    """
    timeline = _timeline_two_year_monash()   # per-work truth: at Monash continuously from 2016
    # truth_dates is stuffed with an affiliations.years-style 1998 backfill decoy; the function must never trust it
    poison_truth = {
        "affiliations_years": {MONASH: [1998, 1999, 2000]},   # decoy: pretends to be at Monash already in 1998
        "monash_first_affiliation_year": 1998,
    }
    result = arrival_rule.detect_arrival(timeline, truth_dates=poison_truth)
    assert result["arrival_year"] == 2016, "must report true arrival as 2016, not be misled by the 1998 backfill decoy"
    assert result["arrival_year"] != 1998, "explicitly reject the 1998 backfill (golden case 4)"
    assert result["arrival_institution"] == MONASH


def test_T33_trust_affiliations_years_redline_is_false():
    # Guard that the rule value really is false (rule anchor): RED['arrival'].trust_affiliations_years == False.
    # If it were changed to true, the premise of the whole 1998-rejection logic collapses; this test catches that drift.
    from common._redlines import RED
    assert RED["arrival"]["trust_affiliations_years"] is False


def test_T33_method_and_window_read_from_redlines_not_hardcoded():
    # Guard: thresholds are read from RED['arrival'] (method=modal_institution / sustain_window_years=2).
    from common._redlines import RED
    assert RED["arrival"]["method"] == "modal_institution"
    assert RED["arrival"]["sustain_window_years"] == 2


def test_detect_arrival_ignores_nonwhitelisted_caller_responsibility():
    # P-3 rule: that canonical_inst_ids already passed EDUCATION_WHITELIST is the caller's responsibility;
    # the function trusts that the input is already folded and filtered, and does not redo the whitelist inside (only the input structure is public).
    # This only asserts: given already-folded bare ids, it raises no error and decides normally (legitimate ids are not filtered out a second time).
    result = arrival_rule.detect_arrival(_timeline_two_year_monash(), truth_dates={})
    assert result["arrival_institution"] == MONASH
