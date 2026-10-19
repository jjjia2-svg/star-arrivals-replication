"""M1-T-ABS abstract_reverse.py red tests (#16 / closure item 2).

Three things are tested:
  1. reconstruct_abstract: rebuilds a readable abstract_text from a {token:[positions]}
     inverted index, ordered by position.
     - None/empty -> None;
     - position gap (some index has no token) -> skip the gap, faithful to OpenAlex's lossy
       format (no padding, no exception).
  2. flatten_work_text: outputs {work_id(bare), title, abstract_text}, exactly the 3 WORK_TEXT
     columns;
     - title comes from the snapshot title (falls back to display_name, then to None, but the
       row is kept);
     - never produces has_abstract (the 3 columns are fixed).
  3. write_work_text: every row passes assert_matches_schema(.., WORK_TEXT) before writing ->
     exactly 3 keys.

Only data shape and inversion logic are checked, with no identification choices. Uses small
fixtures and never downloads anything.
"""
import pathlib

import pytest

from m1_ingest.abstract_reverse import (
    reconstruct_abstract,
    flatten_work_text,
    write_work_text,
    ENABLE_WORK_TEXT,
)
from common.schema import WORK_TEXT


# --------------------------------------------------------------------------
# 1. reconstruct_abstract: inverted-index reconstruction
# --------------------------------------------------------------------------

def test_reconstruct_basic_in_position_order():
    # {token:[positions]} -> joined by position. Positions may be out of order or repeated.
    idx = {"Mutu": [0, 19], "is": [1], "great": [2]}
    out = reconstruct_abstract(idx)
    # Positions 0,1,2,19 join into the text; the gap 3..18 has no token and is skipped.
    assert out.split()[:3] == ["Mutu", "is", "great"]
    assert out.split()[-1] == "Mutu"  # second occurrence at position 19


def test_reconstruct_none_and_empty_return_none():
    assert reconstruct_abstract(None) is None
    assert reconstruct_abstract({}) is None


def test_reconstruct_position_gap_is_skipped_not_filled():
    # Positions 0 and 2 have tokens, position 1 is missing -> the result has only two tokens; no
    # empty string is inserted and nothing is raised.
    idx = {"alpha": [0], "gamma": [2]}
    out = reconstruct_abstract(idx)
    assert out == "alpha gamma"


# --------------------------------------------------------------------------
# 2. flatten_work_text: aligned to the 3 WORK_TEXT columns
# --------------------------------------------------------------------------

def test_flatten_work_text_exactly_three_keys_no_has_abstract():
    work = {
        "id": "https://openalex.org/W123",
        "title": "A Study",
        "abstract_inverted_index": {"hello": [0], "world": [1]},
    }
    row = flatten_work_text(work)
    assert set(row.keys()) == set(WORK_TEXT.keys())
    assert set(row.keys()) == {"work_id", "title", "abstract_text"}
    assert "has_abstract" not in row
    assert row["work_id"] == "W123"  # bare (URL prefix stripped)
    assert row["title"] == "A Study"
    assert row["abstract_text"] == "hello world"


def test_flatten_title_falls_back_to_display_name_then_none():
    # title missing -> fall back to display_name
    w1 = {"id": "https://openalex.org/W1", "display_name": "Fallback Title"}
    assert flatten_work_text(w1)["title"] == "Fallback Title"
    # title and display_name both missing -> None, but the row is still emitted (not dropped)
    w2 = {"id": "https://openalex.org/W2"}
    row = flatten_work_text(w2)
    assert row["title"] is None
    assert row["work_id"] == "W2"
    assert row["abstract_text"] is None  # no inverted index


def test_enable_work_text_default_true():
    assert ENABLE_WORK_TEXT is True


# --------------------------------------------------------------------------
# 3. write_work_text: write + schema guard + determinism
# --------------------------------------------------------------------------

def test_write_work_text_roundtrip_and_deterministic(tmp_path: pathlib.Path):
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    rows = [
        {"work_id": "W2", "title": "Bbb", "abstract_text": "y"},
        {"work_id": "W1", "title": "Aaa", "abstract_text": "x"},
    ]
    p1 = tmp_path / "work_text_1.parquet"
    p2 = tmp_path / "work_text_2.parquet"
    write_work_text(rows, p1)
    write_work_text(list(reversed(rows)), p2)  # different input order

    t = pq.read_table(p1)
    assert t.column_names == list(WORK_TEXT.keys())
    # deterministic sort by PK work_id -> W1 first
    assert t.column("work_id").to_pylist() == ["W1", "W2"]
    # byte-level determinism: same content, different input order -> identical file bytes
    assert p1.read_bytes() == p2.read_bytes()


def test_write_work_text_rejects_bad_schema(tmp_path: pathlib.Path):
    pytest.importorskip("pyarrow")
    from common.schema import SchemaMismatchError

    bad = [{"work_id": "W1", "title": "x", "abstract_text": "y", "has_abstract": True}]
    with pytest.raises(SchemaMismatchError):
        write_work_text(bad, tmp_path / "bad.parquet")
