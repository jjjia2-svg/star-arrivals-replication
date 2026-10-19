"""M7a — two corrections to the star definition.

(1) age_eligible — seniority threshold: within-cell rank at a very low academic age (age 0-1) is noise (the m-quotient problem),
   so such people are excluded from star identification. min_academic_age is read from RED; null → raise.
(2) assign_star_subfield — anchoring the star's cell subfield: OpenAlex tags economists with random cross-field labels,
   and "pick by paper count" puts a true economist into a noise subfield nobody cites (A5027090359→management information systems). Changed to: within the **economics
   scope** (subfield_whitelist: include 2002 + optional 2000) pick **by citations**; no economics
   papers → fall back to 2002 and mark inferred. Reuses the G5 boundary (2003 finance / field 14 business do not count as economics).
Pure functions, no IO.
"""


# ============ (1) age_eligible (seniority threshold) ============

def test_age_eligible_excludes_fresh_phd():
    """Academic age 0 (fresh graduate, e.g. A5046393143) → not eligible (within-cell rank at age≈0 is noise)."""
    from m7a_star.pctile_engine import age_eligible
    assert age_eligible(0, min_academic_age=2) is False


def test_age_eligible_excludes_one_year():
    """Academic age 1 → still not eligible (the first two years, ages 0 and 1, are a degenerate tier)."""
    from m7a_star.pctile_engine import age_eligible
    assert age_eligible(1, min_academic_age=2) is False


def test_age_eligible_passes_at_min():
    """Academic age = threshold → eligible (>=)."""
    from m7a_star.pctile_engine import age_eligible
    assert age_eligible(2, min_academic_age=2) is True


def test_age_eligible_passes_zenou():
    """Zenou arrives in 2016 at academic age 24 → eligible (the gold standard must not be wrongly killed)."""
    from m7a_star.pctile_engine import age_eligible
    assert age_eligible(24, min_academic_age=2) is True


def test_age_eligible_raises_on_unsigned():
    """min_academic_age = None (unset in RED) → raise, never quietly default."""
    import pytest
    from m7a_star.pctile_engine import age_eligible
    from common._redlines import RedlineUnsigned
    with pytest.raises(RedlineUnsigned):
        age_eligible(5, min_academic_age=None)


# ============ (3) star_flags — combine cell-level judgement × seniority threshold (rank ≤ p·N, exact integer arithmetic) ============
# star_flags takes the within-cell competition rank (not a floating-point pct);
# star = rank ≤ p·cell_n, with exact integer arithmetic via Fraction (no floating-point boundary); ties share a rank ⇒ the whole group enters or leaves together.
# The order of the gates is fixed: seniority False (first) → thin cell None → quota test.

_P = dict(p1=0.01, p5=0.05)          # star.percentile_primary / max(percentile_robustness) as configured


def test_star_flags_thin_cell_is_none():
    """Cell too thin (cell_n < top-1% gate) → top-1% tier = None (cannot be estimated, no forced judgement)."""
    from m7a_star.pctile_engine import star_flags
    s1, s5 = star_flags(1, 50, 24, gate1=100, gate5=30, min_academic_age=2, **_P)
    assert s1 is None                # 50 < 100 → None
    assert s5 is True                # 50 >= 30 and rank 1 ≤ 0.05×50=2.5 and old enough → True


def test_star_flags_too_junior_is_false_not_none():
    """Cell large enough but too junior (academic age 0 < threshold) → False (evaluated but ineligible), not None."""
    from m7a_star.pctile_engine import star_flags
    s1, s5 = star_flags(1, 15000, 0, gate1=100, gate5=30, min_academic_age=2, **_P)
    assert s1 is False               # cell large enough, rank 1, but academic age 0 → excluded
    assert s5 is False


def test_star_flags_junior_false_beats_thin_none():
    """Must be red (order of judgement): academic age too low **and** cell too thin: the seniority gate is judged first → both tiers False (not None).
    The age gate classifies a person as "not a star" and runs before the cell gate."""
    from m7a_star.pctile_engine import star_flags
    s1, s5 = star_flags(1, 10, 0, gate1=100, gate5=30, min_academic_age=2, **_P)
    assert s1 is False and s5 is False


def test_star_flags_eligible_top1_true_zenou_anchor():
    """Zenou anchor: rank 18 / 10,308 → 18/10308 ≤ 1/100 → top 1% True (+ top 5%)."""
    from m7a_star.pctile_engine import star_flags
    s1, s5 = star_flags(18, 10308, 24, gate1=100, gate5=30, min_academic_age=2, **_P)
    assert s1 is True
    assert s5 is True


