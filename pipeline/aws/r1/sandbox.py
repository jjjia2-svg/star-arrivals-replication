#!/usr/bin/env python3
"""R1 F2 sandbox: run the October chain on a clone where no October product can be read by accident.
Runs on an R1 instance only. Standard library only (inotify through ctypes).

  sandbox.py purge --repo R --tsv config/r1/base_inputs.tsv --ref /work/ref/october --config B0|M
                   --table STAGES.json --allowlist config/r1/read_allowlist_0828.txt --out STAGE_OUT [--work DIR]
  sandbox.py watch --repo R --ref REF --status WORK/status.txt --reads WORK/reads --pid WORK/sandbox_watch.pid
  sandbox.py check --record base_record.json --reads DIR [--reads DIR] --allowlist A --config B0|M --out STAGE_OUT
                   --table STAGES.json [--repo R] [--work DIR]

purge (stage `sandbox`), in this order; a STOP before step 3 moves nothing:
  1. the TSV equals `git ls-files -s` under the four roots (same paths, same blob ids; the r1_input rows' blobs
     too), else STOP TSV_STALE;
  2. no `repo:` output token of any stage in --table equals or contains a base or r1_input path (run_stages deletes
     a stage's outputs before running it), else STOP OUTPUT_COVERS_BASE;
  3. every product moves to REF/<repo path> (os.rename; copy2 + unlink across devices), then REF is made read-only;
  4. the marker R/.r1_sandbox.json {config, commit, ref, tsv_sha256};
  5. every base and r1_input file present in the clone is made read-only and fingerprinted into
     STAGE_OUT/base_record.json {path: {sha256, inode, mtime_ns, size}};
  6. the watcher starts in its own session, ignoring SIGHUP (setsid + nohup); purge waits for its READY (30 s).
watch: inotify IN_OPEN|IN_CREATE|IN_MOVED_TO on every directory under data/cal2026-08-28,
  pipeline/stars/caliber_2026-08-28, data/raw_verified (only names containing cal2026-08-28),
  data/cal2026-10/_invalid_run2 (base, but it holds byte copies of October event products, so every read of it
  must be allowlisted) and REF. The stage of
  an event is the last word of the status file (run_stages writes '<UTC> STAGE <name>'), followed through the same
  event queue, so a read is charged to the stage that was running when it happened. Each (stage, path) is appended
  once to READS/<stage>.tsv as '<stage>\\t<repo path>' or '<stage>\\tref:<path>'. A queue overflow writes __LOST__.
  Leaving a stage (a status change), and a clean SIGTERM drain, append '<stage>\\t__END__' to its log: a log that
  ends with it is complete. run_stages writes '<UTC> IDLE' after each stage and waits for that end line.
  Stage boundaries are acknowledged through READS/<stage>.tsv: the watcher creates it while handling the
  stage's status line, and run_stages starts the stage only once it exists (J0 review #7).
check (stage `sandbox_check`): stops the watcher first (its last events are flushed and the rehash below is not
  logged), rehashes the base inputs, matches every logged read against the allowlist for --config, writes
  STAGE_OUT/sandbox_check.json {verdict OK|STOP_REWRITE|G_READ_FAIL|AUDIT_LOST, rewritten, gread,
  unused_allowlist, audited_stages, audit_missing, audit_unterminated} and exits 1 unless OK. A watcher that is
  gone or will not stop = AUDIT_LOST; so is a stage of --table between sandbox and sandbox_check without a log, or
  whose log does not end with its end line (J0 review #5).
  The first --reads is the live log directory (WORK/reads); a stage log found only in a later one (the resumed
  job's WORK/resume/_reads) is copied into it first, so the audit of a skipped stage survives a second resume;
  then only the live directory is read, so a stage that reran here is judged by its fresh log alone.
--work defaults to $WORK and --repo to $REPO_DIR (run_stages sets both). The watcher's files are WORK/status.txt,
WORK/reads/, WORK/sandbox_watch.pid and WORK/sandbox_watch.log.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import dataclasses
import errno
import functools
import hashlib
import json
import os
import pathlib
import posixpath
import re
import select
import shutil
import signal
import stat
import struct
import subprocess
import sys
import time

HOSTS = ("ec2-r1-test", "ec2-r1")
#: the four trees whose tracked files config/r1/base_inputs.tsv classifies
ROOTS = ("data/cal2026-10", "data/frames", "analysis/expected", "data/cal2026-08-28")
CLASSES = ("base", "product", "r1_input")
TSV_HEADER = ("path", "class", "git_blob", "producer", "reason")
CONFIGS = ("B0", "M")
#: repo trees whose reads are logged; under data/raw_verified only file names containing the needle.
#: data/cal2026-10/_invalid_run2 stays base (write_events reads its verdicts table) but also holds byte copies of
#: October event products, so it is watched: a read of any file there other than an allowlisted one is reported
#: (pre-J0 sandbox review 2026-10-16, finding 1)
WATCHED = ("data/cal2026-08-28", "pipeline/stars/caliber_2026-08-28", "data/raw_verified",
           "data/cal2026-10/_invalid_run2")
NAME_FILTER = {"data/raw_verified": "cal2026-08-28"}
LOST = "__LOST__"
END = "__END__"                      # the last line of a complete stage log (Watcher.end_stage)
NO_STAGE = "__nostage__"
STAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9_]{0,40}$")
PID_NAME, LOG_NAME = "sandbox_watch.pid", "sandbox_watch.log"
READY_SECS, STOP_SECS = 30, 60
MARKER = ".r1_sandbox.json"

# <sys/inotify.h>
IN_CLOSE_WRITE, IN_OPEN, IN_MOVED_TO, IN_CREATE = 0x8, 0x20, 0x80, 0x100
IN_Q_OVERFLOW, IN_IGNORED, IN_ONLYDIR, IN_ISDIR = 0x4000, 0x8000, 0x01000000, 0x40000000
IN_NONBLOCK, IN_CLOEXEC = 0o4000, 0o2000000
READ_MASK = IN_OPEN | IN_CREATE | IN_MOVED_TO | IN_ONLYDIR
STATUS_MASK = IN_CLOSE_WRITE | IN_MOVED_TO | IN_ONLYDIR
EVENT = struct.Struct("iIII")                      # struct inotify_event {int wd; u32 mask, cookie, len; char name[]}


class Stop(Exception):
    """A purge that must not go on; `items` are the offending paths (or 'stage token -> path')."""

    def __init__(self, code: str, items):
        self.code, self.items = code, [str(x) for x in items]
        super().__init__(f"{code}: {', '.join(self.items[:10])}{' ...' if len(self.items) > 10 else ''}")


# ---- formats shared with tools/r1_classify_cal_tree.py ----------------------------------------------------------
@functools.lru_cache(maxsize=None)
def glob_re(pattern: str) -> re.Pattern:
    """'**' matches across '/', '*' and '?' stay inside one path segment, everything else is literal (fullmatch)."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        out.append({"*": "[^/]*", "?": "[^/]"}.get(pattern[i], re.escape(pattern[i])))
        i += 1
    return re.compile("".join(out))


