#!/usr/bin/env python3
"""analysis/lib/run_all_stages.py - the helpers behind analysis/run_all.sh.

Every path comes from the canon that the paths config in force selects ($SAR_PATHS_CONFIG, else
config/paths.yaml; analysis/lib/canon.py): the October 2026 roots, or a canon tree (a directory holding
CANON.json and one folder per canon key). Nothing here spells a data root.

    run_all_stages.py env               shell exports of the canon in force: D (frames root), X (expected
                                        root), CAL (cal root), O (output root), CANON (the canon root, the
                                        directory holding the cal root) and CANON_NAME (october | M)
    run_all_stages.py describe          two lines for the start of a run: the canon's name and place, and
                                        its event counts
    run_all_stages.py cells             the canon's cell lists as one TSV: the header
                                        label driver frame ref out_name stack, then one row per cell
                                        (config/r1/cells/oct29.tsv for October; M.tsv, then M_evcl.tsv
                                        for a canon tree)
    run_all_stages.py unpack            restore each file <canon>/PACKED.tsv lists from its xz copy. The
                                        final-job format records path, sha256, bytes, xz_sha256 and
                                        xz_bytes; the earlier path/packed/sha256 format also works.
                                        Both recorded sizes and hashes are checked. The file is
                                        decompressed into a temporary file beside it, its sha256 must equal
                                        the listed one, and only then is it renamed into place. A file
                                        already in place with that sha256 is kept. Any problem stops with
                                        nothing renamed for that file. No PACKED.tsv, or October: nothing
                                        to do
    run_all_stages.py verify-manifests  every line of the canon's MANIFESTs: the file exists and its sha256
                                        matches. October: data/MANIFEST.sha256 and
                                        analysis/expected/MANIFEST.sha256. A canon tree: the
                                        <canon>/<prefix>/MANIFEST.sha256 of each of the six canon keys,
                                        keys '<prefix>/<rel>' only; a missing one, or a frames or
                                        expected one that pins nothing, is a problem too
    run_all_stages.py seal --out FILE --outputs F [F ...] --inputs F [F ...]
                                        record the sha256 of each 3est output and each input it read, and
                                        the canon; exit 4 if a listed file is missing
    run_all_stages.py check-seal FILE [--require F [F ...]]
                                        exit 4 on a missing or malformed seal, a missing or changed output
                                        or input, a required output the seal does not hold, or a seal made
                                        under another canon (root, frames/expected roots or CANON.json)
    run_all_stages.py check-no-ssd      exit 5 if CANON, D, X or O resolve under the configured ssd_root,
                                        $SAR_SSD_ROOT or /Volumes (stage 3light runs on the canon, never on
                                        a data disk)

Exit codes: 0 OK, 1 MANIFEST_FAIL or UNPACK_FAIL, 2 usage, 3 PATHS_CONFIG_ERROR ($SAR_PATHS_CONFIG is
relative or names no file), 4 SEAL_FAIL, 5 DATA_DISK, 6 CANON_ERROR (a paths config that selects no valid
canon, a canon without its counts, or a malformed cell list). Standard library + PyYAML (through
paths.py); reads no person-level data and prints paths, counts, cell rows and codes only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import lzma
import os
import re
import shlex
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from analysis.lib import canon  # noqa: E402
from analysis.lib.paths import config_file, load_paths  # noqa: E402

SEAL_SCHEMA = "sar.r1.run_all_seal.v1"
EXPORTS = ("D", "X", "CAL", "O", "CANON", "CANON_NAME")
#: the directory every macOS external volume mounts under; a canon or output there is a data disk
VOLUMES = Path("/Volumes")
RC_MANIFEST, RC_USAGE, RC_CONFIG, RC_SEAL, RC_DISK, RC_CANON = 1, 2, 3, 4, 5, 6
#: where the cell lists live, and which lists each canon runs (tools/compare_all.py keeps the same table)
CELLS_DIR = REPO / "config" / "r1" / "cells"
CELL_LISTS = {"october": ("oct29.tsv",), "M": ("M.tsv", "M_evcl.tsv")}
CELL_COLUMNS = ("label", "driver", "frame", "ref", "out_name", "stack")
#: rmac = re-run with the Rscript on PATH; rcloud = the large cells, custody-checked unless RUN_CLOUD_CELLS=1
STACKS = ("rmac", "rcloud")
NAME_RX = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]*")
#: the list of the canon's xz-compressed files, at the canon root
PACKED = "PACKED.tsv"
PACKED_COLUMNS = ("path", "packed", "sha256")
PACKED_JOB_COLUMNS = ("path", "sha256", "bytes", "xz_sha256", "xz_bytes")
FIELD_NAMES = (("econ", "economics"), ("chemistry", "chemistry"), ("math_stats", "mathematics and statistics"))
#: the MANIFESTs stage 1 verifies in October (data/MANIFEST.sha256, analysis/expected/MANIFEST.sha256); a canon
#: tree verifies the MANIFEST of every canon key
OCTOBER_KINDS = ("frames", "expected")
#: the keys whose MANIFEST must pin at least one file (stage 2 reads them)
NONEMPTY_KINDS = ("frames", "expected")


class SealError(RuntimeError):
    """A seal cannot be written (a listed file is missing)."""


class UnpackError(RuntimeError):
    """A file PACKED.tsv lists cannot be restored as listed."""


def _P(P):
    return P if P is not None else load_paths()


def _shown(p, repo: Path) -> str:
    """A path as a run prints it: relative to the repository when it lies inside it, else absolute."""
    p = Path(p).resolve()
    try:
        return p.relative_to(repo).as_posix()
    except ValueError:
        return str(p)


# ---- env and describe -----------------------------------------------------------------------------------
def exports(P: dict | None = None) -> dict:
    """{D, X, CAL, O, CANON, CANON_NAME} of the canon in force, as strings (absolute, resolved)."""
    P = _P(P)
    s = canon.state(P)
    return {"D": str(s.roots["frames"]), "X": str(s.roots["expected"]), "CAL": str(s.roots["cal"]),
            "O": str(Path(P["output"]).resolve()), "CANON": str(s.roots["cal"].parent), "CANON_NAME": s.mode}


def fingerprint(P: dict | None = None) -> dict:
    """What identifies the canon a seal was made under."""
    P = _P(P)
    s = canon.state(P)
    cj = s.root / canon.CANON_JSON if s.mode == "M" else None
    return {"name": s.mode, "root": str(s.roots["cal"].parent), "frames": str(s.roots["frames"]),
            "expected": str(s.roots["expected"]), "canon_json_sha256": canon.sha256(cj) if cj else None}


def describe(P: dict | None = None, cfg=None) -> list[str]:
    """The canon's name and place (and the paths config, when given), then its event counts by field.
    CanonError when the canon has no valid counts."""
    P = _P(P)
    s = canon.state(P)
    c = canon.counts(P)
    what = "the October 2026 version" if s.mode == "october" else f"the canon tree at {_shown(s.root, s.repo)}"
    where = f" (paths config {_shown(cfg, s.repo)})" if cfg is not None else ""
    by_field = ", ".join(f"{name} {c['events'][k]}" for k, name in FIELD_NAMES)
    return [f"== canon: {s.mode} - {what}{where} ==", f"   events: {c['events_total']} ({by_field})"]


# ---- cells ----------------------------------------------------------------------------------------------
def cell_lists(P: dict | None = None) -> list[Path]:
    """The cell lists of the canon in force, in run order."""
    return [CELLS_DIR / name for name in CELL_LISTS[canon.state(_P(P)).mode]]


def _cell_problem(r: dict) -> str | None:
    if None in r or any(not isinstance(r.get(c), str) or not r[c] for c in CELL_COLUMNS):
        return "not six non-empty columns"
    if any(re.search(r"\s", r[c]) for c in CELL_COLUMNS):
        return "a value holds a space"
    if r["stack"] not in STACKS:
        return f"stack {r['stack']!r} is not one of {list(STACKS)}"
    for c in ("label", "frame", "out_name") + (() if r["ref"] == "-" else ("ref",)):
        if not NAME_RX.fullmatch(r[c]):
            return f"{c} {r[c]!r} is not a plain file name"
    if not r["out_name"].endswith(".json") or (r["ref"] != "-" and not r["ref"].endswith(".json")):
        return "out_name and ref name .json files"
    d = Path(r["driver"])
    if d.is_absolute() or ".." in d.parts or d.parts[:2] != ("analysis", "estimation") or not (REPO / d).is_file():
        return f"driver {r['driver']!r} is not a file under analysis/estimation"
    return None


def cells(P: dict | None = None) -> list[dict]:
    """The rows of the canon's cell lists, in run order; CanonError on a malformed list."""
    rows, labels, outs = [], set(), set()
    for f in cell_lists(P):
        try:
            fh = open(f, encoding="utf-8", newline="")
        except OSError as e:
            raise canon.CanonError(f"cell list {f}: {e}") from None
        with fh:
            rd = csv.DictReader(fh, delimiter="\t")
            if tuple(rd.fieldnames or ()) != CELL_COLUMNS:
                raise canon.CanonError(f"cell list {f}: the header must be {' '.join(CELL_COLUMNS)}")
            for n, r in enumerate(rd, 2):
                why = _cell_problem(r)
                if why is None and (r["label"] in labels or r["out_name"] in outs):
                    why = "a label or out_name listed twice"
                if why is not None:
                    raise canon.CanonError(f"cell list {f.name} line {n}: {why}")
                labels.add(r["label"])
                outs.add(r["out_name"])
                rows.append({c: r[c] for c in CELL_COLUMNS})
    if not rows:
        raise canon.CanonError("the canon's cell lists hold no cell")
    return rows


