"""U0 common/ledger.py: append-only event log + idempotency key.

Cross-cutting base layer, identification-neutral (no identification-threshold values).

Iron rules (DRIFT-L1):
  - Only .append; never mix in .emit / .tally (that is the job of the reconcile layer).
  - Every append: validate the schema first (the six LEDGER_EVENT keys + the status enum), then persist through
    durable_append (G7 sequence); append-only, never truncated.
  - already_done(key): only a hit with status == "ok" counts as done (idempotency-key semantics); a hit with
    transient/permanent/skip does not count as done and must be redone.

durable_append seam (G7):
  The on-disk verb is provided by atomic_io.durable_append (atomic_io.py, WAL durable append).
  This module takes it through the dependency-injected durable_append parameter; the default is the local
  _local_durable_append (open append + flush + os.fsync), so the U0 unit tests stand alone and do not hard-depend
  on a sibling module that may not be present yet.
  Once atomic_io.durable_append is available, callers just pass it in; no change needed.
"""
from __future__ import annotations

import json
import os
from typing import Callable, Dict, Optional

from common.schema import LEDGER_EVENT, assert_matches_schema

# Legal enum for LEDGER_EVENT.status (verbatim from the schema.py comment: ok/transient/permanent/skip)
_VALID_STATUS = ("ok", "transient", "permanent", "skip")

# Idempotency "done" criterion: only ok counts as a terminal success (T11)
_DONE_STATUS = "ok"

DurableAppend = Callable[[str, str], None]


def _local_durable_append(path: str, line: str) -> None:
    """Default local durable append: open append -> write -> flush -> os.fsync.

    The minimal local implementation of the G7 "durable append" (the fallback when atomic_io.durable_append is not available).
    Each line carries its own newline (JSONL); fsync guarantees that frames already written survive a crash.
    """
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


class Ledger:
    """Append-only idempotent event log.

    One line = one LEDGER_EVENT (JSONL). The same idempotency_key may appear on several lines
    (e.g. transient first, then ok); already_done judges by "has this key ever had status==ok".
    """

    def __init__(
        self,
        path,
        *,
        durable_append: Optional[DurableAppend] = None,
    ) -> None:
        """
        Args:
            path: event log file path (_ledger/<unit>/events.jsonl); str or PathLike.
            durable_append: durable append verb (path:str, line:str) -> None;
                            None -> use the local _local_durable_append (G7 fallback).
        """
        self._path = os.fspath(path)
        self._durable_append: DurableAppend = durable_append or _local_durable_append
        # Idempotency view: idempotency_key -> has status=="ok" ever appeared
        self._done: Dict[str, bool] = {}
        self._reload_from_disk()

    # -- Crash recovery: rebuild the idempotency view from an existing events.jsonl --
    def _reload_from_disk(self) -> None:
        if not os.path.exists(self._path):
            return
        with open(self._path, "r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError:
                    # Torn/half-written line: skip that single line so the whole log read does not crash (same spirit as checkpoint)
                    continue
                key = row.get("idempotency_key")
                if key is None:
                    continue
                if row.get("status") == _DONE_STATUS:
                    self._done[key] = True
                else:
                    # A hit with a non-ok status: record that the key has been seen (but is still not done); flip to True when an ok appears
                    self._done.setdefault(key, False)

    def append(
        self,
        *,
        op_id: str,
        status: str,
        shard_id: str,
        idempotency_key: str,
        ts: str,
        reason: str,
    ) -> None:
        """Append one event (append-only): validate the schema first -> persist with durable_append -> update the idempotency view.

        Pre-write validation (a failed validation never reaches disk):
          1. The row's key set equals exactly the six LEDGER_EVENT keys (assert_matches_schema).
          2. status is one of ok/transient/permanent/skip.
        """
        event = {
            "op_id": op_id,
            "status": status,
            "shard_id": shard_id,
            "idempotency_key": idempotency_key,
            "ts": ts,
            "reason": reason,
        }
        # 1. Pre-write schema validation: the six keys match exactly (extra or missing both raise SchemaMismatchError)
        assert_matches_schema(event.keys(), LEDGER_EVENT, label="LEDGER_EVENT")
        # 2. status enum check (before writing; invalid -> ValueError, nothing written)
        if status not in _VALID_STATUS:
            raise ValueError(
                f"LEDGER_EVENT.status is invalid: {status!r}; allowed: {_VALID_STATUS}"
            )
        # 3. Durable append (G7), append-only, never truncated
        line = json.dumps(event, ensure_ascii=False) + "\n"
        self._durable_append(self._path, line)
        # 4. Update the in-memory idempotency view (ok flips to True; otherwise just record it as seen)
        if status == _DONE_STATUS:
            self._done[idempotency_key] = True
        else:
            self._done.setdefault(idempotency_key, False)

    def already_done(self, key: str) -> bool:
        """Idempotency query: has this idempotency_key ever completed with status=="ok".

        Hit and status==ok -> True (skip the redo);
        no hit / hit but never ok (transient/permanent/skip) -> False (must redo).
        """
        return self._done.get(key, False)
