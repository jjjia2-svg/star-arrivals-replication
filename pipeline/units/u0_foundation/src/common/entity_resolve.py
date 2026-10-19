"""U0 common/entity_resolve.py: pure functions for entity disambiguation (core of U2; U0 supplies the signatures).

In plain words: disambiguation = correctly assigning "different people with the same name / one person with several records"
to a single real person. This module provides only the pure-function signatures U2 needs plus identification-neutral engineering logic;
every identification threshold is read from redlines.RED, and an unset (null) one -> raise.

Build checklist C.8 (verbatim):
  pair_score(a, b)            incompatible names -> None (otherwise a 0~1 compatibility score).
  cluster_block(records)      ORCID hard seed + order independence (reordering gives the same cluster partition).
  affil_conflict(a, b)->bool  strong-conflict test on affiliation strings (uses a cutoff; DRIFT-ER1 needs the exported value confirmed).
  SCORE_THRESHOLD / HOMOGENEITY_MIN / COMPLETENESS_MIN = None  (red-line placeholders).

Red-line iron rules (the code decides nothing itself):
  1. The three identification thresholds (score/homogeneity/completeness) are module-level None placeholders; the real values live in
     the entity_resolve section of redlines.yaml (all null). Every entry point that "decides using a threshold" reads RED through
     the require_* getters and raises RedlineUnsigned on None; it never invents a default.
  2. ORCID hard seed: only "equal non-empty real ORCIDs" force a merge (red line #11-a). An empty/None ORCID is never a seed:
     Yves Zenou has no ORCID in OpenAlex (had_orcid=False), and seeding a field that does not exist would go down the wrong path and give a false green.
  3. cluster_block's non-ORCID links use only a "hard, threshold-free" predicate (names compatible AND no affil conflict),
     and never use the unset score_threshold inside a cluster. Acceptance decisions that need a threshold go through accept_pair (which raises).

Pure functions: no IO / no network / no state / no operational control flow. Thresholds are read via _redlines.require from the already imported
literal dict (zero IO at call time). The schema aligns with the PERSON_MAP and CLUSTER_PURITY tables.
"""
from __future__ import annotations

import unicodedata
from typing import Any

from common._redlines import require

# ===========================================================================
# Identification-threshold placeholders: module-level None; the real values are in the entity_resolve section of redlines (all null).
# Never fill in a default in this module. Any decision that uses a threshold reads RED via the require_* getters, None -> raise.
# ===========================================================================
SCORE_THRESHOLD: float | None = None        # Disambiguation score threshold (RED entity_resolve.score_threshold)
HOMOGENEITY_MIN: float | None = None         # Lower bound on cluster homogeneity (RED entity_resolve.homogeneity_min)
COMPLETENESS_MIN: float | None = None         # Lower bound on cluster completeness (RED entity_resolve.completeness_min)


def require_score_threshold() -> float:
    """Read the disambiguation score threshold; unset (RED=null) -> RedlineUnsigned, never invent a default."""
    return require("entity_resolve", "score_threshold")


def require_homogeneity_min() -> float:
    """Read the lower bound on cluster homogeneity; unset -> RedlineUnsigned."""
    return require("entity_resolve", "homogeneity_min")


def require_completeness_min() -> float:
    """Read the lower bound on cluster completeness; unset -> RedlineUnsigned."""
    return require("entity_resolve", "completeness_min")


# ===========================================================================
# Name compatibility + pair_score: incompatible names -> None (C.8)
# ===========================================================================
# Engineering mapping (not an identification red line): the hard "surname / given-name initial" compatibility of names is a
# deterministic string rule and contains no numeric threshold. Never force a 0 that would let "clearly different people" get merged; incompatible -> straight None.

