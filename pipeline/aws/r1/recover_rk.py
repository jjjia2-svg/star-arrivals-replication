#!/usr/bin/env python3
"""R1 recovery job, instance side (job kind 'rec'): bring the 10-02 ranking runs RK1-RK5 back.

For each rkN under <bucket>/rkN/<date>/: copy it into a fresh directory, check both sha256 files,
extract both tars with tarfile's 'data' filter, then the gates:
  * both sha256 files match; RK1/RK2 payload shas equal the values printed at the time (T:2744,
    T:3109) and RK3's prefix (T:3235);
  * every RESULT.txt is OK; RK1/RK4 control_fail == []; RK2/RK5 gate_fail == [];
  * each kit script in a payload equals its rebuild from the history (the Write record plus the
    one recorded Edit), so the copies we reuse are exactly what ran;
  * the repo/ subset in the RK1/RK2/RK4/RK5 payloads equals `git archive` of the base commit;
  * launch side (never in S3): prep_rk1.py is rebuilt from its Write record and run with its recorded
    input; it must reproduce the RK1 payload's in/requests.json and in/control.json byte for byte.
    run_caliber's historical/October call lists read the legacy tree (not on S3 before P3), so they
    are stubbed empty and drops.csv/adds.csv are left to P3 (a note).
Notes, not gates: the user-data scripts and custody templates rebuilt from the history (Write
records, replayed sed, heredocs, a replayed literal Python transform - no recorded shell or Python is
executed), each checked against its run's boot.log trace; rough run minutes from S3 times.
Uploads every extracted file except the payload repo/ subset (it is in git) to
<bucket>/<dest>/rkN/{payload,out,raw}/ and <dest>/launch_side/, plus manifest.tsv, checks.json,
summary.json and RESULT.txt (OK or RECOVERY_FAIL). <dest> must be under r1/ (run-scoped:
r1/recovered/<job>). A fail is "<code> | <text>"; summary.json carries only the codes, counts, pins and
minutes, never fail texts. Standard library only; the `aws` CLI does the S3 copies. Refuses to run off
an R1 instance ($SAR_HOST).
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tarfile

AWS_HOSTS = ("ec2-r1-test", "ec2-r1")
RUNS = ("rk1", "rk2", "rk3", "rk4", "rk5")
KNOWN_PAYLOAD_SHA = {"rk1": "ef48dae8bcbf0d3e4fd6e69e05908ec919e9fd243868eb8f9ca4eefea73cde83",
                     "rk2": "5b46cce26f4e1fe6b587813a91f65034bc82ea373fc320c75250bce2f02ca640"}
KNOWN_PAYLOAD_SHA_PREFIX = {"rk3": "81fb86efbc35db72"}
KIT_LINES = {"rk1.py": (2664, [2675]), "rk2.py": (3071, [3082]), "rk3.py": (3205, []), "rk5_match.py": (4546, [])}
KIT_IN_PAYLOAD = {"rk1.py": ("rk1", "rk4"), "rk2.py": ("rk2", "rk5"), "rk3.py": ("rk3",), "rk5_match.py": ("rk5",)}
REPORT_GATES = {"rk1": ("rk1_report.json", "control_fail"), "rk2": ("rk2_report.json", "gate_fail"),
                "rk4": ("rk1_report.json", "control_fail"), "rk5": ("rk2_report.json", "gate_fail")}
BASE_COMMIT = "8b4ac189796b900c3cad2ee6c79aee48083323b4"
RK1_REPO_PATHS = ("pipeline", "analysis/lib", "config", "setup/requirements.txt", "data/cal2026-08-28/calls_2026-08-28.csv")
REPO_RUNS = ("rk1", "rk2", "rk4", "rk5")
#: launch-side files (the RK kit recovery notes, §1; not shipped): how each was made, at which history line
LS_WRITES = {"prep_rk1.py": 2683, "userdata.sh": 2724}
LS_HEREDOC = {"userdata3.sh": 3228, "custody.json": 2783, "custody_rk2.json": 3131}
LS_SED = {"userdata2.sh": (3108, "userdata.sh"), "userdata4.sh": (3360, "userdata.sh")}
LS_PYREPLACE = {"userdata5.sh": (4570, "userdata2.sh")}
#: per run: its boot script, and what that script must name (S3 prefix, scripts run) - checked in boot.log
BOOT_MARKS = {"rk1": ("userdata.sh", ["rk1/20261002", "/work/rk1.py"]),
              "rk2": ("userdata2.sh", ["rk2/20261002", "/work/rk2.py"]),
              "rk3": ("userdata3.sh", ["rk3/20261002", "/work/rk3.py"]),
              "rk4": ("userdata4.sh", ["rk4/20261002", "/work/rk1.py"]),
              "rk5": ("userdata5.sh", ["rk5/20261002", "/work/rk5_match.py", "/work/rk2.py"])}
SWEEP_WF = "workflows/wf_9b087077-158.json"
PREP_GATED = ("requests.json", "control.json")
PREP_STUB = "def historical_calls():\n    return set(), set(), {}\n\n\ndef october_calls():\n    return set(), []\n"


def require_aws_host() -> None:
    if os.environ.get("SAR_HOST", "").strip() not in AWS_HOSTS:
        raise SystemExit("R1 rule (design v3 §4): recover_rk.py runs only on an R1 AWS instance ($SAR_HOST)")


def fail(code, text) -> str:
    """'<code> | <text>'. The code names run/check only (no person); summary.json keeps only codes."""
    return f"{code} | {text}"


def sha256(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def expected_sha(sha_file) -> tuple:
    line = pathlib.Path(sha_file).read_text(encoding="utf-8").strip().splitlines()[0]
    hexd, name = line.split(None, 1)
    return hexd.lower(), pathlib.PurePosixPath(name.strip().lstrip("*")).name


def verify(p, sha_file):
    want, name = expected_sha(sha_file)
    if name != pathlib.Path(p).name:
        return f"{pathlib.Path(sha_file).name} names {name}, not {pathlib.Path(p).name}"
    got = sha256(p)
    return None if got == want else f"{pathlib.Path(p).name}: sha256 {got} != {want}"


def safe_extract(tar_path, dest) -> None:
    dest = pathlib.Path(dest)
    if dest.exists() and any(dest.iterdir()):
        raise RuntimeError(f"{dest} is not empty")
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "r:gz") as tf:
        tf.extractall(dest, filter="data")


def history_lines(evidence) -> dict:
    out = {}
    for f in sorted((pathlib.Path(evidence) / "history").glob("T_*-*.jsonl")):
        a, b = (int(x) for x in f.stem[2:].split("-"))
        lines = f.read_text(encoding="utf-8").splitlines()
        if len(lines) != b - a + 1:
            raise RuntimeError(f"{f.name}: {len(lines)} lines, want {b - a + 1}")
        for i, line in enumerate(lines):
            out[a + i] = json.loads(line)
    return out


def tool_input(rec, tool) -> dict:
    content = (rec.get("message") or {}).get("content")
    for blk in content if isinstance(content, list) else []:
        if isinstance(blk, dict) and blk.get("type") == "tool_use" and blk.get("name") == tool:
            return blk["input"]
    raise RuntimeError(f"no {tool} call in this history record")


def rebuild(lines, write_line, edit_lines, basename) -> bytes:
    if write_line not in lines:
        raise RuntimeError(f"T:{write_line} is not in the history slices")
    w = tool_input(lines[write_line], "Write")
    got = pathlib.PurePosixPath(w["file_path"]).name
    if got != basename:
        raise RuntimeError(f"T:{write_line} names {got}, not {basename}")
    text = w["content"]
    for n in edit_lines:
        if n not in lines:
            raise RuntimeError(f"T:{n} is not in the history slices")
        e = tool_input(lines[n], "Edit")
        if pathlib.PurePosixPath(e["file_path"]).name != basename:
            raise RuntimeError(f"T:{n} edits another file")
        if e.get("replace_all"):
            raise RuntimeError(f"T:{n} is a replace_all edit, which the kit never used")
        k = text.count(e["old_string"])
        if k != 1:
            raise RuntimeError(f"{basename}: T:{n} old_string occurs {k} times")
        text = text.replace(e["old_string"], e["new_string"], 1)
    return text.encode("utf-8")


def heredoc_body(cmd, target) -> str:
    """The body of the one `cat > <…>target <<EOF` (or <<'EOF') heredoc in a recorded command, unchanged.
    An unquoted heredoc's $(…) stay as written: the file that existed had them filled."""
    pat = re.compile(r"cat > [^\n<]*?" + re.escape(target) + r" <<'?(\w+)'?\n(.*?)\n\1(?:\n|$)", re.S)
    found = pat.findall(cmd)
    if len(found) != 1:
        raise RuntimeError(f"{target}: {len(found)} heredocs in the recorded command, want 1")
    return found[0][1] + "\n"