# ---- unpack ---------------------------------------------------------------------------------------------
def _canon_rel(root: Path, rel: str, where: str) -> Path:
    p = Path(rel)
    if not rel or p.is_absolute() or ".." in p.parts or rel != p.as_posix():
        raise UnpackError(f"{where}: {rel!r} is not a path inside the canon")
    return root / p


def packed_rows(root: Path) -> list[dict]:
    """The rows of <root>/PACKED.tsv ([] when there is none); UnpackError when it is malformed."""
    f = root / PACKED
    if not f.is_file():
        return []
    lines = [ln for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
    header = tuple(lines[0].split("\t")) if lines else ()
    if header not in (PACKED_COLUMNS, PACKED_JOB_COLUMNS):
        raise UnpackError(f"{f}: the header must be {' '.join(PACKED_COLUMNS)} or "
                          f"{' '.join(PACKED_JOB_COLUMNS)}")
    rows = []
    for n, ln in enumerate(lines[1:], 2):
        cells_ = ln.split("\t")
        where = f"{PACKED} line {n}"
        if len(cells_) != len(header):
            raise UnpackError(f"{where}: not {len(header)} columns")
        values = dict(zip(header, cells_))
        path, sha = values["path"], values["sha256"]
        packed = values.get("packed", path + ".xz")
        dest, src = _canon_rel(root, path, where), _canon_rel(root, packed, where)
        if not packed.endswith(".xz") or dest == src:
            raise UnpackError(f"{where}: the packed copy of {path} must be an .xz file")
        for field in ("sha256",) + (("xz_sha256",) if header == PACKED_JOB_COLUMNS else ()):
            if not re.fullmatch(r"[0-9a-f]{64}", values[field]):
                raise UnpackError(f"{where}: {field} is not a sha256")
        row = {"path": path, "packed": packed, "sha256": sha, "dest": dest, "src": src}
        if header == PACKED_JOB_COLUMNS:
            for field in ("bytes", "xz_bytes"):
                if not re.fullmatch(r"[0-9]+", values[field]):
                    raise UnpackError(f"{where}: {field} must be a non-negative integer")
                row[field] = int(values[field])
            row["xz_sha256"] = values["xz_sha256"]
        rows.append(row)
    return rows


def unpack(P: dict | None = None) -> list[str]:
    """Restore the canon's packed files (see the module docstring); one line per listed file, or UnpackError."""
    s = canon.state(_P(P))
    return unpack_root(s.root) if s.mode == "M" else []


def unpack_root(root: Path, made: list | None = None) -> list[str]:
    """Restore the files <root>/PACKED.tsv lists (see the module docstring); one line per listed file, or
    UnpackError. `made`, when given, collects each file renamed into place, so a caller that only checks the
    restored files can remove them afterwards."""
    done = []
    for r in packed_rows(Path(root)):
        dest, src = r["dest"], r["src"]
        had = dest.is_file()
        if had and canon.sha256(dest) == r["sha256"] and ("bytes" not in r or dest.stat().st_size == r["bytes"]):
            done.append(f"KEPT {r['path']} (sha256 matches {PACKED})")
            continue
        if not src.is_file():
            raise UnpackError(f"{r['packed']}: missing ({PACKED} lists it for {r['path']})")
        if "xz_bytes" in r and src.stat().st_size != r["xz_bytes"]:
            raise UnpackError(f"{r['packed']}: compressed size differs from {PACKED}")
        if "xz_sha256" in r and canon.sha256(src) != r["xz_sha256"]:
            raise UnpackError(f"{r['packed']}: compressed sha256 differs from {PACKED}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".unpacking")
        h = hashlib.sha256()
        try:
            with lzma.open(src) as fin, open(tmp, "wb") as fout:
                for chunk in iter(lambda: fin.read(1 << 20), b""):
                    h.update(chunk)
                    fout.write(chunk)
        except (OSError, EOFError, lzma.LZMAError) as e:
            tmp.unlink(missing_ok=True)
            raise UnpackError(f"{r['packed']}: cannot be decompressed ({e.__class__.__name__}: {e})") from None
        if h.hexdigest() != r["sha256"]:
            tmp.unlink()
            raise UnpackError(f"{r['path']}: the sha256 of {r['packed']} decompressed is {h.hexdigest()}, "
                              f"{PACKED} lists {r['sha256']}")
        if "bytes" in r and tmp.stat().st_size != r["bytes"]:
            tmp.unlink()
            raise UnpackError(f"{r['path']}: decompressed size differs from {PACKED}")
        os.replace(tmp, dest)
        if made is not None:
            made.append(dest)
        done.append(f"UNPACKED {r['path']} from {r['packed']}" + (" (replaced a copy with another sha256)" if had else ""))
    return done


# ---- stage 1 ----------------------------------------------------------------------------------------
def manifest_kinds(P: dict | None = None) -> tuple:
    """The canon keys whose MANIFESTs stage 1 verifies: frames and expected in October, all six in a canon tree."""
    return canon.KEYS if canon.mode(_P(P)) == "M" else OCTOBER_KINDS


def verify_manifests(P: dict | None = None, kinds=None) -> list[str]:
    """Problems of the canon's MANIFESTs (those of `kinds`, by default manifest_kinds()); [] = every line exists
    and matches."""
    P = _P(P)
    s = canon.state(P)
    kinds = manifest_kinds(P) if kinds is None else kinds
    probs = []
    for kind in kinds:
        man = canon.manifest(kind, P)
        if not man.is_file():
            probs.append(f"{kind}: no MANIFEST at {man}")
            continue
        pins = canon.read_manifest(man)
        if not pins and kind in NONEMPTY_KINDS:
            probs.append(f"{kind}: {man} pins nothing")
        for key, want in pins.items():
            if s.mode == "M":
                pre = s.prefix[kind]
                if not key.startswith(pre + "/"):
                    probs.append(f"{key}: outside '{pre}/' in {man}")
                    continue
                f = canon.resolve(key, P)
            else:   # tools/verify_manifest.py semantics: the repo root first, then the MANIFEST's own dir
                f = s.repo / key
                if not f.exists():
                    f = man.parent / key
            if not f.is_file():
                probs.append(f"{key}: missing ({f})")
            elif canon.sha256(f) != want:
                probs.append(f"{key}: sha256 differs from {man}")
    return probs


# ---- 3est seal ----------------------------------------------------------------------------------------
def _abs(p) -> str:
    return str(Path(p).resolve())


def seal(out, outputs, inputs, P: dict | None = None) -> dict:
    """Write the seal of a finished 3est pass; SealError if a listed file is missing."""
    outputs, inputs = [_abs(p) for p in outputs], [_abs(p) for p in inputs]
    missing = [p for p in outputs + inputs if not Path(p).is_file()]
    if missing:
        raise SealError(f"cannot seal: {len(missing)} listed file(s) missing, e.g. {missing[0]}")
    if not outputs:
        raise SealError("cannot seal: no 3est output listed")
    rec = {"schema": SEAL_SCHEMA, "canon": fingerprint(P),
           "outputs": {p: canon.sha256(p) for p in outputs}, "inputs": {p: canon.sha256(p) for p in inputs}}
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, out)
    return rec


def check_seal(path, require=(), P: dict | None = None) -> list[str]:
    """Problems of a 3est seal against the files and the canon in force; [] = fresh."""
    path = Path(path)
    if not path.is_file():
        return [f"no seal at {path}: run stage 3est first"]
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        return [f"{path}: not JSON ({e})"]
    if not (isinstance(rec, dict) and rec.get("schema") == SEAL_SCHEMA and isinstance(rec.get("outputs"), dict)
            and isinstance(rec.get("inputs"), dict) and isinstance(rec.get("canon"), dict) and rec["outputs"]):
        return [f"{path}: not a {SEAL_SCHEMA} seal"]
    probs = []
    now = fingerprint(P)
    diff = sorted(k for k in set(now) | set(rec["canon"]) if now.get(k) != rec["canon"].get(k))
    if diff:
        probs.append(f"sealed under another canon ({', '.join(diff)} differ): sealed {rec['canon'].get('name')} at "
                     f"{rec['canon'].get('root')}, in force {now['name']} at {now['root']}")
    for kind in ("outputs", "inputs"):
        for p, want in sorted(rec[kind].items()):
            if not Path(p).is_file():
                probs.append(f"{kind[:-1]} missing since the seal: {p}")
            elif canon.sha256(p) != want:
                probs.append(f"{kind[:-1]} changed since the seal: {p}")
    for p in require:
        if _abs(p) not in rec["outputs"]:
            probs.append(f"required 3est output not in the seal: {_abs(p)}")
    return probs


# ---- 3light data-disk guard -----------------------------------------------------------------------------
def disk_roots(P: dict | None = None) -> list[Path]:
    P = _P(P)
    roots = [VOLUMES]
    if P.get("ssd_root"):
        roots.append(Path(P["ssd_root"]))
    env = os.environ.get("SAR_SSD_ROOT", "").strip()
    if env:
        roots.append(Path(env).expanduser())
    out = []
    for r in roots:
        for v in (Path(os.path.abspath(r)), r.resolve()):
            if v not in out:
                out.append(v)
    return out


def check_no_ssd(P: dict | None = None) -> list[str]:
    """'<NAME> <path> lies under <disk root>' for each of CANON, D, X, O on a data disk; [] = none."""
    P = _P(P)
    ex = exports(P)
    disks = disk_roots(P)
    probs = []
    for name in ("CANON", "D", "X", "O"):
        p = Path(ex[name])
        forms = {Path(os.path.abspath(p)), p.resolve()}
        hit = next((d for d in disks for f in forms if f == d or d in f.parents), None)
        if hit is not None:
            probs.append(f"{name} {p} lies under the data-disk root {hit}")
    return probs


# ---- CLI --------------------------------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("env", "describe", "cells", "unpack", "verify-manifests", "check-no-ssd"):
        sub.add_parser(name)
    s = sub.add_parser("seal")
    s.add_argument("--out", required=True)
    s.add_argument("--outputs", nargs="+", required=True)
    s.add_argument("--inputs", nargs="+", required=True)
    c = sub.add_parser("check-seal")
    c.add_argument("seal")
    c.add_argument("--require", nargs="+", default=[])
    a = ap.parse_args(argv)
    try:
        config_file()
    except (ValueError, OSError) as e:      # paths.py refuses a relative $SAR_PATHS_CONFIG or one naming no file
        print(f"PATHS_CONFIG_ERROR {e} (give the path of a paths config file, for example "
              f"$PWD/config/paths_october.yaml)", file=sys.stderr)
        return RC_CONFIG
    try:
        if a.cmd == "env":
            for k, v in exports().items():
                print(f"export {k}={shlex.quote(v)}")
            return 0
        if a.cmd == "describe":
            print("\n".join(describe(cfg=config_file())))
            return 0
        if a.cmd == "cells":
            rows = cells()                       # every list read and checked before a line is printed
            w = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
            w.writerow(CELL_COLUMNS)
            for r in rows:
                w.writerow([r[k] for k in CELL_COLUMNS])
            return 0
        if a.cmd == "unpack":
            try:
                done = unpack()
            except UnpackError as e:
                print(f"UNPACK_FAIL {e}")
                return RC_MANIFEST
            for line in done:
                print(line)
            print(f"UNPACK_OK {len(done)} file(s)" if done else f"UNPACK_OK nothing to unpack (no {PACKED} in the canon)")
            return 0
        if a.cmd == "verify-manifests":
            probs = verify_manifests()
            for p in probs:
                print(f"MISMATCH {p}")
            print(f"MANIFEST_OK {' '.join(manifest_kinds())}" if not probs else f"MANIFEST_FAIL {len(probs)}")
            return RC_MANIFEST if probs else 0
        if a.cmd == "seal":
            try:
                rec = seal(a.out, a.outputs, a.inputs)
            except SealError as e:
                print(f"SEAL_FAIL {e}")
                return RC_SEAL
            print(f"SEALED {len(rec['outputs'])} outputs, {len(rec['inputs'])} inputs, canon "
                  f"{rec['canon']['name']} -> {a.out}")
            return 0
        if a.cmd == "check-seal":
            probs = check_seal(a.seal, a.require)
            for p in probs:
                print(f"SEAL_FAIL {p}")
            if not probs:
                print(f"SEAL_OK {a.seal}")
            return RC_SEAL if probs else 0
        probs = check_no_ssd()
        for p in probs:
            print(f"DATA_DISK {p}")
        if not probs:
            print("NO_SSD_OK")
        return RC_DISK if probs else 0
    except canon.CanonError as e:
        print(f"CANON_ERROR {e}", file=sys.stderr)
        return RC_CANON


if __name__ == "__main__":
    sys.exit(main())
