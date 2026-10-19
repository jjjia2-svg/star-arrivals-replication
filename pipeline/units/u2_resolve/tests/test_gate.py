"""TDD red tests for U2 gate.py (G1-G4). Fixtures are inline."""
import json

import pytest
from common.reverse_validate import ResolveGateFail
from m2_resolve.gate import (
    assert_zenou_works_count,
    build_adjudication_queue,
    check_star_candidate_superset,
    compute_cluster_purity,
    run_exit_gate,
    run_m2_exit_gate,
    run_zenou_golden_check,
    _assert_upstream_fields,
    _check_subfield_coverage,
    _no_signal_fragments,
    _writeback_person_map_purity,
)

# Correctly resolved Yves Zenou observation frame (for the golden e2e test): all anchors match and in range (works 583, arrival 2016, Monash)
GOOD_ZENOU_FRAME = {
    "found": True,
    "resolved_single_person": True,
    "is_star_at_p01": True,
    "institution_canonical_observed": "I56590836",   # Monash (not Stockholm/Sydney)
    "armi_folded_to_monash": True,
    "caulfield_folded_to_none": True,
    "rejected_1998_backfill": True,
    "read_affiliations_years": False,                 # Red line #3: never read affiliations.years
    "took_largest_cluster": False,                    # 13 fragments merged back; do not take the largest cluster
    "arrival_year_observed": 2016,
    "works_count_observed": 583,
}


def _inject_floors(monkeypatch, *, recall, precision, completeness, homogeneity, faceting):
    """Tests inject the reverse_validate threshold floors (production keeps null; the monkeypatch lives only in tests/)."""
    from common._redlines import RED

    rv = RED["reverse_validate"]
    monkeypatch.setitem(rv, "recall_large_dept", recall)
    monkeypatch.setitem(rv, "recall_small_dept", recall)
    monkeypatch.setitem(rv, "precision_min", precision)
    monkeypatch.setitem(rv, "completeness_min", completeness)
    monkeypatch.setitem(rv, "homogeneity_min", homogeneity)
    monkeypatch.setitem(rv, "faceting_recall_min", faceting)


# ===================== G1: exit gate = U0 validate_resolution =====================

def test_exit_gate_raises_redline_unsigned_when_thresholds_null(tmp_path):
    """Threshold unset (RED=null) -> validate_resolution raises RedlineUnsigned via evaluate_gate; never passes silently."""
    from common._redlines import RedlineUnsigned

    labels = {"Z1": "Z", "Z2": "Z"}
    with pytest.raises(RedlineUnsigned):
        run_exit_gate(labels, labels, is_large_dept=True, evidence_path=tmp_path / "ev.json")


def test_exit_gate_passes_when_metrics_meet_floors(tmp_path, monkeypatch):
    """Perfect prediction + injected permissive floors -> exit gate passes (no raise), all metrics 1.0."""
    _inject_floors(monkeypatch, recall=0.0, precision=0.0, completeness=0.0, homogeneity=0.0, faceting=0.0)
    labels = {"Z1": "Z", "Z2": "Z", "Z3": "Z"}
    metrics = run_exit_gate(labels, labels, is_large_dept=True, evidence_path=tmp_path / "ev.json")
    assert metrics["completeness"] == 1.0 and metrics["homogeneity"] == 1.0


def test_under_merge_caught_by_completeness_not_pairwise_recall(tmp_path, monkeypatch):
    """#11-b: under-merge (one person split into several clusters) -> completeness drops and trips the gate; with a permissive recall floor it does not fail on recall."""
    # recall floor 0.0 (permissive) + completeness floor 0.99 (strict) -> under-merge fails only on completeness
    _inject_floors(monkeypatch, recall=0.0, precision=0.0, completeness=0.99, homogeneity=0.0, faceting=0.0)
    gt = {"Z1": "Z", "Z2": "Z", "Z3": "Z"}         # Truth: the same person
    pred = {"Z1": "P1", "Z2": "P2", "Z3": "P3"}     # under-merge: split into 3
    ev = tmp_path / "ev.json"
    with pytest.raises(ResolveGateFail):
        run_exit_gate(pred, gt, is_large_dept=True, evidence_path=ev)
    fails = json.loads(ev.read_text(encoding="utf-8"))["fails"]
    assert "completeness" in fails, "under-merge should be caught by completeness (#11-b)"
    assert "recall" not in fails, "recall floor is loose → pairwise recall is not used to judge under-merge (#11-b)"


