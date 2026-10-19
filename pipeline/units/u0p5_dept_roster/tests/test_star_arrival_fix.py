"""Applying the human-check corrections to Table B (per-person check of 15 star arrival years) - star_arrival_fix TDD.

In plain words: the corrections follow the evidence - year_start of 6 people is changed to the evidence year
(human_verified=True + evidence records the human_verified_web source), and the part-timer Person SF3 is tagged part-time under Q3
(row kept + evidence tagged, row not physically deleted). Writing follows the earlier precedent:
back up the current file first (A15 writes only the first copy), emit a new version directory, never overwrite an existing one.
The "local transfer, not a foreign poach" call does not touch roster rows (it belongs to the U4 is_foreign_poach consumer side).
"""
import json

import pyarrow.parquet as pq
import pytest

from roster.star_arrival_fix import (
    apply_star_fixes,
    main_star_fix,
    write_versioned_roster,
)


def _row(aid, name, *, dept="monash_econ", ys=None, ye=None,
         evidence="official_roster", conf="high", hv=False):
    return {"dept_key": dept, "author_id": aid, "display_name": name,
            "year_start": ys, "year_end": ye, "evidence": evidence,
            "confidence": conf, "human_verified": hv}


def _sample_rows():
    return [
        _row("A_S1", "Person SF1", ys=2016, ye=2025),                 # the year must change to 2021
        _row("A_KEEP", "Untouched Person", ys=2003, ye=2020),             # not in the corrections
        _row("A_ADJ", "Person SF3", ys=2017, ye=2025),                 # Q3 part-time tag
        _row("A_YR", "Person SF2", dept="unsw_econ", hv=True),            # UNSW missing year -> filled with the human-checked year
    ]


def _year_fixes():
    return {
        "A_S1": {"dept_key": "monash_econ", "year_start": 2021,
                  "evidence": "human_verified_web:CV/Wayback — test evidence (2021-)"},
        "A_YR": {"dept_key": "unsw_econ", "year_start": 2019,
                 "evidence": "human_verified_web:CV/Wayback — test evidence (2019-)"},
    }


def _adjunct_flags():
    return {"A_ADJ": {"dept_key": "monash_econ",
                      "note": "adjunct_q3: test note"}}


# ---- pure function: apply_star_fixes -------------------------------------------------

def test_year_fix_sets_year_hv_conf_and_evidence():
    """Year correction: year_start=evidence year + human_verified=True + confidence=high +
    evidence replaced by a human_verified_web string; other rows untouched."""
    res = apply_star_fixes(_sample_rows(), year_fixes=_year_fixes(),
                           adjunct_flags=_adjunct_flags())
    by = {r["author_id"]: r for r in res["rows"]}
    assert by["A_S1"]["year_start"] == 2021
    assert by["A_S1"]["human_verified"] is True
    assert by["A_S1"]["confidence"] == "high"
    assert by["A_S1"]["evidence"].startswith("human_verified_web:")
    assert by["A_S1"]["year_end"] == 2025          # year_end is outside the correction, untouched
    # UNSW missing-year row -> directly set to the human-checked year (the original None came from the fallback rule)
    assert by["A_YR"]["year_start"] == 2019 and by["A_YR"]["human_verified"] is True
    # rows not in the corrections stay as they are, field by field
    assert by["A_KEEP"] == _sample_rows()[1]


def test_year_fix_unknown_author_raises():
    """fail-loud: an author_id in the correction list is not found in the roster -> ValueError naming it (never silently skip the fix)."""
    fixes = {"A_TYPO": {"dept_key": "monash_econ", "year_start": 2020,
                        "evidence": "human_verified_web:CV"}}
    with pytest.raises(ValueError, match="A_TYPO"):
        apply_star_fixes(_sample_rows(), year_fixes=fixes, adjunct_flags={})


def test_year_fix_wrong_dept_raises():
    """fail-loud: author_id is present but dept_key does not match (correction attached to the wrong department) -> ValueError."""
    fixes = {"A_S1": {"dept_key": "unsw_econ", "year_start": 2021,
                       "evidence": "human_verified_web:CV"}}
    with pytest.raises(ValueError, match="A_S1"):
        apply_star_fixes(_sample_rows(), year_fixes=fixes, adjunct_flags={})


def test_year_fix_ambiguous_two_rows_raises():
    """fail-loud: the same (author_id, dept_key) hits 2 rows (dirty roster) -> ValueError, do not guess which row."""
    rows = _sample_rows() + [_row("A_S1", "Person SF1 dup", ys=2010)]
    with pytest.raises(ValueError, match="A_S1"):
        apply_star_fixes(rows, year_fixes=_year_fixes(), adjunct_flags={})


