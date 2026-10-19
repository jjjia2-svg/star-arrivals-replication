"""Tests for U0 snapshot_reader.py (group 6: T19-T20).

- T19: iter_jsonl_gz_shards streams line by line and never untars or loads a whole disk at once;
       shard_id = Path(p).name including .gz (keeps memory bounded).
- T20: a truncated or corrupt shard -> raises CorruptShardError (=17), never silently treated as empty (CORRUPT_SHARD).
Also tests count_records_gz(path) -> int.

Rule: this module does not depend on duckdb to read gz (U0 snapshot_reader has no duckdb dependency).
A gzip JSONL snapshot shard = one JSON record per line, the whole file gzip-compressed.
"""
import gzip
import json
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common.snapshot_reader import (  # noqa: E402
    CorruptShardError,
    count_records_gz,
    iter_jsonl_gz_shards,
)
from identity.exit_codes import CORRUPT_SHARD  # noqa: E402


# --- fixture: write a valid gzip JSONL shard ---
def _write_gz_jsonl(path: pathlib.Path, records: list[dict]) -> None:
    """Write JSON line by line and gzip the whole file (= the form of an OpenAlex snapshot shard)."""
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


# ============================================================
# T19: stream line by line + shard_id = Path(p).name including .gz
# ============================================================
def test_t19_iter_yields_shard_id_and_record(tmp_path):
    """Yields (shard_id, record) one by one; the record contents match what was written and the order is preserved."""
    p = tmp_path / "part_000.jsonl.gz"
    recs = [{"id": "W1", "n": 1}, {"id": "W2", "n": 2}, {"id": "W3", "n": 3}]
    _write_gz_jsonl(p, recs)

    out = list(iter_jsonl_gz_shards([str(p)]))

    assert [r for _, r in out] == recs
    # order preserved
    assert [r["id"] for _, r in out] == ["W1", "W2", "W3"]


def test_t19_shard_id_is_basename_including_gz(tmp_path):
    """shard_id must be Path(p).name (with the .gz suffix), not the full path and not the suffix-stripped name."""
    p = tmp_path / "part_042.jsonl.gz"
    _write_gz_jsonl(p, [{"id": "W1"}])

    shard_ids = [sid for sid, _ in iter_jsonl_gz_shards([str(p)])]

    assert shard_ids == ["part_042.jsonl.gz"]
    # check: includes .gz (not the basename with the suffix stripped)
    assert shard_ids[0].endswith(".gz")
    # check: not the full path
    assert "/" not in shard_ids[0]


def test_t19_multiple_shards_each_tagged_with_own_basename(tmp_path):
    """Several shards: each record carries the basename of its own shard; the order across shards = the order of paths."""
    p1 = tmp_path / "part_000.jsonl.gz"
    p2 = tmp_path / "part_001.jsonl.gz"
    _write_gz_jsonl(p1, [{"id": "A"}])
    _write_gz_jsonl(p2, [{"id": "B"}, {"id": "C"}])

    out = list(iter_jsonl_gz_shards([str(p1), str(p2)]))

    assert out == [
        ("part_000.jsonl.gz", {"id": "A"}),
        ("part_001.jsonl.gz", {"id": "B"}),
        ("part_001.jsonl.gz", {"id": "C"}),
    ]


def test_t19_returns_lazy_iterator_not_materialized_list(tmp_path):
    """Check streaming: the return value is a lazy iterator (not a list), proving the whole disk is never loaded at once."""
    import collections.abc

    p = tmp_path / "part_000.jsonl.gz"
    _write_gz_jsonl(p, [{"id": "W1"}, {"id": "W2"}])

    it = iter_jsonl_gz_shards([str(p)])
    # an iterator, not an already materialised container
    assert isinstance(it, collections.abc.Iterator)
    assert not isinstance(it, (list, tuple))
    # can be taken one by one with next (streaming semantics)
    first_sid, first_rec = next(it)
    assert first_sid == "part_000.jsonl.gz"
    assert first_rec == {"id": "W1"}


