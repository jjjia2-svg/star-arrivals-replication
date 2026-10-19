"""io_real - real-data loading adapter layer (eight-table contract gate + 10c provenance binding).

Why an adapter layer: the real tables are too big (authorship_edges 79.06M rows / refs_edges 237M rows /
works 46.5M rows / work_text 3.8GB) to materialise fully in Python. DuckDB extracts a **bounded subgraph** out of
core, then feeds it to the same pure functions the synthetic tests use (m4_dose/m5b_aggregate) -
**no second dose/aggregation implementation is ever built** (guards against definition drift).

Subgraph definition (engineering-level extraction, touches no identification definition):
  - pool (incumbent_pool) = the distinct incumbent_person_id of paper_contrib
    (the incumbent output population frozen by U4 - the person form of the roster's incumbents);
  - dose edge domain = the **full-history** edges of the author fragments of (pool ∪ shipping stars) + the
    **full-byline** edges of the works of (pool ∪ stars)
    (the latter lets the M5b exclusion set see each work's complete author list, and also serves as bridges for
    the closure);
  - closure domain = the same edge set (the two bridge edges of a two-hop i↔mid↔star necessarily fall within
    pool works ∪ star works - i ∈ pool ⇒ bridge 1 ∈ pool works; star end ⇒ bridge 2 ∈ star works; the middle
    person needs no separate full-history extraction);
  - refs domain = the refs of the works of (pool ∪ stars) people (raw material of coupling; IDF pool = this
    subgraph's refs, the current build_ref_idf convention inside run_dose - engineering level, see report);
  - work_text: not scanned in embed-deferred mode (secondary dose deferred, vectors are never fabricated).

Contract gate: each table's column set is exactly equal to the u0 schema (after stripping the hive bucket column
from paper_contrib); the star_set/events artifact-header four-tuple == the pinned 10c values, otherwise
ProvenanceMismatch HALT (not WARN).
events.star_person_id holds author_id (the 10c reality) -> folded to person via person_map; a shipping star with a
missing mapping -> fail-loud.
"""
from __future__ import annotations

import json
import pathlib

from common.manifest import ProvenanceMismatch, verify_provenance
from common.schema import (
    AUTHORSHIP_EDGES,
    EVENTS,
    PAPER_CONTRIB,
    PERSON_MAP,
    REFS_EDGES,
    STAR_SET,
    WORKS,
    assert_matches_schema,
)
from m4_dose import io_load
from m5b_aggregate import star_coauthored_works as scw


# ---------------------------------------------------------------------------
# Single-table loading (small tables read in full + contract gate)
# ---------------------------------------------------------------------------
def _read_parquet_rows(path_or_glob: str, *, schema: dict, label: str,
                       drop_cols: tuple = ()) -> list[dict]:
    import duckdb

    con = duckdb.connect()
    try:
        rel = con.execute(
            f"SELECT * FROM read_parquet('{path_or_glob}', hive_partitioning=0)"
        )
        cols = [d[0] for d in rel.description]
        keep = [c for c in cols if c not in drop_cols]
        assert_matches_schema(keep, schema, label=label)
        rows = [dict(zip(cols, t)) for t in rel.fetchall()]
    finally:
        con.close()
    if drop_cols:
        rows = [{k: v for k, v in r.items() if k not in drop_cols} for r in rows]
    return rows


def _verify_header(dir_path: str, expected: dict, *, label: str) -> None:
    p = pathlib.Path(dir_path) / "manifest_header.json"
    if not p.is_file():
        raise ProvenanceMismatch(
            f"[{label}] upstream manifest_header missing: {p} — provenance cannot be shown, HALT",
            key="manifest_header",
        )
    verify_provenance(json.loads(p.read_text(encoding="utf-8")), expected)


def load_person_map(path: str) -> list[dict]:
    return _read_parquet_rows(path, schema=PERSON_MAP, label="person_map")


def load_star_set(dir_path: str, *, expected_provenance: dict) -> list[dict]:
    _verify_header(dir_path, expected_provenance, label="star_set")
    return _read_parquet_rows(str(pathlib.Path(dir_path) / "star_set.parquet"),
                              schema=STAR_SET, label="star_set")


def load_events(dir_path: str, person_map_rows, *,
                expected_provenance: dict) -> list[dict]:
    """events loading + author->person folding (10c: the star_person_id column holds author_id).

    A shipping star (the 12 people in events) with no person_map mapping -> ValueError fail-loud
    (a 12-row small table; with even one missing, dose cannot be computed; never let it pass with a WARN).
    """
    _verify_header(dir_path, expected_provenance, label="events")
    rows = _read_parquet_rows(str(pathlib.Path(dir_path) / "data.parquet"),
                              schema=EVENTS, label="events")
    pid_by_author = {r["author_id"]: r["person_id"] for r in person_map_rows}
    out = []
    for r in rows:
        author = r["star_person_id"]
        pid = pid_by_author.get(author)
        if pid is None:
            raise ValueError(
                f"events star {author!r} has no person_map mapping — a shipped star must fold to a person, "
                "fail-loud (author→person link layer)"
            )
        out.append({**r, "star_person_id": pid})
    return out


