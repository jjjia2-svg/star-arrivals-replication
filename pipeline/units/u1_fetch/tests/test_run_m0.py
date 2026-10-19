"""Tests for run_m0.py: the M0 snapshot orchestration (manifest -> view -> capacity gate -> sync commands -> freeze -> canonical_id_map).

Behaviour covered:
  1. Call order: fetch_manifest -> view -> capacity gate -> sync commands (run through an injected fake
     runner) -> canonical_id_map.
  2. Byte-contract alignment (key): the top-level manifest.entities[] is split per entity into a
     {entity:{'meta':{'content_length','record_count'}}} view, which is fed to capacity_gate correctly.
  3. Capacity-gate blocking: any arm that fails -> CapacityGateError(exit=CAPACITY_GATE_FAIL=16); after a
     block, sync never runs.
  + merged_ids replay to find roots -> canonical_id_map rows with 4 keys (including merge chains folded to the root).

Discipline: only a small fake manifest.json fixture and a fake runner are used to test orchestration; never
a real S3 download, never a real write to the SSD. Output goes to tmp_path. Exit codes are always named
constants (no bare numbers).
"""
from __future__ import annotations

import gzip
import json

import pytest

from m0_snapshot import run_m0 as R
from m0_snapshot import s3_sync as S3
from identity.exit_codes import CAPACITY_GATE_FAIL


_GB = 1024 ** 3


# ---------------------------------------------------------------------------
# fixture: a small fake top-level manifest.json (observed shape: entities[] has content_length/record_count + files[])
# ---------------------------------------------------------------------------
def _file_entry(url: str, *, content_length: int, record_count: int) -> dict:
    return {"url": url, "meta": {"content_length": content_length, "record_count": record_count}}


def _fake_top_manifest(*, works_bytes=600 * _GB, authors_bytes=80 * _GB, inst_bytes=1 * _GB) -> dict:
    """A small fake top-level manifest: three entities, each with content_length/record_count and one file shard.

    This is the observed shape of the single top-level manifest.json (there is no per-entity manifest).
    The root content_length of each entity is used for the byte-contract view split; files[].meta lets
    assert_manifest_shape pass.
    """
    return {
        "date": "2026-06-01",
        "format": "jsonl",
        "meta": {"record_count": 3, "content_length": works_bytes + authors_bytes + inst_bytes},
        "entities": [
            {
                "entity": "works", "record_count": 500, "content_length": works_bytes,
                "files": [_file_entry(
                    "s3://openalex/data/jsonl/works/updated_date=2026-06-01/part_000.gz",
                    content_length=works_bytes, record_count=500)],
            },
            {
                "entity": "authors", "record_count": 90, "content_length": authors_bytes,
                "files": [_file_entry(
                    "s3://openalex/data/jsonl/authors/updated_date=2026-06-01/part_000.gz",
                    content_length=authors_bytes, record_count=90)],
            },
            {
                "entity": "institutions", "record_count": 1, "content_length": inst_bytes,
                "files": [_file_entry(
                    "s3://openalex/data/jsonl/institutions/updated_date=2026-06-01/part_000.gz",
                    content_length=inst_bytes, record_count=1)],
            },
        ],
    }


def _ok_cfg(*, free_bytes=3600 * _GB) -> dict:
    """Capacity-gate inputs: big disk, mounted, >= min_tb, small derived volume -> everything passes by default (the real byte gate is controlled by free_bytes)."""
    return {
        "snapshot_root_mounted": True,
        "snapshot_root_free_bytes": free_bytes,
        "snapshot_root_total_bytes": free_bytes,
        "snapshot_root_min_tb": 2.0,
        "est_derived_bytes": 50 * _GB,
        "tmp_used_bytes": 0,
        "same_physical_disk": True,
        "safety_margin": 1.15,
    }


class _RecordingRunner:
    """Fake runner: records the order of commands called and returns a fake stdout per command (manifest cp -> manifest bytes; sync -> empty).

    Zero network, zero S3: injected in place of the real subprocess_runner; the call-order assertion and
    "sync does not run after a capacity-gate block" both rely on it.
    """

    def __init__(self, manifest_obj: dict) -> None:
        self._manifest_blob = json.dumps(manifest_obj).encode("utf-8")
        self.calls: list[list[str]] = []

    def __call__(self, cmd) -> bytes:
        self.calls.append(list(cmd))
        # manifest cp command (contains 'cp') -> return the top-level manifest bytes; everything else (sync) -> empty stdout.
        if "cp" in cmd:
            return self._manifest_blob
        return b""


