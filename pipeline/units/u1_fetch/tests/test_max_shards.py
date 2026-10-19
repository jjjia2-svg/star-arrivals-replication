"""max_shards subset smoke switch: build_plan keeps only the first N sorted shards (a full run takes 18h and cannot resume, so first check the start-up path on a small sample)."""


def _mk_snapshot(tmp_path, n=3):
    works = tmp_path / "works" / "updated_date=2026-01-01"
    works.mkdir(parents=True)
    for i in range(n):
        (works / f"part_{i:04d}.gz").write_bytes(b"x")
    return tmp_path


def test_build_plan_respects_max_shards(tmp_path):
    from m1_ingest.run_m1_full import build_plan

    snap = _mk_snapshot(tmp_path, 3)
    full = build_plan(snap, tmp_path / "o", n_workers=1, bucket_row_cap=10)
    assert full["work_shard_count"] == 3 and full["max_shards"] is None

    sub = build_plan(snap, tmp_path / "o", n_workers=1, bucket_row_cap=10, max_shards=2)
    assert sub["work_shard_count"] == 2, "max_shards should limit to the first N shards"
    assert sub["max_shards"] == 2


def test_run_full_dry_run_carries_max_shards(tmp_path):
    """When run_full is not executing, it still passes max_shards through into the plan (the driver can echo it)."""
    from m1_ingest.run_m1_full import run_full

    snap = _mk_snapshot(tmp_path, 5)
    plan = run_full(snap, tmp_path / "o", registry=[], econ_dept_ids=set(),
                    execute=False, max_shards=3)
    assert plan["executed"] is False
    assert plan["work_shard_count"] == 3 and plan["max_shards"] == 3
