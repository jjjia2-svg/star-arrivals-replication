"""M7a-T7 event orchestration + arrival-year consistency hard gate.

In plain words: derive_star_event runs one star's evidence rows through the full chain: pollution_guard cleaning (drop fake Australian years)
→ build_per_work_timeline → detect_arrival (U0 modal-institution method) / detect_departure (old main institution exit)
→ select_truth_date (evidence tier) → assemble_event builds the 11 EVENTS columns.
arrival_consistency_diff is the most important new gate in this wave: for stars about to ship (is_star_5pct ∧ is_foreign_poach),
events.arrival_year (detect_arrival route) must equal the frozen star_set.arrival (pick_arrival_year route,
fingerprint bound) person by person; if not → a difference report (who / which year each route says / evidence); the code never picks a route by itself — a human decides at the identification layer.

Zenou gold-standard fixture (checks #33-#37 one by one):
  #33 dept_id == MONASH_CANONICAL_ID (I56590836, not Sydney);
  #34 arrival ∈ ZENOU_STRUCTURAL.arrival_year_range=(2015,2017) closed interval, rejects the 1998 back-fill;
  #35 prior_main_exited == True (old main IFN I77432436 exited, as judged by detect_departure);
  #36 the fixture contains 1998/2003/2006 stamped + 2005 CEPR fake Monash years → after cleaning no pre-2015 arrival is produced;
  #37 same fixture → the "never in Australia before" judgement does not lose the poaching eligibility because of fake Australian years (printed true affiliations are kept).
"""
import pytest

from identity.golden import MONASH_CANONICAL_ID, ZENOU_STRUCTURAL


# ---- Zenou fixture (S8-7 both directions; shape follows the pollution_guard/clean_au_attributions arguments) ----
# The #36 fixture shape: overseas history = IFN as the single old main institution (same source as the U3/T7 synthetic fixture for #34),
# + 1998/2003/2006 stamped fake Monash + 2005 CEPR explosion + true Monash 2016-2018.
# Note: a multi-hop prior history (Southampton→IFN→Monash) makes detect_arrival (the "first" persistent switch) pick
#   the earlier move — that is a design gap at the identification layer; it is not worked around inside the fixture, a separate documentation test pins the behaviour and it is escalated for a human decision.

IFN = "I77432436"          # old main institution Stockholm/IFN (institutions table present, check #35)
SOTON = "I200000001"       # Southampton (GB, printed true affiliation, used by the #37 fixture)
GAINS = "I200000002"       # GAINS (FR, printed true affiliation, used by the #37 fixture)


def _zenou_dirty_evidence():
    """#36 fixture as specified: true IFN overseas history + 1998/2003/2006 stamped fake Monash
    + 2005 CEPR explosion (Monash caught up in it) + true Monash 2016-2018."""
    ev = [{"work_id": f"W{y}", "publication_year": y, "raw_affil": "IFN, Stockholm",
           "canonical_ids": [IFN], "attributes_to_au": False}
          for y in [2001, 2002, 2004, 2010, 2013, 2014]]
    for y in (1998, 2003, 2006):                                         # stamped fake Monash
        ev.append({"work_id": f"W{y}f", "publication_year": y,
                   "raw_affil": "Monash University - Department of Economics",
                   "canonical_ids": ["I56590836"], "attributes_to_au": True})
    ev.append({"work_id": "W2005f", "publication_year": 2005,           # CEPR parse explosion
               "raw_affil": "Centre for Economic Policy Research (CEPR), London",
               "canonical_ids": ["I4210140326", IFN, "I161593684",
                                 "I56590836", "I197518295"], "attributes_to_au": True})
    ev += [{"work_id": f"W{y}", "publication_year": y,
            "raw_affil": "Monash University, Clayton, Australia",
            "canonical_ids": ["I56590836"], "attributes_to_au": True}
           for y in [2016, 2017, 2018]]                                  # true Monash
    return ev


def _zenou_truth_evidence():
    """Table B manually checked 2016 (official_roster tier) — the real shape of the promoted roster."""
    from m7a_star.evidence_assembly import assemble_arrival_evidence
    return assemble_arrival_evidence(
        roster_rows=[{"year_start": 2016, "confidence": "high", "human_verified": True},
                     {"year_start": 1995, "confidence": "low", "human_verified": False}])


