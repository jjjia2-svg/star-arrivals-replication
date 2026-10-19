"""m4_dose/candidate_pairs.py - candidate pair enumeration.

Produces bounded candidate pairs (incumbent_person_id, star_person_id, event_id, t_minus_1, degree):
  - degree-1 test = **coauthor_pre_arrival** (a named function; the dose-side window = frozen at t-1):
    it is a **different concept and a different function** from the output-side
    `star_coauthored_paper_alltime` (full-history exclusion, M5b), and **the two never reuse each other** - the two
    windows deliberately differ (guarded by a test).
  - t_minus_1 is **read directly from events.t_minus_1**, never computed as arrival_year-1
    (the single source of truth for the freeze point is EVENTS).
  - Pairs are built only for true stars: star_pids is folded by io_load.fold_star_person_ids with the pinned
    column mapping (p01 ⟺ is_star_1pct); events whose star is not in the star set are skipped.
  - Bounded: pairs come only along real co-authorship edges, **the global all-pairs set is never materialised**.
  - Person level: authorship_edges (author_id) are first folded to person_id via person_map;
    edges whose author has no mapping are counted + WARN, never silent.
  - Truncation always goes through cutoff.filter_works_until (the single truncation entry, verified by a spy test).
degree-2 rows are closed by degree2_closure and merged in run_dose (degree-1 takes priority in dedup).
"""
from __future__ import annotations

import warnings

from . import cutoff


def person_level_edges(authorship_edges, person_map_rows):
    """Author-level edges -> person-level edges {work_id, person_id, publication_year}.

    Edges whose author has no person_map mapping: counted + UserWarning (not silently dropped, no author_id used as
    a placeholder), and removed from the person-level graph (cannot be attributed to a person = cannot form a pair).
    Returns (person_edges: list[dict], n_unmapped: int).
    """
    pid_by_author = {r["author_id"]: r["person_id"] for r in person_map_rows}
    person_edges: list[dict] = []
    unmapped: set[str] = set()
    for e in authorship_edges:
        pid = pid_by_author.get(e["author_id"])
        if pid is None:
            unmapped.add(e["author_id"])
            continue
        person_edges.append({
            "work_id": e["work_id"],
            "person_id": pid,
            "publication_year": e["publication_year"],
        })
    if unmapped:
        warnings.warn(
            f"person_level_edges: {len(unmapped)} edge-table author_ids have no person_map mapping "
            f"(unmapped, not silent): {sorted(unmapped)[:5]}",
            UserWarning,
            stacklevel=2,
        )
    return person_edges, len(unmapped)


def coauthor_pre_arrival(person_edges, star_pid: str, t_minus_1: int) -> set:
    """Dose-side degree-1 test (named window): the set of persons who co-authored directly with the star up to t-1.

    Window = frozen at the year before arrival (inclusive), via the single truncation entry
    cutoff.filter_works_until; guards against endogenous selection (co-authorship that only builds up after
    arrival does not count as dose-side closeness).
    ⚠️ A different function from the output-side star_coauthored_paper_alltime (full-history exclusion); they are
    not reused. The star never enters the returned set.
    """
    frozen = cutoff.filter_works_until(person_edges, t_minus_1)
    star_works = {r["work_id"] for r in frozen if r["person_id"] == star_pid}
    partners = {
        r["person_id"]
        for r in frozen
        if r["work_id"] in star_works and r["person_id"] != star_pid
    }
    return partners


def enumerate_degree1_pairs(events, star_pids, person_edges) -> list:
    """Enumerate degree-1 candidate pair rows per event (bounded, not Cartesian).

    Each row: {incumbent_person_id, star_person_id, event_id, t_minus_1, degree=1}
      - event.star_person_id not in star_pids -> the whole event is skipped (pairs only for true stars);
      - t_minus_1 = event["t_minus_1"] read directly (not computed);
      - incumbent = coauthor_pre_arrival(...) (the star itself is already excluded).
    Returns rows sorted by (event_id, incumbent) (deterministic).
    """
    rows: list[dict] = []
    for ev in events:
        star = ev["star_person_id"]
        if star not in star_pids:
            continue
        t_minus_1 = ev["t_minus_1"]  # read directly, never arrival_year-1
        for inc in sorted(coauthor_pre_arrival(person_edges, star, t_minus_1)):
            rows.append({
                "incumbent_person_id": inc,
                "star_person_id": star,
                "event_id": ev["event_id"],
                "t_minus_1": t_minus_1,
                "degree": 1,
            })
    rows.sort(key=lambda r: (r["event_id"], r["incumbent_person_id"]))
    return rows
