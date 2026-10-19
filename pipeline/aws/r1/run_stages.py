#!/usr/bin/env python3
"""R1 multi-stage driver (F25; resume N13). Runs on an R1 instance only. Standard library only.

  run_stages.py --table T.json --repo DIR --commit SHA --prefix s3://BUCKET/r1/runs/JOB --work /work --out /work/out
                [--pins P.json] [--env-pins E.json] [--resume-dir DIR]

Per stage in table order: copy its script from the commit to WORK/<basename> (never run in place under
pipeline/), clear its outputs, run `bash -c cmd` (env PY, REPO_DIR, COMMIT, WORK, STAGE_OUT=WORK/prod/<name>),
digest its outputs, push them and a done marker to <prefix>/stages/. The first failure ends the job:
RESULT.txt = 'STAGE_FAIL <name> <why>'. Fingerprint = cmd + script blob + resolved inputs (ruling R12).
After every pushed stage (ran or skipped), WORK/reads/ (the sandbox read logs, F2) is synced to
<prefix>/stages/_reads/. While a sandbox watcher is up (WORK/sandbox_watch.pid), a stage that ran is closed before
its push: run_stages writes '<UTC> IDLE' to WORK/status.txt and waits (WATCH_WAIT_SECS) for the watcher's
'<stage>\\t__END__' line on reads/<stage>.tsv, else STAGE_FAIL 'AUDIT_LOST watcher'; the log's sha256 goes into the
marker (reads_sha256), and such a stage is restored on --resume-dir only together with an equal log from
<resume>/_reads/, which is then copied into WORK/reads/ (J0 review #5). Likewise, before a stage runs,
run_stages waits (WATCH_WAIT_SECS) for the watcher to acknowledge its 'STAGE <name>' line by creating
reads/<name>.tsv, else STAGE_FAIL (J0 review #7).
summary.json carries the commit and each stage's STAGE_OUT reports (cells_report_*
as written; gate_report_*, report_*, stop_report_*, final_report_* through name_free), a failed stage's too.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

HOSTS = ("ec2-r1-test", "ec2-r1")
SCHEMA = "sar.r1.stages.v1"
PREFIX = re.compile(r"^s3://[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]/r1/runs/[a-z0-9][a-z0-9-]{2,40}$")
NAME = re.compile(r"^[a-z0-9][a-z0-9_]{0,40}$")
TOKEN = re.compile(r"^(repo|work|data|env|stage):(.+)$")
KEYS = ("name", "owner", "cmd", "inputs", "outputs", "est_min", "needs")
#: the sandbox watcher's files under WORK (pipeline/aws/r1/sandbox.py PID_NAME, END; tests pin the equality)
WATCH_PID, READS_DIR, END = "sandbox_watch.pid", "reads", "__END__"
WATCH_WAIT_SECS = 30


class StageError(RuntimeError):
    """A stage that cannot run, or ran and failed."""


def load_table(path) -> dict:
    t = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if t.get("schema") != SCHEMA or not isinstance(t.get("stages"), list) or not t["stages"]:
        raise StageError(f"{path}: not a {SCHEMA} table")
    names, seen = [x.get("name") for x in t["stages"]], []
    for s in t["stages"]:
        miss = [k for k in KEYS if k not in s]
        if miss:
            raise StageError(f"stage {s.get('name')!r}: missing {miss}")
        if not NAME.match(s["name"]) or s["name"] in seen:
            raise StageError(f"bad or duplicate stage name {s['name']!r}")
        for tok in s["inputs"] + s["outputs"]:
            m = TOKEN.match(tok)
            if not m or ".." in m.group(2).split("/") or m.group(2).startswith("/"):
                raise StageError(f"stage {s['name']}: bad token {tok!r}")
        if s.get("resume", "always") != "always":
            raise StageError(f"stage {s['name']}: resume may only be 'always' (or absent)")
        if any(not tok.startswith(("work:", "repo:")) for tok in s["outputs"]):
            raise StageError(f"stage {s['name']}: outputs must be work: or repo: tokens")
        # a need that runs later is always wrong; a need not in the table yet is allowed only while incomplete
        late = [n for n in s["needs"] if n not in seen and (t.get("complete") or n in names)]
        if late:
            raise StageError(f"stage {s['name']} needs {late}, which do not run before it")
        seen.append(s["name"])
    return t


def git(repo, *args) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise StageError(f"git {args[0] if args else ''}: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def sha256_file(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def digest_of(path) -> str:
    path = pathlib.Path(path)
    if path.is_file():
        return sha256_file(path)
    if not path.is_dir():
        raise StageError(f"declared output missing: {path}")
    rows = sorted((p.relative_to(path).as_posix(), sha256_file(p)) for p in path.rglob("*") if p.is_file())
    return hashlib.sha256("".join(f"{s}  {r}\n" for r, s in rows).encode()).hexdigest()


def resolve_out(tok, *, work, repo) -> pathlib.Path:
    kind, rel = TOKEN.match(tok).groups()
    return (pathlib.Path(work) if kind == "work" else pathlib.Path(repo)) / rel


def fingerprint(stage, *, repo, commit, pins, env_pins, done) -> str:
    res = {}
    if stage.get("script"):
        res["script"] = git(repo, "rev-parse", f"{commit}:{stage['script']}")
    for tok in sorted(stage["inputs"]):
        kind, val = TOKEN.match(tok).groups()
        try:
            res[tok] = {"repo": lambda: git(repo, "rev-parse", f"{commit}:{val}"),
                        "data": lambda: pins["pins"][val]["manifest_sha256"],
                        "env": lambda: env_pins["layers"][val]["sha256"],
                        "stage": lambda: done[val]["outputs_digest"]}[kind]()
        except KeyError as e:
            raise StageError(f"stage {stage['name']}: input {tok} has no value ({e})") from None
    return hashlib.sha256(json.dumps({"cmd": stage["cmd"], "inputs": res}, sort_keys=True).encode()).hexdigest()


# s3() and status() write only under the validated --prefix (s3://<bucket>/r1/runs/<job>).
def s3(args) -> None:
    r = subprocess.run(["aws", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise StageError(f"aws {' '.join(args[:2])} failed (rc {r.returncode}): {r.stderr.strip()[:200]}")


def _status_local(work, text) -> pathlib.Path:
    p = pathlib.Path(work) / "status.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"{dt.datetime.now(dt.timezone.utc):%Y-%m-%dT%H:%M:%SZ} {text}\n", encoding="utf-8")
    return p


def status(prefix, text, work) -> None:
    p = _status_local(work, text)
    s3(["s3", "cp", "--only-show-errors", str(p), f"{prefix}/status.txt"])


def _watched(work) -> bool:
    """A sandbox watcher is up (F2): its pid file exists from the end of `sandbox` until `sandbox_check` stops it."""
    return (pathlib.Path(work) / WATCH_PID).exists()


def _last_line(p):
    try:
        lines = [ln for ln in pathlib.Path(p).read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return None
    return lines[-1] if lines else None


def ack_stage(stage, *, work) -> None:
    """With a watcher up: before the stage runs, wait until the watcher has taken in its status line - it creates
    reads/<stage>.tsv while handling that event (sandbox.Watcher.feed). The watcher reads the status file when it
    handles the event, so without this wait a stalled watcher could read a later stage's line and charge this
    stage's reads to it (J0 review #7). WORK/reads is new on every instance and a restored stage's log is
    copied in only when the stage is not run, so no stale file can stand in for the acknowledgement."""
    work = pathlib.Path(work)
    if not _watched(work):
        return
    log = work / READS_DIR / f"{stage['name']}.tsv"
    deadline = time.monotonic() + WATCH_WAIT_SECS
    while not log.exists():
        if time.monotonic() > deadline:
            raise StageError(f"stage {stage['name']}: sandbox watcher did not acknowledge the stage boundary "
                             f"within {WATCH_WAIT_SECS} s")
        time.sleep(0.05)


def close_stage(stage, marker, *, work) -> None:
    """With a watcher up: leave the stage on the status file ('IDLE' is no stage name) and wait until the watcher
    has written the stage's end line - every read of the stage is then in its log - and bind the log to the
    marker. No end line within WATCH_WAIT_SECS = the watcher is dead or stalled: AUDIT_LOST at once."""
    work = pathlib.Path(work)
    if not _watched(work):
        return
    _status_local(work, "IDLE")
    log, end = work / READS_DIR / f"{stage['name']}.tsv", f"{stage['name']}\t{END}"
    deadline = time.monotonic() + WATCH_WAIT_SECS
    while _last_line(log) != end:
        if time.monotonic() > deadline:
            raise StageError(f"AUDIT_LOST watcher: no end line on {READS_DIR}/{log.name} within {WATCH_WAIT_SECS} s")
        time.sleep(0.05)
    marker["reads_sha256"] = sha256_file(log)


def push(stage, marker, *, prefix, work, repo) -> None:
    base = f"{prefix}/stages/{stage['name']}"
    for tok in stage["outputs"]:
        local, key = resolve_out(tok, work=work, repo=repo), tok.replace(":", "/", 1)
        if local.is_dir():
            s3(["s3", "sync", "--only-show-errors", f"{local}/", f"{base}/files/{key}/"])
        else:
            s3(["s3", "cp", "--only-show-errors", str(local), f"{base}/files/{key}"])
    m = pathlib.Path(work) / "stages" / f"{stage['name']}.done.json"
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_text(json.dumps(marker, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    s3(["s3", "cp", "--only-show-errors", str(m), f"{prefix}/stages/{stage['name']}.done.json"])


def _json_or_empty(p) -> dict:
    if p is None or not pathlib.Path(p).is_file():
        return {}
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))


def restore(stage, marker, *, resume_dir, work, repo) -> bool:
    """Copy the prior job's products into place; True iff every digest matches its marker. While a watcher audits
    this job, the stage's prior read log (<resume>/_reads/<stage>.tsv) must also equal the marker's reads_sha256;
    it is then copied into WORK/reads/, so the stage keeps exactly that audit (J0 review #5)."""
    log = pathlib.Path(resume_dir) / "_reads" / f"{stage['name']}.tsv"
    want = marker.get("reads_sha256")
    if _watched(work) and not (want and log.is_file() and sha256_file(log) == want):
        return False
    base = pathlib.Path(resume_dir) / stage["name"] / "files"
    for tok in stage["outputs"]:
        src, dst = base / tok.replace(":", "/", 1), resolve_out(tok, work=work, repo=repo)
        if dst.is_dir():
            shutil.rmtree(dst)
        elif dst.exists():
            dst.unlink()
        if src.is_dir():
            shutil.copytree(src, dst)
        elif src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        else:
            return False
        if digest_of(dst) != marker["outputs"].get(tok):
            return False
    if _watched(work):
        live = pathlib.Path(work) / READS_DIR / log.name
        live.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(log, live)
    return True


def run_one(stage, *, repo, commit, work, out, fp) -> dict:
    t0 = time.time()
    if stage.get("script"):
        dst = work / pathlib.Path(stage["script"]).name
        dst.write_text(git(repo, "show", f"{commit}:{stage['script']}") + "\n", encoding="utf-8")
    for tok in stage["outputs"]:
        p = resolve_out(tok, work=work, repo=repo)
        shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)
    stage_out = work / "prod" / stage["name"]
    stage_out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PY=os.environ.get("PY", sys.executable), REPO_DIR=str(repo), COMMIT=commit,
               WORK=str(work), STAGE_OUT=str(stage_out))
    with open(out / "logs" / f"{stage['name']}.log", "w", encoding="utf-8") as log:
        rc = subprocess.run(["bash", "-c", stage["cmd"]], cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    if rc:
        raise StageError(f"rc={rc}")
    outs = {tok: digest_of(resolve_out(tok, work=work, repo=repo)) for tok in stage["outputs"]}
    return {"schema": "sar.r1.stage_done.v1", "stage": stage["name"], "fingerprint": fp, "outputs": outs,
            "outputs_digest": hashlib.sha256(json.dumps(outs, sort_keys=True).encode()).hexdigest(),
            "secs": round(time.time() - t0), "commit": commit}


#: report keys whose value may reach the Mac as written (S3 -> Mac: ids, counts, codes; never person names)
NAME_FREE_KEYS = frozenset(("path", "rule", "verdict", "status", "mode", "label", "columns", "counts", "codes", "ids",
                            "worst_ulp", "result", "gate", "stage", "code", "commit", "secs", "missing", "changed"))
NAME_FREE_PREFIXES = ("rows_", "n_")
#: an OpenAlex author id ('A' or 'P_A' + 6-12 digits), optionally ':' + a year/school suffix
OPENALEX_ID = re.compile(r"^(P_)?A\d{6,12}(:[a-z0-9_]+)?$")
#: a dict key that cannot be a person's name: lower-case tokens (fields, stages, codes) and cell labels (P1_econ ...)
SAFE_KEY = re.compile(r"^([a-z0-9][a-z0-9_.-]{0,63}|P\d[A-Za-z0-9_]{0,63})$")
_DROP = object()


def _whitelisted(key) -> bool:
    return key is not None and (key in NAME_FREE_KEYS or key.startswith(NAME_FREE_PREFIXES))


def _name_free(v, key):
    """key: the dict key that holds v (None inside a list or at the top)."""
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            k = str(k)
            if not (_whitelisted(k) or OPENALEX_ID.match(k) or SAFE_KEY.match(k)):
                continue                           # a key that could be a name goes with its value
            y = _name_free(x, k)
            if y is _DROP or (isinstance(y, (dict, list)) and not y and x):
                continue                           # nothing but names was in it
            out[k] = y
        return out
    if isinstance(v, list):
        return [y for y in (_name_free(x, key) for x in v) if y is not _DROP]
    if isinstance(v, str):
        if not _whitelisted(key) or (key == "ids" and not OPENALEX_ID.match(v)):
            return _DROP
        return v
    return v                                       # numbers, booleans, null


def name_free(obj):
    """What of a stage report may reach summary.json (S3 -> Mac: never person names). A string survives only
    under a whitelisted key (NAME_FREE_KEYS, rows_*, n_*), and under 'ids' only as an OpenAlex id; a dict keeps
    only whitelisted, id-shaped or safe (lower-case token / cell label) keys; a container emptied by the drop
    is dropped too. Numbers, booleans and null pass. A bare string gives None."""
    y = _name_free(obj, None)
    return None if y is _DROP else y


#: STAGE_OUT reports that reach summary.json: cells reports as written (labels, statuses), the rest name-free
RAW_REPORTS = ("cells_report_*.json",)
NAME_FREE_REPORTS = ("gate_report_*.json", "report_*.json", "stop_report_*.json", "final_report_*.json")


def _reports(work, name) -> dict:
    """Small machine-readable reports a stage leaves in its STAGE_OUT: into summary.json (also for a failed stage,
    so a STOP's ids reach the Mac)."""
    out, d = {}, pathlib.Path(work) / "prod" / name
    for pats, clean in ((RAW_REPORTS, lambda x: x), (NAME_FREE_REPORTS, name_free)):
        for p in sorted(q for pat in pats for q in d.glob(pat)):
            try:
                out[p.name] = clean(json.loads(p.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                out[p.name] = "unreadable"
    return out


def sync_reads(*, prefix, work) -> None:
    """The sandbox watcher's read logs (WORK/reads/<stage>.tsv) to <prefix>/stages/_reads/ after every pushed
    stage; a --resume-from pull of stages/ brings them back as /work/resume/_reads for sandbox_check (F2)."""
    reads = pathlib.Path(work) / "reads"
    if reads.is_dir():
        s3(["s3", "sync", "--only-show-errors", f"{reads}/", f"{prefix}/stages/_reads/"])


def _manifest(out) -> None:
    """out/MANIFEST.sha256 over every file in out/ (r1kit fetch --author-ok needs it)."""
    out = pathlib.Path(out)
    rows = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256")
    (out / "MANIFEST.sha256").write_text("".join(f"{sha256_file(p)}  {p.relative_to(out).as_posix()}\n" for p in rows),
                                         encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 multi-stage driver")
    for k in ("--table", "--repo", "--commit", "--prefix", "--work", "--out"):
        ap.add_argument(k, required=True)
    ap.add_argument("--pins")
    ap.add_argument("--env-pins")
    ap.add_argument("--resume-dir")
    a = ap.parse_args(argv)
    if os.environ.get("SAR_HOST", "").strip() not in HOSTS:
        raise SystemExit("R1 rule: run_stages.py runs only on an R1 instance ($SAR_HOST)")
    if not PREFIX.match(a.prefix):
        raise SystemExit(f"refusing prefix {a.prefix!r}: pushes go only to s3://<bucket>/r1/runs/<job>")
    repo, work, out = pathlib.Path(a.repo), pathlib.Path(a.work), pathlib.Path(a.out)
    (out / "logs").mkdir(parents=True, exist_ok=True)
    table = load_table(a.table)
    pins = _json_or_empty(a.pins or repo / "config" / "r1" / "input_pins.json")
    env_pins = _json_or_empty(a.env_pins or repo / "config" / "r1" / "env_pins.json")
    done, rows, result, reports = {}, [], "OK", {}
    for st in table["stages"]:
        try:
            fp = fingerprint(st, repo=repo, commit=a.commit, pins=pins, env_pins=env_pins, done=done)
            mk = pathlib.Path(a.resume_dir) / f"{st['name']}.done.json" if a.resume_dir else None
            if mk and mk.is_file() and st.get("resume") != "always":     # input custody reruns on every instance
                prior = json.loads(mk.read_text(encoding="utf-8"))
                if prior.get("fingerprint") == fp and restore(st, prior, resume_dir=a.resume_dir, work=work, repo=repo):
                    push(st, prior, prefix=a.prefix, work=work, repo=repo)
                    sync_reads(prefix=a.prefix, work=work)
                    done[st["name"]] = prior
                    rows.append({"stage": st["name"], "status": "skipped", "secs": 0, "fp16": fp[:16]})
                    reports[st["name"]] = _reports(work, st["name"])
                    continue
            status(a.prefix, f"STAGE {st['name']}", work)
            ack_stage(st, work=work)                                   # F2: the watcher has taken in the boundary
            marker = run_one(st, repo=repo, commit=a.commit, work=work, out=out, fp=fp)
            close_stage(st, marker, work=work)                         # F2: the stage's audit is complete
            push(st, marker, prefix=a.prefix, work=work, repo=repo)
            sync_reads(prefix=a.prefix, work=work)
            done[st["name"]] = marker
            rows.append({"stage": st["name"], "status": "ran", "secs": marker["secs"], "fp16": fp[:16]})
            reports[st["name"]] = _reports(work, st["name"])
        except (StageError, OSError) as e:
            rows.append({"stage": st["name"], "status": "failed", "why": str(e)[:300]})
            result = f"STAGE_FAIL {st['name']} {str(e)[:120]}"
            reports[st["name"]] = _reports(work, st["name"])           # a STOP's ids (stop_report_*) reach the Mac
            break
    (out / "RESULT.txt").write_text(result + "\n", encoding="utf-8")
    (out / "summary.json").write_text(json.dumps({"table": table["job"], "commit": a.commit, "stages": rows,
                                                  "result": result.split()[0],
                                                  "reports": {k: v for k, v in reports.items() if v}},
                                                 indent=1) + "\n", encoding="utf-8")
    _manifest(out)
    return 0 if result == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
