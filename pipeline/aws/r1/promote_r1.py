#!/usr/bin/env python3
"""R1 promotion (F4, J1a stage `promote`): package J1a's assembled M frames and the gold-row cell
estimates into one promoted layout with MANIFESTs and a refreeze record, then gate it (post-promotion
custody, part of gate 1's custody concept, not a third gate). Runs on an R1 instance only ($SAR_HOST).

October's pipeline/frames/cal2026-10/promote.py is NOT used and NOT touched: moving M into data/frames
and analysis/expected stays the author's call after P5. This script writes only under --out.

  promote_r1.py run   --frames DIR --estimates DIR [DIR ...] --cells M.tsv M_evcl.tsv
                      --october-golds /work/ref/october/analysis/expected
                      --october-frames /work/ref/october/data/frames --out $STAGE_OUT
  promote_r1.py check --frames DIR --estimates DIR [DIR ...] --cells M.tsv M_evcl.tsv --out $STAGE_OUT

run writes
  <out>/frames/            byte copies of every file in --frames (the assembled M frames; the source
                           MANIFEST.sha256 must describe exactly those files) + MANIFEST.sha256
  <out>/expected/          the gold-row cell JSONs under their out_name + MANIFEST.sha256 + SOURCES.md
                           (tools/freeze_expected.main's logic, parameterised; that tool is never run
                           and its EXPECTED list is never rewritten)
  <out>/expected_refreeze_r1.json
                           {frames: {X: {october_sha256, new_sha256}},
                            expected: {name: {october_sha256, new_sha256, changed}}, cells_tsv_sha256}
                           (the October side is read, read-only, from the --october-* reference copy;
                           null where October has no such file)
  <out>/report_promote.json counts only
Before anything is written every input is checked; a gold row with no estimate (or two), a bad source
MANIFEST, an --out inside an October tree, or an --out that already holds a promotion is a STOP: rc 1,
'STOP' on stdout, nothing written. MANIFEST rows are bare file names, as analysis/expected's.

The gold rows: rows of the --cells TSVs whose `kind` is 'gold' when the TSV has a kind column, else
every row except the C10 cells (P1_econ_fnfix_old79 / _new37). For M.tsv + M_evcl.tsv that is the 27
gold cells (the 29 October golds minus C10); robustness rows are not golds.

check (postpromote) fails on: a source frame missing from <out>/frames (FRAME_MISSING) or with another
sha256 (FRAME_STALE); any other file there (FRAME_EXTRA); a promoted gold missing (GOLD_MISSING) or not
byte-equal to the cell output just run (GOLD_DIFF), or that output missing (CELL_MISSING); any other
file in <out>/expected (EXPECTED_EXTRA); tools/verify_manifest.py not printing MANIFEST_OK on either
MANIFEST, or a MANIFEST that does not list exactly the files beside it (MANIFEST_FAIL / MANIFEST_ROWS),
or a listed bare name that would resolve at the repo root first (MANIFEST_SHADOWED); a refreeze record
that disagrees with the promoted files or the cells TSVs (REFREEZE_STALE). It writes
gate_report_postpromote.json (name-free: codes, counts, labels, file names) and exits 1 on FAIL.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

HOSTS = ("ec2-r1-test", "ec2-r1")
HERE = pathlib.Path(__file__).resolve().parent
#: the C10 cells (p2_decisions c_rulings C10 = 'v3'): October golds that are not M golds
C10_LABELS = ("P1_econ_fnfix_old79", "P1_econ_fnfix_new37")
CELL_COLUMNS = ("label", "driver", "frame", "ref", "out_name", "stack")
#: repo trees October owns; an --out inside one (or inside the --october-* copies) is refused
OCTOBER_TREES = ("data/frames", "analysis/expected", "data/cal2026-10")
MANIFEST = "MANIFEST.sha256"
SOURCES = "SOURCES.md"
RECORD = "expected_refreeze_r1.json"
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]*$")


class Stop(RuntimeError):
    """An input that forbids the promotion; nothing is written."""


# ---------------------------------------------------------------------------------------------

def sha256_file(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def code_repo() -> pathlib.Path:
    """The checkout that holds tools/verify_manifest.py: this file's own, or $REPO_DIR."""
    cands = list(HERE.parents) + ([pathlib.Path(os.environ["REPO_DIR"])] if os.environ.get("REPO_DIR") else [])
    for c in cands:
        if (c / "tools" / "verify_manifest.py").is_file() and (c / "pipeline" / "aws" / "r1").is_dir():
            return c
    raise Stop("cannot find the repo checkout that holds tools/verify_manifest.py (set $REPO_DIR)")


