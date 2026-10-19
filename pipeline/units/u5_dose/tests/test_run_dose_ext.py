"""run_dose extensions: deferred secondary dose (embed environment missing) + incumbent pool filter + independent closure edge domain.

All three extensions are engineering-level, and with default parameters behavior is identical to the existing 75 tests (zero regression):
  1. embedder=None -> **secondary dose embed is deferred**: the embed_cos column is NA (None), diag records
     embed_deferred=true, and the return value says so explicitly; vectors are never faked and the main line is never
     blocked (the primary dose is unaffected, since the #16 primary/secondary isolation already keeps embed out of coupling_share).
  2. incumbent_pool: in a real two-university run the incumbent endpoint of a dose pair is limited to incumbents (deg1+deg2 use the same pool);
     None (default) = no filtering (synthetic tests unchanged). The middleman (the degree-2 bridge) is **not limited by the pool**
     (#9 full-edge-table rule: the pool limits endpoints, not bridges).
  3. closure_edges: degree-2 closure can use a larger edge set than the dose computation domain (including all the middleman's edges);
     None (default) = the same edge set as the dose.
"""
from __future__ import annotations

import pyarrow.parquet as pq

from common.manifest import sha256_file
from m4_dose import degree2_closure, io_load, run_dose

from test_run_dose import _cfg, _det_embedder, _mk_inputs


def _run(mk, tmp_path, *, sub="out", inputs=None, embedder=_det_embedder, **kw):
    inputs = inputs if inputs is not None else _mk_inputs(mk)
    out_root = tmp_path / sub
    report = run_dose.run_m4_dose(
        inputs, config=_cfg(tmp_path), out_root=out_root,
        ledger_path=tmp_path / sub / "_ledger_events.jsonl",
        p_level="p01", embedder=embedder, **kw,
    )
    return out_root, report


def _rows(out_root):
    return pq.read_table(str(out_root / "_frozen" / "dose.parquet")).to_pylist()


# ---------------------------------------------------------------------------
# 1. embed deferred (embedder=None)
# ---------------------------------------------------------------------------
def test_embedder_none_defers_embed_cos_na(mk, tmp_path, signed_dose):
    """embedder=None -> embed_cos is all None (NA); diag and the return value both state embed_deferred."""
    out_root, report = _run(mk, tmp_path, embedder=None)
    rows = _rows(out_root)
    assert rows and all(r["embed_cos"] is None for r in rows)
    assert report["embed_deferred"] is True
    import json
    diag = json.loads((out_root / "diag.json").read_text(encoding="utf-8"))
    assert diag["embed_deferred"] is True
    # The frozen vector table is still present (0 rows, correct column order), so the reproduction contract has no missing file
    emb = pq.read_table(str(out_root / "_frozen" / "work_embeddings.parquet"))
    assert emb.num_rows == 0


def test_embedder_none_does_not_require_work_text(mk, tmp_path, signed_dose):
    """Deferred mode does not read work_text, so missing source text does not block the main line (76% of real works have no abstract)."""
    inputs = _mk_inputs(mk)
    inputs.work_text = []          # All missing
    out_root, report = _run(mk, tmp_path, inputs=inputs, embedder=None)
    assert report["skipped"] is False
    assert all(r["embed_cos"] is None for r in _rows(out_root))


def test_embedder_none_main_dose_unchanged(mk, tmp_path, signed_dose):
    """The primary dose (coupling_share) has the same value, row by row, as a non-deferred run: deferring the secondary dose never touches the main line (#16)."""
    out_a, _ = _run(mk, tmp_path, sub="a", embedder=_det_embedder)
    out_b, _ = _run(mk, tmp_path, sub="b", embedder=None)
    key = lambda r: (r["incumbent_person_id"], r["star_person_id"],
                     r["event_id"], r["degree"])
    a = {key(r): r["coupling_share"] for r in _rows(out_a)}
    b = {key(r): r["coupling_share"] for r in _rows(out_b)}
    assert a == b


def test_embedder_none_two_run_byte_identical(mk, tmp_path, signed_dose):
    """Deferred mode gives byte-identical output on two runs (#27 determinism holds with NA columns)."""
    out_a, _ = _run(mk, tmp_path, sub="a", embedder=None)
    out_b, _ = _run(mk, tmp_path, sub="b", embedder=None)
    assert sha256_file(out_a / "_frozen" / "dose.parquet") == \
           sha256_file(out_b / "_frozen" / "dose.parquet")


