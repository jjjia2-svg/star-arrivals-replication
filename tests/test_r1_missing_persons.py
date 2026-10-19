# -*- coding: utf-8 -*-
"""pipeline/aws/r1/missing_persons.py - missing-outcome persons at M scale (N3 + J0-MEAS.3i).

Every table is a toy built in tmp_path (duckdb writes the parquets); no data disk is opened. The one
October-equality test imports econ920_lib and hands it a run-config stage section naming a tmp roster table.
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
import sys

import duckdb
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import missing_persons as mp   # noqa: E402

UNITS_REL = "fwci_fullsnapshot_rebuild_2026-08-09/data/econ_units_2026-08-09.parquet"
PATCH_REL = "econ_final_2026-08-13/patch/works_by_author.jsonl"
ECON_COLS = ["incumbent_person_id", "year", "star_person_id", "event_id", "treated", "post",
             "dose_coupling_baseline", "dose_topic", "dose_low_confidence", "age_gap", "fwci_frac",
             "pub_count", "fwci_frac_ex_star", "pub_count_ex_star", "fwci_mean", "fwci_mean_ex_star", "channel"]
OLD_EV, NEW_EV = "A900:2005", "A901:2012"
ID_RE = re.compile(r"^P_A\d+$")


def _parquet(con, path: pathlib.Path, select_sql: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY ({select_sql}) TO '{path.as_posix()}' (FORMAT parquet)")
    return path


def _jsonl(path: pathlib.Path, authors: list[str]) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for i, a in enumerate(authors):
            f.write(json.dumps({"author_id": a, "work_id": f"W{i}", "publication_year": 2005}) + "\n")
    return path


def _econ_row(pid, year, ev, pc, channel="dept_only"):
    star = "P_" + ev.split(":")[0]
    return [pid, str(year), star, ev, "true", "false", "0.0", "0.0", "false", "3.0", "", pc, "", pc, "", "", channel]


@pytest.fixture
def econ(tmp_path):
    """v2 toy tree. P_A1 units, P_A2 frozen patch, P_A3 supplement only, P_A4/P_A5 nowhere (old / prodlib
    event), P_A6/P_A7 nowhere but without publications."""
    con = duckdb.connect()
    v2 = tmp_path / "v2"
    units = _parquet(con, v2 / UNITS_REL,
                     "SELECT * FROM (VALUES ('P_A1', 'W1', 2005)) t(incumbent_person_id, work_id, publication_year)")
    frozen = _jsonl(v2 / PATCH_REL, ["A2", "A2"])
    sup = _jsonl(tmp_path / "sup" / "works_by_author_supplement.jsonl", ["A3"])
    shadow = tmp_path / "shadow" / "works_by_author.jsonl"
    shadow.parent.mkdir(parents=True)
    shadow.write_bytes(frozen.read_bytes() + sup.read_bytes())
    rows = [_econ_row("P_A1", 2004, OLD_EV, "3"), _econ_row("P_A2", 2004, OLD_EV, "1.0"),
            _econ_row("P_A3", 2004, OLD_EV, "2"),
            _econ_row("P_A4", 2004, OLD_EV, "1"), _econ_row("P_A4", 2005, OLD_EV, "2", "network"),
            _econ_row("P_A5", 2011, NEW_EV, "2.0", "both"), _econ_row("P_A5", 2012, NEW_EV, "1"),
            _econ_row("P_A6", 2004, OLD_EV, "0"), _econ_row("P_A6", 2005, OLD_EV, ""),
            _econ_row("P_A7", 2011, NEW_EV, "0.0")]
    pre_y = tmp_path / "pre_y.csv"
    with open(pre_y, "w", newline="", encoding="utf-8") as f:
        f.write(",".join(ECON_COLS) + "\n")
        for r in rows:
            f.write(",".join(r) + "\n")
    con.close()
    return {"v2": v2, "units": units, "frozen": frozen, "sup": sup, "shadow": shadow, "pre_y": pre_y,
            "prodlib": {NEW_EV}, "tmp": tmp_path}


def _all_persons(res):
    return sorted({p for k in mp.ECON_CLASSES for p in res[k]["persons"]})


def test_reads_the_patch_it_is_given(econ):
    legacy = mp.agg_missing_r1(econ["pre_y"], econ["units"], [econ["frozen"]], econ["prodlib"])
    assert "P_A3" in legacy["old_event_rows_blocking"]["persons"]
    shadow = mp.agg_missing_r1(econ["pre_y"], econ["units"], [econ["shadow"]], econ["prodlib"])
    assert "P_A3" not in _all_persons(shadow)
    assert shadow["patch"]["path"] == str(econ["shadow"]) and shadow["patch"]["persons"] == 2


def test_equals_the_october_function_on_the_legacy_patch(econ, monkeypatch):
    sys.path.insert(0, str(REPO / "pipeline" / "frames" / "cal2026-10" / "econ920"))
    L = pytest.importorskip("econ920_lib")
    cal10 = econ["tmp"] / "cal10"
    cal10.mkdir()
    with open(cal10 / "roster_added_2026-10.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["dept_key", "school", "author_id"])
        w.writerow(["x_econ", "x", "A4"])
    # since R1 W1-OCT-A the roster additions come from the run config's stage section (stage.roster_added),
    # never from a path chosen by existence; an unset $SAR_R1_CONFIG is a STOP, so the section is passed here
    monkeypatch.delenv("SAR_R1_CONFIG", raising=False)
    with pytest.raises(RuntimeError, match=r"^UNSET: \$SAR_R1_CONFIG is not set"):     # r1_config.ConfigStop
        L.agg_missing_persons(econ["pre_y"], econ["v2"], econ["prodlib"])
    october = L.agg_missing_persons(econ["pre_y"], econ["v2"], econ["prodlib"],
                                    stage_cfg={"roster_added": str(cal10 / "roster_added_2026-10.csv")})
    ours = mp.agg_missing_r1(econ["pre_y"], econ["v2"] / UNITS_REL, [econ["v2"] / PATCH_REL], econ["prodlib"],
                             added_ids={"P_A4"})
    assert ours == october
    assert october["old_event_rows_blocking"]["persons_in_roster_added_2026-10"] == 1


def test_m_list_covers_both_classes(econ):
    res = mp.agg_missing_r1(econ["pre_y"], econ["units"], [econ["frozen"]], econ["prodlib"])
    old, new = res["old_event_rows_blocking"], res["prodlib_event_rows_written_NA"]
    assert old["persons"] == ["P_A3", "P_A4"] and old["rows"] == 3 and old["person_years"] == 3
    assert old["events"] == [OLD_EV] and old["by_channel"] == {"network": 1, "dept_only": 2, "both": 0}
    assert new["persons"] == ["P_A5"] and new["rows"] == 2 and new["events"] == [NEW_EV]
    assert mp.coverage_gate(res, "stop", 1) == ("AGG_MISSING", ["P_A3", "P_A4", "P_A5"])


def test_m_stops_with_ids_only_and_b0_reports_only(econ):
    res = mp.agg_missing_r1(econ["pre_y"], econ["units"], [econ["shadow"]], econ["prodlib"])
    m_out, b0_out = econ["tmp"] / "m_out", econ["tmp"] / "b0_out"
    assert mp.write_report(m_out, "agg_missing", res, mode="stop", round=1) == mp.EXIT_STOP == 3
    assert not (m_out / "report_agg_missing.json").exists()
    rep = json.loads((m_out / "stop_report_agg_missing.json").read_text(encoding="utf-8"))
    assert rep["code"] == "AGG_MISSING" and rep["persons"] == ["P_A4", "P_A5"] and rep["n_persons"] == 2
    assert all(ID_RE.match(p) for p in rep["persons"])
    assert not any("name" in k for k in _keys(rep))
    assert mp.write_report(b0_out, "agg_missing", res, mode="report", round=1) == 0
    assert not (b0_out / "stop_report_agg_missing.json").exists()
    rep0 = json.loads((b0_out / "report_agg_missing.json").read_text(encoding="utf-8"))
    assert rep0["code"] == "OK" and rep0["mode"] == "report" and rep0["persons"] == ["P_A4", "P_A5"]
    for rnd in (1, 2, 5):
        assert mp.coverage_gate(res, "report", rnd)[0] == "OK"
    with pytest.raises(ValueError):
        mp.coverage_gate(res, "maybe", 1)


def test_second_round_still_missing_gives_its_own_code(econ, tmp_path):
    res = mp.agg_missing_r1(econ["pre_y"], econ["units"], [econ["shadow"]], econ["prodlib"])
    assert mp.coverage_gate(res, "stop", 1) == ("AGG_MISSING", ["P_A4", "P_A5"])
    assert mp.coverage_gate(res, "stop", 2) == ("AGG_MISSING_AFTER_FETCH", ["P_A4", "P_A5"])
    # no endless fetch loop: round 2 records the ids for the change note and lets the build go on
    out = tmp_path / "r2"
    assert mp.write_report(out, "agg_missing", res, mode="stop", round=2) == 0
    rep = json.loads((out / "report_agg_missing.json").read_text(encoding="utf-8"))
    assert rep["code"] == "AGG_MISSING_AFTER_FETCH" and rep["round"] == 2
    assert rep["classes"]["old_event_rows_blocking"]["rows"] == 2
    empty = {k: {"rows": 0, "persons": [], "person_years": 0, "events": [], "by_channel": {}}
             for k in mp.ECON_CLASSES}
    assert mp.coverage_gate(empty, "stop", 1) == ("OK", []) == mp.coverage_gate(empty, "stop", 2)


def test_extra_patches_cover_persons(econ):
    res = mp.agg_missing_r1(econ["pre_y"], econ["units"], [econ["frozen"], econ["sup"]], econ["prodlib"])
    assert _all_persons(res) == ["P_A4", "P_A5"]
    assert res["patch"]["path"] == [str(econ["frozen"]), str(econ["sup"])]
    assert res["patch"]["persons"] == 2 and len(res["patch"]["sha256"]) == 2
    with pytest.raises(ValueError):
        mp.agg_missing_r1(econ["pre_y"], econ["units"], [], econ["prodlib"])


CHEM_COLS = ["incumbent_person_id", "year", "star_person_id", "event_id", "treated", "post",
             "dose_coupling_baseline", "dose_topic", "dose_low_confidence", "age_gap", "fwci_frac",
             "pub_count", "fwci_frac_ex_star", "pub_count_ex_star", "fwci_mean", "fwci_mean_ex_star", "channel"]


def _chem_row(pid, year, ev, pc, channel="dept_only"):
    return [pid, f"{year}", ev.split(":")[0], ev, "True", "False", "", "0.5", "False", "4.0", "1.0", pc, "1.0", pc,
            "1.0", "1.0", channel]


@pytest.fixture
def chem(tmp_path):
    con = duckdb.connect()
    d = tmp_path / "chem"
    edges = _parquet(con, d / "edges" / "part-0.parquet", """SELECT * FROM (VALUES
        ('A10', 'W1', 2005), ('A11', 'W2', 2007), ('A11', 'W5', NULL), ('A99', 'W3', 2008), ('A13', 'W4', 2009))
        t(author_id, work_id, publication_year)""")
    works = _parquet(con, d / "works" / "part-0.parquet", """SELECT * FROM (VALUES
        ('W1', 2005), ('W2', 2007), ('W3', 2008), ('W5', 2006)) t(work_id, publication_year)""")
    pmap = _parquet(con, d / "pmap.parquet", """SELECT * FROM (VALUES
        ('A12', 'X1'), ('A99', 'X1'), ('A10', 'X2')) t(author_id, person_id)""")
    con.close()
    frame_dir = d / "frames"
    frame_dir.mkdir()
    frame = frame_dir / "analysis_frame_chemistry_new_gold_2026-08-10.csv"
    rows = [_chem_row("A10", 2005, "A800:monash", "3.0"),
            _chem_row("A11", 2006, "A800:monash", "2.0"), _chem_row("A11", 2006, "A801:anu", "2.0", "network"),
            _chem_row("A11", 2007, "A800:monash", "1.0"),
            _chem_row("A12", 2008, "A800:monash", "1.0"),
            _chem_row("A13", 2009, "A801:anu", "4.0", "both"),
            _chem_row("A14", 2009, "A801:anu", "0.0"), _chem_row("A14", 2010, "A801:anu", "")]
    with open(frame, "w", newline="", encoding="utf-8") as f:
        f.write(",".join(CHEM_COLS) + "\n")
        for r in rows:
            f.write(",".join(r) + "\n")
    return {"frame": frame, "frame_dir": frame_dir, "pmap": pmap,
            "edges": (d / "edges" / "*.parquet").as_posix(), "works": (d / "works" / "*.parquet").as_posix(),
            "tmp": tmp_path}


def _y_report(frame_dir, field, agg_missing, key="gold_new"):
    (frame_dir / f"g_yrebuild_{field}.json").write_text(json.dumps(
        {"field": field, "swap": {key: {"out": "/elsewhere/x.csv", "transition": {"agg_missing": agg_missing}},
                                  "gold_machineold": {"transition": {"agg_missing": 99}}}}), encoding="utf-8")


def test_chemmath_coverage_lists_person_years_with_papers_and_no_aggregate(chem):
    res = mp.chemmath_agg_missing(chem["frame"], chem["pmap"], chem["edges"], chem["works"])
    miss = res["missing"]
    # A11 2006: edges only in 2007 or with no year; A13 2009: its work is not in the works table.
    # A12 2008 is covered through its alias A99; A10 and A11 2007 have their own edge x works row.
    assert miss["persons"] == ["P_A11", "P_A13"]
    assert (miss["rows"], miss["person_years"]) == (3, 2)
    assert miss["events"] == ["A800:monash", "A801:anu"]
    assert res["persons_without_works"] == {"count": 2}          # A13 (work outside the table) and A14
    assert res["rows_with_papers"] == 6
    assert mp.coverage_gate(res, "stop", 1) == ("AGG_MISSING", ["P_A11", "P_A13"])

    _y_report(chem["frame_dir"], "chemistry", 3)
    out = chem["tmp"] / "stage_out"
    code = mp.main(["chemmath", "--frames", str(chem["frame_dir"]), "--pmap", str(chem["pmap"]),
                    "--edges", chem["edges"], "--works", chem["works"], "--out", str(out)])
    assert code == 3 and not (out / "report_coverage.json").exists()
    rep = json.loads((out / "stop_report_coverage.json").read_text(encoding="utf-8"))
    assert rep["code"] == "AGG_MISSING" and rep["persons"] == ["P_A11", "P_A13"]
    assert rep["fields"]["chemistry"]["cross_check"] == {"status": "EQUAL", "y_step_agg_missing": 3, "rows": 3}

    _y_report(chem["frame_dir"], "chemistry", 5, key="none_new")
    out2 = chem["tmp"] / "stage_out2"
    assert mp.main(["chemmath", "--frames", str(chem["frame_dir"]), "--pmap", str(chem["pmap"]),
                    "--edges", chem["edges"], "--works", chem["works"], "--out", str(out2)]) == 3
    rep2 = json.loads((out2 / "stop_report_coverage.json").read_text(encoding="utf-8"))
    assert rep2["code"] == "CROSSCHECK_FAIL"
    assert rep2["fields"]["chemistry"]["cross_check"]["status"] == "MISMATCH"


def test_chemmath_full_coverage_passes(chem):
    frame = chem["frame"]
    keep = [ln for ln in frame.read_text(encoding="utf-8").splitlines(keepends=True)
            if not ln.startswith(("A11,2006", "A13,"))]
    frame.write_text("".join(keep), encoding="utf-8")
    _y_report(chem["frame_dir"], "chemistry", 0)
    out = chem["tmp"] / "ok_out"
    assert mp.main(["chemmath", "--frames", str(chem["frame_dir"]), "--pmap", str(chem["pmap"]),
                    "--edges", chem["edges"], "--works", chem["works"], "--out", str(out)]) == 0
    rep = json.loads((out / "report_coverage.json").read_text(encoding="utf-8"))
    assert rep["code"] == "OK" and rep["persons"] == [] and rep["n_persons"] == 0


ALLOWED_KEYS = {
    "code", "mode", "round", "persons", "n_persons", "classes", "fields", "inputs",
    "old_event_rows_blocking", "prodlib_event_rows_written_NA", "missing", "persons_without_works",
    "rows", "person_years", "events", "by_channel", "network", "dept_only", "both", "count",
    "persons_in_roster_added_2026-10", "frame_sha256", "rows_with_papers",
    "cross_check", "status", "y_step_agg_missing", "chemistry", "math_stats", "units", "patch", "sha256",
}
VALUE_RES = [ID_RE, re.compile(r"^A\d+:[A-Za-z0-9_]+$"), re.compile(r"^[0-9a-f]{64}$"),
             re.compile(r"^(OK|AGG_MISSING|AGG_MISSING_AFTER_FETCH|CROSSCHECK_FAIL|EQUAL|MISMATCH|NO_REPORT|"
                        r"report|stop)$")]


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def _strings(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)
    elif isinstance(obj, str):
        yield obj


def test_summary_has_no_names(econ, chem):
    res = mp.agg_missing_r1(econ["pre_y"], econ["units"], [econ["frozen"], econ["sup"]], econ["prodlib"])
    code, ids = mp.coverage_gate(res, "stop", 1)
    econ_sum = mp.summary(res, code, ids, mode="stop", round=1)
    _y_report(chem["frame_dir"], "chemistry", 3)
    out = chem["tmp"] / "names_out"
    mp.main(["chemmath", "--frames", str(chem["frame_dir"]), "--pmap", str(chem["pmap"]),
             "--edges", chem["edges"], "--works", chem["works"], "--out", str(out)])
    chem_sum = json.loads((out / "stop_report_coverage.json").read_text(encoding="utf-8"))
    for s in (econ_sum, chem_sum):
        assert set(_keys(s)) <= ALLOWED_KEYS, set(_keys(s)) - ALLOWED_KEYS
        bad = [v for v in _strings(s) if not any(r.match(v) for r in VALUE_RES)]
        assert not bad, bad
    # an id that is not an OpenAlex author id never reaches a summary
    pre = econ["pre_y"]
    pre.write_text(pre.read_text(encoding="utf-8") + ",".join(_econ_row("Jane Doe", 2004, OLD_EV, "1")) + "\n",
                   encoding="utf-8")
    res2 = mp.agg_missing_r1(pre, econ["units"], [econ["frozen"]], econ["prodlib"])
    with pytest.raises(ValueError):
        mp.coverage_gate(res2, "stop", 1)
