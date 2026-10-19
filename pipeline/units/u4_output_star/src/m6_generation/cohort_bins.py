"""M6-T2 cohort_bins: academic-age bins (GAP-3 grid) + thin-bin soft warning (GAP-2 threshold 50).

In plain words: cut academic age into bins (0 / 1 / 2-5 / 6-9 / ...); a bin with fewer than 50 people gets a "thin bin" soft flag
(bin_below_min), a reminder not to trust that bin's group-level estimates too much. The true headcount bin_n_authors is stored separately, no information is lost.

Rules: GAP-3 grid = the first 2 years as single bins + one bin per 4 years afterwards (a thin wrapper of identity.cohort.cohort_bin);
GAP-2 min_authors_per_bin=50, decoupled from the percentile hard gate cell_min_n.floor(30) (a display-only soft flag).
Thresholds are read from RED, not hard-coded; unset -> require raises.
"""
from __future__ import annotations

from common._redlines import require
from identity.cohort import cohort_bin as _cohort_bin


def cohort_bin(age: int) -> str:
    """Academic-age bin (GAP-3 grid): 0 and 1 as single bins, then one bin per 4 years. Thin wrapper of identity.cohort.cohort_bin."""
    return _cohort_bin(age)


def bin_below_min(bin_n_authors: int) -> bool:
    """Thin-bin soft warning: the bin has fewer than min_authors_per_bin (50) people -> True (a display-only flag, does not drive estimation).

    The threshold is read from RED (unset -> require raises); decoupled from the percentile hard gate cell_min_n.floor(30).
    The continuous headcount bin_n_authors is stored by the caller in generation_person, no information is lost.
    """
    threshold = require("star", "min_authors_per_bin")
    return bin_n_authors < threshold