def load_paper_contrib(glob_: str) -> list[dict]:
    return _read_parquet_rows(glob_, schema=PAPER_CONTRIB, label="paper_contrib",
                              drop_cols=("bucket",))


# ---------------------------------------------------------------------------
# DuckDB subgraph extraction (out of core - big tables are never fully materialised)
# ---------------------------------------------------------------------------
def _register_ids(con, name: str, ids) -> None:
    import pyarrow as pa

    con.register(f"_{name}_arrow", pa.table({"id": sorted(ids)}))
    con.execute(f"CREATE OR REPLACE TEMP TABLE {name} AS "
                f"SELECT id FROM _{name}_arrow")
    con.unregister(f"_{name}_arrow")


def edges_for_authors(con, glob_: str, author_ids) -> list[dict]:
    """Edge rows of an author set (edges with a missing year are dropped - the accounting for missing years goes separately through null_year_edge_keys)."""
    _register_ids(con, "want_authors", author_ids)
    rows = con.execute(
        f"SELECT e.work_id, e.author_id, e.publication_year "
        f"FROM read_parquet('{glob_}', hive_partitioning=0) e JOIN want_authors w ON e.author_id = w.id "
        f"WHERE e.publication_year IS NOT NULL "
        f"ORDER BY e.work_id, e.author_id"
    ).fetchall()
    return [{"work_id": a, "author_id": b, "publication_year": c}
            for a, b, c in rows]


def edges_for_works(con, glob_: str, work_ids) -> list[dict]:
    """Full-byline edge rows of a work set (edges with a missing year dropped, as above)."""
    _register_ids(con, "want_works", work_ids)
    rows = con.execute(
        f"SELECT e.work_id, e.author_id, e.publication_year "
        f"FROM read_parquet('{glob_}', hive_partitioning=0) e JOIN want_works w ON e.work_id = w.id "
        f"WHERE e.publication_year IS NOT NULL "
        f"ORDER BY e.work_id, e.author_id"
    ).fetchall()
    return [{"work_id": a, "author_id": b, "publication_year": c}
            for a, b, c in rows]


def null_year_edge_rows(con, glob_: str, author_ids) -> list[dict]:
    """Edges with a missing year (the accounting side of "keep dropping + count"):
    returns the edge rows within the author set whose publication_year IS NULL.

    Rationale: a missing-year edge can only belong to a missing-year work (edge year = works.publication_year,
    single source) -> its pc contribution cell is already dropped by the missing-year accounting
    (aggregate n_dropped_null_pub_year), and dose truncation cannot tell before from after (it cannot enter any
    by-year computation) - so **dropping them from the dose domain** costs nothing on the retained side.
    But **the M5b exclusion set is independent of year** (the literal full-history exclusion): a missing-year work
    co-authored with a star still enters the exclusion set -> these rows stay in exclusion_edges and are dropped
    only from the dose edge domain.
    """
    _register_ids(con, "null_yr_authors", author_ids)
    rows = con.execute(
        f"SELECT e.work_id, e.author_id "
        f"FROM read_parquet('{glob_}', hive_partitioning=0) e "
        f"JOIN null_yr_authors w ON e.author_id = w.id "
        f"WHERE e.publication_year IS NULL "
        f"ORDER BY e.work_id, e.author_id"
    ).fetchall()
    return [{"work_id": a, "author_id": b, "publication_year": None}
            for a, b in rows]


def refs_for_works(con, glob_: str, work_ids) -> list[dict]:
    _register_ids(con, "want_ref_works", work_ids)
    rows = con.execute(
        f"SELECT r.work_id, r.referenced_work_id "
        f"FROM read_parquet('{glob_}', hive_partitioning=0) r JOIN want_ref_works w ON r.work_id = w.id "
        f"ORDER BY r.work_id, r.referenced_work_id"
    ).fetchall()
    return [{"work_id": a, "referenced_work_id": b} for a, b in rows]


def works_for_ids(con, glob_: str, work_ids) -> list[dict]:
    _register_ids(con, "want_work_rows", work_ids)
    rel = con.execute(
        f"SELECT k.* FROM read_parquet('{glob_}', hive_partitioning=0) k "
        f"JOIN want_work_rows w ON k.work_id = w.id ORDER BY k.work_id"
    )
    cols = [d[0] for d in rel.description]
    assert_matches_schema(cols, WORKS, label="works")
    return [dict(zip(cols, t)) for t in rel.fetchall()]


