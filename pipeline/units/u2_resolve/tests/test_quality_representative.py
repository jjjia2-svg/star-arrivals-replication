"""U2 quality-representative diagnostic column (root-cause fix B, step 1) - TDD red tests.

New diagnostic column quality_representative_author_id: each cluster's representative is the member with the
highest cited_by_count among the members that are "field-consistent (the member's modal field is
economics OR equals the cluster's modal field) AND name-compatible".

Iron rules (same discipline as flag A, "detect only, never split automatically"):
  - Do not touch person_id / the min-id grouping / the 0.8 threshold / the clustering logic;
  - Pure diagnostic column, add only, change nothing - the existing 14 columns stay byte-identical;
  - Safe for Yves Zenou: the main id is already field-consistent and the most cited -> representative = main id, same as before.
"""
import pytest

from m2_resolve.gate import compute_cluster_purity, quality_representative

ECON = "2002"   # subfield_whitelist.include[0] (Economics and Econometrics)
MED = "2740"    # Any non-economics subfield (medicine)


def _purity(person_map, authors, works):
    return {r["person_id"]: r for r in compute_cluster_purity(person_map, authors, works)}


# ============ schema: 14 -> 15 columns ============

def test_schema_has_quality_representative_column():
    """CLUSTER_PURITY 14->15 columns: quality_representative_author_id (str) added;
    compute_cluster_purity puts that key in every row, row key set == schema key set (add only, change nothing)."""
    from common.schema import CLUSTER_PURITY

    assert "quality_representative_author_id" in CLUSTER_PURITY
    assert CLUSTER_PURITY["quality_representative_author_id"] == "str"
    person_map = [{"author_id": "Z1", "person_id": "P_Z"}]
    authors = [{"author_id": "Z1", "display_name": "Yves Zenou", "orcid": None}]
    works = [{"author_id": "Z1", "work_id": "W1", "subfield_id": ECON}]
    rows = compute_cluster_purity(person_map, authors, works)
    assert set(rows[0].keys()) == set(CLUSTER_PURITY.keys())


# ============ same-name fragment type: highly cited real person + empty fragment in one cluster ============

def test_namesake_fragment_type_picks_real_person_not_min_id_fragment():
    """Same-name fragment type: the min-id is an empty fragment with 0 citations, the real person (highly cited economist) is in the same cluster -> quality representative = the real person's id;
    person_id (min-id rule) stays byte-identical - diagnose only, never re-point."""
    person_map = [{"author_id": "A0001", "person_id": "P_A0001"},
                  {"author_id": "A0009", "person_id": "P_A0001"}]
    authors = [{"author_id": "A0001", "display_name": "R. Testname", "orcid": None},
               {"author_id": "A0009", "display_name": "Richard Testname", "orcid": None}]
    works = [
        {"author_id": "A0009", "work_id": "W1", "subfield_id": ECON, "cited_by_count": 900},
        {"author_id": "A0009", "work_id": "W2", "subfield_id": ECON, "cited_by_count": 2100},
    ]  # A0001 empty fragment: 0 works
    rows = compute_cluster_purity(person_map, authors, works)
    assert len(rows) == 1
    r = rows[0]
    assert r["person_id"] == "P_A0001"                       # min-id grouping unchanged
    assert r["quality_representative_author_id"] == "A0009"  # representative != min-id empty fragment


# ============ field gate ============

def test_field_gate_blocks_medical_namesake_despite_higher_citations():
    """Field-conflict cluster (the root of the same-name medical-id problem): cluster modal = economics, the same-name medical id has more citations but
    its modal field is neither economics nor equal to the cluster modal -> removed by the field gate, representative = the economics member."""
    person_map = [{"author_id": "AE", "person_id": "P_AE"},
                  {"author_id": "AM", "person_id": "P_AE"}]
    authors = [{"author_id": "AE", "display_name": "Robert Testname", "orcid": None},
               {"author_id": "AM", "display_name": "R. Testname", "orcid": None}]
    works = [
        {"author_id": "AE", "work_id": "W1", "subfield_id": ECON, "cited_by_count": 50},
        {"author_id": "AE", "work_id": "W2", "subfield_id": ECON, "cited_by_count": 60},
        {"author_id": "AM", "work_id": "W3", "subfield_id": MED, "cited_by_count": 99999},
    ]
    rows = compute_cluster_purity(person_map, authors, works)
    assert rows[0]["quality_representative_author_id"] == "AE"


