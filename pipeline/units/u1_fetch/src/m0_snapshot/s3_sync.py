"""M0-1 s3_sync.py — build the aws s3 sync command for the full fetch + parse/save the top-level official manifest.

Scope (TDD of command construction): only builds command strings and parses the top-level manifest; never really downloads from S3.
The real sync / cp lives in the operations scripts; here are pure functions + an injected runner, so tests use no network.

=== Official usage (OpenAlex snapshot + manifest docs) ===
  Full snapshot: s3://openalex --no-sign-request is anonymous and free, refreshed quarterly, gzip JSONL <2GB,
  partitioned by updated_date=YYYY-MM-DD. Source: OpenAlex docs download-to-your-machine and snapshot-data-format.

=== Verified S3 paths (anonymous --no-sign-request run) ===
  Two differences from the original plan; the verified facts apply here:
  1. The path includes the jsonl/ level: the real path = s3://openalex/data/jsonl/<entity>/
       -> OPENALEX_DATA_PREFIX = "data/jsonl" (not the old "data").
  2. There is no per-entity manifest: the truth = a single top-level s3://openalex/data/jsonl/manifest.json,
       containing entities[].files[] (all entities); a per-entity manifest -> 404.
       -> fetch_official_manifest copies the top level once, then takes that entity's files[] from entities[];
         assert_manifest_shape validates the top-level {date,format,meta,entities[]} + that every file has url+meta.

=== Machine facts ===
  A 4TB external SSD (<SAR_SSD_MOUNT>, 3.6TiB free) is attached, with aws/pyarrow/boto3/duckdb installed;
  the snapshot is fetched with --no-sign-request, so no OpenAlex key is needed.
  Full works compressed is 639GB (manifest meta.content_length≈665688383258, 510372821 records),
  ~1.6TB uncompressed -> an external disk is required; the economics-filtered derived tables are much smaller, so 4TB suffices.

RED LINE placeholder (fetch strategy, not changed unilaterally): fetch strategy (a) full fetch to a >=2TB disk with a hard capacity gate,
  or (b) seed-subset filtering (--exclude '*' --include ...) -> this module defaults to (a) full; (b) must be chosen explicitly by a human.

Hard rules:
  - JSON is saved through common.atomic_io.atomic_write_bytes(blob) (C-C: atomic_io has no atomic_write_json).
  - Bad bytes / parse failure -> raise (never silently treated as "0 shards expected"; this was the root cause of the earlier Sydney 27k failure).
  - Every sys.exit uses the named constants of identity.exit_codes (this module does not exit during command construction).
"""
from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Sequence

from common.atomic_io import atomic_write_bytes

# ===========================================================================
# Constants (following the verified S3 path)
# ===========================================================================
OPENALEX_S3_BUCKET: str = "openalex"
# The verified path includes the jsonl/ level (see point 1 in the module docstring): s3://openalex/data/jsonl/<entity>/
OPENALEX_DATA_PREFIX: str = "data/jsonl"
# The three entity types (works/authors/institutions); the institutions canonical_id_map is produced by M0.
SYNC_ENTITIES: tuple[str, str, str] = ("works", "authors", "institutions")
# Anonymous-access flag (no key needed, no rate limit).
ANON_FLAG: str = "--no-sign-request"
# The verified file name of the single top-level manifest (see point 2 in the module docstring: a per-entity one would 404).
MANIFEST_OBJECT_NAME: str = "manifest.json"
# Keys each file's meta must contain (real remote bytes + record count, fed to the capacity gate + the reconcile check).
MANIFEST_FILE_META_KEYS: tuple[str, str] = ("record_count", "content_length")

# Injected runner signature: takes a command list -> returns stdout bytes (the real implementation uses subprocess; tests inject a fake runner).
Runner = Callable[[Sequence[str]], bytes]


