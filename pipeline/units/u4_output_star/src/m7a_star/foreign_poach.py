"""foreign_poach: pure foreign-poach filter (downstream use of the pollution guard).

Rule: a star must have "truly moved in from outside Australia and never held a post in
Australia before". **Pollution must be cleaned first** before judging whether the person
was in Australia before arrival, otherwise fake Australian records wrongly kill a true
outside hire (Yves Zenou: all of this person's pre-arrival Monash records are CEPR mis-attributions
or current-affiliation stamp backfills, i.e. all fake). Both kinds of pollution are
cleaned: is_parse_explosion (one raw string → several institutions) and is_stamped_affil
(university first + a pure separator = backfilled). Pure function.
"""
from __future__ import annotations

from collections import defaultdict

from m7a_star.pollution_guard import is_parse_explosion, is_stamped_affil


def is_foreign_poach(pre_affil_rows) -> bool:
    """Pre-arrival affiliation records → whether this is a pure foreign poach (moved in from outside Australia and never truly in Australia before).

    pre_affil_rows: [{raw_affil, canonical_affil_id, country_code}] (all affiliation rows before the arrival year).
    - Clean AU = country=AU and that raw_affil is **neither exploded nor stamped** (evidence of truly being in Australia).
    - foreign_poach = has overseas evidence and no clean AU. Empty records / no overseas → False (no evidence of a "move in", no forced call).
    """
    by_raw: dict = defaultdict(lambda: {"canons": set(), "countries": set()})
    for r in pre_affil_rows:
        c = r.get("canonical_affil_id")
        if c and c not in ("__NONE__", "AFFIL_NONE"):
            by_raw[r["raw_affil"]]["canons"].add(c)
            by_raw[r["raw_affil"]]["countries"].add(r.get("country_code"))

    clean_au = overseas = False
    for raw, d in by_raw.items():
        polluted = is_parse_explosion(d["canons"]) or is_stamped_affil(raw)
        for cc in d["countries"]:
            if cc == "AU" and not polluted:
                clean_au = True          # Clean evidence of truly being in Australia
            if cc and cc != "AU":
                overseas = True          # Overseas evidence
    return overseas and not clean_au
