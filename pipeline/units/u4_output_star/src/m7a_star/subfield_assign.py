"""subfield_assign: person × year subfield = the mode of that year's papers, ties take the lexicographically smallest.

In plain words: which subfield does each of a person's papers in a given year belong to? Take
"the one that appears most" as the person's subfield for that year; ties take the smallest id
(deterministic, reproducible).

Rule: person × year subfield = the mode of that year's papers, ties take the lexicographically
smallest (subfield_id = a 4-digit code string, so lexicographically smallest = smallest number).
A diagnostic/engineering rule with no identification threshold. Pure function.

Note: the subfield of the star circles does not go through this function. Literature (a 2020
Journal of Economic Literature survey of economics fields: a field = a set of journals; OpenAlex single-paper labels are only 53-72%
accurate) and real-data checks (economics papers on arXiv get labelled "physics") show that guessing
the candidate field from single-paper labels or journals is not stable. The rule is roster-based
instead (the candidates are all human-verified members of economics departments → all assigned to
economics), implemented directly in run_u4.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable


def assign_subfield(subfield_ids: Iterable[str]) -> str:
    """List of subfields of the year's papers → mode; ties take the lexicographically smallest.

    - Empty input → raise (a person-year without papers must not be assigned a subfield; a gap fails loudly).
    - Deterministic: independent of input order (sort by frequency descending first, ties broken by subfield_id ascending).
    """
    ids = list(subfield_ids)
    if not ids:
        raise ValueError(
            "assign_subfield: no paper subfields (empty input) — a person-year without papers must not be assigned a subfield"
        )
    counts = Counter(ids)
    # Higher frequency first (-count), ties take the lexicographically smallest (id ascending).
    return min(counts, key=lambda s: (-counts[s], s))