def test_t19_blank_lines_skipped_not_parsed(tmp_path):
    """Empty and whitespace-only lines are skipped (snapshots often end with one); they are not treated as corruption and yield no empty record."""
    p = tmp_path / "part_000.jsonl.gz"
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "W1"}) + "\n")
        fh.write("\n")           # empty line
        fh.write("   \n")        # whitespace-only line
        fh.write(json.dumps({"id": "W2"}) + "\n")

    out = list(iter_jsonl_gz_shards([str(p)]))

    assert [r for _, r in out] == [{"id": "W1"}, {"id": "W2"}]


def test_t19_empty_gzip_file_yields_nothing(tmp_path):
    """A valid gzip file with 0 records -> yields nothing (a legitimately empty file, not corruption)."""
    p = tmp_path / "part_000.jsonl.gz"
    _write_gz_jsonl(p, [])

    out = list(iter_jsonl_gz_shards([str(p)]))

    assert out == []


# ============================================================
# T20: truncated/corrupt shard -> CorruptShardError(=17), never silently treated as empty
# ============================================================
def test_t20_truncated_gzip_raises_corrupt_shard(tmp_path):
    """A truncated gzip stream (cut in the middle of writing) -> raises CorruptShardError where it is torn, not silently treated as empty."""
    p = tmp_path / "part_000.jsonl.gz"
    _write_gz_jsonl(p, [{"id": "W%d" % i, "payload": "x" * 200} for i in range(50)])
    # cut off a tail piece to make a truncated gzip (trailing CRC/length missing)
    raw = p.read_bytes()
    p.write_bytes(raw[: len(raw) // 2])

    with pytest.raises(CorruptShardError):
        list(iter_jsonl_gz_shards([str(p)]))


def test_t20_not_gzip_at_all_raises_corrupt_shard(tmp_path):
    """Bytes that are not gzip at all (bad magic number) -> CorruptShardError, not silently treated as empty."""
    p = tmp_path / "part_000.jsonl.gz"
    p.write_bytes(b"this is not gzip at all, plain garbage bytes")

    with pytest.raises(CorruptShardError):
        list(iter_jsonl_gz_shards([str(p)]))


def test_t20_bad_json_line_raises_corrupt_shard(tmp_path):
    """An invalid JSON line inside the gzip (a torn record) -> CorruptShardError, not silently skipped or treated as empty."""
    p = tmp_path / "part_000.jsonl.gz"
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "W1"}) + "\n")
        fh.write('{"id": "W2", "broken": \n')  # torn JSON line
        fh.write(json.dumps({"id": "W3"}) + "\n")

    with pytest.raises(CorruptShardError):
        list(iter_jsonl_gz_shards([str(p)]))


def test_t20_corrupt_shard_error_carries_shard_id(tmp_path):
    """CorruptShardError should say which shard (basename) was bad, to help locate it and never be silent."""
    p = tmp_path / "part_077.jsonl.gz"
    p.write_bytes(b"\x1f\x8b\x08bogustail")  # corrupt gzip

    with pytest.raises(CorruptShardError) as ei:
        list(iter_jsonl_gz_shards([str(p)]))

    # the error message contains the shard name (with .gz), to help operations locate it
    assert "part_077.jsonl.gz" in str(ei.value)


def test_t20_corrupt_shard_exit_code_is_17():
    """CorruptShardError.exit_code == CORRUPT_SHARD == 17 (a distinguishable exit code)."""
    err = CorruptShardError("part_x.jsonl.gz", "truncated")
    assert err.exit_code == CORRUPT_SHARD
    assert err.exit_code == 17


