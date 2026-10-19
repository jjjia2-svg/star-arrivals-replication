"""io_real — real-data loading adapter layer (eight-table contract gate + 10c provenance binding).

The real tables are too large (edges 79 million / refs 237 million rows) to materialise in full -> DuckDB extracts a subgraph out of core,
and feeds the **same** pure functions as the synthetic tests (never a second dose/aggregation implementation — prevents B5).
This test checks the adapter on a small parquet universe in tmp: extraction result == plain-Python filter result.
"""
from __future__ import annotations

import json
import pathlib

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import io_real
from common.manifest import ProvenanceMismatch


def _write(dir_path: pathlib.Path, name: str, rows: list[dict], cols: list[str]):
    dir_path.mkdir(parents=True, exist_ok=True)
    table = pa.table({c: [r[c] for r in rows] for c in cols})
    pq.write_table(table, str(dir_path / name))


def _mini_universe(tmp_path, mk):
    """Mini mirror of the SSD layout: u1 (one file each for edges/refs/works/work_text) + u2 pm +
    u4 (star_set+header / events+header / pc with a bucket column)."""
    root = tmp_path / "derived"
    edges = [
        mk.edge("W_CO", "A_S", 2014), mk.edge("W_CO", "A_I", 2014),
        mk.edge("W_I1", "A_I", 2012),
        mk.edge("W_S1", "A_S", 2013),
        mk.edge("W_X", "A_OUT", 2010),          # an out-of-domain person's work (must not be extracted)
        mk.edge("W_NOYR", "A_I", None),         # edge with a missing year (the OpenAlex norm): excluded + logged
    ]
    _write(root / "u1" / "authorship_edges", "part-0.parquet", edges,
           ["work_id", "author_id", "publication_year"])
    refs = [mk.ref("W_CO", "R1"), mk.ref("W_S1", "R1"), mk.ref("W_S1", "R2"),
            mk.ref("W_X", "R9")]
    _write(root / "u1" / "refs_edges", "part-0.parquet", refs,
           ["work_id", "referenced_work_id"])
    works = [mk.work("W_CO", 2014), mk.work("W_I1", 2012), mk.work("W_S1", 2013),
             mk.work("W_X", 2010)]
    _write(root / "u1" / "works", "part-0.parquet", works, list(works[0].keys()))
    _write(root / "u1" / "work_text", "part-0.parquet",
           [mk.text(w["work_id"]) for w in works],
           ["work_id", "title", "abstract_text"])

    pm = [mk.pm("A_S", "P_S"), mk.pm("A_I", "P_I"), mk.pm("A_OUT", "P_OUT")]
    _write(root / "u2" / "person_map", "data.parquet", pm, list(pm[0].keys()))

    stars = [mk.star("A_S")]
    _write(root / "u4" / "star_set", "star_set.parquet", stars,
           list(stars[0].keys()))
    prov = {"source_snapshot_merkle": "m_x", "config_sha": "c_x",
            "rule_version": "r_signed", "stars_set_hash": "s_x"}
    (root / "u4" / "star_set" / "manifest_header.json").write_text(
        json.dumps(prov), encoding="utf-8")

    events = [mk.event("A_S:2016", "A_S", 2016, 2015)]   # author_id key (10c reality)
    _write(root / "u4" / "events", "data.parquet", events,
           list(events[0].keys()))
    (root / "u4" / "events" / "manifest_header.json").write_text(
        json.dumps(prov), encoding="utf-8")

    pc = [dict(mk.pc("W_CO", "P_I", "P_I", 2014, frac_credit=0.5, fwci=2.0),
               bucket=0),
          dict(mk.pc("W_CO", "P_I", "P_S", 2014, frac_credit=0.5, fwci=2.0),
               bucket=1),
          dict(mk.pc("W_I1", "P_I", "P_I", 2012, frac_credit=1.0, fwci=1.0),
               bucket=0)]
    _write(root / "u4" / "paper_contrib", "part-0.parquet", pc, list(pc[0].keys()))

    paths = {
        "authorship_edges_glob": str(root / "u1" / "authorship_edges" / "*.parquet"),
        "refs_edges_glob": str(root / "u1" / "refs_edges" / "*.parquet"),
        "works_glob": str(root / "u1" / "works" / "*.parquet"),
        "work_text_glob": str(root / "u1" / "work_text" / "*.parquet"),
        "person_map": str(root / "u2" / "person_map" / "data.parquet"),
        "star_set_dir": str(root / "u4" / "star_set"),
        "events_dir": str(root / "u4" / "events"),
        "paper_contrib_glob": str(root / "u4" / "paper_contrib" / "*.parquet"),
    }
    return paths, prov


# ---------------------------------------------------------------------------
# single-table load + contract gate
# ---------------------------------------------------------------------------
def test_load_paper_contrib_drops_bucket_and_gates(tmp_path, mk):
    paths, _ = _mini_universe(tmp_path, mk)
    rows = io_real.load_paper_contrib(paths["paper_contrib_glob"])
    assert len(rows) == 3
    assert "bucket" not in rows[0]                    # strip the hive bucket column
    from common.schema import PAPER_CONTRIB, assert_matches_schema
    assert_matches_schema(rows[0].keys(), PAPER_CONTRIB, label="pc")