def test_bcubed_directionality():
    """Directionality: under-merge lowers bcubed_recall (=completeness); over-merge lowers bcubed_precision (=homogeneity)."""
    from common.reverse_validate import bcubed_f1

    gt = {"a": "X", "b": "X", "c": "X"}
    under = bcubed_f1({"a": "1", "b": "2", "c": "3"}, gt)         # split (under-merge)
    assert under["bcubed_recall"] < under["bcubed_precision"]
    gt2 = {"a": "X", "b": "X", "c": "Y"}
    over = bcubed_f1({"a": "1", "b": "1", "c": "1"}, gt2)         # wrongly merged (over-merge)
    assert over["bcubed_precision"] < over["bcubed_recall"]


# ===================== G2: cluster purity diagnostics + write quality columns back to person_map =====================

def test_compute_cluster_purity_schema():
    """cluster_purity rows = the 15 columns of the CLUSTER_PURITY schema (distinct_orcid_hit added by fix A;
    quality_representative_author_id added by root-cause fix B1), one row per person."""
    from common.schema import CLUSTER_PURITY

    person_map = [{"author_id": "Z1", "person_id": "P_Z"}, {"author_id": "Z2", "person_id": "P_Z"}]
    authors = [
        {"author_id": "Z1", "display_name": "Yves Zenou", "orcid": None},
        {"author_id": "Z2", "display_name": "Y Zenou", "orcid": None},
    ]
    works = [
        {"author_id": "Z1", "work_id": "W1", "subfield_id": "S_econ", "institution_id": "I_m"},
        {"author_id": "Z2", "work_id": "W2", "subfield_id": "S_econ", "institution_id": "I_m"},
    ]
    rows = compute_cluster_purity(person_map, authors, works)
    assert len(rows) == 1
    assert set(rows[0].keys()) == set(CLUSTER_PURITY.keys())


def test_overmerge_cluster_flagged_suspected():
    """A cluster with a strict majority of econ plus one paper from a different subfield -> suspected_overmerge, and the outlier work goes into ejected_work_ids."""
    person_map = [{"author_id": "M1", "person_id": "P_M"}]
    authors = [{"author_id": "M1", "display_name": "Some One", "orcid": None}]
    works = [{"author_id": "M1", "work_id": f"W{i}", "subfield_id": "S_econ", "institution_id": "I_m"} for i in range(3)]
    works.append({"author_id": "M1", "work_id": "W_out", "subfield_id": "S_med", "institution_id": "I_h"})
    r = compute_cluster_purity(person_map, authors, works)[0]
    assert r["purity_flag"] == "suspected_overmerge"
    assert "W_out" in r["ejected_work_ids"]
    assert r["topic_outlier_hit"] is True


def test_clean_cluster_flagged_clean():
    """Homogeneous cluster -> purity_flag=clean."""
    person_map = [{"author_id": "Z1", "person_id": "P_Z"}]
    authors = [{"author_id": "Z1", "display_name": "Yves Zenou", "orcid": None}]
    works = [{"author_id": "Z1", "work_id": "W1", "subfield_id": "S_econ", "institution_id": "I_m"}]
    assert compute_cluster_purity(person_map, authors, works)[0]["purity_flag"] == "clean"


