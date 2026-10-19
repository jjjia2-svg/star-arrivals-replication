"""M7a build_star: assembly layer, compute citation stock -> pick stars within cells (definition A).

In plain words: given a group of people (each with subfield / academic-age band / paper list) + a cutoff year -> compute each person's citation stock (cut at cutoff)
-> pick the top 1%/5% within (subfield x academic age x year) cells. Feeding real data from works/panel/roster is done in run_u4;
this layer only does the deterministic assembly "stock -> cells".
Pure assembly, no IO.
"""
from __future__ import annotations

from identity.cohort import cohort_bin

from m7a_star.citation_stock import person_citation_stock
from m7a_star.star_identify import classify_all_cells


def assemble_records(stock_rows, subfield_rows, first_pub_by_person: dict) -> list[dict]:
    """Merge per-person per-year stock + subfield + academic age -> cell records (fed to classify_all_cells).

    stock_rows: [{person_id, year, stock}] (produced by PERSON_YEAR_STOCK_SQL).
    subfield_rows: [{person_id, year, subfield_id}] (produced by PERSON_YEAR_SUBFIELD_SQL).
    first_pub_by_person: {person_id: true first-publication year} (supplied by the panel).
    - academic age = year - first_pub -> cohort_bin (M6 definition).
    - A (person, year) without subfield is skipped (no cell is invented); a subfield but no first_pub -> raise (bad data).
    Returns [{person_id, subfield_id, cohort_age_bin, year, value(=stock)}]. Pure function.
    """
    sf = {(r["person_id"], r["year"]): r["subfield_id"] for r in subfield_rows}
    out: list[dict] = []
    for s in stock_rows:
        pid, yr = s["person_id"], s["year"]
        subfield_id = sf.get((pid, yr))
        if subfield_id is None:
            continue
        fp = first_pub_by_person.get(pid)
        if fp is None:
            raise ValueError(
                f"assemble_records: person {pid!r} has no first_pub_year, so academic age cannot be computed (bad data)"
            )
        out.append({
            "person_id": pid,
            "subfield_id": subfield_id,
            "cohort_age_bin": cohort_bin(yr - fp),
            "year": yr,
            "value": s["stock"],
        })
    return out


def identify_stars_at_cutoff(people, *, cutoff_year: int, cell_min_n: dict) -> list[dict]:
    """A group of people + cutoff year -> per-person stock -> pick stars within cells.

    people: each {person_id, subfield_id, cohort_age_bin, works}
            (works = the person's paper list [{publication_year, cited_by_count}]).
    cutoff_year: stock accumulates up to this year (inclusive); for a star arriving at t, pass t-1. cell year = cutoff_year.
    Returns: classify_all_cells output (one row per person, with the cell key + within-cell percentile + is_star_1pct/5pct).
    """
    records = [
        {
            "person_id": p["person_id"],
            "subfield_id": p["subfield_id"],
            "cohort_age_bin": p["cohort_age_bin"],
            "year": cutoff_year,
            "value": person_citation_stock(p["works"], up_to_year=cutoff_year),
        }
        for p in people
    ]
    return classify_all_cells(records, cell_min_n)
