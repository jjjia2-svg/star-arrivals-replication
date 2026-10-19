"""U0.5 step 3, write Table B, TDD - DEPT_ROSTER_PANEL row construction + deterministic parquet write.

Two test layers:
  A) to_table_b_row() - pure function: (parsed record + align verdict) -> Table B 8-column row.
     - dept_key=monash_econ; author_id=bare (matched) or None (needs_human);
     - evidence=official_roster (current Pure roster); human_verified=False (decided automatically, not human-checked);
     - confidence follows the align verdict (high/medium); needs_human -> confidence=low + author_id=None;
     - year_start/year_end follow parsed (missing -> None).
  B) write_table_b() - assert_matches_schema(DEPT_ROSTER_PANEL) before writing; the row key set is exactly 8 columns;
     deterministic (same content gives an identical byte-level sha).

Hard rules: schema verbatim (8 columns, more or fewer raise); author_id bare; evidence/human_verified as specified;
  never use affiliations.years as year (the year in this table comes from the Pure archive interval, arrival is judged separately).
"""
from __future__ import annotations

import hashlib
import pathlib

import pytest

from common.schema import DEPT_ROSTER_PANEL, assert_matches_schema
from roster.table_b import to_table_b_row, write_table_b, DEPT_KEY


# ---------------------------------------------------------------------------
# fixtures: parsed records + align verdicts
# ---------------------------------------------------------------------------
def _parsed(name, ys=2010, ye=2025):
    return {
        "display_name": name, "email": None, "title_raw": "Professor",
        "year_start": ys, "year_end": ye,
        "is_adjunct": False, "is_emeritus": False, "center": None,
    }


_HIT = {"author_id": "A5017376589", "confidence": "high", "needs_human": False}
_NEEDS_HUMAN = {"author_id": None, "confidence": None, "needs_human": True}


# ===========================================================================
# A) to_table_b_row - schema + field values
# ===========================================================================
def test_row_matches_schema_exactly():
    """Row key set is exactly the 8 DEPT_ROSTER_PANEL columns (more or fewer raise)."""
    row = to_table_b_row(_parsed("Yves Zenou", 1995, 2026), _HIT)
    # passes if nothing is raised:
    assert_matches_schema(row.keys(), DEPT_ROSTER_PANEL, label="dept_roster_panel")


def test_row_dept_key_is_monash_econ():
    row = to_table_b_row(_parsed("Yves Zenou"), _HIT)
    assert row["dept_key"] == "monash_econ"
    assert DEPT_KEY == "monash_econ"


def test_row_author_id_bare_on_hit():
    """Matched -> author_id=bare (no URL prefix)."""
    row = to_table_b_row(_parsed("Yves Zenou", 1995, 2026), _HIT)
    assert row["author_id"] == "A5017376589"
    assert not row["author_id"].startswith("http")


def test_row_evidence_is_official_roster():
    """evidence=official_roster (snapshot of the current Pure roster)."""
    row = to_table_b_row(_parsed("Yves Zenou"), _HIT)
    assert row["evidence"] == "official_roster"


def test_row_human_verified_false():
    """human_verified=False - decided automatically, not human-checked (stars/first-order colleagues become True only after a later human check)."""
    row = to_table_b_row(_parsed("Yves Zenou"), _HIT)
    assert row["human_verified"] is False


def test_row_confidence_follows_verdict():
    """confidence follows the align verdict (high)."""
    row = to_table_b_row(_parsed("Yves Zenou"), _HIT)
    assert row["confidence"] == "high"


def test_needs_human_row_author_id_none_conf_low():
    """needs_human -> author_id=None + confidence=low (red line #1: never guess an id)."""
    row = to_table_b_row(_parsed("John Smith"), _NEEDS_HUMAN)
    assert row["author_id"] is None
    assert row["confidence"] == "low"


def test_row_years_passthrough():
    """year_start/year_end follow parsed; missing year -> None (no placeholder numbers)."""
    row = to_table_b_row(_parsed("Yves Zenou", 1995, 2026), _HIT)
    assert row["year_start"] == 1995 and row["year_end"] == 2026
    none_row = to_table_b_row(_parsed("Person P", None, None), _HIT)
    assert none_row["year_start"] is None and none_row["year_end"] is None


def test_row_display_name_passthrough():
    row = to_table_b_row(_parsed("Yves Zenou"), _HIT)
    assert row["display_name"] == "Yves Zenou"


# ===========================================================================
# B) write_table_b - schema guard + determinism
# ===========================================================================
def test_write_then_read_roundtrip(tmp_path):
    """Write -> read back, row count/columns match + author_id written correctly."""
    import pyarrow.parquet as pq

    rows = [
        to_table_b_row(_parsed("Yves Zenou", 1995, 2026), _HIT),
        to_table_b_row(_parsed("John Smith"), _NEEDS_HUMAN),
    ]
    target = tmp_path / "dept_roster_panel_monash.parquet"
    write_table_b(rows, target)
    tbl = pq.read_table(str(target))
    assert tbl.num_rows == 2
    assert set(tbl.column_names) == set(DEPT_ROSTER_PANEL.keys())
    d = tbl.to_pylist()
    by_name = {r["display_name"]: r for r in d}
    assert by_name["Yves Zenou"]["author_id"] == "A5017376589"
    assert by_name["John Smith"]["author_id"] is None


def test_write_is_deterministic(tmp_path):
    """Two writes of the same content -> byte-level sha equal (deterministic parquet, the key to reproducibility)."""
    rows = [to_table_b_row(_parsed("Yves Zenou", 1995, 2026), _HIT)]
    a = tmp_path / "a.parquet"
    b = tmp_path / "b.parquet"
    write_table_b(rows, a)
    write_table_b(rows, b)
    sha_a = hashlib.sha256(a.read_bytes()).hexdigest()
    sha_b = hashlib.sha256(b.read_bytes()).hexdigest()
    assert sha_a == sha_b


def test_write_rejects_bad_schema(tmp_path):
    """A row with one extra stray key -> assert_matches_schema raises before writing (a dirty table is never silently written)."""
    bad = to_table_b_row(_parsed("Yves Zenou"), _HIT)
    bad["rogue_col"] = 1
    with pytest.raises(Exception):
        write_table_b([bad], tmp_path / "bad.parquet")


def test_write_empty_ok(tmp_path):
    """Empty rows -> still writes a 0-row parquet with the correct column order (downstream does not crash on a missing file)."""
    import pyarrow.parquet as pq

    target = tmp_path / "empty.parquet"
    write_table_b([], target)
    tbl = pq.read_table(str(target))
    assert tbl.num_rows == 0
    assert set(tbl.column_names) == set(DEPT_ROSTER_PANEL.keys())
