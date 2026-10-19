"""m7c golden_gate + attrition + reconcile red tests.

Coverage: T38 (structural red HALT / observation out of range WARN / structural red overrides release) /
T39 (classify_golden pure-function property) / T40 (unbalanced tally raises / extra keys rejected) /
T41 (NA HUMAN_REVIEW propagation, in test_run_gates) / T42 (G-reverse skip B6-REVVAL);
the attrition diagnostic + Lee bounds flag.
"""
from __future__ import annotations

import inspect

import pytest

from m7c_gates import attrition_gate as ag
from m7c_gates import golden_gate as gg
from m7c_gates import reconcile_gate as rg


# --- T38/HIGH-3: structural red HALT / observation out of range WARN / structural red overrides release --------------
def _golden(structural_pass=True, observed_in_range=True, flips=()):
    return {"structural_pass": structural_pass,
            "observed_in_range": observed_in_range, "flips": list(flips),
            "works_count_observed": 583, "arrival_year_observed": 2016}


def test_structural_fail_halts():
    assert gg.decide_golden_action(_golden(structural_pass=False,
                                           flips=["institution_canonical"])) \
        == "HALT"


def test_observed_out_of_range_warns():
    assert gg.decide_golden_action(_golden(observed_in_range=False)) == "WARN"


def test_structural_beats_release():
    v = gg.decide_golden_action(_golden(structural_pass=False),
                                release_changed=True)
    assert v == "HALT", "a structural red overrides a release change"


def test_release_changed_human_review():
    assert gg.decide_golden_action(_golden(), release_changed=True) \
        == "HUMAN_REVIEW"


def test_all_pass():
    assert gg.decide_golden_action(_golden()) == "PASS"


def test_classify_golden_is_pure():
    """T39 property: the classify_golden source has no sys.exit/open(/write."""
    from identity.golden import classify_golden

    src = inspect.getsource(classify_golden)
    assert "sys.exit" not in src and "open(" not in src \
        and ".write" not in src


# --- Yves Zenou material assembly (U6 observable side) ---------------------------------------------
def test_build_zenou_material_from_synthetic_world(zenou_inputs):
    mat = gg.build_zenou_material(
        star_set=zenou_inputs.star_set, events=zenou_inputs.events,
        person_map=zenou_inputs.person_map, panel=zenou_inputs.panel,
    )
    assert mat["found"] is True
    assert mat["resolved_single_person"] is True, "several author fragments fold into a single person"
    assert mat["is_star_at_p01"] is True
    assert mat["institution_canonical_observed"] == "I56590836"
    assert mat["arrival_year_observed"] == 2016
    assert mat["rejected_1998_backfill"] is True
    assert mat["read_affiliations_years"] is False, "never trust affiliations.years"
    assert mat["took_largest_cluster"] is False
    assert mat["works_count_observed"] == 583, "works_count is summed year by year from the panel"
    assert mat["n_author_fragments"] >= 2, "the fold must really happen (>=2 fragments)"


def test_zenou_material_flags_sydney_misplacement(zenou_inputs):
    """Move the Yves Zenou event to Sydney -> institution_canonical fails -> structural HALT."""
    from identity.golden import classify_golden

    for e in zenou_inputs.events:
        if e["event_id"].startswith("AZ1"):
            e["dept_id"] = "I129604602"           # Sydney
    mat = gg.build_zenou_material(
        star_set=zenou_inputs.star_set, events=zenou_inputs.events,
        person_map=zenou_inputs.person_map, panel=zenou_inputs.panel,
    )
    res = classify_golden(mat)
    assert res["structural_pass"] is False
    assert "institution_canonical" in res["flips"]
    assert gg.decide_golden_action(res) == "HALT"


# --- attrition diagnostic ---------------------------------------
def test_attrition_diag_two_groups_and_lee_flag():
    treated = [{"incumbent_person_id": "P_I1", "event_id": "E1",
                "arrival_year": 2016},
               {"incumbent_person_id": "P_I2", "event_id": "E1",
                "arrival_year": 2016}]
    ends = {"P_I2": 2018}                      # I2 leaves the department within the window (2018 <= 2021)
    last_pub = {"P_I1": 2026, "P_I2": 2016}    # I2 has no publication after leaving = complete-exit proxy
    diag = ag.run_attrition_diag(treated, membership_end=ends.get,
                                 last_pub_year=last_pub.get, window_years=5,
                                 control_pairs=())
    t = diag["treated"]
    assert t["n_incumbent_events"] == 2
    assert t["n_left_dept_within_window"] == 1
    assert t["leave_rate"] == pytest.approx(0.5)
    assert t["leave_timing_rel_arrival"] == {"2": 1}, "timing distribution = exit year − arrival year"
    assert t["n_exit_academia_proxy"] == 1
    assert diag["control"]["empty"] is True, "both schools' nt pool is empty -> control group recorded as empty"
    assert diag["lee_bounds_required"] is True, \
        "attrition inside the window -> Lee-bounds-needed flag (the flag is recorded, nothing is computed)"
    assert "unsigned" in diag["lee_bounds_note"] or "11" in diag["lee_bounds_note"]


def test_attrition_zero_leavers_flag_false():
    treated = [{"incumbent_person_id": "P_I1", "event_id": "E1",
                "arrival_year": 2016}]
    diag = ag.run_attrition_diag(treated, membership_end=lambda p: None,
                                 last_pub_year=lambda p: 2026, window_years=5,
                                 control_pairs=())
    assert diag["treated"]["leave_rate"] == 0.0
    assert diag["lee_bounds_required"] is False


# --- T40: strict tally validation -------------------------------------------------------
def test_tally_imbalance_raises(tmp_path):
    import json

    p = tmp_path / "tally.json"
    p.write_text(json.dumps({"stage": "s", "expected": 10, "kept": 8,
                             "failed": 0, "skipped": 0, "balanced": True,
                             "op_id_arm": "N/A"}))
    with pytest.raises(rg.TallyImbalance):
        rg.run_reconcile_gate([p])


def test_tally_rejects_extra_keys(tmp_path):
    import json

    p = tmp_path / "tally.json"
    p.write_text(json.dumps({"stage": "s", "expected": 1, "kept": 1,
                             "failed": 0, "skipped": 0, "balanced": True,
                             "op_id_arm": "N/A", "extra_diag": 7}))
    with pytest.raises(rg.TallyImbalance, match="extra"):
        rg.run_reconcile_gate([p])


def test_tally_clean_passes(tmp_path):
    import json

    p = tmp_path / "tally.json"
    p.write_text(json.dumps({"stage": "s", "expected": 2, "kept": 1,
                             "failed": 0, "skipped": 1, "balanced": True,
                             "op_id_arm": "N/A"}))
    res = rg.run_reconcile_gate([p])
    assert res["verdict"] == "PASS" and res["n_tallies"] == 1


@pytest.mark.skip(reason="B6-REVVAL: the whole-file contract of common/reverse_validate.py is missing "
                         "(B-1); until U0 produces it, the G-reverse half is not implemented and no false green is produced")
def test_reverse_exit_recheck_catches_under_recall():
    ...


def test_reverse_gate_status_records_blocker():
    st = rg.reverse_gate_status()
    assert st["status"] == "skip" and "B6-REVVAL" in st["reason"]
