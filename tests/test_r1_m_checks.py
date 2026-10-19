# -*- coding: utf-8 -*-
"""analysis/paper/_m_checks.py: the four checks final-03 (canon M, 2026-10-18) stopped on, and the three roster
checks ledger_carried needs under M, each keeping October's output as it was."""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

import duckdb
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from analysis.paper import _m_checks as mc   # noqa: E402


def test_star_stocks_skip_rows_without_a_stock(tmp_path):
    """ledger_carried: an M restake row with no after_stock (a candidate that is not an event) is left out;
    October has none, so its stocks are unchanged."""
    f = tmp_path / "restake.csv"
    f.write_text("author_id,field,arrival_true,after_stock\nA1,chemistry,2010,7\nA2,chemistry,2012,\n"
                 "A3,math_stats,2011,4\n", encoding="utf-8")
    con = duckdb.connect()
    assert mc.star_stocks(con, f, "chemistry") == {("A1", 2010): 7}
    assert mc.star_stocks(con, f, "math_stats") == {("A3", 2011): 4}


def test_report_cell_matches_the_pinned_estimate_by_name_and_hash(tmp_path):
    """ledger_robustness: a J1b report cell records the producing instance's path; the check uses the file name
    and the sha256 of the pinned estimate the ledger reads."""
    est = tmp_path / "estimates" / "P1nc_chemistry.json"
    est.parent.mkdir()
    est.write_text('{"status": "OK"}\n', encoding="utf-8")
    sha = hashlib.sha256(est.read_bytes()).hexdigest()
    cell = {"json": "/elsewhere/output/r1/robustness/nocentre/estimates/P1nc_chemistry.json", "json_sha256": sha}
    assert mc.cell_is(cell, est)
    assert not mc.cell_is({**cell, "json_sha256": "0" * 64}, est)
    assert not mc.cell_is({**cell, "json": "/x/P1nc_math_stats.json"}, est)


def test_spell_start_note_keeps_octobers_words_and_says_what_m_checks():
    """ledger_funnel: October's ceilings (chem 2023, math 2020) give its clause word for word; R1's (2025 in every
    field) leave no year up to 2024 to cross-check, and the clause says so."""
    assert mc.spell_start_note({"econ": 2025, "chem": 2023, "math": 2020}) == \
        "(cross-checked: roster_chemmath_verified has no chem start in 2024, no math start in 2021-2024)"
    m = mc.spell_start_note({"econ": 2025, "chem": 2025, "math": 2025})
    assert "2021" not in m and "2024" in m and m.startswith("(") and m.endswith(")")


def test_thesis_values_are_asserted_in_october_only():
    """ledger_funnel: the derived values must equal the thesis appendix's in October (the spec); in M they are the
    new numbers the final job installs, so no equality is asserted."""
    want = {"roster_spell_max_start": {"econ": 2025, "chem": 2023, "math": 2020}}
    got = {"roster_spell_max_start": {"econ": 2025, "chem": 2025, "math": 2025}}
    with pytest.raises(AssertionError, match="roster_spell_max_start"):
        mc.check_thesis_values(got, want, ["roster_spell_max_start"], "october")
    mc.check_thesis_values(got, want, ["roster_spell_max_start"], "M")
    mc.check_thesis_values(want, want, ["roster_spell_max_start"], "october")


def test_every_origin_country_has_a_name_and_one_region():
    """fig_star_origins: R1 adds stars arriving from Ethiopia (ET), Nigeria, Colombia, Slovenia, Ukraine, Pakistan
    and Saudi Arabia; every country a region lists has a name, and none sits in two regions. Slovenia (Koper)
    lies inside the Europe panel, so it must be in EUROPE (the dots module's panel check)."""
    sys.path.insert(0, str(REPO / "analysis" / "paper"))
    src = (REPO / "analysis" / "paper" / "fig_star_origins.py").read_text(encoding="utf-8")
    ns: dict = {}
    start, end = src.index("COUNTRY_NAMES = {"), src.index("\n\n\n", src.index("REGIONS = ("))
    exec(compile(src[start:end], "fig_star_origins.py", "exec"), ns)      # the constant block only
    names, regions = ns["COUNTRY_NAMES"], ns["REGIONS"]
    assert names["ET"] == "Ethiopia" and "ET" in dict(regions)["africa"]
    want = {"CO": ("Colombia", "latin_america"), "NG": ("Nigeria", "africa"), "PK": ("Pakistan", "asia"),
            "SA": ("Saudi Arabia", "asia"), "SI": ("Slovenia", "europe"), "UA": ("Ukraine", "europe")}
    for cc, (name, region) in want.items():
        assert names.get(cc) == name and cc in dict(regions)[region], cc
    assert {"SI", "UA"} <= ns["EUROPE"] and {"PK", "SA"} <= ns["ASIA"]
    listed = [c for _r, cs in regions for c in cs]
    assert len(listed) == len(set(listed)) and set(listed) <= set(names)


