"""m7a discipline_gate — discipline gate (flag mode) + sanity gate: TDD red tests (root cause D).

Root problem (GAP-3): the registry's subfield_excluded=[Finance] had no consumer anywhere in the pipeline (a config that looked active but did nothing).
This gate makes it a real consumer: at the U4 cell-candidate step → if any in-post member's publications have a modal subfield in that school's
excluded list → set discipline_flag (**no hard removal** — removal is a manual decision).
Sanity gate (root cause E, fix 3): candidates with academic_age≤1 get sanity_flag_age and go on the manual-review list.
"""
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from m7a_star.discipline_gate import (
    SUBFIELD_NAME_TO_ID,
    discipline_flag_rows,
    excluded_ids_by_dept,
    modal_subfield_from_counts,
    sanity_age_flag_rows,
)

ECON, FIN = "2002", "2003"


# ============ name → subfield_id mapping (registry stores names, works stores ids) ============

def test_name_to_id_mapping_covers_signed_names():
    """The registry uses names (Finance), works uses ids (2003) — the mapping table must cover both excluded values."""
    assert SUBFIELD_NAME_TO_ID["Finance"] == FIN
    assert SUBFIELD_NAME_TO_ID["Economics and Econometrics"] == ECON


def test_excluded_ids_by_dept_maps_names():
    reg = [{"dept_key": "monash_econ", "subfield_excluded": ["Finance"]},
           {"dept_key": "unsw_econ", "subfield_excluded": []}]
    got = excluded_ids_by_dept(reg)
    assert got == {"monash_econ": frozenset({FIN}), "unsw_econ": frozenset()}


def test_excluded_ids_by_dept_unknown_name_fails_loud():
    """A discipline name in the registry that is not in the mapping table → raise (prevents "config changed, gate silently does nothing" = GAP-3 recurring)."""
    reg = [{"dept_key": "x_econ", "subfield_excluded": ["Astrology"]}]
    with pytest.raises(ValueError, match="Astrology"):
        excluded_ids_by_dept(reg)


# ============ modal subfield (mode; ties take the smallest id = same as S8-3) ============

def test_modal_subfield_tie_breaks_min_id():
    assert modal_subfield_from_counts({ECON: 2, FIN: 2}) == ECON     # tie → smallest id
    assert modal_subfield_from_counts({FIN: 3, ECON: 1}) == FIN
    assert modal_subfield_from_counts({}) is None


# ============ discipline_flag (flag only, no hard removal) ============

def test_discipline_flags_hit_and_miss():
    cands = [{"author_id": "A_FIN", "name": "Fin Person", "dept": "monash_econ"},
             {"author_id": "A_EC", "name": "Econ Person", "dept": "monash_econ"}]
    modal = {"A_FIN": FIN, "A_EC": ECON}
    excl = {"monash_econ": frozenset({FIN})}
    rows = discipline_flag_rows(cands, modal, excl)
    by = {r["author_id"]: r for r in rows}
    assert by["A_FIN"]["discipline_flag"] is True
    assert by["A_FIN"]["modal_subfield"] == FIN
    assert by["A_EC"]["discipline_flag"] is False
    # Flag only: both people stay in the rows (nobody is removed — who to remove is a manual identification decision)
    assert len(rows) == 2


def test_discipline_flags_missing_dept_in_registry_fails_loud():
    """Candidate's dept not in the registry → raise (GAP-4 scope mismatch is never silently passed)."""
    cands = [{"author_id": "A1", "name": "X", "dept": "ghost_econ"}]
    with pytest.raises(ValueError, match="ghost_econ"):
        discipline_flag_rows(cands, {"A1": ECON}, {"monash_econ": frozenset()})


def test_discipline_flags_no_modal_signal_flag_none():
    """Candidate with no subfield signal (0 works) → modal None → flag None (cannot be evaluated; never fake False)."""
    cands = [{"author_id": "A0", "name": "NoWorks", "dept": "monash_econ"}]
    rows = discipline_flag_rows(cands, {}, {"monash_econ": frozenset({FIN})})
    assert rows[0]["modal_subfield"] is None and rows[0]["discipline_flag"] is None


# ============ Sanity gate: academic_age ≤ 1 ============

def test_sanity_age_flags_low_age_flagged():
    stars = [
        {"author_id": "A0", "name": "Zero", "dept": "monash_econ", "academic_age": 0},
        {"author_id": "A1", "name": "One", "dept": "monash_econ", "academic_age": 1},
        {"author_id": "A2", "name": "Two", "dept": "monash_econ", "academic_age": 2},
        {"author_id": "AN", "name": "NoPool", "dept": "unsw_econ", "academic_age": None},
    ]
    rows = sanity_age_flag_rows(stars)
    by = {r["author_id"]: r for r in rows}
    assert by["A0"]["sanity_flag_age"] is True
    assert by["A1"]["sanity_flag_age"] is True
    assert by["A2"]["sanity_flag_age"] is False
    assert by["AN"]["sanity_flag_age"] is None       # not in the pool, academic age unknown → None, not False