def name_free(obj):
    """run_stages.name_free (W1-KIT) when present; the report is name-free by construction anyway
    (codes, counts, cell labels and file names only)."""
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    try:
        fn = getattr(importlib.import_module("run_stages"), "name_free", None)
    except ImportError:
        fn = None
    return fn(obj) if fn else obj


def gold_rows(cells) -> list[dict]:
    """The gold rows of the cells TSVs, in file order (see the module docstring)."""
    rows = []
    for tsv in cells:
        with open(tsv, encoding="utf-8", newline="") as fh:
            rd = csv.DictReader(fh, delimiter="\t")
            missing = [c for c in CELL_COLUMNS if c not in (rd.fieldnames or [])]
            if missing:
                raise Stop(f"{tsv}: missing columns {missing}")
            has_kind = "kind" in rd.fieldnames
            for r in rd:
                if has_kind:
                    if (r.get("kind") or "").strip() not in ("gold", "robust"):
                        raise Stop(f"{tsv}: row {r['label']!r} has kind {r.get('kind')!r} (want gold|robust)")
                    if r["kind"].strip() != "gold":
                        continue
                elif r["label"] in C10_LABELS:
                    continue
                rows.append({k: r[k] for k in CELL_COLUMNS})
    names = [r["out_name"] for r in rows]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise Stop(f"gold out_name listed twice: {dup}")
    bad = [n for n in names if not SAFE_NAME.match(n) or not n.endswith(".json")]
    if bad:
        raise Stop(f"gold out_name not a plain .json file name: {bad}")
    if not rows:
        raise Stop("no gold rows in the cells TSVs")
    return rows


def find_estimates(rows, est_dirs) -> tuple[dict, list, list]:
    """out_name -> the one estimate file; (found, missing names, names found more than once)."""
    found, missing, dup = {}, [], []
    for r in rows:
        hits = [pathlib.Path(d) / r["out_name"] for d in est_dirs if (pathlib.Path(d) / r["out_name"]).is_file()]
        if not hits:
            missing.append(r["out_name"])
        elif len(hits) > 1:
            dup.append(r["out_name"])
        else:
            found[r["out_name"]] = hits[0]
    return found, missing, dup


