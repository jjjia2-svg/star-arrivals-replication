"""star_coauthored_works: the M5b exclusion set (cases #31-35 + #48b).

Definitions:
  - The delivery-set definition matches events: p01 <=> is_star_1pct AND is_foreign_poach /
    p05 <=> is_star_5pct AND is_foreign_poach (real data: all 28 people at 5pct, 12 with AND poach;
    the 16-person difference means the delivery definition really changes behavior);
  - star_set has a single source (keyed by author_id) -> folded to person_id via person_map (#2/C1,
    without importing is_star_coauthored);
  - exclusion set = {works whose signing person set intersects star_pids} (never walk along the coauthor graph, #35);
  - exclude the full history, star_coauthored_paper_alltime (#8): a different function from the dose side's coauthor_pre_arrival
    (frozen at t-1); they never reuse each other and their windows deliberately differ (#48b).
"""
from __future__ import annotations

import pathlib
import re

import pytest

from m5b_aggregate import star_coauthored_works as scw


# ---------------------------------------------------------------------------
# Delivery-definition folding (#31 + delivery set definition)
# ---------------------------------------------------------------------------
def test_star_person_ids_p01_p05_disjoint_columns(mk):
    """#31: A is 1% only, B is 5% only, C is both -> p01=={A,C}, p05=={A,B,C}; p10 -> raise."""
    stars = [
        mk.star("A_A", is_star_1pct=True, is_star_5pct=True),    # 1% (1%⊆5%)
        mk.star("A_B", is_star_1pct=False, is_star_5pct=True),   # 5% only
        mk.star("A_C", is_star_1pct=True, is_star_5pct=True),
    ]
    pm = [mk.pm("A_A", "P_A"), mk.pm("A_B", "P_B"), mk.pm("A_C", "P_C")]
    p01, n0 = scw.ship_star_person_ids(stars, pm, p_level="p01")
    p05, n1 = scw.ship_star_person_ids(stars, pm, p_level="p05")
    assert p01 == {"P_A", "P_C"} and p05 == {"P_A", "P_B", "P_C"}
    assert n0 == 0 and n1 == 0
    with pytest.raises(ValueError, match="p_level"):
        scw.ship_star_person_ids(stars, pm, p_level="p10")


def test_ship_caliber_requires_foreign_poach(mk):
    """Delivery-set definition = flag AND is_foreign_poach (same as events): a non-poached star does not enter the exclusion source."""
    stars = [
        mk.star("A_POACH", is_star_5pct=True, is_foreign_poach=True),
        mk.star("A_LOCAL", is_star_5pct=True, is_foreign_poach=False),  # Domestic star
        mk.star("A_NONE", is_star_5pct=True, is_foreign_poach=None),   # Thin circle None
    ]
    pm = [mk.pm("A_POACH", "P_POACH"), mk.pm("A_LOCAL", "P_LOCAL"),
          mk.pm("A_NONE", "P_NONE")]
    p05, _ = scw.ship_star_person_ids(stars, pm, p_level="p05")
    assert p05 == {"P_POACH"}


def test_flag_none_is_not_star(mk):
    """Thin circle None != True (schema [22]: those not in the pool are None); never treated as a star."""
    stars = [mk.star("A_X", is_star_5pct=None, is_foreign_poach=True)]
    pm = [mk.pm("A_X", "P_X")]
    p05, _ = scw.ship_star_person_ids(stars, pm, p_level="p05")
    assert p05 == set()


def test_unmapped_star_fragment_not_silently_dropped(mk):
    """#33: a star author_id missing from the person_map mapping -> counted + WARN, never used as a placeholder."""
    stars = [mk.star("A_S1"), mk.star("A_S2")]
    pm = [mk.pm("A_S1", "P_S1")]  # A_S2 has no mapping
    with pytest.warns(UserWarning, match="person_map"):
        pids, n_unmapped = scw.ship_star_person_ids(stars, pm, p_level="p05")
    assert pids == {"P_S1"}
    assert n_unmapped == 1
    assert "A_S2" not in pids  # Do not use author_id as a person_id placeholder


# ---------------------------------------------------------------------------
# Exclusion set star_coauthored_paper_alltime (#32/#34/#35 + exclude full history #8)
# ---------------------------------------------------------------------------
def test_coauthored_map_via_person_map(mk):
    """#32: two author fragments of a star fold into one person -> the coauthored works of each fragment all enter the exclusion set."""
    pm = [mk.pm("A_S", "P_S"), mk.pm("A_S_ALT", "P_S"), mk.pm("A_E", "P_E")]
    edges = [
        mk.edge("W1", "A_S", 2010), mk.edge("W1", "A_E", 2010),
        mk.edge("W2", "A_S_ALT", 2012), mk.edge("W2", "A_E", 2012),
        mk.edge("W3", "A_E", 2013),
    ]
    out = scw.star_coauthored_paper_alltime({"P_S"}, edges, pm)
    assert out == frozenset({"W1", "W2"})


