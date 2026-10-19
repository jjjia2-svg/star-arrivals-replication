"""pollution_guard: drop the two forms of "fake Australian year".

In plain words: two kinds of dirty data can invent a "fake Australian year" for a star.
Both are removed from the input of the "never in Australia" judgement and of arrival
assembly, which protects Yves Zenou from being wrongly killed or wrongly dated by a fake
Monash year:
  ① CEPR parse explosion: one raw string is parsed into several institutions (Australian
     ones included by accident) → the Australian attribution of that raw string is not trustworthy.
  ② Archive stamping: the author's current affiliation is stamped back onto old papers;
     the form is university first + a pure separator directly linked to the department name.

The stamped criterion mirrors _sep_is_pure of U0.5 roster/byline.py (a pure separator
segment = only university-name noise words + punctuation → stamped; if another
organisation word such as Business/School/... appears → printed). ★ The authority for
the morphology rules is byline.py. The noise-word set and the pure-separator criterion
(_sep_is_pure) faithfully mirror byline's 10-word set; the locating logic (find the first
university/department) is a simplification of byline's span window: correct for the
Yves Zenou fixture and simple strings, while multi-institution joint-appointment strings
(with a real hierarchy at the tail) are a known limitation, left to be aligned with the
byline span logic at the assembly stage (once the real row structure is known).
Pure functions, no IO.
"""
from __future__ import annotations

import re
from typing import Iterable

# Faithful mirror of U0.5 roster/byline.py _SEP_NOISE_WORDS (exactly these 10 words, none
# added): if a separator segment contains only these words (+ punctuation) → pure
# separator → stamped. If other words appear (clayton/victoria campus or state names,
# business/school/... organisation words) → a real hierarchy exists → printed, kept
# (adding clayton/victoria/vic/and would wrongly kill real Australian affiliations, so
# they were removed).
_SEP_NOISE_WORDS = frozenset({
    "university", "of", "the", "new", "south", "wales", "australia", "sydney",
    "monash", "unsw",
})


def is_parse_explosion(canonical_ids: Iterable[str]) -> bool:
    """Set of canonical institution ids parsed from one raw_affil → is it a "parse explosion" (> 1 distinct institution)?

    Real CEPR fixture: one "CEPR, London" string was parsed into 5 inst ids (including Monash by accident) → True.
    The same id repeated is not several institutions (counted by distinct). None (unparsed) is not an institution and is ignored. A single institution → False.
    """
    return len({i for i in canonical_ids if i is not None}) > 1


def _sep_is_pure(sep: str) -> bool:
    """Is the separator segment "pure" (only university-name noise words + punctuation)? Mirrors byline._sep_is_pure."""
    letters = re.findall(r"[A-Za-z]+", sep)
    return all(w.lower() in _SEP_NOISE_WORDS for w in letters)


def is_stamped_affil(raw_affil: str) -> bool:
    """Archive-stamping criterion: university first + a pure separator directly linked to the department name (mirrors byline; pinned by the Yves Zenou fixture).

    stamped = "university" comes before "department" in the string, and the separator segment between the two is pure (only noise words + punctuation).
    - "Monash University - Department of Economics" → True (sep=' - ' is pure).
    - No "department" / department first / a real organisation level (Business School etc.) in between → False (printed, genuine).
    """
    low = raw_affil.lower()
    dept_start = low.find("department")
    if dept_start < 0:
        return False                      # No department-name phrase → not the stamped form (a bare university name / a genuine affiliation)
    uni = low.find("university")
    if uni < 0 or uni >= dept_start:
        return False                      # Not "university first": no university, or department first
    uni_end = uni + len("university")
    sep = raw_affil[uni_end:dept_start]   # The separator segment between the university token and the department name
    return _sep_is_pure(sep)


def clean_au_attributions(rows: Iterable[dict]) -> dict:
    """Given one person's affiliation evidence rows, drop the two forms of "fake Australian year": attributed to Australia and (parse explosion or stamped).

    Each row {raw_affil: str, canonical_ids: list, attributes_to_au: bool}.
    - attributes_to_au: whether the row attributes this person to an Australian (economics department) institution.
    - The guard only handles "fake Australian years" → rows not attributed to Australia are left untouched (kept even if their parse exploded).
    Returns {"kept": [rows], "dropped": [rows], "n_dropped": int}; kept feeds the "never in Australia" judgement and arrival assembly.
    """
    kept: list[dict] = []
    dropped: list[dict] = []
    for r in rows:
        polluted = r["attributes_to_au"] and (
            is_parse_explosion(r["canonical_ids"]) or is_stamped_affil(r["raw_affil"])
        )
        (dropped if polluted else kept).append(r)
    return {"kept": kept, "dropped": dropped, "n_dropped": len(dropped)}
