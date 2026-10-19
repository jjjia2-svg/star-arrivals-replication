#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R1 V3-NET (C5): freeze the two-hop network at T-1.

THE RULE (design v3 point 8; p2_decisions.json c_rulings C5 = 'v3'; code list C5 "drop the
deg-2 unfrozen arm"). A degree-2 relation (incumbent - mid - star) counts only if BOTH bridge edges, star-mid
and mid-incumbent, have a joint paper with publication year <= T-1, where T is the arrival year of the
event table the run uses (re-dates included). Degree 1 is already frozen at T-1 in prodlib
(prodlib.py:416-421); the new part is that prodlib's deg-2 "unfrozen" arm (prodlib.py:431-437) leaves the
network frame. Network-only relations that drop leave P1 and P2; 'both' relations are rebuilt by the union
builder / clone as dept_only, which is why the filter runs on the NETWORK frame BEFORE the union rung;
Panel 3's A_far in_net follows from the P2 channel column.

WHAT THIS MODULE DOES
  classify(con, graph, events, incumbents)  one SQL pass that replicates prodlib.build_subgraph (merged /
        pedges: snapshot edges of the seed works plus the supplement, years from the works table, the
        person map or the identity) and prodlib.build_pairs:384-449 (hop1 / hop2 earliest joint years,
        deg1_full with both edge years <= t1, banned = deg1_full + the star, frozen = y1 <= t1 and
        y2 <= t1). Seeds = the event stars and the frame's incumbents (all their author fragments under
        a person map), so hop2 is restricted to the incumbents the frame actually holds. Each
        (incumbent, event) gets deg1 | deg2_frozen | deg2_unfrozen | none.
  filter_frame(frame_in, classes, out, id_norm)  keeps the deg1 and deg2_frozen lines byte for byte (line
        endings included), drops deg2_unfrozen, and STOPs (NetworkFreezeStop, ids only, nothing written)
        on a relation that is 'none' (no path in the graph that built it) or that classify never saw.
        A 'none' relation is a STOP for a decision, never a silent keep or drop.
  apply(run_cfg, frame_in, out, ...)  the hook F11 / F14 call: switch row 'network_freeze' off -> the input
        path comes back, nothing is read or written (the October chains never import this module).
  proof_allowances(report)  the dropped relations, for F11's union_rows_proof.
  observe_prodlib(field, mirror, cfg, rec)  TEST/ORACLE ONLY: runs the pinned prodlib like
        stage.run_prodlib and records build_pairs' (degree, degree2_bridge_frozen) per pair.
  oracle(spec, out) / CLI `oracle`  the big-host proof (tests/test_r1_network_freeze_real.py, batch B4).

CLASSIFICATION GRAPH = the graph the row's builder used (decision sheet, not shipped): for chem/maths and the econ
prodlib-built events, the rendered prodlib config (graph_from_prodlib_config) - for the 2026-08-15 fn-fix
events that is the frozen econ_fnfix.json, whose snapshot copy and person map hold incumbents the U2 map lacks
(econ920_m.fnfix_graph; t-big-04); for the July-preserved econ rows, 11-school edges + the shadow's
concatenated econ supplement + the U2 person map (econ920_m.split_net1 / freeze_graphs). An unexplained
relation STOPs; J0's oracle measures the count on October inputs first.

Out of scope (since 2026-10-15): the new-star departure ledger and departure frames (F20) - the
paper prints no star-departure robustness.

    network_freeze.py oracle --spec SPEC.json --out DIR      (R1 instance only; prints RESULT OK|STOP)
