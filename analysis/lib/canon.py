"""Which inputs the paper generators read: the October trees in the repository, or an M canon.

The generators read six paths.yaml keys from the paths config in force (config/paths.yaml, or the
file $SAR_PATHS_CONFIG names). When all six point at their October roots the mode is october; when
all six sit under one directory that holds CANON.json, that directory is an M canon:

    key                 October root                              M root
    cal                 data/cal2026-10                           <canon>/cal
    frames              data/frames                               <canon>/frames
    expected            analysis/expected                         <canon>/expected
    raw_verified        data/raw_verified                         <canon>/raw_verified
    paper_inputs        data/paper_inputs                         <canon>/paper_inputs
    cal_intermediates   output/cal_intermediates/cal2026-10       <canon>/cal_intermediates

Mode. In M, all six keys sit directly under one canon root (the parent of the cal root), whose
CANON.json reads:
    {"schema": "sar.r1.canon.v1", "canon": "M", "prefix": {<key>: <dir name>}, "switches": {<name>: bool}}
A config that moves only some keys, or a root without CANON.json, is refused (CanonError), so two
runs are never mixed silently.

Where an M canon may live. Outside the clone (for example /work/canon_m), or inside it under data/
(for example data/report). Anywhere else in the clone is refused. Wherever it lives, neither the
canon root nor a key directory may equal, contain or lie inside an October root, with symlinks
followed on both sides, so a key that links into an October tree outside the clone is refused too
(check_place).

MANIFEST keys. The October MANIFESTs are used as they are (repo-relative keys such as
data/cal2026-10/events_econ_cal2026-10.csv; analysis/expected uses bare names). An M canon has one
MANIFEST.sha256 per key, written by tools/r1_canon.py, with keys '<prefix>/<rel>' (such as
cal/events_econ_cal2026-10.csv) wherever the canon lives, so a file from the wrong run cannot pass.
key(path) gives the key a path has in the canon in force.

This is the only module that spells the October roots. The generators take every root from
load_paths() and every MANIFEST key and provenance string from key();
tests/test_r1_canon_generators.py checks that their October output stays byte-identical.

    from analysis.lib import canon
    canon.mode()                         # 'october' | 'M'
    canon.key(P["cal"] / "events_econ_cal2026-10.csv")
    canon.manifest("cal")                # the MANIFEST.sha256 the cal root is pinned by
    canon.pinned(path)                   # path, after its sha256 matched
    canon.switch("p_full_precision")     # False in October; CANON.json switches in M
    canon.counts()["events"]["econ"]     # October: config/r1/counts_B0.json; M: <canon>/cal/counts.json
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from analysis.lib.paths import REPO_ROOT, config_file, load_paths

SCHEMA = "sar.r1.canon.v1"
CANON_JSON = "CANON.json"
MANIFEST = "MANIFEST.sha256"
COUNTS = "counts.json"
COUNTS_SCHEMA = "sar.r1.counts.v1"
FIELDS = ("econ", "chemistry", "math_stats")
KEYS = ("cal", "frames", "expected", "raw_verified", "paper_inputs", "cal_intermediates")
#: the October root of each canon key, repo-relative (the values an October paths config holds)
OCTOBER = {"cal": "data/cal2026-10", "frames": "data/frames", "expected": "analysis/expected",
           "raw_verified": "data/raw_verified", "paper_inputs": "data/paper_inputs",
           "cal_intermediates": "output/cal_intermediates/cal2026-10"}
#: the October MANIFEST that pins each key's files (repo-relative). cal_intermediates has none:
#: its one file (pairs_unified.csv) is pinned by the October econ build report.
OCTOBER_MANIFEST = {"cal": "data/cal2026-10/MANIFEST.sha256", "frames": "data/MANIFEST.sha256",
                    "raw_verified": "data/MANIFEST.sha256", "expected": "analysis/expected/MANIFEST.sha256",
                    "paper_inputs": "data/paper_inputs/MANIFEST.sha256"}
#: the prefixes tools/r1_canon.py copy-october writes (an assembled canon may name its own)
DEFAULT_PREFIX = {k: k for k in KEYS}
#: the one directory of the clone an M canon may live under
M_HOME = "data"


class CanonError(RuntimeError):
    """The canon in force is malformed, mixed, or a lookup has no answer in it."""


class Canon:
    """The resolved canon: mode, the six roots, the canon root and CANON.json (M only)."""

    def __init__(self, mode, roots, repo, root=None, meta=None, repo_raw=None):
        self.mode, self.roots, self.repo, self.root, self.meta = mode, roots, repo, root, meta
        self.repo_raw = repo_raw or repo

    @property
    def prefix(self) -> dict:
        return dict(self.meta["prefix"]) if self.meta else {}


def _paths(P):
    return P if P is not None else load_paths()


def state(P: dict | None = None) -> Canon:
    """The canon the paths config in force (or `P`) selects; CanonError if it is mixed or malformed."""
    P = _paths(P)
    repo_raw = Path(P.get("repo_root", REPO_ROOT))
    repo = repo_raw.resolve()
    missing = [k for k in KEYS if k not in P]
    if missing:
        raise CanonError(f"paths config {config_file()} lacks the canon keys {missing}; "
                         "config/paths.yaml lists all six")
    roots = {k: Path(P[k]).resolve() for k in KEYS}
    at_october = {k: roots[k] == (repo / OCTOBER[k]).resolve() for k in KEYS}
    if all(at_october.values()):
        return Canon("october", roots, repo, repo_raw=repo_raw)
    if any(at_october.values()):
        raise CanonError(
            "mixed canon roots: " + ", ".join(k for k in KEYS if at_october[k]) + " point at October, "
            + ", ".join(k for k in KEYS if not at_october[k]) + " do not; move all six keys or none")
    root = roots["cal"].parent
    cj = root / CANON_JSON
    if not cj.is_file():
        raise CanonError(f"{root} is not an M canon: no {CANON_JSON} next to the cal root {roots['cal']}")
    try:
        meta = json.loads(cj.read_text(encoding="utf-8"))
    except ValueError as e:
        raise CanonError(f"{cj}: not JSON ({e})") from None
    _check_meta(meta, cj)
    for k in KEYS:
        if roots[k] != (root / meta["prefix"][k]).resolve():
            raise CanonError(f"paths key {k} = {roots[k]} is not {root}/{meta['prefix'][k]} "
                             f"({cj} prefix); every canon key must sit under one canon root")
    check_place(root, repo, roots.values())
    return Canon("M", roots, repo, root, meta, repo_raw=repo_raw)


def _within(p: Path, d: Path) -> bool:
    return p == d or d in p.parents


def check_place(root, repo, key_roots=()) -> None:
    """CanonError unless an M canon may live at `root`. The root and every key directory, after
    symlinks are followed, must not equal, contain or lie inside an October root (as spelled or
    after symlinks are followed), wherever they are. Those inside the clone `repo` must also lie
    under <repo>/data/."""
    repo, root = Path(repo).resolve(), Path(root).resolve()
    home = repo / M_HOME
    octs = sorted({repo / v for v in OCTOBER.values()} | {(repo / v).resolve() for v in OCTOBER.values()})
    for p in [root, *(Path(r).resolve() for r in key_roots)]:
        if _within(p, repo) and home not in p.parents:
            raise CanonError(f"M canon path {p} is inside the clone {repo} but not under {home}/; "
                             f"an M canon lives outside the clone or under {M_HOME}/")
        hit = next((o for o in octs if _within(p, o) or _within(o, p)), None)
        if hit is not None:
            raise CanonError(f"M canon path {p} overlaps the October root {hit}; "
                             "it must not equal, contain or lie inside one")


def _check_meta(meta, where) -> None:
    ok = isinstance(meta, dict) and meta.get("schema") == SCHEMA and meta.get("canon") == "M"
    pre = meta.get("prefix") if ok else None
    ok = ok and isinstance(pre, dict) and set(pre) == set(KEYS) and all(
        isinstance(v, str) and v and "/" not in v and v not in (".", "..") for v in pre.values()) \
        and len(set(pre.values())) == len(KEYS)
    sw = meta.get("switches") if ok else None
    ok = ok and isinstance(sw, dict) and all(isinstance(v, bool) for v in sw.values())
    if not ok:
        raise CanonError(f"{where}: not a {SCHEMA} file (canon 'M', prefix = one directory name per key "
                         f"{list(KEYS)}, switches = {{name: bool}})")


def mode(P: dict | None = None) -> str:
    """'october' or 'M'."""
    return state(P).mode


def root(key_name: str, P: dict | None = None) -> Path:
    """The root of one canon key in the canon in force."""
    return state(P).roots[key_name]


def kind_of(path, P: dict | None = None) -> str:
    """The canon key whose root holds `path` (the longest root wins); CanonError if none does."""
    s = state(P)
    p = Path(path).resolve()
    for k in sorted(KEYS, key=lambda k: -len(str(s.roots[k]))):
        if p == s.roots[k] or s.roots[k] in p.parents:
            return k
    raise CanonError(f"{p} is under no canon root")


def key(path, P: dict | None = None) -> str:
    """The MANIFEST key / provenance string of `path`: repo-relative in October (exactly
    `path.resolve().relative_to(repo_root)`, as the generators wrote it before this module),
    '<prefix>/<rel>' under an M root, and repo-relative for a repo file outside the canon in M."""
    s = state(P)
    p = Path(path).resolve()
    if s.mode == "M":
        try:
            k = kind_of(p, P)
        except CanonError:
            k = None
        if k is not None:
            rel = p.relative_to(s.roots[k]).as_posix()
            return s.prefix[k] if rel == "." else f"{s.prefix[k]}/{rel}"
    try:
        return p.relative_to(s.repo).as_posix()
    except ValueError:
        pass
    try:   # a symlinked data directory: the path as spelled, against the repo as configured
        return Path(os.path.abspath(path)).relative_to(s.repo_raw).as_posix()
    except ValueError:
        raise CanonError(f"{p} is neither under a canon root nor inside the repo {s.repo}") from None


_key_of = key   # pinned() takes a `key` argument, as its October pin helpers always did


def resolve(k: str, P: dict | None = None) -> Path:
    """The path a key names (the inverse of key()). In M, a '<prefix>/...' key and a key recorded by
    an October report under an October root (data/cal2026-10/...) both map onto the M root."""
    s = state(P)
    k = str(k).strip()
    if s.mode == "M":
        for name in sorted(KEYS, key=lambda n: -len(OCTOBER[n])):
            for pre in (s.prefix[name], OCTOBER[name]):
                if k == pre or k.startswith(pre + "/"):
                    return s.roots[name] / k[len(pre):].lstrip("/") if k != pre else s.roots[name]
    return s.repo / k


def october_path(key_name: str, rel: str = "") -> Path:
    """Where a canon key's file lives in October (the source a carried row is copied from)."""
    return (REPO_ROOT / OCTOBER[key_name] / rel) if rel else REPO_ROOT / OCTOBER[key_name]


