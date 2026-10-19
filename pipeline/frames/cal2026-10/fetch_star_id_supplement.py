#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cal2026-10/fetch_star_id_supplement.py — the star-works supplement for every star whose OpenAlex
id the October caliber corrects (D5: A5091326353 A5090515599 -> A5091326353). Repo-authored; the
ONLY live-API step of Piece A. Pattern: pipeline/stars/caliber_2026-08-28/run_supplement.py +
supplement_fetch.py (wire protocol, 70_prep row shape, request log without the key).

    setup/.venv/bin/python pipeline/frames/cal2026-10/fetch_star_id_supplement.py --execute

Inputs (all DATA, nothing hand-typed here)
  data/cal2026-10/star_id_corrections_2026-10.csv   old_id,new_id,field,school,arrival,evidence
  data/cal2026-10/calls_2026-10.csv                 per-paper calls; rows with action=exclude for
                                                     the NEW id are dropped from the supplement
  data/star_recheck_2026-09-22/works/<new_id>.json  the 09-22 pre-arrival works cache (tripwire:
                                                     every cached work must still be on the profile;
                                                     not shipped, restricted deposit)
  the data mirror's u1_full_11school_2026-07-16/authorship_edges (measure only: how many of the
                                                     fetched works the June snapshot already holds)
Outputs (frozen into data/cal2026-10/)
  works_<new_id>_2026-10.json                       every work of the live profile (work_record shape)
  edges_supplement_star_id_corrections_2026-10.jsonl  70_prep-shaped rows, seed_author = new_id,
                                                     after the calls-table exclusions, profile order
  api_request_log_star_id_corrections_2026-10.jsonl one line per HTTP request, no api key
  supplement_report_star_id_corrections_2026-10.json  counts, sha256s, snapshot overlap, STOPs

Assumptions written down
  * The supplement adds the corrected id's works to prodlib's works domain the way the fnfix and
    cal2026-08-28 supplements do (works present in the snapshot keep the snapshot row: prodlib
    `works_domain` prefers snapshot rows, `merged` de-duplicates on (work, author)). It is
    consumed only by the economics prodlib config (stage.py concatenates it after the two frozen
    supplements). The old id's works are NOT fetched and NOT added: they belong to someone else.
  * The person map is NOT touched here. Measured 2026-09-22: the u2 person map already merges BOTH
    ids into P_A5090515599 (merge_reason raw_affil_text), and the June snapshot already holds 132
    works of A5091326353 (2004-2025) and 8 of A5090515599 (2021-2026). See stage.py for what that
    means for the frame.
  * A live profile that no longer contains a cached pre-arrival work is a moved profile -> STOP,
    nothing frozen (the 08-28 tripwire).
  * No MANIFEST is written: data/cal2026-10/MANIFEST.sha256 belongs to the October caliber driver.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import os
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))
OLD_LAYER = REPO / "pipeline" / "stars" / "caliber_2026-08-28"
if str(OLD_LAYER) not in sys.path:
    sys.path.insert(0, str(OLD_LAYER))
import supplement_fetch as sf                                          # noqa: E402

from analysis.lib.paths import load_paths                              # noqa: E402

CAL = REPO / "data" / "cal2026-10"
STAMP = "2026-10"
TAG = "star_id_corrections"
CORRECTIONS = CAL / f"star_id_corrections_{STAMP}.csv"
CALLS = CAL / f"calls_{STAMP}.csv"
RECHECK_WORKS = REPO / "data" / "star_recheck_2026-09-22" / "works"   # not shipped (restricted deposit)

STOPS: list[str] = []


def _stop(msg: str) -> None:
    STOPS.append(msg)
    print(f"\n*** STOP: {msg}", flush=True)


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def corrections() -> list[dict]:
    rows = list(csv.DictReader(open(CORRECTIONS, newline="", encoding="utf-8")))
    assert rows, f"{CORRECTIONS} is empty"
    for r in rows:
        assert r["old_id"] != r["new_id"] and r["new_id"].startswith("A"), r
    return rows


def exclusions_for(aid: str) -> set[str]:
    return {r["work_id"] for r in csv.DictReader(open(CALLS, newline="", encoding="utf-8"))
            if r["author_id"] == aid and r["action"] == "exclude"}


