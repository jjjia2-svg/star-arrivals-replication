"""TDD red tests for U0 departure_rule.py.

Guards the interface contract:
  - C.5: detect_departure = orcid_end_date + 4 years of zero authorship (legacy_depart_rule).
  - detect_departure(per_work_timeline_canonical, inst_id, truth_dates) -> int|None
  - truth_dates: dict|None, structure {"arrivals":{inst_id:year}, "exits":{inst_id:year}}
    (externally scraped; only consumed, never fetched or fed back).
  - per_work_timeline_canonical reuses arrival_rule's P-3 input-structure contract
    (each entry {work_id, publication_year, canonical_inst_ids}).
  - identity rule: no IO / no network / no state; the thresholds are read only from RED["arrival"]["legacy_depart_rule"].

Rule (RED["arrival"]["legacy_depart_rule"]):
  orcid_end_date: true          -> if truth_dates.exits has an exit year for that inst, take it as the departure year
  zero_authorship_years: 4      -> otherwise: 4 consecutive years of zero authorship after the inst's last active year = departure

Plain words:
  detect_departure = the year a person left an institution. The employment end year from ORCID / truth data comes first;
  if there is none, look for "no paper at that institution for 4 consecutive years after the last publication there" -> departed.

These tests are purely local, with no network and no data fetching. For the threshold (4) they test only "read from RED / None -> raise" and do not hard-code it.
"""
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common._redlines import RED, RedlineUnsigned  # noqa: E402
from identity import departure_rule  # noqa: E402

INST = "I56590836"   # Monash bare
OTHER = "I161593684" # Stockholm bare


def _w(year, inst_ids):
    """Build one per_work_timeline_canonical entry (following the P-3 contract, 3 keys)."""
    return {"work_id": f"W{year}", "publication_year": year, "canonical_inst_ids": inst_ids}


# ============ ORCID/truth first: truth_dates.exits hit -> take that exit year ============

def test_departure_uses_orcid_exit_when_present():
    # orcid_end_date=true and truth_dates.exits has that inst -> take the exit year directly
    timeline = [_w(2010, [INST]), _w(2011, [INST])]
    truth = {"arrivals": {}, "exits": {INST: 2015}}
    assert departure_rule.detect_departure(timeline, INST, truth) == 2015


def test_departure_orcid_exit_for_other_inst_ignored():
    # truth_dates.exits has only other insts -> not used; fall back to the zero-authorship rule
    timeline = [_w(2010, [INST]), _w(2011, [INST])]
    truth = {"arrivals": {}, "exits": {OTHER: 2015}}
    # the inst's last active year is 2011 and no year follows -> less than the 4-year window -> not departed, None
    assert departure_rule.detect_departure(timeline, INST, truth) is None


# ============ 4-year zero-authorship rule (fallback when there is no ORCID exit year) ============

def test_departure_zero_authorship_four_years():
    # the inst's last active year is 2010; 2011..2014 are 4 consecutive years elsewhere (zero authorship at INST) -> departed
    timeline = [
        _w(2009, [INST]), _w(2010, [INST]),
        _w(2011, [OTHER]), _w(2012, [OTHER]), _w(2013, [OTHER]), _w(2014, [OTHER]),
    ]
    truth = {"arrivals": {}, "exits": {}}
    # departure year = the year after the last active year (2011): 4 consecutive zero-authorship years reached
    assert departure_rule.detect_departure(timeline, INST, truth) == 2011


def test_departure_not_enough_zero_years_returns_none():
    # last active 2010, afterwards only 2011..2013 (3 years) of zero authorship -> less than 4 years -> None
    timeline = [
        _w(2010, [INST]),
        _w(2011, [OTHER]), _w(2012, [OTHER]), _w(2013, [OTHER]),
    ]
    truth = {"arrivals": {}, "exits": {}}
    assert departure_rule.detect_departure(timeline, INST, truth) is None


def test_departure_still_active_returns_none():
    # published at that inst throughout, no 4-year gap -> not departed, None
    timeline = [_w(y, [INST]) for y in range(2010, 2020)]
    truth = {"arrivals": {}, "exits": {}}
    assert departure_rule.detect_departure(timeline, INST, truth) is None


def test_departure_never_at_inst_returns_none():
    # never published at that inst -> no departure to speak of, None
    timeline = [_w(2010, [OTHER]), _w(2011, [OTHER])]
    truth = {"arrivals": {}, "exits": {}}
    assert departure_rule.detect_departure(timeline, INST, truth) is None


def test_departure_truth_dates_none_falls_back_to_zero_authorship():
    # truth_dates=None -> go straight to the zero-authorship rule (no crash)
    timeline = [
        _w(2010, [INST]),
        _w(2011, [OTHER]), _w(2012, [OTHER]), _w(2013, [OTHER]), _w(2014, [OTHER]),
    ]
    assert departure_rule.detect_departure(timeline, INST, None) == 2011


# ============ thresholds are read only from RED + None -> raise (unset-threshold rule) ============

def test_departure_reads_window_from_red(monkeypatch):
    # set zero_authorship_years to 2 -> a 2-year gap after the last active year 2010 already means departure
    monkeypatch.setitem(RED["arrival"]["legacy_depart_rule"], "zero_authorship_years", 2)
    timeline = [_w(2010, [INST]), _w(2011, [OTHER]), _w(2012, [OTHER])]
    assert departure_rule.detect_departure(timeline, INST, None) == 2011


def test_departure_raises_when_window_unsigned(monkeypatch):
    # zero_authorship_years = None (unset) -> raise, never silently default to 4
    monkeypatch.setitem(RED["arrival"]["legacy_depart_rule"], "zero_authorship_years", None)
    timeline = [_w(2010, [INST]), _w(2011, [OTHER])]
    with pytest.raises(RedlineUnsigned):
        departure_rule.detect_departure(timeline, INST, None)


def test_departure_raises_when_orcid_flag_unsigned(monkeypatch):
    # orcid_end_date = None (unset) -> raise (whether to trust the ORCID exit year is a rule; not decided here)
    monkeypatch.setitem(RED["arrival"]["legacy_depart_rule"], "orcid_end_date", None)
    timeline = [_w(2010, [INST])]
    truth = {"arrivals": {}, "exits": {INST: 2015}}
    with pytest.raises(RedlineUnsigned):
        departure_rule.detect_departure(timeline, INST, truth)


# ============ P-3 input-structure contract (reused from arrival_rule, guards against a falsely passing fixture) ============

def test_departure_rejects_affiliations_years_field():
    # forbidden field affiliations_years (contaminates the rule that affiliations.years is untrusted) -> raise, never silently accepted
    bad = [{
        "work_id": "W1", "publication_year": 2010,
        "canonical_inst_ids": [INST], "affiliations_years": [1998],
    }]
    with pytest.raises(ValueError):
        departure_rule.detect_departure(bad, INST, None)


def test_departure_rejects_descending_year_order():
    # not ascending -> raise (P-3 contract)
    bad = [_w(2012, [INST]), _w(2010, [INST])]
    with pytest.raises(ValueError):
        departure_rule.detect_departure(bad, INST, None)


def test_departure_empty_timeline_returns_none():
    assert departure_rule.detect_departure([], INST, None) is None


def test_departure_inst_id_none_raises():
    # inst_id is None = a caller bug -> raise
    timeline = [_w(2010, [INST])]
    with pytest.raises((ValueError, TypeError)):
        departure_rule.detect_departure(timeline, None, None)
