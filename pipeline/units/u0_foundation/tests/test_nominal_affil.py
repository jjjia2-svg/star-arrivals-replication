"""identity/nominal_affil: shared pure function for the nominal-affiliation behaviour flag.

In plain words: if "the share of the person's works that carry the home institution" is below the
threshold (star.nominal_affiliation_min_share = 0.05), set nominal_affiliation_flag and put the person on
the manual-review list; **the flag does not drop anyone automatically** (a human reviews the list).
The semantics are identical to u0p5 roster/nominal_affil.flag_member (the prototype); extracted into U0 identity =
single source of truth, for U4 production use (the u0p5 copy duplicates it).
"""
import pytest

from common._redlines import RED, RedlineUnsigned
from identity.nominal_affil import (
    REASON_BELOW,
    REASON_NO_WORKS,
    REASON_ZERO,
    flag_member,
)

TH = 0.05   # star.nominal_affiliation_min_share = 0.05; the flag does not drop anyone


def test_signed_threshold_in_redlines():
    """The threshold is in the red-line config (0.05); consumers read it from RED and never scatter literals."""
    assert RED["star"]["nominal_affiliation_min_share"] == 0.05


def test_no_works_in_corpus_flagged_with_own_reason():
    """A corpus with zero works is not proof of nominal affiliation -> share=None + flag True + a separate reason (cannot be assessed, goes to manual review)."""
    r = flag_member("A1", n_works_total=0, n_works_school=0, threshold=TH)
    assert r["school_share"] is None
    assert r["nominal_affiliation_flag"] is True
    assert r["reason"] == REASON_NO_WORKS


def test_zero_school_works_type():
    """Zero-home-affiliation type: has works but 0 carry the home institution -> share=0 + flag True + reason=zero_school_works."""
    r = flag_member("A2", n_works_total=40, n_works_school=0, threshold=TH)
    assert r["school_share"] == 0.0
    assert r["nominal_affiliation_flag"] is True
    assert r["reason"] == REASON_ZERO


def test_below_threshold_flagged_low_share_type():
    """Low-share type: share 0.019 < 0.05 -> flag True + reason=below_threshold."""
    r = flag_member("A3", n_works_total=105, n_works_school=2, threshold=TH)
    assert r["nominal_affiliation_flag"] is True
    assert r["reason"] == REASON_BELOW


def test_at_or_above_threshold_not_flagged():
    """share >= threshold -> no flag (reason None). Exactly at the threshold is not flagged (< semantics; a share just under the line, 0.0468,
    would be flagged, and is handled as a poaching case and noted in the flag table)."""
    r = flag_member("A4", n_works_total=100, n_works_school=5, threshold=TH)
    assert r["nominal_affiliation_flag"] is False and r["reason"] is None


def test_school_gt_total_fails_loud():
    """Bad counts (school > total) -> ValueError, fails loudly."""
    with pytest.raises(ValueError):
        flag_member("A5", n_works_total=3, n_works_school=4, threshold=TH)


def test_unsigned_threshold_raises():
    """threshold=None (unset) -> RedlineUnsigned, never a silent default (identity rule)."""
    with pytest.raises(RedlineUnsigned):
        flag_member("A6", n_works_total=10, n_works_school=1, threshold=None)
