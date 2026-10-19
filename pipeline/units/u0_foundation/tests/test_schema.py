"""Tests for the U0 schema.py contract (group 1: T01-T06).

Covers the 28 table-schema constants and the enforcement of assert_matches_schema: the row key
set must equal the schema key set exactly; extra or missing keys both raise. Column names and
types follow the specification verbatim; no invented columns.

T01 one extra row key -> raise (the row key set must equal the schema key set exactly)
T02 one missing row key (CANONICAL_ID_MAP without is_deleted) -> raise (CT-4d: exactly 4 keys)
T03 ANALYSIS_FRAME has exactly 15 columns, includes fwci_frac_ex_star, has no group/pub_frac
    (group dropped 13->12; then 12->15: pub_frac renamed pub_count
    + new pub_count_ex_star/fwci_mean/fwci_mean_ex_star)
T04 REFS_EDGES column name = referenced_work_id (not ref_work_id) (official anchor DA-6b)
T05 every one of the 28 constants can be imported from common.schema, no dangling import
T06 GENERATION_PERSON PK does not contain year (gen_pk_includes_year=false)
T07 STAR_SET has exactly 14 columns keyed by author_id (aligned with the star set frozen on
    2026-07-08; the old 9 columns star_person_id/metric/... are obsolete; column names and
    types follow the frozen star_set.parquet as measured)
T08 PAIRWISE_DOSE has exactly 11 columns including degree2_bridge_frozen (the 11 columns of
    the U5 dose spec v3, in spec order; the double-bridge-edge freeze flag)
"""
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

# all 28 schema constants + the enforcement function (imports must not dangle; failure = stop)
from common.schema import (  # noqa: E402
    assert_matches_schema,
    # B.1 base / ledger tables (3)
    CANONICAL_ID_MAP,
    LEDGER_EVENT,
    TALLY,
    # B.2 U1 output tables (9)
    AUTHORSHIP_EDGES,
    REFS_EDGES,
    WORKS,
    AUTHORS,
    WORK_TEXT,
    WORKS_AFFIL,
    WORK_FIRST_PUB,
    INSTITUTIONS,
    FWCI_BASELINE_POP,
    # B.3 U0.5 department roster tables (2)
    ECON_DEPT_REGISTRY,
    DEPT_ROSTER_PANEL,
    # B.4 U2 entity-resolution tables (2)
    PERSON_MAP,
    CLUSTER_PURITY,
    # B.5 analysis-layer tables (3)
    ANALYSIS_FRAME,
    PAPER_CONTRIB,
    OUTPUT,
    # B.6 schema constants of downstream units (9)
    PANEL,
    AFFIL_TIMELINE,
    STAR_SET,
    EVENTS,
    FWCI_BASELINE,
    GENERATION_PERSON,
    GENERATION_PAIR,
    PAIRWISE_DOSE,
    GROUPS_ABC,
)


# ---------------------------------------------------------------------------
# T01: one extra row key -> raise
# ---------------------------------------------------------------------------
def test_t01_extra_row_key_raises():
    # CANONICAL_ID_MAP has exactly 4 keys; a row with one extra surplus key must raise
    row_keys = set(CANONICAL_ID_MAP.keys()) | {"surplus_extra_col"}
    with pytest.raises((ValueError, KeyError, AssertionError)):
        assert_matches_schema(row_keys, CANONICAL_ID_MAP, label="CANONICAL_ID_MAP")


# ---------------------------------------------------------------------------
# T02: one missing row key (CANONICAL_ID_MAP without is_deleted) -> raise (CT-4d: exactly 4 keys)
# ---------------------------------------------------------------------------
def test_t02_missing_row_key_raises():
    assert "is_deleted" in CANONICAL_ID_MAP  # guards exactly 4 keys including is_deleted
    row_keys = set(CANONICAL_ID_MAP.keys()) - {"is_deleted"}
    with pytest.raises((ValueError, KeyError, AssertionError)):
        assert_matches_schema(row_keys, CANONICAL_ID_MAP, label="CANONICAL_ID_MAP")


def test_t02_canonical_id_map_exactly_four_keys():
    # CT-4d: exactly 4 keys = raw_id / canonical_id / id_type / is_deleted
    assert set(CANONICAL_ID_MAP.keys()) == {
        "raw_id",
        "canonical_id",
        "id_type",
        "is_deleted",
    }


