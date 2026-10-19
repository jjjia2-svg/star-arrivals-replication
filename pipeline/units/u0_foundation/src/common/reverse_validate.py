"""U0 foundation · reverse_validate — reverse-validation evaluation (B³-F1 / Pairwise-F1 / faceting).

In plain words: compare the entity-resolution result with an externally scraped ground-truth roster, compute
recall, precision and cluster quality, and refuse to proceed if a floor is not met. The whole file lands in U0;
all six identification-caliber thresholds are placeholders set to None.

The caliber-neutral "evaluation algorithm" part (B³/pairwise/faceting) is pure statistics and caliber-free;
the "pass/fail" thresholds (six floors) are identification red lines, all read from redlines.reverse_validate,
with zero hardcoding in the module.

Hard rules:
  1. The six thresholds (recall_large_dept / recall_small_dept / precision_min / completeness_min /
     homogeneity_min / faceting_recall_min) are all placeholder null; require() raises
     RedlineUnsigned on None and never defaults silently. The identification caliber is set in the
     red-line ledger, never by the code itself.
  2. Ground truth is externally scraped and used only as a comparison fixture; it is never fed back into
     redlines.yaml (no self-filled thresholds).
  3. The thin shells (validate_resolution / m2_exit_gate) = pure judgement -> atomic evidence write -> raise
     ResolveGateFail; the exit code matches exit_codes.RESOLVE_GATE_FAIL (=12) (downstream asserts the
     exception type + .exit_code, never a bare number).
  4. A missing rapidfuzz does not degrade (the environment gate is guarded by preflight; this file's
     evaluation logic never falls back silently).

faceting_recall: recall is computed per works_bucket x year facet and the worst facet is reported (the gate
looks at the min), preventing the false green of "overall recall looks good while one small facet actually
misses a whole block".
"""
from __future__ import annotations

import itertools
import json
from collections import defaultdict
from typing import Any, Hashable, Iterable, Mapping, Sequence

from common._redlines import RED, require  # Single entry point for thresholds (the identification caliber is read from here)
from common.atomic_io import atomic_write_bytes  # G7 atomic write (evidence to disk)
from identity import exit_codes


class ResolveGateFail(Exception):
    """The U2 disambiguation gate failed -> HALT. Carries the exit code (matches exit_codes.RESOLVE_GATE_FAIL=12).

    Downstream asserts "exception type + .exit_code distinguishability" and never a bare number.
    """

    exit_code = exit_codes.RESOLVE_GATE_FAIL


# ===========================================================================
# Internal helper: turn {entity: cluster_label} into a set of "same-cluster pairs" (the pairwise primitive)
# ===========================================================================
def _same_cluster_pairs(labels: Mapping[Hashable, Hashable]) -> set[frozenset]:
    """Return the set of all unordered pairs that are "same cluster and different elements".

    labels: {entity_id: cluster_label}. A pair (i, j) is in the same cluster iff label[i] == label[j].
    Uses frozenset({i, j}) as the unordered pair; i==j does not count (no self-pairs).
    """
    by_cluster: dict[Hashable, list[Hashable]] = defaultdict(list)
    for ent, lab in labels.items():
        by_cluster[lab].append(ent)
    pairs: set[frozenset] = set()
    for members in by_cluster.values():
        for i, j in itertools.combinations(members, 2):
            pairs.add(frozenset((i, j)))
    return pairs


# ===========================================================================
# pairwise_f1 — pairwise P/R/F1
# ===========================================================================
def pairwise_f1(
    predicted_labels: Mapping[Hashable, Hashable],
    true_labels: Mapping[Hashable, Hashable],
) -> dict:
    """Pairwise precision/recall/F1.

    precision = |predicted same-cluster pairs ∩ true same-cluster pairs| / |predicted same-cluster pairs|
    recall    = |predicted same-cluster pairs ∩ true same-cluster pairs| / |true same-cluster pairs|
    Convention: when the denominator is 0 the metric = 1.0 (no predicted positive pairs -> no false positives;
    no true positive pairs -> nothing to miss).
    """
    pred_pairs = _same_cluster_pairs(predicted_labels)
    true_pairs = _same_cluster_pairs(true_labels)
    correct = pred_pairs & true_pairs

    precision = len(correct) / len(pred_pairs) if pred_pairs else 1.0
    recall = len(correct) / len(true_pairs) if true_pairs else 1.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return {
        "pairwise_precision": precision,
        "pairwise_recall": recall,
        "pairwise_f1": f1,
    }


