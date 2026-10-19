"""incumbent_roster tests (written test-first): the three-step fold chain, the fixed values for the never-treated pool (nt-pool), the CEM variables and the pop-min rule, and the nt-pool in the two-school case.

Covers: T15 (scheme-B pool) / T16 (4 CEM variables, field excluded) / T17a (Table B chain) /
T17b (pop-min: at least 2 distinct years) / T18 (author_id folded to person) / T19 (dept_key bridge).
The nt-pool is empty for the two schools: record it and keep the 11 schools; do not fabricate a pool.
"""
from __future__ import annotations

import inspect

import pytest

from m7b_assemble import incumbent_roster as ir


# --- T18: Table B author_id folded to a person via person_map (several ids of one person -> one) -----------
def test_table_b_author_id_folded_via_person_map(mk):
    roster = [mk.roster("monash_econ", "AZ1"), mk.roster("monash_econ", "AZ2")]
    pm = [mk.pm("AZ1", "P_Z"), mk.pm("AZ2", "P_Z")]
    members, diag = ir.fold_roster_to_persons(roster, pm)
    persons = {m["person_id"] for m in members}
    assert persons == {"P_Z"}, "one person with several author_ids must fold into a single person, not one row each"
    assert diag["n_unmapped_author_rows"] == 0


def test_fold_counts_unmapped_authors_warn_not_crash(mk):
    """Rows that fail to fold are counted in a sidecar + WARN; a None author_id also counts as not folded."""
    roster = [mk.roster("unsw_econ", "A_NOMAP"), mk.roster("unsw_econ", None)]
    members, diag = ir.fold_roster_to_persons(roster, [mk.pm("AX", "P_X")])
    assert members == []
    assert diag["n_unmapped_author_rows"] == 2


# --- T19: dept_key bridged to the events dept_id space via Table A openalex_inst_id ---------
def test_dept_key_bridged_to_dept_id_via_table_a(mk):
    bridge = ir.bridge_dept_to_inst([
        mk.registry("monash_econ", "I56590836"),
        mk.registry("unsw_econ", "I31746571"),
    ])
    assert bridge == {"monash_econ": "I56590836", "unsw_econ": "I31746571"}


def test_bridge_rejects_wrong_schema(mk):
    row = mk.registry("monash_econ", "I56590836")
    row.pop("university")
    with pytest.raises(Exception):
        ir.bridge_dept_to_inst([row])


# --- T17a: interval expanded to years + late binding (null-null -> year bound by the panel's primary affiliation) ----------
def test_in_dept_years_from_interval(mk):
    members = [{"person_id": "P_I2", "dept_key": "monash_econ",
                "year_start": 2010, "year_end": 2018, "author_id": "AI2"}]
    idx = ir.build_in_dept_index(members, [], {"monash_econ": "I56590836"})
    ys = idx.years("P_I2")
    assert 2010 in ys and 2018 in ys and 2009 not in ys and 2019 not in ys
    assert idx.basis_counts["roster_interval"] == 1


def test_in_dept_years_null_null_late_binds_via_panel(mk):
    """Late binding: an interval with both ends null -> the years where the panel's primary_affil_id equals the
    school id (side data only binds the year; Table B stays the authority on membership - modal_hint plays no part)."""
    members = [{"person_id": "P_I3", "dept_key": "unsw_econ",
                "year_start": None, "year_end": None, "author_id": "AI3"}]
    panel = [mk.panel("P_I3", y, primary_affil_id="I31746571")
             for y in (2012, 2013)] + [mk.panel("P_I3", 2011,
                                                primary_affil_id="AFFIL_NONE")]
    idx = ir.build_in_dept_index(members, panel, {"unsw_econ": "I31746571"})
    assert idx.years("P_I3") == frozenset({2012, 2013})
    assert idx.basis_counts["panel_bound"] == 1


def test_in_dept_open_end_means_still_member(mk):
    members = [{"person_id": "P_A", "dept_key": "monash_econ",
                "year_start": 2015, "year_end": None, "author_id": "A"}]
    idx = ir.build_in_dept_index(members, [], {"monash_econ": "I56590836"})
    assert 2015 in idx.years("P_A") and 2026 in idx.years("P_A")
    assert 2014 not in idx.years("P_A")
    assert idx.membership_end("P_A") is None      # open interval = has not left


def test_membership_end_from_interval(mk):
    members = [{"person_id": "P_I2", "dept_key": "monash_econ",
                "year_start": 2010, "year_end": 2018, "author_id": "AI2"}]
    idx = ir.build_in_dept_index(members, [], {"monash_econ": "I56590836"})
    assert idx.membership_end("P_I2") == 2018


