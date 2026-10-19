"""Tests for schema_map: the field-mapping tests plus the row iterators.

Behaviour covered, following the official field mapping:
  - bare() strips the OpenAlex URL prefix, is idempotent, and maps None/"" to None.
  - assert_snapshot_fields_present with a required key missing -> sys.exit(EXIT_FIELDS_MISSING=19).
  - flatten_work puts None for missing fields and never drops the row; subfield_id is taken from the last
    segment of the primary_topic.subfield.id URL (not == int).
  - iter_authorship_edges has exactly 3 columns (never raw_affil/institution_id).
  - iter_referenced_edges uses the column name referenced_work_id (the official anchor).
  - iter_works_affil_rows still emits one row with institution_id=None when the institution is empty.
  - iter_institutions / flatten_institution produce the 7-column INSTITUTIONS shape, including foreign
    institutions (country_code).

These tests use a small-sample fixture of works JSON to test logic and never download from S3.
"""
import pytest

from m1_ingest import schema_map
from common.schema import (
    WORKS,
    AUTHORSHIP_EDGES,
    REFS_EDGES,
    WORKS_AFFIL,
    INSTITUTIONS,
    assert_matches_schema,
)
from identity.exit_codes import EXIT_FIELDS_MISSING


# --------------------------------------------------------------------------
# fixture: one snapshot works record with all fields present (following the observed fields + the official shape)
# --------------------------------------------------------------------------
def _work_full():
    """A works record with all fields present (Zenou style: foreign institution + several authors + subfield in URL form)."""
    return {
        "id": "https://openalex.org/W2000000001",
        "publication_year": 2018,
        "type": "article",
        "primary_topic": {
            "id": "https://openalex.org/T10001",
            "subfield": {"id": "https://openalex.org/subfields/2002", "display_name": "Economics and Econometrics"},
        },
        "fwci": 1.85,
        "cited_by_count": 42,
        "referenced_works": [
            "https://openalex.org/W1000000001",
            "https://openalex.org/W1000000002",
        ],
        "has_references": True,
        "is_paratext": False,
        "is_retracted": False,
        "citation_normalized_percentile": {
            "value": 0.97,
            "is_in_top_1_percent": True,
            "is_in_top_10_percent": True,
        },
        "title": "Networks in the Economy",
        "abstract_inverted_index": {"Networks": [0], "matter": [1]},
        "authorships": [
            {
                "author": {
                    "id": "https://openalex.org/A5017376589",
                    "display_name": "Yves Zénou",
                    "orcid": "https://orcid.org/0000-0001-6516-0812",
                },
                "author_position": "first",
                "raw_affiliation_strings": ["Monash University, Australia"],
                "institutions": [
                    {
                        "id": "https://openalex.org/I56590836",
                        "display_name": "Monash University",
                        "country_code": "AU",
                        "type": "education",
                        "lineage": ["https://openalex.org/I56590836"],
                        "ror": "https://ror.org/02bfwt286",
                    }
                ],
            },
            {
                "author": {
                    "id": "https://openalex.org/A5099999999",
                    "display_name": "Co Author",
                    "orcid": None,
                },
                "author_position": "middle",
                "raw_affiliation_strings": ["Institute for International Economic Studies, Stockholm"],
                "institutions": [
                    {
                        "id": "https://openalex.org/I161593684",
                        "display_name": "Stockholm University",
                        "country_code": "SE",
                        "type": "education",
                        "lineage": ["https://openalex.org/I161593684"],
                        "ror": "https://ror.org/05f0yaq80",
                    }
                ],
            },
        ],
    }


# ===========================================================================
# bare(): strip the prefix + idempotent + None/"" -> None
# ===========================================================================
def test_bare_strips_openalex_url_prefix():
    assert schema_map.bare("https://openalex.org/W2000000001") == "W2000000001"
    assert schema_map.bare("https://openalex.org/A5017376589") == "A5017376589"