def test_star_flags_top5_not_top1():
    """Rank in (1%·N, 5%·N] → top 5% yes, top 1% no. rank 300/10000: 0.01 < 0.03 ≤ 0.05."""
    from m7a_star.pctile_engine import star_flags
    s1, s5 = star_flags(300, 10000, 8, gate1=100, gate5=30, min_academic_age=2, **_P)
    assert s1 is False               # cell large enough but the rank is outside the 1% quota
    assert s5 is True


def test_star_flags_exact_quota_boundary_integer_arithmetic():
    """Must be red (4) rank ≤ p·N integer boundary: exactly equal to the quota → enters; one place more → out (exact Fraction arithmetic, no floating point)."""
    from m7a_star.pctile_engine import star_flags
    kw = dict(gate1=100, gate5=30, min_academic_age=2, **_P)
    assert star_flags(1, 100, 24, **kw)[0] is True    # 1 == 0.01×100 exactly on the line → enters
    assert star_flags(2, 100, 24, **kw)[0] is False   # 2 > 1 → out
    assert star_flags(5, 100, 24, **kw)[1] is True    # 5 == 0.05×100 exactly on the line → enters
    assert star_flags(6, 100, 24, **kw)[1] is False


def test_star_flags_tie_group_moves_together():
    """Must be red (3): a tie group enters or leaves as a whole (ties share one rank ⇒ same judgement): N=200, 1% quota = 2.
    3 people tied at the top → each rank=1 ≤ 2 → all enter; 2 people tied at 3rd (2 people above them) → rank=3 > 2 → all out."""
    from m7a_star.pctile_engine import star_flags
    kw = dict(gate1=100, gate5=30, min_academic_age=2, **_P)
    in_flags = [star_flags(1, 200, 10, **kw)[0] for _ in range(3)]    # 3 tied people at rank 1
    out_flags = [star_flags(3, 200, 10, **kw)[0] for _ in range(2)]   # 2 tied people at rank 3
    assert in_flags == [True, True, True]
    assert out_flags == [False, False]


def test_star_flags_cutoff_reads_signed_p_not_hardcoded():
    """B1: the quota is computed from the configured p, not hard-coded. p1=0.02 → rank 150/10000 = 0.015 ≤ 0.02 → top 1% True."""
    from m7a_star.pctile_engine import star_flags
    s1, _ = star_flags(150, 10000, 24, gate1=100, gate5=30, min_academic_age=2, p1=0.02, p5=0.05)
    assert s1 is True                # a hard-coded 0.01 would give False (150/10000 > 0.01); reading the configured p=0.02 → True


# ============ (4) robust_first_pub — drop a same-name namesake's "lone leading old paper" ============

def test_robust_first_pub_drops_1963_namesake_report():
    """1963 anchor: a report by a namesake is 32 years before the true career (from 1995) → true debut 1995."""
    from m6_generation.academic_age import robust_first_pub
    years = [1963, 1995, 1998, 1998, 1999, 2002]
    assert robust_first_pub(years, max_leading_gap=10) == 1995


def test_robust_first_pub_drops_1965_namesake_work():
    """1965 anchor: a medical paper by a namesake is 25 years before the true career (from 1990) → true debut 1990."""
    from m6_generation.academic_age import robust_first_pub
    years = [1965, 1990, 1992, 1993, 1994]
    assert robust_first_pub(years, max_leading_gap=10) == 1990


def test_robust_first_pub_keeps_continuous_career():
    """Continuous career (no big gap, e.g. Zenou from 1991) → true debut year unchanged (a true early paper is not wrongly removed)."""
    from m6_generation.academic_age import robust_first_pub
    years = [1991, 1992, 1993, 1995, 1996]
    assert robust_first_pub(years, max_leading_gap=10) == 1991


def test_robust_first_pub_single_paper():
    """Only one paper → that year (a gap cannot be judged, keep it)."""
    from m6_generation.academic_age import robust_first_pub
    assert robust_first_pub([2010], max_leading_gap=10) == 2010


def test_robust_first_pub_small_gap_kept():
    """Gap <= threshold (e.g. 3 years) → not same-name pollution, keep the earliest year."""
    from m6_generation.academic_age import robust_first_pub
    assert robust_first_pub([2000, 2003, 2004], max_leading_gap=10) == 2000


def test_robust_first_pub_empty_raises():
    """No publication year → raise (the debut year cannot be computed; corrupt data fails loudly)."""
    import pytest
    from m6_generation.academic_age import robust_first_pub
    with pytest.raises(ValueError):
        robust_first_pub([], max_leading_gap=10)


def test_robust_first_pub_unsigned_gap_raises():
    """max_leading_gap = None (unset in RED) → raise, never quietly default."""
    import pytest
    from m6_generation.academic_age import robust_first_pub
    from common._redlines import RedlineUnsigned
    with pytest.raises(RedlineUnsigned):
        robust_first_pub([2000, 2001], max_leading_gap=None)