SED_EXPR = re.compile(r"-e '(s#([^#]*)#([^#]*)#(g?))'")


def sed_replay(cmd, src_text, src, dst) -> str:
    """Replay a recorded `sed -e 's#A#B#[g]' … SRC > DST`. Only the shape where BRE and Python regex
    agree is accepted: A made of letters, digits, '/', '.', '_', '-' and spaces; B without '\\' or '&'.
    Without g, sed replaces the first match on each line; expressions apply in order, line by line."""
    m = re.search(r"sed((?: -e '[^']*')+) " + re.escape(src) + r" > " + re.escape(dst) + r"(?:\s|$)", cmd)
    if not m:
        raise RuntimeError(f"no `sed … {src} > {dst}` in the recorded command")
    exprs = SED_EXPR.findall(m.group(1))
    if not exprs or len(exprs) != m.group(1).count(" -e "):
        raise RuntimeError(f"{dst}: sed expressions outside the replayable shape")
    for _, a, b, _g in exprs:
        if not re.fullmatch(r"[A-Za-z0-9/._ -]+", a) or "\\" in b or "&" in b:
            raise RuntimeError(f"{dst}: sed expression {a!r} -> {b!r} is outside the replayable shape")
    out = []
    for line in src_text.splitlines(keepends=True):
        for _, a, b, g in exprs:
            line = re.sub(a, b, line, count=0 if g else 1)
        out.append(line)
    return "".join(out)


