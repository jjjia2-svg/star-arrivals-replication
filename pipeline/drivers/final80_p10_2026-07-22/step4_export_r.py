# -*- coding: utf-8 -*-
"""step4 — assemble the R delivery package: v2_output/r_52ev_2026-07-21/.

data/: frame CSV x2 (same 15-column schema, column by column) + event-coverage CSV + event->school mapping CSV.
How to run (original layout): cd multiplex_pipeline && PYTHONHASHSEED=0 python3 <working scripts>/final52_2026-07-21/step4_export_r.py
"""
import csv
import json
import pathlib
import sys

import pyarrow.parquet as pq

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from common80 import DEPT_INST_11, R_PKG, U4_OUT, U6_OUT  # noqa: E402

FRAME_COLS = ["incumbent_person_id", "year", "star_person_id", "event_id",
              "treated", "post", "dose_coupling", "dose_low_confidence",
              "age_gap", "fwci_frac", "pub_count", "fwci_frac_ex_star",
              "pub_count_ex_star", "fwci_mean", "fwci_mean_ex_star"]


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "True" if v else "False"
    return v


def export_frame(p_level: str):
    src = U6_OUT / "frame" / "_frozen" / f"analysis_frame_{p_level}.parquet"
    if not src.is_file():
        cands = list((U6_OUT / "frame").rglob(f"analysis_frame_{p_level}.parquet"))
        assert cands, f"frame file missing: {p_level}"
        src = cands[0]
    rows = pq.read_table(str(src)).to_pylist()
    out = R_PKG / "data" / f"analysis_frame_{p_level}_52ev_2026-07-21.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(FRAME_COLS)
        for r in rows:
            w.writerow([_fmt(r[c]) for c in FRAME_COLS])
    print(f"frame {p_level}: {len(rows)} rows → {out.name}")
    return len(rows)


def export_coverage():
    cov = json.loads((U6_OUT / "_reports" / "coverage_groups.json").read_text("utf-8"))
    out = R_PKG / "data" / "event_coverage_2026-07-21.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["p_level", "n_events_nominal", "n_events_in_frame",
                    "dropped_zero_coupling_event_ids"])
        for p in ("p01", "p05"):
            w.writerow([p, cov["events_nominal"][p], cov["events_in_frame"][p],
                        ";".join(cov["events_dropped_zero_coupling"][p])])
    print("coverage →", out.name)
    return cov


def export_event_map():
    ev = pq.read_table(str(U4_OUT / "events" / "data.parquet")).to_pylist()
    school_by_inst = {v: k.replace("_econ", "") for k, v in DEPT_INST_11.items()}
    out = R_PKG / "data" / "events_v3_52_2026-07-21.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["event_id", "school", "arrival_year", "arrival_source",
                    "arrival_evidence_strength"])
        for e in sorted(ev, key=lambda x: x["event_id"]):
            w.writerow([e["event_id"], school_by_inst[e["dept_id"]],
                        e["arrival_year"], e["arrival_source"],
                        e["arrival_evidence_strength"]])
    print("event map →", out.name)


if __name__ == "__main__":
    (R_PKG / "data").mkdir(parents=True, exist_ok=True)
    (R_PKG / "output" / "tables").mkdir(parents=True, exist_ok=True)
    (R_PKG / "output" / "figures").mkdir(parents=True, exist_ok=True)
    n1 = export_frame("p01")
    n5 = export_frame("p05")
    export_coverage()
    export_event_map()
    print(f"STEP4_DONE rows p01={n1} p05={n5} → {R_PKG}")
