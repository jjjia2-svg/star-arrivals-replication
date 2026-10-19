"""TDD red test for M1-T5 canonical_id.py: fixtures test normalisation + 4-key table rows + three
kinds of cmap.

Covers (closure item 4, U0 interface):
  - build_canonical_map(rows, *, id_type): thin wrapper over U0 replay_merged_ids ->
    {raw_id:(canonical,is_deleted)}; resolves the root iteratively (a long chain folds to the final
    root); a cycle re-raises (never loops forever); an invalid id_type raises.
  - canonicalize(raw_id, cmap): folds a raw id to canonical through cmap
    (author_id canonical space is pinned: several raw ids of one person all fold to one root);
    not in cmap -> unchanged (already a root).
  - is_deleted(raw_id, cmap): whether the final root is a deletion sentinel.
  - to_canonical_rows(resolved, *, id_type): emits CANONICAL_ID_MAP 4-key rows (including
    is_deleted), each row passing the schema guard.
  - write_canonical_id_map(...): writes the 4-key rows through an injected sink (the parquet
    sink comes from HashBucketWriter; it is injected here to avoid hard coupling to a module
    that is not yet built).
  - The three entity kinds (works/authors/institutions) each get the right id_type -> the
    same canonical space.

Rule: small fixtures test the logic and never download from S3; DELETION_SENTINELS_AUTHORS
is an empty U0 placeholder and is never filled in here.
"""
from __future__ import annotations

import pytest

from m1_ingest import canonical_id as cid
from common.schema import CANONICAL_ID_MAP, assert_matches_schema
from identity.constants import ENTITY_TO_IDTYPE


# ---------------------------------------------------------------------------
# build_canonical_map: thin replay wrapper (long chain folds to the final root + a cycle raises)
# ---------------------------------------------------------------------------
_WORKS_ROWS = [
    {"raw_id": "W111", "canonical_id": "W222"},   # W111→W222
    {"raw_id": "W222", "canonical_id": "W333"},   # chain W111->W222->W333
    {"raw_id": "W444", "canonical_id": "W4285719527"},  # merged into the deletion sentinel
]


def test_build_canonical_map_follows_chain_to_root():
    cmap = cid.build_canonical_map(_WORKS_ROWS, id_type="work")
    # the long chain folds to the final root W333
    assert cmap["W111"][0] == "W333"
    assert cmap["W222"][0] == "W333"


def test_build_canonical_map_is_deleted_on_sentinel_root():
    cmap = cid.build_canonical_map(_WORKS_ROWS, id_type="work")
    # W444 root = W4285719527 ∈ DELETION_SENTINELS_WORKS -> is_deleted=True
    assert cmap["W444"] == ("W4285719527", True)
    # root is not a sentinel -> is_deleted=False
    assert cmap["W111"][1] is False


def test_build_canonical_map_cycle_raises():
    cyclic = [
        {"raw_id": "WA", "canonical_id": "WB"},
        {"raw_id": "WB", "canonical_id": "WA"},  # cycle WA->WB->WA
    ]
    with pytest.raises(ValueError):
        cid.build_canonical_map(cyclic, id_type="work")


def test_build_canonical_map_rejects_unknown_id_type():
    """id_type must be one of the ENTITY_TO_IDTYPE values (work/author/institution/...); otherwise
    raise."""
    with pytest.raises((KeyError, ValueError)):
        cid.build_canonical_map(_WORKS_ROWS, id_type="planet")


def test_build_canonical_map_authors_deletion_sentinel_is_empty_placeholder():
    """The authors deletion sentinels are an empty U0 placeholder -> any root gives is_deleted=False
    (no value is filled in)."""
    rows = [{"raw_id": "A111", "canonical_id": "A222"}]
    cmap = cid.build_canonical_map(rows, id_type="author")
    assert cmap["A111"] == ("A222", False)


# ---------------------------------------------------------------------------
# canonicalize: fold a raw id to canonical (author_id space pinned)
# ---------------------------------------------------------------------------
def test_canonicalize_maps_raw_to_root():
    cmap = cid.build_canonical_map(_WORKS_ROWS, id_type="work")
    # same space: W111 and W222 both fold to W333 (no split)
    assert cid.canonicalize("W111", cmap) == "W333"
    assert cid.canonicalize("W222", cmap) == "W333"


