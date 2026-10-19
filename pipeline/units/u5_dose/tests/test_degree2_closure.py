"""degree2_closure — red tests for degree-2 two-hop closure (#7b/#8/#9/#10/#11/#12/#13).

#5 (strict two-sided freeze): a degree-2 channel i<->MID<->star counts as a frozen channel only if both bridge edges exist before t-1;
if either bridge edge forms only after arrival -> the channel's main dose is recorded as 0, degree2_bridge_frozen=False, and it enters only the post-arrival robustness checks.
"""
from __future__ import annotations

import pathlib

import pytest

from m4_dose import candidate_pairs, degree2_closure


def _pedges(mk, triples):
    """triples: (work_id, person_id, year) -> person-level edges (skips author folding, given directly as person)."""
    return [{"work_id": w, "person_id": p, "publication_year": y} for w, p, y in triples]


def _db(tmp_path) -> pathlib.Path:
    return tmp_path / "deg2.db"


_CAPS = dict(cap_k=50, cap_per_star=100)


def test_refuses_memory_db(tmp_path, mk):
    """#8: ':memory:' -> raise — degree-2 needs a persistent .db that can spill, preventing the old OOM defect."""
    edges = _pedges(mk, [("W1", "P_I", 2014), ("W1", "P_M", 2014)])
    with pytest.raises(ValueError):
        degree2_closure.close_degree2(
            ":memory:", edges, "P_STAR", 2015, exclude_pids=set(), **_CAPS
        )


def test_degree2_edges_must_predate_t_minus_1(tmp_path, mk):
    """#7b (#5, hard test): star-side bridge edge 2017 > t-1=2015 -> the channel does not close as frozen,
    the row is still produced but degree2_bridge_frozen=False (the main dose is then recorded as 0); both edges <=2015 -> True.
    """
    # Scenario A: i<->MID 2015 (frozen), MID<->star 2017 (after arrival) -> frozen=False
    edges_a = _pedges(mk, [
        ("W_IM", "P_I", 2015), ("W_IM", "P_MID", 2015),
        ("W_MS", "P_MID", 2017), ("W_MS", "P_STAR", 2017),
    ])
    out_a = degree2_closure.close_degree2(
        _db(tmp_path), edges_a, "P_STAR", 2015, exclude_pids=set(), **_CAPS
    )
    assert [(r["incumbent_person_id"], r["degree2_bridge_frozen"]) for r in out_a] \
        == [("P_I", False)]

    # Scenario B: both bridge edges <= 2015 -> closes normally, frozen=True
    edges_b = _pedges(mk, [
        ("W_IM", "P_I", 2014), ("W_IM", "P_MID", 2014),
        ("W_MS", "P_MID", 2015), ("W_MS", "P_STAR", 2015),
    ])
    out_b = degree2_closure.close_degree2(
        _db(tmp_path / "b"), edges_b, "P_STAR", 2015, exclude_pids=set(), **_CAPS
    )
    assert [(r["incumbent_person_id"], r["degree2_bridge_frozen"]) for r in out_b] \
        == [("P_I", True)]


def test_degree2_only_closed(tmp_path, mk):
    """#10: P_INC2 is connected to the star only through P_MID in two hops (both bridge edges <= t-1) -> closure returns P_INC2."""
    edges = _pedges(mk, [
        ("W1", "P_INC2", 2013), ("W1", "P_MID", 2013),   # inc2 ↔ mid
        ("W2", "P_MID", 2014), ("W2", "P_STAR", 2014),   # mid ↔ star
    ])
    out = degree2_closure.close_degree2(
        _db(tmp_path), edges, "P_STAR", 2015, exclude_pids=set(), **_CAPS
    )
    incs = {r["incumbent_person_id"] for r in out}
    assert incs == {"P_INC2"}  # the two-hop closure yields only INC2; MID is degree-1 (intermediary != star, no self-loop)


def test_degree1_priority_dedup_via_exclude(tmp_path, mk):
    """H2 degree-1 first: a person already directly linked at degree 1 goes into exclude_pids -> no degree-2 row is produced (precondition of #27b)."""
    edges = _pedges(mk, [
        ("W1", "P_INC2", 2013), ("W1", "P_MID", 2013),
        ("W2", "P_MID", 2014), ("W2", "P_STAR", 2014),
    ])
    deg1 = candidate_pairs.coauthor_pre_arrival(edges, "P_STAR", 2015)
    assert deg1 == {"P_MID"}
    out = degree2_closure.close_degree2(
        _db(tmp_path), edges, "P_STAR", 2015, exclude_pids=deg1, **_CAPS
    )
    assert {r["incumbent_person_id"] for r in out} == {"P_INC2"}  # MID is excluded by de-duplication


