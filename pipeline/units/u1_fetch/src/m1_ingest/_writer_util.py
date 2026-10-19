"""M1 internal helpers: bare-id normalisation + deterministic parquet writing (shared by the five new table writers).

Why this module is self-contained instead of depending on schema_map / hash_bucket_writer:
  - these two modules are built separately and may not exist yet at this stage;
  - the five table writers must be testable on their own (small fixtures), so they must not import symbols that may be missing;
  - once hash_bucket_writer.HashBucketWriter is available, run_m1 can use it to write bucketed tables;
    this module only guarantees the smallest testable surface: a single deterministic parquet file + a schema guard.

Determinism (Repro): before writing, rows are canonical-sorted by the PK columns and written with fixed pyarrow
  parameters (zstd / no dictionary encoding / one row group / no pandas metadata), so identical content gives
  byte-identical sha.
Neutral on identification choices: pure data shape, no identification thresholds, no network.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from common.schema import assert_matches_schema

# OpenAlex entity id URL prefix. bare() strips it to get the W.../A.../I... id.
OPENALEX_URL_PREFIX = "https://openalex.org/"


def bare(oid):
    """OpenAlex id URL string -> bare id (strips the "https://openalex.org/" prefix).

    - None / "" -> None (no raise; the caller decides how to handle a missing value);
    - already bare (no prefix) -> returned unchanged (idempotent);
    - the prefix is stripped case-insensitively (the official prefix is always the same, but be tolerant).
    """
    if oid is None:
        return None
    s = str(oid)
    if s == "":
        return None
    low = s.lower()
    if low.startswith(OPENALEX_URL_PREFIX):
        return s[len(OPENALEX_URL_PREFIX):]
    return s


# Deterministic pyarrow write parameters - the single authoritative constant (hash_bucket_writer imports it from here, no second copy):
#   compression=zstd fixed; use_dictionary=False disables dictionary encoding (avoids dictionary-order drift);
#   write_statistics=False writes no statistics -> byte-stable;
#   store_schema=False: do not put the ARROW:schema flatbuffer into the footer -
#     those bytes differ across platforms (Arrow issues #39399/#40202, macOS vs Linux) and are the
#     only known unavoidable source of byte differences between a local Mac run and an AWS EC2 run; reads use the native parquet schema.
#   Note: row_group_size is filled in at write time from the table's actual row count (single row group), so it is not in this constant dict.
#   Note: u0p5 keeps its own independent copy with the same settings and deliberately does NOT sync store_schema - tables A/B
#       were already written with the old bytes and changing it would churn existing outputs; alignment is left for the next roster rebuild.
_DETERMINISTIC_PARQUET_KW: dict = {
    "compression": "zstd",
    "use_dictionary": False,
    "write_statistics": False,
    "store_schema": False,
}


def _deterministic_write(table, target: Path) -> None:
    """Write a single deterministic parquet file (one row group; large tables go through HashBucketWriter buckets)."""
    import pyarrow.parquet as pq

    pq.write_table(
        table,
        str(target),
        row_group_size=max(1, table.num_rows),  # One row group: few rows, written in one go
        **_DETERMINISTIC_PARQUET_KW,
    )


def write_rows_parquet(
    rows: Iterable[dict],
    target,
    *,
    schema: dict,
    pk_cols: Sequence[str],
    label: str,
) -> None:
    """Write rows to a deterministic single-file parquet, checking every row against the schema first.

    Steps:
      1. materialise rows into a list;
      2. per row, assert_matches_schema(row.keys(), schema, label=label) (extra or missing keys raise);
      3. canonical-sort by pk_cols (None last, stable);
      4. column order = schema key order (fixed, independent of dict insertion order);
      5. write with _deterministic_write.

    Empty rows: still writes a 0-row parquet with the correct column order (downstream reconcile does not crash on a missing file).
    """
    import pyarrow as pa

    materialized = [dict(r) for r in rows]
    for r in materialized:
        assert_matches_schema(r.keys(), schema, label=label)

    col_order = list(schema.keys())

    def _sort_key(r):
        # None is sorted as (1, "") after the non-None (0, value) of the same column, which keeps the order deterministic.
        return tuple((r[c] is None, "" if r[c] is None else r[c]) for c in pk_cols)

    materialized.sort(key=_sort_key)

    columns = {c: [r[c] for r in materialized] for c in col_order}
    table = pa.table({c: columns[c] for c in col_order})
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    _deterministic_write(table, target)