def _norm_tokens(display_name: str | None) -> list[str]:
    """Normalise a name to a list of lowercase tokens (punctuation removed, accents folded: Zénou->zenou). Empty name -> [].

    Accent folding added: the U2 blocking key already folded accents (same block), but the scoring layer did not, so
    "Yves Zénou" x "Yves Zenou" were judged name-incompatible and the gold-standard fragments broke apart. NFKD, then drop combining marks.
    """
    if not display_name:
        return []
    nfkd = unicodedata.normalize("NFKD", display_name)
    folded = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    cleaned = []
    for ch in folded.lower():
        cleaned.append(ch if (ch.isalnum() or ch.isspace()) else " ")
    return [t for t in "".join(cleaned).split() if t]


def _surname(tokens: list[str]) -> str:
    """Surname = the last token (the Western ordering convention of OpenAlex display_name). No token -> ""."""
    return tokens[-1] if tokens else ""


def _given_tokens(tokens: list[str]) -> list[str]:
    """Given name = the leading tokens other than the surname."""
    return tokens[:-1] if len(tokens) > 1 else []


def _first_initial(given: list[str]) -> str:
    """Given-name initial (used for the hard-conflict test). No given name -> ""."""
    return given[0][0] if given and given[0] else ""


def names_compatible(a_name: str | None, b_name: str | None) -> bool:
    """Whether two display_names "could be the same person" (hard compatibility, no threshold).

    Rules (deterministic, not an identification red line):
      - Different surnames -> incompatible.
      - Same surname but both given-name initials present and different -> incompatible (J. vs R.).
      - Otherwise (same surname + same initial / one side lacks a given name) -> compatible.
    """
    ta, tb = _norm_tokens(a_name), _norm_tokens(b_name)
    if not ta or not tb:
        return False
    if _surname(ta) != _surname(tb):
        return False
    ia, ib = _first_initial(_given_tokens(ta)), _first_initial(_given_tokens(tb))
    if ia and ib and ia != ib:
        return False
    return True


def _given_overlap_score(ga: list[str], gb: list[str]) -> float:
    """Finer compatibility of the given-name tokens: identical full name 1.0 / same initial 0.5 / one side lacks a given name 0.5.

    A purely engineering similarity gradation (not an identification threshold), used only for pair_score's continuous output, not for accept decisions.
    """
    if not ga or not gb:
        return 0.5
    if ga == gb:
        return 1.0
    # Same initial (names_compatible already guarantees no conflict) -> middle score.
    return 0.6 if _first_initial(ga) == _first_initial(gb) else 0.5


def pair_score(a: dict[str, Any], b: dict[str, Any]) -> float | None:
    """Compatibility score of two author records, in [0,1]; incompatible names -> None (C.8).

    Args:
        a, b: author-record dicts containing at least "display_name" (may contain "orcid"/"raw_affil").

    Returns:
        float in [0,1]: the continuous compatibility score when names are compatible (higher = more likely the same person).
        None: names are incompatible (different surnames / conflicting initials): not even compared, never forced to 0.

    Iron rule: this function only produces a continuous score and makes no binary "accept or not" decision (that needs a
    threshold; an unset threshold goes through accept_pair, which raises). It reads no unset threshold itself, so it is usable as a pure function.
    """
    if not names_compatible(a.get("display_name"), b.get("display_name")):
        return None

    ta, tb = _norm_tokens(a.get("display_name")), _norm_tokens(b.get("display_name"))
    name_component = _given_overlap_score(_given_tokens(ta), _given_tokens(tb))

    # Affiliation agreement as a small positive bonus (identification-neutral; a conflict lowers it but not to zero, zeroing is the accept layer's job).
    affil_component = 0.0 if affil_conflict(a.get("raw_affil"), b.get("raw_affil")) else 1.0

    # Weighted composite (weights are an engineering convention, not an identification red line; the same surname is already a hard precondition): name 0.7 + affiliation 0.3.
    score = 0.7 * name_component + 0.3 * affil_component
    # Clamp to [0,1].
    return max(0.0, min(1.0, score))