# ===========================================================================
# 2. Byte-contract alignment: split the top-level entities[] into a per-entity capacity view (key)
# ===========================================================================
def test_manifest_view_splits_entities_into_per_entity_meta():
    """Top-level manifest.entities[] -> a {entity:{'meta':{'content_length','record_count'}}} view per entity."""
    manifest = _fake_top_manifest(works_bytes=600 * _GB, authors_bytes=80 * _GB, inst_bytes=1 * _GB)
    view = R.fetch_official_manifest_view(manifest, entities=("works", "authors", "institutions"))

    # One view per entity; the root meta.content_length = that entity's entities[i].content_length.
    assert set(view) == {"works", "authors", "institutions"}
    assert view["works"]["meta"]["content_length"] == 600 * _GB
    assert view["works"]["meta"]["record_count"] == 500
    assert view["authors"]["meta"]["content_length"] == 80 * _GB
    assert view["institutions"]["meta"]["record_count"] == 1


def test_manifest_view_feeds_capacity_gate_real_byte_correctly():
    """The view is fed to capacity_gate correctly: real_byte_gate sums the split root meta.content_length to get real bytes."""
    from m0_snapshot import capacity_gate as CAP

    manifest = _fake_top_manifest(works_bytes=600 * _GB, authors_bytes=80 * _GB, inst_bytes=1 * _GB)
    view = R.fetch_official_manifest_view(manifest)
    # Remote real bytes = 681GB over the three entities; x1.15 = 783.15GB required.
    out = CAP.real_byte_gate(view, snapshot_root_free_bytes=3600 * _GB, safety_margin=1.15)
    assert out["ok"] is True
    assert out["remote_gb"] == pytest.approx((600 + 80 + 1), rel=1e-6)
    # free is set to 700GB -> required 783GB > free -> rejected (shows the view really reached the byte gate).
    tight = CAP.real_byte_gate(view, snapshot_root_free_bytes=700 * _GB, safety_margin=1.15)
    assert tight["ok"] is False


def test_manifest_view_missing_entity_raises_not_silent():
    """A requested entity is missing from the top-level manifest -> raise naming it (never silently count 0 bytes, which would make the capacity gate falsely green)."""
    manifest = _fake_top_manifest()
    with pytest.raises(S3.ManifestShapeError):
        R.fetch_official_manifest_view(manifest, entities=("works", "sources"))  # sources is absent


def test_manifest_view_default_entities_covers_all_in_manifest():
    """entities=None -> split every entity that appears in the top-level manifest."""
    manifest = _fake_top_manifest()
    view = R.fetch_official_manifest_view(manifest)
    assert set(view) == {"works", "authors", "institutions"}


# ===========================================================================
# 1. Call order: fetch_manifest -> view -> capacity gate -> sync commands (run through the fake runner)
# ===========================================================================
def test_orchestration_call_sequence_manifest_then_sync(tmp_path):
    """Order: cp to fetch the manifest first, then sync entity by entity; all commands go through the injected fake runner (zero network)."""
    manifest = _fake_top_manifest()
    runner = _RecordingRunner(manifest)
    out = R.run_m0_snapshot(
        cfg=_ok_cfg(), snapshot_root=str(tmp_path), runner=runner,
        do_freeze=False,  # freezing needs real .gz files on disk; turned off in the orchestration test (snapshot_freeze has its own tests)
    )
    # The first command = manifest cp (fetches the single top-level manifest.json).
    assert "cp" in runner.calls[0]
    assert any("manifest.json" in tok for tok in runner.calls[0])
    # After that come three sync commands (works/authors/institutions).
    sync_calls = [c for c in runner.calls if "sync" in c]
    assert len(sync_calls) == 3
    synced_entities = {c[3].rstrip("/").split("/")[-1] for c in sync_calls}  # the last segment of the s3 source URI = entity
    assert synced_entities == {"works", "authors", "institutions"}
    # sync_plan is in the return value (only command strings are built; the injected runner does the real run).
    assert out["sync_plan"] is not None and len(out["sync_plan"]) == 3


