"""U0 common/coauthor_split.py: fractional coauthor counting (#10).

In plain words: a paper with N listed authors splits its "contribution" equally by head count; each author gets 1/N
(fractional credit). The denominator is the paper's number of listed authors N (#10); it is never swapped for
N-1, corresponding-author weighting, or an integer 1. Feeds PAPER_CONTRIB.frac_credit.

Build checklist C.10/C.4 + B[18]:
  coauthor_split(...) fractional counting; the denominator = number of listed authors N (#10).
  PAPER_CONTRIB.frac_credit: float32; the shares of all authors on one paper sum to 1.0 (contribution is conserved).

Counting rules:
  - The denominator is strictly the number of distinct listed authors N (#10). The same author_id listed twice
    still counts as one head (N counts distinct ids), so duplicate listings cannot inflate the denominator and
    dilute the shares.
  - This is the engineering definition of the equal split (1/N) of fractional counting, not an identification
    red-line threshold; it reads no redlines.
  - Degenerate case: no listed authors (N=0) -> empty result, never a division by zero.

Pure function: no IO / no network / no state.
"""
from __future__ import annotations

from typing import Iterable


def coauthor_split(author_ids: Iterable[str]) -> dict[str, float]:
    """Split a paper's "contribution" equally (fractionally) among its listed authors (#10).

    Args:
        author_ids: iterable of the work's listed author_ids (duplicates allowed; folded to distinct heads).

    Returns:
        dict author_id -> frac_credit (= 1/N, N = number of distinct listed authors).
        The shares of all authors sum to 1.0 (one paper's contribution is conserved); no listed authors -> {} (no division by zero).

    Denominator = number of listed authors N (#10): a strict count of distinct heads, never N-1,
    corresponding-author weighting, or an integer 1.
    """
    # Fold to distinct heads (keeps first-appearance order, deterministic; duplicate listings do not inflate the denominator N).
    distinct: list[str] = []
    seen: set[str] = set()
    for aid in author_ids:
        if aid not in seen:
            seen.add(aid)
            distinct.append(aid)

    n = len(distinct)        # Denominator = number of distinct listed authors N (#10)
    if n == 0:
        return {}            # Degenerate case: no listed authors -> empty, never a division by zero

    share = 1.0 / n          # 1/N each (fractional equal split)
    return {aid: share for aid in distinct}
