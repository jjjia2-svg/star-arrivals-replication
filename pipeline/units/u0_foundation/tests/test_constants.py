"""TDD red tests for U0 constants.py.

Guards:
  - B.1: ENTITY_TO_IDTYPE is the single source of truth, exactly 5 keys (works/authors/institutions/sources/publishers).
  - C.2 + T31: the build_registry_by_id index key is pinned to record["openalex_id"] (not id);
    it is the second argument of fold_to_canonical; no .get() fallback (a silent empty value would split the index-key rule); pure function, no IO.
"""
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from identity import constants  # noqa: E402


# ============ B.1: ENTITY_TO_IDTYPE, exactly 5 keys ============

def test_entity_to_idtype_verbatim_five_keys():
    # exactly these 5 keys, character for character, never invented
    assert constants.ENTITY_TO_IDTYPE == {
        "works": "work",
        "authors": "author",
        "institutions": "institution",
        "sources": "source",
        "publishers": "publisher",
    }


def test_entity_to_idtype_exactly_five_entries():
    # exactly 5 entries; more or fewer is wrong
    assert len(constants.ENTITY_TO_IDTYPE) == 5


def test_entity_to_idtype_keys_set():
    assert set(constants.ENTITY_TO_IDTYPE.keys()) == {
        "works",
        "authors",
        "institutions",
        "sources",
        "publishers",
    }


# ============ C.2 / T31: build_registry_by_id index key = openalex_id ============

def test_build_registry_by_id_indexes_on_openalex_id():
    # T31: the index key is pinned to record["openalex_id"] (not id)
    registry = [
        {"openalex_id": "I56590836", "id": "https://openalex.org/I56590836", "display_name": "Monash"},
        {"openalex_id": "I161593684", "id": "https://openalex.org/I161593684", "display_name": "Stockholm"},
    ]
    out = constants.build_registry_by_id(registry)
    # key = the literal openalex_id, not the id field
    assert set(out.keys()) == {"I56590836", "I161593684"}
    # value = the whole record
    assert out["I56590836"]["display_name"] == "Monash"
    assert out["I161593684"]["display_name"] == "Stockholm"


def test_build_registry_by_id_value_is_whole_record():
    registry = [{"openalex_id": "I56590836", "type": "education", "extra": 42}]
    out = constants.build_registry_by_id(registry)
    assert out["I56590836"] == {"openalex_id": "I56590836", "type": "education", "extra": 42}


def test_build_registry_by_id_does_not_use_id_field_as_key():
    # Drift-point guard: never use id (the OpenAlex URL form) as the index key
    registry = [{"openalex_id": "I56590836", "id": "https://openalex.org/I56590836"}]
    out = constants.build_registry_by_id(registry)
    assert "https://openalex.org/I56590836" not in out
    assert "I56590836" in out


def test_build_registry_by_id_missing_openalex_id_raises_keyerror():
    # T31 rule: no .get() fallback; a missing openalex_id -> KeyError, fails loudly, never silently yields an empty value
    registry = [{"id": "https://openalex.org/I56590836"}]  # deliberately has no openalex_id
    try:
        constants.build_registry_by_id(registry)
        assert False, "a missing openalex_id should raise KeyError, not silently fall back"
    except KeyError:
        pass


def test_build_registry_by_id_empty_list_returns_empty_dict():
    assert constants.build_registry_by_id([]) == {}


def test_build_registry_by_id_is_pure_no_mutation():
    # pure function: does not modify its argument
    registry = [{"openalex_id": "I56590836", "type": "education"}]
    snapshot = [dict(r) for r in registry]
    constants.build_registry_by_id(registry)
    assert registry == snapshot
