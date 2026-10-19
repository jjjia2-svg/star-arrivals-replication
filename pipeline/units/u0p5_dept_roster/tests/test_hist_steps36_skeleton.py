"""Historical roster steps 3-6 TDD - strict subfield filter (flag, don't delete) / fold persons / threshold / interval recovery of leavers.

Rule discipline (fixed rules or mechanical steps only, no discretionary choices):
  - G5: main subfield rule = 2002 Economics and Econometrics; a miss **lowers confidence, never deletes**
    (in this batch all rows have confidence=low + the share goes into stats; the rule to raise to medium is left to the step 7 quality gate).
  - Q1: department member criterion = the department has >=2 distinct years - the value comes only from
    require("roster","dept_membership_min"), pure functions take an explicit parameter.
  - Step 4a: the threshold is judged at the person level (U2 person_map folds persons), so a prolific author split across several ids is not wrongly filtered out (red test #13);
    Table B / skeleton rows still use the raw author_id (red test #11).
  - Step 5: a leaver's year_end = the last byline year (never filled with 2025); a missing year stays empty, not filled with 0 (red tests #5/#10).
  - How stamped strings are used is left open -> evidence_rule is a required parameter ("all"/"printed_only"), with no default;
    the runner produces both rules in parallel.
"""
import hashlib

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


# -- Normaliser (red test #9: int 2002 / "2002" / "subfields/2002" / URL -> "2002") ----
def test_norm_subfield_dual_format():
    from roster.byline_skeleton import norm_subfield_id

    assert norm_subfield_id(2002) == "2002"
    assert norm_subfield_id("2002") == "2002"
    assert norm_subfield_id("subfields/2002") == "2002"
    assert norm_subfield_id("https://openalex.org/subfields/2002") == "2002"
    assert norm_subfield_id(None) is None


def test_econ_subfields_consumed_from_signed_redline():
    """Sentinel note 1: the subfield whitelist is consumed from require("subfield_whitelist","include"),
    one single source - when the YAML changes this follows automatically, no hard-coded copy is left."""
    from common._redlines import require
    from roster.byline_skeleton import ECON_SUBFIELDS

    assert ECON_SUBFIELDS == set(require("subfield_whitelist", "include"))


# -- Fixture for the pure function build_skeleton_rows ---------------------------------
def _hit(w, a, dk, style="printed"):
    return {"work_id": w, "author_id": a, "dept_key": dk, "match_style": style}


def _base_inputs():
    """A_keep: two years 2005/2008 -> passes the threshold; A_one: only one year 2010 -> fails;
    A_f1+A_f2: two fragments of the same person P_STAR, one year each -> merged at person level, passes the threshold (red test #13);
    A_left: 2003/2005 and nothing after -> leaver with year_end=2005 (red test #10)."""
    hits = [
        _hit("W1", "A_keep", "monash_econ"), _hit("W2", "A_keep", "monash_econ"),
        _hit("W3", "A_one", "monash_econ"),
        _hit("W4", "A_f1", "monash_econ"), _hit("W5", "A_f2", "monash_econ"),
        _hit("W6", "A_left", "unsw_econ"), _hit("W7", "A_left", "unsw_econ"),
    ]
    year_by_pair = {("W1", "A_keep"): 2005, ("W2", "A_keep"): 2008,
                    ("W3", "A_one"): 2010,
                    ("W4", "A_f1"): 2016, ("W5", "A_f2"): 2019,
                    ("W6", "A_left"): 2003, ("W7", "A_left"): 2005}
    subfield_by_work = {"W1": "2002", "W2": "2003", "W3": "2002",
                        "W4": "2002", "W5": "2002", "W6": "2002", "W7": None}
    person_of = {"A_keep": "P_keep", "A_one": "P_one",
                 "A_f1": "P_STAR", "A_f2": "P_STAR", "A_left": "P_left"}
    return hits, year_by_pair, subfield_by_work, person_of


def _build(evidence_rule="all", membership_min=2, **kw):
    from roster.byline_skeleton import build_skeleton_rows

    hits, ybp, sbw, pof = _base_inputs()
    return build_skeleton_rows(
        kw.get("hits", hits), kw.get("year_by_pair", ybp),
        kw.get("subfield_by_work", sbw), kw.get("person_of", pof),
        evidence_rule=evidence_rule, membership_min=membership_min,
    )


def test_membership_min_judged_at_person_level_oversplit_star_kept():
    """Red test #13: fragments with 1 year each, 2 years at person level -> both fragment rows enter the skeleton (a prolific author split across several ids is not wrongly filtered out)."""
    skeleton, stats, summary = _build()
    by_a = {r["author_id"]: r for r in skeleton}
    assert "A_f1" in by_a and "A_f2" in by_a
    assert by_a["A_f1"]["year_start"] == 2016 and by_a["A_f1"]["year_end"] == 2016
    assert by_a["A_f2"]["year_start"] == 2019 and by_a["A_f2"]["year_end"] == 2019


