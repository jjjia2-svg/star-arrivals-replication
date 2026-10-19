"""M5-T1 paper_contrib: per-paper contribution rows (+ isc#2).

In plain words: each paper is expanded into rows "department incumbent i x co-author p of this paper", carrying the paper's fractional count
frac_credit (=1/number of signatures) + quality score fwci + whether a star co-authored (isc) + subfield. Downstream U5
de-duplicates to (work, incumbent) for each person's output; taking (i, p) pairs gives the collaboration network.

Rules (fixed; this module only consumes them):
  - frac_credit = 1/number of distinct author_ids (#10 fractional): a repeated signature counts as 1 person;
    0 authors raises (never emits inf); counts author_id, not person -> does not change with U2 cluster merging.
  - Row granularity (work_id, incumbent_person_id, person_id): the schema [18] PK; per work, incumbent x person (M5-T3 invariant).
    Only works with >=1 incumbent.
  - isc#2: the only definition of is_star_coauthored lives in identity.output_rule; this module imports and reuses it,
    never rewrites it. Two-stage: star set passed empty -> all False (placeholder); after M7a freezes star_set, run_u4 backfills.
  - fwci is computed by M5-T2 and passed in; this layer does not recompute (the FWCI path never reads isc, isc is written only in this layer).

Pure-function rule: no IO / no network / no state.
"""
from __future__ import annotations

from typing import Iterable, Mapping

# isc#2 rule: single definition, reused directly; downstream must not rewrite the decision.
from identity.output_rule import is_star_coauthored


def frac_credit(author_ids: Iterable[str]) -> float:
    """Fractional count weight = 1 / number of distinct author_ids (#10 fractional counting).

    - A repeated signature counts as 1 person (de-duplicated by author_id).
    - Counts author_id (the raw signature), not person_id -> does not change with U2 cluster merging.
    - 0 authors -> raise ValueError (never 1/0 giving inf).
    """
    n = len(set(author_ids))
    if n == 0:
        raise ValueError("frac_credit: work has no credited authors (author_ids empty) — refusing to produce inf from 1/0")
    return 1.0 / n


def build_paper_contrib_rows(
    work: dict,
    *,
    author_person: Mapping[str, str],
    incumbent_person_ids: Iterable[str],
    star_person_ids: Iterable[str] = frozenset(),
) -> list[dict]:
    """One work -> paper_contrib rows (incumbent x person per work).

    Args:
        work: {work_id, author_ids: list[str], publication_year, subfield_id, fwci}.
        author_person: author_id -> person_id (person_map, read-only 2 columns).
        incumbent_person_ids: set of department incumbents' person_ids (table-B roster).
        star_person_ids: set of star person_ids (two-stage: stage 1 passes empty -> isc all False).

    Returns: list of 8-key rows (schema [18]); a work with no incumbent -> [].
    """
    incumbents = set(incumbent_person_ids)
    # author_id -> person_id (an author_id with no mapping does not enter the person set, but still counts in the frac_credit denominator).
    mapped = [author_person[a] for a in work["author_ids"] if a in author_person]
    if any(p is None for p in mapped):
        # U2 contract: person_id should be a non-empty str. On None raise loudly with the work_id, never skip silently
        # (a silent skip is a dangerous default). Fail loudly so the upstream gets checked.
        raise ValueError(
            f"paper_contrib: person_map value for work {work['work_id']!r} contains None "
            "(U2 contract violated, person_id must be a non-empty str) — refusing to continue silently; check upstream"
        )
    persons = sorted(set(mapped))
    on_work_incumbents = [p for p in persons if p in incumbents]
    if not on_work_incumbents:
        return []

    frac = frac_credit(work["author_ids"])
    # isc: the only definition, fed all co-author person_ids of the work (two-stage: star set empty -> False).
    isc = is_star_coauthored({"author_person_ids": persons}, star_person_ids)

    rows: list[dict] = []
    for inc in on_work_incumbents:              # Sorted by person_id, deterministic
        for p in persons:
            rows.append({
                "work_id": work["work_id"],
                "incumbent_person_id": inc,
                "person_id": p,
                "publication_year": work["publication_year"],
                "frac_credit": frac,
                "fwci": work["fwci"],
                "is_star_coauthored": isc,
                "subfield_id": work["subfield_id"],
            })
    return rows
