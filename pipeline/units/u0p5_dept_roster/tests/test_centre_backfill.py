"""Roster v3 centre backfill merge - centre_backfill TDD.

In plain words: the boundary rule (economics-type centres of the same establishment/community count towards the in-post pool) is applied retroactively to Monash/UNSW:
114 recommended additions + 3 held-over cases accepted + 6 missed department-core people go into the roster. Q6 handover: they enter the
main-analysis in-post pool and the affil_type label is kept (centre_only / both, written machine-readably into evidence).
Output follows the starfix precedent: v2 untouched, new version directory roster_v2026-07-11_centres/, never overwriting an existing one.
Hard rules: v2 rows pass through byte for byte; the 6 hand-checked year-correction rows must still be present unchanged (guard);
addition rows never collide on the key (author_id|name, dept, evidence) with existing ones; a name/id collision fails loudly.
"""
import pytest

from roster.centre_backfill import (
    build_centre_addition_rows,
    merge_v3,
)


def _v2_row(aid, name, *, dept="monash_econ", ys=None, ye=None,
            evidence="official_roster", conf="high", hv=False):
    return {"dept_key": dept, "author_id": aid, "display_name": name,
            "year_start": ys, "year_end": ye, "evidence": evidence,
            "confidence": conf, "human_verified": hv}


def _addition(name="Person H", *, dept="monash_econ", aid="A_PH",
              segments=((1989, 2016),), affil="centre_only", red_dot=False,
              centre="CHE", conf="medium", url="https://example.org/evidence"):
    return {
        "display_name": name, "dept_key": dept, "author_id": aid,
        "segments": [list(s) for s in segments], "affil_type": affil,
        "dept_red_dot": red_dot, "centre": centre, "confidence": conf,
        "years_text_raw": "1989–c.2016 全职教授", "evidence_urls": [url],
        "aid_note": None, "ruling": None, "note": "",
    }


# ---- build_centre_addition_rows: addition records -> Table B rows ---------------------------

def test_addition_one_row_per_segment_with_machine_readable_labels():
    """A one-spell person yields 1 row; a two-spell person yields 2 rows (Person CB2 precedent); evidence carries centre_roster +
    a machine-readable affil_type label + the evidence URL; hv is always False (year spans have not passed the final per-person check)."""
    rows = build_centre_addition_rows([
        _addition(),
        _addition(name="Person CB2", dept="unsw_econ", aid="A_PH2",
                  segments=((2011, 2013), (2016, 2026))),
    ])
    assert len(rows) == 3
    r0 = rows[0]
    assert r0["dept_key"] == "monash_econ" and r0["author_id"] == "A_PH"
    assert r0["year_start"] == 1989 and r0["year_end"] == 2016
    assert r0["human_verified"] is False
    assert "centre_roster:CHE" in r0["evidence"]
    assert "affil_type=centre_only" in r0["evidence"]
    assert "https://example.org/evidence" in r0["evidence"]
    second_dept = [r for r in rows if r["author_id"] == "A_PH2"]
    assert [(r["year_start"], r["year_end"]) for r in second_dept] == [(2011, 2013), (2016, 2026)]
    # the evidence of the two spell rows must differ (segment note), otherwise the (aid,dept,evidence) key collides
    assert second_dept[0]["evidence"] != second_dept[1]["evidence"]


def test_dept_red_dot_rows_use_dept_history_evidence_and_both():
    """Missed department-core people: evidence prefix dept_history_web + affil_type=both (department + centre double evidence)."""
    rows = build_centre_addition_rows([
        _addition(name="Person I", aid="A_PI", segments=((1988, 2004),),
                  affil="both", red_dot=True, centre="CIREO"),
    ])
    assert len(rows) == 1
    assert rows[0]["evidence"].startswith("dept_history_web:")
    assert "affil_type=both" in rows[0]["evidence"]


