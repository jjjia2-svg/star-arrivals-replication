#!/usr/bin/env python3
"""R1 rank gate (EC2 only, stdlib): M's own-field ranking is the unedited RK6b code (rk6_requests.py build +
rk6b_rank.py) re-run on pinned inputs, and this script holds its output to the pinned rk6b reference.

  gate     --new DIR --ref DIR --asserts JSON --out DIR
           both runs passed their own gates (RESULT OK; G1_0705, G1_11, GEQ == 0; one flips row per request),
           then ranks_A / ranks_own / ranks_C / flips are content-equal (same key set, every column string-equal
           per key; file byte-equality recorded), then the named asserts hold on the new run.
           RESULT.txt OK | RANK_REPRO_FAIL, exit 1 on fail. A fail STOPs J1a before M is built; the person-level
           list goes to the author (V3-RANK ruling).
  diff     --new DIR --ref DIR --allowed-ids FILE --out DIR
           a re-run after changed paper checks (rk6b-06 vs rk6b-05): every row outside the allowed persons equal at
           4 dp, else RANK_DIFF_STOP.
  collect  --stage DIR... --out DIR
           the rankrepro job's last step: every stage's RESULT.txt is OK; their summary.json files side by side.

Reads only the six named files of a run (never boot.log, which carries the raw bucket name). report.json holds
ids, keys and columns only; summary.json holds counts only.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import re
import sys

AWS_HOSTS = ("ec2-r1-test", "ec2-r1")
CSV_FILES = ("ranks_A.csv", "ranks_own.csv", "ranks_C.csv", "flips.csv")
NAMED_FILES = CSV_FILES + ("summary.json", "RESULT.txt")
GATES = ("G1_0705", "G1_11", "GEQ")
KEY_Y = re.compile(r"\|Y(\d{4})$")
AID = re.compile(r"\bA\d{6,}\b")
REPORT_MAX = 200
TOL = 5e-5


def load_rows(d, name) -> dict:
    """{key: row} of one named csv; the header rides along under '' so compare() can check it."""
    if name not in CSV_FILES:
        raise ValueError(f"{name} is not one of the named rank files")
    with open(pathlib.Path(d) / name, encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh)
        if "key" not in (rd.fieldnames or []):
            raise SystemExit(f"{name}: no key column")
        rows, dup = {}, []
        for r in rd:
            if r["key"] in rows:
                dup.append(r["key"])
            rows[r["key"]] = r
    if dup:
        raise SystemExit(f"{name}: duplicate keys {dup[:5]}")
    rows[""] = list(rd.fieldnames or [])
    return rows


def _ids(key, row) -> set:
    parts = key.split("|")
    out = {row.get("person_id", ""), row.get("author_id", "")}
    if len(parts) > 1:
        out.add(parts[1])
    return out - {""}


def _same(a, b, dp) -> bool:
    if a == b:
        return True
    if dp is None:
        return False
    try:
        return round(float(a), dp) == round(float(b), dp)
    except (TypeError, ValueError):
        return False


def compare(ref, new, name, allowed_ids=frozenset(), dp=None) -> list:
    """Diffs (file, key, column, ref value, new value) between two load_rows() results. A key on one side only is
    (file, key, 'key', 'present'|'missing', 'missing'|'present'). Rows of an allowed person are skipped on both sides.
    dp=None: string equality (the gate); dp=4: numbers equal at 4 dp (the diff after changed paper checks)."""
    out = []
    rh, nh = ref.get("", []), new.get("", [])
    if rh != nh:
        out.append((name, "", "header", ",".join(rh), ",".join(nh)))
    for key in sorted((set(ref) | set(new)) - {""}):
        r, n = ref.get(key), new.get(key)
        if (_ids(key, r or {}) | _ids(key, n or {})) & set(allowed_ids):
            continue
        if r is None or n is None:
            out.append((name, key, "key", "missing" if r is None else "present", "present" if r is None else "missing"))
            continue
        for col in rh:
            if not _same(r.get(col), n.get(col), dp):
                out.append((name, key, col, r.get(col), n.get(col)))
    return out


def check_run(d) -> list:
    """An RK6b run's own verdict: RESULT OK, every gate present and 0, one flips row per request."""
    d = pathlib.Path(d)
    fails = []
    try:
        result = (d / "RESULT.txt").read_text(encoding="utf-8").split()
        summary = json.loads((d / "summary.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [f"{d.name}: unreadable RESULT.txt/summary.json ({type(e).__name__})"]
    if result[:1] != ["OK"] or summary.get("result") != "OK":
        fails.append(f"{d.name}: RESULT {' '.join(result[:1]) or '-'} / summary {summary.get('result')}")
    gates = summary.get("gates") or {}
    for g in GATES:
        if gates.get(g) != 0:
            fails.append(f"{d.name}: gate {g} = {gates.get(g)}")
    try:
        with open(d / "flips.csv", encoding="utf-8", newline="") as fh:
            n = sum(1 for _ in csv.DictReader(fh))
    except OSError:
        n = None
    if n != summary.get("requests"):
        fails.append(f"{d.name}: flips rows {n} != requests {summary.get('requests')}")
    return fails


def _truth(v) -> bool | None:
    return {"True": True, "False": False}.get(v)


def check_named(new_dir, asserts) -> list:
    """Each assert {person_id, field, pass own|C, pct, in, [arrival]}: exactly one flips row for the person in the
    field (joined to the ranks by its key), the pass's pct within 5e-5, its in-flag, and the key's arrival (Y+1)."""
    flips = load_rows(new_dir, "flips.csv")
    ranks = {"own": load_rows(new_dir, "ranks_own.csv"), "C": load_rows(new_dir, "ranks_C.csv")}
    fails = []
    for a in asserts.get("asserts", []):
        pid, field, pas = a["person_id"], a["field"], a["pass"]
        tag = f"{pid} {field} {pas}"
        keys = [k for k, r in flips.items() if k and r["person_id"] == pid and r["field"] == field]
        if len(keys) != 1:
            fails.append(f"{tag}: {len(keys)} rank rows in flips.csv")
            continue
        key, f = keys[0], flips[keys[0]]
        if "arrival" in a and int(KEY_Y.search(key).group(1)) + 1 != int(a["arrival"]):
            fails.append(f"{tag}: arrival {int(KEY_Y.search(key).group(1)) + 1} != {a['arrival']}")
        row = ranks[pas].get(key)
        pct = row.get("pct") if row else None
        if not pct or abs(float(pct) - float(a["pct"])) >= TOL:
            fails.append(f"{tag}: pct {pct or '-'} != {a['pct']}")
        if "in" in a and _truth(f["in_own" if pas == "own" else "in_C"]) is not bool(a["in"]):
            fails.append(f"{tag}: in_{pas} {f['in_own' if pas == 'own' else 'in_C']} != {a['in']}")
    return fails


def _bytes_equal(a, b, name) -> bool:
    return (pathlib.Path(a) / name).read_bytes() == (pathlib.Path(b) / name).read_bytes()


def _write(out, summary, report, result) -> None:
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "report.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "RESULT.txt").write_text(result + "\n", encoding="utf-8")
    print(f"RESULT {result}")


def _cap(lines) -> list:
    """Fail lines (they carry run dir names, ids, gate names and numbers, never a person's name), at most 200."""
    return [str(x) for x in lines][:REPORT_MAX]


def gate(a) -> int:
    asserts = json.loads(pathlib.Path(a.asserts).read_text(encoding="utf-8"))
    if asserts.get("schema") != "sar.r1.rank_named.v1":
        raise SystemExit(f"{a.asserts}: schema {asserts.get('schema')!r} is not sar.r1.rank_named.v1")
    run_fails = [f"new {x}" for x in check_run(a.new)] + [f"ref {x}" for x in check_run(a.ref)]
    summary = {"result": "RANK_REPRO_FAIL", "run_fails": len(run_fails), "diffs": {}, "byte_equal": {}, "named": ""}
    report = {"run_fails": _cap(run_fails), "diffs": [], "named_fails": []}
    if run_fails:
        _write(a.out, summary, report, "RANK_REPRO_FAIL")
        return 1
    diffs = []
    for name in CSV_FILES:
        d = compare(load_rows(a.ref, name), load_rows(a.new, name), name)
        summary["diffs"][name] = len(d)
        summary["byte_equal"][name] = _bytes_equal(a.ref, a.new, name)
        diffs += d
    named = check_named(a.new, asserts)
    n = len(asserts.get("asserts", []))
    summary["named"] = f"{n - len(named)}/{n}"
    report["diffs"] = [list(x[:3]) for x in diffs[:REPORT_MAX]]
    report["named_fails"] = _cap(named)
    result = "OK" if not diffs and not named else "RANK_REPRO_FAIL"
    summary["result"] = result
    _write(a.out, summary, report, result)
    return 0 if result == "OK" else 1


def read_allowed(p) -> frozenset:
    ids = set()
    for line in pathlib.Path(p).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0]
        ids.update(AID.findall(line))
    return frozenset(ids)


def diff(a) -> int:
    allowed = read_allowed(a.allowed_ids)
    run_fails = [f"new {x}" for x in check_run(a.new)] + [f"ref {x}" for x in check_run(a.ref)]
    summary = {"result": "RANK_DIFF_STOP", "allowed": len(allowed), "run_fails": len(run_fails), "diffs": {}, "moved": []}
    report = {"run_fails": _cap(run_fails), "diffs": []}
    if run_fails:
        _write(a.out, summary, report, "RANK_DIFF_STOP")
        return 1
    diffs, moved = [], set()
    for name in CSV_FILES:
        ref, new = load_rows(a.ref, name), load_rows(a.new, name)
        d = compare(ref, new, name, allowed_ids=allowed, dp=4)
        summary["diffs"][name] = len(d)
        diffs += d
        for x in compare(ref, new, name, dp=4):                  # what the allowed persons actually changed
            if not x[1]:                                         # a header diff names no person
                continue
            row = ref.get(x[1]) or new.get(x[1]) or {}
            moved |= _ids(x[1], row) & allowed
    summary["moved"] = sorted(moved)
    report["diffs"] = [list(x[:3]) for x in diffs[:REPORT_MAX]]
    result = "OK" if not diffs else "RANK_DIFF_STOP"
    summary["result"] = result
    _write(a.out, summary, report, result)
    return 0 if result == "OK" else 1


def collect(a) -> int:
    stages, bad = {}, []
    for d in map(pathlib.Path, a.stage):
        try:
            res = (d / "RESULT.txt").read_text(encoding="utf-8").split()[:1]
            stages[d.name] = json.loads((d / "summary.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            res = []
            stages[d.name] = {}
        if res != ["OK"]:
            bad.append(d.name)
    result = "OK" if not bad else "RANKREPRO_FAIL"
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps({"result": result, "not_ok": bad, "stages": stages},
                                                 indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "RESULT.txt").write_text(result + "\n", encoding="utf-8")
    print(f"RESULT {result}")
    return 0 if result == "OK" else 1


def main(argv=None) -> int:
    if os.environ.get("SAR_HOST", "").strip() not in AWS_HOSTS:
        raise SystemExit("R1 rule (design v3 §4): rank_r1.py runs only on an R1 AWS instance ($SAR_HOST)")
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gate")
    for n in ("--new", "--ref", "--asserts", "--out"):
        g.add_argument(n, required=True)
    d = sub.add_parser("diff")
    for n in ("--new", "--ref", "--allowed-ids", "--out"):
        d.add_argument(n, required=True)
    c = sub.add_parser("collect")
    c.add_argument("--stage", action="append", required=True)
    c.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    return {"gate": gate, "diff": diff, "collect": collect}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
