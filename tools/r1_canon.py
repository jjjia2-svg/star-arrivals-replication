#!/usr/bin/env python3
"""tools/r1_canon.py - write, check and (for tests) copy an M canon.

An M canon is one directory per canon key (analysis/lib/canon.py KEYS) plus CANON.json. It lives
outside the clone (for example /work/canon_m) or under the clone's data/ directory, and in both
cases clear of the October roots, with symlinks followed (canon.check_place). The paper generators
read it when the paths config in force points the six canon keys at it.

    r1_canon.py manifest ROOT              write ROOT/<prefix>/MANIFEST.sha256 for every key present:
                                           one '<sha256>  <prefix>/<rel>' line per file under it
                                           (MANIFEST.sha256 itself excluded), sorted by key
    r1_canon.py check ROOT [--tsv F]       every analysis/lib/canon_reads.tsv row under a canon key
                                           exists and matches its MANIFEST, and no MANIFEST line has
                                           a key outside its own prefix -> CANON_OK / CANON_FAIL
    r1_canon.py copy-october DEST          for tests: copy the six October roots to DEST/<key> and add
          [--switch NAME=true|false]...    DEST/cal/counts.json (the October counts), CANON.json and
          [--paths-out FILE]               the MANIFESTs; DEST must be a place an M canon may live.
          [--output DIR]                   --paths-out writes a paths yaml that selects DEST (the config
                                           in force with the six keys moved; --output also moves output)

Exit codes: 0 OK, 1 CANON_FAIL, 2 usage. Standard library and PyYAML only. The output holds paths
and counts only, never person-level data.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from analysis.lib import canon  # noqa: E402
from analysis.lib.paths import config_file  # noqa: E402

TSV = REPO / "analysis" / "lib" / "canon_reads.tsv"
KINDS = ("product", "carried", "optional")


# ---- the reads contract ----------------------------------------------------------------------------
def read_tsv(path=TSV) -> list[dict]:
    """The rows of canon_reads.tsv: [{generator, key, rel, kind, reason}]."""
    rows, header = [], None
    for n, ln in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not ln.strip() or ln.startswith("#"):
            continue
        cells = ln.split("\t")
        if header is None:
            header = cells
            if header != ["generator", "key", "rel", "kind", "reason"]:
                raise SystemExit(f"{path}:{n}: header {header} is not generator/key/rel/kind/reason")
            continue
        if len(cells) != 5 or cells[3] not in KINDS or not all(c.strip() for c in cells):
            raise SystemExit(f"{path}:{n}: malformed row {cells}")
        rows.append(dict(zip(header, cells)))
    return rows


# ---- manifest --------------------------------------------------------------------------------------
def load_meta(root: Path) -> dict:
    cj = root / canon.CANON_JSON
    meta = json.loads(cj.read_text(encoding="utf-8"))
    canon._check_meta(meta, cj)
    return meta


def prefixes(root: Path) -> dict:
    cj = root / canon.CANON_JSON
    return load_meta(root)["prefix"] if cj.is_file() else dict(canon.DEFAULT_PREFIX)


def files_under(d: Path):
    for p in sorted(d.rglob("*")):
        if p.is_file() and not (p.parent == d and p.name == canon.MANIFEST):
            yield p


def write_manifests(root: Path) -> dict:
    """ROOT/<prefix>/MANIFEST.sha256 for every key directory present; {prefix: n files}."""
    root = Path(root)
    done = {}
    for k, pre in prefixes(root).items():
        d = root / pre
        if not d.is_dir():
            continue
        lines = sorted((f"{canon.sha256(p)}  {pre}/{p.relative_to(d).as_posix()}" for p in files_under(d)),
                       key=lambda ln: ln.split("  ", 1)[1])
        (d / canon.MANIFEST).write_text("".join(ln + "\n" for ln in lines), encoding="utf-8")
        done[pre] = len(lines)
    return done


# ---- check -----------------------------------------------------------------------------------------
def check(root: Path, tsv=TSV) -> list[str]:
    """Problems of the canon at ROOT against the reads contract; [] means CANON_OK."""
    root = Path(root)
    probs = []
    try:
        pre = load_meta(root)["prefix"]
    except (OSError, ValueError, canon.CanonError) as e:
        return [f"{root / canon.CANON_JSON}: {e}"]
    mans = {}
    for k, p in pre.items():
        man = root / p / canon.MANIFEST
        if not man.is_file():
            mans[k] = None
            continue
        mans[k] = canon.read_manifest(man)
        stray = [x for x in mans[k] if not x.startswith(p + "/")]
        if stray:
            probs.append(f"{p}/{canon.MANIFEST}: {len(stray)} key(s) outside '{p}/', e.g. {stray[0]}")
    for r in read_tsv(tsv):
        k = r["key"]
        if k not in canon.KEYS:
            continue   # read in place (legacy, fwci, repo), never part of the canon
        p = pre[k]
        d = root / p
        if mans[k] is None:
            if r["kind"] != "optional":
                probs.append(f"{p}/{r['rel']}: no {p}/{canon.MANIFEST} ({r['generator']})")
            continue
        hits = sorted(f.relative_to(d).as_posix() for f in files_under(d)
                      if fnmatch.fnmatchcase(f.relative_to(d).as_posix(), r["rel"]))
        if not hits:
            if r["kind"] != "optional":
                probs.append(f"{p}/{r['rel']}: missing ({r['kind']}, {r['generator']})")
            continue
        for rel in hits:
            mk = f"{p}/{rel}"
            if mk not in mans[k]:
                probs.append(f"{mk}: not in {p}/{canon.MANIFEST}")
            elif canon.sha256(d / rel) != mans[k][mk]:
                probs.append(f"{mk}: sha256 differs from {p}/{canon.MANIFEST}")
    return sorted(set(probs))


# ---- copy-october (test helper) ----------------------------------------------------------------------
def write_paths_yaml(dest: Path, out: Path, output=None, prefix=None) -> Path:
    """A paths yaml = the config in force with the six canon keys moved under DEST (and output re-rooted
    when given). Every value is written absolute (repo_root "." = the clone that reads it), so the file
    works from any directory.

    Every value is a double-quoted string, as config/paths.yaml writes repo_root. yaml.safe_dump wrote '.'
    plain, and R's yaml package (analysis/lib/paths.R) resolves a plain scalar with the YAML 1.1 float
    pattern [-+]?([0-9][0-9_]*)?\\.[0-9.]*([eE][-+][0-9]+)?, which '.' matches (PyYAML's resolver needs a
    digit): R read NA ('. is not a real') and sar_paths() stopped at `if (startsWith(v, "/"))`, so every
    R paper generator failed under a copy-october canon. A quoted scalar is a string to every
    YAML reader. One 'key: "value"' line per key (JSON string syntax, never wrapped)."""
    import re
    from analysis.lib.paths import load_paths
    P = load_paths()
    prefix = prefix or canon.DEFAULT_PREFIX
    cfg = {k: str(v) for k, v in P.items() if k != "repo_root"}
    cfg["repo_root"] = "."
    for k in canon.KEYS:
        cfg[k] = str(Path(dest).resolve() / prefix[k])
    if output is not None:
        cfg["output"] = str(Path(output).resolve())
    bad = [k for k in cfg if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k)]
    if bad:
        raise SystemExit(f"write_paths_yaml: paths keys {bad} are not plain names")
    Path(out).write_text("".join(f"{k}: {json.dumps(v, ensure_ascii=False)}\n" for k, v in cfg.items()),
                         encoding="utf-8")
    return Path(out)


def copy_october(dest: Path, switches=None) -> dict:
    """An M canon at DEST that is a byte copy of October (plus CANON.json, cal/counts.json and the
    prefix MANIFESTs). DEST follows canon.check_place. The October roots are only read."""
    dest = Path(dest).resolve()
    try:
        canon.check_place(dest, REPO)
    except canon.CanonError as e:
        raise SystemExit(f"copy-october: {e}") from None
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"copy-october: {dest} exists and is not empty")
    dest.mkdir(parents=True, exist_ok=True)
    pre = dict(canon.DEFAULT_PREFIX)
    for k in canon.KEYS:
        src = canon.october_path(k)
        if src.is_dir():
            shutil.copytree(src, dest / pre[k], symlinks=False)
        else:
            (dest / pre[k]).mkdir(parents=True)   # cal_intermediates is git-ignored; absent on a fresh clone
    from pipeline.lib import r1_config
    (dest / pre["cal"] / canon.COUNTS).write_text(json.dumps(r1_config.counts(), indent=1) + "\n", encoding="utf-8")
    meta = {"schema": canon.SCHEMA, "canon": "M", "prefix": pre, "switches": dict(switches or {})}
    (dest / canon.CANON_JSON).write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return write_manifests(dest)


def _switch(s: str):
    name, _, val = s.partition("=")
    if not name or val not in ("true", "false"):
        raise argparse.ArgumentTypeError(f"--switch NAME=true|false, got {s!r}")
    return name, val == "true"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("manifest"); m.add_argument("root")
    c = sub.add_parser("check"); c.add_argument("root"); c.add_argument("--tsv", default=str(TSV))
    o = sub.add_parser("copy-october"); o.add_argument("dest")
    o.add_argument("--switch", type=_switch, action="append", default=[])
    o.add_argument("--paths-out", default=None); o.add_argument("--output", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "manifest":
        for pre, n in write_manifests(Path(a.root)).items():
            print(f"MANIFEST {pre} {n} files")
        return 0
    if a.cmd == "check":
        probs = check(Path(a.root), a.tsv)
        for p in probs:
            print(f"CANON_FAIL {p}")
        n = sum(1 for r in read_tsv(a.tsv) if r["key"] in canon.KEYS)
        print(f"CANON_OK {n} rows" if not probs else f"CANON_FAIL {len(probs)} problem(s)")
        return 0 if not probs else 1
    done = copy_october(Path(a.dest), dict(a.switch))
    for pre, n in done.items():
        print(f"MANIFEST {pre} {n} files")
    if a.paths_out:
        print("paths", write_paths_yaml(Path(a.dest), Path(a.paths_out), a.output), f"(from {config_file()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
