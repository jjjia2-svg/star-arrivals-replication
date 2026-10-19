"""M0-6 zenodo_anchor — snapshot release reproducibility-anchor slot + Zenodo DOI backfill + re-seal COMMIT.

  - Release version anchor (for reproducibility): from the snapshot_manifest.json written by M0-2, extract a stable reproducibility identity
    (merkle_root / sync_date / max_updated_date / s3_etag / topics_version) -> an anchor dict;
    merging/reproduction first compares this tuple, and any drift means it is not the same snapshot.
  - zenodo_doi placeholder: initially None (a placeholder, to be backfilled after the real m0 publication; same discipline as the other
    "backfill after m0" placeholders; a DOI value is never invented).
  - backfill_zenodo_doi: write the real DOI into snapshot_manifest.json -> recompute its own sha (U0 sha256_file) ->
    so that re-seal puts the DOI-containing manifest's own sha under COMMIT protection (the anchor is protected after filling).
  - reseal_commit: uses the U0 write_dataset_commit two-phase COMMIT (stage->commit); a signed rule_version
    goes to _frozen/ -> dataset_is_valid; one containing unsigned stays in staging (sign-off isolation).

Consumes (built in U0): common/manifest.{write_dataset_commit, sha256_file};
  common/atomic_io.atomic_write_bytes (NOT atomic_write_json — the JSON is dumped -> encoded -> atomic_write_bytes here).
Neutral about identification choices: pure local writes + sha; no network, no real DOI minting (real publication is left to the operations script; this module only takes a DOI string to backfill).
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Mapping

from common import atomic_io
from common import manifest as _u0_manifest

# The logical name of snapshot_manifest.json in the COMMIT payload (its own sha is put under header protection via write_dataset_commit).
SNAPSHOT_MANIFEST_NAME: str = "snapshot_manifest.json"

# DOI placeholder strings (none of these counts as a real DOI; backfilling with one = locking the slot without filling it, which is rejected).
_PLACEHOLDER_DOI_TOKENS: frozenset[str] = frozenset(
    {"", "none", "null", "placeholder", "pending", "tbd", "todo", "xxx"}
)


# =============================================================================
# Release version anchor — extract a stable reproducibility identity (merging/reproduction compares against it)
# =============================================================================

def build_release_anchor(snapshot_manifest_obj: Mapping[str, Any]) -> dict[str, Any]:
    """Extract the release reproducibility anchor from snapshot_manifest (a stable four-part identity + the DOI slot status).

    Argument = the parsed snapshot_manifest.json written by M0-2 (with merkle_root / openalex_release /
      topics_version / zenodo_doi).
    A missing openalex_release block -> raise an error naming it (the reproducibility anchor must not lack the snapshot identity; not silently passed).
    Returns the anchor dict:
      {merkle_root, sync_date, max_updated_date, s3_etag, topics_version, zenodo_doi, doi_pending}.
      doi_pending = (zenodo_doi is still a placeholder) -> a reminder that it has not been backfilled (becomes False after the m0 backfill).
    """
    if "openalex_release" not in snapshot_manifest_obj:
        raise ValueError(
            "build_release_anchor: snapshot_manifest lacks the openalex_release block — "
            "the reproducibility anchor needs the snapshot identity (sync_date/s3_etag); refusing to pass silently"
        )
    release = snapshot_manifest_obj["openalex_release"]
    if "merkle_root" not in snapshot_manifest_obj:
        raise ValueError("build_release_anchor: snapshot_manifest lacks merkle_root (freeze proof)")

    doi = snapshot_manifest_obj.get("zenodo_doi")
    return {
        "merkle_root": snapshot_manifest_obj["merkle_root"],
        "sync_date": release.get("sync_date"),
        "max_updated_date": release.get("max_updated_date"),
        "s3_etag": release.get("s3_etag"),
        "topics_version": snapshot_manifest_obj.get("topics_version"),
        "zenodo_doi": doi,
        "doi_pending": _is_placeholder_doi(doi),
    }


def _is_placeholder_doi(doi: Any) -> bool:
    """Whether the DOI is still a placeholder (None / empty / a placeholder string). A placeholder is treated as awaiting backfill."""
    if doi is None:
        return True
    if not isinstance(doi, str):
        return False
    return doi.strip().lower() in _PLACEHOLDER_DOI_TOKENS


# =============================================================================
# DOI backfill — write into snapshot_manifest.json + recompute its own sha
# =============================================================================

def backfill_zenodo_doi(
    manifest_path: pathlib.Path | str,
    *,
    doi: Any,
) -> dict[str, Any]:
    """Write the real Zenodo DOI into snapshot_manifest.json -> atomic write back -> recompute its own sha.

    manifest_path: path of the snapshot_manifest.json written by M0-2.
    doi: the real DOI string (e.g. "10.5281/zenodo.1234567"); it must be supplied as a real value by the operations script / maintainer,
         and this module never invents one. Empty string / None / a placeholder string -> raise (refuses to lock the slot with a fake fill).
    Returns {sha_before, sha_after, doi}: the sha is computed by U0 sha256_file; if the content changes, sha_after != sha_before.

    Written the C-C way: json.dumps(sort_keys, indent=2).encode -> atomic_io.atomic_write_bytes
      (sort_keys keeps it deterministic; does not rely on the non-existent atomic_write_json).
    """
    if _is_placeholder_doi(doi):
        raise ValueError(
            f"backfill_zenodo_doi: refusing to backfill with a placeholder/empty DOI (got {doi!r}) — "
            "the real DOI must come from the operations script or the author, this module does not invent one (a placeholder in the slot = a fake fill)"
        )

    path = pathlib.Path(manifest_path)
    sha_before = _u0_manifest.sha256_file(path)

    obj = json.loads(path.read_text(encoding="utf-8"))
    obj["zenodo_doi"] = doi

    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8")
    atomic_io.atomic_write_bytes(path, blob)

    sha_after = _u0_manifest.sha256_file(path)
    return {"sha_before": sha_before, "sha_after": sha_after, "doi": doi}


# =============================================================================
# re-seal COMMIT — put the DOI-containing manifest's own sha under COMMIT protection (via the U0 two-phase flow)
# =============================================================================

def reseal_commit(
    commit_root: pathlib.Path | str,
    manifest_path: pathlib.Path | str,
    *,
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    """Re-seal the snapshot_manifest.json (with the DOI backfilled) into COMMIT, so the reproducibility anchor is itself protected.

    Uses the U0 common.manifest.write_dataset_commit two-phase flow:
      payload = {SNAPSHOT_MANIFEST_NAME: <manifest bytes>} -> .stage() -> .commit().
      The committer header's dataset_merkle is computed from those bytes (its own sha is protected); a signed rule_version ->
      promoted to _frozen/ -> dataset_is_valid; one containing unsigned -> stays in staging (sign-off isolation).

    provenance: the PROVENANCE_KEYS four-tuple (source_snapshot_merkle/config_sha/rule_version/stars_set_hash);
      supplied by the m0 caller, not invented here (in particular, the rule_version sign-off state decides whether it lands in _frozen/).
    Returns {committed:True, signed:bool}.
    """
    path = pathlib.Path(manifest_path)
    manifest_bytes = path.read_bytes()

    committer = _u0_manifest.write_dataset_commit(
        pathlib.Path(commit_root),
        {SNAPSHOT_MANIFEST_NAME: manifest_bytes},
        provenance=provenance,
    )
    committer.stage().commit()
    # signed is decided by rule_version (the same U0 rule: containing "unsigned" means not signed -> only staging).
    # Derived from provenance directly, without reading the committer's private attributes (the public surface is enough).
    rule_version = str(provenance.get("rule_version", ""))
    signed = "unsigned" not in rule_version.lower()
    return {"committed": True, "signed": signed}
