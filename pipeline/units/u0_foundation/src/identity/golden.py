"""Yves Zenou gold-standard anchor ZENOU_STRUCTURAL (merged field set) + the pure judgement classify_golden.

Seven assertions of the gold-standard test.
Identity constants layer: no IO / no network / no state / no operational control flow.

Why a gold standard (in plain words):
  Yves Zenou is a known must-catch case — the pipeline must (1) find Zenou and recognize this person as a star (2) place this person at Monash (not Sydney)
  (3) arrival year = 2016 (moved from Stockholm, modal-institution method) (4) explicitly reject the 1998 backfill (never read
  affiliations.years) (5) not take the largest cluster (13 fragments with no ORCID merge back into the same person) (6) works_count
  in [550,620] (7) the Stockholm foreign institution is present in institutions.parquet.
  Missing a person / a false event must never recur (hard requirement). If any anchor flips -> structural_pass=False
  -> the caller issues GOLDEN_FAIL(=18, see exit_codes.py).
"""
from __future__ import annotations

from typing import Any, Dict

# --- Monash canonical id (bare; the named form "Monash University (I56590836)" is discarded) ---
MONASH_CANONICAL_ID: str = "I56590836"

# --- The single merged ZENOU_STRUCTURAL anchor field set (no field invented) ---
# Ground-truth anchor (measured live): A5017376589, orcid 0000-0001-6516-0812,
#   last_known_institutions=[] (empty), affiliations=42 entries.
ZENOU_STRUCTURAL: Dict[str, Any] = {
    "name": "Yves Zénou",
    "must_be_found": True,
    "must_resolve_single_person": True,
    "must_be_star_at_p": 0.01,
    "institution_canonical": "I56590836",
    "institution_not": "University of Sydney",
    "cluster_pure_econ_network": True,
    "armi_fold_to_monash": True,
    "caulfield_no_phantom_arrival": True,
    "monash_1998_tagged_not_arrival_1998": True,
    "arrival_requires_modal_and_prior_exit": True,
    "works_count_range": (550, 620),
    "arrival_year_range": (2015, 2017),   # True arrival 2016, endpoints included
}

# --- To be filled in with the snapshot version after the m0 freeze (reproducibility anchor, not an identification caliber) ---
ZENOU_OBSERVED: Dict[str, Any] = {
    "_anchored_release": None,
    "_topics_version": None,
}


def _in_range_inclusive(value: int, bounds: tuple[int, int]) -> bool:
    """Whether value falls in the closed interval [lo, hi] (endpoints included). value missing (None) -> False."""
    if value is None:
        return False
    lo, hi = bounds
    return lo <= value <= hi


def classify_golden(frame: Dict[str, Any]) -> Dict[str, Any]:
    """Run the gold-standard judgement on a Yves Zenou observation frame (a pure function, no IO).

    Input frame (the measured observation from the U1 Yves Zenou vertical slice) fields:
      - found:bool                            can be found
      - resolved_single_person:bool           disambiguated into a single person (neither split nor wrongly merged)
      - is_star_at_p01:bool                    recognized as a top-1% star
      - institution_canonical_observed:str     the folded institution (must == MONASH_CANONICAL_ID)
      - armi_folded_to_monash:bool             the ARMI facility folds to Monash
      - caulfield_folded_to_none:bool          Caulfield is not forced onto any university (folds to None)
      - arrival_year_observed:int              the observed arrival year
      - rejected_1998_backfill:bool            explicitly rejected the Monash 1998 backfill
      - read_affiliations_years:bool           whether affiliations[].years was (wrongly) read (arrival red line: must be False)
      - took_largest_cluster:bool              whether the largest cluster was (wrongly) taken (must be False)
      - works_count_observed:int               the observed total works count

    Returns:
      {
        structural_pass:bool,        all structural anchors are right (any flip -> False -> GOLDEN_FAIL)
        observed_in_range:bool,      works_count and arrival_year both fall in the anchored closed interval [lo,hi]
        flips:list[str],             names of the flipped anchors (for diagnosis; [] when structural_pass=True)
        works_count_observed:int,
        arrival_year_observed:int,
      }

    Rule: this function only reads the frame + the ZENOU_STRUCTURAL anchor and changes no identification caliber (the caliber is in redlines).
    """
    flips: list[str] = []

    # (1) found + recognized as a star
    if not frame.get("found", False):
        flips.append("must_be_found")
    if not frame.get("resolved_single_person", False):
        flips.append("must_resolve_single_person")
    if not frame.get("is_star_at_p01", False):
        flips.append("must_be_star_at_p")

    # (2) placed at Monash (not Sydney): the folded institution canonical must == the anchored Monash id
    if frame.get("institution_canonical_observed") != ZENOU_STRUCTURAL["institution_canonical"]:
        flips.append("institution_canonical")

    # Institution-folding sub-anchors: ARMI -> Monash; Caulfield -> None (no university forced)
    if not frame.get("armi_folded_to_monash", False):
        flips.append("armi_fold_to_monash")
    if not frame.get("caulfield_folded_to_none", False):
        flips.append("caulfield_no_phantom_arrival")

    # (4) explicitly reject the 1998 backfill + never read affiliations.years (arrival red line)
    if not frame.get("rejected_1998_backfill", False):
        flips.append("monash_1998_tagged_not_arrival_1998")
    if frame.get("read_affiliations_years", False):
        # Reading affiliations[].years violates the arrival red line; even if the numbers happen to be right it counts as a flip
        flips.append("trust_affiliations_years_violation")
    if frame.get("arrival_year_observed") == 1998:
        # Arrival landing directly on 1998 = the 1998 backfill was not stopped
        flips.append("arrival_year_is_1998")

    # (5) do not take the largest cluster (the 13 fragments with no ORCID must merge back into the same person, do not greedily take the largest cluster)
    if frame.get("took_largest_cluster", False):
        flips.append("took_largest_cluster")

    structural_pass = len(flips) == 0

    # (6) observed_in_range: works_count in [550,620] and arrival_year in [2015,2017] (endpoints included)
    works_count_observed = frame.get("works_count_observed")
    arrival_year_observed = frame.get("arrival_year_observed")
    observed_in_range = (
        _in_range_inclusive(works_count_observed, ZENOU_STRUCTURAL["works_count_range"])
        and _in_range_inclusive(arrival_year_observed, ZENOU_STRUCTURAL["arrival_year_range"])
    )

    return {
        "structural_pass": structural_pass,
        "observed_in_range": observed_in_range,
        "flips": flips,
        "works_count_observed": works_count_observed,
        "arrival_year_observed": arrival_year_observed,
    }
