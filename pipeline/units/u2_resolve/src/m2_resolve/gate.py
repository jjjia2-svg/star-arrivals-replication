"""U2 exit gate + acceptance diagnostics + manual-review queue (G1-G4); does not produce person_map (resolve.py is the only producer).

Reads the person_map frozen by resolve.py -> calls U0 validate_resolution as the exit gate (completeness blocks under-merge,
#11-b) + over-merge diagnostics + manual-review queue + Zenou golden-standard e2e + Monash attribution + second freeze.
Only orchestrates calls into U0/U1 and never rewrites an algorithm. Every identification threshold is null -> RedlineUnsigned (a value must be set by hand).
For conventions and redlines see ../../CONTRACT.md + ../../README.md.
"""
import sys
from collections import Counter, defaultdict

from common._redlines import RED, require
from common.entity_resolve import affil_conflict, names_compatible
from common.reverse_validate import (
    bcubed_f1,
    faceting_recall,
    pairwise_f1,
    validate_resolution,
)
from m2_resolve.resolve import run_overmerge_probe, _is_star_or_direct_collaborator


def run_exit_gate(
    pred_labels,
    gt_labels,
    *,
    is_large_dept,
    evidence_path,
    pred_facet_records=None,
    gt_facet_records=None,
    facet_key=("works_bucket", "year"),
):
    """G1 exit gate: build metrics -> call U0 validate_resolution (threshold not set -> RedlineUnsigned; below standard -> ResolveGateFail).

    metrics mapping (B³ is directional, #11-b):
      recall/precision = pairwise (pairwise_f1; at real-data scale switch to compute_recall_precision, same definition)
      completeness     = bcubed_recall    (hard constraint on under-merge, #11-b: not pairwise recall)
      homogeneity      = bcubed_precision  (hard constraint on over-merge)
      faceting_recall  = worst facet recall (no facet data -> 1.0)
    The hard-gate decision is left entirely to U0 evaluate_gate (recall/precision/completeness/homogeneity/faceting); B³/pairwise serve only as
    the source of metrics + diagnostics and add no gate of their own. Inside validate_resolution: threshold null -> RedlineUnsigned (no evidence written);
    below standard -> atomically write the evidence (including fails) + raise ResolveGateFail.
    Returns metrics (pass path only; a failure has already raised).
    """
    pw = pairwise_f1(pred_labels, gt_labels)
    b3 = bcubed_f1(pred_labels, gt_labels)
    if pred_facet_records is not None and gt_facet_records is not None:
        fr = faceting_recall(pred_facet_records, gt_facet_records, facet_key=facet_key)["faceting_recall"]
    else:
        fr = 1.0
    metrics = {
        "recall": pw["pairwise_recall"],
        "precision": pw["pairwise_precision"],
        "completeness": b3["bcubed_recall"],      # hard bound on under-merge (#11-b)
        "homogeneity": b3["bcubed_precision"],    # hard bound on over-merge
        "faceting_recall": fr,
    }
    validate_resolution(metrics, is_large_dept=is_large_dept, evidence_path=str(evidence_path))
    return metrics


# ===========================================================================
# G2 - cluster purity diagnostics (cluster_purity) + write the quality columns back to person_map (HIGH-3, exactly once)
# ===========================================================================
def _assert_upstream_fields(author_records, works):
    """Fail loudly at start-up: a missing required upstream field means HALT (it points at an unshipped U1 table, an engineering gap, not an open convention).

    Note: currently checks display_name (authors) + subfield_id (works); the full upstream check (raw_affil/title)
    will be added once the works_affil/work_text signals are wired in. Never compute a constant purity over an all-missing column and pretend it passed (mirrors the U1 probe-halt).
    """
    if any("display_name" not in r for r in author_records):
        raise RuntimeError("[U2 G2] author display_name missing → HALT (U1 authors table not shipped? engineering gap)")
    if any("subfield_id" not in w for w in works):
        raise RuntimeError("[U2 G2] works subfield_id missing → HALT (U1 works table not shipped? engineering gap)")


def _check_subfield_coverage(works):
    """Subfield coverage safety net (C-4): floor not set -> RedlineUnsigned (same discipline as the other thresholds, never a quiet default);
    set and coverage < floor -> HALT pointing at C-4 (topic_source downgrade). U1 measured subfield as present -> it will pass once the floor is set."""
    floor = require("resolve", "subfield_coverage_floor")  # null → RedlineUnsigned
    n = len(works)
    covered = sum(1 for w in works if w.get("subfield_id") is not None)
    coverage = covered / n if n else 1.0
    if coverage < floor:
        raise RuntimeError(
            f"[U2 G2] subfield coverage {coverage:.3f} < floor {floor} → HALT (C-4); topic_source=degraded"
        )
    return coverage


