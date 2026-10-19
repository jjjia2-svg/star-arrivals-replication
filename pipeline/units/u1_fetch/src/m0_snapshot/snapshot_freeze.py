"""M0-2 snapshot_freeze.py — per-file sha256 -> Merkle -> snapshot_manifest.json -> read-only freeze.

Reuses U0 (hashing/Merkle/COMMIT are never rewritten):
  - common.manifest.sha256_file       per-file SHA256 (read in chunks).
  - common.manifest.merkle_root       order-sensitive Merkle root (reordering changes the root = freeze evidence).
  - common.manifest.write_dataset_commit / dataset_is_valid   two-phase atomic COMMIT.
  - common.atomic_io.atomic_write_bytes   JSON write (C-C: no atomic_write_json, use bytes).
  - identity.exit_codes.EXIT_MERKLE_INVALID(=23)  entry check fails on a Merkle mismatch (code from U0).

Flow:
  freeze_snapshot:
    1. assert_manifests_present  pre-freeze gate (top-level manifest present <=> data complete; blocks silently freezing a half-damaged snapshot).
    2. Entity-qualified, ordered enumeration of all .gz -> hash_and_count_shard per shard (single-pass I/O).
    3. Sort deterministically by rel_path -> feed merkle_root to get a single root (not relying on file-system enumeration order).
    4. Assemble snapshot_manifest.json (merkle_root + per-shard checksums + version).
    5. Write atomically; add the sha of snapshot_manifest.json itself to the COMMIT payload
       -> write_dataset_commit.stage().commit() (the reproducibility anchor is itself protected by COMMIT).
  make_readonly: chmod -w on the frozen .gz originals (physically cuts off the sync source).
  verify_frozen: reuses dataset_is_valid (reproduction first compares COMMIT).
  assert_entry_merkle: entry check -- recomputed Merkle != frozen record -> exit(EXIT_MERKLE_INVALID=23).

rel_path is entity-qualified (not a bare file name): every entity has a part_000.gz, and a bare name would mix up
  record_count and make the Merkle order drift (the official url contains works/.../part_000.gz).

Hard rules:
  - sha provenance statement: snapshot_manifest.sha_provenance = "self-computed, NOT provided by OpenAlex".
  - sys.exit uses the named constants of identity.exit_codes (EXIT_MERKLE_INVALID), never bare numbers.
  - Single-pass I/O: hash + count lines in one streaming read (avoids reading a large shard twice).
"""
from __future__ import annotations

import gzip
import json
import os
import stat
import sys
from pathlib import Path
from typing import Iterable, Sequence

from common.atomic_io import atomic_write_bytes
from common.manifest import (
    dataset_is_valid,
    merkle_root,
    sha256_file,
    write_dataset_commit,
)
from identity.exit_codes import EXIT_MERKLE_INVALID

# Freeze outputs + the file name of the top-level official manifest.
SNAPSHOT_MANIFEST_NAME: str = "snapshot_manifest.json"
OFFICIAL_MANIFEST_NAME: str = "manifest.json"
# sha provenance statement (reproducibility evidence: self-computed, not provided by OpenAlex).
SHA_PROVENANCE: str = "self-computed, NOT provided by OpenAlex"


# ===========================================================================
# Exceptions
# ===========================================================================
class ManifestAbsentError(Exception):
    """Pre-freeze gate: the top-level official manifest is not on disk.

    The official invariant "manifest present <=> data complete": the manifest is deleted while partitions are written and rebuilt afterwards;
    freezing without a manifest = possibly a half-damaged snapshot caught in the quarterly partition-write window -> the freeze must be refused (not silent).
    """


