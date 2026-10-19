"""A4 regression: atomic_write_bytes must not silently commit a truncated file after a short write.

`os.write(fd, data)` is a single system call and POSIX lets it write only part of the data (returning
< len(data)); a large blob (>~2GiB, the macOS single-call limit) or ENOSPC causes a short write.
The old code ignored the return value, so durable_fsync + os.replace atomically committed the truncated
file as the target, and downstream code read a syntactically complete but tail-less parquet without any
exception. Fix: loop until everything is written.
"""
from __future__ import annotations

import os
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common.atomic_io import atomic_write_bytes  # noqa: E402


def test_atomic_write_survives_short_write(tmp_path, monkeypatch):
    """os.write writes only 16 bytes per call (a contract-faithful short write) -> must loop until done and commit the full 5000 bytes."""
    target = tmp_path / "out.bin"
    payload = b"x" * 5000
    real_write = os.write

    def short_write(fd, b):
        return real_write(fd, b[:16])       # writes only the first 16 bytes each time, returning the true count

    monkeypatch.setattr(os, "write", short_write)
    atomic_write_bytes(target, payload)
    assert target.read_bytes() == payload   # old code: only 16 bytes get committed -> this assertion FAILS