# ===========================================================================
# bcubed_f1 — B³ P/R/F1 (the S2AND/WhoIsWho standard)
# ===========================================================================
def bcubed_f1(
    predicted_labels: Mapping[Hashable, Hashable],
    true_labels: Mapping[Hashable, Hashable],
) -> dict:
    """B-cubed precision/recall/F1 (element-level average).

    For each element e (present in both pred and true):
      correctness(e, e') = 1 when e,e' are in the same cluster in pred and in the same cluster in true.
      precision(e) = #{e': same cluster in pred and in true} / #{e': same cluster in pred}   (includes e itself)
      recall(e)    = #{e': same cluster in pred and in true} / #{e': same cluster in true}   (includes e itself)
    B³P = mean_e precision(e); B³R = mean_e recall(e).
    Computed only over elements labelled on both sides (the evaluation domain is the intersection).
    """
    common_ents = [e for e in predicted_labels if e in true_labels]

    pred_by_cluster: dict[Hashable, set] = defaultdict(set)
    true_by_cluster: dict[Hashable, set] = defaultdict(set)
    for e in common_ents:
        pred_by_cluster[predicted_labels[e]].add(e)
        true_by_cluster[true_labels[e]].add(e)

    if not common_ents:
        # No element to evaluate -> by convention a perfect score (no evidence against); consistent with the perfect degenerate case.
        return {"bcubed_precision": 1.0, "bcubed_recall": 1.0, "bcubed_f1": 1.0}

    p_sum = 0.0
    r_sum = 0.0
    for e in common_ents:
        pred_cluster = pred_by_cluster[predicted_labels[e]]
        true_cluster = true_by_cluster[true_labels[e]]
        both = pred_cluster & true_cluster  # Same cluster in pred and in true (includes e)
        p_sum += len(both) / len(pred_cluster)
        r_sum += len(both) / len(true_cluster)

    n = len(common_ents)
    precision = p_sum / n
    recall = r_sum / n
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return {
        "bcubed_precision": precision,
        "bcubed_recall": recall,
        "bcubed_f1": f1,
    }


# ===========================================================================
# compute_recall_precision — the five pairwise keys (con is a placeholder; predictions/truth are read from on-disk fixtures)
# ===========================================================================
def _load_labels_jsonl(path: str) -> dict[Hashable, Hashable]:
    """Read JSONL (one {id, cluster} per line) -> {id: cluster}.

    The ground truth is an externally scraped roster on disk; it is only read, never written back (isolation rule).
    """
    labels: dict[Hashable, Hashable] = {}
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            labels[rec["id"]] = rec["cluster"]
    return labels


def compute_recall_precision(con, predicted_path: str, ground_truth_path: str) -> dict:
    """Pairwise recall/precision + three pair counts (n_pairs_gt / n_pairs_pred / n_pairs_correct).

    Arguments:
      con: DuckDB connection placeholder (this minimal implementation reads JSONL directly; with real m0 data
           it will query parquet through con, and the signature stays fixed so downstream call sites do not change).
      predicted_path / ground_truth_path: paths of the {id, cluster} JSONL fixtures.
    Returns: {recall, precision, n_pairs_gt, n_pairs_pred, n_pairs_correct}.
    Hard rule: the ground truth is read only as the comparison baseline and never fed back into rules or thresholds.
    """
    pred_labels = _load_labels_jsonl(predicted_path)
    gt_labels = _load_labels_jsonl(ground_truth_path)

    pred_pairs = _same_cluster_pairs(pred_labels)
    gt_pairs = _same_cluster_pairs(gt_labels)
    correct = pred_pairs & gt_pairs

    n_pairs_pred = len(pred_pairs)
    n_pairs_gt = len(gt_pairs)
    n_pairs_correct = len(correct)

    precision = n_pairs_correct / n_pairs_pred if n_pairs_pred else 1.0
    recall = n_pairs_correct / n_pairs_gt if n_pairs_gt else 1.0
    return {
        "recall": recall,
        "precision": precision,
        "n_pairs_gt": n_pairs_gt,
        "n_pairs_pred": n_pairs_pred,
        "n_pairs_correct": n_pairs_correct,
    }


# ===========================================================================
# faceting_recall(*, facet_key) — recall per works_bucket x year facet
# ===========================================================================
def faceting_recall(
    predicted: Iterable[Mapping[str, Any]],
    ground_truth: Iterable[Mapping[str, Any]],
    *,
    facet_key: Sequence[str],
) -> dict:
    """Compute recall per facet_key (e.g. works_bucket x year) and report the worst facet.

    In plain words: group the people in the true roster by (works_bucket, year); for each group compute
    "how many predicted hits / how many truly there", then take the worst group as the overall faceting
    recall, which prevents "overall recall looks good while one small bucket actually misses a whole block".

    Arguments:
      predicted / ground_truth: each record has at least "id" + every field named in facet_key.
      facet_key: keyword-only (after *), such as ("works_bucket", "year").
    Returns: {per_facet: {(facet value tuple): recall}, faceting_recall: worst-facet recall}.
    Hard rule: the ground truth is externally scraped, read only for comparison, and never fed back into rules.
    """
    def _facet_of(rec: Mapping[str, Any]) -> tuple:
        return tuple(rec[k] for k in facet_key)

    gt_by_facet: dict[tuple, set] = defaultdict(set)
    for rec in ground_truth:
        gt_by_facet[_facet_of(rec)].add(rec["id"])

    pred_ids: set = {rec["id"] for rec in predicted}

    per_facet: dict[tuple, float] = {}
    for facet, gt_ids in gt_by_facet.items():
        hit = len(gt_ids & pred_ids)
        per_facet[facet] = hit / len(gt_ids) if gt_ids else 1.0

    overall = min(per_facet.values()) if per_facet else 1.0
    return {"per_facet": per_facet, "faceting_recall": overall}


