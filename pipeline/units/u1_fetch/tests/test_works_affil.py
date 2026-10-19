"""M1-T-WAFF works_affil.py red tests (closure item 3 / the P-12 disambiguation crux).

Tests (build list group 5, works_affil section + killer):
  1. iter_works_affil_rows: every authorship × institution is spread into 4 columns
     {work_id, author_id, institution_id, raw_affiliation_strings:list<str>};
     - * empty institution -> still emits a row with institution_id=None (raw_affil is kept as the disambiguation fallback);
     - raw_affiliation_strings stays as list<str>, never flattened or zeroed.
  2. * Zenou killer ①: the raw_affiliation_strings (containing "Monash University") of an ORCID-less fragment work are written out faithfully.
  3. WorksAffilWriter.add + canonical mapping: author_id/institution_id are written as canonical through cmap (closure item 4);
     without a cmap they stay bare as given.
  4. write_works_affil: before writing, assert_matches_schema(.., WORKS_AFFIL) with exactly 4 keys; deterministic.

Only the data shape is checked, no identification convention is touched; small fixture samples, never a real download.
"""
import pathlib

import pytest

from m1_ingest.works_affil import (
    iter_works_affil_rows,
    WorksAffilWriter,
    write_works_affil,
)
from common.schema import WORKS_AFFIL


# Zenou ORCID-less fragment work: the author is attached to Monash, but institutions resolve to empty -> only raw_affil is the fallback.
ZENOU_FRAGMENT = {
    "id": "https://openalex.org/W7777",
    "authorships": [
        {
            "author": {"id": "https://openalex.org/A5017376589"},
            "institutions": [],  # * institution resolution failed (common, 7.4)
            "raw_affiliation_strings": ["Monash University, Melbourne, Australia"],
        }
    ],
}


def test_iter_rows_four_keys_institution_none_still_emits():
    rows = list(iter_works_affil_rows(ZENOU_FRAGMENT))
    assert len(rows) == 1
    r = rows[0]
    assert set(r.keys()) == set(WORKS_AFFIL.keys())
    assert set(r.keys()) == {"work_id", "author_id", "institution_id", "raw_affiliation_strings"}
    # * an empty institution still emits a row, institution_id=None
    assert r["institution_id"] is None
    assert r["work_id"] == "W7777"
    assert r["author_id"] == "A5017376589"


def test_raw_affil_preserved_not_zeroed():
    # * killer ①: raw_affiliation_strings containing "Monash University" is written out faithfully, not zeroed or flattened.
    rows = list(iter_works_affil_rows(ZENOU_FRAGMENT))
    raw = rows[0]["raw_affiliation_strings"]
    assert isinstance(raw, list)
    assert raw == ["Monash University, Melbourne, Australia"]


def test_one_row_per_authorship_times_institution():
    work = {
        "id": "https://openalex.org/W1",
        "authorships": [
            {
                "author": {"id": "https://openalex.org/A1"},
                "institutions": [
                    {"id": "https://openalex.org/I10"},
                    {"id": "https://openalex.org/I20"},
                ],
                "raw_affiliation_strings": ["X Univ", "Y Inst"],
            }
        ],
    }
    rows = list(iter_works_affil_rows(work))
    # two institutions -> two rows, each with its institution_id, and raw_affil carried on every row (as is)
    assert len(rows) == 2
    assert {r["institution_id"] for r in rows} == {"I10", "I20"}
    for r in rows:
        assert r["raw_affiliation_strings"] == ["X Univ", "Y Inst"]


def test_writer_applies_canonical_map():
    # cmap maps raw author/institution ids to canonical (closure item 4).
    author_cmap = {"A_old": "A_new"}
    inst_cmap = {"I_old": "I_canon"}
    w = WorksAffilWriter(author_cmap=author_cmap, institution_cmap=inst_cmap)
    w.add(work_id="W1", author_id="A_old", institution_id="I_old",
          raw_affiliation_strings=["Z"])
    rows = w.rows()
    assert rows[0]["author_id"] == "A_new"
    assert rows[0]["institution_id"] == "I_canon"
    # ids not in cmap stay as given (no mapping, no invention)
    w.add(work_id="W2", author_id="A_keep", institution_id=None,
          raw_affiliation_strings=[])
    assert w.rows()[1]["author_id"] == "A_keep"
    assert w.rows()[1]["institution_id"] is None


def test_write_works_affil_schema_guard_and_deterministic(tmp_path: pathlib.Path):
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    rows = [
        {"work_id": "W2", "author_id": "A2", "institution_id": "I2",
         "raw_affiliation_strings": ["b"]},
        {"work_id": "W1", "author_id": "A1", "institution_id": None,
         "raw_affiliation_strings": ["a"]},
    ]
    p1 = tmp_path / "waff1.parquet"
    p2 = tmp_path / "waff2.parquet"
    write_works_affil(rows, p1)
    write_works_affil(list(reversed(rows)), p2)

    t = pq.read_table(p1)
    assert t.column_names == list(WORKS_AFFIL.keys())
    # sorted by PK (work_id, author_id) -> (W1,A1) comes first
    assert t.column("work_id").to_pylist() == ["W1", "W2"]
    assert p1.read_bytes() == p2.read_bytes()


def test_write_works_affil_rejects_bad_schema(tmp_path: pathlib.Path):
    pytest.importorskip("pyarrow")
    from common.schema import SchemaMismatchError

    bad = [{"work_id": "W1", "author_id": "A1"}]  # missing institution_id + raw_affil
    with pytest.raises(SchemaMismatchError):
        write_works_affil(bad, tmp_path / "bad.parquet")