#: the October added-roster sheet's header (data/cal2026-10/roster_added_2026-10.csv, 88 rows) and R1's
#: (cal/roster_added_2026-10.csv in the M canon, mapped from roster_added_r1.csv: a spell table)
OCTOBER_ADDED = ["dept_key", "school", "author_id", "year_start", "year_end", "evidence", "confidence",
                 "human_verified", "evidence_url", "year_start_orig", "year_end_orig", "year_corrected",
                 "id_issue", "year_note", "verify_source", "dup_person_flag"]
R1_ADDED = ["dept_key", "author_id", "year_start", "year_end", "year_source"]


def test_added_roster_sheet_has_evidence_only_in_octobers_form():
    """ledger_carried groups 4/6: October's added-roster sheet carries the evidence the fellow/DECRA and
    arc.gov.au rules read (evidence_url among its columns); R1's is a spell table with no evidence column."""
    assert mc.added_sheet_has_evidence(OCTOBER_ADDED)
    assert not mc.added_sheet_has_evidence(R1_ADDED)
    assert not mc.added_sheet_has_evidence(None)          # an empty file has no header


def test_roster_counts_people_and_spells(tmp_path):
    """ledger_carried groups 3 and 5: a roster parquet holds one row per spell, and people are distinct
    author_id. October's econ roster has one row per person (1,008 = 1,008); R1's has several."""
    pq = tmp_path / "roster.parquet"
    con = duckdb.connect()
    con.execute("COPY (SELECT * FROM (VALUES ('A1', 2010), ('A1', 2015), ('A2', 2012)) t(author_id, year_start)) "
                f"TO '{pq}' (FORMAT parquet)")
    assert mc.roster_counts(con, pq) == (2, 3)


def test_prep_report_must_count_the_roster_in_force():
    """ledger_carried group 3: prep_final_report.json's added_people is used only when its roster block counts
    the roster in force (same people, same spells). October's rosters match it (chemistry 518 people / 533
    spells); R1's chemistry roster (1,010 / 1,422) does not, and neither does a roster with one more spell."""
    chem = {"spells": 533, "people": 518, "base_people": 384, "added_people": 134}
    assert mc.report_describes_roster(chem, 518, 533)
    assert not mc.report_describes_roster(chem, 1010, 1422)
    assert not mc.report_describes_roster(chem, 518, 534)
    assert not mc.report_describes_roster({}, 518, 533)


R1_ROSTERS = "data/cal2026-10r1/inputs/rosters"  # private sources, not shipped


@pytest.mark.skipif(not (REPO / R1_ROSTERS).is_dir(), reason="R1 roster sources are not shipped")
def test_nocentre_roster_is_the_incfel_twin_the_run_config_pins(tmp_path):
    """ledger_carried group 3 under M: config/r1/M.json pins the roster in force (roster_gold_<f>_r1.parquet,
    found by its sha256, so a copy under the canon is found too) and its no-research-centre twin
    (roster_gold_<f>_r1_incfel.parquet, the J1b no-centre unit's roster). A roster no pin has gives None; a twin
    whose bytes differ from its pin stops."""
    pins = json.loads((REPO / "config" / "r1" / "M.json").read_text(encoding="utf-8"))["pins"]
    for f in ("chemistry", "math_stats"):
        copy = tmp_path / f"roster_gold_{f}.parquet"
        copy.write_bytes((REPO / R1_ROSTERS / f"roster_gold_{f}_r1.parquet").read_bytes())
        assert mc.nocentre_roster(copy, pins, REPO) == REPO / R1_ROSTERS / f"roster_gold_{f}_r1_incfel.parquet"
        assert mc.nocentre_roster(REPO / "data" / "raw_verified" / f"roster_gold_{f}.parquet", pins, REPO) is None
    bad = dict(pins, **{f"{R1_ROSTERS}/roster_gold_chemistry_r1_incfel.parquet": "0" * 64})
    with pytest.raises(AssertionError, match="incfel"):
        mc.nocentre_roster(REPO / R1_ROSTERS / "roster_gold_chemistry_r1.parquet", bad, REPO)