# ===========================================================================
# Exceptions
# ===========================================================================
class ManifestShapeError(Exception):
    """The top-level official manifest has an invalid shape (missing entities / a file missing the url or meta key).

    Raise an error naming the missing key; never silently .get None as "0 shards expected" (the root cause of the earlier Sydney 27k failure).
    """


# ===========================================================================
# Command construction (pure functions; only builds strings, nothing really runs)
# ===========================================================================
def _entity_s3_uri(entity: str) -> str:
    """The entity's source prefix on S3: s3://openalex/data/jsonl/<entity>/ (includes jsonl/, verified)."""
    return f"s3://{OPENALEX_S3_BUCKET}/{OPENALEX_DATA_PREFIX}/{entity}/"


def _ensure_known_entity(entity: str) -> None:
    if entity not in SYNC_ENTITIES:
        raise ValueError(
            f"unknown entity {entity!r}; only {SYNC_ENTITIES} are allowed (gate 1: three types)."
        )


def build_sync_cmd(
    entity: str,
    *,
    snapshot_root: str,
    dryrun: bool = False,
) -> list[str]:
    """Build `aws s3 sync s3://openalex/data/jsonl/<entity>/ <snapshot_root>/<entity>/ --no-sign-request`.

    Pure command construction (nothing really runs): entity must be in SYNC_ENTITIES, otherwise ValueError.
    The source path includes the jsonl/ level (verified); the anonymous-access flag is always included; if dryrun is given, --dryrun is appended.
    Target = that entity's subdirectory under snapshot_root (the frozen read-only area is kept separate from derived).

    Official usage: full snapshot (s3://openalex --no-sign-request);
        for the verified path see point 1 in the module docstring.
    """
    _ensure_known_entity(entity)
    # Target local directory: <snapshot_root>/<entity>/ (spaces in the path are handled by the caller/shell layer; the list form needs no manual escaping).
    dest = f"{snapshot_root.rstrip('/')}/{entity}/"
    cmd = [
        "aws",
        "s3",
        "sync",
        _entity_s3_uri(entity),
        dest,
        ANON_FLAG,
    ]
    if dryrun:
        cmd.append("--dryrun")
    return cmd


def build_manifest_cp_cmd() -> list[str]:
    """Build `aws s3 cp s3://openalex/data/jsonl/manifest.json - --no-sign-request`.

    The verified single top-level manifest (see point 2 in the module docstring: a per-entity one would 404); cp to stdout (-) so it is easy to inject for parsing.
    Official usage, manifest section (one manifest per entity is the old description;
        verified: a single top-level file containing entities[]; enumerate in bulk from the manifest, do not glob yourself).
    """
    manifest_uri = f"s3://{OPENALEX_S3_BUCKET}/{OPENALEX_DATA_PREFIX}/{MANIFEST_OBJECT_NAME}"
    return ["aws", "s3", "cp", manifest_uri, "-", ANON_FLAG]


# ===========================================================================
# Top-level manifest shape validation + fetch (verified model: a single top-level file with entities[])
# ===========================================================================
def assert_manifest_shape(manifest_obj: Mapping[str, Any]) -> None:
    """Validate the top-level manifest shape {date, format, meta, entities[]}; every entity/file has url+meta.

    A missing required key -> raise ManifestShapeError naming the key (never a silent .get None).
    Per entity: has an entity name + files (list); per file: has url + meta{record_count,content_length}.
    """
    if not isinstance(manifest_obj, Mapping):
        raise ManifestShapeError(f"top-level manifest is not a dict: {type(manifest_obj)!r}")
    for root_key in ("date", "format", "meta", "entities"):
        if root_key not in manifest_obj:
            raise ManifestShapeError(f"top-level manifest lacks root key {root_key!r}")
    entities = manifest_obj["entities"]
    if not isinstance(entities, list) or not entities:
        raise ManifestShapeError("top-level manifest.entities must be a non-empty list")
    for ent in entities:
        if "entity" not in ent:
            raise ManifestShapeError("an entity item lacks the 'entity' name field")
        name = ent["entity"]
        files = ent.get("files")
        if not isinstance(files, list):
            raise ManifestShapeError(f"entity {name!r} lacks files (list)")
        for f in files:
            if "url" not in f:
                raise ManifestShapeError(f"entity {name!r} has a file without url")
            meta = f.get("meta")
            if not isinstance(meta, Mapping):
                raise ManifestShapeError(
                    f"entity {name!r} file {f['url']!r} lacks meta (dict)"
                )
            for mk in MANIFEST_FILE_META_KEYS:
                if mk not in meta:
                    raise ManifestShapeError(
                        f"entity {name!r} file {f['url']!r} has a meta lacking {mk!r} "
                        "— raise by name, never silently treat it as 0 parts to fetch"
                    )