# ============ build_star_set wiring (registry injected → real consumer; default None means no behaviour change) ============

_ROSTER_SCHEMA = pa.schema([
    ("author_id", pa.string()), ("display_name", pa.string()), ("dept_key", pa.string()),
    ("year_start", pa.int64()), ("confidence", pa.string()), ("human_verified", pa.bool_()),
])


def _w(root, subpath, rows, schema=None):
    p = root / subpath
    p.parent.mkdir(parents=True, exist_ok=True)
    tbl = pa.Table.from_pylist(rows, schema=schema) if schema else pa.Table.from_pylist(rows)
    pq.write_table(tbl, str(p))


def _mini_root(tmp_path):
    """Two-candidate mini root: A_FIN publishes only in Finance (2003), A_EC only in economics (2002); both arrive in 2016."""
    from run_u4 import ROSTER_FILES
    r = tmp_path
    _w(r, ROSTER_FILES[0], [
        {"author_id": "A_FIN", "display_name": "Fin Person", "dept_key": "monash_econ",
         "year_start": 2016, "confidence": "high", "human_verified": True},
        {"author_id": "A_EC", "display_name": "Econ Person", "dept_key": "monash_econ",
         "year_start": 2016, "confidence": "high", "human_verified": True},
    ], schema=_ROSTER_SCHEMA)
    _w(r, ROSTER_FILES[1], [], schema=_ROSTER_SCHEMA)
    _w(r, "u1_edges_full_2026-07-05/authorship_edges/part.parquet", [
        {"author_id": "A_FIN", "work_id": "W1"}, {"author_id": "A_FIN", "work_id": "W2"},
        {"author_id": "A_EC", "work_id": "W3"}])
    _w(r, "u1_edges_full_2026-07-05/works/part.parquet", [
        {"work_id": "W1", "publication_year": 2010, "cited_by_count": 50, "subfield_id": FIN},
        {"work_id": "W2", "publication_year": 2012, "cited_by_count": 40, "subfield_id": FIN},
        {"work_id": "W3", "publication_year": 2010, "cited_by_count": 30, "subfield_id": ECON}])
    _w(r, "u1_edges_full_2026-07-05/institutions/part.parquet", [
        {"institution_id": "I56590836", "country_code": "AU"}])
    _w(r, "u2_person_map_2026-07-05/person_map/part.parquet", [
        {"author_id": "A_FIN", "person_id": "P_F"}, {"author_id": "A_EC", "person_id": "P_E"}])
    _w(r, "u3_panel_2026-07-06/panel/part.parquet",
       [{"person_id": "P_F", "year": 2016, "primary_affil_id": "I56590836"}])
    _w(r, "u3_panel_2026-07-06/affil_timeline/part.parquet",
       [{"person_id": "P_F", "year": 2010, "raw_affil": "X", "canonical_affil_id": "I56590836"}])
    return r


def test_build_star_set_registry_rows_attach_discipline_flags(tmp_path):
    """registry_rows injected → result['discipline_flags']: A_FIN (modal=Finance) is flagged,
    A_EC is not; the stars row schema is untouched (the flag does not enter the star_set frozen surface)."""
    from run_u4 import build_star_set
    reg = [{"dept_key": "monash_econ", "subfield_excluded": ["Finance"]},
           {"dept_key": "unsw_econ", "subfield_excluded": ["Finance"]}]
    res = build_star_set(_mini_root(tmp_path), registry_rows=reg)
    flags = {r["author_id"]: r for r in res["discipline_flags"]}
    assert flags["A_FIN"]["discipline_flag"] is True
    assert flags["A_EC"]["discipline_flag"] is False
    star_keys = set(res["stars"][0].keys())
    assert "discipline_flag" not in star_keys        # frozen surface unchanged


# ============ E5 productionisation: discipline gate flag → excluded from candidates by default ============

def test_build_star_set_discipline_gate_excludes_by_default(tmp_path):
    """Must be red (rule: "actuarial / non-economics excluded by discipline"): registry injected + default mode → candidates with discipline_flag=True
    are **excluded from the candidate cells by default** (not in stars / not in the pool); every excluded person goes into the auditable
    result['discipline_excluded'] (author_id/modal/dept all included; reversible and re-checkable)."""
    from run_u4 import build_star_set
    reg = [{"dept_key": "monash_econ", "subfield_excluded": ["Finance"]},
           {"dept_key": "unsw_econ", "subfield_excluded": ["Finance"]}]
    res = build_star_set(_mini_root(tmp_path), registry_rows=reg)
    star_ids = {s["author_id"] for s in res["stars"]}
    assert "A_FIN" not in star_ids                   # excluded by default (exclusion by discipline)
    assert "A_EC" in star_ids                        # economists are unaffected
    excl = {r["author_id"]: r for r in res["discipline_excluded"]}
    assert set(excl) == {"A_FIN"}
    assert excl["A_FIN"]["modal_subfield"] == FIN
    assert excl["A_FIN"]["dept"] == "monash_econ"
    # the flag table still covers the excluded (complete audit: the basis for exclusion can be looked up)
    flags = {r["author_id"]: r for r in res["discipline_flags"]}
    assert flags["A_FIN"]["discipline_flag"] is True