# ===========================================================================
# evaluate_gate — pure judgement returning the fails list; any RED threshold None -> raise
# ===========================================================================
def evaluate_gate(
    *,
    recall: float,
    precision: float,
    completeness: float,
    homogeneity: float,
    faceting_recall: float,
    is_large_dept: bool,
) -> list:
    """Pure judgement: compare the six measured metrics with the six red-line floors and return the list of failed items (fails).

    Hard rule: if any RED threshold is None (unset placeholder), require() raises RedlineUnsigned and
    never lets it pass silently. The recall floor is chosen as large/small by is_large_dept. No IO (pure function).

    Thresholds (all read from RED["reverse_validate"], zero hardcoding in the module):
      recall_large_dept / recall_small_dept — recall floor (one of large/small department)
      precision_min / completeness_min / homogeneity_min / faceting_recall_min
    Returns: fails (list[str]); an empty list = all passed.
    """
    # Any placeholder None makes require raise directly (it fails before any comparison, never passing silently).
    recall_floor = require(
        "reverse_validate",
        "recall_large_dept" if is_large_dept else "recall_small_dept",
    )
    # Even for a large department, also force-read the small floor (and vice versa), so any unset floor fails and a change of department class cannot hide one.
    require("reverse_validate", "recall_small_dept" if is_large_dept else "recall_large_dept")
    precision_min = require("reverse_validate", "precision_min")
    completeness_min = require("reverse_validate", "completeness_min")
    homogeneity_min = require("reverse_validate", "homogeneity_min")
    faceting_recall_min = require("reverse_validate", "faceting_recall_min")

    fails: list[str] = []
    if recall < recall_floor:
        fails.append("recall")
    if precision < precision_min:
        fails.append("precision")
    if completeness < completeness_min:
        fails.append("completeness")
    if homogeneity < homogeneity_min:
        fails.append("homogeneity")
    if faceting_recall < faceting_recall_min:
        fails.append("faceting_recall")
    return fails


# ===========================================================================
# Thin shells: validate_resolution / m2_exit_gate — pure judgement -> atomic evidence write -> raise
# ===========================================================================
def _gate_and_persist(
    metrics: Mapping[str, float],
    *,
    is_large_dept: bool,
    evidence_path: str,
    gate_label: str,
) -> None:
    """Common body of the thin shells: evaluate_gate (pure judgement) -> atomic evidence write -> raise ResolveGateFail if not passed.

    Order rules:
      1. evaluate_gate (any threshold None -> RedlineUnsigned is raised here and no evidence is written).
      2. Atomic evidence write (passed + fails + measured metrics + label), G7 atomic write.
      3. Non-empty fails -> raise ResolveGateFail(=12).
    """
    fails = evaluate_gate(
        recall=metrics["recall"],
        precision=metrics["precision"],
        completeness=metrics["completeness"],
        homogeneity=metrics["homogeneity"],
        faceting_recall=metrics["faceting_recall"],
        is_large_dept=is_large_dept,
    )
    passed = len(fails) == 0
    record = {
        "gate": gate_label,
        "is_large_dept": is_large_dept,
        "metrics": dict(metrics),
        "fails": fails,
        "passed": passed,
    }
    blob = (json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    atomic_write_bytes(evidence_path, blob)

    if not passed:
        raise ResolveGateFail(
            f"{gate_label}: reverse validation failed, fails={fails} (large dept={is_large_dept})"
        )


def validate_resolution(
    metrics: Mapping[str, float],
    *,
    is_large_dept: bool,
    evidence_path: str,
) -> None:
    """U2 disambiguation reverse-validation gate (thin shell). Pure judgement -> atomic evidence write -> raise ResolveGateFail if not passed.

    metrics must contain: recall / precision / completeness / homogeneity / faceting_recall.
    Unset thresholds -> RedlineUnsigned is raised first (no evidence written).
    """
    _gate_and_persist(
        metrics,
        is_large_dept=is_large_dept,
        evidence_path=evidence_path,
        gate_label="reverse_validation",
    )


def m2_exit_gate(
    metrics: Mapping[str, float],
    *,
    is_large_dept: bool,
    evidence_path: str,
) -> None:
    """M2 (U2 disambiguation unit) exit gate (thin shell). Same semantics as validate_resolution, distinguished by label."""
    _gate_and_persist(
        metrics,
        is_large_dept=is_large_dept,
        evidence_path=evidence_path,
        gate_label="m2_exit_gate",
    )
