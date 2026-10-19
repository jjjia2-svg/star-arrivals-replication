"""Tests for manifest_reconcile.py: fixtures check parsing and reconcile; never a real S3 download.

Behaviour covered (the observed manifest shape):
  - parse_top_manifest: parse the top-level manifest.json (the only manifest) and check the
    {date,format,meta,entities[]} shape.
  - files_for_entity: take an entity's files[] list from entities[] (there is no per-entity manifest).
  - assert_manifest_shape: a missing meta/entities/files/url raises, naming the field; no silent .get None.
  - list_expected_shards: take .gz file names from files[].url (feeds the reconcile arm).
  - remote_record_count_for_entity: entities[entity].record_count (the true remote count).
  - reconcile_shards: the expected .gz set must equal the downloaded .gz set; a mismatch ->
    sys.exit(TALLY_IMBALANCE=15).
  - record_count conservation arm: the sum of files[].meta.record_count == entities[entity].record_count.

Observed manifest shape, verbatim:
  { "date":"2026-06-26", "format":"jsonl",
    "meta": {"record_count":..., "content_length":...},
    "entities": [ {"entity":"works", "record_count":..., "content_length":...,
                   "files":[{"url":"s3://openalex/data/jsonl/works/updated_date=.../part_0000.gz",
                             "meta":{"content_length":...,"record_count":...}}, ...]}, ... ] }
"""
from __future__ import annotations

import json

import pytest

from m0_snapshot import manifest_reconcile as mr
from identity.exit_codes import TALLY_IMBALANCE


# ---------------------------------------------------------------------------
# fixture: a mini top-level manifest in the observed shape (2 entities, a few files each)
# ---------------------------------------------------------------------------
def _mini_manifest():
    return {
        "date": "2026-06-26",
        "format": "jsonl",
        "meta": {"record_count": 9, "content_length": 9000},
        "entities": [
            {
                "entity": "works",
                "record_count": 5,
                "content_length": 5000,
                "files": [
                    {
                        "url": "s3://openalex/data/jsonl/works/updated_date=2016-06-24/part_0000.gz",
                        "meta": {"content_length": 3000, "record_count": 3},
                    },
                    {
                        "url": "s3://openalex/data/jsonl/works/updated_date=2016-06-25/part_0000.gz",
                        "meta": {"content_length": 2000, "record_count": 2},
                    },
                ],
            },
            {
                "entity": "authors",
                "record_count": 4,
                "content_length": 4000,
                "files": [
                    {
                        "url": "s3://openalex/data/jsonl/authors/updated_date=2016-06-24/part_0000.gz",
                        "meta": {"content_length": 4000, "record_count": 4},
                    }
                ],
            },
        ],
    }


# ---------------------------------------------------------------------------
# parse + shape
# ---------------------------------------------------------------------------
def test_parse_top_manifest_from_bytes_roundtrips():
    blob = json.dumps(_mini_manifest()).encode("utf-8")
    obj = mr.parse_top_manifest(blob)
    assert obj["date"] == "2026-06-26"
    assert obj["format"] == "jsonl"
    names = [e["entity"] for e in obj["entities"]]
    assert "works" in names and "authors" in names


def test_parse_top_manifest_accepts_str_too():
    text = json.dumps(_mini_manifest())
    obj = mr.parse_top_manifest(text)
    assert obj["format"] == "jsonl"


def test_assert_manifest_shape_accepts_valid():
    mr.assert_manifest_shape(_mini_manifest())  # valid input does not raise


def test_assert_manifest_shape_raises_on_missing_entities():
    bad = _mini_manifest()
    del bad["entities"]
    with pytest.raises((KeyError, ValueError)):
        mr.assert_manifest_shape(bad)


def test_assert_manifest_shape_raises_on_empty_entities():
    bad = _mini_manifest()
    bad["entities"] = []
    with pytest.raises(ValueError):
        mr.assert_manifest_shape(bad)


def test_assert_manifest_shape_raises_on_missing_meta():
    bad = _mini_manifest()
    del bad["meta"]
    with pytest.raises((KeyError, ValueError)):
        mr.assert_manifest_shape(bad)


def test_assert_manifest_shape_raises_when_file_missing_url():
    bad = _mini_manifest()
    del bad["entities"][0]["files"][0]["url"]
    with pytest.raises((KeyError, ValueError)):
        mr.assert_manifest_shape(bad)


