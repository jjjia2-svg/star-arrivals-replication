#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""caliber_2026-10/write_events.py — the October event tables and the top-5% subsets, from the
per-machine verdicts (README: two extractions, one machine):

* economics: the 2026-08-28 table minus the events of rechecked stars whose cleaned stock fails the
  top-10% cut on the extraction that admitted them (`restake_econ11_aug_2026-10.csv`,
  event_keep=False), with the star-id corrections applied; every other economics event keeps its
  July/August verdict. The p05 subset uses `restake_econ11_aug_all_2026-10.csv` (pass_p05 for all).
* chemistry, mathematics: the run-2 verdicts of run_caliber.py on `u1_edges_full` (their admitting
  machine) — `_invalid_run2/verdicts_2026-10.csv` — except that a below-cut verdict for a star the
  author ruled to keep on 2026-08-13 (A5083769806, kept by author ruling 2026-08-13) is not applied.

Writes data/cal2026-10/events_{field}_cal2026-10.csv and events_{field}_cal2026-10_p05.csv in the
2026-08-28 shapes, plus events_decision_2026-10.json (what changed and why) and MANIFEST.sha256.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]
CAL = REPO / "data" / "cal2026-10"
RV = REPO / "data" / "raw_verified"
AUTHOR_KEEP = {"A5083769806": "kept by author ruling 2026-08-13"}


def _read(p):
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    corr = {r["old_id"]: r["new_id"] for r in _read(CAL / "star_id_corrections_2026-10.csv")}
    econ17 = {r["author_id"]: r for r in _read(CAL / "restake_econ11_aug_2026-10.csv")}
    econ_all = {r["author_id"]: r for r in _read(CAL / "restake_econ11_aug_all_2026-10.csv")}
    cm = {r["author_id"]: r for r in _read(CAL / "_invalid_run2" / "verdicts_2026-10.csv") if r["field"] != "econ"}
    decision = {"dropped": [], "kept_by_author_ruling": [], "id_corrected": corr, "p05": {}}

    def write(field, src, keep_fn, p05_fn, id_col, key_fn):
        text = (RV / src).read_bytes().decode("utf-8")
        lines = [ln for ln in text.split("\n") if ln]
        hdr, body = lines[0], lines[1:]
        out, out05 = [hdr], [hdr]
        for ln in body:
            f = next(csv.reader([ln]))
            old = f[id_col]
            new = corr.get(old, old)
            if new != old:
                f[id_col] = new
                if field == "econ":
                    f[0] = f[0].replace(old, new)
                buf = io.StringIO(); csv.writer(buf, lineterminator="").writerow(f); ln = buf.getvalue()
            if not keep_fn(new):
                decision["dropped"].append({"field": field, "event": key_fn(f), "star": new})
                continue
            out.append(ln)
            if p05_fn(new):
                out05.append(ln)
        (CAL / f"events_{field}_cal2026-10.csv").write_text("\n".join(out) + "\n", encoding="utf-8")
        (CAL / f"events_{field}_cal2026-10_p05.csv").write_text("\n".join(out05) + "\n", encoding="utf-8")
        decision["p05"][field] = {"events": len(out) - 1, "p05_events": len(out05) - 1}
        print(f"{field}: {len(body)} -> {len(out) - 1} events; p05 subset {len(out05) - 1}")

    def econ_keep(a):
        return econ17[a]["event_keep"] == "True" if a in econ17 else True
    def econ_p05(a):
        r = econ_all.get(a)
        return bool(r) and r["after_pass_p05"] == "True" and r["event_keep"] == "True"
    write("econ", "events_econ_cal2026-08-28.csv", econ_keep, econ_p05, 1, lambda f: f[0])

    def cm_keep(a):
        v = cm.get(a)
        if v is None:
            return True
        if v["event_cal2026_10"] == "True":
            return True
        if a in AUTHOR_KEEP:
            decision["kept_by_author_ruling"].append({"star": a, "why": AUTHOR_KEEP[a], "machine_pct": v["after_pct"]})
            return True
        return False
    def cm_p05(a):
        v = cm.get(a)
        return bool(v) and v["event_p05"] == "True"
    write("chemistry", "events_chemistry_cal2026-08-28.csv", cm_keep, cm_p05, 2, lambda f: f"{f[2]}:{f[1]}")
    write("math_stats", "events_math_stats_cal2026-08-28.csv", cm_keep, cm_p05, 2, lambda f: f"{f[2]}:{f[1]}")

    (CAL / "events_decision_2026-10.json").write_text(json.dumps(decision, ensure_ascii=False, indent=1), encoding="utf-8")
    files = sorted(p for p in CAL.iterdir() if p.is_file() and p.name != "MANIFEST.sha256")
    (CAL / "MANIFEST.sha256").write_text("".join(f"{_sha(p)}  {p.relative_to(REPO)}\n" for p in files), encoding="utf-8")
    print("dropped:", [(d["field"], d["event"]) for d in decision["dropped"]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
