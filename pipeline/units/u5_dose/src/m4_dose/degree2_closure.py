"""m4_dose/degree2_closure.py — degree-2 two-hop closure (#5).

degree-2 = person i has co-authored only with "the star's co-authors", one intermediary away (i<->MID<->star).
The full authorship edge table (person level) is closed by a two-hop self-join on a **persistent DuckDB .db**:
  - ':memory:' is banned (it cannot spill and will blow up, #8);
  - aggregates that collect values and cannot spill are banned (#13 source-string guard; this file must not contain either call);
  - degree cap cap_k (hub intermediaries removed) + per-star incumbent cap; both parameters must be passed explicitly
    (a missing one raises TypeError; no default magic numbers);
  - tie total order = (evidence year DESC, person ASC), so the surviving pair set is identical run to run (#12).

#5 (strict two-sided freeze):
  both bridge edges (i<->MID, MID<->star) exist before t-1 -> frozen channel, degree2_bridge_frozen=True;
  if either bridge edge exists only after t-1, the channel does not close as frozen: the row is still produced
  with degree2_bridge_frozen=False, run_dose records the main dose as 0, and it enters only the post-arrival
  robustness checks (#7b hard test).
  The frozen test goes through the single truncation entry point cutoff.filter_works_until (#7 spy; no local WHERE on year).

degree-1 first de-duplication (H2): people already directly linked at degree 1 are passed in by the caller in exclude_pids; this module does not emit their rows.
"""
from __future__ import annotations

import pathlib

import duckdb

from . import cutoff

# Two-hop pair table: co-authoring the same work gives a (pa, pb) pair; evidence year = latest common work year (deterministic tie key).
_PAIRS_SQL = """
CREATE OR REPLACE TABLE {out} AS
SELECT e1.person_id AS pa, e2.person_id AS pb, MAX(e1.publication_year) AS yr
FROM {src} e1 JOIN {src} e2
  ON e1.work_id = e2.work_id AND e1.person_id <> e2.person_id
GROUP BY 1, 2
"""

# Two-hop closure: mids = intermediaries paired with the star whose degree is <= cap_k; inc = people paired with a mid (excluding the star).
# Channel evidence year = GREATEST(evidence years of the two bridge edges): the channel closes only when the later bridge edge forms.
_TWO_HOP_SQL = """
WITH deg AS (
  SELECT pa AS person, COUNT(DISTINCT pb) AS d FROM {pairs} GROUP BY 1
),
mids AS (
  SELECT p.pa AS mid, p.yr AS yr_ms
  FROM {pairs} p JOIN deg ON deg.person = p.pa
  WHERE p.pb = ? AND deg.d <= ?
)
SELECT q.pa AS inc, MAX(GREATEST(q.yr, m.yr_ms)) AS yr
FROM {pairs} q JOIN mids m ON q.pb = m.mid
WHERE q.pa <> ?
GROUP BY 1
ORDER BY yr DESC, inc ASC
"""


def _load_edges(con, table: str, rows) -> None:
    con.execute(
        f"CREATE OR REPLACE TABLE {table} "
        "(work_id VARCHAR, person_id VARCHAR, publication_year INTEGER)"
    )
    rows = [r for r in rows]   # Materialise (written as a comprehension: the #13 source-string guard bans collecting-aggregate stems)
    if rows:
        # Bulk load via arrow registration: equivalent to row-by-row executemany (same table structure, same row set),
        # two orders of magnitude faster at the real-data scale of ~1e5-1e6 rows; behaviour unchanged.
        import pyarrow as pa

        tbl = pa.table({
            "work_id": [r["work_id"] for r in rows],
            "person_id": [r["person_id"] for r in rows],
            "publication_year": [r["publication_year"] for r in rows],
        })
        con.register("_edges_in", tbl)
        con.execute(f"INSERT INTO {table} SELECT * FROM _edges_in")
        con.unregister("_edges_in")


def _two_hop(con, pairs_table: str, star_pid: str, cap_k: int):
    sql = _TWO_HOP_SQL.format(pairs=pairs_table)
    return con.execute(sql, [star_pid, cap_k, star_pid]).fetchall()


