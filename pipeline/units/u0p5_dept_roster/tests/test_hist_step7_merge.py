"""Historical roster step 7 TDD - Table B merge (preview version) + trusted set + human review queue.

Rule discipline:
  - The final Table B file is never overwritten - the merge output is a new preview file, promoted to final only after a person has approved the stamp rule.
  - Trusted set rules (G2 official roster wins / Q0 candidates need a human check / Q10 unchecked ones enter robustness checks only):
    all official_roster rows go in; a candidate row must have human_verified=True; candidate rows of stars + first-order colleagues that are not
    human-checked never enter the trusted set (red test #18: an automatic call can be overruled by a person).
  - Merge = one row per distinct evidence (red test #12: same parquet, schema guard, deterministic).
  - Human review queue = unchecked candidates of stars + first-order colleagues + stamp-only pairs, layered by reason, nothing silently dropped.
"""
import hashlib

import pyarrow as pa
import pyarrow.parquet as pq


def _official(a, dk="monash_econ", name="Some One", hv=True):
    return {"dept_key": dk, "author_id": a, "display_name": name,
            "year_start": None, "year_end": None,
            "evidence": "official_roster", "confidence": "high", "human_verified": hv}


def _cand(a, dk="monash_econ", name=None, ys=2005, ye=2015, hv=False):
    return {"dept_key": dk, "author_id": a, "display_name": name,
            "year_start": ys, "year_end": ye,
            "evidence": "raw_affil_year", "confidence": "low", "human_verified": hv}


def test_merge_keeps_both_evidence_rows_and_schema():
    """Red test #12 semantics: the same person's official row + raw_affil_year candidate row coexist (one row per
    distinct evidence, no merging, no de-duplication); all rows keep the 8 Table B columns."""
    from common.schema import DEPT_ROSTER_PANEL
    from roster.byline_merge import merge_candidate_rows

    merged = merge_candidate_rows(
        [_official("A1"), _official("A2")],
        [_cand("A1"), _cand("A3")],
    )
    assert len(merged) == 4
    for r in merged:
        assert set(r.keys()) == set(DEPT_ROSTER_PANEL.keys())
    a1 = [r for r in merged if r["author_id"] == "A1"]
    assert {r["evidence"] for r in a1} == {"official_roster", "raw_affil_year"}


def test_merge_never_mutates_inputs():
    from roster.byline_merge import merge_candidate_rows

    off = [_official("A1")]
    cand = [_cand("A1")]
    snap_off, snap_cand = [dict(r) for r in off], [dict(r) for r in cand]
    merge_candidate_rows(off, cand)
    assert off == snap_off and cand == snap_cand


def test_write_merged_preview_deterministic_and_never_official_filename(tmp_path):
    """The preview file name carries the merged_ prefix + a rule suffix; two writes of the same input are byte-equal;
    it is never written under a final Table B file name (dept_roster_panel_monash/unsw.parquet)."""
    from roster.byline_merge import write_merged_preview

    rows = [_official("A1"), _cand("A2")]
    p1 = write_merged_preview(rows, tmp_path / "o1", suffix="printed_only")
    p2 = write_merged_preview(rows, tmp_path / "o2", suffix="printed_only")
    assert p1.name == "dept_roster_panel_merged_printed_only.parquet"
    assert p1.name not in ("dept_roster_panel_monash.parquet", "dept_roster_panel_unsw.parquet")
    assert hashlib.sha256(p1.read_bytes()).hexdigest() == hashlib.sha256(p2.read_bytes()).hexdigest()
    back = pq.read_table(str(p1))
    from common.schema import DEPT_ROSTER_PANEL
    assert back.column_names == list(DEPT_ROSTER_PANEL.keys())
    assert back.schema.field("year_start").type == pa.int16()
    meta = pq.ParquetFile(str(p1)).metadata.metadata or {}
    assert b"ARROW:schema" not in meta


