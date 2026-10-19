"""M6-T1 academic_age: academic age = focal year - true first-publication year.

In plain words: academic age = the year the star arrives - the year of the person's first paper. The first-publication year must come from the U1
work_first_pub table (true career history), not the earliest panel year (which is truncated by the collection boundary). A negative age is an upstream bug: fail loudly.

Rules: #9 age baseline = true first-publication year; focal = arrival-year snapshot (frozen by gen-pk).
This layer = a thin wrapper of identity.cohort.academic_age + a domain guard (negative age raises). Pure function, no IO.
"""
from __future__ import annotations

from identity.cohort import academic_age as _cohort_academic_age

# Note: this module's former verbatim copy is deleted; the single source of truth =
#   u0_foundation identity/first_pub.py::robust_first_pub (the shared pure function; the two namesake-contamination cases of 1963 and
#   1965, Yves Zenou 1991 and the gap<=10 boundary semantics are all pinned there). It is re-exported here to keep the existing
#   import surface (build_star_set / stock_fold_diag / measurement scripts do `from m6_generation.academic_age import`).
from identity.first_pub import robust_first_pub  # noqa: F401  (single-source re-export)


def academic_age(first_pub_year: int, focal_year: int) -> int:
    """Academic age = focal_year - first_pub_year (true first-publication year).

    - first_pub_year is passed by the caller from the U1 work_first_pub true value (not the earliest panel year).
    - Either year missing (None) -> raise (guarded already in identity.cohort).
    - Negative age (first_pub > focal) -> raise: a first-publication year after the arrival year is an upstream bug, never treated as 0.
    """
    age = _cohort_academic_age(first_pub_year, focal_year)
    if age < 0:
        raise ValueError(
            f"academic_age: negative academic age ({age}) — first_pub_year({first_pub_year}) > "
            f"focal_year({focal_year}); upstream bug, failing loudly (never treated as 0)"
        )
    return age
