"""identity/dose.py — pure functions for dose.

Hard rules (identity layer): no IO / no network / no state / no operational control flow.

  - coupling_share = the main dose: the "coupling share" of the references two people share up to t-1
    (bibliographic coupling). The normalization caliber is read from RED["dose"]["coupling_normalization"].
  - topic_cos / embed_cos = secondary doses (never enter dose_coupling); deterministic cosine (sorted-keys +
    math.fsum).

Red line (the code never decides it): coupling_normalization = cosine, set in redlines.yaml;
  jaccard is kept as a robustness variant at the M4 call layer. The guard is unchanged: this module has a
  handler for each of the two known normalizations and never sets a private default; if the key is changed
  back to null, require() still raises RedlineUnsigned (value changes go through the red-line ledger).

In plain words:
  coupling_share = how many of the same references they cite -> how close their knowledge is -> how high the dose.
  topic_cos / embed_cos = the cosine similarity of topic vectors / abstract embeddings.

Arguments:
  coupling_share(refs_a:set, refs_b:set, ref_idf:dict|None=None) -> float
  topic_cos(vec_a:dict, vec_b:dict) -> float
  embed_cos(vec_a:list, vec_b:list) -> float
"""
from __future__ import annotations

import math
from typing import Mapping

from common._redlines import require

# The two normalization calibers implemented (the value read from RED must be one of them; never set a private default).
_NORM_JACCARD = "jaccard"
_NORM_COSINE = "cosine"


def _idf_weight(ref: str, ref_idf: Mapping[str, float] | None) -> float:
    """Weight of a single reference: no idf table -> 1.0 (equal weight); with a table -> take its idf (a hub reference naturally gets a low weight).

    A ref with no weight counts as equal weight 1.0 (not removed, not silently dropped).
    """
    if ref_idf is None:
        return 1.0
    return float(ref_idf.get(ref, 1.0))


def coupling_share(
    refs_a: set,
    refs_b: set,
    ref_idf: Mapping[str, float] | None = None,
) -> float:
    """Main dose: the coupling share of two reference sets (symmetric, in [0,1]).

    The normalization caliber is read from RED["dose"]["coupling_normalization"] (unset -> raise):
      - jaccard: weighted intersection / weighted union
      - cosine : weighted intersection / sqrt(weighted|A| * weighted|B|)
    If ref_idf is given, weight by idf (down-weighting hub references); otherwise equal weight.

    Rules:
      - Caliber unset (null) -> RedlineUnsigned (never self-decide cosine/Jaccard).
      - refs is None -> ValueError (never silently pass it as an empty set).
      - Both sides empty / no intersection -> 0.0 (no divide-by-zero crash, no NaN).
    """
    if refs_a is None or refs_b is None:
        raise ValueError("coupling_share: refs must not be None (if upstream did not fetch them, fail loudly)")

    norm = require("dose", "coupling_normalization")  # Unset -> raise
    if norm not in (_NORM_JACCARD, _NORM_COSINE):
        raise NotImplementedError(
            f"coupling_share: unrecognised normalisation {norm!r} — only 'jaccard'/'cosine' are implemented; never set a private default."
        )

    set_a = set(refs_a)
    set_b = set(refs_b)
    inter = set_a & set_b
    if not inter:
        return 0.0

    w_inter = math.fsum(_idf_weight(r, ref_idf) for r in sorted(inter))

    if norm == _NORM_JACCARD:
        union = set_a | set_b
        w_union = math.fsum(_idf_weight(r, ref_idf) for r in sorted(union))
        if w_union <= 0.0:
            return 0.0
        return w_inter / w_union

    # cosine: weighted intersection / sqrt(weighted|A| * weighted|B|)
    w_a = math.fsum(_idf_weight(r, ref_idf) for r in sorted(set_a))
    w_b = math.fsum(_idf_weight(r, ref_idf) for r in sorted(set_b))
    denom = math.sqrt(w_a * w_b)
    if denom <= 0.0:
        return 0.0
    return w_inter / denom


def topic_cos(vec_a: Mapping[str, float], vec_b: Mapping[str, float]) -> float:
    """Secondary dose: cosine similarity of sparse dict vectors (deterministic: sorted-keys + math.fsum).

    Empty vector / zero norm -> 0.0 (no divide-by-zero crash). Never enters dose_coupling (a secondary signal only).
    """
    if vec_a is None or vec_b is None:
        raise ValueError("topic_cos: vector must not be None")

    keys = sorted(set(vec_a) & set(vec_b))
    dot = math.fsum(float(vec_a[k]) * float(vec_b[k]) for k in keys)
    norm_a = math.sqrt(math.fsum(float(v) * float(v) for v in (vec_a[k] for k in sorted(vec_a))))
    norm_b = math.sqrt(math.fsum(float(v) * float(v) for v in (vec_b[k] for k in sorted(vec_b))))
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def embed_cos(vec_a: list, vec_b: list) -> float:
    """Secondary dose: cosine similarity of dense list vectors (math.fsum).

    Mismatched dimensions -> ValueError (an upstream bug fails loudly, never zero-pad). Zero norm -> 0.0.
    embed_cos is boundary_sensitive: it never enters a deterministic hash (the caller's responsibility); this function only computes the value.
    """
    if vec_a is None or vec_b is None:
        raise ValueError("embed_cos: vector must not be None")
    if len(vec_a) != len(vec_b):
        raise ValueError(
            f"embed_cos: dimensions differ ({len(vec_a)} vs {len(vec_b)}) — upstream bug, never zero-pad."
        )

    dot = math.fsum(float(a) * float(b) for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(math.fsum(float(a) * float(a) for a in vec_a))
    norm_b = math.sqrt(math.fsum(float(b) * float(b) for b in vec_b))
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
