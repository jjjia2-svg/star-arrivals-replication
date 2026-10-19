#!/usr/bin/env python3
"""build_doublestar.py — double-star overlap drop datasets on the CANON frames (T6-3).

The paper's §3 sixth concern promises exactly one rule and no prior run exists anywhere
(2026-08-28 causal-gap audit: promised in writing, never run, no earlier code anywhere), so the implementation is the
paper's own sentence, nothing more:

    "dropping events that overlap with an earlier arrival in the same department"

Operationalisation, disclosed: event e (department d, arrival a_e) is dropped iff some event
e' of the same department has a_{e'} < a_e and a_e - a_{e'} <= 5 — i.e. e arrives while an
earlier star's treatment window is still running. The window is the paper's own coverage
window for Model 1, "the arrival year and the five years after it" (§3), the widest of the
three panels, applied as ONE rule across panels. Same-department pairs arriving in the SAME
year have no "earlier" member and are kept per the sentence; their count is reported.

Departments: economics events carry school in the canon ledger (one department per school
within the field); chemistry/math events are keyed star:school with school from the cal
event tables.

Outputs: drop tables + accounting to data/robustness_2026-08-29_b/doublestar/, variant
frames to --stage (scratch; regenerable from canon in seconds — P1/P2 by byte-preserving
line surgery, A_far via the proven ev map, P3 math_stats full via the shipped pairs_none
table re-slimmed by the repo's make_slim).

--spec (2026-09-10): `med` (default) = the retired median-cut A_far frames, the 2026-08-29 run
unchanged; `pos` = the paper's Panel 3 since 2026-08-30 (dose > 0): the A_far surgery reads
data/frames/p3_afar_pos_{field}.parquet through the pos maps and freezes under
data/robustness_2026-09-10_p3pos/doublestar/. The drop rule, the drop table, the P1/P2 line
surgery and the P3 math full re-slim are spec-independent and run the same code. --fields
restricts the FRAME surgery to the fields whose proven map exists (econ's pos map needs
pairs_unified.csv regenerated with the data disk); the drop table is always computed for all
three fields, and the fields not built are recorded in the report, never silently skipped.

Inputs by required flag (2026-10-16, R1 F3 part 8; no default, no environment fallback):
  --events-dir       chemistry/math_stats events_{field}_cal2026-10.csv (October: data/cal2026-10, whose
                     two tables are byte-equal to the data/cal2026-08-28/events_{field}_cal.csv read before)
  --frames-dir       p1_events_ledger_econ.csv, p1_frame_<f>.csv, p2_becoming_<f>.csv and the A_far frame
                     (October: data/frames)
  --pairs-none-math  the pairs table the P3 math full re-slim filters; replaces $SAR_PAIRS_MATH_STATS,
                     which is refused if still set (October: data/cal2026-08-28/frames/pairs_none_math_stats.parquet)
Relative values resolve against the repo root. With the October values every output is October's.
"""
import hashlib
import json
import os
import pathlib
import subprocess
import sys

import pandas as pd

REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.append(str(pathlib.Path(__file__).resolve().parent))
from build_departure import (AFAR_FRAME, DEFAULT_STAGE as _DEP_STAGE, FREEZE_ROOT, SPECS,  # noqa: E402
                             afar_map, edit_csv_lines)

FIELDS = ("econ", "chemistry", "math_stats")
DEFAULT_STAGE = {"med": "/private/tmp/sar_doublestar_2026-08-29",
                 "pos": "/private/tmp/sar_doublestar_2026-09-10_pos"}
assert set(DEFAULT_STAGE) == set(_DEP_STAGE) == set(SPECS)
W = 5  # the Model-1 coverage window: arrival year + five years after it


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def canon_events(field: str, *, events_dir: pathlib.Path, frames_dir: pathlib.Path) -> pd.DataFrame:
    if field == "econ":
        ev = pd.read_csv(pathlib.Path(frames_dir) / "p1_events_ledger_econ.csv")
        return ev[["event_id", "school", "arrival_year"]].rename(
            columns={"arrival_year": "arrival"})
    e = pd.read_csv(pathlib.Path(events_dir) / f"events_{field}_cal2026-10.csv")
    e["event_id"] = e.author_id + ":" + e.school
    return e[["event_id", "school", "arrival_corrected"]].rename(
        columns={"arrival_corrected": "arrival"})