def frags_of_persons(person_map_rows, persons) -> set:
    """person set -> the set of all its author fragments (all author_ids in the U2 cluster)."""
    wanted = set(persons)
    return {r["author_id"] for r in person_map_rows if r["person_id"] in wanted}


def build_real_inputs(paths: dict, *, pinned_star_provenance: dict,
                      duckdb_db_path: str):
    """Real-data eight tables -> bounded subgraph -> io_load.U5Inputs + extras (closure_edges/pool/counts).

    paths has eight keys: authorship_edges_glob / refs_edges_glob / works_glob /
                work_text_glob / person_map / star_set_dir / events_dir /
                paper_contrib_glob (a missing key raises KeyError, no defaults are assigned).
    """
    import duckdb

    # -- small tables read in full + contract gate + provenance binding --------------------------------
    pm = load_person_map(paths["person_map"])
    star_rows = load_star_set(paths["star_set_dir"],
                              expected_provenance=pinned_star_provenance)
    events = load_events(paths["events_dir"], pm,
                         expected_provenance=pinned_star_provenance)
    pc = load_paper_contrib(paths["paper_contrib_glob"])

    # -- pool and stars (person form) ------------------------------------------------
    pool = {r["incumbent_person_id"] for r in pc}
    ship_p05, _n_unmapped_ship = scw.ship_star_person_ids(star_rows, pm,
                                                          p_level="p05")
    pool_frags = frags_of_persons(pm, pool)
    star_frags = frags_of_persons(pm, ship_p05)

    db_file = pathlib.Path(duckdb_db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_file))
    try:
        con.execute("SET preserve_insertion_order=false")
        eg = paths["authorship_edges_glob"]
        edges_star = edges_for_authors(con, eg, star_frags)
        edges_pool = edges_for_authors(con, eg, pool_frags)
        star_works = {e["work_id"] for e in edges_star}
        pool_works = {e["work_id"] for e in edges_pool}
        # full-byline edges of the relevant works (the M5b exclusion set sees the complete author list + degree-2 bridges)
        edges_onworks = edges_for_works(con, eg, star_works | pool_works)
        # missing-year edge accounting (as in U4: dropped from the dose domain + counted, never silent;
        # the M5b exclusion set is independent of year -> these rows enter exclusion_edges, not the dose edge domain)
        null_year_rows = null_year_edge_rows(con, eg, star_frags | pool_frags)

        seen: set = set()
        merged: list = []
        for e in edges_star + edges_pool + edges_onworks:
            k = (e["work_id"], e["author_id"])
            if k not in seen:
                seen.add(k)
                merged.append(e)
        merged.sort(key=lambda e: (e["work_id"], e["author_id"]))

        dose_person_works = star_works | pool_works
        refs = refs_for_works(con, paths["refs_edges_glob"], dose_person_works)
        pc_works = {r["work_id"] for r in pc}
        works = works_for_ids(con, paths["works_glob"],
                              dose_person_works | pc_works)
    finally:
        con.close()

    inputs = io_load.U5Inputs(
        authorship_edges=merged,
        refs_edges=refs,
        works=works,
        work_text=[],                      # embed deferred: the 3.8GB of text is not scanned, no fabricated vectors
        person_map=pm,
        star_set=star_rows,
        events=events,
        paper_contrib=pc,
    )
    total_unmapped = 0
    for p_level in ("p01", "p05"):
        pids, n_unmapped = io_load.fold_star_person_ids(star_rows, pm,
                                                        p_level=p_level)
        inputs.star_pids[p_level] = pids
        total_unmapped = max(total_unmapped, n_unmapped)
    inputs.n_unmapped_star_authors = total_unmapped

    io_load.assert_events_have_t_minus_1(inputs.events)          # B-EVENTS-T1
    io_load.assert_article_review_domain(pc, works)              # caveat#4 (fwci domain)

    extras = {
        "closure_edges": None,   # closure domain = the same edge set (pool works ∪ star works already contain both bridges)
        # M5b exclusion-set edge domain (independent of year, full-history exclusion): dose edge domain + missing-year edges
        "exclusion_edges": merged + null_year_rows,
        "n_dropped_null_year_edges": len(null_year_rows),
        "incumbent_pool": pool,
        "embed_deferred": True,
        "n_pool_persons": len(pool),
        "n_ship_p05_stars": len(ship_p05),
        "n_edges_subgraph": len(merged),
        "n_refs_subgraph": len(refs),
        "n_works_subgraph": len(works),
        "n_pc_rows": len(pc),
    }
    inputs.report = {**extras}
    return inputs, extras
