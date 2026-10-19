"""U5 definitions: OUTPUT grows from 6 to 12 keys and ANALYSIS_FRAME from 12 to 15 columns.

Definitions:
  A  Publication count: pub_count / pub_count_ex_star = plain counts (each paper counts 1,
     including papers with missing fwci); the exclusion set is is_star_coauthored, the same
     source as fwci_frac_ex_star.
     n_works_frac = sum of frac_credit (fractional count; robustness column, not in the U6 frame).
     The frame column pub_frac is renamed pub_count (it was always a plain count).
  B  Mean quality per paper: fwci_mean / fwci_mean_ex_star = simple mean over papers with
     non-NA fwci (equal weight per paper, no fractional credit); a denominator (number of
     non-NA papers) of 0 -> None (a year with no papers is NA, never filled with 0).
  D  Benchmark: fwci_full / fwci_full_ex_star = sum of fwci with full counting, no fractional
     credit (non-NA fwci only; not in the frame).
  Unchanged: fwci_frac / fwci_frac_ex_star (the headline outcome, fractional credit) keep their
     definition exactly; quality stays a None placeholder (the field normalisation is computed
     across tables in U5, not in this layer).

Rules (each pinned by a test below):
  - pub_count counts ALL papers (including those whose fwci is NA/None/NaN);
  - the fwci_* family (frac/full/mean, six keys) uses only papers with non-NA fwci;
  - mean denominator = number of non-NA papers; when it is 0 the value is None (never 0);
  - if no non-NA papers remain after dropping stars, fwci_mean_ex_star = None.
"""
import math
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common.schema import ANALYSIS_FRAME, OUTPUT  # noqa: E402
from identity.output_rule import aggregate_output  # noqa: E402

INC = "P_incumbent"


def _one_row(contribs):
    rows = aggregate_output(contribs)
    assert len(rows) == 1
    return rows[0]


# ===========================================================================
# schema constants: OUTPUT 12 keys / ANALYSIS_FRAME 15 columns (final key sets, pinned verbatim)
# ===========================================================================

def test_output_schema_exactly_12_keys_signed_20260709():
    # 2 primary keys + 10 value keys = 12; key names exactly as defined
    assert set(OUTPUT.keys()) == {
        "incumbent_person_id", "year",
        "pub_count", "pub_count_ex_star", "n_works_frac",
        "fwci_frac", "fwci_frac_ex_star",
        "fwci_full", "fwci_full_ex_star",
        "fwci_mean", "fwci_mean_ex_star",
        "quality",
    }
    assert len(OUTPUT) == 12


def test_output_schema_renames_n_works_to_pub_count():
    # n_works is exposed as pub_count (a plain count, honest name); the old name must not remain
    assert "n_works" not in OUTPUT
    assert "pub_count" in OUTPUT


def test_analysis_frame_exactly_15_cols_signed_20260709():
    # 12 -> 15: pub_frac is renamed pub_count, plus new pub_count_ex_star / fwci_mean /
    # fwci_mean_ex_star; the other 11 columns are unchanged
    assert set(ANALYSIS_FRAME.keys()) == {
        "incumbent_person_id", "year", "star_person_id", "event_id",
        "treated", "post", "dose_coupling", "dose_low_confidence", "age_gap",
        "fwci_frac", "pub_count", "fwci_frac_ex_star",
        "pub_count_ex_star", "fwci_mean", "fwci_mean_ex_star",
    }
    assert len(ANALYSIS_FRAME) == 15
    assert "pub_frac" not in ANALYSIS_FRAME  # misleading old name removed


# ===========================================================================
# pub_count / pub_count_ex_star: plain counts, including papers with missing fwci
# ===========================================================================

def test_pub_count_counts_every_paper_including_fwci_missing():
    # 3 papers, 1 with fwci=None -> pub_count=3 (a plain count ignores fwci)
    row = _one_row([
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 0.5,
         "fwci": 2.0, "is_star_coauthored": False},
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 0.25,
         "fwci": 4.0, "is_star_coauthored": False},
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 1.0,
         "fwci": None, "is_star_coauthored": False},
    ])
    assert row["pub_count"] == 3


