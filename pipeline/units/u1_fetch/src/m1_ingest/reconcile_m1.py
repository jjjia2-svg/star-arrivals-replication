"""M1-T7 reconcile_m1 - four-number reconciliation after M1 streams the tables out + shard arm + de-duplication + two-run consistency.

Why it is needed (guards against the root cause of the Sydney 27k silent data loss):
  M0 reconcile (manifest_reconcile.py) covers "shard download completeness" (expected .gz == downloaded .gz).
  The M1 side covers "after records are expanded into the derived tables, do the counts match the manifest's external truth" -
  after scanning the snapshot and writing the tables, the books must be counted: is the expected record count (sum of manifest record_count)
  == kept + failed + skipped, is the set of scanned shards == the manifest's expected shard set, and are there duplicate PKs in the derived tables.
  Any imbalance -> HALT, never silent.

What this module does:
  1. compute_expected_from_manifest(manifest, *, entity): external truth = sum of record_count of the entity.
  2. expected_shard_urls_from_manifest(manifest, *, entity): list of expected shard urls of the entity (thin wrapper around M0).
  3. reconcile_pass(...): four-number reconciliation arm, thin wrapper around U0 common.reconcile.reconcile_fetch -
       expected == kept + failed + skipped (tolerance diff_tolerance).
       The op_id set arm is honestly closed: the M1 stream scan has no per-record op_id, so an empty set is fed -> the set arm balances trivially,
         and the tally's op_id_arm is marked "N/A" (no pretence of per-record op_id reconciliation; schema.TALLY allows N/A).
       diff_tolerance unset (None) -> reconcile_fetch raises RedlineUnsigned, propagated (never silently defaults to 0).
       Imbalance -> reconcile_fetch exit(TALLY_IMBALANCE=15).
  4. reconcile_scanned_shards(...): shard-count arm, thin wrapper around M0 reconcile_shards -
       the scanned shard set == the manifest's expected shard set, otherwise exit(EXIT_RECONCILE_FAIL=TALLY_IMBALANCE 15).
  5. compact_dedup(parquet_paths, *, pk_cols): DuckDB count(*)-count(DISTINCT pk);
       ==0 passes and returns 0, otherwise exit(EXIT_DEDUP_NONZERO=21) (duplicate PKs = the expansion logic missed de-duplication).
  6. assert_two_run_identical(run_a, run_b, *, pk_cols): per-part row counts + sorted PK multiset
       equal across two runs (deterministic reproduction; unequal -> AssertionError).

Reuses U0 / M0, no rewrite:
  - U0 common.reconcile.reconcile_fetch (three arms + placeholder rule + exit 15).
  - M0 manifest_reconcile.{expected_record_count_from_files, list_expected_shards, reconcile_shards}
    (top-level manifest parsing + shard-set reconciliation; measured shape entities[].files[]).
  - exit_codes: TALLY_IMBALANCE(15) / EXIT_DEDUP_NONZERO(21) (no bare numbers).

Neutral on identification choices: reconciliation / de-duplication / reproduction are cross-cutting engineering and touch no identification rule.
  The only point touching an identification choice is diff_tolerance (unset -> the raise propagates, the allowed difference is never chosen here).
"""
from __future__ import annotations

import pathlib
import sys
from typing import Any, Iterable, Mapping, Sequence

# U0 foundation: four-number three-arm reconciliation (placeholder rule + exit 15).
from common.reconcile import reconcile_fetch
# M0 sibling module: top-level manifest parsing + shard-set reconciliation (measured shape entities[].files[]).
from m0_snapshot.manifest_reconcile import (
    expected_record_count_from_files,
    list_expected_shards,
    reconcile_shards,
)
# Single source of truth for exit codes (no bare numbers).
from identity.exit_codes import EXIT_DEDUP_NONZERO


# ===========================================================================
# External truth from the manifest (thin wrapper around M0)
# ===========================================================================
def compute_expected_from_manifest(manifest_obj: Mapping[str, Any], *, entity: str) -> int:
    """Expected record count = sum of files[].meta.record_count of the entity (external truth, feeds the arithmetic arm).

    Thin wrapper around M0 expected_record_count_from_files (top-level manifest entities[].files[] shape).
    """
    return expected_record_count_from_files(manifest_obj, entity=entity)


