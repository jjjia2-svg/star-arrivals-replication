"""U0 registration red tests for the historical roster (the u0p5_hist byline line): schema + exit codes + threshold keys.

Covers:
  - the three byline_* intermediate tables are registered in common/schema.py (the core table BYLINE_YEAR_EVIDENCE
    must contain source_work_ids: the lifeline that every year is traceable to its source);
  - five new exit codes numbered consecutively 25-29 (no collision with 12-24, none in the 1-11 range);
  - roster.dept_membership_min = 2 (distinct years, an independent threshold,
    never reusing population_gate.pop_min).
"""
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))


def test_byline_schemas_registered():
    from common import schema as S
    # match_style: archive sources (RePEc style) stamp the "current unit" onto historical papers
    # ('Monash University - Department of Economics' pulls Yves Zenou back to 1998) -> tag each match mechanically as
    # printed (department first / nested hierarchy) vs stamped (university first, joined by a bare separator); how the tag is used is left open.
    assert S.BYLINE_DEPT_HITS == {
        "work_id": "str", "author_id": "str", "dept_key": "str",
        "matched_phrase": "str", "institution_id": "str", "match_style": "category",
    }
    # core base table: every year point must trace back to concrete works (source_work_ids is not a decorative column);
    # n_printed_style = the number of works behind that year point that have printed-form support (=0 -> stamped-only support, a reduced-confidence flag).
    assert S.BYLINE_YEAR_EVIDENCE == {
        "author_id": "str", "dept_key": "str", "year": "int16",
        "n_papers_that_year": "int32", "n_printed_style": "int32",
        "source_work_ids": "list<str>",
    }
    # skeleton = a subset of table B (the same 8 columns; evidence is fixed to raw_affil_year, guaranteed by the writer)
    assert S.BYLINE_ROSTER_SKELETON == S.DEPT_ROSTER_PANEL


def test_hist_roster_exit_codes_sequential_and_unique():
    from identity import exit_codes as E
    assert E.EXIT_ROSTER_UPSTREAM_FAIL == 25
    assert E.EXIT_ROSTER_REGISTRY_MISSING == 26
    assert E.EXIT_BYLINE_SCHEMA_FAIL == 27
    assert E.EXIT_BYLINE_EMPTY_HITS_FAIL == 28
    assert E.EXIT_BYLINE_YEAR_NULL_FAIL == 29
    vals = [getattr(E, n) for n in dir(E) if n.startswith("EXIT_")]
    assert len(vals) == len(set(vals)), "exit code collision"


def test_dept_membership_min_signed_independent_of_pop_min():
    # department-membership criterion: >=2 distinct years, an independent key (guards against rule migration: not the string rule of pop_min)
    from common._redlines import RED, require
    assert require("roster", "dept_membership_min") == 2
    assert RED["population_gate"]["pop_min"] == "ge_2_distinct_publication_years"  # each exists independently
