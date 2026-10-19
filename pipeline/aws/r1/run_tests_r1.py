#!/usr/bin/env python3
"""R1 instance-side test runner (job kind 'test'). Standard library only.

The spec is tab-separated, one run per line:   label  commit  expect  pytest_args  baseline
  expect    pass      pytest exited 0
            fail      pytest ran and reported failures (rc 1, >= 1 failure), or collection errors that are all a
                      missing module (rc 2; a SyntaxError is not a red), and every failure is in a selected file
                      (ruling R13)
            record    always ok (a baseline)
            noregress pytest completed (rc 0 or 1), every failing test also failed in the baseline, and it
                      collected at least as many tests as the baseline (ruling R13)
  baseline  '-', '@<label>' (an earlier line of this spec) or a junit xml path
Each line: detached checkout of the commit in --repo, `git clean -fdxq`, then
`<python> -m pytest <args> --junitxml=<out>/<label>.xml`, environment passed through (SAR_HOST
included). rc 5 (no tests collected) and rc 4 (usage, e.g. a missing file) never count as a pass or
as a red fail. Writes <out>/results.json, <out>/summary.json and <out>/RESULT.txt (OK or MISMATCH);
exit 0 iff every line met its expectation. The repo's checkout is restored at the end.
It refuses to run off an R1 instance ($SAR_HOST), and refuses a checkout holding config/r1/local.env:
`git clean -fdxq` on the Mac checkout would delete ignored files (local.env, setup/.venv,
.superpowers/ with the progress ledger, output/).
--overlay DIR (B4, t-big-04): the same clean deletes git-ignored inputs placed in the checkout before the
runner starts (J0's output/cal_intermediates/*.csv, which the big-host tests read), so DIR's tree is copied
into the checkout after every line's clean; a path that still exists after the clean is tracked by git and
is refused (SystemExit), never overwritten.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

EXPECTS = ("pass", "fail", "record", "noregress")
AWS_HOSTS = ("ec2-r1-test", "ec2-r1")


def require_safe_place(repo) -> None:
    if os.environ.get("SAR_HOST", "").strip() not in AWS_HOSTS:
        raise SystemExit("R1 rule (design v3 §4): run_tests_r1.py runs only on an R1 AWS instance ($SAR_HOST)")
    if (pathlib.Path(repo) / "config" / "r1" / "local.env").exists():
        raise SystemExit(f"{repo} holds config/r1/local.env - that is the Mac checkout; refusing to git clean it")


def read_spec(path) -> list:
    rows, labels = [], set()
    for n, line in enumerate(pathlib.Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 5:
            raise SystemExit(f"spec line {n}: want 5 tab-separated fields, got {len(parts)}")
        label, commit, expect, args, baseline = (p.strip() for p in parts)
        if expect not in EXPECTS:
            raise SystemExit(f"spec line {n}: expect must be one of {EXPECTS}, got {expect!r}")
        if expect == "noregress" and baseline == "-":
            raise SystemExit(f"spec line {n}: noregress needs a baseline")
        if baseline.startswith("@") and baseline[1:] not in labels:
            raise SystemExit(f"spec line {n}: baseline {baseline} is not an earlier label")
        if label in labels:
            raise SystemExit(f"spec line {n}: duplicate label {label!r}")
        labels.add(label)
        rows.append({"label": label, "commit": commit, "expect": expect, "args": args, "baseline": baseline})
    if not rows:
        raise SystemExit("empty spec")
    return rows


def junit_failed(path) -> tuple:
    """({id of a failing or erroring test case: its message and text}, number of test cases) from a junit xml."""
    root = ET.parse(path).getroot()
    failed, n = {}, 0
    for tc in root.iter("testcase"):
        n += 1
        e = tc.find("failure")
        e = e if e is not None else tc.find("error")
        if e is not None:
            failed[f"{tc.get('classname', '')}::{tc.get('name', '')}"] = f"{e.get('message', '')}\n{e.text or ''}"
    return failed, n


def junit_skipped_passed(path) -> tuple:
    """(skipped ids, passed ids) from a junit xml."""
    root = ET.parse(path).getroot()
    skipped, passed = set(), set()
    for tc in root.iter("testcase"):
        cid = f"{tc.get('classname', '')}::{tc.get('name', '')}"
        if tc.find("skipped") is not None:
            skipped.add(cid)
        elif tc.find("failure") is None and tc.find("error") is None:
            passed.add(cid)
    return skipped, passed


def _selected(args) -> list:
    """The paths a pytest argument string selects: tokens that are not flags or a flag's value (-m, -k, -p)."""
    out, skip = [], False
    for t in shlex.split(args):
        if skip:
            skip = False
            continue
        if t in ("-m", "-k", "-p"):
            skip = True
            continue
        if not t.startswith("-"):
            t = t.split("::", 1)[0]
            out.append((t[2:] if t.startswith("./") else t).rstrip("/"))
    return out


def _module(case_id) -> str:
    """A junit case id 'tests.test_x::name' (or '::tests.test_x' for a collection error) as 'tests/test_x.py'."""
    cls, _, name = case_id.partition("::")
    parts = (cls or name).split(".")
    for i, p in enumerate(parts):
        if p.startswith("test_"):                      # 'tests' (a folder) is not the module
            return "/".join(parts[:i + 1]) + ".py"
    return "/".join(parts) + ".py"