def test_works_without_subfield_not_fake_clean():
    """Papers exist but no subfield signal anywhere in the cluster -> never fake homogeneity=1.0
    and pass as clean; homogeneity=None (cannot be assessed) + purity_flag=low_confidence (goes to the G3 human-review queue)."""
    person_map = [{"author_id": "N1", "person_id": "P_N"}]
    authors = [{"author_id": "N1", "display_name": "No Signal", "orcid": None}]
    works = [
        {"author_id": "N1", "work_id": "W1", "subfield_id": None, "institution_id": "I_m"},
        {"author_id": "N1", "work_id": "W2", "subfield_id": None, "institution_id": "I_m"},
    ]
    r = compute_cluster_purity(person_map, authors, works)[0]
    assert r["topic_homogeneity"] is None
    assert r["purity_flag"] == "low_confidence"
    assert r["topic_source"] == "concepts_fallback"


def test_zero_works_homogeneity_none_not_one():
    """A cluster with 0 papers also gets homogeneity None (previously faked as 1.0);
    purity_flag=low_confidence is unchanged."""
    person_map = [{"author_id": "E1", "person_id": "P_E"}]
    authors = [{"author_id": "E1", "display_name": "Empty Person", "orcid": None}]
    r = compute_cluster_purity(person_map, authors, [])[0]
    assert r["topic_homogeneity"] is None
    assert r["purity_flag"] == "low_confidence"


def test_subfield_floor_unsigned_raises_redline():
    """Subfield-coverage floor unset (the resolve section has it but the value is null) -> RedlineUnsigned (same discipline as the other thresholds)."""
    from common._redlines import RedlineUnsigned

    works = [{"author_id": "Z1", "work_id": "W1", "subfield_id": "S_econ", "institution_id": "I"}]
    with pytest.raises(RedlineUnsigned):
        _check_subfield_coverage(works)


def test_upstream_fields_missing_halts():
    """authors lacks display_name -> HALT (points to the U1 table not having been produced; an engineering gap)."""
    with pytest.raises(RuntimeError):
        _assert_upstream_fields([{"author_id": "Z1", "orcid": None}],
                                [{"author_id": "Z1", "work_id": "W1", "subfield_id": "S"}])


def test_purity_writeback_fills_person_map_quality_cols():
    """G2's single write-back: topic_homogeneity->cluster_homogeneity, topic_completeness->completeness, purity_flag->purity_flag."""
    person_map = [{
        "author_id": "Z1", "person_id": "P_Z", "merge_reason": "block_cluster",
        "cluster_homogeneity": None, "completeness": None, "purity_flag": None, "had_orcid": False,
    }]
    purity = [{"person_id": "P_Z", "topic_homogeneity": 0.95, "topic_completeness": 1.0, "purity_flag": "clean"}]
    out = _writeback_person_map_purity(person_map, purity)
    assert out[0]["cluster_homogeneity"] == 0.95
    assert out[0]["completeness"] == 1.0
    assert out[0]["purity_flag"] == "clean"
    assert out[0] is not person_map[0]  # Write a new copy atomically; do not edit in place


# ===================== G3: human-review queue (stars 100% + low purity + no-signal fragments) =====================

def test_star_and_collaborator_queued_in_adjudication():
    """Stars + direct coauthors always enter the queue; clean non-star non-coauthors do not."""
    person_map = [
        {"author_id": "STAR", "person_id": "P_STAR"},
        {"author_id": "COLLAB", "person_id": "P_COLLAB"},
        {"author_id": "CLEAN", "person_id": "P_CLEAN"},
    ]
    purity = [{"person_id": p, "purity_flag": "clean"} for p in ("P_STAR", "P_COLLAB", "P_CLEAN")]
    edges = [
        {"work_id": "W1", "author_id": "STAR"},
        {"work_id": "W1", "author_id": "COLLAB"},
        {"work_id": "W2", "author_id": "CLEAN"},
    ]
    q = build_adjudication_queue(person_map, purity, {"STAR"}, edges, no_signal_ids=set())
    ids = {r["author_id"] for r in q}
    assert {"STAR", "COLLAB"} <= ids
    assert "CLEAN" not in ids