def test_work_excluded_at_most_once(mk):
    """#34: one work attached to two stars -> the exclusion set is a frozenset and the work enters only once."""
    pm = [mk.pm("A_S1", "P_S1"), mk.pm("A_S2", "P_S2"), mk.pm("A_E", "P_E")]
    edges = [
        mk.edge("W_DUO", "A_S1", 2010), mk.edge("W_DUO", "A_S2", 2010),
        mk.edge("W_DUO", "A_E", 2010),
    ]
    out = scw.star_coauthored_paper_alltime({"P_S1", "P_S2"}, edges, pm)
    assert isinstance(out, frozenset)
    assert out == frozenset({"W_DUO"})


def test_first_order_only_not_graph_walk(mk):
    """#35: ego1 <-> star W_co, ego2 only <-> ego1 W_2hop -> the exclusion set is only {W_co} (catches a graph-walking mutant)."""
    pm = [mk.pm("A_S", "P_S"), mk.pm("A_E1", "P_E1"), mk.pm("A_E2", "P_E2")]
    edges = [
        mk.edge("W_co", "A_S", 2010), mk.edge("W_co", "A_E1", 2010),
        mk.edge("W_2hop", "A_E1", 2012), mk.edge("W_2hop", "A_E2", 2012),
    ]
    out = scw.star_coauthored_paper_alltime({"P_S"}, edges, pm)
    assert out == frozenset({"W_co"})
    assert "W_2hop" not in out


def test_alltime_no_year_cutoff(mk):
    """#8 exclude full history: works coauthored after the star arrives (any year) enter the exclusion set too, with no t-1 cutoff."""
    pm = [mk.pm("A_S", "P_S"), mk.pm("A_E", "P_E")]
    edges = [
        mk.edge("W_PRE", "A_S", 1999), mk.edge("W_PRE", "A_E", 1999),
        mk.edge("W_POST", "A_S", 2025), mk.edge("W_POST", "A_E", 2025),
    ]
    out = scw.star_coauthored_paper_alltime({"P_S"}, edges, pm)
    assert out == frozenset({"W_PRE", "W_POST"})


def test_unmapped_edge_author_counted_not_silent(mk):
    """Same as #33 (edge side): an author missing from the mapping in the edge table -> WARN + count, neither silent nor a placeholder."""
    pm = [mk.pm("A_S", "P_S")]
    edges = [
        mk.edge("W1", "A_S", 2010), mk.edge("W1", "A_GHOST", 2010),
    ]
    with pytest.warns(UserWarning):
        out = scw.star_coauthored_paper_alltime({"P_S"}, edges, pm)
    assert out == frozenset({"W1"})


def test_star_solo_paper_also_excluded(mk):
    """A star's solo work also counts as "a star in the author line" -> enters the exclusion set (the literal definition: signing set intersects star set is non-empty)."""
    pm = [mk.pm("A_S", "P_S")]
    edges = [mk.edge("W_SOLO", "A_S", 2010)]
    out = scw.star_coauthored_paper_alltime({"P_S"}, edges, pm)
    assert out == frozenset({"W_SOLO"})


# ---------------------------------------------------------------------------
# #48b the two windows deliberately differ + #2/C1 source guard
# ---------------------------------------------------------------------------
def test_degree1_dose_vs_exstar_use_distinct_named_windows(mk):
    """#48b: dose side coauthor_pre_arrival (frozen at t-1) vs output side alltime (exclude full history).

    Construct a star work after t-1: the dose side does not include that partner, while the output-side exclusion set
    includes the work, proving the two windows differ and each is correct; a source grep checks that both names are present.
    """
    from m4_dose import candidate_pairs

    pm = [mk.pm("A_S", "P_S"), mk.pm("A_E", "P_E")]
    edges = [mk.edge("W_LATE", "A_S", 2018), mk.edge("W_LATE", "A_E", 2018)]
    person_edges, _ = candidate_pairs.person_level_edges(edges, pm)

    partners = candidate_pairs.coauthor_pre_arrival(person_edges, "P_S", 2015)
    assert partners == set()                        # Dose side: 2018 > t-1 does not count
    out = scw.star_coauthored_paper_alltime({"P_S"}, edges, pm)
    assert out == frozenset({"W_LATE"})             # Output side: the full history is still excluded

    src_scw = pathlib.Path(scw.__file__).read_text(encoding="utf-8")
    src_cp = pathlib.Path(candidate_pairs.__file__).read_text(encoding="utf-8")
    assert "star_coauthored_paper_alltime" in src_scw
    assert "coauthor_pre_arrival" in src_cp
    # No reuse: the output-side module never imports or calls the dose-side window function, and vice versa (a mention in docs is allowed;
    # a call form = immediately followed by an opening parenthesis)
    assert not re.search(r"import.*coauthor_pre_arrival|coauthor_pre_arrival\(",
                         src_scw)
    assert not re.search(
        r"import.*star_coauthored_paper_alltime|star_coauthored_paper_alltime\(",
        src_cp)


def test_source_never_imports_is_star_coauthored():
    """#2/C1: the M5b exclusion set is derived from star_set; the source does not import the is_star_coauthored function."""
    src = pathlib.Path(scw.__file__).read_text(encoding="utf-8")
    assert not re.search(r"import.*\bis_star_coauthored\b", src)
    assert "star_rule" not in src
