"""D4 on the October caliber (cal2026-10): the verified-pool exclusion is a property of the frames.

Under the 2026-08-28 canon, analysis/robustness/verified_pool/build_verified_pool.py dropped 162
network-route incumbents who were not on the verified economics roster. Under the October caliber the
network pool IS the verified roster (D2), so the exclusion happens at frame-build time (D4). These tests
pin that: with the builder's own identity rule (P_<author_id> directly, or the person_id of that
author_id in the 2026-07-16 11-school person map), NO person in the October Panel 1 / Panel 2 economics
frames is off data/cal2026-10/roster_econ_verified_2026-10.parquet, and the 74 persons the builder
would still flag against the 2026-08-09 roster it reads are exactly October D3 roster additions.
Measured 2026-09-23 by analysis/robustness/verified_pool/measure_d4_cal2026-10.py, whose report is
pinned here when present. The person map lives on the data SSD; without it the map-form tests skip.
"""
import json, pathlib

import duckdb, pytest

from analysis.lib.paths import load_paths

REPO = pathlib.Path(__file__).resolve().parents[1]
F1 = REPO / "data/frames/p1_frame_econ.csv"
F2 = REPO / "data/frames/p2_becoming_econ.csv"
OLD = REPO / "data/raw_verified/roster_econ_verified.parquet"
NEW = REPO / "data/cal2026-10/roster_econ_verified_2026-10.parquet"
ADD = REPO / "data/cal2026-10/roster_added_2026-10.csv"
REPORT = REPO / "data/cal2026-10/robustness/verified_pool/d4_measure_report.json"


def _person_map():
    ssd = load_paths()["ssd_root"]          # ${SAR_SSD_ROOT:-...} expanded, relative values resolved
    pm = ssd / "derived/u2_person_map_11school_2026-07-16/person_map/data.parquet"
    if not pm.is_file():
        pytest.skip(f"person map not mounted: {pm}")
    return pm


@pytest.fixture(scope="module")
def con():
    pm = _person_map()
    c = duckdb.connect()
    c.execute(f"create table pm as select author_id, person_id from '{pm}'")
    c.execute(f"create table f1 as select incumbent_person_id pid, channel from read_csv_auto('{F1}')")
    c.execute(f"create table f2 as select 'P_'||pid pid, channel from read_csv_auto('{F2}')")
    for name, src in (("old_p", f"'{OLD}'"), ("new_p", f"'{NEW}'"), ("add_p", f"read_csv_auto('{ADD}')")):
        c.execute(f"create table {name} as select distinct 'P_'||v.author_id pid from {src} v "
                  f"union select distinct pm.person_id pid from {src} v join pm using(author_id)")
    return c


def test_rosters_are_the_920_plus_88():
    c = duckdb.connect()
    n_old = c.execute(f"select count(distinct author_id) from '{OLD}'").fetchone()[0]
    n_new = c.execute(f"select count(distinct author_id) from '{NEW}'").fetchone()[0]
    n_add = c.execute(f"select count(distinct author_id) from read_csv_auto('{ADD}')").fetchone()[0]
    n_both = c.execute(f"select count(distinct a.author_id) from '{OLD}' a join '{NEW}' b using(author_id)").fetchone()[0]
    assert (n_old, n_new, n_add, n_both) == (920, 1008, 88, 920)


@pytest.mark.parametrize("t", ["f1", "f2"])
def test_d4_no_frame_person_is_off_the_october_roster(con, t):
    off = con.execute(f"select count(distinct pid) from {t} where pid not in (select pid from new_p)").fetchone()[0]
    assert off == 0, f"{t}: {off} persons off the October verified roster — D4 is not a property of the frames"


@pytest.mark.parametrize("t", ["f1", "f2"])
def test_persons_off_the_0809_roster_are_exactly_october_additions(con, t):
    off = con.execute(f"select count(distinct pid) from {t} where pid not in (select pid from old_p)").fetchone()[0]
    off_add = con.execute(f"select count(distinct pid) from {t} where pid not in (select pid from old_p) "
                          "and pid in (select pid from add_p)").fetchone()[0]
    assert off == 74 and off_add == 74, (off, off_add)


def test_measure_report_pins_the_verdict():
    if not REPORT.is_file():
        pytest.skip(f"not present: {REPORT}")
    r = json.loads(REPORT.read_text())
    assert r["d4_verdict"].startswith("PASS")
    for panel in ("panel1", "panel2"):
        assert r[panel]["vs_roster_2026-10"]["persons_not_on_roster"] == 0
        assert r[panel]["vs_roster_2026-08-09"]["persons_not_on_roster"] == 74
        assert r[panel]["vs_roster_2026-08-09"]["not_on_roster_but_in_2026-10_additions"] == 74
        assert r[panel]["persons"] == 822 and r[panel]["events"] == 113
