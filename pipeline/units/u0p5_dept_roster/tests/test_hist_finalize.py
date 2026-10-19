"""Historical roster finalisation TDD - human review results + printed_only skeleton -> final Table B.

Rules:
  - Only people with verdict in {keep, keep_adjust} enter the roster: if the skeleton has rows -> apply the year corrections +
    human_verified=True + confidence=high (human-checked); if the skeleton has no row (a pure stamp confirmed by the human check,
    e.g. A5086383420) -> synthesise a row with evidence="manual", and the years must come from the human correction (none -> raise loudly).
  - student/parttime/ebs/centre/excluded/uncertain/merge/split -> not in Table B
    (the labels stay in the review results, not lost).
  - official rows are kept as they are (G2); official and raw_affil_year rows for the same (author,dept) coexist;
    the same (author,dept,evidence) may not repeat.
  - Back up the original file before writing the final file; writing goes through write_table_b (the old u0p5 write parameters, do not touch).
"""
import pyarrow.parquet as pq
import pytest


def _official(a, name="Off Person"):
    return {"dept_key": "monash_econ", "author_id": a, "display_name": name,
            "year_start": None, "year_end": None,
            "evidence": "official_roster", "confidence": "high", "human_verified": True}


def _skel(a, ys=2010, ye=2020, name="Skel Person"):
    return {"dept_key": "monash_econ", "author_id": a, "display_name": name,
            "year_start": ys, "year_end": ye,
            "evidence": "raw_affil_year", "confidence": "low", "human_verified": False}


def _rev(a, verdict, ys="", ye="", name="Rev Person"):
    return {"author_id": a, "dept_key": "monash_econ", "display_name": name,
            "verdict": verdict, "year_start_fix": ys, "year_end_fix": ye,
            "role_tag": "", "merge_into": "", "note": ""}


def test_keep_adjust_in_skeleton_gets_fixed_years_and_hv():
    from roster.byline_finalize import build_final_rows

    rows = build_final_rows(
        official_rows=[_official("A_off")],
        skeleton_rows=[_skel("A_zen", 2011, 2025)],
        review_rows=[_rev("A_zen", "keep_adjust", 2016, 2025)],
        dept_key="monash_econ")
    cand = [r for r in rows if r["evidence"] == "raw_affil_year"]
    assert len(cand) == 1
    assert (cand[0]["year_start"], cand[0]["year_end"]) == (2016, 2025), "the reviewed year correction is applied"
    assert cand[0]["human_verified"] is True and cand[0]["confidence"] == "high"
    assert any(r["author_id"] == "A_off" and r["evidence"] == "official_roster" for r in rows)


def test_keep_not_in_skeleton_synthesized_as_manual():
    """Case A5086383420: a person with a pure stamp is confirmed by official records -> a synthesised evidence=manual row."""
    from roster.byline_finalize import build_final_rows

    rows = build_final_rows(
        official_rows=[], skeleton_rows=[],
        review_rows=[_rev("A_pc", "keep_adjust", 2020, 2025, name="Person C")],
        dept_key="monash_econ")
    assert len(rows) == 1
    r = rows[0]
    assert r["evidence"] == "manual" and r["human_verified"] is True
    assert (r["year_start"], r["year_end"]) == (2020, 2025)
    assert r["display_name"] == "Person C"


def test_keep_not_in_skeleton_without_years_raises():
    from roster.byline_finalize import build_final_rows

    with pytest.raises(ValueError, match="year correction"):
        build_final_rows(official_rows=[], skeleton_rows=[],
                         review_rows=[_rev("A_x", "keep")], dept_key="monash_econ")


def test_non_keep_verdicts_do_not_enter_table_b():
    from roster.byline_finalize import build_final_rows

    skel = [_skel(a) for a in ("A_st", "A_pt", "A_ebs", "A_ex", "A_un")]
    rev = [_rev("A_st", "student"), _rev("A_pt", "parttime"), _rev("A_ebs", "ebs_member"),
           _rev("A_ex", "exclude_misattribution"), _rev("A_un", "uncertain_chrome")]
    rows = build_final_rows(official_rows=[], skeleton_rows=skel, review_rows=rev,
                            dept_key="monash_econ")
    assert rows == [], "any non-keep verdict never enters Table B (the label stays in the review results)"


def test_skeleton_rows_without_review_stay_pending_low():
    """An ordinary candidate row that never entered the human-review queue (Q10): keep it in the roster as pending with low confidence? - No.
    The finalised Table B takes only official rows + human-checked rows; unchecked candidates stay in the skeleton file (downstream reads them on demand)."""
    from roster.byline_finalize import build_final_rows

    rows = build_final_rows(official_rows=[_official("A_off")],
                            skeleton_rows=[_skel("A_nobody")],
                            review_rows=[], dept_key="monash_econ")
    assert all(r["author_id"] != "A_nobody" for r in rows), (
        "unreviewed candidates stay out of the official Table B (Q0/Q10; the skeleton file is still kept in full)"
    )


