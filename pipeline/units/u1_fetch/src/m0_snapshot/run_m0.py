"""M0 assembly run_m0 — M0 snapshot orchestration (parse manifest -> capacity gate -> s3 sync commands -> freeze -> replay merged_ids to build canonical_id_map).

Why this is "assembly" and not new logic (same discipline as run_m1):
  Command construction, manifest parsing, the capacity gate, freezing and merge replay are already the job of sibling
  modules (s3_sync / manifest_reconcile / capacity_gate / snapshot_freeze / merged_ids / zenodo_anchor). run_m0 only chains them
  in the right order, guards the key invariants, and produces reproducibility evidence. Here the orchestration is tested with
  fixtures: it NEVER really downloads from S3 and NEVER really writes to the SSD (real runs are left to the vertical slice).

Main flow (run_m0_snapshot, with an injected runner):
  1. fetch_official_manifest(runner)         -> get the single top-level manifest.json (s3_sync; verified: there is no per-entity manifest).
  2. fetch_official_manifest_view(manifest)  -> byte-contract alignment: split the top-level manifest's entities[] per entity
       into {entity:{'meta':{'content_length','record_count'}}} views and feed capacity_gate.
  3. snapshot_capacity_gate(cfg, official_manifests=view) -> capacity gate (if any check fails -> HALT on CAPACITY_GATE_FAIL).
  4. build_sync_cmd(entity)                   -> build an aws s3 sync command per entity (only builds strings, run through the runner; tests use a fake runner).
  5. freeze_snapshot(...)                     -> per-shard SHA -> Merkle -> snapshot_manifest.json -> COMMIT (snapshot_freeze).
  6. canonical_map_from_csv_bytes(...)        -> replay the legacy merged_ids to find roots -> canonical_id_map 4-key rows (merged_ids).

Dependency-injected runner (DI runner):
  - Runner = Callable[[Sequence[str]], bytes] (same signature as s3_sync.Runner).
  - The real subprocess runner (subprocess_runner) is for operations; tests inject a fake runner -> no network, no S3.
  - If the capacity gate blocks -> raise CapacityGateError (the caller exits on CAPACITY_GATE_FAIL=16); fetching never continues silently.

Byte-contract alignment (key point):
  The official_manifests that capacity_gate.real_byte_gate consumes looks like
    {entity: {'meta': {'content_length', 'record_count'}}}  <- one "manifest view" per entity;
  but verified on the real service, OpenAlex has only one top-level manifest.json, which contains entities[].content_length / record_count
    (there is no per-entity manifest; a per-entity URL -> 404).
  fetch_official_manifest_view splits the top-level manifest's entities[] per entity into that view, then feeds capacity_gate.

Neutral about identification choices: orchestration / command construction / the capacity gate / reproducibility evidence are engineering plumbing.
  merged_ids replay is a cross-cutting mechanism for "which id is canonical" and is equally neutral.
"""
from __future__ import annotations

import subprocess
from typing import Any, Callable, Iterable, Mapping, Sequence

# --- U0 code registry (named constants, never bare numbers) ---
from identity.exit_codes import CAPACITY_GATE_FAIL

# --- M0 sibling modules (command construction / capacity gate / freeze / merge replay) ---
from m0_snapshot import capacity_gate as CAP
from m0_snapshot import merged_ids as MID
from m0_snapshot import s3_sync as S3
from m0_snapshot import snapshot_freeze as FREEZE

# Injected runner signature (same as s3_sync.Runner): takes a command list -> returns stdout bytes.
# The real implementation uses subprocess; tests inject a fake runner, no network, no S3.
Runner = Callable[[Sequence[str]], bytes]

# Keys that each per-entity manifest view must contain, as expected by capacity_gate.real_byte_gate / the view's consumers.
_ENTITY_VIEW_META_KEYS: tuple[str, str] = ("content_length", "record_count")