# ---------------------------------------------------------------------------
# T03: ANALYSIS_FRAME has exactly 15 columns, includes fwci_frac_ex_star, has no group/pub_frac
#      (definition change: 12->15, pub_frac renamed pub_count +
#       new pub_count_ex_star/fwci_mean/fwci_mean_ex_star; the other 11 columns unchanged)
# ---------------------------------------------------------------------------
def test_t03_analysis_frame_exactly_15_cols_has_fwci_frac_ex_star_no_group():
    assert len(ANALYSIS_FRAME) == 15, (
        "after G1 removes group there are 12 columns; after the U5 specification pack: exactly 15 columns"
    )
    assert "fwci_frac_ex_star" in ANALYSIS_FRAME
    assert "group" not in ANALYSIS_FRAME       # group dropped (13->12)
    assert "pub_frac" not in ANALYSIS_FRAME    # the misleading old name was renamed pub_count
    assert "pub_count" in ANALYSIS_FRAME


# ---------------------------------------------------------------------------
# T04: REFS_EDGES column name = referenced_work_id (not ref_work_id)
# ---------------------------------------------------------------------------
def test_t04_refs_edges_col_name_referenced_work_id():
    assert "referenced_work_id" in REFS_EDGES  # official anchor DA-6b
    assert "ref_work_id" not in REFS_EDGES
    # the contract pins exactly 2 columns
    assert set(REFS_EDGES.keys()) == {"work_id", "referenced_work_id"}


# ---------------------------------------------------------------------------
# T04b: INSTITUTIONS has exactly 7 columns, including country_code (used to detect foreign institutions) + display_name;
#       associated_institutions stays list<dict> (essential for fold_to_canonical path3), the type column name is unchanged
#       (C-A: U1 alignment added display_name+country_code, 5->7 columns)
# ---------------------------------------------------------------------------
def test_t04b_institutions_seven_cols_has_country_code():
    assert len(INSTITUTIONS) == 7, "C-A: after adding display_name+country_code → exactly 7 columns"
    # Yves Zenou case: foreign institutions are detected via country_code (e.g. SE=Stockholm)
    assert "country_code" in INSTITUTIONS, "INSTITUTIONS must include country_code (supports identifying foreign institutions)"
    assert "display_name" in INSTITUTIONS  # readable for operations + used by downstream display
    # fold_to_canonical path3 reads assoc.relationship/type/id -> the type must be list<dict>, never list<str>
    assert INSTITUTIONS["associated_institutions"] == "list<dict>"
    # the column name type is unchanged (not inst_type), minimal change
    assert "type" in INSTITUTIONS and "inst_type" not in INSTITUTIONS
    assert set(INSTITUTIONS.keys()) == {
        "institution_id", "display_name", "country_code",
        "type", "lineage", "associated_institutions", "ror",
    }


# ---------------------------------------------------------------------------
# T05: all 28 constants can be imported from common.schema, no dangling import
# ---------------------------------------------------------------------------
def test_t05_all_28_schema_constants_importable_non_empty():
    all_28 = [
        CANONICAL_ID_MAP, LEDGER_EVENT, TALLY,
        AUTHORSHIP_EDGES, REFS_EDGES, WORKS, AUTHORS, WORK_TEXT,
        WORKS_AFFIL, WORK_FIRST_PUB, INSTITUTIONS, FWCI_BASELINE_POP,
        ECON_DEPT_REGISTRY, DEPT_ROSTER_PANEL,
        PERSON_MAP, CLUSTER_PURITY,
        ANALYSIS_FRAME, PAPER_CONTRIB, OUTPUT,
        PANEL, AFFIL_TIMELINE, STAR_SET, EVENTS, FWCI_BASELINE,
        GENERATION_PERSON, GENERATION_PAIR, PAIRWISE_DOSE, GROUPS_ABC,
    ]
    assert len(all_28) == 28
    for s in all_28:
        assert isinstance(s, dict)
        assert len(s) >= 1  # every schema has at least 1 column, none dangling


def test_t05_fwci_baseline_and_pop_coexist_distinct():
    # FWCI_BASELINE and FWCI_BASELINE_POP coexist and differ (derived table != accumulator population)
    assert FWCI_BASELINE is not FWCI_BASELINE_POP
    assert "expected_citations" in FWCI_BASELINE  # only in the derived table
    assert "expected_citations" not in FWCI_BASELINE_POP
    assert "cit_hist_32" in FWCI_BASELINE_POP  # only in the accumulator population