def test_bare_is_idempotent_on_already_bare_id():
    # an id that is already bare stays itself after another bare() (idempotent).
    assert schema_map.bare("W2000000001") == "W2000000001"


def test_bare_none_and_empty_become_none():
    assert schema_map.bare(None) is None
    assert schema_map.bare("") is None


def test_url_prefix_constant_pinned():
    assert schema_map.OPENALEX_URL_PREFIX == "https://openalex.org/"


# ===========================================================================
# assert_snapshot_fields_present: a missing required key -> exit(19) / all present -> PASS
# ===========================================================================
def test_assert_snapshot_fields_present_passes_when_all_present():
    # all required keys present -> no raise, no exit.
    schema_map.assert_snapshot_fields_present([_work_full()], n=1)


def test_assert_snapshot_fields_present_exits_19_when_required_key_missing():
    bad = _work_full()
    del bad["referenced_works"]  # drop one required key
    with pytest.raises(SystemExit) as exc:
        schema_map.assert_snapshot_fields_present([bad], n=1)
    assert exc.value.code == EXIT_FIELDS_MISSING == 19


# ===========================================================================
# flatten_work: missing fields give None and no row is dropped / subfield_id from the URL's last segment / aligned with the 12 WORKS columns
# ===========================================================================
def test_flatten_work_matches_works_schema_exactly():
    row = schema_map.flatten_work(_work_full())
    # The key set must equal the 12 WORKS columns exactly (the assert before writing must not fail).
    assert_matches_schema(row.keys(), WORKS, label="WORKS")


def test_flatten_work_subfield_id_taken_from_url_tail_not_int():
    row = schema_map.flatten_work(_work_full())
    # primary_topic.subfield.id = ".../subfields/2002" -> take the last segment "2002" (a string, not the int 2002).
    assert row["subfield_id"] == "2002"


def test_flatten_work_bare_ids_and_counts():
    row = schema_map.flatten_work(_work_full())
    assert row["work_id"] == "W2000000001"
    assert row["publication_year"] == 2018
    assert row["work_type"] == "article"
    assert row["cited_by_count"] == 42
    # referenced_works_count = len(referenced_works).
    assert row["referenced_works_count"] == 2
    assert row["fwci"] == 1.85
    assert row["is_in_top_1_percent"] is True
    assert row["is_in_top_10_percent"] is True


def test_flatten_work_missing_fields_become_none_not_dropped():
    sparse = {"id": "https://openalex.org/W3", "publication_year": 2020}
    row = schema_map.flatten_work(sparse)
    # still aligned with 12 columns (no row is dropped); missing fields = None.
    assert_matches_schema(row.keys(), WORKS, label="WORKS")
    assert row["work_id"] == "W3"
    assert row["fwci"] is None
    assert row["subfield_id"] is None
    assert row["cited_by_count"] is None
    # referenced_works missing -> count 0, has_references is not forced to True.
    assert row["referenced_works_count"] == 0


# ===========================================================================
# iter_authorship_edges: exactly 3 columns, never raw_affil/institution_id
# ===========================================================================
def test_iter_authorship_edges_exactly_three_columns_high4():
    edges = list(schema_map.iter_authorship_edges(_work_full()))
    assert len(edges) == 2  # two authorships
    for e in edges:
        # the key set is exactly the 3 AUTHORSHIP_EDGES columns; never raw_affil / institution_id.
        assert_matches_schema(e.keys(), AUTHORSHIP_EDGES, label="AUTHORSHIP_EDGES")
        assert "raw_affiliation_strings" not in e
        assert "institution_id" not in e
        assert e["work_id"] == "W2000000001"
        assert e["publication_year"] == 2018
    assert {e["author_id"] for e in edges} == {"A5017376589", "A5099999999"}


