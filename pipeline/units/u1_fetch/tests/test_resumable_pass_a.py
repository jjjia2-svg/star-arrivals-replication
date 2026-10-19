"""Resumable pass A (scan for seeds): checkpoint every N shards; after a crash, restart, skip the scanned shards and continue.

Core invariant: the result of crash + restart + resume == the result of one full scan (seed_authors /
seed_work_ids / first_pub are identical one by one). The safety root is that pass A is idempotent (set
dedup plus year min, commutative and associative).
The checkpoint is crash-safe: two slots plus an atomic CURRENT pointer switch (a crash in the middle of a
write leaves CURRENT pointing at the old complete checkpoint).
"""
import gzip
import json
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from m1_ingest import passes as P  # noqa: E402
from m1_ingest.first_pub import FirstPubAccumulator  # noqa: E402
from common.snapshot_reader import iter_jsonl_gz_shards  # noqa: E402

MONASH = "I_MONASH"
REGISTRY = P.build_registry([{"openalex_id": MONASH, "type": "education"}])
ECON = {MONASH}


def _work(wid, year, authors):
    """authors = [(author_id, inst_id_or_None)]; a non-None inst means the author is attached to Monash (education)."""
    return {
        "id": f"https://openalex.org/{wid}",
        "publication_year": year,
        "authorships": [
            {"author": {"id": f"https://openalex.org/{aid}"},
             "institutions": ([{"id": f"https://openalex.org/{inst}", "type": "education"}] if inst else [])}
            for aid, inst in authors
        ],
    }


def _write_shard(path, works):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for w in works:
            f.write(json.dumps(w) + "\n")


def _make_shards(tmp_path):
    s = tmp_path / "snap"
    _write_shard(s / "a.gz", [_work("W1", 2010, [("A1", MONASH)]), _work("W2", 2005, [("A2", None)])])
    _write_shard(s / "b.gz", [_work("W3", 2003, [("A1", MONASH), ("A3", None)])])
    _write_shard(s / "c.gz", [_work("W4", 2015, [("A2", MONASH)]), _work("W5", 2001, [("A1", None)])])
    return [str(s / "a.gz"), str(s / "b.gz"), str(s / "c.gz")]


class _PosFP:
    """Positional-add adapter: pass_a_seed_authors calls first_pub.add(author_id, year) with positional arguments
    (the real run_m1 path uses the same _PositionalFirstPub); FirstPubAccumulator.add takes keyword arguments."""

    def __init__(self, fp):
        self.fp = fp

    def add(self, author_id, year):
        self.fp.add(author_id=author_id, publication_year=year)


def _full_scan(shards):
    """Non-resume reference: one full scan (pass_a_seed_authors over a flat stream)."""
    fp = FirstPubAccumulator()
    stream = (rec for sp in shards for _sid, rec in iter_jsonl_gz_shards([sp]))
    r = P.pass_a_seed_authors(stream, econ_dept_ids=ECON, registry_by_id=REGISTRY, first_pub=_PosFP(fp))
    return r.seed_authors, r.seed_work_ids, {row["author_id"]: row["first_pub_year"] for row in fp.rows()}


class _Crash(Exception):
    pass


def test_resume_after_crash_equals_full_scan(tmp_path):
    from m1_ingest.resumable_pass_a import pass_a_seed_authors_resumable

    shards = _make_shards(tmp_path)
    ref_sa, ref_sw, ref_fp = _full_scan(shards)

    ckpt = str(tmp_path / "ckpt")
    # First run: simulate a crash after shard 1 is processed (and checkpointed).
    fp1 = FirstPubAccumulator()

    def crash_after_first(i):
        if i == 0:
            raise _Crash()

    with pytest.raises(_Crash):
        pass_a_seed_authors_resumable(
            shards, econ_dept_ids=ECON, registry_by_id=REGISTRY, first_pub=fp1,
            ckpt_dir=ckpt, checkpoint_every_n=1, _crash_hook=crash_after_first,
        )

    # Restart: a fresh accumulator, restore from the checkpoint, skip the already scanned a.gz, and continue with b/c.
    fp2 = FirstPubAccumulator()
    res = pass_a_seed_authors_resumable(
        shards, econ_dept_ids=ECON, registry_by_id=REGISTRY, first_pub=fp2,
        ckpt_dir=ckpt, checkpoint_every_n=1,
    )
    got_fp = {r["author_id"]: r["first_pub_year"] for r in fp2.rows()}

    assert res.seed_authors == ref_sa, "Resumed seed_authors == full scan"
    assert res.seed_work_ids == ref_sw, "Resumed seed_work_ids == full scan"
    assert got_fp == ref_fp, "Resumed first_pub == full scan (per author)"


