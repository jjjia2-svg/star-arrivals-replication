"""io_real: U6 real-data loading adapter (nine read-only sources + double-anchor provenance binding).

Contract gates: each table's column set is exactly the u0 schema; the star_set/events artifact-header 4-tuples equal the values pinned by the u4 ship,
and the dose_p01/dose_p05/output artifact headers equal the values pinned by the u5 ship. Any mismatch is a ProvenanceMismatch
HALT (not a WARN). Large tables (panel with 2 million rows / work_first_pub buckets) are read only with projection/filters,
and unrelated rows are never fully materialized.

The panel slice projects 5 columns {person_id, year, primary_affil_id, n_works_year,
first_pub_year}, taking only "dose incumbents ∪ roster persons ∪ event-star persons";
for a person missing a first-publication year, fall back to U1 work_first_pub (e.g. A5120638581: a 2025 newcomer is not in the panel).
"""
from __future__ import annotations

import json
import pathlib

import pyarrow.dataset as pads
import pyarrow.parquet as pq

from common.manifest import PROVENANCE_KEYS, ProvenanceMismatch, \
    verify_provenance
from common.schema import DEPT_ROSTER_PANEL, ECON_DEPT_REGISTRY, EVENTS, \
    OUTPUT, PAIRWISE_DOSE, PERSON_MAP, STAR_SET, assert_matches_schema

_PANEL_COLS = ("person_id", "year", "primary_affil_id", "n_works_year",
               "first_pub_year")


def _read_rows(path, *, schema: dict, label: str) -> list:
    t = pq.read_table(str(path))
    assert_matches_schema(t.schema.names, schema, label=label)
    return t.to_pylist()


def _verify_header(dir_path, expected: dict, *, label: str) -> dict:
    p = pathlib.Path(dir_path) / "manifest_header.json"
    if not p.is_file():
        raise ProvenanceMismatch(
            f"[{label}] upstream manifest_header missing: {p} — origin cannot be proven, HALT",
            key="manifest_header")
    header = json.loads(p.read_text(encoding="utf-8"))
    verify_provenance(header, {k: expected[k] for k in PROVENANCE_KEYS})
    return header


def build_real_inputs(paths: dict, *, pins_u4: dict, pins_u5: dict):
    """Nine-source loading -> U6Inputs. paths keys (a missing key raises KeyError; no default is assigned):
    person_map / star_set_dir / events_dir / dose_p01_dir / dose_p05_dir /
    output_dir / roster_files / registry / panel_dir / work_first_pub_glob /
    u5_diag_files.
    """
    from m7b_assemble.inputs import U6Inputs

    pm = _read_rows(paths["person_map"], schema=PERSON_MAP, label="person_map")

    hdr_star = _verify_header(paths["star_set_dir"], pins_u4, label="star_set")
    star_rows = _read_rows(
        pathlib.Path(paths["star_set_dir"]) / "star_set.parquet",
        schema=STAR_SET, label="star_set")
    _verify_header(paths["events_dir"], pins_u4, label="events")
    events = _read_rows(pathlib.Path(paths["events_dir"]) / "data.parquet",
                        schema=EVENTS, label="events")

    dose: dict = {}
    for lev in ("p01", "p05"):
        d_dir = pathlib.Path(paths[f"dose_{lev}_dir"]) / "_frozen"
        _verify_header(d_dir, pins_u5, label=f"dose_{lev}")
        dose[lev] = _read_rows(d_dir / "dose.parquet", schema=PAIRWISE_DOSE,
                               label=f"dose_{lev}")

    out_dir = pathlib.Path(paths["output_dir"]) / "_frozen"
    hdr_output = _verify_header(out_dir, pins_u5, label="output")
    output = {
        "p01": _read_rows(out_dir / "output_star1pct.parquet", schema=OUTPUT,
                          label="output_p01"),
        "p05": _read_rows(out_dir / "output_star5pct.parquet", schema=OUTPUT,
                          label="output_p05"),
    }

    roster: list = []
    for f in paths["roster_files"]:
        roster.extend(_read_rows(f, schema=DEPT_ROSTER_PANEL,
                                 label="dept_roster_panel"))
    registry = _read_rows(paths["registry"], schema=ECON_DEPT_REGISTRY,
                          label="econ_dept_registry")

    # --- panel slice (projection + persons filter) -------------------------------------
    pid_by_author = {r["author_id"]: r["person_id"] for r in pm}
    persons = set()
    for lev in ("p01", "p05"):
        persons |= {d["incumbent_person_id"] for d in dose[lev]}
    persons |= {pid_by_author[r["author_id"]] for r in roster
                if r["author_id"] in pid_by_author}
    persons |= {pid_by_author[e["star_person_id"]] for e in events
                if e["star_person_id"] in pid_by_author}
    ds = pads.dataset(str(paths["panel_dir"]))
    t = ds.to_table(columns=list(_PANEL_COLS),
                    filter=pads.field("person_id").isin(sorted(persons)))
    panel = t.to_pylist()

    # --- first-publication-year fallback: person missing from panel -> U1 work_first_pub (query only the missing fragments) ------------
    have_fp = {p["person_id"] for p in panel if p["first_pub_year"] is not None}
    missing_persons = sorted(
        {d["incumbent_person_id"] for lev in ("p01", "p05")
         for d in dose[lev]} - have_fp)
    work_first_pub: dict = {}
    if missing_persons:
        frags = sorted(a for a, pid in pid_by_author.items()
                       if pid in set(missing_persons))
        import duckdb

        con = duckdb.connect()
        try:
            import pyarrow as pa

            con.register("_want", pa.table({"id": frags}))
            rows = con.execute(
                f"SELECT w.author_id, w.first_pub_year FROM read_parquet("
                f"'{paths['work_first_pub_glob']}', hive_partitioning=0) w "
                f"JOIN _want t ON w.author_id = t.id"
            ).fetchall()
        finally:
            con.close()
        work_first_pub = {a: y for a, y in rows if y is not None}

    upstream_diag: dict = {}
    for name, f in (paths.get("u5_diag_files") or {}).items():
        fpath = pathlib.Path(f)
        if fpath.is_file():
            upstream_diag[name] = json.loads(fpath.read_text(encoding="utf-8"))

    quad = {k: hdr_star[k] for k in PROVENANCE_KEYS}
    quad_u5 = {k: hdr_output[k] for k in PROVENANCE_KEYS}
    inputs = U6Inputs(
        person_map=pm, star_set=star_rows, events=events, dose=dose,
        output=output, roster=roster, registry=registry, panel=panel,
        work_first_pub=work_first_pub,
        upstream_provenance={"u4": quad, "u5": quad_u5},
        upstream_diag=upstream_diag,
    )
    inputs.report = {
        "n_person_map": len(pm), "n_star_set": len(star_rows),
        "n_events": len(events),
        "n_dose": {p: len(dose[p]) for p in ("p01", "p05")},
        "n_output": {p: len(output[p]) for p in ("p01", "p05")},
        "n_roster": len(roster), "n_panel_slice": len(panel),
        "n_persons_of_interest": len(persons),
        "n_first_pub_fallback": len(work_first_pub),
        "missing_first_pub_persons": missing_persons,
    }
    return inputs
