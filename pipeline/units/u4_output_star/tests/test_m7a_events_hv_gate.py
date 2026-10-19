"""events consistency gate, supplementary rule — manual-check web evidence prevails (TDD, both sides tested).

In plain words: if a shipped star's arrival year carries **manual-check evidence** (roster human_verified / human_verified_web /
the adjudication file's arrival_verifications, with year == frozen year), then when the byline route (detect_arrival_to_dept)
differs from the frozen year the mismatch is **downgraded to a diagnostic record** (written to arrival_mismatch_report, tagged
"explained: human_verified evidence prevails"), and the event row is written with the **authoritative frozen year**, no HALT.
A star without manual-check evidence: the HALT discipline is unchanged (two routes differ → ArrivalMismatch as before + the events table is not written at all).
"""
import json

import pytest

from identity.golden import MONASH_CANONICAL_ID

EDGES_SUB = "u1_edges_full_2026-07-05"
ZID = "A5017376589"
KID = "A_K2_UNSW"
IFN = "I77432436"
OXF = "I300000001"
UNSW = "I31746571"


def _mk_root(tmp_path):
    root = tmp_path / "derived"
    mdir = root / EDGES_SUB / "_manifest"
    mdir.mkdir(parents=True)
    (mdir / "run_manifest.json").write_text(
        json.dumps({"source_snapshot_merkle": "snap:HV"}), encoding="utf-8")
    return root


def _frozen_rows(zenou_arrival=2016, k2_arrival=2014):
    return [
        {"author_id": ZID, "arrival": zenou_arrival, "dept": "monash_econ",
         "is_star_1pct": True, "is_star_5pct": True, "is_foreign_poach": True},
        {"author_id": KID, "arrival": k2_arrival, "dept": "unsw_econ",
         "is_star_1pct": False, "is_star_5pct": True, "is_foreign_poach": True},
    ]


def _zenou_evidence():
    """Overseas history IFN 2013/2014 → Monash 2016/2017 (detect_arrival_to_dept = 2016)."""
    ev = [{"work_id": f"W{y}", "publication_year": y, "raw_affil": "IFN, Stockholm",
           "canonical_ids": [IFN], "attributes_to_au": False} for y in (2013, 2014)]
    ev += [{"work_id": f"W{y}", "publication_year": y,
            "raw_affil": "Monash University, Clayton, Australia",
            "canonical_ids": ["I56590836"], "attributes_to_au": True} for y in (2016, 2017)]
    return ev


def _k2_evidence(unsw_from=2014):
    ev = [{"work_id": f"K{y}", "publication_year": y, "raw_affil": "University of Oxford",
           "canonical_ids": [OXF], "attributes_to_au": False} for y in (2008, 2009)]
    ev += [{"work_id": f"K{y}", "publication_year": y,
            "raw_affil": "School of Economics, UNSW Sydney",
            "canonical_ids": [UNSW], "attributes_to_au": True}
           for y in (unsw_from, unsw_from + 1, unsw_from + 2)]
    return ev


def _ship(tmp_path, *, frozen, hv_basis=None, truth=None, k2_evidence=None):
    from run_u4 import ship_events
    return ship_events(
        _mk_root(tmp_path), tmp_path / "out",
        frozen_star_rows=frozen,
        evidence_by_star={ZID: _zenou_evidence(),
                          KID: k2_evidence if k2_evidence is not None else _k2_evidence()},
        truth_evidence_by_star=truth if truth is not None else {ZID: {"official_roster": 2016}},
        modal_inst_year_by_star={ZID: True, KID: True},
        hv_arrival_basis=hv_basis)


def test_explained_mismatch_ships_with_authoritative_year(tmp_path):
    """Green side: frozen 2017 (manual check) vs detect 2016 → no HALT; the event row uses the **authoritative frozen year 2017**
    (t-1 2016, official_roster/strong); the difference is downgraded to a diagnostic record (explained tag + halt=False);
    K2 with both routes in the same year goes through as usual; n_events = the whole shipped set."""
    import pyarrow.parquet as pq

    res = _ship(tmp_path, frozen=_frozen_rows(zenou_arrival=2017),
                hv_basis={ZID: "roster:human_verified_web"},
                truth={ZID: {"official_roster": 2017}})
    rows = {r["star_person_id"]: r
            for r in pq.read_table(str(tmp_path / "out" / "events" / "data.parquet")).to_pylist()}
    assert set(rows) == {ZID, KID}
    assert rows[ZID]["arrival_year"] == 2017 and rows[ZID]["t_minus_1"] == 2016
    assert rows[ZID]["dept_id"] == MONASH_CANONICAL_ID
    assert rows[ZID]["arrival_source"] == "official_roster"
    assert rows[ZID]["arrival_evidence_strength"] == "strong"
    assert rows[KID]["arrival_year"] == 2014                    # a star whose two routes agree is unaffected
    assert res["n_events"] == 2 and res["n_explained_mismatch"] == 1
    assert res["explained_ids"] == [ZID]

    rep = json.loads((tmp_path / "out" / "_reports" / "arrival_mismatch_report.json")
                     .read_text("utf-8"))
    assert rep["n_mismatch"] == 1 and rep["n_explained"] == 1 and rep["n_halt"] == 0
    d = rep["diff"][0]
    assert d["star_person_id"] == ZID and d["halt"] is False
    assert d["explained"] == "human_verified evidence prevails"
    assert d["hv_basis"] == "roster:human_verified_web"
    assert d["star_set_arrival"] == 2017 and d["events_arrival_year"] == 2016


