"""M1-T3 hash_bucket_writer.py - deterministic hash-bucketed parquet writer (bucketing for large tables).

What it does:
  - assigns rows of a narrow table to n_buckets buckets by the sha1 hash of the PK; as soon as a bucket holds bucket_row_cap rows
    a part is flushed (bounded memory, the whole table is never held); within a bucket, before writing, rows are canonical-sorted by PK
    and written with fixed pyarrow parameters -> the same input gives byte-identical sha (Repro).
  - atomic parquet writes: write .partial first, then os.replace (has its own atomic-write base, does not depend on a non-existent atomic_write_parquet).
  - flush_all() returns a manifest (rel_path + sha256 + row_count per part) for run_m1 to assemble provenance.

Deterministic parameters (_DETERMINISTIC_PARQUET_KW):
  - compression=zstd fixed;
  - use_dictionary=False (no dictionary encoding, avoids dictionary-order drift);
  - a single row group (one write per bucket part);
  - no statistics / pandas metadata written -> byte-stable.

Neutral on identification choices: pure data-shape writing, no identification thresholds, no network.
Schema check: every row goes through common.schema.assert_matches_schema before add (extra or missing keys raise).
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable, Sequence

from common.schema import assert_matches_schema
from common.atomic_io import atomic_write_bytes

# pyarrow deterministic write parameters - the single authoritative constant is in _writer_util, re-exported here for reuse (DRY, no second copy).
# Note: row_group_size is filled in at write time from the bucket's actual row count (single row group), so it is not in this constant dict.
from m1_ingest._writer_util import _DETERMINISTIC_PARQUET_KW  # noqa: F401  (re-export)


def bucket_of(pk: str, n: int = 256) -> int:
    """PK string -> bucket number (sha1 hash mod n; stable and identical across processes).

    Uses sha1 (deterministic, unlike the randomly salted built-in hash) -> hex -> int -> mod n.
    """
    h = hashlib.sha1(pk.encode("utf-8")).hexdigest()
    return int(h, 16) % n


def arrow_schema_from_dict(schema: dict):
    """U0 schema dict (column name -> type string) -> pyarrow.Schema (column order = dict key order).

    Types follow the schema type strings (str/int16/int64/float32/bool/category/list<...>);
    category/str -> pa.string; list<str>/list<dict>/list<int32> -> pa.list_(corresponding type).
    The actual columns are inferred by pyarrow from the Python values; this schema mainly pins column order + names.
    """
    import pyarrow as pa

    type_map = {
        "str": pa.string(),
        "category": pa.string(),
        "int8": pa.int8(),
        "int16": pa.int16(),
        "int32": pa.int32(),
        "int64": pa.int64(),
        "float32": pa.float32(),
        "float64": pa.float64(),
        "bool": pa.bool_(),
        "list<str>": pa.list_(pa.string()),
        "list<int32>": pa.list_(pa.int32()),
        # list<dict> = variable structure (associated_institutions); a string-of-json does not work; leave it to pyarrow to infer.
    }
    fields = []
    for name, tstr in schema.items():
        fields.append(pa.field(name, type_map.get(tstr, pa.string())))
    return pa.schema(fields)


class HashBucketWriter:
    """Hash-bucketed parquet writer (deterministic + flush as soon as a bucket is full + manifest).

    Usage:
        w = HashBucketWriter(root, schema=WORKS_AFFIL, pk_cols=("work_id","author_id"))
        w.add(row); ...; manifest = w.flush_all()

    Layout: <root>/bucket=<bbb>/part-<seq>.parquet (bbb zero-padded to 3 digits, seq increasing within a bucket).
    """

    def __init__(
        self,
        root: str,
        *,
        schema: dict,
        pk_cols: Sequence[str],
        n_buckets: int = 256,
        bucket_row_cap: int = 200_000,
    ):
        self.root = Path(root)
        self.schema = schema
        self.pk_cols = tuple(pk_cols)
        self.n_buckets = n_buckets
        self.bucket_row_cap = bucket_row_cap
        self.col_order = list(schema.keys())
        # Per-bucket row buffer + the number of parts already flushed for that bucket (used to increment part file names).
        self._buffers: dict[int, list[dict]] = {}
        self._part_seq: dict[int, int] = {}
        # Accumulated manifest entries (rel_path/sha256/row_count).
        self._manifest: list[dict] = []

    def _pk_str(self, row: dict) -> str:
        # PK columns joined into a stable string (None -> empty-string placeholder; separated by \x1f so values cannot bleed into each other).
        return "\x1f".join("" if row[c] is None else str(row[c]) for c in self.pk_cols)

    def add(self, row: dict) -> None:
        """Add one row: check the schema first, then hash the PK into a bucket; flush a part as soon as the bucket is full."""
        assert_matches_schema(row.keys(), self.schema, label=self._label())
        b = bucket_of(self._pk_str(row), n=self.n_buckets)
        buf = self._buffers.setdefault(b, [])
        buf.append(dict(row))
        if len(buf) >= self.bucket_row_cap:
            self.flush_shard(b)

    def _label(self) -> str:
        return self.root.name or "TABLE"

    def _sort_key(self, row: dict):
        # canonical-sort by PK: None last (1,""), non-None (0, value).
        return tuple(
            (row[c] is None, "" if row[c] is None else row[c]) for c in self.pk_cols
        )

    def flush_shard(self, bucket: int) -> None:
        """Write a bucket's current buffer as one deterministic parquet part (atomic write) and clear the buffer."""
        buf = self._buffers.get(bucket)
        if not buf:
            return
        import pyarrow as pa
        import pyarrow.parquet as pq
        import io

        rows = sorted(buf, key=self._sort_key)  # Canonical-sort within the bucket (byte-level determinism)
        columns = {c: [r[c] for r in rows] for c in self.col_order}
        table = pa.table({c: columns[c] for c in self.col_order})

        seq = self._part_seq.get(bucket, 0)
        rel = Path(f"bucket={bucket:03d}") / f"part-{seq:05d}.parquet"
        target = self.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)

        # Serialise to an in-memory buffer (single row group), then write atomically via atomic_write_bytes.
        sink = io.BytesIO()
        pq.write_table(
            table,
            sink,
            row_group_size=max(1, table.num_rows),
            **_DETERMINISTIC_PARQUET_KW,
        )
        blob = sink.getvalue()
        atomic_write_bytes(target, blob)

        self._manifest.append(
            {
                "rel_path": rel.as_posix(),
                "sha256": hashlib.sha256(blob).hexdigest(),
                "row_count": table.num_rows,
            }
        )
        self._part_seq[bucket] = seq + 1
        self._buffers[bucket] = []

    def flush_all(self) -> list[dict]:
        """Flush the remaining buffer of all buckets and return the manifest (sorted by rel_path, deterministic)."""
        for b in sorted(self._buffers.keys()):
            self.flush_shard(b)
        self._manifest.sort(key=lambda e: e["rel_path"])
        return list(self._manifest)