# ===========================================================================
# Exceptions
# ===========================================================================
class CapacityGateError(Exception):
    """The capacity gate before fetching did not pass (any check failed).

    The caller maps this to an exit on CAPACITY_GATE_FAIL=16; fetching never continues silently (with insufficient
    or unmounted disk, a forced 639GB+ download would fill the disk / write to the wrong place). Carries the fails list + per-check diagnostics.
    """

    def __init__(self, gate_result: Mapping[str, Any]) -> None:
        self.gate_result = dict(gate_result)
        self.fails = list(gate_result.get("fails", []))
        self.exit_code = CAPACITY_GATE_FAIL
        super().__init__(
            f"取数前容量门未过 (exit {CAPACITY_GATE_FAIL}): fails={self.fails}"
        )


# ===========================================================================
# Real subprocess runner (for operations; tests inject a fake runner -> nothing really runs)
# ===========================================================================
def subprocess_runner(cmd: Sequence[str]) -> bytes:
    """Real runner: run the command with subprocess and take stdout bytes (operations path; the orchestration tests do not call it).

    Non-zero exit -> CalledProcessError fails loudly (a failed fetch is never silently downgraded to 0 shards).
    This function is for the vertical slice / real runs; fixture-based orchestration tests inject a fake runner instead, with no network.
    """
    completed = subprocess.run(
        list(cmd),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


# ===========================================================================
# Byte-contract alignment — top-level manifest.entities[] -> per-entity capacity views
# ===========================================================================
def fetch_official_manifest_view(
    manifest_obj: Mapping[str, Any],
    *,
    entities: Iterable[str] | None = None,
) -> dict[str, dict[str, dict[str, int]]]:
    """Split the top-level manifest's entities[] into the per-entity views that capacity_gate consumes. Key point.

    Argument manifest_obj = the top-level manifest dict returned by s3_sync.fetch_official_manifest
      (verified shape: {date, format, meta, entities:[{entity, record_count, content_length, files:[...]}, ...]}).
    entities = the subset of entities to include in the capacity gate (None -> all entities; usually the three S3.SYNC_ENTITIES).

    Returns the shape that capacity_gate.real_byte_gate / snapshot_capacity_gate(official_manifests=...) expects:
      {entity: {'meta': {'content_length': <int>, 'record_count': <int>}}}
    -- one "manifest view" per entity, with root meta.content_length = the entity's total compressed bytes (= entities[i].content_length).

    Why this adapter is needed (byte-contract alignment):
      capacity_gate was designed for "one manifest per entity"; verified on the real service, OpenAlex has only one top-level
      manifest.json containing entities[] (no per-entity manifest -> 404). Here the top-level entities[] is split per entity into
      content_length / record_count and wrapped into the view capacity_gate understands, bridging the two shapes.

    A missing entity / an entity missing content_length or record_count -> reuses s3_sync._entity_entry and raises an error naming what is missing
      (never silently counted as 0 bytes, or the capacity gate would falsely pass).
    """
    if entities is None:
        # None -> all entities that appear in the top-level manifest (manifest order kept, deterministic).
        target_entities = [ent["entity"] for ent in manifest_obj["entities"]]
    else:
        target_entities = list(entities)

    view: dict[str, dict[str, dict[str, int]]] = {}
    for entity in target_entities:
        # Reuse s3_sync's entity lookup (missing entity / missing content_length -> ManifestShapeError naming what is missing, not silent).
        content_length = S3.remote_bytes_from_manifest(entity, manifest_obj=manifest_obj)
        entry = S3._entity_entry(entity, manifest_obj)
        if "record_count" not in entry:
            raise S3.ManifestShapeError(
                f"entity {entity!r} lacks record_count — the split capacity view needs it (refusing to proceed silently)"
            )
        view[entity] = {
            "meta": {
                "content_length": int(content_length),
                "record_count": int(entry["record_count"]),
            }
        }
    return view


# ===========================================================================
# Capacity gate (if any check fails -> CapacityGateError; the caller exits on CAPACITY_GATE_FAIL)
# ===========================================================================
def run_capacity_gate(
    cfg: Mapping[str, Any],
    *,
    official_manifests: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the capacity gate before fetching (a thin wrapper of capacity_gate.snapshot_capacity_gate); not passed -> raise CapacityGateError.

    cfg = capacity-gate arguments (snapshot_root_mounted / _free_bytes / _min_tb / est_derived_bytes / ...,
      supplied by config; numeric thresholds are not guessed by this module).
    official_manifests = the per-entity views produced by fetch_official_manifest_view (if given, the real-byte gate is added).

    capacity_gate.snapshot_capacity_gate only returns a verdict and does not exit; run_m0 turns "not passed" into a raise
      (the caller / operations thin shell exits on CAPACITY_GATE_FAIL=16); fetching never continues silently.
    Passed -> returns the gate verdict dict (passed=True + per-check diagnostics).
    """
    result = CAP.snapshot_capacity_gate(cfg, official_manifests=official_manifests)
    if not result["passed"]:
        raise CapacityGateError(result)
    return result


# ===========================================================================
# s3 sync command construction (only builds strings; run through the injected runner — tests use a fake runner, no real download)
# ===========================================================================
def build_sync_plan(
    *,
    snapshot_root: str,
    entities: Sequence[str] = S3.SYNC_ENTITIES,
    dryrun: bool = False,
) -> list[list[str]]:
    """Build an aws s3 sync command list per entity (pure command construction, nothing really runs).

    Returns [[aws,s3,sync,...], ...] -- one per entity; entity not in SYNC_ENTITIES -> ValueError (guarded by s3_sync).
    The source path includes the jsonl/ level (verified) + the anonymous-access flag, all handled by s3_sync.build_sync_cmd.
    """
    return [
        S3.build_sync_cmd(entity, snapshot_root=snapshot_root, dryrun=dryrun)
        for entity in entities
    ]


def execute_sync_plan(plan: Sequence[Sequence[str]], *, runner: Runner) -> list[bytes]:
    """Run the sync commands one by one with the injected runner, and return the list of each command's stdout bytes.

    Tests inject a fake runner (it records the commands called + returns fake stdout) -> no network, no S3.
      Real runs use subprocess_runner (for operations). If the runner raises, it is passed through (a failed fetch is not swallowed).
    """
    return [runner(cmd) for cmd in plan]


# ===========================================================================
# merged_ids replay -> canonical_id_map (per entity; the injected runner provides the decompressed .gz bytes)
# ===========================================================================
def build_canonical_id_map(
    merged_csv_by_entity: Mapping[str, bytes | str],
) -> list[dict[str, Any]]:
    """Replay the legacy merged_ids to find roots -> canonical_id_map 4-key rows (works/authors/institutions).

    Argument merged_csv_by_entity = {entity: decompressed merged_ids CSV bytes/text}
      (run_m0 decompresses legacy merged_ids/<entity>/*.csv.gz with snapshot_reader/gzip and feeds it here;
       tests feed fixture CSV bytes directly).
    Per entity it calls merged_ids.canonical_map_from_csv_bytes (parse + U0 replay_merged_ids to find roots +
      assert_matches_schema to enforce the 4 keys). A merge cycle -> ValueError passed through (never loops forever).
    Returns the combined list of canonical_id_map rows (for M1 canonical_id.py / HashBucketWriter to write as parquet).
    """
    rows: list[dict[str, Any]] = []
    for entity, blob in merged_csv_by_entity.items():
        rows.extend(MID.canonical_map_from_csv_bytes(blob, entity=entity))
    return rows


# ===========================================================================
# Top-level assembly: run_m0_snapshot (end-to-end orchestration; injected runner, a fake runner in tests)
# ===========================================================================
def run_m0_snapshot(
    *,
    cfg: Mapping[str, Any],
    snapshot_root: str,
    runner: Runner,
    entities: Sequence[str] = S3.SYNC_ENTITIES,
    merged_csv_by_entity: Mapping[str, bytes | str] | None = None,
    do_sync: bool = True,
    do_freeze: bool = True,
    freeze_kwargs: Mapping[str, Any] | None = None,
    dryrun: bool = False,
) -> dict[str, Any]:
    """M0 snapshot end-to-end assembly: manifest -> views -> capacity gate -> sync commands -> freeze -> canonical_id_map.

    Call order (invariants guarded):
      1. fetch_official_manifest(runner)         get the single top-level manifest.json (s3_sync; bad bytes raise).
      2. fetch_official_manifest_view(manifest)  byte-contract alignment -> per-entity capacity views.
      3. run_capacity_gate(cfg, view)            capacity gate (must come before sync; not passed -> CapacityGateError HALT).
      4. build_sync_plan + execute_sync_plan     build the commands per entity + run them through the injected runner (a fake runner in tests).
      5. freeze_snapshot(...)                     per-shard SHA -> Merkle -> snapshot_manifest -> COMMIT.
      6. build_canonical_id_map(...)              replay merged_ids to find roots -> canonical_id_map rows.

    Arguments:
      cfg                  capacity-gate arguments (from config; numeric thresholds are not guessed by this module).
      snapshot_root        root of the frozen read-only area (sync target + freeze source; a tmp_path in tests, nothing is written to the real SSD).
      runner               injected runner (fetches the manifest + runs sync); tests inject a fake runner, no network.
      entities             entities to include (default: the three S3.SYNC_ENTITIES).
      merged_csv_by_entity {entity: decompressed merged_ids CSV bytes}; None -> canonical_id_map is not built.
      do_sync / do_freeze  switches (a slice may run only some steps; freezing needs real .gz files on disk, so fixture orchestration tests usually turn freeze off).
      freeze_kwargs        passed through to freeze_snapshot: release_date/max_updated_date/topics_version etc.
      dryrun               append --dryrun to the sync commands (command-construction layer; does not affect whether anything really runs).

    Returns the assembly result dict:
      {manifest, manifest_view, capacity, sync_plan, sync_stdout, snapshot_manifest, canonical_id_map}
      -- keys of disabled steps are None / empty. If the capacity gate blocks, step 3 raises and no later step runs.
    """
    # 1. Get the top-level official manifest (the only manifest, verified; runner injected, bad bytes -> ManifestShapeError raise).
    manifest_obj = S3.fetch_official_manifest(snapshot_root=snapshot_root, runner=runner)

    # 2. Byte-contract alignment: top-level entities[] -> per-entity capacity views.
    manifest_view = fetch_official_manifest_view(manifest_obj, entities=entities)

    # 3. Capacity gate — must come before sync (not passed -> CapacityGateError HALT; a forced 639GB+ download never continues silently).
    capacity = run_capacity_gate(cfg, official_manifests=manifest_view)

    # 4. Build the s3 sync commands + run them through the injected runner (a fake runner in tests, no real S3 download).
    sync_plan: list[list[str]] | None = None
    sync_stdout: list[bytes] | None = None
    if do_sync:
        sync_plan = build_sync_plan(
            snapshot_root=snapshot_root, entities=entities, dryrun=dryrun
        )
        sync_stdout = execute_sync_plan(sync_plan, runner=runner)

    # 5. Freeze (per-shard SHA -> Merkle -> snapshot_manifest -> COMMIT).
    #    Needs real .gz files on disk; fixture orchestration tests usually use do_freeze=False (snapshot_freeze has its own independent tests).
    snapshot_manifest: dict[str, Any] | None = None
    if do_freeze:
        fk = dict(freeze_kwargs or {})
        snapshot_manifest = FREEZE.freeze_snapshot(
            snapshot_root, entities=entities, **fk
        )

    # 6. merged_ids replay -> canonical_id_map (built only if CSVs are given).
    canonical_id_map: list[dict[str, Any]] | None = None
    if merged_csv_by_entity is not None:
        canonical_id_map = build_canonical_id_map(merged_csv_by_entity)

    return {
        "manifest": manifest_obj,
        "manifest_view": manifest_view,
        "capacity": capacity,
        "sync_plan": sync_plan,
        "sync_stdout": sync_stdout,
        "snapshot_manifest": snapshot_manifest,
        "canonical_id_map": canonical_id_map,
    }
