"""Regression: fwci accumulator to_table must not crash when work_type=None is mixed with str in one bucket.

A bare `sorted(self._cells)` compares None with str at the third sort position when type=None and
type=str coexist in the same (subfield, year) bucket -> TypeError, which would blow up hours into a full
run, at the final FWCI assembly. Fixed with a None-safe sort key.
"""
from __future__ import annotations

from m1_ingest import fwci_accumulator as fa


def _w(subfield: str, year: int, wtype, cited: int) -> dict:
    """Minimal snapshot works record (primary_topic.subfield.id in URL form; type may be None)."""
    return {
        "primary_topic": {"subfield": {"id": f"https://openalex.org/subfields/{subfield}"}},
        "publication_year": year,
        "type": wtype,
        "cited_by_count": cited,
    }


def test_to_table_mixed_none_and_str_worktype_no_crash():
    """Same (2002,2015) bucket: type='article' and type=None coexist -> to_table does not crash; the None type sorts last."""
    acc = fa.FwciPopAccumulator()
    acc.add(_w("2002", 2015, "article", 10))
    acc.add(_w("2002", 2015, None, 5))
    rows = acc.to_table()                 # before: str vs None comparison -> TypeError
    keys = [(r["subfield_id"], r["year"], r["work_type"]) for r in rows]
    assert len(keys) == 2
    assert None in [k[2] for k in keys]  # the None-type cell was not swallowed
    assert keys[-1][2] is None           # None-safe: non-None values first, None last
