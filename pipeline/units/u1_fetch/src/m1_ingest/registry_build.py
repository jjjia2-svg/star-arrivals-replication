"""M1 registry_build - build the education registry from the snapshot institutions entity (the registry input of run_m1_full).

registry = the "set of legal canonical education parent institutions" for fold_to_canonical (key domain = all education institutions,
foreign ones included, e.g. Stockholm), so that child institutions / foreign institutions on papers fold back to the parent university. This module:
  (1) build_education_registry(institutions): pure function - picks type in EDUCATION_WHITELIST and takes the fields;
  (2) discover_institution_shards / load_education_registry(snapshot_root): driver - streams the institutions
     shards -> reuses the pure function to filter -> de-duplicates across shards by openalex_id.

Neutral on identification choices: filters only by EDUCATION_WHITELIST + takes the fields build_registry_by_id needs (openalex_id) +
  readable fields (display_name/country_code). It does not decide arrival, does not decide staff status, touches no identification rule.
  The institutions entity is small (~428MB, 137 shards), unlike the 696GB works -> the education-subset registry is only a few MB,
  safe to load fully into memory.
"""
from __future__ import annotations

import glob
from pathlib import Path
from typing import Iterable

from common.inst_lineage import EDUCATION_WHITELIST
from m1_ingest._writer_util import bare


def _to_registry_record(inst: dict) -> dict:
    """institution -> registry record. Key openalex_id = the build_registry_by_id index key (bare);
    + display_name/country_code for people / operations (fold_to_canonical does not read these two, only the key domain)."""
    return {
        "openalex_id": bare(inst.get("id")),
        "type": inst.get("type"),
        "display_name": inst.get("display_name"),
        "country_code": inst.get("country_code"),
    }


def build_education_registry(institutions: Iterable[dict]) -> list[dict]:
    """Pick all institutions with type in EDUCATION_WHITELIST -> list of registry records (bare openalex_id).

    - None items skipped; a missing id (bare -> None) skipped (no key is invented);
    - includes foreign education (Stockholm etc.), no country filter (folding / arrival needs them);
    - pure function: no disk reads, no de-duplication (de-duplication happens across shards in load_education_registry).
    """
    out: list[dict] = []
    for inst in institutions:
        if not inst:
            continue
        if inst.get("type") not in EDUCATION_WHITELIST:
            continue
        rec = _to_registry_record(inst)
        if rec["openalex_id"] is None:
            continue
        out.append(rec)
    return out


def discover_institution_shards(snapshot_root) -> list[str]:
    """List all .gz shards under snapshot_root/institutions (recursive + sorted -> deterministic across machines/runs)."""
    root = Path(snapshot_root)
    return sorted(glob.glob(str(root / "institutions" / "**" / "*.gz"), recursive=True))


def load_education_registry(snapshot_root) -> list[dict]:
    """Stream the snapshot institutions shards -> education registry (reuses the pure-function filter + de-duplicates across shards by id, keeping the first seen).

    In an OpenAlex snapshot an institution normally appears once in one updated_date partition; de-duplication by openalex_id still guards against repeated partitions.
    Streaming: the institution rows are not all materialised; build_education_registry keeps only the education subset (a few MB).
    """
    from common.snapshot_reader import iter_jsonl_gz_shards

    shards = discover_institution_shards(snapshot_root)
    insts = (inst for _shard_id, inst in iter_jsonl_gz_shards(shards))
    seen: dict[str, dict] = {}
    for rec in build_education_registry(insts):
        if rec["openalex_id"] not in seen:
            seen[rec["openalex_id"]] = rec
    return list(seen.values())
