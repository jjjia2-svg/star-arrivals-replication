"""identity/departure_rule.py — pure function for departure detection (legacy_depart_rule, same source as the arrival rule).

Caliber (all read from RED['arrival']['legacy_depart_rule'], zero hardcoding in the module):
  - orcid_end_date: true        -> prefer the exit year of that inst in truth_dates.exits (ORCID/ground truth)
  - zero_authorship_years: 4    -> otherwise: N consecutive years of zero authorship after the last active year at that inst = departed

Pure-function rule (identity layer): no IO / no network / no state / no operational control flow; thresholds are read only from RED,
and unset (None) -> require() raises RedlineUnsigned, never defaulting silently.

Input contract (reuses the input-structure validation of arrival_rule):
  per_work_timeline_canonical: list[dict], each item = {work_id, publication_year,
      canonical_inst_ids}; ascending by publication_year; already folded through the education whitelist;
      it must never contain a field derived from affiliations[].years (arrival red line; a forbidden field is stopped by the validation).
  inst_id: the canonical(bare) id of the target institution to test for departure.
  truth_dates: dict|None, structure {"arrivals":{inst_id:year}, "exits":{inst_id:year}}
      (externally scraped: only consumed, never fetched or fed back).

Returns: int (departure year) | None (no departure judged).

In plain words: detect_departure = the year a person left an institution. Trust the ORCID/ground-truth employment end year first; if there is none, look at
"after the last publication at that institution, 4 consecutive years with no publication at all at that institution" -> departed (departure year = the year after the last active year).
"""
from __future__ import annotations

from typing import Any

from common._redlines import RedlineUnsigned, require

# Reuse the input-structure contract validation of arrival_rule (single source of truth, not rewritten):
#   - _validate_input_contract: validates list / the 3-key set / ascending order / forbidden affiliations fields.
#   - ArrivalInputContractError: the violation exception (a ValueError subclass).
from identity.arrival_rule import (
    ArrivalInputContractError,
    _validate_input_contract,
)


def _inst_active_years(
    per_work_timeline_canonical: list[dict], inst_id: str
) -> set[int]:
    """The set of years in which this author has a bylined publication at inst_id (reads only canonical_inst_ids)."""
    active: set[int] = set()
    for item in per_work_timeline_canonical:
        if inst_id in item["canonical_inst_ids"]:
            active.add(item["publication_year"])
    return active


def detect_departure(
    per_work_timeline_canonical: list[dict],
    inst_id: str,
    truth_dates: dict[str, Any] | None = None,
) -> int | None:
    """Judge the year of departure from inst_id (orcid_end_date first, otherwise N years of zero authorship).

    The caliber is entirely read from RED['arrival']['legacy_depart_rule'] (zero hardcoding; require raises on None,
    so an unset caliber is caught).
    """
    if inst_id is None:
        raise ValueError("detect_departure: inst_id must not be None (caller bug, fail loudly)")

    # --- 0. Read the caliber from RED (zero hardcoding) ---
    legacy = require("arrival", "legacy_depart_rule")  # The caliber dict
    orcid_end_flag = legacy["orcid_end_date"]          # Nested sub-key: whether to trust the ORCID exit year
    zero_years = legacy["zero_authorship_years"]       # Nested sub-key: threshold of consecutive zero-authorship years

    # Nested sub-keys never get a silent default either (consistent with require raising on None).
    if orcid_end_flag is None:
        raise RedlineUnsigned(
            "Red-line key arrival.legacy_depart_rule.orcid_end_date is not set (null) — the code never silently supplies a default."
        )
    if zero_years is None:
        raise RedlineUnsigned(
            "Red-line key arrival.legacy_depart_rule.zero_authorship_years is not set (null) — never silently supply a default."
        )

    # --- 1. Strictly validate the input shape; a forbidden affiliations field is stopped here ---
    _validate_input_contract(per_work_timeline_canonical)

    if not per_work_timeline_canonical:
        return None

    # --- 2. ORCID/ground truth first: if truth_dates.exits has this inst -> trust that exit year ---
    if orcid_end_flag and truth_dates is not None:
        exits = truth_dates.get("exits") or {}
        if inst_id in exits and exits[inst_id] is not None:
            return int(exits[inst_id])

    # --- 3. Fallback: zero_years consecutive years of zero authorship after the last active year at this inst -> departed ---
    active_years = _inst_active_years(per_work_timeline_canonical, inst_id)
    if not active_years:
        # Never published at this inst -> there is no departure to speak of.
        return None

    last_active = max(active_years)
    all_years = [item["publication_year"] for item in per_work_timeline_canonical]
    last_observed = max(all_years)

    # Departure-year candidate = the year after the last active year; "zero_years consecutive years after it" must all have zero authorship at inst.
    # Judge with the right bound of the observation window: from last_active+1 up to last_observed there must be at least zero_years consecutive years,
    # and none of those years may be in active_years (i.e. zero authorship at inst).
    gap_after = last_observed - last_active  # Number of years observed after the last active year (upper bound of the empty-window length)
    if gap_after >= zero_years:
        # The zero_years years last_active+1 .. last_active+zero_years must all have zero authorship at inst.
        # Since last_active = max(active_years) by definition, these years are all > last_active -> necessarily not in active_years.
        return last_active + 1

    return None
