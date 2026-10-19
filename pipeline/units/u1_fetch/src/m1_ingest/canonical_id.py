"""M1-T5 canonical_id - M1-side consumer of the canonical map (raw -> canonical normalisation + 4-key table output).

Why it is needed (merge-redirect semantics):
  M0's merged_ids.py has replayed the legacy merged_ids/*.csv.gz into validated 4-key rows. On the M1 side the same
  replay result is turned into an in-memory lookup table so that, while the tables are streamed out, every raw id is pinned to its
  canonical root and all raw ids of one person / one work fold to a single canonical id (the author_id canonical space is fixed;
  otherwise one person splits into several persons and degrees/spillovers are all wrong). The three entity types
  (works/authors/institutions) share the same normalisation logic -> the same canonical space (run_m1's cross-table foreign-key
  check across the four tables relies on it).

What this module does:
  1. build_canonical_map(rows, *, id_type): thin wrapper around U0 common.manifest.replay_merged_ids, which resolves roots
     -> {raw_id: (terminal_canonical, is_deleted)}; long chains fold to the terminal root, a cycle propagates ValueError (never loops forever).
       - id_type must be one of the values of ENTITY_TO_IDTYPE (work/author/institution/...), otherwise raise (a typo must not select the wrong space).
       - the deletion-sentinel set is chosen by id_type (works include W4285719527; authors/institutions get an empty placeholder set, as in U0, never filled in here).
  2. canonicalize(raw_id, cmap): use cmap to normalise a raw id to its canonical root; if it is not in cmap (never merged)
     -> returned unchanged (it already is canonical); None/empty -> returned unchanged (the caller checks for empty, no crash).
  3. is_deleted(raw_id, cmap): whether the terminal root is a deletion sentinel; not in cmap -> False (no deletion is invented).
  4. to_canonical_rows(cmap, *, id_type): expand the replay result into CANONICAL_ID_MAP 4-key rows (including is_deleted);
     each row goes through assert_matches_schema before writing (exactly 4 keys, extra or missing keys fail).
  5. write_canonical_id_map(cmap, *, id_type, sink): hand the 4-key rows to an injected sink for writing
     (the parquet sink is provided by M1-T3 HashBucketWriter; dependency injection avoids hard coupling to a writer
      that may not exist yet and lets fixture tests capture the rows; run_m1 wires in a HashBucketWriter.add closure).

Reuses U0, no rewrite:
  - replay_merged_ids(rows, *, deletion_sentinels) -> {raw_id:(terminal_canonical,is_deleted)} (a cycle raises ValueError, propagated).
  - DELETION_SENTINELS_WORKS / DELETION_SENTINELS_AUTHORS (empty-set placeholder).
  - CANONICAL_ID_MAP (exactly 4 keys) + assert_matches_schema. ENTITY_TO_IDTYPE (single source of truth for id_type).

Neutral on identification choices: merge normalisation is a cross-cutting mechanism (which id is canonical) and touches no identification rule.
U0 has no deletion-sentinel constant for institutions -> empty set (no institution deletions are known; no sentinel is made up).
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Optional

# U0 foundation (actual interface surface).
from common.manifest import (
    DELETION_SENTINELS_AUTHORS,
    DELETION_SENTINELS_WORKS,
    replay_merged_ids,
)
from common.schema import CANONICAL_ID_MAP, assert_matches_schema
from identity.constants import ENTITY_TO_IDTYPE

# id_type -> deletion-sentinel set (reuses the U0 constants; no known sentinel for institution -> empty set, never invented).
# Key = id_type value (work/author/institution), not the entity name (works/...) - consistent with the build() argument.
_SENTINELS_BY_ID_TYPE: dict[str, set[str]] = {
    "work": DELETION_SENTINELS_WORKS,
    "author": DELETION_SENTINELS_AUTHORS,
    "institution": set(),
}

# Legal id_type values (the value domain of ENTITY_TO_IDTYPE) - fixed, so a typo cannot select the wrong canonical space.
_VALID_ID_TYPES: frozenset[str] = frozenset(ENTITY_TO_IDTYPE.values())

# In-memory form of the canonical map: raw_id -> (canonical_id, is_deleted).
CanonicalMap = dict[str, tuple[str, bool]]


def _assert_id_type(id_type: str) -> None:
    """id_type must be one of the values of ENTITY_TO_IDTYPE; otherwise raise (never silently use the wrong space)."""
    if id_type not in _VALID_ID_TYPES:
        raise ValueError(
            f"unknown id_type {id_type!r}; only the ENTITY_TO_IDTYPE values {sorted(_VALID_ID_TYPES)} are allowed "
            f"(the canonical space is pinned, so a typo cannot mix entities)"
        )


def _sentinels_for_id_type(id_type: str) -> set[str]:
    """Get the deletion-sentinel set for this id_type (work includes W4285719527; author/institution get an empty placeholder set).

    An unregistered id_type is rejected by _assert_id_type before the empty-set fallback; types without a sentinel, such as source/publisher,
    get the empty set (merge normalisation still holds for them, there is just no known deletion target).
    """
    return _SENTINELS_BY_ID_TYPE.get(id_type, set())


# ===========================================================================
# build_canonical_map - thin wrapper around replay (long chains fold to the terminal root, cycles are re-raised)
# ===========================================================================
def build_canonical_map(
    rows: Iterable[Mapping[str, str]],
    *,
    id_type: str,
) -> CanonicalMap:
    """Replay the raw -> canonical merge chain -> {raw_id: (terminal_canonical, is_deleted)}.

    Args:
        rows: each = {"raw_id": str, "canonical_id": str} (a subset of CANONICAL_ID_MAP;
              usually from M0 merged_ids.parse_merged_ids_csv_bytes).
        id_type: a value of ENTITY_TO_IDTYPE (work/author/institution/...); illegal -> raise.
    Returns:
        {raw_id: (terminal_canonical_id, is_deleted)} - roots are resolved iteratively, a long chain A->B->C folds to C.
    Raises:
        ValueError - illegal id_type; or the replay detects a merge cycle (propagated from the U0 replay, never loops forever).

    Thin wrapper: root resolution and cycle detection are left to U0 replay_merged_ids; this function only fixes id_type and the sentinel set.
    """
    _assert_id_type(id_type)
    sentinels = _sentinels_for_id_type(id_type)
    # U0 replay: {raw_id: (terminal_canonical, is_deleted)}; a cycle -> ValueError propagates.
    return replay_merged_ids(rows, deletion_sentinels=sentinels)


# ===========================================================================
# canonicalize / is_deleted - normalise with cmap (author_id space fixed)
# ===========================================================================
def canonicalize(raw_id: Optional[str], cmap: Mapping[str, tuple[str, bool]]) -> Optional[str]:
    """Normalise a raw id to its canonical root.

    - raw_id in cmap -> return its terminal canonical (all raw ids of one person / one work fold to one root, no split).
    - raw_id not in cmap -> returned unchanged (never merged = it is itself a canonical root).
    - None/"" -> returned unchanged (the caller checks for empty; the pure function does not crash).

    This is the only normalising verb that puts author_id / institution_id / work_id into the canonical space;
    all four tables pass through it before writing -> cross-table foreign keys land in the same space.
    """
    if not raw_id:
        return raw_id
    hit = cmap.get(raw_id)
    if hit is None:
        return raw_id
    return hit[0]


def is_deleted(raw_id: Optional[str], cmap: Mapping[str, tuple[str, bool]]) -> bool:
    """Whether the terminal root of this raw id is a deletion sentinel.

    - in cmap -> return the is_deleted recorded by the replay.
    - not in cmap / None -> False (never merged = no deletion is invented).
    """
    if not raw_id:
        return False
    hit = cmap.get(raw_id)
    if hit is None:
        return False
    return bool(hit[1])


# ===========================================================================
# to_canonical_rows / write_canonical_id_map - emit 4-key rows + write (injected sink)
# ===========================================================================
def to_canonical_rows(
    cmap: Mapping[str, tuple[str, bool]],
    *,
    id_type: str,
) -> list[dict[str, Any]]:
    """Expand the replay result into CANONICAL_ID_MAP 4-key rows (raw_id, canonical_id, id_type, is_deleted).

    Each row goes through assert_matches_schema(CANONICAL_ID_MAP) before writing (exactly 4 keys, extra or missing keys fail).
    Illegal id_type -> raise (same space constraint as build_canonical_map).
    Deterministic: output sorted by raw_id (reproducible byte for byte across two runs).
    """
    _assert_id_type(id_type)
    out: list[dict[str, Any]] = []
    for raw_id in sorted(cmap):
        terminal_canonical, deleted = cmap[raw_id]
        row = {
            "raw_id": raw_id,
            "canonical_id": terminal_canonical,
            "id_type": id_type,
            "is_deleted": bool(deleted),
        }
        assert_matches_schema(row.keys(), CANONICAL_ID_MAP, label="CANONICAL_ID_MAP")
        out.append(row)
    return out


def write_canonical_id_map(
    cmap: Mapping[str, tuple[str, bool]],
    *,
    id_type: str,
    sink: Callable[[list[dict[str, Any]]], None],
) -> int:
    """Hand the canonical_id_map 4-key rows to the injected sink for writing; returns the number of rows written.

    Args:
        sink: the write verb (rows: list[dict]) -> None.
              run_m1 wires in the M1-T3 HashBucketWriter (PK=raw_id, deterministic parquet);
              dependency injection avoids hard coupling to a HashBucketWriter that may not exist yet and lets fixture tests capture the rows
              (atomic_io has no atomic_write_parquet, so parquet always goes through HashBucketWriter).

    The rows have already passed the schema check in to_canonical_rows (exactly 4 keys).
    """
    rows = to_canonical_rows(cmap, id_type=id_type)
    sink(rows)
    return len(rows)
