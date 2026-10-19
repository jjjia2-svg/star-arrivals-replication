"""M1 full-scale streaming orchestration, stream_build: no blow-up (streaming increments) +
efficient (parallel) + deterministic (canonical-sort within each bucket).

Why a separate module:
  The old path run_m1.run_slice_tables iterates seed_shards several times and appends all rows
  of the 10 tables to in-memory lists, then hands them to the writer in one go -> 510M works
  would have to stay in memory, about 3TB RAM = OOM. This module adds a separate entry point,
  run_m1_streaming(), which turns "collect a list, then bucket" into "as each work flows past,
  writer.add() puts its rows into the HashBucketWriter bucket of each table (a full bucket is
  flushed to disk)". The algorithm is still the seed snowball's two real passes over the data
  (pass-B needs the seed_authors that pass-A computes first; this is inherent, not a bug);
  only the full materialisation of rows is removed.

Three things (answer first):
  1. No blow-up: class A (the row lists of the 10 tables) is fully streamed, rows go straight
     into buckets and are not kept in memory; class B accumulators (first_pub/authors/fwci/cmap)
     are O(distinct keys), not O(rows), and are kept (the semantics need a full aggregation).
     Memory is bounded by "current bucket buffers x number of tables + accumulators + one work".
  2. Efficient: per-batch multiprocessing (spawn-safe). With n_workers>1, in the map phase each
     worker runs the streaming pass-B on its own batch into a local bucket directory and
     emits local accumulators; the reduce phase merges by (table, bucket), canonical-sorts once
     within each bucket and writes the final single part. With n_workers=1 it is serial
     streaming (the fallback path: no blow-up but single-threaded).
  3. Deterministic: the canonical-sort within a bucket happens only once (when the final writer
     flushes to disk) -> the bytes of a final bucket part depend only on "the set of rows that
     fall into the bucket" + "the canonical-sort order", and not at all on worker count, shard
     order or completion order.
     Accumulators use a deterministic reduce: fwci adds cell by cell, first_pub takes the
     per-author min (associative + commutative); the insertion order of authors/first_pub is
     reproduced under parallelism as (worker_index, local insertion order), which replays the
     serial global order -> byte-identical to serial.

Rule-neutral: this module only changes the on-disk shape, memory strategy and concurrency.
It never touches the seed-selection rule (passes red line #1, fold_to_canonical), the schema,
the identification placeholders (dose / FWCI window / age-bin / diff_tolerance all stay
explicitly passed / RedlineUnsigned), the reconcile formula or the exit codes. The
fwci/first_pub/authors aggregation semantics are unchanged.

Reuse (never rewrite):
  - run_m1's pure functions / orchestration pieces: _PositionalFirstPub / assert_canonical_space /
    reconcile_slice / emit_run_manifest / _emit_provenance_sidecars / _bucketed_table_specs /
    the equivalent _is_relevant test.
  - passes.{pass_a_seed_authors} (pass-A scans all seeds + piggybacks first_pub).
  - schema_map.flatten_work / abstract_reverse.flatten_work_text / institutions.flatten_institution
    / works_affil.iter_works_affil_rows + cmap folding / fwci_accumulator / canonical_id.
  - hash_bucket_writer.HashBucketWriter (the single source of truth for deterministic bucketed
    writing).
"""
from __future__ import annotations

import multiprocessing as mp
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from identity.constants import build_registry_by_id
from m1_ingest import passes as P
from m1_ingest import run_m1 as _RM
from m1_ingest import schema_map as SM
from m1_ingest._writer_util import bare
from m1_ingest.abstract_reverse import flatten_work_text
from m1_ingest.authors import AuthorTable
from m1_ingest.canonical_id import build_canonical_map, canonicalize, to_canonical_rows
from m1_ingest.first_pub import FirstPubAccumulator
from m1_ingest.fwci_accumulator import FwciPopAccumulator
from m1_ingest.hash_bucket_writer import HashBucketWriter
from m1_ingest.institutions import flatten_institution
from m1_ingest.works_affil import iter_works_affil_rows


# Test hook: force a canonical-space split (default False; only test_stream_build injects True).
# Must never affect the production path (always False there); it exists only so a red test can
# check that "the streaming guard fires".
_FORCE_CANONICAL_SPLIT_FOR_TEST = False


# ===========================================================================
# Pure functions: the field-mapping touchpoints for one work (extracted from run_m1's sink closures,
# behaviour identical).
#   These are pure maps of "which rows to produce for one work"; the streaming path calls them
#   directly at the routing point -> no intermediate list is collected.
# ===========================================================================
def _apply_affil_cmap(row: dict, author_cmap: Mapping[str, str], inst_cmap: Mapping[str, str]) -> dict:
    """Fold one row from iter_works_affil_rows to canonical through the cmap (equivalent to
    WorksAffilWriter.add).

    author_id / institution_id are looked up in the cmap and folded to the root; ids missing from
    the cmap stay as they are (no mapping, nothing invented); raw_affiliation_strings stays a
    list<str> as given (the key to disambiguation, never flattened).
    """
    aid = row.get("author_id")
    iid = row.get("institution_id")
    return {
        "work_id": row.get("work_id"),
        "author_id": (author_cmap.get(aid, aid) if aid is not None else None),
        "institution_id": (inst_cmap.get(iid, iid) if iid is not None else None),
        "raw_affiliation_strings": list(row.get("raw_affiliation_strings") or []),
    }


def _canon_edge(work_id, author_id, year, author_cmap_pair: Mapping[str, tuple]) -> dict:
    """Cache one authorship edge (author_id folded to canonical), equivalent to run_m1._edge_sink.

    author_cmap_pair = the {raw:(terminal,is_deleted)} built by build_canonical_map; canonicalize
    takes the root.
    """
    return {
        "work_id": work_id,
        "author_id": canonicalize(author_id, author_cmap_pair),
        "publication_year": year,
    }


# The 5 tables that "grow linearly with works/edges" and are streamed straight into buckets (the
# main culprit of class A: must not stay in memory).
#   The other 5 (institutions/authors/work_first_pub/fwci_baseline_pop/canonical_id_map) are
#   class B aggregates of O(distinct keys) (bounded) and are written at the end.
_STREAMING_TABLES = ("works", "authorship_edges", "refs_edges", "works_affil", "work_text")


# ===========================================================================
# C20: streaming the reconcile seen ledger.
#   Blind spot: the four-number reconcile seen ledger holds 510M work IDs in a main-process set,
#   grows linearly and becomes a memory hog, and the whole set also goes worker -> main process
#   through IPC/pickle. The fix = a textbook external distinct: each worker accumulates a small
#   batch while scanning -> a full batch is sorted and written to a run file -> cleared; at
#   settlement all run files are k-way merged and counted as a stream with adjacent dedup. The
#   distinct / set-difference semantics equal the old set version one for one (tolerance-0 semantics
#   are unchanged; the existing reconcile tests staying green as they are is the hard acceptance
#   criterion).
# ===========================================================================

# C20: number of ledger entries per batch (spill threshold on a full batch): 1e6 ids ≈ tens of MB
# transient, bounded; an engineering constant, not an identification choice.
_C20_SEEN_FLUSH_EVERY = 1_000_000


class _SeenSpill:
    """Spill the seen ledger in sorted batches (sorted runs): the ledger is never kept in memory as
    a whole and never goes through IPC.

    add(): goes into a small batch set (dedup within the batch); on a full batch -> sort and write
    `<spill_dir>/run-XXXXX.txt` (one id per line), then clear.
    finalize(): spills the last batch and returns all run paths (creation order). Duplicates across
    batches are dropped by adjacent dedup on the merge side.
    Run files live under the worker's local directory tree -> cleaned on success / kept on failure,
    the same lifecycle as the existing P0.3.
    """

    __slots__ = ("spill_dir", "flush_every", "_batch", "_paths")

    def __init__(self, spill_dir, flush_every: int = _C20_SEEN_FLUSH_EVERY):
        self.spill_dir = Path(spill_dir)
        self.flush_every = max(1, int(flush_every))
        self._batch: set[str] = set()
        self._paths: list[str] = []

    def add(self, wid: str) -> None:
        self._batch.add(wid)
        if len(self._batch) >= self.flush_every:
            self._flush()

    def _flush(self) -> None:
        if not self._batch:
            return
        self.spill_dir.mkdir(parents=True, exist_ok=True)
        target = self.spill_dir / f"run-{len(self._paths):05d}.txt"
        with open(target, "w", encoding="utf-8") as fh:
            for wid in sorted(self._batch):
                fh.write(wid + "\n")
        self._paths.append(str(target))
        self._batch = set()

    def finalize(self) -> list[str]:
        """Spill the last batch -> merge all of this worker's runs into a single sorted,
        deduplicated file and delete the intermediate runs.

        Why merge into one file: at the full 510M ids with one run per million there are hundreds of
        runs, and heapq.merge on the settlement side would open all handles at once -> hit the fd
        limit (macOS default 256).
        Merging per worker first makes the global fan-in = number of chunks (tens). distinct is
        idempotent -> layered dedup gives exactly the same result as one-shot dedup.
        """
        self._flush()
        if len(self._paths) <= 1:
            return list(self._paths)
        import heapq

        def _lines(p):
            with open(p, "r", encoding="utf-8") as fh:
                for line in fh:
                    yield line.rstrip("\n")

        target = self.spill_dir / "seen-consolidated.txt"
        prev = None
        with open(target, "w", encoding="utf-8") as out:
            for wid in heapq.merge(*[_lines(p) for p in self._paths]):
                if wid == prev:
                    continue
                prev = wid
                out.write(wid + "\n")
        for p in self._paths:
            Path(p).unlink(missing_ok=True)
        self._paths = [str(target)]
        return list(self._paths)


