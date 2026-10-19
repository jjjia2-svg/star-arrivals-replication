"""M1-T-AUTH authors.py red tests (closure item 3).

Tests (including two killer cases):
  1. AuthorTable.add: bare -> canonical (via cmap); several entries for the same canonical
     author -> keep one distinct display_name + the orcid (if any); never split into several rows.
  2. Killer 1: canonical author A5017376589 gets one row with orcid=0000-0001-6516-0812.
  3. Killer 2: after canonical merging the same person does not split -> no duplicate PK
     in authors.author_id.
  4. AUTHORS has 3 columns by default {author_id, display_name, orcid}; open item 4: the
     column count is to be confirmed against real m0 data (3 columns at this stage).
  5. write: before writing, assert_matches_schema(.., AUTHORS) requires exactly 3 keys;
     sorted by author_id for determinism.

Only data shape is checked, with no identification choices; small fixtures, never downloads.
"""
import pathlib

import pytest

from m1_ingest.authors import AuthorTable, write_authors
from common.schema import AUTHORS


def test_add_three_keys_default():
    t = AuthorTable()
    t.add(author_id="https://openalex.org/A1", display_name="Jane Doe",
          orcid="0000-0000-0000-0001")
    rows = t.rows()
    assert len(rows) == 1
    assert set(rows[0].keys()) == set(AUTHORS.keys())
    assert set(rows[0].keys()) == {"author_id", "display_name", "orcid"}
    assert rows[0]["author_id"] == "A1"  # bare


def test_zenou_canonical_row_with_orcid():
    # Killer 1: Yves Zenou A5017376589 + live orcid 0000-0001-6516-0812 land in one row.
    t = AuthorTable()
    t.add(author_id="https://openalex.org/A5017376589", display_name="Yves Zénou",
          orcid="0000-0001-6516-0812")
    rows = t.rows()
    assert rows[0]["author_id"] == "A5017376589"
    assert rows[0]["orcid"] == "0000-0001-6516-0812"
    assert rows[0]["display_name"] == "Yves Zénou"


def test_canonical_merge_no_pk_split():
    # Killer 2: two raw ids fold to the same canonical via cmap -> only one row, PK not duplicated.
    cmap = {"A_old": "A_canon", "A_new": "A_canon"}
    t = AuthorTable(author_cmap=cmap)
    t.add(author_id="A_old", display_name="Y Z", orcid=None)
    t.add(author_id="A_new", display_name="Y Z", orcid="0000-0001-6516-0812")
    rows = t.rows()
    ids = [r["author_id"] for r in rows]
    assert ids == ["A_canon"]          # single row
    assert len(ids) == len(set(ids))   # no duplicate PK
    # the entry that has an orcid value is kept (the later orcid fills in)
    assert rows[0]["orcid"] == "0000-0001-6516-0812"


def test_display_name_kept_when_later_missing():
    # Several entries for the same canonical: the first has a name, a later one lacks it -> the name
    # is not overwritten by None (keep one distinct name).
    cmap = {"A_a": "A_c", "A_b": "A_c"}
    t = AuthorTable(author_cmap=cmap)
    t.add(author_id="A_a", display_name="Real Name", orcid=None)
    t.add(author_id="A_b", display_name=None, orcid=None)
    assert t.rows()[0]["display_name"] == "Real Name"


def test_add_author_obj_convenience():
    # add_author(author_dict) convenience entry (feed it authorships[].author directly).
    t = AuthorTable()
    t.add_author({"id": "https://openalex.org/A9", "display_name": "N", "orcid": None})
    assert t.rows()[0]["author_id"] == "A9"


def test_write_authors_schema_guard_and_deterministic(tmp_path: pathlib.Path):
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    t = AuthorTable()
    t.add(author_id="A2", display_name="Bob", orcid=None)
    t.add(author_id="A1", display_name="Alice", orcid="0000-0000-0000-0002")
    p1 = tmp_path / "auth1.parquet"
    write_authors(t.rows(), p1)

    # build another one with the opposite insertion order -> bytes must be identical (determinism)
    t2 = AuthorTable()
    t2.add(author_id="A1", display_name="Alice", orcid="0000-0000-0000-0002")
    t2.add(author_id="A2", display_name="Bob", orcid=None)
    p2 = tmp_path / "auth2.parquet"
    write_authors(t2.rows(), p2)

    tbl = pq.read_table(p1)
    assert tbl.column_names == list(AUTHORS.keys())
    assert tbl.column("author_id").to_pylist() == ["A1", "A2"]  # sort determinism
    assert p1.read_bytes() == p2.read_bytes()


def test_write_authors_rejects_bad_schema(tmp_path: pathlib.Path):
    pytest.importorskip("pyarrow")
    from common.schema import SchemaMismatchError

    bad = [{"author_id": "A1", "display_name": "x", "orcid": "y",
            "display_name_alternatives": ["z"]}]  # 5 columns (extra columns not in the schema)
    with pytest.raises(SchemaMismatchError):
        write_authors(bad, tmp_path / "bad.parquet")
