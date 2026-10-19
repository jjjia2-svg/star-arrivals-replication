"""Tests for first_pub.py (true career first-publication year).

Cases:
  1. FirstPubAccumulator.add: accumulate each (author_id, publication_year) and take min(year) per author.
  2. Key case: the min is taken after canonical merge. One person with two raw ids (A_old first publishes
     in 2003, A_new in 2010) is folded by cmap into one canonical id -> first_pub_year=2003 (never 2010).
  3. A None year is skipped (it does not enter the min and does not raise).
  4. WORK_FIRST_PUB has 3 columns {author_id, first_pub_year, first_pub_year_is_full_history};
     is_full_history=True (the value comes from a scan of the full publication history).
  5. write: before writing, assert_matches_schema(.., WORK_FIRST_PUB) must see exactly 3 keys; rows are
     sorted by author_id so the output is deterministic.

Checks data shape only, with no identification choices; small fixtures, never a real download.
"""
import pathlib

import pytest

from m1_ingest.first_pub import FirstPubAccumulator, write_first_pub
from common.schema import WORK_FIRST_PUB


def test_accumulator_takes_min_year_per_author():
    acc = FirstPubAccumulator()
    acc.add(author_id="A1", publication_year=2010)
    acc.add(author_id="A1", publication_year=2005)  # earlier
    acc.add(author_id="A1", publication_year=2018)
    rows = acc.rows()
    assert len(rows) == 1
    assert rows[0]["author_id"] == "A1"
    assert rows[0]["first_pub_year"] == 2005


def test_canonical_merge_takes_min_across_raw_ids():
    # Key case: A_old first publishes in 2003, A_new in 2010, both fold to the same canonical id -> 2003.
    cmap = {"A_old": "A_canon", "A_new": "A_canon"}
    acc = FirstPubAccumulator(author_cmap=cmap)
    acc.add(author_id="A_new", publication_year=2010)
    acc.add(author_id="A_old", publication_year=2003)
    rows = acc.rows()
    assert len(rows) == 1
    assert rows[0]["author_id"] == "A_canon"
    # min after merge -> 2003, never 2010
    assert rows[0]["first_pub_year"] == 2003


def test_none_year_skipped():
    acc = FirstPubAccumulator()
    acc.add(author_id="A1", publication_year=None)  # skipped, no exception
    acc.add(author_id="A1", publication_year=2012)
    rows = acc.rows()
    assert rows[0]["first_pub_year"] == 2012
    # An author with only None years has no first_pub_year and emits no row (no trustworthy first year)
    acc.add(author_id="A2", publication_year=None)
    ids = {r["author_id"] for r in acc.rows()}
    assert "A2" not in ids


def test_is_full_history_true_and_three_keys():
    acc = FirstPubAccumulator()
    acc.add(author_id="A1", publication_year=2000)
    row = acc.rows()[0]
    assert set(row.keys()) == set(WORK_FIRST_PUB.keys())
    assert set(row.keys()) == {"author_id", "first_pub_year", "first_pub_year_is_full_history"}
    # full publication history -> is_full_history=True
    assert row["first_pub_year_is_full_history"] is True


def test_add_work_convenience_fans_out_authors():
    # add_work: every author of a work receives that work's publication_year.
    acc = FirstPubAccumulator()
    work = {
        "publication_year": 2008,
        "authorships": [
            {"author": {"id": "https://openalex.org/A1"}},
            {"author": {"id": "https://openalex.org/A2"}},
        ],
    }
    acc.add_work(work)
    ids = {r["author_id"]: r["first_pub_year"] for r in acc.rows()}
    assert ids == {"A1": 2008, "A2": 2008}


def test_write_first_pub_schema_guard_and_deterministic(tmp_path: pathlib.Path):
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    acc = FirstPubAccumulator()
    acc.add(author_id="A2", publication_year=2001)
    acc.add(author_id="A1", publication_year=1999)
    p1 = tmp_path / "fp1.parquet"
    write_first_pub(acc.rows(), p1)

    acc2 = FirstPubAccumulator()
    acc2.add(author_id="A1", publication_year=1999)
    acc2.add(author_id="A2", publication_year=2001)
    p2 = tmp_path / "fp2.parquet"
    write_first_pub(acc2.rows(), p2)

    t = pq.read_table(p1)
    assert t.column_names == list(WORK_FIRST_PUB.keys())
    assert t.column("author_id").to_pylist() == ["A1", "A2"]  # deterministic order
    assert p1.read_bytes() == p2.read_bytes()


def test_write_first_pub_rejects_bad_schema(tmp_path: pathlib.Path):
    pytest.importorskip("pyarrow")
    from common.schema import SchemaMismatchError

    bad = [{"author_id": "A1", "first_pub_year": 2000}]  # is_full_history missing
    with pytest.raises(SchemaMismatchError):
        write_first_pub(bad, tmp_path / "bad.parquet")
