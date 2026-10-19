"""Tests for gz_filter.

Behaviour covered:
  - stream_filter_works streams and never decompresses everything to disk at once (it goes through U0's
    snapshot_reader.iter_jsonl_gz_shards).
  - It filters by keep_pred; shard_id includes .gz; WorkFilterStats counts are correct.
  - A truncated .gz -> CorruptShardError -> exit(CORRUPT_SHARD=17), never silently treated as empty
    (regression for an old bug).
  - DUCKDB_BYPASS_ENABLED=False, and calling read_ndjson_gz_duckdb raises RuntimeError.

Fixtures write small real .gz JSONL samples to a temp dir; nothing is downloaded from S3.
"""
import gzip
import json

import pytest

from m1_ingest import gz_filter
from common.snapshot_reader import CorruptShardError
from identity.exit_codes import CORRUPT_SHARD


def _write_gz(path, records):
    """Write records as gzip JSONL (one per line) to imitate a snapshot shard."""
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def _make_shard(tmp_path, name, records):
    p = tmp_path / name
    _write_gz(p, records)
    return str(p)


# ===========================================================================
# stream_filter_works: streaming filter + shard_id includes .gz + counts are correct
# ===========================================================================
def test_stream_filter_econ_subfield_and_year_window(tmp_path):
    recs = [
        {"id": "W1", "publication_year": 2018, "primary_topic": {"subfield": {"id": "https://openalex.org/subfields/2002"}}},
        {"id": "W2", "publication_year": 1990, "primary_topic": {"subfield": {"id": "https://openalex.org/subfields/2002"}}},  # outside the year window
        {"id": "W3", "publication_year": 2018, "primary_topic": {"subfield": {"id": "https://openalex.org/subfields/2003"}}},  # Finance excluded
    ]
    shard = _make_shard(tmp_path, "part_0000.gz", recs)

    def keep(rec):
        sf = (rec.get("primary_topic") or {}).get("subfield") or {}
        sid = (sf.get("id") or "").rsplit("/", 1)[-1]
        yr = rec.get("publication_year")
        return sid == "2002" and yr is not None and 2000 <= yr <= 2025

    stats = gz_filter.WorkFilterStats()
    kept = list(gz_filter.stream_filter_works([shard], keep_pred=keep, stats=stats))
    assert [r["id"] for _sid, r in kept] == ["W1"]
    assert stats.seen == 3
    assert stats.kept == 1
    assert stats.skipped == 2


def test_stream_filter_yields_shard_id_with_gz_suffix(tmp_path):
    shard = _make_shard(tmp_path, "part_0007.gz", [{"id": "W9", "publication_year": 2010}])
    stats = gz_filter.WorkFilterStats()
    out = list(gz_filter.stream_filter_works([shard], keep_pred=lambda r: True, stats=stats))
    assert len(out) == 1
    shard_id, rec = out[0]
    assert shard_id == "part_0007.gz"  # includes .gz; not the full path, not stripped of the suffix


def test_stream_filter_per_shard_counts(tmp_path):
    s1 = _make_shard(tmp_path, "part_0000.gz", [{"id": "A"}, {"id": "B"}])
    s2 = _make_shard(tmp_path, "part_0001.gz", [{"id": "C"}])
    stats = gz_filter.WorkFilterStats()
    list(gz_filter.stream_filter_works([s1, s2], keep_pred=lambda r: r["id"] != "B", stats=stats))
    assert stats.seen == 3
    assert stats.kept == 2
    assert stats.per_shard["part_0000.gz"]["seen"] == 2
    assert stats.per_shard["part_0000.gz"]["kept"] == 1
    assert stats.per_shard["part_0001.gz"]["kept"] == 1


# ===========================================================================
# Old-bug regression: truncated .gz -> CorruptShardError -> exit(17), never silently treated as empty
# ===========================================================================
def test_stream_filter_corrupt_shard_raises_not_silent_empty(tmp_path):
    # Write a real .gz and truncate its tail -> snapshot_reader fails mid-decompression.
    good = tmp_path / "part_bad.gz"
    _write_gz(good, [{"id": f"W{i}", "publication_year": 2010} for i in range(200)])
    raw = good.read_bytes()
    good.write_bytes(raw[: len(raw) // 2])  # cut in half = truncated

    stats = gz_filter.WorkFilterStats()
    with pytest.raises(CorruptShardError) as exc:
        list(gz_filter.stream_filter_works([str(good)], keep_pred=lambda r: True, stats=stats))
    # Corruption must never degrade to empty: exit_code = CORRUPT_SHARD(17).
    assert exc.value.exit_code == CORRUPT_SHARD == 17


# ===========================================================================
# DUCKDB_BYPASS disabled: flag is False + any call raises
# ===========================================================================
def test_duckdb_bypass_disabled_flag():
    assert gz_filter.DUCKDB_BYPASS_ENABLED is False


def test_read_ndjson_gz_duckdb_raises_runtime_error():
    with pytest.raises(RuntimeError):
        gz_filter.read_ndjson_gz_duckdb("anything.gz")
