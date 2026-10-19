"""TDD red tests for U0 cohort.py.

Guards:
  - academic_age / academic_age_gap / cohort_bin;
    baseline = career_first_pub_year (#9, the true first-publication year of the career).
  - Interface contract:
      academic_age(first_pub_year, focal_year) -> int           (= focal - first)
      academic_age_gap(ego, star) -> float                       (= star.first - ego.first)
      cohort_bin(age) -> str
  - cohort_bin picks its scheme from RED["star"]["age_bins"] = "milojevic" (read from RED, not hard-coded);
    this scheme = first 2 years each on their own + one bin per 4 years after that.
  - identity rule: no IO / no network / no state; the scheme selector is read from RED; an unrecognised scheme -> raise.

Plain words:
  academic_age = current year - true first-publication year. The smaller the age gap between two people, the closer their generation.
  cohort_bin = puts an academic age into a bin: each of the first 2 years on its own, then one bin per 4 years.

These tests are purely local, with no network and no data fetching.
"""
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common._redlines import RED  # noqa: E402
from identity import cohort  # noqa: E402


# ============ academic_age = focal_year − first_pub_year ============

def test_academic_age_basic():
    assert cohort.academic_age(first_pub_year=2000, focal_year=2010) == 10


def test_academic_age_same_year_is_zero():
    assert cohort.academic_age(first_pub_year=2015, focal_year=2015) == 0


def test_academic_age_returns_int():
    out = cohort.academic_age(first_pub_year=2000, focal_year=2007)
    assert isinstance(out, int)
    assert out == 7


def test_academic_age_none_first_pub_raises():
    # true first-publication year missing -> raise (never treat as 0, which would make the person look senior)
    with pytest.raises((ValueError, TypeError)):
        cohort.academic_age(first_pub_year=None, focal_year=2010)


def test_academic_age_none_focal_raises():
    with pytest.raises((ValueError, TypeError)):
        cohort.academic_age(first_pub_year=2000, focal_year=None)


# ============ academic_age_gap = star.first − ego.first ============

def test_academic_age_gap_star_more_senior_positive():
    # star 1990 is more senior than ego 2000 -> gap = 1990 - 2000 = -10
    ego = {"first_pub_year": 2000}
    star = {"first_pub_year": 1990}
    assert cohort.academic_age_gap(ego, star) == -10.0


def test_academic_age_gap_sign_is_star_minus_ego():
    # the direction is strictly star.first - ego.first (interface contract, verbatim)
    ego = {"first_pub_year": 1995}
    star = {"first_pub_year": 2005}
    assert cohort.academic_age_gap(ego, star) == 10.0


def test_academic_age_gap_returns_float():
    ego = {"first_pub_year": 2000}
    star = {"first_pub_year": 2000}
    out = cohort.academic_age_gap(ego, star)
    assert isinstance(out, float)
    assert out == 0.0


def test_academic_age_gap_missing_first_pub_raises():
    with pytest.raises((ValueError, KeyError, TypeError)):
        cohort.academic_age_gap({"first_pub_year": 2000}, {})


def test_academic_age_gap_none_first_pub_raises():
    with pytest.raises((ValueError, TypeError)):
        cohort.academic_age_gap({"first_pub_year": None}, {"first_pub_year": 2000})


# ============ cohort_bin: first 2 years on their own + one bin per 4 years after ============

def test_cohort_bin_age0_singleton():
    # first 2 years on their own: age 0 is its own bin
    assert cohort.cohort_bin(0) == "0"


def test_cohort_bin_age1_singleton():
    assert cohort.cohort_bin(1) == "1"


def test_cohort_bin_age2_starts_four_year_bucket():
    # then one bin per 4 years: ages 2..5 share the bin "2-5"
    assert cohort.cohort_bin(2) == "2-5"
    assert cohort.cohort_bin(3) == "2-5"
    assert cohort.cohort_bin(4) == "2-5"
    assert cohort.cohort_bin(5) == "2-5"


def test_cohort_bin_age6_next_bucket():
    # the next 4-year bin: ages 6..9 share the bin "6-9"
    assert cohort.cohort_bin(6) == "6-9"
    assert cohort.cohort_bin(9) == "6-9"


def test_cohort_bin_age10_bucket():
    assert cohort.cohort_bin(10) == "10-13"


def test_cohort_bin_returns_str():
    assert isinstance(cohort.cohort_bin(7), str)


def test_cohort_bin_reads_scheme_from_red(monkeypatch):
    # the scheme selector is read from RED: changed to an unrecognised scheme -> raise (no silent default binning)
    monkeypatch.setitem(RED["star"], "age_bins", "some_unknown_scheme")
    with pytest.raises((ValueError, NotImplementedError)):
        cohort.cohort_bin(3)


def test_cohort_bin_negative_age_raises():
    # negative academic age = an upstream bug (focal < first_pub): fail loudly, never bin it silently
    with pytest.raises(ValueError):
        cohort.cohort_bin(-1)


def test_cohort_bin_none_age_raises():
    with pytest.raises((ValueError, TypeError)):
        cohort.cohort_bin(None)
