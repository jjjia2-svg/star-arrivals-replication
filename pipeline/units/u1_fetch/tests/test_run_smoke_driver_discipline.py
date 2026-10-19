"""Tests for driver-level scale-up discipline (run_smoke_m1 = the launcher for real runs).

Rule: a full run must explicitly confirm that run_compact_dedup is on and must always pass the
reconcile_manifest external anchor. The run_full docstring says the thin assembly layer does not load the
manifest itself (the operator or a later manifest-loading step supplies it). The operator is the
run_smoke_m1 driver (the launch command), so the anchor is wired here.

Behaviour pinned (both sides):
  - A real full run (execute=True and max_shards=None) with reconcile=False -> RuntimeError, refuses to
    run (a full production run needs an external-anchor reconcile; a subset smoke run with max_shards set is not restricted).
  - reconcile=True -> the driver reads snapshot_root/manifest.json (parse_top_manifest) automatically and
    passes it to run_full as reconcile_manifest (wires the anchor; an old driver lacked this step, so
    --reconcile hit the ValueError in streaming).
  - The driver passes run_compact_dedup=True explicitly (explicit confirmation that it is on; the driver layer has no off switch).
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

pa = pytest.importorskip("pyarrow")

# The driver sits at the repo root (not in units/*/src) -> explicitly put the repo root on sys.path before importing.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import run_smoke_m1 as D  # noqa: E402


def _fake_snapshot(tmp_path, with_manifest=True):
    snap = tmp_path / "snap"
    (snap / "works" / "updated_date=2016-01-01").mkdir(parents=True)
    (snap / "works" / "updated_date=2016-01-01" / "part_0000.gz").write_bytes(b"")
    if with_manifest:
        manifest = {
            "date": "2026-06-26", "format": "jsonl",
            "meta": {"record_count": 1, "content_length": 1},
            "entities": [{
                "entity": "works", "record_count": 1, "content_length": 1,
                "files": [{
                    "url": "s3://openalex/data/jsonl/works/updated_date=2016-01-01/part_0000.gz",
                    "meta": {"content_length": 1, "record_count": 1}}],
            }],
        }
        (snap / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return snap


def test_driver_full_execute_without_reconcile_refused(tmp_path):
    """Refuse side: a real full run (execute=True, max_shards=None) without reconcile -> the driver layer refuses to run (scale-up discipline)."""
    snap = _fake_snapshot(tmp_path)
    with pytest.raises(RuntimeError, match="scale-up discipline"):
        D.run_smoke(snap, tmp_path / "out", execute=True, reconcile=False)


def test_driver_subset_smoke_without_reconcile_allowed(monkeypatch, tmp_path):
    """Allow side: a subset smoke run (max_shards set) does not force reconcile; a smoke run not matching the full manifest is expected."""
    captured = {}
    monkeypatch.setattr(D, "build_inputs", lambda _s, **_k: ([], set()))
    monkeypatch.setattr(D, "compute_repro_creds", lambda **_k: dict(
        source_snapshot_merkle="M", config_sha="C", rule_version="r", code_version="c"))
    monkeypatch.setattr(D, "run_full", lambda *a, **k: captured.update(k) or {"executed": True})

    snap = _fake_snapshot(tmp_path)
    D.run_smoke(snap, tmp_path / "out", execute=True, reconcile=False, max_shards=5)
    assert captured, "A subset smoke run should be allowed into run_full"
    assert captured.get("max_shards") == 5


def test_driver_reconcile_loads_manifest_anchor_and_confirms_dedup(monkeypatch, tmp_path):
    """Anchor side: reconcile=True -> the driver reads snapshot_root/manifest.json and passes the external anchor;
    and it explicitly confirms run_compact_dedup=True."""
    captured = {}
    monkeypatch.setattr(D, "build_inputs", lambda _s, **_k: ([], set()))
    monkeypatch.setattr(D, "compute_repro_creds", lambda **_k: dict(
        source_snapshot_merkle="M", config_sha="C", rule_version="r", code_version="c"))
    monkeypatch.setattr(D, "run_full", lambda *a, **k: captured.update(k) or {"executed": True})
    # The tolerance is read from the red-line settings (value 0); the test depends on nothing beyond the real file: require reads the real file.

    snap = _fake_snapshot(tmp_path)
    D.run_smoke(snap, tmp_path / "out", execute=True, reconcile=True)
    mf = captured.get("reconcile_manifest")
    assert mf is not None, "The driver must install the external manifest anchor (A2: supplied by the operator)"
    assert mf["entities"][0]["entity"] == "works"
    assert captured.get("run_compact_dedup") is True, "The driver explicitly confirms compact+dedup is on"


def test_driver_reconcile_missing_manifest_file_fails_loud(tmp_path):
    """The snapshot root has no manifest.json -> fail loudly (never silently degrade to a reconcile with no anchor)."""
    snap = _fake_snapshot(tmp_path, with_manifest=False)
    with pytest.raises((FileNotFoundError, OSError)):
        D.run_smoke(snap, tmp_path / "out", execute=True, reconcile=True)


def test_driver_threads_reduce_workers_default_auto(monkeypatch, tmp_path):
    """The reduce stage runs in parallel by bucket: the launch command run_smoke defaults to reduce_workers=0 (auto)
    and passes it through to run_full -> the final full-run merge uses all cores automatically (the launch command carries --reduce-workers)."""
    captured = {}
    monkeypatch.setattr(D, "build_inputs", lambda _s, **_k: ([], set()))
    monkeypatch.setattr(D, "compute_repro_creds", lambda **_k: dict(
        source_snapshot_merkle="M", config_sha="C", rule_version="r", code_version="c"))
    monkeypatch.setattr(D, "run_full", lambda *a, **k: captured.update(k) or {"executed": True})

    snap = _fake_snapshot(tmp_path)
    D.run_smoke(snap, tmp_path / "out", execute=True, reconcile=False, max_shards=5)
    assert captured.get("reduce_workers") == 0, "The ignition command must by default pass reduce_workers=0 (auto) through"


def test_driver_threads_explicit_reduce_workers(monkeypatch, tmp_path):
    """Explicit reduce_workers=12 -> run_smoke passes it through unchanged to run_full (the operator controls it exactly by vCPU count)."""
    captured = {}
    monkeypatch.setattr(D, "build_inputs", lambda _s, **_k: ([], set()))
    monkeypatch.setattr(D, "compute_repro_creds", lambda **_k: dict(
        source_snapshot_merkle="M", config_sha="C", rule_version="r", code_version="c"))
    monkeypatch.setattr(D, "run_full", lambda *a, **k: captured.update(k) or {"executed": True})

    snap = _fake_snapshot(tmp_path)
    D.run_smoke(snap, tmp_path / "out", execute=True, reconcile=False, max_shards=5,
                reduce_workers=12)
    assert captured.get("reduce_workers") == 12, "An explicit reduce_workers must be passed through unchanged"