def manifest(kind: str, P: dict | None = None) -> Path:
    """The MANIFEST.sha256 that pins one canon key's files."""
    s = state(P)
    if kind not in KEYS:
        raise CanonError(f"{kind!r} is not a canon key {list(KEYS)}")
    if s.mode == "M":
        return s.roots[kind] / MANIFEST
    if kind not in OCTOBER_MANIFEST:
        raise CanonError(f"October has no MANIFEST for {kind} (its file is pinned by the econ build report)")
    return s.repo / OCTOBER_MANIFEST[kind]


def freeze_manifest(freeze_root, P: dict | None = None) -> Path:
    """The MANIFEST a freeze directory's pin helper reads: the directory's own MANIFEST.sha256 in
    October (unchanged), the canon key's MANIFEST in M (an M canon has one MANIFEST per key); a repo
    directory outside the canon keeps its own MANIFEST in both."""
    s = state(P)
    if s.mode == "october":
        return Path(freeze_root) / MANIFEST
    try:
        kind = kind_of(freeze_root, P)
    except CanonError:
        return Path(freeze_root) / MANIFEST      # a repo freeze outside the canon (read in place)
    return manifest(kind, P)


def read_manifest(path) -> dict:
    """{key: sha256} of a MANIFEST.sha256 ('<sha>  <key>' lines)."""
    out = {}
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        if ln.strip():
            h, _, name = ln.partition("  ")
            out[name.strip()] = h.strip()
    return out


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pinned(path, key: str | None = None, P: dict | None = None) -> Path:
    """`path`, after its sha256 matched its canon key's MANIFEST (else the MANIFEST.sha256 of the
    file's own directory). `key` names the entry in October (an alias, e.g. the _invalid_run2 files
    recorded one level up); an M MANIFEST is written from the files themselves, so in M the key is
    always key(path). CanonError when the file is pinned nowhere or its sha256 differs."""
    s = state(P)
    path = Path(path)
    want_key = key if (key and s.mode == "october") else _key_of(path, P)
    mans = []
    try:
        mans.append(manifest(kind_of(path, P), P))
    except CanonError:
        pass
    mans.append(path.parent / MANIFEST)
    for man in dict.fromkeys(mans):
        if not man.is_file():
            continue
        pins = read_manifest(man)
        if want_key in pins:
            got = sha256(path)
            if got != pins[want_key]:
                raise CanonError(f"{want_key}: sha256 {got} != {man} pin {pins[want_key]}")
            return path
    raise CanonError(f"{want_key}: not pinned in {' nor '.join(str(m) for m in dict.fromkeys(mans))}")


