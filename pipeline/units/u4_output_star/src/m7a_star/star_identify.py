"""star_identify: pick the stars within a circle: compute ranks → apply the gates → label yes/no.

In plain words: given the people of one small circle (same subfield × same academic-age bin ×
same year) with their citation stocks, compute each person's in-circle rank (ties share a
rank) → apply the circle gates (top 1% needs 100 people, top 5% needs 30) → label each
person with two yes/no star versions. If the circle is too thin for a tier, that tier is
labelled NA (None).

This layer only assembles three existing parts: fractional_percentiles (in-circle percentile),
cell_estimable (gate) and identity.star_rule.is_star (decision; cutoff=1−p is the single
definition). Pure foreign-poach filtering, the stock intersection and evidence_source belong
to later layers and are not here. Pure functions, no IO.

★ This classify_all_cells/star_identify path is **a diagnostic reference, not equivalent to
  production**. The production star decision is run_u4._STAR_CELL_SQL, which additionally applies
  ① roster-based subfields (candidates all go to economics) ② robust debut year robust_first_pub
  ③ the seniority gate min_academic_age; this path has none of the three and has diverged.
  Do not use it as a production oracle or a consistency baseline (the two paths are
  deliberately not equivalent; do not add a "consistent" assertion).
★ The rank formula is the plain rank method (rank=1+#strictly higher, pct=1−rank/N; the
  mid-rank method is not used). The percentile follows the shared engine pctile_engine
  automatically, but the rest of this diagnostic path is **not in sync** (the star call
  still goes through the floating-point cutoff of identity.is_star, not the exact integer
  arithmetic rank≤p·N of the production star_flags, and it lacks the three production
  fixes above), so do not use it in production.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from identity.star_rule import is_star

from m7a_star.pctile_engine import cell_estimable, fractional_percentiles


def classify_stars_in_cell(people: Iterable[dict], cell_min_n: dict) -> list[dict]:
    """People of one cell → each person {person_id, citation_percentile, is_star_1pct, is_star_5pct}.

    people: each {person_id, value} (value = citation stock: raw citations accumulated to
      t−1; normalisation comes from the step "rank within the same circle", not from Σ score×FWCI, not h-index).
    - Rank: fractional_percentiles (in-circle percentile, ties share a rank).
    - Per-p gate: the cell is not big enough for that p tier (cell_estimable False) → that tier is None (no forced call).
    - Decision: is_star({citation_percentile, cell_n}, p), the single definition in identity.
    - Empty cell → [].
    """
    rows = list(people)
    n = len(rows)
    if n == 0:
        return []

    pcts = fractional_percentiles([r["value"] for r in rows])
    est_1 = cell_estimable(n, 0.01, cell_min_n)   # Top 1% gate (>=100)
    est_5 = cell_estimable(n, 0.05, cell_min_n)   # Top 5% gate (>=30)

    out: list[dict] = []
    for person, pct in zip(rows, pcts):
        srow = {"citation_percentile": pct, "cell_n": n}
        out.append({
            "person_id": person["person_id"],
            "citation_percentile": pct,
            "is_star_1pct": is_star(srow, p=0.01) if est_1 else None,
            "is_star_5pct": is_star(srow, p=0.05) if est_5 else None,
        })
    return out


def classify_all_cells(records: Iterable[dict], cell_min_n: dict) -> list[dict]:
    """All person-year records → grouped into circles by (subfield_id, cohort_age_bin, year) → stars picked in each circle separately.

    records: each {person_id, subfield_id, cohort_age_bin, year, value} (value = citation stock, definition A).
    - Grouping: the same (subfield × academic-age bin × year) forms one normalised circle; inside a circle classify_stars_in_cell is called (ties share a rank).
    - Returns: one row per person {person_id, subfield_id, cohort_age_bin, year, citation_percentile,
      is_star_1pct, is_star_5pct}; **deterministic order** (cell key + person_id ascending, independent of the input order).
    Pure function, no IO.
    """
    cells: dict = defaultdict(list)
    for r in records:
        cells[(r["subfield_id"], r["cohort_age_bin"], r["year"])].append(r)

    out: list[dict] = []
    for sf, ab, yr in sorted(cells):
        for c in classify_stars_in_cell(cells[(sf, ab, yr)], cell_min_n):
            out.append({
                "person_id": c["person_id"],
                "subfield_id": sf,
                "cohort_age_bin": ab,
                "year": yr,
                "citation_percentile": c["citation_percentile"],
                "is_star_1pct": c["is_star_1pct"],
                "is_star_5pct": c["is_star_5pct"],
            })
    out.sort(key=lambda r: (r["subfield_id"], r["cohort_age_bin"], r["year"], r["person_id"]))
    return out
