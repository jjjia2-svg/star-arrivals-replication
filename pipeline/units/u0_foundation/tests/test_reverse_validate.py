"""Tests for U0 common/reverse_validate.py.

Covers:
  - compute_recall_precision -> {recall, precision, n_pairs_gt, n_pairs_pred, n_pairs_correct} (pairwise)
  - bcubed_f1 -> {bcubed_precision, bcubed_recall, bcubed_f1} (S2AND/WhoIsWho standard)
  - pairwise_f1 -> {pairwise_precision, pairwise_recall, pairwise_f1}
  - faceting_recall(*, facet_key) -> recall by works_bucket x year facet
  - evaluate_gate(*, recall, precision, completeness, homogeneity, faceting_recall, is_large_dept)
      a pure decision returning a fails list; any RED threshold None -> raise (never pass silently).
  - thin wrappers validate_resolution / m2_exit_gate -> atomic_write the evidence + raise ResolveGateFail.
  - class ResolveGateFail(Exception).

Rules:
  - all six thresholds are None placeholders (redlines.reverse_validate.* all null) -> raise on None, never use a default.
  - ground truth = externally scraped, used only as a fixture, never fed back into the rules.
  - exit codes are not asserted as bare numbers -> assert the exception type, and that .exit_code equals exit_codes.RESOLVE_GATE_FAIL.
"""
import json
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common import reverse_validate as rv  # noqa: E402
from common import _redlines  # noqa: E402
from identity import exit_codes  # noqa: E402


# ===========================================================================
# Group A - pairwise_f1: pairwise P/R/F1
# ===========================================================================
def test_pairwise_f1_perfect_clustering():
    # predicted clusters == true clusters -> P=R=F1=1.0.
    pred = {"a": 1, "b": 1, "c": 2, "d": 2}
    true = {"a": "x", "b": "x", "c": "y", "d": "y"}
    out = rv.pairwise_f1(pred, true)
    assert out["pairwise_precision"] == pytest.approx(1.0)
    assert out["pairwise_recall"] == pytest.approx(1.0)
    assert out["pairwise_f1"] == pytest.approx(1.0)


def test_pairwise_f1_overmerge_drops_precision():
    # Merge two real people (x:{a,b}, y:{c,d}) into one predicted cluster -> recall full, precision drops.
    # Predicted same-cluster pairs = C(4,2)=6; true same-cluster pairs = {ab, cd}=2 (all in the prediction) -> recall=1.
    # Only 2 of the predicted pairs are truly same-cluster -> precision=2/6.
    pred = {"a": 1, "b": 1, "c": 1, "d": 1}
    true = {"a": "x", "b": "x", "c": "y", "d": "y"}
    out = rv.pairwise_f1(pred, true)
    assert out["pairwise_recall"] == pytest.approx(1.0)
    assert out["pairwise_precision"] == pytest.approx(2.0 / 6.0)


def test_pairwise_f1_oversplit_drops_recall():
    # A true cluster (x:{a,b,c}) is predicted as 3 singletons -> no predicted same-cluster pairs.
    # With no predicted positive pairs, precision is defined as 1.0 (no false positives); recall=0 (no true pair recovered).
    pred = {"a": 1, "b": 2, "c": 3}
    true = {"a": "x", "b": "x", "c": "x"}
    out = rv.pairwise_f1(pred, true)
    assert out["pairwise_recall"] == pytest.approx(0.0)
    assert out["pairwise_f1"] == pytest.approx(0.0)


def test_pairwise_f1_keys_exact():
    pred = {"a": 1, "b": 1}
    true = {"a": "x", "b": "x"}
    out = rv.pairwise_f1(pred, true)
    assert set(out.keys()) == {
        "pairwise_precision", "pairwise_recall", "pairwise_f1",
    }


# ===========================================================================
# Group B - bcubed_f1: B-cubed P/R/F1 (S2AND/WhoIsWho standard)
# ===========================================================================
def test_bcubed_f1_perfect_clustering():
    pred = {"a": 1, "b": 1, "c": 2, "d": 2}
    true = {"a": "x", "b": "x", "c": "y", "d": "y"}
    out = rv.bcubed_f1(pred, true)
    assert out["bcubed_precision"] == pytest.approx(1.0)
    assert out["bcubed_recall"] == pytest.approx(1.0)
    assert out["bcubed_f1"] == pytest.approx(1.0)


