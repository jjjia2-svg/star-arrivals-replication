"""M7a-T7 arrival_departure — arrival-year assembly: call detect_arrival/departure + assemble the 11 EVENTS columns.

In plain words: feed the cleaned timeline to detect_arrival (modal-institution method + 2-year persistence window) to get the arrival year, then assemble
one EVENTS row (11 columns): arrival year / t-1 / arrival source + strength / old main institution exited / exit year, etc.

Assembly order is a hard rule: pollution_guard cleaning first (drop fake Australian years) → detect_arrival second. Otherwise a fake 2003 Monash
would make Monash no longer "brand new" in 2016 (detect_arrival's arrival = a switch to a brand-new institution) → the true arrival is missed.

Fixed rules: detect_arrival/departure criteria are all fixed (#3 modal-institution method / 2-year window / never trust affiliations.years);
EVENTS schema [23] 11 columns; strength strong/modal_shift mapping (S8-5).
"""
from common.schema import EVENTS, assert_matches_schema


def _zenou_clean_timeline():
    """Cleaned Zenou timeline (fake Monash years already removed by pollution_guard): IFN Stockholm until 2014, Monash 2016+."""
    tl = [{"work_id": f"W{y}", "publication_year": y, "canonical_inst_ids": ["I77432436"]}
          for y in [2001, 2002, 2003, 2004, 2010, 2013, 2014]]
    tl += [{"work_id": f"W{y}", "publication_year": y, "canonical_inst_ids": ["I56590836"]}
           for y in [2016, 2017, 2018]]
    return tl


def test_zenou_clean_timeline_arrival_2016():
    """Cleaned timeline: Monash persists from 2016 → arrival 2016, destination Monash."""
    from identity.arrival_rule import detect_arrival
    arr = detect_arrival(_zenou_clean_timeline())
    assert arr["arrival_year"] == 2016
    assert arr["arrival_institution"] == "I56590836"


def test_uncleaned_fake_monash_breaks_arrival():
    """Counter-example (documentation): without cleaning, a fake 2003 Monash → Monash is no longer 'brand new' in 2016 → 2016 missed.
    This shows pollution_guard cleaning is a precondition for a correct arrival year (assembly cleans first, then detects)."""
    from identity.arrival_rule import detect_arrival
    dirty = _zenou_clean_timeline() + [
        {"work_id": "W2003f", "publication_year": 2003, "canonical_inst_ids": ["I56590836"]}]
    dirty.sort(key=lambda x: x["publication_year"])
    assert detect_arrival(dirty)["arrival_year"] != 2016


def test_assemble_event_matches_events_schema():
    """Assemble one EVENTS row = the 11 columns of schema [23]; t-1 / exit year / evidence source are right."""
    from identity.arrival_rule import detect_arrival
    from m7a_star.arrival_departure import assemble_event
    arr = detect_arrival(_zenou_clean_timeline())
    ev = assemble_event(
        star_person_id="A5017376589", arrival=arr, dept_id="I56590836",
        truth_hit={"arrival_source": "official_roster", "arrival_evidence_strength": "strong"},
        departed_year=2015, modal_inst_year=True,
    )
    assert_matches_schema(ev.keys(), EVENTS, label="events")
    assert ev["arrival_year"] == 2016 and ev["t_minus_1"] == 2015
    assert ev["arrival_source"] == "official_roster" and ev["arrival_evidence_strength"] == "strong"
    assert ev["prior_main_exited"] is True and ev["departed_year"] == 2015


def test_no_arrival_returns_none():
    """No arrival → no event (None)."""
    from m7a_star.arrival_departure import assemble_event
    arr = {"arrival_year": None, "arrival_institution": None,
           "method": "modal_institution", "sustain_window_years": 2}
    assert assemble_event(star_person_id="X", arrival=arr, dept_id="I") is None


def test_no_truth_hit_uses_inferred_source():
    """No ground-truth hit → arrival source = modal_inst_shift, strength = modal_shift (inferred tier)."""
    from m7a_star.arrival_departure import assemble_event
    arr = {"arrival_year": 2016, "arrival_institution": "I56590836",
           "method": "modal_institution", "sustain_window_years": 2}
    ev = assemble_event(star_person_id="A", arrival=arr, dept_id="I56590836")
    assert ev["arrival_source"] == "modal_inst_shift"
    assert ev["arrival_evidence_strength"] == "modal_shift"


def test_no_departure_prior_main_not_exited():
    """No exit year → prior_main_exited False, departed_year None."""
    from m7a_star.arrival_departure import assemble_event
    arr = {"arrival_year": 2016, "arrival_institution": "I",
           "method": "modal_institution", "sustain_window_years": 2}
    ev = assemble_event(star_person_id="A", arrival=arr, dept_id="I", departed_year=None)
    assert ev["prior_main_exited"] is False and ev["departed_year"] is None


# ---- End-to-end integration: dirty evidence → cleaning → build timeline → arrival (shows the assembly chain protects Zenou) --------

def _zenou_dirty_evidence():
    """Dirty evidence: IFN (non-Australian) + fake 2003 stamped Monash + fake 2005 CEPR-burst Monash + true Monash 2016+."""
    ev = [{"work_id": f"W{y}", "publication_year": y, "raw_affil": "IFN, Stockholm",
           "canonical_ids": ["I77432436"], "attributes_to_au": False}
          for y in [2001, 2002, 2004, 2010, 2013, 2014]]
    ev.append({"work_id": "W2003", "publication_year": 2003,
               "raw_affil": "Monash University - Department of Economics",
               "canonical_ids": ["I56590836"], "attributes_to_au": True})           # fake stamp
    ev.append({"work_id": "W2005", "publication_year": 2005,
               "raw_affil": "Centre for Economic Policy Research (CEPR), London",
               "canonical_ids": ["I4210140326", "I77432436", "I161593684",
                                 "I56590836", "I197518295"], "attributes_to_au": True})  # fake CEPR burst
    ev += [{"work_id": f"W{y}", "publication_year": y,
            "raw_affil": "Monash University, Clayton, Australia",
            "canonical_ids": ["I56590836"], "attributes_to_au": True}
           for y in [2016, 2017, 2018]]                                              # true Monash
    return ev


def test_zenou_end_to_end_clean_then_arrival_2016():
    """End to end: dirty evidence (fake 2003 stamp + fake 2005 CEPR burst) → clean_au removes them → build timeline → detect_arrival
    → arrival 2016 (not 2003/2005). Full proof that the assembly chain protects Zenou."""
    from m7a_star.pollution_guard import clean_au_attributions
    from m7a_star.arrival_departure import build_per_work_timeline
    from identity.arrival_rule import detect_arrival
    cleaned = clean_au_attributions(_zenou_dirty_evidence())
    assert cleaned["n_dropped"] == 2                        # one fake stamp and one fake CEPR burst removed
    timeline = build_per_work_timeline(cleaned["kept"])
    arr = detect_arrival(timeline)                          # P-3 contract timeline
    assert arr["arrival_year"] == 2016
    assert arr["arrival_institution"] == "I56590836"
