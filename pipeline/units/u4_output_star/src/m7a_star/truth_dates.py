"""truth_dates: six-source priority selection of arrival-date evidence + evidence strength.

In plain words: the year a star "arrives in Australia" may have evidence from several sources.
Take the most reliable one by the configured priority; literature-grade sources = strong,
inferred-grade = modal_shift; with no evidence return empty (the caller then produces no strong
tier and uses the fallback).

Red line: RED.arrival.source_priority is the six-source order (orcid_employment > arc >
wayback > official_roster > modal_inst_shift > per_work_first_seen); strength has two values,
strong/modal_shift = the engineering mapping (the first 4 literature-grade →
strong, the last 2 inferred-grade → modal_shift; both value sets are in the schema/yaml).
affiliations.years is never trusted (arrival_rule has a built-in self-check). Pure function.
"""
from __future__ import annotations

from typing import Mapping

# Two-value domain of evidence strength (the engineering mapping for the EVENTS table, not a new identification rule):
#   literature-grade source → strong; inferred-grade source → modal_shift.
_STRONG_SOURCES = frozenset({"orcid_employment", "arc", "wayback", "official_roster"})
_MODAL_SHIFT_SOURCES = frozenset({"modal_inst_shift", "per_work_first_seen"})


def _strength(source: str) -> str:
    if source in _STRONG_SOURCES:
        return "strong"
    if source in _MODAL_SHIFT_SOURCES:
        return "modal_shift"
    raise ValueError(
        f"truth_dates: unknown arrival-evidence source {source!r} — not in the fixed two-valued strength domain"
    )


def select_truth_date(evidence: Mapping[str, int], priority: list[str]) -> dict | None:
    """Pick one from the multi-source arrival-year evidence by the configured priority.

    Args:
        evidence: {source_name: arrival_year}, only sources that have evidence.
        priority: the six-source order of source_priority (passed in from RED.arrival.source_priority).
    Returns: {"arrival_year", "arrival_source", "arrival_evidence_strength"} or None (no evidence).

    - Take the first source with evidence in priority order (higher priority first).
    - evidence contains an unknown source outside priority → raise (a gap fails loudly, never silently ignored).
    - No evidence at all → None.
    """
    for src in evidence:
        if src not in priority:
            raise ValueError(
                f"truth_dates: evidence has unknown source {src!r} — not in the fixed source_priority {priority}"
            )
    for src in priority:              # Higher priority first
        if src in evidence:
            return {
                "arrival_year": evidence[src],
                "arrival_source": src,
                "arrival_evidence_strength": _strength(src),
            }
    return None
