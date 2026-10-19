"""M7a citation_stock: star-ranking metric = raw citation "stock" (definition A).

In plain words: for a person, the sum of the **raw citations** received by all papers up to the year before arrival, t-1 (full counting, no splitting,
no FWCI field normalisation) = the "reputation stock", fed to the within-cell ranking that picks stars. Normalisation comes from the step
"rank within the same cell (subfield x academic age x year)", not here.

Definition (A):
  - Raw citations summed (cited_by_count), **not** sum(share x FWCI), **not** h-index.
  - **Full counting**: a paper's citations all go to the author, not split by number of authors (fractional #10 is used only on the output side).
  - Cut at **t-1** (inclusive); papers published after the cutoff are not counted.
Pure function, no IO.
"""
from __future__ import annotations


def person_citation_stock(works, *, up_to_year: int) -> int:
    """Raw citation stock of a person up to up_to_year (inclusive) = sum of cited_by_count (full counting).

    works: each {publication_year:int, cited_by_count:int} (all of one person's papers).
    Papers published after up_to_year are not counted.
    """
    total = 0
    for w in works:
        year = w["publication_year"]
        if year is None:   # No publication year -> the position in time cannot be determined (even whether it is before t-1) -> raise
            raise ValueError(
                f"person_citation_stock: publication_year is None, cannot place the work in time: {w!r}"
            )
        if year > up_to_year:
            continue
        cites = w["cited_by_count"]
        if cites is None:   # Missing citations != 0 citations; missing = bad data -> raise, never silently treated as 0
            raise ValueError(
                f"person_citation_stock: cited_by_count is None (missing ≠ 0, bad data): {w!r}"
            )
        total += cites
    return total