def read_manifest(path) -> dict[str, str]:
    """'<sha256>  <path>' rows -> {basename: sha256} (October's frames MANIFEST lists repo paths)."""
    out = {}
    for n, ln in enumerate(pathlib.Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not ln.strip():
            continue
        h, sep, rel = ln.partition("  ")
        if not sep or not re.fullmatch(r"[0-9a-f]{64}", h):
            raise Stop(f"{path} line {n}: not a sha256 MANIFEST row")
        name = pathlib.PurePosixPath(rel.strip().lstrip("*")).name
        if name in out:
            raise Stop(f"{path}: two rows for {name}")
        out[name] = h
    return out


def source_frames(frames_dir) -> dict[str, str]:
    """{name: sha256} of every file in the assembled frames dir; its MANIFEST must describe exactly them."""
    d = pathlib.Path(frames_dir)
    if not (d / MANIFEST).is_file():
        raise Stop(f"{d}: no {MANIFEST}")
    entries = sorted(p for p in d.iterdir() if p.name != MANIFEST)
    subdirs = [p.name for p in entries if not p.is_file()]
    if subdirs:
        raise Stop(f"{d}: unexpected non-file entries {subdirs}")
    have = {p.name: sha256_file(p) for p in entries}
    man = read_manifest(d / MANIFEST)
    if man != have:
        diff = sorted(n for n in set(man) | set(have) if man.get(n) != have.get(n))
        raise Stop(f"{d}/{MANIFEST} does not describe the files beside it: {diff}")
    bad = [n for n in have if not SAFE_NAME.match(n)]
    if bad:
        raise Stop(f"{d}: file names unsafe for a bare-name MANIFEST: {bad}")
    return have


def shadowed_names(names) -> list[str]:
    """Bare MANIFEST names that exist at the repo root: tools/verify_manifest.py resolves a listed path
    against the repo root before the manifest's own directory, so such a row would check the wrong file."""
    root = code_repo()
    return sorted(n for n in names if (root / n).exists())


def _inside(p: pathlib.Path, base: pathlib.Path) -> bool:
    return p == base or base in p.parents


def check_out_path(out, *, october) -> None:
    o = pathlib.Path(out).resolve()
    repo = code_repo().resolve()
    bases = [repo / t for t in OCTOBER_TREES] + [pathlib.Path(x).resolve() for x in october if x]
    for b in bases:
        if _inside(o, b) or _inside(b, o):
            raise Stop(f"--out {out} overlaps an October tree ({b}); R1 promotion never writes there")
    for sub in ("frames", "expected"):
        d = o / sub
        if d.exists() and (not d.is_dir() or any(d.iterdir())):
            raise Stop(f"{d} already holds files; promote into a fresh stage directory")
    if (o / RECORD).exists():
        raise Stop(f"{o / RECORD} already exists")


def _oct_sha(d, name):
    if d is None:
        return None
    p = pathlib.Path(d) / name
    return sha256_file(p) if p.is_file() else None


def _write_manifest(d: pathlib.Path, names) -> None:
    (d / MANIFEST).write_text("".join(f"{sha256_file(d / n)}  {n}\n" for n in names), encoding="utf-8")


def sources_md(rows, est) -> str:
    return ("# R1 M golds — where each file came from\n\n"
            "Written by pipeline/aws/r1/promote_r1.py (J1a stage `promote`). Each file is a byte copy of the "
            "cell output the J1a cells stages just ran (run_cells.py on config/r1/cells/M.tsv and "
            "M_evcl.tsv against the assembled M frames). October's golds (analysis/expected) are untouched; "
            f"{RECORD} lists the October and new sha256 of every gold and frame. Moving these into "
            "analysis/expected is the author's call after P5.\n\n"
            "| file | cell | stack | driver | frame | ref | source |\n|---|---|---|---|---|---|---|\n"
            + "".join(f"| {r['out_name']} | {r['label']} | {r['stack']} | `{r['driver']}` | {r['frame']} | {r['ref']} "
                      f"| `{est[r['out_name']]}` |\n" for r in rows))


# ---------------------------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------------------------

def run(*, frames, estimates, cells, october_golds, october_frames, out) -> int:
    try:
        rows = gold_rows(cells)
        found, missing, dup = find_estimates(rows, estimates)
        if missing or dup:
            raise Stop(f"gold-row estimates missing {missing} / found more than once {dup}")
        for d in (october_golds, october_frames):
            if not pathlib.Path(d).is_dir():
                raise Stop(f"October reference copy {d} is not a directory")
        check_out_path(out, october=(october_golds, october_frames))
        src = source_frames(frames)
        shadowed = shadowed_names([*src, *(r["out_name"] for r in rows)])
        if shadowed:
            raise Stop(f"names that exist at the repo root, so tools/verify_manifest.py would read those: {shadowed}")
    except Stop as e:
        print(f"STOP {e}")
        return 1
    out = pathlib.Path(out)
    fdir, edir = out / "frames", out / "expected"
    fdir.mkdir(parents=True, exist_ok=True)
    edir.mkdir(parents=True, exist_ok=True)
    for name, h in sorted(src.items()):
        shutil.copyfile(pathlib.Path(frames) / name, fdir / name)
        if sha256_file(fdir / name) != h:
            raise SystemExit(f"copy of {name} does not match its source")
    _write_manifest(fdir, sorted(src))
    for r in rows:
        n = r["out_name"]
        shutil.copyfile(found[n], edir / n)
        if sha256_file(edir / n) != sha256_file(found[n]):
            raise SystemExit(f"copy of {n} does not match its source")
    _write_manifest(edir, [r["out_name"] for r in rows])
    (edir / SOURCES).write_text(sources_md(rows, found), encoding="utf-8")
    record = {
        "schema": "sar.r1.refreeze.v1",
        "frames": {n: {"october_sha256": _oct_sha(october_frames, n), "new_sha256": h} for n, h in sorted(src.items())},
        "expected": {},
        "cells_tsv_sha256": {str(t): sha256_file(t) for t in cells},
        "october_golds": str(october_golds), "october_frames": str(october_frames),
    }
    for r in rows:
        n = r["out_name"]
        o, h = _oct_sha(october_golds, n), sha256_file(edir / n)
        record["expected"][n] = {"label": r["label"], "october_sha256": o, "new_sha256": h, "changed": o != h}
    (out / RECORD).write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    n_changed = sum(v["changed"] for v in record["expected"].values())
    rep = {"stage": "promote", "result": "OK",
           "counts": {"n_frames": len(src), "n_golds": len(rows), "n_golds_changed": n_changed,
                      "n_frames_new_in_m": sum(v["october_sha256"] is None for v in record["frames"].values())}}
    (out / "report_promote.json").write_text(json.dumps(name_free(rep), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"promoted {len(src)} frame files and {len(rows)} golds ({n_changed} changed vs October) into {out}")
    return 0


# ---------------------------------------------------------------------------------------------
# check (postpromote)
# ---------------------------------------------------------------------------------------------

def verify_manifest(path) -> bool:
    """tools/verify_manifest.py must print MANIFEST_OK and exit 0."""
    tool = code_repo() / "tools" / "verify_manifest.py"
    r = subprocess.run([sys.executable, str(tool), str(path)], capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip().splitlines()[-1:] == ["MANIFEST_OK"]


def manifest_rows(d: pathlib.Path, want: list[str]) -> list[str]:
    """Codes for a promoted MANIFEST: it must exist, pass verify_manifest.py, list exactly `want`, and no
    listed bare name may exist at the repo root (verify_manifest.py would read that file first)."""
    m = d / MANIFEST
    if not m.is_file():
        return ["MANIFEST_FAIL"]
    codes = []
    if not verify_manifest(m):
        codes.append("MANIFEST_FAIL")
    try:
        listed = read_manifest(m)
    except Stop:
        return sorted(set(codes) | {"MANIFEST_FAIL"})
    if sorted(listed) != sorted(want):
        codes.append("MANIFEST_ROWS")
    if shadowed_names(listed):
        codes.append("MANIFEST_SHADOWED")
    return codes


def postpromote(*, frames, estimates, cells, out) -> dict:
    out = pathlib.Path(out)
    fdir, edir = out / "frames", out / "expected"
    codes, rows_f, rows_e = set(), [], []
    if not pathlib.Path(frames).is_dir():
        raise Stop(f"--frames {frames} is not a directory")
    src = {p.name: sha256_file(p) for p in sorted(pathlib.Path(frames).iterdir()) if p.is_file() and p.name != MANIFEST}
    for n, h in sorted(src.items()):
        p = fdir / n
        st = "MISSING" if not p.is_file() else ("OK" if sha256_file(p) == h else "STALE")
        rows_f.append({"path": n, "status": st})
    have = sorted(p.name for p in fdir.iterdir()) if fdir.is_dir() else []
    rows_f += [{"path": n, "status": "EXTRA"} for n in have if n != MANIFEST and n not in src]
    codes.update(f"FRAME_{r['status']}" for r in rows_f if r["status"] != "OK")
    codes.update(manifest_rows(fdir, sorted(src)))

    rows = gold_rows(cells)
    found, missing, dup = find_estimates(rows, estimates)
    for r in rows:
        n, p = r["out_name"], edir / r["out_name"]
        if n in missing or n in dup:
            st = "CELL_MISSING"
        elif not p.is_file():
            st = "GOLD_MISSING"
        else:
            st = "OK" if sha256_file(p) == sha256_file(found[n]) else "GOLD_DIFF"
        rows_e.append({"label": r["label"], "path": n, "status": st})
    golds = {r["out_name"] for r in rows}
    have = sorted(p.name for p in edir.iterdir()) if edir.is_dir() else []
    rows_e += [{"label": None, "path": n, "status": "EXPECTED_EXTRA"} for n in have
               if n not in golds and n not in (MANIFEST, SOURCES)]
    codes.update(r["status"] for r in rows_e if r["status"] != "OK")
    if not (edir / SOURCES).is_file():
        codes.add("SOURCES_MISSING")
    em = manifest_rows(edir, [r["out_name"] for r in rows])
    codes.update(em)

    rec_ok = False
    try:
        rec = json.loads((out / RECORD).read_text(encoding="utf-8"))
        rec_ok = ({n: v.get("new_sha256") for n, v in rec["frames"].items()} == src
                  and {n: v.get("new_sha256") for n, v in rec["expected"].items()}
                  == {n: sha256_file(edir / n) if (edir / n).is_file() else None for n in golds}
                  and rec["cells_tsv_sha256"] == {str(t): sha256_file(t) for t in cells})
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        rec_ok = False
    if not rec_ok:
        codes.add("REFREEZE_STALE")
    return {"gate": "postpromote", "verdict": "FAIL" if codes else "PASS", "codes": sorted(codes),
            "counts": {"n_frames": len(src), "n_frames_ok": sum(r["status"] == "OK" for r in rows_f),
                       "n_golds": len(rows), "n_golds_ok": sum(r["status"] == "OK" for r in rows_e)},
            "rows_frames": [r for r in rows_f if r["status"] != "OK"],
            "rows_expected": [r for r in rows_e if r["status"] != "OK"]}


def check(*, frames, estimates, cells, out) -> int:
    try:
        rep = postpromote(frames=frames, estimates=estimates, cells=cells, out=out)
    except Stop as e:
        rep = {"gate": "postpromote", "verdict": "FAIL", "codes": ["INPUT_STOP"], "counts": {}}
        print(f"STOP {e}")
    pathlib.Path(out).mkdir(parents=True, exist_ok=True)
    (pathlib.Path(out) / "gate_report_postpromote.json").write_text(
        json.dumps(name_free(rep), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"postpromote {rep['verdict']} codes={','.join(rep['codes']) or '-'}")
    return 0 if rep["verdict"] == "PASS" else 1


# ---------------------------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 promotion of the M frames and golds (F4) and its post-promotion gate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "check"):
        p = sub.add_parser(name)
        p.add_argument("--frames", required=True, help="the assembled M frames directory (with MANIFEST.sha256)")
        p.add_argument("--estimates", nargs="+", required=True, help="directories holding the cell JSONs by out_name")
        p.add_argument("--cells", nargs="+", required=True, help="cells TSVs (config/r1/cells/M.tsv M_evcl.tsv)")
        p.add_argument("--out", required=True, help="the promoted layout ($STAGE_OUT)")
        if name == "run":
            p.add_argument("--october-golds", required=True, help="read-only October golds (/work/ref/october/analysis/expected)")
            p.add_argument("--october-frames", required=True, help="read-only October frames (/work/ref/october/data/frames)")
    a = ap.parse_args(argv)
    if os.environ.get("SAR_HOST", "").strip() not in HOSTS:
        raise SystemExit("R1 rule: promote_r1.py runs only on an R1 instance ($SAR_HOST)")
    if a.cmd == "run":
        return run(frames=a.frames, estimates=a.estimates, cells=a.cells, october_golds=a.october_golds,
                   october_frames=a.october_frames, out=a.out)
    return check(frames=a.frames, estimates=a.estimates, cells=a.cells, out=a.out)


if __name__ == "__main__":
    sys.exit(main())