def test_bcubed_f1_overmerge_precision_lt_one():
    # Everything merged into one cluster: for each element the predicted cluster has size 4, of which 2 are truly its cluster-mates -> B-cubed precision=2/4=0.5.
    # All members of a true cluster are in one predicted cluster -> B-cubed recall=1.0.
    pred = {"a": 1, "b": 1, "c": 1, "d": 1}
    true = {"a": "x", "b": "x", "c": "y", "d": "y"}
    out = rv.bcubed_f1(pred, true)
    assert out["bcubed_precision"] == pytest.approx(0.5)
    assert out["bcubed_recall"] == pytest.approx(1.0)


def test_bcubed_f1_keys_exact():
    pred = {"a": 1, "b": 1}
    true = {"a": "x", "b": "x"}
    out = rv.bcubed_f1(pred, true)
    assert set(out.keys()) == {
        "bcubed_precision", "bcubed_recall", "bcubed_f1",
    }


# ===========================================================================
# Group C - compute_recall_precision: five pairwise keys (con injects predictions/truth)
# ===========================================================================
def _write_labels(path, mapping):
    """Write {entity_id: cluster_label} as a JSONL fixture (ground truth in the externally scraped form)."""
    with open(path, "w", encoding="utf-8") as fh:
        for ent, lab in mapping.items():
            fh.write(json.dumps({"id": ent, "cluster": lab}) + "\n")


def test_compute_recall_precision_five_keys(tmp_path):
    pred_p = tmp_path / "pred.jsonl"
    gt_p = tmp_path / "gt.jsonl"
    _write_labels(pred_p, {"a": 1, "b": 1, "c": 2, "d": 2})
    _write_labels(gt_p, {"a": "x", "b": "x", "c": "y", "d": "y"})
    out = rv.compute_recall_precision(None, str(pred_p), str(gt_p))
    assert set(out.keys()) == {
        "recall", "precision", "n_pairs_gt", "n_pairs_pred", "n_pairs_correct",
    }


def test_compute_recall_precision_perfect(tmp_path):
    pred_p = tmp_path / "pred.jsonl"
    gt_p = tmp_path / "gt.jsonl"
    _write_labels(pred_p, {"a": 1, "b": 1, "c": 2, "d": 2})
    _write_labels(gt_p, {"a": "x", "b": "x", "c": "y", "d": "y"})
    out = rv.compute_recall_precision(None, str(pred_p), str(gt_p))
    assert out["recall"] == pytest.approx(1.0)
    assert out["precision"] == pytest.approx(1.0)
    assert out["n_pairs_gt"] == 2
    assert out["n_pairs_pred"] == 2
    assert out["n_pairs_correct"] == 2


# ===========================================================================
# Group D - faceting_recall(*, facet_key): recall by works_bucket x year facet
# ===========================================================================
def test_faceting_recall_is_keyword_only():
    # facet_key is keyword-only (after *). Passing it positionally -> TypeError.
    with pytest.raises(TypeError):
        rv.faceting_recall([], [], ("works_bucket", "year"))  # noqa: facet_key passed positionally


def test_faceting_recall_per_facet_min(tmp_path):
    # Two facets (works_bucket x year): one fully recalled, one half recalled.
    # The ground truth has 4 people and the prediction hits 3 of them; report the worst-facet recall (the gate looks at the min).
    ground_truth = [
        {"id": "p1", "works_bucket": "lo", "year": 2010},
        {"id": "p2", "works_bucket": "lo", "year": 2010},
        {"id": "p3", "works_bucket": "hi", "year": 2020},
        {"id": "p4", "works_bucket": "hi", "year": 2020},
    ]
    predicted = [
        {"id": "p1", "works_bucket": "lo", "year": 2010},
        {"id": "p2", "works_bucket": "lo", "year": 2010},
        {"id": "p3", "works_bucket": "hi", "year": 2020},
        # p4 is missed -> recall of facet hi x 2020 = 1/2
    ]
    out = rv.faceting_recall(predicted, ground_truth, facet_key=("works_bucket", "year"))
    assert isinstance(out, dict)
    # recall is reported for every facet; lo x 2010 = 1.0, hi x 2020 = 0.5
    assert out["per_facet"][("lo", 2010)] == pytest.approx(1.0)
    assert out["per_facet"][("hi", 2020)] == pytest.approx(0.5)
    # overall faceting recall = the worst facet (min over facets)
    assert out["faceting_recall"] == pytest.approx(0.5)


