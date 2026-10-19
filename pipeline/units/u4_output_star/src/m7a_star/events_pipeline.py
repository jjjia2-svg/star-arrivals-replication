"""Event orchestration for the stars, plus a hard arrival-year consistency gate.

In plain words: each star's evidence rows go through the full assembly chain:
  pollution_guard.clean_au_attributions (drop fake Australian years)
  → build_per_work_timeline (P-3 contract timeline)
  → detect_arrival_to_dept (asks about the **event department**: the first year the
    person switches to the event department and stays for a 2-year window; it no
    longer catches the first move of a career)
  → detect_departure (the year the old main institution ends; old main = the modal
    institution of the latest recorded year before arrival)
  → select_truth_date (six-source evidence tier → source/strength labels; not used to
    pick the year)
  → assemble_event (builds the 11 EVENTS columns).

Consistency gate: star_set.arrival comes from the pick_arrival_year route (roster
human check first, panel as fallback, fingerprint bound); events.arrival_year comes
from the detect_arrival_to_dept route (modal switch into the event department). For
every star to be shipped (is_star_5pct and is_foreign_poach) the two routes must give
the same year. Any mismatch produces a difference report (who / which year each route
says / the evidence) for a human to decide. This is an identification-layer red line:
the code never picks a route on its own.
Why the sentinel asks about the event department: a person-by-person check of 15
people showed that the old question (the standard detect_arrival, i.e. the first
sustained switch = the first move of a career) was the wrong one. It blocked 10 of 12
stars wrongly (it picked moves to Southampton, IFN, etc. that have nothing to do with
the event department). The authoritative arrival year is
still the roster; this layer is only a cross-checker, and when the two do not line up
it still HALTs and reports.

Assembly-order rule: clean first, then decide (fake Australian years make a true
institution "flash" in the true arrival year and pollute the window, causing a wrong
call; see the arrival_departure docstring). Pure functions, no IO (writing happens in
write_events / run_u4.ship_events).
"""
from __future__ import annotations

from typing import Iterable, Mapping

from common._redlines import require
# The modal-by-year table and the P-3 contract check reuse arrival_rule (single source
# of truth; the modal logic is not rewritten, so that several implementations cannot
# drift apart; departure_rule reuses _validate_input_contract in the same way).
from identity.arrival_rule import _modal_institution_by_year, _validate_input_contract
from identity.departure_rule import detect_departure
from m7a_star.arrival_departure import assemble_event, build_per_work_timeline
from m7a_star.pollution_guard import clean_au_attributions
from m7a_star.truth_dates import select_truth_date


class ArrivalMismatch(RuntimeError):
    """Consistency gate: the arrival year from events (detect_arrival) differs from the frozen star_set (pick_arrival_year).

    HALT. The code never picks a route; the .diff file lists each person's difference
    (who / which year each route says / the evidence) for a human to decide.
    """

    def __init__(self, message: str, diff: list[dict]):
        super().__init__(message)
        self.diff = diff


def detect_arrival_to_dept(per_work_timeline_canonical: list[dict],
                           dept_id: str) -> dict:
    """Sentinel: the cross-checker asks about the **event department**: the first year in
    which the modal institution switches to dept_id and stays the modal institution for
    `sustain_window` consecutive recorded years from that year on.

    Why: a person-by-person check of 15 people showed the old question (detect_arrival
    catching the first move of a career) was the wrong one: it blocked 10 of 12 stars
    wrongly (multi-step career histories were judged to Southampton, IFN, etc., which
    have nothing to do with the event department). Every part of the rule is reused,
    nothing is new: modal-by-year table = arrival_rule._modal_institution_by_year
    (single source of truth), sustain window = RED['arrival'].sustain_window_years
    (value 2), input shape = the P-3 contract (arrival_rule._validate_input_contract).
    Switch semantics: it must be a real switch from elsewhere: an earlier recorded year
    exists and the modal institution of the previous recorded year is not dept_id. A
    career whose first recorded year is already in the event department is not a switch
    (a purely foreign-poached star always has a prior history; if there is none, the
    case goes to the gate for a human). A one-year flash (sustain window not met) is not
    judged; a later window that switches in and stays is still judged (bounce-backs and
    re-entries are settled by the sustain window).

    This is a sentinel, not the authority: the authoritative arrival year is still the
    roster (the pick_arrival_year route); this function's result only feeds the
    consistency gate. When the two do not line up the code still HALTs with a difference
    report and never picks a route itself.
    Returns a 4-key dict (same shape as detect_arrival): {arrival_year,
    arrival_institution, method="modal_institution_to_dept", sustain_window_years}.
    """
    sustain_window = require("arrival", "sustain_window_years")
    _validate_input_contract(per_work_timeline_canonical)
    no_arrival = {"arrival_year": None, "arrival_institution": None,
                  "method": "modal_institution_to_dept",
                  "sustain_window_years": sustain_window}
    modal_by_year = _modal_institution_by_year(per_work_timeline_canonical)
    if not modal_by_year:
        return no_arrival
    years_sorted = sorted(modal_by_year)
    prev_inst: str | None = None
    for idx, year in enumerate(years_sorted):
        inst = modal_by_year[year]
        if inst == dept_id and prev_inst is not None and prev_inst != dept_id:
            window_years = years_sorted[idx: idx + sustain_window]
            if len(window_years) >= sustain_window and all(
                modal_by_year[wy] == dept_id for wy in window_years
            ):
                return {"arrival_year": year, "arrival_institution": dept_id,
                        "method": "modal_institution_to_dept",
                        "sustain_window_years": sustain_window}
        prev_inst = inst
    return no_arrival


