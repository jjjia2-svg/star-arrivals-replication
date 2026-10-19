"""M1-T6 passes - seed-driven multi-pass scan orchestration (pass-A/B/C) + piggy-backed first_pub/work_text/affil/inst.

Why "multi-pass":
  All works together are too big to keep in memory. The approach is a seed-driven snowball:
    pass-A scans everything once and finds the "in-department authors" (institution, after folding, is in econ_dept_ids); the works
           these authors take part in are the seeds; in the same pass it piggy-backs every (author, year) into FirstPubAccumulator
           (the true career first-publication year needs the full history).
    pass-B for seed-related works writes works/refs_edges and caches ALL authorship edges of the work
           (the non-seed collaborators' edges inside a seed work are also needed - otherwise the spillover computation misses the edge
           that receives the spillover), accumulates fwci, writes work_text/works_affil/institutions; and collects the set of cited
           expansion works = frontier.
    pass-C rescans the frontier (works referenced by seed works) to fill in their works rows; all must be hit
           (hits >= frontier_count) otherwise exit(EXIT_FRONTIER_MISS=20) - a dangling reference = an edge pointing to a non-existent node.

Seed ownership uses the real U0 (not injected): inst_lineage.fold_to_canonical (child institution folds to parent institution) +
  in_au_econ_dept (whether the folded id falls in the department boundary set). Institution folding is a pure function; it is only called here, never changed.

Row-level table expansion / field mapping / reversal / writing belong to the sibling modules (schema_map / works_affil / abstract_reverse /
  institutions / hash_bucket_writer). This module makes them injected extract/write closures and is only responsible for
  orchestration + keeping all edges + piggy-back accumulation + the frontier guard - so the orchestration can be tested with fixture works,
  without hard coupling to sibling modules that may not exist yet, and without repeating the field mapping in two places (DRY).
  run_m1 wires in the real closures of the sibling modules.

Reuses U0:
  - inst_lineage.fold_to_canonical(inst, registry_by_id) / in_au_econ_dept(canonical_id, econ_dept_ids).
  - identity.constants.build_registry_by_id (1 argument).
  - exit_codes.EXIT_FRONTIER_MISS (=20; no bare numbers).

Neutral on identification choices: seed snowballing / keeping all edges / the frontier guard are engineering orchestration and touch no
identification rule (dose/FWCI/arrival placeholders all live elsewhere).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Optional

# U0 foundation (actual interface surface).
from common.inst_lineage import fold_to_canonical, in_au_econ_dept
from identity.constants import build_registry_by_id
from identity.exit_codes import EXIT_FRONTIER_MISS

# bare-id normalisation: reuses the single authoritative implementation in _writer_util (strips the OpenAlex URL prefix, idempotent, None/"" -> None);
#   this module used to carry its own copies of _bare and OPENALEX_URL_PREFIX, now unified in one place (DRY).
from m1_ingest._writer_util import bare as _bare  # noqa: F401  (single source of truth)


def build_registry(registry: list[dict]) -> dict[str, dict]:
    """Index the U0.5 table-A registry list as {bare openalex_id: record} (thin wrapper around U0 build_registry_by_id, 1 argument)."""
    return build_registry_by_id(registry)


def _iter_authorships(work: Mapping[str, Any]):
    """Yield (bare author_id, institutions list) per authorship; the orchestration needs only these two, the full field mapping belongs to the sink."""
    for au in work.get("authorships") or []:
        author = au.get("author") or {}
        author_id = _bare(author.get("id"))
        institutions = au.get("institutions") or []
        yield author_id, institutions


def _work_is_seed(
    work: Mapping[str, Any],
    *,
    econ_dept_ids: set[str],
    registry_by_id: Mapping[str, dict],
) -> tuple[bool, set[str]]:
    """Whether this work is a seed, and its set of in-department authors.

    Seed = at least one author has an institution that, after fold_to_canonical, falls in econ_dept_ids.
    Returns (is_seed, seed_author_ids_in_this_work).
    """
    seed_authors_here: set[str] = set()
    for author_id, institutions in _iter_authorships(work):
        if author_id is None:
            continue
        for inst in institutions:
            # In the snapshot the id of authorship.institutions[] is URL-shaped -> fold's internal _bare normalises it; but fold reads the openalex_id key.
            inst_rec = _normalize_inst_for_fold(inst)
            canonical = fold_to_canonical(inst_rec, registry_by_id)
            if in_au_econ_dept(canonical, econ_dept_ids):
                seed_authors_here.add(author_id)
                break  # This author is already confirmed in the department; no need to look at their other institutions
    return (len(seed_authors_here) > 0, seed_authors_here)


def _normalize_inst_for_fold(inst: Mapping[str, Any]) -> dict:
    """Shape one authorship.institutions[] item from the snapshot into the form fold_to_canonical expects.

    fold reads inst['openalex_id'] (path1) + inst['lineage'] (path2) + inst['associated_institutions'] (path3);
    the institution id field in the snapshot is named 'id' (URL-shaped) and there is no 'openalex_id' key -> add openalex_id = id here.
    Other fields (lineage/associated_institutions) pass through unchanged; if missing, fold's internal `or []` falls back to empty.
    The original inst is not modified (pure function); a shallow copy with the added key is returned.
    """
    rec = dict(inst)
    if "openalex_id" not in rec and "id" in rec:
        rec["openalex_id"] = rec["id"]
    return rec


# ===========================================================================
# pass-A: seed identification + piggy-backed first_pub (one full scan)
# ===========================================================================
@dataclass
class PassAResult:
    seed_authors: set[str] = field(default_factory=set)   # In-department authors (bare, before canonical; canonical folding is closed out in run_m1)
    seed_work_ids: set[str] = field(default_factory=set)  # Bare ids of seed works
    seen_authors: set[str] = field(default_factory=set)   # All distinct authors scanned (for reconciliation)


def pass_a_seed_authors(
    work_shards: Iterable[Mapping[str, Any]],
    *,
    econ_dept_ids: set[str],
    registry_by_id: Mapping[str, dict],
    first_pub: Any,
) -> PassAResult:
    """One full scan: find in-department authors (seeds) + record seed works + piggy-back every (author, year) into first_pub.

    Args:
        work_shards: streamed work records (run_m1 passes the snapshot_reader stream; tests pass a fixture list).
        econ_dept_ids: the department boundary set produced by the sole U0.5 producer (bare canonical edu ids).
        registry_by_id: {bare id: record} produced by build_registry.
        first_pub: a FirstPubAccumulator closure with .add(author_id, year) -
                   the true career first-publication year needs the full history, so pass-A feeds every (author, year) during the
                   full scan, non-seed authors included.
    Returns: PassAResult(seed_authors, seed_work_ids, seen_authors).

    Institution folding uses the real U0 fold_to_canonical + in_au_econ_dept (pure functions, only called, never changed).
    """
    result = PassAResult()
    for work in work_shards:
        wid = _bare(work.get("id"))
        year = work.get("publication_year")
        is_seed, seed_authors_here = _work_is_seed(
            work, econ_dept_ids=econ_dept_ids, registry_by_id=registry_by_id
        )
        if is_seed:
            result.seed_authors |= seed_authors_here
            if wid is not None:
                result.seed_work_ids.add(wid)
        # Piggy-back: feed every (author, year) to first_pub (non-seed authors included - only the full history gives the true first-publication year).
        for author_id, _institutions in _iter_authorships(work):
            if author_id is None:
                continue
            result.seen_authors.add(author_id)
            if year is not None:
                first_pub.add(author_id, year)
    return result


# ===========================================================================
# pass-B: write works/refs + cache ALL authorship edges + piggy-back sinks + collect the frontier
# ===========================================================================
@dataclass
class PassBResult:
    frontier: set[str] = field(default_factory=set)       # Set of bare ids of expansion works referenced by seed works
    edge_count: int = 0                                    # Number of cached authorship edges (non-seed authors included)


def pass_b(
    work_shards: Iterable[Mapping[str, Any]],
    *,
    seed_authors: set[str],
    edge_sink: Callable[[str, str, Any], None],
    works_sink: Optional[Callable[[Mapping[str, Any]], None]] = None,
    refs_sink: Optional[Callable[[str, str], None]] = None,
    affil_sink: Optional[Callable[[Mapping[str, Any]], None]] = None,
    inst_sink: Optional[Callable[[Mapping[str, Any]], None]] = None,
    text_sink: Optional[Callable[[Mapping[str, Any]], None]] = None,
    fwci_accumulator: Any = None,
    seed_work_ids: Optional[set[str]] = None,
) -> PassBResult:
    """For seed-related works: write the tables + cache ALL authorship edges + accumulate fwci + collect the frontier.

    Args:
        seed_authors: the in-department author set from pass-A (used to decide whether a work is seed-related).
        edge_sink(work_id, author_id, year): caches one authorship edge -
            called for EVERY author of a seed work (non-seed collaborators included - the key test case), never only the seed authors.
        works_sink(work) / refs_sink(work_id, ref_id) / affil_sink / inst_sink / text_sink:
            row-level expansion / writing closures (the real implementations of the sibling modules; tests may pass only some or none).
            All field mapping is inside these closures; this function only decides whom to call, and does not repeat field logic.
        fwci_accumulator: if it has .add(work), it is called for every work written (covers all works).
        seed_work_ids: if given, used to decide seed works; otherwise "the work contains one of seed_authors".
    Returns: PassBResult(frontier, edge_count).

    Seed-related work = work_id in seed_work_ids, or its authors intersect seed_authors.
    """
    result = PassBResult()
    for work in work_shards:
        wid = _bare(work.get("id"))
        year = work.get("publication_year")
        authors_here = {a for a, _ in _iter_authorships(work) if a is not None}
        is_relevant = (
            (seed_work_ids is not None and wid in seed_work_ids)
            or bool(authors_here & seed_authors)
        )
        if not is_relevant:
            continue

        # Write the works row (field mapping belongs to works_sink).
        if works_sink is not None:
            works_sink(work)
        # Accumulate fwci (covers every work written).
        if fwci_accumulator is not None:
            fwci_accumulator.add(work)
        # Write work_text / works_affil / institutions (field mapping belongs to each sink).
        if text_sink is not None:
            text_sink(work)
        if affil_sink is not None:
            affil_sink(work)
        if inst_sink is not None:
            inst_sink(work)

        # Cache ALL authorship edges of this work (non-seed collaborators included).
        for author_id, _institutions in _iter_authorships(work):
            if author_id is None:
                continue
            edge_sink(wid, author_id, year)
            result.edge_count += 1

        # refs_edges + collect the frontier (cited expansion works).
        for raw_ref in work.get("referenced_works") or []:
            ref_id = _bare(raw_ref)
            if ref_id is None:
                continue
            if refs_sink is not None:
                refs_sink(wid, ref_id)
            result.frontier.add(ref_id)
    return result


# ===========================================================================
# pass-C: rescan the frontier; dangling ratio > the threshold -> exit(EXIT_FRONTIER_MISS=20)
#   About 10% of OpenAlex referenced_works point to works that were merged or deleted (an expected consequence of the official data,
#   dangling references are normal; a full run measured 9.7%); the old "HALT on a single missing work" killed a 33h run
#   -> now tolerate + record + threshold gate.
# ===========================================================================
@dataclass
class PassCResult:
    hits: int = 0                                          # Number of frontier works actually hit in the rescanned shards
    frontier_count: int = 0
    missing_count: int = 0                                 # Number of dangling (not hit) frontier works
    missing_ratio: float = 0.0                             # missing_count / frontier_count


def pass_c(
    work_shards: Iterable[Mapping[str, Any]],
    *,
    frontier: set[str],
    works_sink: Optional[Callable[[Mapping[str, Any]], None]] = None,
    missing_sink: Optional[Callable[[list[str]], None]] = None,
    missing_ratio_halt: Optional[float] = None,
) -> PassCResult:
    """Rescan the frontier (works referenced by seed works) to fill in their works rows; HALT only if dangling exceeds the threshold.

    Args:
        work_shards: stream of rescanned shards (run_m1's second snapshot pass; tests pass fixtures).
        frontier: set of bare ids of expansion works collected by pass-B.
        works_sink(work): writes the works row of a frontier work (field mapping belongs to the sink).
        missing_sink(sorted_ids): when there are dangling ids, receives the sorted list of dangling ids first, WHETHER OR NOT it HALTs
            (the caller writes a sidecar - the lesson of the 123GB incident that left no diagnostic clue).
        missing_ratio_halt: HALT threshold on the dangling ratio; None -> read redlines.yaml pass_c.missing_ratio_halt
            (set to 0.15; a null value raises RedlineUnsigned).
    Returns: PassCResult(hits, frontier_count, missing_count, missing_ratio).
    Exit:
        SystemExit(EXIT_FRONTIER_MISS=20) - missing_ratio > threshold
        (dangling references are normal for OpenAlex; above the threshold it looks more like a real incident: shards missed / schema changed / wrong path).

    Semantics: edges to dangling references are still recorded (refs_edges untouched); only the target work has no metadata row;
          downstream table reads must recognise the empty node and never count it as a 0 value in FWCI/dose.
    Idempotent: the same frontier id appearing several times in the rescan counts as a single hit (counted by hit set).
    """
    import sys

    hit_ids: set[str] = set()
    for work in work_shards:
        wid = _bare(work.get("id"))
        if wid in frontier:
            hit_ids.add(wid)
            if works_sink is not None:
                works_sink(work)

    return _finalize_frontier_missing(
        hit_ids, frontier, missing_sink=missing_sink, missing_ratio_halt=missing_ratio_halt
    )


def _finalize_frontier_missing(
    hit_ids: set,
    frontier: set,
    *,
    missing_sink: Optional[Callable[[list[str]], None]] = None,
    missing_ratio_halt: Optional[float] = None,
) -> PassCResult:
    """Shared tail of pass-C (the serial pass_c and the parallel scan_workers version share the same semantics):
    record the missing count/ratio -> missing_sink writes diagnostics first -> HALT only above the threshold."""
    import sys

    result = PassCResult(hits=len(hit_ids), frontier_count=len(frontier))
    if result.hits < result.frontier_count:
        missing = sorted(frontier - hit_ids)
        result.missing_count = len(missing)
        result.missing_ratio = result.missing_count / result.frontier_count
        if missing_sink is not None:
            missing_sink(missing)                          # Write diagnostics before HALT (the order is deliberate)
        if missing_ratio_halt is None:
            from common._redlines import require
            missing_ratio_halt = require("pass_c", "missing_ratio_halt")
        if result.missing_ratio > missing_ratio_halt:
            sys.stderr.write(
                f"[pass_c] frontier dangling above threshold: hits={result.hits} < frontier={result.frontier_count}; "
                f"missing={result.missing_count} ({result.missing_ratio:.4f} > {missing_ratio_halt}); "
                f"missing(first 5)={missing[:5]} — HALT exit({EXIT_FRONTIER_MISS})\n"
            )
            sys.exit(EXIT_FRONTIER_MISS)
        sys.stderr.write(
            f"[pass_c] dangling references tolerated (S1): missing={result.missing_count}/"
            f"{result.frontier_count} ({result.missing_ratio:.4f} ≤ {missing_ratio_halt}) — continue\n"
        )
    return result