# --- Roster conflict resolution -----------------------------------------------
# The plain union of several rows for the same person and department is a real defect
# (overlap case: an unverified official_roster 2009-2024 row extends the human-verified
# 2023-2025 row outward, so zero-output years outside the true interval get filled with 0).
# Fix: human-verified rows win. An unverified row that overlaps a human-verified row's
# interval is dropped (superseded); a non-overlapping unverified row is kept (another spell
# of employment that the human check did not contradict). A person with no human-verified row
# keeps the plain union (never the naive "verified rows only": the 125 people with no verified
# row would be set to NA).
def test_verified_row_supersedes_overlapping_unverified(mk):
    """Exact replica of the overlap case: unverified 2009-2024 overlaps human-verified 2023-2025 -> only the human-verified interval counts."""
    members = [
        {"person_id": "P_OVL", "dept_key": "monash_econ", "year_start": 2009,
         "year_end": 2024, "author_id": "AOVL", "human_verified": False},
        {"person_id": "P_OVL", "dept_key": "monash_econ", "year_start": 2023,
         "year_end": 2025, "author_id": "AOVL", "human_verified": True},
    ]
    idx = ir.build_in_dept_index(members, [], {"monash_econ": "I56590836"})
    assert idx.years("P_OVL") == frozenset({2023, 2024, 2025}), \
        "an unverified contaminating row widens the employment interval (overlap case) — the human-verified row must take priority"


def test_unverified_only_rows_keep_union(mk):
    """A person with no human-verified row -> plain union (avoids the new error of "verified rows only")."""
    members = [
        {"person_id": "P_U", "dept_key": "monash_econ", "year_start": 2000,
         "year_end": 2005, "author_id": "AU", "human_verified": False},
        {"person_id": "P_U", "dept_key": "monash_econ", "year_start": 2004,
         "year_end": 2010, "author_id": "AU", "human_verified": False},
    ]
    idx = ir.build_in_dept_index(members, [], {"monash_econ": "I56590836"})
    assert idx.years("P_U") == frozenset(range(2000, 2011))


def test_verified_keeps_non_overlapping_unverified_stint(mk):
    """Human-verified 2020-2025 + unverified 2000-2005 (no overlap) -> both spells count (the human check did not contradict it)."""
    members = [
        {"person_id": "P_S", "dept_key": "monash_econ", "year_start": 2000,
         "year_end": 2005, "author_id": "AS", "human_verified": False},
        {"person_id": "P_S", "dept_key": "monash_econ", "year_start": 2020,
         "year_end": 2025, "author_id": "AS", "human_verified": True},
    ]
    idx = ir.build_in_dept_index(members, [], {"monash_econ": "I56590836"})
    ys = idx.years("P_S")
    assert frozenset(range(2000, 2006)) <= ys
    assert frozenset(range(2020, 2026)) <= ys
    assert 2010 not in ys


def test_verified_supersedes_open_interval_unverified(mk):
    """Unverified row with an open interval (null end = open, treated as overlapping everything) + a human-verified row -> the unverified row is dropped."""
    members = [
        {"person_id": "P_O", "dept_key": "monash_econ", "year_start": None,
         "year_end": None, "author_id": "AO", "human_verified": False},
        {"person_id": "P_O", "dept_key": "monash_econ", "year_start": 2023,
         "year_end": 2025, "author_id": "AO", "human_verified": True},
    ]
    panel = [mk.panel("P_O", y, primary_affil_id="I56590836")
             for y in (2010, 2011)]
    idx = ir.build_in_dept_index(members, panel, {"monash_econ": "I56590836"})
    assert idx.years("P_O") == frozenset({2023, 2024, 2025})


def test_conflict_resolution_scoped_per_dept(mk):
    """Resolution happens only within the same person and the **same department**: an unverified row in another department is unaffected by this department's human-verified rows."""
    members = [
        {"person_id": "P_X", "dept_key": "monash_econ", "year_start": 2023,
         "year_end": 2025, "author_id": "AX", "human_verified": True},
        {"person_id": "P_X", "dept_key": "unsw_econ", "year_start": 2009,
         "year_end": 2024, "author_id": "AX", "human_verified": False},
    ]
    idx = ir.build_in_dept_index(
        members, [], {"monash_econ": "I56590836", "unsw_econ": "I31746571"})
    ys = idx.years("P_X")
    assert frozenset(range(2009, 2026)) == ys, "the cross-department union rule is unchanged (a separate case)"


def test_fold_roster_carries_human_verified(mk):
    """fold_roster_to_persons must carry human_verified into members (the input to the resolution)."""
    roster = [mk.roster("monash_econ", "AZ1", human_verified=True)]
    members, _ = ir.fold_roster_to_persons(roster, [mk.pm("AZ1", "P_Z")])
    assert members[0]["human_verified"] is True


# --- T17b: pop-min = at least 2 distinct publication years; min_works removed --------
def test_incumbent_pop_min_distinct_years(mk):
    panel = [mk.panel("P_ONE", 2025, first_pub_year=2025),
             mk.panel("P_TWO", 2020, first_pub_year=2020),
             mk.panel("P_TWO", 2022, first_pub_year=2020)]
    dy = ir.distinct_pub_years(panel)
    assert ir.pop_min_ok(dy.get("P_TWO", 0)) is True
    assert ir.pop_min_ok(dy.get("P_ONE", 0)) is False, \
        "a person whose publications span only 1 year does not pass the pop-min gate (#9: a default of sample composition, not an identification red line)"