# ===========================================================================
# Group E - evaluate_gate: a pure decision returning a fails list; any RED threshold None -> raise
# ===========================================================================
def test_evaluate_gate_raises_when_any_threshold_none():
    # All six thresholds are None placeholders (redlines.reverse_validate.* all null) -> evaluate_gate must raise,
    #   never pass silently. Rule: any RED threshold None -> raise; placeholders never get a default.
    with pytest.raises(_redlines.RedlineUnsigned):
        rv.evaluate_gate(
            recall=0.9,
            precision=0.9,
            completeness=0.9,
            homogeneity=0.9,
            faceting_recall=0.9,
            is_large_dept=True,
        )


def test_evaluate_gate_returns_fails_list_when_thresholds_signed(monkeypatch):
    # Simulate six thresholds with values (inject RED, YAML unchanged): a metric below its floor -> that item goes into the fails list.
    # Ground-truth thresholds are only a fixture and are never fed back into redlines.yaml.
    signed = dict(_redlines.RED)
    signed["reverse_validate"] = {
        "recall_large_dept": 0.80,
        "recall_small_dept": 0.60,
        "precision_min": 0.90,
        "completeness_min": 0.85,
        "homogeneity_min": 0.85,
        "faceting_recall_min": 0.70,
    }
    monkeypatch.setattr(_redlines, "RED", signed)
    monkeypatch.setattr(rv, "RED", signed, raising=False)
    # Large department: recall is compared with recall_large_dept(0.80); 0.75 < 0.80 -> recall goes into fails.
    # precision 0.95 >= 0.90 OK; completeness 0.80 < 0.85 -> goes into fails;
    # homogeneity 0.90 OK; faceting 0.65 < 0.70 -> goes into fails.
    fails = rv.evaluate_gate(
        recall=0.75,
        precision=0.95,
        completeness=0.80,
        homogeneity=0.90,
        faceting_recall=0.65,
        is_large_dept=True,
    )
    assert isinstance(fails, list)
    assert "recall" in fails
    assert "completeness" in fails
    assert "faceting_recall" in fails
    assert "precision" not in fails
    assert "homogeneity" not in fails


def test_evaluate_gate_empty_fails_when_all_pass(monkeypatch):
    signed = dict(_redlines.RED)
    signed["reverse_validate"] = {
        "recall_large_dept": 0.80,
        "recall_small_dept": 0.60,
        "precision_min": 0.90,
        "completeness_min": 0.85,
        "homogeneity_min": 0.85,
        "faceting_recall_min": 0.70,
    }
    monkeypatch.setattr(_redlines, "RED", signed)
    monkeypatch.setattr(rv, "RED", signed, raising=False)
    fails = rv.evaluate_gate(
        recall=0.99,
        precision=0.99,
        completeness=0.99,
        homogeneity=0.99,
        faceting_recall=0.99,
        is_large_dept=True,
    )
    assert fails == []


def test_evaluate_gate_small_dept_uses_small_recall_floor(monkeypatch):
    # is_large_dept=False -> recall is compared with recall_small_dept(0.60), not large(0.80).
    signed = dict(_redlines.RED)
    signed["reverse_validate"] = {
        "recall_large_dept": 0.80,
        "recall_small_dept": 0.60,
        "precision_min": 0.90,
        "completeness_min": 0.85,
        "homogeneity_min": 0.85,
        "faceting_recall_min": 0.70,
    }
    monkeypatch.setattr(_redlines, "RED", signed)
    monkeypatch.setattr(rv, "RED", signed, raising=False)
    # recall 0.70: passes for a small department (>=0.60); wrongly using the large-department floor (0.80) would put it into fails.
    fails = rv.evaluate_gate(
        recall=0.70,
        precision=0.95,
        completeness=0.95,
        homogeneity=0.95,
        faceting_recall=0.95,
        is_large_dept=False,
    )
    assert "recall" not in fails, "a small department should be compared with the recall_small_dept floor, not the large one"


# ===========================================================================
# Group F - thin wrappers validate_resolution / m2_exit_gate: pure decision -> atomic evidence write -> raise
# ===========================================================================
def test_resolve_gate_fail_carries_exit_code():
    # ResolveGateFail carries the exit code, equal to exit_codes.RESOLVE_GATE_FAIL(=12).
    err = rv.ResolveGateFail("gate failed")
    assert err.exit_code == exit_codes.RESOLVE_GATE_FAIL