def test_t20_does_not_silently_return_empty_on_corruption(tmp_path):
    """Counter-example guarding the root cause of the earlier Sydney failure: a corrupt shard must never silently yield [] as if it were empty data."""
    p = tmp_path / "part_000.jsonl.gz"
    # write the first few valid lines + a truncation, to simulate a torn "partial success"
    _write_gz_jsonl(p, [{"id": "W%d" % i} for i in range(30)])
    raw = p.read_bytes()
    p.write_bytes(raw[: len(raw) - 5])  # cut 5 bytes off the tail to break the gzip ending

    raised = False
    try:
        list(iter_jsonl_gz_shards([str(p)]))
    except CorruptShardError:
        raised = True
    # key point: it must raise, never silently return empty or partial data
    assert raised, "a corrupt shard must raise CorruptShardError, never be silently treated as empty"


# ============================================================
# count_records_gz(path) -> int
# ============================================================
def test_count_records_gz_counts_nonblank_lines(tmp_path):
    """count_records_gz = number of records (non-empty lines), equal to the number yielded by iter."""
    p = tmp_path / "part_000.jsonl.gz"
    recs = [{"id": "W%d" % i} for i in range(7)]
    _write_gz_jsonl(p, recs)

    assert count_records_gz(str(p)) == 7


def test_count_records_gz_skips_blank_lines(tmp_path):
    """Empty lines are not counted as records (same empty-line semantics as iter)."""
    p = tmp_path / "part_000.jsonl.gz"
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "W1"}) + "\n")
        fh.write("\n")
        fh.write(json.dumps({"id": "W2"}) + "\n")

    assert count_records_gz(str(p)) == 2


def test_count_records_gz_zero_for_empty_file(tmp_path):
    """A valid empty gzip -> 0 (legitimately empty, not corruption)."""
    p = tmp_path / "part_000.jsonl.gz"
    _write_gz_jsonl(p, [])

    assert count_records_gz(str(p)) == 0


def test_count_records_gz_truncated_raises_corrupt_shard(tmp_path):
    """count_records_gz on a truncated shard -> also raises CorruptShardError, never silently returns a partial count."""
    p = tmp_path / "part_000.jsonl.gz"
    _write_gz_jsonl(p, [{"id": "W%d" % i, "pad": "y" * 100} for i in range(40)])
    raw = p.read_bytes()
    p.write_bytes(raw[: len(raw) // 2])

    with pytest.raises(CorruptShardError):
        count_records_gz(str(p))


# ============================================================
# Rule: this module does not depend on duckdb to read gz
# ============================================================
def test_module_does_not_import_duckdb():
    """Check: U0 snapshot_reader does not depend on duckdb to read gz (plain stdlib gzip).

    Checks the real dependency (sys.modules + import statements), not occurrences of the word 'duckdb' in comments.
    """
    import subprocess

    import common.snapshot_reader as sr

    # 1) The real-dependency check runs in a subprocess: this process's sys.modules can be
    #    polluted by a duckdb that other units legitimately import (first triggered by the u0p5 byline
    #    pre-filter equivalence test). The point of the assertion is
    #    "importing snapshot_reader itself does not pull in duckdb", which is measured precisely only with subprocess isolation.
    code = (
        "import sys; sys.path.insert(0, %r); "
        "import common.snapshot_reader; "
        "raise SystemExit(1 if 'duckdb' in sys.modules else 0)"
    ) % str(pathlib.Path(sr.__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", code], capture_output=True)
    assert r.returncode == 0, "snapshot_reader must never import duckdb (checked in an isolated subprocess)"

    # 2) the source has no real import statement (the word 'duckdb' may appear in a comment explaining "no dependency")
    src = pathlib.Path(sr.__file__).read_text(encoding="utf-8")
    for line in src.splitlines():
        code = line.split("#", 1)[0]  # strip inline comments
        assert "import duckdb" not in code, "snapshot_reader must never import duckdb"
        assert "from duckdb" not in code, "snapshot_reader must never use from duckdb import"
