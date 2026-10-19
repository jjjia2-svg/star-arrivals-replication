"""TDD red tests for U0 common/checkpoint.py (group 3, T12).

Guards:
- checkpoint = a shard-level WAL (frame format lenhex:crc32hex:json), recovered frame by frame.
- T12 crash-recovery rule: a torn frame (CRC mismatch or length mismatch) skips only THAT single frame
  and reading continues with the following good frames; one bad frame never breaks off the whole tail
  (which would lose every already-written good frame after the bad one).

Frame format (verbatim): "<lenhex>:<crc32hex>:<json>\n"
  - lenhex      = the byte length of the json, in hexadecimal
  - crc32hex    = the crc32 of the json bytes, in hexadecimal
  - json        = one frame payload (UTF-8)
  Torn = lenhex does not match the actual json byte length, or the crc32 check fails.
"""
import binascii
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common.checkpoint import (  # noqa: E402
    CheckpointWAL,
    encode_frame,
    iter_frames,
)


def _good_frame_bytes(payload_json: str) -> bytes:
    """Build the bytes of one valid frame (lenhex:crc32hex:json\\n)."""
    body = payload_json.encode("utf-8")
    lenhex = format(len(body), "x")
    crchex = format(binascii.crc32(body) & 0xFFFFFFFF, "x")
    return f"{lenhex}:{crchex}:{payload_json}\n".encode("utf-8")


# --------------------------------------------------------------------------
# encode_frame / round trip
# --------------------------------------------------------------------------

def test_encode_frame_roundtrip(tmp_path):
    # a written frame is read back unchanged by iter_frames
    p = tmp_path / "shard0.wal"
    with open(p, "wb") as f:
        f.write(encode_frame('{"a":1}'))
        f.write(encode_frame('{"b":2}'))
    frames = list(iter_frames(p))
    assert frames == ['{"a":1}', '{"b":2}']


def test_encode_frame_format_is_lenhex_crc_json():
    # frame form = lenhex:crc32hex:json\n (verbatim contract)
    raw = encode_frame('{"x":1}').decode("utf-8")
    assert raw.endswith("\n")
    lenhex, crchex, rest = raw[:-1].split(":", 2)
    body = '{"x":1}'.encode("utf-8")
    assert int(lenhex, 16) == len(body)
    assert int(crchex, 16) == (binascii.crc32(body) & 0xFFFFFFFF)
    assert rest == '{"x":1}'


# --------------------------------------------------------------------------
# T12: a torn frame skips only that frame, reading continues with the following good frames, never breaking off the whole tail
# --------------------------------------------------------------------------

def test_torn_crc_frame_skipped_tail_survives(tmp_path):
    # the CRC of a middle frame is corrupt -> only it is dropped, the good frames before and after all survive
    p = tmp_path / "shard0.wal"
    good1 = _good_frame_bytes('{"i":1}')
    good3 = _good_frame_bytes('{"i":3}')
    # bad frame: lenhex/crc taken from i=2, but the json was tampered with (crc no longer matches)
    body2 = '{"i":2}'.encode("utf-8")
    lenhex = format(len(body2), "x")
    crchex = format(binascii.crc32(body2) & 0xFFFFFFFF, "x")
    torn = f"{lenhex}:{crchex}:{{\"i\":999}}\n".encode("utf-8")  # json changed, crc mismatch
    with open(p, "wb") as f:
        f.write(good1)
        f.write(torn)
        f.write(good3)
    frames = list(iter_frames(p))
    # Key point: good3 after the bad frame must still be read (never break off the whole tail)
    assert frames == ['{"i":1}', '{"i":3}']


