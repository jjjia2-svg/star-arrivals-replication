"""M7a-T8 freeze — the two core parts of freezing star_set/events: stars_set_hash + the Zenou gold-standard gate (step 17).

In plain words: (1) stars_set_hash = a content fingerprint of the "star set + each person's arrival year" (deterministic, order-invariant), which goes into the
provenance four-tuple; (2) the Zenou gold-standard gate = before freezing, the Zenou acceptance check must pass (placed at Monash not Sydney, arrival
2016, 1998 back-fill rejected, affiliations.years not read, the largest cluster not taken); any failure → GOLDEN_FAIL blocks the freeze.

Fixed rules: the Zenou gold standard (must be caught); the classify_golden criteria all live in identity.golden (the only definition;
this layer only calls it and raises on failure). stars_set_hash is computed over normalised content, not raw parquet bytes (S8-8/provenance).
"""
import pytest


def _zenou_good_frame():
    """A Zenou observation frame that passes the gold standard (live ground-truth anchor: works 583, arrival 2016, Monash)."""
    return {
        "found": True, "resolved_single_person": True, "is_star_at_p01": True,
        "institution_canonical_observed": "I56590836",
        "armi_folded_to_monash": True, "caulfield_folded_to_none": True,
        "arrival_year_observed": 2016, "rejected_1998_backfill": True,
        "read_affiliations_years": False, "took_largest_cluster": False,
        "works_count_observed": 583,
    }


# ---- stars_set_hash: content fingerprint (deterministic + order-invariant + content-sensitive) ------------------

def test_stars_set_hash_order_independent():
    """Star set reordered → same fingerprint (computed over normalised content, not insertion order)."""
    from m7a_star.freeze import stars_set_hash
    a = stars_set_hash({"A5017376589": 2016, "P2": 2010})
    b = stars_set_hash({"P2": 2010, "A5017376589": 2016})
    assert a == b


def test_stars_set_hash_changes_with_content():
    """One arrival year changes → fingerprint changes (content-sensitive)."""
    from m7a_star.freeze import stars_set_hash
    assert stars_set_hash({"A": 2016}) != stars_set_hash({"A": 2017})
    assert stars_set_hash({"A": 2016}) != stars_set_hash({"A": 2016, "B": 2016})


# ---- Zenou gold-standard gate: failure → GOLDEN_FAIL blocks the freeze --------------------------------

def test_zenou_good_frame_passes():
    """Good frame → passes the gold standard, no raise."""
    from m7a_star.freeze import assert_zenou_golden
    res = assert_zenou_golden(_zenou_good_frame())
    assert res["structural_pass"] is True and res["observed_in_range"] is True


def test_zenou_sydney_fails_golden():
    """Placed at Sydney (not Monash) → failure → GoldenFailure (blocks the freeze)."""
    from m7a_star.freeze import assert_zenou_golden, GoldenFailure
    bad = dict(_zenou_good_frame(), institution_canonical_observed="University of Sydney")
    with pytest.raises(GoldenFailure):
        assert_zenou_golden(bad)


def test_zenou_1998_backfill_fails_golden():
    """Arrival lands in 1998 (back-fill not stopped) → failure → GoldenFailure."""
    from m7a_star.freeze import assert_zenou_golden, GoldenFailure
    bad = dict(_zenou_good_frame(), arrival_year_observed=1998, rejected_1998_backfill=False)
    with pytest.raises(GoldenFailure):
        assert_zenou_golden(bad)


def test_zenou_read_affiliations_years_fails_golden():
    """Read affiliations.years (violates rule #3) → failure, even if the numbers happen to be right."""
    from m7a_star.freeze import assert_zenou_golden, GoldenFailure
    bad = dict(_zenou_good_frame(), read_affiliations_years=True)
    with pytest.raises(GoldenFailure):
        assert_zenou_golden(bad)
