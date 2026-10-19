"""M6-T1 academic_age — academic age = focal year − true career first-publication year.

In plain words: a person's "academic age" = the year a star arrives − the year of that person's first paper. The first-publication year must come from
the real U1 work_first_pub table (true career history), not the earliest year the person appears in the panel (that one is truncated by the collection boundary).
A negative age (first publication later than the focal year) = upstream bug, blow up loudly.

Rules: academic-age baseline = true career first-publication year; focal = snapshot of the arrival year (frozen by gen-pk).
"""
import pytest


def test_academic_age_from_true_first_pub():
    """Academic age = focal − true first-publication year (2016 − 2000 = 16); the caller passes the work_first_pub true value as the first-publication year."""
    from m6_generation.academic_age import academic_age
    assert academic_age(2000, 2016) == 16


def test_negative_age_raises():
    """First publication later than the focal year → negative age = upstream bug, raise (never let it pass, never treat it as 0)."""
    from m6_generation.academic_age import academic_age
    with pytest.raises(ValueError):
        academic_age(2016, 2000)


def test_none_first_pub_raises():
    """True first-publication year missing → raise (otherwise a person without one is mistaken for senior)."""
    from m6_generation.academic_age import academic_age
    with pytest.raises(ValueError):
        academic_age(None, 2016)


def test_robust_first_pub_is_shared_u0_function():
    """U4's old robust_first_pub copy must be the shared function of u0_foundation
    identity.first_pub itself (single source of truth, semantic drift physically impossible), no longer a second, verbatim-identical implementation."""
    from identity.first_pub import robust_first_pub as shared
    from m6_generation.academic_age import robust_first_pub as u4_copy
    assert u4_copy is shared
