#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""caliber_2026-10/build_calls.py — assemble the per-star work-level cleanup DATA table for the
October 2026 caliber from (a) the signed 2026-08-28 calls, carried forward unchanged, and (b) the
2026-09-22 paper-by-paper recheck of 17 economics stars (data/star_recheck_2026-09-22/, not shipped:
per-paper adjudication records with names; restricted deposit).

Output: data/cal2026-10/calls_2026-10.csv, same schema as calls_2026-08-28.csv
  (author_id,name,work_id,publication_year,action,dossier,note) with actions
  exclude / merge_from_<id> / first_pub_anchor, plus two side tables:
  data/cal2026-10/star_id_corrections_2026-10.csv  (event star ids that point at the wrong person)
  data/cal2026-10/recheck_uncertain_2026-10.csv    (works left uncertain: NOT excluded, listed)

Rules (author decision D5, 2026-09-22): a work adjudicated is_mine=false is excluded from the
star's pre-arrival stock; uncertain works stay (conservative: the stock is not lowered on a
guess); split ids found with evidence become merge_from rows for the supplement fetch, never
restake additions (2026-08-28 policy). Nothing is hand-typed: every row cites its source file.
"""
from __future__ import annotations

import csv
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]
RECHECK = REPO / "data" / "star_recheck_2026-09-22"   # not shipped (restricted deposit)
OLD_CALLS = REPO / "data" / "cal2026-08-28" / "calls_2026-08-28.csv"
OUT_DIR = REPO / "data" / "cal2026-10"
COLS = ["author_id", "name", "work_id", "publication_year", "action", "dossier", "note"]

#: event star ids that resolve to a different person (evidence in targets.csv / adjudication json)
ID_CORRECTIONS = [
    {"old_id": "A5090515599", "new_id": "A5091326353", "field": "econ", "school": "uwa", "arrival": "2009",
     "evidence": "id_split_verified_2026-09-22"},   # public copy: the per-paper adjudication is private
]


def main(argv=None) -> int:
    targets = list(csv.DictReader(open(RECHECK / "targets.csv", encoding="utf-8")))
    old_rows = list(csv.DictReader(open(OLD_CALLS, encoding="utf-8")))
    new_rows, uncertain, missing = [], [], []
    corrected = {c["old_id"]: c["new_id"] for c in ID_CORRECTIONS}
    for t in targets:
        sid = corrected.get(t["star_id"], t["star_id"])
        adj_p = RECHECK / "adjudication" / f"{sid}.json"
        calls_p = RECHECK / "calls" / f"{sid}.csv"
        if not adj_p.exists() or not calls_p.exists():
            missing.append(sid)
            continue
        adj = json.load(open(adj_p, encoding="utf-8"))
        dossier = f"data/star_recheck_2026-09-22/adjudication/{sid}.json"   # a path label; not shipped
        for r in csv.DictReader(open(calls_p, encoding="utf-8")):
            im = r["is_mine"].strip().lower()
            if r.get("belongs_to_main_id", "").strip():
                # a work of a split id that belongs to the star: merge row (fetch), not a restake add
                new_rows.append({"author_id": r["belongs_to_main_id"].strip(), "name": adj["name"],
                                 "work_id": r["work_id"], "publication_year": r["year"],
                                 "action": f"merge_from_{r['author_id']}", "dossier": dossier,
                                 "note": r["reason"][:300]})
                continue
            if im == "false":
                new_rows.append({"author_id": sid, "name": adj["name"], "work_id": r["work_id"],
                                 "publication_year": r["year"], "action": "exclude",
                                 "dossier": dossier, "note": r["reason"][:300]})
            elif im == "uncertain":
                uncertain.append({"author_id": sid, "name": adj["name"], "work_id": r["work_id"],
                                  "publication_year": r["year"], "reason": r["reason"][:300]})
    if missing and "--allow-missing" not in (argv or sys.argv[1:]):
        print("STOP: no adjudication/calls yet for:", ", ".join(missing), file=sys.stderr)
        return 2
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "calls_2026-10.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(old_rows)
        w.writerows(new_rows)
    with open(OUT_DIR / "recheck_uncertain_2026-10.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["author_id", "name", "work_id", "publication_year", "reason"])
        w.writeheader()
        w.writerows(uncertain)
    with open(OUT_DIR / "star_id_corrections_2026-10.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(ID_CORRECTIONS[0].keys()))
        w.writeheader()
        w.writerows(ID_CORRECTIONS)
    n_ex = sum(r["action"] == "exclude" for r in new_rows)
    n_mg = sum(r["action"].startswith("merge_from_") for r in new_rows)
    print(f"calls_2026-10.csv: {len(old_rows)} carried from 2026-08-28 + {n_ex} new exclusions + "
          f"{n_mg} merge rows; {len(uncertain)} uncertain (kept); missing adjudications: {missing or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
