"""m4_dose/topic_vec.py — secondary dose, subfield topic channel (#16).

Position: **the secondary dose is only a robustness check and never enters the main dose coupling_share** (#16; #22 main
and secondary are physically separated — main-path modules must never import this file).

Normalising the two topic-ID formats (#23; official-doc-first):
  OpenAlex topic/subfield IDs are in flight in three formats: int `2002`, str `subfields/2002`, and a full URL
  (an integer-to-string migration since 2024). The secondary dose always passes subfield_id through
  `canonical_subfield_id` and never compares raw values.
  Warning: the intended home of this function is upstream `shared/ids.canonical_subfield_id`, but u0 has no such module
  yet (an upstream gap, like B-SCHEMA-A). Following the rule "use a local implementation until it is registered, never import a dangling symbol",
  this file holds a local literal implementation; once upstream lands shared/ids, this should become a thin forwarder and the local body should be deleted.
  A sourced reference for official-doc-first (an OpenAlex topic-ID usage note) is still to be added.

B-SUBF safety net (measured: primary_topic.subfield is present on 100% of rows):
  the entry check assert_subfield_available stays — an all-empty/missing column -> raise, never silently produce all-zero vectors.
"""
from __future__ import annotations

from identity import dose as identity_dose

from . import cutoff

_URL_PREFIXES: tuple = (
    "https://openalex.org/subfields/",
    "https://api.openalex.org/subfields/",
    "subfields/",
)


class SubfieldUnavailable(ValueError):
    """works lacks subfield_id (column absent / all None) — the B-SUBF safety net, never silent."""


def canonical_subfield_id(x) -> str:
    """subfield ID in three formats (int / 'subfields/N' / full URL) -> canonical bare-number string 'N'.

    None -> ValueError (missing values must first go through assert_subfield_available in the caller; they are not swallowed here).
    """
    if x is None:
        raise ValueError("canonical_subfield_id: None cannot be normalised — upstream lacks subfield")
    s = str(x).strip()
    low = s.lower()
    for prefix in _URL_PREFIXES:
        if low.startswith(prefix):
            s = s[len(prefix):]
            break
    return s


def assert_subfield_available(works_rows, *, label: str = "works") -> None:
    """B-SUBF safety net: works rows lack the subfield_id column / all None -> SubfieldUnavailable."""
    if not works_rows:
        return
    n_present = 0
    for row in works_rows:
        if "subfield_id" not in row:
            raise SubfieldUnavailable(
                f"[{label}] rows lack the subfield_id column — no input for the secondary dose topic channel (B-SUBF)"
            )
        if row["subfield_id"] is not None:
            n_present += 1
    if n_present == 0:
        raise SubfieldUnavailable(
            f"[{label}] subfield_id is all None — no input for the secondary dose topic channel (B-SUBF); "
            "no all-zero vector is silently produced"
        )


def person_topic_vec(person_id: str, person_edges, works_by_id: dict,
                     t_minus_1: int) -> dict:
    """Person-level topic vector = distribution of subfield counts over that person's works up to t-1 (keys normalised).

    Truncation goes through cutoff.filter_works_until (#7); subfield keys pass canonical_subfield_id
    (#23, no raw comparison); a work whose subfield_id is None is skipped (not counted as a 0 key).
    """
    frozen = cutoff.filter_works_until(person_edges, t_minus_1)
    vec: dict = {}
    for row in frozen:
        if row["person_id"] != person_id:
            continue
        w = works_by_id.get(row["work_id"])
        if w is None:
            continue
        sf = w.get("subfield_id")
        if sf is None:
            continue
        key = canonical_subfield_id(sf)
        vec[key] = vec.get(key, 0.0) + 1.0
    return vec


def pair_topic_cos(vec_a: dict, vec_b: dict) -> float:
    """Delegation point for the secondary dose: identity.dose.topic_cos (deterministic cosine; empty/zero-norm -> 0.0)."""
    return identity_dose.topic_cos(vec_a, vec_b)
