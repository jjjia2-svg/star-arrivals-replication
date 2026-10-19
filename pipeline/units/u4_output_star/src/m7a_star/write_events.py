"""EVENTS writer: 11-column schema + PK event_id + canonical sort + atomic write + the star-list guard.

In plain words: the event table is one of the single sources of truth for the downstream
"arrival year / t-1 freeze point", and it is written only after four gates pass:
  ① the row key set is exactly the 11 EVENTS columns (assert_matches_schema; extra or missing keys both blow up);
  ② PK event_id is unique (one event per star; a duplicate = an assembly bug);
  ③ star-list guard: the star list of the event table == the shipped set of the frozen star_set
     (is_star_5pct and is_foreign_poach); one person more or fewer blows up (no missed person
     and no fake event, the Yves Zenou lesson; a hard requirement);
  ④ provenance empty values fail loudly (never write a placeholder string).
Canonical sort by (star_person_id, arrival_year); column order = schema key order; the write
goes through common.atomic_io.atomic_write_bytes (atomic sequence: either old or new, never
half written); parquet bytes are serialised with _DETERMINISTIC_PARQUET_KW (the same
deterministic rule as the whole pipeline).

IO layer (the pure decisions are in events_pipeline).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from common.atomic_io import atomic_write_bytes
from common.schema import EVENTS, assert_matches_schema
from common._redlines import RED
from m1_ingest._writer_util import _DETERMINISTIC_PARQUET_KW


class EventsShipSetMismatch(RuntimeError):
    """Star-list guard: the star list of the event table ≠ the shipped set of the frozen star_set (one more or one fewer both count)."""


# Registered type → arrow physical type (EVENTS int16 cast):
#   the schema declares three int16 columns (arrival_year/t_minus_1/departed_year); automatic
#   inference in pa.table used to write int64, which drifts from the registered schema.
#   category is written as string (the same as the on-disk convention of the whole pipeline:
#   no dictionary on the parquet side; _DETERMINISTIC_PARQUET_KW turns dictionaries off).
_ARROW_TYPE_BY_DECL = {
    "str": "string", "int16": "int16", "category": "string", "bool": "bool",
}


def _events_arrow_schema():
    """Cast each column to an arrow schema by its EVENTS registered type (int16 nullable; None stays null, never filled with 0)."""
    import pyarrow as pa

    factory = {"string": pa.string, "int16": pa.int16, "bool": pa.bool_}
    return pa.schema([
        (col, factory[_ARROW_TYPE_BY_DECL[decl]]())
        for col, decl in EVENTS.items()
    ])


def _events_parquet_bytes(rows: list[dict]) -> bytes:
    """Rows after canonical sort → deterministic parquet bytes (in-memory serialisation for the atomic write)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = _events_arrow_schema()
    columns = {c: [r[c] for r in rows] for c in EVENTS.keys()}
    table = pa.table(columns, schema=schema)     # The int16 cast happens here (an out-of-range value makes arrow blow up; never silently truncated)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, row_group_size=max(1, table.num_rows),
                   **_DETERMINISTIC_PARQUET_KW)
    return sink.getvalue().to_pybytes()


def write_events(
    rows: Iterable[dict],
    out_dir,
    *,
    ship_star_ids: set[str],
    stars_set_hash: str,
    source_snapshot_merkle: str,
    config_sha: str,
    n_polluted_dropped: int,
) -> dict:
    """Write EVENTS (written only if all four gates pass; if any gate blows up → nothing is written).

    Args:
        ship_star_ids: the shipped set derived from the frozen star_set (the author_id set of
            is_star_5pct and is_foreign_poach, produced by events_pipeline.ship_set_ids).
        stars_set_hash: the content fingerprint of the frozen star_set (freeze.stars_set_hash;
            binds the event table to the star set, used by downstream verify_provenance).
        n_polluted_dropped: total count dropped by the pollution guard (recorded in the header).
    Returns {"n_events", "path", "provenance_path", "header"}.
    """
    materialized = [dict(r) for r in rows]

    # --- gate ④ provenance empty values fail loudly (never a placeholder string) ---
    if not stars_set_hash or not source_snapshot_merkle or not config_sha:
        raise ValueError(
            "write_events: empty provenance value (stars_set_hash/source_snapshot_merkle/"
            "config_sha must all be non-empty) — a placeholder string is never written"
        )

    # --- reject an empty table (silently writing an empty event table = a fake clean result) ---
    if not materialized:
        raise ValueError(
            "write_events: 0 event rows + empty ship set — an empty events table is never written silently "
            "(an empty ship set should already fail in ship_events)"
        )

    # --- gate ① the schema has 11 columns (key sets exactly equal) ---
    for r in materialized:
        assert_matches_schema(r.keys(), EVENTS, label="events")

    # --- gate ② PK event_id is unique ---
    ids = [r["event_id"] for r in materialized]
    if len(ids) != len(set(ids)):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"write_events: duplicate event_id {dup} — one event per star; assembly bug")

    # --- gate ③ star list: event star list == shipped set (one more or fewer both blow up) ---
    event_stars = {r["star_person_id"] for r in materialized}
    extra = sorted(event_stars - set(ship_star_ids))
    missing = sorted(set(ship_star_ids) - event_stars)
    if extra or missing:
        raise EventsShipSetMismatch(
            f"S8-8 guard: events-table star list ≠ frozen ship set — extra {extra} / missing {missing} "
            "(not one star more or fewer: no missed people, no fake events)"
        )

    # --- canonical-sort by (star_person_id, arrival_year) (schema [23]) ---
    materialized.sort(key=lambda r: (r["star_person_id"], r["arrival_year"]))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    data_path = out / "data.parquet"
    atomic_write_bytes(data_path, _events_parquet_bytes(materialized))  # Atomic write

    header = {
        "table": "events",
        "stars_set_hash": stars_set_hash,
        "source_snapshot_merkle": source_snapshot_merkle,
        "config_sha": config_sha,
        "rule_version": RED.get("rule_version", ""),
        "n_events": len(materialized),
        "n_ship_stars": len(ship_star_ids),
        "n_polluted_dropped": int(n_polluted_dropped),
    }
    prov_path = out / "manifest_header.json"
    atomic_write_bytes(prov_path, json.dumps(
        header, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8"))
    return {"n_events": len(materialized), "path": str(data_path),
            "provenance_path": str(prov_path), "header": header}
