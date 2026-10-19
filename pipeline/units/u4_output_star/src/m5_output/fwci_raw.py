"""M5-T2: per-paper field-normalised citation ratio (fwci) + R1 three-step order + R2 missing discipline + S8-4 fallback.

In plain words: each paper's quality score = its own citations / the average citations of its pool (=1.0 is the field average).
If it cannot be computed, record honestly "cannot compute + reason", never fill 0 (0 means "scored and last", which differs from "no score").

Rules (fixed; this module only consumes them):
  - R1: (1) included_types whitelist (2) paratext_symmetric_drop=true. The original step (3), "winsorize_pct=99
    upper-tail cap", is dropped (records are kept as is, based on a fact check that none of the 8 benchmark papers
    trims): production stores raw fwci values and skew is handled by the regression layer.
  - R2: missing_fill=NA: missing cell / missing subfield with no fallback -> fwci=None + reason column
  - S8-4: missing subfield -> field-level denominator fallback + fwci_inferred_fallback=True mark
    (the three safeguards, [inferred] share / re-run without them / control left blank, live in the T3 report layer)
Note, import guard (isc#2/B16): this node does not read is_star_coauthored and does not import aggregate_output.
"""
from __future__ import annotations

from common._redlines import require


def compute_fwci(work: dict, expected_by_cell: dict, *,
                 field_expected: dict | None = None,
                 field_of_work=None) -> dict:
    """One work -> {"fwci": float|None, "fwci_missing_reason": str|None,
    "fwci_inferred_fallback": bool}. Denominator key = (subfield_id, year, work_type)."""
    included = set(require("fwci", "included_types"))
    out = {"fwci": None, "fwci_missing_reason": None, "fwci_inferred_fallback": False}

    if work["work_type"] not in included:      # R1-①
        out["fwci_missing_reason"] = "excluded_type"
        return out
    if work.get("is_paratext"):                # R1 step 2 (symmetric: the denominator side is guaranteed by the same baseline list)
        out["fwci_missing_reason"] = "paratext"
        return out

    year = work["publication_year"]
    sub = work.get("subfield_id")
    if sub is None:
        # S8-4: field-level fallback (fall back one level to the field denominator, mark [inferred]; nothing left to fall back to -> NA)
        if field_expected and field_of_work:
            fkey = (field_of_work(work), year, work["work_type"])
            if fkey in field_expected:
                if field_expected[fkey] == 0:      # denominator 0 = undefined -> NA (R2, same as below)
                    out["fwci_missing_reason"] = "zero_expected_cell"
                    return out
                out["fwci"] = work["cited_by_count"] / field_expected[fkey]
                out["fwci_inferred_fallback"] = True
                return out
        out["fwci_missing_reason"] = "missing_subfield_no_fallback"
        return out

    key = (sub, year, work["work_type"])
    if key not in expected_by_cell:
        out["fwci_missing_reason"] = "missing_cell"  # R2: never 0
        return out
    if expected_by_cell[key] == 0:
        # Found on real data: 8,793 article/review cells in pop have zero citations in the whole pool
        # (single-paper small cells from the 1600s-1700s) -> expected=0, the ratio is undefined = cannot compute.
        # R2 "missing_fill=NA + reason column, never 0" covers this verbatim -> NA (an engineering fix-up branch, not a change of definition).
        out["fwci_missing_reason"] = "zero_expected_cell"
        return out
    out["fwci"] = work["cited_by_count"] / expected_by_cell[key]
    return out


def winsorize_fwci(values: list[float]) -> list[float]:
    """Upper-tail p99 cap (linear-interpolated quantile; compresses only the upper tail, leaves the lower tail alone; identity on the empty set).

    Not called in production (records are kept as is: each paper's raw fwci is stored,
    skew is handled by the regression layer); kept only for future analysis-layer reference (historical, tested in test_m5_fwci_raw)."""
    if not values:
        return []
    pct = require("fwci", "winsorize_pct") / 100.0
    s = sorted(values)
    # Linear-interpolated p99 (same method as numpy percentile 'linear'; numpy is not imported, to stay dependency-free)
    idx = pct * (len(s) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    cap = s[lo] + (s[hi] - s[lo]) * (idx - lo)
    return [min(v, cap) for v in values]
