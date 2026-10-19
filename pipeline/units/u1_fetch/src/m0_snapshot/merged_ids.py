"""M0-4 merged_ids — replay the legacy merged_ids -> canonical_id_map (works/authors/institutions).

Why it is needed:
  The OpenAlex main .gz data does not contain deleted/merged entities; merge records are kept separately in the legacy
  merged_ids/<entity>/<date>.csv.gz (columns merge_date,id,merge_into_id). After every sync, ids must be
  redirected to merge_into_id, otherwise citation edges / author attribution point to dead ids (the returned id is the canonical one).

What this module does:
  1. parse_merged_ids_csv_bytes: parse the decompressed CSV text -> rows {raw_id:id, canonical_id:merge_into_id}.
  2. build_canonical_rows: replay with U0 common.manifest.replay_merged_ids to find the root (iterative, a cycle raises) ->
     4-key CANONICAL_ID_MAP rows (raw_id, canonical_id, id_type, is_deleted).
       - id_type comes from identity.constants.ENTITY_TO_IDTYPE[entity] (works->work etc.).
       - is_deleted = the terminal root is in that entity's deletion-sentinel set.
  3. canonical_map_from_csv_bytes: end-to-end helper (CSV bytes -> list of canonical rows).

Reuses U0, no rewriting:
  - replay_merged_ids(rows, *, deletion_sentinels) -> {raw_id:(terminal_canonical,is_deleted)} (a cycle -> ValueError, passed through).
  - DELETION_SENTINELS_WORKS = {"W4285719527"}; DELETION_SENTINELS_AUTHORS = set() (an empty placeholder, never filled in here).
  - assert_matches_schema + CANONICAL_ID_MAP (exactly 4 keys enforced before writing).
  - ENTITY_TO_IDTYPE (the single source of truth for id_type).

Neutral about identification choices: merge replay is a cross-cutting mechanism (which id is canonical).
institutions have no U0 deletion-sentinel constant -> empty set (no known institution deletion case; no sentinel is invented).
Writing canonical_id_map.parquet is the job of M1 canonical_id.py / HashBucketWriter (this module only produces validated rows;
this avoids coupling to the not-yet-built hash_bucket_writer).
"""
from __future__ import annotations

import csv
import io
from typing import Any, Iterable, Iterator, Mapping

# U0 foundation (real surface).
from common.manifest import (
    DELETION_SENTINELS_AUTHORS,
    DELETION_SENTINELS_WORKS,
    replay_merged_ids,
)
from common.schema import CANONICAL_ID_MAP, assert_matches_schema
from identity.constants import ENTITY_TO_IDTYPE

# Columns of the legacy merged_ids CSV (verbatim).
MERGED_IDS_CSV_COLUMNS: tuple[str, ...] = ("merge_date", "id", "merge_into_id")

# entity -> deletion-sentinel set (reuses the U0 constants; institutions have no known sentinel -> empty set, none invented).
_SENTINELS_BY_ENTITY: dict[str, set[str]] = {
    "works": DELETION_SENTINELS_WORKS,
    "authors": DELETION_SENTINELS_AUTHORS,
    "institutions": set(),
}


def sentinels_for_entity(entity: str) -> set[str]:
    """Get the deletion-sentinel set for the entity (works includes W4285719527; authors/institutions are empty placeholders).

    Unknown entity -> KeyError (never silently return an empty set, so a typo cannot pick the wrong entity).
    """
    if entity not in _SENTINELS_BY_ENTITY:
        raise KeyError(
            f"unknown entity {entity!r}; only {sorted(_SENTINELS_BY_ENTITY)} are supported "
            f"(merged_ids is replayed only for works/authors/institutions)"
        )
    return _SENTINELS_BY_ENTITY[entity]