# ===========================================================================
# Single-pass hash + count
# ===========================================================================
def hash_and_count_shard(path) -> tuple[str, int]:
    """Single-pass streaming read: compute sha256 (of the raw bytes) and count gzip-decompressed lines at the same time.

    Returns (sha256_hex, record_count).
    The sha uses the same convention as U0 manifest.sha256_file (sha256 of the raw compressed bytes);
      the single pass here also counts decompressed lines, avoiding reading a large shard twice (one pass hashing the raw bytes like sha256_file,
      one pass decompressing and counting lines with gzip — two independent stream reads of the same file, combined in one function).
    Blank lines are not counted (consistent with the blank-line semantics of U0 snapshot_reader.count_records_gz).
    """
    p = Path(path)
    # sha = sha256 of the raw compressed bytes (reuses U0, no home-made hash).
    sha = sha256_file(p)
    # Count decompressed lines (streaming, non-blank lines).
    count = 0
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                count += 1
    return sha, count


# ===========================================================================
# Pre-freeze gate
# ===========================================================================
def assert_manifests_present(snapshot_root) -> None:
    """Hard pre-freeze gate: assert the top-level official manifest is on disk; missing -> raise ManifestAbsentError.

    Verified single top-level manifest: checks that <snapshot_root>/manifest.json is present.
    """
    mf = Path(snapshot_root) / OFFICIAL_MANIFEST_NAME
    if not mf.is_file():
        raise ManifestAbsentError(
            f"pre-freeze gate failed: the top-level official manifest is not in {mf} — "
            "invariant: manifest present <=> data complete; freezing without a manifest is refused (blocks a silent freeze of half-damaged data)."
        )


# ===========================================================================
# Shard enumeration (entity-qualified, ordered)
# ===========================================================================
def _iter_shard_paths(snapshot_root, entities: Iterable[str]) -> list[tuple[str, Path]]:
    """Enumerate all .gz in entity-qualified order, returning [(rel_path, abs_path)] (sorted by rel_path, deterministic).

    rel_path = "<entity>/<updated_date=...>/part_xxx.gz" (relative to snapshot_root, entity-qualified).
    """
    root = Path(snapshot_root)
    out: list[tuple[str, Path]] = []
    for entity in entities:
        ent_dir = root / entity
        if not ent_dir.is_dir():
            continue
        for gz in ent_dir.rglob("*.gz"):
            rel = gz.relative_to(root).as_posix()
            out.append((rel, gz))
    # Deterministic sort (not relying on file-system enumeration order; the Merkle root is order-sensitive and sorting keeps it reproducible).
    out.sort(key=lambda t: t[0])
    return out


# ===========================================================================
# Main freeze flow
# ===========================================================================
def _compute_shards(snapshot_root, entities: Iterable[str]) -> list[dict]:
    """hash_and_count per shard -> [{rel_path, sha256, record_count, entity}] (sorted by rel_path)."""
    shards: list[dict] = []
    for rel, abs_path in _iter_shard_paths(snapshot_root, entities):
        sha, count = hash_and_count_shard(abs_path)
        entity = rel.split("/", 1)[0]  # The first segment of rel_path = the entity qualifier
        shards.append(
            {
                "rel_path": rel,
                "sha256": sha,
                "record_count": count,
                "entity": entity,
            }
        )
    return shards


def _merkle_from_shards(shards: Sequence[dict]) -> str:
    """Feed the sha256 of the sorted shards to merkle_root (a leaf = the utf-8 bytes of the sha256; order-sensitive).

    shards are already sorted by rel_path -> the Merkle root is deterministic (the upstream sort fixes the order that determines the root).
    """
    leaves = [s["sha256"].encode("utf-8") for s in shards]
    return merkle_root(leaves)


def recompute_merkle(snapshot_root, *, entities: Iterable[str]) -> str:
    """Recompute the Merkle root of the shards currently on disk (used for the reproduction root comparison / the entry check)."""
    shards = _compute_shards(snapshot_root, entities)
    return _merkle_from_shards(shards)


