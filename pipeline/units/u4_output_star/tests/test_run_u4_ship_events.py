"""U4 shipping - ship_events wiring (runner level, synthetic data, does not touch the SSD).

In plain words: run_u4 gets a thin wiring ship_events: the frozen star_set rows are reduced to the shipping set
(is_star_5pct and is_foreign_poach) -> per star derive_star_event (clean -> timeline -> arrival/exit -> evidence
labelling)
-> arrival-year consistency hard gate (events.arrival_year must equal the frozen star_set.arrival person by
person; if not -> a difference report goes to _reports + ArrivalMismatch HALT, the events table is not written
at all, the code never picks one route itself)
-> write to disk (write_events four gates + atomic write) + the dropped-row counts go to _reports
+ provenance reuses resolve_provenance (empty values fail-loud).
Spec: EVENTS produces a single list over the full 5% set, the p01 analysis set = its is_star_1pct subset;
there is no second events table.
"""
import json

import pytest

from identity.golden import MONASH_CANONICAL_ID

EDGES_SUB = "u1_edges_full_2026-07-05"
ZID = "A5017376589"          # Zenou
KID = "A_K2_UNSW"            # synthetic second star (UNSW, 5% tier, no evidence tier -> inferred tier)
IFN = "I77432436"
OXF = "I300000001"
UNSW = "I31746571"


def _mk_root(tmp_path, *, merkle="snap:EVT", with_manifest=True):
    root = tmp_path / "derived"
    if with_manifest:
        mdir = root / EDGES_SUB / "_manifest"
        mdir.mkdir(parents=True)
        (mdir / "run_manifest.json").write_text(
            json.dumps({"source_snapshot_merkle": merkle}), encoding="utf-8")
    else:
        root.mkdir(parents=True)
    return root


def _frozen_rows(zenou_arrival=2016):
    """Frozen star_set rows (minimal key set of the 14-column semantics): 2 shipping stars + 2 non-shipping rows."""
    return [
        {"author_id": ZID, "arrival": zenou_arrival, "dept": "monash_econ",
         "is_star_1pct": True, "is_star_5pct": True, "is_foreign_poach": True},
        {"author_id": KID, "arrival": 2014, "dept": "unsw_econ",
         "is_star_1pct": False, "is_star_5pct": True, "is_foreign_poach": True},
        {"author_id": "A_no5", "arrival": 2010, "dept": "monash_econ",
         "is_star_1pct": False, "is_star_5pct": False, "is_foreign_poach": True},
        {"author_id": "A_home", "arrival": 2011, "dept": "unsw_econ",
         "is_star_1pct": False, "is_star_5pct": True, "is_foreign_poach": False},
    ]


def _zenou_evidence():
    """Zenou's dirty evidence (fixture): genuine overseas history at IFN + 3 stamped rows + 1 fake Monash row from CEPR
    + genuine Monash."""
    ev = [{"work_id": f"W{y}", "publication_year": y, "raw_affil": "IFN, Stockholm",
           "canonical_ids": [IFN], "attributes_to_au": False}
          for y in [2001, 2002, 2004, 2010, 2013, 2014]]
    for y in (1998, 2003, 2006):
        ev.append({"work_id": f"W{y}f", "publication_year": y,
                   "raw_affil": "Monash University - Department of Economics",
                   "canonical_ids": ["I56590836"], "attributes_to_au": True})
    ev.append({"work_id": "W2005f", "publication_year": 2005,
               "raw_affil": "Centre for Economic Policy Research (CEPR), London",
               "canonical_ids": ["I4210140326", IFN, "I161593684",
                                 "I56590836", "I197518295"], "attributes_to_au": True})
    ev += [{"work_id": f"W{y}", "publication_year": y,
            "raw_affil": "Monash University, Clayton, Australia",
            "canonical_ids": ["I56590836"], "attributes_to_au": True}
           for y in [2016, 2017, 2018]]
    return ev


def _k2_evidence():
    """K2 clean timeline: Oxford 2008-2013 -> UNSW 2014-2016 (arrival 2014; under 4 years with zero papers at the
    former employer)."""
    ev = [{"work_id": f"K{y}", "publication_year": y, "raw_affil": "University of Oxford",
           "canonical_ids": [OXF], "attributes_to_au": False}
          for y in [2008, 2009, 2010, 2013]]
    ev += [{"work_id": f"K{y}", "publication_year": y,
            "raw_affil": "School of Economics, UNSW Sydney",
            "canonical_ids": [UNSW], "attributes_to_au": True}
           for y in [2014, 2015, 2016]]
    return ev


