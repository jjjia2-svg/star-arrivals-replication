"""TDD red tests for U0 failure_class.py (T13-T15).

Guards LEDGER_EVENT.status ∈ ok/transient/permanent/skip:
  T13 429/DNS/5xx/timeout -> transient (goes into the refetch queue).
  T14 404/410/parse failure -> permanent.
  T15 a transient failure never returns {} (the root cause of the old Sydney 27k disaster);
      unknown_default_class=None -> raise (an unset threshold never gets a silent default).

Plain words: fetch failures fall into two classes.
  - transient: network glitch / rate limiting / server 5xx. Retrying is enough; it must go into the refetch queue and never be dropped as "no data for this one".
  - permanent: 404/410/broken parse. The record really is gone; mark it permanent.
Root cause of the old Sydney disaster = a transient failure was silently swallowed as an empty return {}, and 27k people vanished. Rule of this module:
a transient classification never returns {} (empty). The fallback direction when there is no signal (unknown_default_class) is an unset placeholder (null);
meeting None must raise, and this module never decides on which side to drop by default.

These tests are purely local, with no network and no data fetching (classification is a pure function; feed it error-signal strings / status codes).
"""
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common.failure_class import (  # noqa: E402
    PERMANENT,
    TRANSIENT,
    UnknownFailureUnsigned,
    classify_failure,
)
from common._redlines import RedlineUnsigned  # noqa: E402


# --- T13: 429/DNS/5xx/timeout → transient ---

@pytest.mark.parametrize(
    "signal",
    [
        {"http_status": 429},          # rate limiting
        {"http_status": 500},          # 5xx server error
        {"http_status": 503},          # 5xx server error
        {"http_status": 502},          # 5xx gateway
        {"error_kind": "dns"},         # DNS resolution failure (network layer)
        {"error_kind": "timeout"},     # timeout
    ],
)
def test_transient_signals_classify_transient(signal):
    # T13: 429/DNS/5xx/timeout are all transient (retryable, go into the refetch queue)
    assert classify_failure(**signal) == TRANSIENT


def test_transient_constant_value():
    # the transient class value = "transient" in the LEDGER_EVENT.status domain
    assert TRANSIENT == "transient"


# --- T14: 404/410/parse failure -> permanent ---

@pytest.mark.parametrize(
    "signal",
    [
        {"http_status": 404},          # resource does not exist
        {"http_status": 410},          # resource permanently removed
        {"error_kind": "parse"},       # parse failure (broken content, retrying is useless)
    ],
)
def test_permanent_signals_classify_permanent(signal):
    # T14: 404/410/parse failure are all permanent
    assert classify_failure(**signal) == PERMANENT


def test_permanent_constant_value():
    # the permanent class value = "permanent" in the LEDGER_EVENT.status domain
    assert PERMANENT == "permanent"


# --- T15a: a transient failure never returns {} (root cause of the Sydney disaster) ---

@pytest.mark.parametrize(
    "signal",
    [
        {"http_status": 429},
        {"http_status": 503},
        {"error_kind": "dns"},
        {"error_kind": "timeout"},
    ],
)
def test_transient_never_returns_empty_dict(signal):
    # Guards the root cause of the Sydney 27k disaster: a transient classification never returns {} (empty) and swallows the data silently
    result = classify_failure(**signal)
    assert result != {}
    assert result is not None
    assert result == TRANSIENT


# --- T15b: unknown_default_class=None -> raise (an unset threshold never gets a silent default) ---

def test_unknown_signal_with_unsigned_default_raises():
    # no recognisable signal + unknown_default_class unset (RED=None) -> raise
    # never decide on a "default side to drop" (that would cross the line)
    with pytest.raises((UnknownFailureUnsigned, RedlineUnsigned)):
        classify_failure(http_status=418)  # teapot code (418): in neither the transient list nor the permanent list


def test_unknown_signal_no_args_raises():
    # no signal at all (neither http_status nor error_kind passed) -> likewise no silent default
    with pytest.raises((UnknownFailureUnsigned, RedlineUnsigned)):
        classify_failure()


def test_unknown_error_kind_with_unsigned_default_raises():
    # an unknown error_kind + unset default -> raise (no silent classification)
    with pytest.raises((UnknownFailureUnsigned, RedlineUnsigned)):
        classify_failure(error_kind="some_unmapped_kind")
