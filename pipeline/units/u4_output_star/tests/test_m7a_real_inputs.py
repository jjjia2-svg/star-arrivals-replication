"""U4 shipping, third wave — three pieces that assemble the real-data inputs for events.

In plain words: the second wave of ship_events consumed synthetic supply; this layer assembles real data into the same shape:
  (1) evidence_by_star: U3 affil_timeline rows → the pollution_guard argument shape
     {work_id, publication_year, raw_affil, canonical_ids, attributes_to_au};
     attributes_to_au is decided **by reusing the country_code route of run_u4._foreign_poach_flags**
     (canonical_affil_id JOIN institutions → country_code=='AU'; code reuse, no new rule).
  (2) truth_evidence_by_star: table B roster rows are taken by author_id (human_verified year_start →
     official_roster tier, using the already-tested evidence_assembly parts); wayback on-roll rows are matched to author_id
     = **exact / normalised name matching only** (case / whitespace / diacritic normalisation is fine, fuzzy matching is forbidden),
     no match → counted in the report, nothing guessed (wayback is a supplementary source; gaps are acceptable).
  (3) modal_inst_year_by_star: the U3 affil_timeline.is_modal ground truth, consume-only (S8-1) —
     a row with is_modal=True for (person, arrival year, event department) → True; no row / all False → False
     (what is read is the absence in the U3 ground truth; this layer never recomputes the mode and passes it off).
All synthetic data, zero SSD writes.
"""
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from run_u4 import ROSTER_FILES

ZID = "A5017376589"
IFN = "I77432436"
MON = "I56590836"
UNSW = "I31746571"


# ---- (1) evidence_rows_from_timeline (pure function: row grouping + AU attribution) --------------------

def _tl(work, year, raw, canon, cc):
    return {"work_id": work, "year": year, "raw_affil": raw,
            "canonical_affil_id": canon, "country_code": cc}


def test_evidence_groups_by_work_and_raw_affil():
    """Several rows with the same (work, raw_affil) (real data shape: one raw parsed into N institutions = N rows)
    → merged into one evidence row, canonical_ids collected, de-duplicated and sorted → is_parse_explosion can judge."""
    from m7a_star.real_inputs import evidence_rows_from_timeline
    rows = evidence_rows_from_timeline([
        _tl("W1", 2005, "CEPR, London", "I_CEPR", "GB"),
        _tl("W1", 2005, "CEPR, London", MON, "AU"),
        _tl("W1", 2005, "CEPR, London", IFN, "SE"),
    ])
    assert len(rows) == 1
    r = rows[0]
    assert r["work_id"] == "W1" and r["publication_year"] == 2005
    assert r["canonical_ids"] == sorted(["I_CEPR", MON, IFN])
    assert r["attributes_to_au"] is True          # the group has an AU institution → attributed to Australia


def test_evidence_attributes_to_au_mirrors_country_code_route():
    """attributes_to_au = any canonical in the group has country_code=='AU'
    (reuses the institutions.country_code route of _foreign_poach_flags verbatim; strings are not looked at)."""
    from m7a_star.real_inputs import evidence_rows_from_timeline
    rows = evidence_rows_from_timeline([
        _tl("W1", 2010, "IFN, Stockholm", IFN, "SE"),
        _tl("W2", 2016, "Monash University, Clayton", MON, "AU"),
        _tl("W3", 2011, "Mystery Institute", "I_X", None),   # no country code → not attributed to AU
    ])
    by = {r["work_id"]: r for r in rows}
    assert by["W1"]["attributes_to_au"] is False
    assert by["W2"]["attributes_to_au"] is True
    assert by["W3"]["attributes_to_au"] is False


def test_evidence_excludes_null_and_sentinel_canonicals():
    """canonical_affil_id is None / '__NONE__' / 'AFFIL_NONE' (unresolved sentinels, present in the real data)
    → not entered into canonical_ids (mirrors the sentinel removal in is_foreign_poach); an all-sentinel row is still kept (canonical_ids
    empty), evidence rows are never silently dropped."""
    from m7a_star.real_inputs import evidence_rows_from_timeline
    rows = evidence_rows_from_timeline([
        _tl("W1", 2010, "Somewhere", "__NONE__", None),
        _tl("W1", 2010, "Somewhere", None, None),
        _tl("W2", 2011, "IFN", IFN, "SE"),
        _tl("W2", 2011, "IFN", "AFFIL_NONE", None),
    ])
    by = {r["work_id"]: r for r in rows}
    assert by["W1"]["canonical_ids"] == [] and by["W1"]["attributes_to_au"] is False
    assert by["W2"]["canonical_ids"] == [IFN]


