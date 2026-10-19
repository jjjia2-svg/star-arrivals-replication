"""U0 common/failure_class.py: classification of fetch failures (transient / permanent).

Cross-cutting base layer, identification-neutral. In plain words: when a fetch fails, it is sorted into one of two classes that decide how to handle it.
  - transient: rate limit 429 / DNS / 5xx / timeout. Retrying is enough; it must go into the refetch queue
    and must never be dropped as "this record has no data".
  - permanent: 404 / 410 / parse failure. The record really is gone; mark it permanent and do not retry.

Iron rules (build checklist section G group 4, T13-T15):
  1. The transient classification never returns {} (empty). That was the root cause of the earlier disaster in which 27k Sydney records
     silently vanished (a transient failure swallowed as an empty dict). This module always returns a classification string, never an empty container.
  2. The fallback direction when no recognisable signal exists (unknown_default_class) is an unset red-line placeholder
     (failure_class.unknown_default_class: null in redlines.yaml). When it is None the code must raise, and must never decide
     on its own "which side to drop by default". It is an identification-rule placeholder; the code itself makes no choice.

Classification values = the "transient" / "permanent" values of the LEDGER_EVENT.status domain (aligned with the schema).
This module consists of pure functions: it takes an error signal (an HTTP status code / an error-type string), makes no network calls and reads no disk (the fallback value
is read via _redlines.require from the already imported literal dict, zero IO at call time).
"""
from __future__ import annotations

from common._redlines import RedlineUnsigned, is_signed, require

# --- classification constants (aligned with the schema.LEDGER_EVENT.status domain: ok/transient/permanent/skip) ---
TRANSIENT: str = "transient"
PERMANENT: str = "permanent"


class UnknownFailureUnsigned(Exception):
    """The signal cannot be classified and the fallback direction (unknown_default_class) is unset -> raised.

    Never classify silently or invent a default. The direction for dropping data when there is no signal is an identification-rule placeholder, not a code decision.
    """


# --- signal lists (engineering mapping, not an identification rule; verbatim from build checklist T13/T14) ---
# Transient HTTP codes: 429 (rate limit) + every 5xx (server side).
_TRANSIENT_HTTP_EXACT: frozenset[int] = frozenset({429})
# Transient error types: DNS resolution failure + timeout (network-layer flakiness; retrying is meaningful).
_TRANSIENT_ERROR_KINDS: frozenset[str] = frozenset({"dns", "timeout"})

# Permanent HTTP codes: 404 (not found) + 410 (permanently removed).
_PERMANENT_HTTP_EXACT: frozenset[int] = frozenset({404, 410})
# Permanent error type: parse failure (the content is broken; retrying is useless).
_PERMANENT_ERROR_KINDS: frozenset[str] = frozenset({"parse"})


def _is_5xx(http_status: int | None) -> bool:
    """5xx server errors (500-599) = transient (retrying is meaningful)."""
    return http_status is not None and 500 <= http_status <= 599


def classify_failure(
    *,
    http_status: int | None = None,
    error_kind: str | None = None,
) -> str:
    """Classify one fetch failure as transient / permanent.

    Args (give at least one; giving none counts as no signal):
        http_status: HTTP status code (e.g. 429/500/404/410).
        error_kind:  non-HTTP error-type string (e.g. "dns"/"timeout"/"parse").

    Returns:
        "transient" (goes into the refetch queue) or "permanent" (not retried).
        Always returns a classification string, never {} / None (guards against the earlier Sydney data-loss bug).

    Raises:
        UnknownFailureUnsigned / RedlineUnsigned: when the signal cannot be classified and
        redlines.failure_class.unknown_default_class is unset (None).
        It never invents a default.

    Rules:
        - The signal lists (429/5xx/DNS/timeout = transient; 404/410/parse = permanent) are an engineering mapping, verbatim
          from build checklist T13/T14, not an identification red line.
        - The no-signal fallback direction is an identification-rule placeholder (null in RED); it raises on None and passes only once set.
    """
    # 1. Transient check (takes precedence over permanent and the fallback): 429 / 5xx / DNS / timeout.
    if http_status is not None:
        if http_status in _TRANSIENT_HTTP_EXACT or _is_5xx(http_status):
            return TRANSIENT
    if error_kind is not None and error_kind in _TRANSIENT_ERROR_KINDS:
        return TRANSIENT

    # 2. Permanent check: 404 / 410 / parse.
    if http_status is not None and http_status in _PERMANENT_HTTP_EXACT:
        return PERMANENT
    if error_kind is not None and error_kind in _PERMANENT_ERROR_KINDS:
        return PERMANENT

    # 3. No recognisable signal -> read the unset fallback direction.
    #    redlines.failure_class.unknown_default_class = null (unset red-line placeholder) ->
    #    require() raises RedlineUnsigned; here it is wrapped once more with UnknownFailureUnsigned semantics.
    #    Never return {} here, and never force permanent/transient as a default.
    if not is_signed("failure_class", "unknown_default_class"):
        raise UnknownFailureUnsigned(
            "Unclassifiable failure signal "
            f"(http_status={http_status!r}, error_kind={error_kind!r}), "
            "and redlines.failure_class.unknown_default_class is not set (null) — "
            "the direction for dropping data on a no-signal fallback is an identification-rule placeholder that a person must set; the code never invents a default."
        )
    # If the fallback direction is ever set, require returns a real value ("transient"/"permanent"); until then this point is never reached.
    return require("failure_class", "unknown_default_class")
