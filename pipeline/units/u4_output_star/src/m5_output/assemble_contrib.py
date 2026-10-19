"""M5 production assembler: paper_contrib assembly (fwci raw value passed straight through) + two-stage isc backfill.
(New module in the first U4 delivery wave; all pure-function parts are reused, this layer only does "scan -> feed -> assemble")

In plain words: read-only scan of U1 works x authorship_edges for "every paper of the incumbents of the two universities + the full author set",
feed each paper to the already-tested parts (frac_credit / 8-key row / compute_fwci), assemble the paper_contrib rows +
diagnostic sidecar rows; then provide two delivery steps: (1) star-set mapping, (2) isc backfill.

Rules (all fixed; this layer only consumes them):
  - Row granularity / frac / two-stage isc = m5_output.paper_contrib (schema [18], 8 keys).
  - fwci = m5_output.fwci_raw.compute_fwci (R1 whitelist + paratext drop, R2 missing -> NA,
    S8-4 field fallback).
  - isc#2: the only definition of is_star_coauthored is identity.output_rule; this module imports and binds the original.
  - S8-8 + star.source_filter=foreign_poach_only: star set = full 5% set AND pure foreign poach
    (star_pool_author_ids; a mechanical combination of two fixed keys, no new definition).
Note: winsorizing is NOT applied (fwci is recorded as is):
  rationale: none of the 8 benchmark papers trims (they use log(1+x) in the regression layer, Poisson QML,
  or raw values; official FWCI is uncapped), so each paper's raw fwci is stored and skew handling is left to the regression layer.
  The earlier "p99 winsorize" step is dropped; the paratext drop is unchanged.
  The former winsor_pool_scope/apply_winsor_stage guard steps have been removed:
  the delivery path has no trimming step (tombstone note at the end of the file).

Purity: no IO except the read-only DuckDB scan; never writes to the SSD (writing happens in run_u4's finalize layer).
"""
from __future__ import annotations

import sys
from collections import defaultdict
from typing import Callable, Iterable, Mapping

from common._redlines import RED
# isc#2 rule: single definition, bind the original (used by backfill_isc; tests assert identity with `is`).
from identity.output_rule import is_star_coauthored
from m5_output.fwci_raw import compute_fwci
from m5_output.paper_contrib import build_paper_contrib_rows

# Diagnostic sidecar row, 5 keys (fwci_native/fwci_incomplete/fwci_missing_reason/
# fwci_inferred_fallback go to the sidecar paper_contrib_diag; the main table [18] has no diagnostic columns).
# fwci_incomplete = (fwci is None): an engineering-derived bool (cannot compute = incomplete), no new threshold.
PAPER_CONTRIB_DIAG: dict[str, str] = {
    "work_id": "str",
    "fwci_native": "float64",
    "fwci_incomplete": "bool",
    "fwci_missing_reason": "str",
    "fwci_inferred_fallback": "bool",
}


def scan_incumbent_works(derived_root, incumbent_author_ids, *,
                         edges_sub="u1_edges_full_2026-07-05") -> list[dict]:
    """DuckDB **read-only** scan: every work signed by an incumbent -> metadata + full author set (sorted, de-duplicated).

    Returns [{work_id, publication_year, subfield_id, work_type, cited_by_count,
    is_paratext, fwci_native, author_ids}] sorted by work_id (deterministic).
    Edges pointing at a work absent from works -> ValueError, fail-loud (upstream integrity broken; never skipped silently).
    """
    import duckdb
    from pathlib import Path

    ep = (Path(derived_root) / edges_sub).as_posix()
    ids = ",".join("'" + a + "'" for a in sorted(incumbent_author_ids))
    con = duckdb.connect()
    try:
        con.execute(
            f"CREATE TEMP TABLE iw AS SELECT DISTINCT work_id "
            f"FROM read_parquet('{ep}/authorship_edges/**/*.parquet') "
            f"WHERE author_id IN ({ids})"
        )
        pair_rows = con.execute(
            f"SELECT e.work_id, e.author_id "
            f"FROM read_parquet('{ep}/authorship_edges/**/*.parquet') e "
            f"JOIN iw USING (work_id)"
        ).fetchall()
        meta_rows = con.execute(
            f"SELECT w.work_id, w.publication_year, w.subfield_id, w.work_type, "
            f"w.cited_by_count, w.is_paratext, w.fwci "
            f"FROM read_parquet('{ep}/works/**/*.parquet') w JOIN iw USING (work_id)"
        ).fetchall()
    finally:
        con.close()

    authors_by_work: dict[str, set] = defaultdict(set)
    for wid, aid in pair_rows:
        authors_by_work[wid].add(aid)
    meta = {r[0]: r for r in meta_rows}
    missing = sorted(set(authors_by_work) - set(meta))
    if missing:
        raise ValueError(
            f"scan_incumbent_works: {len(missing)} works have authorship edges but the works table lacks their metadata "
            f"(edges⋈works integrity broken, e.g. {missing[:3]}) — fail-loud, hand to a person to check upstream"
        )
    out = []
    for wid in sorted(meta):
        _, year, sub, wtype, cites, paratext, native = meta[wid]
        out.append({
            "work_id": wid, "publication_year": year, "subfield_id": sub,
            "work_type": wtype, "cited_by_count": cites, "is_paratext": paratext,
            "fwci_native": native, "author_ids": sorted(authors_by_work[wid]),
        })
    return out