def test_evidence_null_year_fails_loud():
    """timeline row year is None → raise loudly (the detect_arrival P-3 contract needs an int year;
    U3 affil_timeline should have no empty years; one appearing = upstream broken, never skip silently)."""
    from m7a_star.real_inputs import evidence_rows_from_timeline
    with pytest.raises(ValueError, match="year"):
        evidence_rows_from_timeline([_tl("W1", None, "X", IFN, "SE")])


def test_evidence_rows_deterministic_order():
    """Output sorted ascending by (publication_year, work_id, raw_affil) (deterministic, same order on a rerun)."""
    from m7a_star.real_inputs import evidence_rows_from_timeline
    rows = evidence_rows_from_timeline([
        _tl("W9", 2011, "B", IFN, "SE"),
        _tl("W1", 2010, "A", IFN, "SE"),
        _tl("W1", 2010, "AA", MON, "AU"),
    ])
    assert [(r["publication_year"], r["work_id"], r["raw_affil"]) for r in rows] == [
        (2010, "W1", "A"), (2010, "W1", "AA"), (2011, "W9", "B")]


# ---- (1) load_star_evidence (real read: person_map + affil_timeline + institutions) ------

def _w(root, subpath, rows, schema=None):
    p = root / subpath
    p.parent.mkdir(parents=True, exist_ok=True)
    tbl = pa.Table.from_pylist(rows, schema=schema) if schema else pa.Table.from_pylist(rows)
    pq.write_table(tbl, str(p))


def _evidence_root(tmp_path):
    r = tmp_path / "derived"
    _w(r, "u2_person_map_2026-07-05/person_map/part.parquet", [
        {"author_id": ZID, "person_id": "P_Z"},
        {"author_id": "A_EMPTY", "person_id": "P_EMPTY"}])   # mapped, but no timeline rows
    _w(r, "u3_panel_2026-07-06/affil_timeline/part.parquet", [
        {"person_id": "P_Z", "year": 2014, "work_id": "W14", "raw_affil": "IFN, Stockholm",
         "canonical_affil_id": IFN, "is_modal": True},
        {"person_id": "P_Z", "year": 2016, "work_id": "W16", "raw_affil": "Monash University",
         "canonical_affil_id": MON, "is_modal": True},
        {"person_id": "P_OTHER", "year": 2016, "work_id": "WX", "raw_affil": "Elsewhere",
         "canonical_affil_id": "I_X", "is_modal": False}])
    _w(r, "u1_edges_full_2026-07-05/institutions/part.parquet", [
        {"institution_id": IFN, "country_code": "SE"},
        {"institution_id": MON, "country_code": "AU"},
        {"institution_id": "I_X", "country_code": "US"}])
    return r


def test_load_star_evidence_joins_three_tables(tmp_path):
    """Whole chain: person_map folds person → affil_timeline full-career rows → institutions country codes
    → the pollution_guard argument shape; only the requested stars are included, other people's rows do not leak in."""
    from m7a_star.real_inputs import load_star_evidence
    res = load_star_evidence(_evidence_root(tmp_path), [ZID])
    ev = res["evidence_by_star"]
    assert set(ev) == {ZID}
    by = {r["work_id"]: r for r in ev[ZID]}
    assert by["W14"]["attributes_to_au"] is False and by["W14"]["canonical_ids"] == [IFN]
    assert by["W16"]["attributes_to_au"] is True and by["W16"]["canonical_ids"] == [MON]


def test_load_star_evidence_star_without_rows_present_empty(tmp_path):
    """A star with a person_map mapping but no timeline rows → key present, value [] (passed to the ship_events
    detect→consistency-gate path as "no arrival found = disagreement"; no one is silently dropped at the assembly layer)."""
    from m7a_star.real_inputs import load_star_evidence
    res = load_star_evidence(_evidence_root(tmp_path), [ZID, "A_EMPTY"])
    assert res["evidence_by_star"]["A_EMPTY"] == []


