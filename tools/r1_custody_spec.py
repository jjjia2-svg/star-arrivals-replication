#!/usr/bin/env python3
"""Write a custody record: the proof that ties each gold estimate to the exact inputs its cell read.

This script only assembles the record. The check is tools/verify_cloud_custody.py, unedited:

  r1_custody_spec.py --cells M.tsv M_evcl.tsv --reports DIR... --est DIR... --frames-dir <T>/frames
                     --gold-dir <T>/expected --drivers-root <repo> --marker <job>/out/RESULT.txt --out CUSTODY_DIR
                     [--stack rcloud] [--relative-to <repo>]
  verify_cloud_custody.py --custody CUSTODY_DIR --spec CUSTODY_DIR/custody_r1.json     -> CUSTODY_OK

--cells        the gold-row cell lists (columns label driver frame ref out_name stack; every row is a gold row).
--stack S      keep only the rows whose stack is S. rcloud = the four large Panel 3 cells, which the default
               run checks against this record instead of re-running them. Default: every row.
--reports      directories holding run_cells' cells_report_<stack>.json; each entry carries
               inputs = {frame, ref|null, driver}: {name, sha256, md5}, hashed just before the R call.
--est          the cell stages' output directories (run_cells --out: the JSON is at DIR/estimates/<out_name>;
               a directory that holds <out_name> directly is accepted too).
--relative-to  write every local path relative to this repository root, for a record committed in the
               repository and checked from its root. Every path must lie inside it. Default: absolute paths.

Writes, into a new or empty --out only, and only after every check has passed (nothing on a refusal):
  payload.md5      '<md5>  <name>' per distinct frame, driver and ref basename, the md5 taken FROM THE CELLS'
                   OWN RECORDS (never recomputed here: a re-hash would make the check circular)
  fetch/<out_name> byte copies of every gold row's cell output;  fetch/RESULT.txt  a copy of --marker
  custody_r1.json  {task 'r1 rebuild custody', ok true, verify {frame_pairs [[local, name]] for the frames
                   <T>/frames/X, the drivers <repo>/<driver> and the refs <T>/expected/<ref>;
                   fetched_pairs [[out_name, out_name]]; gold_dir <T>/expected; require_marker 'OK'}}
verify_cloud_custody then md5s every local file against payload.md5 (the local bytes must be the bytes the cells
read), compare_json-checks every fetched cell output against <T>/expected (the gold is the cell output) and
asserts the job marker is OK. verify_block joins its ROOT with each path: an absolute path ignores ROOT, a
repo-relative one resolves against the root of the repository that holds the verifier (or --root). The verifier
opens --spec from the current directory, so check a repo-relative record from the repository root.

Refusal codes (exit 1, stderr 'REFUSED <code> ...'): BAD_CELLS, MISSING_RECORD, NAME_MISMATCH, CELL_FAILED,
TWO_MD5, MISSING_ESTIMATE, AMBIGUOUS_ESTIMATE, MISSING_MARKER, OUT_EXISTS, NOT_IN_REPO. Standard library only;
reads no frame.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import shutil
import sys

TASK = "r1 rebuild custody"
MARKER_OK = "OK"
COLUMNS = ("label", "driver", "frame", "ref", "out_name", "stack")
ROLES = ("frame", "driver", "ref")


class Refused(RuntimeError):
    def __init__(self, code: str, why: str):
        super().__init__(f"{code} {why}")
        self.code = code


def read_cells(paths, stack: str | None = None) -> list[dict]:
    """The gold rows of the cell lists; with `stack`, only that stack's rows (duplicates are checked over all)."""
    rows, labels, outs = [], set(), set()
    for p in paths:
        with open(p, encoding="utf-8", newline="") as fh:
            rd = csv.DictReader(fh, delimiter="\t")
            missing = [c for c in COLUMNS if c not in (rd.fieldnames or [])]
            if missing:
                raise Refused("BAD_CELLS", f"{pathlib.Path(p).name}: no column {missing}")
            for r in rd:
                if r["label"] in labels or r["out_name"] in outs:
                    raise Refused("BAD_CELLS", f"duplicate label or out_name {r['label']} / {r['out_name']}")
                labels.add(r["label"])
                outs.add(r["out_name"])
                rows.append({c: r[c] for c in COLUMNS})
    if stack is not None:
        rows = [r for r in rows if r["stack"] == stack]
    if not rows:
        raise Refused("BAD_CELLS", "no cell rows" + ("" if stack is None else f" with stack {stack}"))
    return rows


def local_path(path: pathlib.Path, repo: pathlib.Path | None) -> str:
    """The path as the record writes it: absolute, or relative to `repo` (POSIX form) when one is given."""
    p = path.resolve()
    if repo is None:
        return str(p)
    try:
        return p.relative_to(repo).as_posix()
    except ValueError:
        raise Refused("NOT_IN_REPO", f"{p} is not inside --relative-to {repo}") from None


def read_reports(dirs) -> dict[str, dict]:
    """label -> report entry over every cells_report_*.json; one label in two reports must agree on its inputs."""
    entries: dict[str, dict] = {}
    for d in dirs:
        for p in sorted(pathlib.Path(d).glob("cells_report_*.json")):
            for label, entry in json.loads(p.read_text(encoding="utf-8")).items():
                if label in entries and entries[label].get("inputs") != entry.get("inputs"):
                    raise Refused("MISSING_RECORD", f"{label}: two reports record different inputs")
                entries.setdefault(label, entry)
    return entries


