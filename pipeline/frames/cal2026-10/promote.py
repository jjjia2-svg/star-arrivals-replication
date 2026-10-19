#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cal2026-10/promote.py — make the October caliber the canon: data/frames/ <- data/cal2026-10/frames/,
analysis/expected/ <- data/cal2026-10/estimates/ (the 25 local golds; the four cloud cells from
--cloud-out when the custody chain exists, otherwise the 2026-08-28 golds stay and are listed as
PENDING), tools/freeze_expected.py's EXPECTED list rewritten to the October sources, data/MANIFEST.sha256
regenerated for data/frames/, analysis/expected/MANIFEST.sha256 + SOURCES.md rewritten by
freeze_expected.py, and every replaced gold's old/new sha256 written to
data/cal2026-10/expected_refreeze_2026-10.json (the a22a27e recipe, 2026-08-28, done again).

    setup/.venv/bin/python pipeline/frames/cal2026-10/promote.py --execute [--cloud-out DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[3]
CAL = REPO / "data/cal2026-10"
FRAMES, EXPECTED = REPO / "data/frames", REPO / "analysis/expected"
CLOUD_CELLS = ("P3_econ_fnfix", "P3_fnfix_chemistry", "P3evcl_econ", "P3evcl_chemistry")
_spec = importlib.util.spec_from_file_location("rce10", REPO / "pipeline/stars/caliber_2026-10/run_cal_estimates.py")
rce = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(rce)   # type: ignore[union-attr]
LOCAL_CELLS = [c.name for c in rce.LOCAL_CELLS]


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def rewrite_expected_list(cloud_out: pathlib.Path | None) -> list[tuple[str, str]]:
    entries = [(f"{n}.json", f"cal2026-10/estimates/{n}.json") for n in LOCAL_CELLS]
    for n in CLOUD_CELLS:
        entries.append((f"{n}.json", f"cal2026-10/cloud/fetch/out/{n}.json" if cloud_out else f"cal2026-08-28/estimates/{n}.json"))
    src = REPO / "tools/freeze_expected.py"; s = src.read_text(encoding="utf-8")
    m = re.search(r"^EXPECTED = \[\n.*?^\]\n", s, re.S | re.M)
    assert m, "EXPECTED block not found"
    block = "EXPECTED = [\n" + "".join(f'    ("{d}",{" " * max(1, 36 - len(d))}"{r}"),\n' for d, r in entries) + "]\n"
    s = s[:m.start()] + block + s[m.end():]
    note_old = "P3pos_*/P3med_* (six files) = the 2026-08-30 Panel 3 respecification"
    if note_old in s:
        s = s.replace(
            "\n\nP3pos_*/P3med_* (six files) = the 2026-08-30 Panel 3 respecification, frozen from ",
            "\n\ncal2026-10 (2026-09-23): the 25 local golds are the October caliber run "
            "`data/cal2026-10/estimates/` (pipeline/stars/caliber_2026-10/run_cal_estimates.py; D1-D8 of "
            "the author's design record of 2026-09-22 (private archive); its 08-28 control reproduced every "
            "earlier gold, data/cal2026-10/estimates_control_0828/). The four cloud cells come from "
            "`data/cal2026-10/cloud/` once its custody chain is verified; until then the 2026-08-28 cloud "
            "golds stand and are marked PENDING in the refreeze record. Earlier canon: "
            "P3pos_*/P3med_* (six files) = the 2026-08-30 Panel 3 respecification, frozen from ")
    src.write_text(s, encoding="utf-8")
    return entries


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--cloud-out", default=None, help="data/cal2026-10/cloud/fetch/out after CUSTODY_OK")
    a = ap.parse_args(argv)
    cloud_out = pathlib.Path(a.cloud_out) if a.cloud_out else None
    src_frames = CAL / "frames"
    est = CAL / "estimates"
    missing = [n for n in LOCAL_CELLS if not (est / f"{n}.json").exists()]
    if missing:
        print("STOP: October estimates missing:", missing); return 1
    if cloud_out and any(not (cloud_out / f"{n}.json").exists() for n in CLOUD_CELLS):
        print("STOP: cloud results missing under", cloud_out); return 1
    frames = sorted(p for p in src_frames.iterdir() if p.is_file() and p.name not in ("MANIFEST.sha256", "assembly_2026-10.json"))
    rec = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "frames": {}, "expected": {}, "cloud": "october" if cloud_out else "PENDING (2026-08-28 golds kept)"}
    # a re-run (e.g. --cloud-out after the local promotion) must keep the FIRST run's pre-promotion
    # hashes: the 08-28 rebuild proofs anchor on them (tests/test_pipeline_rebuild.py)
    prev = json.loads((CAL / "expected_refreeze_2026-10.json").read_text()) if (CAL / "expected_refreeze_2026-10.json").exists() else {}
    for p in frames:
        old = FRAMES / p.name
        keep = prev.get("frames", {}).get(p.name, {})
        rec["frames"][p.name] = {"old_sha256": keep["old_sha256"] if "old_sha256" in keep else (sha(old) if old.exists() else None), "new_sha256": sha(p)}
    for n in LOCAL_CELLS + list(CLOUD_CELLS):
        old = EXPECTED / f"{n}.json"
        new = (est / f"{n}.json") if n in LOCAL_CELLS else ((cloud_out / f"{n}.json") if cloud_out else old)
        keep = prev.get("expected", {}).get(n, {})
        promoted_before = keep and keep.get("new_sha256") == (sha(old) if old.exists() else None) and keep.get("old_sha256") != keep.get("new_sha256")
        o = keep["old_sha256"] if promoted_before else (sha(old) if old.exists() else None)
        rec["expected"][n] = {"old_sha256": o, "new_sha256": sha(new), "changed": o != sha(new)}
    if prev:
        rec["history"] = prev.get("history", [{"generated": prev.get("generated"), "step": "earlier promotion"}])
    n_changed = sum(v["changed"] for v in rec["expected"].values())
    if not a.execute:
        print(json.dumps({"would_promote_frames": len(frames), "golds_changing": n_changed, "cloud": rec["cloud"]}, indent=1)); return 0
    # 1. frames
    for p in frames:
        shutil.copyfile(p, FRAMES / p.name)
    # 2. golds: EXPECTED list -> delete the replaced files -> freeze_expected.py recreates + manifest + SOURCES
    entries = rewrite_expected_list(cloud_out)
    for n, v in rec["expected"].items():
        if v["changed"] and (EXPECTED / f"{n}.json").exists():
            (EXPECTED / f"{n}.json").unlink()
    r = subprocess.run([sys.executable, str(REPO / "tools/freeze_expected.py")], capture_output=True, text=True, cwd=REPO)
    print(r.stdout.strip(), r.stderr.strip()[-500:])
    if r.returncode != 0:
        print("STOP: freeze_expected.py failed"); return 1
    # 3. README canon note (before the manifest is hashed)
    readme = FRAMES / "README.md"
    note = ("**Canon since 2026-09-23 (cal2026-10, the October caliber).** Every frame here is a byte copy of "
            "its counterpart in `data/cal2026-10/frames/` (assembled by `pipeline/frames/cal2026-10/assemble_frames.py` "
            "from the per-discipline freezes `frames_econ/`, `frames_chemistry/`, `frames_math_stats/`, the Panel 3 "
            "sweep `frames_afar/` and the D7 variants `frames_variants/`; provenance and controls in their reports and "
            "`tests/test_cal2026_10_*.py`, `tests/test_cal_afar_2026_10.py`, `tests/test_p3_full_variants_2026_10.py`). "
            "Design: the author's design record of 2026-09-22 (private archive) (D1-D8). New files: "
            "`p3_slim_<field>_{p05,dosebin3}.parquet` (D7), `relationships_econ.csv`, `pairs_none_{chemistry,math_stats}.parquet`. "
            "The 2026-08-28 canon below is one directory away (`data/cal2026-08-28/frames/`) and at tag `cal-2026-08-28`.\n\n")
    txt = readme.read_text(encoding="utf-8")
    if "Canon since 2026-09-23" not in txt:
        anchor = "**Canon since the 2026-08-28 freeze"
        assert anchor in txt
        readme.write_text(txt.replace(anchor, note + anchor, 1), encoding="utf-8")
    # 4. data/MANIFEST.sha256: the data/frames lines regenerated, every other line kept
    man = REPO / "data/MANIFEST.sha256"
    keep = [ln for ln in man.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.split("  ", 1)[1].startswith("data/frames/")]
    new_lines = [f"{sha(p)}  data/frames/{p.name}" for p in sorted(FRAMES.iterdir()) if p.is_file()]
    man.write_text("\n".join(keep + new_lines) + "\n", encoding="utf-8")
    (CAL / "expected_refreeze_2026-10.json").write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
    v = subprocess.run([sys.executable, str(REPO / "tools/verify_manifest.py")], capture_output=True, text=True, cwd=REPO).stdout.strip()
    v2 = subprocess.run([sys.executable, str(REPO / "tools/verify_manifest.py"), "analysis/expected/MANIFEST.sha256"], capture_output=True, text=True, cwd=REPO).stdout.strip()
    print(f"promoted {len(frames)} frames; golds changed {n_changed}/{len(rec['expected'])}; cloud = {rec['cloud']}; {v[:60]} | {v2[:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