def _count_distinct_and_skipped(run_paths: Sequence[str], kept_ids) -> tuple[int, int]:
    """Streaming count: k-way merge of all sorted runs + adjacent dedup -> (distinct_seen, |seen −
    kept|).

    heapq.merge is an ordered merge of runs that are each already sorted -> comparing neighbours
    gives global dedup (the distinct semantics equal the old `set(seen)` one for one); the skipped
    test `wid not in kept_ids` equals the old set difference one for one.
    Memory is bounded by "the merge heap (one line per run) + the previous id".
    """
    import heapq

    def _lines(p):
        with open(p, "r", encoding="utf-8") as fh:
            for line in fh:
                yield line.rstrip("\n")

    n_seen = 0
    n_skipped = 0
    prev = None
    for wid in heapq.merge(*[_lines(p) for p in run_paths]):
        if wid == prev:
            continue
        prev = wid
        n_seen += 1
        if wid not in kept_ids:
            n_skipped += 1
    return n_seen, n_skipped


# ===========================================================================
# Local result: the light-weight state that a batch of works returns to the main process after its
# streaming pass-B (class B accumulators + sets + local bucket directory).
#   Class A rows have already been streamed straight into the local HashBucketWriter buckets inside
#   the worker (a full bucket is flushed), and the row lists are never returned -> worker memory is
#   bounded by "bucket buffers x 5 tables + class B accumulators + one work" and does not grow with
#   the total row count.
# ===========================================================================
class _LocalResult:
    """Local result of a worker (or a serial batch) after one batch of works: all picklable,
    light-weight plain data.

    Holds no writer / handle / generator / class A row lists; only:
      - local_dir: the local bucket directory where this worker wrote the 5 streamed tables (str;
        the reduce phase reads it to merge); serial = None.
      - manifests: the local bucket part manifests of the 5 streamed tables ({table: [parts]});
        serial: these are already the final buckets (no reduce needed).
      - author_records: [(canonical_id, display_name, orcid)] in local first-seen order (reproduces
        the serial insertion order).
      - fwci_cells: {(subfield,year,type): (work_count, citation_sum, hist_list)}.
      - inst_by_id: {institution_id: row}, locally deduplicated (O(distinct inst), bounded).
      - frontier/kept: sets (the union reduce is deterministic).
      - seen_spill_paths: paths of the seen ledger's sorted-run files (C20: the ledger goes to disk
        and the set is not returned - the old seen_work_ids set of 510M IDs was a memory/IPC hog and
        is now streamed).
    The main process merges class B in worker order deterministically and reduces the streamed-table
    buckets.
    """

    __slots__ = (
        "local_dir", "manifests", "inst_by_id", "author_records", "fwci_cells",
        "frontier", "seen_spill_paths", "kept_work_ids",
        "edge_authors", "affil_authors", "affil_insts",
    )

    def __init__(self) -> None:
        self.local_dir: Optional[str] = None
        self.manifests: dict[str, list] = {}
        self.inst_by_id: dict[str, dict] = {}
        self.author_records: list[tuple] = []
        self.fwci_cells: dict[tuple, tuple] = {}
        self.frontier: set[str] = set()
        self.seen_spill_paths: list[str] = []
        self.kept_work_ids: set[str] = set()
        # Closure item 4, streaming distinct foreign-key sets (O(distinct), bounded; rows already
        # went into buckets and are not in memory -> collect distinct values while scanning):
        #   edge_authors = authorship_edges.author_id; affil_authors/affil_insts = the two foreign
        #   keys of works_affil.
        self.edge_authors: set[str] = set()
        self.affil_authors: set[str] = set()
        self.affil_insts: set[str] = set()


def _run_passb_local(
    works: Iterable[Mapping[str, Any]],
    *,
    seed_authors: set[str],
    seed_work_ids: set[str],
    author_cmap_pair: Mapping[str, tuple],
    author_cmap_flat: Mapping[str, str],
    inst_cmap_flat: Mapping[str, str],
    local_dir: str,
    n_buckets: int = 256,
    bucket_row_cap: int = 200_000,
    collect_seen: bool = True,
) -> _LocalResult:
    """Run streaming pass-B on a batch of works -> the 5 streamed tables go straight into the
    local-bucket HashBucketWriter (rows are not kept in memory), the internal state of the class B
    (authors/fwci/inst) accumulators + sets are returned to the main process.

    Equivalent to the pass-B section of run_m1.run_slice_tables with the author-collection merged
    in, but without collecting full row lists: as each work flows past, its rows are writer.add()-ed
    into buckets (a full bucket is flushed at once) -> memory is bounded by the bucket buffers, not
    O(total rows).
    The author-collection (a separate pass at run_m1 line 269-271) is merged into pass-B: the
    judgement is equivalent, authors are collected on the way, the output is unchanged (AuthorTable
    is idempotent), and one whole scan is saved.
    """
    specs = _RM._bucketed_table_specs()
    writers = {
        name: HashBucketWriter(
            str(Path(local_dir) / name),
            schema=specs[name][0], pk_cols=specs[name][1],
            n_buckets=n_buckets, bucket_row_cap=bucket_row_cap,
        )
        for name in _STREAMING_TABLES
    }

    lr = _LocalResult()
    lr.local_dir = local_dir
    authors = AuthorTable(author_cmap=author_cmap_flat)
    fwci = FwciPopAccumulator()
    # seen is consumed only by the reconcile count -> not collected when collect_seen=False (S3);
    # collect_seen=True goes through the C20 spill (a full batch is sorted to disk; the ledger is
    # neither resident in memory nor sent through IPC).
    seen_spill = _SeenSpill(Path(local_dir) / "_seen_runs") if collect_seen else None

    for work in works:
        wid = bare(work.get("id"))
        year = work.get("publication_year")
        if seen_spill is not None and wid is not None:
            seen_spill.add(wid)

        authors_here = {a for a, _ in _iter_author_ids(work)}
        is_relevant = (wid in seed_work_ids) or bool(authors_here & seed_authors)
        if not is_relevant:
            continue

        # author-collection (merged into pass-B): collect all authors of seed-relevant works.
        for a in work.get("authorships") or []:
            authors.add_author(a.get("author") or {})

        # works rows -> straight into buckets + fwci accumulation + work_text rows -> straight into buckets.
        writers["works"].add(SM.flatten_work(work))
        if wid is not None:
            lr.kept_work_ids.add(wid)
        fwci.add(work)
        writers["work_text"].add(flatten_work_text(work))

        # works_affil rows -> straight into buckets (cmap folding done in the stream;
        # WorksAffilWriter._rows is not collected).
        for r in iter_works_affil_rows(work):
            ar = _apply_affil_cmap(r, author_cmap_flat, inst_cmap_flat)
            writers["works_affil"].add(ar)
            if ar["author_id"] is not None:
                lr.affil_authors.add(ar["author_id"])
            if ar["institution_id"] is not None:
                lr.affil_insts.add(ar["institution_id"])

        # institutions deduplicated locally (first seen per institution_id; institution_id folded to
        # canonical) -- class B.
        for a in work.get("authorships") or []:
            for inst in a.get("institutions") or []:
                if inst is None:
                    continue
                row = flatten_institution(inst)
                iid = row.get("institution_id")
                iid = inst_cmap_flat.get(iid, iid) if iid is not None else None
                row["institution_id"] = iid
                if iid is not None and iid not in lr.inst_by_id:
                    lr.inst_by_id[iid] = row

        # HIGH-4: all authorship edges of this work (including non-seed collaborators) -> straight
        # into buckets.
        for author_id, _ in _iter_author_ids(work):
            if author_id is None:
                continue
            edge = _canon_edge(wid, author_id, year, author_cmap_pair)
            writers["authorship_edges"].add(edge)
            if edge["author_id"] is not None:
                lr.edge_authors.add(edge["author_id"])

        # refs_edges -> straight into buckets + collect the frontier.
        for raw_ref in work.get("referenced_works") or []:
            ref_id = bare(raw_ref)
            if ref_id is None:
                continue
            writers["refs_edges"].add({"work_id": wid, "referenced_work_id": ref_id})
            lr.frontier.add(ref_id)

    # Flush the local buckets of the 5 streamed tables -> local manifests (the reduce phase merges
    # by bucket); the seen ledger spills its last batch.
    lr.manifests = {name: writers[name].flush_all() for name in _STREAMING_TABLES}
    if seen_spill is not None:
        lr.seen_spill_paths = seen_spill.finalize()

    # Flatten the internal state of the class B accumulators into ordered records (reproduces the
    # serial insertion order, for a deterministic merge in the main process).
    lr.author_records = [
        (cid, authors._by_id[cid]["display_name"], authors._by_id[cid]["orcid"])
        for cid in authors._order
    ]
    lr.fwci_cells = {
        key: (cell.work_count, cell.citation_sum, list(cell.hist))
        for key, cell in fwci._cells.items()
    }
    return lr


