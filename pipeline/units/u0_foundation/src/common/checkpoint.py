"""U0 common/checkpoint.py: shard-level WAL (frame lenhex:crc32hex:json), frame-by-frame recovery.

Cross-cutting base layer, identification-neutral (no identification-threshold values).

WAL = write-ahead log: after each shard unit is processed, one frame is appended; after a crash the log is
used to skip the completed items.
Frame format (exact contract): "<lenhex>:<crc32hex>:<json>\\n"
  - lenhex   = UTF-8 byte length of the json payload, in hex
  - crc32hex = crc32 of the json payload's UTF-8 bytes, in hex
  - json     = one frame's payload string (may itself contain colons; split only on the first two colons)

T12 crash-recovery iron rule (the whole reason this module exists):
  A torn frame = lenhex differs from the actual json byte length, or the crc32 check fails, or the
  structure is incomplete (half-written / no colons).
  A torn frame skips only THAT frame; reading continues with the later good frames and NEVER breaks out,
  dropping the whole tail.
  Counter-example: a naive WAL reader breaks at the first bad frame -> every good frame written after it is lost.
"""
from __future__ import annotations

import binascii
import os
from typing import Iterator


def encode_frame(payload_json: str) -> bytes:
    """Encode one json payload as WAL frame bytes: lenhex:crc32hex:json\\n.

    Args:
        payload_json: one frame's payload (an already serialized json string).
    Returns:
        bytes: one complete frame (including the trailing newline).
    """
    body = payload_json.encode("utf-8")
    lenhex = format(len(body), "x")
    crchex = format(binascii.crc32(body) & 0xFFFFFFFF, "x")
    return f"{lenhex}:{crchex}:{payload_json}\n".encode("utf-8")


def _frame_is_intact(lenhex: str, crchex: str, payload: str) -> bool:
    """Integrity check of one frame: lenhex and crc32 must both match the payload's actual bytes.

    Any mismatch -> False (torn frame). A lenhex/crchex that is not valid hex also counts as torn.
    """
    body = payload.encode("utf-8")
    try:
        declared_len = int(lenhex, 16)
        declared_crc = int(crchex, 16)
    except ValueError:
        return False
    if declared_len != len(body):
        return False
    if declared_crc != (binascii.crc32(body) & 0xFFFFFFFF):
        return False
    return True


def iter_frames(path) -> Iterator[str]:
    """Read a WAL shard frame by frame and yield the payload (json string) of every INTACT frame.

    Crash-recovery semantics (T12):
      - Stream line by line (each frame ends with \\n); memory is bounded.
      - Each frame is validated independently (lenhex + crc32); a torn/incomplete frame -> skip only THAT
        frame and continue, never break.
      - If the last frame is truncated (no trailing \\n / incomplete json) -> treated as torn and skipped;
        the good frames before it were already yielded.
      - Shard does not exist -> empty iteration (no exception), so recovery starts from scratch.

    Args:
        path: WAL shard file path (str or PathLike).
    Yields:
        str: the payload of each intact frame.
    """
    fspath = os.fspath(path)
    if not os.path.exists(fspath):
        return
    with open(fspath, "r", encoding="utf-8", newline="") as f:
        for raw_line in f:
            # A half-written last frame has no trailing newline -> treated as torn, skipped (no break)
            if not raw_line.endswith("\n"):
                continue
            line = raw_line[:-1]  # strip the trailing \n
            # split only on the first two colons; the payload itself may contain colons
            parts = line.split(":", 2)
            if len(parts) != 3:
                # malformed structure (no two colons) -> torn, skip this single frame
                continue
            lenhex, crchex, payload = parts
            if not _frame_is_intact(lenhex, crchex, payload):
                # CRC/len mismatch -> torn, skip this single frame and keep reading later good frames (never break)
                continue
            yield payload


class CheckpointWAL:
    """Shard-level checkpoint WAL: append intact frames + frame-by-frame recovery after a crash.

    One instance corresponds to one shard WAL file; append_frame durably appends one frame,
    recover reads back all intact frames (skipping torn frames).
    """

    def __init__(self, path) -> None:
        """
        Args:
            path: WAL file path of this shard (under _ledger/<unit>/, or the checkpoint area).
        """
        self._path = os.fspath(path)

    def append_frame(self, payload_json: str) -> None:
        """Durably append one frame (open append -> write -> flush -> fsync), append-only.

        Args:
            payload_json: this frame's payload (an already serialized json string).
        """
        frame = encode_frame(payload_json)
        with open(self._path, "ab") as f:
            f.write(frame)
            f.flush()
            os.fsync(f.fileno())

    def recover(self) -> list[str]:
        """Crash recovery: read back the payload of every intact frame (torn frames skipped).

        Returns:
            list[str]: intact-frame payloads in file order.
        """
        return list(iter_frames(self._path))