def test_cluster_modal_branch_admits_dominant_field_member():
    """Rule pinned down: field-consistent = modal is economics **OR equals the cluster modal**.
    When the cluster modal is non-economics, a member of that field qualifies through the second branch (the most cited is chosen).
    NOTE: known conflict, needs manual review: such clusters are also sent to the human-review queue by the over-merge flag; the representative id is diagnostic only."""
    person_map = [{"author_id": "AK", "person_id": "P_AK"},
                  {"author_id": "AT", "person_id": "P_AK"}]
    authors = [{"author_id": "AK", "display_name": "Kate Example", "orcid": None},
               {"author_id": "AT", "display_name": "Kai Example", "orcid": None}]
    works = [
        {"author_id": "AK", "work_id": "W1", "subfield_id": ECON, "cited_by_count": 10},
        {"author_id": "AT", "work_id": "W2", "subfield_id": MED, "cited_by_count": 500},
        {"author_id": "AT", "work_id": "W3", "subfield_id": MED, "cited_by_count": 500},
    ]
    rows = compute_cluster_purity(person_map, authors, works)
    # cluster modal = MED (2 vs 1); AT qualifies via "equals the cluster modal" and has more citations -> chosen (as specified; the tension is noted above)
    assert rows[0]["quality_representative_author_id"] == "AT"


# ============ name gate ============

def test_name_gate_blocks_incompatible_name_member():
    """Name gate: a member with a different surname (merged in from golden_manual / dirty data) cannot be the representative however highly cited -
    names incompatible with most other members -> removed; representative = the most cited among the compatible members."""
    person_map = [{"author_id": "A1", "person_id": "P_A1"},
                  {"author_id": "A2", "person_id": "P_A1"},
                  {"author_id": "A3", "person_id": "P_A1"}]
    authors = [{"author_id": "A1", "display_name": "Jane Smith", "orcid": None},
               {"author_id": "A2", "display_name": "J. Smith", "orcid": None},
               {"author_id": "A3", "display_name": "Bob Jones", "orcid": None}]
    works = [
        {"author_id": "A1", "work_id": "W1", "subfield_id": ECON, "cited_by_count": 10},
        {"author_id": "A2", "work_id": "W2", "subfield_id": ECON, "cited_by_count": 5},
        {"author_id": "A3", "work_id": "W3", "subfield_id": ECON, "cited_by_count": 99999},
    ]
    rows = compute_cluster_purity(person_map, authors, works)
    assert rows[0]["quality_representative_author_id"] == "A1"


# ============ boundary: single-member cluster / empty cluster ============

def test_single_member_cluster_is_own_representative_even_without_works():
    """Single-member cluster: nothing to choose -> representative = the sole member itself (even with 0 works, the diagnostic column is not empty)."""
    person_map = [{"author_id": "S1", "person_id": "P_S1"}]
    authors = [{"author_id": "S1", "display_name": "Solo One", "orcid": None}]
    rows = compute_cluster_purity(person_map, authors, [])
    assert rows[0]["quality_representative_author_id"] == "S1"


def test_empty_multi_member_cluster_representative_none():
    """Empty cluster (several members, 0 works in the whole cluster -> zero field signal): never fake a representative -> None
    (mirrors the B2 fix principle "an all-missing column never passes as clean")."""
    person_map = [{"author_id": "E1", "person_id": "P_E1"},
                  {"author_id": "E2", "person_id": "P_E1"}]
    authors = [{"author_id": "E1", "display_name": "Empty Person", "orcid": None},
               {"author_id": "E2", "display_name": "E. Person", "orcid": None}]
    rows = compute_cluster_purity(person_map, authors, [])
    assert rows[0]["quality_representative_author_id"] is None


