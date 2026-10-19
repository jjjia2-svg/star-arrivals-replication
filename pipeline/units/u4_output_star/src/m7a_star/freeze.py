"""freeze: freeze the two core blocks star_set / events: stars_set_hash + the Yves Zenou golden-test gate.

In plain words: ① stars_set_hash = a content fingerprint of "the star set + each person's
arrival year" (deterministic, invariant to row order), which goes into the provenance
4-tuple; ② the Yves Zenou golden-test gate = before freezing, the Yves Zenou acceptance
test must pass; if any anchor fails → GOLDEN_FAIL blocks the freeze.

Red-line anchor: the Yves Zenou golden test must be caught (missing a person or a fake
event is not allowed); the classify_golden rules live only in identity.golden (single
definition; this layer only calls it and fails loudly on a flip). stars_set_hash takes
the normalised content, not the raw parquet bytes. Pure functions, no IO (the real freeze
writes to disk in the write layer / run_u4).
"""
from __future__ import annotations

import hashlib
from typing import Mapping

from identity.exit_codes import GOLDEN_FAIL
from identity.golden import classify_golden


class GoldenFailure(Exception):
    """A Yves Zenou golden-test anchor failed → the freeze must stop (exit code GOLDEN_FAIL=18). Fails loudly and never silently produces a polluted list."""


def stars_set_hash(star_arrivals: Mapping[str, int]) -> str:
    """Star set + each person's arrival year → content fingerprint (sha256, deterministic, invariant to row order).

    star_arrivals: {star_person_id: arrival_year}.
    Normalisation: sort by person_id → one line "pid\\tyear" per person → sha256. It takes
    content, not raw parquet bytes, so it is stable across on-disk layouts (the
    stars_set_hash of the provenance 4-tuple).
    """
    items = sorted((str(pid), int(yr)) for pid, yr in star_arrivals.items())
    canonical = "\n".join(f"{pid}\t{yr}" for pid, yr in items)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def assert_zenou_golden(frame: dict) -> dict:
    """Freeze gate: passes only if the Yves Zenou golden test (classify_golden) passes; structural_pass=False → GoldenFailure.

    Returns the full classify_golden result (structural_pass/observed_in_range/flips/...) for the audit record.
    Fails loudly: a missed person, a wrong university or a fake arrival is never turned into a star list.
    """
    result = classify_golden(frame)
    if not result["structural_pass"]:
        raise GoldenFailure(
            f"Yves Zenou golden test failed (GOLDEN_FAIL={GOLDEN_FAIL}) — failed anchors flips={result['flips']}; "
            "freeze stopped, needs human inspection (missed person / wrong university / fake arrival / read affiliations.years / took the largest cluster)."
        )
    return result