def test_assert_manifest_shape_raises_when_file_meta_missing_record_count():
    bad = _mini_manifest()
    del bad["entities"][0]["files"][0]["meta"]["record_count"]
    with pytest.raises((KeyError, ValueError)):
        mr.assert_manifest_shape(bad)


def test_parse_top_manifest_rejects_bad_json():
    with pytest.raises(json.JSONDecodeError):
        mr.parse_top_manifest(b"{not valid json")


# ---------------------------------------------------------------------------
# per-entity files[] (the top-level manifest is the only one; there is no per-entity manifest)
# ---------------------------------------------------------------------------
def test_files_for_entity_returns_that_entitys_file_list():
    files = mr.files_for_entity(_mini_manifest(), entity="works")
    assert len(files) == 2
    assert all("url" in f for f in files)
    assert files[0]["url"].endswith("part_0000.gz")


def test_files_for_entity_unknown_entity_raises():
    with pytest.raises((KeyError, ValueError)):
        mr.files_for_entity(_mini_manifest(), entity="institutions")


def test_list_expected_shards_extracts_gz_urls_in_order():
    shards = mr.list_expected_shards(_mini_manifest(), entity="works")
    assert len(shards) == 2
    assert all(s.endswith(".gz") for s in shards)
    # keeps the order inside the manifest (deterministic)
    assert "updated_date=2016-06-24" in shards[0]
    assert "updated_date=2016-06-25" in shards[1]


def test_remote_record_count_for_entity():
    assert mr.remote_record_count_for_entity(_mini_manifest(), entity="works") == 5
    assert mr.remote_record_count_for_entity(_mini_manifest(), entity="authors") == 4


def test_remote_bytes_for_entity():
    assert mr.remote_bytes_for_entity(_mini_manifest(), entity="works") == 5000


def test_expected_record_count_sum_matches_entity_total():
    """Conservation arm: the sum of files[].meta.record_count == entities[entity].record_count."""
    total = mr.expected_record_count_from_files(_mini_manifest(), entity="works")
    assert total == 5  # 3 + 2
    assert total == mr.remote_record_count_for_entity(_mini_manifest(), entity="works")


# ---------------------------------------------------------------------------
# reconcile: expected shard set == downloaded shard set; mismatch -> exit(TALLY_IMBALANCE=15)
# ---------------------------------------------------------------------------
def test_reconcile_shards_all_present_returns_ok(tmp_path):
    expected = mr.list_expected_shards(_mini_manifest(), entity="works")
    got = list(expected)
    result = mr.reconcile_shards(
        expected_urls=expected, present_urls=got, tally_path=tmp_path / "t.json"
    )
    assert result["balanced"] is True
    assert result["expected"] == 2
    assert result["missing_count"] == 0
    assert (tmp_path / "t.json").exists()  # when balanced, a tally receipt is written


def test_reconcile_shards_missing_one_exits_15(tmp_path):
    expected = mr.list_expected_shards(_mini_manifest(), entity="works")
    present = expected[:1]  # a lost shard -> a wholly missing shard must be caught
    with pytest.raises(SystemExit) as exc:
        mr.reconcile_shards(
            expected_urls=expected, present_urls=present, tally_path=tmp_path / "t.json"
        )
    assert exc.value.code == TALLY_IMBALANCE == 15


def test_reconcile_shards_extra_unexpected_exits_15(tmp_path):
    expected = mr.list_expected_shards(_mini_manifest(), entity="works")
    present = list(expected) + [
        "s3://openalex/data/jsonl/works/updated_date=2099-01-01/part_9999.gz"
    ]
    with pytest.raises(SystemExit) as exc:
        mr.reconcile_shards(
            expected_urls=expected, present_urls=present, tally_path=tmp_path / "t.json"
        )
    assert exc.value.code == TALLY_IMBALANCE


def test_reconcile_shards_works_without_tally_path():
    """tally_path=None also works (nothing is written to disk); when balanced it returns a dict."""
    expected = mr.list_expected_shards(_mini_manifest(), entity="authors")
    result = mr.reconcile_shards(expected_urls=expected, present_urls=expected)
    assert result["balanced"] is True