# ---------------------------------------------------------------------------
# T06: GENERATION_PERSON PK does not contain year (gen_pk_includes_year=false)
# ---------------------------------------------------------------------------
def test_t06_generation_person_pk_no_year():
    assert "year" not in GENERATION_PERSON  # the generation grouping key is frozen at the arrival year and does not vary with the panel year
    # PK = (person_id); the schema columns contain person_id and not year
    assert "person_id" in GENERATION_PERSON


# ---------------------------------------------------------------------------
# T07: STAR_SET has exactly 14 columns keyed by author_id
#      Aligned with the star set frozen on 2026-07-08: one row per frozen candidate carrying a star flag,
#      key = OpenAlex author_id (ranking reference pool = all author_ids); column names and types
#      follow the measured star_set.parquet (14 columns, 123 rows).
#      The old 9 columns (star_person_id/metric/evidence_source/dist_to_cutoff/...) are obsolete.
# ---------------------------------------------------------------------------
def test_t07_star_set_exactly_14_cols_author_id_keyed():
    # exactly 14 columns, in the column order of the parquet file
    assert list(STAR_SET.keys()) == [
        "author_id", "name", "dept", "arrival", "subfield", "age_bin",
        "academic_age", "stock", "percentile", "cell_n",
        "is_star_1pct", "is_star_5pct", "age_eligible", "is_foreign_poach",
    ], "STAR_SET must be the current 14 columns (the frozen layout), in the on-disk parquet column order"
    # key types (measured on the parquet file: string->str / int64 / double->float64 / bool)
    assert STAR_SET["author_id"] == "str"       # the key changed: author_id, not star_person_id
    assert STAR_SET["arrival"] == "int64"
    assert STAR_SET["academic_age"] == "int64"  # seniority-threshold input (min_academic_age=2)
    assert STAR_SET["stock"] == "int64"         # cumulative raw citation stock
    assert STAR_SET["percentile"] == "float64"  # parquet double
    assert STAR_SET["cell_n"] == "int64"        # nullable - None for persons not in the pool
    assert STAR_SET["is_star_1pct"] == "bool"   # nullable star flag (thin cell: None)
    assert STAR_SET["is_star_5pct"] == "bool"   # nullable star flag (thin cell: None)
    assert STAR_SET["age_eligible"] == "bool"
    assert STAR_SET["is_foreign_poach"] == "bool"
    # the obsolete columns of the old 9-column version must never come back (metric etc. were dropped)
    for dead_col in ("star_person_id", "metric", "evidence_source",
                     "dist_to_cutoff", "cit_pctile_year", "subfield_id",
                     "cohort_age_bin"):
        assert dead_col not in STAR_SET, f"old column {dead_col} is retired and must not come back"


# ---------------------------------------------------------------------------
# T08: PAIRWISE_DOSE has exactly 11 columns including degree2_bridge_frozen
#      Completes the 11 columns of the U5 dose spec v3 (the earlier 10-column version lacked degree2_bridge_frozen);
#      for degree-2 rows: whether both bridge edges exist before t-1; False -> coupling_share is already recorded as 0.
# ---------------------------------------------------------------------------
def test_t08_pairwise_dose_exactly_11_cols_degree2_bridge_frozen():
    # exactly 11 columns, in the column order of the U5 dose spec v3
    assert list(PAIRWISE_DOSE.keys()) == [
        "incumbent_person_id", "star_person_id", "event_id",
        "coupling_share", "topic_cos", "embed_cos", "coupling_coverage",
        "frozen_at_year", "degree", "degree2_bridge_frozen",
        "boundary_sensitive",
    ], "PAIRWISE_DOSE must be the 11 columns fixed by the U5 specification, in specification order"
    assert PAIRWISE_DOSE["degree2_bridge_frozen"] == "bool"  # the double-bridge-edge freeze flag
    # columns dropped from the old v1 must not come back (dropped: tri_signal_count/agree_flag)
    assert "tri_signal_count" not in PAIRWISE_DOSE
    assert "agree_flag" not in PAIRWISE_DOSE


# ---------------------------------------------------------------------------
# Extra: assert_matches_schema does not raise when the row key set is exactly equal (happy path)
# ---------------------------------------------------------------------------
def test_assert_matches_schema_exact_match_passes():
    row_keys = set(CANONICAL_ID_MAP.keys())
    # exactly equal -> no raise; returning nothing or None are both fine
    assert_matches_schema(row_keys, CANONICAL_ID_MAP, label="CANONICAL_ID_MAP")
