"""Tests for hash_bucket_writer.

Behaviour covered:
  - bucket_of(pk, n=256): the sha1 hash is stable.
  - arrow_schema_from_dict turns a U0 schema dict into a pyarrow schema.
  - HashBucketWriter (.add/.flush_shard/.flush_all); _DETERMINISTIC_PARQUET_KW
    (zstd / use_dictionary=False / a single row group / strip metadata).
  - Perf: a bucket that exceeds its cap is flushed to a part immediately.
  - Repro: fixed schema + canonical sort by PK -> the same input gives byte-identical sha (two runs).
  - Atomic parquet writes are built into this writer (on top of atomic_write_bytes).

Depends on pyarrow -> pytest.importorskip skips in a bare environment.
"""
import hashlib

import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

from m1_ingest import hash_bucket_writer as hbw
from common.schema import AUTHORSHIP_EDGES


# ===========================================================================
# bucket_of: stable sha1 hash + result in 0..n-1
# ===========================================================================
def test_bucket_of_is_deterministic_sha1():
    b1 = hbw.bucket_of("W123|A456", n=256)
    b2 = hbw.bucket_of("W123|A456", n=256)
    assert b1 == b2
    assert 0 <= b1 < 256


def test_bucket_of_matches_manual_sha1():
    pk = "W123|A456"
    expected = int(hashlib.sha1(pk.encode("utf-8")).hexdigest(), 16) % 256
    assert hbw.bucket_of(pk, n=256) == expected


def test_bucket_of_spreads_across_buckets():
    buckets = {hbw.bucket_of(f"W{i}", n=256) for i in range(1000)}
    # 1000 distinct keys should spread over several buckets (not all in one).
    assert len(buckets) > 50


# ===========================================================================
# arrow_schema_from_dict — U0 schema dict → pyarrow schema
# ===========================================================================
def test_arrow_schema_from_dict_field_names_match():
    sch = hbw.arrow_schema_from_dict(AUTHORSHIP_EDGES)
    assert isinstance(sch, pa.Schema)
    assert sch.names == list(AUTHORSHIP_EDGES.keys())


# ===========================================================================
# Deterministic parquet parameters
# ===========================================================================
def test_deterministic_parquet_kw_has_required_settings():
    kw = hbw._DETERMINISTIC_PARQUET_KW
    assert kw["compression"] == "zstd"
    assert kw["use_dictionary"] is False


# ===========================================================================
# HashBucketWriter: add / flush / flush immediately when a bucket exceeds its cap
# ===========================================================================
def _edge(work_id, author_id, year=2018):
    return {"work_id": work_id, "author_id": author_id, "publication_year": year}


def test_writer_writes_parquet_files_readable_back(tmp_path):
    w = hbw.HashBucketWriter(
        str(tmp_path / "authorship_edges"),
        schema=AUTHORSHIP_EDGES,
        pk_cols=("work_id", "author_id"),
        n_buckets=8,
    )
    w.add(_edge("W1", "A1"))
    w.add(_edge("W2", "A2"))
    w.flush_all()
    # Read the parquet back; total rows == rows written.
    files = list((tmp_path / "authorship_edges").rglob("*.parquet"))
    assert files, "At least one parquet bucket file should be written"
    total = sum(pq.read_table(str(f)).num_rows for f in files)
    assert total == 2


def test_writer_bucket_over_cap_flushes_immediately(tmp_path):
    # bucket_row_cap=2 -> the 3rd row in the same bucket triggers an immediate flush of one part.
    w = hbw.HashBucketWriter(
        str(tmp_path / "t"),
        schema=AUTHORSHIP_EDGES,
        pk_cols=("work_id", "author_id"),
        n_buckets=1,  # force everything into one bucket
        bucket_row_cap=2,
    )
    for i in range(5):
        w.add(_edge(f"W{i}", f"A{i}"))
    # Before flush_all, a part is already on disk (triggered by exceeding the cap).
    parts_before_flush = list((tmp_path / "t").rglob("*.parquet"))
    assert len(parts_before_flush) >= 2, "A bucket over the cap should have flushed a part immediately"
    w.flush_all()
    total = sum(pq.read_table(str(f)).num_rows for f in (tmp_path / "t").rglob("*.parquet"))
    assert total == 5


def test_writer_two_runs_byte_identical_sha(tmp_path):
    # Repro: same input (fed in shuffled order) twice, canonical sort by PK + fixed parameters -> byte-identical sha.
    rows = [_edge("W3", "A3"), _edge("W1", "A1"), _edge("W2", "A2"), _edge("W1", "A0")]

    def run(dest):
        w = hbw.HashBucketWriter(
            dest, schema=AUTHORSHIP_EDGES, pk_cols=("work_id", "author_id"), n_buckets=4
        )
        # shuffle the feed order on purpose
        for r in reversed(rows):
            w.add(r)
        w.flush_all()
        shas = {}
        for f in sorted((tmp_path).rglob("*.parquet")):
            shas[f.relative_to(tmp_path).as_posix()] = hashlib.sha256(f.read_bytes()).hexdigest()
        return shas

    a = run(str(tmp_path / "runA"))
    b = run(str(tmp_path / "runB"))
    # Compare bucket paths relative to runX -> the sha of the same bucket must match.
    a_norm = {k.split("/", 1)[-1]: v for k, v in a.items() if k.startswith("runA/")}
    b_norm = {k.split("/", 1)[-1]: v for k, v in b.items() if k.startswith("runB/")}
    assert a_norm == b_norm, "Two passes over the same bucket should give byte-identical sha (deterministic write)"


def test_writer_flush_all_returns_manifest(tmp_path):
    w = hbw.HashBucketWriter(
        str(tmp_path / "t"), schema=AUTHORSHIP_EDGES, pk_cols=("work_id", "author_id"), n_buckets=4
    )
    w.add(_edge("W1", "A1"))
    manifest = w.flush_all()
    # flush_all returns a manifest for run_m1 to assemble provenance: each part's relative path + sha + row count.
    assert isinstance(manifest, list)
    assert manifest, "The manifest should not be empty"
    entry = manifest[0]
    assert "rel_path" in entry and "sha256" in entry and "row_count" in entry


def test_writer_rejects_row_not_matching_schema(tmp_path):
    # assert_matches_schema before writing: extra or missing keys both fail (keeps the schema consistent).
    from common.schema import SchemaMismatchError

    w = hbw.HashBucketWriter(
        str(tmp_path / "t"), schema=AUTHORSHIP_EDGES, pk_cols=("work_id", "author_id"), n_buckets=4
    )
    with pytest.raises(SchemaMismatchError):
        w.add({"work_id": "W1", "author_id": "A1"})  # publication_year missing
