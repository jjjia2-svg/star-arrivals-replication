"""run_dose: M4 orchestration and on-disk output red tests (cases #1/#7/#7b/#18b/#24/#25/#26/#27/#27b/#28/#29/#30).

End to end: synthetic mini-universe -> candidate pairs (deg1+deg2) -> primary dose (delegated to identity) +
secondary dose -> coverage/MNAR diagnostics -> PAIRWISE_DOSE written in canonical 11-column form (two-phase
COMMIT) -> tally/diag sidecars -> idempotent ledger. Everything uses tmp directories; nothing is ever written to the SSD.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

import pyarrow.parquet as pq
import pytest

from common.manifest import dataset_is_valid, sha256_file
from common.schema import PAIRWISE_DOSE
from m4_dose import io_load, run_dose


def _det_embedder(text: str):
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [b / 255.0 for b in digest[:8]]


def _mk_inputs(mk, *, t_minus_1=2015, ms_year=2014, mnar_pad=None):
    """Synthetic mini-universe -> U5Inputs (skips the parquet round trip and builds the in-memory handles directly).

    Base layout:
      P_I  <-> P_S direct coauthorship W_CO(2014)          -> degree-1
      P_M  <-> P_S direct coauthorship W_MS(ms_year)       -> degree-1 (not counted when ms_year > t-1)
      P_I2 <-> P_M coauthorship W_IM(2013)                 -> degree-2 via P_M (the bridge-edge freeze flag looks at ms_year)
      P_I also has W_I1(2012); P_S also has W_S1(2013)
    mnar_pad=(n_extra, n_missing): adds n_extra solo-authored 2014 works by P_I,
      of which n_missing have has_references=False (MNAR scenario).
    """
    pm = [mk.pm("A_S", "P_S"), mk.pm("A_I", "P_I"),
          mk.pm("A_M", "P_M"), mk.pm("A_I2", "P_I2")]
    edges = [
        mk.edge("W_CO", "A_S", 2014), mk.edge("W_CO", "A_I", 2014),
        mk.edge("W_MS", "A_M", ms_year), mk.edge("W_MS", "A_S", ms_year),
        mk.edge("W_IM", "A_I2", 2013), mk.edge("W_IM", "A_M", 2013),
        mk.edge("W_I1", "A_I", 2012),
        mk.edge("W_S1", "A_S", 2013),
    ]
    works = [
        mk.work("W_CO", 2014), mk.work("W_MS", ms_year),
        mk.work("W_IM", 2013), mk.work("W_I1", 2012), mk.work("W_S1", 2013),
    ]
    refs = [
        mk.ref("W_CO", "R1"), mk.ref("W_CO", "R2"),
        mk.ref("W_I1", "R1"),
        mk.ref("W_S1", "R1"), mk.ref("W_S1", "R3"),
        mk.ref("W_S1", "R4"),  # The star shares R4 with I2 within t-1, so a channel that is not frozen but peeks anyway would yield > 0 (mutant-killer)
        mk.ref("W_IM", "R4"), mk.ref("W_MS", "R4"),
    ]
    texts = [mk.text(w["work_id"], abstract_text=f"abs-{w['work_id']}")
             for w in works]

    if mnar_pad is not None:
        n_extra, n_missing = mnar_pad
        for i in range(n_extra):
            wid = f"W_PAD{i}"
            has = i >= n_missing
            edges.append(mk.edge(wid, "A_I", 2014))
            works.append(mk.work(wid, 2014, has_references=has))
            texts.append(mk.text(wid, abstract_text=f"abs-{wid}"))
            if has:
                refs.append(mk.ref(wid, f"R_PAD{i}"))

    inputs = io_load.U5Inputs(
        authorship_edges=edges, refs_edges=refs, works=works, work_text=texts,
        person_map=pm, star_set=[mk.star("A_S")],
        events=[mk.event("E1", "P_S", 2016, t_minus_1)],
        paper_contrib=[],
        star_pids={"p01": {"P_S"}, "p05": {"P_S"}},
    )
    return inputs


def _cfg(tmp_path, **over):
    cfg = {
        "degree2_cap_k": 50,
        "degree2_incumbent_cap_per_star": 100,
        "mnar_missing_threshold": 0.20,
        "duckdb_db_path": str(tmp_path / "duck" / "deg2.db"),
        "embed_model_sha": "m_test",
        "rule_version": "u5_dose_v3_signed_2026-06-28",
        "config_sha": "cfg_test_sha",
        "source_snapshot_merkle": "merkle_test",
        "stars_set_hash": "stars_test_hash",
    }
    cfg.update(over)
    return cfg


def _run(mk, tmp_path, *, sub="out", inputs=None, cfg=None, force=False):
    inputs = inputs if inputs is not None else _mk_inputs(mk)
    cfg = cfg if cfg is not None else _cfg(tmp_path)
    out_root = tmp_path / sub
    report = run_dose.run_m4_dose(
        inputs, config=cfg, out_root=out_root,
        ledger_path=tmp_path / sub / "_ledger_events.jsonl",
        p_level="p01", embedder=_det_embedder, force_recompute=force,
    )
    return out_root, report


def _read_dose(out_root):
    return pq.read_table(str(out_root / "_frozen" / "dose.parquet")).to_pylist()


# ---------------------------------------------------------------------------
# End to end: 11-column schema / row set / unique PK / unit interval / two-bridge flag
# ---------------------------------------------------------------------------
def test_run_dose_end_to_end(tmp_path, mk, signed_dose):
    """PAIRWISE_DOSE has exactly 11 columns, row set = {I(1), M(1), I2(2)}, unique PK (#27b), values in [0,1] (#26)."""
    out_root, report = _run(mk, tmp_path)
    rows = _read_dose(out_root)
    assert set(rows[0].keys()) == set(PAIRWISE_DOSE.keys())
    got = {(r["incumbent_person_id"], r["degree"]) for r in rows}
    assert got == {("P_I", 1), ("P_M", 1), ("P_I2", 2)}
    # Unique PK (#27b)
    pks = [(r["incumbent_person_id"], r["star_person_id"], r["event_id"], r["degree"])
           for r in rows]
    assert len(pks) == len(set(pks))
    # Unit interval (#26)
    for r in rows:
        for col in ("coupling_share", "topic_cos", "embed_cos", "coupling_coverage"):
            assert 0.0 <= r[col] <= 1.0, (r["incumbent_person_id"], col, r[col])
    # Both bridge edges <= t-1 -> degree-2 row has frozen=True; degree-1 rows are always True (an empty bridge set is vacuously true)
    by_inc = {r["incumbent_person_id"]: r for r in rows}
    assert by_inc["P_I2"]["degree2_bridge_frozen"] is True
    assert by_inc["P_I2"]["coupling_share"] > 0.0  # Shared R4 -> the frozen channel computes the true value
    assert by_inc["P_I"]["degree2_bridge_frozen"] is True
    assert report["n_rows"] == 3
    assert dataset_is_valid(out_root)


def test_pairwise_dose_pk_unique_guard():
    """#27b (unit level): duplicate PK rows -> raise (last guard if the H2 degree-1-first de-duplication is broken)."""
    row = {"incumbent_person_id": "P_I", "star_person_id": "P_S",
           "event_id": "E1", "degree": 1}
    with pytest.raises(ValueError):
        run_dose._assert_pk_unique([row, dict(row)])


# ---------------------------------------------------------------------------
# #24/#1: frozen_at_year == events.t_minus_1 (read directly; a poisoned value prevents recomputation)
# ---------------------------------------------------------------------------
@pytest.mark.depends_on_u4
def test_frozen_at_year_equals_t_minus_1_not_recomputed(tmp_path, mk, signed_dose):
    """#24 + #1: poisoned events t_minus_1=2014 (!= arrival-1=2015) -> rows have frozen_at_year==2014."""
    inputs = _mk_inputs(mk, t_minus_1=2014)
    out_root, _ = _run(mk, tmp_path, inputs=inputs)
    rows = _read_dose(out_root)
    assert rows and all(r["frozen_at_year"] == 2014 for r in rows)  # Recomputing 2015 would be caught here


# ---------------------------------------------------------------------------
# #7/#25: every channel uses the same cutoff entry point and the same t-1
# ---------------------------------------------------------------------------
def test_all_channels_same_cutoff(tmp_path, mk, signed_dose, monkeypatch):
    """#7/#25: spy on filter_works_until. Primary coupling / secondary topic / secondary embed / deg1 / deg2
    all receive a t_minus_1 equal to events.t_minus_1 and to the written frozen_at_year."""
    from m4_dose import cutoff as cutoff_mod

    seen = []
    real = cutoff_mod.filter_works_until

    def spy(rows, t):
        seen.append(t)
        return real(rows, t)

    monkeypatch.setattr(cutoff_mod, "filter_works_until", spy)
    out_root, _ = _run(mk, tmp_path)
    rows = _read_dose(out_root)
    assert seen and set(seen) == {2015}
    assert len(seen) >= 5  # deg1 + deg2 + refs for 2 people + coverage/topic/embed: all channels pass through the same entry point
    assert all(r["frozen_at_year"] == 2015 for r in rows)


# ---------------------------------------------------------------------------
# #7b (run level): any bridge edge > t-1 -> primary dose is 0 and flag is False
# ---------------------------------------------------------------------------
def test_degree2_unfrozen_bridge_zero_main_dose(tmp_path, mk, signed_dose):
    """#7b: P_M<->P_S bridge edge in 2017 (> t-1) -> P_I2 row has frozen=False and coupling_share==0.0
    (even if refs really share R4 it must not be counted: strict two-sided freeze, #5)."""
    inputs = _mk_inputs(mk, ms_year=2017)
    out_root, _ = _run(mk, tmp_path, inputs=inputs)
    rows = _read_dose(out_root)
    by_inc = {r["incumbent_person_id"]: r for r in rows}
    # P_M only coauthors with the star after arrival -> not a dose-side degree-1 (coauthor_pre_arrival is frozen at t-1)
    assert "P_M" not in by_inc
    r2 = by_inc["P_I2"]
    assert r2["degree"] == 2
    assert r2["degree2_bridge_frozen"] is False
    assert r2["coupling_share"] == 0.0  # Shared R4 exists, but the channel is not frozen -> forced to 0


# ---------------------------------------------------------------------------
# #18b: MNAR > 20% -> diag flag + WARN (not silent)
# ---------------------------------------------------------------------------
def test_dose_coverage_mnar_flag_above_threshold(tmp_path, mk, signed_dose):
    """#18b: 25% of the refs missing for the works involved -> mnar_robustness_required=True + WARN;
    15% -> False (strictly greater than the threshold)."""
    # The works involved in the base universe's pairs (P_I, P_S, P_M, P_I2 up to 2015) are 5 works, all with has_references=True
    # Add 15 solo works by P_I with 5 missing refs: missing rate 5/20 = 25% > 20%
    inputs_a = _mk_inputs(mk, mnar_pad=(15, 5))
    with pytest.warns(UserWarning, match="MNAR"):
        out_a, rep_a = _run(mk, tmp_path, sub="a", inputs=inputs_a)
    diag_a = json.loads((out_a / "diag.json").read_text(encoding="utf-8"))
    assert diag_a["mnar_robustness_required"] is True
    assert rep_a["refs_missing_rate"] == pytest.approx(0.25)

    # 3/20 = 15% <= 20% -> not flagged
    inputs_b = _mk_inputs(mk, mnar_pad=(15, 3))
    out_b, rep_b = _run(mk, tmp_path, sub="b", inputs=inputs_b)
    diag_b = json.loads((out_b / "diag.json").read_text(encoding="utf-8"))
    assert diag_b["mnar_robustness_required"] is False
    assert rep_b["refs_missing_rate"] == pytest.approx(0.15)


# ---------------------------------------------------------------------------
# #27: two runs are byte-identical (canonical sort + deterministic write parameters + two-phase COMMIT)
# ---------------------------------------------------------------------------
def test_two_run_byte_identical_dose(tmp_path, mk, signed_dose):
    """#27: two independent full runs -> dose.parquet and work_embeddings.parquet have byte-identical sha256."""
    shas = []
    for sub in ("r1", "r2"):
        out_root, _ = _run(mk, tmp_path, sub=sub)
        shas.append((
            sha256_file(out_root / "_frozen" / "dose.parquet"),
            sha256_file(out_root / "_frozen" / "work_embeddings.parquet"),
        ))
    assert shas[0] == shas[1]


# ---------------------------------------------------------------------------
# #28: the ledger only uses .append (no .emit/.tally: DRIFT-L1)
# ---------------------------------------------------------------------------
def test_ledger_append_not_emit():
    """#28: the run_dose source contains ledger.append and no call to .emit( or .tally(."""
    src = pathlib.Path(run_dose.__file__).read_text(encoding="utf-8")
    assert ".append(" in src
    assert ".emit(" not in src
    assert ".tally(" not in src


# ---------------------------------------------------------------------------
# #29: atomic commit, all-or-nothing
# ---------------------------------------------------------------------------
def test_atomic_commit_all_or_nothing(tmp_path, mk, signed_dose):
    """#29: crash before COMMIT -> dataset is invalid and there is no _frozen/dose.parquet; a successful rerun -> valid.

    The crash injection uses its own MonkeyPatch instance. The shared monkeypatch.undo() must not be used
    (it would also undo the three RED keys injected by signed_dose).
    """
    import common.manifest as manifest_mod

    def boom(self):
        raise RuntimeError("injected crash before COMMIT")

    mp = pytest.MonkeyPatch()
    mp.setattr(manifest_mod._DatasetCommitter, "commit", boom)
    try:
        with pytest.raises(RuntimeError, match="injected crash"):
            _run(mk, tmp_path, sub="x")
        out_root = tmp_path / "x"
        assert not dataset_is_valid(out_root)
        assert not (out_root / "_frozen" / "dose.parquet").exists()
    finally:
        mp.undo()

    _run(mk, tmp_path, sub="x", force=True)
    assert dataset_is_valid(out_root)


# ---------------------------------------------------------------------------
# #30: resume skips idempotently
# ---------------------------------------------------------------------------
def test_resume_skips_done_via_idempotency(tmp_path, mk, signed_dose, monkeypatch):
    """#30: a first run logged ok -> a second run with the same idempotency key skips (the poison pill proves nothing was recomputed); only force recomputes."""
    out_root, rep1 = _run(mk, tmp_path)
    assert rep1["skipped"] is False

    from m4_dose import coupling as coupling_mod

    def poison(*a, **k):
        raise AssertionError("recompute happened despite idempotency")

    monkeypatch.setattr(coupling_mod, "pair_coupling", poison)
    out_root2, rep2 = _run(mk, tmp_path)  # Same out_root/ledger -> skip
    assert rep2["skipped"] is True
    with pytest.raises(AssertionError, match="recompute"):
        _run(mk, tmp_path, force=True)  # force -> truly recomputes -> the poison pill fires (proves the skip is idempotence, not coincidence)


# ---------------------------------------------------------------------------
# Engineering discipline: a missing config key raises / an unset red line raises / diagnostics are not mixed into the tally
# ---------------------------------------------------------------------------
def test_config_missing_key_raises(tmp_path, mk, signed_dose):
    """An injected parameter whose key cannot be read raises; no default magic number is assigned."""
    cfg = _cfg(tmp_path)
    cfg.pop("degree2_cap_k")
    with pytest.raises(KeyError):
        _run(mk, tmp_path, cfg=cfg)


def test_run_reads_signed_dose_from_yaml_no_injection(tmp_path, mk):
    """The three dose keys are set in redlines.yaml as cosine/0.0/0.0. With no signed_dose fixture and no
    monkeypatch injection, the run reads the real values straight from redlines.yaml and writes its output
    (the pipeline needs no injection to run)."""
    out_root, report = _run(mk, tmp_path)  # No injection at all: the YAML holds the set values and require() reads them
    rows = _read_dose(out_root)
    assert rows, "with the pinned values the production pipeline should produce dose rows"
    assert report["skipped"] is False and report["n_rows"] == len(rows)
    diag = json.loads((out_root / "diag.json").read_text(encoding="utf-8"))
    assert diag["coverage_floor"] == 0.0  # What is read is exactly the value in the YAML


def test_diag_sidecar_not_in_tally(tmp_path, mk, signed_dose):
    """Diagnostics (MNAR/coverage/unmapped) go to the diag.json sidecar; the tally keeps its strict six keys + op_id_arm discipline."""
    out_root, _ = _run(mk, tmp_path)
    tally = json.loads((out_root / "tally.json").read_text(encoding="utf-8"))
    assert set(tally.keys()) == {"stage", "expected", "kept", "failed", "skipped",
                                 "balanced", "op_id_arm"}
    assert tally["balanced"] is True
    diag = json.loads((out_root / "diag.json").read_text(encoding="utf-8"))
    assert "mnar_robustness_required" in diag
    assert "refs_missing_rate" in diag
    assert "n_unmapped_edge_authors" in diag
