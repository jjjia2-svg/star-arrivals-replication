#!/usr/bin/env python3
"""Lay out an upstream job's stage products, digest-checked (V3-FINAL; used by J1b restore_j1a and FINAL canon).
Runs on an R1 instance only. Standard library only.

  restore_upstream.py --stages [JOB=]DIR [--stages JOB=DIR]... --layout LAYOUT.json --dest DIR --out STAGE_OUT
                      [--repo DIR] [--manifest]

--stages is a pulled stage set (r1/runs/<job>/stages/ -> DIR: <stage>.done.json markers and <stage>/files/<kind>/
<path>, as run_stages.push writes them). One plain DIR serves a layout that names a single job; with several
upstream jobs each set is given as JOB=DIR.

LAYOUT.json: {"schema": "sar.r1.layout.v1", "rows": [...]} (a bare list of rows is accepted too). A row is
  {"dest": REL, "from": {"job": J, "stage": S, "token": "work:prod/x" | "repo:path", "rel": REL-or-""}}
  {"dest": REL, "from": {"repo": PATH}}            (a carried file from the checkout; needs --repo)
For every (job, stage, token) a row uses, run_stages.digest_of over DIR/<stage>/files/<kind>/<path> must equal
DIR/<stage>.done.json outputs[token]. Only when every row has passed are the files copied: <rel> inside the token
(the whole token when rel is "") to <dest>/<REL>. Nothing is ever overwritten. --manifest writes
<dest>/<top dir>/MANIFEST.sha256 for each top dir that has none yet. Writes STAGE_OUT/report_restore.json
(result, code, counts; name-free) and exits 1 with a code on any refusal: BAD_ROW, BAD_PATH, MISSING_MARKER,
MISSING_TOKEN, MISSING_FILE, DIGEST_MISMATCH, DEST_EXISTS.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys

HOSTS = ("ec2-r1-test", "ec2-r1")
HERE = pathlib.Path(__file__).resolve().parent
for _p in (HERE, pathlib.Path(os.environ.get("REPO_DIR", "/nonexistent")) / "pipeline" / "aws" / "r1"):
    if (_p / "run_stages.py").is_file() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import run_stages as rs    # noqa: E402


class Refused(RuntimeError):
    def __init__(self, code, why, **detail):
        super().__init__(f"{code}: {why}")
        self.code, self.detail = code, detail


def _rel(p, what) -> pathlib.PurePosixPath:
    """A relative path that stays inside its root ('' allowed only where the caller says so)."""
    p = str(p)
    q = pathlib.PurePosixPath(p)
    if p.startswith("/") or q.is_absolute() or ".." in q.parts or "\\" in p:
        raise Refused("BAD_PATH", f"{what} {p!r} must be relative and stay inside its root")
    return q


def load_rows(path) -> list:
    t = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    rows = t.get("rows") if isinstance(t, dict) else t
    if isinstance(t, dict) and t.get("schema", "sar.r1.layout.v1") != "sar.r1.layout.v1":
        raise Refused("BAD_ROW", f"layout schema {t.get('schema')!r}")
    if not isinstance(rows, list) or not rows:
        raise Refused("BAD_ROW", "the layout has no rows")
    return rows


def stage_dirs(specs) -> dict:
    """{job: DIR} from JOB=DIR specs; a lone plain DIR maps to None (any one job)."""
    out = {}
    for s in specs:
        job, sep, d = s.partition("=")
        key, d = (job, d) if sep else (None, s)
        if (key is None and len(specs) > 1) or key in out or not d:
            raise Refused("BAD_ROW", "give one plain --stages DIR, or JOB=DIR once per upstream job")
        out[key] = pathlib.Path(d)
    return out


def plan(rows, sets, repo) -> tuple:
    """Every check, nothing copied: [(src, dest_rel)], the (job, stage, token)s checked, counts."""
    jobs = {r.get("from", {}).get("job") for r in rows if isinstance(r, dict) and "job" in r.get("from", {})}
    if None in sets:
        if len(jobs) > 1:
            raise Refused("BAD_ROW", f"one plain --stages DIR cannot serve the jobs {sorted(jobs)}")
        sets = {j: sets[None] for j in jobs}
    copies, checked, dests, n = [], {}, set(), {"stage_rows": 0, "repo_rows": 0}
    for i, r in enumerate(rows):
        if not isinstance(r, dict) or set(r) != {"dest", "from"} or not isinstance(r["from"], dict):
            raise Refused("BAD_ROW", f"row {i}: want {{dest, from}}", row=i)
        dest = _rel(r["dest"], f"row {i} dest")
        if not dest.parts or dest in dests or any(dest in (d, *d.parents) or d in dest.parents for d in dests):
            raise Refused("BAD_ROW", f"row {i}: dest {r['dest']!r} is empty or overlaps another row's", row=i)
        dests.add(dest)
        f = r["from"]
        if set(f) == {"repo"}:
            if repo is None:
                raise Refused("BAD_ROW", f"row {i}: a repo row needs --repo", row=i)
            src = pathlib.Path(repo) / _rel(f["repo"], f"row {i} repo")
            if not src.is_file():
                raise Refused("MISSING_FILE", f"row {i}: repo file {f['repo']} is absent", row=i, path=f["repo"])
            n["repo_rows"] += 1
            copies.append((src, dest))
            continue
        if not {"job", "stage", "token"} <= set(f) <= {"job", "stage", "token", "rel"}:
            raise Refused("BAD_ROW", f"row {i}: from wants job, stage, token, rel", row=i)
        if f["job"] not in sets:
            raise Refused("BAD_ROW", f"row {i}: no --stages set for job {f['job']!r}", row=i)
        m = rs.TOKEN.match(str(f["token"]))
        if not rs.NAME.match(str(f["stage"])) or not m or m.group(1) not in ("work", "repo"):
            raise Refused("BAD_ROW", f"row {i}: bad stage or token", row=i)
        root = sets[f["job"]] / f["stage"] / "files" / m.group(1) / _rel(m.group(2), f"row {i} token")
        key = (f["job"], f["stage"], f["token"])
        if key not in checked:
            mk = sets[f["job"]] / f"{f['stage']}.done.json"
            if not mk.is_file():
                raise Refused("MISSING_MARKER", f"row {i}: {f['job']}/{f['stage']}.done.json is absent", stage=f["stage"])
            want = json.loads(mk.read_text(encoding="utf-8")).get("outputs", {}).get(f["token"])
            if want is None:
                raise Refused("MISSING_TOKEN", f"row {i}: {f['token']} is not an output of {f['stage']}", stage=f["stage"])
            try:
                got = rs.digest_of(root)
            except rs.StageError:
                raise Refused("MISSING_FILE", f"row {i}: {f['token']} of {f['stage']} was not pulled",
                              stage=f["stage"]) from None
            if got != want:
                raise Refused("DIGEST_MISMATCH", f"row {i}: {f['token']} of {f['stage']} differs from its marker",
                              stage=f["stage"])
            checked[key] = got
        rel = str(f.get("rel", ""))
        src = root / _rel(rel, f"row {i} rel") if rel not in ("", ".") else root
        if not src.exists():
            raise Refused("MISSING_FILE", f"row {i}: {rel} is not inside {f['token']} of {f['stage']}", stage=f["stage"])
        n["stage_rows"] += 1
        copies.append((src, dest))
    return copies, checked, n


def _copy(src, dst) -> int:
    pairs = [(src, dst)] if src.is_file() else [(p, dst / p.relative_to(src)) for p in sorted(src.rglob("*"))
                                                 if p.is_file()]
    for s, d in pairs:
        if d.exists():
            raise Refused("DEST_EXISTS", f"{d} exists already")
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(s, d)
    return len(pairs)


def write_manifests(dest, tops) -> int:
    n = 0
    for top in sorted(tops):
        d = dest / top
        if not d.is_dir() or (d / "MANIFEST.sha256").exists():
            continue
        rows = sorted(p for p in d.rglob("*") if p.is_file())
        (d / "MANIFEST.sha256").write_text("".join(f"{rs.sha256_file(p)}  {p.relative_to(d).as_posix()}\n"
                                                   for p in rows), encoding="utf-8")
        n += 1
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="digest-checked layout of upstream stage products")
    ap.add_argument("--stages", action="append", required=True, metavar="[JOB=]DIR")
    for k in ("--layout", "--dest", "--out"):
        ap.add_argument(k, required=True)
    ap.add_argument("--repo")
    ap.add_argument("--manifest", action="store_true")
    a = ap.parse_args(argv)
    if os.environ.get("SAR_HOST", "").strip() not in HOSTS:
        raise SystemExit("R1 rule: restore_upstream.py runs only on an R1 instance ($SAR_HOST)")
    out, dest = pathlib.Path(a.out), pathlib.Path(a.dest)
    out.mkdir(parents=True, exist_ok=True)
    rep = {"schema": "sar.r1.restore.v1"}
    try:
        rows = load_rows(a.layout)
        copies, checked, n = plan(rows, stage_dirs(a.stages), a.repo)
        files = sum(_copy(src, dest / d) for src, d in copies)
        mans = write_manifests(dest, {d.parts[0] for _, d in copies}) if a.manifest else 0
        rep.update(result="OK", code="OK", counts={"rows": len(rows), **n, "tokens_checked": len(checked),
                                                   "files": files, "manifests": mans})
        rc = 0
    except Refused as e:
        rep.update(result="STOP", code=e.code, **{k: v for k, v in e.detail.items() if k in ("stage", "path")},
                   n_row=e.detail.get("row"))
        print(f"restore_upstream: {e}", file=sys.stderr)
        rc = 1
    (out / "report_restore.json").write_text(json.dumps(rep, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"restore_upstream: {rep['result']} {rep['code']} {json.dumps(rep.get('counts', {}), sort_keys=True)}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