def test_load_events_folds_author_to_person(tmp_path, mk):
    """10c reality: events.star_person_id holds an author_id -> folded to person through person_map."""
    paths, prov = _mini_universe(tmp_path, mk)
    pm = io_real.load_person_map(paths["person_map"])
    events = io_real.load_events(paths["events_dir"], pm,
                                 expected_provenance=prov)
    assert events[0]["star_person_id"] == "P_S"       # folded to the person key
    assert events[0]["t_minus_1"] == 2015


def test_load_events_unmapped_star_fail_loud(tmp_path, mk):
    paths, prov = _mini_universe(tmp_path, mk)
    pm = [r for r in io_real.load_person_map(paths["person_map"])
          if r["author_id"] != "A_S"]                 # remove the star's mapping
    with pytest.raises(ValueError, match="person_map"):
        io_real.load_events(paths["events_dir"], pm, expected_provenance=prov)


def test_star_provenance_mismatch_halts(tmp_path, mk):
    """10c provenance binding: the expected four-tuple differs -> ProvenanceMismatch (HALT, not WARN)."""
    paths, prov = _mini_universe(tmp_path, mk)
    bad = dict(prov, stars_set_hash="TAMPERED")
    with pytest.raises(ProvenanceMismatch):
        io_real.load_star_set(paths["star_set_dir"], expected_provenance=bad)


# ---------------------------------------------------------------------------
# subgraph extraction == plain-Python filter (the adapter does not change numbers)
# ---------------------------------------------------------------------------
def test_build_real_inputs_subgraph_matches_python_filter(tmp_path, mk):
    paths, prov = _mini_universe(tmp_path, mk)
    inputs, extras = io_real.build_real_inputs(
        paths, pinned_star_provenance=prov,
        duckdb_db_path=str(tmp_path / "sub.db"),
    )
    # pool = pc incumbents {P_I}; star = {P_S}; out-of-domain A_OUT/W_X never enter the subgraph
    assert extras["incumbent_pool"] == {"P_I"}
    got_edges = {(e["work_id"], e["author_id"]) for e in inputs.authorship_edges}
    assert ("W_X", "A_OUT") not in got_edges
    # edges with a missing year = dropped from the dose domain + logged (they cannot enter any per-year computation);
    # an edge with a missing year can only belong to a work with a missing year -> its pc unit is already dropped by the missing-year log, so the retained side loses nothing
    assert ("W_NOYR", "A_I") not in got_edges
    assert extras["n_dropped_null_year_edges"] == 1
    # the exclusion-set edge domain (M5b) is independent of year (#8, literally "whole history"): edges with a missing year stay in exclusion_edges
    excl_edges = {(e["work_id"], e["author_id"]) for e in extras["exclusion_edges"]}
    assert ("W_NOYR", "A_I") in excl_edges
    assert got_edges <= excl_edges                     # exclusion edge domain contains the dose edge domain
    # the full-history edges of the star + pool authors + the full authorship edges of the relevant works are all present
    assert {("W_CO", "A_S"), ("W_CO", "A_I"), ("W_I1", "A_I"),
            ("W_S1", "A_S")} <= got_edges
    # refs only up to the pool + star works
    assert {(r["work_id"], r["referenced_work_id"]) for r in inputs.refs_edges} \
        == {("W_CO", "R1"), ("W_S1", "R1"), ("W_S1", "R2")}
    # works cover the dose people's works + pc works; star_pids are folded
    assert {w["work_id"] for w in inputs.works} == {"W_CO", "W_I1", "W_S1"}
    assert inputs.star_pids["p05"] == {"P_S"}
    assert extras["embed_deferred"] is True
    assert inputs.work_text == []                      # deferred mode does not scan the 3.8GB of text


def test_build_real_inputs_runs_through_m4_and_m5b(tmp_path, mk, signed_dose):
    """End to end: real-data layout -> adapter -> run_m4_dose (deferred) + run_m5b, all-green products."""
    from m4_dose import run_dose
    from m5b_aggregate import run_m5b
    paths, prov = _mini_universe(tmp_path, mk)
    inputs, extras = io_real.build_real_inputs(
        paths, pinned_star_provenance=prov,
        duckdb_db_path=str(tmp_path / "sub.db"),
    )
    cfg = {
        "degree2_cap_k": 99, "degree2_incumbent_cap_per_star": 99,
        "mnar_missing_threshold": 0.20,
        "duckdb_db_path": str(tmp_path / "deg2.db"),
        "embed_model_sha": "deferred",
        "rule_version": "r_signed", "config_sha": "c_u5",
        "source_snapshot_merkle": "m_x", "stars_set_hash": "s_x",
    }
    rep_dose = run_dose.run_m4_dose(
        inputs, config=cfg, out_root=tmp_path / "dose_p05",
        ledger_path=tmp_path / "ledger.jsonl", p_level="p05", embedder=None,
        closure_edges=extras["closure_edges"],
        incumbent_pool=extras["incumbent_pool"],
    )
    assert rep_dose["n_rows"] == 1 and rep_dose["embed_deferred"] is True
    rep_m5b = run_m5b.run_m5b(
        inputs, config=cfg, out_root=tmp_path / "output",
        ledger_path=tmp_path / "ledger.jsonl",
    )
    assert rep_m5b["n_rows"] == {"p01": 2, "p05": 2}   # P_I×{2012,2014}
    assert rep_m5b["n_excluded_works"] == {"p01": 1, "p05": 1}   # {W_CO}
