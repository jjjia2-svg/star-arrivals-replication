"""M1-T2 gz_filter.py - streaming filter of snapshot works (never decompress a whole disk).

What it does:
  - stream_filter_works reads line by line through U0 common.snapshot_reader.iter_jsonl_gz_shards
    (bounded memory, never untar / load everything) and filters with keep_pred; yields (shard_id, record).
  - shard_id = file basename including .gz (guaranteed by snapshot_reader).
  - WorkFilterStats accumulates seen/kept/skipped + per_shard detail.
  - Regression test of an old bug (root cause of the Sydney 27k incident): a truncated/corrupt .gz -> CorruptShardError(exit_code=17),
    never silently degrades into empty data (the exception propagates, it is not swallowed).

DuckDB bypass disabled (DUCKDB_BYPASS_ENABLED=False): calling read_ndjson_gz_duckdb raises
  RuntimeError (the duckdb-reads-gz bypass was abandoned; plain-Python gzip is the only path).

Neutral on identification choices: keep_pred is injected by the caller (the economics subfield + year-window logic lives in run_m1/passes);
  this module only does "stream + filter + count + corruption is never silent" and embeds no identification thresholds.

Official usage: OpenAlex snapshot (gzip JSONL, one entity per line; enumerate shards from the manifest, do not glob yourself).
"""
from __future__ import annotations

from typing import Callable, Iterator

from common.snapshot_reader import iter_jsonl_gz_shards

# DuckDB reading of gz = abandoned (plain-Python gzip streaming is the only path). The flag is pinned to False; calling it fails.
DUCKDB_BYPASS_ENABLED: bool = False


class WorkFilterStats:
    """Filter counter: global seen/kept/skipped + per_shard detail (feeds the reconciliation arm)."""

    def __init__(self):
        self.seen: int = 0
        self.kept: int = 0
        self.skipped: int = 0
        # per_shard[shard_id] = {"seen": int, "kept": int, "skipped": int}
        self.per_shard: dict[str, dict[str, int]] = {}

    def _shard(self, shard_id: str) -> dict[str, int]:
        return self.per_shard.setdefault(
            shard_id, {"seen": 0, "kept": 0, "skipped": 0}
        )

    def record(self, shard_id: str, kept: bool) -> None:
        self.seen += 1
        ps = self._shard(shard_id)
        ps["seen"] += 1
        if kept:
            self.kept += 1
            ps["kept"] += 1
        else:
            self.skipped += 1
            ps["skipped"] += 1


def stream_filter_works(
    shard_paths,
    *,
    keep_pred: Callable[[dict], bool],
    stats: WorkFilterStats,
) -> Iterator[tuple[str, dict]]:
    """Filter snapshot works shards line by line as a stream, yielding the kept (shard_id, record).

    - goes through iter_jsonl_gz_shards: a generator, line by line, never decompresses a whole disk / materialises a list;
    - keep_pred(rec) True -> yield + count in kept; False -> count in skipped only;
    - a truncated/corrupt .gz -> CorruptShardError is raised by snapshot_reader; this function neither catches nor swallows it
      (corruption never degrades into empty data).
    """
    for shard_id, record in iter_jsonl_gz_shards(shard_paths):
        keep = keep_pred(record)
        stats.record(shard_id, keep)
        if keep:
            yield (shard_id, record)


def read_ndjson_gz_duckdb(path: str):
    """Disabled bypass: reading gz via DuckDB is no longer supported; calling it raises (prevents a silent whole-disk decompress)."""
    raise RuntimeError(
        "the read_ndjson_gz_duckdb bypass is disabled (DUCKDB_BYPASS_ENABLED=False); "
        "the only path = common.snapshot_reader pure-Python gzip streaming read (rule §H)."
    )
