"""Red test for C19 fetch work allocation: static equal split by shard count -> byte-weighted
buckets + dynamic work claiming.

Background:
  A static equal split by shard count leaves a straggler tail: the tail shards are fat, 6 of
  8 workers finish and sit idle, CPU drops from 43% to 12%, and the ETA slips by about 9h.
  Options: a dynamic work-claiming queue, or byte-weighted buckets, or largest-shards-first
  ordering.
  Note: pass-A is cut into small rounds (short tail, not covered here); pass-B/C cut the
  whole input into chunks once, which magnifies the imbalance over the whole run.

This implementation = cut contiguous chunks by bytes (byte-bucketed) + number of chunks >
number of workers + dynamic pool dispatch (work-claiming queue).
Determinism rule: chunks must be contiguous slices of the input order and their concatenation
== the original input; otherwise the global first-seen order replay of authors/institutions
breaks (the existing guard for parallel == serial byte parity).
The red tests check only allocator behaviour, wiring and fixture-level parity; they never run
on real data.
"""
from __future__ import annotations

import gzip
import json

import pytest

pa = pytest.importorskip("pyarrow")

from identity.golden import MONASH_CANONICAL_ID

_REGISTRY = [{"openalex_id": MONASH_CANONICAL_ID, "type": "education"}]
_ECON = {MONASH_CANONICAL_ID}


# ---------------------------------------------------------------------------
# Pure allocator behaviour (sizes injected, no filesystem access)
# ---------------------------------------------------------------------------
def test_allocator_chunks_contiguous_and_complete():
    """Determinism rule: contiguous slices whose concatenation == the original input (order
    untouched)."""
    from m1_ingest import stream_build as S

    paths = [f"p{i:03d}.gz" for i in range(37)]
    sizes = [(i * 7919) % 97 + 1 for i in range(37)]   # pseudo-random but deterministic
    chunks = S._chunk_contiguous_by_bytes(paths, 4, sizes=sizes)
    flat = [p for c in chunks for p in c]
    assert flat == paths, "Concatenated chunks must equal the original input exactly (contiguous split, never reordered)"
    assert all(c for c in chunks), "No empty chunks allowed"


def test_allocator_feeds_dynamic_queue_more_chunks_than_workers():
    """Dynamic claiming: with enough shards, number of chunks > number of workers (the pool queue
    has depth, so idle workers always find work)."""
    from m1_ingest import stream_build as S

    paths = [f"p{i:03d}.gz" for i in range(200)]
    sizes = [10] * 200
    chunks = S._chunk_contiguous_by_bytes(paths, 8, sizes=sizes)
    assert len(chunks) > 8, f"Chunk count ({len(chunks)}) must exceed the worker count (8) for a work-claiming queue to exist"


def test_allocator_byte_bucketed_fat_tail_beats_count_split():
    """Observed shape: the shards late in updated_date are very fat -> an equal split by shard count
    piles the fat tail onto one worker.
    With byte buckets, the fattest chunk's bytes must be <= the fattest share of the old equal split
    by shard count (n_workers shares)."""
    from m1_ingest import stream_build as S

    paths = [f"p{i:03d}.gz" for i in range(16)]
    sizes = [1] * 8 + [20] * 8            # fat tail (168 bytes in total)
    chunks = S._chunk_contiguous_by_bytes(paths, 2, sizes=sizes)
    size_of = dict(zip(paths, sizes))
    byte_max = max(sum(size_of[p] for p in c) for c in chunks)

    old = S._chunk_contiguous(paths, 2)   # old way: equal split by shard count into n_workers shares
    old_max = max(sum(size_of[p] for p in c) for c in old)

    assert byte_max < old_max, (
        f"The fattest chunk under byte-based bucketing ({byte_max}) must be smaller than the fattest share under an equal split by file count ({old_max})"
    )
    # upper bound by construction: one chunk <= target bytes + largest single shard (the greedy step
    # may overshoot by one shard).
    total = sum(sizes)
    n_chunks_target = 2 * S._C19_CHUNKS_PER_WORKER
    assert byte_max <= total / n_chunks_target + max(sizes)


def test_allocator_zero_sizes_falls_back_to_count_split():
    """sizes all 0 (empty files / stat failure) -> fall back to an equal split by shard count; there
    is a floor, no division by zero."""
    from m1_ingest import stream_build as S

    paths = [f"p{i}.gz" for i in range(10)]
    chunks = S._chunk_contiguous_by_bytes(paths, 2, sizes=[0] * 10)
    flat = [p for c in chunks for p in c]
    assert flat == paths
    assert all(c for c in chunks)


