"""M1-T-WAFF works_affil.py: the WORKS_AFFIL table (the key input for disambiguating
the 13 author-id fragments of Yves Zenou).

What it does:
  - One row per authorship x institution: {work_id, author_id, institution_id,
    raw_affiliation_strings:list<str>};
  - If the institution resolves to nothing, still emit one row with institution_id=None
    (raw_affil is then the only fallback, left for U2 disambiguation);
  - raw_affiliation_strings stays a list<str> exactly as given, never flattened or zeroed
    (disambiguation depends on it);
  - author_id / institution_id are mapped to canonical through canonical_id_map
    (same canonical space).

Official OpenAlex usage:
  authorships[].raw_affiliation_strings = list[str] of raw, unformatted affiliation
  strings = the key input for disambiguation;
  institutions[] is often empty, so department membership falls back to raw_affil plus
  manual review; do not rely on institutions alone.
  Never collide with AUTHORSHIP_EDGES (HIGH-4): raw_affil/institution go in this table
  alone, not in authorship_edges.

Red line: pure data shape, no identification choices; the canonical mapping only looks up
cmap and keeps the bare id when missing (nothing is invented).
"""
from __future__ import annotations

from typing import Iterable, Iterator, Mapping, Optional

from common.schema import WORKS_AFFIL
from m1_ingest._writer_util import bare, write_rows_parquet


def _raw_affils(authorship: dict) -> list:
    """Take authorship.raw_affiliation_strings as a list<str> exactly as given (None -> []).

    Keeps the original strings and their order; never flatten, dedupe or zero them
    (disambiguation uses these raw strings to merge Yves Zenou's 13 fragments).
    """
    raw = authorship.get("raw_affiliation_strings")
    if raw is None:
        return []
    return list(raw)


def iter_works_affil_rows(work: dict) -> Iterator[dict]:
    """One work -> one row per authorship x institution (also one row when the institution is empty).

    - With institutions: one row per institution (institution_id=bare(inst.id));
    - Empty institutions: one row with institution_id=None (raw_affil is the fallback);
    - raw_affiliation_strings goes on every row (that authorship's raw strings, as given).
    author_id/institution_id are only made bare here; canonical mapping is done in
    WorksAffilWriter / run_m1.
    """
    work_id = bare(work.get("id"))
    for authorship in work.get("authorships") or []:
        author_id = bare((authorship.get("author") or {}).get("id"))
        raw = _raw_affils(authorship)
        institutions = authorship.get("institutions") or []
        if not institutions:
            # An empty institution still gets one row (raw_affil is the only fallback, left for disambiguation)
            yield {
                "work_id": work_id,
                "author_id": author_id,
                "institution_id": None,
                "raw_affiliation_strings": raw,
            }
            continue
        for inst in institutions:
            yield {
                "work_id": work_id,
                "author_id": author_id,
                "institution_id": bare((inst or {}).get("id")),
                "raw_affiliation_strings": raw,
            }


class WorksAffilWriter:
    """Accumulate works_affil rows and map their ids to canonical.

    author_cmap / institution_cmap = {raw_id: canonical_id} (replayed from M0 merged_ids);
    add() maps each id to canonical and keeps ids missing from the cmap as they are
    (no mapping: nothing is invented).
    raw_affiliation_strings always stays an untouched list<str>.
    """

    def __init__(
        self,
        *,
        author_cmap: Optional[Mapping[str, str]] = None,
        institution_cmap: Optional[Mapping[str, str]] = None,
    ):
        self._author_cmap = author_cmap or {}
        self._institution_cmap = institution_cmap or {}
        self._rows: list[dict] = []

    def add(self, *, work_id, author_id, institution_id, raw_affiliation_strings) -> None:
        a = self._author_cmap.get(author_id, author_id) if author_id is not None else None
        i = (
            self._institution_cmap.get(institution_id, institution_id)
            if institution_id is not None
            else None
        )
        self._rows.append({
            "work_id": work_id,
            "author_id": a,
            "institution_id": i,
            "raw_affiliation_strings": list(raw_affiliation_strings or []),
        })

    def add_work(self, work: dict) -> None:
        """Convenience: add all works_affil rows of one work (through the cmap)."""
        for r in iter_works_affil_rows(work):
            self.add(**r)

    def rows(self) -> list[dict]:
        return list(self._rows)

    def write(self, target) -> None:
        write_works_affil(self._rows, target)


def write_works_affil(rows: Iterable[dict], target) -> None:
    """Write the WORKS_AFFIL parquet (deterministic, with a schema guard before writing).

    Sort key = (work_id, author_id, institution_id): one (work, author) can have several
    institutions -> several rows, so institution_id must be in the sort key for byte-level
    determinism (institution_id=None sorts after the non-None values in the same column).
    """
    write_rows_parquet(
        rows, target,
        schema=WORKS_AFFIL,
        pk_cols=("work_id", "author_id", "institution_id"),
        label="WORKS_AFFIL",
    )
