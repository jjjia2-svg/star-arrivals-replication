# -*- coding: utf-8 -*-
"""caliber_2026-08-28/caliber.py — the two author-signed caliber predicates (D-A, D-B), as data-free
pure functions over columns the frozen tables already carry. Repo-authored; nothing here edits or
shadows a ported file.

Authority: the author's 2026-08-28 decision record (agree to D-A; apply the economics window
1999-2024 everywhere; admit and confirm all listed candidates). Design and measurement: internal review
notes of 2026-08-27 (caliber change impact §5; window widening completeness), not published.

* **D-A** — the seniority gate `aage >= 2` applies EVERYWHERE. It was already present in
  `pipeline/stars/multidisc_2026-07-24/code/star_screening/screening_lib.py` (MIN_ACADEMIC_AGE) and
  `multidisc_gold_2026-08-10/code/60_poach_gate_false_negatives.py:92`, and MISSING from
  `72_restake_fnfix_stars.py:91` (finding F1, `pipeline/stars/README.md`). The ported line is not
  edited — the gate is applied here, on top of the machine's `pass_p10`.
* **D-B** — the event window is uniform across all disciplines and paths: economics' expression
  `1999 <= arrival_true <= 2024`, computed AND consumed everywhere (impact report §1a "Reading 2").
  No hard-coded True rows, no roster-year variant.

The OLD (signed_2026-08-15) caliber's four window paths are kept importable below, verbatim in
semantics, so the two event sets stay derivable side by side and the asymmetry stays checkable.
"""
from __future__ import annotations

import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[3]
_SCREENING = _REPO / "pipeline" / "stars" / "multidisc_2026-07-24" / "code" / "star_screening"
if str(_SCREENING) not in sys.path:
    sys.path.insert(0, str(_SCREENING))
import screening_lib as _L  # noqa: E402  (pure-function module, no IO — see run_stars.NOT_RUNNABLE)

#: D-A threshold — imported from the signed constant, never retyped here.
MIN_ACADEMIC_AGE: int = _L.MIN_ACADEMIC_AGE          # == 2 (redlines_v4_signed_2026-07-05)
#: D-B bounds — economics' expression, now uniform across fields: 1999-2024, as in economics.
WINDOW_LO: int = 1999
WINDOW_HI: int = 2024


def gate_age(aage) -> bool:
    """D-A: the seniority gate, applied to every discipline and every path.

    `aage` is the machine-computed academic age at Y = arrival_true - 1 (column 16 of the restake
    table, or the equivalent column of a suspects row). None (not_in_pool) fails: a person whose
    age the pool cannot compute cannot pass a gate defined on it.
    """
    if aage is None or (isinstance(aage, str) and not aage.strip()):
        return False
    return int(aage) >= MIN_ACADEMIC_AGE


def in_window(arrival_true) -> bool:
    """D-B: the uniform event window `1999 <= arrival_true <= 2024`, on the human-verified TRUE
    arrival year — the economics expression (recovered `00_build_candidates_restake_econ.py`),
    applied to every discipline. Computed and consumed; never a literal."""
    return WINDOW_LO <= int(arrival_true) <= WINDOW_HI


def restake_pass(after_pass) -> bool:
    """The machine's own verdict column (`after_pass` of the 72 restake), normalised.

    Deliberately WITHOUT the age gate — that is finding F1, kept visible: the machine flag is what
    the ported `72` wrote, and D-A is `gate_age`, applied separately so the correction is a named
    predicate rather than a silent rewrite of the machine's output."""
    return after_pass is True or str(after_pass).strip() == "True"


def event_verdict(*, after_pass, aage, arrival_true) -> bool:
    """The corrected-caliber event test for a restaked candidate: machine pass AND D-A AND D-B."""
    return restake_pass(after_pass) and gate_age(aage) and in_window(arrival_true)


# --- the OLD caliber (signed_2026-08-15), importable for the side-by-side -------------------------
# The four window paths exactly as the recovered builders/selectors had them
# (`pipeline/stars/README.md` §(a) "in_window is TWO rules, not one").

def old_in_window_chemmath(arrival_roster) -> bool:
    """Chemistry/math-stats path: `2005 <= int(c['arrival_roster']) <= 2023` on the ROSTER year
    (`00_build_candidates_restake_{chem,math}.py`)."""
    return 2005 <= int(arrival_roster) <= 2023


def old_in_window_econ(arrival_true) -> bool:
    """Economics path: `1999 <= int(r['arrival_true']) <= 2024` — computed by
    `00_build_candidates_restake_econ.py` and then never consumed by the econ selector
    (impact report F-3)."""
    return 1999 <= int(arrival_true) <= 2024


def old_in_window_econ_u4flagged9(_arrival_true=None) -> bool:
    """The literal: `"in_window": True`, no test at all
    (`00_build_candidates_restake_econ_u4flagged9.py`). Kept so the old caliber stays honest."""
    return True


def old_event_verdict_fnfix(*, after_pass, field, in_window_flag) -> bool:
    """The OLD selectors' event test, as the recovered code had it: econ filters on `after_pass`
    alone (`00_select_new_events_econ.py`); chem/math additionally require the frozen `in_window`
    flag (`00_select_new_events_chemmath.py`). No age gate anywhere (F1)."""
    if not restake_pass(after_pass):
        return False
    if field == "econ":
        return True
    return in_window_flag is True or str(in_window_flag).strip() == "True"
