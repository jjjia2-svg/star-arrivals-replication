"""Stream a gzip JSONL snapshot line by line (never untar the whole archive or load it all).

- iter_jsonl_gz_shards(paths) -> Iterator[(shard_id, record)]
    Streams several gzip JSONL shards line by line; shard_id = Path(p).name (including .gz).
    Memory is bounded: a generator yields line by line, and never untars at once, reads the whole file or materializes a list.
- count_records_gz(path) -> int  counts lines one by one (non-empty lines).
- A truncated / corrupt / torn-JSON shard -> raises CorruptShardError(exit_code=17),
    and is never silently treated as empty (the cause of the earlier Sydney 27k failure: corruption must never degrade into empty data).

Hard rule: this module does not depend on duckdb to read gz — it uses the pure Python standard library gzip.
JSONL = one JSON record per line; the whole file gzip-compressed = the shape of an OpenAlex snapshot shard.
"""
from __future__ import annotations

import gzip
import json
import pathlib
import time
import zlib
from typing import Iterator

from identity.exit_codes import CORRUPT_SHARD


class CorruptShardError(Exception):
    """A snapshot shard is truncated / corrupt / contains a torn JSON line.

    It is never swallowed silently as empty data; exit code = CORRUPT_SHARD (=17).
    Carries shard_id (basename, including .gz) so operators can locate it.
    """

    #: The single source of truth for pipeline exit codes (identity/exit_codes.py); 17 is not written as a bare number
    exit_code = CORRUPT_SHARD

    def __init__(self, shard_id: str, reason: str):
        self.shard_id = shard_id
        self.reason = reason
        super().__init__(f"corrupt shard {shard_id}: {reason}")


# Content is deterministically corrupt (retrying does not help) -> immediately raise CorruptShardError, never degrade into empty (the cause of the earlier Sydney 27k failure):
#   EOFError = truncated gzip tail; BadGzipFile = bad magic number; zlib.error = decompression failure.
#   Note: gzip.BadGzipFile is a subclass of OSError, so this tuple must be caught before `except OSError`.
_CORRUPTION_ERRORS = (
    EOFError,
    gzip.BadGzipFile,
    zlib.error,
)


def _iter_one_shard(path: str, *, max_retries: int = 4, base_delay: float = 1.0) -> Iterator[dict]:
    """Read one gzip JSONL shard line by line, lazily yielding each record.

    - Streaming: the file object from gzip.open decompresses on demand and iterates line by line, never loading it all.
    - Blank lines / whitespace-only lines are skipped (common at the end of a snapshot) and not treated as corruption.
    - **Transient IO errors (OSError: EPERM/EIO/EBUSY etc., jitter of an external USB/exFAT disk under heavy load)** -> retried with exponential
      backoff up to max_retries times; the whole shard is retried only when **no record has been yielded yet** (before open / before the first read), to avoid
      duplicate rows downstream (pass-B buckets). Only when retries are exhausted and it still fails is CorruptShardError raised.
      Root cause: a full run crashed after 9 hours on a single "Operation not permitted", and the old code treated any OSError
      as corruption, wiping out every non-resumable run.
    - **Deterministic content corruption (bad gzip / truncation / torn JSON)** -> CorruptShardError immediately, no retry (retrying does not help),
      and never silently treated as empty.
    """
    shard_id = pathlib.Path(path).name
    attempt = 0
    while True:
        # --- open (retry with backoff on a transient IO error; a bad gzip is judged corrupt immediately) ---
        try:
            fh = gzip.open(path, "rt", encoding="utf-8")
        except _CORRUPTION_ERRORS as exc:
            raise CorruptShardError(shard_id, f"cannot open (corrupt gzip): {exc}") from exc
        except OSError as exc:  # EPERM/EIO/EBUSY and other access errors = transient -> retry with backoff
            attempt += 1
            if attempt > max_retries:
                raise CorruptShardError(
                    shard_id, f"cannot open gzip stream after {max_retries} retries: {exc}"
                ) from exc
            time.sleep(base_delay * (2 ** (attempt - 1)))
            continue

        # --- read ---
        yielded_any = False
        retry_read = False
        try:
            for line in fh:  # <- stream line by line, never read() the whole file at once
                stripped = line.strip()
                if not stripped:
                    continue  # Blank / whitespace-only line: legitimately skipped, not corruption
                try:
                    rec = json.loads(stripped)
                except (json.JSONDecodeError, ValueError) as exc:
                    # A torn JSON line = corruption, never silently skipped or treated as empty (no retry)
                    raise CorruptShardError(shard_id, f"malformed JSON line: {exc}") from exc
                yielded_any = True
                yield rec
        except _CORRUPTION_ERRORS as exc:
            # Truncated / bad stream = deterministic corruption, no retry
            raise CorruptShardError(
                shard_id, f"truncated or corrupt gzip stream: {exc}"
            ) from exc
        except OSError as exc:
            # Transient IO jitter in the middle of a read: if records were already yielded, a retry is not safe
            #   (downstream would see duplicates), so declare corruption loudly; if none were yielded and
            #   retries remain -> close and re-read the whole shard (safe, no duplicates).
            if yielded_any or attempt >= max_retries:
                raise CorruptShardError(
                    shard_id, f"IO error during read (yielded={yielded_any}): {exc}"
                ) from exc
            attempt += 1
            retry_read = True
        finally:
            fh.close()

        if retry_read:
            time.sleep(base_delay * (2 ** (attempt - 1)))
            continue
        return  # Finished reading the whole shard


def iter_jsonl_gz_shards(paths) -> Iterator[tuple[str, dict]]:
    """Stream several gzip JSONL shards line by line, yielding (shard_id, record) one at a time.

    - shard_id = Path(p).name (with the .gz suffix), neither the full path nor without the suffix.
    - Memory is bounded: the generator yields record by record; never untars the whole archive, loads it all or materializes a list.
    - Order across shards = the order of paths; order within a shard = the order of file lines.
    - Any shard that is truncated / corrupt / contains torn JSON -> raises CorruptShardError(=17), never silently treated as empty.
    """
    for path in paths:
        shard_id = pathlib.Path(path).name
        for record in _iter_one_shard(path):
            yield (shard_id, record)


def count_records_gz(path: str) -> int:
    """Count the records of one gzip JSONL shard (the number of non-empty lines).

    - Counts line by line in a stream, never loading it all.
    - Blank lines are not counted (consistent with the blank-line semantics of iter_jsonl_gz_shards).
    - Truncated / corrupt / torn JSON -> raises CorruptShardError, never silently returns a partial count.
    """
    return sum(1 for _ in _iter_one_shard(path))
