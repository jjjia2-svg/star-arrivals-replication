"""Nominal-affiliation behaviour flag (nominal_affiliation_flag) TDD - the mechanical part of root cause C.

In plain words: parse.py only recognises adjunct/emeritus/visiting in the title string, so people with no real tie to the home school
(full-time at Stanford, listed in the Monash directory under a plain "Professor") slip through. This module adds a **behavioural diagnostic**:
for a roster member with an author_id, use U1 works_affil to compute "the share of the person's own works that carry the home institution id";
share < threshold (default 0.05) or zero -> nominal_affiliation_flag.

Hard rules (the identification layer decides nothing here):
  - **only raise a flag and list people, never remove anyone** (who is removed is decided by hand; follows the auditable signal_discards precedent);
  - the threshold is a parameter, the default 0.05 is only the diagnostic setting (root-cause table C: '21 with zero Australian works, 26 with share < 0.05');
  - zero works in the corpus != nominal affiliation -> a separate reason (no_works_in_corpus, cannot be assessed -> a human decides);
  - institution matching folds lineage (the home canonical id + all child institutions whose lineage contains it).
"""
import pathlib

import pytest

from roster.nominal_affil import (
    DEFAULT_NOMINAL_THRESHOLD,
    build_flag_table,
    count_author_school_works,
    flag_member,
)


# ═══ flag_member - pure function ════════════════════════════════════════════════════
def test_default_threshold_is_five_percent_diagnostic():
    assert DEFAULT_NOMINAL_THRESHOLD == 0.05


def test_zero_school_works_flags():
    r = flag_member("A1", n_works_total=61, n_works_school=0)
    assert r["nominal_affiliation_flag"] is True
    assert r["reason"] == "zero_school_works"
    assert r["school_share"] == 0.0


def test_below_threshold_flags():
    r = flag_member("A1", n_works_total=100, n_works_school=4)
    assert r["nominal_affiliation_flag"] is True
    assert r["reason"] == "below_threshold"
    assert r["school_share"] == pytest.approx(0.04)


def test_at_or_above_threshold_no_flag():
    r = flag_member("A1", n_works_total=100, n_works_school=5)
    assert r["nominal_affiliation_flag"] is False
    assert r["reason"] is None
    r2 = flag_member("A1", n_works_total=10, n_works_school=9)
    assert r2["nominal_affiliation_flag"] is False


def test_no_works_in_corpus_is_distinct_reason():
    """Zero works in the corpus = cannot be assessed, not evidence of nominal affiliation -> a separate reason, share=None, still flagged for a human decision."""
    r = flag_member("A1", n_works_total=0, n_works_school=0)
    assert r["nominal_affiliation_flag"] is True
    assert r["reason"] == "no_works_in_corpus"
    assert r["school_share"] is None


def test_school_exceeding_total_fails_loud():
    with pytest.raises(ValueError, match="school"):
        flag_member("A1", n_works_total=3, n_works_school=4)


def test_custom_threshold_respected():
    r = flag_member("A1", n_works_total=100, n_works_school=7, threshold=0.10)
    assert r["nominal_affiliation_flag"] is True and r["reason"] == "below_threshold"


# ═══ build_flag_table - assembly + deterministic sorting ════════════════════════════════════
def test_build_flag_table_sorted_flagged_first_share_asc():
    members = [
        {"author_id": "A_ok", "display_name": "Fine", "dept_key": "monash_econ",
         "n_works_total": 50, "n_works_school": 40},
        {"author_id": "A_zero", "display_name": "Zero-share Type", "dept_key": "monash_econ",
         "n_works_total": 61, "n_works_school": 0},
        {"author_id": "A_low", "display_name": "Low Share", "dept_key": "unsw_econ",
         "n_works_total": 100, "n_works_school": 2},
        {"author_id": "A_none", "display_name": "No Works", "dept_key": "unsw_econ",
         "n_works_total": 0, "n_works_school": 0},
    ]
    table = build_flag_table(members)
    assert [r["author_id"] for r in table] == ["A_none", "A_zero", "A_low", "A_ok"]
    flags = {r["author_id"]: r["nominal_affiliation_flag"] for r in table}
    assert flags == {"A_none": True, "A_zero": True, "A_low": True, "A_ok": False}
    # every row carries the threshold for the record (the report is reproducible)
    assert all(r["threshold"] == DEFAULT_NOMINAL_THRESHOLD for r in table)


# ═══ count_author_school_works - DuckDB count (lineage folded) ══════════════════
@pytest.fixture()
def tiny_corpus(tmp_path):
    """Small works_affil + institutions fixture:
      SCHOOL   = I_school (home canonical)
      I_child  = lineage contains I_school (child institution of the home school -> folded, counts as home)
      I_other  = another school
    Authors:
      A_real: 3 works, 2 of them at the home school (1 canonical + 1 child) -> share 2/3
      A_nom:  2 works, all at another school -> share 0
      A_out:  in the corpus but not in the member list -> not in the result
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    wa_dir = tmp_path / "works_affil" / "bucket=000"
    wa_dir.mkdir(parents=True)
    rows = [
        ("W1", "A_real", "I_school"),
        ("W1", "A_real", "I_other"),      # the same work with a double affiliation -> the home-school work is counted once
        ("W2", "A_real", "I_child"),
        ("W3", "A_real", "I_other"),
        ("W4", "A_nom", "I_other"),
        ("W5", "A_nom", None),            # row without an institution -> goes into the denominator only
        ("W6", "A_out", "I_school"),
    ]
    pq.write_table(pa.table({
        "work_id": [r[0] for r in rows],
        "author_id": [r[1] for r in rows],
        "institution_id": [r[2] for r in rows],
    }), str(wa_dir / "part-00000.parquet"))

    inst_dir = tmp_path / "institutions" / "bucket=000"
    inst_dir.mkdir(parents=True)
    pq.write_table(pa.table({
        "institution_id": ["I_school", "I_child", "I_other"],
        "lineage": [["I_school"], ["I_child", "I_school"], ["I_other"]],
    }), str(inst_dir / "part-00000.parquet"))

    return {"works_affil_glob": str(tmp_path / "works_affil" / "*" / "*.parquet"),
            "institutions_glob": str(tmp_path / "institutions" / "*" / "*.parquet")}


def test_count_folds_lineage_and_counts_distinct_works(tiny_corpus):
    counts = count_author_school_works(
        members=[("A_real", "monash_econ"), ("A_nom", "monash_econ")],
        school_inst_ids={"monash_econ": "I_school"},
        **tiny_corpus)
    assert counts[("A_real", "monash_econ")] == {"n_works_total": 3, "n_works_school": 2}
    assert counts[("A_nom", "monash_econ")] == {"n_works_total": 2, "n_works_school": 0}
    assert ("A_out", "monash_econ") not in counts


def test_count_member_absent_from_corpus_gets_zero_totals(tiny_corpus):
    counts = count_author_school_works(
        members=[("A_ghost", "monash_econ")],
        school_inst_ids={"monash_econ": "I_school"},
        **tiny_corpus)
    assert counts[("A_ghost", "monash_econ")] == {"n_works_total": 0, "n_works_school": 0}


def test_count_unknown_dept_fails_loud(tiny_corpus):
    with pytest.raises(ValueError, match="dept_key"):
        count_author_school_works(
            members=[("A_real", "nowhere_econ")],
            school_inst_ids={"monash_econ": "I_school"},
            **tiny_corpus)
