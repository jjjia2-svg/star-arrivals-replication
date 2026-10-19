"""TDD red tests for U0 common/ledger.py (group 3, T10 + T11).

Guards:
- ledger = an append-only event log + idempotency keys; only .append, no .emit/.tally (DRIFT-L1).
- Every append goes through durable_append (G7 persistence) + pre-write schema validation (the six LEDGER_EVENT keys).
- already_done(key): counts as done only on a hit with status==ok (idempotency-key semantics).

LEDGER_EVENT schema (common/schema.py, verbatim):
  {op_id, status, shard_id, idempotency_key, ts, reason}; status ∈ ok/transient/permanent/skip.

durable_append injection: atomic_io.durable_append is provided by atomic_io.py (the G7 sequence);
these tests use a dependency-injected spy / the default local implementation and do not depend hard on sibling modules.
"""
import json
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common.ledger import Ledger  # noqa: E402
from common.schema import LEDGER_EVENT  # noqa: E402


# --------------------------------------------------------------------------
# T10: only .append + goes through durable_append + pre-write schema validation; no .emit/.tally
# --------------------------------------------------------------------------

def test_ledger_only_has_append_no_emit_no_tally():
    # DRIFT-L1: the ledger has only .append and never mixes in .emit / .tally (that is the job of the reconciliation layer)
    assert hasattr(Ledger, "append")
    assert not hasattr(Ledger, "emit"), "ledger must not have .emit (DRIFT-L1)"
    assert not hasattr(Ledger, "tally"), "ledger must not have .tally (DRIFT-L1)"


def test_ledger_append_routes_through_durable_append(tmp_path):
    # every append must go through durable_append (G7 persistence), never bypassing it
    calls = []

    def spy_durable_append(path, line):
        calls.append((path, line))
        # really write to disk so later reads can see it
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)

    led = Ledger(tmp_path / "events.jsonl", durable_append=spy_durable_append)
    led.append(
        op_id="op-1", status="ok", shard_id="s0.gz",
        idempotency_key="k-1", ts="2026-06-29T00:00:00Z", reason="",
    )
    assert len(calls) == 1, "append must call durable_append exactly once"


def test_ledger_append_is_append_only_never_truncates(tmp_path):
    # append-only: after two appends the file has two lines (the second never overwrites the first)
    led = Ledger(tmp_path / "events.jsonl")
    led.append(op_id="op-1", status="ok", shard_id="s0.gz",
               idempotency_key="k-1", ts="t1", reason="")
    led.append(op_id="op-2", status="permanent", shard_id="s0.gz",
               idempotency_key="k-2", ts="t2", reason="404")
    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_ledger_append_writes_full_six_key_schema(tmp_path):
    # once pre-write validation passes, the line on disk has exactly the six LEDGER_EVENT keys
    led = Ledger(tmp_path / "events.jsonl")
    led.append(op_id="op-1", status="ok", shard_id="s0.gz",
               idempotency_key="k-1", ts="t1", reason="")
    row = json.loads((tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert set(row.keys()) == set(LEDGER_EVENT.keys())


def test_ledger_append_rejects_bad_status(tmp_path):
    # pre-write validation: status not in ok/transient/permanent/skip -> raise, nothing written
    led = Ledger(tmp_path / "events.jsonl")
    with pytest.raises(ValueError):
        led.append(op_id="op-x", status="bogus", shard_id="s0.gz",
                   idempotency_key="k-x", ts="t", reason="")
    # a failed validation must write no line
    assert not (tmp_path / "events.jsonl").exists() or \
        (tmp_path / "events.jsonl").read_text(encoding="utf-8") == ""


def test_ledger_append_rejects_missing_field(tmp_path):
    # pre-write validation: a missing field (reason is omitted here) -> raise, nothing written
    led = Ledger(tmp_path / "events.jsonl")
    with pytest.raises(TypeError):
        led.append(op_id="op-x", status="ok", shard_id="s0.gz",  # missing idempotency_key/ts/reason
                   )  # type: ignore[call-arg]


# --------------------------------------------------------------------------
# T11: already_done(key) counts as done only on a hit with status==ok
# --------------------------------------------------------------------------

def test_already_done_true_only_when_hit_and_status_ok(tmp_path):
    led = Ledger(tmp_path / "events.jsonl")
    led.append(op_id="op-1", status="ok", shard_id="s0.gz",
               idempotency_key="done-key", ts="t1", reason="")
    assert led.already_done("done-key") is True


def test_already_done_false_when_key_absent(tmp_path):
    led = Ledger(tmp_path / "events.jsonl")
    assert led.already_done("never-seen") is False


def test_already_done_false_when_hit_but_not_ok(tmp_path):
    # hit but status != ok (transient/permanent/skip) -> not done, must be redone
    led = Ledger(tmp_path / "events.jsonl")
    led.append(op_id="op-1", status="transient", shard_id="s0.gz",
               idempotency_key="retry-key", ts="t1", reason="429")
    assert led.already_done("retry-key") is False


def test_already_done_terminal_ok_wins_over_earlier_transient(tmp_path):
    # the same idempotency key first transient then ok (retry succeeded) -> finally counts as done
    led = Ledger(tmp_path / "events.jsonl")
    led.append(op_id="op-1", status="transient", shard_id="s0.gz",
               idempotency_key="k", ts="t1", reason="429")
    led.append(op_id="op-1", status="ok", shard_id="s0.gz",
               idempotency_key="k", ts="t2", reason="")
    assert led.already_done("k") is True


def test_already_done_reloads_from_existing_file(tmp_path):
    # crash recovery: a new Ledger instance rebuilds the idempotency view from the existing events.jsonl
    path = tmp_path / "events.jsonl"
    led1 = Ledger(path)
    led1.append(op_id="op-1", status="ok", shard_id="s0.gz",
                idempotency_key="persisted", ts="t1", reason="")
    # a brand-new instance, relying only on the log on disk
    led2 = Ledger(path)
    assert led2.already_done("persisted") is True