def _iter_author_ids(work: Mapping[str, Any]):
    """Yield (bare author_id, _) for each authorship; reproduces the author dimension of
    passes._iter_authorships."""
    for au in work.get("authorships") or []:
        author = au.get("author") or {}
        yield bare(author.get("id")), None


# ===========================================================================
# Deterministic merge: combine several _LocalResult (in worker order) into the global accumulator
# state.
# ===========================================================================
def _merge_locals(locals_in_order: Sequence[_LocalResult]):
    """Merge the class B local states deterministically in worker order -> global accumulator state
    + sets (class A rows are not here: they are in the local bucket directories).

    Order guarantee: locals_in_order is already in ascending worker_index (worker_k handles
    consecutive batches -> global work order); authors are replayed in "global first-seen order" ->
    byte-identical to the serial single pass.
    - authors: the same canonical across workers is merged with AuthorTable semantics ("the first
      non-empty wins"); because the replay follows global order, "first" == the serial "first" ->
      same result as serial (the display_name order dependence is resolved here by the global
      order).
    - fwci: cells added element by element (work_count/citation_sum/hist; commutative +
      associative).
    - institutions: one copy per institution_id, by global first seen.
    - frontier/kept: union.
    - seen: C20 streaming: only concatenate the spill run paths in worker order (counting is done as
      a stream in _reconcile_streaming), the ledger set never enters main-process memory (the old
      510M-ID hog).
    - local_dirs: each worker's local bucket directory (str), for the reduce phase to merge the 5
      streamed tables by bucket.
    first_pub is not merged here: it is a product of the pass-A global accumulator (#9 full
    history), used directly by run_m1_streaming.
    """
    authors = AuthorTable()      # cmap was already applied locally; these records hold canonical ids, so no further folding.
    fwci_cells: dict[tuple, list] = {}
    inst_by_id: dict[str, dict] = {}
    frontier: set[str] = set()
    seen_spill_paths: list[str] = []
    kept: set[str] = set()
    local_dirs: list[str] = []
    edge_authors: set[str] = set()
    affil_authors: set[str] = set()
    affil_insts: set[str] = set()

    for lr in locals_in_order:
        if lr.local_dir is not None:
            local_dirs.append(lr.local_dir)
        edge_authors |= lr.edge_authors
        affil_authors |= lr.affil_authors
        affil_insts |= lr.affil_insts
        seen_spill_paths += lr.seen_spill_paths

        # authors: replay in global first-seen order (canonical ids are final; display_name uses the
        # AuthorTable merge semantics).
        for cid, dname, orcid in lr.author_records:
            authors.add(author_id=cid, display_name=dname, orcid=orcid)

        # fwci: cells added element by element.
        for key, (wc, cs, hist) in lr.fwci_cells.items():
            cur = fwci_cells.get(key)
            if cur is None:
                fwci_cells[key] = [wc, cs, list(hist)]
            else:
                cur[0] += wc
                cur[1] += cs
                for i, v in enumerate(hist):
                    cur[2][i] += v

        # institutions: one copy by global first seen.
        for iid, row in lr.inst_by_id.items():
            if iid not in inst_by_id:
                inst_by_id[iid] = row

        frontier |= lr.frontier
        kept |= lr.kept_work_ids

    merged = {
        "authors": authors,
        "fwci_cells": fwci_cells,
        "inst_by_id": inst_by_id,
        "frontier": frontier,
        "seen_spill_paths": seen_spill_paths,
        "kept": kept,
        "local_dirs": local_dirs,
        "edge_authors": edge_authors,
        "affil_authors": affil_authors,
        "affil_insts": affil_insts,
    }
    return merged


# ===========================================================================
# reduce: merge the local parts of the same (table, bucket) from several workers into one final part
# (canonical-sort once within the bucket).
#   Determinism: the final bucket part bytes = "the set of rows in the bucket" + "the canonical-sort
#   order", and are independent of worker count / shard order / completion order (bucket_of=sha1 is
#   stable across processes; the sort is done once after the merge).
# ===========================================================================
def _sort_key_for(pk_cols):
    """Build the canonical-sort key function within a bucket (same semantics as
    HashBucketWriter._sort_key: None sorts last)."""
    def _key(row):
        return tuple(
            (row[c] is None, "" if row[c] is None else row[c]) for c in pk_cols
        )
    return _key


def _merge_sorted_parts(part_paths: Sequence[str], pk_cols, *, batch_size: int = 50_000):
    """Lazy, stable k-way merge of several parquet parts each already canonical-sorted by PK,
    yielding dict rows one by one.

    Item 1 (S2 reduce memory fix): replaces the old "to_pylist the whole bucket into one big list,
    then sorted".
      - Each part was already sorted by _sort_key (= this module's _sort_key_for) before
        HashBucketWriter.flush_shard wrote it;
      - heapq.merge is a stable merge (documented: for sorted inputs it is equivalent to
        sorted(chain(*iters))); ties between equal keys are broken by the order of the part_paths
        list -> row by row identical to the old path sorted(rows concatenated in part order) ->
        byte-equivalent by construction (it does not depend on Arrow sort stability, and there is no
        concat type-normalisation risk).
      - Streaming reads (iter_batches, to_pylist per batch); memory is bounded by "one batch
        frontier per part + the merge heap", and the whole bucket is never materialised as one big
        Python list (which was the root of the S2 OOM).
    Rule-neutral: only the way ordered rows are obtained changes; no field or sort-key semantics are
    touched.
    """
    import heapq
    import pyarrow.parquet as pq

    keyf = _sort_key_for(pk_cols)

    def _part_rows(path):
        pf = pq.ParquetFile(path)
        for batch in pf.iter_batches(batch_size=batch_size):
            for row in batch.to_pylist():
                yield row

    yield from heapq.merge(*[_part_rows(p) for p in part_paths], key=keyf)


def _write_final_bucket_part(part_paths, target: Path, col_order, pk_cols) -> dict:
    """Write the final single part of a bucket from several already PK-sorted parts through the lazy
    k-way merge (item 1); returns the part metadata.

    Same write parameters as HashBucketWriter.flush_shard (zstd/use_dictionary=False/single row
    group) -> byte-identical.
    The merge order == the old path's sorted(all rows of the bucket) order (stable merge), so the
    bytes equal the old "collect everything, then sorted"; the only difference is that the whole
    bucket is no longer materialised as one big Python list before sorting (S2 memory fix). Writing
    a single row group still needs the whole bucket's columns in memory = the memory floor of this
    format (lower it only by adding buckets via n_buckets, see run_m1_full).
    """
    import hashlib
    import io
    import pyarrow as pa
    import pyarrow.parquet as pq
    from m1_ingest._writer_util import _DETERMINISTIC_PARQUET_KW

    columns: dict[str, list] = {c: [] for c in col_order}
    for row in _merge_sorted_parts(part_paths, pk_cols):
        for c in col_order:
            columns[c].append(row[c])
    table = pa.table({c: columns[c] for c in col_order})
    sink = io.BytesIO()
    pq.write_table(table, sink, row_group_size=max(1, table.num_rows), **_DETERMINISTIC_PARQUET_KW)
    blob = sink.getvalue()
    target.parent.mkdir(parents=True, exist_ok=True)
    from common.atomic_io import atomic_write_bytes
    atomic_write_bytes(target, blob)
    return {
        "rel_path": target.relative_to(target.parents[1]).as_posix(),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "row_count": table.num_rows,
    }


def _resolve_reduce_workers(reduce_workers, n_jobs: int) -> int:
    """Resolve the reduce-phase concurrency (pure function, an engineering constant, not an
    identification choice; it only schedules and touches no bytes or rules).

    - n_jobs = the number of non-empty buckets of this table = the concurrency upper bound (the
      bucket count is the Amdahl ceiling: more workers have no bucket to share).
    - reduce_workers is the auto sentinel (None or <=0) -> min(cpu_count, n_jobs) (use all cores,
      never more than the bucket count); an explicit positive number -> min(reduce_workers, n_jobs);
      the result is always >= 1.
    - n_jobs <= 0 (no bucket to merge) -> 1 (no division by zero, no empty pool).
    """
    import os

    if n_jobs <= 0:
        return 1
    if reduce_workers is None or int(reduce_workers) <= 0:
        return max(1, min(os.cpu_count() or 1, n_jobs))
    return max(1, min(int(reduce_workers), n_jobs))


