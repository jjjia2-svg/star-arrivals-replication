"""TDD red tests for U0 inst_lineage.py (group 8 T27-T31; HIGH-10).

Guards the folding rules and the killer fixtures:
  - fold_to_canonical(inst, registry_by_id) -> str|None: a three-way fold
      (1) self is in the registry / (2) a lineage ancestor contains a registry id /
      (3) associated_institutions has relationship in {parent} and is education.
    Returns a bare id; None if it cannot fold.
  - in_au_econ_dept(canonical_id, econ_dept_ids) -> bool: reconciliation only, not an identity authority.
  - EDUCATION_WHITELIST = frozenset({"education"}): read from redlines.RED["education_whitelist"].

Killer counter-examples (hard-won from porting the old code):
  T27 ARMI I2801239119 (facility) -> Monash I56590836 (lineage ancestor).
  T28 Caulfield I4210114009 -> None (must not be forced onto any university).
  T29 Sydney decoy -> never wrongly folded to Monash (the cheap defence of the golden standard).
  T30 Yves Zenou's foreign institution Stockholm I161593684/IFN is present -> fold is not None.
  T31 build_registry_by_id index key = record["openalex_id"], fed in as the second argument.

The fixture shapes match real OpenAlex verbatim:
  lineage = list[str] (URL form), associated_institutions = list[{id,relationship,type}].
These tests are purely local, with no network and no data fetching (identity rule).
"""
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common.inst_lineage import (  # noqa: E402
    EDUCATION_WHITELIST,
    fold_to_canonical,
    in_au_econ_dept,
)

# --- real OpenAlex institution ids (bare) ---
MONASH = "I56590836"
ARMI = "I2801239119"
CAULFIELD = "I4210114009"
STOCKHOLM = "I161593684"
SYDNEY = "I99464096"  # University of Sydney (decoy, not in the registry)


def _registry_by_id():
    """registry_by_id = {bare openalex_id : record}; contains only canonical education parent institutions.

    Monash + Stockholm are legitimate education anchors in the registry (the product of build_registry_by_id).
    """
    return {
        MONASH: {
            "openalex_id": MONASH,
            "display_name": "Monash University",
            "type": "education",
            "lineage": [f"https://openalex.org/{MONASH}"],
            "associated_institutions": [],
            "ror": "https://ror.org/02bfwt286",
        },
        STOCKHOLM: {
            "openalex_id": STOCKHOLM,
            "display_name": "Stockholm University",
            "type": "education",
            "lineage": [f"https://openalex.org/{STOCKHOLM}"],
            "associated_institutions": [],
            "ror": "https://ror.org/05f0yaq80",
        },
    }


# ============ EDUCATION_WHITELIST is read from redlines ============

def test_education_whitelist_is_frozenset_education():
    # C.1 / HIGH-10: EDUCATION_WHITELIST = frozenset({"education"}), read from RED["education_whitelist"]
    assert EDUCATION_WHITELIST == frozenset({"education"})
    assert isinstance(EDUCATION_WHITELIST, frozenset)


# ============ T27: ARMI -> Monash (lineage ancestor) ============

def test_T27_armi_folds_to_monash_full_real_shape():
    # ARMI I2801239119 (facility) -> folds to Monash I56590836 (the real OpenAlex shape verbatim:
    # lineage contains Monash + assoc also contains Monash as parent education -> both path2 and path3 should hit).
    armi = {
        "openalex_id": ARMI,
        "type": "facility",
        "lineage": [
            "https://openalex.org/I2801037857",
            f"https://openalex.org/{ARMI}",
            f"https://openalex.org/{MONASH}",
        ],
        "associated_institutions": [
            {"id": "https://openalex.org/I2801037857", "relationship": "parent", "type": "government"},
            {"id": f"https://openalex.org/{MONASH}", "relationship": "parent", "type": "education"},
        ],
    }
    assert fold_to_canonical(armi, _registry_by_id()) == MONASH


def test_T27_path2_lineage_only_isolated():
    # path2 isolation: only lineage contains the registry ancestor (assoc deliberately emptied) -> must still fold to Monash.
    # Guards against path2 silently breaking while path3 masks it (a false-pass risk exposed by mutation testing).
    armi_lineage_only = {
        "openalex_id": ARMI,
        "type": "facility",
        "lineage": [
            "https://openalex.org/I2801037857",
            f"https://openalex.org/{ARMI}",
            f"https://openalex.org/{MONASH}",
        ],
        "associated_institutions": [],  # emptied -> only path2 can match
    }
    assert fold_to_canonical(armi_lineage_only, _registry_by_id()) == MONASH