def test_allocator_sizes_length_mismatch_raises():
    """sizes and paths of different length = caller bug -> fail loudly, never truncate silently."""
    from m1_ingest import stream_build as S

    with pytest.raises(ValueError):
        S._chunk_contiguous_by_bytes(["a", "b"], 2, sizes=[1])


# ---------------------------------------------------------------------------
# Wiring + parity: the parallel batching of the pass-B / pass-C path source must use the byte
# allocator, and parallel == serial bytes
# ---------------------------------------------------------------------------
def _inst(iid, country):
    return {"id": f"https://openalex.org/{iid}", "display_name": iid,
            "country_code": country, "type": "education",
            "lineage": [f"https://openalex.org/{iid}"]}


def _au(aid, insts, raw):
    return {"author": {"id": f"https://openalex.org/{aid}", "display_name": aid, "orcid": None},
            "institutions": insts, "raw_affiliation_strings": raw}


def _work(wid, year, refs, aus, title):
    return {"id": f"https://openalex.org/{wid}", "publication_year": year, "type": "article",
            "cited_by_count": 7,
            "referenced_works": [f"https://openalex.org/{r}" for r in refs],
            "primary_topic": {"subfield": {"id": "https://openalex.org/subfields/2002"}},
            "authorships": aus, "title": title}


def _mk_gz_shards(tmp_path, n_shards=6, works_per_shard=3):
    """Multi-gz-shard fixture: seeds (Monash) and cited works are mixed across shards (pass-C has
    work to do), sizes uneven."""
    snap = tmp_path / "snap" / "works" / "updated_date=2020-01-01"
    snap.mkdir(parents=True)
    paths = []
    wid = 0
    for s in range(n_shards):
        rows = []
        for _ in range(works_per_shard + (s % 3) * 2):   # shard sizes deliberately uneven
            wid += 1
            if wid % 3 == 0:
                rows.append(_work(
                    f"W_S{wid:03d}", 2000 + wid % 20,
                    refs=[f"W_R{wid - 1:03d}", f"W_R{wid - 2:03d}"],
                    aus=[_au(f"A_M{wid % 5}", [_inst(MONASH_CANONICAL_ID, "AU")],
                             ["Monash University, Department of Economics"]),
                         _au(f"A_X{wid}", [_inst("I_STK", "SE")], ["Stockholm"])],
                    title=f"seed {wid}"))
            else:
                rows.append(_work(f"W_R{wid:03d}", 1995 + wid % 25, refs=[],
                                  aus=[_au(f"A_O{wid}", [_inst("I_STK", "SE")], ["Stockholm"])],
                                  title=f"ref {wid}"))
        gz = snap / f"part_{s:04d}.gz"
        with gzip.open(gz, "wt", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        paths.append(str(gz))
    return paths


def _sig(manifest_for_table):
    return sorted((p["rel_path"], p["sha256"]) for p in manifest_for_table)


def test_path_source_parallel_uses_byte_allocator_and_byte_equals_serial(monkeypatch, tmp_path):
    """Wiring red test: the parallel path source (pass-B n_workers>1 and pass-C scan_workers>1) must
    call the byte allocator; and after the new batching, parallel == serial for every table and
    bucket, with all (rel_path, sha256) equal (the determinism guard must not break)."""
    from m1_ingest import stream_build as S

    paths = _mk_gz_shards(tmp_path)
    calls = []
    real = S._chunk_contiguous_by_bytes

    def _spy(paths_in, n, **kw):
        calls.append((len(list(paths_in)), n))
        return real(paths_in, n, **kw)

    monkeypatch.setattr(S, "_chunk_contiguous_by_bytes", _spy)

    ser = S.run_m1_streaming(
        S.ShardPathSource(paths), S.ShardPathSource(paths),
        registry=_REGISTRY, econ_dept_ids=_ECON,
        out_root=tmp_path / "ser", n_workers=1, scan_workers=1,
    )
    assert calls == [], "The serial path must not split into batches and must not touch the allocator"

    par = S.run_m1_streaming(
        S.ShardPathSource(paths), S.ShardPathSource(paths),
        registry=_REGISTRY, econ_dept_ids=_ECON,
        out_root=tmp_path / "par", n_workers=3, scan_workers=2,
    )
    assert len(calls) >= 2, (
        f"Parallel batching of path sources in both pass-B and pass-C must go through the byte allocator ({len(calls)} actual calls)"
    )
    for tbl in ser:
        assert _sig(par[tbl]) == _sig(ser[tbl]), f"{tbl}: parallel != serial (C19 broke determinism)"
