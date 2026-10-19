"""TDD red tests for U0 common/derived_table.py: reading a derived narrow table (single-file data.parquet or bucketed bucket=*/part-*).

Output-structure seam: the U1 full run writes bucketed <table>/bucket=NNN/part-*.parquet; slice/sample/fixture and
U2 outputs write a single <table>/data.parquet. Downstream (U2/U3) must read both layouts and must NEVER read data_SAMPLE.parquet.
This module is the single source of truth shared by U2/U3 (the layout logic exists once, so the two sides cannot drift apart and one read wrongly).

Layout contract:
  - <dir>/data.parquet exists -> read only it (slice/sample/fixture/U2 person_map single file).
  - otherwise <dir>/bucket=*/part-*.parquet -> read all bucket parts (U1 full bucketed output).
  - neither -> empty / absent.
  - data_SAMPLE.parquet is never read (a single file is recognised only as data.parquet; bucket paths naturally do not contain it).

No identification rule involved: it only reads parquet rows, with no threshold and no network.
"""
import pathlib
import sys

import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common.derived_table import (  # noqa: E402
    read_derived_table,
    read_derived_arrow,
    derived_table_present,
    derived_table_column_names,
    derived_table_content_hash,
    table_part_paths,
)


def _write(path, rows, cols):
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table({c: [r[c] for r in rows] for c in cols})
    pq.write_table(table, str(path))


def test_reads_single_data_parquet(tmp_path):
    d = tmp_path / "works"
    _write(d / "data.parquet", [{"id": "W1", "val": 1}, {"id": "W2", "val": 2}], ["id", "val"])
    rows = read_derived_table(d)
    assert sorted(r["id"] for r in rows) == ["W1", "W2"]


def test_reads_bucketed_parts_when_no_data_parquet(tmp_path):
    d = tmp_path / "works"
    _write(d / "bucket=000" / "part-00000.parquet", [{"id": "W1", "val": 1}], ["id", "val"])
    _write(d / "bucket=001" / "part-00000.parquet", [{"id": "W2", "val": 2}], ["id", "val"])
    rows = read_derived_table(d)
    assert sorted(r["id"] for r in rows) == ["W1", "W2"], "bucketed layout must read all bucket parts"


def test_reads_multiple_parts_in_one_bucket(tmp_path):
    """A bucket may hold several parts (HashBucketWriter flushes when a bucket is full) -> read them all."""
    d = tmp_path / "works"
    _write(d / "bucket=000" / "part-00000.parquet", [{"id": "W1", "val": 1}], ["id", "val"])
    _write(d / "bucket=000" / "part-00001.parquet", [{"id": "W2", "val": 2}], ["id", "val"])
    rows = read_derived_table(d)
    assert sorted(r["id"] for r in rows) == ["W1", "W2"]


def test_prefers_data_parquet_and_never_reads_sample(tmp_path):
    d = tmp_path / "works"
    _write(d / "data.parquet", [{"id": "REAL", "val": 1}], ["id", "val"])
    _write(d / "data_SAMPLE.parquet", [{"id": "SAMPLE", "val": 9}], ["id", "val"])
    rows = read_derived_table(d)
    assert {r["id"] for r in rows} == {"REAL"}, "when data.parquet exists read only it; never read data_SAMPLE.parquet"


def test_bucketed_never_reads_top_level_sample(tmp_path):
    d = tmp_path / "works"
    _write(d / "bucket=000" / "part-00000.parquet", [{"id": "REAL", "val": 1}], ["id", "val"])
    _write(d / "data_SAMPLE.parquet", [{"id": "SAMPLE", "val": 9}], ["id", "val"])
    rows = read_derived_table(d)
    assert {r["id"] for r in rows} == {"REAL"}, "bucketed layout never reads the top-level data_SAMPLE.parquet"


def test_absent_table_empty_and_not_present(tmp_path):
    d = tmp_path / "missing"
    assert read_derived_table(d) == []
    assert derived_table_present(d) is False


def test_present_true_for_both_layouts(tmp_path):
    d1 = tmp_path / "a"
    _write(d1 / "data.parquet", [{"id": "X", "val": 1}], ["id", "val"])
    d2 = tmp_path / "b"
    _write(d2 / "bucket=000" / "part-00000.parquet", [{"id": "Y", "val": 1}], ["id", "val"])
    assert derived_table_present(d1) and derived_table_present(d2)


def test_column_subset(tmp_path):
    d = tmp_path / "works"
    _write(d / "bucket=000" / "part-00000.parquet",
           [{"id": "W1", "val": 1, "extra": "z"}], ["id", "val", "extra"])
    rows = read_derived_table(d, columns=["id"])
    assert rows == [{"id": "W1"}]


