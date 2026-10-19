"""Single source of truth for the registry + org-URL/country checks + the build_registry_by_id adapter (P-2).

In plain words: the institution registry (the OpenAlex institution ids we accept as legitimate canonical
institutions) is the "second-argument authority table" of fold_to_canonical. This module reads it from
disk and enforces the invariant (no-empty-openalex_id) at load time. A bad registry is never let through
silently (a bad index key makes everything downstream drift).

Responsibilities:
  - load_validated_registry(path): read from disk + validate the invariant (the **only** place that touches
    disk; a pure function, no network). Enforces no-empty-openalex_id: any record whose openalex_id is
    missing/None/empty string raises at load time.
  - build_registry_by_id(registry): index the validated list as {openalex_id : record} (in memory, no IO).
    The index key is pinned to record["openalex_id"] (not id); same implementation as identity.constants,
    shared by U3/U4; no per-caller .get() fallbacks (the D1 drift point).

Carrier format (fidelity version): registry JSON top level = {"institutions": [{openalex_id, ...}, ...]}.
load strips the top-level wrapper and returns only the institutions list.
"""
from __future__ import annotations

import json
import pathlib
from typing import List, Union

# P-2: build_registry_by_id is the same implementation as the identity constants layer (U3/U4 share one
# adapter; two drifting implementations are forbidden). Re-exported here, not written a second time.
from identity.constants import build_registry_by_id  # noqa: F401  (re-export)

__all__ = [
    "EmptyOpenalexIdError",
    "build_registry_by_id",
    "load_validated_registry",
]


class EmptyOpenalexIdError(Exception):
    """A registry record has a missing/None/empty openalex_id -> raised at load time (no-empty-openalex_id).

    Never let it through silently: a bad index key makes build_registry_by_id index an empty key or drop a
    record, so the second argument of fold_to_canonical splits into two meanings -> the modal-institution
    method and the arrival decision all drift downstream (the D1 drift point).
    """


def load_validated_registry(
    path: Union[str, pathlib.Path]
) -> List[dict]:
    """Read the fidelity-version registry JSON, enforce no-empty-openalex_id, and return the institutions list.

    Args: path: registry JSON path, top level {"institutions": [...]} (a bare top-level list is also accepted).
    Returns: the institutions record list (each record has a non-empty "openalex_id").
    Raises:
      - EmptyOpenalexIdError: any record's openalex_id is missing/None/empty string (raised at load).
      - FileNotFoundError / json.JSONDecodeError: read / parse failure (never silently falls back to an empty list).

    The only place that touches disk (a pure function otherwise, no network): just open + json.load + validate, no HTTP.
    """
    p = pathlib.Path(path)
    with open(p, "r", encoding="utf-8") as fh:
        loaded = json.load(fh)

    # The fidelity version has {"institutions":[...]} at the top level; a bare top-level list is also accepted.
    if isinstance(loaded, dict):
        records = loaded.get("institutions")
        if records is None:
            raise ValueError(
                f"registry JSON is missing the top-level 'institutions' key: {p}"
            )
    elif isinstance(loaded, list):
        records = loaded
    else:
        raise ValueError(
            f"registry JSON top level must be a mapping or a list, got {type(loaded)!r}: {p}"
        )

    # no-empty-openalex_id: validate record by record at load; any bad id fails immediately (never let through silently).
    for idx, rec in enumerate(records):
        oa_id = rec.get("openalex_id") if isinstance(rec, dict) else None
        if not oa_id:  # None / missing key / empty string all land here
            raise EmptyOpenalexIdError(
                f"registry record[{idx}] has a missing/None/empty openalex_id: "
                f"{rec!r} (no-empty-openalex_id invariant, raised at load)."
            )

    return records
