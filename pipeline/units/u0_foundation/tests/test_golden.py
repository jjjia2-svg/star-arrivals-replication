"""TDD red tests for U0 golden.py (the Yves Zenou golden-standard anchor).

Guards the Yves Zenou golden field set + C.10 (classify_golden signature)
+ GOLDEN_FAIL=18 + G-T37 (Yves Zenou structural_pass=False -> GOLDEN_FAIL=18).

Rules:
  - The ZENOU_STRUCTURAL anchor fields are exactly the golden field set; no field is invented.
  - golden.py is a constant layer + a pure decision (classify_golden), with no IO / no network / no state.
  - structural_pass=False -> the caller emits GOLDEN_FAIL (=18) (the code value is in exit_codes.py).
These tests are purely local, with no network and no data fetching.
"""
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from identity.golden import (  # noqa: E402
    MONASH_CANONICAL_ID,
    ZENOU_OBSERVED,
    ZENOU_STRUCTURAL,
    classify_golden,
)
from identity.exit_codes import GOLDEN_FAIL  # noqa: E402


# --- the ZENOU_STRUCTURAL anchor fields, verbatim (no field invented) ---

def test_monash_canonical_id_is_bare():
    # pin the bare id (not the name-bearing form "Monash University (I56590836)")
    assert MONASH_CANONICAL_ID == "I56590836"


def test_zenou_structural_anchor_fields_verbatim():
    # exactly the ZENOU_STRUCTURAL golden field set
    assert ZENOU_STRUCTURAL["name"] == "Yves Zénou"
    assert ZENOU_STRUCTURAL["must_be_found"] is True
    assert ZENOU_STRUCTURAL["must_resolve_single_person"] is True
    assert ZENOU_STRUCTURAL["must_be_star_at_p"] == 0.01
    assert ZENOU_STRUCTURAL["institution_canonical"] == "I56590836"
    assert ZENOU_STRUCTURAL["institution_not"] == "University of Sydney"
    assert ZENOU_STRUCTURAL["cluster_pure_econ_network"] is True
    assert ZENOU_STRUCTURAL["armi_fold_to_monash"] is True
    assert ZENOU_STRUCTURAL["caulfield_no_phantom_arrival"] is True
    assert ZENOU_STRUCTURAL["monash_1998_tagged_not_arrival_1998"] is True
    assert ZENOU_STRUCTURAL["arrival_requires_modal_and_prior_exit"] is True
    assert ZENOU_STRUCTURAL["works_count_range"] == (550, 620)
    assert ZENOU_STRUCTURAL["arrival_year_range"] == (2015, 2017)  # true arrival 2016, endpoints included


def test_zenou_institution_canonical_matches_monash_constant():
    # institution_canonical must == MONASH_CANONICAL_ID (single source of truth, no drift)
    assert ZENOU_STRUCTURAL["institution_canonical"] == MONASH_CANONICAL_ID


def test_zenou_observed_is_release_placeholder_none():
    # ZENOU_OBSERVED gets the snapshot version filled in after the m0 freeze (a reproduction anchor, not a rule) -> currently a None placeholder
    assert ZENOU_OBSERVED["_anchored_release"] is None
    assert ZENOU_OBSERVED["_topics_version"] is None


# --- C.10: classify_golden(frame) pure decision ---

def _passing_frame() -> dict:
    """A Yves Zenou observation frame that satisfies every structural anchor and has observed values in range."""
    return {
        "found": True,
        "resolved_single_person": True,
        "is_star_at_p01": True,
        "institution_canonical_observed": "I56590836",
        "armi_folded_to_monash": True,
        "caulfield_folded_to_none": True,
        "arrival_year_observed": 2016,
        "rejected_1998_backfill": True,
        "read_affiliations_years": False,
        "took_largest_cluster": False,
        "works_count_observed": 580,
    }


def test_classify_golden_returns_required_keys():
    # C.10: returns structural_pass / observed_in_range / flips / works_count_observed / arrival_year_observed
    out = classify_golden(_passing_frame())
    for k in (
        "structural_pass",
        "observed_in_range",
        "flips",
        "works_count_observed",
        "arrival_year_observed",
    ):
        assert k in out, f"classify_golden output is missing key {k}"


def test_classify_golden_passing_frame_structural_pass_true():
    out = classify_golden(_passing_frame())
    assert out["structural_pass"] is True
    assert out["observed_in_range"] is True
    assert out["flips"] == []
    assert out["works_count_observed"] == 580
    assert out["arrival_year_observed"] == 2016


def test_classify_golden_sydney_misplacement_fails_structural():
    # (2) placed at Sydney (not Monash) -> structural_pass=False, flips records this item
    frame = _passing_frame()
    frame["institution_canonical_observed"] = "I_SYDNEY_DECOY"
    out = classify_golden(frame)
    assert out["structural_pass"] is False
    assert "institution_canonical" in out["flips"]


def test_classify_golden_arrival_1998_backfill_fails_structural():
    # (4) explicit rejection of the 1998 backfill: if 1998 is observed / affiliations.years was read -> structural_pass=False
    frame = _passing_frame()
    frame["arrival_year_observed"] = 1998
    frame["rejected_1998_backfill"] = False
    out = classify_golden(frame)
    assert out["structural_pass"] is False


def test_classify_golden_arrival_year_out_of_range_not_in_range():
    # (6) arrival-year range [2015,2017], endpoints included: 2016 is inside, 2014 outside -> observed_in_range=False
    frame = _passing_frame()
    frame["arrival_year_observed"] = 2014
    out = classify_golden(frame)
    assert out["observed_in_range"] is False


def test_classify_golden_works_count_out_of_range_not_in_range():
    # (6) works_count in [550,620], endpoints included: 540 is outside -> observed_in_range=False
    frame = _passing_frame()
    frame["works_count_observed"] = 540
    out = classify_golden(frame)
    assert out["observed_in_range"] is False


def test_classify_golden_works_count_endpoints_in_range():
    # endpoints included: both 550 and 620 count as in range
    lo = _passing_frame()
    lo["works_count_observed"] = 550
    hi = _passing_frame()
    hi["works_count_observed"] = 620
    assert classify_golden(lo)["observed_in_range"] is True
    assert classify_golden(hi)["observed_in_range"] is True


def test_classify_golden_arrival_year_endpoints_in_range():
    # endpoints included: both 2015 and 2017 count as in range
    lo = _passing_frame()
    lo["arrival_year_observed"] = 2015
    hi = _passing_frame()
    hi["arrival_year_observed"] = 2017
    assert classify_golden(lo)["observed_in_range"] is True
    assert classify_golden(hi)["observed_in_range"] is True


def test_classify_golden_not_found_fails_structural():
    # (1) cannot be found -> structural_pass=False
    frame = _passing_frame()
    frame["found"] = False
    out = classify_golden(frame)
    assert out["structural_pass"] is False


def test_classify_golden_took_largest_cluster_fails_structural():
    # (5) took the largest cluster (13 fragments without ORCID were not merged back into the same person) -> structural_pass=False
    frame = _passing_frame()
    frame["took_largest_cluster"] = True
    out = classify_golden(frame)
    assert out["structural_pass"] is False


def test_golden_fail_exit_code_is_18():
    # second half of T37: structural_pass=False -> the caller emits GOLDEN_FAIL (=18)
    assert GOLDEN_FAIL == 18
