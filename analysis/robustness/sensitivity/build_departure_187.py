#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_departure_187.py — star-departure A/B sensitivity datasets from the 187-event departure
table (author decision D6, 2026-09-22): data/departure_verification_2026-09-10/
departure_verified_2026-09-10.csv (LLM-assisted from public records; not shipped, see the README —
this builder reads whatever the table says).

Same two rules as build_departure.py (2026-08-09 design), now for every discipline:
  A (drop):   remove every event whose star left within SIX years of arrival — verdict
              `left_within_window` (the table's window is arrival..arrival+5) or a numeric
              departure_year <= arrival + 6;
  B (recode): for every event with a numeric departure_year, treatment off from that year on
              (post -> False/0 in P1/P2, D -> 0 in the A_far pair frame) — departures after the
              window still matter for Panels 2 and 3, whose windows run ten years after arrival.
The frame surgery is the line-level, byte-preserving one of build_departure.py (imported); the
A_far frame goes through the proven ev -> event_id map of the caliber being built.

    build_departure_187.py --field econ --frames-dir data/cal2026-10/frames \
        --map data/cal2026-10/afar_event_map/afar_event_map_econ.csv --out data/cal2026-10/departure --stage /private/tmp/sar_dep187
Event ids: econ `star:year`, chemistry/mathematics `star:school` (as in the frames).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import sys

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
from build_departure import edit_csv_lines, sha   # noqa: E402  (the byte-preserving surgery)

LEDGER = REPO / "data" / "departure_verification_2026-09-10" / "departure_verified_2026-09-10.csv"   # not shipped
FIELD_DISC = {"econ": "econ", "chemistry": "chemistry", "math_stats": "math_stats"}


def ledger_rules(field: str) -> tuple[set[str], dict[str, int], dict]:
    d = pd.read_csv(LEDGER, dtype=str).fillna("")
    d = d[d.discipline == FIELD_DISC[field]]
    dep_year = pd.to_numeric(d.departure_year, errors="coerce")
    arrival = pd.to_numeric(d.arrival_year, errors="coerce")
    within6 = (d.verdict == "left_within_window") | (dep_year.notna() & (dep_year <= arrival + 6))
    keyed = d.event_id if field == "econ" else (d.star_author_id + ":" + d.school)
    excl = set(keyed[within6])
    dep_of = {k: int(y) for k, y in zip(keyed, dep_year) if pd.notna(y)}
    rep = {"ledger": str(LEDGER.relative_to(REPO)), "rows": int(len(d)),
           "verdicts": d.verdict.value_counts().to_dict(), "confidence": d.confidence.value_counts().to_dict(),
           "A_dropped_events": sorted(excl), "B_recode_events": {k: v for k, v in sorted(dep_of.items())},
           "unparseable_departure_years": sorted(set(keyed[(d.departure_year != "") & dep_year.isna()])),
           "note": "LLM-assisted verdicts from public records; 45 listed rows flagged for a manual check"}
    return excl, dep_of, rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--field", required=True, choices=list(FIELD_DISC))
    ap.add_argument("--frames-dir", required=True)
    ap.add_argument("--afar", help="A_far pos frame parquet (default <frames-dir>/p3_afar_pos_<field>.parquet)")
    ap.add_argument("--map", help="proven ev -> event_id map csv for that frame")
    ap.add_argument("--out", required=True)
    ap.add_argument("--stage", required=True)
    a = ap.parse_args(argv)
    fr, stage, out = pathlib.Path(a.frames_dir), pathlib.Path(a.stage), pathlib.Path(a.out)
    stage.mkdir(parents=True, exist_ok=True); out.mkdir(parents=True, exist_ok=True)
    excl, dep_of, rep = ledger_rules(a.field)
    f = a.field

    p1, p2 = fr / f"p1_frame_{f}.csv", fr / f"p2_becoming_{f}.csv"
    hdr1 = next(csv.reader([p1.open(encoding="utf-8").readline()]))
    y1, po1, e1 = hdr1.index("year"), hdr1.index("post"), hdr1.index("event_id")
    hdr2 = next(csv.reader([p2.open(encoding="utf-8").readline()]))
    y2, po2, e2 = hdr2.index("year"), hdr2.index("post"), hdr2.index("event_id")

    def recode_p1(cells):
        dep = dep_of.get(cells[e1])
        if dep is None or int(cells[y1]) < dep or cells[po1] != "True":
            return None
        cells = list(cells); cells[po1] = "False"; return cells

    def recode_p2(cells):
        dep = dep_of.get(cells[e2])
        if dep is None or int(cells[y2]) < dep or cells[po2] != "1":
            return None
        cells = list(cells); cells[po2] = "0"; return cells

    frames_events = set(pd.read_csv(p1, usecols=["event_id"]).event_id)
    rep["events_in_frame"] = len(frames_events)
    rep["A_dropped_in_frame"] = sorted(excl & frames_events)
    rep["B_recoded_in_frame"] = {k: v for k, v in dep_of.items() if k in frames_events}
    rep["ledger_events_not_in_frame"] = sorted((excl | set(dep_of)) - frames_events)
    rep["frames"] = {
        "p1_A": edit_csv_lines(p1, stage / f"p1_dep_A_{f}.csv", "event_id", excl, None),
        "p1_B": edit_csv_lines(p1, stage / f"p1_dep_B_{f}.csv", "event_id", set(), recode_p1),
        "p2_A": edit_csv_lines(p2, stage / f"p2_dep_A_{f}.csv", "event_id", excl, None),
        "p2_B": edit_csv_lines(p2, stage / f"p2_dep_B_{f}.csv", "event_id", set(), recode_p2)}
    ctl = edit_csv_lines(p1, stage / "_noop.csv", "event_id", set(), None)
    assert sha(stage / "_noop.csv") == sha(p1), "no-op surgery is not byte-identical — writer bug"
    (stage / "_noop.csv").unlink(); rep["noop_control"] = "BYTE_EQUAL"

    afar = pathlib.Path(a.afar) if a.afar else fr / f"p3_afar_pos_{f}.parquet"
    if a.map and afar.exists():
        mp = pd.read_csv(a.map); ev_of = dict(zip(mp.event_id, mp.ev))
        af = pd.read_parquet(afar)
        excl_ev = {ev_of[e] for e in excl if e in ev_of}
        dep_ev = {ev_of[e]: d for e, d in dep_of.items() if e in ev_of}
        aa = af[~af.ev.isin(excl_ev)]
        bb = af.copy(); depv = bb.ev.map(dep_ev)
        flip = depv.notna() & (bb.year >= depv.fillna(9999)) & (bb.D == 1)
        bb.loc[flip, "D"] = 0
        aa.to_parquet(stage / f"p3_afar_dep_A_{f}.parquet", index=False)
        bb.to_parquet(stage / f"p3_afar_dep_B_{f}.parquet", index=False)
        rep["afar"] = {"frame": str(afar), "events_in_afar": int(af.ev.nunique()), "A_dropped_in_afar": len(excl_ev),
                       "B_recoded_in_afar": len(dep_ev), "A_rows": int(len(aa)), "B_rows_flipped": int(flip.sum())}
    else:
        rep["afar"] = "not built (no --map or no A_far frame)"
    rep["staged_sha256"] = {p.name: sha(p) for p in sorted(stage.iterdir()) if p.is_file()}
    (out / f"departure187_build_report_{f}.json").write_text(json.dumps(rep, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("A_dropped_in_frame", "B_recoded_in_frame", "noop_control", "afar")}, indent=1, default=str)[:1500])
    print("DEPARTURE187_BUILD_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
