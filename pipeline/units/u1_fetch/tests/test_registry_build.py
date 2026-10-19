"""Tests for registry_build: build the education registry from snapshot institutions (the registry input of run_m1_full).

The registry is the set of valid canonical education parent institutions used by fold_to_canonical. Its key
domain is all education institutions (including foreign ones such as Stockholm), so that sub-institutions
and foreign institutions on papers fold back to the parent university. This module only picks
type in EDUCATION_WHITELIST, and keeps the fields build_registry_by_id needs (openalex_id) and readable
fields (display_name/country_code).

Definition-neutral: it only filters by the whitelist and takes fields; it does not decide arrival, employment status
or any identification threshold.
"""
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))  # conftest also bridges this, as a second safeguard

from m1_ingest.registry_build import build_education_registry  # noqa: E402


def _inst(iid, *, itype, name, country, lineage=None):
    return {
        "id": f"https://openalex.org/{iid}",
        "display_name": name,
        "type": itype,
        "country_code": country,
        "lineage": [f"https://openalex.org/{x}" for x in (lineage or [iid])],
    }


def test_keeps_only_education_bare_id_incl_foreign():
    """Keep only type=education; openalex_id is stripped to bare; foreign ones (Stockholm) are kept; non-education (government) is dropped."""
    insts = [
        _inst("I56590836", itype="education", name="Monash University", country="AU"),
        _inst("I_GOV", itype="government", name="Some Gov Dept", country="AU"),
        _inst("I_STK", itype="education", name="Stockholm University", country="SE"),
        _inst("I_FACIL", itype="facility", name="Some Research Facility", country="AU"),
    ]
    reg = build_education_registry(insts)
    ids = {r["openalex_id"] for r in reg}
    assert ids == {"I56590836", "I_STK"}, "Keep only education + bare id, foreign included; government/facility dropped"
    assert all(r["type"] == "education" for r in reg)
    by = {r["openalex_id"]: r for r in reg}
    assert by["I56590836"]["display_name"] == "Monash University"
    assert by["I_STK"]["country_code"] == "SE"


def test_feeds_build_registry_by_id_and_fold_child_to_monash():
    """The registry is fed to build_registry_by_id -> fold_to_canonical: a Monash sub-institution (lineage -> Monash) folds to Monash;
    Monash itself self-hits. This shows the table really lets folding map sub-institutions to the parent university (the whole reason the registry exists)."""
    from identity.constants import build_registry_by_id
    from common.inst_lineage import fold_to_canonical

    reg = build_education_registry([
        _inst("I56590836", itype="education", name="Monash University", country="AU"),
    ])
    idx = build_registry_by_id(reg)
    assert "I56590836" in idx

    # A Monash sub-institution on one paper (facility, not education, lineage includes Monash) -> folds back to Monash.
    child = {"openalex_id": "I_CHILD", "type": "facility",
             "lineage": ["I56590836", "I_CHILD"], "associated_institutions": []}
    assert fold_to_canonical(child, idx) == "I56590836", "Sub-institutions should fold back into the parent university Monash"

    # Monash itself -> self-hit, folds to itself.
    monash = {"openalex_id": "I56590836", "type": "education",
              "lineage": ["I56590836"], "associated_institutions": []}
    assert fold_to_canonical(monash, idx) == "I56590836"


def test_uses_signed_education_whitelist_not_literal():
    """The filter is the EDUCATION_WHITELIST (redlines), not the bare literal 'education'."""
    from common.inst_lineage import EDUCATION_WHITELIST

    assert "education" in EDUCATION_WHITELIST
    # Any type outside the whitelist never enters the registry.
    reg = build_education_registry([_inst("I_HOSP", itype="healthcare", name="Hosp", country="AU")])
    assert reg == []


def test_skips_none_and_missing_id():
    """None entries are skipped; an education record with no id is not added (no invented key)."""
    reg = build_education_registry([
        None,
        {"type": "education", "display_name": "no id", "country_code": "AU"},  # missing id
        _inst("I_OK", itype="education", name="OK Uni", country="AU"),
    ])
    assert {r["openalex_id"] for r in reg} == {"I_OK"}
