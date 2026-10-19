"""M6-T4 generation — generation gap + the generation table generation_person.

In plain words: (1) compute "how many cohorts apart is each person from the star" (age gap = star's first-publication year − my first-publication year; smaller = same generation);
(2) build the one-row-per-person generation table: academic age + which age bin + how many people in that bin + a thin-bin flag.

Fixed rules: gen-pk = one row per person, frozen at the arrival year, no year column (schema [25]); age_gap direction
= star − ego; no group/treated column (that is derived in U6, #G/G1).
"""
import pytest

from common.schema import GENERATION_PERSON, assert_matches_schema


def _persons():
    """Three people: P1/P2 have age gap 0 (same bin '0'), P3 has age gap 4 (bin '2-5'). focal = snapshot at the arrival year."""
    return [
        {"person_id": "P1", "first_pub_year": 2016, "focal_year": 2016},
        {"person_id": "P2", "first_pub_year": 2016, "focal_year": 2016},
        {"person_id": "P3", "first_pub_year": 2012, "focal_year": 2016},
    ]


def test_age_gap_two_arg_star_minus_ego():
    """Age gap = star.first_pub − ego.first_pub (two arguments, no focal; a star who started later gives a positive gap)."""
    from m6_generation.generation import academic_age_gap
    assert academic_age_gap({"first_pub_year": 2000}, {"first_pub_year": 2010}) == 10.0


def test_generation_person_schema_5col_no_year():
    """One row per person = the five GENERATION_PERSON [25] columns, no year (gen-pk)."""
    from m6_generation.generation import build_generation_person
    rows = build_generation_person([_persons()[0]])
    assert len(rows) == 1
    assert_matches_schema(rows[0].keys(), GENERATION_PERSON, label="generation_person")
    assert "year" not in rows[0]


def test_bin_n_authors_counts_people_per_bin():
    """bin_n_authors = number of people in the age bin (aggregated across people): P1 and P2 share bin '0' → 2; P3 is in bin '2-5' → 1."""
    from m6_generation.generation import build_generation_person
    by = {r["person_id"]: r for r in build_generation_person(_persons())}
    assert by["P1"]["cohort_age_bin"] == "0"
    assert by["P1"]["bin_n_authors"] == 2
    assert by["P3"]["cohort_age_bin"] == "2-5"
    assert by["P3"]["bin_n_authors"] == 1


def test_thin_bins_flagged_below_50():
    """Counts 2 and 1 are both below the threshold 50 → every bin is flagged thin (display flag only)."""
    from m6_generation.generation import build_generation_person
    rows = build_generation_person(_persons())
    assert all(r["bin_below_min"] is True for r in rows)


def test_no_group_or_treated_column():
    """The generation table produces no group/treated (#G/G1: grouping is derived in U6; U4 only measures)."""
    from m6_generation.generation import build_generation_person
    row = build_generation_person([_persons()[0]])[0]
    assert "group" not in row and "treated" not in row


# ---- Adversarial review C1: duplicate person_id → fail loudly (violates gen-pk PK=person_id) ----------

def test_duplicate_person_id_raises():
    """gen-pk PK=person_id: duplicate person_id from upstream → raise loudly with the id, never silently produce duplicate PK rows
    (that would inflate bin_n_authors and put the M7a "single source of truth" in the wrong cell)."""
    from m6_generation.generation import build_generation_person
    with pytest.raises(ValueError) as ei:
        build_generation_person([
            {"person_id": "P1", "first_pub_year": 2016, "focal_year": 2016},
            {"person_id": "P1", "first_pub_year": 2010, "focal_year": 2016},  # same person, and the first-publication years conflict
        ])
    assert "P1" in str(ei.value)
