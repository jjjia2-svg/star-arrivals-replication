"""Tests that the failed_ids identity arm is passed through into the u1 production reconcile path.

Background:
  - Reconcile arm 3 compared only the NUMBER of entries in the refetch queue, not the IDENTITY of the
    failed op_ids. So a wrong member in the queue plus a truly failed one missing from it could silently
    skip a refetch. The fix is to pass the set of failed op_ids as an input and make arm 3 a set
    containment check (failed_ids is a subset of queue), plus a test for "queue count is enough but the
    members are wrong".
  - The consuming side exists: U0 common/reconcile.py reconcile_fetch(failed_ids=...).
  - Producer side: the reconcile_m1.reconcile_pass docstring says "on the M1 path a shard-level failure
    goes to M0 refetch, and the failed expectation at the flatten stage is always 0". The u1 streaming
    production path therefore has no per-item failed op_id producer and failed is always 0. Wiring means:
    reconcile_pass opens a failed_ids parameter, and _reconcile_streaming passes an empty identity set
    ("failed is always 0"), so arm 3 uses the identity check from now on. If a real failure producer
    ever appears, swap the empty set for the real set; no wiring gap remains.

Definition-neutral: engineering reconcile pass-through; tolerances and formulas are untouched.
"""
from __future__ import annotations

import pytest

pa = pytest.importorskip("pyarrow")

from identity.exit_codes import TALLY_IMBALANCE
from identity.golden import MONASH_CANONICAL_ID


def test_reconcile_pass_failed_ids_member_mismatch_halts(tmp_path):
    """Main case: the queue count is enough but the members are wrong (wrong member a is queued, truly failed c is absent) -> must HALT 15.

    The old count arm: len(queue)=1 < failed=1 is false -> it would let this through (silently skipping the refetch of c).
    The identity arm: failed_ids={c} is not a subset of queue={a} -> HALT.
    """
    from m1_ingest import reconcile_m1 as REC

    with pytest.raises(SystemExit) as ei:
        REC.reconcile_pass(
            expected=10, kept=9, failed=1, skipped=0,
            stage="t_a12", tally_path=tmp_path / "tally.json",
            refetch_queue={"a"},           # count 1 >= failed 1: the old arm sees no problem
            failed_ids={"c"},              # but the truly failed c is not in the queue -> the identity arm must fail
            diff_tolerance=0,
        )
    assert ei.value.code == TALLY_IMBALANCE


def test_reconcile_pass_failed_ids_all_queued_balances(tmp_path):
    """Pass side: every failed id is in the queue (failed_ids is a subset of queue) -> the tally balances and is returned."""
    from m1_ingest import reconcile_m1 as REC

    tally = REC.reconcile_pass(
        expected=10, kept=9, failed=1, skipped=0,
        stage="t_a12_ok", tally_path=tmp_path / "tally.json",
        refetch_queue={"c", "extra"},
        failed_ids={"c"},
        diff_tolerance=0,
    )
    assert tally["balanced"] is True


def test_streaming_reconcile_wires_failed_ids_identity_arm(monkeypatch, tmp_path):
    """Wiring test: the u1 production reconcile path (_reconcile_streaming) must pass failed_ids to reconcile_pass
    (failed is always 0 -> an empty identity set, not None, which would fall back to the old count arm)."""
    from m1_ingest import reconcile_m1 as REC
    from m1_ingest import stream_build as S

    captured = {}
    real = REC.reconcile_pass

    def _spy(**kw):
        captured.update(kw)
        return real(**kw)

    monkeypatch.setattr(REC, "reconcile_pass", _spy)

    work = {
        "id": "https://openalex.org/W_MS",
        "publication_year": 2016,
        "type": "article",
        "cited_by_count": 1,
        "referenced_works": [],
        "primary_topic": {"subfield": {"id": "https://openalex.org/subfields/2002"}},
        "authorships": [{
            "author": {"id": "https://openalex.org/A1", "display_name": "A1", "orcid": None},
            "institutions": [{
                "id": f"https://openalex.org/{MONASH_CANONICAL_ID}",
                "display_name": "Monash", "country_code": "AU", "type": "education",
                "lineage": [f"https://openalex.org/{MONASH_CANONICAL_ID}"],
            }],
            "raw_affiliation_strings": ["Monash University, Department of Economics"],
        }],
    }
    manifest = {
        "date": "2026-06-26", "format": "jsonl",
        "meta": {"record_count": 1, "content_length": 1},
        "entities": [{
            "entity": "works", "record_count": 1, "content_length": 1,
            "files": [{"url": "s3://openalex/data/jsonl/works/updated_date=2016-01-01/part_0000.gz",
                       "meta": {"content_length": 1, "record_count": 1}}],
        }],
    }
    S.run_m1_streaming(
        [work], [work],
        registry=[{"openalex_id": MONASH_CANONICAL_ID, "type": "education"}],
        econ_dept_ids={MONASH_CANONICAL_ID},
        out_root=tmp_path / "out", n_workers=1,
        reconcile=True, reconcile_diff_tolerance=0,
        reconcile_manifest=manifest,
    )
    assert "failed_ids" in captured, "The production reconcile path must pass failed_ids through (A12 identity arm)"
    assert captured["failed_ids"] == set(), "failed≡0 (existing design) → empty identity set, not a None fallback to the row-count arm"
