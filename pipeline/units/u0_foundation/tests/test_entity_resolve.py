"""TDD red tests for U0 common/entity_resolve.py (core pure functions of U2 disambiguation; U0 provides the signatures).

Guards C.8, the schema, and the redlines entity_resolve section:
  - pair_score(...)            incompatible names -> None (otherwise a compatibility score).
  - cluster_block(...)         ORCID hard seed + order independence (the same records in a different order give the same clustering).
  - affil_conflict(a, b)->bool uses AFFIL_CONFLICT_CUTOFF (the export must be confirmed).
  - SCORE_THRESHOLD / HOMOGENEITY_MIN / COMPLETENESS_MIN = None (unset placeholders);
    a function that meets None -> raise (never a silent default).

Plain words:
  - Disambiguation = correctly assigning same-name different people / same person different records to one real person.
  - pair_score: how alike two author records are (0~1). If the names are not compatible at all (different surnames / conflicting initials) -> None,
    no comparison at all, and never a forced 0 that leaves it a chance of being merged.
  - cluster_block: clusters the records inside one block (a same-name block). ORCID is a hard seed: records with the same real ORCID
    must merge. But an empty/missing ORCID is not a seed (Yves Zenou has no ORCID in OpenAlex, had_orcid=False;
    seeding a field that does not exist goes down the wrong path and makes tests pass falsely, so this is pinned as rule #11-a). Order independence: reorder the records and the clustering is unchanged.
  - affil_conflict: whether the institution strings of two records strongly conflict (judged with an unset cutoff threshold).

Rule: the identification thresholds (score_threshold/homogeneity_min/completeness_min) are all null placeholders in redlines.yaml
that a human must fill in. These tests assert only "meets None -> raise" and never assert a concrete threshold value.

These tests are purely local, with no network and no data fetching (disambiguation scoring/clustering are pure functions; feed them record dicts).
"""
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common.entity_resolve import (  # noqa: E402
    affil_conflict,
    cluster_block,
    pair_score,
)
from common._redlines import RedlineUnsigned  # noqa: E402


# ===========================================================================
# Group A: pair_score: incompatible names -> None (C.8)
# ===========================================================================

def test_pair_score_incompatible_names_returns_none():
    # C.8: names that are not compatible at all (different surnames) -> None, not even a score (never a forced 0 that leaves a chance of merging)
    a = {"display_name": "John Smith", "orcid": "", "raw_affil": "MIT"}
    b = {"display_name": "Jane Doe", "orcid": "", "raw_affil": "MIT"}
    assert pair_score(a, b) is None


def test_pair_score_incompatible_first_initial_returns_none():
    # same surname but conflicting first initials (J. vs R.) -> incompatible names -> None
    a = {"display_name": "John Smith", "orcid": "", "raw_affil": "MIT"}
    b = {"display_name": "Robert Smith", "orcid": "", "raw_affil": "MIT"}
    assert pair_score(a, b) is None


def test_pair_score_compatible_names_returns_number_not_none():
    # compatible names (same person, different spellings: full name vs initial) -> returns a float score, not None
    a = {"display_name": "John Smith", "orcid": "", "raw_affil": "MIT"}
    b = {"display_name": "J. Smith", "orcid": "", "raw_affil": "MIT"}
    score = pair_score(a, b)
    assert score is not None
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


def test_pair_score_identical_records_high_score():
    # two identical records -> compatible, the score should be high (not None)
    a = {"display_name": "John Smith", "orcid": "", "raw_affil": "MIT"}
    score = pair_score(a, dict(a))
    assert score is not None
    assert score > 0.5


# ===========================================================================
# Group B: cluster_block: ORCID hard seed + order independence (C.8)
# ===========================================================================