def test_torn_len_frame_skipped_tail_survives(tmp_path):
    # the lenhex of a middle frame does not match the real byte length -> only it is dropped, the following good frames are still read
    p = tmp_path / "shard0.wal"
    good1 = _good_frame_bytes('{"i":1}')
    good3 = _good_frame_bytes('{"i":3}')
    body2 = '{"i":2}'.encode("utf-8")
    wrong_len = format(len(body2) + 5, "x")  # length deliberately wrong
    crchex = format(binascii.crc32(body2) & 0xFFFFFFFF, "x")
    torn = f"{wrong_len}:{crchex}:{{\"i\":2}}\n".encode("utf-8")
    with open(p, "wb") as f:
        f.write(good1)
        f.write(torn)
        f.write(good3)
    frames = list(iter_frames(p))
    assert frames == ['{"i":1}', '{"i":3}']


def test_truncated_last_frame_does_not_kill_earlier_frames(tmp_path):
    # crash mid-write: the last frame is truncated (no trailing \n / json incomplete) -> all earlier good frames are still read
    p = tmp_path / "shard0.wal"
    good1 = _good_frame_bytes('{"i":1}')
    good2 = _good_frame_bytes('{"i":2}')
    with open(p, "wb") as f:
        f.write(good1)
        f.write(good2)
        # half-written frame: claims 20 bytes but the json is cut off and has no newline
        f.write(b"14:deadbeef:{\"i\":3,\"x")
    frames = list(iter_frames(p))
    assert frames == ['{"i":1}', '{"i":2}']


def test_malformed_no_colons_frame_skipped(tmp_path):
    # a line that is not a frame at all (no two colons) -> skipped, neither raises nor breaks
    p = tmp_path / "shard0.wal"
    good1 = _good_frame_bytes('{"i":1}')
    good2 = _good_frame_bytes('{"i":2}')
    with open(p, "wb") as f:
        f.write(good1)
        f.write(b"garbage-line-without-structure\n")
        f.write(good2)
    frames = list(iter_frames(p))
    assert frames == ['{"i":1}', '{"i":2}']


def test_all_good_frames_pass_through(tmp_path):
    p = tmp_path / "shard0.wal"
    with open(p, "wb") as f:
        for i in range(5):
            f.write(_good_frame_bytes(f'{{"i":{i}}}'))
    frames = list(iter_frames(p))
    assert frames == [f'{{"i":{i}}}' for i in range(5)]


def test_iter_frames_missing_file_yields_empty(tmp_path):
    # the shard does not exist -> empty iteration (no raise), so recovery starts from zero
    frames = list(iter_frames(tmp_path / "nope.wal"))
    assert frames == []


# --------------------------------------------------------------------------
# CheckpointWAL: write to the shard WAL + recover by reading back
# --------------------------------------------------------------------------

def test_checkpoint_wal_write_then_recover(tmp_path):
    wal = CheckpointWAL(tmp_path / "shard_s0.wal")
    wal.append_frame('{"done":"a"}')
    wal.append_frame('{"done":"b"}')
    # a fresh instance recovers from disk
    wal2 = CheckpointWAL(tmp_path / "shard_s0.wal")
    assert wal2.recover() == ['{"done":"a"}', '{"done":"b"}']


def test_checkpoint_wal_recover_skips_torn_keeps_rest(tmp_path):
    # end to end: write two good frames, hand-insert a bad frame in the middle, write one more good frame -> recover skips the bad one and keeps the good ones
    p = tmp_path / "shard_s0.wal"
    wal = CheckpointWAL(p)
    wal.append_frame('{"done":"a"}')
    # hand-assemble a bad frame (crc mismatch)
    body = '{"done":"b"}'.encode("utf-8")
    lenhex = format(len(body), "x")
    crchex = format(binascii.crc32(body) & 0xFFFFFFFF, "x")
    with open(p, "ab") as f:
        f.write(f"{lenhex}:{crchex}:{{\"done\":\"TAMPERED\"}}\n".encode("utf-8"))
    wal.append_frame('{"done":"c"}')
    assert wal.recover() == ['{"done":"a"}', '{"done":"c"}']