def test_merged_preview_bytes_independent_of_input_order(tmp_path):
    """Hardening (the previous batch's BLOCKER-1 discipline): several official rows without an id in one department (real data: Monash 3 / UNSW 2)
    tie on the 4-column sort key - the key must include display_name so the bytes do not depend on input row order;
    determinism must not silently depend on the upstream parquet row order."""
    from roster.byline_merge import write_merged_preview

    r1 = _official(None, name="Alpha Person", hv=False)
    r2 = _official(None, name="Beta Person", hv=False)
    p1 = write_merged_preview([r1, r2], tmp_path / "o1", suffix="all")
    p2 = write_merged_preview([r2, r1], tmp_path / "o2", suffix="all")
    assert p1.read_bytes() == p2.read_bytes(), "flat-key rows must be ordered by display_name, independent of input order"


def test_trusted_view_official_in_unverified_candidates_out():
    """Trusted set (a filter applying the rules above, no new criterion): all official rows go in;
    candidate rows with hv=False stay out; candidate rows with hv=True go in."""
    from roster.byline_merge import trusted_view

    merged = [
        _official("A_off"),
        _cand("A_pending", hv=False),
        _cand("A_done", hv=True),
    ]
    tv = trusted_view(merged, star_and_first_degree=set())
    ids = {(r["author_id"], r["evidence"]) for r in tv}
    assert ("A_off", "official_roster") in ids
    assert ("A_done", "raw_affil_year") in ids
    assert all(r["author_id"] != "A_pending" for r in tv)


def test_star_and_first_degree_require_human_verified():
    """Red test #18: candidate rows of stars + first-order colleagues with hv=False -> not in the trusted set (same rule as ordinary candidates,
    and they must appear in the human review queue so 100% go through a human check, never silently missed)."""
    from roster.byline_merge import build_human_review_queue, trusted_view

    merged = [
        _official("A_star"),                      # the star is on the official site -> the official row goes in as is
        _cand("A_star", hv=False),                # the star's candidate row is not human-checked -> not in the trusted set
        _cand("A_deg1", hv=False),                # first-order collaborator candidate not human-checked
        _cand("A_norm", hv=False),                # ordinary candidate
    ]
    star_set = {"A_star", "A_deg1"}
    tv = trusted_view(merged, star_and_first_degree=star_set)
    assert all(not (r["author_id"] in star_set and r["evidence"] == "raw_affil_year")
               for r in tv), "star + first-order unreviewed candidate rows never enter the trusted set"

    queue = build_human_review_queue(merged, star_and_first_degree=star_set,
                                     stamped_only_pairs=set())
    q_ids = {r["author_id"] for r in queue}
    assert {"A_star", "A_deg1"} <= q_ids, "star + first-order candidates are 100% queued for manual review"
    reasons = {r["author_id"]: r["reason"] for r in queue}
    assert reasons["A_star"] == "star_or_first_degree"


def test_human_review_queue_includes_stamped_only_and_sorted():
    """Human review queue: stamp-only pairs (n_printed_style=0) enter the queue (reason=stamped_only);
    stars + first-order colleagues come first; one person with several reasons gets no duplicate rows (star first)."""
    from roster.byline_merge import build_human_review_queue

    merged = [
        _cand("A_stamp", hv=False),
        _cand("A_both", hv=False),
        _cand("A_norm", hv=False),
    ]
    queue = build_human_review_queue(
        merged, star_and_first_degree={"A_both"},
        stamped_only_pairs={("A_stamp", "monash_econ"), ("A_both", "monash_econ")},
    )
    by_a = {r["author_id"]: r for r in queue}
    assert by_a["A_stamp"]["reason"] == "stamped_only"
    assert by_a["A_both"]["reason"] == "star_or_first_degree", "star priority beats stamp-only"
    assert "A_norm" not in by_a, "ordinary unreviewed candidates do not enter this queue (Q10 already keeps them out of the main definition)"
    assert [r["reason"] for r in queue] == sorted(
        [r["reason"] for r in queue], key=lambda x: x != "star_or_first_degree"
    ), "star + first-order go to the front of the queue"