def test_orchestration_returns_manifest_view_and_capacity(tmp_path):
    """The assembly result contains manifest_view (the byte-contract view) + capacity (the gate verdict passed)."""
    manifest = _fake_top_manifest()
    runner = _RecordingRunner(manifest)
    out = R.run_m0_snapshot(
        cfg=_ok_cfg(), snapshot_root=str(tmp_path), runner=runner, do_freeze=False,
    )
    assert set(out["manifest_view"]) == {"works", "authors", "institutions"}
    assert out["capacity"]["passed"] is True
    # The real byte gate arm is in arms (shows the view really reached the capacity gate).
    assert "real_byte_gate" in out["capacity"]["arms"]


def test_sync_plan_commands_are_constructed_not_executed_directly(tmp_path):
    """build_sync_plan only builds a command list (pure string construction), one per entity, with the anonymous flag."""
    plan = R.build_sync_plan(snapshot_root=str(tmp_path), entities=("works", "authors"))
    assert len(plan) == 2
    for cmd in plan:
        assert cmd[:3] == ["aws", "s3", "sync"]
        assert S3.ANON_FLAG in cmd  # --no-sign-request is mandatory (anonymous, free)


# ===========================================================================
# 3. Capacity-gate blocking: any arm fails -> CapacityGateError; after a block, sync never runs
# ===========================================================================
def test_capacity_gate_blocks_when_not_mounted(tmp_path):
    """SNAPSHOT_ROOT is not mounted -> CapacityGateError(exit=CAPACITY_GATE_FAIL=16)."""
    cfg = _ok_cfg()
    cfg["snapshot_root_mounted"] = False
    manifest = _fake_top_manifest()
    runner = _RecordingRunner(manifest)
    with pytest.raises(R.CapacityGateError) as ei:
        R.run_m0_snapshot(cfg=cfg, snapshot_root=str(tmp_path), runner=runner, do_freeze=False)
    assert ei.value.exit_code == CAPACITY_GATE_FAIL
    assert "snapshot_root_mounted" in ei.value.fails


def test_capacity_gate_blocks_when_remote_exceeds_free(tmp_path):
    """Remote real bytes (681GB x1.15) > free (700GB) -> the real_byte_gate arm rejects -> CapacityGateError."""
    cfg = _ok_cfg(free_bytes=700 * _GB)
    manifest = _fake_top_manifest()  # 681GB over the three entities
    runner = _RecordingRunner(manifest)
    with pytest.raises(R.CapacityGateError) as ei:
        R.run_m0_snapshot(cfg=cfg, snapshot_root=str(tmp_path), runner=runner, do_freeze=False)
    assert "real_byte_gate" in ei.value.fails


def test_capacity_gate_block_prevents_any_sync(tmp_path):
    """After a capacity-gate block, no sync command runs (the fake runner is called once, only for the manifest cp, with no sync)."""
    cfg = _ok_cfg()
    cfg["snapshot_root_mounted"] = False  # must block
    manifest = _fake_top_manifest()
    runner = _RecordingRunner(manifest)
    with pytest.raises(R.CapacityGateError):
        R.run_m0_snapshot(cfg=cfg, snapshot_root=str(tmp_path), runner=runner, do_freeze=False)
    # Only the manifest was fetched with cp, and there is no sync at all (no data is fetched after a block, so no forced 639GB+ download).
    assert all("sync" not in c for c in runner.calls), "After the capacity gate blocks, no sync may run"


def test_run_capacity_gate_passes_through_when_ok():
    """The capacity gate passes everywhere -> run_capacity_gate returns the verdict (passed=True) and does not raise."""
    manifest = _fake_top_manifest()
    view = R.fetch_official_manifest_view(manifest)
    res = R.run_capacity_gate(_ok_cfg(), official_manifests=view)
    assert res["passed"] is True


