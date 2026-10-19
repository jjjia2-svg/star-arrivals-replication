"""Tests for reconcile_m1.py: fixtures check the four-number reconcile, the shard arm, dedup and two-run consistency.

Behaviour covered:
  - reconcile_pass(...): the four-number reconcile arm (expected == kept + failed + skipped), a thin wrapper
    over U0 common.reconcile.reconcile_fetch; unbalanced -> exit(TALLY_IMBALANCE=15);
    the op_id set arm is honestly closed (op_id_arm="N/A": the M1 streaming scan has no per-item op_id, and
    does not pretend to);
    diff_tolerance unset (None) -> raise (passes through the U0 placeholder rule; a default of 0 is never substituted).
  - Shard-count arm: scanned shard set == manifest shard set, otherwise exit(EXIT_RECONCILE_FAIL=TALLY_IMBALANCE 15).
  - compute_expected_from_manifest: the sum of record_count for one entity in the top-level manifest (external ground truth).
  - compact_dedup: DuckDB count(*)-count(DISTINCT pk); ==0 passes, otherwise exit(EXIT_DEDUP_NONZERO=21).
  - assert_two_run_identical: per-part row counts + the sorted PK multiset agree across two runs (deterministic reproduction).

Discipline: all tests use small fixtures to test logic and never download from S3; diff_tolerance and
identification placeholders raise on None and are never decided here.
"""
from __future__ import annotations

import pytest

from m1_ingest import reconcile_m1 as rec
from identity.exit_codes import TALLY_IMBALANCE, EXIT_DEDUP_NONZERO


# top-level manifest fixture (observed shape: entities[].files[].meta.record_count).
_MANIFEST = {
    "date": "2026-06-26",
    "format": "jsonl",
    "meta": {"record_count": 5, "content_length": 999},
    "entities": [
        {
            "entity": "works",
            "record_count": 5,
            "content_length": 999,
            "files": [
                {"url": "s3://openalex/data/jsonl/works/updated_date=2016-01-01/part_0000.gz",
                 "meta": {"content_length": 500, "record_count": 3}},
                {"url": "s3://openalex/data/jsonl/works/updated_date=2016-02-01/part_0000.gz",
                 "meta": {"content_length": 499, "record_count": 2}},
            ],
        },
    ],
}


# ---------------------------------------------------------------------------
# compute_expected_from_manifest: external ground truth (sum of record_count)
# ---------------------------------------------------------------------------
def test_compute_expected_from_manifest_sums_record_counts():
    """expected = the sum of files[].meta.record_count (3+2=5), external ground truth fed to the arithmetic arm."""
    assert rec.compute_expected_from_manifest(_MANIFEST, entity="works") == 5


# ---------------------------------------------------------------------------
# reconcile_pass: four-number reconcile arm (thin wrapper over reconcile_fetch) + op_id arm honestly N/A
# ---------------------------------------------------------------------------
def test_reconcile_pass_balanced_returns_tally_with_na_op_arm(tmp_path):
    """expected==kept+failed+skipped and diff_tolerance=0 -> the tally balances; op_id_arm is honestly marked N/A."""
    tally = rec.reconcile_pass(
        expected=5,
        kept=5,
        failed=0,
        skipped=0,
        stage="m1_works",
        tally_path=tmp_path / "tally.json",
        diff_tolerance=0,
    )
    assert tally["balanced"] is True
    # The M1 streaming scan has no per-item op_id -> the set arm is honestly closed, with no pretend op_id reconcile
    assert tally["op_id_arm"] == "N/A"


def test_reconcile_pass_imbalanced_exits_15(tmp_path):
    """expected != kept+failed+skipped -> exit(TALLY_IMBALANCE=15) (the arithmetic arm of the thin reconcile_fetch wrapper)."""
    with pytest.raises(SystemExit) as ei:
        rec.reconcile_pass(
            expected=5,
            kept=4,      # one short -> unbalanced
            failed=0,
            skipped=0,
            stage="m1_works",
            tally_path=tmp_path / "tally.json",
            diff_tolerance=0,
        )
    assert ei.value.code == TALLY_IMBALANCE


def test_reconcile_pass_unsigned_diff_tolerance_raises(tmp_path):
    """diff_tolerance=None (unset red-line placeholder) -> raise (a default of 0 is never substituted), even if the four numbers balance."""
    with pytest.raises(Exception) as ei:
        rec.reconcile_pass(
            expected=5,
            kept=5,
            failed=0,
            skipped=0,
            stage="m1_works",
            tally_path=tmp_path / "tally.json",
            diff_tolerance=None,
        )
    # not SystemExit (reconcile unbalanced) but RedlineUnsigned (placeholder not set)
    assert not isinstance(ei.value, SystemExit)


