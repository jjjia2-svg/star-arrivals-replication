#!/usr/bin/env python3
"""R1 gate 1 (F23), the J1a gate-1 link and cell custody. The CLI runs on an R1 instance only; the
comparators are a library importable anywhere.

  gates.py gate1 --cells-reports DIR... --jp /work/jp --ref /work/ref/october --rules config/r1/gate1_rules.tsv
                 --tsv config/r1/base_inputs.tsv --frames-manifest $WORK/prod/frames/MANIFEST.sha256
                 --sandbox $WORK/prod/sandbox_check/sandbox_check.json --repo $REPO_DIR --out $STAGE_OUT
  gates.py link --j0 /work/j0 --chain config/r1/chain.json --repo $REPO_DIR --commit $COMMIT --out $STAGE_OUT
  gates.py custody --cells TSV... --reports DIR... --manifest FILE --out $STAGE_OUT

gate1 (B0 only; M has no gold compare: F12 = no, M_rerun = no) PASSes only if all of these hold:
  1. cells   every gold in <ref>/analysis/expected has a B0 cell output that is compare_json-EQUAL (no
             tolerance) to its base. The base is October's gold when JP's own cells reports (its pulled
             stage set) are all EQUAL ('exact'), else JP's EC2 JSON ('ec2', ruling h1); the data layer
             stays exact against October either way;
  2. data    every product row of base_inputs.tsv meets the first matching gate1_rules.tsv rule against
             its reference copy (byte / H1 <= 8 ULP / econ characterise_frame / parquet content /
             json_except; record = sha listed only; not_rebuilt); a product with no rule STOPs;
  3. custody every cell's recorded input frame sha256 (run_cells 'inputs') equals the frames MANIFEST,
             every such frame is listed, and the MANIFEST describes the frames beside it;
  4. sandbox the sandbox check verdict is OK with nothing rewritten and no non-allowlisted read.
It writes gate_report_1.json (name-free, through run_stages.name_free: codes, counts, labels, paths)
and details_1.json (free text; stays in the stage files), and exits 1 on FAIL.

link (J1a's gate1_link): J0's summary result OK, its gate_report_1 verdict PASS, and either J0's commit
is $COMMIT or `git diff --name-only <j0>..$COMMIT` touches none of chain.json's b0_chain_paths (nor
chain.json itself); else exit 1 naming the paths. custody: the check of step 3 for a list of cells
TSVs (J1a's M cells), where every listed cell must be present.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import importlib
import json
import os
import pathlib
import re
import struct
import subprocess
import sys
import time

HOSTS = ("ec2-r1-test", "ec2-r1")
HERE = pathlib.Path(__file__).resolve().parent
RULE_KINDS = ("byte", "h1", "h1_econ", "content", "json_except", "record", "not_rebuilt")
NEEDS_ARG = ("h1", "json_except")
NEEDS_REASON = ("record", "not_rebuilt")          # these skip the comparison, so they must say why (> 20 chars)
RULE_HEADER = ["pattern", "rule", "arg", "reason"]
#: JP's two cell stages; their pulled stage set lies at <jp>/<stage>/files/work/prod/<stage>/
JP_STAGES = ("cells_rmac", "cells_rcloud")
H1_MAX_ULP = 8
ECON_PASS = ("BYTE_EQUAL", "EQUAL_MODULO_Y_SWAPPED_BY_04")
PRODUCT_CODES = {"NO_RULE": "NO_RULE", "STOP": "PRODUCT_STOP", "MISSING": "PRODUCT_MISSING",
                 "REF_MISSING": "REF_MISSING", "ERROR": "RULE_ERROR"}
CELL_CODES = {"DIFF": "CELL_DIFF", "MISSING": "CELL_MISSING", "DUPLICATE": "CELL_DUPLICATE", "NO_BASE": "CELL_NO_BASE"}
MANIFEST_LINE = re.compile(r"^([0-9a-f]{64})\s+\*?(\S.*)$")


class GateError(RuntimeError):
    """An input the gate cannot read the way it must (a bad rules table, a bad MANIFEST line, ...)."""


# ---------------------------------------------------------------------------------------------
# where the code lives: this file's own checkout, or $REPO_DIR when run_stages copied it to $WORK
# ---------------------------------------------------------------------------------------------

def _code_repo() -> pathlib.Path:
    cands = list(HERE.parents) + ([pathlib.Path(os.environ["REPO_DIR"])] if os.environ.get("REPO_DIR") else [])
    for c in cands:
        if (c / "analysis" / "lib" / "compare_json.py").is_file() and (c / "pipeline" / "aws" / "r1").is_dir():
            return c
    raise GateError("cannot find the repo checkout that holds the comparators (set $REPO_DIR)")


def _on_path(p) -> None:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _import(dotted: str):
    _on_path(_code_repo())
    return importlib.import_module(dotted)


def _sibling(name: str):
    """A module of pipeline/aws/r1, from this file's directory or $REPO_DIR/pipeline/aws/r1."""
    dirs = [HERE] + ([pathlib.Path(os.environ["REPO_DIR"]) / "pipeline" / "aws" / "r1"] if os.environ.get("REPO_DIR") else [])
    for d in dirs:
        if (d / f"{name}.py").is_file():
            _on_path(d)
            return importlib.import_module(name)
    raise GateError(f"{name}.py not found next to gates.py or under $REPO_DIR/pipeline/aws/r1")