def test_authorship_edges_is_full_not_seed_incident(tmp_path, mk):
    """#9: closure relies on the **full edge table** — the intermediary<->star edges must also be in the table; given only the seed-incident subset it misses them."""
    full = _pedges(mk, [
        ("W1", "P_INC2", 2013), ("W1", "P_MID", 2013),
        ("W2", "P_MID", 2014), ("W2", "P_STAR", 2014),
    ])
    seed_only = [e for e in full if e["work_id"] == "W1"]  # keep only edges touching an incumbent -> the bridge breaks
    out_full = degree2_closure.close_degree2(
        _db(tmp_path / "f"), full, "P_STAR", 2015, exclude_pids={"P_MID"}, **_CAPS
    )
    out_seed = degree2_closure.close_degree2(
        _db(tmp_path / "s"), seed_only, "P_STAR", 2015, exclude_pids={"P_MID"}, **_CAPS
    )
    assert {r["incumbent_person_id"] for r in out_full} == {"P_INC2"}
    assert out_seed == []  # the seed-incident subset cannot close -> proves the full edge table must be fed


def test_no_cartesian_blowup_and_bounded_per_star(tmp_path, mk):
    """#11: cap_k degree cap + per-star incumbent cap -> the set is bounded.

    hub mid (degree > cap_k) is dropped -> incumbents connected only through the hub do not appear;
    cap_per_star=3 -> at most 3 degree-2 rows per star.
    """
    triples = []
    # hub mid: linked to the star + linked to 20 incumbents (degree 21 > cap_k=5) -> all dropped
    triples += [("W_HS", "P_HUB", 2014), ("W_HS", "P_STAR", 2014)]
    for i in range(20):
        triples += [(f"W_H{i}", "P_HUB", 2014), (f"W_H{i}", f"P_HI{i}", 2014)]
    # normal mid: linked to the star + linked to 5 incumbents (degree 6 <= cap_k... 5+star=6 -> use cap_k=8)
    triples += [("W_NS", "P_NORM", 2014), ("W_NS", "P_STAR", 2014)]
    for i in range(5):
        triples += [(f"W_N{i}", "P_NORM", 2014), (f"W_N{i}", f"P_NI{i}", 2014)]
    edges = _pedges(mk, triples)

    out = degree2_closure.close_degree2(
        _db(tmp_path), edges, "P_STAR", 2015,
        exclude_pids={"P_HUB", "P_NORM"}, cap_k=8, cap_per_star=3,
    )
    incs = {r["incumbent_person_id"] for r in out}
    assert len(out) <= 3                                   # per-star cap
    assert not any(i.startswith("P_HI") for i in incs)     # all hub paths dropped (cap_k)
    assert incs <= {f"P_NI{i}" for i in range(5)}


def test_cap_k_cut_is_deterministic(tmp_path, mk):
    """#12: tie total order (year DESC, person ASC) -> the surviving pair set is identical run to run.

    Two incumbents with the same evidence year and cap_per_star=1 -> the survivor is always the person_id that sorts first ascending.
    """
    edges = _pedges(mk, [
        ("W_A", "P_AAA", 2014), ("W_A", "P_MID", 2014),
        ("W_B", "P_BBB", 2014), ("W_B", "P_MID", 2014),
        ("W_S", "P_MID", 2014), ("W_S", "P_STAR", 2014),
    ])
    survivors = []
    for run in range(2):
        out = degree2_closure.close_degree2(
            _db(tmp_path / f"r{run}"), edges, "P_STAR", 2015,
            exclude_pids={"P_MID"}, cap_k=50, cap_per_star=1,
        )
        survivors.append(tuple(r["incumbent_person_id"] for r in out))
    assert survivors[0] == survivors[1] == ("P_AAA",)  # same-year tie -> the ASC-smallest


def test_forbid_list_aggregate():
    """#13: the degree2_closure source string contains neither `list(` nor `string_agg(` — an aggregate that cannot spill will blow up."""
    src = pathlib.Path(degree2_closure.__file__).read_text(encoding="utf-8")
    assert "string_agg(" not in src
    assert "list(" not in src


def test_degree2_goes_through_single_cutoff(tmp_path, mk, monkeypatch):
    """#7 (degree-2 side): the bridge-edge frozen test goes through the single entry point cutoff.filter_works_until (spy)."""
    from m4_dose import cutoff as cutoff_mod

    seen = []
    real = cutoff_mod.filter_works_until

    def spy(rows, t):
        seen.append(t)
        return real(rows, t)

    monkeypatch.setattr(cutoff_mod, "filter_works_until", spy)
    edges = _pedges(mk, [
        ("W1", "P_I", 2013), ("W1", "P_MID", 2013),
        ("W2", "P_MID", 2014), ("W2", "P_STAR", 2014),
    ])
    degree2_closure.close_degree2(
        _db(tmp_path), edges, "P_STAR", 2015, exclude_pids=set(), **_CAPS
    )
    assert seen and set(seen) == {2015}  # the frozen test goes entirely through the single truncation entry point, with the same t-1