def _reduce_bucket_worker_entry(args: dict) -> dict:
    """Spawn-safe worker for the reduce of one bucket (module-level, all arguments picklable):
    lazily k-way merges a bucket's parts -> the final single part, and returns the part metadata
    ({rel_path, sha256, row_count}).

    Each bucket is independent (input parts are disjoint + output paths are disjoint + no shared
    state); the final bytes depend only on (part_paths, col_order, pk_cols) -> byte-identical to
    serial (_write_final_bucket_part is a pure function; writing goes through atomic_write_bytes,
    and temp names carry pid+uuid -> no name clashes across processes).
    A spawned child does not inherit the parent's sys.path/monkeypatch -> first
    _worker_sys_path_bridge reproduces the import bridge, then it re-imports this module and calls
    _write_final_bucket_part (the same spawn discipline as the pass-B/C workers).
    """
    _worker_sys_path_bridge()
    import importlib

    sb = importlib.import_module("m1_ingest.stream_build")
    return sb._write_final_bucket_part(
        args["part_paths"], Path(args["target"]), args["col_order"], args["pk_cols"],
    )


def _reduce_streaming_table(
    name: str, schema: dict, pk_cols, local_dirs: Sequence[str], final_root: Path, n_buckets: int,
    reduce_workers: int = 1,
) -> list[dict]:
    """Merge each worker's <local_dir>/<name>/bucket=*/part-*.parquet by bucket number into one
    final part per bucket.

    - For each bucket number b: read that bucket's parts from all workers -> merge rows ->
      canonical-sort once -> write the final part.
    - Buckets are independent (input/output/state are disjoint) -> with reduce_workers>1 they run in
      a multiprocess pool, one task per bucket; =1 runs serially bucket by bucket (the fallback
      path, byte-identical to the old path; small fixtures / a single bucket also run serially to
      avoid pool overhead).
      Parallel == serial byte for byte: (1) part_paths is collected once in the main process,
      deterministically, in local_dirs order x sorted glob (the stable merge breaks ties between
      equal keys by it = the old path verbatim); (2) each bucket's bytes depend only on "the set of
      rows in the bucket + the canonical-sort order", not on worker count or completion order; (3)
      the returned parts are sorted by rel_path at the end -> fully decoupled from bucket completion
      order.
      See test_reduce_workers_* (pinned at byte level).
    - An empty bucket produces no part (a part file is never empty, see HashBucketWriter).
    Only part paths are collected (no rows are read); _write_final_bucket_part lazily k-way merges
    and writes final_root/<name>/bucket=b/part-00000.parquet.
    """
    col_order = list(schema.keys())
    (final_root / name).mkdir(parents=True, exist_ok=True)
    # 1) The main process deterministically collects (target, part_paths) of every non-empty bucket;
    #    serial and parallel share this one collection logic, so the input order is identical to the
    #    letter (local_dirs order x sorted glob); the disk is globbed only here, once.
    bucket_jobs: list[tuple[Path, list[str]]] = []
    for b in range(n_buckets):
        bucket_rel = Path(f"bucket={b:03d}")
        part_paths: list[str] = []
        for ld in local_dirs:
            bdir = Path(ld) / name / bucket_rel
            if not bdir.is_dir():
                continue
            for part in sorted(bdir.glob("part-*.parquet")):
                part_paths.append(str(part))
        if not part_paths:
            continue
        target = final_root / name / bucket_rel / "part-00000.parquet"
        bucket_jobs.append((target, part_paths))

    # 2) Each bucket is merged and written independently: serially bucket by bucket, or in a spawn
    #    multiprocess pool (no shared state between buckets -> parallelism does not break byte
    #    determinism).
    n = _resolve_reduce_workers(reduce_workers, len(bucket_jobs))
    if n > 1 and len(bucket_jobs) > 1:
        ctx = mp.get_context("spawn")
        args_list = [
            dict(part_paths=pp, target=str(tg), col_order=col_order, pk_cols=list(pk_cols))
            for (tg, pp) in bucket_jobs
        ]
        with ctx.Pool(processes=min(n, len(args_list))) as pool:
            # chunksize=1 -> an idle worker takes the next bucket (work-claiming queue, balanced
            # tail); pool.map returns in input order, and the result is still sorted by rel_path at
            # the end -> independent of bucket completion order (determinism rule).
            parts = list(pool.map(_reduce_bucket_worker_entry, args_list, 1))
    else:
        parts = [
            _write_final_bucket_part(pp, tg, col_order, pk_cols)
            for (tg, pp) in bucket_jobs
        ]
    parts.sort(key=lambda e: e["rel_path"])
    return parts


# ===========================================================================
# Entry points of spawn-safe workers (module-level top-level functions; all arguments picklable).
# ===========================================================================
def _worker_sys_path_bridge() -> None:
    """Reproduce the conftest bridge before the worker re-imports: anchor on the units directory +
    insert U0_SRC/U1_SRC.

    A spawned child does not inherit the parent's sys.path -> it must inject the paths itself,
    otherwise from common.* / from m1_ingest.* cannot be found.
    The anchor does not count parents levels; it anchors directly on the `units` directory (the safe
    pattern).
    """
    import pathlib
    import sys

    here = pathlib.Path(__file__).resolve()
    units = next(p for p in here.parents if p.name == "units")
    for sub in ("u0_foundation", "u1_fetch"):
        src = units / sub / "src"
        s = str(src)
        if s not in sys.path:
            sys.path.insert(0, s)


class ShardPathSource:
    """A disk-streaming work source that can be iterated repeatedly: every __iter__ newly opens
    iter_jsonl_gz_shards and reads the shards as a stream.

    Why it is needed (the key to not blowing up at full scale): pass-A and pass-B both read the work
    source from the start (the seed snowball is inherently two passes).
    An in-memory list can be iterated repeatedly but must be fully loaded (510M works = OOM); a
    generator cannot be iterated twice. This class holds shard paths (a light list of str) and on
    every iteration opens a fresh U0 streaming gz reader and yields one record at a time -> truly
    streaming, memory bounded by one work.

    - shard_paths: list of shard .gz paths (str).
    - __iter__: yields each work dict (strips the shard_id of (shard_id, record) and gives only the
      record).
    - __len__: number of shards (not the number of works, which is known only after a scan; used by
      the parallel batching to decide "are there enough to split").
    Rule-neutral: only the way works are fed changes; no fields or filters are touched.
    """

    __slots__ = ("shard_paths",)

    def __init__(self, shard_paths: Sequence[str]):
        self.shard_paths = [str(p) for p in shard_paths]

    def __iter__(self):
        from common.snapshot_reader import iter_jsonl_gz_shards
        for _shard_id, record in iter_jsonl_gz_shards(self.shard_paths):
            yield record

    def __len__(self) -> int:
        return len(self.shard_paths)


def _pass_c_worker_entry(args: dict) -> dict:
    """Module-level worker entry for parallel pass-C (spawn-safe, scan_workers): scans its own batch
    of shards; works hit by the frontier are written to its own local bucket (<local_dir>/works,
    same shape as the pass-B local buckets), and the set of hit ids is returned. The finish (missing
    / S1 threshold) belongs to the parent's P._finalize_frontier_missing; this entry contains no
    rule."""
    _worker_sys_path_bridge()
    import importlib
    sb = importlib.import_module("m1_ingest.stream_build")
    from common.snapshot_reader import iter_jsonl_gz_shards as _iter_shards
    from m1_ingest.hash_bucket_writer import HashBucketWriter as _HBW

    writer = _HBW(str(Path(args["local_dir"]) / "works"), schema=args["schema"],
                  pk_cols=args["pk_cols"], n_buckets=args["n_buckets"],
                  bucket_row_cap=args["bucket_row_cap"])
    frontier = args["frontier"]
    hits: set = set()
    for _sid, work in _iter_shards(args["shard_paths"]):
        wid = sb.bare(work.get("id"))
        if wid in frontier:
            hits.add(wid)
            writer.add(sb.SM.flatten_work(work))
    writer.flush_all()
    return {"hits": hits}


def _m1_worker_entry(args: dict) -> _LocalResult:
    """Module-level worker entry (spawn pickles function references -> it cannot be a closure).

    args are all picklable:
      - works=list[dict] (fixture / small-sample batch; memory bounded by one batch), or
      - shard_paths=list[str] (full scale: the worker opens a U0 streaming reader itself and reads
        its own batch of shards one record at a time, without loading them all).
    The seed sets / cmap dicts / local directories are all picklable (no generators / handles /
    writers are passed).
    """
    _worker_sys_path_bridge()
    # Re-import inside the worker (spawn has rebuilt the module); call this module's local pass-B
    # directly.
    import importlib
    sb = importlib.import_module("m1_ingest.stream_build")
    shard_paths = args.get("shard_paths")
    works_source = sb.ShardPathSource(shard_paths) if shard_paths is not None else args["works"]
    return sb._run_passb_local(
        works_source,
        seed_authors=args["seed_authors"],
        seed_work_ids=args["seed_work_ids"],
        author_cmap_pair=args["author_cmap_pair"],
        author_cmap_flat=args["author_cmap_flat"],
        inst_cmap_flat=args["inst_cmap_flat"],
        local_dir=args["local_dir"],
        n_buckets=args["n_buckets"],
        bucket_row_cap=args["bucket_row_cap"],
        collect_seen=args.get("collect_seen", True),
    )


