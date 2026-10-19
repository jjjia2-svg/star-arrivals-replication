"""Table B v2 backfill TDD - affil_type + year_start_provenance promoted to structured columns.

In plain words:
  root cause D: affil_type lived only inside the evidence string -> make it a machine-filterable column;
  root cause E: the source of the arrival year could not be traced -> a year_start_provenance source sub-label column.

Hard rules:
  - Purely mechanical backfill: only **infer** from the existing evidence string; if it cannot be inferred -> conservatively record unknown /
    dept_only (the default entry path), never invent new facts (the identification layer decides nothing);
  - the 8-column base passes through field by field verbatim, the year columns are untouched (red line #3);
  - frozen files are read-only; new output goes to a new dated directory (the caller's job), same content is idempotent, different content fails loudly.
"""
import pathlib

import pytest

from common.schema import DEPT_ROSTER_PANEL_V2
from roster.panel_v2 import (
    backfill_panel_v2,
    infer_affil_type,
    infer_year_start_provenance,
    to_table_b_row_v2,
    upgrade_row_to_v2,
    write_table_b_v2,
)
from roster.table_b import write_table_b

# --- evidence string samples (in the format of the frozen registry_v3 two-school panel, personal descriptions neutralised) ----
EV_CENTRE_BIO = ("centre_roster:CHE|affil_type=centre_only"
                 "|年段:2022 – 现在（bio：2022 入 Monash；2022-05 不在 → 2022-10 在列；RePEc 现登"
                 "|src:http://web.archive.org/web/20221004033953/...|批2026-07-11")
EV_CENTRE_SNAP = ("centre_roster:是。2016 'Ms' Research Fel|affil_type=centre_only"
                  "|年段:2016-03 快照在列（离册区间 2016-03–2019-04）"
                  "|src:http://web.archive.org/web/20160317052828/...|批2026-07-11")
EV_CENTRE_EST = ("centre_roster:是。2016 'Ms' Research Fel|affil_type=centre_only"
                 "|年段:估2015–今（OpenAlex Monash 段 2015-2024）"
                 "|src:http://web.archive.org/web/20160317052828/...|批2026-07-11")
EV_DEPT_RED_DOT = ("dept_history_web:研究实验室 PI|affil_type=both"
                   "|年段:2008-至今在职（2008-08 buseco econ 档案页原话：joined Monash "
                   "|src:http://web.archive.org/web/20080801063506/...|批2026-07-11")
EV_HV_WEB = "human_verified_web:ORCID 就业栏 — '2018–2022 Monash CHE, Research Fellow'"
EV_WAYBACK_HV = ("wayback_snapshot|hv:2026-07-12边界裁决_收;唯一真经济学家(经济学PhD)"
                 "|src:design_notes/.../2026-07-12_discipline_boundary_ruling.md")   # record not shipped


def _v1_row(name="Alice Econ", *, aid="A5000000001", ys=2005, ye=2010,
            evidence="official_roster", conf="high", hv=False, dept="monash_econ"):
    return {"dept_key": dept, "author_id": aid, "display_name": name,
            "year_start": ys, "year_end": ye, "evidence": evidence,
            "confidence": conf, "human_verified": hv}


# ═══ infer_affil_type - mechanical backfill from the evidence string ═══════════════════════════
def test_affil_type_centre_only_from_tag():
    assert infer_affil_type(EV_CENTRE_BIO) == "centre_only"


def test_affil_type_both_from_tag():
    assert infer_affil_type(EV_DEPT_RED_DOT) == "both"


def test_affil_type_default_dept_only_when_no_tag():
    """No tag = entered the roster via the department roster/byline/manual path -> dept_only (the centre backfill is the only path that writes a tag)."""
    for ev in ("official_roster", "raw_affil_year", "manual",
               "wayback_snapshot", EV_HV_WEB, EV_WAYBACK_HV):
        assert infer_affil_type(ev) == "dept_only"


def test_affil_type_explicit_dept_only_tag():
    assert infer_affil_type("x|affil_type=dept_only|y") == "dept_only"