def _records_two_orcid_groups():
    # Two real ORCIDs, 2 records each; ORCID is a hard seed -> records with the same ORCID must merge.
    return [
        {"author_id": "A1", "display_name": "John Smith", "orcid": "0000-0001-0000-0001", "raw_affil": "MIT"},
        {"author_id": "A2", "display_name": "J. Smith", "orcid": "0000-0001-0000-0001", "raw_affil": "MIT"},
        {"author_id": "A3", "display_name": "John Smith", "orcid": "0000-0002-0000-0002", "raw_affil": "Stanford"},
        {"author_id": "A4", "display_name": "John Smith", "orcid": "0000-0002-0000-0002", "raw_affil": "Stanford"},
    ]


def _clusters_as_frozensets(labels: dict) -> set:
    # labels: author_id -> cluster_label; normalised to a "by member set" form, independent of label naming.
    by_cluster: dict = {}
    for author_id, lbl in labels.items():
        by_cluster.setdefault(lbl, set()).add(author_id)
    return {frozenset(v) for v in by_cluster.values()}


def test_cluster_block_orcid_hard_seed_merges_same_orcid():
    # C.8: records with the same real ORCID must merge (hard seed)
    labels = cluster_block(_records_two_orcid_groups())
    clusters = _clusters_as_frozensets(labels)
    assert frozenset({"A1", "A2"}) in clusters   # the two records with ORCID ...0001 merge
    assert frozenset({"A3", "A4"}) in clusters   # the two records with ORCID ...0002 merge


def test_cluster_block_order_independent():
    # C.8: reordering the records leaves the clustering (by member set) unchanged: order independence
    recs = _records_two_orcid_groups()
    labels_forward = cluster_block(recs)
    labels_reverse = cluster_block(list(reversed(recs)))
    assert _clusters_as_frozensets(labels_forward) == _clusters_as_frozensets(labels_reverse)


def test_cluster_block_order_independent_shuffled():
    # another order (swap in the middle) still gives the same clustering
    recs = _records_two_orcid_groups()
    shuffled = [recs[2], recs[0], recs[3], recs[1]]
    base = _clusters_as_frozensets(cluster_block(recs))
    assert _clusters_as_frozensets(cluster_block(shuffled)) == base


def test_cluster_block_empty_orcid_is_not_a_seed():
    # Rule #11-a: an empty ORCID is not a hard seed (Yves Zenou: had_orcid=False).
    # Two records with empty ORCIDs must not be force-merged as one seed "because both ORCIDs are the empty string".
    recs = [
        {"author_id": "B1", "display_name": "John Smith", "orcid": "", "raw_affil": "MIT"},
        {"author_id": "B2", "display_name": "John Smith", "orcid": "", "raw_affil": "Tokyo Univ"},
    ]
    labels = cluster_block(recs)
    # They are not required to be separate (scoring/affil decides that), only: they are not hard-seed merged "because the empty ORCIDs are equal".
    # Use strongly conflicting institutions (MIT vs Tokyo): names compatible but affil conflicts, an empty ORCID does not seed -> should stay separate.
    clusters = _clusters_as_frozensets(labels)
    assert frozenset({"B1", "B2"}) not in clusters


def test_cluster_block_none_orcid_is_not_a_seed():
    # orcid=None is likewise not a hard seed (same as the empty string: a missing field seeds nothing)
    recs = [
        {"author_id": "C1", "display_name": "John Smith", "orcid": None, "raw_affil": "MIT"},
        {"author_id": "C2", "display_name": "John Smith", "orcid": None, "raw_affil": "Tokyo Univ"},
    ]
    labels = cluster_block(recs)
    clusters = _clusters_as_frozensets(labels)
    assert frozenset({"C1", "C2"}) not in clusters


def test_cluster_block_returns_label_per_author_id():
    # output contract: every record's author_id gets a cluster label (nobody is dropped)
    recs = _records_two_orcid_groups()
    labels = cluster_block(recs)
    assert set(labels.keys()) == {"A1", "A2", "A3", "A4"}


# ===========================================================================
# Group C: affil_conflict(a, b) -> bool: uses the cutoff threshold (C.8)
# ===========================================================================

