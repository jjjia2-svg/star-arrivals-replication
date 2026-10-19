"""EVENTS writer — 11-column schema + unique PK event_id + canonical-sort + atomic write + S8-8 guard.

In plain words: four gates before the events table is written: (1) the row key set == the 11 columns of schema [23]; (2) event_id has no duplicates;
(3) S8-8 — the star list of the events table == the frozen star_set shipping set (is_star_5pct ∧ is_foreign_poach),
one person too many or too few raises; (4) an empty provenance value fails loudly (no placeholder strings). canonical-sort by
(star_person_id, arrival_year) (schema [23]); atomic write (common.atomic_io, G7).
"""
import json

import pyarrow.parquet as pq
import pytest

from common.schema import EVENTS


def _event(star_id="A1", ay=2016, dept="I56590836"):
    return {"event_id": f"{star_id}:{ay}", "dept_id": dept,
            "star_person_id": star_id, "arrival_year": ay, "t_minus_1": ay - 1,
            "arrival_source": "official_roster", "arrival_evidence_strength": "strong",
            "modal_inst_year": True, "prior_main_exited": True,
            "min_tenure_ok": True, "departed_year": ay - 1}


def _write(tmp_path, rows, ship_ids, **kw):
    from m7a_star.write_events import write_events
    args = dict(ship_star_ids=set(ship_ids), stars_set_hash="h" * 64,
                source_snapshot_merkle="snap:TEST", config_sha="c" * 64,
                n_polluted_dropped=0)
    args.update(kw)
    return write_events(rows, tmp_path / "events", **args)


def test_write_events_lands_sorted_11cols_with_provenance(tmp_path):
    """Whole chain: 11-column order = schema key order; canonical-sort by (star_person_id, arrival_year);
    manifest_header carries stars_set_hash/merkle/config_sha/rule_version + n_events."""
    rows = [_event("B2", 2014), _event("A1", 2016), _event("A1x", 2010)]
    res = _write(tmp_path, rows, {"A1", "B2", "A1x"})

    p = tmp_path / "events" / "data.parquet"
    assert p.exists()
    t = pq.read_table(str(p))
    assert t.column_names == list(EVENTS.keys())            # column order fixed = schema [23]
    got = t.to_pylist()
    assert [(r["star_person_id"], r["arrival_year"]) for r in got] == [
        ("A1", 2016), ("A1x", 2010), ("B2", 2014)]          # canonical-sort

    hdr = json.loads((tmp_path / "events" / "manifest_header.json").read_text("utf-8"))
    assert hdr["table"] == "events"
    assert hdr["stars_set_hash"] == "h" * 64
    assert hdr["source_snapshot_merkle"] == "snap:TEST"
    assert hdr["config_sha"] == "c" * 64
    assert hdr["rule_version"] == "redlines_v4_signed_2026-07-05"
    assert hdr["n_events"] == 3 == res["n_events"]
    assert hdr["n_polluted_dropped"] == 0


def test_write_events_s88_extra_person_blows(tmp_path):
    """S8-8: the events table has one person not in the shipping set → raise + nothing written to disk."""
    from m7a_star.write_events import EventsShipSetMismatch
    with pytest.raises(EventsShipSetMismatch, match="A_extra"):
        _write(tmp_path, [_event("A1"), _event("A_extra")], {"A1"})
    assert not (tmp_path / "events").exists()


def test_write_events_s88_missing_person_blows(tmp_path):
    """S8-8: a person in the shipping set is absent from the events table (one too few) → also raises (no person may be missed, the Zenou lesson)."""
    from m7a_star.write_events import EventsShipSetMismatch
    with pytest.raises(EventsShipSetMismatch, match="A_missing"):
        _write(tmp_path, [_event("A1")], {"A1", "A_missing"})
    assert not (tmp_path / "events").exists()


def test_write_events_duplicate_event_id_blows(tmp_path):
    """PK event_id duplicated → raise (one event per star; a duplicate = an assembly bug)."""
    with pytest.raises(ValueError, match="event_id"):
        _write(tmp_path, [_event("A1"), _event("A1")], {"A1"})
    assert not (tmp_path / "events").exists()


def test_write_events_schema_mismatch_blows(tmp_path):
    """A row lacks one column (missing departed_year) → SchemaMismatchError (the key set must match exactly; extra or missing both raise)."""
    from common.schema import SchemaMismatchError
    bad = _event("A1")
    bad.pop("departed_year")
    with pytest.raises(SchemaMismatchError):
        _write(tmp_path, [bad], {"A1"})


def test_write_events_empty_table_refused(tmp_path):
    """Empty events table (0 rows + empty shipping set) → raise; silently writing an empty table = a false reconciliation."""
    with pytest.raises(ValueError, match="empty events table"):
        _write(tmp_path, [], set())


def test_write_events_blank_provenance_refused(tmp_path):
    """Any provenance value an empty string → raise + nothing written to disk (never a placeholder string)."""
    with pytest.raises(ValueError, match="provenance"):
        _write(tmp_path, [_event("A1")], {"A1"}, source_snapshot_merkle="")
    with pytest.raises(ValueError, match="provenance"):
        _write(tmp_path, [_event("A1")], {"A1"}, stars_set_hash="")
    assert not (tmp_path / "events").exists()


def test_write_events_atomic_no_tmp_leftover(tmp_path):
    """Atomic write: no *.tmp leftovers in the directory after writing (the G7 tmp→rename sequence finishes cleanly)."""
    _write(tmp_path, [_event("A1")], {"A1"})
    leftovers = [p.name for p in (tmp_path / "events").iterdir()
                 if p.suffix not in (".parquet", ".json")]
    assert leftovers == []
