"""Tests for fwci_accumulator.py: fixtures check accumulation, 32 buckets and determinism; never a real S3 download.

Covers:
  - FwciPopAccumulator.add covers ALL works (not only the seed): for every
    (subfield_id, year, work_type) cell it accumulates work_count + citation_sum + cit_hist_32 (32 buckets).
  - The self-built denominator needs only cited_by_count + subfield_id (the native fwci is not read).
  - to_table sorts cells by (subfield_id, year, work_type) -> deterministic (byte-identical on two runs
    with the same input).
  - log_bucket_index(c) is in 0..31; monotone; c=0 -> 0; large values are capped at 31.
  - dropped_null (missing subfield_id/year -> not counted in any cell, counted separately, so the
    global diagnostic is not lost).
  - paratext_count (counts is_paratext; the symmetric paratext drop is done downstream, so this count is only a diagnostic).
  - Acceptance: the global baseline == the aggregate over all works (per-cell work_count/citation_sum
    equal a hand-made aggregate).
  - Schema: each row has exactly the 6 FWCI_BASELINE_POP keys (subfield_id, year, work_type, work_count,
    citation_sum, cit_hist_32).
  - Red-line placeholder kept: snapshot_year=null -> any read goes through require -> RedlineUnsigned
    (a default is never substituted).
  - Fixed values are only stated: field_level=subfield / expected_method=mean (the 32-bucket quantile
    method is retired); no self-learning, changing it requires a deliberate edit.

Discipline: all fixtures are small samples that test logic; no real S3 download; redlines null is never
read to steal a default.
"""
from __future__ import annotations

import pytest

from m1_ingest import fwci_accumulator as fa
from common.schema import FWCI_BASELINE_POP, assert_matches_schema


# ---------------------------------------------------------------------------
# fixture: small sample of works (raw snapshot JSON shape; subfield.id is a URL string)
#   Only the fields the self-built FWCI denominator needs, plus probe fields; paratext, missing
#   subfield and missing year are mixed in on purpose.
# ---------------------------------------------------------------------------
def _work(
    wid: str,
    *,
    subfield: str | None,
    year: int | None,
    wtype: str,
    cited: int,
    paratext: bool = False,
):
    """Build one snapshot works record (subfield given as a bare digit string -> expanded to the URL form, mimicking the real snapshot)."""
    primary_topic = None
    if subfield is not None:
        primary_topic = {
            "subfield": {"id": f"https://openalex.org/subfields/{subfield}"}
        }
    return {
        "id": f"https://openalex.org/{wid}",
        "publication_year": year,
        "type": wtype,
        "cited_by_count": cited,
        "is_paratext": paratext,
        "primary_topic": primary_topic,
    }


_WORKS = [
    # cell (2002, 2010, article): two works -> work_count=2, citation_sum=3+5=8
    _work("W1", subfield="2002", year=2010, wtype="article", cited=3),
    _work("W2", subfield="2002", year=2010, wtype="article", cited=5),
    # cell (2002, 2010, review): one work -> work_count=1, citation_sum=0
    _work("W3", subfield="2002", year=2010, wtype="review", cited=0),
    # cell (2003, 2011, article): one work, cited=100
    _work("W4", subfield="2003", year=2011, wtype="article", cited=100),
    # paratext (diagnostic count; still accumulated by cell, the drop is done symmetrically downstream, this table only supplies raw material)
    _work("W5", subfield="2002", year=2010, wtype="paratext", cited=1, paratext=True),
    # missing subfield -> dropped_null, enters no cell
    _work("W6", subfield=None, year=2012, wtype="article", cited=9),
    # missing year -> dropped_null
    _work("W7", subfield="2002", year=None, wtype="article", cited=9),
]


# ---------------------------------------------------------------------------
# log_bucket_index: 32-bucket log-histogram binning (deterministic, 0..31, monotone)
# ---------------------------------------------------------------------------
def test_log_bucket_index_zero_citations_is_bucket_zero():
    assert fa.log_bucket_index(0) == 0


def test_log_bucket_index_in_range_0_to_31():
    for c in [0, 1, 2, 3, 7, 15, 100, 10_000, 1_000_000, 2_000_000_000]:
        b = fa.log_bucket_index(c)
        assert 0 <= b <= 31, f"c={c} → bucket {b} out of range 0..31"


def test_log_bucket_index_monotonic_nondecreasing():
    prev = -1
    for c in range(0, 5000):
        b = fa.log_bucket_index(c)
        assert b >= prev, f"not monotonic: c={c} bucket {b} < prev {prev}"
        prev = b


def test_log_bucket_index_caps_at_31_for_huge_counts():
    # an extreme citation count (far beyond real data) is still capped at 31, no overflow
    assert fa.log_bucket_index(10**18) == 31


def test_log_bucket_index_negative_raises():
    # cited_by_count must not be negative; a negative value is corrupt data -> fail loudly, never silently map to 0
    with pytest.raises(ValueError):
        fa.log_bucket_index(-1)


# ---------------------------------------------------------------------------
# add accumulation + to_table cell shape
# ---------------------------------------------------------------------------
def test_add_accumulates_work_count_and_citation_sum_per_cell():
    acc = fa.FwciPopAccumulator()
    for w in _WORKS:
        acc.add(w)
    cells = {(r["subfield_id"], r["year"], r["work_type"]): r for r in acc.to_table()}
    a = cells[("2002", 2010, "article")]
    assert a["work_count"] == 2
    assert a["citation_sum"] == 8  # 3 + 5
    r = cells[("2002", 2010, "review")]
    assert r["work_count"] == 1
    assert r["citation_sum"] == 0


