"""M7a build_star — orchestration/assembly layer: compute stock → pick stars within cells (pure assembly; real data loading is in run_u4).

In plain words: given a set of people (each with subfield / age band / paper list) + a cutoff year → compute each person's citation stock
(definition A) → pick stars per cell (subfield × age × year). The step that loads real data from works/panel/roster is in
run_u4; this layer only does the deterministic "stock → cell" assembly and is TDD-able on small data.
"""


def _cmn():
    from common._redlines import RED
    return RED["star"]["cell_min_n"]


def test_identify_stars_wires_stock_then_cells():
    """Compute each person's stock first (cut at cutoff) → then rank within cells; higher stock → higher percentile within the cell."""
    from m7a_star.build_star import identify_stars_at_cutoff
    people = [
        {"person_id": "A", "subfield_id": "2002", "cohort_age_bin": "6-9",
         "works": [{"publication_year": 2010, "cited_by_count": 500},
                   {"publication_year": 2018, "cited_by_count": 999}]},   # 2018 > cutoff, not counted
        {"person_id": "B", "subfield_id": "2002", "cohort_age_bin": "6-9",
         "works": [{"publication_year": 2010, "cited_by_count": 2}]},
    ]
    out = identify_stars_at_cutoff(people, cutoff_year=2014, cell_min_n=_cmn())
    by = {r["person_id"]: r for r in out}
    # A's stock=500 (the 2018 paper is past the cutoff, not counted) > B's stock=2 → A has the higher within-cell percentile
    assert by["A"]["citation_percentile"] > by["B"]["citation_percentile"]
    # cell year = cutoff; cell too thin → star tier None
    assert by["A"]["year"] == 2014
    assert by["A"]["is_star_1pct"] is None and by["A"]["is_star_5pct"] is None


def test_identify_stars_separate_subfields_rank_apart():
    """Different subfields are ranked separately (cells are not mixed)."""
    from m7a_star.build_star import identify_stars_at_cutoff
    people = [
        {"person_id": "A", "subfield_id": "2002", "cohort_age_bin": "0",
         "works": [{"publication_year": 2010, "cited_by_count": 5}]},
        {"person_id": "C", "subfield_id": "2010", "cohort_age_bin": "0",
         "works": [{"publication_year": 2010, "cited_by_count": 999}]},
    ]
    out = identify_stars_at_cutoff(people, cutoff_year=2014, cell_min_n=_cmn())
    by = {r["person_id"]: r for r in out}
    # Each is alone in its cell → each gets 1−1/1 = 0.0 (naive rank method; the old midpoint value 0.5 is retired).
    # If cells were wrongly mixed: C(999) would get 0.5 and A still 0.0 → this assertion still catches a mixed-cell regression.
    assert by["A"]["citation_percentile"] == 0.0
    assert by["C"]["citation_percentile"] == 0.0


# ============ assemble_records — merge stock + subfield + age → cell records ============

def test_assemble_records_merges_stock_subfield_age():
    """Three sources in one: value=stock, subfield attached, age=year−first_pub → cohort_age_bin."""
    from m7a_star.build_star import assemble_records
    stock = [{"person_id": "P", "year": 2015, "stock": 9968}]
    subfield = [{"person_id": "P", "year": 2015, "subfield_id": "2002"}]
    first_pub = {"P": 1991}
    recs = assemble_records(stock, subfield, first_pub)
    assert len(recs) == 1
    r = recs[0]
    assert (r["person_id"], r["value"], r["subfield_id"], r["year"]) == ("P", 9968, "2002", 2015)
    assert r["cohort_age_bin"] == "22-25"    # age = 2015−1991 = 24


def test_assemble_skips_person_year_without_subfield():
    """A person with no subfield in a year (all papers that year lack subfield) → no record (no cell is forged)."""
    from m7a_star.build_star import assemble_records
    recs = assemble_records([{"person_id": "P", "year": 2015, "stock": 100}], [], {"P": 1991})
    assert recs == []


def test_assemble_raises_on_missing_first_pub():
    """Has a subfield but no first_pub found = corrupt data → raise at the location (age cannot be computed)."""
    import pytest
    from m7a_star.build_star import assemble_records
    stock = [{"person_id": "P", "year": 2015, "stock": 100}]
    subfield = [{"person_id": "P", "year": 2015, "subfield_id": "2002"}]
    with pytest.raises(ValueError, match="first_pub"):
        assemble_records(stock, subfield, {})
