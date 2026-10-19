"""Fold an institution to its canonical education parent institution (red line #1 / HIGH-10).

In plain words: the affiliation OpenAlex gives an author is often a "child institution" (an institute / a hospital / a campus).
It has to be folded back to the "education parent institution" it really belongs to (e.g. Monash University), so that the
modal-institution method for the arrival decision is not scattered by child-institution noise. If it cannot be folded to a
legitimate education parent -> None (never forced onto some university).

Pure function, zero IO, zero network, zero state (identity iron rule): it only matches the already loaded inst dict against
registry_by_id in memory; reading from disk and validating the invariant is done by afid_verify.load_validated_registry.

Three-path fold (fold_to_canonical, as specified in checklist item C.1):
  (1) self hits the registry: inst's own openalex_id is in the registry -> return it (it is already a legitimate parent).
  (2) a lineage ancestor is in the registry: some ancestor in inst's lineage chain is in the registry -> fold to that ancestor.
  (3) in associated_institutions, relationship in {parent} and education:
      an associated parent whose type is in EDUCATION_WHITELIST and whose bare id is in the registry -> fold to it.
All paths return a bare id (e.g. "I56590836", not the URL form); if no path hits -> None.

registry_by_id = {bare openalex_id : record} as produced by afid_verify.build_registry_by_id; its key domain
= the set of legitimate canonical education institutions folded out of U0.5 Table A (including all foreign ones, e.g. Stockholm).
"""
from __future__ import annotations

from typing import Dict, Optional

from common._redlines import require

# --- C.1 / HIGH-10: whitelist of parent-institution relationships, read from redlines (never a hard-coded literal) ---
# RED["education_whitelist"] = ["education"].
EDUCATION_WHITELIST: frozenset = frozenset(require("education_whitelist"))


def _bare(inst_id: Optional[str]) -> Optional[str]:
    """Normalise an OpenAlex id to the bare form (strip the 'https://openalex.org/' prefix).

    lineage / associated_institutions[].id are URL-form in the snapshot; registry keys are bare.
    Both sides are reduced to bare before matching, to avoid URL<->bare misses. None/empty -> returned as is (the caller checks for empty).
    """
    if not inst_id:
        return inst_id
    return inst_id.rsplit("/", 1)[-1] if inst_id.startswith("http") else inst_id


def fold_to_canonical(
    inst: dict, registry_by_id: Dict[str, dict]
) -> Optional[str]:
    """Fold a child institution inst to the bare id of its canonical education parent by three paths; cannot fold -> None.

    Args:
      inst: a single institution record (the in-memory form of one INSTITUTIONS table row), containing at least
              {openalex_id, type, lineage:list<str>, associated_institutions:list<dict>}.
      registry_by_id: {bare openalex_id : record}, the set of legitimate canonical education institutions
                        (produced by build_registry_by_id; the key domain includes all foreign education institutions).
    Returns: on a hit, the bare canonical edu id (e.g. "I56590836"); no path hits -> None.

    Iron rule: a pure function that does not modify its arguments; it only reads inst + registry_by_id, zero IO/zero network.
    """
    # --- path 1: self hits the registry (inst itself is a legitimate parent institution) ---
    self_id = _bare(inst.get("openalex_id"))
    if self_id and self_id in registry_by_id:
        return self_id

    # --- path 2: a lineage ancestor is in the registry ---
    # lineage is the chain from the root to the institution itself; check each entry (excluding itself) for membership in the registry.
    for raw_anc in inst.get("lineage") or []:
        anc = _bare(raw_anc)
        if anc and anc != self_id and anc in registry_by_id:
            return anc

    # --- path 3: in associated_institutions, relationship==parent and type is education ---
    for assoc in inst.get("associated_institutions") or []:
        if assoc.get("relationship") != "parent":
            continue
        if assoc.get("type") not in EDUCATION_WHITELIST:
            continue
        parent = _bare(assoc.get("id"))
        if parent and parent in registry_by_id:
            return parent

    # --- no path hits: cannot fold to a legitimate parent -> None (never forced onto some university) ---
    return None


def in_au_econ_dept(
    canonical_id: Optional[str], econ_dept_ids: set
) -> bool:
    """Whether canonical_id falls inside econ_dept_ids, the set of Australian economics-department boundary institutions.

    Used only as a reconciliation layer, not as the identity authority (G2: Table B is the only authority).
    econ_dept_ids = set[bare canonical edu id] folded out of U0.5 Table A.
    When the call site passes the sentinel (PANEL_AFFIL_NONE) it has already been explicitly converted to None -> None here is simply False (no crash).
    """
    if canonical_id is None:
        return False
    return canonical_id in econ_dept_ids