def _modal_subfield(work_rows):
    """The modal subfield of a set of works (mode; ties take the smallest subfield_id, same deterministic rule as S8-3); no signal -> None."""
    counts = Counter(w.get("subfield_id") for w in work_rows if w.get("subfield_id") is not None)
    if not counts:
        return None
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def quality_representative(recs, works_by_author, *, econ_subfields=None):
    """Per-cluster "quality representative id" diagnostic (root-cause B fix 1): among the members that are field-consistent AND name-compatible,
    take the one with the highest cited_by_count; no qualifying member -> None.

    Definition:
      - field-consistent = the member's modal subfield is economics (subfield_whitelist.include)
        **OR** agrees with the cluster's modal subfield (a member with zero field signal is not consistent, never faked);
      - name-compatible = names_compatible (U0 hard compatibility, no threshold) with **at least half of the
        other cluster members**; a majority anchor, not an all-members anchor, so that one dirty-name member cannot leave the whole cluster with "no representative";
      - ranking = sum of cited_by_count over the member's works, descending; a work missing the cited_by_count key counts as 0
        (affects only the diagnostic ranking, no production column); ties -> smallest author_id (deterministic).
      - a one-member cluster = the member itself (nothing to choose).
    Hard rule: pure diagnostic, zero side effects - does not touch person_id / min-id grouping / the 0.8 threshold / clustering logic
    (same discipline as flagA "detect only, never split automatically", Zenou-safe: the main id is field-consistent and most cited -> representative = main id).
    """
    if econ_subfields is None:
        econ_subfields = set(RED["subfield_whitelist"]["include"])
    members = sorted(recs, key=lambda r: r["author_id"])
    if len(members) == 1:
        return members[0]["author_id"]
    all_works = [w for r in members for w in works_by_author.get(r["author_id"], [])]
    cluster_modal = _modal_subfield(all_works)
    eligible = []
    for r in members:
        aid = r["author_id"]
        mworks = works_by_author.get(aid, [])
        mm = _modal_subfield(mworks)
        field_ok = mm is not None and (mm in econ_subfields or mm == cluster_modal)
        if not field_ok:
            continue
        others = [o for o in members if o["author_id"] != aid]
        n_compat = sum(
            1 for o in others
            if names_compatible(r.get("display_name"), o.get("display_name"))
        )
        if 2 * n_compat < len(others):        # name-compatible with at least half of the other members
            continue
        cites = sum((w.get("cited_by_count") or 0) for w in mworks)
        eligible.append((-cites, aid))
    if not eligible:
        return None
    return min(eligible)[1]