# ---------------------------------------------------------------------------
# 2. incumbent_pool endpoint filter
# ---------------------------------------------------------------------------
def test_incumbent_pool_filters_endpoints(mk, tmp_path, signed_dose):
    """pool={P_I} -> only P_I rows; pool={P_I,P_I2} -> both deg1 and deg2 present; an endpoint outside the pool never yields a row."""
    out_a, _ = _run(mk, tmp_path, sub="a", incumbent_pool={"P_I"})
    rows_a = _rows(out_a)
    assert {r["incumbent_person_id"] for r in rows_a} == {"P_I"}

    out_b, _ = _run(mk, tmp_path, sub="b", incumbent_pool={"P_I", "P_I2"})
    rows_b = _rows(out_b)
    assert {r["incumbent_person_id"] for r in rows_b} == {"P_I", "P_I2"}
    assert {r["degree"] for r in rows_b} == {1, 2}


def test_incumbent_pool_mid_not_restricted(mk, tmp_path, signed_dose):
    """The pool limits endpoints, not bridges (#9): P_M (the middleman) is not in the pool, and P_I2 still closes to degree-2 via P_M."""
    out_root, _ = _run(mk, tmp_path, incumbent_pool={"P_I2"})
    rows = _rows(out_root)
    deg2 = [r for r in rows if r["degree"] == 2]
    assert {r["incumbent_person_id"] for r in deg2} == {"P_I2"}
    assert deg2[0]["degree2_bridge_frozen"] is True


def test_pool_none_default_unchanged(mk, tmp_path, signed_dose):
    """incumbent_pool=None (default) gives exactly the same row set as not passing it: zero regression."""
    out_a, _ = _run(mk, tmp_path, sub="a")
    out_b, _ = _run(mk, tmp_path, sub="b", incumbent_pool=None)
    assert sha256_file(out_a / "_frozen" / "dose.parquet") == \
           sha256_file(out_b / "_frozen" / "dose.parquet")


# ---------------------------------------------------------------------------
# 3. closure_edges independent edge domain + include_pids
# ---------------------------------------------------------------------------
def test_closure_edges_separate_scope(mk, tmp_path, signed_dose):
    """The dose edge domain has no edge rows of the middleman itself, while the closure edge domain does -> degree-2 still closes and the freeze flag is correct.

    Real two-university layout: dose computation domain = edges of incumbents + the star (saves memory);
    closure domain = all edges of incumbents + the star + middlemen (needed for degree-2 bridges).
    """
    inputs = _mk_inputs(mk)
    closure_edges = list(inputs.authorship_edges)                  # All edges (including A_M)
    inputs.authorship_edges = [e for e in inputs.authorship_edges
                               if e["author_id"] != "A_M"]         # The dose domain drops the middleman
    out_root, _ = _run(mk, tmp_path, inputs=inputs,
                       closure_edges=closure_edges,
                       incumbent_pool={"P_I", "P_I2"})
    rows = _rows(out_root)
    deg2 = [r for r in rows if r["degree"] == 2]
    assert {r["incumbent_person_id"] for r in deg2} == {"P_I2"}
    assert deg2[0]["degree2_bridge_frozen"] is True


def test_close_degree2_include_pids(mk, tmp_path, signed_dose):
    """include_pids: the closure result is limited to incumbents in the pool, and the cap budget is allocated within the pool (outside-pool entries use no quota)."""
    pm = [mk.pm(a, f"P_{a[2:]}") for a in
          ("A_S", "A_M", "A_X1", "A_X2", "A_POOL")]
    edges_raw = [
        mk.edge("W_MS", "A_M", 2010), mk.edge("W_MS", "A_S", 2010),
        mk.edge("W_1", "A_X1", 2011), mk.edge("W_1", "A_M", 2011),
        mk.edge("W_2", "A_X2", 2012), mk.edge("W_2", "A_M", 2012),
        mk.edge("W_3", "A_POOL", 2013), mk.edge("W_3", "A_M", 2013),
    ]
    from m4_dose import candidate_pairs
    person_edges, _ = candidate_pairs.person_level_edges(edges_raw, pm)
    out = degree2_closure.close_degree2(
        str(tmp_path / "d.db"), person_edges, "P_S", 2015,
        cap_k=50, cap_per_star=1,          # The budget is only 1
        exclude_pids=set(), include_pids={"P_POOL"},
    )
    # Outside-pool X1/X2 with later evidence years still use no budget; P_POOL inside the pool gets the only slot
    assert [r["incumbent_person_id"] for r in out] == ["P_POOL"]