"""
from __future__ import annotations

import argparse
import collections
import csv
import dataclasses
import hashlib
import importlib
import json
import os
import pathlib
import sys
from typing import Callable, NamedTuple

REPO = pathlib.Path(__file__).resolve().parents[3]
SWITCH = "network_freeze"
CLASSES = ("deg1", "deg2_frozen", "deg2_unfrozen", "none")
KEEP = frozenset({"deg1", "deg2_frozen"})
DROP = frozenset({"deg2_unfrozen"})
HOSTS = ("ec2-r1-test", "ec2-r1")
STOP_CODES = ("UNEXPLAINED", "UNCLASSIFIED", "T1_MISMATCH", "NOT_IN_TABLE", "NO_T1", "STAR_MISMATCH",
              "TABLE_ARRIVAL_MISSING")
IDS_IN_SUMMARY = 200


class NetworkFreezeStop(RuntimeError):
    """V3-NET cannot decide without a ruling. `ids` are (person, event) pairs or event ids - never names."""

    def __init__(self, code: str, ids, detail: str = ""):
        assert code in STOP_CODES, code
        self.code, self.ids = code, sorted(ids)
        shown = ", ".join(map(str, self.ids[:20])) + (" ..." if len(self.ids) > 20 else "")
        super().__init__(f"{code} ({len(self.ids)}): {shown}" + (f" - {detail}" if detail else ""))


@dataclasses.dataclass(frozen=True)
class Graph:
    """Where the edges come from, in prodlib's terms (cfg['snapshot'], cfg['supplement_jsonl'],
    cfg['person_map']). person_map_parquet None = the identity map (chem/maths silver rosters)."""
    edges_glob: str
    works_glob: str
    supplement_jsonl: str | None = None
    person_map_parquet: str | None = None


class Event(NamedTuple):
    event_id: str
    star_person_id: str
    t_minus_1: int


def graph_from_prodlib_config(cfg: dict) -> Graph:
    pm = cfg["person_map"]
    if pm["mode"] == "parquet":
        pm_path = str(pm["path"])
    elif pm["mode"] == "identity":
        pm_path = None
    else:
        raise ValueError(f"person_map.mode {pm['mode']!r} is not one prodlib knows")
    sup = cfg.get("supplement_jsonl")
    return Graph(str(cfg["snapshot"]["edges_glob"]), str(cfg["snapshot"]["works_glob"]),
                 str(sup) if sup else None, pm_path)


# ---- frames ---------------------------------------------------------------------------------------
def sha(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_lines(p) -> tuple[bytes, list[bytes], bool]:
    """(header, data lines, trailing newline?) as raw bytes; a '\\r' stays on its line (inpost_filter rule)."""
    raw = pathlib.Path(p).read_bytes()
    trailing = raw.endswith(b"\n")
    parts = raw.split(b"\n")
    if trailing:
        parts = parts[:-1]
    return parts[0], parts[1:], trailing


def cells(line: bytes) -> list[str]:
    return next(csv.reader([line.decode("utf-8").rstrip("\r")]))


def _frame(p) -> tuple[bytes, list[bytes], bool, list[list[str]], dict[str, int]]:
    header, lines, trailing = read_lines(p)
    hdr = cells(header)
    if "channel" in hdr:
        raise ValueError(f"{p} carries a channel column: V3-NET filters the network frame before the union "
                         "rung (the union builder rebuilds 'both' relations as dept_only); it never edits a "
                         "union output")
    col = {c: hdr.index(c) for c in ("incumbent_person_id", "year", "star_person_id", "event_id", "post")
           if c in hdr}
    missing = {"incumbent_person_id", "year", "star_person_id", "event_id", "post"} - set(col)
    if missing:
        raise ValueError(f"{p} lacks frame columns {sorted(missing)}")
    return header, lines, trailing, [cells(ln) for ln in lines], col


def _ident(x: str) -> str:
    return x


def read_event_table(path) -> dict[str, int]:
    """event_id -> arrival year. Two shapes: (event_id, arrival_year) (econ tables, U4 events parquet) or
    (author_id, school, arrival_corrected) (the chem/maths signed tables, event_id = author:school)."""
    path = pathlib.Path(path)
    if path.suffix == ".parquet":
        import pyarrow.parquet as pq                                     # noqa: PLC0415
        rows = pq.read_table(str(path)).to_pylist()
    else:
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    if not rows:
        return {}
    cols = set(rows[0])
    out, blank = {}, []
    for r in rows:
        if {"event_id", "arrival_year"} <= cols:
            eid, arr = str(r["event_id"]), r["arrival_year"]
        elif {"author_id", "school", "arrival_corrected"} <= cols:
            eid, arr = f"{r['author_id']}:{r['school']}", r["arrival_corrected"]
        else:
            raise ValueError(f"{path}: no (event_id, arrival_year) or (author_id, school, arrival_corrected)")
        if arr is None or str(arr).strip() == "":
            blank.append(eid)
            continue
        out[eid] = int(arr)
    if blank:
        raise NetworkFreezeStop("TABLE_ARRIVAL_MISSING", blank, str(path))
    return out


def events_from_frame(frame_csv, event_table=None, *, id_norm: Callable[[str], str] | None = None,
                      record: dict | None = None) -> list[Event]:
    """One Event per frame event: t_minus_1 = min(year | post true) - 1 (prodlib writes True, the July econ
    rows true). With an event table, every event must be in it and agree (arrival - 1); an event without
    post rows takes the table's arrival and is recorded; without a table it is a STOP."""
    norm = id_norm or _ident
    _h, _l, _t, parsed, col = _frame(frame_csv)
    stars, post_min = collections.defaultdict(set), {}
    for c in parsed:
        e = c[col["event_id"]]
        stars[e].add(norm(c[col["star_person_id"]]))
        if c[col["post"]].strip().lower() in ("true", "1"):
            y = int(c[col["year"]])
            post_min[e] = min(post_min.get(e, y), y)
    two = [e for e, s in stars.items() if len(s) != 1]
    if two:
        raise NetworkFreezeStop("STAR_MISMATCH", two, "an event with more than one star id in the frame")
    table = read_event_table(event_table) if event_table is not None else None
    out, fallback, not_in, mismatch, no_t1, checked = [], [], [], [], [], 0
    for e in sorted(stars):
        if table is not None and e not in table:
            not_in.append(e)
            continue
        if e in post_min:
            t1 = post_min[e] - 1
            if table is not None:
                checked += 1
                if table[e] - 1 != t1:
                    mismatch.append(e)
                    continue
        elif table is not None:
            t1 = table[e] - 1
            fallback.append(e)
        else:
            no_t1.append(e)
            continue
        out.append(Event(e, next(iter(stars[e])), t1))
    for code, ids in (("NOT_IN_TABLE", not_in), ("T1_MISMATCH", mismatch), ("NO_T1", no_t1)):
        if ids:
            raise NetworkFreezeStop(code, ids, f"frame {frame_csv} vs table {event_table}")
    if record is not None:
        record.update({"events": len(out), "crosschecked": checked, "fallback_to_table": fallback,
                       "event_table": str(event_table) if event_table is not None else None})
    return out