def switch(name: str, P: dict | None = None) -> bool:
    """A paper-layer switch: always False in October; in M the CANON.json value, and a name the
    canon does not declare is a CanonError (never a silent default)."""
    s = state(P)
    if s.mode == "october":
        return False
    sw = s.meta["switches"]
    if name not in sw:
        raise CanonError(f"switch {name!r} is not declared in {s.root / CANON_JSON} (declared: {sorted(sw)})")
    return bool(sw[name])


def counts(P: dict | None = None) -> dict:
    """The run's event counts: October = pipeline.lib.r1_config.counts() (config/r1/counts_B0.json
    unless $SAR_R1_COUNTS); M = <canon>/cal/counts.json (sar.r1.counts.v1)."""
    s = state(P)
    if s.mode == "october":
        from pipeline.lib import r1_config
        return r1_config.counts()
    p = s.roots["cal"] / COUNTS
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise CanonError(f"{p}: the M canon's counts file is missing or not JSON ({e})") from None
    ok = (isinstance(d, dict) and d.get("schema") == COUNTS_SCHEMA and isinstance(d.get("events"), dict)
          and all(isinstance(d["events"].get(f), int) for f in FIELDS)
          and isinstance(d.get("events_total"), int) and isinstance(d.get("candidates"), int)
          and d["events_total"] == sum(d["events"][f] for f in FIELDS))
    if not ok:
        raise CanonError(f"{p}: not a {COUNTS_SCHEMA} file (events {FIELDS}, events_total = their sum, candidates)")
    return d
