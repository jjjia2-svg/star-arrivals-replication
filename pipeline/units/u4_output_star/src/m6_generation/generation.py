"""M6-T4 generation: generation gap + generation table generation_person.

In plain words: (1) compute "how many cohorts apart is each person from the star" (age gap age_gap = star first-publication year - my first-publication year; smaller = closer in generation,
the sign itself is a research question and is not presupposed); (2) build a "one row per person" generation table: academic age + which age bin + how many
people in that bin + the thin-bin flag.

Rules: gen-pk = one row per person, frozen at the arrival year, no year column (schema [25]); age_gap direction =
star - ego (verbatim from identity.cohort); no group/treated is produced (that is U6-derived, #G/G1).
generation_pair (with event_id) is produced only after M7a EVENTS, so this module produces only generation_person.
Pure function, no IO.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable

from identity.cohort import academic_age_gap as _cohort_age_gap
from m6_generation.academic_age import academic_age
from m6_generation.cohort_bins import bin_below_min, cohort_bin


def academic_age_gap(ego: dict, star: dict) -> float:
    """Age gap = star.first_pub_year - ego.first_pub_year (thin wrapper; smaller = closer in generation)."""
    return _cohort_age_gap(ego, star)


def build_generation_person(persons: Iterable[dict]) -> list[dict]:
    """Persons -> generation_person rows (one row per person, no year; schema [25]).

    persons: each {person_id, first_pub_year, focal_year}; focal = arrival-year snapshot (frozen by gen-pk).
    Steps: compute academic_age + cohort_age_bin -> count people per bin bin_n_authors -> flag bin_below_min (<50).
    Deterministic: sorted by person_id.
    """
    materialized = list(persons)
    # gen-pk PK=person_id: exactly one arrival-year snapshot per person. Duplicates from upstream -> fail loudly: no silent duplicate-PK rows
    # (they would inflate bin_n_authors and put M7a's "single source of truth" into the wrong cell).
    ids = [p["person_id"] for p in materialized]
    dups = sorted(pid for pid, c in Counter(ids).items() if c > 1)
    if dups:
        raise ValueError(
            f"build_generation_person: duplicate person_id {dups} — the generation table PK is person_id, "
            "each person must have exactly one arrival-year snapshot; upstream duplicates → refusing to silently produce duplicate PK rows"
        )

    computed = []
    for p in materialized:
        age = academic_age(p["first_pub_year"], p["focal_year"])
        b = cohort_bin(age)
        computed.append((p["person_id"], age, b))

    # Cross-person aggregation: how many people in each academic-age bin.
    bin_counts = Counter(b for _, _, b in computed)

    rows = [
        {
            "person_id": person_id,
            "academic_age": age,
            "cohort_age_bin": b,
            "bin_n_authors": bin_counts[b],
            "bin_below_min": bin_below_min(bin_counts[b]),
        }
        for person_id, age, b in computed
    ]
    rows.sort(key=lambda r: r["person_id"])
    return rows