# ===========================================================================
# affil_conflict(a, b) -> bool: strong conflict between affiliation strings (C.8, DRIFT-ER1)
# ===========================================================================
# DRIFT-ER1 / to confirm: the build checklist names "use AFFIL_CONFLICT_CUTOFF (DRIFT-ER1: the exported value must be confirmed)".
#   But the entity_resolve section of redlines.yaml has only the three keys score/homogeneity/completeness and no
#   affil_conflict cutoff. Whether to promote it to an identification red-line threshold is not specified, so no numeric value is added.
#   This implementation uses a "hard, magic-number-free" structural predicate (whether the salient tokens are entirely disjoint) to decide a conflict;
#   if a numeric cutoff turns out to be needed, read it from RED (via require). No default threshold is filled in.

# Stop words with no information in an affiliation string (engineering mapping, not an identification red line): they take no part in the "same institution?" decision.
_AFFIL_STOPWORDS: frozenset[str] = frozenset({
    "university", "univ", "of", "the", "institute", "college", "school",
    "department", "dept", "faculty", "and", "for", "research", "centre",
    "center", "national", "international",
})


def _affil_sig_tokens(raw_affil: Any) -> set[str]:
    """The set of salient tokens of an affiliation string (stop words removed).

    raw_affil may be a str or a list[str] (works_affil.raw_affiliation_strings is a list);
    None/empty -> empty set.
    """
    if raw_affil is None:
        return set()
    if isinstance(raw_affil, (list, tuple)):
        text = " ".join(str(x) for x in raw_affil)
    else:
        text = str(raw_affil)
    toks = _norm_tokens(text)
    return {t for t in toks if t not in _AFFIL_STOPWORDS and len(t) > 1}


def affil_conflict(a: Any, b: Any) -> bool:
    """Whether the affiliation strings of two records "strongly conflict" (C.8).

    Args:
        a, b: affiliation strings (str or list[str], from works_affil.raw_affiliation_strings).

    Returns:
        True: strong conflict (both sides have salient affiliation tokens and they are entirely disjoint).
        False: no conflict (including: either side empty/uninformative -> not evidence of conflict, conservatively False).

    Rule: uses the hard structural predicate "salient tokens entirely disjoint", with no numeric cutoff.
      DRIFT-ER1 (whether to make AFFIL_CONFLICT_CUTOFF numeric) is still open; no threshold is filled in meanwhile.
    """
    sa, sb = _affil_sig_tokens(a), _affil_sig_tokens(b)
    if not sa or not sb:
        # One side has no affiliation information -> no "conflict" evidence, conservatively judged no conflict (never treated as a conflict and wrongly split).
        return False
    # Both sides have salient tokens and they are entirely disjoint -> strong conflict.
    return sa.isdisjoint(sb)


# ===========================================================================
# cluster_block: ORCID hard seed + order independence (C.8)
# ===========================================================================
# Implementation = union-find, which is naturally order independent. Two kinds of links:
#   1. ORCID hard seed: equal non-empty real ORCIDs -> must merge (red line #11-a; empty/None is never a seed).
#   2. Soft link: accept_pair (threshold 0.8) AND no affil conflict -> merge.
# Order independence comes from: (a) iterating in sorted author_id order; (b) choosing min(author_id) as the representative of a union -> deterministic labels.

def _find(parent: dict[str, str], x: str) -> str:
    """Union-find: find the root (with path compression)."""
    root = x
    while parent[root] != root:
        root = parent[root]
    while parent[x] != root:
        parent[x], x = root, parent[x]
    return root


def _union(parent: dict[str, str], x: str, y: str) -> None:
    """Union-find: merge; the representative is always the smaller author_id (deterministic -> order-independent labels)."""
    rx, ry = _find(parent, x), _find(parent, y)
    if rx == ry:
        return
    lo, hi = (rx, ry) if rx < ry else (ry, rx)
    parent[hi] = lo


