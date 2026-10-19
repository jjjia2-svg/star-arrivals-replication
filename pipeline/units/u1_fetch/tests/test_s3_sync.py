"""Tests for s3_sync.py: construction of the aws s3 sync command (only command construction is tested; never a real S3 download).

Based on the observed S3 paths (anonymous --no-sign-request, verified against the real bucket):
  - The real path has a jsonl/ level: s3://openalex/data/jsonl/<entity>/  (OPENALEX_DATA_PREFIX="data/jsonl").
  - There is only one top-level manifest, s3://openalex/data/jsonl/manifest.json (it holds entities[] for
    all entities); there is no per-entity manifest (per-entity gives 404).

Scope: pure command construction + parsing and shape checks of the top-level manifest (using a fixture
dict, no network). The real sync / cp is left to operations scripts; here we assert only that the command
strings are right and that the manifest shape is guarded.
"""
import json

import pytest

from m0_snapshot import s3_sync

# --- M3 port: repo path resolution (legacy hard-coded the author's machine) — config/paths.yaml ---
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents if p.name == "units").parents[1]
if str(_sar_repo) not in _sar_sys.path:
    _sar_sys.path.append(str(_sar_repo))
from pipeline.lib.paths import snapshot_root as _sar_snapshot_root  # noqa: E402


# ---------------------------------------------------------------------------
# build_sync_cmd: build the aws s3 sync command (observed jsonl/ path + --no-sign-request)
# ---------------------------------------------------------------------------
def test_build_sync_cmd_uses_jsonl_prefix_and_anon_flag():
    """The observed path has jsonl/; the command carries --no-sign-request (anonymous, free); the target is under SNAPSHOT_ROOT."""
    cmd = s3_sync.build_sync_cmd(
        "works", snapshot_root=str(_sar_snapshot_root())
    )
    assert cmd[0] == "aws"
    assert cmd[1] == "s3"
    assert cmd[2] == "sync"
    # source = the observed real path s3://openalex/data/jsonl/works/ (with the jsonl/ level)
    assert "s3://openalex/data/jsonl/works/" in cmd
    # the anonymous-free flag must be present (--no-sign-request needs no key and has no throttling)
    assert "--no-sign-request" in cmd
    # target = that entity's subdirectory under SNAPSHOT_ROOT
    assert any("/openalex_pipeline/snapshot" in part and part.endswith("works/") for part in cmd)


def test_build_sync_cmd_dryrun_appends_flag():
    """dryrun=True -> the command ends with --dryrun (command construction can be switched to dry-run)."""
    cmd = s3_sync.build_sync_cmd("works", snapshot_root="/tmp/snap", dryrun=True)
    assert "--dryrun" in cmd


def test_build_sync_cmd_rejects_illegal_entity():
    """entity not in SYNC_ENTITIES -> ValueError (a command for an illegal entity is never built)."""
    with pytest.raises(ValueError):
        s3_sync.build_sync_cmd("garbage_entity", snapshot_root="/tmp/snap")


def test_sync_entities_constant_is_works_authors_institutions():
    """SYNC_ENTITIES = the three types (works/authors/institutions); institutions must be included."""
    assert s3_sync.SYNC_ENTITIES == ("works", "authors", "institutions")


def test_data_prefix_constant_includes_jsonl():
    """OPENALEX_DATA_PREFIX = 'data/jsonl' (observed to include jsonl/, not the old 'data')."""
    assert s3_sync.OPENALEX_DATA_PREFIX == "data/jsonl"
    assert s3_sync.OPENALEX_S3_BUCKET == "openalex"
    assert s3_sync.ANON_FLAG == "--no-sign-request"


# ---------------------------------------------------------------------------
# build_manifest_cp_cmd: the single top-level manifest (observed: not per-entity)
# ---------------------------------------------------------------------------
def test_build_manifest_cp_cmd_points_to_top_level_single_manifest():
    """The single top-level manifest = s3://openalex/data/jsonl/manifest.json (observed; per-entity gives 404)."""
    cmd = s3_sync.build_manifest_cp_cmd()
    assert cmd[:3] == ["aws", "s3", "cp"]
    assert "s3://openalex/data/jsonl/manifest.json" in cmd
    assert "--no-sign-request" in cmd
    # cp to stdout (-) so the output can be injected and parsed
    assert "-" in cmd


