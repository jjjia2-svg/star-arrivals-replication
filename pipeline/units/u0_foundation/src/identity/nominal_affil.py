"""identity/nominal_affil.py — shared pure function for the nominal-affiliation behaviour flag.

Hard rules (identity layer): no IO / no network / no state.

In plain words: roster inclusion used to filter only on the title string, so the A5044618645 type (a person whose real home is at another school and who is listed in this
school's directory under a plain "Professor") slipped through. Behavioural evidence adds a production gate: if "the share of the person's own works that list this
school's institution (folded lineage)" < the threshold -> set nominal_affiliation_flag and **send to the human-review list**.

Threshold = 0.05 (redlines star.nominal_affiliation_min_share);
**the flag does not remove anyone by itself**: each flagged person is reviewed individually and kept or dropped; a
near-threshold case A5019255415 (0.0468, a confirmed poach) is kept and noted in the flag table.

The semantics are identical to u0p5 roster/nominal_affil.flag_member (the diagnostic prototype);
pulled up into U0 identity = a single source, for U4 production use. Folding the u0p5 copy into this one is left for later.
"""
from __future__ import annotations

from typing import Optional

from common._redlines import RedlineUnsigned

REASON_NO_WORKS = "no_works_in_corpus"
REASON_ZERO = "zero_school_works"
REASON_BELOW = "below_threshold"


def flag_member(author_id: str, *, n_works_total: int, n_works_school: int,
                threshold) -> dict:
    """Per-person counts -> flag judgement (a pure function).

    Returns {author_id, n_works_total, n_works_school, school_share,
          nominal_affiliation_flag, reason, threshold}:
      - threshold=None (unset) -> raise RedlineUnsigned (never defaulting silently; the threshold is 0.05);
      - n_works_total == 0 -> share=None, flag=True, reason=no_works_in_corpus
        (cannot be assessed != proven nominal affiliation, classed separately into human review);
      - share == 0        -> flag=True, reason=zero_school_works (A5044618645 type);
      - 0 < share < threshold   -> flag=True, reason=below_threshold (A5008452204 type);
      - share >= threshold       -> flag=False (exactly equal to the threshold is not flagged, < semantics).
    """
    if threshold is None:
        raise RedlineUnsigned(
            "nominal_affil.flag_member: threshold=None — the configured value is in redlines "
            "star.nominal_affiliation_min_share; the caller must pass it explicitly, never a silent default")
    if n_works_school > n_works_total:
        raise ValueError(f"flag_member({author_id}): n_works_school={n_works_school} > "
                         f"n_works_total={n_works_total} — bad count, fail-loud")
    share: Optional[float]
    if n_works_total == 0:
        share, flag, reason = None, True, REASON_NO_WORKS
    else:
        share = n_works_school / n_works_total
        if share == 0.0:
            flag, reason = True, REASON_ZERO
        elif share < threshold:
            flag, reason = True, REASON_BELOW
        else:
            flag, reason = False, None
    return {"author_id": author_id, "n_works_total": n_works_total,
            "n_works_school": n_works_school, "school_share": share,
            "nominal_affiliation_flag": flag, "reason": reason,
            "threshold": threshold}