@pytest.mark.skipif(not (REPO / R1_ROSTERS).is_dir(), reason="R1 roster sources are not shipped")
def test_people_left_out_counts_the_people_only_on_the_full_roster(tmp_path):
    """October: the full chemistry roster less the no-centre one is 134 people (prep_final_report's
    added_people); maths 28. R1: 2 and 5."""
    con = duckdb.connect()
    raw = REPO / "data" / "raw_verified"
    assert mc.people_left_out(con, raw / "roster_gold_chemistry.parquet",
                              raw / "incfel" / "roster_gold_chemistry.parquet") == 134
    assert mc.people_left_out(con, raw / "roster_gold_math_stats.parquet",
                              raw / "incfel" / "roster_gold_math_stats.parquet") == 28
    r1 = REPO / R1_ROSTERS
    assert mc.people_left_out(con, r1 / "roster_gold_chemistry_r1.parquet",
                              r1 / "roster_gold_chemistry_r1_incfel.parquet") == 2
    assert mc.people_left_out(con, r1 / "roster_gold_math_stats_r1.parquet",
                              r1 / "roster_gold_math_stats_r1_incfel.parquet") == 5


ROB_FIX = REPO / "tests" / "fixtures" / "r1_paper" / "base_tree_2026-10-11" / "ledgers" / \
    "data_numbers_2026-10-23_robustness.json"
J1B_CUSTODY = {"schema": "sar.r1.rob_canon_custody.v1", "batch": "cloud", "ok": True, "problems": [],
               "task": "r1 J1b robustness batch cloud - custody (rob_post canon-pack)"}


@pytest.mark.skipif(not ROB_FIX.is_file(), reason="Manuscript fixture is not shipped")
def test_robustness_source_note_names_the_canon_roots_and_the_run():
    """ledger_robustness: _source_note comes from canon.key() of its two roots and the run its cloud custody
    record names. October's keys and custody record (no schema) give October's note word for word; the J1b
    canon-pack record and M keys give a note with no October root or run in it."""
    october = mc.rob_source_note("data/cal2026-10/robustness", "data/cal2026-10/cloud",
                                 mc.rob_run({"task": "cal2026-10 cloud batch", "ok": True}))
    assert october == json.loads(ROB_FIX.read_text(encoding="utf-8"))["_source_note"]
    m = mc.rob_source_note("cal/robustness", "cal/cloud", mc.rob_run(J1B_CUSTODY))
    assert "R1 M (J1b) robustness artifacts under cal/robustness/" in m and "cells under cal/cloud/" in m
    assert "cal2026-10" not in m and "October" not in m
    with pytest.raises(ValueError, match="custody"):
        mc.rob_run({"schema": "sar.some.other.v1"})


def test_ledger_robustness_takes_its_note_roots_from_the_canon():
    from analysis.lib import canon
    from analysis.lib.paths import load_paths
    src = (REPO / "analysis" / "paper" / "ledger_robustness.py").read_text(encoding="utf-8")
    assert "_m_checks.rob_source_note(canon.key(ROBX), canon.key(CLOUD), _m_checks.rob_run(_CUSTODY))" in src
    assert "artifacts under data/cal2026-10" not in src and "cells under data/cal2026-10" not in src
    P = load_paths()                                      # the October keys the note is built from
    assert canon.mode(P) == "october"
    assert (canon.key(P["cal"] / "robustness"), canon.key(P["cal"] / "cloud")) == \
        ("data/cal2026-10/robustness", "data/cal2026-10/cloud")
