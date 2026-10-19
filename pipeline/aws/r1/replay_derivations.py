#!/usr/bin/env python3
"""R1 derivation replay, instance side (job kind 'recder', plan V3-REC): re-run the 10-02 heredoc derivations.

On 10-02 the RK4/RK5 inputs and the census numbers were made by inline `python3 - "$K" … <<'EOF'` heredocs
(history T:2348 … T:4980), never saved as files. config/r1/derivations.json lists those lines and
config/r1/derivations/T0NNNN.py holds each heredoc body as reviewed (sha-pinned, never imported). This job:
  * re-lifts every body from the history slices under --evidence and stops (LIFT_DRIFT) unless it is byte-equal
    to the reviewed copy, the copy equals its pin and the argv names equal the spec - before any step runs;
  * copies the recovered RK inputs (rec-01, read-only) into a fresh replay root, makes the folders the recorded
    shell made, and runs ONLY the python heredoc of each line - never the recorded shell around it - as
    `python -I -` with the body on stdin, in a fresh empty folder per step, the argv names mapped to replay paths;
  * gates: the payload byte copies (DERIVE_FAIL; also a step that exits non-zero), then the census counts and the
    named value (COUNT_FAIL). Notes are counted and reported, never gated.
Writes <out>/RESULT.txt (OK | LIFT_DRIFT | DERIVE_FAIL | COUNT_FAIL), summary.json (codes, counts and shas only),
checks.json (fail texts, no names), logs/<step>.log (each step's stdout/stderr - names, so S3 only),
derived/ (every file the steps wrote; the staged inputs left out) and derived_manifest.tsv. Path references in the
spec: 'repo', 'legacy', 'evidence:<rel>', 'recovered:<rel>', 'replay:<rel>'. Standard library only; refuses to run
off an R1 instance ($SAR_HOST).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import recover_rk as rr

AWS_HOSTS = ("ec2-r1-test", "ec2-r1")
SCHEMA = "sar.r1.derivations.v1"
BODY_DIR = "config/r1/derivations/"
ROOTS = ("evidence", "recovered", "replay")
#: `<python> - "$A" "$B" <<'EOF'\n<body>\nEOF`; <python> is a bare or quoted token (checked by _is_python)
PY_HEREDOC = re.compile(r"""(?P<py>"[^"\n]*"|[^\s"'<>;&|()]+) - (?P<args>(?:"\$\w+" )*)<<'(?P<tag>\w+)'\n"""
                        r"""(?P<body>.*?)\n(?P=tag)(?=\n|$)""", re.S)
ARG = re.compile(r'"\$(\w+)"')


def require_aws_host() -> None:
    if os.environ.get("SAR_HOST", "").strip() not in AWS_HOSTS:
        raise SystemExit("R1 rule (design v3 §4): replay_derivations.py runs only on an R1 AWS instance ($SAR_HOST)")


def _is_python(tok) -> bool:
    t = tok.strip('"')
    return t == "$PY" or pathlib.PurePosixPath(t).name in ("python", "python3")


def lift(cmd) -> tuple:
    """(argv names, body) of the one python heredoc in a recorded command; the shell around it is ignored."""
    found = [m for m in PY_HEREDOC.finditer(cmd) if _is_python(m.group("py"))]
    if len(found) != 1:
        raise RuntimeError(f"{len(found)} python heredocs in the recorded command, want 1")
    m = found[0]
    return ARG.findall(m.group("args")), m.group("body") + "\n"


def step_code(step) -> str:
    return f"T{int(step['line']):05d}"


def _plain_rel(rel) -> bool:
    p = pathlib.PurePosixPath(str(rel))
    return bool(str(rel)) and not p.is_absolute() and ".." not in p.parts


def _check_ref(ref) -> None:
    if ref in ("repo", "legacy"):
        return
    kind, sep, rel = str(ref).partition(":")
    if not sep or kind not in ROOTS or not _plain_rel(rel):
        raise SystemExit(f"bad path reference {ref!r} in the derivations spec")


def load_spec(path) -> dict:
    spec = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if spec.get("schema") != SCHEMA or not spec.get("steps"):
        raise SystemExit(f"{path}: not a {SCHEMA} spec with steps")
    for k in ("mkdirs", "stage", "bytes", "counts", "notes", "named"):
        spec.setdefault(k, [])
    for s in spec["steps"]:
        if s.get("file") != f"{BODY_DIR}{step_code(s)}.py" or sorted(s["args"]) != sorted(s["argv"]):
            raise SystemExit(f"{path}: step {step_code(s)} is malformed")
        for ref in s["args"].values():
            _check_ref(ref)
    for src, dst in spec["stage"]:
        _check_ref(src)
    rels = [*spec["mkdirs"], *(d for _, d in spec["stage"]), *(g["got"] for g in spec["bytes"]),
            *(c["file"] for c in spec["counts"] + spec["notes"] + spec["named"])]
    for rel in rels:
        if not _plain_rel(rel):
            raise SystemExit(f"{path}: {rel!r} is not a relative path inside the replay root")
    for g in spec["bytes"]:
        _check_ref(g["want"])
    return spec