def _chunk_contiguous(items: Sequence, n: int) -> list[list]:
    """Cut items into n contiguous chunks (global order kept: chunk 0 first, chunk n-1 last).

    Contiguous cuts + merging the chunks in order -> the global order the workers process == the
    serial single-pass order -> the accumulator insertion order is the same.
    """
    if n <= 1 or len(items) <= 1:
        return [list(items)]
    size = (len(items) + n - 1) // n
    out = []
    for i in range(0, len(items), size):
        out.append(list(items[i:i + size]))
    return out or [[]]


def _shard_size_bytes(path) -> int:
    """Shard size in bytes (for C19 byte bucketing); stat failure -> 0 (the allocator falls back to
    shard counts by itself, no crash)."""
    import os
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


# C19 target number of chunks per worker (depth of the dynamic work-claiming queue):
#   number of chunks = n_workers x this value. Too few chunks -> the tail becomes a straggler again;
#   too many -> the per-chunk writer/part overhead is magnified.
#   An engineering constant (same granularity as the mp.Pool.map default chunk heuristic), not an
#   identification choice.
_C19_CHUNKS_PER_WORKER = 4


def _chunk_contiguous_by_bytes(paths: Sequence, n_workers: int, *, sizes=None,
                               chunks_per_worker: int = _C19_CHUNKS_PER_WORKER) -> list[list]:
    """C19: static equal split by shard count -> byte-weighted buckets + dynamic work claiming.

    The problem: with a static equal split by shard count the tail has a long straggler (the shards
    late in updated_date are very fat, 6 of 8 workers finish and sit idle, CPU drops from 43% to
    12%, the ETA slips by about 9h); cutting pass-B/C into chunks once over the whole input
    magnifies the imbalance over the whole run. The options are a dynamic work-claiming queue,
    byte-weighted buckets, or largest-shards-first ordering.
    This implementation takes the first two: (1) cut contiguous chunks by accumulated bytes (chunk
    target bytes = total bytes / (workers x chunks_per_worker));
    (2) number of chunks > number of workers, with pool.map(chunksize=1) dispatching dynamically ->
        an idle worker automatically takes the next chunk.
    The bound on tail imbalance drops from "the whole run" to "one chunk" (one chunk <= target bytes
    + the largest single shard, the greedy step overshoots by one).

    Determinism rule (the global-order replay contract with _merge_locals; never change):
      - Every chunk is a contiguous slice of the input order; all chunks concatenated in order ==
        the original input (only boundaries move, never reorder) -> locals_in_order still follows
        global work order -> the first-seen order of authors/institutions is byte-identical to
        serial.
      - Pure function: depends only on paths + sizes (the real disk is stat-ed only if sizes are not
        injected); same input, same output.
    sizes all 0 / total bytes 0 -> fall back to _chunk_contiguous, an equal split by shard count
    into the same number of chunks (there is a floor, no division by zero).
    """
    paths = list(paths)
    if not paths:
        return [[]]
    n_chunks = max(1, int(n_workers)) * max(1, int(chunks_per_worker))
    if n_chunks <= 1 or len(paths) == 1:
        return [paths]
    if sizes is None:
        sizes = [_shard_size_bytes(p) for p in paths]
    sizes = list(sizes)
    if len(sizes) != len(paths):
        raise ValueError(
            f"C19 allocator: sizes({len(sizes)}) and paths({len(paths)}) differ in length — "
            "caller bug, fail-loud, no silent truncation"
        )
    total = sum(sizes)
    if total <= 0:
        return _chunk_contiguous(paths, n_chunks)   # No byte information -> equal split by shard count (behaviour has a floor)
    target = total / n_chunks
    chunks: list[list] = []
    cur: list = []
    cur_bytes = 0
    for p, sz in zip(paths, sizes):
        cur.append(p)
        cur_bytes += sz
        if cur_bytes >= target:                      # Greedy chunk close (may overshoot by one step, upper bound target+max_size)
            chunks.append(cur)
            cur, cur_bytes = [], 0
    if cur:
        chunks.append(cur)
    return chunks


