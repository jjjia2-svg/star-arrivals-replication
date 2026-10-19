"""m5b_aggregate/run_m5b.py — M5b orchestration: exclusion set -> u0 aggregation -> quality -> two named tables
(#42-47).

Flow (read frozen handles -> call pure functions -> triple guard -> atomic write + freeze + reconcile):
  1. Injected parameters are read explicitly key by key (a missing key -> KeyError; an empty-string provenance four-tuple -> raise, fail loud —
     an old defect where an empty provenance passed as green).
  2. Idempotency/resume (#45/#30): key = stage|config_sha|stars_set_hash|merkle|
     rule_version — changing star_set flips the key, so a stale ledger entry is not reused.
  3. For each p_level in (p01, p05) [#1: two named tables]:
     fold the shipped-set stars (ship_star_person_ids, flag AND poach) -> exclusion set (star_coauthored_paper_
     alltime, single source) -> aggregate_via_u0 (12 keys; the aggregation formula lives only in u0, preventing B5) ->
     fill_quality (#3+4, no winsorisation).
  4. Triple guard (u0 reconcile exclusion guard):
     assert_single_source_exclusion (#44, closed once each for p01/p05, derived_from_set passed positionally)
     + assert_deduction_applied_once (number of excluded units = count difference; catches fan-out double or missed deduction)
     + assert_invariant_monotone (sum ex_star <= sum full)
     + assert_two_tables_same_source (#44b: PK sets fully equal + the five columns unaffected by exclusion have equal values row by row).
  5. Reconcile: expected = the number of (inc, year) groups derived independently from the raw pc (an anchor taken before aggregation,
     not a scan of the product — the A2 false-balance lesson); the six-key tally is written atomically via reconcile.
  6. One COMMIT for both tables (write_dataset_commit; one run physically guarantees the same source for both) + output_diag.json
     sidecar (#47; diagnostics are not mixed into the main tables/TALLY) + ledger.append (.append only — DRIFT-L1).
"""
from __future__ import annotations

import json
import pathlib
import shutil
from datetime import datetime, timezone

from common.atomic_io import atomic_write_bytes
from common.ledger import Ledger
from common.manifest import dataset_is_valid, write_dataset_commit
from common.reconcile import (
    assert_deduction_applied_once,
    assert_invariant_monotone,
    assert_single_source_exclusion,
    assert_two_tables_same_source,
    reconcile_fetch,
)
from common.schema import OUTPUT
from m1_ingest._writer_util import write_rows_parquet

from . import aggregate as agg
from . import quality as qual
from . import star_coauthored_works as scw

_PK: tuple = ("incumbent_person_id", "year")
_P_LEVELS: tuple = ("p01", "p05")                       # #1: two named tables
_TABLE_NAME = {"p01": "output_star1pct.parquet", "p05": "output_star5pct.parquet"}
# Shared columns unaffected by exclusion (the substantive test that both tables come from the same source, #44b); the ex_star columns and quality (numerator drops stars,
# varies with the p_level exclusion set) are not in this list.
_SHARED_INVARIANT_COLS: tuple = (
    "pub_count", "n_works_frac", "fwci_frac", "fwci_full", "fwci_mean",
)
_PROVENANCE_KEYS: tuple = (
    "source_snapshot_merkle", "config_sha", "rule_version", "stars_set_hash",
)


def _need(config: dict, key: str):
    """Read an injected parameter explicitly: a missing key -> KeyError (no default magic number)."""
    if key not in config:
        raise KeyError(f"config lacks {key!r} — U5 injected parameters must be given explicitly")
    return config[key]