def test_pub_count_ex_star_counts_only_papers_with_no_star_in_byline():
    # 4 papers: 2 star co-authored (1 of them with missing fwci) + 2 not -> ex_star=2
    # exclusion set = is_star_coauthored, the same source as fwci_frac_ex_star
    row = _one_row([
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 0.5,
         "fwci": 3.0, "is_star_coauthored": True},
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 0.5,
         "fwci": None, "is_star_coauthored": True},
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 1.0,
         "fwci": 1.0, "is_star_coauthored": False},
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 1.0,
         "fwci": None, "is_star_coauthored": False},
    ])
    assert row["pub_count"] == 4
    assert row["pub_count_ex_star"] == 2


# ===========================================================================
# n_works_frac: sum of frac_credit (fractional count; includes papers with missing fwci; not in the frame)
# ===========================================================================

def test_n_works_frac_sums_frac_credit_over_all_papers():
    # sum of frac_credit = 0.5 + 0.25 + 1.0 = 1.75 (a paper with missing fwci still counts: counts ignore fwci)
    row = _one_row([
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 0.5,
         "fwci": 2.0, "is_star_coauthored": False},
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 0.25,
         "fwci": 4.0, "is_star_coauthored": True},
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 1.0,
         "fwci": None, "is_star_coauthored": False},
    ])
    assert row["n_works_frac"] == 1.75


# ===========================================================================
# fwci_full / fwci_full_ex_star: sum of fwci with full counting, no fractional credit (non-NA fwci only)
# ===========================================================================

def test_fwci_full_sums_unweighted_fwci():
    # with frac_credit=0.5: fwci_frac = 0.5*2 + 0.5*4 = 3.0; fwci_full = 2+4 = 6.0
    # (full counting ignores frac_credit, so the two keys must differ: full does not borrow frac_credit)
    row = _one_row([
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 0.5,
         "fwci": 2.0, "is_star_coauthored": False},
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 0.5,
         "fwci": 4.0, "is_star_coauthored": False},
    ])
    assert row["fwci_full"] == 6.0
    assert row["fwci_frac"] == 3.0


def test_fwci_full_ex_star_sums_only_non_star_papers():
    # the star co-authored paper (fwci=4) is dropped; the non-star paper (fwci=2) is kept -> full_ex_star=2.0, full=6.0
    row = _one_row([
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 1.0,
         "fwci": 4.0, "is_star_coauthored": True},
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 1.0,
         "fwci": 2.0, "is_star_coauthored": False},
    ])
    assert row["fwci_full"] == 6.0
    assert row["fwci_full_ex_star"] == 2.0


# ===========================================================================
# fwci_mean / fwci_mean_ex_star: simple mean over non-NA papers (equal weight, no fractional credit); 0 papers -> None
# ===========================================================================

def test_fwci_mean_is_simple_average_equal_weight_not_frac_weighted():
    # fwci 2 and 4 with very different frac_credit (0.1 vs 1.0) -> mean is still (2+4)/2 = 3.0
    # (equal weight per paper; weighting by frac_credit would give a value != 3, which this test catches)
    row = _one_row([
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 0.1,
         "fwci": 2.0, "is_star_coauthored": False},
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 1.0,
         "fwci": 4.0, "is_star_coauthored": False},
    ])
    assert row["fwci_mean"] == 3.0


def test_fwci_mean_denominator_is_nonna_count_only():
    # 3 papers but 1 has fwci=None -> mean = (2+4)/2 = 3.0 (denominator = 2 non-NA papers, not pub_count 3)
    row = _one_row([
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 1.0,
         "fwci": 2.0, "is_star_coauthored": False},
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 1.0,
         "fwci": 4.0, "is_star_coauthored": False},
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 1.0,
         "fwci": None, "is_star_coauthored": False},
    ])
    assert row["fwci_mean"] == 3.0


