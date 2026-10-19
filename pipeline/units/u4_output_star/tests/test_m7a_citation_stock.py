"""M7a citation_stock — star ranking metric = raw citation "stock" (definition A).

In plain words: the sum of the **raw citations** received by all of a person's papers up to the year before arrival, t−1 (full counting, no splitting among co-authors,
no FWCI field normalisation). This is the "reputation stock" that feeds the within-cell ranking to pick stars. Normalisation comes from the "compare ranks within the same cell" step,
not from here.

Fixed rules:
  - Cumulate raw citations (cited_by_count), **not** Σ(score×FWCI), **not** h-index.
  - **Full counting**: a citation counts in full for each author, not split by number of authors (as in the star-selection studies this metric follows).
  - Cut at **t−1** (the year before arrival, inclusive); publication year > cutoff → not counted.
  - Missing citations / missing publication year = corrupt data → raise (fail loudly, never treat as 0, never silently drop).
"""
import pytest


def test_stock_sums_raw_citations_up_to_cutoff():
    """Stock = sum of cited_by_count over papers up to t−1 (full counting)."""
    from m7a_star.citation_stock import person_citation_stock
    works = [
        {"publication_year": 2010, "cited_by_count": 5},
        {"publication_year": 2012, "cited_by_count": 3},
        {"publication_year": 2015, "cited_by_count": 100},   # > cutoff, not counted
    ]
    # arrival t=2015 → cutoff t−1=2014 → sum only 2010(5)+2012(3)=8
    assert person_citation_stock(works, up_to_year=2014) == 8


def test_empty_works_is_zero():
    """No papers → stock 0 (not a raise; a legitimate empty)."""
    from m7a_star.citation_stock import person_citation_stock
    assert person_citation_stock([], up_to_year=2020) == 0


def test_cutoff_year_itself_is_included():
    """The cutoff year itself is included: a publication year == up_to_year counts."""
    from m7a_star.citation_stock import person_citation_stock
    works = [{"publication_year": 2014, "cited_by_count": 7}]
    assert person_citation_stock(works, up_to_year=2014) == 7


def test_zero_citations_is_not_missing():
    """0 citations is a real value (the paper was not cited); it takes part as usual and adds 0."""
    from m7a_star.citation_stock import person_citation_stock
    works = [{"publication_year": 2010, "cited_by_count": 0},
             {"publication_year": 2011, "cited_by_count": 4}]
    assert person_citation_stock(works, up_to_year=2014) == 4


def test_none_citation_raises_located():
    """Missing citations (None) = corrupt data → raise at the location (naming cited_by_count), never treat as 0."""
    from m7a_star.citation_stock import person_citation_stock
    works = [{"publication_year": 2010, "cited_by_count": None}]
    with pytest.raises(ValueError, match="cited_by_count"):
        person_citation_stock(works, up_to_year=2014)


def test_none_year_raises_located():
    """Missing publication year (None) = the time cannot be placed → raise at the location (naming publication_year)."""
    from m7a_star.citation_stock import person_citation_stock
    works = [{"publication_year": None, "cited_by_count": 5}]
    with pytest.raises(ValueError, match="publication_year"):
        person_citation_stock(works, up_to_year=2014)
