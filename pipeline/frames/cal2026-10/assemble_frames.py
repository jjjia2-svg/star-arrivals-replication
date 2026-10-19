#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cal2026-10/assemble_frames.py — gather the October caliber's estimation frames into ONE directory,
data/cal2026-10/frames/, under the canonical data/frames basenames (what analysis/run_all.sh, the
robustness batteries and the cloud launcher read), from the per-piece freeze directories. Every
source directory is a required flag (no defaults, R1 F3), so J0 (the October directories) and J1a
(the M stage directories) run the same code:

  --econ-dir           (econ920)     p2_becoming_econ.csv, p3_slim_econ.parquet, p3_slim_ev_econ.parquet,
                                     p1_events_ledger_econ.csv, relationships_econ.csv
  --econ-p1-dir                      p1_frame_econ.csv, p1_frame_econ_old79.csv, p1_frame_econ_new37.csv
  --chem-dir, --math-dir (run_cal_frames_chemmath)
                                     p1_frame_<f>.csv, p2_becoming_<f>.csv, p3_slim_<f>.parquet,
                                     p3_slim_ev_<f>.parquet, pairs_none_<f>.parquet
  --afar-dir           (run_cal_afar) p3_afar_<f>.parquet, p3_afar_{pos,med}_<f>.parquet, p3_afar_counts.csv,
                                     p3_afar_counts_by_spec.csv, p3_afar_tau_profile.csv
  --variants-dir       (build_p3_full_variants) p3_slim_<f>_{p05,dosebin3}.parquet
  data/frames/p3_afar_speed_bracket.csv  carried over unchanged: caliber-stale since 2026-08-30, no
                                     builder (pipeline/NOT_REPRODUCIBLE.md row 9), read by nothing
                                     in the paper layer, pinned by tests/manifests.
  --pairs-econ, --pairs-pin REPORT#KEY
                                     pairs_unified.csv -> output/cal_intermediates/pairs_unified.csv
                                     (NOT shipped, sha256 recorded, as in 2026-08-28). Its sha256 and
                                     bytes must equal the {sha256, bytes} record at the dotted KEY of
                                     the JSON REPORT before anything is written (PAIRS_PIN_MISMATCH,
                                     exit 1); the source is recorded exactly as passed.
  --out                              the assembled directory

October's values (data/cal2026-10/frames/assembly_2026-10.json), run with cwd = the repo:

    setup/.venv/bin/python pipeline/frames/cal2026-10/assemble_frames.py --execute
        --econ-dir data/cal2026-10/frames_econ --econ-p1-dir data/cal2026-10/frames_econ
        --chem-dir data/cal2026-10/frames_chemistry --math-dir data/cal2026-10/frames_math_stats
        --afar-dir data/cal2026-10/frames_afar --variants-dir data/cal2026-10/frames_variants
        --pairs-econ output/cal_intermediates/cal2026-10/pairs_unified.csv
        --pairs-pin data/cal2026-10/frames_econ/build_report_econ920_2026-10.json#october.pairs_unified
        --out data/cal2026-10/frames

