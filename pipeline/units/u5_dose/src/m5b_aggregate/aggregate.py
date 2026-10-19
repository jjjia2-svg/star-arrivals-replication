"""m5b_aggregate/aggregate.py — feeding layer: paper_contrib -> u0 pure aggregation.

Rule (prevents a recurrence of review finding B5, "several implementations drift apart"):
  the single source of the aggregation formula = u0 identity/output_rule.aggregate_output (12-key definition,
  405+ u0 tests all green). This module **only feeds**: paper_contrib rows -> contribs, where the
  is_star_coauthored flag := work_id is in the exclusion set of this p_level (#2/C1: the same-named marker column of pc is not read —
  that column is a definition marker U4 wrote into the main table; the M5b exclusion set is derived from the single source star_set).
  No accumulation or formula may appear in this file (guarded by a test grep).

Precondition assertion (caveat#4, #40c): paper_contrib must already be in the article+review domain —
  reuse m4_dose.io_load.assert_article_review_domain (checked via works.work_type;
  inherits the U4 filter, neither re-filters nor lets contamination through).

Rows with a missing year: publication_year=None
  cannot enter any per-year computation -> dropped from aggregation + logged in n_dropped_null_pub_year (never silent).
"""
from __future__ import annotations

from identity.output_rule import aggregate_output
from m4_dose.io_load import assert_article_review_domain


def _dedupe_work_incumbent(paper_contrib_rows):
    """pc rows -> contribution units at (work, incumbent) grain (the de-duplication definition set by the U4 producer).

    The docstring of U4 m5_output/paper_contrib.py says in plain words: "every paper is spread into rows of
    'department incumbent i x that paper's co-author p' ... **downstream U5 de-duplicates to (work, incumbent)
    to get each person's output**; taking (i,p) pairs gives the collaboration network". The person dimension is for the
    collaboration network — if output counts were not de-duplicated, the more co-authors a paper has, the more times
    it would be counted (inflated output).

    The work-level values (year/frac/fwci) of rows with the same (work, inc) must agree — disagreement means upstream
    contamination, fail loud, never silently pick one.
    Returns: (units: list[dict] (one per (work, inc)), n_raw_rows: int)
    """
    rows = [r for r in paper_contrib_rows]
    units: dict[tuple, dict] = {}
    for r in rows:
        key = (r["work_id"], r["incumbent_person_id"])
        prev = units.get(key)
        if prev is None:
            units[key] = r
            continue
        for col in ("publication_year", "frac_credit", "fwci"):
            if prev[col] != r[col] and not (prev[col] is None and r[col] is None):
                # NaN != NaN also gets in here — two NaNs count as consistent
                a, b = prev[col], r[col]
                both_nan = (isinstance(a, float) and a != a
                            and isinstance(b, float) and b != b)
                if not both_nan:
                    raise ValueError(
                        f"paper_contrib (work={r['work_id']!r}, "
                        f"inc={r['incumbent_person_id']!r}) inconsistent {col} within the group: "
                        f"{prev[col]!r} vs {r[col]!r} — work-level values must be equal within a group, "
                        "upstream contamination; stop"
                    )
    ordered = [units[k] for k in sorted(units)]   # (work, inc) ascending, deterministic
    return ordered, len(rows)


def to_contribs(paper_contrib_rows, *, exclude_works: frozenset):
    """paper_contrib rows -> contribs argument of u0 aggregate_output (de-duplicate + rename + set flag).

    - first de-duplicate to (work, incumbent) grain (set by the U4 producer, see _dedupe_work_incumbent);
    - year := publication_year (the u0 contract key name);
    - is_star_coauthored := work_id in exclude_works (the exclusion set decides; the pc column is not read);
    - publication_year=None unit: excluded + logged.

    Returns: (contribs: list[dict], stats: dict)
      stats = {n_raw_rows, n_contrib_units, n_dropped_null_pub_year,
               n_excluded_contrib_rows, applied_exclude_works}
      applied_exclude_works = the set of works actually flagged (a subset of exclude_works; for the single-source reconciliation).
    """
    units, n_raw = _dedupe_work_incumbent(paper_contrib_rows)
    contribs: list[dict] = []
    n_null_year = 0
    n_flagged = 0
    applied: set[str] = set()
    for r in units:
        year = r["publication_year"]
        if year is None:
            n_null_year += 1
            continue
        flagged = r["work_id"] in exclude_works
        if flagged:
            n_flagged += 1
            applied.add(r["work_id"])
        contribs.append({
            "incumbent_person_id": r["incumbent_person_id"],
            "year": year,
            "frac_credit": r["frac_credit"],
            "fwci": r["fwci"],
            "is_star_coauthored": flagged,
            "work_id": r["work_id"],   # kept for the quality layer to re-check; u0 aggregation does not read this key -> stripped before aggregating
        })
    stats = {
        "n_raw_rows": n_raw,
        "n_contrib_units": len(contribs) + n_null_year,
        "n_dropped_null_pub_year": n_null_year,
        "n_excluded_contrib_rows": n_flagged,
        "applied_exclude_works": applied,
    }
    return contribs, stats


def aggregate_via_u0(paper_contrib_rows, works_rows, *, exclude_works: frozenset):
    """M5b aggregation entry: domain assertion -> feed -> **call u0 aggregate_output directly** -> 12-key row set.

    Returns: (rows: list[dict] 12 keys (quality=None placeholder), stats: dict)
      stats contains: n_excluded_works (number of works in the exclusion set that actually hit pc) /
                n_papers_fwci_na / n_dropped_null_pub_year / n_excluded_contrib_rows.
    """
    assert_article_review_domain(paper_contrib_rows, works_rows)  # caveat#4 (#40c)
    contribs, stats = to_contribs(paper_contrib_rows, exclude_works=exclude_works)

    u0_contribs = [{k: v for k, v in c.items() if k != "work_id"} for c in contribs]
    rows = aggregate_output(u0_contribs)   # single source of the aggregation formula (u0, prevents B5)

    stats = dict(stats)
    stats["n_excluded_works"] = len(stats.pop("applied_exclude_works"))
    stats["n_papers_fwci_na"] = sum(
        1 for c in contribs
        if c["fwci"] is None or (isinstance(c["fwci"], float) and c["fwci"] != c["fwci"])
    )
    return rows, stats