def test_addition_none_author_id_and_none_years_pass_through():
    """Red line #1: candidate not clean -> author_id=None + confidence=low written as is (never guess);
    a year span with a missing edge (Person CB3 start / Person CB4 end) -> None as is."""
    rows = build_centre_addition_rows([
        _addition(name="Person J", aid=None, segments=((1999, 2004),), conf="low"),
        _addition(name="Person CB3", aid="A_PK", segments=((None, 2016),)),
        _addition(name="Person CB4", dept="unsw_econ", aid="A_PL", segments=((2011, None),)),
    ])
    by = {r["display_name"]: r for r in rows}
    assert by["Person J"]["author_id"] is None
    assert by["Person J"]["confidence"] == "low"
    assert by["Person CB3"]["year_start"] is None
    assert by["Person CB4"]["year_end"] is None


# ---- merge_v3: v2 + additions -> v3 -------------------------------------------------

def _v2_by_school():
    return {
        "monash_econ": [
            _v2_row("A_S1", "Person CB1", ys=2021, ye=2025,
                    evidence="human_verified_web:test evidence (2021-)", hv=True),
            _v2_row("A_OLD", "Existing Person", ys=2003, ye=2020),
        ],
        "unsw_econ": [
            _v2_row("A_UN", "UNSW Person", dept="unsw_econ", ys=2010, ye=2026),
        ],
    }


def _year_fix_expect():
    # guard sample for the 6 starfix corrections: (aid, dept) -> year_start (hv=True)
    return {"A_S1": {"dept_key": "monash_econ", "year_start": 2021}}


def test_merge_appends_additions_and_keeps_v2_rows_verbatim():
    adds = build_centre_addition_rows([_addition()])
    res = merge_v3(_v2_by_school(), adds, year_fixes=_year_fix_expect())
    mon = res["rows_by_school"]["monash_econ"]
    assert len(mon) == 3
    # v2 rows first, field by field unchanged
    assert mon[0] == _v2_by_school()["monash_econ"][0]
    assert mon[1] == _v2_by_school()["monash_econ"][1]
    assert res["report"]["n_added"] == {"monash_econ": 1, "unsw_econ": 0}


def test_merge_rejects_author_id_collision_with_v2():
    """An addition collides with an existing v2 author_id -> fail loudly (a centre member already in the department roster is not a missed person; a human checks)."""
    adds = build_centre_addition_rows([_addition(aid="A_OLD")])
    with pytest.raises(ValueError, match="A_OLD"):
        merge_v3(_v2_by_school(), adds, year_fixes=_year_fix_expect())


def test_merge_rejects_display_name_collision_with_v2():
    """An addition collides with an existing v2 display_name (after normalisation) -> fail loudly (probably one person with two ids; a human checks)."""
    adds = build_centre_addition_rows([_addition(name="existing  person", aid="A_NEW")])
    with pytest.raises(ValueError, match="[Ee]xisting"):
        merge_v3(_v2_by_school(), adds, year_fixes=_year_fix_expect())


def test_merge_verifies_year_fix_rows_still_intact():
    """A hand-checked year-correction row was changed (year/hv mismatch) -> fail loudly (guards against pointing at the wrong version or contamination midway)."""
    v2 = _v2_by_school()
    v2["monash_econ"][0]["year_start"] = 2016            # tampered back to the old year
    adds = build_centre_addition_rows([_addition()])
    with pytest.raises(ValueError, match="A_S1"):
        merge_v3(v2, adds, year_fixes=_year_fix_expect())


def test_merge_rejects_duplicate_addition_keys():
    """Addition rows repeating the same (author_id, dept, evidence) key -> fail loudly."""
    a = _addition()
    adds = build_centre_addition_rows([a, a])
    with pytest.raises(RuntimeError, match="duplicate"):
        merge_v3(_v2_by_school(), adds, year_fixes=_year_fix_expect())


def test_merge_schema_guard_every_row():
    """Every v3 row passes the DEPT_ROSTER_PANEL schema guard (extra or missing keys raise)."""
    adds = build_centre_addition_rows([_addition()])
    adds[0].pop("confidence")
    with pytest.raises(Exception):
        merge_v3(_v2_by_school(), adds, year_fixes=_year_fix_expect())