def incumbents_from_frame(frame_csv, *, id_norm: Callable[[str], str] | None = None) -> dict[str, set[str]]:
    norm = id_norm or _ident
    _h, _l, _t, parsed, col = _frame(frame_csv)
    inc = collections.defaultdict(set)
    for c in parsed:
        inc[c[col["event_id"]]].add(norm(c[col["incumbent_person_id"]]))
    return dict(inc)


# ---- the classifier (prodlib.build_subgraph + build_pairs:384-449, restricted to the frame) ----------
def _q(path: str) -> str:
    return str(path).replace("'", "''")


def _register(con, name: str, cols: dict) -> None:
    import pyarrow as pa                                                 # noqa: PLC0415
    con.register(f"_{name}_arrow", pa.table(cols))
    con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _{name}_arrow")
    con.unregister(f"_{name}_arrow")


def classify(con, graph: Graph, events: list[Event], incumbents: dict[str, set[str]]) -> dict:
    """{(person, event_id): class} for every incumbent of every event, on `con` (a duckdb connection the
    caller owns; a file-backed one on real data, so joins can spill)."""
    ev_ids = {e.event_id for e in events}
    unknown = sorted(set(incumbents) - ev_ids)
    if unknown:
        raise ValueError(f"incumbents for events without an Event: {unknown[:5]}")
    eg, wg = _q(graph.edges_glob), _q(graph.works_glob)
    con.execute("SET preserve_insertion_order=false")
    persons = {e.star_person_id for e in events} | {p for s in incumbents.values() for p in s}
    _register(con, "nf_persons", {"id": sorted(persons)})
    if graph.person_map_parquet:
        con.execute(f"""CREATE OR REPLACE TABLE nf_pm AS
            SELECT author_id, person_id FROM read_parquet('{_q(graph.person_map_parquet)}')""")
        con.execute("""CREATE OR REPLACE TABLE nf_seed AS
            SELECT DISTINCT pm.author_id AS id FROM nf_pm pm JOIN nf_persons p ON pm.person_id = p.id""")
    else:
        con.execute("CREATE OR REPLACE TABLE nf_seed AS SELECT id FROM nf_persons")

    # supplement pairs, exactly as prodlib.build_subgraph reads the jsonl
    w, a, y, t = [], [], [], []
    if graph.supplement_jsonl:
        with open(graph.supplement_jsonl, encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                for au in r["authors"]:
                    w.append(r["work_id"]), a.append(au), y.append(r["publication_year"]), t.append(r.get("type"))
    import pyarrow as pa                                                 # noqa: PLC0415
    _register(con, "nf_sup_raw", {"work_id": pa.array(w, pa.string()), "author_id": pa.array(a, pa.string()),
                                  "jsonl_year": pa.array(y, pa.int64()), "jsonl_type": pa.array(t, pa.string())})
    con.execute("""CREATE OR REPLACE TABLE nf_sup AS
        SELECT work_id, author_id, min(jsonl_year) AS jsonl_year, min(jsonl_type) AS jsonl_type
        FROM nf_sup_raw GROUP BY 1, 2""")
    con.execute(f"""CREATE OR REPLACE TABLE nf_seed_works AS
        SELECT DISTINCT e.work_id
        FROM read_parquet('{eg}', hive_partitioning=0) e JOIN nf_seed s ON e.author_id = s.id
        WHERE e.publication_year IS NOT NULL
        UNION
        SELECT DISTINCT p.work_id FROM nf_sup p JOIN nf_seed s ON p.author_id = s.id""")
    con.execute(f"""CREATE OR REPLACE TABLE nf_works_domain AS
        SELECT w.work_id, w.publication_year
        FROM read_parquet('{wg}', hive_partitioning=0) w JOIN nf_seed_works sw ON w.work_id = sw.work_id""")
    con.execute("""INSERT INTO nf_works_domain
        SELECT p.work_id, min(p.jsonl_year)
        FROM nf_sup p LEFT JOIN nf_works_domain w ON p.work_id = w.work_id
        WHERE w.work_id IS NULL GROUP BY p.work_id""")
    con.execute(f"""CREATE OR REPLACE TABLE nf_merged AS
        WITH snap AS (
          SELECT DISTINCT e.work_id, e.author_id, e.publication_year
          FROM read_parquet('{eg}', hive_partitioning=0) e JOIN nf_seed_works sw ON e.work_id = sw.work_id
          WHERE e.publication_year IS NOT NULL
        ), sup_new AS (
          SELECT p.work_id, p.author_id, wd.publication_year
          FROM nf_sup p JOIN nf_works_domain wd ON p.work_id = wd.work_id
          LEFT JOIN snap sn ON p.work_id = sn.work_id AND p.author_id = sn.author_id
          WHERE sn.work_id IS NULL AND wd.publication_year IS NOT NULL
        )
        SELECT * FROM snap UNION ALL SELECT DISTINCT * FROM sup_new""")
    if graph.person_map_parquet:
        con.execute("""CREATE OR REPLACE TABLE nf_pedges AS
            SELECT m.work_id, pm.person_id, m.publication_year FROM nf_merged m JOIN nf_pm pm
            ON m.author_id = pm.author_id""")
    else:
        con.execute("""CREATE OR REPLACE TABLE nf_pedges AS
            SELECT work_id, author_id AS person_id, publication_year FROM nf_merged""")

    _register(con, "nf_ev", {"event_id": [e.event_id for e in events],
                             "star": [e.star_person_id for e in events],
                             "t1": pa.array([int(e.t_minus_1) for e in events], pa.int64())})
    rel = sorted((p, e) for e, ps in incumbents.items() for p in ps)
    _register(con, "nf_rel", {"inc": pa.array([p for p, _ in rel], pa.string()),
                              "event_id": pa.array([e for _, e in rel], pa.string())})
    # hop1: star <-> mid, earliest joint year (prodlib.py:392-398)
    con.execute("""CREATE OR REPLACE TABLE nf_hop1 AS
        SELECT s.person_id AS star, o.person_id AS mid, min(s.publication_year) AS y1
        FROM nf_pedges s JOIN nf_pedges o USING (work_id)
        JOIN (SELECT DISTINCT star FROM nf_ev) st ON s.person_id = st.star
        WHERE o.person_id <> s.person_id GROUP BY 1, 2""")
    # hop2: mid <-> incumbent, earliest joint year, incumbents of the frame only (prodlib.py:400-406)
    con.execute("""CREATE OR REPLACE TABLE nf_hop2 AS
        SELECT m.person_id AS mid, i.person_id AS inc, min(m.publication_year) AS y2
        FROM nf_pedges m JOIN nf_pedges i USING (work_id)
        JOIN (SELECT DISTINCT mid FROM nf_hop1) h ON m.person_id = h.mid
        JOIN (SELECT DISTINCT inc FROM nf_rel) r ON i.person_id = r.inc
        WHERE m.person_id <> i.person_id GROUP BY 1, 2""")
    rows = con.execute("""
        WITH r AS (SELECT rl.inc, rl.event_id, ev.star, ev.t1 FROM nf_rel rl JOIN nf_ev ev ON ev.event_id = rl.event_id),
        d1 AS (   -- deg1_full (prodlib.py:416-421): a joint work, both edge years <= t1
          SELECT DISTINCT r.inc AS d1_inc, r.event_id AS d1_ev
          FROM r JOIN nf_pedges p1 ON p1.person_id = r.star
          JOIN nf_pedges p2 ON p2.work_id = p1.work_id AND p2.person_id = r.inc
          WHERE p1.publication_year <= r.t1 AND p2.publication_year <= r.t1 AND r.inc <> r.star
        ),
        d2 AS (   -- deg2 frozen / any (prodlib.py:424-437)
          SELECT r.inc AS d2_inc, r.event_id AS d2_ev, bool_or(h1.y1 <= r.t1 AND h2.y2 <= r.t1) AS frozen
          FROM r JOIN nf_hop1 h1 ON h1.star = r.star
          JOIN nf_hop2 h2 ON h2.mid = h1.mid AND h2.inc = r.inc
          GROUP BY 1, 2
        )
        SELECT r.inc, r.event_id,
               CASE WHEN r.inc = r.star THEN 'none'
                    WHEN d1.d1_inc IS NOT NULL THEN 'deg1'
                    WHEN d2.frozen THEN 'deg2_frozen'
                    WHEN d2.d2_inc IS NOT NULL THEN 'deg2_unfrozen'
                    ELSE 'none' END
        FROM r
        LEFT JOIN d1 ON d1.d1_inc = r.inc AND d1.d1_ev = r.event_id
        LEFT JOIN d2 ON d2.d2_inc = r.inc AND d2.d2_ev = r.event_id""").fetchall()
    out = {(p, e): c for p, e, c in rows}
    assert len(out) == len(rel) == len(rows), (len(out), len(rel), len(rows))
    return out


def class_counts(classes: dict) -> dict[str, dict[str, int]]:
    per = collections.defaultdict(lambda: dict.fromkeys(CLASSES, 0))
    for (_p, e), c in classes.items():
        per[e][c] += 1
    return {e: per[e] for e in sorted(per)}


# ---- the filter -------------------------------------------------------------------------------------
def filter_frame(frame_in, classes: dict, out, id_norm: Callable[[str], str] | None = None) -> dict:
    """Keep deg1 / deg2_frozen lines byte for byte, drop deg2_unfrozen; STOP before writing on an
    unclassified or 'none' relation. Report: relations and rows by class, per event, removed relations
    (frame id form), events left with zero rows, input/output sha256."""
    norm = id_norm or _ident
    header, lines, trailing, parsed, col = _frame(frame_in)
    ip, ie = col["incumbent_person_id"], col["event_id"]
    rel_cls: dict[tuple[str, str], str] = {}
    missing = set()
    for c in parsed:
        k = (c[ip], c[ie])
        if k in rel_cls or k in missing:
            continue
        got = classes.get((norm(c[ip]), c[ie]))
        if got is None:
            missing.add(k)
        else:
            assert got in CLASSES, got
            rel_cls[k] = got
    if missing:
        raise NetworkFreezeStop("UNCLASSIFIED", missing, f"relations of {frame_in} that classify never saw")
    none = [k for k, v in rel_cls.items() if v == "none"]
    if none:
        raise NetworkFreezeStop("UNEXPLAINED", none, "network relations with no path in their builder's graph")
    rows_by = dict.fromkeys(CLASSES, 0)
    per_event: dict[str, dict] = {}
    kept = []
    for ln, c in zip(lines, parsed):
        k = (c[ip], c[ie])
        cl = rel_cls[k]
        rows_by[cl] += 1
        d = per_event.setdefault(c[ie], {"relations": dict.fromkeys(CLASSES, 0), "rows_kept": 0,
                                         "rows_dropped": 0})
        if cl in KEEP:
            kept.append(ln)
            d["rows_kept"] += 1
        else:
            d["rows_dropped"] += 1
    rel_by = dict.fromkeys(CLASSES, 0)
    for (_p, e), cl in rel_cls.items():
        rel_by[cl] += 1
        per_event[e]["relations"][cl] += 1
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"\n".join([header] + kept) + (b"\n" if trailing else b""))
    dropped = len(lines) - len(kept)
    assert dropped == rows_by["deg2_unfrozen"] and sum(rows_by.values()) == len(lines)
    removed = sorted([p, e] for (p, e), cl in rel_cls.items() if cl in DROP)
    return {
        "stage": "network_freeze (V3-NET, C5)", "rule": "keep deg1 and deg2 with both bridge edges <= T-1",
        "input": {"frame": str(frame_in), "sha256": sha(frame_in), "rows": len(lines),
                  "relations": len(rel_cls), "events": len(per_event)},
        "relations_by_class": rel_by, "rows_by_class": rows_by, "rows_dropped": dropped,
        "removed_relations": removed,
        "events_left_with_zero_rows": sorted(e for e, d in per_event.items() if d["rows_kept"] == 0),
        "per_event": dict(sorted(per_event.items())),
        "output": {"frame": str(out), "sha256": sha(out), "rows": len(kept), "byte_preserving": True},
    }


