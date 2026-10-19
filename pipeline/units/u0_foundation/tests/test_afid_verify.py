"""TDD red tests for U0 afid_verify.py (P-2 + group 8 T31-T32).

Guards:
  - load_validated_registry(path): the registry is the single source of truth; enforces
    no-empty-openalex_id (load itself raises, an empty id is never silently let through);
    a pure function that makes no network call (reads disk + checks invariants only).
  - build_registry_by_id(registry) -> dict[str,dict]: the index key is pinned to record["openalex_id"]
    (not id); it is the second argument of fold_to_canonical; no .get() fallback (a drift point).

T31 build_registry_by_id index key = record["openalex_id"].
T32 load_validated_registry raises at load on an empty openalex_id (no-empty-openalex_id).

Carrier (registry JSON) = the fidelity layout, top level {institutions:[{openalex_id, ...}]}.
These tests are purely local with no network (load only reads disk).
"""
import json
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common.afid_verify import (  # noqa: E402
    EmptyOpenalexIdError,
    build_registry_by_id,
    load_validated_registry,
)


def _write_registry(tmp_path, institutions):
    """Write a fidelity-layout registry JSON (top level {institutions:[...]}) to tmp and return the path."""
    p = tmp_path / "registry.json"
    p.write_text(json.dumps({"institutions": institutions}), encoding="utf-8")
    return p


# ============ T32: load_validated_registry no-empty-openalex_id ============

def test_T32_load_raises_on_empty_openalex_id(tmp_path):
    # T32: a record whose openalex_id is an empty string -> load raises, never silently let through
    path = _write_registry(tmp_path, [
        {"openalex_id": "I56590836", "type": "education"},
        {"openalex_id": "", "type": "education"},  # empty id: must raise
    ])
    with pytest.raises(EmptyOpenalexIdError):
        load_validated_registry(path)


def test_T32b_load_raises_on_missing_openalex_id_key(tmp_path):
    # A missing openalex_id key altogether (None/absent) also violates no-empty -> load raises
    path = _write_registry(tmp_path, [
        {"openalex_id": "I56590836", "type": "education"},
        {"type": "education"},  # no openalex_id key
    ])
    with pytest.raises(EmptyOpenalexIdError):
        load_validated_registry(path)


def test_T32c_load_raises_on_none_openalex_id(tmp_path):
    path = _write_registry(tmp_path, [
        {"openalex_id": None, "type": "education"},  # explicit None
    ])
    with pytest.raises(EmptyOpenalexIdError):
        load_validated_registry(path)


def test_T32d_load_ok_when_all_ids_present(tmp_path):
    # all openalex_id non-empty -> returns the list normally
    path = _write_registry(tmp_path, [
        {"openalex_id": "I56590836", "type": "education", "display_name": "Monash"},
        {"openalex_id": "I161593684", "type": "education", "display_name": "Stockholm"},
    ])
    out = load_validated_registry(path)
    assert isinstance(out, list)
    assert len(out) == 2
    assert {r["openalex_id"] for r in out} == {"I56590836", "I161593684"}


def test_T32e_load_returns_record_list_not_wrapper(tmp_path):
    # load returns the institutions list (the fidelity top-level wrapper removed), not the whole {institutions:[...]}
    path = _write_registry(tmp_path, [
        {"openalex_id": "I56590836", "type": "education"},
    ])
    out = load_validated_registry(path)
    assert isinstance(out, list)
    assert out[0]["openalex_id"] == "I56590836"


# ============ T31: build_registry_by_id index key = openalex_id ============

def test_T31_build_registry_by_id_indexes_on_openalex_id():
    # T31: the index key is pinned to record["openalex_id"] (not id); it is the second argument of fold_to_canonical
    registry = [
        {"openalex_id": "I56590836", "id": "https://openalex.org/I56590836", "display_name": "Monash"},
        {"openalex_id": "I161593684", "id": "https://openalex.org/I161593684", "display_name": "Stockholm"},
    ]
    out = build_registry_by_id(registry)
    assert set(out.keys()) == {"I56590836", "I161593684"}
    assert out["I56590836"]["display_name"] == "Monash"


def test_T31b_build_registry_by_id_not_indexed_on_id_field():
    # Drift-point guard: never use id (the URL form) as the index key
    registry = [{"openalex_id": "I56590836", "id": "https://openalex.org/I56590836"}]
    out = build_registry_by_id(registry)
    assert "https://openalex.org/I56590836" not in out
    assert "I56590836" in out


def test_T31c_build_registry_by_id_missing_key_raises_keyerror():
    # No .get() fallback: a missing openalex_id -> KeyError, fails loudly (never silently yields an empty value)
    registry = [{"id": "https://openalex.org/I56590836"}]
    with pytest.raises(KeyError):
        build_registry_by_id(registry)


def test_T31d_build_registry_by_id_empty_list():
    assert build_registry_by_id([]) == {}


# ============ load -> build end to end (P-2 adapter chain) ============

def test_load_then_build_pipeline(tmp_path):
    # load_validated_registry(path) -> build_registry_by_id(...) end to end, feeding the second argument of fold_to_canonical
    path = _write_registry(tmp_path, [
        {"openalex_id": "I56590836", "type": "education", "display_name": "Monash"},
        {"openalex_id": "I161593684", "type": "education", "display_name": "Stockholm"},
    ])
    registry = load_validated_registry(path)
    by_id = build_registry_by_id(registry)
    assert set(by_id.keys()) == {"I56590836", "I161593684"}


def test_build_registry_by_id_is_same_impl_as_constants():
    # P-2: U3/U4 share one adapter: afid_verify.build_registry_by_id and identity.constants are the same implementation
    from identity import constants
    assert build_registry_by_id is constants.build_registry_by_id
