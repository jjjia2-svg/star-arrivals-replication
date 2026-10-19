# -*- coding: utf-8 -*-
"""Shared fakes for the R1 kit tests: a fake `aws` CLI backed by a local directory (not collected)."""
from __future__ import annotations

import json
import os
import pathlib
import stat
import sys

FAKE_AWS = r'''#!/usr/bin/env python3
import fnmatch, json, os, pathlib, shutil, sys
args = sys.argv[1:]
with open(os.environ["FAKE_AWS_LOG"], "a") as fh:
    fh.write(json.dumps(args) + "\n")
root = pathlib.Path(os.environ["FAKE_S3_ROOT"])
VALUED = {"--exclude", "--include", "--region", "--query", "--output", "--instance-ids", "--filters"}
if os.environ.get("FAKE_FAIL_WITH_ARGS"):                 # an AWS error that echoes its arguments
    sys.stderr.write("An error occurred: " + " ".join(args) + "\n"); sys.exit(255)

def split(argv):
    pos, opts, i = [], {}, 0
    while i < len(argv):
        a = argv[i]
        if a in VALUED:
            opts.setdefault(a, []).append(argv[i + 1]); i += 2; continue
        if a.startswith("--"):
            opts.setdefault(a, []).append(True); i += 1; continue
        pos.append(a); i += 1
    return pos, opts

def s3(u):
    assert u.startswith("s3://"), u
    return root / u[5:]

def copy_tree(src, dst, opts):
    for f in sorted(src.rglob("*")):
        if f.is_file():
            rel = f.relative_to(src).as_posix()
            if any(fnmatch.fnmatch(rel, p) for p in opts.get("--exclude", [])):
                continue
            t = dst / rel
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, t)

if args[:1] == ["s3"] and len(args) > 1 and args[1] in ("cp", "sync"):
    pos, opts = split(args[2:])
    src, dst = pos[0], pos[1]
    if src.startswith("s3://") and dst == "-":
        p = s3(src)
        if not p.is_file():
            sys.stderr.write("NoSuchKey\n"); sys.exit(1)
        sys.stdout.write(p.read_text()); sys.exit(0)
    s = s3(src) if src.startswith("s3://") else pathlib.Path(src)
    d = s3(dst) if dst.startswith("s3://") else pathlib.Path(dst)
    if args[1] == "sync" or "--recursive" in opts:
        if not s.is_dir():
            sys.exit(0 if args[1] == "sync" else 1)
        copy_tree(s, d, opts); sys.exit(0)
    if not s.is_file():
        sys.stderr.write("NoSuchKey\n"); sys.exit(1)
    if dst.endswith("/"):
        d = d / s.name
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(s, d); sys.exit(0)
if args[:2] == ["ec2", "run-instances"]:
    print(os.environ.get("FAKE_INSTANCE_ID", "i-0fake0000000000001")); sys.exit(0)
if args[:2] == ["ec2", "describe-instances"]:
    pos, opts = split(args[2:])
    if "--filters" not in opts and os.environ.get("FAKE_DESCRIBE_GONE"):
        sys.stderr.write("An error occurred (InvalidInstanceID.NotFound) when calling the DescribeInstances operation\n")
        sys.exit(254)
    print(os.environ.get("FAKE_LIVE", "") if "--filters" in opts else os.environ.get("FAKE_DESCRIBE", ""))
    sys.exit(0)
if args[:2] == ["ec2", "terminate-instances"]:
    print("{}"); sys.exit(0)
sys.exit(0)
'''


def install_fake_aws(tmp_path: pathlib.Path, monkeypatch) -> dict:
    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    aws = bindir / "aws"
    aws.write_text(FAKE_AWS.replace("#!/usr/bin/env python3", "#!" + sys.executable, 1), encoding="utf-8")
    aws.chmod(aws.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    s3root = tmp_path / "fakes3"
    s3root.mkdir()
    log = tmp_path / "aws_calls.jsonl"
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_S3_ROOT", str(s3root))
    monkeypatch.setenv("FAKE_AWS_LOG", str(log))
    for k in ("FAKE_LIVE", "FAKE_DESCRIBE", "FAKE_INSTANCE_ID", "FAKE_DESCRIBE_GONE", "FAKE_FAIL_WITH_ARGS"):
        monkeypatch.delenv(k, raising=False)
    return {"s3root": s3root, "log": log}


def aws_calls(log: pathlib.Path) -> list:
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