def test_suspected_overmerge_person_queued():
    """A person with purity_flag=suspected_overmerge enters the queue (even if not a star)."""
    person_map = [{"author_id": "X", "person_id": "P_X"}]
    purity = [{"person_id": "P_X", "purity_flag": "suspected_overmerge"}]
    q = build_adjudication_queue(person_map, purity, set(), [], no_signal_ids=set())
    assert any(r["author_id"] == "X" for r in q)


def test_no_signal_fragment_unconditionally_queued():
    """No-signal fragments (no work and no coauthor) enter the queue unconditionally (#11-c: small departments in full)."""
    person_map = [{"author_id": "F", "person_id": "P_F"}]
    purity = [{"person_id": "P_F", "purity_flag": "low_confidence"}]
    q = build_adjudication_queue(person_map, purity, set(), [], no_signal_ids={"F"})
    assert any(r["author_id"] == "F" for r in q)


def test_no_signal_fragments_detection():
    """_no_signal_fragments: neither a work nor a coauthor edge = no signal."""
    person_map = [{"author_id": "F", "person_id": "P_F"}, {"author_id": "G", "person_id": "P_G"}]
    works = [{"author_id": "G", "work_id": "W1", "subfield_id": "S"}]      # G has a work
    edges = []
    assert _no_signal_fragments(person_map, works, edges) == {"F"}          # Only F has no signal


def test_star_candidate_superset_guarantee():
    """Candidate stars must be a superset of the true stars (checked once U4 produces the real star_set); on violation return the violating set (WARN for U4 to review)."""
    assert check_star_candidate_superset({"A", "B"}, {"A"}) == set()        # True star A in candidates -> ok
    assert check_star_candidate_superset({"A"}, {"A", "B"}) == {"B"}        # True star B not in candidates -> violation


# ===================== G4: exit orchestration + Yves Zenou end-to-end golden test + idempotence =====================

def test_zenou_golden_structural_pass():
    """Correctly resolved Yves Zenou -> all classify_golden structural anchors pass and in range; the U2 wrapper does not HALT."""
    from identity.golden import classify_golden

    r = classify_golden(GOOD_ZENOU_FRAME)
    assert r["structural_pass"] is True
    assert r["observed_in_range"] is True
    assert run_zenou_golden_check(GOOD_ZENOU_FRAME)["structural_pass"] is True


def test_zenou_golden_fails_if_attributed_to_stockholm():
    """Attribution taken by Stockholm (not Monash) -> institution_canonical anchor fails -> GOLDEN_FAIL."""
    from identity.golden import classify_golden
    from identity.exit_codes import GOLDEN_FAIL

    frame = {**GOOD_ZENOU_FRAME, "institution_canonical_observed": "I161593684"}  # Stockholm
    assert "institution_canonical" in classify_golden(frame)["flips"]
    with pytest.raises(SystemExit) as e:
        run_zenou_golden_check(frame)
    assert e.value.code == GOLDEN_FAIL


def test_zenou_golden_fails_if_read_affiliations_years():
    """Read affiliations.years (violates red line #3) -> fails (even if the counts are right)."""
    from identity.golden import classify_golden

    frame = {**GOOD_ZENOU_FRAME, "read_affiliations_years": True}
    assert classify_golden(frame)["structural_pass"] is False


def test_zenou_golden_fails_if_took_largest_cluster():
    """Took the largest cluster (did not merge the 13 fragments back) -> took_largest_cluster anchor fails."""
    from identity.golden import classify_golden

    frame = {**GOOD_ZENOU_FRAME, "took_largest_cluster": True}
    assert "took_largest_cluster" in classify_golden(frame)["flips"]


def test_assert_zenou_works_count_independent():
    """#11-b: works_count in [550,620] as an independent person-level count assertion (separate from the pairwise gate)."""
    assert assert_zenou_works_count(583) == 583
    with pytest.raises(RuntimeError):
        assert_zenou_works_count(100)