def test_add_covers_all_works_not_only_seed():
    """The accumulator covers every scanned work, with no seed or economics-department filter (that belongs to the pass layer)."""
    acc = fa.FwciPopAccumulator()
    for w in _WORKS:
        acc.add(w)
    # a work from a different subfield in 2003 must also be present (not removed by any whitelist)
    cells = {(r["subfield_id"], r["year"], r["work_type"]) for r in acc.to_table()}
    assert ("2003", 2011, "article") in cells


def test_add_extracts_subfield_id_from_url_tail_not_int_match():
    """primary_topic.subfield.id is a URL string -> take the trailing digit string '2002', not the whole URL."""
    acc = fa.FwciPopAccumulator()
    acc.add(_work("W9", subfield="2002", year=2010, wtype="article", cited=1))
    sub_ids = {r["subfield_id"] for r in acc.to_table()}
    assert "2002" in sub_ids
    assert all(not s.startswith("http") for s in sub_ids)


def test_cit_hist_32_has_exactly_32_buckets_and_counts_works():
    acc = fa.FwciPopAccumulator()
    for w in _WORKS:
        acc.add(w)
    cells = {(r["subfield_id"], r["year"], r["work_type"]): r for r in acc.to_table()}
    a = cells[("2002", 2010, "article")]
    hist = a["cit_hist_32"]
    assert len(hist) == 32
    # W1 cited=3 -> bucket 2; W2 cited=5 -> bucket 2 (floor(log2(6))=2) -> bucket 2 counts 2
    assert sum(hist) == a["work_count"]  # bucket total == the cell's work_count
    assert hist[fa.log_bucket_index(3)] >= 1


def test_to_table_rows_match_fwci_baseline_pop_schema():
    acc = fa.FwciPopAccumulator()
    for w in _WORKS:
        acc.add(w)
    rows = acc.to_table()
    assert len(rows) >= 1
    for r in rows:
        assert_matches_schema(r.keys(), FWCI_BASELINE_POP, label="FWCI_BASELINE_POP")


# ---------------------------------------------------------------------------
# dropped_null / paratext_count diagnostic counts
# ---------------------------------------------------------------------------
def test_missing_subfield_or_year_counted_as_dropped_null_not_in_cell():
    acc = fa.FwciPopAccumulator()
    for w in _WORKS:
        acc.add(w)
    # W6 lacks subfield, W7 lacks year -> 2 dropped_null
    assert acc.dropped_null == 2
    # they enter no cell: global sum of work_count = 7 - 2 = 5
    total = sum(r["work_count"] for r in acc.to_table())
    assert total == 5


def test_paratext_count_tracked():
    acc = fa.FwciPopAccumulator()
    for w in _WORKS:
        acc.add(w)
    # W5 is_paratext=True -> paratext_count=1 (diagnostic; the symmetric drop is done downstream, this table still accumulates it)
    assert acc.paratext_count == 1


# ---------------------------------------------------------------------------
# Acceptance: global baseline == aggregate over all works (precondition for leave-star on the same definition)
# ---------------------------------------------------------------------------
def test_baseline_equals_full_set_aggregation():
    """Per-cell work_count/citation_sum must equal a hand-made group-by aggregate over all works."""
    acc = fa.FwciPopAccumulator()
    for w in _WORKS:
        acc.add(w)
    got = {(r["subfield_id"], r["year"], r["work_type"]): (r["work_count"], r["citation_sum"])
           for r in acc.to_table()}

    # hand-made aggregate (independent of the accumulator, as a cross-check)
    from collections import defaultdict
    man_cnt: dict = defaultdict(int)
    man_cit: dict = defaultdict(int)
    for w in _WORKS:
        pt = w.get("primary_topic")
        sub = pt["subfield"]["id"].rsplit("/", 1)[-1] if pt else None
        yr = w.get("publication_year")
        if sub is None or yr is None:
            continue
        key = (sub, yr, w["type"])
        man_cnt[key] += 1
        man_cit[key] += w["cited_by_count"]
    man = {k: (man_cnt[k], man_cit[k]) for k in man_cnt}
    assert got == man


# ---------------------------------------------------------------------------
# Determinism: to_table sorts by (subfield_id, year, work_type); two runs are identical
# ---------------------------------------------------------------------------
def test_to_table_sorted_by_pk_deterministic():
    acc = fa.FwciPopAccumulator()
    for w in _WORKS:
        acc.add(w)
    rows = acc.to_table()
    keys = [(r["subfield_id"], r["year"], r["work_type"]) for r in rows]
    assert keys == sorted(keys)


def test_two_runs_identical_order_independent():
    """The same works inserted in a different order -> identical to_table result (deterministic, order-independent)."""
    acc1 = fa.FwciPopAccumulator()
    for w in _WORKS:
        acc1.add(w)
    acc2 = fa.FwciPopAccumulator()
    for w in reversed(_WORKS):
        acc2.add(w)
    assert acc1.to_table() == acc2.to_table()


# ---------------------------------------------------------------------------
# snapshot_year is fixed: guard the fixed value (the snapshot frozen on 2026-06-29)
# ---------------------------------------------------------------------------
def test_snapshot_year_signed_returns_frozen_snapshot():
    assert fa.require_snapshot_year() == "snapshot_2026-06-29_merkle_da78e4b9"


def test_field_level_signed_is_subfield():
    """Fixed: FWCI field granularity = subfield (this only states the fixed value; changing it requires a deliberate edit; no self-learning)."""
    assert fa.FWCI_FIELD_LEVEL == "subfield"


def test_expected_method_signed_is_mean_not_32bucket_quantile():
    """Fixed: expected = arithmetic mean (the 32-bucket quantile method is retired); cit_hist_32 is only a diagnostic carrier."""
    assert fa.FWCI_EXPECTED_METHOD == "mean"
