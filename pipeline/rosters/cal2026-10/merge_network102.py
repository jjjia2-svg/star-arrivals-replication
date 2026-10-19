#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cal2026-10/merge_network102.py — fold the 2026-09-13 two-round verification of the 102
never-verified network-route economists into the verified economics roster, under the author's
five rulings of 2026-09-22 (D3), which are DATA in data/cal2026-10/roster_overrides_2026-10.csv:

  D3-1 years: the recheck round's final years win (round2_check.json final_year_*).
  D3-2 UTS CHERE after its 2021 move counts as UTS economics (author ruling 2026-07-10).
  D3-3 unverifiable persons stay at confidence 'low' (2026-08-09 convention).
  D3-4 ids: mixtures of other people are rejected; a confirmed person whose main id is another
       person keeps only their own id; severe merges are kept and flagged.
  D3-5 confirmed persons enter the roster, so the roster channel gains their relations.

Inputs  data/raw_verified/roster_econ_verified.parquet (920, 2026-08-09),
        data/roster_verify_2026-09-13_network102/{results_102.csv, round2_check.json}
        (not shipped: names and per-person evidence; restricted deposit),
        data/cal2026-10/roster_overrides_2026-10.csv
Output  data/cal2026-10/roster_econ_verified_2026-10.parquet (same 16 columns),
        data/cal2026-10/roster_merge_report_2026-10.json, roster_added_2026-10.csv
"""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import sys

import pandas as pd

REPO = pathlib.Path(__file__).resolve().parents[3]
RV = REPO / "data" / "raw_verified" / "roster_econ_verified.parquet"
NET = REPO / "data" / "roster_verify_2026-09-13_network102"   # not shipped (restricted deposit)
CAL = REPO / "data" / "cal2026-10"
SRC = "llm_two_round_2026-09-13 (D3 rulings 2026-09-22)"


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    base = pd.read_parquet(RV)
    res = pd.read_csv(NET / "results_102.csv", dtype=str).fillna("")
    r2 = json.load(open(NET / "round2_check.json", encoding="utf-8"))
    ov = pd.read_csv(CAL / "roster_overrides_2026-10.csv", dtype=str).fillna("")
    ov_by_name = {(r.display_name, r.dept_key): r for r in ov.itertuples()}
    assert len(ov_by_name) == len(ov), "override rows must be unique by (name, dept)"
    added, skipped, used_ov = [], [], set()
    for x in res.itertuples():
        j = r2[x.person_id]
        o = ov_by_name.get((x.display_name, x.dept_key))
        verdict = j["final_verdict"]
        ys, ye = j.get("final_year_start"), j.get("final_year_end")
        conf = None
        author_id = x.person_id[2:] if x.person_id.startswith("P_") else x.person_id
        note = ""
        if o is not None:
            used_ov.add((o.display_name, o.dept_key))
            if o.action == "reject":
                skipped.append({"person_id": x.person_id, "display_name": x.display_name, "dept_key": x.dept_key,
                                "why": o.rule})
                continue
            verdict = "confirmed"
            conf = o.confidence or None
            note = o.rule
            if o.action == "confirm_own_id":
                author_id = o.own_author_id
            if ys is None:
                ys = 2021 if "CHERE" in o.rule else None
        if verdict != "confirmed":
            skipped.append({"person_id": x.person_id, "display_name": x.display_name, "dept_key": x.dept_key,
                            "why": f"round-2 {verdict}: {j.get('final_reject_cause', '')}"})
            continue
        if ys is None:
            skipped.append({"person_id": x.person_id, "display_name": x.display_name, "dept_key": x.dept_key,
                            "why": "confirmed but no start year in either round"})
            continue
        if ye is None:
            ye = 2026
            note = (note + "; " if note else "") + "open end set to 2026"
        idst = j.get("final_id_status", "")
        if conf is None:
            conf = "high" if (j.get("agree_years") and idst in ("ok", "merged_minor")) else "medium"
        r1s, r1e = (x.r1_years.split("-") + ["", ""])[:2]
        r1s = int(r1s) if r1s.isdigit() else int(ys)
        r1e = int(r1e) if r1e.isdigit() else int(ye)
        added.append({
            "dept_key": x.dept_key, "school": x.dept_key.rsplit("_", 1)[0], "author_id": author_id,
            "year_start": int(ys), "year_end": int(ye), "evidence": "llm_two_round_public_records",
            "confidence": conf, "human_verified": False,
            "evidence_url": (x.r1_evidence_urls.split(";")[0] if x.r1_evidence_urls else ""),
            "year_start_orig": r1s, "year_end_orig": r1e, "year_corrected": (r1s, r1e) != (int(ys), int(ye)),
            "id_issue": {"ok": "", "merged_minor": "轻度并号", "merged_severe": "严重并号（保留并标记）",
                         "wrong_person": "主号是别人，只用本人号"}.get(idst, idst),
            "year_note": (note or (j.get("reason") or "")[:160]),
            "verify_source": SRC, "dup_person_flag": "",
        })
    missing_ov = set(ov_by_name) - used_ov
    assert not missing_ov, f"override rows not matched to results_102: {missing_ov}"
    add = pd.DataFrame(added)
    clash = set(add.author_id) & set(base.author_id)
    assert not clash, f"already on the 2026-08-09 roster: {clash}"
    assert add.author_id.is_unique, "duplicate author_id among the added rows"
    out = pd.concat([base, add[base.columns]], ignore_index=True)
    CAL.mkdir(parents=True, exist_ok=True)
    out.to_parquet(CAL / "roster_econ_verified_2026-10.parquet", index=False)
    add.to_csv(CAL / "roster_added_2026-10.csv", index=False)
    rep = {"base_rows": int(len(base)), "added": int(len(add)), "skipped": skipped, "total": int(len(out)),
           "added_by_dept": add.dept_key.value_counts().to_dict(), "added_by_confidence": add.confidence.value_counts().to_dict(),
           "inputs_sha256": {"roster_econ_verified.parquet": sha(RV), "results_102.csv": sha(NET / "results_102.csv"),
                             "round2_check.json": sha(NET / "round2_check.json"),
                             "roster_overrides_2026-10.csv": sha(CAL / "roster_overrides_2026-10.csv")},
           "output_sha256": sha(CAL / "roster_econ_verified_2026-10.parquet")}
    (CAL / "roster_merge_report_2026-10.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"roster: {len(base)} + {len(add)} = {len(out)}; skipped {len(skipped)}; by confidence {rep['added_by_confidence']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