def test_queue_includes_below_threshold_stamped_pairs():
    """Sentinel VIOLATION fix (option 2): the required behaviour is "94 stamp-only pairs enter the human review queue", so stamp-only pairs
    that did not pass the threshold must also enter the queue (separate reason=stamped_only_below_threshold, sorted last),
    so the output matches that behaviour and the human-review coverage is not silently narrowed."""
    from roster.byline_merge import build_human_review_queue

    merged = [_cand("A_q", hv=False)]
    below = [{"author_id": "A_below", "dept_key": "monash_econ", "display_name": "Below, Bob"}]
    queue = build_human_review_queue(
        merged, star_and_first_degree=set(),
        stamped_only_pairs={("A_q", "monash_econ")},
        stamped_below_threshold=below,
    )
    by_a = {r["author_id"]: r for r in queue}
    assert by_a["A_q"]["reason"] == "stamped_only"
    assert by_a["A_below"]["reason"] == "stamped_only_below_threshold"
    assert by_a["A_below"]["year_start"] is None, "below the threshold there is no interval; leave it empty, make up no numbers"
    order = [r["reason"] for r in queue]
    assert order.index("stamped_only") < order.index("stamped_only_below_threshold"), (
        "below-threshold groups go last in the queue"
    )


def test_queue_rows_carry_priority_rank_for_deterministic_parquet_order():
    """Adversarial review FIX-1: sorting the parquet output by the reason string would sink the star + first-order VIP rows (opposite to the CSV order).
    Queue rows carry a priority integer column (star=0/stamped=1/below=2), and the parquet sort key uses it ->
    consistent with the CSV / in-memory order."""
    from roster.byline_merge import build_human_review_queue

    merged = [_cand("A_q", hv=False), _cand("A_vip", hv=False)]
    queue = build_human_review_queue(
        merged, star_and_first_degree={"A_vip"},
        stamped_only_pairs={("A_q", "monash_econ")},
        stamped_below_threshold=[{"author_id": "A_b", "dept_key": "monash_econ",
                                  "display_name": None}],
    )
    assert [r["reason"] for r in queue] == [
        "star_or_first_degree", "stamped_only", "stamped_only_below_threshold"]
    assert [r["priority"] for r in queue] == [0, 1, 2], "priority column = parquet sort key"


def test_merged_sort_key_total_order_nonkey_columns(tmp_path):
    """Adversarial review FIX-2 hardening: rows tied on all 5 keys but different in non-key columns (year_end/human_verified/confidence)
    must still give bytes independent of input order - the sort key is completed into a total order."""
    from roster.byline_merge import write_merged_preview

    r1 = {"dept_key": "monash_econ", "author_id": None, "display_name": None,
          "year_start": None, "year_end": 2011,
          "evidence": "official_roster", "confidence": "high", "human_verified": True}
    r2 = dict(r1, year_end=2013, human_verified=False)
    p1 = write_merged_preview([r1, r2], tmp_path / "o1", suffix="all")
    p2 = write_merged_preview([r2, r1], tmp_path / "o2", suffix="all")
    assert p1.read_bytes() == p2.read_bytes()


def test_reconcile_counts_official_vs_skeleton():
    """Merge reconciliation: official site only (never publishes / low output) / present in both sources / skeleton only (= the recovered leavers pool)."""
    from roster.byline_merge import reconcile_counts

    official = [_official("A_only_off"), _official("A_both")]
    skeleton = [_cand("A_both"), _cand("A_only_sk")]
    rc = reconcile_counts(official + [_official(None, name="No Id")], skeleton)
    assert rc == {"official_only": 1, "both": 1, "skeleton_only": 1,
                  "official_total": 3, "skeleton_total": 2,
                  "official_none_id_rows": 1}, (
        "mixed-base explanation field: total counts rows, only/both count non-None keys, the difference is explicitly visible"
    )
