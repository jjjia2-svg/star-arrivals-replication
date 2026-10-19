"""run_u4 orchestrator — preflight input-readiness check (gate before the real-data U4 smoke run: tables present + row counts + size estimate).

Row counts come from parquet metadata (no full scan), to confirm inputs are complete before the smoke run and to estimate local vs AWS.
"""
import pyarrow as pa
import pyarrow.parquet as pq


def test_preflight_counts_dir_table(tmp_path):
    """Bucketed directory table: sums the metadata row counts of all its parquet files."""
    from run_u4 import preflight
    t = tmp_path / "tbl"
    t.mkdir()
    pq.write_table(pa.table({"x": [1, 2, 3]}), str(t / "part-0.parquet"))
    pq.write_table(pa.table({"x": [4, 5]}), str(t / "part-1.parquet"))
    rep = preflight(tmp_path, tables={"tbl": "tbl"})
    assert rep["tbl"]["present"] is True
    assert rep["tbl"]["n_rows"] == 5
    assert rep["tbl"]["n_files"] == 2


def test_preflight_single_file_table(tmp_path):
    """Single-file table (e.g. the roster .parquet)."""
    from run_u4 import preflight
    pq.write_table(pa.table({"y": [1, 2]}), str(tmp_path / "single.parquet"))
    rep = preflight(tmp_path, tables={"s": "single.parquet"})
    assert rep["s"]["present"] is True and rep["s"]["n_rows"] == 2


def test_preflight_missing_table_flagged(tmp_path):
    """Missing table → present False, no raise (the report says it is missing; the caller decides whether to stop)."""
    from run_u4 import preflight
    rep = preflight(tmp_path, tables={"gone": "nope"})
    assert rep["gone"]["present"] is False and rep["gone"]["n_rows"] == 0


# ---- build_u4 step 1: map_incumbents roster author → person_id ------------------

def test_map_incumbents_attaches_person_id():
    """Roster incumbents are attached to the person_id from disambiguation (person_map reads only 2 columns)."""
    from run_u4 import map_incumbents
    roster = [{"author_id": "A1", "dept_key": "monash_econ", "display_name": "X",
               "year_start": 2018, "year_end": 2026}]
    res = map_incumbents(roster, {"A1": "P_A1"})
    assert res["incumbents"][0]["person_id"] == "P_A1"
    assert res["incumbents"][0]["dept_key"] == "monash_econ"
    assert res["unmapped"] == []


def test_map_incumbents_reports_unmapped_not_silent():
    """A roster person with no disambiguated identity (not in person_map, no works) → reported separately, not silently mixed into the incumbents."""
    from run_u4 import map_incumbents
    roster = [{"author_id": "A2", "dept_key": "unsw_econ", "display_name": "Y",
               "year_start": 2010, "year_end": 2020}]
    res = map_incumbents(roster, {})
    assert res["incumbents"] == [] and res["unmapped"] == ["A2"]