def proof_allowances(report: dict) -> dict[str, set]:
    """For F11's union_rows_proof: 'removed' = the (person, event) relations whose network rows V3-NET
    dropped (they may no longer appear as network/both rows); 'to_dept_candidates' = those of them the
    union rung may rebuild as dept_only rows (a relation that also has a roster channel). This module sees
    only the network frame, so every removed relation is a candidate; the union builder decides."""
    removed = {(p, e) for p, e in report["removed_relations"]}
    return {"removed": removed, "to_dept_candidates": set(removed)}


def apply(run_cfg, frame_in, out, *, graph: Graph, event_table=None, id_norm=None, report_path=None,
          db_path=None) -> tuple[pathlib.Path, dict | None]:
    """The hook. Switch off -> (frame_in, None), nothing read or written. On -> classify the frame's
    relations on `graph`, filter into `out`, write the report to `report_path` if given."""
    frame_in = pathlib.Path(frame_in)
    if not run_cfg.is_on(SWITCH):
        return frame_in, None
    import duckdb                                                        # noqa: PLC0415
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    db = pathlib.Path(db_path) if db_path else out.parent / f".{out.name}.network_freeze.duckdb"
    rec: dict = {}
    events = events_from_frame(frame_in, event_table, id_norm=id_norm, record=rec)
    inc = incumbents_from_frame(frame_in, id_norm=id_norm)
    con = duckdb.connect(str(db))
    try:
        classes = classify(con, graph, events, inc)
    finally:
        con.close()
        for p in (db, pathlib.Path(str(db) + ".wal")):
            if p.exists():
                p.unlink()
    report = filter_frame(frame_in, classes, out, id_norm=id_norm)
    report["events_t1"] = rec
    report["graph"] = dataclasses.asdict(graph)
    if report_path is not None:
        rp = pathlib.Path(report_path)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out, report