def test_unexplained_mismatch_still_halts(tmp_path):
    """Red side (discipline not loosened): the same two-route disagreement but no manual-check evidence → ArrivalMismatch HALT,
    the events table is not written at all; the report marks halt=True, explained=None."""
    from m7a_star.events_pipeline import ArrivalMismatch

    with pytest.raises(ArrivalMismatch):
        _ship(tmp_path, frozen=_frozen_rows(zenou_arrival=2017),
              truth={ZID: {"official_roster": 2017}})
    assert not (tmp_path / "out" / "events").exists()
    rep = json.loads((tmp_path / "out" / "_reports" / "arrival_mismatch_report.json")
                     .read_text("utf-8"))
    assert rep["n_halt"] == 1 and rep["n_explained"] == 0
    assert rep["diff"][0]["halt"] is True and rep["diff"][0]["explained"] is None


def test_mixed_explained_plus_unexplained_halts_whole_table(tmp_path):
    """Mixed: Zenou has manual-check evidence (explained), K2 has none and the two routes differ → whole table HALT (events table not written at all);
    the report has two rows, each with the true halt/explained values (the diagnostic record is still written in full)."""
    from m7a_star.events_pipeline import ArrivalMismatch

    with pytest.raises(ArrivalMismatch):
        _ship(tmp_path, frozen=_frozen_rows(zenou_arrival=2017, k2_arrival=2015),
              hv_basis={ZID: "roster:human_verified"},
              truth={ZID: {"official_roster": 2017}})
    assert not (tmp_path / "out" / "events").exists()
    rep = json.loads((tmp_path / "out" / "_reports" / "arrival_mismatch_report.json")
                     .read_text("utf-8"))
    assert rep["n_mismatch"] == 2 and rep["n_explained"] == 1 and rep["n_halt"] == 1
    by = {d["star_person_id"]: d for d in rep["diff"]}
    assert by[ZID]["halt"] is False and by[ZID]["explained"]
    assert by[KID]["halt"] is True and by[KID]["explained"] is None


def test_explained_detect_none_ships_inferred_label(tmp_path):
    """detect finds no arrival (single institution, no switch) but the frozen year carries manual-check evidence → ship the authoritative year; with no literature-grade ground-truth tier the
    evidence label = per_work_first_seen/modal_shift (inferred tier — the year is derived from the first appearance in the works panel,
    never labelled modal_inst_shift: the detect route is exactly the disagreeing party here)."""
    import pyarrow.parquet as pq

    k2_single = [{"work_id": f"K{y}", "publication_year": y,
                  "raw_affil": "School of Economics, UNSW Sydney",
                  "canonical_ids": [UNSW], "attributes_to_au": True}
                 for y in (2014, 2015, 2016)]
    res = _ship(tmp_path, frozen=_frozen_rows(),
                hv_basis={KID: "adjudication:arrival_verification(cv_career_ladder)"},
                truth={ZID: {"official_roster": 2016}}, k2_evidence=k2_single)
    rows = {r["star_person_id"]: r
            for r in pq.read_table(str(tmp_path / "out" / "events" / "data.parquet")).to_pylist()}
    assert rows[KID]["arrival_year"] == 2014 and rows[KID]["t_minus_1"] == 2013
    assert rows[KID]["arrival_source"] == "per_work_first_seen"
    assert rows[KID]["arrival_evidence_strength"] == "modal_shift"
    assert rows[KID]["prior_main_exited"] is False and rows[KID]["departed_year"] is None
    assert res["n_explained_mismatch"] == 1 and res["explained_ids"] == [KID]
    rep = json.loads((tmp_path / "out" / "_reports" / "arrival_mismatch_report.json")
                     .read_text("utf-8"))
    d = [x for x in rep["diff"] if x["star_person_id"] == KID][0]
    assert d["events_arrival_year"] is None and d["halt"] is False