def test_below_threshold_person_excluded_but_visible_in_stats():
    skeleton, stats, summary = _build()
    assert all(r["author_id"] != "A_one" for r in skeleton), "a single-year person does not pass the fixed threshold"
    st = {(r["author_id"], r["dept_key"]): r for r in stats}
    assert st[("A_one", "monash_econ")]["qualified"] is False, "not in the skeleton but visible in stats, not silently dropped"
    assert st[("A_keep", "monash_econ")]["qualified"] is True


def test_departed_year_end_is_last_byline_not_2025():
    """Red test #10: a leaver's year_end = the last byline year 2005, never filled with 2025."""
    skeleton, _, _ = _build()
    left = next(r for r in skeleton if r["author_id"] == "A_left")
    assert left["year_start"] == 2003 and left["year_end"] == 2005


def test_gap_years_marked_not_zero_filled():
    """Red test #5: A_keep 2005/2008 -> interval [2005,2008] + gap years 2006/2007 recorded in stats,
    never create rows for missing years."""
    skeleton, stats, _ = _build()
    keep = next(r for r in skeleton if r["author_id"] == "A_keep")
    assert keep["year_start"] == 2005 and keep["year_end"] == 2008
    st = next(r for r in stats if r["author_id"] == "A_keep")
    assert st["gap_years"] == [2006, 2007]
    assert len(skeleton) == len({(r["author_id"], r["dept_key"]) for r in skeleton}), "one person, one department, one row"


def test_skeleton_row_shape_is_table_b_8cols_raw_id():
    """Red test #11: skeleton row = the 8 Table B columns; author_id is a raw bare id (does not start with P_);
    evidence=raw_affil_year, confidence=low, human_verified=False (Q10)."""
    from common.schema import BYLINE_ROSTER_SKELETON

    skeleton, _, _ = _build()
    for r in skeleton:
        assert set(r.keys()) == set(BYLINE_ROSTER_SKELETON.keys())
        assert not r["author_id"].startswith("P_")
        assert r["evidence"] == "raw_affil_year"
        assert r["confidence"] == "low"
        assert r["human_verified"] is False


def test_subfield_noncompliant_flagged_not_deleted():
    """G5 semantics: a subfield that misses 2002 -> lower confidence, do not delete. A_keep's W2 is 2003 (Finance) ->
    the row is kept, stats record share=0.5."""
    skeleton, stats, _ = _build()
    assert any(r["author_id"] == "A_keep" for r in skeleton)
    st = next(r for r in stats if r["author_id"] == "A_keep")
    assert st["n_works"] == 2 and st["subfield_2002_works"] == 1
    assert abs(st["subfield_2002_share"] - 0.5) < 1e-9


def test_evidence_rule_required_no_default():
    """Stamp usage is left open -> evidence_rule is required, no default (prevents a rule choice from slipping in silently)."""
    from roster.byline_skeleton import build_skeleton_rows

    hits, ybp, sbw, pof = _base_inputs()
    with pytest.raises(TypeError):
        build_skeleton_rows(hits, ybp, sbw, pof, membership_min=2)  # missing evidence_rule
    with pytest.raises(ValueError):
        build_skeleton_rows(hits, ybp, sbw, pof, evidence_rule="whatever", membership_min=2)


def test_printed_only_rule_drops_stamped_only_years():
    """printed_only rule: stamp-only years do not count towards the threshold/interval (Yves Zenou 1998 shape).
    A_st: 2003 stamped + 2016/2017 printed -> all rule [2003,2017]; printed_only [2016,2017]."""
    hits = [
        _hit("W1", "A_st", "monash_econ", style="stamped"),
        _hit("W2", "A_st", "monash_econ", style="printed"),
        _hit("W3", "A_st", "monash_econ", style="printed"),
    ]
    ybp = {("W1", "A_st"): 2003, ("W2", "A_st"): 2016, ("W3", "A_st"): 2017}
    sbw = {"W1": "2002", "W2": "2002", "W3": "2002"}
    pof = {"A_st": "P_st"}
    sk_all, _, _ = _build(hits=hits, year_by_pair=ybp, subfield_by_work=sbw, person_of=pof,
                          evidence_rule="all")
    sk_pr, _, _ = _build(hits=hits, year_by_pair=ybp, subfield_by_work=sbw, person_of=pof,
                         evidence_rule="printed_only")
    a = next(r for r in sk_all if r["author_id"] == "A_st")
    p = next(r for r in sk_pr if r["author_id"] == "A_st")
    assert (a["year_start"], a["year_end"]) == (2003, 2017)
    assert (p["year_start"], p["year_end"]) == (2016, 2017)


def test_author_missing_from_person_map_identity_fallback_flagged():
    """An author not covered by person_map (outside A*) -> treated as their own person (not silently dropped), flagged in stats."""
    hits = [_hit("W1", "A_out", "monash_econ"), _hit("W2", "A_out", "monash_econ")]
    ybp = {("W1", "A_out"): 2005, ("W2", "A_out"): 2007}
    sbw = {"W1": "2002", "W2": "2002"}
    skeleton, stats, summary = _build(hits=hits, year_by_pair=ybp, subfield_by_work=sbw,
                                      person_of={})
    assert any(r["author_id"] == "A_out" for r in skeleton)
    st = next(r for r in stats if r["author_id"] == "A_out")
    assert st["in_person_map"] is False
    assert summary["n_authors_outside_person_map"] == 1