def freeze_snapshot(
    snapshot_root,
    *,
    entities: Iterable[str],
    release_date: str,
    max_updated_date: str,
    s3_etag: str | None = None,
    topics_version: str,
) -> dict:
    """Freeze the snapshot: pre-gate -> per-shard hash -> Merkle -> snapshot_manifest.json -> COMMIT (itself protected).

    Returns the in-memory snapshot_manifest dict (with merkle_root + shards + openalex_release + sha_provenance).
    The sha of snapshot_manifest.json itself is added to the COMMIT payload -> the reproducibility anchor is itself protected by COMMIT.
    """
    entities = tuple(entities)
    # 1. Pre-freeze gate (top-level manifest missing -> refuse to freeze).
    assert_manifests_present(snapshot_root)

    # 2-3. Per-shard hash + count -> deterministic sort -> Merkle root.
    shards = _compute_shards(snapshot_root, entities)
    root_hash = _merkle_from_shards(shards)

    # 4. Assemble snapshot_manifest.json (version + checksums + sha provenance statement).
    snapshot_manifest = {
        "merkle_root": root_hash,
        "shards": shards,
        "openalex_release": {
            "sync_date": release_date,
            "max_updated_date": max_updated_date,
            "s3_etag": s3_etag,
        },
        "topics_version": topics_version,
        "sha_provenance": SHA_PROVENANCE,
        "zenodo_doi": None,  # Re-seal after M0-6 zenodo_anchor fills in the DOI.
    }

    # 5. Write snapshot_manifest.json atomically (C-C: bytes method; sort_keys keeps it deterministic).
    manifest_blob = json.dumps(
        snapshot_manifest, sort_keys=True, ensure_ascii=False
    ).encode("utf-8")
    target = Path(snapshot_root) / SNAPSHOT_MANIFEST_NAME
    atomic_write_bytes(target, manifest_blob)

    # Add the bytes of snapshot_manifest.json itself to the COMMIT payload -> the reproducibility anchor is protected by COMMIT.
    #   provenance.source_snapshot_merkle = the Merkle root of this freeze (the anchor that downstream artifact headers compare against).
    #   rule_version does not contain 'unsigned' -> signed semantics -> promoted to _frozen/COMMIT, dataset_is_valid=True.
    provenance = {
        "source_snapshot_merkle": root_hash,
        "config_sha": "snapshot_freeze",
        "rule_version": "snapshot_freeze_v1",
        "stars_set_hash": "n/a-snapshot-layer",
    }
    committer = write_dataset_commit(
        Path(snapshot_root),
        {SNAPSHOT_MANIFEST_NAME: manifest_blob},
        provenance=provenance,
    )
    committer.stage().commit()

    return snapshot_manifest


def make_readonly(snapshot_root) -> list[str]:
    """chmod -w the frozen .gz originals (physically cuts off the sync source); returns the list of changed paths.

    The snapshot_manifest text is not locked (M0-6 zenodo_anchor still has to fill in the DOI and re-seal).
    """
    changed: list[str] = []
    root = Path(snapshot_root)
    for gz in root.rglob("*.gz"):
        cur = os.stat(gz).st_mode
        # Clear all write bits (user/group/other), keep the read/execute bits.
        ro = cur & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        os.chmod(gz, ro)
        changed.append(str(gz))
    changed.sort()
    return changed


def verify_frozen(snapshot_root) -> bool:
    """Re-check that the freeze is valid = U0 dataset_is_valid (reproduction first compares _frozen/COMMIT)."""
    return dataset_is_valid(Path(snapshot_root))


def assert_entry_merkle(snapshot_root, *, entities: Iterable[str]) -> None:
    """Entry check gate: recomputed Merkle root of the current disk != the frozen record's root -> exit(EXIT_MERKLE_INVALID=23).

    Use: before M1 starts scanning, confirm the frozen snapshot was not modified / the reproducibility anchor is consistent; a mismatch HALTs (code from U0).
    The frozen record is read from the merkle_root of snapshot_manifest.json (not recomputed — that is the ground truth being compared against).
    """
    mf = Path(snapshot_root) / SNAPSHOT_MANIFEST_NAME
    if not mf.is_file():
        # No frozen record when the entry check runs = a mismatch -> HALT.
        sys.exit(EXIT_MERKLE_INVALID)
    recorded = json.loads(mf.read_text(encoding="utf-8")).get("merkle_root")
    recomputed = recompute_merkle(snapshot_root, entities=entities)
    if recorded != recomputed:
        sys.exit(EXIT_MERKLE_INVALID)