def test_run_m2_exit_gate_orchestration(tmp_path, monkeypatch):
    """Exit orchestration end to end: upstream -> cluster_purity -> write-back -> exit gate -> human-review queue -> Yves Zenou golden test."""
    _inject_floors(monkeypatch, recall=0.0, precision=0.0, completeness=0.0, homogeneity=0.0, faceting=0.0)
    person_map = [{
        "author_id": "Z1", "person_id": "P_Z", "merge_reason": "block_cluster",
        "cluster_homogeneity": None, "completeness": None, "purity_flag": None, "had_orcid": False,
    }]
    authors = [{"author_id": "Z1", "display_name": "Yves Zenou", "orcid": None}]
    works = [{"author_id": "Z1", "work_id": "W1", "subfield_id": "S_econ", "institution_id": "I_m"}]
    res = run_m2_exit_gate(person_map, authors, works, {"Z1": "P_Z"}, GOOD_ZENOU_FRAME,
                           is_large_dept=True, evidence_path=tmp_path / "ev.json")
    assert res["golden"]["structural_pass"] is True
    assert res["person_map"][0]["purity_flag"] == "clean"  # G2 write-back takes effect


def test_gate_evidence_idempotent(tmp_path, monkeypatch):
    """Run twice on the same metrics -> evidence-file sha256 identical (deterministic / idempotent)."""
    import hashlib

    _inject_floors(monkeypatch, recall=0.0, precision=0.0, completeness=0.0, homogeneity=0.0, faceting=0.0)
    labels = {"Z1": "Z", "Z2": "Z"}
    ev1, ev2 = tmp_path / "ev1.json", tmp_path / "ev2.json"
    run_exit_gate(labels, labels, is_large_dept=True, evidence_path=ev1)
    run_exit_gate(labels, labels, is_large_dept=True, evidence_path=ev2)
    assert hashlib.sha256(ev1.read_bytes()).hexdigest() == hashlib.sha256(ev2.read_bytes()).hexdigest()


# ===================== Review fixes: H1 (range check wired into the golden test) + M2 (fail loudly) =====================

def test_zenou_golden_fails_if_works_count_out_of_range():
    """H1/#11-b: works_count outside [550,620] -> GOLDEN_FAIL (observed_in_range is part of the golden check)."""
    from identity.exit_codes import GOLDEN_FAIL

    frame = {**GOOD_ZENOU_FRAME, "works_count_observed": 100}  # Far below 550, structural anchors still all correct
    with pytest.raises(SystemExit) as e:
        run_zenou_golden_check(frame)
    assert e.value.code == GOLDEN_FAIL


def test_zenou_golden_fails_if_arrival_year_out_of_range():
    """H1: arrival year outside [2015,2017] -> GOLDEN_FAIL (observed_in_range)."""
    from identity.exit_codes import GOLDEN_FAIL

    frame = {**GOOD_ZENOU_FRAME, "arrival_year_observed": 2020}  # Structural anchor: arrival!=1998 still passes, but out of range
    with pytest.raises(SystemExit) as e:
        run_zenou_golden_check(frame)
    assert e.value.code == GOLDEN_FAIL


def test_cluster_purity_fails_loud_on_missing_author():
    """M2: an author_id in person_map but not in the authors table -> HALT (no silent downgrade, consistent with _assert_upstream_fields)."""
    person_map = [{"author_id": "GHOST", "person_id": "P_G"}]
    with pytest.raises(RuntimeError):
        compute_cluster_purity(person_map, [], [])  # GHOST is not in authors


# ===================== Fix A: corroborated different-ORCID over-merge flag (gate assembly + queue) =====================
# Rule:
#   suspected_overmerge ⟸ distinct_orcid_hit AND (orcid_field_conflict_hit OR affil_conflict_hit)
#   Detect and queue for human review only; never split automatically; leave cluster_block clustering and the 0.8 threshold untouched.
#   Safe for Yves Zenou: 2 ORCIDs, both economics, both Monash -> no corroborating conflict -> no flag.

