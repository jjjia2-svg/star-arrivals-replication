"""Tests for merged_ids.py: fixtures check parsing, replay and cycle detection; never a real S3 download.

Behaviour covered:
  - parse_merged_ids_csv_bytes: parse the decompressed text of a legacy merged_ids/{entity}/{date}.csv.gz
    (columns merge_date,id,merge_into_id) -> rows {raw_id:id, canonical_id:merge_into_id}.
  - build_canonical_rows: replay with U0 replay_merged_ids to find roots -> CANONICAL_ID_MAP rows with 4 keys
    (raw_id, canonical_id, id_type, is_deleted); id_type comes from ENTITY_TO_IDTYPE[entity].
  - A long merge chain folds to its final root (A->B->C => canonical of A and B is C).
  - DELETION_SENTINELS_WORKS contains W4285719527 -> a root that hits the sentinel -> is_deleted=True.
  - A merge cycle (A->B->A) -> the ValueError from U0 is passed through (never an infinite loop).
  - Each of the three entity types (works/authors/institutions) gets the right id_type; an unknown entity raises.
  - Before writing, every row passes assert_matches_schema(CANONICAL_ID_MAP) (exactly 4 keys).

Discipline: all fixtures are small samples that test logic; DELETION_SENTINELS_AUTHORS is an empty set
placeholder in U0 and is never filled in here.
"""
from __future__ import annotations

import pytest

from m0_snapshot import merged_ids as mi
from common.schema import CANONICAL_ID_MAP, assert_matches_schema
from identity.constants import ENTITY_TO_IDTYPE


# ---------------------------------------------------------------------------
# parse legacy CSV (decompressed text; columns merge_date,id,merge_into_id)
# ---------------------------------------------------------------------------
_WORKS_CSV = (
    "merge_date,id,merge_into_id\n"
    "2023-01-01,W111,W222\n"        # W111 is merged into W222
    "2023-02-01,W222,W333\n"        # chain: W111->W222->W333
    "2023-03-01,W444,W4285719527\n"  # W444 is merged into the deletion sentinel
)


def test_parse_merged_ids_csv_yields_raw_canonical_rows():
    rows = mi.parse_merged_ids_csv_bytes(_WORKS_CSV.encode("utf-8"))
    rows = list(rows)
    assert {"raw_id": "W111", "canonical_id": "W222"} in rows
    assert {"raw_id": "W222", "canonical_id": "W333"} in rows
    assert len(rows) == 3


def test_parse_merged_ids_csv_skips_blank_and_header_only():
    rows = list(mi.parse_merged_ids_csv_bytes(b"merge_date,id,merge_into_id\n"))
    assert rows == []


def test_parse_merged_ids_csv_missing_column_raises():
    bad = b"merge_date,id\n2023-01-01,W111\n"  # merge_into_id column missing
    with pytest.raises((KeyError, ValueError)):
        list(mi.parse_merged_ids_csv_bytes(bad))


# ---------------------------------------------------------------------------
# build_canonical_rows: replay to find roots -> rows with 4 keys
# ---------------------------------------------------------------------------
def test_build_canonical_rows_follows_long_chain_to_terminal_root():
    rows = mi.parse_merged_ids_csv_bytes(_WORKS_CSV.encode("utf-8"))
    out = mi.build_canonical_rows(rows, entity="works")
    by_raw = {r["raw_id"]: r for r in out}
    # the chain folds to the final root W333
    assert by_raw["W111"]["canonical_id"] == "W333"
    assert by_raw["W222"]["canonical_id"] == "W333"


def test_build_canonical_rows_id_type_from_entity():
    rows = mi.parse_merged_ids_csv_bytes(_WORKS_CSV.encode("utf-8"))
    out = mi.build_canonical_rows(rows, entity="works")
    assert all(r["id_type"] == ENTITY_TO_IDTYPE["works"] == "work" for r in out)


