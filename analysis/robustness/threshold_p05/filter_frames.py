#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""threshold_p05/filter_frames.py — the top-5% star-threshold robustness (author decision D7,
2026-09-22): the same models on the subset of events whose star passes the 5% cut of the same
ranking machine (data/cal2026-10/events_{field}_cal2026-10_p05.csv, written by
pipeline/stars/caliber_2026-10/write_events.py).

Nothing is re-estimated differently: each frame is filtered to the p05 events (rows whose event
belongs to the subset are kept byte-for-byte; every other row is dropped), then the VERBATIM
estimation drivers run on the filtered frames exactly as analysis/run_all.sh runs them. Frames:
  P1  p1_frame_{field}.csv          event column `event_id` (econ: star:year; chem/math: star:school)
  P2  p2_becoming_{field}.csv       event column `event_id`
  P3  p3_afar_pos_{field}.parquet   event column `ev` (DENSE_RANK code) -> mapped through the
      proven afar_event_map (data/robustness_2026-09-10_p3pos/afar_event_map/afar_event_map_{field}.csv
      or the October equivalent) to event ids
  P3 econ/chem full pair panels     built at frame-build time from the pair tables (event ids), not here

Usage: filter_frames.py --frames DIR --events-dir data/cal2026-10 --out DIR [--map-dir DIR]
Writes the filtered frames plus filter_report.json (events kept/dropped per frame, rows in/out).
A control: --events-dir pointing at the FULL event tables must reproduce every frame byte-for-byte
(the report records `byte_identical_to_input` per frame).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import sys

FIELDS = ("econ", "chemistry", "math_stats")


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def event_ids(events_dir: pathlib.Path, field: str, suffix: str) -> set[str]:
    p = events_dir / f"events_{field}_cal2026-10{suffix}.csv"
    with open(p, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if field == "econ":
        return {r["event_id"] for r in rows}
    return {f"{r['author_id']}:{r['school']}" for r in rows}


def filter_csv(src: pathlib.Path, dst: pathlib.Path, keep: set[str], col: str) -> dict:
    text = src.read_bytes().decode("utf-8")
    lines = text.split("\n")
    hdr = next(csv.reader([lines[0]]))
    ci = hdr.index(col)
    out, n_in, n_out, seen = [lines[0]], 0, 0, set()
    for ln in lines[1:]:
        if not ln:
            continue
        n_in += 1
        ev = next(csv.reader([ln]))[ci]
        seen.add(ev)
        if ev in keep:
            out.append(ln)
            n_out += 1
    dst.write_text("\n".join(out) + "\n", encoding="utf-8")
    return {"rows_in": n_in, "rows_out": n_out, "events_in": len(seen), "events_out": len(seen & keep),
            "byte_identical_to_input": sha(src) == sha(dst)}


def filter_parquet(src: pathlib.Path, dst: pathlib.Path, keep_codes: set[int]) -> dict:
    import pyarrow.parquet as pq
    import pyarrow.compute as pc
    t = pq.read_table(src)
    mask = pc.is_in(t["ev"], value_set=__import__("pyarrow").array(sorted(keep_codes), type=t["ev"].type))
    t2 = t.filter(mask)
    pq.write_table(t2, dst)
    return {"rows_in": t.num_rows, "rows_out": t2.num_rows, "events_in": len(set(t["ev"].to_pylist())),
            "events_out": len(set(t2["ev"].to_pylist()))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--frames", required=True)
    ap.add_argument("--events-dir", required=True)
    ap.add_argument("--suffix", default="_p05", help="event-table suffix; '' = the full tables (control)")
    ap.add_argument("--map-dir", default=None, help="directory holding afar_event_map_{field}.csv (ev -> event_id)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    fr, ev, out = pathlib.Path(a.frames), pathlib.Path(a.events_dir), pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rep = {"suffix": a.suffix, "frames": {}}
    for field in FIELDS:
        keep = event_ids(ev, field, a.suffix)
        rep["frames"][f"p1_frame_{field}.csv"] = filter_csv(fr / f"p1_frame_{field}.csv", out / f"p1_frame_{field}.csv", keep, "event_id")
        rep["frames"][f"p2_becoming_{field}.csv"] = filter_csv(fr / f"p2_becoming_{field}.csv", out / f"p2_becoming_{field}.csv", keep, "event_id")
        if a.map_dir:
            m = pathlib.Path(a.map_dir) / f"afar_event_map_{field}.csv"
            if m.exists():
                with open(m, newline="", encoding="utf-8") as f:
                    rows = list(csv.DictReader(f))
                codes = {int(r["ev"]) for r in rows if r["event_id"] in keep}
                for name in (f"p3_afar_pos_{field}.parquet",):  # the map is proven for the pos frame only; the full pair panels (cloud cells) get their p05 variant at frame-build time, where pairs still carry event ids
                    if (fr / name).exists():
                        rep["frames"][name] = filter_parquet(fr / name, out / name, codes)
            else:
                rep["frames"][f"p3_{field}"] = "no afar_event_map; P3 not filtered"
        rep["frames"][f"events_{field}"] = len(keep)
    (out / "filter_report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in rep["frames"].items() if isinstance(v, dict) and "rows_out" in v}, indent=0)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