def resolve(ref, bases) -> pathlib.Path:
    if ref in ("repo", "legacy"):
        return pathlib.Path(bases[ref])
    kind, _, rel = ref.partition(":")
    return pathlib.Path(bases[kind]) / rel


def check_lifts(spec, lines, repo) -> tuple:
    fails, shas = [], {}
    for s in spec["steps"]:
        code = step_code(s)
        if s["line"] not in lines:
            fails.append(rr.fail(f"lift/{code}", f"T:{s['line']} is not in the history slices"))
            continue
        try:
            names, body = lift(rr.tool_input(lines[s["line"]], "Bash")["command"])
        except RuntimeError as e:
            fails.append(rr.fail(f"lift/{code}", str(e)))
            continue
        f = pathlib.Path(repo) / s["file"]
        if not f.is_file():
            fails.append(rr.fail(f"lift/{code}", f"the reviewed copy {s['file']} is missing"))
        elif f.read_bytes() != body.encode("utf-8"):
            fails.append(rr.fail(f"lift/{code}", f"the history body differs from the reviewed copy {s['file']}"))
        elif rr.sha256(f) != s["sha256"]:
            fails.append(rr.fail(f"lift/{code}", f"{s['file']} differs from its pin in the spec"))
        elif names != s["argv"]:
            fails.append(rr.fail(f"lift/{code}", f"argv names {names} differ from the spec {s['argv']}"))
        else:
            shas[code] = s["sha256"]
    return fails, shas


def prepare(spec, bases, root) -> list:
    """Copy the staged inputs into the replay root and make the folders the recorded shell made (or that existed)."""
    fails = []
    for src, dst in spec["stage"]:
        s, d = resolve(src, bases), pathlib.Path(root) / dst
        if s.is_dir():
            shutil.copytree(s, d)
        elif s.is_file():
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
        else:
            fails.append(rr.fail(f"stage/{dst}", f"{src} is missing"))
    for rel in spec["mkdirs"]:
        (pathlib.Path(root) / rel).mkdir(parents=True, exist_ok=True)
    for s in spec["steps"]:
        for name in s["argv"]:
            if not resolve(s["args"][name], bases).exists():
                fails.append(rr.fail(f"input/{step_code(s)}", f"${name} -> {s['args'][name]} does not exist"))
    return fails


