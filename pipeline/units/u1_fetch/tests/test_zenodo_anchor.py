"""M0-6 zenodo_anchor red tests - snapshot release reproduction anchor + DOI backfill re-seal (injected, no real publishing).

What is tested (build list M0-6 + task):
  - release version anchor: extract the reproduction identity from snapshot_manifest (merkle_root / sync_date / s3_etag /
    topics_version) -> a stable anchor dict, which reproduction compares against.
  - DOI placeholder: zenodo_doi starts as a placeholder (None/PLACEHOLDER style, to be backfilled at m0); a DOI value is never invented.
  - backfill_zenodo_doi: fill the real DOI into snapshot_manifest.json -> its own sha changes -> re-seal COMMIT.
  - re-seal: once the anchor is filled, dataset_is_valid (via U0 write_dataset_commit, two-phase COMMIT).
  - tamper detection: after filling, change the manifest bytes -> the archived sha no longer matches (reproduction compares sha first).

Discipline: everything is injected via fixture/tmp_path; no network, no real DOI minted; the anchor placeholder waits for the m0 backfill and is never filled in by anyone else.
"""
from __future__ import annotations

import json

import pytest

from m0_snapshot import zenodo_anchor


def _snapshot_manifest_obj():
    """The shape of the snapshot_manifest.json written by M0-2 (source of the release anchor). zenodo_doi starts as a placeholder."""
    return {
        "merkle_root": "a" * 64,
        "shards": [
            {"rel_path": "works/updated_date=2016-06-24/part_0000.gz",
             "sha256": "b" * 64, "record_count": 2439, "entity": "works"},
        ],
        "openalex_release": {
            "sync_date": "2026-06-26",
            "max_updated_date": "2026-06-24",
            "s3_etag": "deadbeef",
        },
        "topics_version": "2024-02",
        "sha_provenance": "self-computed, NOT provided by OpenAlex",
        "zenodo_doi": None,
    }


# --- release version anchor: extract the stable reproduction identity ---

def test_release_anchor_extracts_reproducible_identity():
    anchor = zenodo_anchor.build_release_anchor(_snapshot_manifest_obj())
    # The four reproduction identity items must be present (a merge compares these first; if any drifts it is not the same snapshot).
    assert anchor["merkle_root"] == "a" * 64
    assert anchor["sync_date"] == "2026-06-26"
    assert anchor["s3_etag"] == "deadbeef"
    assert anchor["topics_version"] == "2024-02"


def test_release_anchor_doi_is_placeholder_until_backfilled():
    # Before the m0 backfill zenodo_doi must be a placeholder (None), and the anchor reflects "awaiting backfill" - a DOI is never invented.
    anchor = zenodo_anchor.build_release_anchor(_snapshot_manifest_obj())
    assert anchor["zenodo_doi"] is None
    assert anchor["doi_pending"] is True


def test_release_anchor_missing_release_block_raises():
    # Missing the openalex_release block -> raise naming it (the reproduction anchor cannot lack identity; no silent pass).
    bad = _snapshot_manifest_obj()
    del bad["openalex_release"]
    with pytest.raises((KeyError, ValueError)):
        zenodo_anchor.build_release_anchor(bad)


# --- DOI backfill: write into the manifest + its own sha changes ---

def test_backfill_zenodo_doi_fills_slot_and_changes_self_sha(tmp_path):
    manifest_path = tmp_path / "snapshot_manifest.json"
    obj = _snapshot_manifest_obj()
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8")
    manifest_path.write_bytes(blob)

    from common.manifest import sha256_file
    sha_before = sha256_file(manifest_path)

    result = zenodo_anchor.backfill_zenodo_doi(
        manifest_path, doi="10.5281/zenodo.1234567"
    )

    # The slot is filled with the real DOI (no longer a placeholder).
    reloaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert reloaded["zenodo_doi"] == "10.5281/zenodo.1234567"
    # Its own sha must change (the content changed).
    assert result["sha_after"] != sha_before
    assert result["sha_after"] == sha256_file(manifest_path)


def test_backfill_rejects_empty_or_placeholder_doi(tmp_path):
    # An empty string / None / placeholder wording must not be backfilled as a DOI (that would leave it unfilled and lock the slot).
    manifest_path = tmp_path / "snapshot_manifest.json"
    manifest_path.write_bytes(
        json.dumps(_snapshot_manifest_obj(), sort_keys=True).encode("utf-8")
    )
    for bad in ("", "   ", None):
        with pytest.raises(ValueError):
            zenodo_anchor.backfill_zenodo_doi(manifest_path, doi=bad)


# --- re-seal COMMIT: after filling, the dataset is valid (via the U0 two-phase COMMIT) ---

def test_reseal_commit_makes_dataset_valid(tmp_path):
    # Re-seal after backfill: include the sha of the manifest that now contains the DOI in the COMMIT -> dataset_is_valid.
    manifest_path = tmp_path / "snapshot_manifest.json"
    manifest_path.write_bytes(
        json.dumps(_snapshot_manifest_obj(), sort_keys=True, ensure_ascii=False).encode("utf-8")
    )
    commit_root = tmp_path / "snapshot_commit"

    zenodo_anchor.backfill_zenodo_doi(manifest_path, doi="10.5281/zenodo.1234567")
    zenodo_anchor.reseal_commit(
        commit_root,
        manifest_path,
        provenance={
            "source_snapshot_merkle": "a" * 64,
            "config_sha": "cfg123",
            "rule_version": "redlines_v1_signed_2026-06-26",  # signed -> written to _frozen/
            "stars_set_hash": "stars123",
        },
    )

    from common.manifest import dataset_is_valid
    assert dataset_is_valid(commit_root) is True


def test_reseal_unsigned_rule_version_stays_invalid(tmp_path):
    # rule_version contains unsigned -> COMMIT is written to staging only, dataset_is_valid=False (unsigned rule versions are isolated).
    manifest_path = tmp_path / "snapshot_manifest.json"
    manifest_path.write_bytes(
        json.dumps(_snapshot_manifest_obj(), sort_keys=True, ensure_ascii=False).encode("utf-8")
    )
    commit_root = tmp_path / "snapshot_commit_unsigned"

    zenodo_anchor.backfill_zenodo_doi(manifest_path, doi="10.5281/zenodo.1234567")
    zenodo_anchor.reseal_commit(
        commit_root,
        manifest_path,
        provenance={
            "source_snapshot_merkle": "a" * 64,
            "config_sha": "cfg123",
            "rule_version": "redlines_unsigned_draft",  # unsigned
            "stars_set_hash": "stars123",
        },
    )

    from common.manifest import dataset_is_valid
    assert dataset_is_valid(commit_root) is False


# --- tamper detection: change bytes after filling -> the archived sha does not match ---

def test_tamper_after_backfill_breaks_recorded_sha(tmp_path):
    manifest_path = tmp_path / "snapshot_manifest.json"
    manifest_path.write_bytes(
        json.dumps(_snapshot_manifest_obj(), sort_keys=True, ensure_ascii=False).encode("utf-8")
    )
    result = zenodo_anchor.backfill_zenodo_doi(manifest_path, doi="10.5281/zenodo.1234567")
    recorded_sha = result["sha_after"]

    # Quietly change one byte.
    tampered = manifest_path.read_bytes() + b" "
    manifest_path.write_bytes(tampered)

    from common.manifest import sha256_file
    assert sha256_file(manifest_path) != recorded_sha