def test_load_star_evidence_unmapped_star_fails_loud(tmp_path):
    """A shipped star without a person_map mapping → ValueError naming the star (no disambiguated identity = cannot assemble, never skip silently)."""
    from m7a_star.real_inputs import load_star_evidence
    with pytest.raises(ValueError, match="A_GHOST"):
        load_star_evidence(_evidence_root(tmp_path), [ZID, "A_GHOST"])


# ---- (2) name normalisation + wayback matching (exact / normalised matching only) ---------------------------

def test_normalize_display_name_case_space_diacritics():
    """Normalisation = case / whitespace / diacritics (Zénou→zenou); no fuzzy transformation of any kind."""
    from m7a_star.real_inputs import normalize_display_name as norm
    assert norm("Yves  Zénou ") == norm("yves zenou") == "yves zenou"
    assert norm("RENÉ Example") == "rene example"
    assert norm("A B") != norm("AB")                 # whitespace collapsing ≠ deleting whitespace (nothing guessed)


def test_wayback_match_exact_normalized_same_dept_only():
    """Matching = (dept_key, normalised name) exactly equal; same name in another department does not leak; fuzzy is forbidden (Zenou≠Zeno)."""
    from m7a_star.real_inputs import match_wayback_to_roster
    roster = [
        {"dept_key": "monash_econ", "author_id": ZID, "display_name": "Yves Zénou"},
        {"dept_key": "unsw_econ", "author_id": "A_U", "display_name": "Jane Example"},
    ]
    wb = [
        {"dept_key": "monash_econ", "display_name": "Yves Zenou", "snapshot_year": 2017},
        {"dept_key": "monash_econ", "display_name": "Jane Example", "snapshot_year": 2008},  # wrong department → no match
        {"dept_key": "monash_econ", "display_name": "Yves Zeno", "snapshot_year": 2018},   # one letter off → no match
    ]
    res = match_wayback_to_roster(wb, roster)
    assert {r["snapshot_year"] for r in res["by_author"].get(ZID, [])} == {2017}
    assert "A_U" not in res["by_author"]
    assert res["n_lines"] == 3 and res["n_matched"] == 1 and res["n_unmatched"] == 2


def test_wayback_ambiguous_name_not_attributed():
    """Two authors in the same department with the same normalised name → ambiguous, assigned to no one + counted separately (no match, nothing guessed)."""
    from m7a_star.real_inputs import match_wayback_to_roster
    roster = [
        {"dept_key": "monash_econ", "author_id": "A1", "display_name": "Wei Example"},
        {"dept_key": "monash_econ", "author_id": "A2", "display_name": "WEI EXAMPLE"},
    ]
    wb = [{"dept_key": "monash_econ", "display_name": "Wei Example", "snapshot_year": 2007}]
    res = match_wayback_to_roster(wb, roster)
    assert res["by_author"] == {}
    assert res["n_ambiguous"] == 1 and res["n_matched"] == 0


def _truth_root(tmp_path):
    r = tmp_path / "derived"
    _w(r, ROSTER_FILES[0], [
        {"dept_key": "monash_econ", "author_id": ZID, "display_name": "Yves Zenou",
         "year_start": 2016, "year_end": None, "evidence": "seek",
         "confidence": "high", "human_verified": True},
        {"dept_key": "monash_econ", "author_id": "A_NOHV", "display_name": "No Verify",
         "year_start": 2011, "year_end": None, "evidence": "seek",
         "confidence": "high", "human_verified": False}])
    _w(r, ROSTER_FILES[1], [
        {"dept_key": "unsw_econ", "author_id": "A_U", "display_name": "Jane Example",
         "year_start": None, "year_end": None, "evidence": "seek",
         "confidence": "low", "human_verified": False}])
    _w(r, "u0p5_hist_raw/wayback_full_2026-07-06/parsed/wayback_staff_lines.parquet", [
        {"dept_key": "monash_econ", "display_name": "Yves Zénou", "snapshot_year": 2017},
        {"dept_key": "monash_econ", "display_name": "Yves Zénou", "snapshot_year": 2018},
        {"dept_key": "monash_econ", "display_name": "Ghost Person", "snapshot_year": 2007}])
    return r