def test_affil_type_unrecognized_tag_fails_loud():
    with pytest.raises(ValueError, match="affil_type"):
        infer_affil_type("centre_roster:X|affil_type=banana|年段:2020")


# ═══ infer_year_start_provenance - conservative inference, cannot infer = unknown ════════════════
def test_provenance_none_year_is_unknown():
    assert infer_year_start_provenance(EV_CENTRE_BIO, None) == "unknown"


def test_provenance_hv_web_is_bio_stated():
    assert infer_year_start_provenance(EV_HV_WEB, 2018) == "bio_stated"


def test_provenance_centre_bio_marker_wins_over_snapshot_marker():
    """A year span with both a bio statement + snapshot presence -> bio takes priority (the year value comes from the stated bio)."""
    assert infer_year_start_provenance(EV_CENTRE_BIO, 2022) == "bio_stated"


def test_provenance_centre_snapshot_marker():
    assert infer_year_start_provenance(EV_CENTRE_SNAP, 2016) == "snapshot_first_seen"


def test_provenance_centre_estimate_is_unknown():
    """A year inferred by an 'estimated ...' OpenAlex segment -> neither a stated arrival nor first seen in a snapshot -> unknown (not passed off as either)."""
    assert infer_year_start_provenance(EV_CENTRE_EST, 2015) == "unknown"


def test_provenance_wayback_snapshot_base():
    assert infer_year_start_provenance("wayback_snapshot", 2003) == "snapshot_first_seen"
    # a '|hv:' suffix marking an accepted boundary case only checks identity, the year column stays unchanged -> the provenance label is not flipped
    assert infer_year_start_provenance(EV_WAYBACK_HV, 2003) == "snapshot_first_seen"


def test_provenance_official_roster_is_unknown():
    """official_roster year = the Pure active-publication interval, not a stated arrival (root cause E 'no basis') -> unknown."""
    assert infer_year_start_provenance("official_roster", 2002) == "unknown"


def test_provenance_manual_and_raw_affil_are_unknown():
    assert infer_year_start_provenance("manual", 2023) == "unknown"
    assert infer_year_start_provenance("raw_affil_year", 2016) == "unknown"


# ═══ upgrade_row_to_v2 - pure function, the 8 columns pass straight through field by field ══════════════════════════════
def test_upgrade_row_passes_base_fields_verbatim_and_adds_two():
    r = _v1_row(evidence=EV_CENTRE_BIO, ys=2022, ye=2026)
    v2 = upgrade_row_to_v2(r)
    for k, v in r.items():
        assert v2[k] == v
    assert v2["affil_type"] == "centre_only"
    assert v2["year_start_provenance"] == "bio_stated"
    assert set(v2.keys()) == set(DEPT_ROSTER_PANEL_V2.keys())


def test_upgrade_row_rejects_non_v1_row():
    bad = _v1_row()
    bad["surplus"] = 1
    with pytest.raises(Exception):
        upgrade_row_to_v2(bad)


def test_upgrade_row_does_not_mutate_input():
    r = _v1_row()
    snapshot = dict(r)
    upgrade_row_to_v2(r)
    assert r == snapshot


# ═══ write_table_b_v2 - deterministic write + schema guard ═══════════════════════════════
def test_write_v2_deterministic_and_column_order(tmp_path):
    rows = [upgrade_row_to_v2(_v1_row()),
            upgrade_row_to_v2(_v1_row("Bob Centre", aid=None, ys=None, ye=None,
                                      evidence=EV_CENTRE_EST, conf="low"))]
    p1, p2 = tmp_path / "a.parquet", tmp_path / "b.parquet"
    write_table_b_v2(rows, p1)
    write_table_b_v2(list(reversed(rows)), p2)   # input out of order -> byte-equal after canonical-sort
    assert p1.read_bytes() == p2.read_bytes()
    import pyarrow.parquet as pq
    assert pq.read_table(str(p1)).column_names == list(DEPT_ROSTER_PANEL_V2.keys())