def test_no_pop_min_works_constant_anywhere():
    """Redundancy removed: the source must not reference POP_MIN_WORKS / min_works."""
    src = inspect.getsource(ir)
    assert "POP_MIN_WORKS" not in src
    assert "min_works" not in src


def test_pop_min_token_guard_from_red():
    """pop-min reads the fixed RED token (drift sentinel); it does not hardcode a bare 2 with no source."""
    from common._redlines import RED

    assert RED["population_gate"]["pop_min"] == "ge_2_distinct_publication_years"
    assert ir.POP_MIN_DISTINCT_YEARS == 2


# --- T15: never-treated pool = scheme B (departments with zero arrivals over the whole span); empty for the two schools -> record ---
@pytest.mark.depends_on_u345
def test_never_treated_pool_is_scheme_b_zero_arrival_depts(mk):
    members = [
        {"person_id": "P_I1", "dept_key": "monash_econ",
         "year_start": 2000, "year_end": 2026, "author_id": "AI1"},
        {"person_id": "P_N1", "dept_key": "adelaide_econ",
         "year_start": 2000, "year_end": 2026, "author_id": "AN1"},
    ]
    events = [mk.event("AZ1:2016", "AZ1", 2016, dept_id="I56590836")]
    bridge = {"monash_econ": "I56590836", "adelaide_econ": "I174216632"}
    pool_depts, candidates, diag = ir.never_treated_pool(members, events, bridge)
    assert pool_depts == ["adelaide_econ"], "pool = Table B departments minus the departments that appear in events"
    assert candidates == ["P_N1"]
    assert diag["nt_pool_empty"] is False


def test_never_treated_pool_two_school_empty_records_not_fabricates(mk):
    """Two-school period: the nt-pool is empty -> record it and keep the 11 schools; do not fabricate a pool, do not raise."""
    members = [{"person_id": "P_I1", "dept_key": "monash_econ",
                "year_start": 2000, "year_end": 2026, "author_id": "AI1"},
               {"person_id": "P_I3", "dept_key": "unsw_econ",
                "year_start": 2010, "year_end": 2026, "author_id": "AI3"}]
    events = [mk.event("AZ1:2016", "AZ1", 2016, dept_id="I56590836"),
              mk.event("AS5:2019", "AS5", 2019, dept_id="I31746571")]
    bridge = {"monash_econ": "I56590836", "unsw_econ": "I31746571"}
    pool_depts, candidates, diag = ir.never_treated_pool(members, events, bridge)
    assert pool_depts == [] and candidates == []
    assert diag["nt_pool_empty"] is True
    assert diag["thin_arm_fallback"] == "report_not_yet_treated_only"


def test_scheme_a_reverse_join_not_used():
    """Scheme A (STAR_SET left-join EVENTS, a reverse join) must not be used for the Tier1 main robustness arm (static scan)."""
    src = inspect.getsource(ir)
    assert "anti_join" not in src and "reverse_join" not in src


# --- T16: CEM match = the 4 fixed variables; field proximity is deliberately excluded ---------
def test_never_treated_match_vars_signed_exclude_field():
    from common._redlines import RED

    assert list(RED["groups_control"]["match_vars"]) == [
        "output_trend", "career_length", "output_cadence", "collaboration_scale"
    ]
    assert RED["groups_control"]["exclude_field_proximity_from_match"] is True
    assert tuple(ir.CEM_VARS) == ("output_trend", "career_length",
                                  "output_cadence", "collaboration_scale")
    src = inspect.getsource(ir.cem_match)
    assert "field_proximity" not in src and "subfield" not in src, \
        "field proximity = bad control (#2), never a matching variable"


def test_cem_match_ignores_field_proximity_feature():
    """Candidate and treated unit share the 4 fixed variables but differ hugely in field proximity -> still matched (shows the exclusion works)."""
    treated = [{"incumbent_person_id": "P_T", "event_id": "E1",
                "star_person_id": "P_STAR", "output_trend": 1,
                "career_length": 10, "output_cadence": 2,
                "collaboration_scale": 3, "field_proximity": 0.99}]
    cands = [{"person_id": "P_C", "control_star_person_id": "P_CTRL",
              "output_trend": 1, "career_length": 10, "output_cadence": 2,
              "collaboration_scale": 3, "field_proximity": 0.01}]
    c_rows, diag = ir.cem_match(treated, cands)
    assert len(c_rows) == 1
    row = c_rows[0]
    assert row["treated"] is False
    assert row["matched_treated_event_id"] == "E1"
    assert row["event_id"] == "E1", "C row event_id = matched FK, never silently minted"
    assert row["control_star_person_id"] == "P_CTRL"
    assert row["star_person_id"] == "P_CTRL"


def test_cem_empty_pool_returns_fallback_no_raise():
    c_rows, diag = ir.cem_match([{"incumbent_person_id": "P_T",
                                  "event_id": "E1", "star_person_id": "P_S",
                                  "output_trend": 0, "career_length": 1,
                                  "output_cadence": 1,
                                  "collaboration_scale": 1}], [])
    assert c_rows == []
    assert diag["thin_arm_fallback_triggered"] is True