def test_no_crash_full_run_equals_reference(tmp_path):
    """A run to the end without a crash must also == the reference (resume logic does not change the result)."""
    from m1_ingest.resumable_pass_a import pass_a_seed_authors_resumable

    shards = _make_shards(tmp_path)
    ref_sa, ref_sw, ref_fp = _full_scan(shards)
    fp = FirstPubAccumulator()
    res = pass_a_seed_authors_resumable(
        shards, econ_dept_ids=ECON, registry_by_id=REGISTRY, first_pub=fp,
        ckpt_dir=str(tmp_path / "ckpt"), checkpoint_every_n=2,
    )
    got = {r["author_id"]: r["first_pub_year"] for r in fp.rows()}
    assert (res.seed_authors, res.seed_work_ids, got) == (ref_sa, ref_sw, ref_fp)


def test_resume_does_not_reprocess_done_shards(tmp_path, monkeypatch):
    """After a restart, scanned shards are not opened and read again (done_shards are skipped); only the rest are read."""
    from m1_ingest import resumable_pass_a as RPA
    from m1_ingest.resumable_pass_a import pass_a_seed_authors_resumable

    shards = _make_shards(tmp_path)
    ckpt = str(tmp_path / "ckpt")
    fp1 = FirstPubAccumulator()

    def crash_after_first(i):
        if i == 0:
            raise _Crash()

    with pytest.raises(_Crash):
        pass_a_seed_authors_resumable(shards, econ_dept_ids=ECON, registry_by_id=REGISTRY,
                                      first_pub=fp1, ckpt_dir=ckpt, checkpoint_every_n=1,
                                      _crash_hook=crash_after_first)

    opened = []
    real_iter = RPA.iter_jsonl_gz_shards

    def spy_iter(paths):
        opened.extend(paths)
        return real_iter(paths)

    monkeypatch.setattr(RPA, "iter_jsonl_gz_shards", spy_iter)
    fp2 = FirstPubAccumulator()
    pass_a_seed_authors_resumable(shards, econ_dept_ids=ECON, registry_by_id=REGISTRY,
                                  first_pub=fp2, ckpt_dir=ckpt, checkpoint_every_n=1)
    opened_names = {pathlib.Path(p).name for p in opened}
    assert "a.gz" not in opened_names, "An already scanned a.gz should not be reopened"
    assert {"b.gz", "c.gz"} <= opened_names, "The remaining b/c should be scanned"


def test_same_basename_different_partitions_all_processed(tmp_path):
    """Real-data pitfall (basename collision): part_0000.gz exists in different updated_date partitions, so all of them
    must be scanned; a later one must never be skipped as "already scanned" because its basename is the same (that
    would lose data). The done-key must be the relative path, not the basename."""
    from m1_ingest.resumable_pass_a import pass_a_seed_authors_resumable

    s = tmp_path / "snap"
    _write_shard(s / "updated_date=2016-01-01" / "part_0000.gz", [_work("W1", 2010, [("A1", MONASH)])])
    _write_shard(s / "updated_date=2016-02-01" / "part_0000.gz", [_work("W2", 2011, [("A2", MONASH)])])
    shards = [
        str(s / "updated_date=2016-01-01" / "part_0000.gz"),
        str(s / "updated_date=2016-02-01" / "part_0000.gz"),
    ]
    fp = FirstPubAccumulator()
    res = pass_a_seed_authors_resumable(
        shards, econ_dept_ids=ECON, registry_by_id=REGISTRY,
        first_pub=fp, ckpt_dir=str(tmp_path / "ckpt"), checkpoint_every_n=10,
    )
    assert res.seed_authors == {"A1", "A2"}, "Same basename in different partitions must both be scanned (a basename clash must not skip)"
    assert {"W1", "W2"} <= res.seed_work_ids
