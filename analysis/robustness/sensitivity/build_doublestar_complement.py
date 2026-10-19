#!/usr/bin/env python3
"""build_doublestar_complement.py — the OVERLAPPED half of the double-star split (econ, Panel 1).

The 2026-08-29 T6-3 run (build_doublestar.py) keeps the 18 economics arrivals with no earlier
same-department arrival within five years and freezes the drop table. The manuscript's
Section 4.1 explains the failed placebo test by the overlap of arrival windows; the direct
test of that explanation is the complement: the 98 OVERLAPPED events on their own. If the
explanation is right, their placebo test rejects while the clean 18 pass.

This script builds that complement frame from the canon Panel 1 economics frame by the same
byte-preserving line filter the 2026-08-29 run used (edit_csv_lines), dropping the 18 kept
events instead of the 98 dropped ones, and writes a build report. Controls: (1) every line
in the complement is a byte-identical line of the canon frame; (2) complement rows + the
2026-08-29 kept rows == canon rows. Estimation is by the verbatim driver
analysis/estimation/run_p1.R (see run_doublestar_complement.sh). Written 2026-09-12.
"""
import argparse, csv, hashlib, json, os, pathlib, sys
REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from analysis.lib.paths import load_paths
from analysis.robustness.sensitivity.build_departure import edit_csv_lines

P = load_paths()
ROB_B = REPO / "data" / "robustness_2026-08-29_b"
# 2026-09-23: the drop table's directory may be overridden (the October table lives under
# data/cal2026-10/robustness/doublestar); the expected kept/dropped counts then come from that
# directory's doublestar_build_report.json instead of the 2026-08-29 pins (18 / 98)
DS_DIR = (REPO / os.environ["SAR_DS_DROPS_DIR"]) if os.environ.get("SAR_DS_DROPS_DIR") else (ROB_B / "doublestar")
OUT = REPO / os.environ.get("SAR_ROBUST_OUTDIR", "data/robustness_2026-09-12_dscomp")  # 2026-09-23: env override, old value default


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="/private/tmp/sar_dscomp_2026-09-12")
    a = ap.parse_args(argv)
    stage = pathlib.Path(a.stage); stage.mkdir(parents=True, exist_ok=True)
    drops = list(csv.DictReader(open(DS_DIR / "doublestar_drops.csv", encoding="utf-8")))
    kept = {r["event_id"] for r in drops if r["field"] == "econ" and r["dropped"] == "False"}
    dropped = {r["event_id"] for r in drops if r["field"] == "econ" and r["dropped"] == "True"}
    if os.environ.get("SAR_DS_DROPS_DIR"):
        _r = json.loads((DS_DIR / "doublestar_build_report.json").read_text())["econ"]
        exp_kept, exp_dropped = _r["kept"], _r["dropped"]
    else:
        exp_kept, exp_dropped = 18, 98
    assert len(kept) == exp_kept and len(dropped) == exp_dropped, (len(kept), len(dropped), exp_kept, exp_dropped)
    src = P["frames"] / "p1_frame_econ.csv"
    dst = stage / "p1_dsC_econ.csv"
    acc = edit_csv_lines(src, dst, "event_id", kept, None)
    # controls
    canon = src.read_bytes().split(b"\n"); comp = dst.read_bytes().split(b"\n")
    canon_set = set(canon); assert all(ln in canon_set for ln in comp), "complement line not in canon"
    rep = json.loads((DS_DIR / "doublestar_build_report.json").read_text())
    kept_rows_0829 = rep["econ"]["p1"]["kept_byte_identical"]
    assert acc["kept_byte_identical"] + kept_rows_0829 == rep["econ"]["p1"]["rows_in"] == acc["rows_in"], (acc, kept_rows_0829)
    report = {"rule": f"complement of the double-star drop ({DS_DIR.relative_to(REPO)}): keep only the {len(dropped)} economics "
                      "events that arrived within five years of an earlier same-department arrival",
              "events_in_complement": len(dropped), "events_excluded_clean": len(kept),
              "p1": acc, "control_lines_subset_of_canon": True,
              "control_rows_complement_plus_clean_equals_canon": True,
              "source_frame": "data/frames/p1_frame_econ.csv",
              "source_frame_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
              "staged_sha256": {"p1_dsC_econ.csv": hashlib.sha256(dst.read_bytes()).hexdigest()}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "dscomp_build_report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1)); return 0


if __name__ == "__main__":
    sys.exit(main())