def compute_cluster_purity(person_map_rows, author_records, works):
    """One over-merge diagnostic row per person (CLUSTER_PURITY, 15 columns); reuses R3 run_overmerge_probe + U0 affil_conflict.

    Unsupervised (no ground truth): topic_homogeneity = share of the cluster's modal subfield; topic_completeness cannot test splitting for a single cluster,
    placeholder 1.0 (the real completeness needs ground truth, see exit gate G1). R3 established: many institutions != over-merge, and a topic outlier is ejected only on a strict majority.

    * Fix A (corroborated different-ORCID over-merge flag): on top of the existing overmerge_suspect, OR in
      orcid_overmerge_hit = distinct_orcid_hit AND (orcid_field_conflict_hit OR affil_conflict_hit).
      That is, "at least 2 different valid ORCIDs in a cluster" **must come with a field conflict OR an institution conflict** before the flag is raised (different ORCIDs alone never trigger it ->
      Zenou-safe by construction: both Zenou ORCIDs are economics and Monash, no corroboration -> no flag). Detect and send to the manual-review queue only,
      never splits automatically and never touches cluster_block clustering / the 0.8 threshold. distinct_orcid_hit is written as column 14, the raw signal (traceable).
    * Root-cause B fix 1 (14 -> 15 columns): quality_representative_author_id = the per-cluster quality representative id
      (quality_representative: among the field-consistent AND name-compatible members, the highest cited_by_count; none qualifies -> None).
      A pure diagnostic column; the other 14 columns are untouched; person_id/min-id/clustering are not touched.
    """
    rec_by_id = {r["author_id"]: r for r in author_records}
    # M2: every author_id in person_map must be in the authors table (same U1 source); otherwise U1/U2 are out of sync -> HALT (no silent downgrade)
    missing = {r["author_id"] for r in person_map_rows} - set(rec_by_id)
    if missing:
        raise RuntimeError(
            f"[U2 G2] person_map author_id not in the authors table (U1/U2 out of sync): {sorted(missing)[:5]} → HALT"
        )
    works_by_author = defaultdict(list)
    for w in works:
        works_by_author[w["author_id"]].append(w)
    members_by_person = defaultdict(list)
    for r in person_map_rows:
        members_by_person[r["person_id"]].append(r["author_id"])

    rows = []
    for person_id in sorted(members_by_person):
        aids = members_by_person[person_id]
        recs = [rec_by_id[a] for a in aids if a in rec_by_id]
        pworks = [w for a in aids for w in works_by_author.get(a, [])]
        probe = run_overmerge_probe(recs, pworks)
        affils = [r.get("raw_affil") for r in recs]
        affil_conflict_hit = any(
            affil_conflict(affils[i], affils[j])
            for i in range(len(affils))
            for j in range(i + 1, len(affils))
        )
        subfields = [w.get("subfield_id") for w in pworks if w.get("subfield_id") is not None]
        # In-place fix for review finding B2: when no cluster has any subfield signal, never fake homogeneity=1.0
        # to pass as clean (that would violate the principle set out in _assert_upstream_fields above,
        # "never compute a constant purity over an all-missing column and pretend it passed") -> None = cannot assess, and purity_flag is forced to low_confidence so the row enters the G3 manual-review queue.
        topic_homogeneity = (Counter(subfields).most_common(1)[0][1] / len(subfields)) if subfields else None
        # Fix A: different-ORCID corroboration flag = at least 2 different valid ORCIDs AND (field conflict OR institution conflict); the institution corroboration
        # uses this layer's affil_conflict_hit (the probe has no raw_affil). Different ORCIDs alone never trigger it (Zenou-safe).
        distinct_orcid_hit = probe["distinct_orcid_hit"]
        orcid_overmerge_hit = distinct_orcid_hit and (
            probe["orcid_field_conflict_hit"] or affil_conflict_hit
        )
        overmerge_suspect = probe["overmerge_suspect"] or affil_conflict_hit or orcid_overmerge_hit
        n_works = len(pworks)
        if overmerge_suspect:
            purity_flag = "suspected_overmerge"
        elif n_works == 0 or not subfields:
            purity_flag = "low_confidence"
        else:
            purity_flag = "clean"
        rows.append({
            "person_id": person_id,
            "n_works": n_works,
            "topic_homogeneity": topic_homogeneity,
            "topic_completeness": 1.0,   # A single cluster cannot be tested for splitting without supervision; the real completeness needs ground truth (G1)
            "n_name_variants": len({r.get("display_name") for r in recs}),
            "name_incompat_hit": probe["names_incompat_hit"],
            "dirty_orcid_hit": probe["dirty_orcid_hit"],
            "affil_conflict_hit": affil_conflict_hit,
            "topic_outlier_hit": probe["topic_outlier_hit"],
            "distinct_orcid_hit": distinct_orcid_hit,
            "overmerge_suspect": overmerge_suspect,
            "ejected_work_ids": probe["ejected_work_ids"],
            "purity_flag": purity_flag,
            "topic_source": "primary_topic" if subfields else "concepts_fallback",
            "quality_representative_author_id": quality_representative(recs, works_by_author),
        })
    return rows


def _writeback_person_map_purity(person_map_rows, purity_rows):
    """G2 writes the quality columns back to person_map exactly once (HIGH-3): topic_homogeneity -> cluster_homogeneity,
    topic_completeness -> completeness, purity_flag -> purity_flag. Writes a new copy atomically (no in-place edit, dict copy)."""
    purity_by_person = {p["person_id"]: p for p in purity_rows}
    out = []
    for r in person_map_rows:
        r = dict(r)
        p = purity_by_person.get(r["person_id"])
        if p is not None:
            r["cluster_homogeneity"] = p["topic_homogeneity"]
            r["completeness"] = p["topic_completeness"]
            r["purity_flag"] = p["purity_flag"]
        out.append(r)
    return out


# ===========================================================================
# G3 - manual-review queue (stars 100% + low purity + signal-less fragments) + candidate-superset guarantee
# ===========================================================================
def check_star_candidate_superset(candidate_star_author_ids, true_star_author_ids):
    """Candidate stars must be a superset of the true stars (checked once U4 produces the real star_set); returns the violation set (true stars not among the candidates); non-empty = WARN for U4 to review.

    Dependency direction fixed: the real star_set is produced by U4, after U2 -> U2 never depends on U4 output; at the U2 stage only the candidate superset is used.
    """
    return set(true_star_author_ids) - set(candidate_star_author_ids)


def _no_signal_fragments(person_map_rows, works, edges):
    """Signal-less fragment: no work and no coauthor edge (it can be neither merged nor split safely -> must go to manual review, #11-c all small departments)."""
    has_work = {w["author_id"] for w in works}
    has_edge = {e["author_id"] for e in edges}
    return {
        r["author_id"]
        for r in person_map_rows
        if r["author_id"] not in has_work and r["author_id"] not in has_edge
    }