def test_fwci_mean_zero_nonna_papers_is_none_not_zero():
    # all fwci missing -> denominator 0 -> fwci_mean = None (a year with no papers is NA, never filled with 0);
    # sum-type keys keep a meaningful 0 (fwci_frac/fwci_full = 0.0), and counts are still recorded
    row = _one_row([
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 1.0,
         "fwci": None, "is_star_coauthored": False},
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 0.5,
         "fwci": None, "is_star_coauthored": False},
    ])
    assert row["fwci_mean"] is None
    assert row["fwci_mean_ex_star"] is None
    assert row["pub_count"] == 2
    assert row["fwci_frac"] == 0.0
    assert row["fwci_full"] == 0.0


def test_fwci_mean_ex_star_none_when_all_nonna_papers_are_star_coauthored():
    # only the star co-authored paper has non-NA fwci; the non-star paper's fwci is missing -> after dropping stars the non-NA count = 0 -> None
    # (the with-stars mean is normal = 4.0; the ex_star count is still 1: counts and means are independent)
    row = _one_row([
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 1.0,
         "fwci": 4.0, "is_star_coauthored": True},
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 1.0,
         "fwci": None, "is_star_coauthored": False},
    ])
    assert row["fwci_mean"] == 4.0
    assert row["fwci_mean_ex_star"] is None
    assert row["pub_count_ex_star"] == 1


def test_fwci_mean_ex_star_simple_average_of_non_star_nonna():
    row = _one_row([
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 0.5,
         "fwci": 10.0, "is_star_coauthored": True},
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 0.5,
         "fwci": 1.0, "is_star_coauthored": False},
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 0.25,
         "fwci": 3.0, "is_star_coauthored": False},
    ])
    assert row["fwci_mean_ex_star"] == 2.0   # (1+3)/2: equal weight, the star paper is not included
    assert row["fwci_mean"] == 14.0 / 3      # (10+1+3)/3


# ===========================================================================
# uniform meaning of missing fwci: None and NaN both count as missing; a paper with missing fwci counts in the counts but in no fwci_*
# ===========================================================================

def test_fwci_missing_paper_in_counts_but_in_no_fwci_aggregate():
    # a single paper with fwci=None: every count key records it, and all six fwci keys are "empty aggregates" (sum=0 / mean=None)
    row = _one_row([
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 0.5,
         "fwci": None, "is_star_coauthored": False},
    ])
    assert row["pub_count"] == 1
    assert row["pub_count_ex_star"] == 1
    assert row["n_works_frac"] == 0.5
    assert row["fwci_frac"] == 0.0
    assert row["fwci_frac_ex_star"] == 0.0
    assert row["fwci_full"] == 0.0
    assert row["fwci_full_ex_star"] == 0.0
    assert row["fwci_mean"] is None
    assert row["fwci_mean_ex_star"] is None


def test_fwci_nan_treated_as_missing_like_none():
    # NaN (the NA form in parquet/pandas) is equivalent to None: not in fwci_*, does not poison the sum, counted in the counts
    row = _one_row([
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 1.0,
         "fwci": float("nan"), "is_star_coauthored": False},
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 1.0,
         "fwci": 2.0, "is_star_coauthored": False},
    ])
    assert row["pub_count"] == 2
    assert row["fwci_frac"] == 2.0          # the NaN paper did not turn the sum into NaN
    assert not math.isnan(row["fwci_full"])
    assert row["fwci_full"] == 2.0
    assert row["fwci_mean"] == 2.0          # the denominator counts only the 1 non-NA paper


# ===========================================================================
# row key set = the new OUTPUT 12 keys; quality stays a None placeholder
# ===========================================================================

def test_aggregate_row_keys_exactly_new_output_schema():
    row = _one_row([
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 1.0,
         "fwci": 3.0, "is_star_coauthored": False},
    ])
    assert set(row.keys()) == set(OUTPUT.keys())


def test_quality_remains_none_placeholder():
    # quality = field normalisation, computed across tables in U5; this pure aggregation layer keeps the None placeholder (deliberately left unchanged)
    row = _one_row([
        {"incumbent_person_id": INC, "year": 2016, "frac_credit": 1.0,
         "fwci": 3.0, "is_star_coauthored": False},
    ])
    assert row["quality"] is None