def py_replace_replay(cmd, inputs) -> tuple:
    """Replay a recorded `python3 - <<'EOF'` string transform WITHOUT executing it. Accepted statements
    only: name = <literal>; s = open(<lit>).read(); s = s.replace(<lit|name>, <lit|name>[, <int>])…;
    assert s.count(<lit|name>) == 1; open(<lit>, 'w').write(s); print(…). Anything else refuses."""
    m = re.search(r"python3 - <<'EOF'\n(.*?)\nEOF", cmd, re.S)
    if not m:
        raise RuntimeError("no python3 heredoc in the recorded command")
    env, s, out_name = {}, None, None

    def val(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (str, int)):
            return n.value
        if isinstance(n, ast.Name) and n.id in env:
            return env[n.id]
        raise RuntimeError(f"line {getattr(n, 'lineno', '?')}: not a literal")

    def is_call(n, name):
        return isinstance(n, ast.Call) and getattr(n.func, "id", None) == name

    for st in ast.parse(m.group(1)).body:
        if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
            name, v = st.targets[0].id, st.value
            if name != "s":
                env[name] = val(v)
            elif isinstance(v, ast.Call) and getattr(v.func, "attr", None) == "read" and is_call(v.func.value, "open"):
                s = inputs[val(v.func.value.args[0])]
            else:
                calls = []
                while isinstance(v, ast.Call) and getattr(v.func, "attr", None) == "replace":
                    calls.append(v)
                    v = v.func.value
                if not calls or not (isinstance(v, ast.Name) and v.id == "s") or s is None:
                    raise RuntimeError(f"line {st.lineno}: not a replace chain on s")
                for c in reversed(calls):
                    s = s.replace(*[val(a) for a in c.args])
        elif isinstance(st, ast.Assert):
            t = st.test
            if not (isinstance(t, ast.Compare) and isinstance(t.left, ast.Call)
                    and getattr(t.left.func, "attr", None) == "count" and len(t.comparators) == 1
                    and val(t.comparators[0]) == 1):
                raise RuntimeError(f"line {st.lineno}: assert outside the replayable shape")
            if s is None or s.count(val(t.left.args[0])) != 1:
                raise RuntimeError(f"line {st.lineno}: the recorded assert fails on the replay")
        elif isinstance(st, ast.Expr) and isinstance(st.value, ast.Call):
            c = st.value
            if is_call(c, "print"):
                continue
            if (getattr(c.func, "attr", None) == "write" and is_call(c.func.value, "open")
                    and val(c.func.value.args[1]) == "w" and isinstance(c.args[0], ast.Name) and c.args[0].id == "s"):
                out_name = val(c.func.value.args[0])
                continue
            raise RuntimeError(f"line {st.lineno}: call outside the replayable shape")
        else:
            raise RuntimeError(f"line {st.lineno}: statement outside the replayable shape")
    if s is None or out_name is None:
        raise RuntimeError("the recorded transform reads or writes nothing")
    return out_name, s