def test_T27_path3_assoc_parent_edu_only_isolated():
    # path3 isolation: only the associated parent-education contains the registry id (lineage deliberately does not) -> folds to Monash.
    # Guards against path3 silently breaking while path2 masks it.
    inst_assoc_only = {
        "openalex_id": "I888888888",   # itself is not in the registry
        "type": "facility",
        "lineage": ["https://openalex.org/I888888888"],  # lineage contains only itself -> path2 does not hit
        "associated_institutions": [
            {"id": f"https://openalex.org/{MONASH}", "relationship": "parent", "type": "education"},
        ],
    }
    assert fold_to_canonical(inst_assoc_only, _registry_by_id()) == MONASH


# ============ T28: Caulfield → None ============

def test_T28_caulfield_folds_to_none():
    # Caulfield I4210114009 (healthcare) -> None;
    # real OpenAlex: lineage contains only itself + another healthcare institution (no Monash), and the assoc parent is also healthcare (not education).
    caulfield = {
        "openalex_id": CAULFIELD,
        "type": "healthcare",
        "lineage": [
            f"https://openalex.org/{CAULFIELD}",
            "https://openalex.org/I4210163178",
        ],
        "associated_institutions": [
            {"id": "https://openalex.org/I4210163178", "relationship": "parent", "type": "healthcare"},
        ],
    }
    assert fold_to_canonical(caulfield, _registry_by_id()) is None


# ============ T29: the Sydney decoy is never wrongly folded to Monash ============

def test_T29_sydney_decoy_never_folds_to_monash():
    # Sydney decoy: neither lineage nor assoc contains any registry id -> must be None, never wrongly folded to Monash
    sydney = {
        "openalex_id": SYDNEY,
        "type": "education",
        "lineage": [f"https://openalex.org/{SYDNEY}"],  # contains only itself, itself not in the registry
        "associated_institutions": [
            # Monash is deliberately inserted but with relationship=related (not parent): path 3 must not pick it up
            {"id": f"https://openalex.org/{MONASH}", "relationship": "related", "type": "education"},
        ],
    }
    out = fold_to_canonical(sydney, _registry_by_id())
    assert out != MONASH, "Sydney decoy wrongly folded into Monash — the golden test's cheap-layer defence is broken"
    assert out is None


def test_T29b_parent_must_be_education_not_other_type():
    # path 3 rule: the associated parent must have type in EDUCATION_WHITELIST; a parent that is not education does not fold
    inst = {
        "openalex_id": "I777777777",
        "type": "facility",
        "lineage": ["https://openalex.org/I777777777"],
        "associated_institutions": [
            # a parent with type=government (it is not in the registry) -> no hit
            {"id": "https://openalex.org/I2801037857", "relationship": "parent", "type": "government"},
        ],
    }
    assert fold_to_canonical(inst, _registry_by_id()) is None


# ============ T30: a foreign education institution is present -> not None (self hit) ============

def test_T30_stockholm_foreign_inst_folds_non_none():
    # Yves Zenou's foreign institution Stockholm I161593684: it is itself education and in the registry -> path 1 self hit -> not None
    # keeps test_foreign_inst_folds_non_none_from_table from passing falsely + the coverage domain includes all foreign institutions
    stockholm = {
        "openalex_id": STOCKHOLM,
        "type": "education",
        "lineage": [f"https://openalex.org/{STOCKHOLM}"],
        "associated_institutions": [],
    }
    out = fold_to_canonical(stockholm, _registry_by_id())
    assert out is not None
    assert out == STOCKHOLM


def test_T30b_self_hit_returns_bare_id():
    # path 1: the institution's own openalex_id hits the registry -> returns the bare id (not the URL form)
    monash = _registry_by_id()[MONASH]
    out = fold_to_canonical(monash, _registry_by_id())
    assert out == MONASH
    assert not out.startswith("https://"), "must return a bare id without a URL prefix"


# ============ in_au_econ_dept reconciles only, not an identity authority ============

def test_in_au_econ_dept_membership_true():
    # canonical_id in econ_dept_ids → True
    econ = {MONASH, "I12345678"}
    assert in_au_econ_dept(MONASH, econ) is True


def test_in_au_econ_dept_membership_false():
    econ = {MONASH}
    assert in_au_econ_dept(STOCKHOLM, econ) is False


def test_in_au_econ_dept_none_sentinel_is_false():
    # the call site passes None (the sentinel PANEL_AFFIL_NONE has been turned into None) -> in no department -> False (no crash)
    econ = {MONASH}
    assert in_au_econ_dept(None, econ) is False


def test_in_au_econ_dept_empty_set_is_false():
    assert in_au_econ_dept(MONASH, set()) is False


# ============ fold_to_canonical is a pure function: does not modify its argument ============

def test_fold_to_canonical_does_not_mutate_inst():
    armi = {
        "openalex_id": ARMI,
        "type": "facility",
        "lineage": [f"https://openalex.org/{MONASH}"],
        "associated_institutions": [],
    }
    import copy
    snapshot = copy.deepcopy(armi)
    fold_to_canonical(armi, _registry_by_id())
    assert armi == snapshot, "fold_to_canonical modified its input inst — violates the pure-function rule"