Every source is sha256-checked against its own directory's MANIFEST.sha256 when listed there; a
missing source is a STOP unless --allow-missing names it. Writes assembly_2026-10.json (name ->
source path, sha256, manifest status) and MANIFEST.sha256 over the assembled directory (paths
relative to the repo when --out is inside it, as October's; relative to --out otherwise).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[3]
FIELDS = ("econ", "chemistry", "math_stats")


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def manifest_of(d: pathlib.Path) -> dict[str, str]:
    m = d / "MANIFEST.sha256"
    if not m.exists():
        return {}
    out = {}
    for ln in m.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            h, rel = ln.split("  ", 1)
            out[pathlib.Path(rel.strip()).name] = h
    return out


def pin_of(spec: str) -> dict:
    """REPORT#KEY -> the {sha256, bytes} record at the dotted KEY of the JSON file REPORT."""
    report, _, key = spec.partition("#")
    node = json.loads(pathlib.Path(report).read_text(encoding="utf-8"))
    for part in key.split("."):
        node = node[part]
    return {"sha256": node["sha256"], "bytes": node["bytes"]}


def manifest_path(p: pathlib.Path, out: pathlib.Path) -> str:
    """A MANIFEST.sha256 path for p = out/<name>: repo-relative when --out is inside the repo (October's;
    lexical, like the October code, so a symlinked directory keeps its repo path), else relative to --out."""
    ab = pathlib.Path(os.path.abspath(p))
    return (ab.relative_to(REPO) if ab.is_relative_to(REPO) else p.relative_to(out)).as_posix()


def plan(a) -> list[tuple[str, pathlib.Path]]:
    fe = pathlib.Path(a.econ_dir); ep1 = pathlib.Path(a.econ_p1_dir)
    items = [("p2_becoming_econ.csv", fe / "p2_becoming_econ.csv"), ("p3_slim_econ.parquet", fe / "p3_slim_econ.parquet"),
             ("p3_slim_ev_econ.parquet", fe / "p3_slim_ev_econ.parquet"), ("p1_events_ledger_econ.csv", fe / "p1_events_ledger_econ.csv"),
             ("relationships_econ.csv", fe / "relationships_econ.csv"),
             ("p1_frame_econ.csv", ep1 / "p1_frame_econ.csv"), ("p1_frame_econ_old79.csv", ep1 / "p1_frame_econ_old79.csv"),
             ("p1_frame_econ_new37.csv", ep1 / "p1_frame_econ_new37.csv")]
    for f, d in (("chemistry", pathlib.Path(a.chem_dir)), ("math_stats", pathlib.Path(a.math_dir))):
        items += [(n, d / n) for n in (f"p1_frame_{f}.csv", f"p2_becoming_{f}.csv", f"p3_slim_{f}.parquet",
                                       f"p3_slim_ev_{f}.parquet", f"pairs_none_{f}.parquet")]
    af = pathlib.Path(a.afar_dir)
    for f in FIELDS:
        items += [(n, af / n) for n in (f"p3_afar_{f}.parquet", f"p3_afar_pos_{f}.parquet", f"p3_afar_med_{f}.parquet")]
    items += [(n, af / n) for n in ("p3_afar_counts.csv", "p3_afar_counts_by_spec.csv", "p3_afar_tau_profile.csv")]
    v = pathlib.Path(a.variants_dir)
    for f in FIELDS:
        items += [(n, v / n) for n in (f"p3_slim_{f}_p05.parquet", f"p3_slim_{f}_dosebin3.parquet")]
    items.append(("p3_afar_speed_bracket.csv", REPO / "data/frames/p3_afar_speed_bracket.csv"))
    return items


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--econ-dir", required=True, help="econ920 products (October: data/cal2026-10/frames_econ)")
    ap.add_argument("--econ-p1-dir", required=True, help="the three econ p1 frames (October: the --econ-dir value)")
    ap.add_argument("--chem-dir", required=True, help="chemistry frames (October: data/cal2026-10/frames_chemistry)")
    ap.add_argument("--math-dir", required=True, help="math_stats frames (October: data/cal2026-10/frames_math_stats)")
    ap.add_argument("--afar-dir", required=True)
    ap.add_argument("--variants-dir", required=True, help="variant slims (October: data/cal2026-10/frames_variants)")
    ap.add_argument("--pairs-econ", required=True, help="econ pairs_unified.csv (staged to output/cal_intermediates/)")
    ap.add_argument("--pairs-pin", required=True, metavar="REPORT#KEY",
                    help="JSON report and dotted key of the {sha256, bytes} record the --pairs-econ file must equal")
    ap.add_argument("--allow-missing", nargs="*", default=[])
    ap.add_argument("--out", required=True, help="the assembled directory (October: data/cal2026-10/frames)")
    ap.add_argument("--execute", action="store_true")
    a = ap.parse_args(argv)
    report, sep, key = a.pairs_pin.partition("#")
    if not (report and sep and key):
        ap.error(f"--pairs-pin must be REPORT#KEY, got {a.pairs_pin!r}")
    out = pathlib.Path(a.out)
    rep = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "files": {}, "missing": [], "manifest_mismatch": []}
    for name, src in plan(a):
        if not src.exists():
            rep["missing"].append({"name": name, "source": str(src)}); continue
        h = sha(src); man = manifest_of(src.parent)
        status = "not_in_source_manifest" if name not in man and src.name not in man else ("OK" if man.get(src.name, man.get(name)) == h else "MISMATCH")
        if status == "MISMATCH":
            rep["manifest_mismatch"].append(name)
        rep["files"][name] = {"source": str(src.relative_to(REPO)) if src.is_relative_to(REPO) else str(src), "sha256": h, "source_manifest": status}
    hard_missing = [m["name"] for m in rep["missing"] if m["name"] not in a.allow_missing]
    if hard_missing or rep["manifest_mismatch"]:
        print(json.dumps({"STOP": {"missing": hard_missing, "manifest_mismatch": rep["manifest_mismatch"]}}, indent=1)); return 1
    pe = pathlib.Path(a.pairs_econ)
    try:
        want = pin_of(a.pairs_pin)
    except (OSError, ValueError, KeyError, TypeError) as e:
        want = {"error": f"{type(e).__name__}: {e}"}
    have = {"sha256": sha(pe), "bytes": pe.stat().st_size} if pe.is_file() else None
    if have != want:
        print(json.dumps({"STOP": {"PAIRS_PIN_MISMATCH": {"pairs_econ": str(pe), "pin": a.pairs_pin,
                                                          "want": want, "have": have}}}, indent=1)); return 1
    rep["pairs_unified_econ"] = {"source": str(pe), "sha256": have["sha256"], "staged_to": "output/cal_intermediates/pairs_unified.csv", "shipped": False}
    if not a.execute:
        print(json.dumps({"would_assemble": len(rep["files"]), "missing_allowed": [m["name"] for m in rep["missing"]]}, indent=1)); return 0
    out.mkdir(parents=True, exist_ok=True)
    for name, src in plan(a):
        if src.exists():
            shutil.copyfile(src, out / name)
            assert sha(out / name) == rep["files"][name]["sha256"]
    dest = REPO / "output/cal_intermediates"; dest.mkdir(parents=True, exist_ok=True)
    if (dest / "pairs_unified.csv").exists() or (dest / "pairs_unified.csv").is_symlink():
        (dest / "pairs_unified.csv").unlink()
    shutil.copyfile(pe, dest / "pairs_unified.csv")
    (out / "assembly_2026-10.json").write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
    files = sorted(p for p in out.iterdir() if p.is_file() and p.name != "MANIFEST.sha256")
    (out / "MANIFEST.sha256").write_text("".join(f"{sha(p)}  {manifest_path(p, out)}\n" for p in files), encoding="utf-8")
    print(f"assembled {len(files) - 1} frames into {a.out}; missing (allowed): {[m['name'] for m in rep['missing']]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