def test_canonicalize_passthrough_when_not_in_map():
    """raw id not in cmap (never merged) -> returned unchanged (it is itself the canonical root)."""
    cmap = cid.build_canonical_map(_WORKS_ROWS, id_type="work")
    assert cid.canonicalize("W999", cmap) == "W999"


def test_canonicalize_none_passthrough():
    """None/empty -> unchanged (the caller checks for emptiness; no crash)."""
    cmap = cid.build_canonical_map(_WORKS_ROWS, id_type="work")
    assert cid.canonicalize(None, cmap) is None


def test_is_deleted_reads_sentinel_flag():
    cmap = cid.build_canonical_map(_WORKS_ROWS, id_type="work")
    assert cid.is_deleted("W444", cmap) is True
    assert cid.is_deleted("W111", cmap) is False
    # not in cmap -> not merged / deletion unknown -> False (no deletion is invented)
    assert cid.is_deleted("W999", cmap) is False


# ---------------------------------------------------------------------------
# to_canonical_rows: emit CANONICAL_ID_MAP 4-key rows (including is_deleted), schema guard
# ---------------------------------------------------------------------------
def test_to_canonical_rows_emits_four_key_schema():
    cmap = cid.build_canonical_map(_WORKS_ROWS, id_type="work")
    rows = cid.to_canonical_rows(cmap, id_type="work")
    assert len(rows) == 3
    for r in rows:
        assert_matches_schema(r.keys(), CANONICAL_ID_MAP, label="CANONICAL_ID_MAP")
    by_raw = {r["raw_id"]: r for r in rows}
    assert by_raw["W111"]["canonical_id"] == "W333"
    assert by_raw["W111"]["id_type"] == "work"
    assert by_raw["W444"]["is_deleted"] is True


def test_to_canonical_rows_id_type_must_match_build():
    """to_canonical_rows needs a valid id_type value (same space as build), otherwise raise."""
    cmap = cid.build_canonical_map(_WORKS_ROWS, id_type="work")
    with pytest.raises((KeyError, ValueError)):
        cid.to_canonical_rows(cmap, id_type="planet")


# ---------------------------------------------------------------------------
# three entity kinds -> the same canonical space
# ---------------------------------------------------------------------------
def test_three_entity_classes_each_correct_id_type():
    works = cid.build_canonical_map(
        [{"raw_id": "W1", "canonical_id": "W2"}], id_type=ENTITY_TO_IDTYPE["works"]
    )
    authors = cid.build_canonical_map(
        [{"raw_id": "A1", "canonical_id": "A2"}], id_type=ENTITY_TO_IDTYPE["authors"]
    )
    insts = cid.build_canonical_map(
        [{"raw_id": "I1", "canonical_id": "I2"}], id_type=ENTITY_TO_IDTYPE["institutions"]
    )
    assert cid.to_canonical_rows(works, id_type="work")[0]["id_type"] == "work"
    assert cid.to_canonical_rows(authors, id_type="author")[0]["id_type"] == "author"
    assert cid.to_canonical_rows(insts, id_type="institution")[0]["id_type"] == "institution"


# ---------------------------------------------------------------------------
# write_canonical_id_map: write 4-key rows through an injected sink (the parquet sink comes from
# HashBucketWriter)
# ---------------------------------------------------------------------------
def test_write_canonical_id_map_passes_validated_rows_to_sink():
    """Inject a fake sink that captures the rows: every written row has exactly 4 keys + canonical
    folded correctly; no hard coupling to the not-yet-built HashBucketWriter."""
    cmap = cid.build_canonical_map(_WORKS_ROWS, id_type="work")
    captured: list[dict] = []

    def fake_sink(rows):
        captured.extend(rows)

    n = cid.write_canonical_id_map(cmap, id_type="work", sink=fake_sink)
    assert n == 3
    assert len(captured) == 3
    for r in captured:
        assert set(r.keys()) == set(CANONICAL_ID_MAP.keys())
    by_raw = {r["raw_id"]: r for r in captured}
    assert by_raw["W222"]["canonical_id"] == "W333"
