"""U0 common/reconcile.py — fetch reconciliation, three arms (any imbalance -> HALT, exit code 15).

A caliber-neutral cross-cutting base. In plain words: before a fetch ends, tally the books and confirm
everything that should have been fetched is accounted for, so data is never dropped silently as in the old
UQ/Sydney runs. If any of the three arms is unbalanced, HALT (print the gap + exit(TALLY_IMBALANCE=15)):

  Arm 1, arithmetic: expected == kept + failed + skipped.
  Arm 2, op_id sets: the expected op_id set == the set of op_ids actually seen (anything missing or extra fails).
  Arm 3, refetch precondition: every failed item must already be in the refetch queue before release;
       a failure cannot vanish, it must be queued for refetch.
       When the failed identity set (failed_ids) is given, the test is by identity inclusion
       (failed_ids is a subset of refetch_queue), not just by count: a queue with enough entries but the wrong
       members (a wrong item queued, a truly failed item absent) also HALTs.
       Without an identity set (older callers pass None) it falls back to the old count test, for
       backward compatibility.

Hard rules:
  - If any arm is unbalanced, print the gap first (which stage is off by how much / which op_ids are missing),
    then exit(15); never fail silently.
  - Deduct exactly once: one entry is written off only once and never deducted twice (a double deduction
    would fake a balanced account).
  - diff_tolerance is an unset red-line placeholder (redlines.reconcile.diff_tolerance: null).
    On None it must raise RedlineUnsigned and never pick an "allowed difference" itself.
    The function takes diff_tolerance as an injected argument (the default sentinel reads it from RED), so
    callers and tests can pass a value explicitly; passing None, or RED being unset, raises.

The exit code comes from identity.exit_codes.TALLY_IMBALANCE (the single source of truth; no bare numbers).
The tally row keys match schema.TALLY (six keys + balanced + op_id_arm).
This module only counts, writes the tally atomically, and HALTs; it makes no network calls and reads no
snapshot.
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

from common._redlines import RedlineUnsigned, require
from common.atomic_io import atomic_write_bytes  # Atomic write: the single authoritative implementation (one sequence)
from identity.exit_codes import TALLY_IMBALANCE

# Sentinel: tells "the caller did not pass diff_tolerance" (read it from RED; may be None -> raise) apart from "an explicit value was passed".
_UNSET: object = object()


def _resolve_diff_tolerance(diff_tolerance: Any) -> int | float:
    """Resolve the tolerance: not passed -> read from RED (raise if unset); explicit None -> raise; otherwise use as given.

    Placeholder rule: when redlines.reconcile.diff_tolerance is null, require() raises
    RedlineUnsigned; an explicit None raises too. Never default to 0 silently.
    """
    if diff_tolerance is _UNSET:
        # Read from the red-line ledger (unset = null -> require raises RedlineUnsigned).
        return require("reconcile", "diff_tolerance")
    if diff_tolerance is None:
        raise RedlineUnsigned(
            "reconcile.diff_tolerance was passed explicitly as None (unset red-line placeholder) — "
            "how large a difference is allowed must be set by a person, and the code never silently defaults to 0."
        )
    return diff_tolerance


def _emit_gap(message: str) -> None:
    """Print the reconciliation gap to stderr (a trace before HALT, so the missing items can be located)."""
    print(message, file=sys.stderr)


def reconcile_fetch(
    *,
    expected: int,
    kept: int,
    failed: int,
    skipped: int,
    op_ids_expected: set[str],
    op_ids_seen: set[str],
    stage: str,
    tally_path: pathlib.Path | str,
    refetch_queue: set[str] | None = None,
    failed_ids: set[str] | None = None,
    diff_tolerance: Any = _UNSET,
) -> dict[str, Any]:
    """Three-arm reconciliation; any imbalance -> print the gap + exit(TALLY_IMBALANCE=15).

    Args:
        expected/kept/failed/skipped: the four counts (arm 1, arithmetic).
        op_ids_expected/op_ids_seen:  the two op_id sets (arm 2).
        stage:        stage name (written into the tally and the gap message, for locating problems).
        tally_path:   where the tally row is written (written even when balanced, to keep the record).
        refetch_queue: the set of op_ids already queued for refetch (arm 3; None counts as empty).
        failed_ids:   the identity set of failed op_ids (arm 3). When given, arm 3 tests identity inclusion
                      (failed_ids is a subset of refetch_queue), so a queue with enough entries but the wrong
                      members also HALTs; when not given (None) it falls back to the old count test
                      (`len(queue) < failed`), for backward compatibility.
        diff_tolerance: tolerance; not passed -> read from RED (raise if unset); None -> raise.

    Returns (only when all three arms balance):
        a tally dict whose keys match schema.TALLY: stage/expected/kept/failed/skipped/
        balanced(=True)/op_id_arm(="ok").

    Raises / exits:
        RedlineUnsigned: diff_tolerance is unset (None).
        SystemExit(TALLY_IMBALANCE=15): any arm is unbalanced (the gap is printed first).

    Caliber discipline:
        - The lists and the arithmetic are an engineering reconciliation, not an identification red line.
        - diff_tolerance is an identification-caliber placeholder: None raises, and only a value set in the red-line ledger passes.
        - The exit code uses the named constant (no bare 15).
    """
    # The placeholder rule comes first: resolve the tolerance, and raise if it is unset (even if all three arms would balance).
    tol = _resolve_diff_tolerance(diff_tolerance)

    queue = refetch_queue if refetch_queue is not None else set()
    imbalanced = False

    # --- Arm 1, arithmetic: expected == kept + failed + skipped (within tolerance) ---
    arithmetic_diff = expected - (kept + failed + skipped)
    if abs(arithmetic_diff) > tol:
        imbalanced = True
        _emit_gap(
            f"[reconcile][{stage}] arithmetic arm is unbalanced: "
            f"expected={expected} != kept({kept})+failed({failed})+skipped({skipped})"
            f"={kept + failed + skipped}; gap={arithmetic_diff} (tolerance={tol})"
        )

    # --- Arm 2, op_id sets: expected set == seen set (anything missing or extra fails) ---
    missing_ids = op_ids_expected - op_ids_seen   # Expected but not seen (missed fetch)
    extra_ids = op_ids_seen - op_ids_expected     # Seen but not expected (extra)
    if missing_ids or extra_ids:
        imbalanced = True
        _emit_gap(
            f"[reconcile][{stage}] op_id set arm is unbalanced: "
            f"missing (not fetched)={sorted(missing_ids)} extra (unexpected)={sorted(extra_ids)}"
        )

    # --- Arm 3, refetch precondition: the failed part must already be in the refetch queue (a failure cannot vanish) ---
    #     Deduct exactly once: write off with a set (idempotent), not by repeatedly subtracting from the failed count.
    #     With a failed identity set, test identity inclusion (subset); without one, fall back to the old count test.
    if failed_ids is not None:
        # Identity level: every failed op_id must be in the refetch queue (a queue with enough entries but the wrong members also fails).
        not_queued = failed_ids - queue   # Failed but not queued for refetch (refetch missed)
        if not_queued:
            imbalanced = True
            _emit_gap(
                f"[reconcile][{stage}] refetch precondition arm is unbalanced (identity mismatch): "
                f"failed but not in the refetch queue={sorted(not_queued)}; "
                f"failed_ids={sorted(failed_ids)} refetch_queue={sorted(queue)} "
                f"(a matching count is not enough — every failed op_id must be in the queue individually to pass)."
            )
    elif failed > 0 and len(queue) < failed:
        imbalanced = True
        _emit_gap(
            f"[reconcile][{stage}] refetch precondition arm is unbalanced: "
            f"failed={failed} but the refetch queue has only {len(queue)} entries "
            f"(queue={sorted(queue)}); every failed item must be queued for refetch."
        )

    # --- Any arm unbalanced -> HALT (exit code 15, named constant) ---
    if imbalanced:
        _emit_gap(f"[reconcile][{stage}] tally imbalance → HALT exit({TALLY_IMBALANCE})")
        raise SystemExit(TALLY_IMBALANCE)

    # --- All three arms balance: build the tally row (keys match schema.TALLY), write it atomically, return ---
    tally: dict[str, Any] = {
        "stage": stage,
        "expected": expected,
        "kept": kept,
        "failed": failed,
        "skipped": skipped,
        "balanced": True,
        "op_id_arm": "ok",
    }
    _write_tally_atomic(pathlib.Path(tally_path), tally)
    return tally


def _write_tally_atomic(tally_path: pathlib.Path, tally: dict[str, Any]) -> None:
    """Write the tally row atomically, keeping the record and never dropping it silently.

    The single authoritative implementation of the G7 atomic-write sequence
    (.partial -> flush -> durable_fsync -> os.replace -> fsync(parent)) is atomic_io.atomic_write_bytes;
    this function calls it directly instead of hand-writing another copy
    (the G7 sequence used to be hand-written in several places; it is now consolidated in atomic_io).
    The parent directory is created if missing (atomic_write_bytes assumes it exists).
    """
    tally_path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(tally, ensure_ascii=False, sort_keys=True).encode("utf-8")
    atomic_write_bytes(tally_path, blob)


# ===========================================================================
# Exclusion guards (four functions + the same-source assertion for the two tables)
#   The signatures were fixed early, but u0 never implemented them;
#   the first real consumer is U5 M5b.
#   No identification caliber here: these are all engineering reconciliation assertions; any imbalance raises ExclusionGuardError (fail-loud).
# ===========================================================================


class ExclusionGuardError(ValueError):
    """An exclusion-guard assertion failed (monotonicity / exactly once / single source / same source for two tables) — fail-loud."""


def assert_invariant_monotone(after, before, *, label: str) -> None:
    """Monotonicity guard, clean <= full: the measure after exclusion must never exceed the measure before.

    Two positional arguments (after, before); after = value after exclusion, before = value before exclusion.
    """
    if after > before:
        raise ExclusionGuardError(
            f"[{label}] monotone violated: after exclusion after={after!r} > before exclusion before={before!r} "
            "— the identity clean ≤ full does not hold, fail-loud"
        )


def assert_deduction_applied_once(*, before: int, after: int, exclude_set,
                                  label: str) -> None:
    """Deduct exactly once: before - after == len(exclude_set) (all keyword-only).

    Catches two old faults: double deduction (a fan-out deducts too much, so the difference > the set size) and
    a missed deduction (difference < the set size).
    The size of exclude_set is the anchor: one element can be counted only once (set idempotence).
    """
    exclude = set(exclude_set)
    deducted = before - after
    if deducted != len(exclude):
        raise ExclusionGuardError(
            f"[{label}] deduction not applied exactly once: before={before} after={after} "
            f"deducted={deducted} != len(exclude_set)={len(exclude)} — "
            "too many = the old fan-out double deduction / too few = the exclusion did not apply; both stop"
        )


def assert_single_source_exclusion(exclude_set, derived_from_set, *,
                                   label: str) -> None:
    """Single-source exclusion: the exclusion set actually used must equal exactly the set derived from a single source.

    The second argument is the positional derived_from_set (not a keyword).
    Usage (M5b): exclude_set = the exclusion set the run actually applied;
                derived_from_set = star_coauthored_paper_alltime(star_ids(p)), re-derived independently.
    If the two sides differ, the exclusion set mixed in another source or missed one -> fail-loud.
    """
    exclude = set(exclude_set)
    derived = set(derived_from_set)
    if exclude != derived:
        extra = sorted(exclude - derived)[:5]
        missing = sorted(derived - exclude)[:5]
        raise ExclusionGuardError(
            f"[{label}] exclusion set is not derived from a single source: extra={extra} missing={missing} "
            f"(|exclude|={len(exclude)} |derived|={len(derived)}) — fail-loud"
        )


def apply_exclusion_once(count: int, exclude_set, *, label: str) -> int:
    """Idempotent deduction: returns count - len(set(exclude_set)); a negative result -> raise.

    Write-off by set means one element is never deducted twice (idempotent); a negative result means more was
    deducted than the total, so there must be an upstream bug.
    """
    out = count - len(set(exclude_set))
    if out < 0:
        raise ExclusionGuardError(
            f"[{label}] apply_exclusion_once went negative: count={count} "
            f"len(exclude)={len(set(exclude_set))} — the exclusion set is larger than the total, fail-loud"
        )
    return out


def assert_two_tables_same_source(table_a, table_b, *, pk_cols,
                                  invariant_cols, label: str) -> None:
    """Same-source assertion for two tables: two named tables generated in one pass by the same code.

    Criteria (all three must pass to count as the same source):
      1. the two tables have equal row-key sets (schema);
      2. the two tables have equal PK sets (same-source aggregation gives the same (person, year) groups);
      3. invariant_cols (shared columns the exclusion does not affect, such as pub_count/fwci_frac) have the same value for each PK.
    A table is a list[dict] of rows; invariant_cols is given explicitly by the caller (u0 builds in no table's column caliber).
    """
    rows_a = list(table_a)
    rows_b = list(table_b)
    keys_a = set(rows_a[0].keys()) if rows_a else set()
    keys_b = set(rows_b[0].keys()) if rows_b else set()
    if keys_a != keys_b:
        raise ExclusionGuardError(
            f"[{label}] tables not from the same source: row key sets differ a-b={sorted(keys_a - keys_b)} "
            f"b-a={sorted(keys_b - keys_a)}"
        )

    def _by_pk(rows):
        return {tuple(r[c] for c in pk_cols): r for r in rows}

    a_by = _by_pk(rows_a)
    b_by = _by_pk(rows_b)
    if set(a_by) != set(b_by):
        only_a = sorted(set(a_by) - set(b_by))[:5]
        only_b = sorted(set(b_by) - set(a_by))[:5]
        raise ExclusionGuardError(
            f"[{label}] tables not from the same source: PK sets differ only_in_a={only_a} only_in_b={only_b}"
        )
    for pk, ra in a_by.items():
        rb = b_by[pk]
        for col in invariant_cols:
            if ra[col] != rb[col]:
                raise ExclusionGuardError(
                    f"[{label}] tables not from the same source: shared column {col!r} differs at PK={pk} "
                    f"a={ra[col]!r} b={rb[col]!r} — columns the exclusion does not affect must be equal row by row"
                )