def test_build_canonical_rows_deletion_sentinel_sets_is_deleted():
    rows = mi.parse_merged_ids_csv_bytes(_WORKS_CSV.encode("utf-8"))
    out = mi.build_canonical_rows(rows, entity="works")
    by_raw = {r["raw_id"]: r for r in out}
    # the root of W444 = W4285719527, which is in DELETION_SENTINELS_WORKS -> is_deleted=True
    assert by_raw["W444"]["canonical_id"] == "W4285719527"
    assert by_raw["W444"]["is_deleted"] is True
    # a non-sentinel root -> is_deleted=False
    assert by_raw["W111"]["is_deleted"] is False


def test_build_canonical_rows_each_row_matches_canonical_id_map_schema():
    rows = mi.parse_merged_ids_csv_bytes(_WORKS_CSV.encode("utf-8"))
    out = mi.build_canonical_rows(rows, entity="works")
    assert len(out) >= 1
    for r in out:
        # exactly 4 keys; one extra or one missing both fail
        assert_matches_schema(r.keys(), CANONICAL_ID_MAP, label="CANONICAL_ID_MAP")


# ---------------------------------------------------------------------------
# cycle detection (passes through the raise of U0 replay_merged_ids)
# ---------------------------------------------------------------------------
def test_build_canonical_rows_cycle_raises():
    cyclic = (
        "merge_date,id,merge_into_id\n"
        "2023-01-01,WA,WB\n"
        "2023-02-01,WB,WA\n"  # cycle WA->WB->WA
    )
    rows = mi.parse_merged_ids_csv_bytes(cyclic.encode("utf-8"))
    with pytest.raises(ValueError):
        mi.build_canonical_rows(rows, entity="works")


# ---------------------------------------------------------------------------
# three entity types + an unknown entity
# ---------------------------------------------------------------------------
def test_build_canonical_rows_authors_id_type():
    rows = mi.parse_merged_ids_csv_bytes(
        b"merge_date,id,merge_into_id\n2023-01-01,A111,A222\n"
    )
    out = mi.build_canonical_rows(rows, entity="authors")
    assert all(r["id_type"] == "author" for r in out)
    # DELETION_SENTINELS_AUTHORS is an empty set -> every root gives is_deleted=False (placeholder, not filled in here)
    assert all(r["is_deleted"] is False for r in out)


def test_build_canonical_rows_institutions_id_type():
    rows = mi.parse_merged_ids_csv_bytes(
        b"merge_date,id,merge_into_id\n2023-01-01,I111,I222\n"
    )
    out = mi.build_canonical_rows(rows, entity="institutions")
    assert all(r["id_type"] == "institution" for r in out)


def test_build_canonical_rows_unknown_entity_raises():
    rows = mi.parse_merged_ids_csv_bytes(
        b"merge_date,id,merge_into_id\n2023-01-01,X1,X2\n"
    )
    with pytest.raises((KeyError, ValueError)):
        mi.build_canonical_rows(rows, entity="planets")


# ---------------------------------------------------------------------------
# end to end: CSV bytes -> canonical_id_map rows (one helper for all three types)
# ---------------------------------------------------------------------------
def test_canonical_map_from_csv_bytes_end_to_end():
    out = mi.canonical_map_from_csv_bytes(_WORKS_CSV.encode("utf-8"), entity="works")
    by_raw = {r["raw_id"]: r for r in out}
    assert by_raw["W111"]["canonical_id"] == "W333"
    assert by_raw["W444"]["is_deleted"] is True
    assert set(out[0].keys()) == set(CANONICAL_ID_MAP.keys())


def test_sentinels_for_entity_uses_u0_values():
    """The works sentinels include W4285719527; authors are an empty-set placeholder (as in U0, not filled in here)."""
    works_sent = mi.sentinels_for_entity("works")
    assert "W4285719527" in works_sent
    authors_sent = mi.sentinels_for_entity("authors")
    assert authors_sent == set()
