"""M6-T2 cohort_bins — academic-age bins (grid) + thin-bin soft warning (threshold 50).

In plain words: cut academic age into bins (0 / 1 / 2-5 / 6-9 / …); a bin with fewer than 50 people gets a "thin bin" flag
(bin_below_min), a reminder not to trust that bin's group-level estimate too much. The true head count bin_n_authors is stored separately, so no information is lost.

Rules: grid = the first 2 years as single bins, then one bin per 4 years; min_authors_per_bin=50, decoupled from the hard floor of 30
(a display-only soft flag). Thresholds are read from RED, not hard-coded.
"""
from common._redlines import RED


def test_cohort_bin_signed_grid_shape():
    """Grid: 0→"0", 1→"1", 2/5→"2-5", 6→"6-9", 10→"10-13"."""
    from m6_generation.cohort_bins import cohort_bin
    assert cohort_bin(0) == "0"
    assert cohort_bin(1) == "1"
    assert cohort_bin(2) == "2-5"
    assert cohort_bin(5) == "2-5"
    assert cohort_bin(6) == "6-9"
    assert cohort_bin(10) == "10-13"


def test_bin_below_min_threshold_reads_signed_50():
    """Thin-bin soft warning: count < threshold 50 → True; >= → False. The threshold is read from RED, not hard-coded."""
    from m6_generation.cohort_bins import bin_below_min
    thr = RED["star"]["min_authors_per_bin"]
    assert thr == 50                          # pin the threshold value (guard)
    assert bin_below_min(thr - 1) is True     # 49 → thin
    assert bin_below_min(thr) is False        # 50 → not thin
    assert bin_below_min(thr + 50) is False   # 100 → not thin
