#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cal2026-10/inpost_filter.py — D2: drop every network-route row whose incumbent was NOT in post
at a sample department of the SAME field in the event's arrival year. Repo-authored stage; runs on
a prodlib output frame (analysis_frame_p01_52ev_topicdose_2026-07-21.csv shape, 16 columns, no
channel) BEFORE the union builder, so every row it sees is a network-channel row and the roster
channel's semantics are untouched (the union builder adds roster rows afterwards, on the roster's
own in-post join).

    setup/.venv/bin/python pipeline/frames/cal2026-10/inpost_filter.py FRAME.csv \\
        --roster roster.parquet [--person-map pm.parquet | --identity] [--spells spells.csv] \\
        --out FRAME_inpost.csv --report build_report.json

The rule (the join of the 2026-09-13 in-post diagnostic, an author-only script that is not shipped,
promoted to a construction stage by the author's D2 ruling of 2026-09-22)
  * a SPELL is one roster row (author_id, year_start, year_end), any department of the field's
    sample — the join is on the person only, NOT on the event's school ("in post at a sample
    department", ruling D2; the roster channel keeps its school-matched join elsewhere);
  * a spell is attached to every id form the frame can carry for that person: the bare author_id
    (identity person map: chemistry / math_stats), 'P_' + author_id, and every U2 person_id the
    person map assigns to that author_id (--person-map; the 2026-09-13 diagnostic's two forms);
  * a person's row for event e is KEPT when some spell has year_start <= arrival(e) <= year_end;
    DROPPED_NO_SPELL when the person has no spell at all (not on the field's roster — under D4
    this class is empty by construction once the pool is the roster; measured, not assumed);
    DROPPED_NOT_IN_POST otherwise (joined later or had left);
  * arrival(e) is read FROM THE FRAME: min(year) over the event's rows with post true (prodlib
    writes `True`, the July econ frame `true` — read case-insensitively; every row carries
    post = year >= arrival; event_id formats differ by field
    (econ star:arrival, chem/math author:school) so the id is never parsed);
  * --spells adds person-level spells (pid, year_start, year_end) verbatim — the control's way of
    feeding the 80 persons the 2026-09-13 diagnostic confirmed by person id.

Output: the frame with the dropped rows removed, every kept line byte-identical (line endings
included), header byte-identical; a build_report.json with the relation (person×event) and row
counts per class, per event {arrival, kept, dropped_no_spell, dropped_not_in_post} and per class
persons, the spell sources with sha256s, and the input/output sha256s.

Controls (run_controls.py, C3): on the network-channel rows of the frozen data/frames/p1_frame_econ.csv
with spells = the 920 roster (both id forms) + the 80 confirmed persons, the classes must reproduce
data/robustness_2026-09-13_inpost_diag/build_report.json exactly (network_inpost 1,862 /
network_notinpost 3,430 / network_no_spell 819); on network ∪ both rows, kept must grow by exactly
the both-channel relations (the diagnostic measured both_relations_not_in_post = 0).
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]
FRAME_COLS_MIN = ("incumbent_person_id", "year", "event_id", "post")


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------------------------
# spells
# ---------------------------------------------------------------------------------------------

def spells_from_roster(roster: pathlib.Path, person_map: pathlib.Path | None,
                       identity: bool) -> tuple[dict[str, list[tuple[int, int]]], dict]:
    """pid -> [(ys, ye)], every id form; a roster row with an open end is a hard error (the
    October roster has none; an open end would need the incumbent_roster late-binding rule)."""
    import duckdb                                                      # noqa: PLC0415
    con = duckdb.connect()
    rows = con.execute(f"SELECT author_id, year_start, year_end FROM read_parquet('{roster.as_posix()}')"
                       ).fetchall()
    bad = [r for r in rows if r[1] is None or r[2] is None or r[0] is None]
    assert not bad, f"roster rows with a null id or an open spell end: {bad[:5]}"
    pm_forms: dict[str, set[str]] = collections.defaultdict(set)
    src = {"roster": str(roster), "roster_sha256": sha(roster), "roster_rows": len(rows),
           "roster_persons": len({r[0] for r in rows})}
    if person_map is not None:
        for a, p in con.execute(
                f"SELECT author_id, person_id FROM read_parquet('{person_map.as_posix()}')").fetchall():
            pm_forms[a].add(p)
        src.update({"person_map": str(person_map), "person_map_sha256": sha(person_map)})
    con.close()
    spells: dict[str, list[tuple[int, int]]] = collections.defaultdict(list)
    for a, ys, ye in rows:
        forms = {a, f"P_{a}"} if not identity else {a}
        forms |= pm_forms.get(a, set())
        for f in forms:
            spells[f].append((int(ys), int(ye)))
    src["id_forms"] = "bare author_id" + ("" if identity else " + P_author_id") + \
        (" + U2 person_id" if person_map is not None else "")
    return spells, src