# ---------------------------------------------------------------------------
# top-level manifest shape (fixture dict; observed structure {date,format,meta,entities[]})
# ---------------------------------------------------------------------------
def _good_top_manifest():
    """The observed top-level manifest shape (verbatim)."""
    return {
        "date": "2026-06-26",
        "format": "jsonl",
        "meta": {"record_count": 649096577, "content_length": 745496091411},
        "entities": [
            {
                "entity": "works",
                "record_count": 510372821,
                "content_length": 665688383258,
                "files": [
                    {
                        "url": "s3://openalex/data/jsonl/works/updated_date=2016-06-24/part_0000.gz",
                        "meta": {"content_length": 3038473, "record_count": 2439},
                    },
                    {
                        "url": "s3://openalex/data/jsonl/works/updated_date=2016-07-01/part_0000.gz",
                        "meta": {"content_length": 100, "record_count": 5},
                    },
                ],
            },
            {
                "entity": "authors",
                "record_count": 100,
                "content_length": 200,
                "files": [
                    {
                        "url": "s3://openalex/data/jsonl/authors/updated_date=2016-06-24/part_0000.gz",
                        "meta": {"content_length": 200, "record_count": 100},
                    }
                ],
            },
        ],
    }


def test_assert_manifest_shape_accepts_good_top_manifest():
    """A valid top-level manifest shape -> does not raise."""
    s3_sync.assert_manifest_shape(_good_top_manifest())


def test_assert_manifest_shape_raises_on_missing_entities():
    """entities[] missing -> raise naming it (not silent)."""
    bad = _good_top_manifest()
    del bad["entities"]
    with pytest.raises(Exception):
        s3_sync.assert_manifest_shape(bad)


def test_assert_manifest_shape_raises_when_file_meta_missing_record_count():
    """A file.meta lacks record_count -> raise naming it (never a silent .get None)."""
    bad = _good_top_manifest()
    del bad["entities"][0]["files"][0]["meta"]["record_count"]
    with pytest.raises(Exception):
        s3_sync.assert_manifest_shape(bad)


# ---------------------------------------------------------------------------
# list_expected_shards: take .gz from the top-level manifest entities[entity].files[].url
# ---------------------------------------------------------------------------
def test_list_expected_shards_extracts_gz_urls_for_entity():
    """Take all shard .gz urls of the entity from the top-level manifest (the external ground truth fed to reconcile)."""
    shards = s3_sync.list_expected_shards("works", manifest_obj=_good_top_manifest())
    assert len(shards) == 2
    assert all(s.endswith(".gz") for s in shards)
    assert "s3://openalex/data/jsonl/works/updated_date=2016-06-24/part_0000.gz" in shards


def test_list_expected_shards_raises_on_unknown_entity():
    """The manifest does not have this entity -> raise (do not return empty and treat it as 0 shards)."""
    with pytest.raises(Exception):
        s3_sync.list_expected_shards("sources", manifest_obj=_good_top_manifest())


# ---------------------------------------------------------------------------
# remote_bytes_from_manifest: take the entity's content_length (real remote bytes, not guessed from an estimate)
# ---------------------------------------------------------------------------
def test_remote_bytes_from_manifest_returns_entity_content_length():
    """Take entities[entity].content_length (the top-level meta.content_length is the total over all entities and is not used)."""
    b = s3_sync.remote_bytes_from_manifest("works", manifest_obj=_good_top_manifest())
    assert b == 665688383258


# ---------------------------------------------------------------------------
# fetch_official_manifest: runner injected to get bytes -> save to disk -> json.loads -> shape check
# (using a fake runner, never any network)
# ---------------------------------------------------------------------------
def test_fetch_official_manifest_parses_and_persists(tmp_path):
    """The runner returns the top-level manifest bytes -> saved as a reproducibility credential + parsed + shape check passes."""
    blob = json.dumps(_good_top_manifest()).encode("utf-8")

    def fake_runner(cmd):
        # assert that it really fetches the top-level manifest (no real network)
        assert "s3://openalex/data/jsonl/manifest.json" in cmd
        return blob

    out = s3_sync.fetch_official_manifest(
        snapshot_root=str(tmp_path), runner=fake_runner
    )
    assert out["format"] == "jsonl"
    # reproducibility credential saved: snapshot_root should hold a copy of manifest.json
    persisted = tmp_path / "manifest.json"
    assert persisted.is_file()
    assert json.loads(persisted.read_bytes())["date"] == "2026-06-26"


def test_fetch_official_manifest_raises_on_bad_bytes(tmp_path):
    """The runner returns bad bytes (not JSON) -> raise (never silently treated as "0 shards expected")."""
    def bad_runner(cmd):
        return b"<html>403 forbidden</html>"

    with pytest.raises(Exception):
        s3_sync.fetch_official_manifest(snapshot_root=str(tmp_path), runner=bad_runner)