def snapshot_overlap(aid: str, work_ids: set[str]) -> dict:
    """How many of the fetched works the June snapshot's edge table already carries for this id."""
    import duckdb                                                      # noqa: PLC0415
    derived = pathlib.Path(load_paths()["ssd_root"]) / "derived"
    glob = derived / "u1_full_11school_2026-07-16" / "authorship_edges" / "**" / "*.parquet"
    if not (derived / "u1_full_11school_2026-07-16").is_dir():
        return {"measured": False, "why": f"{derived} not mounted"}
    con = duckdb.connect()
    snap = {t[0] for t in con.execute(
        f"SELECT DISTINCT work_id FROM read_parquet('{glob.as_posix()}', hive_partitioning=0) "
        f"WHERE author_id = ?", [aid]).fetchall()}
    con.close()
    return {"measured": True, "snapshot_works_for_id": len(snap),
            "fetched_in_snapshot": len(work_ids & snap),
            "fetched_not_in_snapshot": sorted(work_ids - snap),
            "snapshot_not_on_live_profile": sorted(snap - work_ids)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--execute", action="store_true", help="required: live OpenAlex requests")
    args = ap.parse_args(argv)
    if not args.execute:
        print("This makes a few live OpenAlex API requests (one profile per corrected id) and "
              "freezes the results into data/cal2026-10/. Re-run with --execute.", file=sys.stderr)
        return 2
    report: dict = {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
                    "authority": "the author's design record of 2026-09-22 (private archive) (D5)",
                    "inputs_sha256": {CORRECTIONS.name: _sha(CORRECTIONS), CALLS.name: _sha(CALLS)},
                    "select_note": "wire protocol = 70_prep's via supplement_fetch; supplement rows "
                                   "carry exactly 70_prep's five keys"}
    key = sf.api_key()
    report["api_key_present"] = bool(key)
    log = sf.RequestLog()
    t0 = time.time()
    sup_lines: list[str] = []
    report["stars"] = {}
    for c in corrections():
        new = c["new_id"]
        recs = sf.fetch_author_works(new, key, log)
        ids = {r["work_id"] for r in recs}
        print(f"[fetch_star_id_supplement] {new} ({c['old_id']} -> {new}): {len(recs)} works live")
        cache_p = RECHECK_WORKS / f"{new}.json"
        tripwire = {"cache": None}
        if cache_p.is_file():
            cache = json.loads(cache_p.read_text(encoding="utf-8"))
            cached = {w["work_id"] for w in cache["works"]}
            missing = sorted(cached - ids)
            tripwire = {"cache": str(cache_p.relative_to(REPO)), "cached_works": len(cached),
                        "cached_fetched_on": cache.get("fetched"), "missing_from_live": missing}
            if missing:
                _stop(f"{new}: {len(missing)} cached 09-22 works are gone from the live profile "
                      f"({missing[:5]}) — the profile moved; nothing frozen")
        else:
            _stop(f"{new}: no 09-22 works cache at {cache_p} — no tripwire possible")
        drop = exclusions_for(new)
        kept = [r for r in recs if r["work_id"] not in drop]
        applied = [{"work_id": w, "dropped": w in ids} for w in sorted(drop)]
        sup_lines += [sf.supplement_line(r, new) for r in kept]
        report["stars"][new] = {
            "old_id": c["old_id"], "field": c["field"], "school": c["school"],
            "arrival": c["arrival"], "works_fetched": len(recs), "exclusions_applied": applied,
            "supplement_rows": len(kept), "tripwire": tripwire,
            "years": {"min": min((r["publication_year"] or 0) for r in kept) if kept else None,
                      "max": max((r["publication_year"] or 0) for r in kept) if kept else None},
            "snapshot_overlap": snapshot_overlap(new, {r["work_id"] for r in kept})}
        report["stars"][new]["_works_json"] = f"works_{new}_{STAMP}.json"
        report["stars"][new]["_records"] = recs                     # frozen below, then dropped
    report["request_total"] = len(log.entries)
    report["fetch_seconds"] = round(time.time() - t0, 1)
    if STOPS:
        failed = pathlib.Path(os.environ.get("SAR_OUT_ROOT") or "/private/tmp") / \
            f"supplement_report_{TAG}_FAILED_{datetime.datetime.now():%Y%m%d_%H%M%S}.json"
        failed.parent.mkdir(parents=True, exist_ok=True)
        for s in report["stars"].values():
            s.pop("_records", None)
        failed.write_text(json.dumps({**report, "stops": STOPS}, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        print(f"[fetch_star_id_supplement] {len(STOPS)} STOP(s) — NOTHING frozen -> {failed}")
        return 1
    for new, s in report["stars"].items():
        (CAL / s["_works_json"]).write_text(json.dumps(s.pop("_records"), ensure_ascii=False)
                                            + "\n", encoding="utf-8")
    sup_p = CAL / f"edges_supplement_{TAG}_{STAMP}.jsonl"
    sup_p.write_text("".join(sup_lines), encoding="utf-8")
    log_p = CAL / f"api_request_log_{TAG}_{STAMP}.jsonl"
    log.write(log_p)
    logged = log_p.read_text(encoding="utf-8")
    assert "api_key" not in logged and (not key or key not in logged), "api key leaked into the log"
    report["outputs_sha256"] = {p.name: _sha(p) for p in [sup_p, log_p] +
                               [CAL / s["_works_json"] for s in report["stars"].values()]}
    rep_p = CAL / f"supplement_report_{TAG}_{STAMP}.json"
    rep_p.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[fetch_star_id_supplement] frozen {sup_p.name} ({len(sup_lines)} rows), {log_p.name} "
          f"({report['request_total']} requests, {report['fetch_seconds']} s), {rep_p.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