def _derive_zenou():
    from m7a_star.events_pipeline import derive_star_event
    return derive_star_event(
        star_person_id="A5017376589", dept_id=MONASH_CANONICAL_ID,
        evidence_rows=_zenou_dirty_evidence(),
        truth_evidence=_zenou_truth_evidence(), modal_inst_year=True)


def test_zenou_event_dept_is_monash_not_sydney():
    """#33: events[Zenou].dept_id == MONASH_CANONICAL_ID."""
    ev = _derive_zenou()["event"]
    assert ev is not None
    assert ev["dept_id"] == MONASH_CANONICAL_ID == "I56590836"


def test_zenou_arrival_2016_not_1998():
    """#34: arrival falls in the closed interval (2015,2017) (true 2016), t_minus_1=2015; rejects the 1998 back-fill."""
    ev = _derive_zenou()["event"]
    lo, hi = ZENOU_STRUCTURAL["arrival_year_range"]
    assert lo <= ev["arrival_year"] <= hi
    assert ev["arrival_year"] == 2016 and ev["t_minus_1"] == 2015
    assert ev["arrival_year"] != 1998


def test_zenou_prior_stockholm_exit():
    """#35: old main IFN exits → prior_main_exited True + departed_year=2015 (the year after the last active year 2014;
    rule: 4 years with no byline); old main = the modal institution of the latest recorded year before arrival (single source of truth: the arrival_rule mode)."""
    res = _derive_zenou()
    assert res["prior_main_inst"] == IFN
    ev = res["event"]
    assert ev["prior_main_exited"] is True
    assert ev["departed_year"] == 2015


def test_zenou_no_false_arrival_before_2015():
    """#36 (S8-7, first direction): fixture contains 1998/2003/2006 stamped + 2005 CEPR fake Monash →
    after cleaning detect_arrival produces no pre-2015 arrival (none of 1998/2003/2005/2006 is judged)."""
    res = _derive_zenou()
    assert res["n_polluted_dropped"] == 4          # 3 stamped + 1 CEPR
    ay = res["event"]["arrival_year"]
    assert ay not in (1998, 2003, 2005, 2006)
    assert ay >= ZENOU_STRUCTURAL["arrival_year_range"][0]


def test_zenou_not_killed_by_fake_au_years():
    """#37 (S8-7, second direction): pre-arrival evidence containing printed true affiliations (Southampton/GAINS/IFN) →
    (1) pollution_guard keeps them (non-Australian affiliations are never touched); (2) the "never in Australia" judgement does not
    lose the poaching eligibility because of fake Australian years (explosion/stamp, which do not count as clean AU)."""
    from m7a_star.foreign_poach import is_foreign_poach
    from m7a_star.pollution_guard import clean_au_attributions
    printed_overseas = [
        {"work_id": "W1999s", "publication_year": 1999,
         "raw_affil": "Department of Economics, University of Southampton",
         "canonical_ids": [SOTON], "attributes_to_au": False},
        {"work_id": "W2012g", "publication_year": 2012,
         "raw_affil": "GAINS, Université du Maine",
         "canonical_ids": [GAINS], "attributes_to_au": False},
    ]
    dirty = _zenou_dirty_evidence() + printed_overseas
    cleaned = clean_au_attributions(dirty)
    kept_raws = {r["raw_affil"] for r in cleaned["kept"]}
    assert "Department of Economics, University of Southampton" in kept_raws
    assert "GAINS, Université du Maine" in kept_raws        # printed true affiliations kept

    cc = {IFN: "SE", SOTON: "GB", GAINS: "FR", "I56590836": "AU",
          "I4210140326": "GB", "I161593684": "SE", "I197518295": "US"}
    pre_rows = []
    for r in dirty:
        if r["publication_year"] >= 2016:          # pre-arrival = before 2016
            continue
        for canon in r["canonical_ids"]:
            pre_rows.append({"raw_affil": r["raw_affil"],
                             "canonical_affil_id": canon, "country_code": cc[canon]})
    assert is_foreign_poach(pre_rows) is True


def test_zenou_event_source_from_truth_dates_not_detect_arrival():
    """#26 end to end: arrival_source/strength come from the truth_dates hit (official_roster/strong),
    not from detect_arrival (which has none); the year is still judged by detect_arrival (truth_dates does not take part in judging the year)."""
    ev = _derive_zenou()["event"]
    assert ev["arrival_source"] == "official_roster"
    assert ev["arrival_evidence_strength"] == "strong"