def launch_side(lines, work) -> tuple:
    """Rebuild the launch-side files into <work>/launch_side/ (with each source command as cmd_T<n>.txt).
    Returns (files, notes). A file that cannot be rebuilt is a note: these files feed nothing downstream;
    prep_rk1.py is gated separately by check_prep."""
    d = pathlib.Path(work) / "launch_side"
    d.mkdir(parents=True, exist_ok=False)
    files, notes = {}, []

    def cmd(n):
        return tool_input(lines[n], "Bash")["command"]
    for name, n in LS_WRITES.items():
        try:
            files[name] = rebuild(lines, n, [], name).decode("utf-8")
        except (KeyError, RuntimeError) as e:
            notes.append(f"{name}: not rebuilt from T:{n}: {e}")
    for name, n in LS_HEREDOC.items():
        try:
            files[name] = heredoc_body(cmd(n), name)
        except (KeyError, RuntimeError) as e:
            notes.append(f"{name}: not rebuilt from T:{n}: {e}")
    notes.append("custody.json, custody_rk2.json: heredoc templates as recorded; the $(...) values were printed at T:2784")
    for name, (n, src) in LS_SED.items():
        try:
            if src not in files:
                raise RuntimeError(f"{src} was not rebuilt")
            files[name] = sed_replay(cmd(n), files[src], src, name)
        except (KeyError, RuntimeError) as e:
            notes.append(f"{name}: not rebuilt from T:{n}: {e}")
    for name, (n, src) in LS_PYREPLACE.items():
        try:
            if src not in files:
                raise RuntimeError(f"{src} was not rebuilt")
            out_name, text = py_replace_replay(cmd(n), {src: files[src]})
            if out_name != name:
                raise RuntimeError(f"the transform writes {out_name}, not {name}")
            files[name] = text
        except (KeyError, RuntimeError, SyntaxError) as e:
            notes.append(f"{name}: not rebuilt from T:{n}: {e}")
    for name, text in sorted(files.items()):
        (d / name).write_text(text, encoding="utf-8")
    for n in sorted({*LS_HEREDOC.values(), *(v[0] for v in LS_SED.values()), *(v[0] for v in LS_PYREPLACE.values())}):
        try:
            (d / f"cmd_T{n:05d}.txt").write_text(cmd(n), encoding="utf-8")
        except (KeyError, RuntimeError):
            pass
    return files, notes