# ===========================================================================
# Top-level entry: run_m1_streaming (streaming + optionally parallel + deterministic; returns the
# same shape as run_m1_slice).
# ===========================================================================
def run_m1_streaming(
    seed_shards: Sequence[Mapping[str, Any]],
    passc_shards: Sequence[Mapping[str, Any]],
    *,
    registry: list[dict],
    econ_dept_ids: set[str],
    out_root,
    n_buckets: int = 256,
    bucket_row_cap: int = 200_000,
    n_workers: int = 1,
    # Wiring (b): the author_id of byline hits with an empty institution is merged into the pass-A
    # seeds (minimal set) -- without it these departed authors would be missing permanently.
    extra_seed_authors: Optional[set] = None,
    author_merged_rows: Optional[Iterable[Mapping[str, str]]] = None,
    institution_merged_rows: Optional[Iterable[Mapping[str, str]]] = None,
    source_snapshot_merkle: str = "STREAM",
    config_sha: str = "CFG",
    rule_version: str = "v",
    code_version: str = "z",
    expected_snapshot_merkle: Optional[str] = None,
    run_field_probe: bool = True,
    run_pass_c: bool = True,
    run_space_guard: bool = True,
    reconcile: bool = False,
    reconcile_stage: str = "m1_stream",
    reconcile_diff_tolerance: Any = None,
    reconcile_manifest: Optional[Mapping[str, Any]] = None,
    reconcile_entity: str = "works",
    # Same default True as the full-scale entry run_full: the entry passes it explicitly, but the
    # lower layer also defaults to on -> a new driver that calls this orchestration directly cannot
    # "forget to turn it on" either; turning it off must be an explicit False.
    run_compact_dedup: bool = True,
    pass_a_ckpt_dir: Optional[str] = None,
    pass_a_checkpoint_every_n: int = 100,
    scan_workers: int = 1,
    # Reduce phase in parallel by bucket: reduce = a single-threaded final step merging 256 buckets
    # x 5 tables one by one, about 45% of the tuned full run (the biggest bottleneck / Amdahl
    # floor). Buckets are independent -> a multiprocess pool runs them in parallel by bucket,
    # byte-identical to serial.
    #   1 = serial (default, zero behaviour change, protects the existing determinism tests); <=0 =
    #   auto (min(cpu, bucket count)); a positive number = explicit concurrency.
    reduce_workers: int = 1,
) -> dict[str, list]:
    """M1 full-scale streaming orchestration: pass-A finds the seeds -> streaming pass-B
    (parallel/serial) with rows going straight into buckets -> pass-C fills the frontier -> closure
    item 4 guard -> (optional) reconcile -> flush the 10 table buckets -> run_manifest + provenance.

    Returns {table name: [part manifest ...]} (same shape as write_tables_bucketed; each part has
    rel_path/sha256/row_count).

    Equivalent to the old path (n_workers=1) + deterministic in parallel (n_workers>1) + two runs
    byte-identical -- see test_stream_build.
    Rule-neutral: no identification placeholder is touched; reconcile_diff_tolerance is a
    placeholder, and turning on reconcile requires passing it explicitly (None -> RedlineUnsigned is
    passed through; the tolerance is never chosen on its own).
    A2 counter-anchor: reconcile=True must be given reconcile_manifest (the external truth from the
    manifest); a missing anchor -> ValueError (no external anchor = a fake reconcile); expected is
    taken from compute_expected_from_manifest, so only then can silent data loss be detected.
    A3 dedup guard: run_compact_dedup defaults to True -> at the end compact_dedup runs on every
    table's actual parquet (count(*)-count(DISTINCT pk) non-zero -> exit 21), stopping duplicate PKs
    produced by reduce/pass-C from reaching U2/U3 raw.
    Turning it off must be an explicit False; the guard is a read-only check and does not change
    product bytes or reconcile semantics.
    """
    out_root = Path(out_root)
    registry_by_id = build_registry_by_id(registry)

    # A2 counter-anchor fail-fast: reconcile requested without an external truth anchor = back to a
    # self-counted fake reconcile -> ValueError at once (no temp directory is created).
    if reconcile and reconcile_manifest is None:
        raise ValueError(
            "reconcile=True needs reconcile_manifest as the external truth anchor (compute_expected_from_manifest); "
            "without it the reconciliation uses its own scanned counts as the expected counts, a false reconciliation (A2 audit root cause); refused."
        )

    # --- build the canonical map first (before dedup / table writes; one root per person) ---
    author_cmap = build_canonical_map(list(author_merged_rows or []), id_type="author")
    inst_cmap = build_canonical_map(list(institution_merged_rows or []), id_type="institution")
    author_cmap_flat = {raw: term for raw, (term, _d) in author_cmap.items()}
    inst_cmap_flat = {raw: term for raw, (term, _d) in inst_cmap.items()}

    # --- field probe (streaming: first n records; assert_snapshot_fields_present signature unchanged) ---
    if run_field_probe:
        _RM.field_probe(seed_shards)

    # ---------- PASS-A: scan all seeds + piggyback first_pub (#9 full history) ----------
    first_pub_global = FirstPubAccumulator(author_cmap=author_cmap_flat)
    if pass_a_ckpt_dir is not None and isinstance(seed_shards, ShardPathSource):
        # Resumable pass-A: iterate over shards + save a checkpoint every N shards + skip already
        # scanned shards after a crash (so one crash does not wipe out a long full run).
        #   The raw FirstPubAccumulator is fed with keyword add directly, without
        #   _PositionalFirstPub. A resumed run == a full scan (idempotent).
        #   scan_workers>1 -> parallel scan rounds (single-threaded ~7-10MiB/s was the bottleneck of
        #   the whole run; accumulation is commutative and associative, parallel == serial is pinned
        #   at byte level by test_parallel_scan; same checkpoint format, so serial and parallel runs
        #   can resume each other).
        if scan_workers and scan_workers > 1:
            from m1_ingest.resumable_pass_a import pass_a_seed_authors_parallel
            pass_a = pass_a_seed_authors_parallel(
                seed_shards.shard_paths,
                econ_dept_ids=econ_dept_ids,
                registry_by_id=registry_by_id,
                first_pub=first_pub_global,
                ckpt_dir=pass_a_ckpt_dir,
                n_workers=scan_workers,
                checkpoint_every_n=pass_a_checkpoint_every_n,
                author_cmap_flat=author_cmap_flat,
            )
        else:
            from m1_ingest.resumable_pass_a import pass_a_seed_authors_resumable
            pass_a = pass_a_seed_authors_resumable(
                seed_shards.shard_paths,
                econ_dept_ids=econ_dept_ids,
                registry_by_id=registry_by_id,
                first_pub=first_pub_global,
                ckpt_dir=pass_a_ckpt_dir,
                checkpoint_every_n=pass_a_checkpoint_every_n,
            )
    else:
        # Old path (fixture / no checkpoint): flat stream + positional adapter (behaviour unchanged).
        first_pub_sink = _RM._PositionalFirstPub(first_pub_global)
        pass_a = P.pass_a_seed_authors(
            seed_shards,
            econ_dept_ids=econ_dept_ids,
            registry_by_id=registry_by_id,
            first_pub=first_pub_sink,
        )
    seed_authors = set(pass_a.seed_authors)
    seed_work_ids = set(pass_a.seed_work_ids)

    # Wiring (b): merge the leaver seeds with an empty byline institution (minimal set; the caller
    # feeds only the author_id of rows with institution=None whose department name matches -- see
    # the run_m1_full extractor).
    #   id space: pass-B seed matching is in the snapshot's bare (raw) space, while the byline hits
    #   come from U1's canonical terminal output -> expand raw aliases in reverse through this run's
    #   own author cmap (the same person, not a new rule), so that "the snapshot byline carries an
    #   old raw id while the hits know only the terminal id" is not missed.
    if extra_seed_authors:
        _extra = {a for a in extra_seed_authors if a is not None}
        _aliases = {raw for raw, (_t, _d) in author_cmap.items() if _t in _extra}
        seed_authors |= _extra | _aliases

    # ---------- PASS-B: stream 5 growing tables into local buckets + return class B state ----------
    import tempfile

    worker_args_base = dict(
        seed_authors=seed_authors,
        seed_work_ids=seed_work_ids,
        author_cmap_pair=author_cmap,
        author_cmap_flat=author_cmap_flat,
        inst_cmap_flat=inst_cmap_flat,
        n_buckets=n_buckets,
        bucket_row_cap=bucket_row_cap,
        collect_seen=bool(reconcile),  # S3: when reconcile is off, seen is not collected (saves the full-scale IPC)
    )

    is_path_source = isinstance(seed_shards, ShardPathSource)
    splittable = len(seed_shards) > 1  # shard count (path source) or work count (in-memory source): enough to split into batches?

    # Temporary root of the local buckets (each worker writes its own <tmp>/worker_k/<table>/...;
    # cleaned after success, kept after failure).
    tmp_root = Path(tempfile.mkdtemp(prefix="m1_stream_", dir=str(out_root.parent)))
    _flush_done = False                                     # P0.3: success flag, so the temporary buckets are not deleted on failure
    try:
        if n_workers and n_workers > 1 and splittable:
            # Parallel map: cut into contiguous batches -> one batch per worker + its own local
            # bucket directory; spawn-safe.
            ctx = mp.get_context("spawn")
            if is_path_source:
                # Full scale: cut contiguously by shard file -> each worker opens a streaming reader
                # and reads its own batch of shards (not loaded all at once).
                #   C19: byte-weighted buckets + number of chunks > number of workers (dynamic work
                #   claiming), replacing the old static equal split by shard count (the straggler
                #   problem); chunks stay contiguous and are merged in order, determinism unchanged.
                payloads = _chunk_contiguous_by_bytes(seed_shards.shard_paths, n_workers)
                args_list = [
                    dict(shard_paths=list(b), local_dir=str(tmp_root / f"worker_{k}"),
                         **worker_args_base)
                    for k, b in enumerate(payloads)
                ]
            else:
                # Fixture / small sample: cut contiguously by work (in-memory source, small batches;
                # no byte measure, keep the equal split by count).
                payloads = _chunk_contiguous(list(seed_shards), n_workers)
                args_list = [
                    dict(works=list(b), local_dir=str(tmp_root / f"worker_{k}"),
                         **worker_args_base)
                    for k, b in enumerate(payloads)
                ]
            with ctx.Pool(processes=min(n_workers, len(args_list))) as pool:
                # C19: chunksize=1 -> tasks are dispatched chunk by chunk dynamically (an idle
                # worker takes the next chunk = work-claiming queue); pool.map still returns results
                # in input order -> locals_in_order keeps the global order (determinism unchanged).
                locals_in_order = pool.map(_m1_worker_entry, args_list, 1)
        else:
            # Serial streaming (fallback path: no blow-up but single-threaded): the whole source
            # flows through once (no list(), truly streaming), rows go straight into the local
            # buckets.
            locals_in_order = [
                _run_passb_local(seed_shards, local_dir=str(tmp_root / "worker_0"),
                                 **worker_args_base)
            ]

        merged = _merge_locals(locals_in_order)
        # first_pub comes from the pass-A global accumulator (#9 full history, including non-seed
        # authors), not from the pass-B local state.
        merged["first_pub_rows"] = first_pub_global.rows()

        # ---------- PASS-C: rescan the frontier to fill in works rows (guard lives in passes) ----------
        # run_pass_c defaults to True -> full-scale behaviour unchanged (the frontier must all be
        # hit, otherwise passes.pass_c exit(20)).
        # run_pass_c=False is only for single-shard smoke runs (a frontier pointing at works off the
        # disk is expected).
        # already = the distinct ids that pass-B really wrote into works (=merged["kept"]); the
        # works rows need not be in memory.
        frontier_to_scan = merged["frontier"] - merged["kept"]
        passc_dir = tmp_root / "passc"
        # MED-2: first clear any dangling sidecar left over from the previous run -- semantics
        # pinned: a sidecar is present <=> this run has danglers. Otherwise a rerun with the same
        # out_root would let old statistics mislead the diagnosis.
        for _stale in ("pass_c_missing.parquet", "pass_c_missing.json"):
            _sp = out_root / "_manifest" / _stale
            if _sp.exists():
                _sp.unlink()
        if run_pass_c and frontier_to_scan:
            passc_specs = _RM._bucketed_table_specs()
            passc_works_writer = HashBucketWriter(
                str(passc_dir / "works"),
                schema=passc_specs["works"][0], pk_cols=passc_specs["works"][1],
                n_buckets=n_buckets, bucket_row_cap=bucket_row_cap,
            )

            def _passc_sink(work) -> None:
                passc_works_writer.add(SM.flatten_work(work))   # straight into buckets, no list is collected
                wid = bare(work.get("id"))
                if wid is not None:
                    merged["kept"].add(wid)

            def _passc_missing_sink(missing_ids: list) -> None:
                # S1: dangling ids + statistics go to a sidecar (written first whether or not it
                # HALTs -- the lesson of the 123GB incident, which left no diagnostic trace).
                # Deterministic: sorted ids in a single column, zstd, one row group.
                import json as _json

                import pyarrow as _pa
                import pyarrow.parquet as _pq

                from m1_ingest._writer_util import _DETERMINISTIC_PARQUET_KW as _KW

                mf_dir = out_root / "_manifest"
                mf_dir.mkdir(parents=True, exist_ok=True)
                t = _pa.table({"work_id": _pa.array(list(missing_ids), type=_pa.string())})
                _pq.write_table(t, str(mf_dir / "pass_c_missing.parquet"),
                                row_group_size=max(1, t.num_rows), **_KW)
                total = len(frontier_to_scan)
                (mf_dir / "pass_c_missing.json").write_text(_json.dumps({
                    "frontier_scanned": total,
                    "hits": total - len(missing_ids),
                    "missing_count": len(missing_ids),
                    "missing_ratio": round(len(missing_ids) / total, 6),
                }, ensure_ascii=False, indent=2), encoding="utf-8")

            if scan_workers and scan_workers > 1 and isinstance(passc_shards, ShardPathSource):
                # Parallel pass-C: shards are split among scan_workers workers, each writes its own
                # local bucket (passc_dir/worker_k, same shape as the pass-B local buckets) -> a
                # stable reduce merge (works PK is unique, the bucketing does not affect the final
                # bytes -- pinned end to end by test_parallel_scan). The finish semantics share
                # P._finalize_frontier_missing (S1 tolerance/HALT is the same code as serial).
                passc_works_writer = None  # the serial writer is not used (each worker builds its own)
                # C19: pass-C is likewise byte-bucketed + dynamically claimed (pass-B/C cut the
                # whole input into chunks once, which magnifies the imbalance over the whole run).
                pc_chunks = _chunk_contiguous_by_bytes(passc_shards.shard_paths, scan_workers)
                pc_args = [
                    dict(shard_paths=list(c), frontier=frontier_to_scan,
                         local_dir=str(passc_dir / f"worker_{k}"),
                         schema=passc_specs["works"][0], pk_cols=passc_specs["works"][1],
                         n_buckets=n_buckets, bucket_row_cap=bucket_row_cap)
                    for k, c in enumerate(pc_chunks)
                ]
                pc_ctx = mp.get_context("spawn")
                with pc_ctx.Pool(processes=min(scan_workers, len(pc_args))) as pc_pool:
                    pc_outs = pc_pool.map(_pass_c_worker_entry, pc_args, 1)
                hit_ids: set = set()
                for o in pc_outs:
                    hit_ids |= o["hits"]
                merged["kept"] |= hit_ids
                merged["local_dirs"] += [a["local_dir"] for a in pc_args]
                P._finalize_frontier_missing(hit_ids, frontier_to_scan,
                                             missing_sink=_passc_missing_sink)
            else:
                P.pass_c(passc_shards, frontier=frontier_to_scan, works_sink=_passc_sink,
                         missing_sink=_passc_missing_sink)
                passc_works_writer.flush_all()
                merged["local_dirs"].append(str(passc_dir))  # the works reduce also takes the pass-C local buckets

        # ---------- Closure item 4 canonical-space guard (streaming: takes distinct sets, no full table) ----------
        # run_space_guard defaults to True -> full-scale behaviour unchanged (a foreign-key split ->
        # exit(22)). Set False only for single-shard smoke runs: work_first_pub contains the pass-A
        # full set of authors (#9), and with a single shard the authors table covers only
        # seed-related authors -> fp ⊄ authors is a property that is consistent only on the full
        # snapshot (the old path is the same), not a bug; a smoke run checks only
        # streaming/memory/determinism, so the guard is skipped.
        if run_space_guard:
            _assert_canonical_space_streaming(merged)

        # ---------- Assemble the 5 class B table rows (bounded: O(distinct keys)) ----------
        # The 5 streamed tables merge by bucket and are not here.
        bclass_rows = _assemble_bclass_rows(merged, author_cmap, inst_cmap)

        # ---------- (optional) reconcile four-number check ----------
        # A2: expected comes from the external manifest truth, not the self-counted seen∪kept.
        if reconcile:
            mf_dir = out_root / "_manifest"
            mf_dir.mkdir(parents=True, exist_ok=True)
            _reconcile_streaming(
                merged,
                stage=reconcile_stage,
                tally_path=mf_dir / "reconcile_tally.json",
                diff_tolerance=reconcile_diff_tolerance,
                manifest=reconcile_manifest,
                entity=reconcile_entity,
            )

        # ---------- flush the final 10 tables ----------
        specs = _RM._bucketed_table_specs()
        manifests: dict[str, list] = {}
        table_meta: dict[str, dict] = {}
        for name, (schema, pk_cols) in specs.items():
            # Create the table root directories first (an empty table has no part but still needs
            # its directory; the provenance sidecar goes to out_root/<name>/; aligned with the old
            # path).
            (out_root / name).mkdir(parents=True, exist_ok=True)
            if name in _STREAMING_TABLES:
                # The 5 streamed tables: several workers' local buckets -> merged by bucket +
                # canonical-sort once -> one final part per bucket.
                #   reduce_workers>1 -> a multiprocess pool by bucket (byte-identical to serial, see
                #   _reduce_streaming_table).
                parts = _reduce_streaming_table(
                    name, schema, pk_cols, merged["local_dirs"], out_root, n_buckets,
                    reduce_workers=reduce_workers,
                )
            else:
                # The 5 class B tables (bounded): rows are poured straight into the final HashBucketWriter.
                writer = HashBucketWriter(
                    str(out_root / name),
                    schema=schema, pk_cols=pk_cols,
                    n_buckets=n_buckets, bucket_row_cap=bucket_row_cap,
                )
                for row in bclass_rows.get(name, []):
                    writer.add(row)
                parts = writer.flush_all()
            manifests[name] = parts
            table_meta[name] = _table_meta_from_parts(parts)

        # ---------- A3 dedup guard (compact_dedup) ----------
        # Per table count(*)-count(DISTINCT pk); duplicates -> exit 21.
        # If reduce/pass-C produced duplicate PKs, the raw output would go straight to U2/U3 with no
        # guard (the T7 acceptance gate was implemented but never called). run_compact_dedup=True
        # turns it on: a DuckDB dedup check runs on each table's actual parquet shards, non-zero ->
        # HALT.
        # The default is True; turning the guard off must be an explicit False.
        # Placed before _flush_done=True: if dedup fails, the local temporary bucket directory is
        # kept (P0.3: not deleted on failure, for diagnosis / resume).
        # reconcile_scanned_shards ("scanned shard set == manifest") is explicitly NOT wired in (a
        # deliberate deferral, not a silent omission):
        #   the manifest lists s3:// urls, while the full run actually scans local SSD shard paths
        #   (run_m1_full.discover_work_shards globs the local disk); the key spaces differ and there
        #   is no manifest -> local path normalisation layer; blindly building one risks a false
        #   HALT. Also, the whole-shard completeness check "shards that should be fetched == shards
        #   actually downloaded" belongs to M0 manifest_reconcile.reconcile_shards. So the M1 finish
        #   adds only the external anchor of the arithmetic arm (A2) + the dedup arm (this block);
        #   the shard arm is to be added once a manifest -> local path bridge exists.
        if run_compact_dedup:
            from m1_ingest import reconcile_m1 as REC
            for _name, (_schema, _pk_cols) in specs.items():
                _part_paths = sorted((out_root / _name).rglob("*.parquet"))
                REC.compact_dedup(_part_paths, pk_cols=list(_pk_cols))

        _flush_done = True                                  # Success only when all 10 tables are flushed and the dedup guard passes
    finally:
        # P0.3: clean up the temporary buckets only on the success path. Exceptions/SystemExit
        # (including a pass-C HALT) always keep them -- "delete on failure" once wiped the
        # half-finished 123GB pass-B/C output of a 33h run (no diagnostic trace left).
        import shutil
        import sys as _sys
        if _flush_done:
            shutil.rmtree(tmp_root, ignore_errors=True)     # The final tables are already in out_root; the temporary files do not go into git
        else:
            _sys.stderr.write(
                f"[m1_stream] abnormal exit — keeping the partial bucket temp directory for diagnosis/resume (clean up manually): {tmp_root}\n"
            )

    # ---------- run_manifest + provenance sidecar (reuses run_m1, shape unchanged) ----------
    _RM.emit_run_manifest(
        table_meta, out_root,
        source_snapshot_merkle=source_snapshot_merkle,
        config_sha=config_sha, rule_version=rule_version, code_version=code_version,
        expected_snapshot_merkle=expected_snapshot_merkle,
    )
    _RM._emit_provenance_sidecars(
        table_meta, out_root,
        source_snapshot_merkle=source_snapshot_merkle,
        config_sha=config_sha, rule_version=rule_version, code_version=code_version,
    )
    return manifests