def test_build_star_set_discipline_gate_flag_mode_rollback(tmp_path):
    """Reversible: discipline_gate_mode='flag' → flag only, no exclusion (the original E1 behaviour), a one-step rollback path."""
    from run_u4 import build_star_set
    reg = [{"dept_key": "monash_econ", "subfield_excluded": ["Finance"]},
           {"dept_key": "unsw_econ", "subfield_excluded": ["Finance"]}]
    res = build_star_set(_mini_root(tmp_path), registry_rows=reg,
                         discipline_gate_mode="flag")
    star_ids = {s["author_id"] for s in res["stars"]}
    assert "A_FIN" in star_ids                       # flag mode: no exclusion
    assert res["discipline_excluded"] == []


def test_build_star_set_discipline_gate_unassessable_not_excluded(tmp_path):
    """Zero-signal candidate (no works at all → modal None, flag None) is **not excluded** (cannot be evaluated ≠ should be removed;
    never fake False and never treat as True and remove)."""
    from run_u4 import build_star_set, ROSTER_FILES
    r = _mini_root(tmp_path)
    _w(r, ROSTER_FILES[1], [
        {"author_id": "A_MUTE", "display_name": "No Works", "dept_key": "unsw_econ",
         "year_start": 2016, "confidence": "high", "human_verified": True}],
       schema=_ROSTER_SCHEMA)
    _w(r, "u2_person_map_2026-07-05/person_map/part_mute.parquet",
       [{"author_id": "A_MUTE", "person_id": "P_MU"}])
    reg = [{"dept_key": "monash_econ", "subfield_excluded": ["Finance"]},
           {"dept_key": "unsw_econ", "subfield_excluded": ["Finance"]}]
    res = build_star_set(r, registry_rows=reg)
    star_ids = {s["author_id"] for s in res["stars"]}
    assert "A_MUTE" in star_ids                      # cannot be evaluated → keep (all-None row)
    flags = {x["author_id"]: x for x in res["discipline_flags"]}
    assert flags["A_MUTE"]["discipline_flag"] is None
    assert {x["author_id"] for x in res["discipline_excluded"]} == {"A_FIN"}


def test_build_star_set_discipline_gate_bad_mode_fails_loud(tmp_path):
    """Misspelled mode → ValueError, fail loudly (never silently treated as the default)."""
    from run_u4 import build_star_set
    with pytest.raises(ValueError, match="discipline_gate_mode"):
        build_star_set(_mini_root(tmp_path), registry_rows=[],
                       discipline_gate_mode="oops")


def test_build_star_set_default_no_registry_keeps_none(tmp_path):
    """Default registry_rows=None → discipline_flags=None (no behaviour change; existing runs unaffected);
    sanity_age_flags is always produced (pure diagnostics, does not touch stars)."""
    from run_u4 import build_star_set
    res = build_star_set(_mini_root(tmp_path))
    assert res["discipline_flags"] is None
    ages = {r["author_id"]: r for r in res["sanity_age_flags"]}
    assert set(ages) == {"A_FIN", "A_EC"}
    # A_FIN first publishes in 2010, Y=2015 → age 5; A_EC likewise → neither should be flagged
    assert ages["A_FIN"]["sanity_flag_age"] is False
    assert ages["A_EC"]["sanity_flag_age"] is False


def test_build_star_set_sanity_flags_low_age_candidate(tmp_path):
    """A candidate who first publishes only in the year before arrival (age 0) → sanity_flag_age=True, goes on the manual-review list
    (root cause E: aage=0 of the A5086383420/A5053503664 type = a wrong-id / wrong-year signal; diagnostic, not a hard override)."""
    from run_u4 import build_star_set, ROSTER_FILES
    r = _mini_root(tmp_path)
    # Add a low-age candidate: first publication = 2015 = t−1 → aage 0
    _w(r, ROSTER_FILES[1], [
        {"author_id": "A_YOUNG", "display_name": "Young One", "dept_key": "unsw_econ",
         "year_start": 2016, "confidence": "high", "human_verified": True}],
       schema=_ROSTER_SCHEMA)
    _w(r, "u1_edges_full_2026-07-05/authorship_edges/part2.parquet",
       [{"author_id": "A_YOUNG", "work_id": "W9"}])
    _w(r, "u1_edges_full_2026-07-05/works/part2.parquet",
       [{"work_id": "W9", "publication_year": 2015, "cited_by_count": 1, "subfield_id": ECON}])
    # Since E5, a candidate must be in person_map (not in the map = a genuine NULL, age cannot be evaluated) — add a singleton cluster.
    _w(r, "u2_person_map_2026-07-05/person_map/part2.parquet",
       [{"author_id": "A_YOUNG", "person_id": "P_Y"}])
    res = build_star_set(r)
    ages = {x["author_id"]: x for x in res["sanity_age_flags"]}
    assert ages["A_YOUNG"]["academic_age"] == 0
    assert ages["A_YOUNG"]["sanity_flag_age"] is True
