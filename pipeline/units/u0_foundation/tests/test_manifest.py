"""TDD red tests for U0 common/manifest.py (T21-T26).

Guards the manifest:
  T21 merkle_root is order-sensitive (a different order gives a different root): the freeze credential.
  T22 write_dataset_commit has two phases: before COMMIT the whole dataset has dataset_is_valid=False.
  T23 replay_merged_ids resolves roots iteratively + raises on a cycle + returns is_deleted;
      DELETION_SENTINELS_WORKS contains W4285719527; DELETION_SENTINELS_AUTHORS is an empty-set placeholder.
  T24 any inequality among the provenance 4-tuple -> raise ProvenanceMismatch(=13), a HALT not a WARN (HIGH-7).
  T25 the source_snapshot_merkle comparison reads only the value already stored in the artifact header and does not recompute the merkle.
  T26 rule_version containing "unsigned" -> the artifact goes to staging, not _frozen/,
      and the header has rule_version_signed=False (isolation of unsigned output).

Discipline: do not assert bare exit-code numbers -> assert the exception type + that .exit_code is distinguishable (consistent with exit_codes.PROVENANCE_MISMATCH).
"""
import hashlib
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common import manifest  # noqa: E402
from identity import exit_codes  # noqa: E402


# ===========================================================================
# T21: merkle_root is order-sensitive (a different order gives a different root)
# ===========================================================================
def test_t21_merkle_root_order_sensitive():
    leaves_a = [b"alpha", b"beta", b"gamma"]
    leaves_b = [b"beta", b"alpha", b"gamma"]  # order changed only
    root_a = manifest.merkle_root(leaves_a)
    root_b = manifest.merkle_root(leaves_b)
    assert root_a != root_b, "merkle_root must be order-sensitive: a different order must give a different root"


def test_t21_merkle_root_deterministic_same_order():
    leaves = [b"alpha", b"beta", b"gamma"]
    assert manifest.merkle_root(leaves) == manifest.merkle_root(list(leaves)), (
        "same order, same leaves → same root (deterministic)"
    )


def test_t21_merkle_root_single_and_empty():
    # a single leaf / an empty leaf set must both be defined (no crash), and differ from each other.
    one = manifest.merkle_root([b"only"])
    empty = manifest.merkle_root([])
    assert isinstance(one, str) and isinstance(empty, str)
    assert one != empty


# ===========================================================================
# T22: write_dataset_commit has two phases: before COMMIT the whole dataset is invalid
# ===========================================================================
def _good_provenance():
    return {
        "source_snapshot_merkle": "m0merkle",
        "config_sha": "cfgsha",
        "rule_version": "redlines_v2_signed_2026-06-27",
        "stars_set_hash": "starhash",
    }


def test_t22_dataset_invalid_until_commit(tmp_path):
    root = tmp_path / "ds"
    payload = {"part-000.parquet": b"row-bytes"}
    # Use a generator / explicit two phases: after the data is written but before the COMMIT marker, dataset_is_valid must be False.
    committer = manifest.write_dataset_commit(
        root, payload, provenance=_good_provenance()
    )
    # phase 1: the data is in staging, no COMMIT yet
    committer.stage()
    assert manifest.dataset_is_valid(root) is False, (
        "before COMMIT: the whole dataset must be judged invalid (atomic commit semantics)"
    )
    # phase 2: write the COMMIT marker
    committer.commit()
    assert manifest.dataset_is_valid(root) is True, "the dataset is valid only after COMMIT"


def test_t22_partial_dataset_without_commit_marker_invalid(tmp_path):
    # Even if the directory holds data files, a missing COMMIT marker = invalid (a dirty directory from a crash between the two phases).
    root = tmp_path / "ds_dirty"
    root.mkdir()
    (root / "part-000.parquet").write_bytes(b"orphan")
    assert manifest.dataset_is_valid(root) is False


# ===========================================================================
# T23: replay_merged_ids resolves roots iteratively + raises on a cycle + carries is_deleted; deletion sentinels
# ===========================================================================
def test_t23_replay_resolves_transitive_root():
    # A->B->C (C is the root): all resolve to C.
    rows = [
        {"raw_id": "A", "canonical_id": "B"},
        {"raw_id": "B", "canonical_id": "C"},
    ]
    out = manifest.replay_merged_ids(
        rows, deletion_sentinels=manifest.DELETION_SENTINELS_WORKS
    )
    assert out["A"][0] == "C"
    assert out["B"][0] == "C"
    # the return value carries is_deleted (the second item of the pair is a bool)
    assert isinstance(out["A"][1], bool)


