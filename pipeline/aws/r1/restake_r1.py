#!/usr/bin/env python3
"""R1 rank tables (EC2 only): the tables every event writer reads, in October's shapes, at one place (the stage
output work:prod/rank_tables). No ranking here.

  b0  --cal DIR --out DIR
      config B0 (own_field off): byte copies of October's frozen restake_econ11_aug / restake_econ11_aug_all and
      _invalid_run2/verdicts files, each sha-checked against its MANIFEST line first (_invalid_run2/MANIFEST.sha256
      records the paths one level up, as data/cal2026-10/<name>). October basenames; kind.json kind B0.
  m   --rk DIR --repo DIR --out DIR
      config M: verdicts from the signed lists (flips_r1.json KEEP/DROP, add_list_r1.json ACCEPT; REJECT is not
      written), ranks from the gated RK6b run in DIR (joined by flips.key, never by author_id). Every in-star must
      have one rank row and a passing pass; after_* come from the admitting pass (own if in_own, else C), before_*
      from pass A; the top-5% flag is author decision 4 for C-admitted stars (pass_p05 on the pass-C row, age and
      window gates) and rk6b's p05_own for everyone else. Arrival = the rank key's Y + 1, which must equal October's
      arrival_true unless a signed redate names the person (fixes_1001 redate, person_overrides arrival_year), and an
      ACCEPT's add-list arrival_year. By-rule rows (no persons/P1 entry) must agree with in_own and pct_own (5e-5).
      Any disagreement STOPs (RESULT.txt STOP, exit 1, no table written) and goes to the author.
      Writes restake_econ_r1.csv, verdicts_chemmath_r1.csv, restake_r1.csv, p05_flags_r1.csv, counts.json,
      summary.json (counts and ids only), kind.json, RESULT.txt.

The pass_p05 / gate_age / in_window predicates are the October ones (run_caliber 2026-10, caliber 2026-08-28),
imported through rk6b_rank.setup_import_paths, so RK6b and these tables share one code path.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import importlib
import json
import os
import pathlib
import re
import shutil
import sys
import types

AWS_HOSTS = ("ec2-r1-test", "ec2-r1")
FIELDS = ("econ", "chemistry", "math_stats")
CAL_LABEL = "data/cal2026-10"                         # the root both October MANIFESTs record paths under
B0_ECON = "restake_econ11_aug_2026-10.csv"
B0_ECON_ALL = "restake_econ11_aug_all_2026-10.csv"
B0_CM = "verdicts_2026-10.csv"
M_ECON, M_CM, M_RESTAKE, M_P05 = "restake_econ_r1.csv", "verdicts_chemmath_r1.csv", "restake_r1.csv", "p05_flags_r1.csv"
RANK_FILES = ("ranks_A.csv", "ranks_own.csv", "ranks_C.csv", "flips.csv")
INPUTS = "data/cal2026-10r1/inputs"   # the signed R1 inputs (not shipped)
SIGNED_FILES = ("flips_r1.json", "add_list_r1.json", "p2_decisions.json", "author_rulings_p1.json",
                "fixes_1001.csv", "person_overrides.csv")
ECON_EXTRA = ["rank_pass", "verdict", "verdict_source", "arrival_oct", "event_id_old"]
CM_EXTRA = ["rank_pass", "verdict", "verdict_source", "arrival_oct"]
KEY_Y = re.compile(r"^([a-z_]+)\|([^|]+)\|Y(\d{4})$")
TOL = 5e-5


def _sha(p) -> str:
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def read_csv(p) -> list:
    with open(p, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def read_header(p) -> list:
    with open(p, encoding="utf-8", newline="") as fh:
        return next(csv.reader(fh))


def _write_csv(p, cols, rows) -> None:
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        # Public headers omit these two personal metadata columns. Unknown fields still fail.
        w.writerows({k: v for k, v in row.items() if k in cols or k not in {"name", "note"}}
                    for row in rows)


def _write_json(p, obj) -> None:
    pathlib.Path(p).write_text(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------------------------------- B0
def _manifest(p) -> dict:
    out = collections.defaultdict(list)
    for line in pathlib.Path(p).read_text(encoding="utf-8").splitlines():
        if line.strip():
            sha, path = line.split("  ", 1)
            out[path].append(sha)
    return out


def copy_october(cal, out) -> dict:
    """The three October tables, each checked against its MANIFEST line, then copied byte for byte."""
    cal, out = pathlib.Path(cal), pathlib.Path(out)
    main_man, run2_man = _manifest(cal / "MANIFEST.sha256"), _manifest(cal / "_invalid_run2" / "MANIFEST.sha256")
    plan = ((B0_ECON, cal / B0_ECON, main_man), (B0_ECON_ALL, cal / B0_ECON_ALL, main_man),
            (B0_CM, cal / "_invalid_run2" / B0_CM, run2_man))
    shas = {}
    for name, src, man in plan:
        want = man.get(f"{CAL_LABEL}/{name}", [])
        if len(want) != 1:
            raise SystemExit(f"B0: {name} has {len(want)} MANIFEST lines (want one, recorded as {CAL_LABEL}/{name})")
        got = _sha(src)
        if got != want[0]:
            raise SystemExit(f"B0: {src.relative_to(cal)} sha256 {got[:12]} != MANIFEST {want[0][:12]}: not October's file")
        shas[name] = got
    out.mkdir(parents=True, exist_ok=True)
    for name, src, _man in plan:
        shutil.copyfile(src, out / name)
        if _sha(out / name) != shas[name]:
            raise SystemExit(f"B0: the copy of {name} differs from its source")
    _write_json(out / "kind.json", {"schema": "sar.r1.rank_tables.v1", "kind": "B0", "inputs": shas})
    _write_json(out / "summary.json", {"result": "OK", "kind": "B0", "files": sorted(shas)})
    (out / "RESULT.txt").write_text("OK\n", encoding="utf-8")
    return shas


# ---------------------------------------------------------------------------------------------------- M inputs
def machine(repo) -> types.SimpleNamespace:
    """run_caliber (2026-10: pass_p05), caliber (gate_age, in_window) and screening_lib (L: P05, CELL_MIN_N), on the
    import paths rk6b_rank used for p05_own. screening_lib is the module restake_equiv._screening_modules() returns;
    it is imported directly because run_screening resolves its data table at import and is not needed here."""
    repo = pathlib.Path(repo)
    saved = list(sys.path)
    try:
        sys.path.append(str(repo / "pipeline" / "aws" / "r1"))          # a /work copy of rk6b_rank.py, if any, wins
        import rk6b_rank                                                # noqa: PLC0415
        rk6b_rank.setup_import_paths(repo)
        stale = sys.modules.get("run_caliber")
        if stale is not None and not hasattr(stale, "pass_p05"):        # the 08-28 run_caliber, imported earlier
            del sys.modules["run_caliber"]
        rc = importlib.import_module("run_caliber")
        caliber = importlib.import_module("caliber")
        L = importlib.import_module("screening_lib")
    finally:
        sys.path[:] = saved
    if pathlib.Path(rc.__file__).resolve().parent.name != "caliber_2026-10" or not hasattr(rc, "pass_p05"):
        raise SystemExit(f"run_caliber resolved to {rc.__file__}, not the 2026-10 layer with pass_p05")
    if pathlib.Path(L.__file__).resolve().parent != rc.restake_equiv.SCREENING.resolve():
        raise SystemExit(f"screening_lib resolved to {L.__file__}, not the repo's ported copy")
    return types.SimpleNamespace(rc=rc, caliber=caliber, L=L)


def load_rank(rk_dir) -> dict:
    rk = pathlib.Path(rk_dir)
    out = {"dir": rk, "flips": read_csv(rk / "flips.csv")}
    for name, tag in (("ranks_A.csv", "A"), ("ranks_own.csv", "own"), ("ranks_C.csv", "C")):
        out[tag] = {r["key"]: r for r in read_csv(rk / name)}
    return out


def _nine(rulings) -> set:
    ids = set()
    for name, rule in (rulings.get("rules_for_the_nine") or {}).items():
        ids |= set(rule) if name == "out_on_rank_either_way" else set((rule.get("persons") or {}))
    return ids


def load_signed(repo) -> dict:
    inp = pathlib.Path(repo) / INPUTS
    flips = json.loads((inp / "flips_r1.json").read_text(encoding="utf-8"))
    adds = json.loads((inp / "add_list_r1.json").read_text(encoding="utf-8"))
    if flips.get("schema") != "sar.r1.flips.v1" or adds.get("schema") != "sar.r1.add_list.v1":
        raise SystemExit("flips_r1.json / add_list_r1.json: unexpected schema")
    p2 = json.loads((inp / "p2_decisions.json").read_text(encoding="utf-8"))
    rulings = json.loads((inp / "author_rulings_p1.json").read_text(encoding="utf-8"))
    redates = {}
    sources = [(r["author_id"], r["value"], "fixes_1001 redate") for r in read_csv(inp / "fixes_1001.csv") if r["fix"] == "redate"]
    sources += [(r["author_id"], r["value"], "person_overrides arrival_year")
                for r in read_csv(inp / "person_overrides.csv") if r["action"] == "arrival_year"]
    for pid, year, src in sources:
        if pid in redates and redates[pid][0] != year:
            raise SystemExit(f"{pid}: two signed arrival years ({redates[pid][0]}, {year})")
        redates[pid] = (year, src)
    summ = inp / "add_list_r1_summary.json"
    return {"flips": flips["rows"], "accept": [r for r in adds["rows"] if r["verdict"] == "ACCEPT"],
            "persons": p2.get("persons") or {}, "nine": _nine(rulings), "redates": redates,
            "add_list_result": json.loads(summ.read_text(encoding="utf-8")).get("result", "") if summ.is_file() else ""}


def load_october(repo) -> dict:
    cal = pathlib.Path(repo) / CAL_LABEL
    return {"cands": {r["author_id"]: r for r in read_csv(cal / "_invalid_run2" / "candidates_2026-10.csv")},
            "econ_header": read_header(cal / B0_ECON), "cm_header": read_header(cal / "_invalid_run2" / B0_CM)}


def econ_columns(october) -> list:
    return list(october["econ_header"]) + ECON_EXTRA


def cm_columns(october) -> list:
    return list(october["cm_header"]) + CM_EXTRA


def restake_columns(mach) -> list:
    return list(mach.rc.restake_equiv.RESTAKE_HEADER)


# ---------------------------------------------------------------------------------------------------- M rules
def admit_pass(flip_row):
    """The pass that admitted a star: own when the own-field rank passes, else C (the label fix), else None."""
    if flip_row.get("in_own") == "True":
        return "own"
    if flip_row.get("in_C") == "True":
        return "C"
    return None


def p05_for(pass_, flip_row, c_row, arrival, mach) -> bool:
    """Author decision 4: a C-admitted star's top-5% flag is pass_p05 on its pass-C row (pct >= 0.95, cell_n >= 30)
    with the age and window gates; everyone else keeps rk6b's p05_own exactly."""
    if pass_ != "C":
        return flip_row.get("p05_own") == "True"
    after = {"pct": float(c_row["pct"]) if c_row.get("pct") else None,
             "cell_n": int(c_row["cell_n"]) if c_row.get("cell_n") else 0}
    return bool(mach.rc.pass_p05(after, mach.L)) and mach.caliber.gate_age(c_row.get("aage")) \
        and mach.caliber.in_window(arrival)


