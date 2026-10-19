"""TDD red tests for U0 atomic_io.py (group 2: T07-T09).

Guards the atomic write sequence (G7):
T07 write sequence = .partial -> flush -> durable_fsync(file) -> os.replace -> durable_fsync(parent_dir)
T08 network/external volume ENOTSUP -> degrade to os.fsync and log it (not silently swallowed)
T09 cross-volume write -> raise CrossVolumeError; the tmp name carries pid+uuid (deterministic + isolated)

No identification rule involved: purely local atomic writes, no data fetching, no network.
"""
import errno
import os
import pathlib
import sys
import uuid

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common.atomic_io import (  # noqa: E402
    atomic_write_bytes,
    durable_fsync,
    CrossVolumeError,
)


# ---------------------------------------------------------------------------
# T07: write sequence = .partial -> flush -> durable_fsync(file) -> os.replace -> durable_fsync(parent_dir)
# ---------------------------------------------------------------------------
def test_t07_write_sequence_order(tmp_path, monkeypatch):
    """Pins the order of the five steps of the write sequence, and that each step acts on the right object."""
    target = tmp_path / "artifact.json"
    calls = []  # record every monitored call in time order

    real_replace = os.replace
    real_fdatasync = getattr(os, "fdatasync", None)
    real_fsync = os.fsync

    def spy_replace(src, dst):
        # .partial must exist first and the target must not exist yet (replace is the atomic rename)
        calls.append(("os.replace", str(src), str(dst)))
        assert str(src).endswith(".partial"), "replace source must be the .partial temporary file"
        return real_replace(src, dst)

    def spy_durable_fsync(fd_or_path):
        calls.append(("durable_fsync", fd_or_path))
        return _orig_durable_fsync(fd_or_path)

    # intercept durable_fsync (the module calls it once on the file and once on the parent)
    import common.atomic_io as aio
    _orig_durable_fsync = aio.durable_fsync
    monkeypatch.setattr(aio, "durable_fsync", spy_durable_fsync)
    monkeypatch.setattr(os, "replace", spy_replace)

    atomic_write_bytes(target, b'{"k": 1}')

    # content is correct
    assert target.read_bytes() == b'{"k": 1}'
    # .partial has been swapped away, nothing left behind
    assert not list(tmp_path.glob("*.partial"))

    names = [c[0] for c in calls]
    # there must be exactly 2 durable_fsync calls (one on the file, one on the parent) around os.replace
    assert names.count("durable_fsync") == 2, f"expected one fsync each on the file and the parent, got {names}"
    assert names.count("os.replace") == 1
    # order: first durable_fsync(file) -> os.replace -> second durable_fsync(parent)
    i_fsync1 = names.index("durable_fsync")
    i_replace = names.index("os.replace")
    i_fsync2 = len(names) - 1 - names[::-1].index("durable_fsync")
    assert i_fsync1 < i_replace < i_fsync2, f"order must be file-fsync → replace → parent-fsync, got {names}"

    # the object of the last durable_fsync must be the parent directory (a path pointing to tmp_path)
    last_fsync_arg = calls[i_fsync2][1]
    assert pathlib.Path(last_fsync_arg) == tmp_path, "the last fsync must be on the parent directory"


# ---------------------------------------------------------------------------
# T08: ENOTSUP (network/external volume does not support fdatasync) -> degrade to os.fsync and log it, not silently swallowed
# ---------------------------------------------------------------------------
def test_t08_enotsup_degrades_to_fsync_and_logs(tmp_path, monkeypatch, caplog):
    """The main flush call on an external/network volume raises ENOTSUP -> must degrade to os.fsync and leave a log line (not silent).

    Runs on any platform: inject an os.fdatasync that raises ENOTSUP (even though native macOS has none),
    then use a separate spy on os.fsync to verify the degradation really happened and the log line was really left.
    """
    fsync_called = {"n": 0}
    real_fsync = os.fsync

    def fake_fdatasync(fd):
        raise OSError(errno.ENOTSUP, "Operation not supported")

    def spy_fsync(fd):
        fsync_called["n"] += 1
        return real_fsync(fd)

    # raising=False: native macOS has no os.fdatasync; monkeypatch can still create the attribute
    monkeypatch.setattr(os, "fdatasync", fake_fdatasync, raising=False)
    monkeypatch.setattr(os, "fsync", spy_fsync)

    fd = os.open(str(tmp_path / "probe.bin"), os.O_WRONLY | os.O_CREAT)
    try:
        os.write(fd, b"x")
        with caplog.at_level("WARNING"):
            durable_fsync(fd)  # it should swallow ENOTSUP, call os.fsync instead, and log it
    finally:
        os.close(fd)

    assert fsync_called["n"] >= 1, "after ENOTSUP it must fall back to os.fsync"
    # not silent: must leave a visible log line (containing ENOTSUP or the word degrade)
    blob = caplog.text.lower()
    assert ("enotsup" in blob) or ("degrad" in blob) or ("fdatasync" in blob), \
        f"the fallback must be logged, not silently swallowed, caplog={caplog.text!r}"