def judge(expect, rc, failed, baseline_failed, *, selected=(), n=0, base_n=0, skipped_now=(), base_passed=()) -> tuple:
    ids = set(failed)
    texts = list(failed.values()) if isinstance(failed, dict) else []
    if expect == "record":
        return True, f"recorded (rc {rc}, {len(ids)} failing)"
    if rc == 5:
        return False, "no tests collected (rc 5)"
    if expect == "pass":
        return rc == 0, ("passed" if rc == 0 else f"expected a pass, got rc {rc} with {len(ids)} failing")
    if expect == "fail":
        if rc not in (1, 2) or not ids:
            return False, f"expected test failures, got rc {rc} with {len(ids)} failing"
        if rc == 2 and (any("SyntaxError" in t for t in texts)
                        or not all(("ModuleNotFoundError" in t or "ImportError" in t) for t in texts)):
            return False, "collection error is not a missing module (SyntaxError or another error)"
        sel = list(selected)
        if sel:
            outside = sorted({_module(i) for i in ids
                              if not any(_module(i) == s or _module(i).startswith(s + "/") for s in sel)})
            if outside:
                return False, f"failures outside the selected files: {outside[:5]}"
        return True, "failed, as a red run should"
    if rc not in (0, 1):
        return False, f"pytest did not complete (rc {rc})"
    new = sorted(ids - set(baseline_failed))
    if new:
        return False, f"{len(new)} new failures: {new[:10]}"
    if n < base_n:
        return False, f"collected {n} < baseline {base_n}"
    gone = sorted(set(skipped_now) & set(base_passed))
    if gone:
        return False, f"{len(gone)} skipped now that passed in the baseline: {gone[:10]}"
    return True, "no new failures"


def git(repo, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def checkout(repo, commit) -> None:
    git(repo, "-c", "advice.detachedHead=false", "checkout", "-q", "--detach", commit)
    git(repo, "clean", "-fdxq")


def lay_overlay(overlay, repo) -> int:
    """Copy every file under `overlay` to the same relative path in the freshly cleaned checkout."""
    n = 0
    for src in sorted(p for p in pathlib.Path(overlay).rglob("*") if p.is_file()):
        rel = src.relative_to(overlay)
        dst = pathlib.Path(repo) / rel
        if dst.exists() or dst.is_symlink():
            raise SystemExit(f"--overlay {rel}: the path is tracked in the checkout; refusing to overwrite it")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        n += 1
    return n


def run_line(row, repo, out, python, overlay=None) -> dict:
    checkout(repo, row["commit"])
    n_overlay = lay_overlay(overlay, repo) if overlay is not None else 0
    junit = out / f"{row['label']}.xml"
    t0 = time.time()
    with open(out / f"{row['label']}.log", "w", encoding="utf-8") as log:
        rc = subprocess.run([python, "-m", "pytest", *shlex.split(row["args"]), f"--junitxml={junit}"],
                            cwd=repo, stdout=log, stderr=subprocess.STDOUT).returncode
    failed, n = junit_failed(junit) if junit.is_file() else ({}, 0)
    skipped, passed = junit_skipped_passed(junit) if junit.is_file() else (set(), set())
    return {"rc": rc, "failed": failed, "n_tests": n, "skipped": skipped, "passed": passed, "secs": round(time.time() - t0),
            "overlay_files": n_overlay}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 instance-side test runner")
    ap.add_argument("--spec", required=True, type=pathlib.Path)
    ap.add_argument("--repo", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--overlay", type=pathlib.Path, help="a tree copied into the checkout after every clean")
    a = ap.parse_args(argv)
    require_safe_place(a.repo)
    if a.overlay is not None and not a.overlay.is_dir():
        raise SystemExit(f"--overlay {a.overlay} is not a directory")
    rows = read_spec(a.spec)
    a.out.mkdir(parents=True, exist_ok=True)
    head = git(a.repo, "rev-parse", "HEAD")
    seen, results = {}, []
    try:
        for row in rows:
            r = run_line(row, a.repo, a.out, a.python, overlay=a.overlay)
            base, base_n, base_passed = set(), 0, set()
            if row["expect"] == "noregress":
                b = row["baseline"]
                if b.startswith("@"):
                    base, base_n, base_passed = set(seen[b[1:]]["failed"]), seen[b[1:]]["n_tests"], seen[b[1:]]["passed"]
                else:
                    bf, base_n = junit_failed(pathlib.Path(b))
                    base, base_passed = set(bf), junit_skipped_passed(pathlib.Path(b))[1]
            ok, why = judge(row["expect"], r["rc"], r["failed"], base, selected=_selected(row["args"]),
                            n=r["n_tests"], base_n=base_n, skipped_now=r["skipped"], base_passed=base_passed)
            seen[row["label"]] = r
            results.append({**row, "rc": r["rc"], "ok": ok, "why": why, "n_tests": r["n_tests"],
                            "n_failed": len(r["failed"]), "n_skipped": len(r["skipped"]),
                            "skipped": sorted(r["skipped"])[:200], "secs": r["secs"],
                            "overlay_files": r["overlay_files"]})
            print(f"{row['label']:<8} {row['expect']:<9} rc={r['rc']} ok={ok} {why}", flush=True)
    finally:
        checkout(a.repo, head)
    (a.out / "results.json").write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    ok = all(x["ok"] for x in results)
    (a.out / "RESULT.txt").write_text("OK\n" if ok else "MISMATCH\n", encoding="utf-8")
    (a.out / "summary.json").write_text(json.dumps({"lines": len(results), "ok": sum(x["ok"] for x in results),
                                                    "result": "OK" if ok else "MISMATCH"}) + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