def run_m5b(inputs, *, config: dict, out_root, ledger_path,
            force_recompute: bool = False, exclusion_edges=None) -> dict:
    """Full M5b orchestration (one run produces two named tables). inputs = io_load.U5Inputs handle.

    exclusion_edges: author-level edge set used to derive the exclusion set (None = inputs.authorship_edges).
      Note: #8 excludes the whole history regardless of year — on the real-data path pass an edge set that "includes edges with a missing year"
      (the dose domain drops edges with a missing year because of truncation, but a star-co-authored work with a missing year still enters the exclusion set;
      its pc units are already dropped by the missing-year log, so OUTPUT is not affected).
    """
    # -- 1. injected parameters + provenance non-empty, fail loud -----------------------------
    mnar_thr = float(_need(config, "mnar_missing_threshold"))
    provenance = {k: str(_need(config, k)) for k in _PROVENANCE_KEYS}
    for k, v in provenance.items():
        if not v.strip():
            raise ValueError(
                f"config provenance key {k!r} is empty — the four-part provenance tuple must be non-empty "
                "(empty provenance was a known past defect; fail loudly)"
            )

    # -- 2. idempotency / resume (#45/#30) --------------------------------------
    out_root = pathlib.Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    ledger_path = pathlib.Path(ledger_path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    stage = "m5b_output"
    idem_key = "|".join((stage, provenance["config_sha"],
                         provenance["stars_set_hash"],
                         provenance["source_snapshot_merkle"],
                         provenance["rule_version"]))
    ledger = Ledger(ledger_path)
    if (not force_recompute) and ledger.already_done(idem_key) \
            and dataset_is_valid(out_root):
        return {"skipped": True, "idempotency_key": idem_key,
                "out_root": str(out_root)}

    # -- 3. each p_level: fold stars -> exclusion set -> u0 aggregation -> quality --------------------
    excl_edges = (exclusion_edges if exclusion_edges is not None
                  else inputs.authorship_edges)
    tables: dict[str, list] = {}
    diag: dict[str, dict] = {}
    for p_level in _P_LEVELS:
        star_pids, n_unmapped = scw.ship_star_person_ids(
            inputs.star_set, inputs.person_map, p_level=p_level
        )
        derived = scw.star_coauthored_paper_alltime(
            star_pids, excl_edges, inputs.person_map
        )
        exclude = frozenset(derived)

        rows, stats = agg.aggregate_via_u0(
            inputs.paper_contrib, inputs.works, exclude_works=exclude
        )
        contribs, _ = agg.to_contribs(inputs.paper_contrib, exclude_works=exclude)
        rows = qual.fill_quality(rows, contribs)
        rows.sort(key=lambda r: tuple(r[c] for c in _PK))

        # -- 4a. guard: single source (#44, derived_from_set passed positionally) ---------------
        assert_single_source_exclusion(exclude, derived, label=f"m5b_{p_level}")
        # -- 4b. guard: deducted exactly once (count difference == number of flagged contribution units) ----------------
        flagged_units = {(c["incumbent_person_id"], c["year"], c["work_id"])
                         for c in contribs if c["is_star_coauthored"]}
        before = sum(r["pub_count"] for r in rows)
        after = sum(r["pub_count_ex_star"] for r in rows)
        assert_deduction_applied_once(before=before, after=after,
                                      exclude_set=flagged_units,
                                      label=f"m5b_{p_level}")
        assert_invariant_monotone(after, before, label=f"m5b_{p_level}_pub_count")

        na_stats = qual.fwci_na_stats(contribs, mnar_missing_threshold=mnar_thr)
        tables[p_level] = rows
        diag[p_level] = {
            "n_ship_stars": len(star_pids),
            "n_unmapped_star_authors": n_unmapped,
            "n_excluded_works": stats["n_excluded_works"],   # number of works that actually hit retained units
            "n_exclusion_set_works": len(exclude),           # full exclusion set (including works with a missing year)
            "n_excluded_contrib_units": stats["n_excluded_contrib_rows"],
            "n_raw_rows": stats["n_raw_rows"],
            "n_contrib_units": stats["n_contrib_units"],
            "n_dropped_null_pub_year": stats["n_dropped_null_pub_year"],
            "n_papers_fwci_na": stats["n_papers_fwci_na"],
            "n_output_rows": len(rows),
            **na_stats,
        }

    # -- 4c. guard: both tables from the same source (#44b, #1) ----------------------------------
    assert_two_tables_same_source(
        tables["p01"], tables["p05"], pk_cols=_PK,
        invariant_cols=_SHARED_INVARIANT_COLS, label="m5b_output",
    )

    # -- 5. reconcile (expected anchor = derived independently from raw pc, before aggregation — prevents A2 false balance) ------
    units, _n_raw = agg._dedupe_work_incumbent(inputs.paper_contrib)
    expected_pks = {(u["incumbent_person_id"], u["publication_year"])
                    for u in units if u["publication_year"] is not None}
    op_expected = {f"{p}|{y}" for p, y in expected_pks}
    op_seen = {f"{r['incumbent_person_id']}|{r['year']}" for r in tables["p01"]}
    reconcile_fetch(
        expected=len(expected_pks), kept=len(tables["p01"]), failed=0, skipped=0,
        op_ids_expected=op_expected, op_ids_seen=op_seen,
        stage=stage, tally_path=out_root / "tally.json",
    )

    # -- 6. one COMMIT for both tables (one run physically guarantees the same source for both) + sidecar + ledger ----------
    build_dir = out_root / "_build_tmp"
    build_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, bytes] = {}
    for p_level in _P_LEVELS:
        tmp = build_dir / _TABLE_NAME[p_level]
        write_rows_parquet(tables[p_level], tmp, schema=OUTPUT, pk_cols=_PK,
                           label=_TABLE_NAME[p_level])
        payload[_TABLE_NAME[p_level]] = tmp.read_bytes()
    shutil.rmtree(build_dir)
    write_dataset_commit(out_root, payload, provenance=provenance).stage().commit()

    diag_doc = {"stage": stage, "p_levels": list(_P_LEVELS), **diag}
    atomic_write_bytes(
        out_root / "output_diag.json",
        json.dumps(diag_doc, ensure_ascii=False, sort_keys=True).encode("utf-8"),
    )

    ledger.append(
        op_id=stage, status="ok", shard_id="p01+p05", idempotency_key=idem_key,
        ts=datetime.now(timezone.utc).isoformat(), reason="",
    )

    return {
        "skipped": False,
        "stage": stage,
        "idempotency_key": idem_key,
        "n_rows": {p: len(tables[p]) for p in _P_LEVELS},
        "n_excluded_works": {p: diag[p]["n_excluded_works"] for p in _P_LEVELS},
        "mnar_robustness_required": {p: diag[p]["mnar_robustness_required"]
                                     for p in _P_LEVELS},
        "out_root": str(out_root),
        "tables": {p: str(out_root / "_frozen" / _TABLE_NAME[p])
                   for p in _P_LEVELS},
    }