def build_adjudication_queue(person_map_rows, purity_rows, candidate_star_author_ids, edges, no_signal_ids):
    """Manual-review queue = stars + direct coauthors 100% ∪ purity∈{suspected_overmerge,low_confidence} ∪ signal-less fragments.

    Empty candidates -> only low-purity and signal-less rows enter (an empty run does not error). canonical-sort by (reason, author_id).
    """
    purity_flag_by_person = {p["person_id"]: p["purity_flag"] for p in purity_rows}
    rows = []
    for r in person_map_rows:
        aid, pid = r["author_id"], r["person_id"]
        if _is_star_or_direct_collaborator(aid, candidate_star_author_ids, edges):
            reason = "star_or_collaborator_100pct"
        elif purity_flag_by_person.get(pid) in {"suspected_overmerge", "low_confidence"}:
            reason = "low_purity"
        elif aid in no_signal_ids:
            reason = "no_signal_fragment"
        else:
            continue
        rows.append({"author_id": aid, "person_id": pid, "reason": reason})
    return sorted(rows, key=lambda r: (r["reason"], r["author_id"]))


# ===========================================================================
# G4 - exit orchestration + Zenou two-way golden-standard e2e + independent count (#11-b) + idempotence
# ===========================================================================
def run_zenou_golden_check(frame):
    """Zenou golden standard: if all classify_golden structural anchors pass, return the verdict; any failure -> sys.exit(GOLDEN_FAIL=18).

    Anchors = findable / a single person / star / Monash (not Stockholm-Sydney) / ARMI->Monash / Caulfield->None /
    reject the 1998 backfill / never read affiliations.years (redline #3) / arrival is not 1998 / never take the largest cluster. A missed person or a false event must never recur.
    """
    from identity.golden import classify_golden
    from identity.exit_codes import GOLDEN_FAIL

    result = classify_golden(frame)
    if not result["structural_pass"]:
        sys.stderr.write(f"[U2 G4] Yves Zenou golden structural anchor flipped flips={result['flips']} → GOLDEN_FAIL\n")
        sys.exit(GOLDEN_FAIL)
    if not result["observed_in_range"]:
        # H1/#11-b: the works_count in [550,620] + arrival in [2015,2017] range checks are wired into the golden standard (not only the structural anchors)
        sys.stderr.write(
            f"[U2 G4] Yves Zenou out of range works={result['works_count_observed']} "
            f"arrival={result['arrival_year_observed']} → GOLDEN_FAIL (#11-b)\n"
        )
        sys.exit(GOLDEN_FAIL)
    return result


def assert_zenou_works_count(n_works, bounds=(550, 620)):
    """#11-b independent person-level count assertion (separate from the pairwise gate): works_count in [lo,hi], otherwise HALT."""
    lo, hi = bounds
    if not (lo <= n_works <= hi):
        raise RuntimeError(f"[U2 G4] Yves Zenou works_count {n_works} ∉ [{lo},{hi}] → HALT (#11-b independent count)")
    return n_works


def run_m2_exit_gate(
    person_map_rows,
    author_records,
    works,
    gt_labels,
    golden_frame,
    *,
    candidate_star_author_ids=frozenset(),
    edges=(),
    is_large_dept,
    evidence_path,
):
    """G4 exit orchestration: upstream -> cluster_purity -> write back -> exit gate (HALT short-circuits) -> manual-review queue -> Zenou golden standard.

    Threshold not set -> run_exit_gate raises RedlineUnsigned (short-circuit, nothing after it runs); golden standard fails -> GOLDEN_FAIL.
    Deterministic: same input -> same output + same evidence sha. Returns {metrics, purity, person_map, queue, golden}.
    Note: this orchestration runs on in-memory data; the real-data version (read person_map.parquet + build the frame from the Zenou vertical slice) is a real-data integration,
        waiting for the full U1 three tables to ship (data BLOCKER).
    """
    _assert_upstream_fields(author_records, works)
    purity = compute_cluster_purity(person_map_rows, author_records, works)
    person_map_final = _writeback_person_map_purity(person_map_rows, purity)
    pred_labels = {r["author_id"]: r["person_id"] for r in person_map_rows}
    metrics = run_exit_gate(pred_labels, gt_labels, is_large_dept=is_large_dept, evidence_path=evidence_path)
    no_signal = _no_signal_fragments(person_map_rows, works, list(edges))
    queue = build_adjudication_queue(person_map_final, purity, set(candidate_star_author_ids), list(edges), no_signal)
    golden = run_zenou_golden_check(golden_frame)
    return {"metrics": metrics, "purity": purity, "person_map": person_map_final, "queue": queue, "golden": golden}
