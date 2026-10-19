"""m4_dose/coupling.py — calling layer for the main dose (red line #16).

Main dose = bibliographic coupling: the share of references that the two people's works up to t-1 have in common.
It is frozen in the past by construction and is the most resistant to post-arrival convergence contamination (the reason #16 uses it as the main dose).

Rules:
  - **The single source of the formula is identity.dose.coupling_share. This module only delegates and never rewrites it**
    (#14; IDF down-weighting and cosine normalisation both live in identity; the normalisation choice is read from RED,
    and if it is not set, RedlineUnsigned propagates unchanged: the code never fills it in itself).
  - B-NORM-INJECT closure: the `coupling_share` signature is unchanged; normalisation variants are robustness checks in the calling layer
    (the Jaccard robustness variant is out of scope: the main dose has a single definition).
  - The refs column name is anchored to the official name `referenced_work_id` (U0 schema), accessed by direct key —
    a wrong name raises KeyError (#15), with no silent compatibility.
  - Truncation goes through the single entry point cutoff.filter_works_until (#7); refs_edges has no year,
    so a person's work years come from person_edges (sourced from the works join, H4).
  - R7 window length: the default is the full history up to t-1, plus a `window_years=None` stub
    (# robustness knob: the freeze direction is fixed (#16); the window length is optional and does not block).
  - This file only touches inputs derived from refs_edges/works; no secondary-dose stem may appear in it
    (the #22 source-guard test bans them all; main and secondary doses are physically separated at file level).
"""
from __future__ import annotations

import math

from identity import dose as identity_dose

from . import cutoff


def refs_by_work(refs_rows) -> dict:
    """refs_edges rows -> {work_id: set(referenced_work_id)}.

    Direct key access to referenced_work_id: a wrong column name (e.g. the old name ref_work_id) raises KeyError (#15).
    """
    out: dict[str, set] = {}
    for r in refs_rows:
        out.setdefault(r["work_id"], set()).add(r["referenced_work_id"])
    return out


def build_ref_idf(refs_rows, *, idf_floor: float) -> dict:
    """All refs in the corpus -> IDF weight table (down-weights hub refs; #17).

    idf(ref) = ln(N / df(ref)); N = number of distinct citing works in the corpus, df = number of citing works that cite it.
    weight = max(idf, idf_floor). The floor idf_floor is read by the calling layer from
    RED dose.hub_ref_idf_floor and passed in (M4 only imports RED and passes the value; it never assigns it in this directory).
    A hub cited by every work: idf=ln(1)=0, so with floor 0.0 its weight is 0 (it drops to zero once identity applies the weights).
    Engineering note: ln(N/df) is the standard IDF form. The direction (down-weighting hubs) is fixed; the exact
    function is an engineering choice (not an identification red line), and variants only affect robustness checks.
    """
    df: dict[str, set] = {}
    citing: set = set()
    for r in refs_rows:
        w = r["work_id"]
        ref = r["referenced_work_id"]
        citing.add(w)
        df.setdefault(ref, set()).add(w)
    n = len(citing)
    out: dict[str, float] = {}
    for ref in sorted(df):
        idf = math.log(n / len(df[ref])) if n > 0 else 0.0
        out[ref] = max(idf, float(idf_floor))
    return out


def person_refs_until(person_id: str, person_edges, refs_map: dict,
                      t_minus_1: int, *, window_years: int | None = None) -> set:
    """Union of referenced_works over all of a person's works up to t-1 (raw input for the main dose, #16).

    person_edges rows must carry publication_year (from the works join, H4) —
    truncated through cutoff.filter_works_until (inclusive; a missing year raises).
    window_years: robustness knob — the freeze direction is fixed (#16), the window length is optional;
      None (default) = full history up to t-1; an integer w = only the rolling window [t-1-w+1, t-1].
    """
    frozen = cutoff.filter_works_until(person_edges, t_minus_1)
    if window_years is not None:
        lo = t_minus_1 - int(window_years) + 1
        frozen = [r for r in frozen if r["publication_year"] >= lo]
    refs: set = set()
    for row in frozen:
        if row["person_id"] == person_id:
            refs |= refs_map.get(row["work_id"], set())
    return refs


def pair_coupling(refs_a: set, refs_b: set, ref_idf: dict | None) -> float:
    """Delegation point for the main dose: identity.dose.coupling_share(refs_a, refs_b, ref_idf=ref_idf).

    Delegate only (#14) — normalisation, weighting and divide-by-zero semantics all live in identity;
    if RED dose.coupling_normalization is not set, RedlineUnsigned propagates unchanged.
    """
    return identity_dose.coupling_share(refs_a, refs_b, ref_idf=ref_idf)


def pair_coverage(person_a: str, person_b: str, person_edges, works_by_id: dict,
                  t_minus_1: int) -> float:
    """coupling_coverage = share of works in the two people's t-1 union with has_references=True (#18).

    Raw input for the refs MNAR (missing not at random) diagnosis (caveat#1): works with few citations are more likely
    to lack refs, so the missingness is non-random.
    Low coverage -> the run layer flags boundary_sensitive per RED coverage_floor;
    a global missing rate above mnar_missing_threshold flags mnar_robustness_required.
    Empty union -> 0.0 (no divide-by-zero crash). A work not in works_by_id -> KeyError (fail loud).
    """
    frozen = cutoff.filter_works_until(person_edges, t_minus_1)
    union_works = {
        r["work_id"] for r in frozen if r["person_id"] in (person_a, person_b)
    }
    if not union_works:
        return 0.0
    n_with = sum(
        1 for w in sorted(union_works) if works_by_id[w]["has_references"]
    )
    return n_with / len(union_works)
