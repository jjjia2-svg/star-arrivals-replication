"""identity/output_rule.py — output aggregation and the single definition of is_star_coauthored.

Three things (every rule is a fixed definition; nothing is invented here):
  1. is_star_coauthored(work, star_person_ids) -> bool
     The single definition (2 arguments, no parallel set). No downstream code may rewrite the test;
     all of it imports this function. The flag column is stored in the main table
     PAPER_CONTRIB.is_star_coauthored, but the FWCI baseline never reads it (see item 2).
  2. fwci_baseline_contribution(work) -> dict
     Accumulation contribution to the FWCI baseline (the denominator population). It never reads
     is_star_coauthored (denominator_leave_star=false, stars are not removed from the denominator):
     the denominator population does not depend on star co-authorship, only on
     subfield/year/work_type/cited_by_count.
  3. aggregate_output(contribs) -> list[dict]
     Builds the OUTPUT table (per person per year, 12 keys):
       three count keys pub_count / pub_count_ex_star / n_works_frac (include papers with missing fwci)
       + four sum keys fwci_frac(_ex_star) / fwci_full(_ex_star) (only papers with non-NA fwci)
       + two mean keys fwci_mean(_ex_star) (0 papers -> None, never filled with 0)
       + a placeholder for quality (None). The exact definition of each key is in that function's docstring.

Pure-function rule (identity layer): no IO, no network, no state; thresholds are read only from RED,
nothing is hard-coded.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable

from common._redlines import require

# Self-check at import: the two fwci rules (denominator_leave_star, numerator_leave_star) must have the
# expected values. If either was changed, the identification rule has changed: fail loudly for a
# human to re-decide; this layer does not pick a fallback.
#   denominator_leave_star=false: the denominator (baseline population) keeps stars, so
#                                 fwci_baseline_contribution does not read that column.
#   numerator_leave_star=true:    the numerator drops star co-authored papers, so aggregate_output
#                                 produces fwci_frac_ex_star.
_DENOMINATOR_LEAVE_STAR = require("fwci", "denominator_leave_star")
_NUMERATOR_LEAVE_STAR = require("fwci", "numerator_leave_star")
if _DENOMINATOR_LEAVE_STAR is not False:
    raise ValueError(
        "RED['fwci'].denominator_leave_star must be false (the denominator does not exclude stars); "
        f"got {_DENOMINATOR_LEAVE_STAR!r} — the rule has changed and a person must re-decide, the code does not decide for itself."
    )
if _NUMERATOR_LEAVE_STAR is not True:
    raise ValueError(
        "RED['fwci'].numerator_leave_star must be true (only papers co-authored with stars are excluded from the numerator); "
        f"got {_NUMERATOR_LEAVE_STAR!r} — the rule has changed and a person must re-decide, the code does not decide for itself."
    )


def is_star_coauthored(work: dict, star_person_ids: Iterable[str]) -> bool:
    """Whether a work is co-authored with any star (the single definition, 2 arguments).

    Args:
        work: dict with at least "author_person_ids": list[str] (person_id of every disambiguated co-author of the work).
        star_person_ids: set of star person_ids (list or set).
    Returns: True if any co-author person_id is in star_person_ids, else False.

    Rule: this is the only definition; downstream code imports it and must not rewrite the test.
          The flag column is stored in the main table PAPER_CONTRIB, but the FWCI baseline never
          reads it (see fwci_baseline_contribution).
    """
    star_set = set(star_person_ids)
    if not star_set:
        return False
    author_ids = work.get("author_person_ids", [])
    return any(pid in star_set for pid in author_ids)


def fwci_baseline_contribution(work: dict) -> dict[str, Any]:
    """Contribution of one work to the FWCI baseline (denominator population).

    Star-removal isolation (denominator_leave_star=false): this function reads only
    subfield_id / year / work_type / cited_by_count. It never reads the is_star_coauthored column.
    The denominator population is all works of the same year, type and subfield (including
    star co-authored ones), regardless of star co-authorship.

    Returns the accumulation key and count:
        {"key": (subfield_id, year, work_type), "cited_by_count": int}
    The FWCI accumulator sums work_count / citation_sum by key (FWCI_BASELINE_POP).
    """
    return {
        "key": (work["subfield_id"], work["year"], work["work_type"]),
        "cited_by_count": work["cited_by_count"],
    }


def _fwci_missing(fwci) -> bool:
    """Whether fwci is missing (NA): None and NaN both count (a parquet/pandas NA arrives as NaN).

    Rule: a paper with missing fwci enters the count keys (pub_count family / n_works_frac) but none of
    the fwci_* aggregates (the six frac/full/mean keys); the mean denominator counts only non-NA papers.
    """
    return fwci is None or (isinstance(fwci, float) and math.isnan(fwci))


def aggregate_output(contribs: Iterable[dict]) -> list[dict]:
    """Aggregate per-work contributions into OUTPUT table rows (per person per year).

    The output has 12 keys (2 identifying keys + 10 value keys).

    contribs: iterable of per-work-per-incumbent contribution dicts, each with at least:
        incumbent_person_id: str
        year: int
        frac_credit: float           # fractional count weight (denominator = number of authors N)
        fwci: float | None           # the work's FWCI; may be missing (None/NaN = NA)
        is_star_coauthored: bool     # flag from the main table PAPER_CONTRIB (used only for the ex-star numerator)

    Produces one OUTPUT row (12 keys, following the schema) per (incumbent_person_id, year).
    Exact definition of the 10 value keys:

      Publication counts (count keys ignore fwci; papers with missing fwci still count):
        pub_count          = number of all papers the person signed that year (plain count, 1 per paper).
        pub_count_ex_star  = same, only papers with no star in the author list (the exclusion set is
                             is_star_coauthored, exactly the same source as fwci_frac_ex_star).
        n_works_frac       = Σ frac_credit (fractional count; robustness column, not in the U6 frame).

      Summed quality (only papers with non-NA fwci; 0 is meaningful, sum=0.0 in an all-NA year):
        fwci_frac          = Σ frac_credit × fwci (headline outcome; fractional credit).
        fwci_frac_ex_star  = same, only papers not co-authored with a star (numerator_leave_star=true).
        fwci_full          = Σ fwci (full count, no splitting; literature-comparison robustness column, not in the frame).
        fwci_full_ex_star  = same, only papers not co-authored with a star.

      Mean quality (each paper weighted equally, no splitting: fractional credit has no meaning in a per-paper average):
        fwci_mean          = Σ fwci ÷ (number of papers with non-NA fwci); denominator 0 -> None
                             (a year with 0 papers is NA, never filled with 0).
        fwci_mean_ex_star  = same, only papers not co-authored with a star; if no non-NA papers remain after
                             removing star papers -> None.

      Placeholder:
        quality            = None. The field-normalised citation ratio needs a cross-table join with
                             the FWCI baseline table and is computed downstream (U5); this pure
                             aggregation layer does not build field-normalised values.

    The denominator keeps stars (denominator_leave_star=false): only the two numerator versions
    (with / without stars) are produced here, with no separate star-removed denominator.
    """
    # Group and accumulate: (incumbent_person_id, year) -> accumulators.
    grouped: dict[tuple[str, int], dict[str, float]] = defaultdict(
        lambda: {
            "pub_count": 0,            # plain count (includes papers with missing fwci)
            "pub_count_ex_star": 0,    # plain count, papers not co-authored with a star only
            "n_works_frac": 0.0,       # Σ frac_credit (includes papers with missing fwci)
            "fwci_frac": 0.0,          # Σ frac×fwci, only papers with non-NA fwci
            "fwci_frac_ex_star": 0.0,
            "fwci_full": 0.0,          # Σ fwci, only papers with non-NA fwci
            "fwci_full_ex_star": 0.0,
            "n_fwci": 0,               # number of papers with non-NA fwci (mean denominator)
            "n_fwci_ex_star": 0,       # number of non-star-coauthored papers with non-NA fwci (mean_ex_star denominator)
        }
    )

    for c in contribs:
        key = (c["incumbent_person_id"], c["year"])
        acc = grouped[key]
        non_star = not c["is_star_coauthored"]          # numerator_leave_star=true: drop star co-authored papers

        # count keys: ignore fwci; papers with missing fwci still count
        acc["pub_count"] += 1
        acc["n_works_frac"] += c["frac_credit"]
        if non_star:
            acc["pub_count_ex_star"] += 1

        # fwci_* keys: only papers with non-NA fwci enter (NA rule)
        fwci = c["fwci"]
        if _fwci_missing(fwci):
            continue
        weighted = c["frac_credit"] * fwci
        acc["fwci_frac"] += weighted                    # numerator keeps stars: count everything
        acc["fwci_full"] += fwci
        acc["n_fwci"] += 1
        if non_star:
            acc["fwci_frac_ex_star"] += weighted
            acc["fwci_full_ex_star"] += fwci
            acc["n_fwci_ex_star"] += 1

    rows: list[dict] = []
    for (incumbent_person_id, year), acc in grouped.items():
        rows.append({
            "incumbent_person_id": incumbent_person_id,
            "year": year,
            "pub_count": acc["pub_count"],
            "pub_count_ex_star": acc["pub_count_ex_star"],
            "n_works_frac": acc["n_works_frac"],
            "fwci_frac": acc["fwci_frac"],
            "fwci_frac_ex_star": acc["fwci_frac_ex_star"],
            "fwci_full": acc["fwci_full"],
            "fwci_full_ex_star": acc["fwci_full_ex_star"],
            # mean: denominator = number of non-NA papers; 0 -> None (a year with 0 papers is NA, never filled with 0)
            "fwci_mean": (acc["fwci_full"] / acc["n_fwci"]) if acc["n_fwci"] else None,
            "fwci_mean_ex_star": (
                (acc["fwci_full_ex_star"] / acc["n_fwci_ex_star"])
                if acc["n_fwci_ex_star"] else None
            ),
            "quality": None,   # Filled downstream (U5) after a cross-table join with the FWCI baseline; this layer does not build field-normalised values.
        })
    return rows