# ===========================================================================
# Assemble the rows of the 5 class B tables (bounded aggregates; the 5 streamed tables merge by
# bucket and are not here).
# ===========================================================================
def _assemble_bclass_rows(merged: dict, author_cmap, inst_cmap) -> dict[str, list]:
    """Flatten the 5 class B table rows out of the merged state
    (institutions/authors/work_first_pub/fwci/canonical_id_map).

    These 5 are O(distinct keys) aggregates (bounded, small) and their content matches the
    corresponding tables of run_slice_tables.
    The other 5 tables that grow linearly with works/edges
    (works/authorship_edges/refs_edges/works_affil/work_text) are streamed straight into buckets ->
    merged by reduce and not assembled here (that is the key to not blowing up).
    """
    authors: AuthorTable = merged["authors"]
    # first_pub uses the rows of the pass-A global accumulator directly (#9 full history; already
    # folded to canonical, taking the min).
    first_pub_rows = merged["first_pub_rows"]
    fwci_rows = []
    # None-safe sort: work_type can be None, and a bare sorted raises TypeError on None x str;
    # non-None values first, None last.
    for key in sorted(merged["fwci_cells"], key=lambda k: (k[0], k[1], k[2] is None, "" if k[2] is None else k[2])):
        subfield_id, year, work_type = key
        wc, cs, hist = merged["fwci_cells"][key]
        fwci_rows.append({
            "subfield_id": subfield_id,
            "year": year,
            "work_type": work_type,
            "work_count": wc,
            "citation_sum": cs,
            "cit_hist_32": list(hist),
        })
    cmap_rows = []
    cmap_rows.extend(to_canonical_rows(author_cmap, id_type="author"))
    cmap_rows.extend(to_canonical_rows(inst_cmap, id_type="institution"))

    return {
        "institutions": list(merged["inst_by_id"].values()),
        "authors": authors.rows(),
        "work_first_pub": first_pub_rows,
        "fwci_baseline_pop": fwci_rows,
        "canonical_id_map": cmap_rows,
    }