def _inputs():
    return dict(
        evidence_by_star={ZID: _zenou_evidence(), KID: _k2_evidence()},
        truth_evidence_by_star={
            ZID: {"official_roster": 2016}},           # K2 has no evidence tier -> fall back to the inferred tier
        modal_inst_year_by_star={ZID: True, KID: True},
    )


def _ship(tmp_path, frozen=None, **overrides):
    from run_u4 import ship_events
    root = overrides.pop("root", None)
    if root is None:
        root = _mk_root(tmp_path)
    args = dict(frozen_star_rows=frozen if frozen is not None else _frozen_rows(),
                **_inputs())
    args.update(overrides)
    return ship_events(root, tmp_path / "out", **args)


# ---- pass side: both routes agree on the year -> write + provenance + accounting --------------------------------

def test_ship_events_lands_ship_set_rows_with_provenance(tmp_path):
    """Whole chain passes: the events table is exactly the shipping set, 2 rows; Zenou row = Monash/2016/t-1 2015/former
    employer exit/official_roster+strong; K2 row = UNSW/2014/inferred tier/former employer not exited; header
    four-tuple non-empty, stars_set_hash == freeze.stars_set_hash(all frozen rows) (events table <-> star set
    binding)."""
    import pyarrow.parquet as pq
    from common._redlines import sha256_of_red
    from m7a_star.freeze import stars_set_hash

    res = _ship(tmp_path)
    rows = {r["star_person_id"]: r
            for r in pq.read_table(str(tmp_path / "out" / "events" / "data.parquet")).to_pylist()}
    assert set(rows) == {ZID, KID}                     # exactly the shipping set; non-stars / non-poached do not enter

    z = rows[ZID]
    assert z["dept_id"] == MONASH_CANONICAL_ID
    assert z["arrival_year"] == 2016 and z["t_minus_1"] == 2015
    assert z["arrival_source"] == "official_roster"
    assert z["arrival_evidence_strength"] == "strong"
    assert z["prior_main_exited"] is True and z["departed_year"] == 2015
    assert z["min_tenure_ok"] is True

    k = rows[KID]
    assert k["dept_id"] == UNSW
    assert k["arrival_year"] == 2014 and k["t_minus_1"] == 2013
    assert k["arrival_source"] == "modal_inst_shift"   # no evidence tier -> inferred tier
    assert k["arrival_evidence_strength"] == "modal_shift"
    assert k["prior_main_exited"] is False and k["departed_year"] is None

    hdr = json.loads((tmp_path / "out" / "events" / "manifest_header.json").read_text("utf-8"))
    assert hdr["stars_set_hash"] == stars_set_hash(
        {s["author_id"]: s["arrival"] for s in _frozen_rows()})
    assert hdr["source_snapshot_merkle"] == "snap:EVT"
    assert hdr["config_sha"] == sha256_of_red()
    assert hdr["n_events"] == 2 == res["n_events"]
    assert hdr["n_polluted_dropped"] == 4              # Zenou 3 stamped + 1 CEPR

    rep = (tmp_path / "out" / "_reports" / "events_pollution_dropped.csv").read_text("utf-8")
    assert f"{ZID},4" in rep and f"{KID},0" in rep     # dropped-row counts recorded


def test_ship_events_single_list_5pct_p01_subset(tmp_path):
    """One-list guard: only one events table is produced (the full 5% set); the p01 analysis set == its is_star_1pct
    subset (Zenou alone), a subset of the events star set; there is no second events table file."""
    import pyarrow.parquet as pq

    res = _ship(tmp_path)
    parquets = sorted((tmp_path / "out").rglob("*.parquet"))
    assert [p.parent.name for p in parquets] == ["events"]   # the only events table
    event_ids = {r["star_person_id"] for r in pq.read_table(str(parquets[0])).to_pylist()}
    assert res["p01_event_ids"] == [ZID]                     # 1% subset (KID is only in the 5% tier)
    assert set(res["p01_event_ids"]) <= event_ids            # p01 is a subset of the full 5% set, the same table


# ---- HALT side: the two routes disagree -> difference report + ArrivalMismatch, events table not written --------------