def render_tsv(rows) -> str:
    rows = [tuple(r) for r in rows]
    for r in rows:
        if len(r) != len(TSV_HEADER) or any("\t" in f or "\n" in f for f in r):
            raise ValueError(f"bad base_inputs row {r!r}")
    return "".join("\t".join(r) + "\n" for r in [TSV_HEADER, *rows])


def load_tsv(path) -> list[dict]:
    lines = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
    if not lines or tuple(lines[0].split("\t")) != TSV_HEADER:
        raise ValueError(f"{path}: header is not {TSV_HEADER}")
    rows = []
    for n, ln in enumerate(lines[1:], 2):
        f = ln.split("\t")
        if len(f) != len(TSV_HEADER) or f[1] not in CLASSES or not f[0]:
            raise ValueError(f"{path}:{n}: bad row")
        rows.append(dict(zip(TSV_HEADER, f)))
    return rows


@dataclasses.dataclass(frozen=True)
class AllowRow:
    glob: str                              # a repo path glob, or 'ref:<glob>' for the October reference copy
    configs: tuple                         # ('*',) = every config
    stages: tuple | None                   # None = every stage
    reason: str

    def applies(self, config: str) -> bool:
        return "*" in self.configs or config in self.configs

    def allows(self, stage: str, path: str) -> bool:
        return (self.stages is None or stage in self.stages) and bool(glob_re(self.glob).fullmatch(path))