def signed_counts(signed) -> dict:
    out = {f: collections.Counter() for f in FIELDS}
    for r in signed["flips"]:
        out[r["field"]]["keep_187" if r["verdict"] == "KEEP" else "drop_187"] += 1
    for r in signed["accept"]:
        out[r["field"]]["accept"] += 1
    return {f: {"keep_187": c["keep_187"], "drop_187": c["drop_187"], "accept": c["accept"],
                "stars": c["keep_187"] + c["accept"]} for f, c in out.items()}


def _pct_close(a, b) -> bool:
    if not a or not b:
        return a == b
    return abs(float(a) - float(b)) < TOL


def build_m(rk, signed, october, mach, sink=None):
    """(econ_rows, cm_rows, counts, problems) - problems name ids only; any problem STOPs the stage. A dict passed as
    `sink` also receives the restake_r1.csv rows, the p05 flag rows and the ids ranked under a corrected id."""
    by_person = collections.defaultdict(list)
    for f in rk["flips"]:
        by_person[f["person_id"]].append(f)
    stars = [("flips_r1", r["verdict"], r) for r in signed["flips"]] + [("add_list_r1", "ACCEPT", r) for r in signed["accept"]]
    econ, cm, restake, p05_rows, problems, id_corrected = [], [], [], [], [], []
    counts = {f: collections.Counter() for f in FIELDS}
    for source, verdict, s in stars:
        pid, field = s["person_id"], s["field"]
        keep = verdict in ("KEEP", "ACCEPT")
        rows = by_person.get(pid, [])
        if len(rows) != 1:
            problems.append(f"{pid}: {len(rows)} rank rows in flips.csv (want one)")
            continue
        fr = rows[0]
        m = KEY_Y.match(fr["key"])
        if not m or fr["field"] != field or m.group(1) != field or m.group(2) != pid:
            problems.append(f"{pid}: rank key {fr['key']} does not belong to {field}|{pid}")
            continue
        arrival = int(m.group(3)) + 1
        if str(arrival) != str(fr.get("arrival")):
            problems.append(f"{pid}: flips arrival {fr.get('arrival')} != key Y+1 {arrival}")
        a_row, o_row, c_row = rk["A"].get(fr["key"]), rk["own"].get(fr["key"]), rk["C"].get(fr["key"])
        ap = admit_pass(fr) if keep else None
        if keep and ap is None:
            problems.append(f"{pid}: {verdict} but no passing pass (in_own {fr.get('in_own') or '-'}, in_C {fr.get('in_C') or '-'})")
            continue
        adm = (c_row if ap == "C" else o_row)
        if adm is None:
            problems.append(f"{pid}: no ranks_{ap or 'own'} row for {fr['key']}")
            continue
        # by rule = no persons / P1 entry: an in-star then needs the own-field rank (qualifies); a DROP may be a
        # 'signed_out' row, whose rank can pass, so only its pct_own is checked
        by_rule = pid not in signed["persons"] and pid not in signed["nine"]
        if by_rule:
            if keep and fr.get("in_own") != "True":
                problems.append(f"{pid}: {verdict} by rule but the own-field rank fails (in_own {fr.get('in_own') or '-'})")
            if not _pct_close(str(s.get("pct_own", "")), fr.get("pct_own", "")):
                problems.append(f"{pid}: signed pct_own {s.get('pct_own') or '-'} != rank pct_own {fr.get('pct_own') or '-'}")
        oct_row = october["cands"].get(pid) if source == "flips_r1" else None
        redate = signed["redates"].get(pid)
        if source == "flips_r1":
            if oct_row is None:
                problems.append(f"{pid}: one of the 187 but not in October's candidates")
                continue
            want, why = (int(redate[0]), redate[1]) if redate else (int(oct_row["arrival_true"]), "October")
            if arrival != want:
                problems.append(f"{pid}: arrival {arrival} != {why} {want} (October {oct_row['arrival_true']})")
        else:
            if str(arrival) != str(s.get("arrival_year")):
                problems.append(f"{pid}: arrival {arrival} != add list {s.get('arrival_year')}")
            if redate and int(redate[0]) != arrival:
                problems.append(f"{pid}: arrival {arrival} != {redate[1]} {redate[0]}")
        if o_row and c_row and o_row.get("aage") and c_row.get("aage") and o_row["aage"] != c_row["aage"]:
            problems.append(f"{pid}: aage own {o_row['aage']} != aage C {c_row['aage']}")
        if adm["author_id"] != pid:
            id_corrected.append(pid)
        p05 = p05_for(ap or "own", fr, c_row or {}, arrival, mach)
        aage = adm.get("aage", "")
        gate_age, in_window = mach.caliber.gate_age(aage), mach.caliber.in_window(arrival)
        a = a_row or {}
        school = oct_row["school"] if oct_row else s.get("school", "")
        arrival_oct = oct_row["arrival_true"] if oct_row else ""
        common = {"author_id": pid, "name": s.get("name", ""), "school": school, "arrival_true": arrival,
                  "rank_pass": ap or "", "verdict": verdict, "verdict_source": source, "arrival_oct": arrival_oct}
        if field == "econ":
            econ.append({**common, "before_stock": a.get("stock", ""), "before_pct": a.get("pct", ""),
                         "before_pass_p10": a.get("pass_p10", ""), "after_stock": adm.get("stock", ""),
                         "after_cell": adm.get("cell", ""), "after_cell_n": adm.get("cell_n", ""),
                         "after_pct": adm.get("pct", ""), "after_pass_p10": adm.get("pass_p10", ""),
                         "after_pass_p05": p05, "aage": aage, "gate_age": gate_age, "in_window": in_window,
                         "event_keep": keep, "july_pct": "", "note": adm.get("note", ""),
                         "event_id_old": oct_row["event_id_old"] if oct_row else ""})
        else:
            machine_p05 = bool(mach.rc.pass_p05({"pct": float(adm["pct"]) if adm.get("pct") else None,
                                                  "cell_n": int(adm["cell_n"]) if adm.get("cell_n") else 0}, mach.L))
            cm.append({**common, "field": field, "event_id_old": oct_row["event_id_old"] if oct_row else "",
                       "before_pct": a.get("pct", ""), "after_pct": adm.get("pct", ""),
                       "after_cell_n": adm.get("cell_n", ""), "after_pass": adm.get("pass_p10", ""),
                       "pass_p05": machine_p05, "aage": aage, "gate_age": gate_age, "in_window": in_window,
                       "event_cal2026_10": keep, "event_p05": p05 and keep,
                       "reason_if_out": "" if keep else "signed_drop", "note": adm.get("note", "")})
        restake.append({"author_id": pid, "name": s.get("name", ""), "field": field, "school": school,
                        "arrival_true": arrival, "before_stock": a.get("stock", ""), "before_cell": a.get("cell", ""),
                        "before_pct": a.get("pct", ""), "before_pass": a.get("pass_p10", ""),
                        "after_stock": adm.get("stock", ""), "after_cell": adm.get("cell", ""),
                        "after_cell_n": adm.get("cell_n", ""), "after_pct": adm.get("pct", ""),
                        "after_pass": adm.get("pass_p10", ""), "note": adm.get("note", ""), "aage": aage})
        c = counts[field]
        c["keep_187" if verdict == "KEEP" else "drop_187" if verdict == "DROP" else "accept"] += 1
        if keep:
            c["stars"] += 1
            c["own" if ap == "own" else "label_fix"] += 1
            c["p05"] += bool(p05)
            p05_rows.append({"star_id": pid, "field": field, "p05": p05, "basis": ap,
                             "pct": adm.get("pct", ""), "cell_n": adm.get("cell_n", "")})
    counts = {f: {k: c[k] for k in ("stars", "keep_187", "drop_187", "accept", "p05", "label_fix", "own")}
              for f, c in counts.items()}
    want = signed_counts(signed)
    for f in FIELDS:
        got = {k: counts[f][k] for k in want[f]}
        if got != want[f]:
            problems.append(f"counts {f}: tables {got} != signed lists {want[f]}")
    econ.sort(key=lambda r: r["author_id"])
    cm.sort(key=lambda r: (r["field"], r["author_id"]))
    if sink is not None:
        sink.update({"restake": sorted(restake, key=lambda r: r["author_id"]),
                     "p05": sorted(p05_rows, key=lambda r: (r["field"], r["star_id"])), "id_corrected": sorted(id_corrected)})
    return econ, cm, counts, problems


