"""M0-5 manifest_reconcile — parse the top-level manifest.json + reconcile expected shards == downloaded shards.

Verified on the real service (anonymous --no-sign-request run):
  OpenAlex's only manifest = the top-level s3://openalex/data/jsonl/manifest.json (there is NO per-entity manifest;
  s3://openalex/data/jsonl/works/manifest -> 404). The top-level manifest contains all entities, shaped:
    { "date":"YYYY-MM-DD", "format":"jsonl",
      "meta": {"record_count":N, "content_length":B},          # total over all entities
      "entities": [
        { "entity":"works", "record_count":n, "content_length":b,
          "files":[ {"url":"s3://openalex/data/jsonl/works/updated_date=.../part_NNNN.gz",
                     "meta":{"content_length":..,"record_count":..}}, ... ] },
        ... ] }
  -> an entity's shard list = files[] of the entities[] item whose entity matches (this module's files_for_entity).

Official usage (snapshot section):
  - s3://openalex --no-sign-request is anonymous and free; for each entity, enumerate in bulk "from the manifest, do not glob yourself".
  - Here "one manifest per entity" is corrected to "entities[].files[] of the single top-level manifest" (the verified shape).

Reconciliation rule:
  expected shard set (list_expected_shards) == downloaded .gz set; mismatch -> sys.exit(EXIT_RECONCILE_FAIL).
  EXIT_RECONCILE_FAIL maps to the existing U0 code TALLY_IMBALANCE=15 (U1 reuses the existing name and invents no number).
  A record_count mismatch is fed back to the conservation arm of U0 common.reconcile.reconcile_fetch (compute_expected_from_files).

Neutral about identification choices: this module only parses the manifest and reconciles shard completeness.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Iterable, Mapping, Sequence

# U0 code registry: EXIT_RECONCILE_FAIL = TALLY_IMBALANCE = 15 (mapped by name, no bare number).
from identity.exit_codes import TALLY_IMBALANCE as EXIT_RECONCILE_FAIL

# Keys every file's meta in the top-level manifest must have (missing -> raise an error naming the key, no silent .get None).
MANIFEST_FILE_META_KEYS: tuple[str, ...] = ("content_length", "record_count")
# Keys the root of the top-level manifest must have.
MANIFEST_TOP_KEYS: tuple[str, ...] = ("date", "format", "meta", "entities")
# Keys the top-level meta must have (total over all entities).
MANIFEST_TOP_META_KEYS: tuple[str, ...] = ("record_count", "content_length")
# Keys every entity item must have.
MANIFEST_ENTITY_KEYS: tuple[str, ...] = ("entity", "record_count", "content_length", "files")


# ===========================================================================
# Parsing + shape validation
# ===========================================================================
def parse_top_manifest(blob: bytes | str) -> dict[str, Any]:
    """Parse the bytes/text of the top-level manifest.json into a dict and validate its shape.

    blob = the real bytes saved by M0-1 fetch_official_manifest (reproducibility evidence), or a test fixture.
    Parse failure / wrong shape -> raise (never silently pass as "0 shards expected").
    """
    if isinstance(blob, bytes):
        text = blob.decode("utf-8")
    else:
        text = blob
    obj = json.loads(text)  # Invalid JSON -> JSONDecodeError fails loudly
    assert_manifest_shape(obj)
    return obj


def assert_manifest_shape(manifest_obj: Mapping[str, Any]) -> None:
    """Validate the top-level manifest shape: root {date,format,meta,entities[]} + files[] per entity + url+meta per file.

    Any missing key raises by name (KeyError carries the key name), no silent .get None — so a half-damaged
    manifest is not taken as "0 shards expected" and a whole batch of data is not missed.
    """
    if not isinstance(manifest_obj, Mapping):
        raise ValueError(f"manifest should be an object/dict, got {type(manifest_obj).__name__}")
    for key in MANIFEST_TOP_KEYS:
        if key not in manifest_obj:
            raise KeyError(f"top-level manifest lacks required key {key!r} (observed shape {MANIFEST_TOP_KEYS})")
    meta = manifest_obj["meta"]
    if not isinstance(meta, Mapping):
        raise ValueError("top-level manifest.meta should be an object")
    for key in MANIFEST_TOP_META_KEYS:
        if key not in meta:
            raise KeyError(f"top-level manifest.meta lacks {key!r}")
    entities = manifest_obj["entities"]
    if not isinstance(entities, Sequence) or isinstance(entities, (str, bytes)):
        raise ValueError("top-level manifest.entities should be a list")
    if len(entities) == 0:
        raise ValueError("top-level manifest.entities is empty — refusing to pass it as 0 entities")
    for ent in entities:
        _assert_entity_shape(ent)


def _assert_entity_shape(ent: Mapping[str, Any]) -> None:
    """Single entity item shape: {entity,record_count,content_length,files[]} + url+meta per file."""
    if not isinstance(ent, Mapping):
        raise ValueError("each entities[] item should be an object")
    for key in MANIFEST_ENTITY_KEYS:
        if key not in ent:
            raise KeyError(f"entities[] item lacks {key!r} (entity={ent.get('entity')!r})")
    files = ent["files"]
    if not isinstance(files, Sequence) or isinstance(files, (str, bytes)):
        raise ValueError(f"entities[{ent.get('entity')!r}].files should be a list")
    for f in files:
        if not isinstance(f, Mapping):
            raise ValueError("each files[] item should be an object")
        if "url" not in f:
            raise KeyError(f"files[] item lacks 'url' (entity={ent.get('entity')!r})")
        if "meta" not in f:
            raise KeyError(f"files[] item lacks 'meta' (url={f.get('url')!r})")
        fmeta = f["meta"]
        if not isinstance(fmeta, Mapping):
            raise ValueError(f"files[].meta should be an object (url={f.get('url')!r})")
        for mk in MANIFEST_FILE_META_KEYS:
            if mk not in fmeta:
                raise KeyError(f"files[].meta lacks {mk!r} (url={f.get('url')!r})")


# ===========================================================================
# Get files[] by entity (the only manifest is the top-level one; there is no per-entity manifest)
# ===========================================================================
def _entity_entry(manifest_obj: Mapping[str, Any], *, entity: str) -> Mapping[str, Any]:
    """From entities[], take the item whose entity matches; if absent -> KeyError (never silently return empty)."""
    for ent in manifest_obj["entities"]:
        if ent.get("entity") == entity:
            return ent
    available = [e.get("entity") for e in manifest_obj["entities"]]
    raise KeyError(f"top-level manifest.entities has no {entity!r}; available: {available}")


def files_for_entity(manifest_obj: Mapping[str, Any], *, entity: str) -> list[dict[str, Any]]:
    """Get an entity's files[] list (each item {url, meta{content_length,record_count}}).

    This is the only entry point for "an entity's shard list": OpenAlex has no per-entity manifest,
    so the shard list can only come from entities[].files[] of the top-level manifest.
    """
    return list(_entity_entry(manifest_obj, entity=entity)["files"])


def list_expected_shards(manifest_obj: Mapping[str, Any], *, entity: str) -> list[str]:
    """The list of .gz shard urls to fetch for this entity (manifest order kept -> deterministic, fed to the reconcile check)."""
    return [f["url"] for f in files_for_entity(manifest_obj, entity=entity)]


def remote_record_count_for_entity(manifest_obj: Mapping[str, Any], *, entity: str) -> int:
    """The entity's remote total record count = entities[entity].record_count (the real remote count, not a guess)."""
    return int(_entity_entry(manifest_obj, entity=entity)["record_count"])


