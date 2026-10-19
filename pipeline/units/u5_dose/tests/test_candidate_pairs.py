"""candidate_pairs — red tests for candidate-pair enumeration (#2/#3/#4/#5; #8 dose-side named window).

degree-1 = direct co-authorship with the star; the dose side is judged by the named function coauthor_pre_arrival (frozen at t-1, #8)
— a different function from the output-side star_coauthored_paper_alltime (whole history excluded, M5b step 3), and the two are not reused for each other.
"""
from __future__ import annotations

import pytest

from m4_dose import candidate_pairs


def _person_edges(mk, pm_pairs, edge_triples):
    """authorship_edges (author level) + person_map -> person-level edges."""
    pm = [mk.pm(a, p) for a, p in pm_pairs]
    edges = [mk.edge(w, a, y) for w, a, y in edge_triples]
    person_edges, n_unmapped = candidate_pairs.person_level_edges(edges, pm)
    return person_edges, n_unmapped


def test_degree1_uses_person_not_author(mk):
    """#2: the same person's two author_ids fold to P_INC -> the degree-1 set returns {P_INC} once (person level, not author level)."""
    person_edges, _ = _person_edges(
        mk,
        pm_pairs=[("A_X1", "P_INC"), ("A_X2", "P_INC"), ("A_S", "P_STAR")],
        edge_triples=[
            ("W1", "A_X1", 2014), ("W1", "A_S", 2014),   # fragment 1 co-authored with the star
            ("W2", "A_X2", 2015), ("W2", "A_S", 2015),   # fragment 2 co-authored with the star
        ],
    )
    out = candidate_pairs.coauthor_pre_arrival(person_edges, "P_STAR", 2015)
    assert out == {"P_INC"}


def test_star_self_excluded(mk):
    """#3: candidate pair incumbent != star — a star never enters their own degree-1 set."""
    person_edges, _ = _person_edges(
        mk,
        pm_pairs=[("A_S", "P_STAR"), ("A_I", "P_I")],
        edge_triples=[("W1", "A_S", 2014), ("W1", "A_I", 2014)],
    )
    out = candidate_pairs.coauthor_pre_arrival(person_edges, "P_STAR", 2015)
    assert "P_STAR" not in out
    assert out == {"P_I"}


def test_coauthor_pre_arrival_frozen_to_t_minus_1(mk):
    """#8 dose-side window = frozen at t-1: co-authorship only in 2016 (> t-1=2015) -> not degree-1."""
    person_edges, _ = _person_edges(
        mk,
        pm_pairs=[("A_S", "P_STAR"), ("A_I", "P_I"), ("A_J", "P_J")],
        edge_triples=[
            ("W_pre", "A_S", 2014), ("W_pre", "A_I", 2014),   # co-authored before t-1 -> counts
            ("W_post", "A_S", 2016), ("W_post", "A_J", 2016), # co-authored after arrival -> does not count
        ],
    )
    out = candidate_pairs.coauthor_pre_arrival(person_edges, "P_STAR", 2015)
    assert out == {"P_I"}


@pytest.mark.depends_on_u4
def test_only_real_stars_p1(mk):
    """#4: p_level='p01' builds pairs only for stars with is_star_1pct=True (star_pids come from the fixed column mapping)."""
    person_edges, _ = _person_edges(
        mk,
        pm_pairs=[("A_S1", "P_S1"), ("A_S2", "P_S2"), ("A_I", "P_I")],
        edge_triples=[
            ("W1", "A_S1", 2014), ("W1", "A_I", 2014),
            ("W2", "A_S2", 2014), ("W2", "A_I", 2014),
        ],
    )
    events = [
        mk.event("E1", "P_S1", 2016, 2015),
        mk.event("E2", "P_S2", 2016, 2015),  # P_S2 is not in the p01 star set -> no pairs built
    ]
    rows = candidate_pairs.enumerate_degree1_pairs(
        events, star_pids={"P_S1"}, person_edges=person_edges
    )
    assert {(r["incumbent_person_id"], r["star_person_id"], r["event_id"]) for r in rows} \
        == {("P_I", "P_S1", "E1")}
    assert all(r["degree"] == 1 for r in rows)


@pytest.mark.depends_on_u4
def test_t_minus_1_read_not_recomputed(mk):
    """#1: candidate-pair rows read t_minus_1 directly from events.t_minus_1 and never compute arrival-1.

    Poisoned fixture: arrival_year=2016 but t_minus_1=2013 (the source of truth deliberately != arrival-1)
    -> the row must carry 2013 (if an implementation quietly computes arrival-1=2015, this test catches it).
    """
    person_edges, _ = _person_edges(
        mk,
        pm_pairs=[("A_S", "P_STAR"), ("A_I", "P_I")],
        edge_triples=[("W1", "A_S", 2012), ("W1", "A_I", 2012)],
    )
    events = [mk.event("E1", "P_STAR", 2016, 2013)]
    rows = candidate_pairs.enumerate_degree1_pairs(
        events, star_pids={"P_STAR"}, person_edges=person_edges
    )
    assert len(rows) == 1
    assert rows[0]["t_minus_1"] == 2013


def test_bounded_no_global_cross(mk):
    """#5: 10 stars x 5 degree-1 collaborators each -> exactly 50 rows, not a global Cartesian product (500 rows)."""
    pm_pairs, edge_triples, events, star_pids = [], [], [], set()
    for s in range(10):
        star_a, star_p = f"A_S{s}", f"P_S{s}"
        pm_pairs.append((star_a, star_p))
        star_pids.add(star_p)
        events.append((f"E{s}", star_p))
        for i in range(5):
            inc_a, inc_p = f"A_I{s}_{i}", f"P_I{s}_{i}"
            pm_pairs.append((inc_a, inc_p))
            w = f"W{s}_{i}"
            edge_triples += [(w, star_a, 2014), (w, inc_a, 2014)]
    person_edges, _ = _person_edges(mk, pm_pairs, edge_triples)
    event_rows = [mk.event(eid, sp, 2016, 2015) for eid, sp in events]
    rows = candidate_pairs.enumerate_degree1_pairs(
        event_rows, star_pids=star_pids, person_edges=person_edges
    )
    assert len(rows) == 50  # each star pairs only with their own 5 collaborators, never a full 10x50 cross


def test_unmapped_edge_author_counted_not_silent(mk):
    """An edge-table author_id with no person_map mapping -> counted + WARN (not silently dropped) — the same discipline as #33, on the edge side."""
    pm = [mk.pm("A_KNOWN", "P_K")]
    edges = [mk.edge("W1", "A_KNOWN", 2014), mk.edge("W1", "A_GHOST", 2014)]
    with pytest.warns(UserWarning, match="unmapped"):
        person_edges, n_unmapped = candidate_pairs.person_level_edges(edges, pm)
    assert n_unmapped == 1
    assert {r["person_id"] for r in person_edges} == {"P_K"}
