"""EVENTS int16 casting.

In plain words: schema.py [23] declares arrival_year/t_minus_1/departed_year as int16,
but write_events used to let pyarrow infer them automatically → written as int64, drifting from the registered schema.
This test pins: the physical type of each column in the written parquet == the registered type (int16 cast; departed_year
is a nullable int16, None stays null and is never filled with 0). Synthetic data, zero SSD writes.
"""
import pyarrow.parquet as pq


def _event(sid, arrival, *, departed=None):
    return {"event_id": f"{sid}:{arrival}", "dept_id": "I56590836",
            "star_person_id": sid, "arrival_year": arrival, "t_minus_1": arrival - 1,
            "arrival_source": "official_roster", "arrival_evidence_strength": "strong",
            "modal_inst_year": True, "prior_main_exited": departed is not None,
            "min_tenure_ok": True, "departed_year": departed}


def _write(tmp_path, rows):
    from m7a_star.write_events import write_events
    return write_events(rows, tmp_path / "events",
                        ship_star_ids={r["star_person_id"] for r in rows},
                        stars_set_hash="H", source_snapshot_merkle="M",
                        config_sha="C", n_polluted_dropped=0)


def test_events_year_columns_land_as_int16(tmp_path):
    """The three [23] int16 columns are written as pa.int16 (not the auto-inferred int64); the str/bool/category column types are also right."""
    import pyarrow as pa

    _write(tmp_path, [_event("A1", 2016, departed=2015)])
    schema = pq.read_table(str(tmp_path / "events" / "data.parquet")).schema
    assert schema.field("arrival_year").type == pa.int16()
    assert schema.field("t_minus_1").type == pa.int16()
    assert schema.field("departed_year").type == pa.int16()
    assert schema.field("event_id").type == pa.string()
    assert schema.field("arrival_source").type == pa.string()
    assert schema.field("modal_inst_year").type == pa.bool_()


def test_events_departed_none_stays_null_int16(tmp_path):
    """departed_year=None (no exit) → null in the int16 column, the value is not cast to 0 (a missing year stays empty, never filled with 0)."""
    _write(tmp_path, [_event("A1", 2016, departed=None)])
    t = pq.read_table(str(tmp_path / "events" / "data.parquet"))
    assert t.column("departed_year").to_pylist() == [None]
    assert t.column("arrival_year").to_pylist() == [2016]