def test_ship_events_halts_on_arrival_mismatch_with_report(tmp_path):
    """The frozen star_set says 2017, the events route says 2016 -> ArrivalMismatch HALT;
    the difference report goes to _reports (who / what year each route says / evidence); the events table is never
    written."""
    from m7a_star.events_pipeline import ArrivalMismatch

    with pytest.raises(ArrivalMismatch):
        _ship(tmp_path, frozen=_frozen_rows(zenou_arrival=2017))

    assert not (tmp_path / "out" / "events").exists()        # HALT = the events table is not written at all
    rep = json.loads((tmp_path / "out" / "_reports" / "arrival_mismatch_report.json")
                     .read_text("utf-8"))
    assert rep["n_mismatch"] == 1
    d = rep["diff"][0]
    assert d["star_person_id"] == ZID                        # who
    assert d["star_set_arrival"] == 2017                     # the year the frozen route says
    assert d["events_arrival_year"] == 2016                  # the year the events route says
    assert d["arrival_source"] == "official_roster"          # what the evidence is
    assert d["truth_evidence"] == {"official_roster": 2016}
    assert d["detected_arrival_institution"] == "I56590836"


def test_ship_events_halt_report_covers_no_arrival_star(tmp_path):
    """A shipping star is judged to have no arrival on the events route (evidence leaves only a single institution) ->
    also a disagreement between the routes -> the report has events_arrival_year=None + HALT (a person is never
    silently dropped from the events table)."""
    from m7a_star.events_pipeline import ArrivalMismatch

    inputs = _inputs()
    inputs["evidence_by_star"] = dict(inputs["evidence_by_star"])
    inputs["evidence_by_star"][KID] = [                      # K2 is left with only UNSW, a single institution -> no switch
        {"work_id": f"K{y}", "publication_year": y,
         "raw_affil": "School of Economics, UNSW Sydney",
         "canonical_ids": [UNSW], "attributes_to_au": True}
        for y in [2014, 2015, 2016]]
    with pytest.raises(ArrivalMismatch):
        _ship(tmp_path, **inputs)
    rep = json.loads((tmp_path / "out" / "_reports" / "arrival_mismatch_report.json")
                     .read_text("utf-8"))
    ks = [d for d in rep["diff"] if d["star_person_id"] == KID]
    assert len(ks) == 1 and ks[0]["events_arrival_year"] is None
    assert ks[0]["star_set_arrival"] == 2014


# ---- fail-loud side: every input gap fails loudly ----------------------------------------------

def test_ship_events_empty_ship_set_refused(tmp_path):
    """Shipping set empty (no 5% and poach rows) -> ValueError (an empty events table is never silent)."""
    frozen = [{"author_id": "A_no5", "arrival": 2010, "dept": "monash_econ",
               "is_star_1pct": False, "is_star_5pct": False, "is_foreign_poach": True}]
    with pytest.raises(ValueError, match="ship set"):
        _ship(tmp_path, frozen=frozen)


def test_ship_events_missing_evidence_coverage_refused(tmp_path):
    """A shipping star lacks the evidence rows -> ValueError naming it (a person is never silently skipped)."""
    inputs = _inputs()
    inputs["evidence_by_star"] = {ZID: _zenou_evidence()}    # missing KID
    with pytest.raises(ValueError, match=KID):
        _ship(tmp_path, **inputs)


def test_ship_events_missing_modal_flag_refused(tmp_path):
    """A shipping star lacks the is_modal corroboration supply (U3, consume-only) -> ValueError naming it, no defaults
    are made up."""
    inputs = _inputs()
    inputs["modal_inst_year_by_star"] = {ZID: True}          # missing KID
    with pytest.raises(ValueError, match=KID):
        _ship(tmp_path, **inputs)


def test_ship_events_unknown_dept_key_refused(tmp_path):
    """A frozen row's dept is not in the DEPT_INST mapping (outside the two-university smoke-test scope) -> ValueError
    naming it."""
    frozen = _frozen_rows()
    frozen[0] = dict(frozen[0], dept="anu_econ")
    with pytest.raises(ValueError, match="anu_econ"):
        _ship(tmp_path, frozen=frozen)


def test_ship_events_missing_u1_manifest_fail_loud(tmp_path):
    """U1 run_manifest absent -> resolve_provenance ValueError, the events table is not written."""
    root = _mk_root(tmp_path, with_manifest=False)
    with pytest.raises(ValueError, match="run_manifest"):
        _ship(tmp_path, root=root)
    assert not (tmp_path / "out" / "events").exists()
