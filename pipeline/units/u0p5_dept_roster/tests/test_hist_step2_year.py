"""Historical roster step 2, year determination, TDD - byline_dept_hits x authorship_edges -> byline_year_evidence.

Implementation layer of red line #3 + red tests #4/#6:
  - the only legitimate source of a year = the (work_id, author_id) join with authorship_edges.publication_year;
  - every (author, dept, year) evidence point must carry a non-empty source_work_ids (traceable to a concrete work - a positive assertion;
    a year point without a work source always raises);
  - pairs in hits that do not join to edges -> the byline_year_mismatch sidecar (not silently dropped);
  - after the join, years all null / nothing joins -> SystemExit(EXIT_BYLINE_YEAR_NULL_FAIL=29);
  - the byline code never touches the OpenAlex author aggregate fields (source-scan guard).
"""
import hashlib
import pathlib

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


def _write_hits(tmp_path, rows):
    t = pa.table({
        "work_id": pa.array([r[0] for r in rows], type=pa.string()),
        "author_id": pa.array([r[1] for r in rows], type=pa.string()),
        "dept_key": pa.array([r[2] for r in rows], type=pa.string()),
        "matched_phrase": pa.array([r[3] for r in rows], type=pa.string()),
        "institution_id": pa.array([r[4] for r in rows], type=pa.string()),
        "match_style": pa.array([r[5] if len(r) > 5 else "printed" for r in rows], type=pa.string()),
    })
    p = tmp_path / "byline_dept_hits.parquet"
    pq.write_table(t, str(p))
    return p


def _write_edges(tmp_path, rows):
    t = pa.table({
        "work_id": pa.array([r[0] for r in rows], type=pa.string()),
        "author_id": pa.array([r[1] for r in rows], type=pa.string()),
        "publication_year": pa.array([r[2] for r in rows], type=pa.int16()),
    })
    d = tmp_path / "authorship_edges"
    d.mkdir(exist_ok=True)
    pq.write_table(t, str(d / "part-00000.parquet"))
    return d


_PHR = "Department of Economics"


def test_year_evidence_join_aggregate_and_traceable(tmp_path):
    from common.schema import BYLINE_YEAR_EVIDENCE
    from roster.byline import build_year_evidence

    hits = _write_hits(tmp_path, [
        ("W1", "A1", "monash_econ", _PHR, "I56590836"),
        ("W2", "A1", "monash_econ", _PHR, "I56590836"),   # second paper in the same year
        ("W3", "A1", "monash_econ", _PHR, None),
        ("W4", "A2", "unsw_econ", "School of Economics", "I31746571"),
    ])
    edges = _write_edges(tmp_path, [
        ("W1", "A1", 2005), ("W2", "A1", 2005), ("W3", "A1", 2008), ("W4", "A2", 2010),
        ("W9", "A9", 1999),  # an edge unrelated to hits, must not leak in
    ])
    out = tmp_path / "out"
    summary = build_year_evidence(hits, edges, out)

    ev = pq.read_table(str(out / "byline_year_evidence.parquet"))
    assert ev.column_names == list(BYLINE_YEAR_EVIDENCE.keys())
    assert ev.schema.field("year").type == pa.int16()
    assert ev.schema.field("n_papers_that_year").type == pa.int32()
    rows = {(r["author_id"], r["dept_key"], r["year"]): r for r in ev.to_pylist()}
    assert rows[("A1", "monash_econ", 2005)]["n_papers_that_year"] == 2
    assert rows[("A1", "monash_econ", 2005)]["n_printed_style"] == 2
    assert rows[("A1", "monash_econ", 2005)]["source_work_ids"] == ["W1", "W2"], "provenance column sort is deterministic"
    assert rows[("A1", "monash_econ", 2008)]["source_work_ids"] == ["W3"]
    assert rows[("A2", "unsw_econ", 2010)]["source_work_ids"] == ["W4"]
    assert all(len(r["source_work_ids"]) > 0 for r in ev.to_pylist()), (
        "red test #4 positive assertion: every year point can be traced to a concrete work_id"
    )
    assert summary["n_year_points"] == 3 and summary["n_mismatch"] == 0


def test_year_evidence_stamped_only_year_point_counted_zero_printed(tmp_path):
    """A stamp-only year point has n_printed_style=0 (the Yves Zenou 1998-2015 shape) - a mechanical count;
    whether it counts as presence evidence is not decided here (identification-adjacent)."""
    from roster.byline import build_year_evidence

    hits = _write_hits(tmp_path, [
        ("W1", "A1", "monash_econ", _PHR, None, "stamped"),
        ("W2", "A1", "monash_econ", _PHR, None, "stamped"),
        ("W3", "A1", "monash_econ", _PHR, None, "printed"),  # the same person has another year in printed form
    ])
    edges = _write_edges(tmp_path, [("W1", "A1", 2003), ("W2", "A1", 2003), ("W3", "A1", 2017)])
    out = tmp_path / "out"
    build_year_evidence(hits, edges, out)
    rows = {(r["author_id"], r["year"]): r for r in
            __import__("pyarrow.parquet", fromlist=["read_table"]).read_table(
                str(out / "byline_year_evidence.parquet")).to_pylist()}
    assert rows[("A1", 2003)]["n_printed_style"] == 0, "stamp-only year points must be identifiable"
    assert rows[("A1", 2003)]["n_papers_that_year"] == 2, "but the points are not deleted (how to use them is a manual decision)"
    assert rows[("A1", 2017)]["n_printed_style"] == 1