def assemble_paper_contrib(derived_root, *, incumbent_person_ids, author_person: Mapping[str, str],
                           expected_by_cell: dict, field_expected: dict | None = None,
                           field_of_work: Callable | None = None,
                           edges_sub="u1_edges_full_2026-07-05") -> dict:
    """Production assembly: scan incumbents' works -> per-paper 8-key rows + diagnostic rows.

    - Incumbent scope = the roster person set passed in (table-B roster folded via person_map, not defined here);
      fold out all their author_ids (one person can have several author profiles) -> scan keys.
    - Stage 1 of two-stage isc: star set passed empty -> all False (backfill goes through backfill_isc).
    - fwci: compute_fwci (expected taken from fwci_baseline; S8-4 field_expected/field_of_work
      passed through; if no fallback is left -> NA + reason, never 0). fwci raw values pass straight through:
      this function produces the final stored value, no trimming step follows.
    Returns {"rows", "diag", "n_works", "n_incumbent_authors"} (deterministic row order).
    """
    incumbents = set(incumbent_person_ids)
    inc_authors = sorted(a for a, p in author_person.items() if p in incumbents)
    if not inc_authors:
        raise ValueError(
            "assemble_paper_contrib: the incumbent set maps to no author_id "
            f"(incumbent_person_ids={len(incumbents)}, no person_map hit) — "
            "an empty scan scope is an assembly failure; a 0-row table is never produced silently"
        )
    works = scan_incumbent_works(derived_root, inc_authors, edges_sub=edges_sub)

    rows: list[dict] = []
    diag: list[dict] = []
    for w in works:
        fw = compute_fwci(
            {"work_id": w["work_id"], "work_type": w["work_type"],
             "is_paratext": w["is_paratext"], "publication_year": w["publication_year"],
             "subfield_id": w["subfield_id"], "cited_by_count": w["cited_by_count"]},
            expected_by_cell, field_expected=field_expected, field_of_work=field_of_work)
        wrows = build_paper_contrib_rows(
            {"work_id": w["work_id"], "author_ids": w["author_ids"],
             "publication_year": w["publication_year"], "subfield_id": w["subfield_id"],
             "fwci": fw["fwci"]},
            author_person=author_person, incumbent_person_ids=incumbents,
            star_person_ids=frozenset())          # Stage 1 of two-stage isc: isc is always False
        if not wrows:
            continue  # No incumbent among the persons this work maps to (the scan is by author; the person-level check is here)
        rows += wrows
        diag.append({
            "work_id": w["work_id"],
            "fwci_native": w["fwci_native"],
            "fwci_incomplete": fw["fwci"] is None,
            "fwci_missing_reason": fw["fwci_missing_reason"],
            "fwci_inferred_fallback": fw["fwci_inferred_fallback"],
        })
    return {"rows": rows, "diag": diag, "n_works": len(diag),
            "n_incumbent_authors": len(inc_authors)}


# ---- Tombstone: the winsor step has been removed ---------------------------------
# This place used to hold the two delivery guards winsor_pool_scope() + apply_winsor_stage()
# (shipping was halted because the pool scope was undecided). Winsorizing is not applied (record as is), because
# none of the 8 benchmark papers winsorizes and official FWCI is uncapped: each paper's raw fwci is stored,
# skew handling belongs to the regression layer, and the earlier "p99 winsorize" half-rule is dropped
# (paratext drop unchanged). Both functions were deleted, so the delivery path has no trimming step; guard against revival:
# tests/test_m5_assemble_contrib.py::test_winsor_stage_removed_per_signed_no_winsorize.
# The pure function m5_output.fwci_raw.winsorize_fwci is kept (historical, not called in production).