# ---- the prodlib observer (oracle / tests only) -----------------------------------------------------
def _stage_module():
    layer = REPO / "pipeline" / "frames" / "cal2026-10"
    for p in (str(REPO), str(layer), str(REPO / "pipeline" / "stars" / "caliber_2026-08-28")):
        if p not in sys.path:
            sys.path.insert(0, p)
    return importlib.import_module("stage")


def observe_prodlib(field: str, mirror, cfg: dict, rec: dict) -> tuple[pathlib.Path, list[tuple]]:
    """Run the pinned prodlib on `cfg` exactly like stage.run_prodlib, recording what build_pairs returns:
    [(incumbent, star, event_id, degree, degree2_bridge_frozen)]. The staged prodlib is imported AFTER
    frames_stage.preimport_prodlib_units (so mpimports binds this repo's ported units), its file and sha
    are asserted, and build_pairs is wrapped in its module globals (prodlib.build calls it there)."""
    pa_stage = _stage_module()
    fs08 = pa_stage.fs08
    mirror = pathlib.Path(mirror)
    mirror.mkdir(parents=True, exist_ok=True)
    fs08.stage_prodlib(mirror)
    rec.setdefault("unit_modules", fs08.preimport_prodlib_units())
    code = mirror / "code"
    target = (code / "prodlib.py").resolve()
    for name in ("prodlib", "mpimports"):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(code))
    prodlib = importlib.import_module("prodlib")
    assert pathlib.Path(prodlib.__file__).resolve() == target, (prodlib.__file__, target)
    want = fs08.PINNED_LEGACY_CODE["multidisc_prod_2026-07-24/code/prodlib.py"]
    assert fs08.sha(target) == want, "staged prodlib is not the pinned code"
    seen: list[tuple] = []
    orig = prodlib.build_pairs

    def recording_build_pairs(*args, **kwargs):
        pairs = orig(*args, **kwargs)
        seen.extend((r["incumbent_person_id"], r["star_person_id"], r["event_id"], int(r["degree"]),
                     bool(r["degree2_bridge_frozen"])) for r in pairs)
        return pairs

    prodlib.build_pairs = recording_build_pairs
    try:
        frame = pa_stage.run_prodlib(field, mirror, cfg, rec)
    finally:
        prodlib.build_pairs = orig
    assert sys.modules.get("prodlib") is prodlib, "build_frame.py imported another prodlib"
    assert seen, "build_pairs was never called"
    return pathlib.Path(frame), seen


