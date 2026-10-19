"""M7a-T4 star_identify — pick stars within a cell: compute rank → apply gate → label yes/no (step 12).

In plain words: given the people of a "small cell" (same subfield × same age band × same year) and each one's citation stock, compute each person's within-cell rank
(ties share a rank), apply the cell gate (top 1% needs 100 people, top 5% needs 30), and label each person with two versions of yes/no star (1% / 5%).
A cell too thin for a given tier → that tier is NA (None, no forced judgement).

Fixed rules: rank = self-built three-dimension within-cell rank, ties share a rank, gate = max(pct_p,floor), is_star = the
single definition in identity (cutoff=1−p). This layer only combines these three plus the per-p gate → NA; the purely-foreign-poach filter / stock intersection are later T4 layers.
"""
from common._redlines import RED


def _cmn():
    return RED["star"]["cell_min_n"]


def _cell(n):
    """n people, citation values 0..n-1 (all distinct, no ties); having the highest value first does not matter (ranked by value)."""
    return [{"person_id": f"P{i}", "value": float(i)} for i in range(n)]


def test_top_of_100_cell_is_star_both():
    """100-person cell (passes both gates): the top person is a star at both 1% and 5%; mid-ranked people are not."""
    from m7a_star.star_identify import classify_stars_in_cell
    rows = classify_stars_in_cell(_cell(100), _cmn())
    top = next(r for r in rows if r["person_id"] == "P99")
    assert top["is_star_1pct"] is True and top["is_star_5pct"] is True
    mid = next(r for r in rows if r["person_id"] == "P50")
    assert mid["is_star_1pct"] is False and mid["is_star_5pct"] is False


def test_50person_cell_none_for_1pct_but_5pct_computed():
    """50-person cell: top 1% needs 100 people → not enough → is_star_1pct=None; top 5% needs 30 → enough → computed as usual."""
    from m7a_star.star_identify import classify_stars_in_cell
    rows = classify_stars_in_cell(_cell(50), _cmn())
    top = next(r for r in rows if r["person_id"] == "P49")
    assert top["is_star_1pct"] is None      # cell too thin for 1%
    assert top["is_star_5pct"] is True      # 1−1/50 = 0.98 ≥ 0.95 (naive rank method)


def test_29person_cell_both_none():
    """29-person cell: top 5% needs 30 → not enough; top 1% needs 100 → not enough → both versions None."""
    from m7a_star.star_identify import classify_stars_in_cell
    rows = classify_stars_in_cell(_cell(29), _cmn())
    assert all(r["is_star_1pct"] is None and r["is_star_5pct"] is None for r in rows)


def test_tied_people_share_star_flag():
    """Tied people get the same yes/no (ties share a rank, never split)."""
    from m7a_star.star_identify import classify_stars_in_cell
    # 100 people: the top two tie on the highest value → same rank score → same label
    people = [{"person_id": f"P{i}", "value": float(i)} for i in range(98)]
    people += [{"person_id": "TIE_A", "value": 999.0}, {"person_id": "TIE_B", "value": 999.0}]
    rows = {r["person_id"]: r for r in classify_stars_in_cell(people, _cmn())}
    assert rows["TIE_A"]["is_star_5pct"] == rows["TIE_B"]["is_star_5pct"]
    assert rows["TIE_A"]["citation_percentile"] == rows["TIE_B"]["citation_percentile"]


# ============ classify_all_cells — split into cells by (subfield × age × year), pick stars independently in each cell ============

def test_classify_all_cells_groups_and_ranks_independently():
    """Different cells are ranked separately; each person gets one row carrying the cell key + within-cell percentile."""
    from m7a_star.star_identify import classify_all_cells
    records = [
        {"person_id": "A", "subfield_id": "2002", "cohort_age_bin": "6-9", "year": 2015, "value": 100.0},
        {"person_id": "B", "subfield_id": "2002", "cohort_age_bin": "6-9", "year": 2015, "value": 1.0},
        {"person_id": "C", "subfield_id": "2010", "cohort_age_bin": "6-9", "year": 2015, "value": 50.0},
    ]
    out = classify_all_cells(records, _cmn())
    by = {r["person_id"]: r for r in out}
    assert len(out) == 3
    # Cell (2002,6-9,2015) has two people A>B → naive-rank percentile 1−1/2=0.5 / 1−2/2=0.0; C is alone in another cell → 0.0
    # (naive rank method; the old midpoint values 0.75/0.25/0.5 are retired)
    assert by["A"]["citation_percentile"] == 0.5
    assert by["B"]["citation_percentile"] == 0.0
    assert by["C"]["citation_percentile"] == 0.0
    # cell key carried back
    assert by["A"]["subfield_id"] == "2002" and by["A"]["cohort_age_bin"] == "6-9" and by["A"]["year"] == 2015
    # cell too thin → both star tiers None (1% needs 100, 5% needs 30)
    assert by["A"]["is_star_1pct"] is None and by["A"]["is_star_5pct"] is None


def test_classify_all_cells_deterministic_order():
    """Output is in a deterministic order (by cell key + person_id), independent of input order."""
    from m7a_star.star_identify import classify_all_cells
    recs = [
        {"person_id": "Z", "subfield_id": "2002", "cohort_age_bin": "0", "year": 2020, "value": 3.0},
        {"person_id": "Y", "subfield_id": "2002", "cohort_age_bin": "0", "year": 2020, "value": 9.0},
    ]
    out1 = classify_all_cells(recs, _cmn())
    out2 = classify_all_cells(list(reversed(recs)), _cmn())
    assert [r["person_id"] for r in out1] == [r["person_id"] for r in out2] == ["Y", "Z"]


def test_empty_cell_empty():
    from m7a_star.star_identify import classify_stars_in_cell
    assert classify_stars_in_cell([], _cmn()) == []