def test_adjunct_flag_appends_evidence_keeps_row_and_year():
    """Q3 part-time tag: append a note to evidence (machine-searchable 'adjunct_q3'), keep the row (no physical delete),
    year_start / human_verified untouched (2017 is a contaminated year, never stamped as human-checked)."""
    res = apply_star_fixes(_sample_rows(), year_fixes={},
                           adjunct_flags=_adjunct_flags())
    by = {r["author_id"]: r for r in res["rows"]}
    assert len(res["rows"]) == len(_sample_rows())          # row count unchanged
    assert "adjunct_q3" in by["A_ADJ"]["evidence"]
    assert by["A_ADJ"]["evidence"].startswith("official_roster")   # original evidence kept, traceable
    assert by["A_ADJ"]["year_start"] == 2017                # year untouched
    assert by["A_ADJ"]["human_verified"] is False           # contaminated year never stamped as human-checked


def test_apply_report_lists_old_and_new():
    """Application report: every correction records old -> new (auditable)."""
    res = apply_star_fixes(_sample_rows(), year_fixes=_year_fixes(),
                           adjunct_flags=_adjunct_flags())
    rep = {r["author_id"]: r for r in res["report"]["year_fixes_applied"]}
    assert rep["A_S1"]["old_year_start"] == 2016
    assert rep["A_S1"]["new_year_start"] == 2021
    assert rep["A_YR"]["old_year_start"] is None
    assert res["report"]["adjunct_flagged"] == ["A_ADJ"]


# ---- writing: write_versioned_roster (back up first + new version, never overwrite an existing one) -------------

def _canonical(tmp_path):
    """Build the current two-school parquet files (canonical), return {dept: path}."""
    from roster.table_b import write_table_b
    mon = tmp_path / "u0p5_roster" / "dept_roster_panel_monash.parquet"
    uns = tmp_path / "u0p5_roster" / "dept_roster_panel_unsw.parquet"
    rows = _sample_rows()
    write_table_b([r for r in rows if r["dept_key"] == "monash_econ"], mon)
    write_table_b([r for r in rows if r["dept_key"] == "unsw_econ"], uns)
    return {"monash_econ": mon, "unsw_econ": uns}


def test_write_versioned_roster_backup_plus_new_version(tmp_path):
    """Three write guarantees: ① the current file is backed up into backup_dir (bytes as is) and the current file is untouched;
    ② the new version goes into version_dir (deterministic parquet, 8-column schema); ③ re-running is idempotent (same content does not raise)."""
    cur = _canonical(tmp_path)
    fixed = apply_star_fixes(_sample_rows(), year_fixes=_year_fixes(),
                             adjunct_flags=_adjunct_flags())
    vdir = tmp_path / "u0p5_roster" / "roster_v2026-07-10_starfix"
    bdir = tmp_path / "u0p5_roster" / "_backup_2026-07-10_pre_starfix"
    cur_bytes = {k: p.read_bytes() for k, p in cur.items()}

    s1 = write_versioned_roster(fixed["rows"], version_dir=vdir, backup_dir=bdir,
                                current_paths=cur)
    # ① backup present + current file untouched
    for dept, p in cur.items():
        assert (bdir / p.name).read_bytes() == cur_bytes[dept]
        assert p.read_bytes() == cur_bytes[dept]
    # ② new version present and the year fixed
    new_mon = pq.read_table(str(vdir / "dept_roster_panel_monash.parquet")).to_pylist()
    by = {r["author_id"]: r for r in new_mon}
    assert by["A_S1"]["year_start"] == 2021 and by["A_S1"]["human_verified"] is True
    assert "adjunct_q3" in by["A_ADJ"]["evidence"]
    new_uns = pq.read_table(str(vdir / "dept_roster_panel_unsw.parquet")).to_pylist()
    assert {r["author_id"]: r for r in new_uns}["A_YR"]["year_start"] == 2019
    # ③ idempotent re-run: same content -> no raise, the backup is not overwritten
    s2 = write_versioned_roster(fixed["rows"], version_dir=vdir, backup_dir=bdir,
                                current_paths=cur)
    assert s2["backup_created"] is False and s1["backup_created"] is True


def test_write_versioned_roster_divergent_existing_version_raises(tmp_path):
    """The new-version slot is occupied by other content -> raise loudly (never overwrite an existing one, the SSD write rule)."""
    cur = _canonical(tmp_path)
    fixed = apply_star_fixes(_sample_rows(), year_fixes=_year_fixes(),
                             adjunct_flags=_adjunct_flags())
    vdir = tmp_path / "u0p5_roster" / "roster_v2026-07-10_starfix"
    bdir = tmp_path / "u0p5_roster" / "_backup_2026-07-10_pre_starfix"
    vdir.mkdir(parents=True)
    (vdir / "dept_roster_panel_monash.parquet").write_bytes(b"someone else's bytes")
    with pytest.raises(ValueError, match="never overwrite"):
        write_versioned_roster(fixed["rows"], version_dir=vdir, backup_dir=bdir,
                               current_paths=cur)


