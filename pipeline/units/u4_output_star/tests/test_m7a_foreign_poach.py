"""M7a foreign_poach — purely foreign poach filter (definition: moved in from outside Australia + never employed in Australia before).

Key: to judge "was in Australia before arrival" the pollution must be cleaned first (S8-7) — otherwise fake Australian records wrongly kill a true outside hire (the Zenou lesson).
Both kinds of pollution are cleaned: CEPR parse explosion (one raw string → several institutions including a fake Monash) + stamp back-fill (the current unit back-filled onto old papers).
Reuses pollution_guard.is_parse_explosion + is_stamped_affil.
"""


def test_foreign_poach_when_all_au_is_pollution():
    """Zenou type: all pre-arrival AU is pollution (CEPR explosion + stamped Monash) + a true overseas record → foreign poach True."""
    from m7a_star.foreign_poach import is_foreign_poach
    rows = [
        {"raw_affil": "Centre for Economic Policy Research (CEPR)", "canonical_affil_id": "I56590836", "country_code": "AU"},
        {"raw_affil": "Centre for Economic Policy Research (CEPR)", "canonical_affil_id": "I161593684", "country_code": "SE"},
        {"raw_affil": "Monash University - Department of Economics", "canonical_affil_id": "I56590836", "country_code": "AU"},
        {"raw_affil": "Stockholm University", "canonical_affil_id": "I161593684", "country_code": "SE"},
    ]
    assert is_foreign_poach(rows) is True


def test_not_foreign_poach_when_real_au_before():
    """Truly in Australia before arrival (a single-institution, non-stamped UTS) → not a purely foreign poach."""
    from m7a_star.foreign_poach import is_foreign_poach
    rows = [
        {"raw_affil": "Economics Discipline Group, University of Technology Sydney", "canonical_affil_id": "I1234", "country_code": "AU"},
        {"raw_affil": "Yale University", "canonical_affil_id": "I5678", "country_code": "US"},
    ]
    assert is_foreign_poach(rows) is False


def test_not_foreign_poach_when_no_overseas_evidence():
    """No overseas evidence ever (only AU) → does not count as "moved in from outside"."""
    from m7a_star.foreign_poach import is_foreign_poach
    rows = [{"raw_affil": "University of Melbourne", "canonical_affil_id": "I999", "country_code": "AU"}]
    assert is_foreign_poach(rows) is False


def test_empty_pre_history_not_foreign_poach():
    """No institution records at all before arrival → no "moved in from outside" evidence → False (no hard judgement)."""
    from m7a_star.foreign_poach import is_foreign_poach
    assert is_foreign_poach([]) is False