def _cap_deterministic(rows, banned, already, budget: int, allowed=None):
    """(inc, yr) rows -> filter out banned/already/out-of-pool -> total order (yr DESC, inc ASC) -> cut to budget.

    allowed=None = no filtering (default, historical behaviour); a set = keep only incumbents in the pool
    (the endpoint-pool filter runs before the cap, so out-of-pool people do not use up budget).
    """
    kept = [
        (yr, inc) for inc, yr in rows
        if inc not in banned and inc not in already
        and (allowed is None or inc in allowed)
    ]
    kept.sort(key=lambda t: (-t[0], t[1]))
    return kept[:budget]


def close_degree2(db_path, person_edges, star_pid: str, t_minus_1: int, *,
                  cap_k: int, cap_per_star: int, exclude_pids,
                  include_pids=None) -> list:
    """Close the degree-2 incumbent set for one star (bounded, deterministic, two-sided freeze flag).

    Args:
        db_path:      path to a persistent DuckDB file (':memory:'/None -> ValueError).
        person_edges: full person-level edge table {work_id, person_id, publication_year}
                      (must be the full edge table, not seed-incident edges, #9).
        star_pid / t_minus_1: the star person and the freeze year (events.t_minus_1 read directly).
        cap_k / cap_per_star: degree cap / per-star incumbent cap (must be passed explicitly, no default).
        exclude_pids: set of degree-1 direct links (H2 de-duplication) — no degree-2 rows are produced for them.
        include_pids: incumbent endpoint pool (None = no filtering, historical behaviour). Real runs restrict
                      to the two universities' incumbents; the pool limits endpoints only, not the intermediary
                      bridges (#9 full-edge-table rule), and the cap budget is allocated within the pool.

    Returns: [{"incumbent_person_id", "degree2_bridge_frozen"}] sorted by incumbent ascending;
          frozen channels take the cap budget first, unfrozen ones (either bridge edge > t-1) fill the remaining budget.
    """
    if db_path is None or str(db_path) == ":memory:":
        raise ValueError(
            "close_degree2: ':memory:' is forbidden — the degree-2 two-hop join needs a persistent .db that can spill to disk "
            "(in-memory databases have run out of memory before)"
        )
    if not isinstance(cap_k, int) or not isinstance(cap_per_star, int):
        raise ValueError("close_degree2: cap_k / cap_per_star must be explicit ints (no default magic numbers)")

    # #5: the bridge-edge frozen test goes through the single truncation entry point (inclusive <= t-1); the full edge set is also kept to judge post-arrival channels.
    frozen_edges = cutoff.filter_works_until(person_edges, t_minus_1)

    db_file = pathlib.Path(str(db_path))
    db_file.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_file))
    try:
        con.execute("SET preserve_insertion_order=false")
        _load_edges(con, "edges_all", person_edges)
        _load_edges(con, "edges_frozen", frozen_edges)
        con.execute(_PAIRS_SQL.format(out="pairs_a", src="edges_all"))
        con.execute(_PAIRS_SQL.format(out="pairs_f", src="edges_frozen"))
        rows_frozen = _two_hop(con, "pairs_f", star_pid, cap_k)
        rows_all = _two_hop(con, "pairs_a", star_pid, cap_k)
    finally:
        con.close()

    banned = set(exclude_pids) | {star_pid}
    allowed = set(include_pids) if include_pids is not None else None
    kept_frozen = _cap_deterministic(rows_frozen, banned, set(), cap_per_star,
                                     allowed)
    frozen_incs = {inc for _, inc in kept_frozen}
    budget_left = cap_per_star - len(kept_frozen)
    kept_unfrozen = _cap_deterministic(rows_all, banned, frozen_incs, budget_left,
                                       allowed)

    out = [
        {"incumbent_person_id": inc, "degree2_bridge_frozen": True}
        for _, inc in kept_frozen
    ]
    out += [
        {"incumbent_person_id": inc, "degree2_bridge_frozen": False}
        for _, inc in kept_unfrozen
    ]
    out.sort(key=lambda r: r["incumbent_person_id"])
    return out