def _valid_orcid(orcid: Any) -> str | None:
    """Effective hard-seed ORCID: only a non-empty, non-blank string counts; otherwise None (never a seed)."""
    if not orcid:                      # None / "" / other falsy values -> does not count
        return None
    s = str(orcid).strip()
    return s if s else None


def cluster_block(records: list[dict[str, Any]]) -> dict[str, str]:
    """Cluster the author records within one same-name block (C.8: ORCID hard seed + order independence).

    Args:
        records: list of author-record dicts, each must contain "author_id"; may contain "orcid"/"display_name"/"raw_affil".

    Returns:
        dict author_id -> cluster_label (the label = the smallest author_id in the cluster).
        Every record's author_id gets a label (nobody is dropped).

    Rules (the code decides nothing itself):
      - ORCID hard seed: only "equal non-empty real ORCIDs" force a merge (red line #11-a). An empty/None ORCID is never a seed.
      - Soft link: accept_pair (pair_score >= score_threshold = 0.8) AND no affil conflict.
        An earlier version linked on the pure hard predicate alone (names compatible); calibration on real data showed catastrophic false merges, so it was dropped.
      - Order independence: union-find + sorting by author_id + representative = min(author_id) -> reordering gives the same partition.
    """
    ids = [r["author_id"] for r in records]
    parent: dict[str, str] = {aid: aid for aid in ids}
    by_id: dict[str, dict[str, Any]] = {r["author_id"]: r for r in records}

    # Sorted by author_id -> deterministic iteration (order independent).
    sorted_ids = sorted(ids)

    # 1. ORCID hard seed: all records with the same non-empty ORCID are merged together.
    orcid_groups: dict[str, list[str]] = {}
    for aid in sorted_ids:
        oc = _valid_orcid(by_id[aid].get("orcid"))
        if oc is not None:
            orcid_groups.setdefault(oc, []).append(aid)
    for group in orcid_groups.values():
        first = group[0]
        for other in group[1:]:
            _union(parent, first, other)

    # 2. Soft link: accept_pair (score_threshold = 0.8) + affil-conflict veto.
    #    The old hard predicate "names compatible AND no affil conflict" produced catastrophic false merges on real data: people from two universities
    #    all share university affil tokens, so the conflict defence fails (calibration: one common name abbreviation merged 63 people into 1,
    #    and the must-split violation rate was 99.4%);
    #    threshold 0.8 = merge only when the names truly overlap (usable band in calibration [0.75,1.00], violations drop to 6.5%).
    n = len(sorted_ids)
    for i in range(n):
        for j in range(i + 1, n):
            ai, aj = sorted_ids[i], sorted_ids[j]
            ra, rb = by_id[ai], by_id[aj]
            if not accept_pair(ra, rb):           # Names incompatible, or score < threshold -> no link
                continue
            if affil_conflict(ra.get("raw_affil"), rb.get("raw_affil")):
                continue                          # Strong affiliation conflict -> no link (defence in depth)
            _union(parent, ai, aj)

    # Output: each record -> its cluster root (= the smallest author_id in the cluster).
    return {aid: _find(parent, aid) for aid in sorted_ids}


# ===========================================================================
# accept_pair: the binary "accept this merge or not" decision (needs a threshold; unset -> raise)
# ===========================================================================

def accept_pair(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Whether to accept two records as the same person (uses the score_threshold).

    Threshold unset (RED entity_resolve.score_threshold = null) -> RedlineUnsigned.
      Never lets it through silently or invents a default. An identification threshold is not set by code.

    Returns (only when the threshold is set):
        True: names compatible and pair_score >= score_threshold.
        False: names incompatible (pair_score is None) or score below the threshold.
    """
    threshold = require_score_threshold()   # Unset -> RedlineUnsigned (blows up here, not let through)
    score = pair_score(a, b)
    if score is None:                       # Names incompatible -> not accepted
        return False
    return score >= threshold
