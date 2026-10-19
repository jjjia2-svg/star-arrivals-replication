"""stock_query: duckdb query of the "citation stock" per person per year (definition A).

The at-scale version of the pure atom person_citation_stock. **Reference pool = all author_ids**
(every author in works = the global economics population, using OpenAlex's own author
disambiguation); it does **not join the internal person_map**. person_map disambiguation is used
only to "recognise the candidates" (candidate person_id ↔ author_id) and is **not** the reference
distribution: using it as the pool puts Yves Zenou only at the 94th percentile and Zenou is missed,
while using all authors puts Zenou at the 99.83 percentile, top 1% (golden test PASS).

The `person_id` column of the output = the ranking entity = **the OpenAlex author_id** (downstream
classify_all_cells calls it person_id generically).
The table names default to works / authorship_edges (duckdb view or CREATE TABLE); the caller registers them first.
"""
from __future__ import annotations

# Per author per year = the sum of raw citations accumulated up to and including that year; full counting (a paper's citations count in full for every author, not divided by the number of authors).
PERSON_YEAR_STOCK_SQL = """
WITH pw AS (
    SELECT e.author_id        AS person_id,
           w.publication_year AS year,
           w.cited_by_count   AS cites
    FROM authorship_edges e
    JOIN works w ON e.work_id = w.work_id
),
per_year AS (
    SELECT person_id, year, SUM(cites) AS year_cites
    FROM pw
    GROUP BY person_id, year
)
SELECT person_id,
       year,
       SUM(year_cites) OVER (
           PARTITION BY person_id ORDER BY year
           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
       ) AS stock
FROM per_year
ORDER BY person_id, year
"""

# Per author per year subfield = the mode of that year's papers; ties take the lexicographically smallest subfield_id (= the smallest number).
PERSON_YEAR_SUBFIELD_SQL = """
WITH pw AS (
    SELECT e.author_id        AS person_id,
           w.publication_year AS year,
           w.subfield_id      AS subfield_id
    FROM authorship_edges e
    JOIN works w ON e.work_id = w.work_id
    WHERE w.subfield_id IS NOT NULL
),
counts AS (
    SELECT person_id, year, subfield_id, COUNT(*) AS n
    FROM pw
    GROUP BY person_id, year, subfield_id
),
ranked AS (
    SELECT person_id, year, subfield_id,
           ROW_NUMBER() OVER (
               PARTITION BY person_id, year
               ORDER BY n DESC, subfield_id ASC
           ) AS rk
    FROM counts
)
SELECT person_id, year, subfield_id
FROM ranked
WHERE rk = 1
ORDER BY person_id, year
"""

# fail-loud: missing citation count (NULL) ≠ 0 citations; SQL SUM silently skips NULL → check with this before a production run, and blow up if > 0.
NULL_CITATION_CHECK_SQL = """
SELECT COUNT(*) AS n_null
FROM authorship_edges e
JOIN works w ON e.work_id = w.work_id
WHERE w.cited_by_count IS NULL OR w.publication_year IS NULL
"""


def assert_no_null_citations(con) -> None:
    """Guard before a real run: if any works that enter the stock have NULL cited_by_count/publication_year → blow up."""
    (n_null,) = con.execute(NULL_CITATION_CHECK_SQL).fetchone()
    if n_null:
        raise ValueError(
            f"stock_query: {n_null} works counted in the stock lack cited_by_count/publication_year "
            f"(missing ≠ 0, SUM would silently drop them) — never silent; clean or fill them first"
        )


def compute_person_year_stock(con) -> list[dict]:
    """Run PERSON_YEAR_STOCK_SQL → [{person_id(=author_id), year, stock}] (ascending)."""
    rows = con.execute(PERSON_YEAR_STOCK_SQL).fetchall()
    return [{"person_id": p, "year": y, "stock": s} for p, y, s in rows]