def test_year_evidence_unjoinable_hit_goes_to_mismatch_sidecar(tmp_path):
    from roster.byline import build_year_evidence

    hits = _write_hits(tmp_path, [
        ("W1", "A1", "monash_econ", _PHR, None),
        ("W_GHOST", "A1", "monash_econ", _PHR, None),  # not in edges -> upstream inconsistency
    ])
    edges = _write_edges(tmp_path, [("W1", "A1", 2005)])
    out = tmp_path / "out"
    summary = build_year_evidence(hits, edges, out)

    mm = pq.read_table(str(out / "byline_year_mismatch.parquet")).to_pylist()
    assert [(r["work_id"], r["author_id"]) for r in mm] == [("W_GHOST", "A1")], (
        "a hit that cannot be joined goes to the sidecar for manual review, not silently dropped"
    )
    assert summary["n_mismatch"] == 1


def test_year_evidence_all_unjoinable_halts_after_sidecar(tmp_path):
    from roster.byline import build_year_evidence

    hits = _write_hits(tmp_path, [("W_GHOST", "A1", "monash_econ", _PHR, None)])
    edges = _write_edges(tmp_path, [("W1", "A1", 2005)])
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as e:
        build_year_evidence(hits, edges, out)
    assert e.value.code == 29
    assert (out / "byline_year_mismatch.parquet").exists(), "write the diagnostic sidecar before HALT (same discipline as S1)"


def test_year_evidence_deterministic(tmp_path):
    from roster.byline import build_year_evidence

    hits = _write_hits(tmp_path, [
        ("W2", "A1", "monash_econ", _PHR, None),
        ("W1", "A1", "monash_econ", _PHR, None),
    ])
    edges = _write_edges(tmp_path, [("W1", "A1", 2005), ("W2", "A1", 2005)])
    o1, o2 = tmp_path / "o1", tmp_path / "o2"
    build_year_evidence(hits, edges, o1)
    build_year_evidence(hits, edges, o2)
    n = "byline_year_evidence.parquet"
    assert hashlib.sha256((o1 / n).read_bytes()).hexdigest() == hashlib.sha256((o2 / n).read_bytes()).hexdigest()


def test_year_evidence_missing_match_style_column_halts(tmp_path):
    """Adversarial review LOW-8: feeding the old 5-column hits into step 2 would silently leave n_printed_style all 0 -
    schema guard: missing match_style column -> HALT 27 (EXIT_BYLINE_SCHEMA_FAIL)."""
    from roster.byline import build_year_evidence

    t5 = pa.table({
        "work_id": pa.array(["W1"], type=pa.string()),
        "author_id": pa.array(["A1"], type=pa.string()),
        "dept_key": pa.array(["monash_econ"], type=pa.string()),
        "matched_phrase": pa.array([_PHR], type=pa.string()),
        "institution_id": pa.array([None], type=pa.string()),
    })
    hp = tmp_path / "byline_dept_hits.parquet"
    pq.write_table(t5, str(hp))
    edges = _write_edges(tmp_path, [("W1", "A1", 2005)])
    with pytest.raises(SystemExit) as e:
        build_year_evidence(hp, edges, tmp_path / "out")
    assert e.value.code == 27


def test_year_evidence_conflicting_years_tripwire(tmp_path):
    """Adversarial review LOW-3: one (work,author) with two different publication_year values = corrupt upstream,
    never silently last-wins - must raise."""
    from roster.byline import build_year_evidence

    hits = _write_hits(tmp_path, [("W1", "A1", "monash_econ", _PHR, None)])
    edges = _write_edges(tmp_path, [("W1", "A1", 2005), ("W1", "A1", 2007)])
    with pytest.raises(RuntimeError, match="conflict"):
        build_year_evidence(hits, edges, tmp_path / "out")


def test_byline_module_never_touches_author_aggregate_fields():
    """Red line #3 source-level guard: the byline module must never contain OpenAlex author aggregate field names (those are not an employment ledger).
    works_affil's raw_affiliation_strings is legitimate (singular affiliation, no clash)."""
    import roster.byline as B

    src = pathlib.Path(B.__file__).read_text(encoding="utf-8")
    assert "affiliations" not in src, "forbidden field name (author.affiliations — the Yves Zenou 1998 backfill pitfall)"
    assert ".years" not in src, "forbidden .years read (red line #3)"
