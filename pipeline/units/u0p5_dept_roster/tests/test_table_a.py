"""U0.5 Table A ECON_DEPT_REGISTRY producer TDD - resolves the old project BLOCKER #1 "econ_dept_ids has no producer".

Coarse rule to start: econ_dept_ids = the university institution set of the two schools {Monash, UNSW}; downstream filters it to economics departments by
the member list + the G5 subfield (Economics and Econometrics). The boundary metadata comes from G5.
"""
import pytest

from common.schema import ECON_DEPT_REGISTRY, assert_matches_schema
from identity.golden import MONASH_CANONICAL_ID  # "I56590836"

_UNSW_INST_ID = "I31746571"  # pending human review (red-line neighbourhood)


def test_table_a_rows_schema_and_ids():
    from roster.table_a import build_table_a_rows

    rows = build_table_a_rows()
    assert len(rows) == 2  # coarse smoke test = the two schools Monash + UNSW
    for r in rows:
        assert_matches_schema(r.keys(), ECON_DEPT_REGISTRY, label="econ_dept_registry")  # exactly 10 columns
    by_key = {r["dept_key"]: r for r in rows}
    assert by_key["monash_econ"]["openalex_inst_id"] == MONASH_CANONICAL_ID
    assert by_key["unsw_econ"]["openalex_inst_id"] == _UNSW_INST_ID
    # G5: economics department, not business school + main subfield rule = Economics and Econometrics
    assert all(r["is_business_school"] is False for r in rows)
    assert all("Economics and Econometrics" in r["subfield_primary"] for r in rows)


def test_build_econ_dept_ids_folds_to_two_unis():
    from roster.table_a import build_econ_dept_ids, build_table_a_rows

    rows = build_table_a_rows()
    # the registry treats the 2 schools' institutions as education anchors (fold path1 self-in-registry -> returns itself)
    registry_by_id = {
        r["openalex_inst_id"]: {"openalex_id": r["openalex_inst_id"], "type": "education"}
        for r in rows
    }
    ids = build_econ_dept_ids(rows, registry_by_id)
    # coarse rule = the canonical institution set of the two schools (fed directly to U1 pass_a_seed_authors)
    assert ids == {MONASH_CANONICAL_ID, _UNSW_INST_ID}


def test_econ_dept_ids_drops_unfoldable():
    """An inst not in the registry (cannot fold to an education landing point) -> not in econ_dept_ids (a legitimate None, no error)."""
    from roster.table_a import build_econ_dept_ids

    rows = [{"dept_key": "x_econ", "university": "X", "openalex_inst_id": "I_GHOST",
             "dept_name_variants": ["Department of Economics"], "is_business_school": False,
             "subfield_primary": ["Economics and Econometrics"], "subfield_robustness_flagged": [],
             "subfield_excluded": ["Finance"], "source": "manual", "human_verified": False}]
    assert build_econ_dept_ids(rows, registry_by_id={}) == set()  # empty registry -> cannot fold -> empty set


def test_table_a_human_verified_both_signed():
    """UNSW I31746571 is confirmed (the full run showed that A5006435210/A5103238089/A5054240727
    all attach their home-school bylines to it) -> both schools' rows have
    human_verified=True (required for the historical roster step-0 pre-gate [red test #7] to pass)."""
    from roster.table_a import build_table_a_rows

    assert all(r["human_verified"] is True for r in build_table_a_rows())


def test_table_a_variants_evidence_backed():
    """dept_name_variants contains the real variants added by the full works_affil evidence scan:
    - UNSW's historical old name 'Department of Economics' (a real string for 141 authors, e.g. 'Department of Economics,
      University of New South Wales') - keeping only the current name would miss the early 2000s = the period the historical roster is meant to recover;
    - the Monash EBS '&' form (113 authors, 'Monash University - Department of Econometrics &
      Business Statistics') - the 'and' form of the phrase does not hit it."""
    from roster.table_a import build_table_a_rows

    by = {r["dept_key"]: r for r in build_table_a_rows()}
    assert "Department of Economics" in by["unsw_econ"]["dept_name_variants"]
    assert "Department of Econometrics & Business Statistics" in by["monash_econ"]["dept_name_variants"]


# ── Piece 3: write_table_a (deterministic parquet, in the table_b style) ──────────────────
def test_write_table_a_deterministic_schema_and_lists(tmp_path):
    """write_table_a writes a deterministic parquet: reads back 2 rows, 10-column schema, list column round-trips, two writes are byte-equal."""
    import hashlib
    import pyarrow.parquet as pq
    from roster.table_a import build_table_a_rows, write_table_a

    rows = build_table_a_rows()
    t1, t2 = tmp_path / "a1.parquet", tmp_path / "a2.parquet"
    write_table_a(rows, t1)
    write_table_a(rows, t2)

    back = pq.read_table(str(t1)).to_pylist()
    assert len(back) == 2
    assert set(back[0].keys()) == set(ECON_DEPT_REGISTRY.keys()), "written columns = the 10 columns of ECON_DEPT_REGISTRY"
    by = {r["dept_key"]: r for r in back}
    assert by["monash_econ"]["openalex_inst_id"] == MONASH_CANONICAL_ID
    assert "Economics and Econometrics" in by["monash_econ"]["subfield_primary"], "list columns must round-trip"
    assert hashlib.sha256(t1.read_bytes()).hexdigest() == hashlib.sha256(t2.read_bytes()).hexdigest(), (
        "two writes of the same input must be byte-identical (deterministic)"
    )


# ── Piece 3: run_u0p5.main_table_a wiring (produce + write Table A + summary; does not touch the real SSD, uses a tmp target) ──
def test_main_table_a_writes_table_and_summary(tmp_path):
    """main_table_a(target=tmp) -> writes Table A parquet (2 rows) + summary_table_a.json in the same directory; returns the summary."""
    import pyarrow.parquet as pq
    from roster.run_u0p5 import main_table_a

    target = tmp_path / "econ_dept_registry.parquet"
    summary = main_table_a(target=target)

    assert target.exists()
    assert len(pq.read_table(str(target)).to_pylist()) == 2
    assert (tmp_path / "summary_table_a.json").exists(), "the summary sidecar goes in the same directory as target (tmp, never touches the real SSD)"
    assert summary["table_a_rows"] == 2
    assert summary["openalex_inst_ids"]["monash_econ"] == MONASH_CANONICAL_ID
