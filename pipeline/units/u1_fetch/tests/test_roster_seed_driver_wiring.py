"""Driver-level wiring test for the roster seed arm: run_smoke_m1 passes roster_seed_paths through to run_full.

Background: the library function run_m1_full.run_full already has a roster_seed_paths arm (tested by
test_byline_seed_wiring.py::test_run_full_roster_seed_paths_arm_merges_and_reports, which passes), but the
launch driver run_smoke_m1 did not wire it. A full AWS re-pick would then silently drop the roster arm,
which is the fix for authors the harvest missed entirely.

Behaviour pinned:
  - run_smoke(roster_seed_paths=[...]) -> run_full receives roster_seed_paths unchanged (extraction and union happen in the library).
  - Not given (default None) -> run_full receives None; existing runs are unchanged.
  - Fail loudly before launch: any roster path that does not exist -> RuntimeError, never enter an 18 h full run in a bad state.
  - CLI: --roster-seed <path...> (nargs="+", default None) feeds run_smoke.

Definition-neutral: it only widens the harvest (fetch more, miss nothing) and touches no identification
choice; roster row content and author_id are untouched.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

pytest.importorskip("pyarrow")

# The driver sits at the repo root (not in units/*/src) -> explicitly put the repo root on sys.path before importing.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import run_smoke_m1 as D  # noqa: E402


def _fake_snapshot(tmp_path):
    snap = tmp_path / "snap"
    (snap / "works" / "updated_date=2016-01-01").mkdir(parents=True)
    (snap / "works" / "updated_date=2016-01-01" / "part_0000.gz").write_bytes(b"")
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


def _stub_heavy(monkeypatch, captured):
    monkeypatch.setattr(D, "build_inputs", lambda _s, **_k: ([], set()))
    monkeypatch.setattr(D, "compute_repro_creds", lambda **_k: dict(
        source_snapshot_merkle="M", config_sha="C", rule_version="r", code_version="c"))
    monkeypatch.setattr(D, "run_full", lambda *a, **k: captured.update(k) or {"executed": True})


def _fake_roster(tmp_path, name="roster.parquet"):
    import pyarrow as pa
    import pyarrow.parquet as pq
    p = tmp_path / name
    pq.write_table(pa.table({"author_id": ["A1", None, "A2"]}), str(p))
    return p


def test_driver_threads_roster_seed_paths_to_run_full(monkeypatch, tmp_path):
    """Wiring side: run_smoke(roster_seed_paths=[...]) -> run_full receives it unchanged (extraction belongs to the library)."""
    captured = {}
    _stub_heavy(monkeypatch, captured)
    snap = _fake_snapshot(tmp_path)
    r1 = _fake_roster(tmp_path, "r1.parquet")
    r2 = _fake_roster(tmp_path, "r2.parquet")

    D.run_smoke(snap, tmp_path / "out", execute=True, reconcile=False, max_shards=5,
                roster_seed_paths=[str(r1), str(r2)])
    assert captured.get("roster_seed_paths") == [str(r1), str(r2)], \
        "The ignition driver must pass roster_seed_paths through to run_full (roster arm)"


def test_driver_default_no_roster_seed_is_none(monkeypatch, tmp_path):
    """No-regression side: roster_seed_paths not given -> run_full receives None (existing runs are unchanged)."""
    captured = {}
    _stub_heavy(monkeypatch, captured)
    snap = _fake_snapshot(tmp_path)

    D.run_smoke(snap, tmp_path / "out", execute=True, reconcile=False, max_shards=5)
    assert captured.get("roster_seed_paths") is None


def test_driver_missing_roster_path_fails_loud(monkeypatch, tmp_path):
    """Fail-loud side: any roster path that does not exist -> RuntimeError before launch (never enter an 18 h full run in a bad state)."""
    captured = {}
    _stub_heavy(monkeypatch, captured)
    snap = _fake_snapshot(tmp_path)
    r1 = _fake_roster(tmp_path, "r1.parquet")

    with pytest.raises(RuntimeError, match="roster"):
        D.run_smoke(snap, tmp_path / "out", execute=True, reconcile=False, max_shards=5,
                    roster_seed_paths=[str(r1), str(tmp_path / "NOT_THERE.parquet")])
    assert not captured, "A missing path must be caught before entering run_full"


def test_cli_parser_roster_seed_flag():
    """CLI side: --roster-seed takes several paths (nargs='+'), default None."""
    p = D._parser()
    a = p.parse_args(["--out-root", "/tmp/o", "--roster-seed", "a.parquet", "b.parquet"])
    assert a.roster_seed == ["a.parquet", "b.parquet"]
    a2 = p.parse_args(["--out-root", "/tmp/o"])
    assert a2.roster_seed is None