# ============ Yves Zenou case + determinism ============

def test_zenou_type_main_id_stays_representative():
    """Yves Zenou case: in a fragment cluster the main id (economics + most cited) is chosen; purity stays clean, existing columns untouched."""
    person_map = [{"author_id": "Z_FRAG1", "person_id": "P_Z"},
                  {"author_id": "Z_FRAG2", "person_id": "P_Z"},
                  {"author_id": "Z_MAIN", "person_id": "P_Z"}]
    authors = [{"author_id": "Z_MAIN", "display_name": "Yves Zenou", "orcid": None},
               {"author_id": "Z_FRAG1", "display_name": "Y. Zenou", "orcid": None},
               {"author_id": "Z_FRAG2", "display_name": "Y Zenou", "orcid": None}]
    works = [
        {"author_id": "Z_MAIN", "work_id": "W1", "subfield_id": ECON, "cited_by_count": 5000},
        {"author_id": "Z_MAIN", "work_id": "W2", "subfield_id": ECON, "cited_by_count": 4000},
        {"author_id": "Z_FRAG1", "work_id": "W3", "subfield_id": ECON, "cited_by_count": 3},
    ]
    rows = compute_cluster_purity(person_map, authors, works)
    r = rows[0]
    assert r["quality_representative_author_id"] == "Z_MAIN"
    assert r["purity_flag"] == "clean"                # existing verdicts unchanged
    assert r["topic_homogeneity"] == 1.0


def test_missing_cited_by_count_counts_zero_tie_breaks_min_author_id():
    """works lacks the cited_by_count key (old fixture / column not wired) -> counts as 0, affecting only the diagnostic ordering;
    ties -> deterministically take the smallest author_id (canonical-sort discipline)."""
    person_map = [{"author_id": "B2", "person_id": "P_B1"},
                  {"author_id": "B1", "person_id": "P_B1"}]
    authors = [{"author_id": "B1", "display_name": "Ann Lee", "orcid": None},
               {"author_id": "B2", "display_name": "A. Lee", "orcid": None}]
    works = [{"author_id": "B1", "work_id": "W1", "subfield_id": ECON},
             {"author_id": "B2", "work_id": "W2", "subfield_id": ECON}]
    rows = compute_cluster_purity(person_map, authors, works)
    assert rows[0]["quality_representative_author_id"] == "B1"


# ============ direct tests of the pure function ============

def test_quality_representative_pure_function_field_and_name_gates():
    """Direct test of the pure function: field gate + name gate + most-cited all apply together."""
    recs = [{"author_id": "R1", "display_name": "Jane Smith", "orcid": None},
            {"author_id": "R2", "display_name": "J. Smith", "orcid": None}]
    works_by_author = {
        "R1": [{"work_id": "W1", "subfield_id": ECON, "cited_by_count": 7}],
        "R2": [{"work_id": "W2", "subfield_id": ECON, "cited_by_count": 30}],
    }
    assert quality_representative(recs, works_by_author) == "R2"


def test_quality_representative_econ_injection():
    """econ_subfields is injectable (by default read from the RED subfield_whitelist.include)."""
    recs = [{"author_id": "R1", "display_name": "Jane Smith", "orcid": None},
            {"author_id": "R2", "display_name": "J. Smith", "orcid": None}]
    works_by_author = {
        "R1": [{"work_id": "W1", "subfield_id": "S_X", "cited_by_count": 7}],
        "R2": [{"work_id": "W2", "subfield_id": "S_Y", "cited_by_count": 3},
               {"work_id": "W3", "subfield_id": "S_Y", "cited_by_count": 3}],
    }
    # Inject S_X as "economics": R1 qualifies via the economics branch; R2 qualifies via the cluster-modal branch (S_Y 2 papers vs 1),
    # citation sum 6 < 7 -> R1 is chosen
    assert quality_representative(recs, works_by_author, econ_subfields={"S_X"}) == "R1"