def _prior_main_institution(timeline: list[dict], arrival_year: int) -> str | None:
    """Old main institution = the modal institution of the latest recorded year before the arrival year (Yves Zenou: the 2014 mode is IFN).

    The single source of truth for the modal rule is arrival_rule._modal_institution_by_year (not rewritten).
    No recorded year before arrival → None (when detect_arrival finds an arrival, a prior year structurally exists; None is a defensive fallback).
    """
    modal_by_year = _modal_institution_by_year(timeline)
    prior_years = [y for y in modal_by_year if y < arrival_year]
    if not prior_years:
        return None
    return modal_by_year[max(prior_years)]


def derive_star_event(
    *,
    star_person_id: str,
    dept_id: str,
    evidence_rows: Iterable[dict],
    truth_evidence: Mapping[str, int],
    modal_inst_year: bool,
) -> dict:
    """One star: evidence rows → (clean → timeline → arrival/departure → evidence labels) → EVENTS row.

    Args:
        evidence_rows: each row {work_id, publication_year, raw_affil, canonical_ids,
            attributes_to_au} (the pollution_guard input shape; derived from the U3
            affil_timeline).
        truth_evidence: output of evidence_assembly.assemble_arrival_evidence,
            {source: year} (six source names); {} = no evidence → inferred-tier fallback.
        modal_inst_year: corroboration that the arrival year is_modal (U3 affil_timeline,
            consume-only; this layer never recomputes the mode to stand in for it; the
            caller passes the U3 value).
    Returns:
        {"event": EVENTS 11-column dict | None (no arrival found for the event department),
         "n_polluted_dropped": int (count dropped by the pollution guard, written to _reports),
         "prior_main_inst": str | None (old main institution, for audit),
         "arrival": the raw 4-key dict of detect_arrival_to_dept (for audit),
         "arrival_inst_mismatch": bool (defensive note; by construction the arrival
          institution of the to_dept judgement is the event department, and no arrival
          → event=None, which takes the None-disagreement path of the consistency gate),
         "timeline": the cleaned P-3 timeline (used by the human-review release path to
          rebuild the event row at the authoritative year,
          build_event_at_authoritative_year, without cleaning again)}

    The arrival year is judged with detect_arrival_to_dept (asks for the first sustained
    window of switching into the event department), not with the first move of a career
    asked by the standard detect_arrival (which wrongly blocked 10 of 12 stars). The old
    structural guard "arrival institution != event department → event=None" therefore no
    longer arises (by construction the institution is the event department). When no
    sustained window of switching into the event department is found → event=None, and
    the consistency gate reports it for a human to decide. The HALT rule is unchanged,
    and the authority is still the roster arrival year (an identification-layer choice
    that stays with a human).
    """
    cleaned = clean_au_attributions(evidence_rows)
    timeline = build_per_work_timeline(cleaned["kept"])
    # Sentinel: ask about the event department (rationale and rules: see the detect_arrival_to_dept docstring)
    arrival = detect_arrival_to_dept(timeline, dept_id)

    inst_mismatch = (
        arrival["arrival_year"] is not None
        and arrival["arrival_institution"] != dept_id
    )

    prior_inst: str | None = None
    departed_year: int | None = None
    if arrival["arrival_year"] is not None and not inst_mismatch:
        prior_inst = _prior_main_institution(timeline, arrival["arrival_year"])
        if prior_inst is not None:
            departed_year = detect_departure(timeline, prior_inst)

    # Evidence tier → source/strength labels (truth_dates does not take part in choosing the
    # year); the six-source order is read from RED (required: unset None → raise, never a silent default).
    truth_hit = select_truth_date(dict(truth_evidence),
                                  list(require("arrival", "source_priority")))

    event = None
    if not inst_mismatch:
        event = assemble_event(
            star_person_id=star_person_id, arrival=arrival, dept_id=dept_id,
            truth_hit=truth_hit, departed_year=departed_year,
            modal_inst_year=modal_inst_year)
    return {
        "event": event,
        "n_polluted_dropped": cleaned["n_dropped"],
        "prior_main_inst": prior_inst,
        "arrival": arrival,
        "arrival_inst_mismatch": inst_mismatch,
        "timeline": timeline,
    }


