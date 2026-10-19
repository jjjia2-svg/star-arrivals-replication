"""Single entry point for thresholds / identification rules — import reads contracts/redlines.yaml into a literal dict RED.

Implementation:
  - The YAML lives in contracts/redlines.yaml; this module safe_loads it once at import into the RED dict.
  - identity-layer functions only `from common._redlines import RED` / `require(...)` to get literals,
    and never touch the disk at run time ("identity zero IO" = zero IO at call time; the disk is read only once, at import of this module).
  - RED is the only source of thresholds; no module may hard-code identification values.

Two hard rules:
  1. An unset red-line key = None (null); reading None through require() → raise RedlineUnsigned,
     never silently defaulting. Placeholders for identification values are set by a person, never decided by code.
  2. The preflight environment gate (3) compares the SHA of RED with that of safe_load(YAML) (sha256_of_red /
     sha256_of_yaml_file are provided for it); any mismatch → HALT.

Note: this module only exposes threshold literals + value guards; it invents no identification values.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

import yaml

# contracts/ sits under the multiplex_pipeline/ root.
# path of this file = multiplex_pipeline/units/u0_foundation/src/common/_redlines.py
# parents: [0]=common [1]=src [2]=u0_foundation [3]=units [4]=multiplex_pipeline
_PIPELINE_ROOT = pathlib.Path(__file__).resolve().parents[4]
REDLINES_YAML: pathlib.Path = _PIPELINE_ROOT / "contracts" / "redlines.yaml"


class RedlineUnsigned(Exception):
    """Raised when an unset red-line key (value None) is read — never silently returns a default/None."""


def _load_red() -> dict[str, Any]:
    """Read the YAML once at import into a literal dict. Raise on failure (never silently fall back to an empty dict)."""
    with open(REDLINES_YAML, "r", encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
    if not isinstance(loaded, dict):
        raise ValueError(f"redlines.yaml top level must be a mapping, got {type(loaded)!r}")
    return loaded


# ★literal threshold dict — fixed once at import; downstream uses from common._redlines import RED.
RED: dict[str, Any] = _load_red()


def require(section: str, key: str | None = None) -> Any:
    """Fetch a threshold from RED; on None (unset placeholder) → raise RedlineUnsigned, on a missing key → KeyError.

    Usage:
        require("cohort", "same_gen_max_gap_years")  # → 5
        require("education_whitelist")               # top-level scalar/list key: → ["education"]
        require("entity_resolve", "score_threshold") # unset → raise RedlineUnsigned

    Hard rules:
      - Misspelled key / missing section → KeyError (it must blow up, no silent fallback).
      - Value is None (red-line placeholder) → RedlineUnsigned (never silently default).
      - Value is not None → returned as is (require only blocks None, not real values).
    """
    node = RED[section]  # missing section → KeyError (intended)
    if key is None:
        value = node
    else:
        if not isinstance(node, dict):
            raise KeyError(
                f"redlines section {section!r} is not a mapping, cannot read sub-key {key!r}"
            )
        value = node[key]  # missing sub-key → KeyError (intended)

    if value is None:
        raise RedlineUnsigned(
            f"red-line key {section}" + (f".{key}" if key else "")
            + " has no value (null) — it must be supplied in the red-line table; the code never substitutes a default."
        )
    return value


def is_signed(section: str, key: str | None = None) -> bool:
    """Whether this red-line key is set (present and not None). A missing key returns False, no raise."""
    try:
        node = RED[section]
        value = node if key is None else node[key]
    except (KeyError, TypeError):
        return False
    return value is not None


def _canonical_blob(obj: Any) -> bytes:
    """Deterministic serialization (sort_keys + compact separators), for SHA comparison."""
    return json.dumps(
        obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def sha256_of_red() -> str:
    """Deterministic SHA256 of the RED literal dict (used by preflight environment gate 3)."""
    return hashlib.sha256(_canonical_blob(RED)).hexdigest()


def sha256_of_yaml_file(path: pathlib.Path | str | None = None) -> str:
    """Deterministic SHA256 of contracts/redlines.yaml after safe_load (compared with RED for consistency)."""
    p = pathlib.Path(path) if path is not None else REDLINES_YAML
    with open(p, "r", encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
    return hashlib.sha256(_canonical_blob(loaded)).hexdigest()


def red_matches_yaml(path: pathlib.Path | str | None = None) -> bool:
    """Whether the SHA of RED and of the YAML safe_load agree (guards against code and YAML drifting apart)."""
    return sha256_of_red() == sha256_of_yaml_file(path)
