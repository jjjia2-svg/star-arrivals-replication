#!/usr/bin/env python3
"""R1 input checks on an instance (P3b V3-UP / F25 verify_inputs). Standard library only.

  verify_inputs.py pin --bucket S3URL --inventory TSV --repo DIR --work DIR --out DIR --job JOB
      job kind 'pin': sync every prefix of the inventory's data_sync pairs, write a content manifest for
      each, and summary.json = the pins file (schema sar.r1.input_pins.v1). Never writes S3 itself.
  verify_inputs.py data --job-spec JSON --pins JSON --out DIR
      every data_sync destination of a job against its pin (files, bytes, manifest sha256); nested
      destinations are left out of the outer one. Prints VERIFY_OK n or VERIFY_FAIL lines.
  verify_inputs.py recovered --dir DIR --pins JSON
      every row of DIR/manifest.tsv against the file on disk, and manifest.tsv against its git pin.
  verify_inputs.py relink --map TSV --root DIR --old PREFIX --new PREFIX
      recreate the symlinks an upload skipped (tools/r1_upload_once.py, not shipped, writes the map: rel, target), with the
      data-disk prefix OLD mapped to NEW; a target outside OLD or missing under NEW fails. Read-only folders
      are opened for the links and closed again.
Runs only on an R1 instance ($SAR_HOST), from its copy under /work/.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys

HOSTS = ("ec2-r1-test", "ec2-r1")


def sha256_file(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_of_dir(root, exclude=(), workers=None) -> dict:
    root = pathlib.Path(root)
    skip = {pathlib.Path(x).resolve() for x in exclude}
    rows = []
    for dirpath, dirnames, filenames in os.walk(root):
        d = pathlib.Path(dirpath)
        for n in list(dirnames):
            p = d / n
            if p.is_symlink():
                raise SystemExit(f"symlink in a pinned folder: {p}")
            if p.resolve() in skip:
                dirnames.remove(n)
        for n in filenames:
            p = d / n
            if p.is_symlink():
                raise SystemExit(f"symlink in a pinned folder: {p}")
            rows.append((p.relative_to(root).as_posix(), p))
    rows.sort(key=lambda r: r[0])
    with cf.ThreadPoolExecutor(workers or os.cpu_count() or 4) as ex:
        shas = list(ex.map(lambda r: sha256_file(r[1]), rows))
    text = "".join(f"{s}  {rel}\n" for (rel, _), s in zip(rows, shas))
    return {"files": len(rows), "bytes": sum(p.stat().st_size for _, p in rows),
            "manifest_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "text": text}


def _pin(a) -> int:
    sys.path.insert(0, str(pathlib.Path(a.repo) / "tools"))
    import r1_input_inventory as inv  # noqa: PLC0415
    pairs = inv.all_sync_pairs(inv.read_tsv(a.inventory))
    work, out = pathlib.Path(a.work), pathlib.Path(a.out)
    (out / "manifests").mkdir(parents=True, exist_ok=True)
    pins = {}
    for src, _dest in pairs:
        cur = work / "cur"
        shutil.rmtree(cur, ignore_errors=True)
        cur.mkdir(parents=True)
        subprocess.run(["aws", "s3", "sync", "--only-show-errors", f"{a.bucket.rstrip('/')}/{src}", f"{cur}/"], check=True)
        m = manifest_of_dir(cur)
        if m["files"] == 0:
            raise SystemExit(f"nothing under {src}")
        (out / "manifests" / (src.replace("/", "__") + ".sha256")).write_text(m["text"], encoding="utf-8")
        pins[src] = {k: m[k] for k in ("files", "bytes", "manifest_sha256")}
        shutil.rmtree(cur, ignore_errors=True)
    (out / "summary.json").write_text(json.dumps({"schema": "sar.r1.input_pins.v1", "pin_job": a.job, "pins": pins},
                                                 indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "RESULT.txt").write_text("OK\n", encoding="utf-8")
    print(f"PINNED {len(pins)}")
    return 0


def _data(a) -> int:
    spec = json.loads(pathlib.Path(a.job_spec).read_text(encoding="utf-8"))
    pins = json.loads(pathlib.Path(a.pins).read_text(encoding="utf-8")).get("pins", {})
    pairs = [(s, d) for s, d in spec.get("data_sync", [])]
    report, bad = {}, []
    for src, dest in pairs:
        if src not in pins:
            bad.append(f"{src}: no pin in config/r1/input_pins.json")
            report[src] = {"ok": False}
            continue
        nested = [d for s, d in pairs if d != dest and d.startswith(dest)]
        m = manifest_of_dir(dest, exclude=nested)
        got = {k: m[k] for k in ("files", "bytes", "manifest_sha256")}
        ok = all(got[k] == pins[src][k] for k in got)
        report[src] = {"ok": ok, **got}
        if not ok:
            bad.append(f"{src}: files {got['files']}/{pins[src]['files']} bytes {got['bytes']}/{pins[src]['bytes']} "
                       f"manifest {got['manifest_sha256'][:12]}/{pins[src]['manifest_sha256'][:12]}")
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "verify_inputs.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for line in bad:
        print("VERIFY_FAIL " + line)
    if not bad:
        print(f"VERIFY_OK {len(pairs)}")
    return 1 if bad else 0


def _recovered(a) -> int:
    d = pathlib.Path(a.dir)
    pins = json.loads(pathlib.Path(a.pins).read_text(encoding="utf-8"))
    bad = []
    man = d / "manifest.tsv"
    if not man.is_file() or sha256_file(man) != pins.get("manifest.tsv"):
        bad.append("manifest.tsv: missing or differs from its git pin")
    rows = list(csv.DictReader(open(man, encoding="utf-8", newline=""), delimiter="\t")) if man.is_file() else []
    for r in rows:
        # recover_rk.manifest_rows(): launch-side files are run 'kit', part 'launch_side', stored at <dir>/launch_side/
        p = (d / r["part"] / r["member"]) if r["run"] == "kit" else (d / r["run"] / r["part"] / r["member"])
        if not p.is_file() or sha256_file(p) != r["sha256"]:
            bad.append(f"{r['run']}/{r['part']}/{r['member']}: missing or sha differs")
    for line in bad:
        print("RECOVERED_FAIL " + line)
    if not bad:
        print(f"RECOVERED_OK {len(rows)}")
    return 1 if bad else 0


def _relink(a) -> int:
    old, new, root = a.old.rstrip("/"), a.new.rstrip("/"), pathlib.Path(a.root)
    with open(a.map, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    bad, made, opened = [], 0, {}

    def writable(d):
        chain = []
        while True:
            chain.append(d)
            if d == root or root not in d.parents:
                break
            d = d.parent
        for x in reversed(chain):
            if x.exists() and not os.access(x, os.W_OK):
                opened.setdefault(x, x.stat().st_mode & 0o7777)
                x.chmod(opened[x] | 0o200)

    try:
        for r in rows:
            t = r["target"]
            if not t.startswith(old + "/"):
                bad.append(f"{r['rel']}: target outside {old}")
                continue
            nt = new + t[len(old):]
            if not os.path.exists(nt):
                bad.append(f"{r['rel']}: target missing {nt}")
                continue
            link = root / r["rel"]
            if link.is_symlink() and os.readlink(link) == nt:
                continue
            if link.exists() or link.is_symlink():
                bad.append(f"{r['rel']}: something else is in the way")
                continue
            try:
                anc = link.parent
                while not anc.exists() and anc != root:
                    anc = anc.parent
                writable(anc)                                   # open the nearest existing folder and its parents
                new_dirs = []
                d = link.parent
                while not d.exists():
                    new_dirs.append(d)
                    d = d.parent
                link.parent.mkdir(parents=True, exist_ok=True)
                for nd in new_dirs:                             # folders made here end read-only like the rest
                    opened.setdefault(nd, nd.stat().st_mode & 0o7777 & ~0o222)
                os.symlink(nt, link)
                made += 1
            except OSError as e:
                bad.append(f"{r['rel']}: {e.__class__.__name__}: {e}")
    finally:
        for d in sorted(opened, key=lambda x: len(x.parts), reverse=True):
            d.chmod(opened[d])
    for line in bad:
        print("RELINK_FAIL " + line)
    if not bad:
        print(f"RELINK_OK {made}")
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 input checks (instance)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pin")
    for n in ("--bucket", "--inventory", "--repo", "--work", "--out", "--job"):
        p.add_argument(n, required=True)
    d = sub.add_parser("data")
    for n in ("--job-spec", "--pins", "--out"):
        d.add_argument(n, required=True)
    r = sub.add_parser("recovered")
    for n in ("--dir", "--pins"):
        r.add_argument(n, required=True)
    rl = sub.add_parser("relink")
    for n in ("--map", "--root", "--old", "--new"):
        rl.add_argument(n, required=True)
    a = ap.parse_args(argv)
    if os.environ.get("SAR_HOST", "").strip() not in HOSTS:
        raise SystemExit("R1 rule: verify_inputs.py runs only on an R1 instance ($SAR_HOST)")
    return {"pin": _pin, "data": _data, "recovered": _recovered, "relink": _relink}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
