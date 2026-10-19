"""identity/first_pub.py — shared pure function robust_first_pub for the robust debut year.

Hard rules (identity layer): no IO / no network / no state / no operational control flow.

Why it lives here: this function originated on the U4 candidate side
(m6_generation/academic_age.py), while the panel / reference pool / U6 used a bare min(first_pub)
-> a systematic asymmetry where academic age is "clean at one end and dirty at the other" (evidence: four cases had academic age inflated by 54 / 49 / 40 / 57 years).
Pulled up into U0 identity = a single source, so U3/U5/U6/measurement scripts can share the same semantics.
Switching production (panel / pool / U6 using it) changes the identification caliber; this module only provides the function itself.
The existing U4 copy is left as is (its semantics are identical to this function); consolidating it comes later.

In plain words: robust debut year = the true first publication year after removing a "lone leading old paper" (separated from the later
real career by > max_leading_gap years = contamination by a same-name person). A continuous career (no large gap) -> the earliest year is untouched.
"""
from __future__ import annotations

from common._redlines import RedlineUnsigned


def robust_first_pub(years, *, max_leading_gap) -> int:
    """The true debut year after removing a "lone leading old paper" (separated from the later real career by > max_leading_gap years = contamination by a same-name person).

    Definition (identical to U4 m6_generation.academic_age.robust_first_pub;
    original anchors: two cases of old papers by same-name others in 1963 / 1965): the true debut year = the earliest year whose gap to the next
    publication year is <= max_leading_gap (the last paper with no successor is kept only when it is the sole candidate). A continuous career (no large gap)
    -> the earliest year is untouched (a true early paper is not removed by mistake, such as Yves Zenou 1991).
    - years: all publication years of the person (may repeat / be unordered). Empty -> raise (the true debut year cannot be computed, bad data fails loudly).
    - max_leading_gap = None (unset red line) -> raise RedlineUnsigned, never defaulting silently. A pure function, no IO.
    - A gap exactly equal to max_leading_gap -> kept (<= semantics; A5071656006 in 1985 sits exactly on the line and cannot be removed,
      it must go through U4 work_pollution_discards; the division of labour with this function is clear).
    """
    if max_leading_gap is None:
        raise RedlineUnsigned(
            "robust_first_pub: academic_age.robust_first_pub_max_gap = None (not set) — never silently default"
        )
    ys = sorted(set(years))
    if not ys:
        raise ValueError("robust_first_pub: no publication years (empty) — cannot compute the true first-publication year")
    for i, y in enumerate(ys):
        gap_next = (ys[i + 1] - y) if i + 1 < len(ys) else None
        if gap_next is None or gap_next <= max_leading_gap:
            return y
    return ys[-1]              # Theoretically unreachable (the last element has gap_next=None and must already have returned)