def observed_class(degree: int, frozen: bool) -> str:
    return "deg1" if degree == 1 else ("deg2_frozen" if frozen else "deg2_unfrozen")


# ---- the oracle (big host, batch B4) ----------------------------------------------------------------
def _default_table(cfg: dict):
    ev = cfg["events"]
    if ev["mode"] == "signed_csv":
        return ev["signed_csv"]
    if ev["mode"] == "u4_frozen":
        return str(pathlib.Path(ev["events_dir"]) / "data.parquet")
    return None


def _classify_file(frame, graph, table, db) -> tuple[dict, dict]:
    import duckdb                                                        # noqa: PLC0415
    rec: dict = {}
    events = events_from_frame(frame, table, record=rec)
    con = duckdb.connect(str(db))
    try:
        return classify(con, graph, events, incumbents_from_frame(frame)), rec
    finally:
        con.close()


def _observe(item: dict, out: pathlib.Path) -> dict:
    label = item["label"]
    cfg = json.loads(pathlib.Path(item["config"]).read_text(encoding="utf-8"))
    work = out / label
    cfg["run_dir"] = str(work / "run")
    rec: dict = {}
    frame, pairs = observe_prodlib(item["field"], work / "mirror", cfg, rec)
    obs = {(p, e): observed_class(d, f) for p, _s, e, d, f in pairs}
    assert len(obs) == len(pairs), "a (person, event) pair twice in build_pairs"
    table = item.get("event_table") or _default_table(cfg)
    classes, t1rec = _classify_file(frame, graph_from_prodlib_config(cfg), table, work / "classify.duckdb")
    mism = sorted(k for k in set(obs) | set(classes) if obs.get(k) != classes.get(k))
    per_mine = class_counts(classes)
    built = json.loads((work / "run" / "build_report.json").read_text(encoding="utf-8"))["pairs"]["per_event"]
    zero = dict.fromkeys(CLASSES, 0)
    per_bad = sorted(e for e in set(built) | set(per_mine)
                     if {k: built.get(e, {}).get(k, 0) for k in CLASSES[:3]}
                     != {k: per_mine.get(e, zero)[k] for k in CLASSES[:3]})
    return {"pairs_observed": len(obs), "relations_classified": len(classes),
            "by_class_observed": dict(collections.Counter(obs.values())),
            "none": sum(1 for v in classes.values() if v == "none"),
            "pair_mismatches": len(mism), "pair_mismatch_ids": [list(k) for k in mism[:IDS_IN_SUMMARY]],
            "per_event_mismatches": len(per_bad), "per_event_mismatch_ids": per_bad[:IDS_IN_SUMMARY],
            "events_t1": {k: v for k, v in t1rec.items() if k != "fallback_to_table"},
            "fallback_to_table": t1rec.get("fallback_to_table", []),
            "frame_sha256": sha(frame)}