# ===========================================================================
# merged_ids replay -> canonical_id_map (including merge chains folded to the root)
# ===========================================================================
def _merged_csv(rows: list[tuple[str, str, str]]) -> bytes:
    """Build legacy merged_ids CSV bytes (columns merge_date,id,merge_into_id)."""
    lines = ["merge_date,id,merge_into_id"]
    lines += [f"{d},{i},{m}" for (d, i, m) in rows]
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_canonical_id_map_built_from_merged_ids():
    """merged_ids replay -> canonical_id_map rows with 4 keys (raw_id/canonical_id/id_type/is_deleted)."""
    merged = {
        "authors": _merged_csv([("2026-01-01", "A_OLD", "A_NEW")]),
        "institutions": _merged_csv([("2026-01-01", "I_OLD", "I_NEW")]),
    }
    rows = R.build_canonical_id_map(merged)
    by_raw = {r["raw_id"]: r for r in rows}
    assert by_raw["A_OLD"]["canonical_id"] == "A_NEW"
    assert by_raw["A_OLD"]["id_type"] == "author"
    assert by_raw["I_OLD"]["id_type"] == "institution"
    # exactly 4 keys (guarded by assert_matches_schema; merged_ids is already validated).
    assert set(by_raw["A_OLD"]) == {"raw_id", "canonical_id", "id_type", "is_deleted"}


def test_canonical_id_map_folds_merge_chain_to_terminal_root():
    """Merge chain A1->A2->A3: the canonical_id of both A1 and A2 folds to the final root A3 (U0 replay finds the root)."""
    merged = {"authors": _merged_csv([
        ("2026-01-01", "A1", "A2"),
        ("2026-01-02", "A2", "A3"),
    ])}
    rows = R.build_canonical_id_map(merged)
    by_raw = {r["raw_id"]: r for r in rows}
    assert by_raw["A1"]["canonical_id"] == "A3"
    assert by_raw["A2"]["canonical_id"] == "A3"


def test_orchestration_produces_canonical_id_map_when_csv_given(tmp_path):
    """End to end: given merged_csv_by_entity -> the assembly result contains canonical_id_map rows."""
    manifest = _fake_top_manifest()
    runner = _RecordingRunner(manifest)
    merged = {"authors": _merged_csv([("2026-01-01", "A_OLD", "A_NEW")])}
    out = R.run_m0_snapshot(
        cfg=_ok_cfg(), snapshot_root=str(tmp_path), runner=runner,
        do_freeze=False, merged_csv_by_entity=merged,
    )
    raws = {r["raw_id"] for r in out["canonical_id_map"]}
    assert "A_OLD" in raws


def test_orchestration_no_canonical_map_when_csv_absent(tmp_path):
    """No merged_csv given -> canonical_id_map is None (not built by force)."""
    manifest = _fake_top_manifest()
    runner = _RecordingRunner(manifest)
    out = R.run_m0_snapshot(
        cfg=_ok_cfg(), snapshot_root=str(tmp_path), runner=runner, do_freeze=False,
    )
    assert out["canonical_id_map"] is None


# ===========================================================================
# manifest saved to disk (reproducibility credential) + bad bytes raise (never silently count as 0 shards)
# ===========================================================================
def test_manifest_persisted_to_snapshot_root(tmp_path):
    """fetch_official_manifest saves the top-level manifest.json reproducibility credential into snapshot_root."""
    manifest = _fake_top_manifest()
    runner = _RecordingRunner(manifest)
    R.run_m0_snapshot(cfg=_ok_cfg(), snapshot_root=str(tmp_path), runner=runner, do_freeze=False)
    mf = tmp_path / "manifest.json"
    assert mf.is_file()
    persisted = json.loads(mf.read_text(encoding="utf-8"))
    assert persisted["entities"][0]["entity"] == "works"


def test_bad_manifest_bytes_raise_not_silent_zero(tmp_path):
    """The runner returns bad bytes (not valid JSON) -> ManifestShapeError is raised (never silently treated as 0 expected shards)."""
    def _bad_runner(cmd):
        return b"<<< not json >>>"
    with pytest.raises(S3.ManifestShapeError):
        R.run_m0_snapshot(cfg=_ok_cfg(), snapshot_root=str(tmp_path), runner=_bad_runner, do_freeze=False)


# ===========================================================================
# subprocess_runner is left to operations (not really run at this stage): assert only that it exists + its signature shape
# ===========================================================================
def test_subprocess_runner_exists_for_ops_but_not_invoked_in_tests():
    """subprocess_runner is left to the operational path (the real run); the orchestration tests inject a fake runner in its place, and this test only asserts that it exists and is callable."""
    assert callable(R.subprocess_runner)
    # Not actually called (it would really run aws): only confirm it is the DI runner slot (Runner signature).
    assert R.Runner is not None