def test_load_star_truth_evidence_buckets(tmp_path):
    """Whole chain: roster human_verified 2016 → official_roster tier; wayback match hits
    {2017,2018} → take the earliest, 2017; unmatched wayback rows are counted in the report (nothing guessed)."""
    from m7a_star.real_inputs import load_star_truth_evidence
    res = load_star_truth_evidence(_truth_root(tmp_path), [ZID, "A_U"])
    truth = res["truth_evidence_by_star"]
    assert truth[ZID] == {"official_roster": 2016, "wayback": 2017}
    assert truth["A_U"] == {}                        # no manual-check year, no wayback → empty tier (inferred-tier fallback)
    rep = res["wayback_report"]
    assert rep["n_lines"] == 3 and rep["n_unmatched"] == 1
    assert rep["n_matched"] == 2


def test_load_star_truth_evidence_unverified_roster_not_strong(tmp_path):
    """An unchecked roster year never passes as the official_roster tier (the evidence_assembly rule is already tested; the assembly layer does not bypass it)."""
    from m7a_star.real_inputs import load_star_truth_evidence
    res = load_star_truth_evidence(_truth_root(tmp_path), ["A_NOHV"])
    assert res["truth_evidence_by_star"]["A_NOHV"] == {}


# ---- (3) modal_inst_year ground truth (consume-only, S8-1) ----------------------------------

def _modal_root(tmp_path):
    r = tmp_path / "derived"
    _w(r, "u2_person_map_2026-07-05/person_map/part.parquet", [
        {"author_id": ZID, "person_id": "P_Z"},
        {"author_id": "A_NOROW", "person_id": "P_N"},
        {"author_id": "A_FALSE", "person_id": "P_F"}])
    _w(r, "u3_panel_2026-07-06/affil_timeline/part.parquet", [
        {"person_id": "P_Z", "year": 2016, "work_id": "W1", "raw_affil": "Monash",
         "canonical_affil_id": MON, "is_modal": True},
        {"person_id": "P_Z", "year": 2016, "work_id": "W2", "raw_affil": "IFN",
         "canonical_affil_id": IFN, "is_modal": False},
        {"person_id": "P_F", "year": 2014, "work_id": "W3", "raw_affil": "UNSW",
         "canonical_affil_id": UNSW, "is_modal": False}])
    return r


def test_modal_flags_consume_u3_truth(tmp_path):
    """A row with is_modal=True for the department's institution in the arrival year → True; a row with is_modal=False → False;
    no (person, year, department) row → False (absence = no modal evidence for that department that year; the key is still present, supply is complete)."""
    from m7a_star.real_inputs import load_star_modal_flags
    flags = load_star_modal_flags(
        _modal_root(tmp_path),
        {ZID: (2016, "monash_econ"), "A_FALSE": (2014, "unsw_econ"),
         "A_NOROW": (2010, "monash_econ")},
        dept_inst_map={"monash_econ": MON, "unsw_econ": UNSW})
    assert flags == {ZID: True, "A_FALSE": False, "A_NOROW": False}


def test_modal_flags_unmapped_star_fails_loud(tmp_path):
    """A star without a person_map mapping → ValueError naming the star (S8-1 consume-only supply is broken, never default)."""
    from m7a_star.real_inputs import load_star_modal_flags
    with pytest.raises(ValueError, match="A_GHOST"):
        load_star_modal_flags(_modal_root(tmp_path), {"A_GHOST": (2010, "monash_econ")},
                              dept_inst_map={"monash_econ": MON})


def test_modal_flags_unknown_dept_fails_loud(tmp_path):
    """dept_key not in the mapping (outside the two-school smoke scope) → ValueError naming it (same defence as ship_events)."""
    from m7a_star.real_inputs import load_star_modal_flags
    with pytest.raises(ValueError, match="anu_econ"):
        load_star_modal_flags(_modal_root(tmp_path), {ZID: (2016, "anu_econ")},
                              dept_inst_map={"monash_econ": MON})