def test_t23_replay_cycle_raises():
    # X->Y->X forms a cycle: must raise (never loop forever).
    rows = [
        {"raw_id": "X", "canonical_id": "Y"},
        {"raw_id": "Y", "canonical_id": "X"},
    ]
    with pytest.raises(Exception):
        manifest.replay_merged_ids(
            rows, deletion_sentinels=manifest.DELETION_SENTINELS_WORKS
        )


def test_t23_replay_marks_deletion_sentinel():
    # resolving to the deletion sentinel W4285719527 -> is_deleted=True.
    rows = [{"raw_id": "Wdup", "canonical_id": "W4285719527"}]
    out = manifest.replay_merged_ids(
        rows, deletion_sentinels=manifest.DELETION_SENTINELS_WORKS
    )
    assert out["Wdup"][0] == "W4285719527"
    assert out["Wdup"][1] is True, "resolving to a deletion sentinel → is_deleted=True"


def test_t23_deletion_sentinels_constants():
    # DELETION_SENTINELS_WORKS contains W4285719527; AUTHORS = an empty-set placeholder (to be filled after the m0 freeze).
    assert "W4285719527" in manifest.DELETION_SENTINELS_WORKS
    assert manifest.DELETION_SENTINELS_AUTHORS == set(), (
        "DELETION_SENTINELS_AUTHORS is an empty-set placeholder, to be backfilled later"
    )


# ===========================================================================
# T24: any inequality among the provenance 4-tuple -> raise ProvenanceMismatch(=13), a HALT not a WARN
# ===========================================================================
def test_t24_provenance_keys_constant():
    assert manifest.PROVENANCE_KEYS == (
        "source_snapshot_merkle",
        "config_sha",
        "rule_version",
        "stars_set_hash",
    )


def test_t24_provenance_match_passes():
    a = _good_provenance()
    b = dict(a)
    # all equal -> does not raise, returns True
    assert manifest.verify_provenance(a, b) is True


def test_t24_provenance_mismatch_raises_with_exit_code():
    a = _good_provenance()
    for k in manifest.PROVENANCE_KEYS:
        b = dict(a)
        b[k] = "DIFFERENT"
        with pytest.raises(manifest.ProvenanceMismatch) as ei:
            manifest.verify_provenance(a, b)
        # HALT semantics: the exception carries the exit code, consistent with exit_codes.PROVENANCE_MISMATCH (=13)
        assert ei.value.exit_code == exit_codes.PROVENANCE_MISMATCH


# ===========================================================================
# T25: the source_snapshot_merkle comparison reads only the value already stored in the artifact header and does not recompute the merkle
# ===========================================================================
def test_t25_provenance_reads_stored_merkle_not_recompute(monkeypatch):
    # The comparison is string equality on the stored value and never calls merkle_root to recompute.
    called = {"n": 0}
    real_merkle = manifest.merkle_root

    def _spy(*args, **kwargs):
        called["n"] += 1
        return real_merkle(*args, **kwargs)

    monkeypatch.setattr(manifest, "merkle_root", _spy)
    a = _good_provenance()
    b = dict(a)
    manifest.verify_provenance(a, b)
    assert called["n"] == 0, "provenance comparison must not recompute the merkle root (read only the value stored in the artifact header)"


# ===========================================================================
# T26: rule_version containing "unsigned" -> goes to staging, not _frozen/, header signed=False
# ===========================================================================
def test_t26_unsigned_rule_version_lands_in_staging(tmp_path):
    root = tmp_path / "ds_unsigned"
    payload = {"part-000.parquet": b"x"}
    prov = _good_provenance()
    prov["rule_version"] = "redlines_unsigned_draft"  # contains "unsigned"
    committer = manifest.write_dataset_commit(root, payload, provenance=prov)
    committer.stage()
    committer.commit()
    # the artifact goes to the staging area, not _frozen/
    assert (committer.staging_dir / "COMMIT").exists()
    assert not (root / "_frozen").exists(), "an artifact containing unsigned must never land in _frozen/"
    # the header is marked rule_version_signed=False
    assert committer.header["rule_version_signed"] is False


def test_t26_signed_rule_version_lands_in_frozen(tmp_path):
    root = tmp_path / "ds_signed"
    payload = {"part-000.parquet": b"y"}
    committer = manifest.write_dataset_commit(
        root, payload, provenance=_good_provenance()
    )
    committer.stage()
    committer.commit()
    # signed -> goes to _frozen/, header signed=True
    assert (root / "_frozen" / "COMMIT").exists()
    assert committer.header["rule_version_signed"] is True


# ===========================================================================
# Addendum: sha256_file (kept consistent with the standard library)
# ===========================================================================
def test_sha256_file_matches_hashlib(tmp_path):
    p = tmp_path / "blob.bin"
    data = b"hash-me-deterministically"
    p.write_bytes(data)
    assert manifest.sha256_file(p) == hashlib.sha256(data).hexdigest()