def dropset(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    drops, sameyear = [], set()
    for _, g in df.groupby("school"):
        for _, r in g.iterrows():
            earlier = g[g.arrival < r.arrival]
            if ((r.arrival - earlier.arrival) <= W).any():
                drops.append(r.event_id)
            if len(g[(g.arrival == r.arrival) & (g.event_id != r.event_id)]):
                sameyear.add(r.event_id)
    return sorted(drops), sorted(sameyear)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--spec", choices=SPECS, default="med",
                    help="A_far frames to operate on: med = retired median cut (default, the "
                         "2026-08-29 run); pos = dose > 0, the paper's Panel 3 since 2026-08-30")
    ap.add_argument("--stage", help=f"default per --spec: {DEFAULT_STAGE}")
    ap.add_argument("--fields", default=",".join(FIELDS),
                    help="fields whose variant FRAMES are built (default all three); the drop "
                         "table always covers all three")
    ap.add_argument("--events-dir", required=True,
                    help="dir of events_{chemistry,math_stats}_cal2026-10.csv (October: data/cal2026-10)")
    ap.add_argument("--frames-dir", required=True,
                    help="dir of p1_events_ledger_econ.csv, p1_frame_<f>.csv, p2_becoming_<f>.csv and the A_far "
                         "frames (October: data/frames)")
    ap.add_argument("--pairs-none-math", required=True,
                    help="pairs_none table the P3 math full re-slim filters (October: "
                         "data/cal2026-08-28/frames/pairs_none_math_stats.parquet)")
    args = ap.parse_args(argv)
    if os.environ.get("SAR_PAIRS_MATH_STATS"):
        ap.error("$SAR_PAIRS_MATH_STATS is replaced by --pairs-none-math; unset it")
    events_dir, frames_dir = REPO / args.events_dir, REPO / args.frames_dir
    pairs_none_math = REPO / args.pairs_none_math
    print(json.dumps({"inputs": {"events_dir": str(events_dir), "frames_dir": str(frames_dir),
                                 "pairs_none_math": str(pairs_none_math)}}))
    stage = pathlib.Path(args.stage or DEFAULT_STAGE[args.spec])
    stage.mkdir(parents=True, exist_ok=True)
    OUT = REPO / (os.environ.get("SAR_ROBUST_OUTDIR") or f"{FREEZE_ROOT[args.spec]}/doublestar")  # 2026-09-23: env override, old value default
    OUT.mkdir(parents=True, exist_ok=True)
    build_fields = tuple(f for f in args.fields.split(",") if f)
    assert set(build_fields) <= set(FIELDS), build_fields
    rep: dict = {"rule": f"drop e iff an earlier same-department arrival is within {W} years "
                         f"(the §3 Model-1 coverage window); same-year pairs kept (no 'earlier' "
                         f"member), counts disclosed"}
    if args.spec != "med":
        rep["spec"] = args.spec
        rep["afar_frame"] = AFAR_FRAME[args.spec]
    if set(build_fields) != set(FIELDS):
        rep["fields_built"] = list(build_fields)
        rep["fields_NOT_built"] = [f for f in FIELDS if f not in build_fields]
    all_rows = []
    for field in FIELDS:
        ev = canon_events(field, events_dir=events_dir, frames_dir=frames_dir)
        drops, sameyear = dropset(ev)
        rep[field] = {"events": len(ev), "dropped": len(drops), "kept": len(ev) - len(drops),
                      "same_year_pair_events_kept": len(sameyear)}
        all_rows += [{"field": field, "event_id": e, "dropped": True} for e in drops]
        all_rows += [{"field": field, "event_id": e, "dropped": False}
                     for e in ev.event_id if e not in set(drops)]
        dset = set(drops)
        if field not in build_fields:
            rep[field]["frames"] = "NOT BUILT (field excluded by --fields; no proven map)"
            continue

        # P1 / P2: byte-preserving line drops
        p1 = frames_dir / f"p1_frame_{field}.csv"
        p2 = frames_dir / f"p2_becoming_{field}.csv"
        rep[field]["p1"] = edit_csv_lines(p1, stage / f"p1_ds_{field}.csv", "event_id", dset, None)
        rep[field]["p2"] = edit_csv_lines(p2, stage / f"p2_ds_{field}.csv", "event_id", dset, None)

        # A_far: through the proven ev map
        mp = afar_map(args.spec, field)
        af = pd.read_parquet(frames_dir / pathlib.PurePosixPath(AFAR_FRAME[args.spec].format(field=field)).name)
        drop_ev = set(mp[mp.event_id.isin(dset)].ev)
        afd = af[~af.ev.isin(drop_ev)]
        afd.to_parquet(stage / f"p3_afar_ds_{field}.parquet", index=False)
        rep[field]["afar"] = {"events_in_afar": int(af.ev.nunique()),
                              "dropped_in_afar": len(drop_ev), "rows_kept": len(afd)}

        # P3 full panel, math_stats only (the one locally runnable full panel): filter the
        # shipped pairs table by event and re-slim with the repo's make_slim
        if field == "math_stats":
            pn = pd.read_parquet(pairs_none_math)   # 2026-10-16: --pairs-none-math (was $SAR_PAIRS_MATH_STATS)
            kept = pn[~pn.event_id.isin(dset)]
            src = stage / "pairs_none_ds_math_stats.parquet"
            kept.to_parquet(src, index=False)
            evp = stage / "p3_slim_ev_ds_math_stats.parquet"
            noev = stage / "p3_slim_ds_math_stats.parquet"
            proc = subprocess.run(
                [sys.executable, str(REPO / "pipeline/frames/make_slim.py"), "math_stats",
                 str(src), str(evp), "--noev", str(noev)],
                cwd=REPO, capture_output=True, text=True)
            assert proc.returncode == 0, proc.stdout[-1000:] + proc.stderr[-1000:]
            rep[field]["p3_full"] = {"pairs_rows_kept": len(kept),
                                     "make_slim": proc.stdout.strip().splitlines()[-1]}
    pd.DataFrame(all_rows).to_csv(OUT / "doublestar_drops.csv", index=False)
    rep["staged_sha256"] = {f.name: sha(f) for f in sorted(stage.iterdir()) if f.is_file()}
    (OUT / "doublestar_build_report.json").write_text(json.dumps(rep, indent=1) + "\n",
                                                      encoding="utf-8")
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk in
                          ("events", "dropped", "kept", "same_year_pair_events_kept")}
                      if isinstance(v, dict) else v for k, v in rep.items()
                      if k != "staged_sha256"}, indent=1))
    print("DOUBLESTAR_BUILD_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
