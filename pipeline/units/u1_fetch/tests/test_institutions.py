"""Tests for institutions.py.

Behaviour covered:
  1. flatten_institution: a dehydrated institution dict -> an INSTITUTIONS row with 7 columns
     {institution_id(bare), display_name, country_code, type, lineage,
      associated_institutions(list<dict>), ror}.
  2. Zenou's Stockholm institution I161593684 (country_code=SE) must land in the table with country_code
     present, so downstream (U3) can tell it is a foreign institution (is_foreign).
  3. The ARMI lineage chain is kept whole (the list is not flattened); Caulfield type=healthcare is written.
  4. associated_institutions stays list<dict> (fold_to_canonical path3 reads relationship/type/id);
     the ror column is present.
  5. iter_institutions: every authorships[].institutions[] of a work becomes a row (including foreign
     ones; no in_au filter at all).
  6. write_institutions: before writing, assert_matches_schema(.., INSTITUTIONS) must see exactly 7 keys.

Checks data shape only, with no identification choices; small fixtures, never a real download.
"""
import pathlib

import pytest

from m1_ingest.institutions import (
    flatten_institution,
    iter_institutions,
    write_institutions,
)
from common.schema import INSTITUTIONS


# Zenou slice fixture: Stockholm (foreign, SE) + ARMI (facility, lineage includes Monash) + Caulfield (healthcare)
STOCKHOLM = {
    "id": "https://openalex.org/I161593684",
    "display_name": "Stockholm University",
    "country_code": "SE",
    "type": "education",
    "lineage": ["https://openalex.org/I161593684"],
    "associated_institutions": [],
    "ror": "https://ror.org/05f0yyx03",
}
ARMI = {
    "id": "https://openalex.org/I2801239119",
    "display_name": "Australian Regenerative Medicine Institute",
    "country_code": "AU",
    "type": "facility",
    "lineage": [
        "https://openalex.org/I2801239119",
        "https://openalex.org/I56590836",  # Monash
    ],
    "associated_institutions": [
        {"id": "https://openalex.org/I56590836", "relationship": "parent", "type": "education"},
    ],
    "ror": "https://ror.org/02bfwt286",
}


def test_flatten_institution_seven_keys_with_country_code():
    row = flatten_institution(STOCKHOLM)
    assert set(row.keys()) == set(INSTITUTIONS.keys())
    assert len(row) == 7
    # bare id
    assert row["institution_id"] == "I161593684"
    # Zenou key case: country_code is present and == SE (the field that decides "foreign")
    assert row["country_code"] == "SE"
    assert row["display_name"] == "Stockholm University"


def test_armi_lineage_chain_preserved_as_list():
    row = flatten_institution(ARMI)
    # lineage stays a list and includes Monash (bare or as-is; at least the chain is whole and not flattened)
    assert isinstance(row["lineage"], list)
    assert len(row["lineage"]) == 2
    # associated_institutions stays list<dict> (needed by path3) and has a relationship key
    assert isinstance(row["associated_institutions"], list)
    assert isinstance(row["associated_institutions"][0], dict)
    assert "relationship" in row["associated_institutions"][0]
    assert row["ror"] == "https://ror.org/02bfwt286"


def test_caulfield_healthcare_type_落盘():
    caulfield = {
        "id": "https://openalex.org/I4210114009",
        "display_name": "Caulfield Hospital",
        "country_code": "AU",
        "type": "healthcare",
        "lineage": ["https://openalex.org/I4210114009"],
        "associated_institutions": [],
        "ror": None,
    }
    row = flatten_institution(caulfield)
    assert row["type"] == "healthcare"
    assert row["institution_id"] == "I4210114009"


def test_iter_institutions_includes_foreign_no_au_filter():
    # One work, one author with two institutions: one domestic (ARMI/AU) and one foreign (Stockholm/SE).
    work = {
        "id": "https://openalex.org/W9",
        "authorships": [
            {"institutions": [ARMI, STOCKHOLM]},
        ],
    }
    rows = list(iter_institutions(work))
    ids = {r["institution_id"] for r in rows}
    # No in_au filter: the foreign Stockholm institution must be present too
    assert "I161593684" in ids
    assert "I2801239119" in ids


def test_iter_institutions_empty_institutions_yields_nothing():
    # empty institutions -> this table emits no row (the institutions table keeps only institutions that really appear; the fallback for empty institutions lives in works_affil).
    work = {"id": "https://openalex.org/W0", "authorships": [{"institutions": []}]}
    assert list(iter_institutions(work)) == []


def test_write_institutions_schema_guard_and_deterministic(tmp_path: pathlib.Path):
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    rows = [flatten_institution(STOCKHOLM), flatten_institution(ARMI)]
    p1 = tmp_path / "inst1.parquet"
    p2 = tmp_path / "inst2.parquet"
    write_institutions(rows, p1)
    write_institutions(list(reversed(rows)), p2)

    t = pq.read_table(p1)
    assert t.column_names == list(INSTITUTIONS.keys())
    # deterministic: sorted by institution_id -> I161593684 comes before I2801239119
    assert t.column("institution_id").to_pylist() == ["I161593684", "I2801239119"]
    assert p1.read_bytes() == p2.read_bytes()


def test_write_institutions_rejects_bad_schema(tmp_path: pathlib.Path):
    pytest.importorskip("pyarrow")
    from common.schema import SchemaMismatchError

    bad = [{"institution_id": "I1"}]  # many columns missing
    with pytest.raises(SchemaMismatchError):
        write_institutions(bad, tmp_path / "bad.parquet")
