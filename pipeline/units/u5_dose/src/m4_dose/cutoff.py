"""m4_dose/cutoff.py — the single t-1 truncation helper (red line #16).

Freeze to t-1 = compute the dose only from data up to the year before the star's arrival year, which prevents
reverse contamination from "the two converging only after arrival" (identification red line #16).

Rules:
  - **T-deg2 / T-coup / T-topic / T-embed are all truncated through this function; nobody writes their own WHERE**
    (keeps the degree-2 branch from drifting to arrival_year on its own; checked by the #7/#25 spy tests).
  - Inclusive bound: publication_year <= t_minus_1 (#6).
  - H4 precondition: every input row must carry a non-None publication_year. refs_edges itself has no year
    (2 columns {work_id, referenced_work_id}, U0 schema), so the year used for truncation must come from a join
    with works.parquet first; a forgotten join raises CutoffYearMissing loudly and never silently keeps everything (#6b).
  - t_minus_1 missing (None) -> ValueError (B-EVENTS-T1: the single source of the freeze point is events.t_minus_1,
    read directly; if it is missing, upstream did not provide it, and the code never falls back to arrival_year-1).
"""
from __future__ import annotations


class CutoffYearMissing(ValueError):
    """A row lacks publication_year (key absent or value None) — H4: the year used for truncation must come from a works join first."""


def filter_works_until(rows, t_minus_1):
    """Filter rows by publication_year <= t_minus_1 (inclusive) — the only truncation entry point in U5.

    Args:
        rows: iterable of dict rows; each row must carry a non-None "publication_year"
              (passing bare 2-column refs_edges rows raises CutoffYearMissing, #6b).
        t_minus_1: freeze year = events.t_minus_1 read directly (int; None -> ValueError).

    Returns:
        list[dict] — the original row objects (not copied), order preserved.

    Raises:
        ValueError        — t_minus_1 is None or not an integer.
        CutoffYearMissing — any row lacks publication_year or has value None.
    """
    if t_minus_1 is None:
        raise ValueError(
            "filter_works_until: t_minus_1 must not be None — the freeze point must be read directly from "
            "events.t_minus_1; the cut-off is never silently skipped."
        )
    if not isinstance(t_minus_1, int):
        raise ValueError(
            f"filter_works_until: t_minus_1 must be an int, got {type(t_minus_1).__name__}"
        )

    kept = []
    for row in rows:
        year = row.get("publication_year")
        if year is None:
            raise CutoffYearMissing(
                "filter_works_until: row lacks publication_year — refs_edges has no year, "
                f"the year used for the cut-off must come from a join with works.parquet first; offending row keys={sorted(row.keys())}"
            )
        if year <= t_minus_1:  # inclusive bound (#6)
            kept.append(row)
    return kept