def run_step(step, bases, repo, steps_dir, logs, python) -> int:
    """Only the reviewed body (proven equal to the history lift), on stdin to `python -I -`, in a new empty folder."""
    code = step_code(step)
    cwd = pathlib.Path(steps_dir) / code
    cwd.mkdir(parents=True, exist_ok=False)
    argv = [str(resolve(step["args"][n], bases)) for n in step["argv"]]
    body = (pathlib.Path(repo) / step["file"]).read_bytes()
    with open(pathlib.Path(logs) / f"{code}.log", "wb") as log:
        r = subprocess.run([python, "-I", "-", *argv], input=body, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
    return r.returncode


def check_bytes(spec, bases, root) -> tuple:
    fails, state = [], {}
    for g in spec["bytes"]:
        got, want = pathlib.Path(root) / g["got"], resolve(g["want"], bases)
        if not got.is_file() or not want.is_file():
            state[g["name"]] = "missing"
            fails.append(rr.fail(f"bytes/{g['name']}", f"{g['got']} or {g['want']} is missing"))
        elif got.read_bytes() != want.read_bytes():
            state[g["name"]] = "differs"
            fails.append(rr.fail(f"bytes/{g['name']}", f"{g['got']} differs from {g['want']}"))
        else:
            state[g["name"]] = "ok"
    return fails, state


def count_rows(path, true=(), false=()) -> int:
    """Rows of a pandas-written CSV whose `true` columns read True and `false` columns read False."""
    with open(path, encoding="utf-8", newline="") as fh:
        return sum(1 for r in csv.DictReader(fh)
                   if all(r[c] == "True" for c in true) and all(r[c] == "False" for c in false))


def check_counts(items, root, gate) -> tuple:
    fails, got = [], {}
    for c in items:
        try:
            n = count_rows(pathlib.Path(root) / c["file"], c.get("true", []), c.get("false", []))
        except (OSError, KeyError):
            n = None
        got[c["code"]] = n
        if gate and n != c["want"]:
            fails.append(rr.fail(f"count/{c['code']}", f"{c['file']}: {n} rows, want {c['want']}"))
    return fails, got


def check_named(items, root) -> tuple:
    """One row, found by the sha256 of its key (the key itself is never in the spec or the summary)."""
    fails, state = [], {}
    for c in items:
        code = f"named/{c['code']}"
        try:
            with open(pathlib.Path(root) / c["file"], encoding="utf-8", newline="") as fh:
                rows = [r for r in csv.DictReader(fh)
                        if hashlib.sha256(r[c["key_column"]].encode("utf-8")).hexdigest() == c["key_sha256"]]
        except (OSError, KeyError):
            rows = []
        if len(rows) != 1:
            state[c["code"]] = "missing"
            fails.append(rr.fail(code, f"{c['file']}: {len(rows)} rows match the pinned key, want 1"))
            continue
        try:
            v = float(rows[0][c["column"]])
        except (KeyError, ValueError):
            v = None
        ok = v is not None and round(v, c["dp"]) == c["want"]
        state[c["code"]] = "ok" if ok else "differs"
        if not ok:
            fails.append(rr.fail(code, f"{c['column']} = {v} does not round to {c['want']} at {c['dp']} places"))
    return fails, state


def copy_derived(spec, root, dest) -> list:
    """Every file the steps wrote (the staged inputs left out) -> dest; rows (member, bytes, sha256)."""
    staged = [pathlib.PurePosixPath(d) for _, d in spec["stage"]]
    rows = []
    for p in sorted(pathlib.Path(root).rglob("*")):
        rel = pathlib.PurePosixPath(p.relative_to(root).as_posix())
        if not p.is_file() or any(rel == s or s in rel.parents for s in staged):
            continue
        t = pathlib.Path(dest) / rel
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, t)
        rows.append((rel.as_posix(), p.stat().st_size, rr.sha256(p)))
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 replay of the 10-02 heredoc derivations")
    ap.add_argument("--spec", required=True, type=pathlib.Path, help="config/r1/derivations.json")
    ap.add_argument("--evidence", required=True, type=pathlib.Path)
    ap.add_argument("--recovered", required=True, type=pathlib.Path, help="the pulled rec-01 recovery (read-only)")
    ap.add_argument("--repo", required=True, type=pathlib.Path)
    ap.add_argument("--legacy", required=True, type=pathlib.Path, help="the synced legacy v2_output tree")
    ap.add_argument("--work", required=True, type=pathlib.Path, help="a new or empty folder")
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--python", default=sys.executable, help="interpreter for the replayed bodies")
    a = ap.parse_args(argv)
    require_aws_host()
    if a.work.exists() and (not a.work.is_dir() or any(a.work.iterdir())):
        raise SystemExit(f"{a.work} is used: the replay wants a new or empty work folder")
    spec = load_spec(a.spec)
    root, steps_dir, logs = a.work / "root", a.work / "steps", a.out / "logs"
    root.mkdir(parents=True)
    steps_dir.mkdir()
    logs.mkdir(parents=True, exist_ok=True)
    bases = {"repo": a.repo, "legacy": a.legacy, "evidence": a.evidence, "recovered": a.recovered, "replay": root}
    status = {step_code(s): "not_run" for s in spec["steps"]}
    byte_state, counts, note_counts, named = {}, {}, {}, {}
    derive, count_fails = [], []
    try:
        lift_fails, lift_shas = check_lifts(spec, rr.history_lines(a.evidence), a.repo)
    except (RuntimeError, ValueError, OSError) as e:
        lift_fails, lift_shas = [rr.fail("lift/history", f"{e.__class__.__name__}: {e}")], {}
    if not lift_fails:
        derive = prepare(spec, bases, root)
        for s in spec["steps"] if not derive else []:
            code = step_code(s)
            rc = run_step(s, bases, a.repo, steps_dir, logs, a.python)
            status[code] = "ok" if rc == 0 else "fail"
            if rc != 0:
                derive.append(rr.fail(f"step/{code}", f"exited {rc}; its output is in logs/{code}.log"))
                break
        if not derive:
            derive, byte_state = check_bytes(spec, bases, root)
            f1, counts = check_counts(spec["counts"], root, gate=True)
            _, note_counts = check_counts(spec["notes"], root, gate=False)
            f2, named = check_named(spec["named"], root)
            count_fails = f1 + f2
    fails = lift_fails + derive + count_fails
    result = "LIFT_DRIFT" if lift_fails else "DERIVE_FAIL" if derive else "COUNT_FAIL" if count_fails else "OK"
    rows = copy_derived(spec, root, a.out / "derived")
    (a.out / "derived_manifest.tsv").write_text("member\tbytes\tsha256\n" + "".join(
        "\t".join(map(str, r)) + "\n" for r in rows), encoding="utf-8")
    gated = {g["got"] for g in spec["bytes"]} | {c["file"] for c in spec["counts"] + spec["named"]}
    shas = {r[0]: r[2] for r in rows if r[0] in gated}
    (a.out / "checks.json").write_text(json.dumps({"fails": fails, "notes": ["notes are counted, never gated"]},
                                                  indent=1, sort_keys=True) + "\n", encoding="utf-8")
    summary = {"result": result, "fail_codes": sorted({f.split(" | ", 1)[0] for f in fails}), "fails": len(fails),
               "steps": status, "lift_sha256": lift_shas, "bytes": byte_state, "counts": counts,
               "note_counts": note_counts, "named": named, "shas": shas, "derived_files": len(rows),
               "derived_manifest_sha256": rr.sha256(a.out / "derived_manifest.tsv")}
    (a.out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (a.out / "RESULT.txt").write_text(result + "\n", encoding="utf-8")
    for f in fails:
        print("FAIL", f)
    print(result, f"{len(rows)} derived files")
    return 0 if result == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