def _u5_matrix(dose_parquet, classes: dict) -> dict:
    import pyarrow.parquet as pq                                         # noqa: PLC0415
    names = pq.ParquetFile(str(dose_parquet)).schema_arrow.names
    if "degree2_bridge_frozen" not in names or "degree" not in names:
        return {"flags": "absent", "columns": names}
    t = pq.read_table(str(dose_parquet), columns=["incumbent_person_id", "event_id", "degree",
                                                  "degree2_bridge_frozen"]).to_pylist()
    u5 = {}
    for r in t:
        u5[(r["incumbent_person_id"], r["event_id"])] = observed_class(int(r["degree"]),
                                                                       bool(r["degree2_bridge_frozen"]))
    both = set(u5) & set(classes)
    matrix = collections.Counter(f"{u5[k]}->{classes[k]}" for k in both)
    return {"flags": "present", "matrix": dict(sorted(matrix.items())), "relations_both": len(both),
            "only_in_u5": len(set(u5) - set(classes)),
            "only_in_frame": len(set(classes) - set(u5)),
            "disagreement_ids": [list(k) for k in sorted(k for k in both if u5[k] != classes[k])][:IDS_IN_SUMMARY]}


def _frame_item(item: dict, out: pathlib.Path) -> dict:
    label = item["label"]
    work = out / label
    work.mkdir(parents=True, exist_ok=True)
    if "config" in item:
        graph = graph_from_prodlib_config(json.loads(pathlib.Path(item["config"]).read_text(encoding="utf-8")))
    else:
        g = item["graph"]
        graph = Graph(g["edges_glob"], g["works_glob"], g.get("supplement_jsonl"), g.get("person_map"))
    res: dict = {"stop": None, "frame_sha256": sha(item["frame"])}
    try:
        classes, t1rec = _classify_file(item["frame"], graph, item.get("event_table"), work / "classify.duckdb")
    except NetworkFreezeStop as e:
        res.update({"stop": e.code, "stop_ids": [list(x) if isinstance(x, tuple) else x
                                                  for x in e.ids[:IDS_IN_SUMMARY]]})
        return res
    res["events_t1"] = {k: v for k, v in t1rec.items() if k != "fallback_to_table"}
    res["fallback_to_table"] = t1rec.get("fallback_to_table", [])
    res["u5"] = _u5_matrix(item["u5_dose"], classes) if item.get("u5_dose") else {"flags": "not_given"}
    try:
        rep = filter_frame(item["frame"], classes, work / "frame_v3net.csv")
    except NetworkFreezeStop as e:
        rel = collections.Counter(classes.values())
        res.update({"stop": e.code, "stop_ids": [list(x) for x in e.ids[:IDS_IN_SUMMARY]],
                    "n_stop_ids": len(e.ids), "relations_by_class": {k: rel.get(k, 0) for k in CLASSES}})
        return res
    res.update({k: rep[k] for k in ("relations_by_class", "rows_by_class", "rows_dropped",
                                    "events_left_with_zero_rows")})
    res["input"], res["output"] = rep["input"], rep["output"]
    res["relations_removed"] = len(rep["removed_relations"])
    res["per_event"] = {e: {"relations": d["relations"], "rows_dropped": d["rows_dropped"]}
                        for e, d in rep["per_event"].items()}
    return res