def test_orcid_zenou_type_two_orcid_same_field_not_flagged():
    """Golden-test safe: 2 different ORCIDs + same subfield (econ) + same institution (Monash) -> distinct_orcid_hit=True
    but NO corroborating conflict -> never flag suspected_overmerge (different ORCIDs alone never trigger)."""
    person_map = [{"author_id": "Z1", "person_id": "P_Z"}, {"author_id": "Z2", "person_id": "P_Z"}]
    authors = [
        {"author_id": "Z1", "display_name": "Yves Zenou", "orcid": "0000-0002-1111-1111",
         "raw_affil": ["Monash University Melbourne Australia"]},
        {"author_id": "Z2", "display_name": "Yves Zenou", "orcid": "0000-0002-2222-2222",
         "raw_affil": ["Monash University Melbourne Australia"]},
    ]
    works = [
        {"author_id": "Z1", "work_id": "W1", "subfield_id": "S_econ", "institution_id": "I_m"},
        {"author_id": "Z2", "work_id": "W2", "subfield_id": "S_econ", "institution_id": "I_m"},
    ]
    r = compute_cluster_purity(person_map, authors, works)[0]
    assert r["distinct_orcid_hit"] is True
    assert r["overmerge_suspect"] is False
    assert r["purity_flag"] != "suspected_overmerge"


def test_orcid_namesake_type_field_conflict_flagged():
    """Two-ORCID same-name case: 2 different ORCIDs + field conflict (econ vs pulmonology) + same institution (both UCD, no institution conflict) ->
    flagged suspected_overmerge on field corroboration (closes the structural gap where the strict majority of the old topic gate cannot catch a 50/50 split)."""
    person_map = [{"author_id": "K1", "person_id": "P_K"}, {"author_id": "K2", "person_id": "P_K"}]
    authors = [
        {"author_id": "K1", "display_name": "John Namesake", "orcid": "0000-0003-1111-1111",
         "raw_affil": ["University College Dublin Ireland"]},
        {"author_id": "K2", "display_name": "John Namesake", "orcid": "0000-0003-2222-2222",
         "raw_affil": ["University College Dublin Ireland"]},
    ]
    works = [
        {"author_id": "K1", "work_id": "W1", "subfield_id": "S_econ", "institution_id": "I_ucd"},
        {"author_id": "K1", "work_id": "W2", "subfield_id": "S_econ", "institution_id": "I_ucd"},
        {"author_id": "K2", "work_id": "W3", "subfield_id": "S_pulmonology", "institution_id": "I_ucd"},
        {"author_id": "K2", "work_id": "W4", "subfield_id": "S_pulmonology", "institution_id": "I_ucd"},
    ]
    r = compute_cluster_purity(person_map, authors, works)[0]
    assert r["distinct_orcid_hit"] is True
    assert r["affil_conflict_hit"] is False, "both UCD → institutions do not conflict, only domain evidence can be relied on"
    assert r["overmerge_suspect"] is True
    assert r["purity_flag"] == "suspected_overmerge"


def test_orcid_institution_conflict_flagged():
    """2 different ORCIDs + same field (econ) but conflicting institution strings (Monash vs Tokyo) -> flagged on institution corroboration
    (corroboration = field OR institution; this is the OR branch)."""
    person_map = [{"author_id": "D1", "person_id": "P_D"}, {"author_id": "D2", "person_id": "P_D"}]
    authors = [
        {"author_id": "D1", "display_name": "Wei Toyname", "orcid": "0000-0004-1111-1111",
         "raw_affil": ["Monash University Melbourne Australia"]},
        {"author_id": "D2", "display_name": "Wei Toyname", "orcid": "0000-0004-2222-2222",
         "raw_affil": ["University of Tokyo Japan"]},
    ]
    works = [
        {"author_id": "D1", "work_id": "W1", "subfield_id": "S_econ", "institution_id": "I_m"},
        {"author_id": "D2", "work_id": "W2", "subfield_id": "S_econ", "institution_id": "I_t"},
    ]
    r = compute_cluster_purity(person_map, authors, works)[0]
    assert r["distinct_orcid_hit"] is True
    assert r["affil_conflict_hit"] is True
    assert r["purity_flag"] == "suspected_overmerge"


