"""M7a-T7 arrival_departure: arrival-year assembly, building the 11-column EVENTS row.

In plain words: after detect_arrival (U0, modal-institution method + 2-year sustain window) has judged the arrival year, this layer assembles it + the arrival-evidence
hit + the previous home's exit year into one EVENTS row (schema [23], 11 columns).

Assembly order rule (followed by run_u4): first clean with pollution_guard.clean_au_attributions (drop fake Australian years) ->
then build per_work_timeline -> detect_arrival. Otherwise fake Australian years stop the true institution from being "new" in the true arrival year -> a missed detection.

Rule anchors: the detect_arrival/departure definitions are fixed (#3); the three EVENTS columns (modal_inst_year/prior_main_exited/
arrival_evidence_strength) are assembled in this layer; with no ground-truth hit, strength/source go to the inferred tier (modal_inst_shift/
modal_shift). min_tenure_ok = the 2-year sustain window already guaranteed by detect_arrival (no separate min_tenure
rule: an established arrival satisfies it). Pure function, no IO.
"""
from __future__ import annotations

from typing import Any, Iterable


def build_per_work_timeline(rows: Iterable[dict]) -> list[dict]:
    """Cleaned evidence rows -> P-3 input of detect_arrival (per_work_timeline_canonical).

    rows: each {work_id, publication_year, canonical_ids, ...} (the kept output of pollution_guard.clean_au_
    attributions). Merge canonical_ids by work_id -> the three keys {work_id, publication_year,
    canonical_inst_ids}, sorted ascending by (year, work_id) (P-3 contract).

    Assembly order rule: clean_au_attributions must run before this function (drop fake Australian years); otherwise fake Australian years
    stop the true institution from being "new" in the true arrival year -> detect_arrival misses it (see test_uncleaned_fake_monash).
    """
    by_work: dict[str, dict] = {}
    for r in rows:
        w = r["work_id"]
        if w not in by_work:
            by_work[w] = {"work_id": w, "publication_year": r["publication_year"], "_insts": set()}
        by_work[w]["_insts"].update(r["canonical_ids"])
    timeline = [
        {"work_id": e["work_id"], "publication_year": e["publication_year"],
         "canonical_inst_ids": sorted(e["_insts"])}
        for e in by_work.values()
    ]
    timeline.sort(key=lambda x: (x["publication_year"], x["work_id"]))
    return timeline


def assemble_event(
    *,
    star_person_id: str,
    arrival: dict,
    dept_id: str,
    truth_hit: dict | None = None,
    departed_year: int | None = None,
    modal_inst_year: bool = False,
) -> dict | None:
    """detect_arrival result + evidence hit + exit year -> 11-column EVENTS row (schema [23]). No arrival -> None.

    Args:
        arrival: the 4-key dict returned by detect_arrival {arrival_year, arrival_institution, method, sustain_window_years}.
        dept_id: canonical education parent (university-level) id of the arrival department.
        truth_hit: what truth_dates.select_truth_date returns, {arrival_source, arrival_evidence_strength},
                   or None (no ground-truth hit -> inferred tier).
        departed_year: departure_rule.detect_departure result, int|None (the previous home's exit year).
        modal_inst_year: corroboration bool that the arrival year is_modal (U3 affil_timeline).
    """
    ay: Any = arrival["arrival_year"]
    if ay is None:
        return None                       # No arrival -> no event

    if truth_hit is not None:
        src = truth_hit["arrival_source"]
        strength = truth_hit["arrival_evidence_strength"]
    else:
        # No ground-truth hit -> the arrival year is driven by a modal-institution switch -> inferred tier.
        src = "modal_inst_shift"
        strength = "modal_shift"

    return {
        "event_id": f"{star_person_id}:{ay}",
        "dept_id": dept_id,
        "star_person_id": star_person_id,
        "arrival_year": ay,
        "t_minus_1": ay - 1,
        "arrival_source": src,
        "arrival_evidence_strength": strength,
        "modal_inst_year": modal_inst_year,
        "prior_main_exited": departed_year is not None,
        "min_tenure_ok": True,            # detect_arrival already guarantees the 2-year sustain window -> an established arrival satisfies it
        "departed_year": departed_year,   # int|None (no exit -> None; a missing year stays blank, never filled with 0)
    }