def expected_shard_urls_from_manifest(manifest_obj: Mapping[str, Any], *, entity: str) -> list[str]:
    """Expected shard url list of the entity (manifest order is kept -> deterministic; thin wrapper around M0 list_expected_shards)."""
    return list_expected_shards(manifest_obj, entity=entity)


# ===========================================================================
# Four-number reconciliation arm (thin wrapper around U0 reconcile_fetch; the op_id arm is honestly N/A)
# ===========================================================================
def reconcile_pass(
    *,
    expected: int,
    kept: int,
    failed: int,
    skipped: int,
    stage: str,
    tally_path: pathlib.Path | str,
    refetch_queue: set[str] | None = None,
    failed_ids: set[str] | None = None,
    diff_tolerance: Any,
) -> dict[str, Any]:
    """Four-number reconciliation: expected == kept + failed + skipped (thin wrapper around reconcile_fetch).

    Args:
        expected: the external truth (from compute_expected_from_manifest), not a number M1 counted itself
                  (counting and checking against itself is a fake balance; the manifest must be the external anchor).
        kept/failed/skipped: M1's four scan numbers.
        failed_ids: set of failed op_id identities (passed through): if given ->
                    arm 3 checks identity inclusion (failed_ids subset of refetch_queue); a queue with enough entries but wrong members
                    (wrong ones enqueued / a truly failed one absent) also HALTs; if not given (None) -> falls back to the old count check.
        diff_tolerance: tolerance (identification placeholder); must be passed explicitly -
                        None -> reconcile_fetch raises RedlineUnsigned (never silently defaults to 0);
                        0 / some value -> balance is judged with that tolerance.
    Returns (only when the reconciliation balances):
        tally dict (keys aligned with schema.TALLY), in which op_id_arm is relabelled "N/A" -
        the M1 stream scan has no per-record op_id and does not pretend to have run the set arm (schema.TALLY allows N/A).
    Raises / exits:
        RedlineUnsigned - diff_tolerance unset (None), propagated from reconcile_fetch.
        SystemExit(TALLY_IMBALANCE=15) - arithmetic arm imbalance, triggered by reconcile_fetch.

    The op_id set arm is honestly closed: feeding empty sets op_ids_expected/op_ids_seen -> the set arm balances trivially
      (empty minus empty = no missing/extra), then the returned tally's op_id_arm is overwritten with "N/A".
    Refetch precondition arm: the M1 stream scan has no refetch queue, so failed must be 0 to balance (failures without a queue -> arm 3 HALTs);
      on the M1 path shard-level failures belong to M0 refetch, so the expected failed count at the expansion stage is always 0.
    """
    tally = reconcile_fetch(
        expected=expected,
        kept=kept,
        failed=failed,
        skipped=skipped,
        op_ids_expected=set(),   # M1 has no per-record op_id -> empty sets (the set arm balances trivially)
        op_ids_seen=set(),
        stage=stage,
        tally_path=tally_path,
        refetch_queue=refetch_queue,
        failed_ids=failed_ids,   # Identity arm passed through
        diff_tolerance=diff_tolerance,
    )
    # Honest labelling: M1 does not run the op_id set arm -> overwrite with "N/A" (schema.TALLY: op_id_arm in ok/"N/A").
    tally["op_id_arm"] = "N/A"
    return tally


# ===========================================================================
# Shard-count arm (thin wrapper around M0 reconcile_shards)
# ===========================================================================
def reconcile_scanned_shards(
    *,
    manifest_obj: Mapping[str, Any],
    entity: str,
    scanned_urls: Iterable[str],
    tally_path: pathlib.Path | str | None = None,
) -> dict[str, Any]:
    """The scanned shard set == the manifest's expected shard set, otherwise exit(EXIT_RECONCILE_FAIL=TALLY_IMBALANCE 15).

    Catches whole-shard faults: M1 missed an expected shard (missing) or scanned leftovers outside the release (extra).
    Thin wrapper around M0 reconcile_shards (shard-set reconciliation + exit 15).
    """
    expected_urls = expected_shard_urls_from_manifest(manifest_obj, entity=entity)
    return reconcile_shards(
        expected_urls=expected_urls,
        present_urls=scanned_urls,
        tally_path=tally_path,
    )