def test_no_duplicate_author_dept_evidence():
    from roster.byline_finalize import build_final_rows

    rows = build_final_rows(
        official_rows=[_official("A_zen", name="Zenou")],
        skeleton_rows=[_skel("A_zen", 2011, 2025, name="Zenou")],
        review_rows=[_rev("A_zen", "keep_adjust", 2016, 2025)],
        dept_key="monash_econ")
    keys = [(r["author_id"], r["dept_key"], r["evidence"]) for r in rows]
    assert len(keys) == len(set(keys)) == 2, "official + raw_affil_year rows both kept, no duplicate"


def test_multiple_none_id_official_rows_are_not_duplicates():
    """Real-data shape: Monash's official roster has 3 people without an id (distinct real people with author_id=None) -
    not duplicates; true duplicates (same id, same evidence) must still raise loudly."""
    from roster.byline_finalize import build_final_rows

    rows = build_final_rows(
        official_rows=[_official(None, name="No Id One"), _official(None, name="No Id Two")],
        skeleton_rows=[], review_rows=[], dept_key="monash_econ")
    assert len(rows) == 2

    with pytest.raises(RuntimeError, match="duplicate"):
        build_final_rows(
            official_rows=[_official("A_dup"), _official("A_dup")],
            skeleton_rows=[], review_rows=[], dept_key="monash_econ")


def test_finalize_idempotent_rerun_on_finalized_file(tmp_path):
    """Idempotent: re-running on an already finalised Table B (re-run after the review results are updated, e.g. A5086383420 2020->2019) -
    official rows are recognised only by evidence=official_roster, human-checked rows are rebuilt from this review, nothing is stacked."""
    from roster.byline_finalize import build_final_rows

    finalized = [
        _official("A_off"),
        dict(_skel("A_zen", 2016, 2025), human_verified=True, confidence="high"),  # already added last time
    ]
    official_only = [r for r in finalized if r["evidence"] == "official_roster"]
    rows = build_final_rows(
        official_rows=official_only,
        skeleton_rows=[_skel("A_zen", 2011, 2025)],
        review_rows=[_rev("A_zen", "keep_adjust", 2016, 2025)],
        dept_key="monash_econ")
    assert len(rows) == 2, "a rerun does not stack"
    zen = [r for r in rows if r["author_id"] == "A_zen"]
    assert len(zen) == 1 and zen[0]["year_start"] == 2016


def test_finalize_writes_backup_then_new_file(tmp_path):
    from roster.byline_finalize import finalize_school_table_b
    from roster.table_b import write_table_b

    old = [_official("A_off")]
    official_path = tmp_path / "dept_roster_panel_monash.parquet"
    write_table_b(old, official_path)
    orig_bytes = official_path.read_bytes()

    new_rows = old + [dict(_skel("A_new", 2016, 2025), human_verified=True,
                           confidence="high")]
    backup_dir = tmp_path / "_backup"
    finalize_school_table_b(new_rows, official_path, backup_dir=backup_dir)

    assert (backup_dir / "dept_roster_panel_monash.parquet").read_bytes() == orig_bytes, (
        "the original file must be backed up byte-identical before finalizing"
    )
    back = pq.read_table(str(official_path)).to_pylist()
    assert len(back) == 2 and any(r["author_id"] == "A_new" for r in back)


def test_finalize_second_run_preserves_first_prefinalize_backup(tmp_path):
    """A15: a second finalisation (re-run after updated review results) must never overwrite the one original pre-finalisation backup.
    A fixed-name copy2 would, on the second run, overwrite that clean pre-finalize original with the "already finalised file" -> the rollback anchor is lost.
    After the fix: the first original's bytes never change; the current (finalised) file is saved as a secondary backup, not silently dropped."""
    from roster.byline_finalize import finalize_school_table_b
    from roster.table_b import write_table_b

    official_path = tmp_path / "dept_roster_panel_monash.parquet"
    write_table_b([_official("A_off")], official_path)
    prefinalize_bytes = official_path.read_bytes()
    backup_dir = tmp_path / "_backup"
    canonical = backup_dir / "dept_roster_panel_monash.parquet"

    # first finalisation (adds A_z@2016)
    finalize_school_table_b(
        [_official("A_off"), dict(_skel("A_z", 2016, 2025), human_verified=True, confidence="high")],
        official_path, backup_dir=backup_dir)
    assert canonical.read_bytes() == prefinalize_bytes, "the first backup = the clean pre-finalize original"

    # second finalisation (updated review: A_z year 2016->2015; official_path is now the finalised file)
    finalize_school_table_b(
        [_official("A_off"), dict(_skel("A_z", 2015, 2025), human_verified=True, confidence="high")],
        official_path, backup_dir=backup_dir)

    # A15 core: the one pre-finalize original is still there, not overwritten
    assert canonical.read_bytes() == prefinalize_bytes, (
        "a second finalize overwrote the only pre-finalize backup (A15)"
    )
    # and the current (finalised) file is not silently dropped - a secondary backup was saved
    others = [p for p in backup_dir.iterdir() if p.name != canonical.name]
    assert others, "a second finalize should save the current file as a secondary backup (no silent loss)"


def test_finalize_refuses_without_backup_dir(tmp_path):
    from roster.byline_finalize import finalize_school_table_b
    from roster.table_b import write_table_b

    official_path = tmp_path / "dept_roster_panel_monash.parquet"
    write_table_b([_official("A_off")], official_path)
    with pytest.raises(TypeError):
        finalize_school_table_b([_official("A_off")], official_path)  # missing backup_dir keyword