def find_estimate(est_dirs, out_name) -> pathlib.Path:
    hits = []
    for d in est_dirs:
        for c in (pathlib.Path(d) / "estimates" / out_name, pathlib.Path(d) / out_name):
            if c.is_file() and c.resolve() not in {h.resolve() for h in hits}:
                hits.append(c)
    if not hits:
        raise Refused("MISSING_ESTIMATE", f"no cell output {out_name} under --est")
    if len({h.read_bytes() for h in hits}) > 1:
        raise Refused("AMBIGUOUS_ESTIMATE", f"{out_name}: {len(hits)} different cell outputs under --est")
    return hits[0]


def build(rows, reports, *, est_dirs, frames_dir, gold_dir, drivers_root, repo=None) -> tuple[dict, list, list]:
    """(payload {basename: md5}, frame_pairs, fetched [(out_name, source path)]), or Refused. With `repo` (a
    resolved path), the frame_pairs paths are relative to it."""
    payload: dict[str, str] = {}
    pairs: list[list[str]] = []
    fetched = []
    local_of = {"frame": lambda n: frames_dir / n, "driver": lambda n: drivers_root / n, "ref": lambda n: gold_dir / n}
    for r in rows:
        entry = reports.get(r["label"])
        if not isinstance(entry, dict) or not isinstance(entry.get("inputs"), dict):
            raise Refused("MISSING_RECORD", f"{r['label']}: no cell report entry with an inputs record")
        if entry.get("status") == "FAIL" or entry.get("rc") not in (0, None):
            raise Refused("CELL_FAILED", f"{r['label']}: status {entry.get('status')} rc {entry.get('rc')}")
        for role in ROLES:
            want = r[role]
            rec = entry["inputs"].get(role)
            if role == "ref" and want == "-":
                if rec is not None:
                    raise Refused("NAME_MISMATCH", f"{r['label']}: a ref record but the cell list names none")
                continue
            if not isinstance(rec, dict) or not rec.get("md5"):
                raise Refused("MISSING_RECORD", f"{r['label']}: no {role} md5 recorded at cell time")
            if rec.get("name") != want:
                raise Refused("NAME_MISMATCH", f"{r['label']}: {role} record {rec.get('name')!r} != cell list {want!r}")
            base = pathlib.PurePosixPath(want).name
            if payload.setdefault(base, rec["md5"]) != rec["md5"]:
                raise Refused("TWO_MD5", f"payload name {base} has two md5s across the cells")
            pair = [local_path(local_of[role](want), repo), base]
            if pair not in pairs:
                pairs.append(pair)
        fetched.append((r["out_name"], find_estimate(est_dirs, r["out_name"])))
    return payload, pairs, fetched


def write(out: pathlib.Path, *, payload, pairs, fetched, marker, gold_dir, cells_paths, stack=None,
          relative=False) -> dict:
    (out / "fetch").mkdir(parents=True, exist_ok=True)
    (out / "payload.md5").write_text("".join(f"{h}  {n}\n" for n, h in sorted(payload.items())), encoding="utf-8")
    for name, src in fetched:
        shutil.copyfile(src, out / "fetch" / name)
    shutil.copyfile(marker, out / "fetch" / "RESULT.txt")
    spec = {"task": TASK, "ok": True,
            "verify": {"frame_pairs": pairs, "fetched_pairs": [[n, n] for n, _ in fetched],
                       "gold_dir": str(gold_dir), "require_marker": MARKER_OK},
            "n_cells": len(fetched), "n_payload": len(payload),
            "cells_tsv_sha256": {pathlib.Path(p).name: hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
                                 for p in cells_paths},
            "payload_md5_source": "run_cells inputs records (cells_report_<stack>.json), not recomputed"}
    if stack is not None:
        spec["stack"] = stack
    if relative:
        spec["paths"] = "relative to the repository root"
    (out / "custody_r1.json").write_text(json.dumps(spec, indent=1) + "\n", encoding="utf-8")
    return spec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Write a custody record for cells that are checked, not re-run")
    ap.add_argument("--cells", nargs="+", required=True)
    ap.add_argument("--reports", nargs="+", required=True)
    ap.add_argument("--est", nargs="+", required=True)
    for k in ("--frames-dir", "--gold-dir", "--drivers-root", "--marker", "--out"):
        ap.add_argument(k, required=True)
    ap.add_argument("--stack", default=None, help="keep only the cell rows of this stack (default: every row)")
    ap.add_argument("--relative-to", default=None, metavar="REPO",
                    help="write local paths relative to this repository root (default: absolute)")
    a = ap.parse_args(argv)
    out = pathlib.Path(a.out)
    repo = pathlib.Path(a.relative_to).resolve() if a.relative_to is not None else None
    try:
        if out.exists() and (not out.is_dir() or any(out.iterdir())):
            raise Refused("OUT_EXISTS", f"{out} exists and is not an empty directory")
        marker = pathlib.Path(a.marker)
        if not marker.is_file():
            raise Refused("MISSING_MARKER", f"no job marker {marker}")
        gold_dir = pathlib.Path(a.gold_dir).resolve()
        rows = read_cells(a.cells, stack=a.stack)
        payload, pairs, fetched = build(rows, read_reports(a.reports), est_dirs=a.est,
                                        frames_dir=pathlib.Path(a.frames_dir), gold_dir=gold_dir,
                                        drivers_root=pathlib.Path(a.drivers_root), repo=repo)
        gold_rec = local_path(gold_dir, repo)
    except Refused as e:
        print(f"REFUSED {e}", file=sys.stderr)
        return 1
    spec = write(out, payload=payload, pairs=pairs, fetched=fetched, marker=marker, gold_dir=gold_rec,
                 cells_paths=a.cells, stack=a.stack, relative=repo is not None)
    print(f"CUSTODY_SPEC_WRITTEN n_cells={spec['n_cells']} n_payload={spec['n_payload']} -> {out / 'custody_r1.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