def name_free(obj):
    return _sibling("run_stages").name_free(obj)


def _econ920_lib():
    _on_path(_code_repo() / "pipeline" / "frames" / "cal2026-10" / "econ920")
    return importlib.import_module("econ920_lib")


# ---------------------------------------------------------------------------------------------
# comparators (October's own rules)
# ---------------------------------------------------------------------------------------------

def ulps(x: float, y: float) -> int:
    """frames_stage.ulps: the two doubles' bit patterns as signed 64-bit integers, absolute difference."""
    a, b = (struct.unpack("<q", struct.pack("<d", v))[0] for v in (x, y))
    return abs(a - b)


def sha256_file(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rule_byte(ref, new) -> dict:
    a, b = sha256_file(ref), sha256_file(new)
    return {"ok": a == b, "sha256_ref": a, "sha256_new": b}


def rule_h1_lines(ref, new, allowed_cols, max_ulp: int = H1_MAX_ULP) -> dict:
    """The H1 characterisation (analysis/robustness/sensitivity/run_nocentre.py characterise,
    run_cal_frames.union_characterise): the same line count and header, differences only in
    `allowed_cols`, each within `max_ulp`. A line whose field count differs is a difference outside
    the allowed columns."""
    allowed = tuple(allowed_cols)
    with open(ref, newline="", encoding="utf-8") as fh:
        fa = fh.readlines()
    with open(new, newline="", encoding="utf-8") as fh:
        fb = fh.readlines()
    if len(fa) != len(fb):
        return {"ok": False, "reason": f"line counts differ {len(fa)} vs {len(fb)}", "worst_ulp": None}
    if not fa:
        return {"ok": True, "differing_lines": 0, "of": 0, "worst_ulp": 0, "unexpected_columns": []}
    if fa[0] != fb[0]:
        return {"ok": False, "reason": "header differs", "worst_ulp": None}
    cols = next(csv.reader([fa[0]]))
    n, worst, badcols = 0, 0, set()
    for a, b in zip(fa[1:], fb[1:]):
        if a == b:
            continue
        n += 1
        ca, cb = next(csv.reader([a])), next(csv.reader([b]))
        if len(ca) != len(cols) or len(cb) != len(cols):
            badcols.add("<field count>")
            continue
        for j, (x, y) in enumerate(zip(ca, cb)):
            if x != y:
                if cols[j] not in allowed:
                    badcols.add(cols[j])
                else:
                    try:
                        worst = max(worst, ulps(float(x), float(y)))
                    except ValueError:
                        badcols.add(cols[j])
    return {"ok": not badcols and worst <= max_ulp, "differing_lines": n, "of": len(fa) - 1, "worst_ulp": worst,
            "unexpected_columns": sorted(badcols)}


def _frame_lines(p) -> list[str]:
    """A frame's non-empty lines with every \\r removed: frames_stage.read_frame_rows' own reading."""
    return [ln.replace("\r", "") for ln in pathlib.Path(p).read_bytes().decode("utf-8").split("\n") if ln]


def rule_h1_econ(ref, new) -> dict:
    """The H1 preconditions first - the same header line and the same line count, read as read_frame_rows
    reads them - then econ920_lib.characterise_frame (loaded on first use): PASS on BYTE_EQUAL or
    EQUAL_MODULO_Y_SWAPPED_BY_04, STOP on NOT_EQUAL. characterise_frame compares only the reference's
    columns, keyed, so without the preconditions an added column passed (J0 review #3, 2026-10-16)."""
    la, lb = _frame_lines(ref), _frame_lines(new)
    if la[:1] != lb[:1]:
        return {"ok": False, "verdict": "NOT_EQUAL", "reason": "header differs", "worst_ulp": None}
    if len(la) != len(lb):
        return {"ok": False, "verdict": "NOT_EQUAL", "reason": f"line counts differ {len(la)} vs {len(lb)}",
                "worst_ulp": None}
    c = _econ920_lib().characterise_frame(pathlib.Path(ref), pathlib.Path(new))
    return {"ok": c["verdict"] in ECON_PASS, "verdict": c["verdict"],
            "worst_ulp": max(c.get("worst_ulp_by_column", {}).values(), default=0), "detail": c}


def rule_content(ref, new) -> dict:
    """tools.content_equal.content_equal: parquet by content (row order is not a verdict), else bytes."""
    r = _import("tools.content_equal").content_equal(ref, new)
    return {"ok": bool(r.equal), "mode": r.mode, "rows_ref": r.rows_a, "rows_new": r.rows_b, "detail": r.detail}


def _canon(v) -> str:
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


def rule_json_except(ref, new, keys) -> dict:
    """Every top-level key of the reference except `keys` must be present in `new` with an identical
    value (types included: 11 is not 11.0). Keys only `new` has are listed, not judged: the October
    report predates them."""
    a = json.loads(pathlib.Path(ref).read_text(encoding="utf-8"))
    b = json.loads(pathlib.Path(new).read_text(encoding="utf-8"))
    if not isinstance(a, dict) or not isinstance(b, dict):
        return {"ok": _canon(a) == _canon(b), "changed": [] if _canon(a) == _canon(b) else ["<root>"]}
    skip = set(keys)
    changed = sorted(k for k in a if k not in skip and (k not in b or _canon(a[k]) != _canon(b[k])))
    return {"ok": not changed, "changed": changed, "ignored": sorted(skip & set(a)), "extra_in_new": sorted(set(b) - set(a))}


def compare_cells(golds, est_dirs, base_dirs) -> tuple[dict, dict]:
    """Each gold name -> EQUAL | DIFF | MISSING (no cell output) | DUPLICATE (two outputs) | NO_BASE.
    The output is <est_dir>/estimates/<name>; the base is the first <base_dir>/<name>. The comparison
    is analysis.lib.compare_json (no tolerance; `secs` and `file` ignored)."""
    cj = _import("analysis.lib.compare_json")
    status, details = {}, {}
    for name in golds:
        hits = [pathlib.Path(d) / "estimates" / name for d in est_dirs if (pathlib.Path(d) / "estimates" / name).is_file()]
        bases = [pathlib.Path(d) / name for d in base_dirs if (pathlib.Path(d) / name).is_file()]
        if not hits:
            status[name] = "MISSING"
        elif len(hits) > 1:
            status[name] = "DUPLICATE"
        elif not bases:
            status[name] = "NO_BASE"
        else:
            diffs = cj.compare(json.loads(hits[0].read_text(encoding="utf-8")), json.loads(bases[0].read_text(encoding="utf-8")))
            status[name] = "DIFF" if diffs else "EQUAL"
            if diffs:
                details[name] = [str(d)[:300] for d in diffs[:5]]
    return status, details


# ---------------------------------------------------------------------------------------------
# the rules table and the products
# ---------------------------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Rule:
    pattern: str
    rule: str
    arg: str
    reason: str
    rx: re.Pattern


def _glob_rx(pattern: str) -> re.Pattern:
    """'**/' = any number of directories (also none), '**' = anything, '*' and '?' stay in one segment."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def load_rules(path) -> list[Rule]:
    """gate1_rules.tsv: TAB columns pattern, rule, arg ('-' when none), reason; '#' lines are comments."""
    lines = [ln.rstrip("\n").rstrip("\r") for ln in pathlib.Path(path).read_text(encoding="utf-8").splitlines()]
    lines = [ln for ln in lines if ln.strip() and not ln.startswith("#")]
    if not lines or lines[0].split("\t") != RULE_HEADER:
        raise ValueError(f"{path}: header must be {RULE_HEADER}")
    rules, seen = [], set()
    for n, ln in enumerate(lines[1:], 2):
        f = ln.split("\t")
        if len(f) != 4:
            raise ValueError(f"{path} row {n}: {len(f)} fields, want 4")
        pattern, kind, arg, reason = (x.strip() for x in f)
        if kind not in RULE_KINDS:
            raise ValueError(f"{path} row {n}: unknown rule {kind!r}")
        if (kind in NEEDS_ARG) == (arg == "-"):
            raise ValueError(f"{path} row {n}: rule {kind} {'needs' if kind in NEEDS_ARG else 'takes no'} arg")
        if not reason or (kind in NEEDS_REASON and len(reason) <= 20):
            raise ValueError(f"{path} row {n}: rule {kind} needs a reason of more than 20 characters")
        if pattern in seen or pattern.startswith("/") or ".." in pattern.split("/"):
            raise ValueError(f"{path} row {n}: duplicate or unsafe pattern {pattern!r}")
        seen.add(pattern)
        rules.append(Rule(pattern, kind, arg, reason, _glob_rx(pattern)))
    return rules


def match_rule(rules, path: str):
    return next((r for r in rules if r.rx.match(path)), None)


def read_products(tsv) -> list[str]:
    """The product rows (class 'product') of config/r1/base_inputs.tsv (F2)."""
    lines = pathlib.Path(tsv).read_text(encoding="utf-8").splitlines()
    hdr = lines[0].split("\t") if lines else []
    if "path" not in hdr or "class" not in hdr:
        raise GateError(f"{tsv}: no path/class header")
    ip, ic = hdr.index("path"), hdr.index("class")
    out = []
    for ln in lines[1:]:
        f = ln.split("\t")
        if len(f) > max(ip, ic) and f[ic] == "product":
            if f[ip].startswith("/") or ".." in f[ip].split("/"):
                raise GateError(f"{tsv}: unsafe product path {f[ip]!r}")
            out.append(f[ip])
    return out


def _apply(rule: Rule, ref: pathlib.Path, new: pathlib.Path) -> dict:
    if rule.rule == "byte":
        return rule_byte(ref, new)
    if rule.rule == "h1":
        return rule_h1_lines(ref, new, rule.arg.split(","))
    if rule.rule == "h1_econ":
        return rule_h1_econ(ref, new)
    if rule.rule == "content":
        return rule_content(ref, new)
    return rule_json_except(ref, new, rule.arg.split(","))


def check_products(products, rules, *, repo, ref) -> tuple[list, list]:
    """One row per product: PASS | STOP | MISSING (not rebuilt) | REF_MISSING | NO_RULE | ERROR, or
    RECORD / NOT_REBUILT for the rows that skip the comparison. Returns (rows, sorted codes)."""
    repo, ref = pathlib.Path(repo), pathlib.Path(ref)
    rows, codes = [], set()
    for path in products:
        rule = match_rule(rules, path)
        row = {"path": path, "rule": rule.rule if rule else None}
        new, old = repo / path, ref / path
        if rule is None:
            row["status"] = "NO_RULE"
        elif rule.rule == "not_rebuilt":
            row["status"] = "NOT_REBUILT"
        elif rule.rule == "record":
            row["status"] = "RECORD"
            row["detail"] = {"sha256_new": sha256_file(new) if new.is_file() else None,
                             "sha256_ref": sha256_file(old) if old.is_file() else None}
        elif not old.is_file():
            row["status"] = "REF_MISSING"
        elif not new.is_file():
            row["status"] = "MISSING"
        else:
            try:
                res = _apply(rule, old, new)
                row["status"] = "PASS" if res["ok"] else "STOP"
                if res.get("worst_ulp") is not None:
                    row["worst_ulp"] = res["worst_ulp"]
                row["detail"] = res
            except Exception as e:              # noqa: BLE001 - a comparison that cannot be made is a STOP
                row["status"], row["detail"] = "ERROR", f"{type(e).__name__}: {e}"[:500]
        if row["status"] in PRODUCT_CODES:
            codes.add(PRODUCT_CODES[row["status"]])
        rows.append(row)
    return rows, sorted(codes)


# ---------------------------------------------------------------------------------------------
# cells: golds, JP parity, custody, sandbox
# ---------------------------------------------------------------------------------------------

def golds_of(ref) -> list[str]:
    d = pathlib.Path(ref) / "analysis" / "expected"
    return sorted(p.name for p in d.glob("*.json")) if d.is_dir() else []


def parity_mode(jp, golds, ref) -> tuple:
    """(mode, base dirs, JP rows, codes) from JP's pulled cells stages: 'exact' when every JP cell is
    EQUAL and JP produced every gold, so the base is October's gold; 'ec2' otherwise, with JP's own
    EC2 estimates as the base (ruling h1)."""
    reports, est = {}, []
    for st in JP_STAGES:
        d = pathlib.Path(jp) / st / "files" / "work" / "prod" / st
        for p in sorted(d.glob("cells_report_*.json")):
            reports.update(json.loads(p.read_text(encoding="utf-8")))
        if (d / "estimates").is_dir():
            est.append(d / "estimates")
    if not reports:
        return None, [], [], ["JP_MISSING"]
    rows = [{"label": lab, "status": (e or {}).get("status")} for lab, e in sorted(reports.items())]
    have = {p.name for d in est for p in d.glob("*.json")}
    if all(r["status"] == "EQUAL" for r in rows) and set(golds) <= have:
        return "exact", [pathlib.Path(ref) / "analysis" / "expected"], rows, []
    return "ec2", est, rows, []


def cell_reports(dirs) -> list[tuple[str, str, dict]]:
    """(stack, label, entry) for every cells_report_<stack>.json in the given dirs."""
    out = []
    for d in dirs:
        for p in sorted(pathlib.Path(d).glob("cells_report_*.json")):
            stack = p.stem[len("cells_report_"):]
            for lab, e in json.loads(p.read_text(encoding="utf-8")).items():
                out.append((stack, lab, e if isinstance(e, dict) else {}))
    return out


def read_manifest(path) -> dict[str, str]:
    """MANIFEST.sha256 rows '<sha256>  <repo path>' -> {file name: sha256}."""
    out = {}
    for n, ln in enumerate(pathlib.Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not ln.strip():
            continue
        m = MANIFEST_LINE.match(ln)
        if not m:
            raise GateError(f"{path} line {n}: not a sha256 MANIFEST row")
        name = pathlib.PurePosixPath(m.group(2).strip()).name
        if name in out:
            raise GateError(f"{path}: two rows for {name}")
        out[name] = m.group(1)
    return out


def custody_rows(entries, manifest) -> tuple[list, list]:
    """entries: (label, frame the cell must have read or None, run_cells report entry or None).
    Every MANIFEST row must describe the file beside it; every cell's recorded input frame must be
    listed with the same sha256. Returns (rows, sorted codes)."""
    manifest = pathlib.Path(manifest)
    if not manifest.is_file():
        return [{"label": None, "path": manifest.name, "status": "MANIFEST_MISSING"}], ["MANIFEST_MISSING"]
    man = read_manifest(manifest)
    rows, codes = [], set()
    for name, sha in sorted(man.items()):
        f = manifest.parent / name
        if not f.is_file() or sha256_file(f) != sha:
            rows.append({"label": None, "path": name, "status": "MANIFEST_STALE"})
            codes.add("MANIFEST_STALE")
    for label, want, entry in entries:
        name = None
        if entry is None:
            st = "NO_CELL"
        elif not isinstance(entry.get("inputs"), dict) or not isinstance(entry["inputs"].get("frame"), dict):
            st = "NO_INPUTS"
        else:
            fr = entry["inputs"]["frame"]
            name = pathlib.PurePosixPath(str(fr.get("name") or "")).name
            if want is not None and name != pathlib.PurePosixPath(want).name:
                st = "WRONG_FRAME"
            elif name not in man:
                st = "UNLISTED"
            elif fr.get("sha256") != man[name]:
                st = "SHA"
            else:
                st = "OK"
        rows.append({"label": label, "path": name, "status": st})
        if st != "OK":
            codes.add(f"CUSTODY_{st}")
    return rows, sorted(codes)


def sandbox_codes(path) -> list[str]:
    p = pathlib.Path(path)
    if not p.is_file():
        return ["SANDBOX_MISSING"]
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return ["SANDBOX_UNREADABLE"]
    v, codes = s.get("verdict"), []
    if v != "OK":
        codes.append(f"SANDBOX_{v}" if isinstance(v, str) and re.fullmatch(r"[A-Z_]{1,40}", v) else "SANDBOX_BAD_VERDICT")
    if s.get("rewritten"):
        codes.append("SANDBOX_REWRITTEN")
    if s.get("gread"):
        codes.append("SANDBOX_GREAD")
    return codes


def _write(out: pathlib.Path, tag: str, report: dict, details: dict) -> None:
    """gate_report_<tag>.json (name-free: it reaches summary.json) and details_<tag>.json (free text,
    stays in the stage files on S3)."""
    out.mkdir(parents=True, exist_ok=True)
    (out / f"gate_report_{tag}.json").write_text(json.dumps(name_free(report), indent=1, sort_keys=True) + "\n",
                                                 encoding="utf-8")
    (out / f"details_{tag}.json").write_text(json.dumps(details, indent=1, sort_keys=True, default=str) + "\n",
                                             encoding="utf-8")


def gate1(*, cells_reports, jp, ref, rules, tsv, frames_manifest, sandbox, repo, out) -> dict:
    """Gate 1 without the host / config checks (main does those). Writes the reports; returns the report."""
    t0 = time.time()
    out, ref = pathlib.Path(out), pathlib.Path(ref)
    codes = set()
    golds = golds_of(ref)
    if not golds:
        codes.add("NO_GOLDS")
    mode, bases, rows_jp, c = parity_mode(jp, golds, ref)
    codes.update(c)
    cstat, cdet = compare_cells(golds, cells_reports, bases) if mode else ({g: "NO_BASE" for g in golds}, {})
    codes.update(CELL_CODES[s] for s in cstat.values() if s != "EQUAL")
    entries = cell_reports(cells_reports)
    if not entries:
        codes.add("CELLS_REPORT_MISSING")
    failed = sorted(lab for _st, lab, e in entries if e.get("status") == "FAIL")
    if failed:
        codes.add("CELL_FAIL")
    prows, pcodes = check_products(read_products(tsv), load_rules(rules), repo=repo, ref=ref)
    codes.update(pcodes)
    krows, kcodes = custody_rows([(lab, None, e) for _st, lab, e in entries], frames_manifest)
    codes.update(kcodes)
    codes.update(sandbox_codes(sandbox))
    count = lambda st: sum(r["status"] == st for r in prows)    # noqa: E731
    report = {
        "gate": "gate1", "verdict": "FAIL" if codes else "PASS", "mode": mode or "none", "codes": sorted(codes),
        "counts": {"n_golds": len(golds), "n_cells_equal": sum(s == "EQUAL" for s in cstat.values()),
                   "n_cells_reported": len(entries), "n_products": len(prows), "n_products_pass": count("PASS"),
                   "n_products_record": count("RECORD"), "n_products_not_rebuilt": count("NOT_REBUILT")},
        "rows_cells": [{"label": g, "status": s} for g, s in sorted(cstat.items()) if s != "EQUAL"]
                      + [{"label": lab, "status": "FAIL"} for lab in failed],
        "rows_jp": [r for r in rows_jp if r["status"] != "EQUAL"],
        "rows_products": [{k: r[k] for k in ("path", "rule", "status", "worst_ulp") if k in r}
                          for r in prows if r["status"] in PRODUCT_CODES],
        "rows_custody": [r for r in krows if r["status"] != "OK"],
        "secs": round(time.time() - t0, 1)}
    details = {"cells": cdet, "jp": rows_jp, "products": prows, "custody": krows,
               "bases": [str(b) for b in bases], "sandbox": str(sandbox)}
    _write(out, "1", report, details)
    return report


# ---------------------------------------------------------------------------------------------
# custody (J1a's M cells) and the J1a link
# ---------------------------------------------------------------------------------------------

def custody_main(*, cells, reports, manifest, out) -> int:
    idx: dict[tuple, list] = {}
    for st, lab, e in cell_reports(reports):
        idx.setdefault((st, lab), []).append(e)
    entries = []
    for tsv in cells:
        with open(tsv, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh, delimiter="\t"):
                hits = idx.get((r["stack"], r["label"]), [])
                entries.append((r["label"], r["frame"], hits[0] if len(hits) == 1 else None))
    rows, codes = custody_rows(entries, manifest)
    report = {"gate": "custody", "verdict": "FAIL" if codes else "PASS", "codes": codes,
              "counts": {"n_cells": len(entries), "n_ok": sum(r["status"] == "OK" for r in rows)},
              "rows_custody": [r for r in rows if r["status"] != "OK"]}
    _write(pathlib.Path(out), "custody", report, {"custody": rows, "manifest": str(manifest)})
    return 1 if codes else 0


def _under(path: str, bases) -> bool:
    return any(path == b.rstrip("/") or path.startswith(b.rstrip("/") + "/") for b in bases)


def link(*, j0, chain, repo, commit, out) -> int:
    codes, changed, details = set(), [], {}
    sp = pathlib.Path(j0) / "summary.json"
    s = json.loads(sp.read_text(encoding="utf-8")) if sp.is_file() else {}
    if not s:
        codes.add("J0_SUMMARY_MISSING")
    if s.get("result") != "OK":
        codes.add("J0_NOT_OK")
    verdicts = [rep.get("verdict") for st in (s.get("reports") or {}).values() if isinstance(st, dict)
                for name, rep in st.items() if name == "gate_report_1.json" and isinstance(rep, dict)]
    if verdicts != ["PASS"]:
        codes.add("GATE1_NOT_PASS")
    paths = json.loads(pathlib.Path(chain).read_text(encoding="utf-8")).get("b0_chain_paths")
    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p for p in paths):
        codes.add("CHAIN_BAD")
        paths = []
    try:                                         # chain.json itself defines the B0 steps
        paths = [*paths, pathlib.Path(chain).resolve().relative_to(pathlib.Path(repo).resolve()).as_posix()]
    except ValueError:
        pass
    j0c = s.get("commit")
    details.update(j0_commit=j0c, b0_chain_paths=paths)
    if not isinstance(j0c, str) or not re.fullmatch(r"[0-9a-f]{7,40}", j0c):
        codes.add("J0_NO_COMMIT")
    elif j0c != commit:
        r = subprocess.run(["git", "-C", str(repo), "diff", "--name-only", f"{j0c}..{commit}"], capture_output=True, text=True)
        if r.returncode != 0:
            codes.add("GIT_DIFF_FAILED")
            details["git"] = r.stderr.strip()[:300]
        else:
            changed = sorted(p for p in r.stdout.splitlines() if p and _under(p, paths))
            if changed:
                codes.add("B0_CHAIN_CHANGED")
    report = {"gate": "gate1_link", "verdict": "FAIL" if codes else "PASS", "codes": sorted(codes), "changed": changed,
              "commit": commit}
    _write(pathlib.Path(out), "link", report, details)
    for p in changed:
        print(f"B0-chain path changed since J0: {p}")
    return 1 if codes else 0


# ---------------------------------------------------------------------------------------------

def _config_name() -> str:
    return _import("pipeline.lib.r1_config").load_env().name


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 gate 1, the J1a link and cell custody")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gate1")
    g.add_argument("--cells-reports", nargs="+", required=True)
    for k in ("--jp", "--ref", "--rules", "--tsv", "--frames-manifest", "--sandbox", "--repo", "--out"):
        g.add_argument(k, required=True)
    lk = sub.add_parser("link")
    for k in ("--j0", "--chain", "--repo", "--commit", "--out"):
        lk.add_argument(k, required=True)
    cu = sub.add_parser("custody")
    cu.add_argument("--cells", nargs="+", required=True)
    cu.add_argument("--reports", nargs="+", required=True)
    for k in ("--manifest", "--out"):
        cu.add_argument(k, required=True)
    a = ap.parse_args(argv)
    if os.environ.get("SAR_HOST", "").strip() not in HOSTS:
        raise SystemExit("R1 rule: gates.py runs only on an R1 instance ($SAR_HOST)")
    if a.cmd == "link":
        return link(j0=a.j0, chain=a.chain, repo=a.repo, commit=a.commit, out=a.out)
    if a.cmd == "custody":
        return custody_main(cells=a.cells, reports=a.reports, manifest=a.manifest, out=a.out)
    try:
        name = _config_name()
    except Exception as e:                      # noqa: BLE001 - no loadable config is no B0
        raise SystemExit(f"gate 1 is B0-only and needs a loadable B0 run config ($SAR_R1_CONFIG): "
                         f"{getattr(e, 'code', None) or type(e).__name__}") from None
    if name != "B0":
        raise SystemExit(f"gate 1 is B0-only (config {name}): M has no gold compare (F12 = no, M_rerun = no)")
    rep = gate1(cells_reports=a.cells_reports, jp=a.jp, ref=a.ref, rules=a.rules, tsv=a.tsv,
                frames_manifest=a.frames_manifest, sandbox=a.sandbox, repo=a.repo, out=a.out)
    print(f"gate1 {rep['verdict']} mode={rep['mode']} codes={','.join(rep['codes']) or '-'}")
    return 0 if rep["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