# ===========================================================================
# Closure item 4, streaming version: takes the merged state's distinct sets (no full table
# materialised in memory).
# ===========================================================================
def _assert_canonical_space_streaming(merged: dict) -> None:
    """Streaming closure item 4: foreign-key distinct ⊆ primary-key distinct; if any fails ->
    exit(EXIT_CANONICAL_SPACE_SPLIT=22).

    Guards 3 relations (reuses run_m1.assert_canonical_space; None foreign keys do not enter the
    subset test):
      - authorship_edges.author_id ⊆ authors.author_id
      - works_affil.author_id      ⊆ authors.author_id
      - works_affil.institution_id ⊆ institutions.institution_id
    It is fed "distinct foreign-key/primary-key sets collected while streaming" (O(distinct),
    bounded), with no full table in memory. The exit code is unchanged.

    It never guards work_first_pub.author_id ⊆ authors: first_pub is the pass-A full-history
    superset (#9, every (author, year), non-seed authors included, is fed in -- only the full
    history yields the true first-publication year), while authors holds only the authors of
    seed-related works -> at full scale fp_authors ⊋ authors is a design property, not a canonical
    split. The old version fed fp_authors to the guard as a "⊆ authors foreign key", which is bound
    to be false the first time at full scale -> a false exit(22) and not one row written (a
    blocker-level bug).
    Approach: do not put work_first_pub into tables -> inside the run_m1 guard it is the empty set
    -> empty ⊆ authors always holds and never fires; the other 3 are guarded as usual. first_pub's
    own canonical consistency is ensured by passing everything through author_cmap_flat, so no
    cross-table comparison is needed.
    """
    authors_tbl: AuthorTable = merged["authors"]
    author_ids = {cid for cid in authors_tbl._order}
    institution_ids = set(merged["inst_by_id"].keys())

    edge_authors = set(merged["edge_authors"])
    affil_authors = set(merged["affil_authors"])
    affil_insts = set(merged["affil_insts"])

    # Test hook: force a split (always False in production).
    if _FORCE_CANONICAL_SPLIT_FOR_TEST:
        edge_authors = edge_authors | {"A_GHOST_FORCED_SPLIT"}

    # Reuse run_m1's guard (reassemble the distinct sets into the tables shape it takes: same
    # behaviour verbatim + same exit code).
    # work_first_pub is deliberately not passed (see the docstring above): fp is the full superset
    # and does not take part in the ⊆ authors guard.
    tables = {
        "authors": [{"author_id": a, "display_name": None, "orcid": None} for a in author_ids],
        "institutions": [{"institution_id": i} for i in institution_ids],
        "authorship_edges": [{"author_id": a} for a in edge_authors],
        "works_affil": (
            [{"author_id": a, "institution_id": None} for a in affil_authors]
            + [{"author_id": None, "institution_id": i} for i in affil_insts]
        ),
    }
    _RM.assert_canonical_space(tables)


# ===========================================================================
# Streaming reconcile: the feed source is replaced by the merged state's seen/kept (the formula is
# verbatim the same as run_m1).
# ===========================================================================
def _reconcile_streaming(merged, *, stage, tally_path, diff_tolerance, manifest, entity="works") -> dict:
    """Streaming four-number reconcile: expected is the manifest's external truth, skipped is
    counted independently (seen − kept). A thin wrapper over reconcile_pass.

    A2 fix (root cause of the "fake reconcile"): the old expected = seen ∪ frontier_only, and by the
    set identity |seen ∪ kept| ≡ |kept| + |seen − kept| expected == kept + skipped always held, so
    the arithmetic arm did nothing -> a shard silently truncated and 28,500 records short, seen and
    kept shrank together, the difference was always 0, and even with diff_tolerance=0 there was no
    alarm (the Sydney 27k / UQ 28,500 incident). The new expected is set by the manifest
    record_count (external truth, not self-counted), and skipped = the independent count of (seen −
    kept), those actually scanned in seen but not written to a table -> the identity is broken, so
    silent data loss can really be found.

    Same convention as run_m1.compute_slice_tally_counts:
      seen = distinct works seen by pass-B; kept = distinct works really written to works
      (merged["kept"]); expected = compute_expected_from_manifest(manifest, entity); skipped = |seen
      − kept|; failed = 0.
      The reconcile arm expected == kept + failed + skipped is now a real test: a silently truncated
      shard -> seen shrinks -> kept+skipped shrinks -> no longer matches the manifest expected ->
      HALT (no more fake balancing).
    C20: the seen ledger is streamed - merged["seen_spill_paths"] are the sorted-run files the
    workers wrote to disk; here they are k-way merged and the distinct count and |seen − kept| are
    counted as a stream with adjacent dedup, with semantics equal to the old `set(merged["seen"])`
    one for one (tolerance-0 semantics unchanged); the ledger no longer enters main-process memory
    (measured: 510M IDs were a memory hog). The kept set is also consumed by pass-C and stays in
    memory (about 46.5M, not what this item is about); it is referenced directly here, not copied.
    diff_tolerance is an identification placeholder: None -> RedlineUnsigned is passed through (no
    default is ever slipped in); rule-neutral, tolerance unchanged.
    """
    from m1_ingest import reconcile_m1 as REC

    kept_ids = merged["kept"]        # Read-only membership test, no copy (the old set() copy doubled memory for nothing)
    # skipped is counted independently: seen when scanned but not written to a table (purely
    # legitimate out-of-department skips) -- no longer derived back from expected (breaks the
    # fake-reconcile identity).
    _n_seen, n_skipped = _count_distinct_and_skipped(
        merged.get("seen_spill_paths") or [], kept_ids
    )
    # expected = the manifest's external truth (not the self-counted seen∪kept); only then can
    # silent data loss be found.
    expected = REC.compute_expected_from_manifest(manifest, entity=entity)
    return REC.reconcile_pass(
        expected=expected,
        kept=len(kept_ids),
        failed=0,
        # A12 identity arm pass-through: by design, in the M1 streaming path a shard-level failure
        # goes to M0 refetch and failed is always 0 at the table-building stage -> the failure
        # identity set is always empty; pass the empty set (rather than None, which falls back to
        # the count arm) so arm 3 uses the identity-containment test -- if a real failure-producing
        # point appears later, swap in the real set; the wire is no longer cut.
        failed_ids=set(),
        skipped=n_skipped,
        stage=stage,
        tally_path=tally_path,
        diff_tolerance=diff_tolerance,
    )


# ===========================================================================
# Fold HashBucketWriter's part manifest into the table meta that run_manifest takes (sha + row
# count).
# ===========================================================================
def _table_meta_from_parts(parts: list[dict]) -> dict:
    """Bucket part manifest -> {sha256, row_count, rel_path} (for run_manifest/provenance).

    A bucketed table has several parts: row_count = sum of the parts' row counts; sha256 = the
    parts' shas concatenated and hashed again (deterministic aggregation, independent of part order
    -> already sorted by rel_path); rel_path = the table root (several parts do not point to one
    file).
    """
    import hashlib

    total_rows = sum(p["row_count"] for p in parts)
    h = hashlib.sha256()
    for p in sorted(parts, key=lambda e: e["rel_path"]):
        h.update(p["rel_path"].encode("utf-8"))
        h.update(p["sha256"].encode("utf-8"))
    return {
        "sha256": h.hexdigest(),
        "row_count": total_rows,
        "rel_path": ".",
    }