def test_write_versioned_roster_canonical_changed_after_backup_raises(tmp_path):
    """The backup already exists but the current file was changed later (sha differs) -> raise loudly for a human to check (the backup anchor is not silently displaced)."""
    from roster.table_b import write_table_b
    cur = _canonical(tmp_path)
    fixed = apply_star_fixes(_sample_rows(), year_fixes=_year_fixes(),
                             adjunct_flags=_adjunct_flags())
    vdir = tmp_path / "u0p5_roster" / "roster_v2026-07-10_starfix"
    bdir = tmp_path / "u0p5_roster" / "_backup_2026-07-10_pre_starfix"
    write_versioned_roster(fixed["rows"], version_dir=vdir, backup_dir=bdir,
                           current_paths=cur)
    # the current file was touched by a third party
    write_table_b([_row("A_NEW", "Sneaky Edit", ys=1999)], cur["monash_econ"])
    with pytest.raises(ValueError, match="backup"):
        write_versioned_roster(fixed["rows"], version_dir=vdir, backup_dir=bdir,
                               current_paths=cur)


# ---- end to end: main_star_fix (read the corrections JSON -> apply -> write a new version + summary) -----------

def test_main_star_fix_end_to_end(tmp_path):
    """Thin assembly end to end: corrections JSON (annotations format) -> current parquet of both schools ->
    new version + backup + summary sidecar; poach_dispositions do not touch roster rows (they belong to U4)."""
    cur = _canonical(tmp_path)
    ann = {
        "date": "2026-07-10",
        "authorized_by": "2026-07-10 人工裁定「按证据改」(测试夹具)",
        "year_start_fixes": {
            "A_S1": {"dept_key": "monash_econ", "display_name": "Person SF1",
                      "old_year_start": 2016, "year_start": 2021,
                      "evidence": "human_verified_web:test evidence (2021-)",
                      "url": "https://example.org/cv"},
            "A_YR": {"dept_key": "unsw_econ", "display_name": "Person SF2",
                     "old_year_start": None, "year_start": 2019,
                     "evidence": "human_verified_web:test evidence (2019-)",
                     "url": "https://example.org/evidence"},
        },
        "identity_dispositions": {
            "A_ADJ": {"dept_key": "monash_econ", "display_name": "Person SF3",
                      "disposition": "adjunct_q3_not_incumbent",
                      "exclude_from_candidates": True,
                      "note": "adjunct_q3: test note"},
        },
        "poach_dispositions": {
            "A_ANY": {"dept_key": "monash_econ", "prior_au_employment": True,
                      "is_foreign_poach": False, "note": "本地转入"},
        },
    }
    ann_path = tmp_path / "u0p5_roster" / "roster_fix_2026-07-10_star_arrival_annotations.json"
    ann_path.write_text(json.dumps(ann, ensure_ascii=False), encoding="utf-8")

    vdir = tmp_path / "u0p5_roster" / "roster_v2026-07-10_starfix"
    bdir = tmp_path / "u0p5_roster" / "_backup_2026-07-10_pre_starfix"
    summary = main_star_fix(annotations_path=ann_path, current_paths=cur,
                            version_dir=vdir, backup_dir=bdir)

    new_mon = {r["author_id"]: r for r in pq.read_table(
        str(vdir / "dept_roster_panel_monash.parquet")).to_pylist()}
    assert new_mon["A_S1"]["year_start"] == 2021
    assert new_mon["A_S1"]["evidence"].startswith("human_verified_web:")
    assert "https://example.org/cv" in new_mon["A_S1"]["evidence"]   # requirement: both the source and the URL go into evidence
    assert "adjunct_q3" in new_mon["A_ADJ"]["evidence"]
    # poach dispositions do not touch roster rows
    assert "A_ANY" not in new_mon or new_mon["A_ANY"]["evidence"] == "official_roster"
    # the summary sidecar is written into the version directory
    sj = json.loads((vdir / "summary_starfix_2026-07-10.json").read_text("utf-8"))
    assert sj["n_year_fixes"] == 2 and sj["n_adjunct_flagged"] == 1
    assert sj["annotations_sha256"] and sj["authorized_by"].startswith("2026-07-10 人工裁定")
    assert summary["rows_by_school"]["monash_econ"] == 3
    assert summary["rows_by_school"]["unsw_econ"] == 1