def test_no_truth_evidence_falls_back_to_modal_shift():
    """No evidence tier at all → inferred tier modal_inst_shift/modal_shift (explicit fallback mapping)."""
    from m7a_star.events_pipeline import derive_star_event
    res = derive_star_event(
        star_person_id="A5017376589", dept_id=MONASH_CANONICAL_ID,
        evidence_rows=_zenou_dirty_evidence(), truth_evidence={}, modal_inst_year=False)
    assert res["event"]["arrival_source"] == "modal_inst_shift"
    assert res["event"]["arrival_evidence_strength"] == "modal_shift"


def test_no_arrival_detected_returns_none_event():
    """A single institution from start to end (no switch) → detect_arrival finds no arrival → event=None (no event is forged)."""
    from m7a_star.events_pipeline import derive_star_event
    rows = [{"work_id": f"W{y}", "publication_year": y, "raw_affil": "IFN, Stockholm",
             "canonical_ids": [IFN], "attributes_to_au": False} for y in [2010, 2011, 2012]]
    res = derive_star_event(star_person_id="A1", dept_id="I56590836",
                            evidence_rows=rows, truth_evidence={}, modal_inst_year=False)
    assert res["event"] is None


def test_multi_switch_prehistory_detects_arrival_to_event_dept():
    """Sentinel engineering fix: the cross-checker now asks
    "the first persistent window **that switches into the event department**" — a multi-hop prior history (Southampton→IFN→Monash) no longer catches
    the first move in a career (2001 IFN; the old question wrongly blocked 10 of 12), but asks about Monash → 2016, and builds the event row.
    The authority is still the roster arrival year (the pick_arrival_year route); this function is only a sentinel — if it cannot align, it still
    HALTs + reports as before (the consistency gate is untouched)."""
    from m7a_star.events_pipeline import derive_star_event
    rows = [{"work_id": "W1999", "publication_year": 1999,
             "raw_affil": "Department of Economics, University of Southampton",
             "canonical_ids": [SOTON], "attributes_to_au": False}]
    rows += [{"work_id": f"W{y}", "publication_year": y, "raw_affil": "IFN, Stockholm",
              "canonical_ids": [IFN], "attributes_to_au": False}
             for y in [2001, 2002, 2004, 2010, 2013, 2014]]
    rows += [{"work_id": f"W{y}", "publication_year": y,
              "raw_affil": "Monash University, Clayton, Australia",
              "canonical_ids": ["I56590836"], "attributes_to_au": True}
             for y in [2016, 2017, 2018]]
    res = derive_star_event(star_person_id="A5017376589", dept_id=MONASH_CANONICAL_ID,
                            evidence_rows=rows, truth_evidence=_zenou_truth_evidence(),
                            modal_inst_year=True)
    assert res["arrival"]["arrival_year"] == 2016            # ask about the event department → Monash 2016
    assert res["arrival"]["arrival_institution"] == MONASH_CANONICAL_ID
    assert res["event"] is not None and res["event"]["arrival_year"] == 2016
    assert res["arrival_inst_mismatch"] is False
    assert res["prior_main_inst"] == IFN                     # old main is still the modal institution of the latest recorded year before arrival
    assert res["event"]["prior_main_exited"] is True


# ---- detect_arrival_to_dept direct tests (sentinel engineering fix) -------------------

def _tl(pairs):
    """[(year, inst)] → P-3 contract timeline (one work, one institution per year)."""
    return [{"work_id": f"W{y}", "publication_year": y, "canonical_inst_ids": [i]}
            for y, i in pairs]


def test_detect_to_dept_skips_flash_year_finds_sustained_window():
    """A one-year flash at the event department (2005) does not count as arrival (the persistence window is not met); only the first **persistent** window
    switching into the event department (2016, 2017) counts → 2016."""
    from m7a_star.events_pipeline import detect_arrival_to_dept
    tl = _tl([(2001, IFN), (2005, "I56590836"), (2006, IFN), (2014, IFN),
              (2016, "I56590836"), (2017, "I56590836")])
    got = detect_arrival_to_dept(tl, "I56590836")
    assert got["arrival_year"] == 2016
    assert got["arrival_institution"] == "I56590836"
    assert got["method"] == "modal_institution_to_dept"
    assert got["sustain_window_years"] == 2                  # RED persistence window, nothing hard-coded