def test_validate_resolution_raises_on_unsigned_thresholds(tmp_path):
    # all six thresholds null (default redlines) -> the thin wrapper hits None in the pure decision -> raise (never pass silently).
    evidence_path = tmp_path / "reverse_validation_large.json"
    with pytest.raises(_redlines.RedlineUnsigned):
        rv.validate_resolution(
            metrics={
                "recall": 0.9, "precision": 0.9, "completeness": 0.9,
                "homogeneity": 0.9, "faceting_recall": 0.9,
            },
            is_large_dept=True,
            evidence_path=str(evidence_path),
        )


def test_validate_resolution_writes_evidence_and_raises_on_fail(tmp_path, monkeypatch):
    # thresholds set + metrics below them -> atomically write the evidence file + raise ResolveGateFail(=12).
    signed = dict(_redlines.RED)
    signed["reverse_validate"] = {
        "recall_large_dept": 0.80,
        "recall_small_dept": 0.60,
        "precision_min": 0.90,
        "completeness_min": 0.85,
        "homogeneity_min": 0.85,
        "faceting_recall_min": 0.70,
    }
    monkeypatch.setattr(_redlines, "RED", signed)
    monkeypatch.setattr(rv, "RED", signed, raising=False)
    evidence_path = tmp_path / "reverse_validation_large.json"
    with pytest.raises(rv.ResolveGateFail) as ei:
        rv.validate_resolution(
            metrics={
                "recall": 0.10, "precision": 0.10, "completeness": 0.10,
                "homogeneity": 0.10, "faceting_recall": 0.10,
            },
            is_large_dept=True,
            evidence_path=str(evidence_path),
        )
    assert ei.value.exit_code == exit_codes.RESOLVE_GATE_FAIL
    # atomic write: the evidence file is on disk and records the fails.
    assert evidence_path.exists()
    rec = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert rec["passed"] is False
    assert "recall" in rec["fails"]


def test_validate_resolution_writes_pass_evidence_no_raise(tmp_path, monkeypatch):
    # thresholds set + all metrics meet them -> write passed=True evidence, no raise.
    signed = dict(_redlines.RED)
    signed["reverse_validate"] = {
        "recall_large_dept": 0.80,
        "recall_small_dept": 0.60,
        "precision_min": 0.90,
        "completeness_min": 0.85,
        "homogeneity_min": 0.85,
        "faceting_recall_min": 0.70,
    }
    monkeypatch.setattr(_redlines, "RED", signed)
    monkeypatch.setattr(rv, "RED", signed, raising=False)
    evidence_path = tmp_path / "reverse_validation_large.json"
    rv.validate_resolution(
        metrics={
            "recall": 0.99, "precision": 0.99, "completeness": 0.99,
            "homogeneity": 0.99, "faceting_recall": 0.99,
        },
        is_large_dept=True,
        evidence_path=str(evidence_path),
    )
    rec = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert rec["passed"] is True
    assert rec["fails"] == []


def test_m2_exit_gate_raises_on_unsigned_thresholds(tmp_path):
    # m2_exit_gate is the same kind of thin wrapper: six thresholds unset -> raise (never pass silently).
    evidence_path = tmp_path / "m2_gate.json"
    with pytest.raises(_redlines.RedlineUnsigned):
        rv.m2_exit_gate(
            metrics={
                "recall": 0.9, "precision": 0.9, "completeness": 0.9,
                "homogeneity": 0.9, "faceting_recall": 0.9,
            },
            is_large_dept=True,
            evidence_path=str(evidence_path),
        )


# ===========================================================================
# Group G - ground-truth isolation rule (never fed back into the rules)
# ===========================================================================
def test_ground_truth_thresholds_not_written_back_to_redlines():
    # Ground truth = externally scraped, used only as a fixture, never fed back into the rules.
    # The module's default six thresholds are still None (placeholders) and are not self-filled by any evaluation.
    rvs = _redlines.RED["reverse_validate"]
    for key in (
        "recall_large_dept", "recall_small_dept", "precision_min",
        "completeness_min", "homogeneity_min", "faceting_recall_min",
    ):
        assert rvs[key] is None, (
            f"reverse_validate.{key} must stay a None placeholder (unset), never filled in by code"
        )
