"""TDD red tests for U0 common/coauthor_split.py (#10 fractional counting).

Guards PAPER_CONTRIB.frac_credit:
  coauthor_split(...) is fractional counting, with the denominator = number of authors N.

Plain words:
  A paper has N authors and the "credit" is split equally per head: each author gets 1/N. This is
  fractional credit. The denominator is the paper's author count N (not another scheme such as no
  denominator or last-author weighting).
  Example: a paper with 4 co-authors gives each frac_credit = 1/4 = 0.25; all together sum to 1.0.

Rules:
  - The denominator is strictly the author count N; never swapped for N-1, corresponding-author weighting or the integer 1.
  - frac_credit over all authors sums to 1.0 (a single paper's credit is conserved).
  - Feeds PAPER_CONTRIB.frac_credit (float32).

These tests are purely local, with no network and no data fetching (fractional splitting is plain arithmetic).
"""
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common.coauthor_split import coauthor_split  # noqa: E402


# --- core: denominator = number of authors N, 1/N each ---

def test_four_authors_each_quarter():
    # 4 co-authors, each frac_credit = 1/4 = 0.25
    shares = coauthor_split(["A1", "A2", "A3", "A4"])
    assert shares == {"A1": 0.25, "A2": 0.25, "A3": 0.25, "A4": 0.25}


def test_single_author_full_credit():
    # 1 sole author, denominator N=1, that author gets the full 1.0
    shares = coauthor_split(["A1"])
    assert shares == {"A1": 1.0}


def test_two_authors_each_half():
    shares = coauthor_split(["A1", "A2"])
    assert shares == {"A1": 0.5, "A2": 0.5}


def test_denominator_is_byline_count_n():
    # The denominator is strictly the author count N: 5 authors -> 1/5 = 0.2 each (not 1/(N-1) or another scheme)
    authors = ["A1", "A2", "A3", "A4", "A5"]
    shares = coauthor_split(authors)
    for a in authors:
        assert shares[a] == pytest.approx(1.0 / 5)


def test_shares_sum_to_one():
    # a single paper's credit is conserved: frac_credit over all authors sums to 1.0
    authors = [f"A{i}" for i in range(7)]
    shares = coauthor_split(authors)
    assert sum(shares.values()) == pytest.approx(1.0)


def test_share_for_one_author_is_reciprocal_n():
    # take one author's share = 1/N
    authors = ["A1", "A2", "A3"]
    shares = coauthor_split(authors)
    assert shares["A2"] == pytest.approx(1.0 / 3)


# --- degenerate / boundary cases: defensive checks ---

def test_empty_author_list_returns_empty():
    # no authors (N=0) -> empty result (must not divide by zero)
    assert coauthor_split([]) == {}


def test_duplicate_author_ids_collapse_to_distinct_bylines():
    # The same author_id appearing twice in the author list is still one head; N counts distinct authors.
    # (Prevents counting a duplicated byline as two denominator slots, which would dilute the share.)
    shares = coauthor_split(["A1", "A1", "A2"])
    assert set(shares.keys()) == {"A1", "A2"}
    assert shares["A1"] == pytest.approx(0.5)
    assert shares["A2"] == pytest.approx(0.5)
    assert sum(shares.values()) == pytest.approx(1.0)


def test_result_values_are_float():
    # frac_credit feeds PAPER_CONTRIB.frac_credit:float32 -> the value must be a float
    shares = coauthor_split(["A1", "A2", "A3"])
    for v in shares.values():
        assert isinstance(v, float)