def test_detect_to_dept_none_when_never_sustained():
    """The event department flashes in a single year and never persists → no arrival (None; passed to the consistency-gate report for a human decision, nothing forged)."""
    from m7a_star.events_pipeline import detect_arrival_to_dept
    tl = _tl([(2001, IFN), (2005, "I56590836"), (2006, IFN), (2007, IFN)])
    got = detect_arrival_to_dept(tl, "I56590836")
    assert got["arrival_year"] is None and got["arrival_institution"] is None


def test_detect_to_dept_none_when_career_starts_at_dept():
    """The first recorded year of the career is already at the event department (no "switch from elsewhere") → not a switch → None
    (a purely foreign-poached star must have a prior history; none = a data anomaly, passed to the gate for a human decision)."""
    from m7a_star.events_pipeline import detect_arrival_to_dept
    tl = _tl([(2016, "I56590836"), (2017, "I56590836"), (2018, "I56590836")])
    assert detect_arrival_to_dept(tl, "I56590836")["arrival_year"] is None


def test_detect_to_dept_enforces_p3_contract():
    """The P-3 contract is still enforced (reuses the arrival_rule validation): a forbidden key (affiliations) → raise loudly."""
    from identity.arrival_rule import ArrivalInputContractError
    from m7a_star.events_pipeline import detect_arrival_to_dept
    bad = [{"work_id": "W1", "publication_year": 2016,
            "canonical_inst_ids": ["I56590836"], "affiliations": [{"years": [1998]}]}]
    with pytest.raises(ArrivalInputContractError):
        detect_arrival_to_dept(bad, "I56590836")


# ---- Consistency hard gate: events.arrival_year vs frozen star_set.arrival --------------

def _frozen(author_id="A5017376589", arrival=2016, s5=True, s1=True, poach=True):
    return {"author_id": author_id, "arrival": arrival, "dept": "monash_econ",
            "is_star_5pct": s5, "is_star_1pct": s1, "is_foreign_poach": poach}


def _event(star_id="A5017376589", ay=2016, src="official_roster", strength="strong"):
    return {"event_id": f"{star_id}:{ay}", "dept_id": "I56590836",
            "star_person_id": star_id, "arrival_year": ay, "t_minus_1": ay - 1,
            "arrival_source": src, "arrival_evidence_strength": strength,
            "modal_inst_year": True, "prior_main_exited": True,
            "min_tenure_ok": True, "departed_year": ay - 1}


def test_consistency_gate_passes_when_equal():
    """Both routes agree on the year (2016==2016) → empty diff → pass."""
    from m7a_star.events_pipeline import arrival_consistency_diff
    diff = arrival_consistency_diff({"A5017376589": _event()}, [_frozen()])
    assert diff == []


def test_consistency_gate_reports_mismatch_both_years_and_evidence():
    """Routes differ (events=2017 vs frozen=2016) → the diff row carries all three: who / which year each route says / evidence
    (source + strength). The code never picks a route by itself."""
    from m7a_star.events_pipeline import arrival_consistency_diff
    diff = arrival_consistency_diff({"A5017376589": _event(ay=2017)}, [_frozen()])
    assert len(diff) == 1
    d = diff[0]
    assert d["star_person_id"] == "A5017376589"
    assert d["star_set_arrival"] == 2016            # pick_arrival_year route (fingerprint bound)
    assert d["events_arrival_year"] == 2017         # detect_arrival route
    assert d["arrival_source"] == "official_roster"
    assert d["arrival_evidence_strength"] == "strong"


def test_consistency_gate_reports_missing_event_as_diff():
    """A shipped star for whom the events route finds no arrival (event=None) → also a disagreement between the routes → a diff row
    (events_arrival_year=None), passed to a human, never silently skipped."""
    from m7a_star.events_pipeline import arrival_consistency_diff
    diff = arrival_consistency_diff({"A5017376589": None}, [_frozen()])
    assert len(diff) == 1
    assert diff[0]["events_arrival_year"] is None
    assert diff[0]["star_set_arrival"] == 2016


def test_consistency_gate_ignores_non_shipped():
    """A non-shipped row (5% flag False, or not a purely foreign poach) does not enter the gate — the gate only covers stars about to ship."""
    from m7a_star.events_pipeline import arrival_consistency_diff
    frozen = [_frozen(author_id="A2", arrival=2010, s5=False, s1=False, poach=True),
              _frozen(author_id="A3", arrival=2011, s5=True, s1=False, poach=False)]
    assert arrival_consistency_diff({}, frozen) == []
