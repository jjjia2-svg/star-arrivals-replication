"""identity constants layer: ENTITY_TO_IDTYPE + the build_registry_by_id adapter.

Pure constants + an in-memory index; no IO / no network / no state.
- ENTITY_TO_IDTYPE: the single source of truth mapping OpenAlex entity type -> id_type (exactly 5 keys).
  The U3 guard / canonical_id_map classification / the id_type argument of build_canonical_map all import it from here; bare literals are forbidden.
- build_registry_by_id: index a validated registry list into {openalex_id: record},
  to feed the second argument of fold_to_canonical.
"""
from typing import Dict, List


# --- Entity type -> id_type, the single source of truth (exactly 5 keys, never invent any) ---
ENTITY_TO_IDTYPE: Dict[str, str] = {
    "works": "work",
    "authors": "author",
    "institutions": "institution",
    "sources": "source",
    "publishers": "publisher",
}


def build_registry_by_id(registry: List[dict]) -> Dict[str, dict]:
    """Index a registry list into a {record["openalex_id"]: record} dict.

    Contract:
      - The index key is fixed = record["openalex_id"] (not record["id"], which is the OpenAlex URL form).
        Once fixed, U3/U4 import the same one and must not each add their own .get() fallback (silently producing empty values would split the index-key caliber and cause drift).
      - A pure function with no IO: reading from disk and the no-empty-openalex_id invariant check are the job of load_validated_registry
        (afid_verify.py); this function only builds the in-memory index and makes no network calls.
      - A missing openalex_id -> a loud KeyError (subscript record["openalex_id"], never a .get fallback).

    Argument: registry — the validated record list (each has at least "openalex_id").
    Returns: {openalex_id (bare, such as "I56590836"): the whole record}.
    """
    return {record["openalex_id"]: record for record in registry}
