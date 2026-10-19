"""common/derived_table.py: read derived narrow tables (a single-file data.parquet or bucketed bucket=*/part-*).

Item 2 (output-layout seam, single source of truth): the U1 full run (stream_build) writes bucketed
<table>/bucket=NNN/part-*.parquet; slice/sample/fixture and the U2 person_map write a single <table>/data.parquet.
Downstream (U2/U3) reads through this module; both layouts are transparent, and data_SAMPLE.parquet is NEVER read.
The layout logic lives in this one place, so U2/U3 cannot each keep a copy that drifts and reads the wrong thing.

Layout contract (table_part_paths):
  1. <dir>/data.parquet exists -> return only it (the single-file convention of slice/sample/fixture/U2 output).
  2. Otherwise <dir>/bucket=*/part-*.parquet (sorted) -> the U1 full bucketed output (several buckets, several parts per bucket).
  3. Neither -> [].
  - data_SAMPLE.parquet is never selected (the single-file branch accepts only the exact name data.parquet; the bucket glob cannot match it).

Identification-neutral: only reads parquet rows/column names; no identification thresholds, no network. Reading follows the existing U2/U3 approach (pyarrow -> list[dict]).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence


def table_part_paths(table_dir) -> list[Path]:
    """Resolve the physical part paths of a derived table (per the layout contract; see the module docstring).

    Single file first (data.parquet) -> otherwise bucketed (bucket=*/part-*.parquet, sorted so deterministic) -> otherwise [].
    Never returns data_SAMPLE.parquet.
    """
    table_dir = Path(table_dir)
    single = table_dir / "data.parquet"
    if single.exists():
        return [single]
    return sorted(table_dir.glob("bucket=*/part-*.parquet"))


def derived_table_present(table_dir) -> bool:
    """Whether the table is present (a part exists in either the single-file or the bucketed layout)."""
    return bool(table_part_paths(table_dir))


def derived_table_column_names(table_dir) -> list[str]:
    """Read a table's column names (only the first part's schema, no data loaded); missing -> []."""
    import pyarrow.parquet as pq

    paths = table_part_paths(table_dir)
    if not paths:
        return []
    return list(pq.read_schema(str(paths[0])).names)


def read_derived_arrow(table_dir, columns: Optional[Sequence[str]] = None):
    """Read the given columns of a derived table (single-file or bucketed) -> pyarrow.Table (for cases that need Arrow, such as duckdb register,
    e.g. U3 _load_person_works). Missing -> raises FileNotFoundError (callers should guard first with derived_table_present).

    columns=None reads all columns. Bucketed multi-part tables are merged with concat_tables(promote_options='default')
    (a part whose column is entirely empty has a null type, which the other parts' types fill in, so concat does not fail on mismatched types).
    Row order: a bucketed merge does not guarantee a global order (downstream joins/aggregations do not depend on order; a downstream that needs order sorts itself).
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    paths = table_part_paths(table_dir)
    if not paths:
        raise FileNotFoundError(f"derived table missing (neither a single data.parquet nor bucketed bucket=*/part-*): {table_dir}")
    cols = list(columns) if columns is not None else None
    # Use ParquetFile(p).read() rather than pq.read_table(path): the latter goes through the dataset API, which
    #   infers hive partitioning from the bucket=NNN directory name -> injects a phantom `bucket` dictionary column
    #   (verified empirically with pyarrow 24; reading all columns with columns=None is affected).
    #   ParquetFile reads only the file's own schema, with no path inference.
    tables = [pq.ParquetFile(str(p)).read(columns=cols) for p in paths]
    if len(tables) == 1:
        return tables[0]
    return pa.concat_tables(tables, promote_options="default")


def read_derived_table(table_dir, columns: Optional[Sequence[str]] = None) -> list[dict]:
    """Read the given columns of a derived table (single-file or bucketed) -> list[dict]; missing -> []."""
    if not derived_table_present(table_dir):
        return []
    return read_derived_arrow(table_dir, columns).to_pylist()


def _sha256_file(path) -> str:
    """SHA256 hex of the file content (read in chunks, never loading the whole file into memory; same algorithm as common.manifest.sha256_file)."""
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def derived_table_content_hash(table_dir) -> str:
    """Content hash of a derived table (the resume anchor; both layouts transparent).

    - Single file (data.parquet): returns sha256(data.parquet) directly -> identical to the existing downstream
      sha256_file(data.parquet), so switching to this module leaves existing U3 manifest/resume behaviour unchanged.
    - Bucketed: feed rel_path + sha256 part by part (sorted by relative path) -> an aggregate hash (deterministic, independent of part order;
      if any part's content changes or a bucket is added/removed, the hash changes -> resume rebuilds correctly).
    Missing -> FileNotFoundError (callers should guard first).
    """
    import hashlib

    paths = table_part_paths(table_dir)
    if not paths:
        raise FileNotFoundError(f"derived table missing: {table_dir}")
    if len(paths) == 1 and paths[0].name == "data.parquet":
        return _sha256_file(paths[0])
    base = Path(table_dir)
    h = hashlib.sha256()
    for p in paths:  # table_part_paths is already sorted -> deterministic
        h.update(p.relative_to(base).as_posix().encode("utf-8"))
        h.update(_sha256_file(p).encode("utf-8"))
    return h.hexdigest()