def test_write_v2_rejects_v1_rows(tmp_path):
    with pytest.raises(Exception):
        write_table_b_v2([_v1_row()], tmp_path / "x.parquet")


# ═══ backfill_panel_v2 - frozen 8-column parquet -> new 10-column parquet ════════════════
def _make_v1_panel(tmp_path) -> pathlib.Path:
    rows = [
        _v1_row("Yves Zenou", aid="A5017376589", ys=1995, ye=2026,
                evidence="official_roster", conf="low"),
        _v1_row("Centre Person", aid="A5000000002", ys=2022, ye=2026,
                evidence=EV_CENTRE_BIO, conf="medium"),
        _v1_row("Red Dot", aid=None, ys=2008, ye=2020,
                evidence=EV_DEPT_RED_DOT, conf="low"),
        _v1_row("No Year", aid="A5000000003", ys=None, ye=None,
                evidence=EV_CENTRE_EST, conf="low"),
    ]
    src = tmp_path / "dept_roster_panel_test.parquet"
    write_table_b(rows, src)
    return src


def test_backfill_preserves_base_fields_and_row_count(tmp_path):
    import pandas as pd
    src = _make_v1_panel(tmp_path)
    dst = tmp_path / "out" / "dept_roster_panel_test.parquet"
    report = backfill_panel_v2(src, dst)

    a = pd.read_parquet(src)
    b = pd.read_parquet(dst)
    assert len(a) == len(b) == report["n_rows"]
    # the 8-column base is unchanged field by field (same canonical-sort -> same order)
    for col in a.columns:
        assert list(a[col].fillna("~NA~")) == list(b[col].fillna("~NA~")), col
    assert list(b.columns) == list(DEPT_ROSTER_PANEL_V2.keys())


def test_backfill_report_counts(tmp_path):
    src = _make_v1_panel(tmp_path)
    dst = tmp_path / "out.parquet"
    report = backfill_panel_v2(src, dst)
    assert report["affil_type_counts"] == {"dept_only": 1, "centre_only": 2, "both": 1}
    assert report["year_start_provenance_counts"] == {
        "bio_stated": 1, "unknown": 3}
    assert report["sha256"]


def test_backfill_idempotent_same_content_ok_but_drift_fails(tmp_path):
    src = _make_v1_panel(tmp_path)
    dst = tmp_path / "out.parquet"
    r1 = backfill_panel_v2(src, dst)
    r2 = backfill_panel_v2(src, dst)          # re-run with the same content -> idempotent
    assert r1["sha256"] == r2["sha256"]
    dst.write_bytes(b"corrupted")             # target already exists with different content -> fail loudly
    with pytest.raises(RuntimeError, match="different content"):
        backfill_panel_v2(src, dst)


# ═══ to_table_b_row_v2 - the build path produces V2 rows directly ════════════════
def test_build_path_v2_row_defaults_dept_only():
    parsed = {"display_name": "New Hire", "year_start": 2024, "year_end": 2026}
    verdict = {"author_id": "A5000000009", "confidence": "high", "needs_human": False}
    row = to_table_b_row_v2(parsed, verdict, dept_key="monash_econ")
    assert row["affil_type"] == "dept_only"
    assert row["year_start_provenance"] == "unknown"   # official_roster interval year -> not passed off as a stated arrival
    assert set(row.keys()) == set(DEPT_ROSTER_PANEL_V2.keys())


def test_build_path_v2_row_explicit_affil_type():
    parsed = {"display_name": "Centre Hire", "year_start": None, "year_end": None}
    verdict = {"author_id": None, "needs_human": True}
    row = to_table_b_row_v2(parsed, verdict, dept_key="unsw_econ",
                            affil_type="centre_only")
    assert row["affil_type"] == "centre_only"
    assert row["year_start_provenance"] == "unknown"
    with pytest.raises(ValueError, match="affil_type"):
        to_table_b_row_v2(parsed, verdict, dept_key="unsw_econ", affil_type="banana")