def build_event_at_authoritative_year(
    *,
    star_person_id: str,
    dept_id: str,
    timeline: list[dict],
    truth_evidence: Mapping[str, int],
    modal_inst_year: bool,
    arrival_year: int,
) -> dict:
    """Assembly path for the human-review release: human-verified web evidence prevails. Builds
    the EVENTS row with the **authoritative arrival year** (the frozen / roster human-verified
    year), so ship_events can replace the detect-route product when the disagreement is
    explained by human-verified evidence.

    - Evidence label: if a literature-grade truth tier exists (official_roster / orcid_employment /
      wayback / arc), select_truth_date takes it in the six-source order; with no tier →
      **per_work_first_seen / modal_shift** (inferred tier: the authoritative year comes from
      the first appearance in the works panel (panel fallback); never label it
      modal_inst_shift, because the detect modal-switch route is the disagreeing side here,
      and using its label would be false provenance).
    - Departure year: recompute _prior_main_institution + detect_departure at the
      authoritative year (same parts as derive).
    - Assembles only, never judges: the caller (ship_events) must first pass the hv
      criterion and write the disagreement into arrival_mismatch_report (downgraded to a
      diagnostic record); this function does not check the evidence.
    Returns {"event": EVENTS 11-column dict, "prior_main_inst": str | None}.
    """
    truth_hit = select_truth_date(dict(truth_evidence),
                                  list(require("arrival", "source_priority")))
    if truth_hit is None:
        truth_hit = {"arrival_year": None,
                     "arrival_source": "per_work_first_seen",
                     "arrival_evidence_strength": "modal_shift"}
    prior_inst = _prior_main_institution(timeline, arrival_year)
    departed_year = (detect_departure(timeline, prior_inst)
                     if prior_inst is not None else None)
    arrival = {"arrival_year": int(arrival_year), "arrival_institution": dept_id,
               "method": "authoritative_roster_year",
               "sustain_window_years": require("arrival", "sustain_window_years")}
    event = assemble_event(
        star_person_id=star_person_id, arrival=arrival, dept_id=dept_id,
        truth_hit=truth_hit, departed_year=departed_year,
        modal_inst_year=modal_inst_year)
    return {"event": event, "prior_main_inst": prior_inst}


def ship_set_ids(frozen_star_rows: Iterable[dict]) -> set[str]:
    """Frozen star_set rows → ship-set author_ids (is_star_5pct and is_foreign_poach; EVENTS yields
    a single list over the full 5% set; the poach filter is already part of the star definition)."""
    return {s["author_id"] for s in frozen_star_rows
            if s.get("is_star_5pct") and s.get("is_foreign_poach")}


def arrival_consistency_diff(
    events_by_star: Mapping[str, dict | None],
    frozen_star_rows: Iterable[dict],
) -> list[dict]:
    """Pure decision of the hard consistency gate: for each shipped star, compare the arrival
    years of the two routes and return the difference rows (empty = pass).

    - frozen route: star_set.arrival (set by pick_arrival_year, fingerprint bound);
    - events route: arrival_year of derive_star_event (set by detect_arrival).
    A difference row = {star_person_id, star_set_arrival, events_arrival_year,
              arrival_source, arrival_evidence_strength, note}: who / which year each
    route says / the evidence.
    A shipped star with no arrival found (event=None / missing) is also a disagreement
    (events_arrival_year=None) and also goes to a human.
    Non-shipped rows (5% flag False, or not a pure foreign poach) do not enter the gate.
    This function only reports differences and never takes a side.
    """
    frozen_by_id = {s["author_id"]: s for s in frozen_star_rows}
    diff: list[dict] = []
    for sid in sorted(ship_set_ids(frozen_by_id.values())):
        star_arrival = frozen_by_id[sid]["arrival"]
        event = events_by_star.get(sid)
        if event is None:
            diff.append({
                "star_person_id": sid,
                "star_set_arrival": star_arrival,
                "events_arrival_year": None,
                "arrival_source": None,
                "arrival_evidence_strength": None,
                "note": "events 路线 (清洗→众数切换 detect_arrival) 判无到任; "
                        "冻结 star_set (pick_arrival_year) 有到任年 — 人裁",
            })
            continue
        if event["arrival_year"] != star_arrival:
            diff.append({
                "star_person_id": sid,
                "star_set_arrival": star_arrival,
                "events_arrival_year": event["arrival_year"],
                "arrival_source": event["arrival_source"],
                "arrival_evidence_strength": event["arrival_evidence_strength"],
                "note": "两路到任年不等: 冻结 star_set=pick_arrival_year 路线 vs "
                        "events=detect_arrival 路线 — 绝不代码自选, 人裁",
            })
    return diff
