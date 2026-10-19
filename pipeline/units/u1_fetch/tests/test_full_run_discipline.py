"""Tests for the full-run discipline: external anchor enforced on full production runs.

Rule under test:
  - A full production run must explicitly confirm run_compact_dedup is on, and must always pass the
    external reconcile_manifest anchor. run_compact_dedup defaults to on.
  - If `expected` is taken from the run's own scan counts, the reconcile is circular and checks nothing;
    the fix is an external manifest as ground truth. The engine (run_m1_streaming) already fails fast;
    this test moves the enforcement up to the production assembly layer run_full (refusal comes first,
    before preflight or shard discovery) and to the driver run_smoke_m1 (a full run must turn reconcile
    on and wire the anchor automatically).

Behaviour pinned (both sides):
  - run_full: execute=True and reconcile=True with reconcile_manifest=None -> ValueError, refuses to run,
    never enters run_m1_streaming, writes nothing (not even the environment-gate audit record; the
    discipline check comes first).
  - run_full: manifest given -> passed through unchanged (allow side).
Definition-neutral: engineering reconcile discipline; tolerances and formulas are untouched.
"""
from __future__ import annotations

import pytest

pa = pytest.importorskip("pyarrow")

from identity.golden import MONASH_CANONICAL_ID

_REGISTRY = [{"openalex_id": MONASH_CANONICAL_ID, "type": "education"}]
_ECON = {MONASH_CANONICAL_ID}
_REAL_CREDS = dict(source_snapshot_merkle="M", config_sha="C",
                   rule_version="r", code_version="c")


def _make_snapshot(tmp_path, n_shards=1):
    snap = tmp_path / "snap"
    d = snap / "works" / "updated_date=2016-01-01"
    d.mkdir(parents=True)
    for i in range(n_shards):
        (d / f"part_{i:03d}.gz").write_bytes(b"")
    return snap


def _manifest_works(n=1):
    return {
        "date": "2026-06-26", "format": "jsonl",
        "meta": {"record_count": n, "content_length": 1},
        "entities": [{
            "entity": "works", "record_count": n, "content_length": 1,
            "files": [{"url": "s3://openalex/data/jsonl/works/updated_date=2016-01-01/part_0000.gz",
                       "meta": {"content_length": 1, "record_count": n}}],
        }],
    }


def test_run_full_reconcile_without_manifest_refused_before_anything(monkeypatch, tmp_path):
    """Refuse side: execute+reconcile without an external manifest anchor -> ValueError, raised first in the
    assembly layer; never enters streaming (the spy must not be called) and writes nothing (out_root must not exist)."""
    from m1_ingest import run_m1_full as F

    called = []
    monkeypatch.setattr(F, "run_m1_streaming", lambda *a, **k: called.append(1) or {})
    snap = _make_snapshot(tmp_path)
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="external"):
        F.run_full(snap, out, registry=_REGISTRY, econ_dept_ids=_ECON,
                   execute=True, reconcile=True, reconcile_diff_tolerance=0,
                   **_REAL_CREDS)
    assert called == [], "a missing external anchor must be refused at the assembly layer, never reaching run_m1_streaming"
    assert not out.exists(), "Refused run = nothing written to disk (the discipline check comes before the environment gate and shard discovery)"


def test_run_full_reconcile_with_manifest_passes_anchor_through(monkeypatch, tmp_path):
    """Allow side: manifest given -> passed through unchanged to run_m1_streaming (anchor neither lost nor altered)."""
    from m1_ingest import run_m1_full as F

    captured = {}

    def _spy(_seed, _passc, **kw):
        captured.update(kw)
        return {}

    monkeypatch.setattr(F, "run_m1_streaming", _spy)
    snap = _make_snapshot(tmp_path)
    manifest = _manifest_works()
    res = F.run_full(snap, tmp_path / "out", registry=_REGISTRY, econ_dept_ids=_ECON,
                     execute=True, reconcile=True, reconcile_diff_tolerance=0,
                     reconcile_manifest=manifest, **_REAL_CREDS)
    assert res["executed"] is True
    assert captured.get("reconcile") is True
    assert captured.get("reconcile_manifest") is manifest, "the external anchor must be passed through unchanged"
