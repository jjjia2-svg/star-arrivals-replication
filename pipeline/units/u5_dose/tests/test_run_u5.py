"""run_u5: thin CLI top-level orchestration (io loading -> m4 p01/p05 -> m5b).

Covers: (1) end-to-end outputs are complete and valid; (2) tampered pins HALT; (3) config assembly of nine keys (the non-binding
cap upper bound is derived from the person_map row count, so the unset knob runs in a "never reaches the cap" way; see the
build_config docstring); (4) rule_version consistency gate.
"""
from __future__ import annotations

import json

import pytest

import run_u5
from common.manifest import ProvenanceMismatch, dataset_is_valid

from test_io_real import _mini_universe


def test_build_config_nine_keys_and_nonbinding_caps(tmp_path):
    cfg = run_u5.build_config(
        n_person_map_rows=100,
        pinned=dict(run_u5.PINNED_UPSTREAM_10C),
        duckdb_db_path=str(tmp_path / "d.db"),
    )
    for key in ("degree2_cap_k", "degree2_incumbent_cap_per_star",
                "mnar_missing_threshold", "duckdb_db_path", "embed_model_sha",
                "rule_version", "config_sha", "source_snapshot_merkle",
                "stars_set_hash"):
        assert key in cfg
    # cap = person_map row count + 1 -> every degree / per-star set in the subgraph is < cap (a mathematical upper bound that is never reached)
    assert cfg["degree2_cap_k"] == 101
    assert cfg["degree2_incumbent_cap_per_star"] == 101
    assert cfg["mnar_missing_threshold"] == 0.20     # MNAR missing-rate threshold: 20%
    assert len(cfg["config_sha"]) == 64              # Real sha256, not a placeholder


def test_run_all_end_to_end(tmp_path, mk, signed_dose):
    paths, prov = _mini_universe(tmp_path, mk)
    out_root = tmp_path / "ship"
    report = run_u5.run_all(
        paths, out_root=out_root, pinned=prov,
        duckdb_db_path=str(tmp_path / "sub.db"),
        enforce_red_coherence=False,      # The synthetic universe's pins are not the real redlines version
    )
    for sub in ("dose_p01", "dose_p05", "output"):
        assert dataset_is_valid(out_root / sub), sub
    assert report["m5b"]["n_rows"] == {"p01": 2, "p05": 2}
    assert report["dose"]["p05"]["n_rows"] == 1
    assert report["dose"]["p05"]["embed_deferred"] is True
    assert report["caps_nonbinding_proof"]["cap_exceeds_universe"] is True
    summary = json.loads(
        (out_root / "_reports" / "run_summary_u5.json").read_text(encoding="utf-8"))
    assert summary["m5b"]["n_excluded_works"] == {"p01": 1, "p05": 1}


def test_run_all_pins_tamper_halts(tmp_path, mk, signed_dose):
    paths, prov = _mini_universe(tmp_path, mk)
    with pytest.raises(ProvenanceMismatch):
        run_u5.run_all(
            paths, out_root=tmp_path / "ship2",
            pinned=dict(prov, stars_set_hash="TAMPERED"),
            duckdb_db_path=str(tmp_path / "sub2.db"),
            enforce_red_coherence=False,
        )


def test_run_all_red_coherence_gate(tmp_path, mk, signed_dose):
    """enforce_red_coherence=True (the default for real runs): pins.rule_version must equal the current
    redlines rule_version. A version drift between the upstream freeze and this run's definitions -> HALT."""
    paths, prov = _mini_universe(tmp_path, mk)   # prov.rule_version = 'r_signed'
    with pytest.raises(ValueError, match="rule_version"):
        run_u5.run_all(
            paths, out_root=tmp_path / "ship3", pinned=prov,
            duckdb_db_path=str(tmp_path / "sub3.db"),
            enforce_red_coherence=True,
        )
