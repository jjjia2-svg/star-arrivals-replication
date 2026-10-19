"""identity/star_rule.py — pure function is_star that decides whether a researcher is a star.

Rules (identity layer):
  - No IO, no network, no state, no operational control flow.
  - Thresholds are read only from common._redlines.RED (percentile_primary / cell_min_n.floor);
    the module hard-codes no identification threshold.
  - A threshold that is not set (None in RED) -> require() raises RedlineUnsigned; no silent default.

Definition (plain words):
  Star = a researcher whose citation percentile (0..1, larger = higher) within the
  "same subfield x same arrival-year cohort" falls in the top percentile_primary.
  percentile_primary=0.01 -> top 1% (read from RED, not hard-coded). Equivalent: percentile >= 1 - p.
  A cell (one cohort unit) with fewer than cell_min_n.floor members is a thin cell -> return None
  (no forced call), following the interface contract "thin cell -> None".

Input row (per person per cohort):
  {"citation_percentile": float(0..1), "cell_n": int}  # percentile computed upstream + cell sample size

Returns: True / False / None (thin cell).
"""
from __future__ import annotations

from typing import Any

from common._redlines import RedlineUnsigned, require


def is_star(row: dict[str, Any], p: float | None = None) -> bool | None:
    """Decide whether row is a star (top p, default percentile_primary); thin cell -> None.

    p: star percentile cutoff. Default None -> use percentile_primary from RED (main definition, top 1%);
       p=0.05 -> top-5% entry. cutoff = 1 - p.
       The per-p estimation gate max(pct_p, floor) is handled by pctile_engine (M7a-T3), not here
       (this function only applies cutoff=1-p and the floor thin-cell gate).

    Threshold sources (nothing hard-coded):
      - cutoff = 1.0 - p (default p = RED["star"]["percentile_primary"])
      - floor  = RED["star"]["cell_min_n"]["floor"]        (thick/thin cell gate)
    If either is unset (None) -> require() raises RedlineUnsigned.

    Rule: if citation_percentile is missing or None -> raise (never treat it as 0, which would drop
    a true star or misclassify; a gap must fail loudly).
    """
    if row is None:
        raise ValueError("is_star: row must not be None")

    # p defaults to None -> use percentile_primary from RED (main definition); an explicit p is used as given (e.g. the 5% entry).
    # Default used but unset -> require raises RedlineUnsigned (no silent default).
    if p is None:
        p = require("star", "percentile_primary")
    # cell_min_n is a nested dict (require only guards two levels of None); read the floor sub-key and
    # guard None here, matching require's None -> raise behaviour, so a nested sub-key never gets a silent default.
    cell_min_n = require("star", "cell_min_n")
    floor_n = cell_min_n["floor"]  # missing -> KeyError (intended)
    if floor_n is None:
        raise RedlineUnsigned(
            "Red-line key star.cell_min_n.floor is not set (value is null) — the code never silently supplies a default."
        )

    cell_n = row["cell_n"]  # missing -> KeyError (intended: fail loudly)
    if cell_n is None:
        raise ValueError("is_star: cell_n must not be None")

    # thin cell -> no forced star call (interface contract "thin cell -> None")
    if cell_n < floor_n:
        return None

    pct = row["citation_percentile"]  # missing -> KeyError (intended)
    if pct is None:
        raise ValueError("is_star: citation_percentile must not be None (a gap fails loudly, it is not treated as 0)")

    cutoff = 1.0 - p
    return pct >= cutoff
