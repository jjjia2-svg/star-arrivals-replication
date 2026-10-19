"""U0.5 (4) Yves Zenou golden-standard slice anchor + arrival note (the roster-layer part).

The U0.5 roster layer is only responsible for three things of the golden standard: "can be found + author_id
aligned + lands in the right department / Table B"; the arrival year (arrival=2016) **is not in this table**, it comes
from U1 works + the modal-institution method + manual verification (a profile year field is never used as the arrival).
This module provides:
  - the Yves Zenou ground-truth anchor (A5017376589 / name);
  - zenou_slice_note(): a machine-readable note that fixes "arrival 2016 is a hint, to be verified by U1; never use
    Pure 1995 or affiliations.years as the arrival", written into the output description as a reproduction credential.

★ Institutional affiliation (Monash, not Sydney) and the star decision (top 1%) are not produced by U0.5 - the U0
  identity anchors are reused (MONASH_CANONICAL_ID / classify_golden / ZENOU_STRUCTURAL); U0.5 does not build a second
  copy.

Hard rule: never trust the Pure single year field / affiliations[].years as the arrival; author_id is bare.
"""
from __future__ import annotations

# Yves Zenou ground-truth anchor (measured live; same source as U0 golden ZENOU_STRUCTURAL).
ZENOU_AUTHOR_ID = "A5017376589"
ZENOU_NAME = "Yves Zenou"

# Start of the publication range given by the Pure archive (NOT the arrival!).
ZENOU_PURE_YEAR_START = 1995
# True arrival year (from Stockholm, joined 2015-09 / effective 2016-01) - only a hint, to be verified by U1 works + the modal method.
ZENOU_ARRIVAL_HINT = 2016


def zenou_slice_note() -> dict:
    """Machine-readable note of the U0.5 roster layer on Yves Zenou's arrival (goes into the output description as a
    reproduction credential).

    Pins down the rule: this table gives no authoritative arrival; arrival 2016 is a hint, decided by U1 works + the
    modal-institution method + manual review; never use Pure's 1995 (the start of the publication range) or
    affiliations[].years as the arrival.
    """
    return {
        "author_id": ZENOU_AUTHOR_ID,
        "display_name": ZENOU_NAME,
        "dept_key": "monash_econ",
        "pure_year_start": ZENOU_PURE_YEAR_START,        # 1995 = start of the Pure publication range
        "arrival_year_authoritative": False,             # this table gives no authoritative arrival
        "arrival_year_hint": ZENOU_ARRIVAL_HINT,         # 2016, only a hint
        "arrival_pending_unit": "U1",                    # to be verified by U1 works + the modal-institution method
        "never_use_pure_year_as_arrival": True,          # 1995 ≠ arrival
        "never_use_affiliations_years": True,            # affiliations[].years is never used as the arrival
        "note": (
            "到任 2016 待 U1 works + 众数机构法验 (红线 #3); "
            "Pure year_start=1995 是发表区间起点、非到任; 绝不用 affiliations[].years 判到任。"
        ),
    }