# ===========================================================================
# iter_referenced_edges: column name referenced_work_id (the official anchor, not ref_work_id)
# ===========================================================================
def test_iter_referenced_edges_column_name_is_referenced_work_id():
    refs = list(schema_map.iter_referenced_edges(_work_full()))
    assert len(refs) == 2
    for r in refs:
        assert_matches_schema(r.keys(), REFS_EDGES, label="REFS_EDGES")
        assert "referenced_work_id" in r  # the official anchor name, not ref_work_id
    assert {r["referenced_work_id"] for r in refs} == {"W1000000001", "W1000000002"}


# ===========================================================================
# iter_works_affil_rows: an empty institution still emits one row with institution_id=None
# ===========================================================================
def test_iter_works_affil_rows_keeps_raw_affil_list_not_flattened():
    rows = list(schema_map.iter_works_affil_rows(_work_full()))
    z = [r for r in rows if r["author_id"] == "A5017376589"][0]
    assert_matches_schema(z.keys(), WORKS_AFFIL, label="WORKS_AFFIL")
    # raw_affiliation_strings stays list<str> as-is, not flattened.
    assert z["raw_affiliation_strings"] == ["Monash University, Australia"]
    assert z["institution_id"] == "I56590836"


def test_iter_works_affil_rows_empty_institutions_still_emits_row_with_none():
    work = {
        "id": "https://openalex.org/W4",
        "authorships": [
            {
                "author": {"id": "https://openalex.org/A7"},
                "raw_affiliation_strings": ["Some Unmatched Affiliation"],
                "institutions": [],  # institution matching failed (often empty)
            }
        ],
    }
    rows = list(schema_map.iter_works_affil_rows(work))
    assert len(rows) == 1  # still emits one row (raw_affil is left for the disambiguation fallback)
    assert rows[0]["institution_id"] is None
    assert rows[0]["raw_affiliation_strings"] == ["Some Unmatched Affiliation"]


# ===========================================================================
# iter_institutions / flatten_institution: INSTITUTIONS 7 columns, including foreign ones
# ===========================================================================
def test_iter_institutions_emits_seven_column_rows_including_foreign():
    rows = list(schema_map.iter_institutions(_work_full()))
    by_id = {r["institution_id"]: r for r in rows}
    # Monash (AU) + Stockholm (SE) are both present (no Australia filter).
    assert "I56590836" in by_id
    assert "I161593684" in by_id
    for r in rows:
        assert_matches_schema(r.keys(), INSTITUTIONS, label="INSTITUTIONS")
    # country_code is the field that decides whether an institution is foreign (the Zenou case).
    assert by_id["I161593684"]["country_code"] == "SE"
    assert by_id["I56590836"]["country_code"] == "AU"


def test_flatten_institution_associated_kept_as_list_of_dict():
    inst = {
        "id": "https://openalex.org/I2801239119",
        "display_name": "Australian Regenerative Medicine Institute",
        "country_code": "AU",
        "type": "facility",
        "lineage": ["https://openalex.org/I56590836", "https://openalex.org/I2801239119"],
        "associated_institutions": [
            {"id": "https://openalex.org/I56590836", "relationship": "parent", "type": "education"}
        ],
        "ror": "https://ror.org/xyz",
    }
    row = schema_map.flatten_institution(inst)
    assert_matches_schema(row.keys(), INSTITUTIONS, label="INSTITUTIONS")
    assert row["institution_id"] == "I2801239119"
    assert row["type"] == "facility"
    # associated_institutions stays list<dict> (fold path3 reads relationship/type/id; list<str> would lose them).
    assert isinstance(row["associated_institutions"], list)
    assert row["associated_institutions"][0]["relationship"] == "parent"
    # lineage = a list of bare ids.
    assert row["lineage"] == ["I56590836", "I2801239119"]


def test_reconstruct_abstract_reexported_from_schema_map():
    # schema_map re-exports reconstruct_abstract (implemented in abstract_reverse.py).
    assert hasattr(schema_map, "reconstruct_abstract")
    assert schema_map.reconstruct_abstract({"Hello": [0], "world": [1]}) == "Hello world"
