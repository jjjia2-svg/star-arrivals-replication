#!/usr/bin/env python3
"""build_departure.py — star-departure A/B sensitivity datasets on the CANON frames (T6-2).

Old design (2026-08-09, the author's departure-robustness results note, not shipped; builder
`v2_output/multidisc_v2_2026-08-04/results/departure_robustness/scripts/00_build_departure_datasets.py`),
economics only, re-applied unchanged to the canon event set (116 events):

  A (drop):   remove every event whose star is HUMAN-VERIFIED to have departed (or died)
              within 6 years of arrival (`within_6y == yes`) — 17 events, same as 2026-08-09;
  B (recode): for every event with a verified departure year, switch treatment off from the
              departure year on (post/D -> 0 for year >= departure_year) — 22 events.

The evidence base is the SAME human-verified ledger (25 econ verdicts out of the 120-star
screen; machine departure signals were shown there to err by up to 9 years, so no mechanical
extension is attempted). COVERAGE GAP, disclosed not improvised: the screen covers exactly
the 79 pre-fnfix events; the 37 events added by the foreign-poach fix have never been
screened for departures, so they are treated as "not known to have left" (the paper's §3
wording) and are untouched by both variants. Extending the ledger needs the same human
verification step — author-level work.

Frame surgery is LINE-level (byte-preserving outside the touched field), verified by strict
walks; A_far uses the proven ev -> event_id map from afar_event_map.py. Variant frames go to
--stage (scratch; they regenerate deterministically from canon in seconds); the recode table,
per-file sha256 and the accounting go to data/robustness_2026-08-29_b/departure/.

--spec (2026-09-10): `med` (default) = the retired median-cut A_far frame, the 2026-08-29 run
unchanged; `pos` = the paper's Panel 3 since 2026-08-30 (dose > 0): the A_far surgery reads
data/frames/p3_afar_pos_econ.parquet through the pos map from `afar_event_map.py --spec pos`
and freezes under data/robustness_2026-09-10_p3pos/departure/. The ledger, the P1/P2 line
surgery and every control are the same code for both specs (P1/P2 do not depend on the cut, so
their variant frames must come out byte-identical across specs — the wrapper checks that).
"""
import csv
import hashlib
import io
import json
import os
import pathlib
import sys

import pandas as pd

REPO = pathlib.Path(__file__).resolve().parents[3]
LEGACY = REPO / "config"  # resolved below via analysis.lib.paths
sys.path.append(str(REPO))
from analysis.lib.paths import load_paths  # noqa: E402

SPECS = ("med", "pos")
FREEZE_ROOT = {"med": "data/robustness_2026-08-29_b", "pos": "data/robustness_2026-09-10_p3pos"}
AFAR_FRAME = {"med": "data/frames/p3_afar_{field}.parquet",
              "pos": "data/frames/p3_afar_pos_{field}.parquet"}
DEFAULT_STAGE = {"med": "/private/tmp/sar_departure_2026-08-29",
                 "pos": "/private/tmp/sar_departure_2026-09-10_pos"}