def test_affil_conflict_returns_bool():
    # C.8: affil_conflict returns a bool
    out = affil_conflict("Massachusetts Institute of Technology", "MIT")
    assert isinstance(out, bool)


def test_affil_conflict_same_institution_no_conflict():
    # the same institution written differently -> no conflict (False)
    assert affil_conflict("Monash University", "Monash University") is False


def test_affil_conflict_clearly_different_institutions_conflict():
    # clearly different institutions (different countries, different names) -> conflict (True)
    assert affil_conflict("Monash University Melbourne Australia",
                          "University of Tokyo Japan") is True


# ===========================================================================
# Group D: unset placeholder thresholds None -> raise (C.8, unset-threshold rule)
# ===========================================================================

def test_thresholds_are_none_placeholders():
    # the three identification thresholds are None placeholders at module level (unset; a human fills them in)
    import common.entity_resolve as er
    assert er.SCORE_THRESHOLD is None
    assert er.HOMOGENEITY_MIN is None
    assert er.COMPLETENESS_MIN is None


def test_score_threshold_getter_returns_signed_value():
    # Q5 = 0.8 (calibrated on real data: a cliff at 0.75, the equivalence band [0.75,1.00] taken at its middle): the getter returns this value
    from common.entity_resolve import require_score_threshold
    assert require_score_threshold() == 0.8


def test_homogeneity_min_getter_raises_when_unsigned():
    from common.entity_resolve import require_homogeneity_min
    with pytest.raises(RedlineUnsigned):
        require_homogeneity_min()


def test_completeness_min_getter_raises_when_unsigned():
    from common.entity_resolve import require_completeness_min
    with pytest.raises(RedlineUnsigned):
        require_completeness_min()


def test_accept_pair_uses_signed_threshold():
    # With Q5 = 0.8: same full name + same institution (score=1.0>=0.8) -> accept; different names with compatible initials only (score≈0.3<0.8) -> reject
    from common.entity_resolve import accept_pair
    a = {"display_name": "John Smith", "orcid": "", "raw_affil": "MIT"}
    same = {"display_name": "John Smith", "orcid": "", "raw_affil": "MIT"}
    diff_given = {"display_name": "Jane Smith", "orcid": "", "raw_affil": "MIT"}
    assert accept_pair(a, same) is True
    assert accept_pair(a, diff_given) is False


def test_cluster_block_soft_edge_respects_signed_threshold():
    """Q5 = 0.8 must be used in production clustering (lesson from calibration on real data):
    same surname, different given names, same-university institution (in a two-university population
    the affil_conflict defence fails: everyone shares the university token)
    -> never soft-link (below the threshold). Prevents the disastrous false merge of 63 people sharing one common name abbreviation into 1."""
    from common.entity_resolve import cluster_block
    recs = [
        {"author_id": "A1", "display_name": "Wei Chen", "orcid": None,
         "raw_affil": ["Department of Economics, Monash University"]},
        {"author_id": "A2", "display_name": "Wen Chen", "orcid": None,
         "raw_affil": ["Monash Business School, Monash University"]},
    ]
    labels = cluster_block(recs)
    assert labels["A1"] != labels["A2"], "same surname with a different given name must not be soft-linked on 'no institution conflict' (threshold 0.8 not met)"


def test_cluster_block_full_name_match_still_merges_at_signed_threshold():
    """At 0.8, the same full name + compatible institution (score=1.0) still merges: the Yves Zenou fragment scenario is unaffected."""
    from common.entity_resolve import cluster_block
    recs = [
        {"author_id": "B1", "display_name": "Yves Zenou", "orcid": None,
         "raw_affil": ["Department of Economics, Monash University"]},
        {"author_id": "B2", "display_name": "Yves Zénou", "orcid": None,
         "raw_affil": ["Monash University"]},
    ]
    labels = cluster_block(recs)
    assert labels["B1"] == labels["B2"]