def remote_bytes_for_entity(manifest_obj: Mapping[str, Any], *, entity: str) -> int:
    """The entity's remote total bytes = entities[entity].content_length (fed to the capacity gate real_byte_gate)."""
    return int(_entity_entry(manifest_obj, entity=entity)["content_length"])


def expected_record_count_from_files(manifest_obj: Mapping[str, Any], *, entity: str) -> int:
    """Conservation check: the sum of files[].meta.record_count (should == entities[entity].record_count)."""
    return sum(
        int(f["meta"]["record_count"])
        for f in files_for_entity(manifest_obj, entity=entity)
    )


# ===========================================================================
# Shard-completeness reconciliation (expected == downloaded; mismatch -> exit 15)
# ===========================================================================
def reconcile_shards(
    *,
    expected_urls: Iterable[str],
    present_urls: Iterable[str],
    tally_path: Any = None,
) -> dict[str, Any]:
    """Expected shard set == downloaded shard set; any missing/extra -> sys.exit(EXIT_RECONCILE_FAIL=15).

    Catches two whole-shard failures:
      - missing: expected but not downloaded (sync dropped a shard / hit the quarterly partition-write window) -> a whole batch of data is missing.
      - extra:   downloaded but not in the expected list (leftover from another release / path drift) -> dirty data mixed in.
    If balanced -> write the tally JSON (reproducibility evidence, written if a path is given) + return {balanced:True,...}.

    The exit code uses the named constant EXIT_RECONCILE_FAIL (=TALLY_IMBALANCE=15), never a bare number.
    """
    expected_set = set(expected_urls)
    present_set = set(present_urls)
    missing = expected_set - present_set
    extra = present_set - expected_set
    balanced = (len(missing) == 0 and len(extra) == 0)
    tally = {
        "stage": "m0_shard_reconcile",
        "expected": len(expected_set),
        "present": len(present_set),
        "missing_count": len(missing),
        "extra_count": len(extra),
        "balanced": balanced,
        "missing": sorted(missing),
        "extra": sorted(extra),
    }
    if tally_path is not None:
        _write_tally(tally_path, tally)
    if not balanced:
        sys.stderr.write(
            f"[m0_shard_reconcile] shard reconciliation does not balance: "
            f"missing={sorted(missing)} extra={sorted(extra)} — HALT (exit {EXIT_RECONCILE_FAIL})\n"
        )
        sys.exit(EXIT_RECONCILE_FAIL)
    return tally


def _write_tally(tally_path: Any, tally: Mapping[str, Any]) -> None:
    """Write the tally JSON (deterministic sort_keys); uses atomic_write_bytes to really flush to disk (C-C: there is no atomic_write_json)."""
    import pathlib

    from common.atomic_io import atomic_write_bytes

    blob = json.dumps(tally, sort_keys=True, ensure_ascii=False).encode("utf-8")
    atomic_write_bytes(pathlib.Path(tally_path), blob)
