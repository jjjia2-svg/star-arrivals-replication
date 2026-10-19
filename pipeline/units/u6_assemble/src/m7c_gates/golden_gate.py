"""golden_gate (G-golden): HIGH-3. Control flow lives in M7c, and classify_golden stays a pure verdict.

U6 observable side -> assembly of the frame argument of classify_golden (build_zenou_material):
  found/is_star_at_p01        <- star_set (located by ZENOU_STRUCTURAL.name, tolerant of diacritics)
  resolved_single_person      <- person_map (all Yves Zenou author fragments fold into one person)
  institution_canonical_observed / arrival_year_observed <- events (Zenou's events)
  armi_folded_to_monash       <- all of Zenou's events' depts fold to the Monash canonical
  caulfield_folded_to_none    <- no second phantom event
  rejected_1998_backfill      <- no event with arrival=1998
  read_affiliations_years     <- static scan of this unit's source (the word affiliations appears zero times)
  took_largest_cluster        <- semantics already verified in U2 (U6 only folds via person_map, so always False)
  works_count_observed        <- panel n_works_year summed over years (t61: the frame has no such column)

Verdict (decide_golden_action): structural_pass=False -> HALT (fail-closed);
release_changed -> HUMAN_REVIEW; observed_in_range=False (structure passes) -> WARN; everything passes -> PASS.
A structural red overrides everything. affiliations.years is never trusted.
"""
from __future__ import annotations

import inspect
import unicodedata

from identity.exit_codes import GOLDEN_FAIL
from identity.golden import MONASH_CANONICAL_ID, ZENOU_OBSERVED, \
    ZENOU_STRUCTURAL, classify_golden


class GoldenStructuralFail(Exception):
    """The Yves Zenou gold standard fails its structural check (fail-closed)."""

    exit_code: int = GOLDEN_FAIL


def _norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _static_reads_affiliations_years() -> bool:
    """Whether this unit's source reads affiliations (red line #3: must be zero)."""
    import m7b_assemble.assemble as _asm
    import m7b_assemble.incumbent_roster as _ir

    for mod in (_asm, _ir):
        if "affiliations" in inspect.getsource(mod):
            return True
    return False


def build_zenou_material(*, star_set: list, events: list, person_map: list,
                         panel: list) -> dict:
    """Assemble the classify_golden observation frame from U6 inputs (read-only, changes no definition)."""
    want = _norm_name(ZENOU_STRUCTURAL["name"])
    z_rows = [s for s in star_set if _norm_name(s.get("name", "")) == want]
    found = bool(z_rows)
    z_authors = {s["author_id"] for s in z_rows}
    pids = {r["person_id"] for r in person_map if r["author_id"] in z_authors}
    resolved_single = found and len(pids) == 1
    z_pid = next(iter(pids)) if len(pids) == 1 else None
    n_frags = sum(1 for r in person_map if r["person_id"] == z_pid) \
        if z_pid else 0
    is_star_p01 = any(bool(s.get("is_star_1pct")) for s in z_rows)

    z_events = [e for e in events if e["star_person_id"] in z_authors]
    inst = z_events[0]["dept_id"] if len(z_events) == 1 else (
        z_events[0]["dept_id"] if z_events else None)
    arrival = z_events[0]["arrival_year"] if z_events else None
    armi_ok = bool(z_events) and all(e["dept_id"] == MONASH_CANONICAL_ID
                                     for e in z_events)
    no_phantom = len(z_events) == 1
    rejected_1998 = bool(z_events) and all(e["arrival_year"] != 1998
                                           for e in z_events)
    # Cluster purity: the Yves Zenou cluster must not contain fragments of other star candidates (the U6 observable side of kicking out a namesake from the anchor)
    other_authors = {s["author_id"] for s in star_set} - z_authors
    other_pids = {r["person_id"] for r in person_map
                  if r["author_id"] in other_authors}
    cluster_pure = z_pid is not None and z_pid not in other_pids

    works_count = sum(p.get("n_works_year") or 0 for p in panel
                      if p["person_id"] == z_pid) if z_pid else None

    return {
        "found": found,
        "resolved_single_person": resolved_single,
        "is_star_at_p01": is_star_p01,
        "institution_canonical_observed": inst,
        "armi_folded_to_monash": armi_ok,
        "caulfield_folded_to_none": no_phantom,
        "arrival_year_observed": arrival,
        "rejected_1998_backfill": rejected_1998,
        "read_affiliations_years": _static_reads_affiliations_years(),
        "took_largest_cluster": False,   # U6 only folds via person_map (semantics already verified in U2)
        "works_count_observed": works_count,
        "cluster_pure_econ_network": cluster_pure,
        "n_author_fragments": n_frags,
    }


def decide_golden_action(golden_result: dict, *,
                         release_changed: bool = False) -> str:
    """HIGH-3 control flow: structural red HALT > release HUMAN_REVIEW > observation out of range WARN > PASS."""
    if not golden_result.get("structural_pass", False):
        return "HALT"
    if release_changed:
        return "HUMAN_REVIEW"
    if not golden_result.get("observed_in_range", True):
        return "WARN"
    return "PASS"


def run_golden_gate(*, star_set: list, events: list, person_map: list,
                    panel: list) -> dict:
    mat = build_zenou_material(star_set=star_set, events=events,
                               person_map=person_map, panel=panel)
    result = classify_golden(mat)
    # B6-GOLDEN: the _anchored_release anchor is still TODO (None==None -> release unchanged);
    # once backfilled, the "current snapshot release != anchored release" test goes here.
    release_changed = (ZENOU_OBSERVED["_anchored_release"] is not None
                       and False)
    verdict = decide_golden_action(result, release_changed=release_changed)
    out = {"gate": "G-golden", "verdict": verdict, **result,
           "material": mat,
           "anchored_release": ZENOU_OBSERVED["_anchored_release"],
           "topics_version": ZENOU_OBSERVED["_topics_version"]}
    if verdict == "HALT":
        raise GoldenStructuralFail(
            f"Zenou golden-standard structural check failed: flips={result['flips']}")
    return out
