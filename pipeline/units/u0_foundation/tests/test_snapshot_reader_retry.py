"""snapshot_reader retries transient IO errors: it distinguishes "temporarily cannot be opened (retry)" from "the file is really corrupt (fail)".

Root cause (a full run that crashed after 9 hours): a USB exFAT disk under heavy load flickered and gzip.open raised OSError
"Operation not permitted" (EPERM); the old code treated any OSError as CorruptShardError, which wiped out the whole non-resumable run.
Fix: OSError of the access kind (EPERM/EIO/EBUSY etc.) = transient -> retry N times with backoff; only corrupt content
(BadGzipFile/zlib.error/EOFError) or a persistent failure raises CorruptShardError.
Safety: a whole shard is retried only when NO record has been yielded yet (before open / before the first read), to avoid duplicate rows downstream (pass-B buckets).
"""
import gzip
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common import snapshot_reader as SR  # noqa: E402


def _write_gz(path, lines):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for ln in lines:
            f.write(ln + "\n")


def test_transient_oserror_at_open_is_retried_then_succeeds(monkeypatch, tmp_path):
    p = tmp_path / "s.gz"
    _write_gz(p, ['{"id":"W1"}', '{"id":"W2"}'])
    calls = {"n": 0}
    real_open = gzip.open

    def flaky_open(*a, **k):
        calls["n"] += 1
        if calls["n"] <= 2:                      # the first 2 attempts fail transiently
            raise OSError(1, "Operation not permitted")
        return real_open(*a, **k)

    monkeypatch.setattr(SR.gzip, "open", flaky_open)
    rows = list(SR._iter_one_shard(str(p), max_retries=4, base_delay=0.001))
    assert rows == [{"id": "W1"}, {"id": "W2"}], "should read everything correctly after retries"
    assert calls["n"] == 3, "2 flaky opens + 1 success"


def test_persistent_oserror_finally_raises_corrupt(monkeypatch, tmp_path):
    p = tmp_path / "s.gz"
    _write_gz(p, ['{"id":"W1"}'])

    def always_eperm(*a, **k):
        raise OSError(1, "Operation not permitted")

    monkeypatch.setattr(SR.gzip, "open", always_eperm)
    with pytest.raises(SR.CorruptShardError):        # retries exhausted -> only then fail
        list(SR._iter_one_shard(str(p), max_retries=3, base_delay=0.001))


def test_bad_gzip_content_not_retried(monkeypatch, tmp_path):
    """Real corruption (non-gzip content) is deterministically bad: never retried, raises CorruptShardError directly (guards the root cause of the earlier Sydney failure, 27k)."""
    p = tmp_path / "bad.gz"
    p.write_bytes(b"this is not gzip")
    calls = {"n": 0}
    real_open = gzip.open

    def counting_open(*a, **k):
        calls["n"] += 1
        return real_open(*a, **k)

    monkeypatch.setattr(SR.gzip, "open", counting_open)
    with pytest.raises(SR.CorruptShardError):
        list(SR._iter_one_shard(str(p), max_retries=4, base_delay=0.001))
    assert calls["n"] == 1, "corrupt content is not retried (judged corrupt after a single open)"


def test_malformed_json_line_still_raises_no_retry(tmp_path):
    p = tmp_path / "s.gz"
    with gzip.open(p, "wt", encoding="utf-8") as f:
        f.write('{"id":"W1"}\n')
        f.write("{not json}\n")
    with pytest.raises(SR.CorruptShardError):
        list(SR._iter_one_shard(str(p)))


def test_healthy_shard_reads_normally_no_delay(tmp_path):
    """With no errors the behaviour is unchanged: normal record-by-record reading, no retry or backoff is triggered."""
    p = tmp_path / "s.gz"
    _write_gz(p, ['{"id":"W1"}', '{"id":"W2"}', '{"id":"W3"}'])
    rows = list(SR._iter_one_shard(str(p)))
    assert [r["id"] for r in rows] == ["W1", "W2", "W3"]
