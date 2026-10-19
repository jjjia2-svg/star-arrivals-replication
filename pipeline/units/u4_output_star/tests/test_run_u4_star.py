"""run_u4 assembly layer: candidate "arrival-year choice" - the formalised definition from the assembly script.

When several arrival years coexist (e.g. Zenou has a contaminated 1995 + the true 2016): prefer human_verified,
then high confidence, then the earliest non-null. All null -> None (arrival cannot be located, skipped).
"""


def test_pick_arrival_prefers_human_verified():
    """Zenou case: 1995 (low / unverified) vs 2016 (high / hand-verified) -> choose 2016 (avoids the contaminated backfill)."""
    from run_u4 import pick_arrival_year
    rows = [
        {"year_start": 1995, "confidence": "low", "human_verified": False},
        {"year_start": 2016, "confidence": "high", "human_verified": True},
    ]
    assert pick_arrival_year(rows) == 2016


def test_pick_arrival_high_conf_over_low_when_no_human():
    """None hand-verified -> take the high-confidence one."""
    from run_u4 import pick_arrival_year
    rows = [
        {"year_start": 2005, "confidence": "low", "human_verified": False},
        {"year_start": 2011, "confidence": "high", "human_verified": False},
    ]
    assert pick_arrival_year(rows) == 2011


def test_pick_arrival_earliest_when_tied():
    """Hand-verification and confidence both equal -> take the earliest year (conservative)."""
    from run_u4 import pick_arrival_year
    rows = [
        {"year_start": 2015, "confidence": "high", "human_verified": True},
        {"year_start": 2012, "confidence": "high", "human_verified": True},
    ]
    assert pick_arrival_year(rows) == 2012


def test_pick_arrival_all_null_is_none():
    """No arrival year at all (the UNSW batch) -> None (skipped, not made up)."""
    from run_u4 import pick_arrival_year
    rows = [{"year_start": None, "confidence": "high", "human_verified": False}]
    assert pick_arrival_year(rows) is None


# ============ Zenou golden hard gate (must pass before writing to disk) ============

def test_zenou_golden_passes_when_all_five():
    """All five conditions met -> no error."""
    from run_u4 import assert_zenou_golden
    assert_zenou_golden([{"author_id": "A5017376589", "is_star_1pct": True,
                          "is_foreign_poach": True, "arrival": 2016, "dept": "monash_econ"}])


def test_zenou_golden_fails_if_not_top1():
    """Missed (not top 1%) -> GoldenFailure."""
    import pytest
    from run_u4 import assert_zenou_golden, GoldenFailure
    with pytest.raises(GoldenFailure):
        assert_zenou_golden([{"author_id": "A5017376589", "is_star_1pct": False,
                              "is_foreign_poach": True, "arrival": 2016, "dept": "monash_econ"}])


def test_zenou_golden_fails_if_wrong_year():
    """Arrival year contaminated into 1995 -> GoldenFailure."""
    import pytest
    from run_u4 import assert_zenou_golden, GoldenFailure
    with pytest.raises(GoldenFailure):
        assert_zenou_golden([{"author_id": "A5017376589", "is_star_1pct": True,
                              "is_foreign_poach": True, "arrival": 1995, "dept": "monash_econ"}])


def test_zenou_golden_fails_if_absent():
    """Zenou cannot be found -> GoldenFailure (missing a person is not allowed)."""
    import pytest
    from run_u4 import assert_zenou_golden, GoldenFailure
    with pytest.raises(GoldenFailure):
        assert_zenou_golden([])