def test_unyeared_counted_per_pair_not_per_row():
    """Adversarial review MED-1: one undated (work,author) pair with several hits rows (several phrases/styles) ->
    n_unyeared_pairs counts 1 per [pair], not inflated per row (a reproducibility field, must be fixed before the 11 schools)."""
    hits = [
        _hit("W_NY", "A1", "monash_econ"),
        {"work_id": "W_NY", "author_id": "A1", "dept_key": "monash_econ",
         "match_style": "stamped"},
        _hit("W_NY", "A1", "unsw_econ"),
        _hit("W1", "A1", "monash_econ"), _hit("W2", "A1", "monash_econ"),
    ]
    ybp = {("W1", "A1"): 2005, ("W2", "A1"): 2008}
    _, _, summary = _build(hits=hits, year_by_pair=ybp,
                           subfield_by_work={"W1": "2002", "W2": "2002"},
                           person_of={"A1": "P1"})
    assert summary["n_unyeared_pairs"] == 1


def test_null_author_hits_skipped_and_counted():
    """Adversarial review LOW-1: hits with author_id=None (28 rows in the real data) are explicitly intercepted at this layer -
    not in the skeleton/stats, counted in the summary, not relying on an upstream coincidence as the guard."""
    hits = [
        {"work_id": "W_N", "author_id": None, "dept_key": "monash_econ",
         "match_style": "printed"},
        _hit("W1", "A1", "monash_econ"), _hit("W2", "A1", "monash_econ"),
    ]
    ybp = {("W1", "A1"): 2005, ("W2", "A1"): 2008, ("W_N", None): 2005}
    skeleton, stats, summary = _build(hits=hits, year_by_pair=ybp,
                                      subfield_by_work={"W1": "2002", "W2": "2002"},
                                      person_of={"A1": "P1"})
    assert all(r["author_id"] is not None for r in skeleton)
    assert all(r["author_id"] is not None for r in stats)
    assert summary["n_null_author_hits"] == 1


def test_write_skeleton_deterministic_and_schema(tmp_path):
    """Red test #19 + write: two writes are byte-equal; skeleton has 8 columns, column order = schema key order; stats are equally deterministic."""
    from roster.byline_skeleton import write_skeleton
    from common.schema import BYLINE_ROSTER_SKELETON

    skeleton, stats, _ = _build()
    o1, o2 = tmp_path / "o1", tmp_path / "o2"
    write_skeleton(skeleton, stats, o1, suffix="all")
    write_skeleton(skeleton, stats, o2, suffix="all")
    for name in ("byline_roster_skeleton_all.parquet", "byline_skeleton_stats_all.parquet"):
        b1, b2 = (o1 / name).read_bytes(), (o2 / name).read_bytes()
        assert hashlib.sha256(b1).hexdigest() == hashlib.sha256(b2).hexdigest()
    sk = pq.read_table(str(o1 / "byline_roster_skeleton_all.parquet"))
    assert sk.column_names == list(BYLINE_ROSTER_SKELETON.keys())
    assert sk.schema.field("year_start").type == pa.int16()
    meta = pq.ParquetFile(str(o1 / "byline_roster_skeleton_all.parquet")).metadata.metadata or {}
    assert b"ARROW:schema" not in meta


def test_display_name_filled_via_lookup_none_when_missing():
    skeleton, _, _ = _build()
    from roster.byline_skeleton import fill_display_names

    filled = fill_display_names(skeleton, {"A_keep": "Keep, Kate"})
    by_a = {r["author_id"]: r for r in filled}
    assert by_a["A_keep"]["display_name"] == "Keep, Kate"
    assert by_a["A_left"]["display_name"] is None, "a name that cannot be found stays None, no name is made up (spirit of red line #1)"


def test_year_evidence_reconstruction_matches_pairs(tmp_path):
    """The runner rebuilds (work,author)->year from the written hits+evidence, without rescanning 79 million edges:
    evidence.source_work_ids contains work -> year. The provenance column of red test #4 is used here."""
    from roster.byline_skeleton import year_by_pair_from_evidence

    ev = pa.table({
        "author_id": pa.array(["A1", "A1"], type=pa.string()),
        "dept_key": pa.array(["monash_econ"] * 2, type=pa.string()),
        "year": pa.array([2005, 2008], type=pa.int16()),
        "n_papers_that_year": pa.array([2, 1], type=pa.int32()),
        "n_printed_style": pa.array([2, 1], type=pa.int32()),
        "source_work_ids": pa.array([["W1", "W2"], ["W3"]], type=pa.list_(pa.string())),
    })
    p = tmp_path / "byline_year_evidence.parquet"
    pq.write_table(ev, str(p))
    ybp = year_by_pair_from_evidence(p)
    assert ybp == {("W1", "A1"): 2005, ("W2", "A1"): 2005, ("W3", "A1"): 2008}
