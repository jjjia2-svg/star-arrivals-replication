"""U1 deterministic write parameters use store_schema=False. Guard: the footer has no ARROW:schema.

Why:
  pyarrow's default store_schema=True embeds the Arrow schema as flatbuffers in the "ARROW:schema" KV
  metadata of the parquet footer. Those bytes are known to differ across platforms (Arrow issues
  #39399/#40202, macOS vs Linux), and they are the only known unavoidable source of difference in a
  byte-for-byte comparison of a local Mac run against an AWS EC2 run. Removing them removes a known trap;
  the rest (zstd, same version, single thread) is deterministic in theory and is still backed by the
  50-shard measured reconcile gate.

Guard: for parquet written through _DETERMINISTIC_PARQUET_KW, the KV metadata must not contain ARROW:schema.
(The independent copy of the write parameters in u0p5 is deliberately left unchanged: tables A/B were
already written with the old bytes, and changing it would churn existing products. Aligning it is left for
the next roster rebuild.)
"""
import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

from m1_ingest._writer_util import _DETERMINISTIC_PARQUET_KW, _deterministic_write


def _kv_meta(path) -> dict:
    md = pq.ParquetFile(str(path)).metadata.metadata
    return dict(md or {})


def test_deterministic_kw_pins_store_schema_false():
    assert _DETERMINISTIC_PARQUET_KW.get("store_schema") is False, (
        "S2: deterministic-write callers must explicitly pass store_schema=False (Arrow #39399 cross-platform byte difference)")


def test_deterministic_write_has_no_arrow_schema_kv(tmp_path):
    t = pa.table({"a": ["x", "y"], "b": ["1", "2"]})
    target = tmp_path / "t.parquet"
    _deterministic_write(t, target)
    assert b"ARROW:schema" not in _kv_meta(target), (
        "A footer carrying ARROW:schema = cross-platform reconciliation will fail (Arrow #39399)")


def test_deterministic_write_roundtrip_content_unchanged(tmp_path):
    """Dropping ARROW:schema changes only the footer metadata; the content, column order and types read back are unchanged."""
    t = pa.table({"a": ["x", "y"], "b": ["1", "2"]})
    target = tmp_path / "t.parquet"
    _deterministic_write(t, target)
    back = pq.read_table(str(target))
    assert back.column_names == ["a", "b"]
    assert back.column("a").to_pylist() == ["x", "y"]
    assert back.column("b").to_pylist() == ["1", "2"]