# ---------------------------------------------------------------------------
# shard-count arm: scanned shard set == manifest shard set, otherwise exit(15)
# ---------------------------------------------------------------------------
def test_reconcile_shards_arm_balanced(tmp_path):
    """Scanned shard set == manifest expected shard set -> balanced (no exit)."""
    expected = rec.expected_shard_urls_from_manifest(_MANIFEST, entity="works")
    out = rec.reconcile_scanned_shards(
        manifest_obj=_MANIFEST,
        entity="works",
        scanned_urls=list(expected),       # all scanned
        tally_path=tmp_path / "shards.json",
    )
    assert out["balanced"] is True


def test_reconcile_shards_arm_missing_exits_15(tmp_path):
    """A shard was missed in the scan -> the shard-set arm is unbalanced -> exit(EXIT_RECONCILE_FAIL=TALLY_IMBALANCE 15)."""
    expected = rec.expected_shard_urls_from_manifest(_MANIFEST, entity="works")
    short = list(expected)[:-1]            # the last shard is missed
    with pytest.raises(SystemExit) as ei:
        rec.reconcile_scanned_shards(
            manifest_obj=_MANIFEST,
            entity="works",
            scanned_urls=short,
            tally_path=tmp_path / "shards.json",
        )
    assert ei.value.code == TALLY_IMBALANCE


# ---------------------------------------------------------------------------
# compact_dedup: count(*)-count(DISTINCT pk); ==0 passes, otherwise exit(21)
# ---------------------------------------------------------------------------
def test_compact_dedup_zero_passes(tmp_path):
    """No duplicate pk -> dup=0 passes and returns 0 (no exit)."""
    pytest.importorskip("pyarrow")
    pytest.importorskip("duckdb")
    import pyarrow as pa
    import pyarrow.parquet as pq

    t = pa.table({"work_id": ["W1", "W2", "W3"], "author_id": ["A1", "A2", "A3"]})
    p = tmp_path / "part_000.parquet"
    pq.write_table(t, p)
    dup = rec.compact_dedup([p], pk_cols=("work_id", "author_id"))
    assert dup == 0


def test_compact_dedup_nonzero_exits_21(tmp_path):
    """Duplicate pk -> dup>0 -> exit(EXIT_DEDUP_NONZERO=21)."""
    pytest.importorskip("pyarrow")
    pytest.importorskip("duckdb")
    import pyarrow as pa
    import pyarrow.parquet as pq

    # (W1,A1) appears twice -> duplicate pk
    t = pa.table({"work_id": ["W1", "W1", "W2"], "author_id": ["A1", "A1", "A2"]})
    p = tmp_path / "part_000.parquet"
    pq.write_table(t, p)
    with pytest.raises(SystemExit) as ei:
        rec.compact_dedup([p], pk_cols=("work_id", "author_id"))
    assert ei.value.code == EXIT_DEDUP_NONZERO


# ---------------------------------------------------------------------------
# assert_two_run_identical: per-part row counts + sorted PK multiset agree across two runs
# ---------------------------------------------------------------------------
def test_assert_two_run_identical_same_passes(tmp_path):
    pytest.importorskip("pyarrow")
    import pyarrow as pa
    import pyarrow.parquet as pq

    run_a = tmp_path / "a"
    run_b = tmp_path / "b"
    run_a.mkdir()
    run_b.mkdir()
    t = pa.table({"work_id": ["W2", "W1"], "author_id": ["A2", "A1"]})
    pq.write_table(t, run_a / "part_000.parquet")
    pq.write_table(t, run_b / "part_000.parquet")
    # same input twice -> the PK multisets agree (after sorting), no raise
    rec.assert_two_run_identical(run_a, run_b, pk_cols=("work_id", "author_id"))


def test_assert_two_run_identical_diff_raises(tmp_path):
    pytest.importorskip("pyarrow")
    import pyarrow as pa
    import pyarrow.parquet as pq

    run_a = tmp_path / "a"
    run_b = tmp_path / "b"
    run_a.mkdir()
    run_b.mkdir()
    pq.write_table(pa.table({"work_id": ["W1"], "author_id": ["A1"]}), run_a / "part_000.parquet")
    pq.write_table(pa.table({"work_id": ["W2"], "author_id": ["A2"]}), run_b / "part_000.parquet")
    with pytest.raises(AssertionError):
        rec.assert_two_run_identical(run_a, run_b, pk_cols=("work_id", "author_id"))