def afar_map(spec: str, field: str) -> "pd.DataFrame":
    """The proven ev -> event_id map for `spec`/`field`, or a clear failure: a map is only ever
    written by afar_event_map.py after its content-equality proof, so an absent file means the
    proof has not been run (econ: needs pairs_unified.csv, regenerated through the caliber shadow
    with the data disk mounted) — nothing is inferred in its place."""
    map_dir = os.environ.get("SAR_AFAR_MAP_DIR")  # 2026-09-23: env override of the proven-map dir; default = the spec's freeze root
    f = (REPO / map_dir if map_dir else REPO / FREEZE_ROOT[spec] / "afar_event_map") / f"afar_event_map_{field}.csv"
    assert f.is_file(), (
        f"no proven A_far event map for spec={spec} field={field}: {f} is absent. Build it with "
        f"`afar_event_map.py --spec {spec}` (econ additionally needs --pairs-econ/--regen-econ); "
        f"a map is never inferred here.")
    return pd.read_csv(f)


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def edit_csv_lines(src: pathlib.Path, dest: pathlib.Path, event_col: str,
                   drop_events: set[str], recode) -> dict:
    """Stream `src` to `dest`: drop data lines whose event is in `drop_events`; otherwise let
    `recode(cells) -> cells|None` edit the parsed row (None = keep the line byte-identical).
    Every untouched line is copied byte-for-byte; returns the accounting."""
    raw = src.read_bytes()
    lines = raw.split(b"\n")
    trailing = lines and lines[-1] == b""
    if trailing:
        lines = lines[:-1]
    hdr = next(csv.reader([lines[0].decode("utf-8").rstrip("\r")]))
    ci = hdr.index(event_col)
    out, dropped, edited, kept = [], 0, 0, 0
    for i, ln in enumerate(lines):
        if i == 0:
            out.append(ln)
            continue
        cells = next(csv.reader([ln.decode("utf-8").rstrip("\r")]))
        if cells[ci] in drop_events:
            dropped += 1
            continue
        new = recode(cells) if recode else None
        if new is None:
            kept += 1
            out.append(ln)
        else:
            edited += 1
            buf = io.StringIO()
            csv.writer(buf, lineterminator="").writerow(new)
            out.append(buf.getvalue().encode("utf-8"))
    dest.write_bytes(b"\n".join(out) + (b"\n" if trailing else b""))
    return {"rows_in": len(lines) - 1, "dropped": dropped, "edited": edited,
            "kept_byte_identical": kept}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--spec", choices=SPECS, default="med",
                    help="A_far frame to operate on: med = retired median cut (default, the "
                         "2026-08-29 run); pos = dose > 0, the paper's Panel 3 since 2026-08-30")
    ap.add_argument("--stage", help=f"scratch dir for the variant frames (regenerable; not "
                                    f"frozen); default per --spec: {DEFAULT_STAGE}")
    args = ap.parse_args(argv)
    stage = pathlib.Path(args.stage or DEFAULT_STAGE[args.spec])
    stage.mkdir(parents=True, exist_ok=True)
    OUT = REPO / FREEZE_ROOT[args.spec] / "departure"
    OUT.mkdir(parents=True, exist_ok=True)
    rep: dict = {"design": "2026-08-09 departure A/B (verbatim rules) on canon 116 events"}
    if args.spec != "med":
        rep["spec"] = args.spec
        rep["afar_frame"] = AFAR_FRAME[args.spec].format(field="econ")

    # ---- 1. the verified ledger, matched into canon ------------------------------------------
    v2 = pathlib.Path(load_paths()["legacy_v2_output"])
    old = pd.read_csv(v2 / "multidisc_v2_2026-08-04/results/departure_robustness/departure_match_econ.csv")
    scr = pd.read_csv(v2 / "multidisc_v2_2026-08-04/verify/star_departure_screen.csv")
    ev = pd.read_csv(REPO / "data/frames/p1_events_ledger_econ.csv")
    m = old.merge(ev[["event_id", "star_id", "school", "arrival_year"]], on="star_id",
                  how="left", suffixes=("_old", ""))
    assert m.event_id.notna().all(), "a verified star no longer matches any canon event"
    assert (m.arrival == m.arrival_year).all(), "arrival year moved for a verified star"
    assert (m.school_old == m.school).all(), "school moved for a verified star"
    A = m[(m.within_6y == "yes") & (m.verdict.isin(["departed", "deceased"]))]
    B = m[m.verdict.isin(["departed", "deceased"]) & m.departure_year.notna()]
    excl = set(A.event_id)
    dep_of = dict(zip(B.event_id, B.departure_year.astype(int)))
    covered = ev.star_id.isin(set(scr[scr.field == "econ"].star_id))
    uncovered = ev[~covered].event_id.tolist()
    rep["ledger"] = {"verified_verdicts": len(m), "A_dropped_events": sorted(excl),
                     "B_recode_events": {k: int(v) for k, v in sorted(dep_of.items())},
                     "counts": {"A": len(excl), "B": len(dep_of)}}
    rep["coverage"] = {
        "canon_events": len(ev), "screened": int(covered.sum()),
        "never_screened": len(uncovered),
        "note": ("the 37 foreign-poach-fix events postdate the 120-star departure screen; no "
                 "departure verification exists for them, so they are 'not known to have left' "
                 "and untouched — extending the ledger requires the human verification step"),
        "never_screened_events": uncovered}
    m.to_csv(OUT / "dep_match_canon.csv", index=False)

    # ---- 2. P1 / P2 variants by line surgery --------------------------------------------------
    p1 = REPO / "data/frames/p1_frame_econ.csv"
    p2 = REPO / "data/frames/p2_becoming_econ.csv"
    hdr1 = next(csv.reader([p1.open(encoding="utf-8").readline()]))
    y1, po1 = hdr1.index("year"), hdr1.index("post")
    e1 = hdr1.index("event_id")

    def recode_p1(cells):
        dep = dep_of.get(cells[e1])
        if dep is None or int(cells[y1]) < dep or cells[po1] != "True":
            return None
        cells = list(cells)
        cells[po1] = "False"
        return cells

    hdr2 = next(csv.reader([p2.open(encoding="utf-8").readline()]))
    y2, po2, e2 = hdr2.index("year"), hdr2.index("post"), hdr2.index("event_id")

    def recode_p2(cells):
        dep = dep_of.get(cells[e2])
        if dep is None or int(cells[y2]) < dep or cells[po2] != "1":
            return None
        cells = list(cells)
        cells[po2] = "0"
        return cells

    rep["frames"] = {}
    rep["frames"]["p1_A"] = edit_csv_lines(p1, stage / "p1_dep_A.csv", "event_id", excl, None)
    rep["frames"]["p1_B"] = edit_csv_lines(p1, stage / "p1_dep_B.csv", "event_id", set(), recode_p1)
    rep["frames"]["p2_A"] = edit_csv_lines(p2, stage / "p2_dep_A.csv", "event_id", excl, None)
    rep["frames"]["p2_B"] = edit_csv_lines(p2, stage / "p2_dep_B.csv", "event_id", set(), recode_p2)
    # writer-path control: empty surgery must reproduce the input byte-identically
    ctl = edit_csv_lines(p1, stage / "_noop.csv", "event_id", set(), None)
    assert sha(stage / "_noop.csv") == sha(p1), "no-op surgery is not byte-identical — writer bug"
    (stage / "_noop.csv").unlink()
    rep["noop_control"] = "BYTE_EQUAL"

    # ---- 3. A_far variants through the proven ev map ------------------------------------------
    mp = afar_map(args.spec, "econ")
    af = pd.read_parquet(REPO / AFAR_FRAME[args.spec].format(field="econ"))
    ev_of = dict(zip(mp.event_id, mp.ev))
    excl_ev = {ev_of[e] for e in excl if e in ev_of}
    dep_ev = {ev_of[e]: d for e, d in dep_of.items() if e in ev_of}
    a = af[~af.ev.isin(excl_ev)]
    b = af.copy()
    depv = b.ev.map(dep_ev)
    flip = depv.notna() & (b.year >= depv.fillna(9999)) & (b.D == 1)
    b.loc[flip, "D"] = 0
    a.to_parquet(stage / "p3_afar_dep_A.parquet", index=False)
    b.to_parquet(stage / "p3_afar_dep_B.parquet", index=False)
    rep["afar"] = {"events_in_afar": int(af.ev.nunique()),
                   "A_dropped_in_afar": len(excl_ev), "B_recoded_in_afar": len(dep_ev),
                   "A_rows": len(a), "B_rows_flipped": int(flip.sum())}

    # ---- 4. shas of everything staged ---------------------------------------------------------
    rep["staged_sha256"] = {f.name: sha(f) for f in sorted(stage.iterdir()) if f.is_file()}
    (OUT / "departure_build_report.json").write_text(json.dumps(rep, indent=1) + "\n",
                                                     encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("ledger", "coverage", "afar", "noop_control")
                      if k in rep}, indent=1, default=str)[:1500])
    print(f"variant frames staged in {stage}")
    print("DEPARTURE_BUILD_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
