"""TDD red tests for U0 identity/first_pub.py: the shared pure function robust_first_pub.

Background:
  The robust first-publication year robust_first_pub used to live only on the candidate side of U4
  (m6_generation/academic_age.py); panel / reference pool / U6 used a bare min, so academic age was clean
  at one end and polluted at the other (a systematic asymmetry). It is now extracted as a shared pure
  function of U0 identity (single source of truth), with semantics identical to the U4 version
  (the 1963/1965/Yves Zenou anchors are all kept).
  Switching production code (panel / pool / U6) to it changes the identification rule and is not done here;
  this file covers only the function itself and its measurement use.

Plain words: robust first-publication year = the true first-publication year after dropping
  "isolated leading old papers" (separated from the real career that follows by more than max_leading_gap years
  = pollution from a same-name person). A continuous career keeps its earliest year.

These tests are purely local, with no network and no data fetching.
"""
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from common._redlines import RedlineUnsigned  # noqa: E402
from identity.first_pub import robust_first_pub  # noqa: E402


def test_drops_isolated_leading_namesake_paper():
    """1963 anchor: a same-name person's report is 32 years before the real career in 1995 -> dropped, first-publication year = 1995."""
    years = [1963, 1995, 1998, 2001, 2005]
    assert robust_first_pub(years, max_leading_gap=10) == 1995


def test_drops_1965_namesake_work():
    """1965 anchor: a same-name person's medical paper -> dropped, true first-publication year 1990."""
    years = [1965, 1990, 1993, 1996]
    assert robust_first_pub(years, max_leading_gap=10) == 1990


def test_keeps_continuous_career_zenou():
    """Yves Zenou anchor: a continuous career (no large gap) -> the earliest year 1991 is kept (a real early paper is not dropped by mistake)."""
    years = [1991, 1994, 1996, 1999, 2003]
    assert robust_first_pub(years, max_leading_gap=10) == 1991


def test_drops_chain_of_isolated_old_papers():
    """Several isolated old papers are skipped one by one: [1930, 1950, 1990, 1995] gap=10 -> 1990."""
    assert robust_first_pub([1930, 1950, 1990, 1995], max_leading_gap=10) == 1990


def test_single_year_is_its_own_debut():
    """Only one year (the last paper has no successor = the only candidate) -> keep it."""
    assert robust_first_pub([2007], max_leading_gap=10) == 2007


def test_duplicates_and_unsorted_input_ok():
    """Repeated / unordered input (the shape of real data) -> equivalent to sorted(set(...))."""
    assert robust_first_pub([2001, 1995, 2001, 1995, 1998], max_leading_gap=10) == 1995


def test_unsigned_gap_raises_redline():
    """max_leading_gap=None (unset threshold) -> RedlineUnsigned, never a silent default."""
    with pytest.raises(RedlineUnsigned):
        robust_first_pub([1995, 1998], max_leading_gap=None)


def test_empty_years_raises():
    """Empty publication years -> ValueError (the true first-publication year cannot be computed; bad data fails loudly)."""
    with pytest.raises(ValueError):
        robust_first_pub([], max_leading_gap=10)


def test_boundary_gap_equal_is_kept():
    """A gap exactly equal to max_leading_gap -> kept (<= semantics, same as the U4 version;
    this is exactly why 1985 for A5071656006 cannot be dropped and must go through work_pollution_discards)."""
    assert robust_first_pub([1985, 1995, 1998], max_leading_gap=10) == 1985