def run_m(rk_dir, repo, out) -> int:
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    mach = machine(repo)
    rk = load_rank(rk_dir)
    signed, october = load_signed(repo), load_october(repo)
    extra = {}
    econ, cm, counts, problems = build_m(rk, signed, october, mach, sink=extra)
    result = "OK" if not problems else "STOP"
    summary = {"result": result, "kind": "M", "counts": counts, "problems": problems[:200], "n_problems": len(problems),
               "id_corrected": extra["id_corrected"], "add_list_result": signed["add_list_result"],
               "label_fix_ids": sorted(r["star_id"] for r in extra["p05"] if r["basis"] == "C")}
    if result == "OK":
        _write_csv(out / M_ECON, econ_columns(october), econ)
        _write_csv(out / M_CM, cm_columns(october), cm)
        _write_csv(out / M_RESTAKE, restake_columns(mach), extra["restake"])
        _write_csv(out / M_P05, ["star_id", "field", "p05", "basis", "pct", "cell_n"], extra["p05"])
        _write_json(out / "counts.json", counts)
        inputs = {f"rank:{n}": _sha(pathlib.Path(rk_dir) / n) for n in RANK_FILES}
        inputs.update({f"repo:{INPUTS}/{n}": _sha(pathlib.Path(repo) / INPUTS / n) for n in SIGNED_FILES})
        inputs[f"repo:{CAL_LABEL}/_invalid_run2/candidates_2026-10.csv"] = \
            _sha(pathlib.Path(repo) / CAL_LABEL / "_invalid_run2" / "candidates_2026-10.csv")
        _write_json(out / "kind.json", {"schema": "sar.r1.rank_tables.v1", "kind": "M", "inputs": inputs})
    _write_json(out / "summary.json", summary)
    (out / "RESULT.txt").write_text(result + "\n", encoding="utf-8")
    for p in problems[:200]:
        print("STOP " + p)
    print(f"RESULT {result} " + " ".join(f"{f}={counts[f]['stars']}" for f in FIELDS))
    return 0 if result == "OK" else 1


def main(argv=None) -> int:
    if os.environ.get("SAR_HOST", "").strip() not in AWS_HOSTS:
        raise SystemExit("R1 rule (design v3 §4): restake_r1.py runs only on an R1 AWS instance ($SAR_HOST)")
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("b0")
    b.add_argument("--cal", required=True)
    b.add_argument("--out", required=True)
    m = sub.add_parser("m")
    for n in ("--rk", "--repo", "--out"):
        m.add_argument(n, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "b0":
        shas = copy_october(a.cal, a.out)
        print(f"RESULT OK B0 {len(shas)} files")
        return 0
    return run_m(a.rk, a.repo, a.out)


if __name__ == "__main__":
    sys.exit(main())
