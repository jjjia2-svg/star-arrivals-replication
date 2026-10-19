"""Tests for parallel scanning (scan_workers): pass A and pass C move from one thread to many cores, and the result must stay byte-identical.

Background (measured in the cloud): single-threaded pass A/C runs at about 7-10 MiB/s, and 14 of the 16 cores of
the machine sit idle, so a full run takes about 36 h. Both scans are naturally parallel: the pass-A
accumulation is a set union plus min (commutative and associative); pass C filters each shard independently,
and its output goes through HashBucketWriter local buckets plus the existing reduce, which merges stably
(same as pass B, already pinned by the byte-level guard).

Invariants pinned:
  1. Parallel pass A == serial pass A (the seed set and the full-history first_pub min are equal row by row).
  2. Parallel + crash resume == one full scan.
  3. End to end: the 10-table parts (rel_path, sha256) of run_m1_streaming(scan_workers=3)
     == those with scan_workers=1, exactly (including the reduce merge after pass-C parallel bucketing).
Definition-neutral: only the scheduling changes; seed rule, fields and thresholds are untouched.
"""
from __future__ import annotations

import gzip
import json

import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

from identity.golden import MONASH_CANONICAL_ID
from m1_ingest import stream_build as S
from m1_ingest.first_pub import FirstPubAccumulator
from m1_ingest.resumable_pass_a import (
    pass_a_seed_authors_parallel,
    pass_a_seed_authors_resumable,
)

_REGISTRY = [{"openalex_id": MONASH_CANONICAL_ID, "type": "education"}]
_ECON = {MONASH_CANONICAL_ID}
_REG_BY_ID = {MONASH_CANONICAL_ID: {"openalex_id": MONASH_CANONICAL_ID, "type": "education"}}


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


def _mk_shards(tmp_path, n_partitions=4, works_per_shard=3):
    """Write the fixture works into multi-partition gz shards (pins partition-relative done-keys + cross-shard parallelism).
    Each partition has 2 shards; seed works (Monash) and cited works are interleaved so the frontier crosses shards."""
    paths = []
    wid = 0
    for p in range(n_partitions):
        pdir = tmp_path / f"updated_date=2020-0{p + 1}-01"
        pdir.mkdir(parents=True)
        for s in range(2):
            rows = []
            for _ in range(works_per_shard):
                wid += 1
                if wid % 3 == 0:  # every third work is a Monash seed, citing two other works
                    rows.append(_work(
                        f"W_S{wid:03d}", 2000 + wid % 20,
                        refs=[f"W_R{wid - 1:03d}", f"W_R{wid - 2:03d}"],  # it cites two non-seed works (they really exist -> no dangling refs)
                        aus=[_au(f"A_M{wid % 5}", [_inst(MONASH_CANONICAL_ID, "AU")],
                                 ["Monash University, Department of Economics"]),
                             _au(f"A_X{wid}", [_inst("I_STK", "SE")], ["Stockholm"])],
                        title=f"seed {wid}"))
                else:  # non-seed; some of them are exactly the W_R targets cited by other seeds
                    rows.append(_work(
                        f"W_R{wid:03d}", 1995 + wid % 25, refs=[],
                        aus=[_au(f"A_O{wid}", [_inst("I_STK", "SE")], ["Stockholm"])],
                        title=f"ref {wid}"))
            gz = pdir / f"part_{s:04d}.gz"
            with gzip.open(gz, "wt", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(json.dumps(r) + "\n")
            paths.append(str(gz))
    return paths


def _fp_rows(fp: FirstPubAccumulator) -> dict:
    return {r["author_id"]: r["first_pub_year"] for chunk in fp.iter_rows_chunks() for r in chunk}


def test_parallel_pass_a_equals_serial(tmp_path):
    paths = _mk_shards(tmp_path / "snap")
    fp_s = FirstPubAccumulator()
    ser = pass_a_seed_authors_resumable(
        paths, econ_dept_ids=_ECON, registry_by_id=_REG_BY_ID,
        first_pub=fp_s, ckpt_dir=tmp_path / "ck_s", checkpoint_every_n=3)
    fp_p = FirstPubAccumulator()
    par = pass_a_seed_authors_parallel(
        paths, econ_dept_ids=_ECON, registry_by_id=_REG_BY_ID,
        first_pub=fp_p, ckpt_dir=tmp_path / "ck_p", n_workers=3, checkpoint_every_n=3)
    assert set(par.seed_authors) == set(ser.seed_authors)
    assert set(par.seed_work_ids) == set(ser.seed_work_ids)
    assert _fp_rows(fp_p) == _fp_rows(fp_s), "Parallel first_pub differs from serial (min/union should not depend on order)"


def test_parallel_pass_a_resume_after_crash_equals_full(tmp_path):
    paths = _mk_shards(tmp_path / "snap")

    class _Boom(RuntimeError):
        pass

    fp1 = FirstPubAccumulator()
    calls = {"n": 0}

    def _crash(_i):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _Boom()  # crash after the first checkpoint

    with pytest.raises(_Boom):
        pass_a_seed_authors_parallel(
            paths, econ_dept_ids=_ECON, registry_by_id=_REG_BY_ID,
            first_pub=fp1, ckpt_dir=tmp_path / "ck", n_workers=3,
            checkpoint_every_n=3, _crash_hook=_crash)

    fp2 = FirstPubAccumulator()
    par = pass_a_seed_authors_parallel(
        paths, econ_dept_ids=_ECON, registry_by_id=_REG_BY_ID,
        first_pub=fp2, ckpt_dir=tmp_path / "ck", n_workers=3, checkpoint_every_n=3)

    fp_ref = FirstPubAccumulator()
    ref = pass_a_seed_authors_resumable(
        paths, econ_dept_ids=_ECON, registry_by_id=_REG_BY_ID,
        first_pub=fp_ref, ckpt_dir=tmp_path / "ck_ref", checkpoint_every_n=999)
    assert set(par.seed_authors) == set(ref.seed_authors)
    assert set(par.seed_work_ids) == set(ref.seed_work_ids)
    assert _fp_rows(fp2) == _fp_rows(fp_ref), "Parallel resumed result != single-pass full scan"


def _sig(parts):
    return sorted((p["rel_path"], p["sha256"]) for p in parts)


def test_streaming_scan_workers_end_to_end_byte_equal(tmp_path):
    paths = _mk_shards(tmp_path / "snap", n_partitions=4, works_per_shard=4)
    src1 = S.ShardPathSource(paths)
    src2 = S.ShardPathSource(paths)

    mf1 = S.run_m1_streaming(
        S.ShardPathSource(paths), src1,
        registry=_REGISTRY, econ_dept_ids=_ECON,
        out_root=tmp_path / "out1", n_workers=2,
        pass_a_ckpt_dir=str(tmp_path / "ckA1"), scan_workers=1)
    mf3 = S.run_m1_streaming(
        S.ShardPathSource(paths), src2,
        registry=_REGISTRY, econ_dept_ids=_ECON,
        out_root=tmp_path / "out3", n_workers=2,
        pass_a_ckpt_dir=str(tmp_path / "ckA3"), scan_workers=3)
    assert set(mf1.keys()) == set(mf3.keys())
    for name in mf1:
        assert _sig(mf1[name]) == _sig(mf3[name]), (
            f"Table {name}: part sha differs between scan_workers=3 and =1 (parallel scan broke byte determinism)")