def oracle(spec: dict, out) -> dict:
    """spec (sar.r1.v3net_oracle_spec.v1): {"observe": [{label, field, config, event_table?}],
    "frames": [{label, frame, config | graph{edges_glob, works_glob, supplement_jsonl, person_map},
    event_table?, u5_dose?}]}. Writes out/summary.json (counts and ids only) and returns it."""
    if os.environ.get("SAR_HOST", "").strip() not in HOSTS:
        raise SystemExit("network_freeze oracle runs only on an R1 instance ($SAR_HOST)")
    if spec.get("schema") != "sar.r1.v3net_oracle_spec.v1":
        raise SystemExit(f"spec schema {spec.get('schema')!r} is not sar.r1.v3net_oracle_spec.v1")
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    summary: dict = {"schema": "sar.r1.v3net_oracle.v1", "observe": {}, "frames": {}}
    for item in spec.get("observe", []):
        summary["observe"][item["label"]] = _observe(item, out)
    for item in spec.get("frames", []):
        summary["frames"][item["label"]] = _frame_item(item, out)
    bad_obs = [k for k, r in summary["observe"].items()
               if r["pair_mismatches"] or r["per_event_mismatches"] or r["none"]]
    bad_fr = [k for k, r in summary["frames"].items() if r["stop"]]
    summary["result"] = "OK" if not bad_obs and not bad_fr else "STOP"
    summary["stopped"] = {"observe": bad_obs, "frames": bad_fr}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                                      encoding="utf-8")
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("oracle", help="the V3-NET big-host proof (R1 instance only)")
    o.add_argument("--spec", required=True)
    o.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    s = oracle(json.loads(pathlib.Path(a.spec).read_text(encoding="utf-8")), a.out)
    print(f"RESULT {s['result']}")
    return 0 if s["result"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
