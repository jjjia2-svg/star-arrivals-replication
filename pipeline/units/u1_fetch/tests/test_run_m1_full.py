"""Tests for the full-run driver run_m1_full: wiring (the dry_run plan + credential checks for execute).

Definition-neutral: it checks only assembly, the execute switch and reproducibility-credential discipline,
and touches no identification placeholder.
run_m1.py is untouched (old tests do not regress); run_m1_full is an independent full-run entry point and a thin wrapper over run_m1_streaming.
"""
from __future__ import annotations

import pytest

pa = pytest.importorskip("pyarrow")

from identity.golden import MONASH_CANONICAL_ID

_REGISTRY = [{"openalex_id": MONASH_CANONICAL_ID, "type": "education"}]
_ECON_DEPT_IDS = {MONASH_CANONICAL_ID}


def _make_snapshot(tmp_path, n_shards=3):
    """Build a fake snapshot root: snapshot_root/works/updated_date=.../part_*.gz (empty files; dry_run only counts them and does not read them)."""
    snap = tmp_path / "snap"
    shard_dir = snap / "works" / "updated_date=2016-01-01"
    shard_dir.mkdir(parents=True)
    for i in range(n_shards):
        (shard_dir / f"part_{i:03d}.gz").write_bytes(b"")
    return snap


def test_run_m1_full_dry_run_returns_plan_no_write(tmp_path):
    """dry_run (execute=False, the default): returns the plan (with the real shard count) + executed=False + never writes to disk."""
    from m1_ingest import run_m1_full as F

    snap = _make_snapshot(tmp_path, n_shards=3)
    out = tmp_path / "out"
    plan = F.run_full(
        snap, out, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS, execute=False,
    )
    assert plan["executed"] is False
    assert plan["work_shard_count"] == 3, "Should count the real number of works shards"
    assert not out.exists(), "dry_run should not create or write out_root"


def test_run_m1_full_default_is_dry_run(tmp_path):
    """Without execute -> dry_run by default (safe): a big full run never starts without an explicit --execute."""
    from m1_ingest import run_m1_full as F

    snap = _make_snapshot(tmp_path, n_shards=2)
    plan = F.run_full(snap, tmp_path / "out", registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS)
    assert plan["executed"] is False
    assert plan["work_shard_count"] == 2


def test_run_m1_full_execute_requires_real_provenance(tmp_path):
    """execute=True but the reproducibility credentials are None (placeholders) -> an explicit ValueError; placeholders never pollute run_manifest."""
    from m1_ingest import run_m1_full as F

    snap = _make_snapshot(tmp_path, n_shards=1)
    with pytest.raises(ValueError):
        F.run_full(
            snap, tmp_path / "out", registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
            execute=True,  # all reproducibility credentials missing -> must raise, no placeholder run is allowed
        )


def test_run_m1_full_discover_shards_sorted(tmp_path):
    """Shard discovery is deterministic: list every .gz under works and sort them (stable across machines and runs)."""
    from m1_ingest import run_m1_full as F

    snap = _make_snapshot(tmp_path, n_shards=4)
    shards = F.discover_work_shards(snap)
    assert len(shards) == 4
    assert shards == sorted(shards), "Shard paths must be sorted (determinism)"
    assert all(s.endswith(".gz") for s in shards)


def test_run_m1_full_no_identification_flags_in_cli():
    """CLI discipline: argparse must not have any identification flag (no --dose/--fwci-window/--diff-tolerance)."""
    from m1_ingest import run_m1_full as F

    parser = F._build_arg_parser()
    opt_strings = {s for a in parser._actions for s in a.option_strings}
    forbidden = {"--dose", "--fwci-window", "--diff-tolerance", "--age-bin", "--arrival"}
    assert not (opt_strings & forbidden), f"The CLI must not expose identification-rule flags: {opt_strings & forbidden}"


# ===========================================================================
# compact+dedup is on by default (full-run entry point)
#   run_full defaults to run_compact_dedup=True so the dedup guard cannot be forgotten; tests and smoke
#   runs must pass False explicitly to turn it off. The spy checks only the wiring switch and does not
#   really run the stream (definition-neutral).
# ===========================================================================
_REAL_CREDS = dict(source_snapshot_merkle="MERKLE_T", config_sha="CFG_T",
                   rule_version="rv_t", code_version="cv_t")


def _spy_streaming(monkeypatch):
    """Replace run_m1_streaming in the run_m1_full namespace with a spy: capture kwargs, do not really run."""
    from m1_ingest import run_m1_full as F

    captured = {}

    def _spy(_seed, _passc, **kw):
        captured.update(kw)
        return {}

    monkeypatch.setattr(F, "run_m1_streaming", _spy)
    return captured


def test_run_m1_full_execute_defaults_compact_dedup_on(monkeypatch, tmp_path):
    """run_full execute=True without run_compact_dedup -> the default path must pass run_compact_dedup=True into run_m1_streaming (compact+dedup runs by default)."""
    from m1_ingest import run_m1_full as F

    captured = _spy_streaming(monkeypatch)
    snap = _make_snapshot(tmp_path, n_shards=1)
    out = F.run_full(
        snap, tmp_path / "out", registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        execute=True, **_REAL_CREDS,
    )
    assert out["executed"] is True
    assert captured.get("run_compact_dedup") is True, (
        "The full-run entry point must enable compact+dedup by default"
    )


def test_run_m1_full_explicit_false_disables_compact_dedup(monkeypatch, tmp_path):
    """Explicit run_compact_dedup=False -> it does not run (the only way for tests and smoke runs to turn the guard off is to pass False explicitly; there is no silent default-off any more)."""
    from m1_ingest import run_m1_full as F

    captured = _spy_streaming(monkeypatch)
    snap = _make_snapshot(tmp_path, n_shards=1)
    F.run_full(
        snap, tmp_path / "out", registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        execute=True, run_compact_dedup=False, **_REAL_CREDS,
    )
    assert captured.get("run_compact_dedup") is False, "An explicit False must be passed through unchanged (can be turned off, but only explicitly)"


def test_run_m1_full_defaults_reduce_workers_auto(monkeypatch, tmp_path):
    """The reduce stage runs in parallel by bucket: the full-run driver run_full defaults to reduce_workers=0 (auto)
    and passes it through to run_m1_streaming -> the final production merge uses all cores automatically (cuts the biggest bottleneck by about 45%)."""
    from m1_ingest import run_m1_full as F

    captured = _spy_streaming(monkeypatch)
    snap = _make_snapshot(tmp_path, n_shards=1)
    F.run_full(
        snap, tmp_path / "out", registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        execute=True, **_REAL_CREDS,
    )
    assert captured.get("reduce_workers") == 0, "run_full must by default pass reduce_workers=0 (auto) through"


def test_run_m1_full_explicit_reduce_workers_threaded(monkeypatch, tmp_path):
    """Explicit reduce_workers=6 -> passed through unchanged to run_m1_streaming (the operator can control reduce concurrency exactly)."""
    from m1_ingest import run_m1_full as F

    captured = _spy_streaming(monkeypatch)
    snap = _make_snapshot(tmp_path, n_shards=1)
    F.run_full(
        snap, tmp_path / "out", registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        execute=True, reduce_workers=6, **_REAL_CREDS,
    )
    assert captured.get("reduce_workers") == 6, "An explicit reduce_workers must be passed through unchanged"