# ---- isc two-stage backfill (star_set author_id key -> person mapping -> intersection) -----------------

def star_pool_author_ids(star_rows: Iterable[dict]) -> list[str]:
    """Frozen star_set rows -> set of star author_ids (a mechanical combination of fixed rules, no new definition):

    - S8-8: the star pool takes the **full 5% set** (p01 analysis uses its 1% subset) -> take rows where is_star_5pct is
      True (None = thin cell, cannot estimate / False = evaluated but not reached; neither enters).
    - Fixed star.source_filter=foreign_poach_only (rule: "stars are pure foreign poaches") -> additionally AND
      is_foreign_poach. If source_filter is changed -> fail loudly and hand it back for re-judgement (same self-check pattern as output_rule).
    """
    sf = RED["star"]["source_filter"]
    if sf != "foreign_poach_only":
        raise ValueError(
            f"star_pool_author_ids: RED['star'].source_filter={sf!r} ≠ "
            "'foreign_poach_only' — the star definition has changed; a person must re-judge the isc star set, no self-decided fallback"
        )
    return [r["author_id"] for r in star_rows
            if r.get("is_star_5pct") is True and r.get("is_foreign_poach") is True]


def fold_star_authors_to_persons(star_author_ids: Iterable[str],
                                 author_person: Mapping[str, str]) -> dict:
    """Map star author_id -> person_id (dict form of the 2 columns person_map reads).

    A star with no mapping -> counted + stderr WARN, **never silently shrink the set** (missing one star = a false isc False,
    which directly hurts U5's star-exclusion definition). Returns {"star_person_ids": set, "unmapped_star_author_ids": list}.
    """
    star_pids: set = set()
    unmapped: list[str] = []
    for aid in star_author_ids:
        pid = author_person.get(aid)
        if pid is None:
            unmapped.append(aid)
        else:
            star_pids.add(pid)
    unmapped = sorted(unmapped)
    if unmapped:
        sys.stderr.write(
            f"[U4/isc-backfill] WARN: {len(unmapped)} star author_ids lack a person_map "
            f"mapping (e.g. {unmapped[:3]}) — these stars cannot take part in the isc intersection; counted and reported, not silent\n"
        )
    return {"star_person_ids": star_pids, "unmapped_star_author_ids": unmapped}


def backfill_isc(rows: Iterable[dict], star_person_ids: Iterable[str]) -> list[dict]:
    """Stage 2 of two-stage isc: per-work author person set ∩ star person set -> backfill is_star_coauthored.

    - A work's author person set = distinct person_id over all its rows (assembled rows already enumerate
      incumbent x all mapped co-authors, so distinct person_id = the mapped author set).
    - The decision = identity.output_rule.is_star_coauthored itself (the only isc#2 definition, not rewritten).
    - Two stars on one work -> the bool is still a single True (no stacking); row count / other fields are untouched (returns new rows, input not modified).
    """
    materialized = [dict(r) for r in rows]
    persons_by_work: dict = defaultdict(set)
    for r in materialized:
        persons_by_work[r["work_id"]].add(r["person_id"])
    star_set = set(star_person_ids)
    isc_by_work = {
        wid: is_star_coauthored({"author_person_ids": sorted(pids)}, star_set)
        for wid, pids in persons_by_work.items()
    }
    for r in materialized:
        r["is_star_coauthored"] = isc_by_work[r["work_id"]]
    return materialized


def write_fwci_na_report(diag_rows: Iterable[dict], out_dir) -> dict:
    """FWCI-NA count report: counts grouped by missing reason, written to
    <out_dir>/_reports/fwci_na_counts.csv. Computable rows are recorded as reason="ok". Diagnostic layer, no definition thresholds."""
    import csv
    from pathlib import Path

    counts: dict[str, int] = {}
    for r in diag_rows:
        reason = r.get("fwci_missing_reason") or "ok"
        counts[reason] = counts.get(reason, 0) + 1
    rpt_dir = Path(out_dir) / "_reports"
    rpt_dir.mkdir(parents=True, exist_ok=True)
    path = rpt_dir / "fwci_na_counts.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fwci_missing_reason", "n"])
        for reason in sorted(counts):
            w.writerow([reason, counts[reason]])
    return counts
