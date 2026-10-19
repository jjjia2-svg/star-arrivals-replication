"""M7a-T5b pollution_guard — pollution defence: remove the two forms of "fake Australian year" (checks #36/#37, S8-7).

In plain words: two kinds of dirty data can invent a "fake Australian year" for a star — (1) CEPR parse explosion (one raw string is parsed into
a pile of institutions, with Australian ones caught up in it), (2) archive stamping (the author's current unit is stamped back onto old papers: university first + a pure separator directly joined to the department name).
Both are removed from the input of the "never in Australia" judgement and of arrival assembly (S8-7), protecting Zenou from being wrongly excluded / wrongly dated by a fake Monash year.

Zenou real fixture (from the real U3 data): CEPR "Centre for Economic Policy Research (CEPR), London" →
5 inst ids including Monash (I56590836); the stamp "Monash University - Department of Economics" stamped back onto 2003;
true affiliations Southampton/GAINS/IUI Stockholm (non-Australian) should be kept.

Fixed rules: S8-7 (remove both forms); the stamped criterion mirrors U0.5 byline._sep_is_pure (pure separator = only university-name noise words + punctuation).
"""


# ---- CEPR parse explosion: one raw → several canonical institutions ----------------------------

def test_cepr_parse_explosion_detected():
    """One raw string parsed into >1 institution = parse explosion (the real CEPR fixture has 5 ids, Monash caught up in it)."""
    from m7a_star.pollution_guard import is_parse_explosion
    cepr_ids = ["I4210140326", "I77432436", "I161593684", "I56590836", "I197518295"]
    assert is_parse_explosion(cepr_ids) is True


def test_single_institution_not_explosion():
    """One raw string parsed into only 1 institution = normal, not an explosion."""
    from m7a_star.pollution_guard import is_parse_explosion
    assert is_parse_explosion(["I56590836"]) is False
    assert is_parse_explosion(["I56590836", "I56590836"]) is False  # a repeated identical id does not count as several institutions


# ---- Archive stamping: university first + pure separator directly joined to the department name -----------------------------------

def test_stamped_monash_department_detected():
    """Real Zenou stamping fixture: university first + pure separator (' - ') directly joined to the department name → stamped."""
    from m7a_star.pollution_guard import is_stamped_affil
    assert is_stamped_affil("Monash University - Department of Economics") is True


def test_printed_non_au_not_stamped():
    """A true affiliation (non-Australian, no stamping form) is not stamped and should be kept."""
    from m7a_star.pollution_guard import is_stamped_affil
    assert is_stamped_affil("University of Southampton") is False
    assert is_stamped_affil("IUI Stockholm") is False
    assert is_stamped_affil("GAINS-Université du Maine") is False


def test_printed_with_real_hierarchy_not_stamped():
    """University first but with a real level in between (organisation words such as Business School) = a genuine printed affiliation, not a stamp."""
    from m7a_star.pollution_guard import is_stamped_affil
    assert is_stamped_affil(
        "UNSW Australia Business School, School of Economics, High Street"
    ) is False


def test_dept_first_not_stamped():
    """Department first (dept-first) = genuinely printed, not a stamp (the stamping form is university first)."""
    from m7a_star.pollution_guard import is_stamped_affil
    assert is_stamped_affil("Department of Economics, Monash University") is False


# ---- Adversarial review C-1: the noise-word set faithfully mirrors byline (no private additions such as clayton/victoria) --------

def test_real_campus_layer_kept_matches_byline():
    """A real campus level (Clayton) = a real level → kept as printed (faithfully mirrors byline's 10-word noise set,
    so genuine Australian affiliations are not wrongly killed)."""
    from m7a_star.pollution_guard import is_stamped_affil
    assert is_stamped_affil("Monash University Clayton, Department of Economics") is False
    assert is_stamped_affil("Monash University, Victoria, Department of Economics") is False


# ---- Adversarial review C-4: parse explosion ignores None (None is not an institution) ------------------------------

def test_explosion_ignores_none():
    """None (unparsed) is not an institution → one real institution + None ≠ explosion."""
    from m7a_star.pollution_guard import is_parse_explosion
    assert is_parse_explosion(["I56590836", None]) is False


# ---- Assembly: clean_au_attributions wires up the two detectors to remove fake Australian rows (S8-7) ----------------

def _row(raw, ids, au):
    return {"raw_affil": raw, "canonical_ids": list(ids), "attributes_to_au": au}


def test_zenou_stamped_and_cepr_dropped_printed_kept():
    """Real Zenou fixture: stamped Monash + CEPR-explosion Monash → removed; true affiliation Southampton (non-Australian) → kept."""
    from m7a_star.pollution_guard import clean_au_attributions
    rows = [
        _row("Monash University - Department of Economics", ["I56590836"], True),
        _row("Centre for Economic Policy Research (CEPR), London",
             ["I4210140326", "I77432436", "I161593684", "I56590836", "I197518295"], True),
        _row("University of Southampton", ["I000SOTON"], False),
    ]
    res = clean_au_attributions(rows)
    assert res["n_dropped"] == 2
    assert {r["raw_affil"] for r in res["kept"]} == {"University of Southampton"}


def test_real_au_affil_kept():
    """True Australian affiliation (single institution, no stamping form, with a Clayton campus level) → kept, not wrongly removed."""
    from m7a_star.pollution_guard import clean_au_attributions
    rows = [_row("Monash University Clayton, Department of Economics", ["I56590836"], True)]
    res = clean_au_attributions(rows)
    assert res["n_dropped"] == 0 and len(res["kept"]) == 1


def test_non_au_row_never_dropped_even_if_exploded():
    """Rows attributed to non-Australian places are unaffected by the pollution defence (the defence only handles 'fake Australian years')."""
    from m7a_star.pollution_guard import clean_au_attributions
    rows = [_row("CEPR, London", ["I1", "I2", "I3"], False)]
    res = clean_au_attributions(rows)
    assert res["n_dropped"] == 0 and len(res["kept"]) == 1
