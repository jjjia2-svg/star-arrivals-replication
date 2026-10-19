#!/usr/bin/env python3
"""R1 RK6 inputs and summaries (instance side). No ranking here.

  build      requests.json for the recovered RK ranking script from the merged candidate table, plus
             the RK1 production inputs (drops, adds, control) copied byte for byte from the recovered
             RK1 payload. Every original star (G0) and every open candidate with an id and an arrival
             year is ranked. Prior per-paper cleaning comes from RK4's requests. With --paper-checks /
             --rk6a-out / --rulings (Task 9) it also folds in the validated paper checks and stages
             what rk6b_rank.py needs.
  summarize  after RK6a: recount the 187 control from the csvs (rk1.py never checks their number),
             counts only in summary.json, and the review pack for the paper checks.
Runs only on an R1 instance ($SAR_HOST); the job runs a copy at /work/rk6_requests.py.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import os
import pathlib
import re
import shutil
import sys

AWS_HOSTS = ("ec2-r1-test", "ec2-r1")
RANKED = {"rank", "rank_after_check", "author_ruling", "rule_pending"}
FIELDS = ("econ", "chemistry", "math_stats")
#: G0 people whose per-paper list must be (re)built by the paper checks
ALWAYS_CHECK = {"A5008470795": "A5008470795: the 10-01 per-paper list was lost; rebuild it (fixes_1001.csv)",
                "A5001177483": "A5001177483: confirm every work of the merged ids is this person's (10-01, h9)"}
WID = re.compile(r"W\d+")
AID = re.compile(r"A\d{6,}")


def sha256(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def require_recovered(rec, pins=None) -> None:
    """The recovery passed, rk1.py matches its manifest, and (with pins) both match the sha256 values
    committed in git after the recovery run (config/r1/recovered_pins.json), so the S3 copy is not
    checked only against another file in the same S3 folder."""
    rec = pathlib.Path(rec)
    checks = json.loads((rec / "checks.json").read_text(encoding="utf-8"))
    if checks.get("fails") or (rec / "RESULT.txt").read_text(encoding="utf-8").strip() != "OK":
        raise SystemExit(f"the recovery did not pass: {len(checks.get('fails', []))} fails")
    want = None
    for line in (rec / "manifest.tsv").read_text(encoding="utf-8").splitlines()[1:]:
        run, part, member, _size, sha = line.split("\t")
        if (run, part, member) == ("rk1", "payload", "rk1.py"):
            want = sha
    if want is None or sha256(rec / "rk1" / "payload" / "rk1.py") != want:
        raise SystemExit("rk1.py does not match the recovery manifest")
    if pins:
        pin = json.loads(pathlib.Path(pins).read_text(encoding="utf-8"))
        got = {"rk1/payload/rk1.py": sha256(rec / "rk1" / "payload" / "rk1.py"), "manifest.tsv": sha256(rec / "manifest.tsv")}
        bad = [k for k, v in got.items() if pin.get(k) != v]
        if bad:
            raise SystemExit(f"the recovered copies differ from the git pins (config/r1/recovered_pins.json): {bad}")


def control_recount(out, ctrl) -> tuple:
    """rk1.py checks each CONTROL row it wrote but never how many it wrote, and counts 'both empty' as a
    match. Recount from ranks_<ext>_A.csv against control.json: every control exactly once, to 4 dp."""
    gaps, empty, n_rows = [], 0, {}
    for ext in sorted({c["ext"] for c in ctrl}):
        exp = {(c["author_id"], int(c["arrival_true"])): c["expected_pct"] for c in ctrl if c["ext"] == ext}
        p = pathlib.Path(out) / f"ranks_{ext}_A.csv"
        seen, vals = collections.Counter(), {}
        for r in (read_csv(p) if p.is_file() else []):
            if r["key"].startswith("CONTROL|"):
                k = (r["author_id"], int(r["arrival_true"]))
                seen[k] += 1
                vals[k] = None if r["pct"] in ("", "None") else float(r["pct"])
        n_rows[ext] = sum(seen.values())
        for k, e in exp.items():
            g = vals.get(k)
            if seen[k] != 1:
                gaps.append(f"control {ext} {k[0]}: {seen[k]} rows")
            elif e is None and g is None:
                empty += 1
            elif e is None or g is None or abs(g - e) >= 5e-5:
                gaps.append(f"control {ext} {k[0]}: {g} vs {e}")
        gaps += [f"control {ext} {k[0]}: not in control.json" for k in seen if k not in exp]
    return gaps, empty, n_rows


def prior_cleaning(rk4_requests) -> dict:
    out = {}
    for r in rk4_requests:
        if not r.get("cleaning"):
            continue
        cur = out.setdefault(r["ids"][0], {"exclude_wids": set(), "min_years": set()})
        cur["exclude_wids"].update(r.get("exclude_wids") or [])
        if r.get("min_year"):
            cur["min_years"].add(int(r["min_year"]))
    return out


def requests_from_merged(rows, prior, checks=None) -> tuple:
    checks = checks or {}
    out, skipped, seen = [], [], set()
    for r in rows:
        g0 = "G0" in r["sources"].split("|")
        if not (g0 or r["status"] in RANKED) or not r["person_id"] or not str(r["arrival_year"]).strip():
            continue
        if r["field"] not in FIELDS:
            raise SystemExit(f"{r['person_id']}: field {r['field']!r}")
        pid = r["person_id"]
        ids = [i for i in r["all_ids"].split("|") if i]
        ids = [pid] + [i for i in ids if i != pid]
        pc = prior.get(pid, {"exclude_wids": set(), "min_years": set()})
        excl, min_year, note, id_corrected = set(pc["exclude_wids"]), None, "", False
        if len(pc["min_years"]) == 1:
            min_year = next(iter(pc["min_years"]))
        elif len(pc["min_years"]) > 1:
            note = f"prior min_year conflict {sorted(pc['min_years'])}: none applied"
        ck = checks.get(pid)
        if ck:
            if not ck["id_ok"]:
                if not ck["correct_ids"]:
                    skipped.append(pid)
                    continue
                ids, id_corrected = list(dict.fromkeys(ck["correct_ids"])), True
            excl |= set(ck["exclude_wids"])
            ids += [i for i in ck["merge_ids"] if i not in ids]
        y = int(r["arrival_year"]) - 1
        key = f"{r['field']}|{pid}|Y{y}"
        if key in seen:
            raise SystemExit(f"duplicate request {key}")
        seen.add(key)
        out.append({"key": key, "person": pid, "ids": ids, "Y": y, "field": r["field"],
                    "exclude_wids": sorted(excl), "min_year": min_year,
                    "cleaning": bool(excl or min_year or len(ids) > 1), "prior_cleaning": pid in prior,
                    "paper_checked": bool(ck), "id_corrected": id_corrected, "needs_paper_review": False,
                    "reason": (r.get("status_reason") or "")[:300], "src": r["sources"], "status": r["status"], "note": note})
    return sorted(out, key=lambda q: q["key"]), skipped


def read_csv(p) -> list:
    with open(p, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def cmd_build(a) -> int:
    require_recovered(a.recovered, a.pins)
    if a.rk6a_out:
        res = a.rk6a_out / "RESULT.txt"
        if not res.is_file() or res.read_text(encoding="utf-8").split()[:1] != ["OK"]:
            raise SystemExit("RK6a did not pass (its RESULT.txt is not OK): no RK6b")
    a.out.mkdir(parents=True, exist_ok=False)
    rk1in = a.recovered / "rk1" / "payload" / "in"
    for name in ("drops.csv", "adds.csv", "control.json"):
        shutil.copyfile(rk1in / name, a.out / name)
    rk4 = json.loads((a.recovered / "rk4" / "payload" / "in" / "requests.json").read_text(encoding="utf-8"))
    checks = {}
    if a.paper_checks:
        if not a.rk6a_out:
            raise SystemExit("--paper-checks needs --rk6a-out (the works lists to check against)")
        checks = load_paper_checks(a.paper_checks, a.rk6a_out / "review_pack" / "works")
    reqs, skipped = requests_from_merged(read_csv(a.merged), prior_cleaning(rk4), checks)
    (a.out / "requests.json").write_text(json.dumps(reqs, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (a.out / "skipped.json").write_text(json.dumps(skipped) + "\n", encoding="utf-8")
    if a.rk6a_out:
        shutil.copyfile(a.rk6a_out / "ranks_11_A.csv", a.out / "rk6a_ranks_11_A.csv")
    if a.rulings:
        shutil.copyfile(a.rulings, a.out / "rulings_p1.json")
    inputs = {p.name: sha256(p) for p in sorted(a.out.iterdir())}
    inputs["merged:candidates_merged.csv"] = sha256(a.merged)
    (a.out / "inputs.json").write_text(json.dumps(inputs, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"requests {len(reqs)}; skipped (no usable id) {len(skipped)}")
    return 0


def cmd_summarize(a) -> int:
    out = a.rk_out
    result = (out / "RESULT.txt").read_text(encoding="utf-8").strip() if (out / "RESULT.txt").is_file() else "MISSING"
    rep = json.loads((out / "rk1_report.json").read_text(encoding="utf-8")) if (out / "rk1_report.json").is_file() else {}
    gaps, empty, ctrl_rows = control_recount(out, json.loads((a.inp / "control.json").read_text(encoding="utf-8")))
    (out / "control_recount.json").write_text(json.dumps({"gaps": gaps, "empty_matches": empty, "rows": ctrl_rows},
                                                          indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if gaps and result == "OK":
        result = "CONTROL_FAIL"
        (out / "RESULT.txt").write_text("CONTROL_FAIL\n", encoding="utf-8")
    reqs = json.loads((a.inp / "requests.json").read_text(encoding="utf-8"))
    ranks = {r["key"]: r for r in read_csv(out / "ranks_11_A.csv")}
    merged = {r["person_id"]: r for r in read_csv(a.merged)}
    counts = {}
    for q in reqs:
        r, arrival = ranks.get(q["key"]), q["Y"] + 1
        ok = bool(r) and r["pass_p10"] == "True" and r["aage"] not in ("", "None") and int(r["aage"]) >= 2 and 1999 <= arrival <= 2024
        k = f"{q['field']}|{q['status']}|{'G0' if 'G0' in q['src'].split('|') else 'new'}"
        c = counts.setdefault(k, {"requests": 0, "pass_unfiltered": 0, "not_in_pool": 0})
        c["requests"] += 1
        c["pass_unfiltered"] += int(ok)
        c["not_in_pool"] += int(bool(r) and r["note"] == "not_in_pool")
    import pandas as pd   # noqa: PLC0415 - only on the instance and in tests
    works = pd.read_parquet(out / "works_11.parquet")
    pack = out / "review_pack" / "works"
    pack.mkdir(parents=True, exist_ok=True)
    need = []
    for q in reqs:
        pid, g0 = q["person"], "G0" in q["src"].split("|")
        if (not g0 and not q["prior_cleaning"]) or pid in ALWAYS_CHECK:
            m = merged.get(pid, {})
            need.append({"person_id": pid, "ids": q["ids"], "name": m.get("name", ""), "field": q["field"],
                         "school": m.get("school", ""), "arrival_year": q["Y"] + 1, "status": q["status"],
                         "why": ALWAYS_CHECK.get(pid, "new candidate without a prior per-paper check")})
        w = works[works.aid.isin(q["ids"]) & (works.yr <= q["Y"])].sort_values(["yr", "wid"])
        rows = [{"wid": x.wid, "aid": x.aid, "yr": int(x.yr), "c": None if x.c != x.c else int(x.c),
                 "sf": x.sf, "title": x.title} for x in w.itertuples()]
        (pack / f"{pid}.json").write_text(json.dumps({"person_id": pid, "ids": q["ids"], "Y": q["Y"], "works": rows},
                                                     ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "review_pack" / "needs_check.json").write_text(json.dumps(need, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "review_pack" / "needs_check_ids.txt").write_text("".join(n["person_id"] + "\n" for n in need), encoding="utf-8")
    summary = {"result": result, "control_fail": len(rep.get("control_fail", [])) if rep else None,
               "control_rows": ctrl_rows, "control_gaps": len(gaps), "control_empty": empty,
               "requests": len(reqs), "needs_check": len(need), "counts": counts}
    (out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("result", "control_fail", "control_gaps", "control_empty", "requests", "needs_check")}))
    return 0 if result == "OK" else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 RK6 inputs and summaries")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--merged", required=True, type=pathlib.Path)
    b.add_argument("--recovered", required=True, type=pathlib.Path)
    b.add_argument("--out", required=True, type=pathlib.Path)
    b.add_argument("--pins", type=pathlib.Path, help="config/r1/recovered_pins.json (git)")
    b.add_argument("--paper-checks", type=pathlib.Path)
    b.add_argument("--rk6a-out", type=pathlib.Path)
    b.add_argument("--rulings", type=pathlib.Path)
    b.add_argument("--fail-summary", type=pathlib.Path,
                   help="on a refusal, write a summary.json (ids and the reason's first line, no names) and RESULT.txt here")
    s = sub.add_parser("summarize")
    s.add_argument("--rk-out", required=True, type=pathlib.Path)
    s.add_argument("--in", dest="inp", required=True, type=pathlib.Path)
    s.add_argument("--merged", required=True, type=pathlib.Path)
    a = ap.parse_args(argv)
    if os.environ.get("SAR_HOST", "").strip() not in AWS_HOSTS:
        raise SystemExit("R1 rule (design v3 §4): rk6_requests.py runs only on an R1 AWS instance ($SAR_HOST)")
    if a.cmd != "build":
        return cmd_summarize(a)
    try:
        return cmd_build(a)
    except SystemExit as e:
        if a.fail_summary and not isinstance(e.code, int):
            msg = str(e.code)
            a.fail_summary.parent.mkdir(parents=True, exist_ok=True)
            a.fail_summary.write_text(json.dumps({"result": "BUILD_FAIL", "reason": msg.splitlines()[0][:160],
                                                  "ids": sorted(set(AID.findall(msg)))}, indent=1) + "\n", encoding="utf-8")
            (a.fail_summary.parent / "RESULT.txt").write_text("BUILD_FAIL\n", encoding="utf-8")
        raise


def load_paper_checks(d, works_dir) -> dict:
    """Merge the two AI rounds per person, after checking every field (plan Task 8 schemas).

    exclude = (round-1 exclusions | round-2 missed) - round-2 wrongly excluded; merge ids likewise;
    the id counts as right only if both rounds say so; corrected ids are used only when both rounds
    say the id is wrong and round 2 names the right one. Any malformed file, a missing round, or a
    listed work that is not in the person's RK6a works list refuses the whole set. An extra file adds
    exclusions on merged or corrected profiles (their works are not in that list), and may drop a merge the
    rounds made (merge_ids_drop) when a later check found that profile is someone else."""
    d, works_dir = pathlib.Path(d), pathlib.Path(works_dir)
    r1s = {p.stem: p for p in sorted((d / "round1").glob("A*.json"))}
    r2s = {p.stem: p for p in sorted((d / "round2").glob("A*.json"))}
    errs, out = [], {}
    for pid in sorted(set(r1s) | set(r2s)):
        if pid not in r1s or pid not in r2s:
            errs.append(f"{pid}: needs both round1 and round2 (two rounds are required)")
            continue
        try:
            r1 = json.loads(r1s[pid].read_text(encoding="utf-8"))
            r2 = json.loads(r2s[pid].read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errs.append(f"{pid}: {e}")
            continue
        if r1.get("schema") != "sar.r1.paper_read.v1" or r2.get("schema") != "sar.r1.paper_check2.v1":
            errs.append(f"{pid}: wrong schema")
        if r1.get("person_id") != pid or r2.get("person_id") != pid:
            errs.append(f"{pid}: the person_id inside a file differs from its name")
        if not str(r1.get("agent", "")).strip() or not str(r2.get("agent", "")).strip():
            errs.append(f"{pid}: agent missing")
        if not isinstance(r1.get("id_ok"), bool) or not isinstance(r2.get("id_ok"), bool):
            errs.append(f"{pid}: id_ok must be true or false")
        wids = [*r1.get("exclude_wids", []), *r2.get("wrongly_excluded_wids", []), *r2.get("missed_wids", [])]
        aids = [*r1.get("merge_ids", []), *r1.get("correct_ids", []), *r2.get("merge_ids_add", []),
                *r2.get("merge_ids_drop", []), *r2.get("correct_ids", [])]
        bad = [w for w in wids if not WID.fullmatch(str(w))] + [x for x in aids if not AID.fullmatch(str(x))]
        if bad:
            errs.append(f"{pid}: malformed ids {bad[:5]}")
        wf = works_dir / f"{pid}.json"
        if not wf.is_file():
            errs.append(f"{pid}: no works list in the RK6a review pack")
            continue
        known = {w["wid"] for w in json.loads(wf.read_text(encoding="utf-8"))["works"]}
        unknown = [w for w in wids if w not in known]
        if unknown:
            errs.append(f"{pid}: excludes works not in the person's list: {unknown[:5]}")
        excl = (set(r1.get("exclude_wids", [])) | set(r2.get("missed_wids", []))) - set(r2.get("wrongly_excluded_wids", []))
        drop = set(r2.get("merge_ids_drop", []))
        merge = [x for x in dict.fromkeys([*r1.get("merge_ids", []), *r2.get("merge_ids_add", [])]) if x not in drop]
        id_ok = bool(r1.get("id_ok")) and bool(r2.get("id_ok"))
        both_wrong = (r1.get("id_ok") is False) and (r2.get("id_ok") is False)
        correct = list(r2.get("correct_ids") or []) if both_wrong else []
        out[pid] = {"exclude_wids": sorted(excl), "merge_ids": merge, "id_ok": id_ok, "correct_ids": correct}
    # extra/<pid>.json (2026-10-11): works on a merged or corrected profile are not in the RK6a
    # works list, so the rounds cannot exclude them; this file names the ones someone else wrote. Each profile it
    # covers must be merged (here or in the rounds) or be the corrected id.
    for p in sorted((d / "extra").glob("A*.json")) if (d / "extra").is_dir() else []:
        pid = p.stem
        if pid not in r1s or pid not in r2s:
            errs.append(f"{pid}: extra file without round1 and round2")
            continue
        try:
            x = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errs.append(f"{pid}: extra file {e}")
            continue
        bad = []
        if x.get("schema") != "sar.r1.paper_extra.v1":
            bad.append("schema")
        if x.get("person_id") != pid:
            bad.append("person_id")
        if not str(x.get("decided", "")).strip():
            bad.append("decided is empty")
        if not str(x.get("agent", "")).strip():
            bad.append("agent")
        ws, ms, ps = x.get("exclude_wids") or [], x.get("merge_ids") or [], x.get("profile_ids") or []
        # merge_ids_drop (J0-MEAS.3e, 2026-10-16): a later check found a profile the rounds merged holds someone
        # else's works; it leaves the merge ids as round 2's merge_ids_drop would, so none of its works rank or dose
        ds = x.get("merge_ids_drop") or []
        mal = [w for w in ws if not WID.fullmatch(str(w))] + [a for a in [*ms, *ps, *ds] if not AID.fullmatch(str(a))]
        if mal:
            bad.append(f"malformed ids {mal[:5]}")
        cur = out.get(pid)
        if cur is not None and not mal:
            stray = sorted({d for d in ds if d not in cur["merge_ids"] or d in ms})
            if stray:
                bad.append(f"merge_ids_drop {stray} are not merged by the rounds alone")
            allowed = (set(ms) | set(cur["merge_ids"]) | set(cur["correct_ids"])) - set(ds)
            if not ps or not set(ps) <= allowed:
                bad.append(f"profile_ids {sorted(set(ps) - allowed) or '[]'} are neither merged nor the corrected id")
        if bad:
            errs.append(f"{pid}: extra file refused: " + "; ".join(bad))
            continue
        if cur is not None:
            cur["exclude_wids"] = sorted(set(cur["exclude_wids"]) | set(ws))
            cur["merge_ids"] = [m for m in cur["merge_ids"] if m not in ds]
            cur["merge_ids"] += [m for m in ms if m not in cur["merge_ids"]]
    if errs:
        raise SystemExit("paper checks refused:\n  " + "\n  ".join(errs))
    return out


if __name__ == "__main__":
    sys.exit(main())
