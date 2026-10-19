"""Evidence assembly: roster (table B) / wayback supply → the six-source input of truth_dates.

In plain words: select_truth_date takes a {source: year} dict; this layer assembles each
star's evidence into that input:
  - table B roster human_verified year_start → official_roster tier (exactly:
    "official_roster = table B human_verified year_start"; a roster year that is not
    human-verified never passes as literature-grade);
  - wayback on-roster snapshots (the snapshot_year in which the person appears on the
    department page list) → wayback tier (the earliest on-roster year is an upper-bound
    anchor for the arrival);
  - ORCID employment / ARC = later increments (no real supply yet; an explicit None =
    not fetched; external, isolated, used only as an anchor and never fed back into the rules).
The six source names follow RED.arrival.source_priority verbatim; modal_inst_shift /
per_work_first_seen are inferred-tier fallbacks (assemble_event falls to them when no
ground-truth tier hits). They are not external evidence and this layer does not produce them.
The personal-page arrival_hint_year (person_page_parse) is a "lead column"; its module
docstring says the authoritative arrival year belongs to the arrival rule plus human
review and the table never overrides it, so this layer does not consume it.

Pure functions, no IO.
"""
from __future__ import annotations

from typing import Iterable


def roster_arrival_evidence(roster_rows: Iterable[dict]) -> int | None:
    """Table B roster rows (one star) → the official_roster-tier evidence year; no human-verified year → None (no strong tier is produced).

    Only human_verified rows count (official_roster = table B human_verified year_start;
    Yves Zenou's low-confidence, unverified, polluted 1995 backfill is rejected
    here). With several human-verified rows the tie-break reuses run_u4.pick_arrival_year
    (one implementation, to prevent the rule drifting; the frozen star_set.arrival uses it
    too): restricted to the human-verified subset = high confidence first, then the earliest
    non-empty year.
    """
    # Lazy import: run_u4 does not import m7a_star.* at top level (all inside functions), so there is no cycle; keeping it inside the function is a second safeguard.
    from run_u4 import pick_arrival_year   # Reuse, do not rewrite

    verified = [r for r in roster_rows if r.get("human_verified")]
    return pick_arrival_year(verified) if verified else None


def wayback_arrival_evidence(presence_rows: Iterable[dict]) -> int | None:
    """Wayback on-roster snapshot rows (the person appears in a department staff page list) → wayback-tier evidence year.

    presence_rows: each row has at least snapshot_year (histraw STAFF_LINE shape).
    Takes the earliest on-roster snapshot year = the upper-bound anchor "in the department by this year at the latest"; no on-roster row → None.
    An on-roster row whose snapshot_year is None → the parsed input is broken: fail loudly (never skip silently and fake a clean result).
    """
    years: list[int] = []
    for r in presence_rows:
        y = r.get("snapshot_year")
        if y is None:
            raise ValueError(
                "wayback_arrival_evidence: a listed snapshot row lacks snapshot_year — "
                "the parser output is broken; failing loudly (never silently skipped)"
            )
        years.append(int(y))
    return min(years) if years else None


def assemble_arrival_evidence(
    *,
    roster_rows: Iterable[dict] = (),
    wayback_rows: Iterable[dict] = (),
    orcid_employment_year: int | None = None,
    arc_year: int | None = None,
) -> dict[str, int]:
    """Supply of each tier → the input {source: year} of truth_dates.select_truth_date (only sources that have evidence).

    Key names follow the six sources of RED.arrival.source_priority verbatim, never invented:
      orcid_employment / arc  ← later increments; enter only when a year is passed explicitly (not fetched = None);
      wayback                 ← earliest on-roster snapshot year;
      official_roster         ← table B human_verified year_start.
    modal_inst_shift / per_work_first_seen are inferred tiers and are not assembled here (when
    no ground-truth tier hits, assemble_event falls to modal_inst_shift/modal_shift by itself).
    """
    evidence: dict[str, int] = {}
    if orcid_employment_year is not None:
        evidence["orcid_employment"] = int(orcid_employment_year)
    if arc_year is not None:
        evidence["arc"] = int(arc_year)
    wb = wayback_arrival_evidence(wayback_rows)
    if wb is not None:
        evidence["wayback"] = wb
    ro = roster_arrival_evidence(roster_rows)
    if ro is not None:
        evidence["official_roster"] = ro
    return evidence