def test_column_names_from_first_part(tmp_path):
    d = tmp_path / "works"
    _write(d / "bucket=000" / "part-00000.parquet", [{"id": "W1", "val": 1}], ["id", "val"])
    assert derived_table_column_names(d) == ["id", "val"]


def test_part_paths_data_parquet_only(tmp_path):
    d = tmp_path / "works"
    _write(d / "data.parquet", [{"id": "W1", "val": 1}], ["id", "val"])
    _write(d / "data_SAMPLE.parquet", [{"id": "S", "val": 9}], ["id", "val"])
    paths = [p.name for p in table_part_paths(d)]
    assert paths == ["data.parquet"], "only data.parquet counts, SAMPLE excluded"


# --- read_derived_arrow: returns a pyarrow.Table (for duckdb register, e.g. U3 _load_person_works) ---
def test_read_arrow_concats_buckets_to_table(tmp_path):
    d = tmp_path / "works"
    _write(d / "bucket=000" / "part-00000.parquet", [{"id": "W1", "val": 1}], ["id", "val"])
    _write(d / "bucket=001" / "part-00000.parquet", [{"id": "W2", "val": 2}], ["id", "val"])
    t = read_derived_arrow(d)
    assert t.num_rows == 2
    assert set(t.column("id").to_pylist()) == {"W1", "W2"}


def test_read_arrow_single_file(tmp_path):
    d = tmp_path / "works"
    _write(d / "data.parquet", [{"id": "W1", "val": 1}], ["id", "val"])
    t = read_derived_arrow(d)
    assert t.column("id").to_pylist() == ["W1"]


# --- derived_table_content_hash: the resume anchor; for a single file it must equal the plain sha256(file) (U3's existing manifest is untouched) ---
def test_content_hash_single_file_equals_plain_file_sha(tmp_path):
    import hashlib
    d = tmp_path / "works"
    _write(d / "data.parquet", [{"id": "W1", "val": 1}], ["id", "val"])
    raw = (d / "data.parquet").read_bytes()
    assert derived_table_content_hash(d) == hashlib.sha256(raw).hexdigest(), (
        "single-file content hash must equal plain sha256(data.parquet) — consistent with the old U3 sha256_file path, existing manifests unchanged"
    )


def test_content_hash_bucketed_deterministic_and_sensitive(tmp_path):
    d = tmp_path / "works"
    _write(d / "bucket=000" / "part-00000.parquet", [{"id": "W1", "val": 1}], ["id", "val"])
    h1 = derived_table_content_hash(d)
    assert h1 == derived_table_content_hash(d), "bucketed content hash must be deterministic (equal on two runs)"
    _write(d / "bucket=001" / "part-00000.parquet", [{"id": "W2", "val": 2}], ["id", "val"])
    assert derived_table_content_hash(d) != h1, "content changed (bucket added) → hash must change (so resume rebuilds)"


# ---------------------------------------------------------------------------
# A new hazard outside the change under test: for a single part-file path, pyarrow 24 infers a hive partition
# and injects a phantom `bucket` dictionary column from the bucket=NNN directory name (a full-column read
# with columns=None is hit; U3 _load_person_works reads all columns).
# Guard: the columns read back == the file's real columns, never `bucket`.
# ---------------------------------------------------------------------------
def test_bucketed_read_has_no_phantom_bucket_column(tmp_path):
    d = tmp_path / "works_affil"
    (d / "bucket=017").mkdir(parents=True)
    _write(d / "bucket=017" / "part-00000.parquet", [{"a": "x", "b": "1"}], ["a", "b"])
    t = read_derived_arrow(d)
    assert t.column_names == ["a", "b"], (
        f"read-back columns {t.column_names} — a phantom column inferred from the path appeared (pyarrow hive partitioning)")
    rows = read_derived_table(d)
    assert rows == [{"a": "x", "b": "1"}]


def test_bucketed_multi_part_read_no_phantom_column_and_concat_ok(tmp_path):
    d = tmp_path / "edges"
    (d / "bucket=000").mkdir(parents=True)
    (d / "bucket=001").mkdir(parents=True)
    _write(d / "bucket=000" / "part-00000.parquet", [{"a": "x", "b": "1"}], ["a", "b"])
    _write(d / "bucket=001" / "part-00000.parquet", [{"a": "y", "b": "2"}], ["a", "b"])
    t = read_derived_arrow(d)
    assert t.column_names == ["a", "b"]
    assert t.num_rows == 2