def _entity_entry(entity: str, manifest_obj: Mapping[str, Any]) -> Mapping[str, Any]:
    """Take that entity's item from the top-level manifest.entities[]; absent -> raise (never return empty as 0 shards)."""
    for ent in manifest_obj.get("entities", []):
        if ent.get("entity") == entity:
            return ent
    raise ManifestShapeError(
        f"top-level manifest has no entity {entity!r}; available: "
        f"{[e.get('entity') for e in manifest_obj.get('entities', [])]}"
    )


def list_expected_shards(
    entity: str,
    *,
    manifest_obj: Mapping[str, Any],
) -> list[str]:
    """Get all shard .gz urls of the entity (external ground truth, fed to reconcile as the expected shard set).

    Taken from the top-level manifest.entities[entity].files[].url; entity absent -> raise (not treated as 0 shards).
    """
    entry = _entity_entry(entity, manifest_obj)
    files = entry.get("files")
    if not isinstance(files, list):
        raise ManifestShapeError(f"entity {entity!r} lacks files (list)")
    return [f["url"] for f in files]


def remote_bytes_from_manifest(
    entity: str,
    *,
    manifest_obj: Mapping[str, Any],
) -> int:
    """Get the entity's remote total bytes = entities[entity].content_length (ground truth, not an estimate).

    Uses the entity-level content_length, not the top-level meta.content_length (that is the total over all entities).
    """
    entry = _entity_entry(entity, manifest_obj)
    if "content_length" not in entry:
        raise ManifestShapeError(f"entity {entity!r} lacks content_length")
    return int(entry["content_length"])


def fetch_official_manifest(
    *,
    snapshot_root: str,
    runner: Runner,
) -> dict:
    """Get the top-level official manifest: the injected runner fetches the bytes -> save as reproducibility evidence -> json.loads -> shape validation.

    Verified single top-level file: cp the top-level manifest.json once (build_manifest_cp_cmd).
    runner(cmd) -> bytes (the real implementation uses subprocess to take stdout; tests inject a fake runner, no network).
    Saved as: atomic_write_bytes(<snapshot_root>/manifest.json, blob) — reproducibility evidence (C-C: no atomic_write_json, use bytes).
    Bad bytes / parse failure -> raise (never silently treated as "0 shards expected").
    """
    cmd = build_manifest_cp_cmd()
    blob = runner(cmd)
    if not isinstance(blob, (bytes, bytearray)):
        raise ManifestShapeError(
            f"runner should return bytes, got {type(blob)!r} — a failed manifest fetch must not degrade silently"
        )
    # Save the reproducibility evidence (write the raw bytes first, then parse; evidence is kept even if parsing fails).
    from pathlib import Path

    target = Path(snapshot_root) / MANIFEST_OBJECT_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(target, bytes(blob))
    # Parse + shape validation (bad bytes -> JSONDecodeError raised, not swallowed).
    try:
        manifest_obj = json.loads(bytes(blob).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ManifestShapeError(
            f"top-level manifest bytes are not valid JSON: {exc} — never treat it as 0 parts to fetch"
        ) from exc
    assert_manifest_shape(manifest_obj)
    return manifest_obj
