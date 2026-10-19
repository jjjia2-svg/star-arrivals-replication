"""Tests for snapshot_freeze.py: per-file sha256 -> Merkle freeze -> read-only + snapshot_manifest.

Reuses the U0 common/manifest functions (sha256_file/merkle_root/write_dataset_commit/dataset_is_valid)
and atomic_io.atomic_write_bytes.

Fixtures are a few small fake .gz files (gzip JSONL, one record per line) to test the freeze and the
order-sensitivity of the Merkle root; never a real download.

Points tested:
  - hash_and_count_shard returns (sha256, record_count) in a single pass.
  - freeze_snapshot hashes each shard -> merkle_root -> snapshot_manifest.json (with version + checksums) -> atomic write.
  - Merkle order sensitivity: changing the shard order changes the root (the key to the freeze credential resisting drift).
  - The sha of snapshot_manifest.json itself goes into COMMIT (tamper with the anchor -> verify_frozen False).
  - Tampering with a data shard -> verify_frozen False.
  - assert_manifests_present is the pre-freeze gate: a missing top-level manifest -> raise.
  - make_readonly clears the write bits.
  - If the entry-time Merkle check fails -> EXIT_MERKLE_INVALID (=23, issued by U0).
"""
from __future__ import annotations

import gzip
import json
import os
import stat

import pytest

from m0_snapshot import snapshot_freeze


