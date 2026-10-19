"""m5b_aggregate/quality.py — quality fill.

Definition (each point is anchored to an existing rule):
  - quality = **fractional-credit-weighted mean of per-paper FWCI** (divide-then-average, #7):
      quality(person, year) = sum(frac_credit*fwci) / sum(frac_credit),
      summation rows = the papers of that person-year with non-NA fwci that are not star-co-authored (the numerator rows and the divisor rows are the same, row by row);
  - the per-paper fwci (= actual / expected, expected = **mean** for the same year, same type, same subfield) is computed by U4
    (paper_contrib.fwci); this step **only takes the weighted average** — never recomputes expected and never touches the denominator
    (#41d; leave-star on the denominator side is forbidden, RED fwci.denominator_leave_star=false);
  - **star co-authored works are dropped on the numerator side only** (RED output_quality.quality_numerator_drop_star_coauthored
    =true, #3+4) — the flag comes from the exclusion set (#2/C1) and varies with p_level;
  - note: there is **no winsorisation at all** (not trimmed, recorded as is) — this layer must not introduce any cap step;
  - NA is not treated as 0; all NA / zero person-years left after dropping stars = None (NA, never filled with 0);
  - FWCI NA rate > mnar_missing_threshold -> mnar_robustness_required=true + WARN
    (caveat#1, #41c) — the diagnostic goes to a sidecar, not into the main table.
"""
from __future__ import annotations

import math
import warnings

from common._redlines import require

# Definition self-check (at import): if a pinned value drifts, blow up loudly for a human to re-judge; this layer does not choose a fallback itself.
_Q_NUM_DROP_STAR = require("output_quality", "quality_numerator_drop_star_coauthored")
_DENOM_LEAVE_STAR = require("fwci", "denominator_leave_star")
if _Q_NUM_DROP_STAR is not True:
    raise ValueError(
        "RED['output_quality'].quality_numerator_drop_star_coauthored must be true "
        f"(rule #3+4: the numerator side drops star-coauthored papers); got {_Q_NUM_DROP_STAR!r} — the rule has changed and a person must re-decide."
    )
if _DENOM_LEAVE_STAR is not False:
    raise ValueError(
        "RED['fwci'].denominator_leave_star must be false (rule #3+4: the denominator side does not drop stars); "
        f"got {_DENOM_LEAVE_STAR!r} — the rule has changed and a person must re-decide."
    )


def _fwci_missing(fwci) -> bool:
    """Whether fwci is NA (None or NaN) — the same criterion as u0 output_rule._fwci_missing."""
    return fwci is None or (isinstance(fwci, float) and math.isnan(fwci))


def fill_quality(rows, contribs) -> list[dict]:
    """Fill the quality column of the aggregated row set from None with the defined value; the other 11 keys are left untouched value by value.

    Args:
        rows:     12-key rows produced by aggregate_via_u0 (quality=None placeholder).
        contribs: per-paper contributions produced by to_contribs (with the is_star_coauthored flag + frac + fwci).
    Returns: a new list of rows (the input row objects are not modified).
    """
    num: dict[tuple, float] = {}
    den: dict[tuple, float] = {}
    terms: dict[tuple, list] = {}
    for c in contribs:
        if _fwci_missing(c["fwci"]):
            continue                       # NA enters neither the numerator nor the weights (not treated as 0)
        if c["is_star_coauthored"]:
            continue                       # #3+4: drop star co-authored works on the numerator side
        key = (c["incumbent_person_id"], c["year"])
        terms.setdefault(key, []).append(
            (float(c["frac_credit"]) * float(c["fwci"]), float(c["frac_credit"]))
        )
    for key, pairs in terms.items():
        num[key] = math.fsum(p[0] for p in pairs)   # fsum, deterministic
        den[key] = math.fsum(p[1] for p in pairs)

    out: list[dict] = []
    for r in rows:
        key = (r["incumbent_person_id"], r["year"])
        new_row = dict(r)
        d = den.get(key, 0.0)
        # 0 qualifying papers (all NA / all star co-authored) -> None (NA, never filled with 0); no winsorisation, no cap.
        new_row["quality"] = (num[key] / d) if d > 0.0 else None
        out.append(new_row)
    return out


def fwci_na_stats(paper_contrib_rows, *, mnar_missing_threshold: float) -> dict:
    """FWCI NA-rate diagnostic (caveat#1, #41c): above the threshold -> flag + WARN (not a silent log line).

    Returns {n_rows, n_fwci_na, fwci_na_rate, mnar_robustness_required,
          mnar_missing_threshold} — the diagnostic goes to a sidecar, not into the OUTPUT main table (#47).
    """
    rows = list(paper_contrib_rows)
    n = len(rows)
    n_na = sum(1 for r in rows if _fwci_missing(r["fwci"]))
    rate = (n_na / n) if n else 0.0
    required = rate > mnar_missing_threshold
    if required:
        warnings.warn(
            f"[m5b] FWCI NA rate {rate:.1%} > {mnar_missing_threshold:.0%} — "
            "MNAR (missing not at random) risk; downstream must run robustness checks "
            "(mnar_robustness_required=true, caveat#1)",
            UserWarning,
            stacklevel=2,
        )
    return {
        "n_rows": n,
        "n_fwci_na": n_na,
        "fwci_na_rate": rate,
        "mnar_robustness_required": required,
        "mnar_missing_threshold": mnar_missing_threshold,
    }
