"""U2 entity resolution / disambiguation - the only producer of person_map (R1-R5).

Only orchestrates calls into U0/U1 and never rewrites U0 algorithms. Every identification threshold is null -> RedlineUnsigned (a value must be set by hand).
For conventions see ../../CONTRACT.md + ../../README.md.
"""
import csv
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from common.entity_resolve import (
    affil_conflict,
    cluster_block,
    names_compatible,
    pair_score,
    require_score_threshold,
    _find,
    _union,
    _valid_orcid,
)
from identity.exit_codes import EXIT_INPUT_NOT_CANONICAL


def _strip_accents(text):
    """Accent folding: NFKD decomposition, then drop the combining marks (é->e), so "Zénou" and "Zenou" get the same name_key."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def _name_key(display_name):
    """U2's private blocking key = (capitalised first initial, lower-case accent-folded surname).

    U0 name_key is a phantom in the spec (PHANTOM); U2 builds its own coarse bucketing key (S2AND convention: first-initial + surname).
    """
    folded = _strip_accents(display_name).strip()
    tokens = folded.split()
    if not tokens:
        return ("", "")
    initial = tokens[0][:1].upper()
    surname = tokens[-1].lower()
    return (initial, surname)


def build_blocks(author_records):
    """Coarsely bucket author records by name_key -> dict[(initial, surname), list[record]].

    blocking = first split coarsely by "surname + first initial" and compare pairs only inside a bucket, avoiding an N² comparison over the whole library.
    """
    blocks = defaultdict(list)
    for rec in author_records:
        blocks[_name_key(rec["display_name"])].append(rec)
    return dict(blocks)


def _assert_author_id_canonical_space(records, cmap_rows):
    """Entry guard: assert that every author_id is already U1-canonical (not a redirect source).

    canonical_id_map rows {raw_id, canonical_id, ...}: raw != canonical = a redirect source (not normalised).
    If an author_id hits the redirect-source set, upstream did not fold cleanly -> exit(EXIT_INPUT_NOT_CANONICAL); never
    accept it silently (otherwise the same person with raw≠canonical would be silently lost). Reads only the two columns {raw_id, canonical_id}.

    Note: the real U1 canonical_id_map stores only the redirect rows of merged ids (canonicalize returns an id absent
    from the table unchanged); so "reflexive rows raw==canonical" are ignored here and not treated as redirects, and are not fed to replay_merged_ids
    (a reflexive row would form a self-loop and raise).
    """
    redirects = {
        row["raw_id"] for row in cmap_rows if row["raw_id"] != row["canonical_id"]
    }
    bad = sorted({r["author_id"] for r in records if r["author_id"] in redirects})
    if bad:
        sys.stderr.write(
            f"[U2] author_id still has unresolved redirects (upstream not fully folded): {bad} "
            f"→ HALT EXIT_INPUT_NOT_CANONICAL\n"
        )
        sys.exit(EXIT_INPUT_NOT_CANONICAL)


def resolve_block_partition(records):
    """Cluster inside a block -> {author_id: person_id}; person_id = 'P_' + smallest author_id in the cluster.

    Calls U0 cluster_block (internally union-find + ORCID hard seed + order-independent, returns the bare min author_id);
    U2 only adds the 'P_' prefix to make a person-level entity id. No extra sorting beforehand (cluster_block is already order-independent; more sorting would be YAGNI);
    the threshold redline takes effect only in R4 accept_pair; R1 clusters on hard predicates alone and never touches score_threshold.
    """
    labels = cluster_block(records)  # {author_id: smallest author_id in the cluster (bare value)}
    return {aid: f"P_{root}" for aid, root in labels.items()}


def _read_u1_table(data_root, table, columns, *, required=True):
    """Read the given columns of a U1 derived table <data_root>/derived/u1_edges/<table>/ -> list[dict].

    Read through common.derived_table (the single source of truth for the seam): a single-file data.parquet (slice/sample/fixture) or
    bucketed bucket=*/part-* (full U1 stream_build output) are handled transparently; data_SAMPLE.parquet is never read.
    required=True and the table missing -> FileNotFoundError pointing at "U1 full run not shipped"; required=False and missing -> [] (optional table).
    """
    from common.derived_table import read_derived_table, derived_table_present

    table_dir = Path(data_root) / "derived" / "u1_edges" / table
    if not derived_table_present(table_dir):
        if required:
            raise FileNotFoundError(
                f"U1 derived table missing: {table_dir} (neither a single-file data.parquet nor bucketed bucket=*/part-* exists) "
                f"— U1 full run not shipped? (does not block fixture TDD; blocks the real-data smoke test)"
            )
        return []
    return read_derived_table(table_dir, columns)


def load_u1(data_root):
    """Read the U1 derived tables.

    Returns (author_records, cmap_rows, edges, works_affil):
      - author_records: [{author_id, display_name, orcid}, ...]  (for blocking + cluster_block)
      - cmap_rows:       [{raw_id, canonical_id}, ...]            (canonical entry assertion, reads two columns only)
      - edges:           [{work_id, author_id}, ...]             (one-hop direct coauthors of stars; optional, [] if missing)
      - works_affil:     [{author_id, raw_affiliation_strings}, ...]  (the institution defence: same name, different institution is not merged;
                          B1 fix, wired into cluster_block's affil_conflict; optional, [] if missing)
    """
    authors = _read_u1_table(data_root, "authors", ["author_id", "display_name", "orcid"])
    cmap_rows = _read_u1_table(data_root, "canonical_id_map", ["raw_id", "canonical_id"])
    edges = _read_u1_table(data_root, "authorship_edges", ["work_id", "author_id"], required=False)
    works_affil = _read_u1_table(
        data_root, "works_affil", ["author_id", "raw_affiliation_strings"], required=False
    )
    return authors, cmap_rows, edges, works_affil


def tag_orcid_merges(person_of, records):
    """After-the-fact attribution merge_reason=orcid_prior: if >=2 members of one person cluster share the same valid ORCID -> mark orcid_prior.

    cluster_block already has the ORCID hard seed built in (empty/None never seeds, #11-a); this function only reads the result for attribution and never re-merges.
    Uses U0 _valid_orcid to decide "valid orcid", the same definition as cluster_block's seed (single source of truth).
    Returns a subset {author_id: 'orcid_prior'}; the other merge_reason values are filled in by the caller.
    """
    by_person = defaultdict(list)
    for r in records:
        by_person[person_of[r["author_id"]]].append(r)
    tagged = {}
    for members in by_person.values():
        by_orcid = defaultdict(list)
        for r in members:
            oc = _valid_orcid(r.get("orcid"))
            if oc is not None:
                by_orcid[oc].append(r["author_id"])
        for aids in by_orcid.values():
            if len(aids) >= 2:               # >=2 members of a cluster share a valid ORCID = a merge driven by ORCID
                for aid in aids:
                    tagged[aid] = "orcid_prior"
    return tagged


def collect_orcid_conflicts(records):
    """Dirty-ORCID set: the same valid ORCID attached to incompatible names (U0 orcid_name_conflicts does not exist, U2 implements its own).

    Method: group by valid orcid; if any two names within one orcid are not names_compatible -> that orcid is dirty.
    A dirty orcid = the code cannot be trusted (one code, several people); it goes to review_queue for manual review; ORCID is never trusted blindly (redline #11).
    """
    by_orcid = defaultdict(list)
    for r in records:
        oc = _valid_orcid(r.get("orcid"))
        if oc is not None:
            by_orcid[oc].append(r)
    dirty = set()
    for oc, recs in by_orcid.items():
        names = [x.get("display_name") for x in recs]
        if any(
            not names_compatible(names[i], names[j])
            for i in range(len(names))
            for j in range(i + 1, len(names))
        ):
            dirty.add(oc)
    return dirty


def _raw_affil_text_authors(person_of, records, edges):
    """raw_affil_text: in a non-orcid multi-member cluster, every member has a raw_affil and no two share a coauthor
    (= merged back by institution text / name, not by the collaboration network; the crux of the 13 single-paper Zenou fragments = one paper, no collaborators, merged by raw_affil).
    Returns the set of these author_ids (reachable only once the raw_affil signal is in place after B1).
    """
    rec_by_id = {r["author_id"]: r for r in records}
    authors_by_work = defaultdict(set)
    for e in edges:
        authors_by_work[e["work_id"]].add(e["author_id"])
    coauthors = defaultdict(set)
    for work_authors in authors_by_work.values():
        for a in work_authors:
            coauthors[a].update(work_authors - {a})
    members_by_person = defaultdict(list)
    for aid, pid in person_of.items():
        members_by_person[pid].append(aid)
    out = set()
    for aids in members_by_person.values():
        if len(aids) < 2:
            continue
        if not all(rec_by_id.get(a, {}).get("raw_affil") for a in aids):
            continue
        no_shared_coauthor = all(
            not (coauthors[aids[i]] & coauthors[aids[j]])
            for i in range(len(aids))
            for j in range(i + 1, len(aids))
        )
        if no_shared_coauthor:
            out.update(aids)
    return out


def _write_review_queue(path, rows):
    """Write review_queue.csv (dirty ORCIDs awaiting manual review); fixed column order + always written (even with 0 rows, so downstream does not crash on a missing file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["author_id", "orcid", "reason"])
        w.writeheader()
        for r in rows:
            w.writerow(r)


def run_resolve(data_root, out_dir, *, candidate_star_author_ids=frozenset(),
                scale_bounds=None):
    """Read U1 -> canonical guard -> cluster -> ORCID three states -> manual-review override -> write person_map + 3 queues.

    person_map has 7 columns: merge_reason ∈ {orcid_prior, golden_manual, raw_affil_text, block_cluster}; the three quality columns
    are None placeholders for G2 to write back. The manual-review override (golden_manual_overrides.csv, source=human) overrides person_id before the freeze.
    Stars (candidate_star_author_ids) + direct coauthors without an override -> manual_required_queue.csv (the orchestration does not let them through).
    Dirty ORCID -> review_queue.csv. Writes <out_dir>/{person_map/data.parquet, manual_required_queue.csv, review_queue.csv}.

    scale_bounds (the real-data scale smoke gate for U2):
      A production run must pass {table name: (lo, hi)} expected ranges - the gate runs BEFORE the full U1 tables are read (it stops
      quadratic-stall / ledger-memory incidents before the run starts); on failure -> SystemExit(SCALE_GATE_FAIL=31), and person_map is not written at all
      (the gate's own audit record preflight_scale_result.json is always written, preflight pattern).
      Not passed (None) -> the gate is skipped (the existing fixture/TDD path, behaviour unchanged).
    """
    from common.schema import PERSON_MAP
    from m1_ingest._writer_util import write_rows_parquet

    # ---- scale smoke gate: runs before load_u1 reads everything ----
    if scale_bounds is not None:
        from m2_resolve.scale_gate import preflight_u2_scale_check

        _rc = preflight_u2_scale_check(
            data_root, bounds=scale_bounds,
            result_path=Path(out_dir) / "preflight_scale_result.json",
        )
        if _rc != 0:
            raise SystemExit(_rc)

    authors, cmap_rows, edges, works_affil = load_u1(data_root)
    _assert_author_id_canonical_space(authors, cmap_rows)  # leftover redirect -> exit(EXIT_INPUT_NOT_CANONICAL)

    # B1: the raw_affiliation_strings of works_affil are aggregated per author and attached to the record -> the
    #     affil_conflict of cluster_block really takes effect (same name, different institution is not merged; the crux for merging the 13 Zenou fragments back by raw_affil text).
    affil_by_author = defaultdict(list)
    for wa in works_affil:
        affil_by_author[wa["author_id"]].extend(wa.get("raw_affiliation_strings") or [])
    enriched = [{**a, "raw_affil": (affil_by_author.get(a["author_id"]) or None)} for a in authors]

    person_of = {}
    for _key, recs in build_blocks(enriched).items():
        person_of.update(resolve_block_partition(recs))
    orcid_tags = tag_orcid_merges(person_of, enriched)  # >=2 sharing a valid ORCID in a cluster -> orcid_prior
    affil_text = _raw_affil_text_authors(person_of, enriched, edges)  # merged back by institution text, no collaboration -> raw_affil_text

    rows = [
        {
            "author_id": a["author_id"],
            "person_id": person_of[a["author_id"]],
            "merge_reason": (
                "orcid_prior" if a["author_id"] in orcid_tags
                else "raw_affil_text" if a["author_id"] in affil_text
                else "block_cluster"
            ),
            "cluster_homogeneity": None,       # placeholder -> written back exactly once by G2
            "completeness": None,              # placeholder -> written back by G2
            "purity_flag": None,               # placeholder -> written back by G2
            "had_orcid": bool(a.get("orcid")),
        }
        for a in enriched
    ]
    # manual-review override (source=human): overrides person_id + sets golden_manual (final truth, applied before the freeze)
    overrides_csv = Path(__file__).parent / "manual_review" / "golden_manual_overrides.csv"
    rows, overridden = apply_manual_review_overrides(rows, overrides_csv)

    target = Path(out_dir) / "person_map" / "data.parquet"
    write_rows_parquet(rows, target, schema=PERSON_MAP, pk_cols=["author_id"], label="person_map")

    # stars + direct coauthors: 100% manual-review queue (no override -> enters the queue, the orchestration does not let them through)
    queue = build_manual_required_queue(rows, set(candidate_star_author_ids), edges, overridden)
    _write_manual_required_queue(Path(out_dir) / "manual_required_queue.csv", queue)

    # dirty ORCID (one code attached to incompatible names) -> review_queue.csv for manual review (ORCID is not trusted blindly, redline #11)
    dirty = collect_orcid_conflicts(enriched)
    review_rows = sorted(
        (
            {"author_id": a["author_id"], "orcid": _valid_orcid(a.get("orcid")),
             "reason": "dirty_orcid_name_conflict"}
            for a in enriched
            if _valid_orcid(a.get("orcid")) in dirty
        ),
        key=lambda r: r["author_id"],
    )
    _write_review_queue(Path(out_dir) / "review_queue.csv", review_rows)
    return target


def _orcid_field_conflict(records, works):
    """Corroboration signal (fix A): group the cluster's works' subfields by ORCID; if the subfield sets of any two different ORCIDs
    are **completely disjoint** (and each non-empty) -> field conflict True.

    The crux is that the conflict is **tied to an ORCID split** (not a cluster-level "spans two fields"), hence Zenou-safe: if the papers of two ORCIDs
    all touch the same subfield (economics) -> the sets intersect -> no conflict -> no flag. Only a true wrong merge, such as ORCID-A all economics and ORCID-B all pulmonology,
    counts as a conflict. ORCID groups with no subfield do not take part (conservative, fewer false positives). A missing orcid/
    subfield in records/works is always handled with .get.
    """
    orcid_of = {r["author_id"]: _valid_orcid(r.get("orcid")) for r in records}
    subfields_by_orcid = defaultdict(set)
    for w in works:
        oc = orcid_of.get(w.get("author_id"))
        sf = w.get("subfield_id")
        if oc is not None and sf is not None:
            subfields_by_orcid[oc].add(sf)
    orcids = sorted(oc for oc, sfs in subfields_by_orcid.items() if sfs)
    return any(
        subfields_by_orcid[orcids[i]].isdisjoint(subfields_by_orcid[orcids[j]])
        for i in range(len(orcids))
        for j in range(i + 1, len(orcids))
    )


def run_overmerge_probe(records, works):
    """In-cluster over-merge probe (no ground truth; uses internal-consistency signals; #11, the main guard against wrong merges).

    U0 has no overmerge_probe -> U2 assembles it from existing U0 pieces. Checks:
      ① names_incompat: any two names in the cluster are not names_compatible (U0).
      ③ topic_outlier: when the cluster's works have a **strict majority** modal subfield, a work with a different subfield is an outlier -> ejected
         (no strict majority = topic is ambiguous, no automatic ejection, fewer false positives; protects interdisciplinary authors; audit MEDIUM-C4).
      ④ multi_inst: distinct institution_id >= 2 (* weak signal, never decides over-merge alone; institution = weak feature, redline #11).
         Note: currently uses distinct institution_id; the U0 fold_to_canonical parent-institution folding will be wired in once the INSTITUTIONS registry is loaded.
      ⑤ dirty_orcid: collect_orcid_conflicts(records) hit (one code, several people).
      ⑥ distinct_orcid / orcid_field_conflict (* raw signals of fix A): distinct_orcid_hit = the cluster has
         >=2 different valid ORCIDs; orcid_field_conflict_hit = the subfield sets grouped by ORCID are pairwise disjoint.
         These **two are only raw signals and are never folded into this function's overmerge_suspect** - the corroborating combination
         (distinct AND (field OR institution)) is assembled by gate.compute_cluster_purity (the institution corroboration affil_conflict
         has raw_affil only at that layer). Zenou-safe by construction: different ORCIDs alone never trigger it; they need field/institution corroboration.
    overmerge_suspect = names_incompat ∨ dirty_orcid ∨ (some ejected outlier work). **multi_inst / different ORCIDs
    alone do not trigger it** (redline). R3 only computes and returns in memory; it does not write to disk or write back to person_map (HIGH-3: the person_map quality columns are written back by G2).
    """
    names = [r.get("display_name") for r in records]
    names_incompat_hit = any(
        not names_compatible(names[i], names[j])
        for i in range(len(names))
        for j in range(i + 1, len(names))
    )
    dirty_orcid_hit = bool(collect_orcid_conflicts(records))

    # topic outlier: eject the odd one out only when a strict-majority modal subfield exists (no majority -> no ejection, fewer false positives)
    ejected = []
    topic_outlier_hit = False
    counts = Counter(w.get("subfield_id") for w in works if w.get("subfield_id") is not None)
    if counts:
        modal, modal_n = counts.most_common(1)[0]
        if modal_n > len(works) / 2:                     # strict majority
            ejected = sorted(
                w["work_id"]
                for w in works
                if w.get("subfield_id") is not None and w.get("subfield_id") != modal
            )
            topic_outlier_hit = bool(ejected)

    distinct_inst = {w.get("institution_id") for w in works if w.get("institution_id")}
    multi_inst_hit = len(distinct_inst) >= 2

    # raw signals of fix A (not folded into overmerge_suspect; gate assembles the corroboration)
    distinct_orcids = {_valid_orcid(r.get("orcid")) for r in records}
    distinct_orcids.discard(None)
    distinct_orcid_hit = len(distinct_orcids) >= 2
    orcid_field_conflict_hit = distinct_orcid_hit and _orcid_field_conflict(records, works)

    overmerge_suspect = names_incompat_hit or dirty_orcid_hit or bool(ejected)
    return {
        "names_incompat_hit": names_incompat_hit,
        "dirty_orcid_hit": dirty_orcid_hit,
        "topic_outlier_hit": topic_outlier_hit,
        "multi_inst_hit": multi_inst_hit,
        "distinct_orcid_hit": distinct_orcid_hit,
        "orcid_field_conflict_hit": orcid_field_conflict_hit,
        "ejected_work_ids": ejected,
        "overmerge_suspect": overmerge_suspect,
    }


def calibrate_thresholds(authors, grid, *, expected_clusters=None, signals_available=None):
    """Threshold calibration (RL1): sweep a threshold grid and report the cluster count per t + feasible_band for a person to choose the value from; never fills a value itself and never writes RED.

    grid=None -> production mode: read the score_threshold set in RED (null -> RedlineUnsigned, raised here, no pass-through).
    grid=[...] -> calibration mode: each t is swept as an explicit parameter (reusing U0 pair_score/affil_conflict scoring + _find/_union,
                the scoring algorithm is not rewritten). The report has source=external + must_author_sign=true; feasible_band is only
                a reference for the person who sets the value and never feeds back into redlines.yaml (ground truth never feeds back into the rules).
    Plainly: fitting thresholds to a synthetic fixture is circular (it shows mechanism behaviour only, not calibration against real ground truth); fitting to the real Zenou
          works_count in [550,620] is meaningful only on real data (full U1); the threshold values are always set by a person, never by the code.
    """
    if grid is None:
        require_score_threshold()  # production reads the value set in RED; null -> RedlineUnsigned (never a quiet default)
        raise NotImplementedError("calibrate_thresholds is calibration mode only; production clustering goes through run_resolve")

    ids = sorted(r["author_id"] for r in authors)
    by_id = {r["author_id"]: r for r in authors}
    grid_results = []
    for t in grid:
        parent = {aid: aid for aid in ids}
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = by_id[ids[i]], by_id[ids[j]]
                s = pair_score(a, b)
                if s is None or s < t:                 # names incompatible, or score < threshold -> no edge
                    continue
                if affil_conflict(a.get("raw_affil"), b.get("raw_affil")):
                    continue
                _union(parent, ids[i], ids[j])
        n_clusters = len({_find(parent, aid) for aid in ids})
        grid_results.append({"threshold": t, "n_clusters": n_clusters})

    feasible_band = (
        [r["threshold"] for r in grid_results if r["n_clusters"] == expected_clusters]
        if expected_clusters is not None
        else []
    )
    return {
        "grid_results": grid_results,
        "feasible_band": feasible_band,
        "signal_availability": signals_available
        or {"coauthor": "degraded", "raw_affil": "degraded", "title": "degraded", "subfield": "degraded"},
        "observed_signal_contribution": {},  # filled in by real-data calibration; the synthetic fixture only proves the mechanism
        "source": "external",
        "must_author_sign": True,
    }


# ===========================================================================
# R5 - traceable merge_reason + manual-review override + stars 100% manual review
# ===========================================================================
_MERGE_REASON_PRIORITY = ("orcid_prior", "golden_manual", "raw_affil_text", "block_cluster")


def assign_merge_reason(present_reasons):
    """From the signals present, take the highest-priority merge_reason (orcid_prior > golden_manual > raw_affil_text > block_cluster)."""
    for reason in _MERGE_REASON_PRIORITY:
        if reason in present_reasons:
            return reason
    return "block_cluster"


def apply_manual_review_overrides(person_map_rows, overrides_csv_path):
    """Read golden_manual_overrides.csv (source=human) -> override person_id for the matching author_id + set golden_manual.

    Returns (updated rows, set(overridden author_id)). CSV missing/empty -> returned unchanged. Manual review = the human-anchored final truth;
    other columns and rows without an override are untouched (the 7 PERSON_MAP keys are unchanged, the schema is not broken).
    """
    overrides = {}
    p = Path(overrides_csv_path)
    if p.exists():
        with open(p, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                aid = (row.get("author_id") or "").strip()
                pid = (row.get("person_id") or "").strip()
                if aid and pid:
                    overrides[aid] = pid
    overridden = set()
    out = []
    for r in person_map_rows:
        r = dict(r)
        if r["author_id"] in overrides:
            r["person_id"] = overrides[r["author_id"]]
            r["merge_reason"] = "golden_manual"
            overridden.add(r["author_id"])
        out.append(r)
    return out, overridden


def _is_star_or_direct_collaborator(author_id, candidate_star_author_ids, edges):
    """author_id is a candidate star, or collaborates with some candidate star one hop away on authorship_edges (co-occurs on the same work).

    Candidate stars = the entry parameter candidate_star_author_ids (a superset; the real star_set is produced by U4, after U2).
    """
    if author_id in candidate_star_author_ids:
        return True
    star_works = {e["work_id"] for e in edges if e["author_id"] in candidate_star_author_ids}
    return any(e["work_id"] in star_works and e["author_id"] == author_id for e in edges)


def build_manual_required_queue(person_map_rows, candidate_star_author_ids, edges, overridden_ids):
    """Stars + direct coauthors: 100% manual-review queue; rows without a golden_manual override -> enter the queue (the orchestration does not let them through).

    Empty candidates -> empty queue (an empty run does not error); rows already overridden do not enter again. canonical-sort by author_id.
    """
    # Performance fix (semantically equivalent): the old version called _is_star_or_direct_collaborator per row, and each call scanned edges twice in full
    #   -> 160k rows × 14M edges = a quadratic stall (a real-data run was still under 1% after 3.4 h; fixtures were too small to show it).
    #   Now: build star_works -> collaborators sets in one pass over the whole library, so the per-row test is O(1). The predicate function is kept for tests / single-point calls.
    star_works = {e["work_id"] for e in edges if e["author_id"] in candidate_star_author_ids}
    collaborators = {e["author_id"] for e in edges if e["work_id"] in star_works}
    in_queue = set(candidate_star_author_ids) | collaborators
    rows = [
        {"author_id": r["author_id"], "person_id": r["person_id"], "reason": "star_or_collaborator_100pct"}
        for r in person_map_rows
        if r["author_id"] not in overridden_ids and r["author_id"] in in_queue
    ]
    return sorted(rows, key=lambda r: r["author_id"])


def _write_manual_required_queue(path, rows):
    """Write manual_required_queue.csv (stars awaiting 100% manual review); fixed column order + always written (even with 0 rows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["author_id", "person_id", "reason"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