# ===========================================================================
# Parse the legacy merged_ids CSV (decompressed text)
# ===========================================================================
def parse_merged_ids_csv_bytes(blob: bytes | str) -> Iterator[dict[str, str]]:
    """Parse the decompressed merged_ids CSV -> rows {raw_id:id, canonical_id:merge_into_id}.

    Argument = decompressed CSV bytes/text (columns merge_date,id,merge_into_id). Yields row by row, streaming.
      - merge_date is used only for the sidecar high-water mark (not written by this function; run_m0 writes it); per row only id / merge_into_id are taken.
      - Missing column (no merge_into_id header) -> KeyError fails loudly (no silent .get None).
      - Empty file / header only -> yields no rows.

    This function does not read the disk (.gz decompression + streaming is done by run_m0 with snapshot_reader/gzip); only the text parsing logic is here.
    """
    if isinstance(blob, bytes):
        text = blob.decode("utf-8")
    else:
        text = blob
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    missing = [c for c in MERGED_IDS_CSV_COLUMNS if c not in fieldnames]
    if missing:
        raise KeyError(
            f"merged_ids CSV lacks columns {missing}; expected {MERGED_IDS_CSV_COLUMNS}, got header {fieldnames}"
        )
    for rec in reader:
        raw = rec["id"]
        canon = rec["merge_into_id"]
        if raw is None or canon is None or raw == "" or canon == "":
            # Half row (id/merge_into_id empty) — skipped, not treated as a merge pointer.
            continue
        yield {"raw_id": raw, "canonical_id": canon}


# ===========================================================================
# Replay to find the root -> 4-key canonical rows
# ===========================================================================
def build_canonical_rows(
    rows: Iterable[Mapping[str, str]],
    *,
    entity: str,
) -> list[dict[str, Any]]:
    """Replay with U0 replay_merged_ids -> list of CANONICAL_ID_MAP 4-key rows.

    Each row = {raw_id, canonical_id (terminal root), id_type (=ENTITY_TO_IDTYPE[entity]), is_deleted (root in sentinel set)}.
      - Long merge chain A->B->C: the canonical_id of both A and B folds to the terminal root C.
      - Merge cycle -> replay_merged_ids raises ValueError, passed through here (never loops forever).
      - Unknown entity -> KeyError (neither id_type nor the sentinels can be found).
    Before writing, every row passes assert_matches_schema(CANONICAL_ID_MAP) (exactly 4 keys; extra or missing keys fail).
    """
    if entity not in ENTITY_TO_IDTYPE:
        raise KeyError(
            f"unknown entity {entity!r}; ENTITY_TO_IDTYPE only has {sorted(ENTITY_TO_IDTYPE)}"
        )
    id_type = ENTITY_TO_IDTYPE[entity]
    sentinels = sentinels_for_entity(entity)
    # U0 replay: {raw_id: (terminal_canonical, is_deleted)}; a cycle -> ValueError passed through.
    resolved = replay_merged_ids(rows, deletion_sentinels=sentinels)
    out: list[dict[str, Any]] = []
    for raw_id, (terminal_canonical, is_deleted) in resolved.items():
        row = {
            "raw_id": raw_id,
            "canonical_id": terminal_canonical,
            "id_type": id_type,
            "is_deleted": bool(is_deleted),
        }
        assert_matches_schema(row.keys(), CANONICAL_ID_MAP, label="CANONICAL_ID_MAP")
        out.append(row)
    return out


def canonical_map_from_csv_bytes(blob: bytes | str, *, entity: str) -> list[dict[str, Any]]:
    """End-to-end helper: decompressed CSV bytes -> canonical_id_map 4-key rows (parse + replay to the root).

    run_m0 calls it per entity: it streams the legacy merged_ids/<entity>/*.csv.gz, feeds the decompressed bytes here,
    then writes the returned rows to canonical_id_map.parquet through M1 canonical_id.py / HashBucketWriter.
    """
    rows = list(parse_merged_ids_csv_bytes(blob))
    return build_canonical_rows(rows, entity=entity)