def spells_from_csv(p: pathlib.Path, spells: dict) -> dict:
    n = 0
    with open(p, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            spells[r["pid"]].append((int(r["year_start"]), int(r["year_end"])))
            n += 1
    return {"spells_csv": str(p), "spells_csv_sha256": sha(p), "rows": n}


# ---------------------------------------------------------------------------------------------
# the filter
# ---------------------------------------------------------------------------------------------

def read_lines(p: pathlib.Path) -> tuple[bytes, list[bytes], bool]:
    """(header line, data lines, trailing newline?) — raw bytes, '\\r' kept on each line."""
    raw = p.read_bytes()
    trailing = raw.endswith(b"\n")
    parts = raw.split(b"\n")
    if trailing:
        parts = parts[:-1]
    return parts[0], parts[1:], trailing


def cells(line: bytes) -> list[str]:
    return next(csv.reader([line.decode("utf-8").rstrip("\r")]))


def classify(frame: pathlib.Path, spells: dict[str, list[tuple[int, int]]]) -> dict:
    header, lines, trailing = read_lines(frame)
    hdr = cells(header)
    for c in FRAME_COLS_MIN:
        assert c in hdr, f"frame lacks column {c}: {hdr}"
    ip, iy, ie, ipost = (hdr.index(c) for c in FRAME_COLS_MIN)
    parsed = [cells(ln) for ln in lines]
    arrival: dict[str, int] = {}
    for c in parsed:
        if c[ipost].strip().lower() in ("true", "1"):     # prodlib writes True; the July frame true
            y = int(c[iy])
            arrival[c[ie]] = min(arrival.get(c[ie], y), y)
    events = {c[ie] for c in parsed}
    assert events <= set(arrival), f"events without a post=True row: {sorted(events - set(arrival))[:5]}"
    cls: dict[tuple[str, str], str] = {}
    for c in parsed:
        k = (c[ip], c[ie])
        if k in cls:
            continue
        sp = spells.get(c[ip])
        if not sp:
            cls[k] = "dropped_no_spell"
        elif any(ys <= arrival[c[ie]] <= ye for ys, ye in sp):
            cls[k] = "kept"
        else:
            cls[k] = "dropped_not_in_post"
    return {"header": header, "lines": lines, "trailing": trailing, "parsed": parsed,
            "ip": ip, "ie": ie, "arrival": arrival, "cls": cls}


def run(frame: pathlib.Path, spells: dict, sources: dict, out: pathlib.Path,
        report_p: pathlib.Path) -> dict:
    st = classify(frame, spells)
    cls, parsed = st["cls"], st["parsed"]
    rel = collections.Counter(cls.values())
    rows = collections.Counter(cls[(c[st["ip"]], c[st["ie"]])] for c in parsed)
    per_event: dict[str, dict] = {}
    for (pid, ev), k in cls.items():
        d = per_event.setdefault(ev, {"arrival": st["arrival"][ev], "kept": 0,
                                      "dropped_no_spell": 0, "dropped_not_in_post": 0})
        d[k] += 1
    persons = {k: len({pid for (pid, ev), c in cls.items() if c == k})
               for k in ("kept", "dropped_no_spell", "dropped_not_in_post")}
    out.parent.mkdir(parents=True, exist_ok=True)
    kept_lines = [ln for ln, c in zip(st["lines"], parsed) if cls[(c[st["ip"]], c[st["ie"]])] == "kept"]
    blob = b"\n".join([st["header"]] + kept_lines) + (b"\n" if st["trailing"] else b"")
    out.write_bytes(blob)
    report = {
        "stage": "inpost_filter (D2, 2026-09-22)", "rule": "keep (person, event) iff some spell of the"
        " person in the field's roster has year_start <= arrival <= year_end; join on the person only",
        "input": {"frame": str(frame), "sha256": sha(frame), "rows": len(parsed),
                  "relations": len(cls), "events": len(st["arrival"])},
        "spells": {**sources, "persons_with_spells": len(spells)},
        "relations_by_class": {k: rel.get(k, 0) for k in ("kept", "dropped_no_spell",
                                                          "dropped_not_in_post")},
        "rows_by_class": {k: rows.get(k, 0) for k in ("kept", "dropped_no_spell",
                                                      "dropped_not_in_post")},
        "persons_by_class": persons,
        "events_left_with_zero_rows": sorted(e for e, d in per_event.items() if d["kept"] == 0),
        "per_event": dict(sorted(per_event.items())),
        "output": {"frame": str(out), "sha256": sha(out), "rows": len(kept_lines),
                   "byte_preserving": True},
    }
    report_p.parent.mkdir(parents=True, exist_ok=True)
    report_p.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("frame", type=pathlib.Path)
    ap.add_argument("--roster", type=pathlib.Path, help="roster parquet (author_id, year_start, year_end)")
    ap.add_argument("--person-map", type=pathlib.Path, default=None,
                    help="U2 person_map parquet: adds each author's person_id as an id form")
    ap.add_argument("--identity", action="store_true",
                    help="identity person map (chemistry/math_stats): bare author_id form only")
    ap.add_argument("--spells", type=pathlib.Path, default=None,
                    help="extra person-level spells CSV (pid,year_start,year_end), used verbatim")
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--report", type=pathlib.Path, required=True)
    a = ap.parse_args(argv)
    spells: dict = collections.defaultdict(list)
    sources: dict = {}
    if a.roster is not None:
        spells, sources = spells_from_roster(a.roster, a.person_map, a.identity)
    if a.spells is not None:
        sources["extra"] = spells_from_csv(a.spells, spells)
    if not spells:
        print("no spells: give --roster and/or --spells", file=sys.stderr)
        return 2
    rep = run(a.frame, spells, sources, a.out, a.report)
    print(json.dumps({k: rep[k] for k in ("relations_by_class", "rows_by_class",
                                          "events_left_with_zero_rows")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