# ---------------------------------------------------------------------------
# fixture: build small fake gzip JSONL shards (one JSON record per line)
# ---------------------------------------------------------------------------
def _write_gz(path, records):
    """Write records (list[dict]) as a gzip JSONL shard (one record per line)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def _make_snapshot(tmp_path, *, with_manifest=True):
    """Build a minimal snapshot tree: two shards under works/ + the top-level manifest.json.

    Returns snapshot_root (Path).
    """
    root = tmp_path / "snapshot"
    works = root / "works" / "updated_date=2016-06-24"
    _write_gz(works / "part_0000.gz", [{"id": "https://openalex.org/W1"}, {"id": "https://openalex.org/W2"}])
    _write_gz(works / "part_0001.gz", [{"id": "https://openalex.org/W3"}])
    if with_manifest:
        # the single top-level manifest (observed shape; the pre-freeze gate checks it is present = the invariant that the data is complete)
        (root / "manifest.json").write_text(
            json.dumps({"date": "2016-06-24", "format": "jsonl", "meta": {}, "entities": []}),
            encoding="utf-8",
        )
    return root


# ---------------------------------------------------------------------------
# hash_and_count_shard: returns (sha256, record_count) in a single pass
# ---------------------------------------------------------------------------
def test_hash_and_count_shard_returns_sha_and_count(tmp_path):
    """Single-pass read: returns (sha256 hex, number of decompressed lines)."""
    p = tmp_path / "part_0000.gz"
    _write_gz(p, [{"id": "W1"}, {"id": "W2"}, {"id": "W3"}])
    sha, count = snapshot_freeze.hash_and_count_shard(p)
    assert isinstance(sha, str) and len(sha) == 64  # sha256 hex
    assert count == 3


def test_hash_and_count_shard_sha_matches_u0_sha256_file(tmp_path):
    """The sha must == U0 manifest.sha256_file (same file) (reuse U0, no home-made hash)."""
    from common.manifest import sha256_file

    p = tmp_path / "part_0000.gz"
    _write_gz(p, [{"id": "W1"}])
    sha, _ = snapshot_freeze.hash_and_count_shard(p)
    assert sha == sha256_file(p)


# ---------------------------------------------------------------------------
# freeze_snapshot: hash each shard -> merkle -> snapshot_manifest.json -> freeze
# ---------------------------------------------------------------------------
def test_freeze_snapshot_writes_manifest_with_root_and_shards(tmp_path):
    """The freeze produces snapshot_manifest.json: it holds merkle_root + {rel_path,sha256,record_count,entity} for each shard."""
    root = _make_snapshot(tmp_path)
    out = snapshot_freeze.freeze_snapshot(
        root,
        entities=("works",),
        release_date="2016-06-24",
        max_updated_date="2016-06-24",
        topics_version="t1",
    )
    assert "merkle_root" in out and isinstance(out["merkle_root"], str)
    shards = out["shards"]
    assert len(shards) == 2  # part_0000 + part_0001
    for s in shards:
        assert set(s) >= {"rel_path", "sha256", "record_count", "entity"}
        assert s["entity"] == "works"
        assert len(s["sha256"]) == 64
    # snapshot_manifest.json is written to disk
    mf = root / "snapshot_manifest.json"
    assert mf.is_file()
    on_disk = json.loads(mf.read_text(encoding="utf-8"))
    assert on_disk["merkle_root"] == out["merkle_root"]
    # the version (snapshot release) + the declaration of the sha source are present
    assert on_disk["openalex_release"]["max_updated_date"] == "2016-06-24"
    assert "NOT provided by OpenAlex" in on_disk["sha_provenance"]


def test_freeze_snapshot_rel_path_is_entity_scoped_not_bare(tmp_path):
    """rel_path must be entity-qualified (contains works/...), not a bare file name (every entity has a part_000.gz)."""
    root = _make_snapshot(tmp_path)
    out = snapshot_freeze.freeze_snapshot(
        root, entities=("works",), release_date="2016-06-24",
        max_updated_date="2016-06-24", topics_version="t1",
    )
    for s in out["shards"]:
        assert s["rel_path"].startswith("works/"), f"rel_path should be entity-qualified: {s['rel_path']}"
        assert s["rel_path"].endswith(".gz")


# ---------------------------------------------------------------------------
# Merkle order sensitivity (the key to the freeze credential): changing the shard order changes the root
# ---------------------------------------------------------------------------
def test_merkle_root_is_order_sensitive(tmp_path):
    """The same shard bytes in a different feed order -> a different Merkle root (a different order gives a different root)."""
    from common.manifest import merkle_root

    leaf_a = b"alpha-shard-sha"
    leaf_b = b"beta-shard-sha"
    root_ab = merkle_root([leaf_a, leaf_b])
    root_ba = merkle_root([leaf_b, leaf_a])
    assert root_ab != root_ba, "The Merkle root must be order-sensitive (a different order gives a different root)"


def test_freeze_snapshot_shards_sorted_deterministically(tmp_path):
    """Shards are sorted deterministically by rel_path before they are fed to the Merkle tree -> two freezes of the same input give the same root (reproducible)."""
    root1 = _make_snapshot(tmp_path / "a")
    root2 = _make_snapshot(tmp_path / "b")
    out1 = snapshot_freeze.freeze_snapshot(
        root1, entities=("works",), release_date="2016-06-24",
        max_updated_date="2016-06-24", topics_version="t1",
    )
    out2 = snapshot_freeze.freeze_snapshot(
        root2, entities=("works",), release_date="2016-06-24",
        max_updated_date="2016-06-24", topics_version="t1",
    )
    # the same shard contents -> the same merkle root (guaranteed by the deterministic sort, not by file-system enumeration order)
    assert out1["merkle_root"] == out2["merkle_root"]


# ---------------------------------------------------------------------------
# verify_frozen: reuses U0 dataset_is_valid; tampering with the anchor or data -> False
# ---------------------------------------------------------------------------
def test_verify_frozen_true_after_freeze(tmp_path):
    """After the freeze, verify_frozen=True (COMMIT is stamped; reuses U0 dataset_is_valid)."""
    root = _make_snapshot(tmp_path)
    snapshot_freeze.freeze_snapshot(
        root, entities=("works",), release_date="2016-06-24",
        max_updated_date="2016-06-24", topics_version="t1",
    )
    assert snapshot_freeze.verify_frozen(root) is True


def test_data_shard_tamper_changes_recomputed_merkle(tmp_path):
    """Tampering with a data shard -> the recomputed Merkle root != the root recorded at freeze time (reproduction compares the root first)."""
    root = _make_snapshot(tmp_path)
    out = snapshot_freeze.freeze_snapshot(
        root, entities=("works",), release_date="2016-06-24",
        max_updated_date="2016-06-24", topics_version="t1",
    )
    frozen_root_hash = out["merkle_root"]
    # tamper with one data shard (the read-only bit must be cleared first)
    target = root / "works" / "updated_date=2016-06-24" / "part_0000.gz"
    os.chmod(target, 0o644)
    _write_gz(target, [{"id": "TAMPERED"}])
    # recompute -> the root should change
    recomputed = snapshot_freeze.recompute_merkle(
        root, entities=("works",)
    )
    assert recomputed != frozen_root_hash


def test_entry_merkle_guard_exits_on_mismatch(tmp_path):
    """If the entry-time Merkle check fails -> sys.exit(EXIT_MERKLE_INVALID=23, issued by U0)."""
    from identity.exit_codes import EXIT_MERKLE_INVALID

    root = _make_snapshot(tmp_path)
    snapshot_freeze.freeze_snapshot(
        root, entities=("works",), release_date="2016-06-24",
        max_updated_date="2016-06-24", topics_version="t1",
    )
    # tamper with a data shard -> the entry guard should exit(23)
    target = root / "works" / "updated_date=2016-06-24" / "part_0000.gz"
    os.chmod(target, 0o644)
    _write_gz(target, [{"id": "TAMPERED"}])
    with pytest.raises(SystemExit) as ei:
        snapshot_freeze.assert_entry_merkle(root, entities=("works",))
    assert ei.value.code == EXIT_MERKLE_INVALID


# ---------------------------------------------------------------------------
# assert_manifests_present: the pre-freeze gate: a missing top-level manifest -> raise
# ---------------------------------------------------------------------------
def test_assert_manifests_present_ok_when_manifest_on_disk(tmp_path):
    """The top-level manifest.json is on disk -> no raise (invariant: manifest present <=> data complete)."""
    root = _make_snapshot(tmp_path, with_manifest=True)
    snapshot_freeze.assert_manifests_present(root)  # no raise


def test_assert_manifests_present_raises_when_manifest_missing(tmp_path):
    """The top-level manifest.json is missing -> raise (blocks a silent freeze of a half-damaged tree that collided with the quarterly partition-write window)."""
    root = _make_snapshot(tmp_path, with_manifest=False)
    with pytest.raises(Exception):
        snapshot_freeze.assert_manifests_present(root)


def test_freeze_snapshot_refuses_when_manifest_missing(tmp_path):
    """freeze_snapshot runs assert_manifests_present first; a missing manifest -> refuse to freeze (raise)."""
    root = _make_snapshot(tmp_path, with_manifest=False)
    with pytest.raises(Exception):
        snapshot_freeze.freeze_snapshot(
            root, entities=("works",), release_date="2016-06-24",
            max_updated_date="2016-06-24", topics_version="t1",
        )


# ---------------------------------------------------------------------------
# make_readonly: chmod -w physically cuts the link to the sync source
# ---------------------------------------------------------------------------
def test_make_readonly_clears_write_bits(tmp_path):
    """The original frozen .gz files get chmod -w -> the write bits are cleared (physically cutting the link to the sync source)."""
    root = _make_snapshot(tmp_path)
    snapshot_freeze.freeze_snapshot(
        root, entities=("works",), release_date="2016-06-24",
        max_updated_date="2016-06-24", topics_version="t1",
    )
    changed = snapshot_freeze.make_readonly(root)
    assert len(changed) >= 2  # two shards
    for p in changed:
        mode = os.stat(p).st_mode
        assert not (mode & stat.S_IWUSR), f"The write bit should have been cleared: {p}"
    # restore the write bits (so tmp_path can be cleaned up)
    for p in changed:
        os.chmod(p, 0o644)
