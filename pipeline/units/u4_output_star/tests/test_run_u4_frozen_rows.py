"""U4 shipping - frozen_star_rows reads the frozen files + verifies the stars_set_hash binding.

In plain words: the ship_events / isc backfill consumes the frozen star_set rows. On reading, it must recompute
stars_set_hash({author_id: arrival}) and compare it with the fingerprint stored in manifest_header.json - a
mismatch means the frozen file was altered or the wrong file was read -> HALT (FrozenStarSetMismatch); shipping
never continues with a corrupted star set. Synthetic data, zero SSD writes.
"""
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


def _rows():
    return [
        {"author_id": "A1", "name": "One", "dept": "monash_econ", "arrival": 2016,
         "subfield": "2002", "age_bin": "22-25", "academic_age": 25, "stock": 900,
         "percentile": 0.99, "cell_n": 120, "is_star_1pct": True, "is_star_5pct": True,
         "age_eligible": True, "is_foreign_poach": True},
        {"author_id": "A2", "name": "Two", "dept": "unsw_econ", "arrival": 2011,
         "subfield": "2002", "age_bin": "6-9", "academic_age": 8, "stock": 10,
         "percentile": 0.4, "cell_n": 120, "is_star_1pct": False, "is_star_5pct": False,
         "age_eligible": True, "is_foreign_poach": False},
    ]


def _mk_frozen(tmp_path, *, rows=None, header_hash=None):
    from m7a_star.freeze import stars_set_hash
    rows = rows if rows is not None else _rows()
    d = tmp_path / "u4_star_set_2026-07-08"
    d.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), str(d / "star_set.parquet"))
    h = header_hash if header_hash is not None else stars_set_hash(
        {r["author_id"]: r["arrival"] for r in rows})
    (d / "manifest_header.json").write_text(
        json.dumps({"table": "star_set", "stars_set_hash": h,
                    "rule_version": "redlines_v4_signed_2026-07-05"}),
        encoding="utf-8")
    return d


def test_load_frozen_rows_verifies_hash_binding(tmp_path):
    """happy path: rows read back + recomputed fingerprint == manifest_header fingerprint -> pass, return
    rows/fingerprint/header."""
    from run_u4 import load_frozen_star_rows
    d = _mk_frozen(tmp_path)
    res = load_frozen_star_rows(d)
    assert [r["author_id"] for r in res["rows"]] == ["A1", "A2"]
    assert res["stars_set_hash"] == res["header"]["stars_set_hash"]
    assert res["rows"][0]["arrival"] == 2016


def test_load_frozen_rows_hash_mismatch_halts(tmp_path):
    """Fingerprint mismatch (frozen file altered / wrong file read) -> FrozenStarSetMismatch HALT, naming both
    fingerprints."""
    from run_u4 import FrozenStarSetMismatch, load_frozen_star_rows
    d = _mk_frozen(tmp_path, header_hash="deadbeef")
    with pytest.raises(FrozenStarSetMismatch, match="deadbeef"):
        load_frozen_star_rows(d)


def test_load_frozen_rows_missing_parquet_fails(tmp_path):
    """star_set.parquet absent -> ValueError (no frozen file, never continue empty-handed)."""
    from run_u4 import load_frozen_star_rows
    d = _mk_frozen(tmp_path)
    (d / "star_set.parquet").unlink()
    with pytest.raises(ValueError, match="star_set"):
        load_frozen_star_rows(d)


def test_load_frozen_rows_missing_or_empty_header_hash_fails(tmp_path):
    """manifest_header absent / stars_set_hash empty -> ValueError (no binding = cannot verify; the parquet is not
    trusted bare)."""
    from run_u4 import load_frozen_star_rows
    d1 = _mk_frozen(tmp_path)
    (d1 / "manifest_header.json").unlink()
    with pytest.raises(ValueError, match="manifest_header"):
        load_frozen_star_rows(d1)
    d2 = _mk_frozen(tmp_path / "b", header_hash="")
    with pytest.raises(ValueError, match="stars_set_hash"):
        load_frozen_star_rows(d2)
