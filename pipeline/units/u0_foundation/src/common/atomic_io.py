"""U0 foundation: atomic_io. Atomic write (G7 sequence) + durable fsync.

Tests T07-T09 (build checklist section G, written test-first) cover the G7 sequence.
Identification-neutral: a purely local on-disk primitive; no data fetching, no network, no identification thresholds.

G7 atomic-write sequence (a crash never leaves a half file):
    write .partial -> flush -> durable_fsync(file) -> os.replace (atomic rename) -> durable_fsync(parent_dir)

Iron rules (T07-T09):
  - durable_fsync prefers os.fdatasync; on an external/network volume that raises ENOTSUP it degrades to
    os.fsync and logs it (never swallowed silently); any other OSError (e.g. EIO) is re-raised, not
    swallowed as ENOTSUP.
  - Across volumes (os.replace EXDEV) -> raise CrossVolumeError (never silently fall back to copy).
  - The .partial temp name carries pid + uuid (deterministically traceable + concurrency-isolated; two
    writes never collide).
"""
from __future__ import annotations

import errno
import logging
import os
import uuid
from pathlib import Path

logger = logging.getLogger("multiplex_pipeline.u0.atomic_io")

# .partial = suffix marking an unfinished file; until the rename succeeds, no reader treats it as finished.
PARTIAL_SUFFIX = ".partial"


class CrossVolumeError(OSError):
    """The target's parent directory and the temp file are on different volumes (os.replace EXDEV).

    An atomic rename only holds inside one filesystem; across volumes it must fail explicitly and never
    silently degrade to a non-atomic copy+delete (that would break the G7 crash-safety guarantee).
    """


def durable_fsync(fd_or_path) -> None:
    """Flush data all the way to disk (durable). An fd uses fdatasync; a directory path uses fsync.

    Args:
      - int fd  -> file descriptor: prefers os.fdatasync (flushes data but not metadata, faster);
                  external/network volumes often raise ENOTSUP -> degrade to os.fsync and log it
                  (T08, not silent); any other OSError is re-raised (T08: EIO must not be swallowed).
      - str/Path -> directory path: open a directory fd -> os.fsync -> close (persists the parent
                  directory entry; the last G7 step).
    """
    # Directory-path form: open it as an fd and fsync the directory itself (so the directory entry after the rename is on disk)
    if not isinstance(fd_or_path, int):
        dir_fd = os.open(os.fspath(fd_or_path), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        return

    fd = fd_or_path
    # Main flush primitive: use fdatasync when available (data only, faster), else fall back to os.fsync.
    # Names are resolved at call time -> tests can monkeypatch either os.fdatasync or os.fsync to exercise the ENOTSUP path.
    primary = getattr(os, "fdatasync", None) or os.fsync
    try:
        primary(fd)
    except OSError as e:
        if e.errno == errno.ENOTSUP:
            # The external/network volume does not support this flush call -> degrade to os.fsync, but log it (never swallowed silently).
            logger.warning(
                "durable_fsync: %s ENOTSUP on fd=%s, degrading to os.fsync",
                getattr(primary, "__name__", "fsync"), fd,
            )
            os.fsync(fd)
        else:
            # Not ENOTSUP (e.g. EIO): a real error, re-raised, not swallowed as ENOTSUP.
            raise


def atomic_write_bytes(target, data: bytes) -> None:
    """G7 atomic write of bytes to target. After a crash the file holds either the old or the new content, never half.

    Sequence (T07 pins the order):
      1. Write a .partial temp file in the same directory (name carries pid+uuid, T09)
      2. flush + durable_fsync(file)  <- data reaches disk first
      3. os.replace(.partial -> target) <- atomic rename (across volumes raises CrossVolumeError, T09)
      4. durable_fsync(parent_dir)     <- directory entry reaches disk
    """
    target = Path(target)
    parent = target.parent

    # .partial and target share a directory -> same volume, so os.replace can rename atomically.
    # The name carries pid + uuid: pid traces the source process, uuid keeps concurrent/retried writes from colliding (T09).
    tmp_name = f"{target.name}.{os.getpid()}.{uuid.uuid4().hex}{PARTIAL_SUFFIX}"
    tmp_path = parent / tmp_name

    # Steps 1+2: write .partial -> flush -> durable_fsync(file)
    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        # A4: os.write is a single system call and can write short (return < len(data));
        # a large blob (above the ~2 GiB macOS per-call limit) or ENOSPC both cause it. Ignoring the return value would
        # commit a truncated file as complete -> loop until every byte is written; no progress (return <=0) fails loudly,
        # never silently committing a truncated file.
        mv = memoryview(data)
        off = 0
        while off < len(mv):
            n = os.write(fd, mv[off:])
            if n <= 0:
                raise OSError(
                    f"atomic_write_bytes: os.write made no progress (returned {n}), {off}/{len(mv)} bytes written"
                )
            off += n
        # flush: os.write has put the data in the OS buffer; durable_fsync pushes it to the physical disk.
        durable_fsync(fd)
    finally:
        os.close(fd)

    # Step 3: atomic rename. Across volumes -> EXDEV -> CrossVolumeError (no silent copy).
    try:
        os.replace(str(tmp_path), str(target))
    except OSError as e:
        # Rename failed: clean up .partial; classify the cross-volume case separately.
        try:
            os.unlink(str(tmp_path))
        except OSError:
            pass
        if e.errno == errno.EXDEV:
            raise CrossVolumeError(
                e.errno,
                f"cross-volume rename refused: {tmp_path} -> {target} "
                f"(.partial and target must be on the same filesystem)",
            ) from e
        raise

    # Step 4: durable_fsync(parent_dir) so the new directory entry is on disk too.
    durable_fsync(parent)