def check_prep(prep_text, evidence, work, rk1_in, python) -> list:
    """Gate: run the rebuilt prep_rk1.py the way it ran (HERE/in, HERE.parent/sweep/v2/verify_result.json
    = the wf_9b087077 result, the repo at its own path) and compare what it writes with the RK1 payload."""
    run = pathlib.Path(work) / "prep_run"
    for sub in ("rk1", "sweep/v2", "stub"):
        (run / sub).mkdir(parents=True)
    script = run / "rk1" / "prep_rk1.py"
    script.write_text(prep_text, encoding="utf-8")
    result = json.loads((pathlib.Path(evidence) / SWEEP_WF).read_text(encoding="utf-8"))["result"]
    (run / "sweep" / "v2" / "verify_result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    (run / "stub" / "run_caliber.py").write_text(PREP_STUB, encoding="utf-8")
    code = ("import runpy, sys; sys.path.insert(0, sys.argv[1]); import run_caliber; "
            "runpy.run_path(sys.argv[2], run_name='__main__')")
    r = subprocess.run([python, "-c", code, str(run / "stub"), str(script)], cwd=run / "rk1", capture_output=True, text=True)
    if r.returncode != 0:
        return [fail("launch_side/prep_rk1", f"the rebuilt prep_rk1.py exited {r.returncode}: {r.stderr.strip()[-300:]}")]
    fails = []
    for name in PREP_GATED:
        got, want = run / "rk1" / "in" / name, pathlib.Path(rk1_in) / name
        if not got.is_file() or not want.is_file() or got.read_bytes() != want.read_bytes():
            fails.append(fail("launch_side/prep_rk1", f"{name}: the rebuild does not reproduce the RK1 payload's in/{name}"))
    return fails


def boot_notes(files, work) -> list:
    out = []
    for run, (ud, marks) in BOOT_MARKS.items():
        log = pathlib.Path(work) / run / "raw" / "out" / "boot.log"
        trace = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        text = files.get(ud, "")
        for mk in marks:
            out.append(f"{run} boot.log vs {ud}: {mk!r} in user-data {mk in text}, in boot.log trace {mk in trace}")
    return out


def run_minutes(bucket, run, date, status):
    """Rough run length: payload upload time (just before launch) to the DONE time in status.txt."""
    try:
        ls = subprocess.run(["aws", "s3", "ls", f"{bucket}/{run}/{date}/in/payload.tar.gz"],
                            capture_output=True, text=True, check=True).stdout.split()
        start = dt.datetime.strptime(f"{ls[0]} {ls[1]}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
        end = dt.datetime.fromisoformat(status.split()[0].replace("Z", "+00:00"))
        return round((end - start).total_seconds() / 60, 1)
    except (subprocess.CalledProcessError, IndexError, ValueError):
        return None


def fetch_run(bucket, run, date, work) -> pathlib.Path:
    raw = pathlib.Path(work) / run / "raw"
    if raw.exists():
        raise RuntimeError(f"{raw} exists: recovery wants fresh directories")
    raw.mkdir(parents=True)
    subprocess.run(["aws", "s3", "cp", "--only-show-errors", "--recursive", f"{bucket}/{run}/{date}/", f"{raw}/"], check=True)
    return raw


def check_run(run, raw, work) -> tuple:
    fails = []
    pay, out = (raw / "in" / "payload.tar.gz", raw / "in" / "payload.sha256"), (raw / "out" / "out.tar.gz", raw / "out" / "out.sha256")
    for p, s in (pay, out):
        if not p.is_file() or not s.is_file():
            fails.append(fail(f"{run}/files", f"missing {p.name} or {s.name}"))
            continue
        err = verify(p, s)
        if err:
            fails.append(fail(f"{run}/sha", err))
    if fails:
        return fails, {}
    psha = sha256(pay[0])
    if run in KNOWN_PAYLOAD_SHA and psha != KNOWN_PAYLOAD_SHA[run]:
        fails.append(fail(f"{run}/payload_sha_known", f"payload sha {psha} differs from the value printed at the time"))
    if run in KNOWN_PAYLOAD_SHA_PREFIX and not psha.startswith(KNOWN_PAYLOAD_SHA_PREFIX[run]):
        fails.append(fail(f"{run}/payload_sha_known", f"payload sha {psha[:16]} differs from the prefix printed at the time"))
    work = pathlib.Path(work)
    safe_extract(pay[0], work / run / "payload")
    safe_extract(out[0], work / run / "out")
    od = work / run / "out" / "out"
    res = od / "RESULT.txt"
    if not res.is_file() or res.read_text(encoding="utf-8").strip() != "OK":
        fails.append(fail(f"{run}/result", "RESULT.txt is not OK"))
    if run in REPORT_GATES:
        fn, key = REPORT_GATES[run]
        rp = od / fn
        val = json.loads(rp.read_text(encoding="utf-8")).get(key) if rp.is_file() else "missing"
        if val != []:
            fails.append(fail(f"{run}/{key}", f"{fn} {key} = {val!r}"))
    status = (raw / "status.txt").read_text(encoding="utf-8").strip() if (raw / "status.txt").is_file() else ""
    return fails, {"payload_sha256": psha, "out_sha256": sha256(out[0]), "status": status}


def check_kit(work, lines) -> list:
    fails = []
    for name, (w, edits) in KIT_LINES.items():
        try:
            want = rebuild(lines, w, edits, name)
        except (KeyError, RuntimeError) as e:
            fails.append(fail(f"kit/{name}", f"cannot rebuild from the history: {e}"))
            continue
        for run in KIT_IN_PAYLOAD[name]:
            got = pathlib.Path(work) / run / "payload" / name
            if not got.is_file():
                fails.append(fail(f"kit/{name}/{run}", f"{name} missing from the {run} payload"))
            elif got.read_bytes() != want:
                fails.append(fail(f"kit/{name}/{run}", f"the {run} payload copy of {name} differs from the history rebuild"))
    return fails


def tree_diff(a, b) -> list:
    a, b = pathlib.Path(a), pathlib.Path(b)

    def files(root):
        return {p.relative_to(root).as_posix() for p in root.rglob("*")
                if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
    fa, fb = files(a), files(b)
    out = [f"only in the archive: {x}" for x in sorted(fa - fb)]
    out += [f"only in the payload: {x}" for x in sorted(fb - fa)]
    out += [f"differs: {x}" for x in sorted(fa & fb) if (a / x).read_bytes() != (b / x).read_bytes()]
    return out


def check_repo_subsets(work, repo) -> list:
    ref = pathlib.Path(work) / "_git_archive_base"
    ref.mkdir(parents=True, exist_ok=False)
    arch = subprocess.run(["git", "-C", str(repo), "archive", BASE_COMMIT, *RK1_REPO_PATHS],
                          capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(arch)) as tf:
        tf.extractall(ref, filter="data")
    fails = []
    for run in REPO_RUNS:
        diff = tree_diff(ref, pathlib.Path(work) / run / "payload" / "repo")
        if diff:
            fails.append(fail(f"{run}/repo_subset", f"payload repo/ differs from git archive {BASE_COMMIT[:7]}: {diff[:5]}"))
    return fails


def parts(work, run) -> tuple:
    w = pathlib.Path(work) / run
    return (("payload", w / "payload"), ("out", w / "out" / "out"), ("raw", w / "raw"))


def keep(part, rel) -> bool:
    if part == "payload" and rel.split("/", 1)[0] == "repo":
        return False
    return not (part == "raw" and rel.endswith(".tar.gz"))


def manifest_rows(work) -> list:
    rows = []
    for run in RUNS:
        for part, root in parts(work, run):
            if not root.is_dir():
                continue
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    rel = p.relative_to(root).as_posix()
                    if keep(part, rel):
                        rows.append((run, part, rel, p.stat().st_size, sha256(p)))
    ls = pathlib.Path(work) / "launch_side"
    for p in sorted(ls.glob("*")) if ls.is_dir() else []:
        if p.is_file():
            rows.append(("kit", "launch_side", p.name, p.stat().st_size, sha256(p)))
    return rows


def upload(bucket, dest, work, out) -> None:
    if not dest.startswith("r1/") or ".." in dest:
        raise SystemExit(f"refusing to write outside r1/: {dest}")
    for run in RUNS:
        for part, root in parts(work, run):
            if not root.is_dir():
                continue
            extra = {"payload": ["--exclude", "repo/*"], "raw": ["--exclude", "*.tar.gz"]}.get(part, [])
            subprocess.run(["aws", "s3", "cp", "--only-show-errors", "--recursive", *extra, f"{root}/",
                            f"{bucket}/{dest}/{run}/{part}/"], check=True)
    ls = pathlib.Path(work) / "launch_side"
    if ls.is_dir():
        subprocess.run(["aws", "s3", "cp", "--only-show-errors", "--recursive", f"{ls}/", f"{bucket}/{dest}/launch_side/"], check=True)
    for name in ("manifest.tsv", "checks.json", "summary.json", "RESULT.txt"):
        subprocess.run(["aws", "s3", "cp", "--only-show-errors", str(pathlib.Path(out) / name), f"{bucket}/{dest}/{name}"], check=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 recovery of RK1-RK5")
    ap.add_argument("--bucket", required=True, help="s3://<bucket>")
    ap.add_argument("--date", default="20261002")
    ap.add_argument("--evidence", required=True, type=pathlib.Path)
    ap.add_argument("--repo", required=True, type=pathlib.Path)
    ap.add_argument("--work", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--dest", required=True, help="run-scoped, under r1/: r1/recovered/<job>")
    ap.add_argument("--python", default=sys.executable, help="interpreter for the rebuilt prep_rk1.py")
    a = ap.parse_args(argv)
    require_aws_host()
    if not a.dest.startswith("r1/") or ".." in a.dest:
        raise SystemExit(f"refusing to write outside r1/: {a.dest}")
    a.out.mkdir(parents=True, exist_ok=True)
    fails, info, notes = [], {}, []
    for run in RUNS:
        f, i = check_run(run, fetch_run(a.bucket, run, a.date, a.work), a.work)
        i["minutes_est"] = run_minutes(a.bucket, run, a.date, i.get("status", ""))
        fails += f
        info[run] = i
    if not fails:
        lines = history_lines(a.evidence)
        fails += check_kit(a.work, lines)
        fails += check_repo_subsets(a.work, a.repo)
        files, ls_notes = launch_side(lines, a.work)
        notes += ls_notes
        if "prep_rk1.py" in files:
            fails += check_prep(files["prep_rk1.py"], a.evidence, a.work, a.work / "rk1" / "payload" / "in", a.python)
        else:
            fails.append(fail("launch_side/prep_rk1", "prep_rk1.py could not be rebuilt from T:2683"))
        notes.append("drops.csv/adds.csv: not rebuilt here - historical_calls() reads the legacy tree, uploaded only in P3")
        notes += boot_notes(files, a.work)
    rows = manifest_rows(a.work)
    (a.out / "manifest.tsv").write_text("run\tpart\tmember\tbytes\tsha256\n"
                                        + "".join("\t".join(map(str, r)) + "\n" for r in rows), encoding="utf-8")
    (a.out / "checks.json").write_text(json.dumps({"fails": fails, "notes": notes, "runs": info}, indent=1, sort_keys=True) + "\n",
                                       encoding="utf-8")
    result = "OK" if not fails else "RECOVERY_FAIL"
    (a.out / "RESULT.txt").write_text(result + "\n", encoding="utf-8")
    by_key = {f"{r[0]}/{r[1]}/{r[2]}": r[4] for r in rows}
    pins = {k: by_key[src] for k, src in (("rk1/payload/rk1.py", "rk1/payload/rk1.py"),
                                          ("launch_side/prep_rk1.py", "kit/launch_side/prep_rk1.py")) if src in by_key}
    pins["manifest.tsv"] = sha256(a.out / "manifest.tsv")
    summary = {"result": result, "fail_codes": sorted({f.split(" | ", 1)[0] for f in fails}), "fails": len(fails),
               "notes": len(notes), "files": len(rows), "pins": pins,
               "minutes_est": {run: info[run].get("minutes_est") for run in RUNS}}
    (a.out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    upload(a.bucket, a.dest, a.work, a.out)
    for f in fails:
        print("FAIL", f)
    print(result, f"{len(rows)} files")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