def load_allowlist(path) -> list[AllowRow]:
    """TAB rows: glob, configs (B0|M|* or a comma list), stages (* or a comma list), reason (> 30 chars)."""
    rows = []
    for n, ln in enumerate(pathlib.Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        f = ln.split("\t")
        if len(f) != 4:
            raise ValueError(f"{path}:{n}: want 4 TAB fields, got {len(f)}")
        glob, configs, stages, reason = (x.strip() for x in f)
        cfg = tuple(c.strip() for c in configs.split(","))
        if not glob or any(c not in CONFIGS + ("*",) for c in cfg):
            raise ValueError(f"{path}:{n}: configs must be B0, M or *")
        st = None if stages == "*" else tuple(s.strip() for s in stages.split(","))
        if st is not None and not all(STAGE_NAME.match(s) for s in st):
            raise ValueError(f"{path}:{n}: bad stage list {stages!r}")
        if glob.startswith("ref:") and st is None:
            raise ValueError(f"{path}:{n}: a ref: row names the stages that may read the reference copy")
        if len(reason) <= 30:
            raise ValueError(f"{path}:{n}: the reason must be longer than 30 characters")
        rows.append(AllowRow(glob, cfg, st, reason))
    return rows


# ---- helpers -----------------------------------------------------------------------------------------------------
def sha256_file(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tracked(repo, paths) -> dict:
    """{path: blob id} from `git ls-files -s` for the given pathspecs."""
    r = subprocess.run(["git", "-C", str(repo), "ls-files", "-s", "-z", "--", *paths], capture_output=True)
    if r.returncode != 0:
        raise Stop("GIT", [r.stderr.decode("utf-8", "replace").strip()[:200]])
    out = {}
    for rec in r.stdout.split(b"\0"):
        if rec:
            meta, path = rec.split(b"\t", 1)
            out[path.decode("utf-8")] = meta.split()[1].decode()
    return out


def tsv_drift(rows, repo) -> list[str]:
    """Paths where the TSV and the clone's git index disagree (missing row, extra row, other blob)."""
    idx = tracked(repo, ROOTS)
    have = {r["path"]: r["git_blob"] for r in rows if r["class"] != "r1_input"}
    drift = sorted(p for p in set(idx) | set(have) if idx.get(p) != have.get(p))
    r1 = [r for r in rows if r["class"] == "r1_input" and not r["path"].startswith("s3:")]
    if r1:
        got = tracked(repo, [r["path"] for r in r1])
        drift += [r["path"] for r in r1 if got.get(r["path"]) != r["git_blob"]]
    return drift


def covered_outputs(table: dict, protected) -> list[str]:
    """'stage token -> path' for every repo: output that equals or contains a protected path."""
    hits = []
    for st in table.get("stages", []):
        for tok in st.get("outputs", []):
            if not tok.startswith("repo:"):
                continue
            t = posixpath.normpath(tok[len("repo:"):])
            hit = next((p for p in protected if t == "." or p == t or p.startswith(t + "/")), None)
            if hit:
                hits.append(f"{st.get('name')} {tok} -> {hit}")
    return hits


def fingerprint(repo, paths) -> dict:
    out = {}
    for p in paths:
        st = os.stat(pathlib.Path(repo) / p)
        out[p] = {"sha256": sha256_file(pathlib.Path(repo) / p), "inode": st.st_ino, "mtime_ns": st.st_mtime_ns,
                  "size": st.st_size}
    return out


def _move(src: pathlib.Path, dst: pathlib.Path) -> int:
    """1 when the move had to copy across devices."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(src, dst)
        return 0
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
    shutil.copy2(src, dst)
    os.unlink(src)
    return 1


def _read_only(p) -> None:
    os.chmod(p, stat.S_IMODE(os.stat(p).st_mode) & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def _read_only_tree(top: pathlib.Path) -> None:
    for root, _dirs, files in os.walk(top, topdown=False):         # children before their directory
        for f in files:
            _read_only(pathlib.Path(root) / f)
        _read_only(root)


def _write_json(p: pathlib.Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n", encoding="utf-8")


# ---- purge -------------------------------------------------------------------------------------------------------
def purge(*, repo, tsv, ref, config, table, allowlist, out, work) -> dict:
    repo, ref, out, work = (pathlib.Path(x).absolute() for x in (repo, ref, out, work))
    if config not in CONFIGS:
        raise Stop("BAD_CONFIG", [config])
    rows = load_tsv(tsv)
    load_allowlist(allowlist)                       # a malformed allowlist stops here, not hours later in check
    drift = tsv_drift(rows, repo)
    if drift:
        raise Stop("TSV_STALE", drift)
    protected = [r["path"] for r in rows if r["class"] != "product" and not r["path"].startswith("s3:")]
    covers = covered_outputs(json.loads(pathlib.Path(table).read_text(encoding="utf-8")), protected)
    if covers:
        raise Stop("OUTPUT_COVERS_BASE", covers)
    products = [r["path"] for r in rows if r["class"] == "product"]
    missing = [p for p in products + protected if not (repo / p).is_file()]
    if missing:
        raise Stop("INPUT_MISSING", missing)
    if ref == repo or repo in ref.parents:
        raise Stop("REF_INSIDE_REPO", [ref])
    if ref.exists() and any(ref.iterdir()):
        raise Stop("REF_NOT_EMPTY", [ref])

    n_cross = sum(_move(repo / p, ref / p) for p in products)
    ref.mkdir(parents=True, exist_ok=True)
    _read_only_tree(ref)
    commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                            check=True).stdout.strip()
    _write_json(repo / MARKER, {"config": config, "commit": commit, "ref": str(ref), "tsv_sha256": sha256_file(tsv)})
    for p in protected:
        _read_only(repo / p)
    _write_json(out / "base_record.json", fingerprint(repo, protected))
    pid = start_watcher(repo=repo, ref=ref, work=work)
    report = {"stage": "sandbox", "code": "OK", "config": config, "commit": commit, "n_moved": len(products),
              "n_moved_across_devices": n_cross, "n_protected": len(protected), "watcher_pid": pid}
    _write_json(out / "report_sandbox.json", report)
    return report


def start_watcher(*, repo, ref, work, wait=READY_SECS) -> int:
    """Start `watch` in its own session (setsid) with SIGHUP ignored (nohup); return its pid once READY."""
    work = pathlib.Path(work)
    work.mkdir(parents=True, exist_ok=True)
    log = work / LOG_NAME
    with open(log, "w", encoding="utf-8") as fh:
        proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), "watch", "--repo", str(repo),
                                 "--ref", str(ref), "--status", str(work / "status.txt"), "--reads",
                                 str(work / "reads"), "--pid", str(work / PID_NAME)],
                                stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                                start_new_session=True, close_fds=True)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if "READY" in log.read_text(encoding="utf-8", errors="replace").split():
            return proc.pid
        if proc.poll() is not None:
            raise Stop("WATCH_FAILED", [log.read_text(encoding="utf-8", errors="replace")[-300:]])
        time.sleep(0.1)
    proc.kill()
    raise Stop("WATCH_TIMEOUT", [f"no READY within {wait} s"])


def _alive(pid: int) -> bool:
    try:
        fields = pathlib.Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return fields[0] != "Z"                                   # an exited, unreaped watcher is not alive
    except (OSError, IndexError):
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def stop_watcher(pid_file, timeout=STOP_SECS) -> str:
    """SIGTERM the watcher and wait until it has flushed and removed its pid file.
    Returns stopped | absent (no pid file) | dead (died without cleaning up) | timeout."""
    pid_file = pathlib.Path(pid_file)
    try:
        pid = int(pid_file.read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return "absent"
    if not _alive(pid):
        return "dead"
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_file.exists():
            return "stopped"
        time.sleep(0.05)
    return "timeout"


# ---- watch -------------------------------------------------------------------------------------------------------
def parse_events(buf: bytes) -> list[tuple[int, int, str]]:
    """(wd, mask, name) for each struct inotify_event in a read buffer (names are NUL-padded)."""
    out, i = [], 0
    while i + EVENT.size <= len(buf):
        wd, mask, _cookie, n = EVENT.unpack_from(buf, i)
        i += EVENT.size
        out.append((wd, mask, buf[i:i + n].split(b"\0", 1)[0].decode("utf-8", "surrogateescape")))
        i += n
    return out


def _libc():
    libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
    libc.inotify_init1.argtypes, libc.inotify_init1.restype = [ctypes.c_int], ctypes.c_int
    libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
    libc.inotify_add_watch.restype = ctypes.c_int
    return libc


class Watcher:
    """Turns inotify events into per-stage read logs. Without an fd (tests) it only parses and logs."""

    def __init__(self, *, repo, ref, status, reads, fd=None, libc=None):
        self.repo, self.ref = pathlib.Path(repo), pathlib.Path(ref)
        self.status, self.reads = pathlib.Path(status), pathlib.Path(reads)
        self.fd, self.libc = fd, libc
        self.wds: dict[int, tuple[str, str]] = {}            # wd -> (repo|ref, path relative to its tree)
        self.status_wd = None
        self.seen: set = set()
        self.files: dict = {}
        self.reads.mkdir(parents=True, exist_ok=True)
        self.stage = self._read_stage()
        self._file(self.stage)

    def _read_stage(self) -> str:
        try:
            words = self.status.read_text(encoding="utf-8").split()
        except OSError:
            words = []
        return words[-1] if words and STAGE_NAME.match(words[-1]) else NO_STAGE

    def _file(self, stage):
        if stage not in self.files:
            self.files[stage] = open(self.reads / f"{stage}.tsv", "a", encoding="utf-8")
        return self.files[stage]

    def _add(self, path, mask) -> int:
        wd = self.libc.inotify_add_watch(self.fd, os.fsencode(str(path)), mask)
        if wd < 0:
            e = ctypes.get_errno()
            raise OSError(e, f"inotify_add_watch {path}: {os.strerror(e)}")
        return wd

    def add_tree(self, kind: str, top, rel: str, *, gone_ok: bool = False) -> None:
        """Watch `top` and every directory below it. gone_ok: a directory created and removed again before
        it could be watched is skipped (nothing in it can be read any more); any other failure raises."""
        for dirpath, _dirs, _files in os.walk(top):
            sub = pathlib.Path(dirpath).relative_to(top).as_posix()
            try:
                wd = self._add(dirpath, READ_MASK)
            except OSError as e:
                if gone_ok and e.errno in (errno.ENOENT, errno.ENOTDIR):
                    continue
                raise
            self.wds[wd] = (kind, rel if sub == "." else posixpath.join(rel, sub))

    def watch_status(self) -> None:
        self.status_wd = self._add(self.status.parent, STATUS_MASK)

    def end_stage(self) -> None:
        """'<stage>\\t__END__' on the current stage's log: the watcher has left the stage (a status change) or is
        stopping cleanly (SIGTERM drain). Events are handled in queue order, so every read charged to the stage
        is already above this line; a watcher killed outright leaves none. 'No stage' gets no end line."""
        if self.stage == NO_STAGE:
            return
        fh = self._file(self.stage)
        fh.write(f"{self.stage}\t{END}\n")
        fh.flush()

    def log(self, path: str) -> None:
        if (self.stage, path) in self.seen:
            return
        self.seen.add((self.stage, path))
        fh = self._file(self.stage)
        fh.write(f"{self.stage}\t{path}\n")
        fh.flush()

    def feed(self, buf: bytes) -> None:
        for wd, mask, name in parse_events(buf):
            if mask & IN_Q_OVERFLOW:
                self.log(LOST)                                   # events were dropped: fail closed
                continue
            if wd == self.status_wd and self.status_wd is not None:
                if name == self.status.name:
                    new = self._read_stage()
                    if new != self.stage:
                        self.end_stage()                         # leaving a stage closes its log
                        self.stage = new
                    self._file(self.stage)                       # an empty log still records an audited stage
                continue
            if mask & IN_IGNORED or wd not in self.wds:
                continue
            kind, rel = self.wds[wd]
            relpath = posixpath.join(rel, name) if name else rel
            if mask & IN_ISDIR:                                  # directory events are not reads, but a new
                if name and mask & (IN_CREATE | IN_MOVED_TO) and self.fd is not None:     # directory is watched too
                    self.add_tree(kind, (self.ref if kind == "ref" else self.repo) / relpath, relpath, gone_ok=True)
                continue
            if not name:
                continue
            if kind == "repo" and any((rel == root or rel.startswith(root + "/")) and needle not in name
                                      for root, needle in NAME_FILTER.items()):
                continue
            self.log(f"ref:{relpath}" if kind == "ref" else relpath)

    def close(self) -> None:
        for fh in self.files.values():
            fh.close()
        self.files = {}


def _drain(fd: int) -> bytes:
    chunks = []
    while True:
        try:
            b = os.read(fd, 1 << 16)
        except BlockingIOError:
            break
        if not b:
            break
        chunks.append(b)
    return b"".join(chunks)


def watch(*, repo, ref, status, reads, pid) -> int:
    repo, ref, pid = pathlib.Path(repo), pathlib.Path(ref), pathlib.Path(pid)
    libc = _libc()
    fd = libc.inotify_init1(IN_NONBLOCK | IN_CLOEXEC)
    if fd < 0:
        raise OSError(ctypes.get_errno(), "inotify_init1 failed")
    stop: list = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    w = Watcher(repo=repo, ref=ref, status=status, reads=reads, fd=fd, libc=libc)
    try:
        w.watch_status()
        for root in WATCHED:
            if (repo / root).is_dir():
                w.add_tree("repo", repo / root, root)
        w.add_tree("ref", ref, "")
        pid.write_text(f"{os.getpid()}\n", encoding="utf-8")
        print(f"READY {len(w.wds)} directories", flush=True)
        while not stop:
            if select.select([fd], [], [], 0.5)[0]:
                w.feed(_drain(fd))
        w.feed(_drain(fd))                       # everything the kernel queued before the SIGTERM
        w.end_stage()                            # a clean stop closes the running stage's log
    except BaseException:
        w.log(LOST)
        raise
    finally:
        w.close()
        os.close(fd)
        pid.unlink(missing_ok=True)              # last: stop_watcher waits for this
    return 0


# ---- check -------------------------------------------------------------------------------------------------------
def load_reads(dirs) -> tuple[list[tuple[str, str]], set]:
    """Every '<stage>\\t<path>' line under the given read-log directories, and the stages that have a log."""
    reads, stages = [], set()
    for d in dirs:
        d = pathlib.Path(d)
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.tsv")):
            stages.add(f.stem)
            for ln in f.read_text(encoding="utf-8").splitlines():
                if ln.strip():
                    stage, _, path = ln.partition("\t")
                    reads.append((stage, path))
    return reads, stages


def carry_forward(dirs) -> list[str]:
    """Copy into the first (live) read-log directory every <stage>.tsv of a later (resumed) directory that the
    live one lacks: a stage skipped on this resume keeps its audit for the next one, because run_stages syncs
    only the live directory to <prefix>/stages/_reads/. A stage that ran here keeps its own fresh log."""
    dirs = [pathlib.Path(d) for d in dirs]
    if len(dirs) < 2:
        return []
    live, have, copied = dirs[0], {p.name for p in dirs[0].glob("*.tsv")}, []
    for d in dirs[1:]:
        for f in sorted(d.glob("*.tsv")) if d.is_dir() else []:
            if f.name not in have:
                live.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, live / f.name)
                have.add(f.name)
                copied.append(f.stem)
    return copied


def ended_logs(d) -> set:
    """The stages whose log in `d` ends with its end line (Watcher.end_stage): a complete audit of that stage."""
    out = set()
    for f in sorted(pathlib.Path(d).glob("*.tsv")) if pathlib.Path(d).is_dir() else []:
        lines = [ln for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if lines and lines[-1] == f"{f.stem}\t{END}":
            out.add(f.stem)
    return out


def audited_span(table) -> list[str]:
    """The stages of a stage table strictly between `sandbox` and `sandbox_check`: each ran or was restored under
    the watcher, so each needs one complete log (J0 review #5)."""
    names = [s["name"] for s in json.loads(pathlib.Path(table).read_text(encoding="utf-8"))["stages"]]
    if "sandbox" not in names or "sandbox_check" not in names or names.index("sandbox") > names.index("sandbox_check"):
        raise ValueError(f"{table}: no sandbox ... sandbox_check span")
    return names[names.index("sandbox") + 1:names.index("sandbox_check")]


def collect_reads(dirs) -> tuple[list, set, set, list]:
    """(reads, stages, ended, carried) with exactly one log per stage: carry_forward first copies into the live
    directory (the first) every log only a resumed one has, then only the live directory is read - the fresh log
    of a stage that reran here, never its obsolete resumed one as well."""
    dirs = [pathlib.Path(d) for d in dirs]
    carried = carry_forward(dirs)
    reads, stages = load_reads(dirs[:1])
    return reads, stages, ended_logs(dirs[0]), carried


def check(record: dict, reads: list, allow: list, config: str, repo, *, stages=(), expected=(), ended=()) -> dict:
    """The sandbox verdict. record = base_record.json; reads = [(stage, path)]; allow = load_allowlist(...).
    expected = audited_span(table): each needs a log in `stages` that ends with its end line (in `ended`), else
    AUDIT_LOST (audit_missing / audit_unterminated). End rows are not reads."""
    if config not in CONFIGS:
        raise ValueError(f"config must be one of {CONFIGS}, got {config!r}")
    repo = pathlib.Path(repo)
    rewritten = []
    for path in sorted(record):
        p, want = repo / path, record[path]
        try:
            st = os.stat(p)
            got = {"sha256": sha256_file(p), "size": st.st_size, "inode": st.st_ino, "mtime_ns": st.st_mtime_ns}
        except FileNotFoundError:
            rewritten.append([path, "missing"])
            continue
        except OSError:
            rewritten.append([path, "unreadable"])
            continue
        rewritten += [[path, k] for k in ("sha256", "size", "inode", "mtime_ns") if got[k] != want.get(k)]
    rows = [r for r in allow if r.applies(config)]
    used, gread, lost = set(), [], False
    for stage, path in sorted(set(reads)):
        if path == LOST:
            lost = True
            continue
        if path == END:
            continue
        hit = {i for i, r in enumerate(rows) if r.allows(stage, path)}
        used |= hit
        if not hit:
            gread.append([stage, path])
    have = set(stages) | {s for s, _ in reads}
    missing = [s for s in expected if s not in have]
    unterminated = [s for s in expected if s in have and s not in set(ended)]
    lost = lost or bool(missing or unterminated)
    verdict = ("STOP_REWRITE" if rewritten else "AUDIT_LOST" if lost else "G_READ_FAIL" if gread else "OK")
    return {"verdict": verdict, "rewritten": rewritten, "gread": gread,
            "unused_allowlist": [r.glob for i, r in enumerate(rows) if i not in used],
            "audited_stages": sorted(have), "audit_missing": missing, "audit_unterminated": unterminated}


# ---- CLI ---------------------------------------------------------------------------------------------------------
def _env_path(value, var, flag) -> pathlib.Path:
    v = value or os.environ.get(var, "").strip()
    if not v:
        raise SystemExit(f"sandbox.py: give {flag} or set ${var}")
    return pathlib.Path(v)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 F2 sandbox: purge October products, watch reads, check at the end")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("purge")
    for k in ("--repo", "--tsv", "--ref", "--config", "--table", "--allowlist", "--out"):
        p.add_argument(k, required=True)
    p.add_argument("--work")
    w = sub.add_parser("watch")
    for k in ("--repo", "--ref", "--status", "--reads", "--pid"):
        w.add_argument(k, required=True)
    c = sub.add_parser("check")
    c.add_argument("--record", required=True)
    c.add_argument("--reads", required=True, action="append")
    for k in ("--allowlist", "--config", "--out"):
        c.add_argument(k, required=True)
    c.add_argument("--repo")
    c.add_argument("--work")
    c.add_argument("--table", help="the stage table; its stages between sandbox and sandbox_check need a complete log")
    a = ap.parse_args(argv)
    if os.environ.get("SAR_HOST", "").strip() not in HOSTS:
        raise SystemExit("R1 rule: sandbox.py runs only on an R1 instance ($SAR_HOST)")
    if a.cmd == "check" and not a.table:
        raise SystemExit("sandbox.py check: give --table (the stage table whose sandbox..sandbox_check span "
                         "is audited)")

    if a.cmd == "watch":
        return watch(repo=a.repo, ref=a.ref, status=a.status, reads=a.reads, pid=a.pid)

    out = pathlib.Path(a.out)
    if a.cmd == "purge":
        work = _env_path(a.work, "WORK", "--work")
        try:
            rep = purge(repo=a.repo, tsv=a.tsv, ref=a.ref, config=a.config, table=a.table, allowlist=a.allowlist,
                        out=out, work=work)
        except Stop as e:
            _write_json(out / "stop_report_sandbox.json", {"stage": "sandbox", "code": e.code,
                                                           "n_changed": len(e.items), "changed": e.items[:50]})
            print(f"STOP {e}", file=sys.stderr)
            return 1
        print(f"SANDBOX_OK moved={rep['n_moved']} protected={rep['n_protected']} watcher={rep['watcher_pid']}")
        return 0

    repo, work = _env_path(a.repo, "REPO_DIR", "--repo"), _env_path(a.work, "WORK", "--work")
    expected = audited_span(a.table)
    state = stop_watcher(work / PID_NAME)        # first: the rehash below must not be logged as a read
    reads, stages, ended, carried = collect_reads(a.reads)     # the first --reads is the live log directory
    if state != "stopped":
        reads.append(("sandbox_check", LOST))    # a watcher that died or will not stop: the audit is incomplete
    record = json.loads(pathlib.Path(a.record).read_text(encoding="utf-8"))
    res = check(record, reads, load_allowlist(a.allowlist), a.config, repo, stages=stages, expected=expected,
                ended=ended)
    _write_json(out / "sandbox_check.json", {"schema": "sar.r1.sandbox_check.v1", "config": a.config,
                                             "watcher": state, "carried_from_resume": carried, **res})
    _write_json(out / "report_sandbox_check.json", {
        "stage": "sandbox_check", "verdict": res["verdict"], "n_rewritten": len(res["rewritten"]),
        "n_gread": len(res["gread"]), "n_unused_allowlist": len(res["unused_allowlist"]),
        "n_audited_stages": len(res["audited_stages"]), "n_audit_missing": len(res["audit_missing"]),
        "n_audit_unterminated": len(res["audit_unterminated"])})
    print(f"SANDBOX_CHECK {res['verdict']} rewritten={len(res['rewritten'])} gread={len(res['gread'])} "
          f"watcher={state}")
    return 0 if res["verdict"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
