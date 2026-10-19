"""identity/cohort.py — pure functions for academic age / generation bins.

Hard rules (identity layer): no IO / no network / no state / no operational control flow.
  - baseline = career_first_pub_year (the true career first-publication year; set by RED["academic_age"]
    ["baseline"], upstream M1 produces first_pub_year from it, and this module only does arithmetic).
  - The bin-scheme selector of cohort_bin is read from RED["star"]["age_bins"] (= "milojevic"); the
    module does not hardcode the scheme name; an unrecognized scheme -> raise (never silently fall back to a default bin).

In plain words:
  academic_age = focal_year - true career first-publication year.
  academic_age_gap = star.first_pub_year - ego.first_pub_year (the smaller, the closer in generation).
  cohort_bin = milojevic: the first 2 years each stand alone (0 / 1), then one bin per 4 years
                        ("2-5" / "6-9" / "10-13" / ...).

The grid (first 2 years alone (0/1) + one bin per 4 years after: 2-5/6-9/10-13/...) is authoritative.
  An older interface example, cohort_bin->"7-10", was a draft error.
"""
from __future__ import annotations

from common._redlines import require

# Name of the milojevic scheme (the selector read from RED must equal it); threshold for the first 2 years standing alone.
_SCHEME_MILOJEVIC = "milojevic"
_SINGLETON_YEARS = 2   # First 2 years alone (ages 0 and 1 each form a bin)
_BUCKET_WIDTH = 4      # After that, one bin per 4 years


def academic_age(first_pub_year: int, focal_year: int) -> int:
    """Academic age = focal_year - first_pub_year (the true career first-publication year).

    Hard rule: if either year is missing (None) -> raise (never treat it as 0, or a person with no first-publication year would be mistaken for senior/new).
    """
    if first_pub_year is None:
        raise ValueError("academic_age: first_pub_year must not be None (a missing real first-publication year must fail loudly)")
    if focal_year is None:
        raise ValueError("academic_age: focal_year must not be None")
    return int(focal_year) - int(first_pub_year)


def academic_age_gap(ego: dict, star: dict) -> float:
    """Academic-age gap = star.first_pub_year - ego.first_pub_year (the direction exactly as in the interface contract).

    Sign: positive = the star entered later (younger than ego); negative = the star is more senior. The regression layer uses it to split same-generation / cross-generation.
    Hard rule: if either first_pub_year is missing/None -> raise.
    """
    ego_first = ego["first_pub_year"]    # Missing key -> KeyError (intentional)
    star_first = star["first_pub_year"]  # Missing key -> KeyError (intentional)
    if ego_first is None or star_first is None:
        raise ValueError("academic_age_gap: first_pub_year must not be None")
    return float(star_first) - float(ego_first)


def cohort_bin(age: int) -> str:
    """Generation bin (milojevic): the first 2 years alone + one bin per 4 years after.

    The scheme selector is read from RED["star"]["age_bins"] (no hardcoded scheme name); anything other than milojevic
    -> NotImplementedError (never silently fall back to a default bin).

    Returns:
      age 0 -> "0", age 1 -> "1"                       (first 2 years alone)
      age >=2 -> "lo-hi" 4-year bin, lo = 2 + 4*k, hi = lo+3 (such as "2-5"/"6-9"/"10-13")
    Hard rule: age None / negative -> raise (an upstream bug fails loudly).
    """
    if age is None:
        raise ValueError("cohort_bin: age must not be None")
    age_int = int(age)
    if age_int < 0:
        raise ValueError(f"cohort_bin: age must not be negative ({age_int}); upstream bug with focal<first_pub")

    scheme = require("star", "age_bins")  # Read the scheme selector from RED
    if scheme != _SCHEME_MILOJEVIC:
        raise NotImplementedError(
            f"cohort_bin: unrecognised age_bins scheme {scheme!r} — only 'milojevic' is implemented; "
            "never silently fall back to a default binning."
        )

    # First 2 years alone
    if age_int < _SINGLETON_YEARS:
        return str(age_int)

    # After that one bin per 4 years, counted from age=2: 2-5 / 6-9 / 10-13 / ...
    k = (age_int - _SINGLETON_YEARS) // _BUCKET_WIDTH
    lo = _SINGLETON_YEARS + k * _BUCKET_WIDTH
    hi = lo + _BUCKET_WIDTH - 1
    return f"{lo}-{hi}"