def test_no_orcid_field_split_not_flagged_by_new_rule():
    """Boundary: no ORCID + field split 50/50 -> distinct_orcid_hit=False -> the new flag does not fire
    (a field conflict alone never triggers it, different ORCIDs are required; and a 50/50 split has no strict majority, so the old topic gate does not eject either)."""
    person_map = [{"author_id": "N1", "person_id": "P_N"}, {"author_id": "N2", "person_id": "P_N"}]
    authors = [
        {"author_id": "N1", "display_name": "Jane Doe", "orcid": None, "raw_affil": None},
        {"author_id": "N2", "display_name": "Jane Doe", "orcid": None, "raw_affil": None},
    ]
    works = [
        {"author_id": "N1", "work_id": "W1", "subfield_id": "S_econ", "institution_id": "I_a"},
        {"author_id": "N2", "work_id": "W2", "subfield_id": "S_med", "institution_id": "I_a"},
    ]
    r = compute_cluster_purity(person_map, authors, works)[0]
    assert r["distinct_orcid_hit"] is False
    assert r["purity_flag"] != "suspected_overmerge"


def test_zenou_six_fragments_multi_orcid_not_flagged():
    """Yves Zenou's 6 fragments merged into 1 are unaffected: 6 members (4 without ORCID + 2 different econ ORCIDs), all Monash, all econ ->
    distinct_orcid_hit=True but no corroborating conflict -> no flag (clustering untouched; diagnostic layer only)."""
    aff = ["Monash University Melbourne Australia"]
    person_map = [{"author_id": f"Z{i}", "person_id": "P_Z"} for i in range(1, 7)]
    authors = [
        {"author_id": "Z1", "display_name": "Yves Zenou", "orcid": "0000-0002-1111-1111", "raw_affil": aff},
        {"author_id": "Z2", "display_name": "Y Zenou", "orcid": "0000-0002-2222-2222", "raw_affil": aff},
        {"author_id": "Z3", "display_name": "Yves Zenou", "orcid": None, "raw_affil": aff},
        {"author_id": "Z4", "display_name": "Y Zenou", "orcid": None, "raw_affil": aff},
        {"author_id": "Z5", "display_name": "Yves Zénou", "orcid": None, "raw_affil": aff},
        {"author_id": "Z6", "display_name": "Yves Zenou", "orcid": None, "raw_affil": aff},
    ]
    works = [{"author_id": f"Z{i}", "work_id": f"W{i}", "subfield_id": "S_econ", "institution_id": "I_m"}
             for i in range(1, 7)]
    rows = compute_cluster_purity(person_map, authors, works)
    assert len(rows) == 1, "6 fragments are still 1 person (clustering unchanged)"
    r = rows[0]
    assert r["distinct_orcid_hit"] is True
    assert r["purity_flag"] != "suspected_overmerge"


def test_namesake_type_enters_adjudication_queue():
    """A two-ORCID same-name cluster flagged suspected_overmerge -> enters the human-review queue (reason=low_purity, even if not a star)."""
    person_map = [{"author_id": "K1", "person_id": "P_K"}, {"author_id": "K2", "person_id": "P_K"}]
    purity = [{"person_id": "P_K", "purity_flag": "suspected_overmerge"}]
    q = build_adjudication_queue(person_map, purity, set(), [], no_signal_ids=set())
    assert {"K1", "K2"} <= {r["author_id"] for r in q}


def test_cluster_purity_has_distinct_orcid_column():
    """CLUSTER_PURITY 13->14 columns: distinct_orcid_hit added; compute_cluster_purity includes that key in every row."""
    from common.schema import CLUSTER_PURITY

    assert "distinct_orcid_hit" in CLUSTER_PURITY
    person_map = [{"author_id": "Z1", "person_id": "P_Z"}]
    authors = [{"author_id": "Z1", "display_name": "Yves Zenou", "orcid": None}]
    works = [{"author_id": "Z1", "work_id": "W1", "subfield_id": "S_econ", "institution_id": "I_m"}]
    r = compute_cluster_purity(person_map, authors, works)[0]
    assert "distinct_orcid_hit" in r