# ===========================================================================
# compact_dedup - DuckDB count(*)-count(DISTINCT pk); ==0 passes, otherwise exit(21)
# ===========================================================================
def compact_dedup(
    parquet_paths: Sequence[pathlib.Path | str],
    *,
    pk_cols: Sequence[str],
) -> int:
    """Number of duplicate PKs across the shards of a derived table = count(*) - count(DISTINCT pk); ==0 passes and returns 0, otherwise exit(21).

    Args:
        parquet_paths: the parquet shard paths of the table (part_*.parquet written by HashBucketWriter).
        pk_cols: the primary-key columns of the table (e.g. (work_id, author_id) for works_affil).
    Returns: 0 (no duplicate PK).
    Exit: SystemExit(EXIT_DEDUP_NONZERO=21) - duplicate PKs exist (the expansion logic missed de-duplication / canonical folding did not take effect).

    DuckDB count distinct is bounded (the whole table is not materialised into memory); duckdb is installed (1.5.4).
    Empty path set -> 0 (no table to check, not treated as duplicates; the caller must ensure it is non-empty).
    """
    import duckdb  # Local import: tests use importorskip("duckdb") to cover bare environments

    paths = [str(pathlib.Path(p)) for p in parquet_paths]
    if not paths:
        return 0
    pk_expr = ", ".join(f'"{c}"' for c in pk_cols)
    # read_parquet takes a url list -> one query across shards (DuckDB scans as a stream, does not load everything).
    con = duckdb.connect()
    try:
        # Parameterised file list (avoids path injection by string concatenation); the list is bound directly.
        total, distinct = con.execute(
            f"SELECT count(*), count(DISTINCT ({pk_expr})) FROM read_parquet(?)",
            [paths],
        ).fetchone()
    finally:
        con.close()
    dup = int(total) - int(distinct)
    if dup != 0:
        sys.stderr.write(
            f"[m1_compact_dedup] duplicate PK={dup} (pk={tuple(pk_cols)}; "
            f"total={total} distinct={distinct}) — HALT exit({EXIT_DEDUP_NONZERO})\n"
        )
        sys.exit(EXIT_DEDUP_NONZERO)
    return dup


# ===========================================================================
# assert_two_run_identical - per-part row counts + sorted PK multiset equal across two runs
# ===========================================================================
def _part_files(run_root: pathlib.Path | str) -> list[pathlib.Path]:
    """All parquet shards under a run directory (sorted, deterministic traversal)."""
    root = pathlib.Path(run_root)
    return sorted(root.rglob("*.parquet"))


def _sorted_pk_multiset(parquet_paths: Sequence[pathlib.Path], pk_cols: Sequence[str]) -> list[tuple]:
    """Read the PK columns of several parquets -> sorted PK multiset (list[tuple], duplicates kept, order-independent)."""
    import pyarrow.parquet as pq

    keys: list[tuple] = []
    for p in parquet_paths:
        table = pq.read_table(p, columns=list(pk_cols))
        cols = [table.column(c).to_pylist() for c in pk_cols]
        keys.extend(zip(*cols))
    return sorted(keys)


def assert_two_run_identical(
    run_a: pathlib.Path | str,
    run_b: pathlib.Path | str,
    *,
    pk_cols: Sequence[str],
) -> None:
    """The outputs of two runs are deterministically identical: sum of per-part row counts + sorted PK multiset equal; otherwise AssertionError.

    Deterministic reproduction (Repro): same input + HashBucketWriter with fixed schema/sort -> the PK multisets of the two runs are equal element by element.
    It does not compare file bytes (left to run_m1's SHA arm); here the semantic sets (PK multiset + total row count) are compared, which is more robust.
    """
    parts_a = _part_files(run_a)
    parts_b = _part_files(run_b)
    pk_a = _sorted_pk_multiset(parts_a, pk_cols)
    pk_b = _sorted_pk_multiset(parts_b, pk_cols)
    assert len(pk_a) == len(pk_b), (
        f"row counts differ between the two passes: run_a={len(pk_a)} run_b={len(pk_b)} (pk={tuple(pk_cols)})"
    )
    assert pk_a == pk_b, (
        f"PK multisets differ between the two passes (pk={tuple(pk_cols)}): "
        f"a-only={sorted(set(pk_a) - set(pk_b))[:5]} b-only={sorted(set(pk_b) - set(pk_a))[:5]}"
    )
