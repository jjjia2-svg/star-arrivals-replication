"""M1 resumable pass-A (seed scan with resume) - checkpoint every N shards; after a crash, a restart skips scanned shards and continues.

Root cause: pass-A of a full run is a single ~10h scan with no resume -> one disk hiccup / crash = everything lost (one such incident lost 9 hours).
This module turns pass-A into "shard iteration + periodic checkpoint + restart skips done_shards".
Invariant: resumed result == one full scan (pass-A is idempotent: the seed set de-duplicates, first_pub takes the min, commutative and associative).
It does not build seen_authors (only for reconciliation, off in the smoke test) -> saves memory (one of the pressure sources at crash time).
Checkpoint is crash-safe: two slots slot_a/slot_b + atomic switch of the CURRENT pointer - a crash in the middle of writing leaves CURRENT pointing at the old complete checkpoint.
Neutral on identification choices: only replaces the scan driver + checkpoint; seed detection reuses passes._work_is_seed (institution folding is only called, never changed).
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

from common.atomic_io import atomic_write_bytes
from common.snapshot_reader import iter_jsonl_gz_shards
from m1_ingest import passes as P
from m1_ingest.first_pub import FirstPubAccumulator

_SLOTS = ("slot_a", "slot_b")


def _write_ids_parquet(path: Path, ids: Iterable[str]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table({"v": sorted(ids)})  # Sorted -> deterministic checkpoint (the internal order of a set is irrelevant)
    sink = io.BytesIO()
    pq.write_table(table, sink)
    atomic_write_bytes(path, sink.getvalue())


def _read_ids_parquet(path: Path) -> set:
    import pyarrow.parquet as pq

    if not path.exists():
        return set()
    return set(pq.read_table(str(path)).column("v").to_pylist())


def _write_first_pub_parquet(path: Path, first_pub) -> None:
    """Stream-write the first_pub checkpoint (ParquetWriter in chunks -> the peak is one chunk, avoids a ~10GB spike / OOM).
    Written directly (an uncommitted slot only becomes live when CURRENT is committed, so per-file atomicity is not needed); a final fsync makes it durable before CURRENT is switched."""
    import os
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = pa.schema([("author_id", pa.string()), ("first_pub_year", pa.int64())])
    writer = pq.ParquetWriter(str(path), schema)
    wrote = False
    try:
        for chunk in first_pub.iter_rows_chunks():
            writer.write_table(pa.table(
                {"author_id": [r["author_id"] for r in chunk],
                 "first_pub_year": [r["first_pub_year"] for r in chunk]}, schema=schema))
            wrote = True
        if not wrote:  # Empty accumulator -> write 0 rows (correct schema)
            writer.write_table(pa.table(
                {"author_id": pa.array([], pa.string()),
                 "first_pub_year": pa.array([], pa.int64())}, schema=schema))
    finally:
        writer.close()
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_current(ckpt_dir: Path) -> Optional[str]:
    p = ckpt_dir / "CURRENT"
    if not p.exists():
        return None
    name = p.read_text(encoding="utf-8").strip()
    return name if name in _SLOTS else None


def save_checkpoint(ckpt_dir, *, done_shards, seed_authors, seed_work_ids, first_pub) -> None:
    """Atomic checkpoint (two slots + CURRENT switch): write the non-current slot -> then point CURRENT at it (the old checkpoint stays valid until the moment of the switch)."""
    ckpt_dir = Path(ckpt_dir)
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    cur = _read_current(ckpt_dir)
    target = _SLOTS[1] if cur == _SLOTS[0] else _SLOTS[0]  # Write to the other slot
    slot = ckpt_dir / target
    slot.mkdir(parents=True, exist_ok=True)
    _write_ids_parquet(slot / "seed_authors.parquet", seed_authors)
    _write_ids_parquet(slot / "seed_work_ids.parquet", seed_work_ids)
    _write_first_pub_parquet(slot / "first_pub.parquet", first_pub)
    atomic_write_bytes(
        slot / "done_shards.json",
        json.dumps(sorted(done_shards), ensure_ascii=False).encode("utf-8"),
    )
    # The last step atomically switches CURRENT -> from this moment the new checkpoint is live; a crash in any earlier step leaves CURRENT pointing at the old complete checkpoint.
    atomic_write_bytes(ckpt_dir / "CURRENT", target.encode("utf-8"))


def load_checkpoint(ckpt_dir) -> Optional[dict]:
    """Read the latest complete checkpoint (the slot CURRENT points to); none -> None."""
    ckpt_dir = Path(ckpt_dir)
    cur = _read_current(ckpt_dir)
    if cur is None:
        return None
    slot = ckpt_dir / cur
    done_p = slot / "done_shards.json"
    if not done_p.exists():
        return None
    return {
        "done_shards": json.loads(done_p.read_text(encoding="utf-8")),
        "seed_authors": _read_ids_parquet(slot / "seed_authors.parquet"),
        "seed_work_ids": _read_ids_parquet(slot / "seed_work_ids.parquet"),
        "first_pub_path": str(slot / "first_pub.parquet"),  # Path, so the driver can restore as a stream (not read the whole table)
    }


def pass_a_seed_authors_resumable(
    shard_paths,
    *,
    econ_dept_ids: set,
    registry_by_id: Mapping[str, dict],
    first_pub: FirstPubAccumulator,
    ckpt_dir,
    checkpoint_every_n: int = 100,
    _crash_hook: Optional[Callable[[int], None]] = None,
) -> "P.PassAResult":
    """Scan seeds (with resume): iterate shards -> update seed/first_pub per shard -> checkpoint every N shards -> a restart skips done_shards.

    A resumed run == a full scan (idempotent). Does not build seen_authors (saves memory; not used on the streaming path).
    """
    done: set = set()
    seed_authors: set = set()
    seed_work_ids: set = set()

    ckpt = load_checkpoint(ckpt_dir)
    if ckpt is not None:
        done = set(ckpt["done_shards"])
        seed_authors = set(ckpt["seed_authors"])
        seed_work_ids = set(ckpt["seed_work_ids"])
        first_pub.load_from_parquet(ckpt["first_pub_path"])  # Stream restore, avoids the spike / OOM

    since = 0
    for i, sp in enumerate(shard_paths):
        # The done-key uses the partition-relative path (updated_date=X/part_N.gz), never the basename -
        #   different updated_date partitions all have a part_0000.gz, so basenames would collide -> a shard wrongly judged "already scanned" is skipped = missing data.
        sid = f"{Path(sp).parent.name}/{Path(sp).name}"
        if sid in done:
            continue  # Already scanned -> skip (resume)
        for _sid, work in iter_jsonl_gz_shards([sp]):
            year = work.get("publication_year")
            is_seed, seed_here = P._work_is_seed(
                work, econ_dept_ids=econ_dept_ids, registry_by_id=registry_by_id
            )
            if is_seed:
                seed_authors |= seed_here
                wid = P._bare(work.get("id"))
                if wid is not None:
                    seed_work_ids.add(wid)
            for author_id, _inst in P._iter_authorships(work):
                if author_id is not None and year is not None:
                    first_pub.add(author_id=author_id, publication_year=year)
        done.add(sid)
        since += 1
        if since >= checkpoint_every_n:
            save_checkpoint(ckpt_dir, done_shards=done, seed_authors=seed_authors,
                            seed_work_ids=seed_work_ids, first_pub=first_pub)
            since = 0
        if _crash_hook is not None:
            _crash_hook(i)

    save_checkpoint(ckpt_dir, done_shards=done, seed_authors=seed_authors,
                    seed_work_ids=seed_work_ids, first_pub=first_pub)
    return P.PassAResult(seed_authors=seed_authors, seed_work_ids=seed_work_ids)


# ===========================================================================
# Parallel pass-A (scan_workers) - single-threaded scanning of 620GB at ~7-10MiB/s is the bottleneck of the whole run,
# and the accumulation is a set union + min (commutative and associative) -> scan shards in parallel, merge per round; the result equals the serial one record by record.
# Round structure: each round takes checkpoint_every_n shards -> splits them contiguously among n_workers -> merge -> checkpoint (same checkpoint format as serial,
# so serial/parallel runs can resume each other). Neutral on identification choices: the worker body is the same logic as the serial one, seed detection is untouched.
# ===========================================================================
def _chunk_contiguous_local(items: list, n: int) -> list[list]:
    """Split contiguously into n batches (same semantics as stream_build._chunk_contiguous; copied locally to avoid an import cycle)."""
    if n <= 1 or len(items) <= 1:
        return [list(items)] if items else []
    size = (len(items) + n - 1) // n
    return [items[i:i + size] for i in range(0, len(items), size)]


def _pass_a_scan_worker(payload: dict) -> dict:
    """spawn-safe worker: scan its own batch of shards -> return (done sids, seed set, min first_pub of this batch)."""
    # Aligned with stream_build._m1_worker_entry/_pass_c_worker_entry: spawned child processes explicitly add a sys.path bridge
    # (in some environments spawn does not pass the parent path).
    import pathlib
    import sys as _sys
    _units = next(p for p in pathlib.Path(__file__).resolve().parents if p.name == "units")
    for _sub in ("u0_foundation", "u1_fetch"):
        _src = str(_units / _sub / "src")
        if _src not in _sys.path:
            _sys.path.insert(0, _src)

    fp = FirstPubAccumulator(author_cmap=payload.get("author_cmap_flat"))
    seed_authors: set = set()
    seed_work_ids: set = set()
    done: list[str] = []
    econ_dept_ids = payload["econ_dept_ids"]
    registry_by_id = payload["registry_by_id"]
    for sp in payload["shard_paths"]:
        sid = f"{Path(sp).parent.name}/{Path(sp).name}"
        for _sid, work in iter_jsonl_gz_shards([sp]):
            year = work.get("publication_year")
            is_seed, seed_here = P._work_is_seed(
                work, econ_dept_ids=econ_dept_ids, registry_by_id=registry_by_id
            )
            if is_seed:
                seed_authors |= seed_here
                wid = P._bare(work.get("id"))
                if wid is not None:
                    seed_work_ids.add(wid)
            for author_id, _inst in P._iter_authorships(work):
                if author_id is not None and year is not None:
                    fp.add(author_id=author_id, publication_year=year)
        done.append(sid)
    pairs = [(r["author_id"], r["first_pub_year"])
             for chunk in fp.iter_rows_chunks() for r in chunk]
    return {"done": done, "seed_authors": seed_authors,
            "seed_work_ids": seed_work_ids, "first_pub_pairs": pairs}


def pass_a_seed_authors_parallel(
    shard_paths,
    *,
    econ_dept_ids: set,
    registry_by_id: Mapping[str, dict],
    first_pub: FirstPubAccumulator,
    ckpt_dir,
    n_workers: int,
    checkpoint_every_n: int = 100,
    author_cmap_flat: Optional[Mapping[str, str]] = None,
    _crash_hook: Optional[Callable[[int], None]] = None,
) -> "P.PassAResult":
    """Scan seeds in parallel (with resume): each round hands checkpoint_every_n shards to n_workers to scan in parallel -> merge -> checkpoint.

    Invariants (pinned by test_parallel_scan): parallel == serial (min/union are order-independent); resumed == one run.
    Shares the checkpoint format with the serial resumable version -> the two versions can pick up each other's runs.
    """
    import multiprocessing as mp

    done: set = set()
    seed_authors: set = set()
    seed_work_ids: set = set()

    ckpt = load_checkpoint(ckpt_dir)
    if ckpt is not None:
        done = set(ckpt["done_shards"])
        seed_authors = set(ckpt["seed_authors"])
        seed_work_ids = set(ckpt["seed_work_ids"])
        first_pub.load_from_parquet(ckpt["first_pub_path"])

    remaining = [sp for sp in shard_paths
                 if f"{Path(sp).parent.name}/{Path(sp).name}" not in done]
    if not remaining:
        save_checkpoint(ckpt_dir, done_shards=done, seed_authors=seed_authors,
                        seed_work_ids=seed_work_ids, first_pub=first_pub)
        return P.PassAResult(seed_authors=seed_authors, seed_work_ids=seed_work_ids)

    round_size = max(checkpoint_every_n, n_workers)
    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=n_workers) as pool:
        for r0 in range(0, len(remaining), round_size):
            batch = remaining[r0:r0 + round_size]
            payloads = [
                dict(shard_paths=list(c), econ_dept_ids=econ_dept_ids,
                     registry_by_id=dict(registry_by_id),
                     author_cmap_flat=dict(author_cmap_flat) if author_cmap_flat else None)
                for c in _chunk_contiguous_local(batch, n_workers)
            ]
            for out in pool.map(_pass_a_scan_worker, payloads):
                seed_authors |= out["seed_authors"]
                seed_work_ids |= out["seed_work_ids"]
                for a, y in out["first_pub_pairs"]:
                    first_pub.add(author_id=a, publication_year=y)
                done.update(out["done"])
            save_checkpoint(ckpt_dir, done_shards=done, seed_authors=seed_authors,
                            seed_work_ids=seed_work_ids, first_pub=first_pub)
            if _crash_hook is not None:
                _crash_hook(r0)

    return P.PassAResult(seed_authors=seed_authors, seed_work_ids=seed_work_ids)
