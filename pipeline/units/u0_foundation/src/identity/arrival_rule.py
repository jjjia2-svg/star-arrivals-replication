"""identity/arrival_rule.py — pure function for arrival detection (red line #3: modal-institution method + a 2-year sustain window).

Caliber (all read from RED['arrival'], zero hardcoding in the module):
  - method = modal_institution          modal-institution method
  - sustain_window_years = 2            after arrival the new institution must persist for >=2 consecutive years to count (guards against single-year false positives)
  - trust_affiliations_years = false    never trust affiliations[].years (Yves Zenou gold-standard case: this field
                                        backfills Monash to 1998, a real false positive)
  - migrant_only_in_main = true         (the main sample keeps only true in-migrants; this layer only produces the arrival year, the in-migrant filter is downstream)

Pure-function rule (identity layer): no IO / no network / no state / no operational control flow; thresholds are read only from RED.

Public input-structure contract (guards against fixtures guessing the wrong shape):
  per_work_timeline_canonical: list[dict], each item = {
     "work_id": str,                  # canonical(bare)
     "publication_year": int,
     "canonical_inst_ids": list[str], # all canonical(bare) education institution ids of that author on that work (already folded)
  }
  Constraints (the caller's responsibility; this function validates the shape): sorted ascending by publication_year;
        canonical_inst_ids have passed EDUCATION_WHITELIST + fold_to_canonical;
        it must never contain any field derived from affiliations[].years (red line #3).
  Rule: this contract only exposes the input data structure; the decision caliber (modal-institution method / 2-year window / never trust affiliations.years)
        is sealed inside and does not change with the public structure.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from common._redlines import require

# The set of keys allowed in an input item (fixed at exactly these 3; a forbidden key such as affiliations means caliber contamination).
_ALLOWED_ITEM_KEYS: frozenset[str] = frozenset(
    {"work_id", "publication_year", "canonical_inst_ids"}
)


class ArrivalInputContractError(ValueError):
    """per_work_timeline_canonical violates the public input-structure contract (shape / ascending order / forbidden fields).

    Fail loudly, never swallow silently: a wrong shape would give a false-green window decision and must be stopped before the decision.
    """


def _validate_input_contract(per_work_timeline_canonical: Any) -> None:
    """Guard the public input-structure contract; a violation raises ArrivalInputContractError.

    Checks:
      1. The top level is a list.
      2. Each item is a dict whose key set is exactly {work_id, publication_year, canonical_inst_ids};
         extra keys (especially affiliations / affiliations_years) -> raise (red line #3, guards against contamination).
      3. publication_year is an int (not bool); canonical_inst_ids is a list.
      4. The whole list is ascending by publication_year (non-descending, not out of order).
    """
    if not isinstance(per_work_timeline_canonical, list):
        raise ArrivalInputContractError(
            f"per_work_timeline_canonical must be a list, got {type(per_work_timeline_canonical)!r}"
        )

    prev_year: int | None = None
    for i, item in enumerate(per_work_timeline_canonical):
        if not isinstance(item, dict):
            raise ArrivalInputContractError(f"item {i} must be a dict, got {type(item)!r}")

        keys = set(item.keys())
        if keys != _ALLOWED_ITEM_KEYS:
            extra = keys - _ALLOWED_ITEM_KEYS
            missing = _ALLOWED_ITEM_KEYS - keys
            # Forbidden fields (such as affiliations / affiliations_years) land in extra; missing required keys land in missing.
            raise ArrivalInputContractError(
                f"item {i} key set violates the P-3 contract: extra={sorted(extra)} missing={sorted(missing)} "
                f"(the contract pins exactly {sorted(_ALLOWED_ITEM_KEYS)}; it never includes derived affiliations[].years fields)"
            )

        year = item["publication_year"]
        # bool is a subclass of int; exclude it explicitly (publication_year must not be True/False).
        if isinstance(year, bool) or not isinstance(year, int):
            raise ArrivalInputContractError(
                f"item {i} publication_year must be an int, got {type(year)!r}"
            )

        if not isinstance(item["canonical_inst_ids"], list):
            raise ArrivalInputContractError(
                f"item {i} canonical_inst_ids must be list[str], got "
                f"{type(item['canonical_inst_ids'])!r}"
            )

        if prev_year is not None and year < prev_year:
            raise ArrivalInputContractError(
                f"per_work_timeline_canonical must be in ascending publication_year order; "
                f"item {i} year={year} < previous item year={prev_year}"
            )
        prev_year = year


def _modal_institution_by_year(
    per_work_timeline_canonical: list[dict],
) -> dict[int, str]:
    """Compute the modal institution year by year (the core of the modal-institution method): flatten and count
    the canonical_inst_ids of all works of that year and take the institution id that occurs most.
    On a tie take the smallest id in lexicographic order, which is deterministic and reproducible.

    Reads only canonical_inst_ids; never touches affiliations.years (structurally it cannot get it, the contract forbids that field).
    Returns {year: modal_institution_id}; a year with no institution id at all is left out of the result.
    """
    per_year_counter: dict[int, Counter] = {}
    for item in per_work_timeline_canonical:
        year = item["publication_year"]
        counter = per_year_counter.setdefault(year, Counter())
        for inst_id in item["canonical_inst_ids"]:
            counter[inst_id] += 1

    modal: dict[int, str] = {}
    for year, counter in per_year_counter.items():
        if not counter:
            continue
        # Highest frequency; on a tie -> the lexicographically smallest id (deterministic, reproducible).
        max_count = max(counter.values())
        winners = sorted(k for k, v in counter.items() if v == max_count)
        modal[year] = winners[0]
    return modal


def detect_arrival(
    per_work_timeline_canonical: list[dict],
    truth_dates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Decide arrival with the modal-institution method + a 2-year sustain window (red line #3).

    Arguments:
        per_work_timeline_canonical: see the input-structure contract in the module docstring (this function strictly validates the shape).
        truth_dates: external truth dictionary (orcid/arc/wayback hits etc.). This decision layer never takes an
            affiliations[].years-style backfill from it (trust_affiliations_years=false); the arrival year is decided
            entirely by the per-work modal-institution sustain window. truth_dates is only a carrier for downstream evidence strength / source labels
            and takes no part in deciding "which year".

    Returns a dict:
        {
          "arrival_year": int | None,        # the arrival year (the first modal switch year that satisfies the sustain window); none -> None
          "arrival_institution": str | None, # canonical(bare) id of the institution arrived at; none -> None
          "method": "modal_institution",     # the caliber source (read from RED and echoed back for audit)
          "sustain_window_years": int,       # the sustain window actually used (read from RED)
        }

    The caliber is entirely read from RED['arrival'], with no hardcoded threshold in the module.
    """
    # --- 0. Read the caliber from RED (zero hardcoding; require raises on None, which catches an unset caliber) ---
    method = require("arrival", "method")                       # "modal_institution"
    sustain_window = require("arrival", "sustain_window_years")  # 2
    trust_affil_years = require("arrival", "trust_affiliations_years")  # False

    # Red line #3 self-check: the premise of this whole algorithm = never trust affiliations.years. If that setting is changed to true,
    #   the identification caliber was changed upstream — this decision layer must not keep using the "reject backfill" logic, and fails loudly for a re-decision.
    if trust_affil_years:
        raise ArrivalInputContractError(
            "RED['arrival'].trust_affiliations_years=true conflicts with the premise of this decision layer "
            "(this layer's rule is anchored on never trusting affiliations.years, red line #3); the rule has changed and a person must re-decide, the code does not decide for itself."
        )

    # This decision layer implements only the modal-institution method; any other method value = a caliber change, with no self-decided fallback.
    if method != "modal_institution":
        raise ArrivalInputContractError(
            f"RED['arrival'].method={method!r} is not modal_institution; this layer implements only the modal-institution method, "
            "any other rule must be decided by a person, not by the code."
        )

    # --- 1. Strictly validate the input shape; a forbidden affiliations field is stopped here ---
    _validate_input_contract(per_work_timeline_canonical)

    no_arrival = {
        "arrival_year": None,
        "arrival_institution": None,
        "method": method,
        "sustain_window_years": sustain_window,
    }

    if not per_work_timeline_canonical:
        return no_arrival

    # --- 2. Modal institution year by year (reads only canonical_inst_ids) ---
    modal_by_year = _modal_institution_by_year(per_work_timeline_canonical)
    if not modal_by_year:
        return no_arrival

    years_sorted = sorted(modal_by_year.keys())

    # --- 3. Find the first arrival where "the modal institution switches to a brand-new institution + the new institution persists for sustain_window years" ---
    #     Arrival = a true in-migration: (a) the institution differs from the modal institution of the immediately preceding year (a switch); (b) from that year on,
    #     the modal institution of sustain_window consecutive recorded years is it (the sustain window); (c) the institution is "brand-new": it has never
    #     appeared as a modal institution before. Condition (c) excludes "bouncing back to the old base" (e.g. Stockholm->Monash for one year->Stockholm,
    #     returning to Stockholm is not an arrival), and also excludes the first institution at the start of a career (prev_inst is None).
    prev_inst: str | None = None
    seen_modal_insts: set[str] = set()   # Modal institutions seen before (including all earlier years), used to judge "is it brand-new"
    for idx, year in enumerate(years_sorted):
        inst = modal_by_year[year]

        is_switch = prev_inst is not None and inst != prev_inst
        is_new_institution = inst not in seen_modal_insts
        if is_switch and is_new_institution:
            # Check that, from this year on (including this year), the modal institution of sustain_window consecutive "recorded years" all == inst.
            window_years = years_sorted[idx: idx + sustain_window]
            if len(window_years) >= sustain_window and all(
                modal_by_year[wy] == inst for wy in window_years
            ):
                return {
                    "arrival_year": year,
                    "arrival_institution": inst,
                    "method": method,
                    "sustain_window_years": sustain_window,
                }

        seen_modal_insts.add(inst)
        prev_inst = inst

    return no_arrival