def test_t08_other_oserror_not_swallowed(tmp_path, monkeypatch):
    """An OSError other than ENOTSUP (such as EIO) must never be silently degraded as if it were ENOTSUP -> it must be re-raised.

    Cross-platform: inject an os.fdatasync that raises EIO and assert durable_fsync lets EIO propagate unchanged.
    """
    def fake_fdatasync(fd):
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(os, "fdatasync", fake_fdatasync, raising=False)

    fd = os.open(str(tmp_path / "probe2.bin"), os.O_WRONLY | os.O_CREAT)
    try:
        os.write(fd, b"y")
        with pytest.raises(OSError) as ei:
            durable_fsync(fd)
        assert ei.value.errno == errno.EIO, "EIO is not ENOTSUP and must not be swallowed by the fallback"
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# T09: cross-volume write -> raise CrossVolumeError; the tmp name carries pid + uuid
# ---------------------------------------------------------------------------
def test_t09_cross_volume_raises(tmp_path, monkeypatch):
    """The target's parent directory and the .partial temp file are not on the same volume (os.replace EXDEV) -> CrossVolumeError."""
    target = tmp_path / "out.json"

    real_replace = os.replace

    def fake_replace(src, dst):
        # simulate cross-volume: os.replace raises EXDEV between different file systems
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "replace", fake_replace)

    with pytest.raises(CrossVolumeError):
        atomic_write_bytes(target, b"data")


def test_t09_tmp_name_has_pid_and_uuid(tmp_path, monkeypatch):
    """.partial temp name must carry pid + uuid (deterministic traceability + isolation between concurrent writers)."""
    target = tmp_path / "out.json"
    seen_tmp_names = []

    real_replace = os.replace

    def spy_replace(src, dst):
        seen_tmp_names.append(pathlib.Path(src).name)
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)
    atomic_write_bytes(target, b"data")

    assert len(seen_tmp_names) == 1
    tmp_name = seen_tmp_names[0]
    assert tmp_name.endswith(".partial"), f"temporary name must end with .partial, got {tmp_name}"
    # carries the current process pid
    assert str(os.getpid()) in tmp_name, f"temporary name must contain pid={os.getpid()}, got {tmp_name}"
    # carries a parseable uuid (extract the hex segment from the name to verify)
    # the name looks like out.json.<pid>.<uuid hex>.partial -> take the uuid segment
    parts = tmp_name.split(".")
    hex_candidates = [p for p in parts if len(p) >= 32 and all(c in "0123456789abcdef" for c in p)]
    assert hex_candidates, f"temporary name must contain a uuid hex segment (≥32 hex), got {tmp_name}"
    # parseable by uuid.UUID = a real uuid, not an arbitrary string
    uuid.UUID(hex=hex_candidates[0])


def test_t09_concurrent_tmp_names_distinct(tmp_path, monkeypatch):
    """Two consecutive writes to the same target -> the two .partial names must differ (uuid keeps concurrent writers from colliding)."""
    target = tmp_path / "out.json"
    names = []

    real_replace = os.replace

    def spy_replace(src, dst):
        names.append(pathlib.Path(src).name)
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)
    atomic_write_bytes(target, b"a")
    atomic_write_bytes(target, b"b")

    assert len(names) == 2
    assert names[0] != names[1], "the .partial names of two writes must differ (uuid isolation)"
