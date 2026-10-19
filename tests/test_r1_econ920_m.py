# -*- coding: utf-8 -*-
"""R1 F11 + F13 hook (W2-ECONM): pipeline/aws/r1/econ920_m.py on toy inputs (small runner).

Every table is written in tmp_path: ledger-shaped event tables, the new-events age table, a signed
events decision and flips list, a star-id correction table, 17-column pre-y frames and a toy
person map. Nothing reads the data disk, the legacy tree or the October frames; the October
library (econ920_lib / run_econ920) is only imported. Expected values are written out by hand
from the toy inputs, never computed with the module under test.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import types

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "pipeline" / "aws" / "r1"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import econ920_m as em            # noqa: E402

L, R = em.L, em.R

HDR = ("event_id,star_id,school,arrival_year,arrival_source,arrival_evidence,status_P1_B0_binary,"
       "reason,evidence_source")
COLS = ["incumbent_person_id", "year", "star_person_id", "event_id", "treated", "post",
        "dose_coupling_baseline", "dose_topic", "dose_low_confidence", "age_gap", "fwci_frac",
        "pub_count", "fwci_frac_ex_star", "pub_count_ex_star", "fwci_mean", "fwci_mean_ex_star", "channel"]

D5_OLD, D5_NEW = "A5090515599:2009", "A5091326353:2009"
A5028731684_OLD, A5028731684_NEW = "A5028731684:2010", "A5028731684:2008"
A5110738002_EVENT = "A5110738002:2009"
A5044432173_EVENT = "A5044432173:2006"


def sha(p) -> str:
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def line(event: str, school: str = "anu", rest: str = "official_roster,strong,IN,,x", cr: bool = True) -> str:
    star, year = event.split(":")
    return f"{event},{star},{school},{year},{rest}" + ("\r" if cr else "")


def write_table(p: pathlib.Path, events, cr: bool = True) -> pathlib.Path:
    p.write_bytes(("\n".join([HDR + ("\r" if cr else "")] + [line(e, cr=cr) for e in events]) + "\n").encode())
    return p


# ------------------------------------------------------------------------------------------------ the toy world
class World:
    """08-28 econ table (old + new events), the new-events age table, October-style corrections, the
    M table/decision events_r1 writes, the signed flips. Two DROP stars hold old events, one DROP star
    holds a new (age-table) event, one re-dated star holds an age-table event, A5044432173 is only in the age
    table, A5028731684 is re-dated in place, A5091326353 is id-corrected, A5110738002 is restored, two stars are new."""

    OLD = ["A1:2003", "A2:2010", A5028731684_OLD, D5_OLD, A5110738002_EVENT, "A11:2005"]
    NEW = ["A3:2012", "A7:2011", "A12:2013"]          # in the 08-28 table and in the age table
    ADDED = ["A9:2015", "A8:2016"]

    def __init__(self, tmp: pathlib.Path):
        self.tmp = tmp
        self.e0828 = write_table(tmp / "events_econ_cal2026-08-28.csv", self.OLD + self.NEW)
        rows = ["author_id,name,school,arrival,dept_id,evidence_url,verdict_source"]
        for e in self.NEW + [A5044432173_EVENT]:
            a, y = e.split(":")
            rows.append(f"{a},n{a},anu,{y},d,u,s")
        self.age = tmp / "new_events_econ.csv"
        self.age.write_text("\n".join(rows) + "\n", encoding="utf-8")
        self.corr = tmp / "star_id_corrections.csv"
        self.corr.write_text("old_id,new_id,field,school,arrival,evidence\n"
                             "A5090515599,A5091326353,econ,uwa,2009,x\n", encoding="utf-8")
        m_events = [A5028731684_NEW, D5_NEW, A5110738002_EVENT, "A11:2005", "A12:2013", "A7:2012"] + self.ADDED
        self.events = tmp / "events"
        self.events.mkdir()
        self.m_table = write_table(self.events / "events_econ_cal2026-10.csv", m_events, cr=False)
        self.decision = {
            "schema": "sar.r1.events_decision.v1", "config": "M",
            "dropped": [{"field": "econ", "event": e, "star": e.split(":")[0]} for e in ("A1:2003", "A3:2012")],
            "absent_in_october": [{"field": "econ", "star": "A2"}],
            "redated": [{"field": "econ", "star": "A5028731684", "old_event": A5028731684_OLD, "new_event": A5028731684_NEW,
                         "old_year": 2010, "new_year": 2008, "source": "fixes_1001 redate"},
                        {"field": "econ", "star": "A7", "old_event": "A7:2011", "new_event": "A7:2012",
                         "old_year": 2011, "new_year": 2012, "source": "person_overrides arrival_year"}],
            "restored": [{"field": "econ", "event": A5110738002_EVENT, "star": "A5110738002"}],
            "added": [{"field": "econ", "event": e, "star": e.split(":")[0]} for e in self.ADDED]
            + [{"field": "chemistry", "event": "A20:monash", "star": "A20"}],
            "arrival_checks": [], "id_corrected": {"A5090515599": "A5091326353"}}
        (self.events / "events_decision_2026-10.json").write_text(json.dumps(self.decision), encoding="utf-8")
        flips = [{"person_id": p, "field": "econ", "verdict": "DROP", "decided": "x"} for p in ("A1", "A2", "A3")]
        flips += [{"person_id": "A30", "field": "chemistry", "verdict": "DROP", "decided": "x"}]
        flips += [{"person_id": p, "field": "econ", "verdict": "KEEP", "decided": "x"}
                  for p in ("A5028731684", "A5091326353", "A5110738002", "A11", "A12", "A7")]
        self.flips = tmp / "flips_r1.json"
        self.flips.write_text(json.dumps({"schema": "sar.r1.flips.v1", "rows": flips}), encoding="utf-8")

    def plan(self):
        return em.plan_m(events_dir=self.events, flips=self.flips, corrections=self.corr,
                         e0828_table=self.e0828, new_events_csv=self.age)


# ------------------------------------------------------------------------------------------------ F11
def test_plan_from_data(tmp_path):
    w = World(tmp_path)
    plan = w.plan()
    assert sorted(plan.removed_old) == ["A1:2003", "A2:2010"]              # the DROP stars' old events
    assert set(plan.regen) == {D5_NEW, A5028731684_NEW, "A7:2012", "A9:2015", "A8:2016"}
    assert plan.regen[D5_NEW]["kind"] == "corrected" and plan.regen[D5_NEW]["old"] == D5_OLD
    assert plan.regen[A5028731684_NEW] == {**plan.regen[A5028731684_NEW], "kind": "redated", "old": A5028731684_OLD}
    assert plan.regen["A9:2015"]["kind"] == "added" and plan.regen["A9:2015"]["old"] is None
    assert A5110738002_EVENT not in plan.regen and A5110738002_EVENT not in plan.removed_old and A5110738002_EVENT in plan.restored
    # A5044432173 (age table only), the DROP star holding an age-table event, the re-dated age-table star
    assert sorted(plan.removed_new_stars) == ["A3", "A5044432173", "A7"]
    assert sorted(plan.removed_new_events) == ["A3:2012", A5044432173_EVENT, "A7:2011"]       # string order: A3 < A50... < A7
    assert plan.ledger_redates == {A5028731684_OLD: A5028731684_NEW}             # in-place: its line is in the ledger
    assert plan.ledger_appends == ["A7:2012", "A9:2015", "A8:2016"]        # table order
    assert plan.ledger_corrections == {"events": {D5_OLD: D5_NEW}, "stars": {"A5090515599": "A5091326353"}}
    assert sorted(plan.unstar) == ["A1", "A2", "A3", "A30"]               # every field's DROP star
    assert sorted(plan.new_stars) == ["A20", "A8", "A9"]
    assert plan.m_events[0] == A5028731684_NEW and len(plan.m_events) == 8


def test_plan_stops_on_an_unsigned_removal_and_an_unexplained_event(tmp_path):
    w = World(tmp_path)
    flips = json.loads(w.flips.read_text())
    flips["rows"] = [r for r in flips["rows"] if r["person_id"] != "A2"]
    w.flips.write_text(json.dumps(flips))
    with pytest.raises(em.MStop) as e:
        w.plan()
    assert e.value.code == "REMOVAL_NOT_SIGNED" and "A2:2010" in e.value.ids
    (tmp_path / "b").mkdir()
    w = World(tmp_path / "b")
    w.m_table.write_bytes(w.m_table.read_bytes() + line("A99:2001", cr=False).encode() + b"\n")
    with pytest.raises(em.MStop) as e:
        w.plan()
    assert e.value.code == "M_EVENT_UNEXPLAINED" and e.value.ids == ["A99:2001"]


def test_redate_ledger_lines_rewrites_cols_0_and_3(tmp_path):
    w = World(tmp_path)
    plan = w.plan()
    old_lines = [line(e) for e in ["A11:2005", A5028731684_OLD, D5_NEW, A5110738002_EVENT, "A12:2013"]]
    blob = ("\n".join([HDR + "\r"] + old_lines) + "\n").encode()
    appends = [plan.lines[e] for e in plan.ledger_appends]
    out, rec = em.finish_ledger(blob, redates=plan.ledger_redates, appends=appends, m_events=plan.m_events)
    got = out.split(b"\n")
    want_redated = line(A5028731684_OLD).replace(f"{A5028731684_OLD},A5028731684,anu,2010,",
                                               f"{A5028731684_NEW},A5028731684,anu,2008,")
    assert got[2] == want_redated.encode()                                 # cols 0 and 3, the '\r' kept
    assert [g for i, g in enumerate(got[:6]) if i != 2] == [g for i, g in enumerate(blob.split(b"\n")[:6]) if i != 2]
    # F10's lines byte for byte, ended like the ledger's own lines (CRLF here): a ledger with mixed line ends
    # is one the union stage's CSV sniffer cannot read (j1a-07)
    assert got[6:9] == [a.rstrip(b"\r") + b"\r" for a in appends] and got[9] == b""
    assert all(g.endswith(b"\r") for g in got[:9])
    lf = blob.replace(b"\r\n", b"\n")
    out_lf, _ = em.finish_ledger(lf, redates=plan.ledger_redates, appends=[a + b"\r" for a in appends],
                                 m_events=plan.m_events)
    assert b"\r" not in out_lf                                              # an LF ledger stays LF
    assert rec["redated_lines"] == {A5028731684_OLD: 1} and rec["appended"] == plan.ledger_appends
    with pytest.raises(em.MStop) as e:                                     # 0 hits
        em.finish_ledger(blob.replace(A5028731684_OLD.encode(), b"A5028731684:2011"), redates=plan.ledger_redates,
                         appends=appends, m_events=plan.m_events)
    assert e.value.code == "REDATE_LEDGER_HITS"
    twice = blob + line(A5028731684_OLD).encode() + b"\n"
    with pytest.raises(em.MStop) as e:                                     # 2 hits
        em.finish_ledger(twice, redates=plan.ledger_redates, appends=appends, m_events=plan.m_events)
    assert e.value.code == "REDATE_LEDGER_HITS"
    with pytest.raises(em.MStop) as e:                                     # ledger events != M events
        em.finish_ledger(blob, redates=plan.ledger_redates, appends=appends[:-1], m_events=plan.m_events)
    assert e.value.code == "LEDGER_EVENTS_MISMATCH" and e.value.ids == ["A8:2016"]


def test_redates_map_requires_firstpub_redate():
    redated = {A5028731684_OLD: A5028731684_NEW}
    good = {A5028731684_OLD: {"new": A5028731684_NEW, "firstpub_redate": "keep", "decided": "h2"}}
    assert em.check_redates_map(good, redated)[A5028731684_OLD]["firstpub_redate"] == "keep"
    for bad, code in ((None, "REDATES_MAP_MISSING"), ({}, "REDATES_MAP_MISSING"),
                      ({A5028731684_OLD: {"new": A5028731684_NEW, "decided": "h2"}}, "REDATE_FIRSTPUB_MISSING"),
                      ({A5028731684_OLD: {"new": A5028731684_NEW, "firstpub_redate": "move", "decided": "h2"}},
                       "REDATE_FIRSTPUB_NOT_KEEP"),
                      ({A5028731684_OLD: {"new": "A5028731684:2009", "firstpub_redate": "keep", "decided": "h2"}},
                       "REDATES_MAP_MISMATCH"),
                      ({**good, "A1:2003": {"new": "A1:2004", "firstpub_redate": "keep", "decided": "h2"}},
                       "REDATES_MAP_EXTRA")):
        with pytest.raises(em.MStop) as e:
            em.check_redates_map(bad, redated)
        assert e.value.code == code
    assert em.check_redates_map(None, {}) == {}                              # nothing re-dated: no map needed


def test_redate_in_corr_stars_stops():
    redate_stars = {"A5028731684"}
    em.check_corrections([{"old_id": "A5090515599", "new_id": "A5091326353", "field": "econ"}], redate_stars)
    for row in ({"old_id": "A5090515599", "new_id": "A5090515599", "field": "econ"},
                {"old_id": "A5028731684", "new_id": "A5000000001", "field": "econ"},
                {"old_id": "A5000000002", "new_id": "A5028731684", "field": "econ"}):
        with pytest.raises(em.MStop) as e:
            em.check_corrections([row], redate_stars)
        assert e.value.code in ("CORRECTION_SELF", "CORRECTION_REDATED")


def _ss_row(aid, arrival, age, name="x"):
    return {"author_id": aid, "name": name, "dept": "anu_econ", "arrival": arrival, "subfield": "20",
            "age_bin": None, "academic_age": age, "stock": None, "percentile": None, "cell_n": None,
            "is_star_1pct": True, "is_star_5pct": True, "age_eligible": True, "is_foreign_poach": True}


def test_star_set_m():
    rows = [_ss_row("A1", 2003, 9), _ss_row("A5090515599", 2009, 12), _ss_row("A5028731684", 2010, 8),
            _ss_row("A11", 2005, 20)]
    new = [{"author_id": "A9", "name": "n9", "school": "monash", "arrival": 2015, "aage": 14, "rank_pass": "C",
            "restake": {"after_cell": "2002|10-14", "after_stock": "120", "after_pct": "0.991", "after_cell_n": "77"}}]
    out, rec = em.star_set_rows_m(rows, corr_stars={"A5090515599": "A5091326353"}, unstar={"A1", "A2"},
                                  redates={A5028731684_OLD: A5028731684_NEW}, new_stars=new,
                                  rank_age={"A5091326353": 12, "A5028731684": 6, "A11": 19},
                                  event_stars={"A5091326353", "A5028731684", "A11"})
    ids = [r["author_id"] for r in out]
    assert ids == ["A5091326353", "A5028731684", "A11", "A9"]               # DROP row gone, the id-corrected star re-keyed
    ma = out[0]
    assert (ma["arrival"], ma["academic_age"]) == (2009, 12)                # frozen age kept
    mar = out[1]
    assert (mar["arrival"], mar["academic_age"]) == (2008, 6)               # first-pub year unchanged
    assert mar["arrival"] - 1 - mar["academic_age"] == 2010 - 1 - 8
    a9 = out[3]
    assert a9["academic_age"] == 14 and a9["is_star_1pct"] is True and a9["dept"] == "monash_econ"
    assert a9["arrival"] == 2015 and a9["subfield"] == "20" and a9["age_bin"] == "10-14"
    assert rec["removed"] == ["A1"] and rec["added"] == ["A9"]
    assert rec["age_differs_from_rank"] == [{"star": "A11", "frozen": 20, "rank": 19}]   # reported, not used
    with pytest.raises(em.MStop) as e:
        em.star_set_rows_m(rows, corr_stars={}, unstar=set(), redates={}, rank_age={}, event_stars=set(),
                           new_stars=[{**new[0], "rank_pass": None}])
    assert e.value.code == "NEW_STAR_RANK_PASS"
    with pytest.raises(em.MStop) as e:
        em.star_set_rows_m(rows, corr_stars={}, unstar=set(), redates={}, rank_age={}, event_stars=set(),
                           new_stars=[{**new[0], "aage": None}])
    assert e.value.code == "NEW_STAR_AGE_MISSING"


# ---- j1a-05 STOP STARSET_NEW_PRESENT: a new (ACCEPT) econ star can already hold a row of the frozen u4_aug star set.
# That set is the U4 candidate table (277 rows, one per author_id; 165 are not October events). The union clone
# (00_build_frame_econ920_cal.py) reads it twice: is_star_1pct rows -> the ex_star alias set (l.280-288), and
# star_first = arrival - 1 - academic_age (l.367-369), looked up only for an event's own star (build_rows, l.376).
# So October never read a non-event row's arrival or age. The new event's row replaces the frozen row in place,
# built exactly as for an absent new star; only one star carrying two events of this run stops.
def _new(aid, school, arrival, aage=14, name="", rank_pass="own", restake=None):
    return {"author_id": aid, "name": name, "school": school, "arrival": arrival, "aage": aage,
            "rank_pass": rank_pass, "restake": restake or {}}


def test_a_new_star_with_a_frozen_candidate_row_takes_that_row():
    same = {**_ss_row("A9", 2015, 3), "dept": "monash_econ", "name": "frozen9", "percentile": 0.9665,
            "is_star_1pct": False, "is_foreign_poach": False}            # same school and arrival, a 5% candidate
    moved = {**_ss_row("A8", 2011, None), "dept": "monash_econ", "name": "frozen8", "is_star_1pct": None,
             "is_star_5pct": None, "age_eligible": None, "is_foreign_poach": False}   # a later domestic move, no age
    rows = [_ss_row("A11", 2005, 20), same, moved]
    new = [_new("A9", "monash", 2015, aage=14, restake={"after_cell": "2002|10-14", "after_stock": "120",
                                                        "after_pct": "0.991", "after_cell_n": "77"}),
           _new("A8", "melbourne", 2001, aage=9, name="n8", rank_pass="C")]
    out, rec = em.star_set_rows_m(rows, corr_stars={}, unstar=set(), redates={}, new_stars=new,
                                  rank_age={"A11": 20}, event_stars={"A11"})
    assert [r["author_id"] for r in out] == ["A11", "A9", "A8"]          # one row per star, the frozen order
    assert out[0] == rows[0]                                             # every other row untouched
    a9, a8 = out[1], out[2]
    assert (a9["dept"], a9["arrival"], a9["academic_age"]) == ("monash_econ", 2015, 14)   # the rank's aage, not 3
    assert (a9["stock"], a9["percentile"], a9["cell_n"], a9["age_bin"]) == (120, 0.991, 77, "10-14")
    assert a9["name"] == "frozen9"                                       # the rank row has no name: the frozen one
    assert (a8["dept"], a8["arrival"], a8["academic_age"], a8["name"]) == ("melbourne_econ", 2001, 9, "n8")
    for r in (a9, a8):                                                   # new stars are stars everywhere
        assert (r["is_star_1pct"], r["is_star_5pct"], r["age_eligible"], r["is_foreign_poach"]) == (True,) * 4
    assert rec["added"] == ["A9", "A8"] and rec["rows_in"] == 3 and rec["rows_out"] == 3
    rep = {d["star"]: d for d in rec["replaced"]}
    assert sorted(rep) == ["A8", "A9"]
    assert rep["A9"]["event"] == "A9:2015" and rep["A9"]["same_school_and_arrival"] is True
    assert rep["A9"]["frozen"]["first_pub"] == 2015 - 1 - 3 and rep["A9"]["new"]["first_pub"] == 2015 - 1 - 14
    assert rep["A9"]["first_pub_differs"] is True and rep["A9"]["frozen"]["is_star_1pct"] is False
    assert rep["A8"]["event"] == "A8:2001" and rep["A8"]["same_school_and_arrival"] is False
    assert (rep["A8"]["frozen"]["dept"], rep["A8"]["frozen"]["arrival"]) == ("monash_econ", 2011)
    assert rep["A8"]["frozen"]["first_pub"] is None and rep["A8"]["new"]["first_pub"] == 2001 - 1 - 9
    assert rec["age_differs_from_rank"] == []                            # R1P3-16's list is the existing events'


def test_the_eight_j1a05_stars_take_their_frozen_rows():
    """The eight econ ACCEPT stars j1a-05 stopped on, with their frozen dept / arrival / age / flags (copied by hand
    from econ_fnfix_2026-08-15/u4_aug/star_set/star_set.parquet) and the add list's school / arrival; aage is a toy
    value (the M rank tables exist only on AWS). None stops; each keeps one row, now at the add list's event."""
    eight = [  # author_id, frozen dept, frozen arrival, frozen age, frozen (1pct, 5pct, age_eligible, poach), add list
        ("A5025170313", "unsw_econ", 2009, 13, (True, True, True, False), "unsw", 2009),
        ("A5107479283", "unsw_econ", 2009, None, (None, None, None, False), "unsw", 2012),
        ("A5015900048", "monash_econ", 2005, None, (None, None, None, False), "monash", 2015),
        ("A5028500315", "monash_econ", 1988, 0, (False, False, False, False), "monash", 2011),
        ("A5077362668", "unsw_econ", 2018, 7, (False, False, True, False), "unsw", 2018),
        ("A5019255415", "monash_econ", 2005, 3, (False, True, True, True), "monash", 2005),
        ("A5039052555", "monash_econ", 2011, 19, (True, True, True, False), "melbourne", 2001),
        ("A5054240727", "unsw_econ", 2011, 40, (True, True, True, False), "uts", 2006)]
    rows = [_ss_row(ZENOU, 2016, 20)]
    for aid, dept, arr, age, (p1, p5, ae, fp), _s, _y in eight:
        rows.append({**_ss_row(aid, arr, age), "dept": dept, "is_star_1pct": p1, "is_star_5pct": p5,
                     "age_eligible": ae, "is_foreign_poach": fp})
    new = [_new(aid, s, y, aage=10) for aid, *_f, s, y in eight]
    out, rec = em.star_set_rows_m(rows, corr_stars={}, unstar=set(), redates={}, new_stars=new,
                                  rank_age={ZENOU: 20}, event_stars={ZENOU})
    assert len(out) == len(rows) == len({r["author_id"] for r in out})
    got = {r["author_id"]: r for r in out}
    for aid, _d, _a, _g, _f, s, y in eight:
        assert (got[aid]["dept"], got[aid]["arrival"], got[aid]["academic_age"]) == (f"{s}_econ", y, 10)
        assert got[aid]["is_star_1pct"] is True
    same = {d["star"] for d in rec["replaced"] if d["same_school_and_arrival"]}
    assert same == {"A5025170313", "A5077362668", "A5019255415"}
    assert {d["star"] for d in rec["replaced"]} == {e[0] for e in eight}
    assert got[ZENOU] == rows[0]


def test_the_star_set_stops_only_when_one_star_would_carry_two_events():
    """The star set and the clone's star_first hold one row (one first-publication year) per star, and
    provenance_m refuses a star twice: a new star that is also an existing event star of this run, a star with two
    new events, or a frozen set with two rows for the star is a case the signed rules do not settle."""
    rows = [_ss_row("A11", 2005, 20), _ss_row("A9", 2015, 3)]
    kw = dict(corr_stars={}, unstar=set(), redates={}, rank_age={"A11": 20})
    cases = [
        (rows, [_new("A11", "anu", 2012)], {"A11"}, "A11"),             # an existing event star, a second arrival
        (rows[:1], [_new("A7", "anu", 2012)], {"A11", "A7"}, "A7"),     # ... with or without a frozen row
        (rows, [_new("A9", "monash", 2015), _new("A9", "uts", 2018)], {"A11"}, "A9"),   # two new events
        (rows + [_ss_row("A9", 2009, 1)], [_new("A9", "monash", 2015)], {"A11"}, "A9")]  # two frozen rows
    for rws, new, ev, star in cases:
        with pytest.raises(em.MStop) as e:
            em.star_set_rows_m(rws, new_stars=new, event_stars=ev, **kw)
        assert e.value.code == "STARSET_NEW_PRESENT" and e.value.ids == [star]



# ---- W2-1 (2026-10-16; N11 + F17): the M star set's percentile is the signed admitting-pass
# value for EVERY M star - the signed 4-dp pct_own string (flips_r1.json for KEEP, add_list_r1.json for ACCEPT)
# at the precision gaps_zenou checks (1e-9); frozen October academic ages stay for existing events
ZENOU = "A5017376589"


def _signed_toy():
    flips = [{"person_id": ZENOU, "field": "econ", "verdict": "KEEP", "flip": "none", "pct_own": "0.9986"},
             {"person_id": "A11", "field": "econ", "verdict": "KEEP", "flip": "in->out", "pct_own": "0.7679"},
             {"person_id": "A12", "field": "econ", "verdict": "KEEP", "flip": "in->out", "pct_own": ""},
             {"person_id": "A14", "field": "econ", "verdict": "KEEP", "flip": "none", "pct_own": "0.95"},
             {"person_id": "A1", "field": "econ", "verdict": "DROP", "flip": "none", "pct_own": "0.95"},
             {"person_id": "A13", "field": "chemistry", "verdict": "KEEP", "flip": "none", "pct_own": "0.99"}]
    adds = [{"person_id": "A9", "field": "econ", "verdict": "ACCEPT", "pct_own": "0.991"},
            {"person_id": "A8", "field": "econ", "verdict": "ACCEPT", "pct_own": ""},
            {"person_id": "A7", "field": "econ", "verdict": "REJECT", "pct_own": "0.95"}]
    ranks = {ZENOU: {"rank_pass": "own", "after_pct": 0.99857123}, "A11": {"rank_pass": "C", "after_pct": 0.93456789},
             "A12": {"rank_pass": "C", "after_pct": 0.91234567}, "A14": {"rank_pass": "own", "after_pct": 0.97},
             "A9": {"rank_pass": "own", "after_pct": 0.99104}, "A8": {"rank_pass": "own", "after_pct": 0.95551}}
    return flips, adds, ranks


def test_signed_percentile_is_the_admitting_pass_value():
    flips, adds, ranks = _signed_toy()
    pct, rec = em.signed_percentiles(flips_rows=flips, add_rows=adds, rank_row=ranks.__getitem__)
    assert pct(ZENOU) == float("0.9986")                     # the signed string itself, not the rank's 0.99857...
    assert abs(pct(ZENOU) - float(flips[0]["pct_own"])) <= 1e-9          # gaps_zenou's check (d)
    assert pct("A9") == float("0.991")                       # ACCEPT: the add list's value
    assert pct("A11") == 0.9346 and pct("A12") == 0.9123     # admitted on pass C: the admitting rank, 4 dp
    assert pct("A8") == 0.9555                               # own pass, no signed value: the rank, reported
    assert pct("A14") == 0.95                                # the signed value wins; the difference is reported
    for bad in ("A1", "A7", "A13", "A404"):                  # DROP, REJECT, another field, unknown
        with pytest.raises(em.MStop) as e:
            pct(bad)
        assert e.value.code == "STARSET_UNSIGNED"
    assert rec["from_signed"] == sorted([ZENOU, "A14", "A9"])            # each list sorted, ids only
    assert rec["from_rank_pass_c"] == ["A11", "A12"] and rec["own_without_signed_value"] == ["A8"]
    assert rec["signed_vs_rank_differs"] == ["A14"]          # 0.95 vs 0.97: beyond restake_r1's 5e-5


def test_star_set_m_writes_the_signed_percentile_for_every_star_and_keeps_frozen_ages():
    flips, adds, ranks = _signed_toy()
    pct, _rec = em.signed_percentiles(flips_rows=flips, add_rows=adds, rank_row=ranks.__getitem__)
    rows = [_ss_row(ZENOU, 2016, 20), _ss_row("A11", 2005, 20), _ss_row("A1", 2003, 9)]
    rows[0]["percentile"] = 0.997                            # October's frozen value: the July u4 rank (99.7)
    new = [{"author_id": "A9", "name": "n9", "school": "monash", "arrival": 2015, "aage": 14, "rank_pass": "own",
            "restake": {"after_cell": "2002|10-14", "after_stock": "120", "after_pct": "0.99104", "after_cell_n": "77"}}]
    out, rec = em.star_set_rows_m(rows, corr_stars={}, unstar={"A1"}, redates={}, new_stars=new,
                                  rank_age={ZENOU: 21, "A11": 19}, event_stars={ZENOU, "A11"}, signed_pct=pct)
    got = {r["author_id"]: r for r in out}
    assert sorted(got) == ["A11", ZENOU, "A9"]                   # string order: A11 < A50... < A9
    assert got[ZENOU]["percentile"] == float("0.9986") and got["A11"]["percentile"] == 0.9346
    assert got["A9"]["percentile"] == float("0.991")
    assert got[ZENOU]["academic_age"] == 20 and got["A11"]["academic_age"] == 20      # frozen October ages stay
    assert rec["percentile"]["changed"] == [ZENOU, "A11", "A9"]
    # without a signed map (the October plan, econ920_null's switch-off proof) the frozen percentiles stay
    out0, rec0 = em.star_set_rows_m(rows, corr_stars={}, unstar={"A1"}, redates={}, new_stars=[], rank_age={},
                                    event_stars={ZENOU, "A11"})
    assert [r["percentile"] for r in out0] == [0.997, None] and "percentile" not in rec0
    # j1a-06: a frozen U4 candidate row that is no event of the run keeps its frozen percentile (October never
    # read it); an event star with no signed row still stops the build
    rows2 = rows + [_ss_row("A404", 2012, 15)]
    rows2[-1]["percentile"] = None
    out2, rec2 = em.star_set_rows_m(rows2, corr_stars={}, unstar={"A1"}, redates={}, new_stars=[], rank_age={},
                                    event_stars={ZENOU, "A11"}, signed_pct=pct)
    got2 = {r["author_id"]: r for r in out2}
    assert got2["A404"]["percentile"] is None and got2[ZENOU]["percentile"] == float("0.9986")
    assert rec2["percentile"]["frozen_non_event"] == ["A404"]
    with pytest.raises(em.MStop) as e:
        em.star_set_rows_m(rows2, corr_stars={}, unstar={"A1"}, redates={}, new_stars=[], rank_age={},
                           event_stars={ZENOU, "A11", "A404"}, signed_pct=pct)
    assert e.value.code == "STARSET_UNSIGNED"


def test_the_m_star_set_step_reads_the_signed_lists_of_the_run_config(tmp_path, monkeypatch):
    """Steps.star_set (M) builds the percentile map from config M's signed flips and add list; the October plan
    (no rank tables) passes none."""
    flips, adds, ranks = _signed_toy()
    (tmp_path / "flips.json").write_text(json.dumps({"schema": "sar.r1.flips.v1", "rows": flips}))
    (tmp_path / "add.json").write_text(json.dumps({"schema": "sar.r1.add_list.v1", "rows": adds}))
    rt = tmp_path / "rank_tables"
    rt.mkdir()
    (rt / em.verdict_source.M_ECON).write_text("author_id,name\nA9,n9\n")
    seen = {}
    monkeypatch.setattr(em, "star_set_m", lambda src, out, **kw: seen.update(kw) or {"rows_out": 0})

    class Src:
        def row(self, field, a):
            return {"aage": 14, "arrival_true": 2015, "school": "monash", **ranks[a]}

    plan = types.SimpleNamespace(m_events=[f"{ZENOU}:2016", "A9:2015"], unstar=["A1"], redates={},
                                 regen={"A9:2015": {"kind": "added", "star": "A9", "school": "monash"}})
    cfg = types.SimpleNamespace(repo=tmp_path, raw={"signed": {"flips": "repo:flips.json", "add_list": "repo:add.json"}})
    ctx = types.SimpleNamespace(src=Src(), plan=plan, cfg=cfg, rank_tables=rt, v2=tmp_path, work=tmp_path, report={})
    em.Steps().star_set(ctx)
    assert seen["signed_pct"](ZENOU) == float("0.9986") and seen["signed_pct"]("A9") == float("0.991")
    assert ctx.report["star_set_percentile"]["from_signed"] == [ZENOU, "A9"]
    assert seen["event_stars"] == {ZENOU}            # the stars of the run's other events: not the added A9
    assert [n["author_id"] for n in seen["new_stars"]] == ["A9"]
    ctx2 = types.SimpleNamespace(src=None, plan=plan, cfg=cfg, rank_tables=rt, v2=tmp_path, work=tmp_path, report={})
    seen.clear()
    em.Steps().star_set(ctx2)
    assert seen["signed_pct"] is None and seen["event_stars"] == {ZENOU}


# ------------------------------------------------------------------------------------------------ REGEN-AGE
# j1a-10 STOP: prodlib built the regenerated rows' age_gap with October's works_robust rule while the union clone and
# the kept July / fn-fix rows use the 08-15 rule (star = arrival - 1 - academic_age of the star set; incumbent = U3
# panel). Option A (ruling 2026-10-17): in M, prodlib takes the 08-15 rule and a star set whose ages are the M star
# set's. The frozen ages below are the real ones (econ_fnfix_2026-08-15 star set); A5002563598's rank aage 2 is the age
# the j1a-10 numbers imply (clone 23 = 2014 - 1991).
STAR_C = "A5002563598"                                    # admitted on pass C (the j1a-10 relation's star)
STAR_CORR, STAR_RD1, STAR_RD2 = "A5091326353", "A5028731684", "A5071656006"   # id-corrected; two re-dated
REGEN_TOY = {"A5091326353:2009": {"kind": "corrected", "old": "A5090515599:2009", "star": STAR_CORR},
             "A5028731684:2008": {"kind": "redated", "old": "A5028731684:2010", "star": STAR_RD1},
             f"{STAR_RD2}:2001": {"kind": "redated", "old": f"{STAR_RD2}:2000", "star": STAR_RD2},
             f"{STAR_C}:2017": {"kind": "added", "old": None, "star": STAR_C},
             "A9:2015": {"kind": "added", "old": None, "star": "A9"}}
RESTAKE_HDR = "author_id,name,school,arrival_true,rank_pass,aage,after_pct,note"


def _m_star_set_toy():
    """The M star set of the five regenerated stars plus one kept event star (A11), built by star_set_rows_m."""
    rows = [_ss_row("A5090515599", 2009, 4), _ss_row(STAR_RD1, 2010, 19), _ss_row(STAR_RD2, 2000, 4),
            _ss_row("A11", 2005, 7)]
    new = [_new(STAR_C, "melbourne", 2017, aage=2, rank_pass="C"), _new("A9", "monash", 2015, aage=14)]
    out, _rec = em.star_set_rows_m(rows, corr_stars={"A5090515599": STAR_CORR}, unstar=set(),
                                   redates={"A5028731684:2010": "A5028731684:2008", f"{STAR_RD2}:2000": f"{STAR_RD2}:2001"},
                                   new_stars=new, rank_age={}, event_stars={STAR_CORR, STAR_RD1, STAR_RD2, "A11"})
    return out


def _restake_toy(**aage) -> bytes:
    """A restake table as restake_r1 writes it (csv.DictWriter: CRLF, minimal quoting); aage per star."""
    ages = {STAR_CORR: "6", STAR_RD1: "20", STAR_RD2: "5", STAR_C: "2", "A9": "14", "A11": "9", **aage}
    names = {STAR_CORR: '"Doe, J."'}             # a quoted cell
    rows = [RESTAKE_HDR] + [f"{a},{names.get(a, 'n' + a)},anu,2009,own,{g},0.991,"
                            for a, g in ages.items() if g is not None]
    return ("\r\n".join(rows) + "\r\n").encode()


def test_the_m_first_pub_switch_is_the_0815_rule():
    pcfg = {"star_first_pub": {"mode": "works_robust"}, "ego_first_pub": {"mode": "works_robust"},
            "indept": {"mode": "roster_intervals"}, "run_dir": "r"}
    rec = em.m_first_pub(pcfg, "/d/u3_panel_11school_2026-07-16/panel/data.parquet")
    assert pcfg == {"star_first_pub": {"mode": "star_set_academic_age"}, "ego_first_pub": {"mode": "panel_then_wfp"},
                    "indept": {"mode": "roster_intervals",
                               "panel_glob": "/d/u3_panel_11school_2026-07-16/panel/data.parquet"}, "run_dir": "r"}
    assert rec["old"] == {"star_first_pub": {"mode": "works_robust"}, "ego_first_pub": {"mode": "works_robust"},
                          "indept.panel_glob": None}
    assert rec["new"] == {"star_first_pub": {"mode": "star_set_academic_age"}, "ego_first_pub": {"mode": "panel_then_wfp"},
                          "indept.panel_glob": "/d/u3_panel_11school_2026-07-16/panel/data.parquet"}
    assert em.U3_PANEL_REL == "u3_panel_11school_2026-07-16/panel/data.parquet"   # the file the union clone reads


def test_the_regenerated_stars_take_the_m_star_set_ages():
    """The id-corrected star keeps its frozen age (re-keyed), a re-dated star's age moves with the arrival (h2: the first-publication
    year stays), a new star keeps the admitting rank's aage (pass C or own)."""
    ages = em.regen_star_ages(_m_star_set_toy(), REGEN_TOY)
    assert ages == {STAR_CORR: 4, STAR_RD1: 17, STAR_RD2: 5, STAR_C: 2, "A9": 14}


def test_prodlib_restake_rewrites_only_the_regenerated_stars_aage():
    ages = {STAR_CORR: 4, STAR_RD1: 17, STAR_RD2: 5, STAR_C: 2, "A9": 14}
    src = _restake_toy()
    blob, rec = em.prodlib_restake(src, ages, table_stars={STAR_CORR, STAR_RD1, STAR_RD2, STAR_C, "A9", "A11"})
    want = src.replace(b'A5091326353,"Doe, J.",anu,2009,own,6,', b'A5091326353,"Doe, J.",anu,2009,own,4,')
    want = want.replace(b"A5028731684,nA5028731684,anu,2009,own,20,", b"A5028731684,nA5028731684,anu,2009,own,17,")
    assert want != src and blob == want                      # every other byte as given (CRLF, quoting, A11's 9)
    assert rec["changed"] == [{"star": STAR_RD1, "restake_aage": 20, "star_set_age": 17},
                              {"star": STAR_CORR, "restake_aage": 6, "star_set_age": 4}]
    assert rec["unchanged"] == [STAR_C, STAR_RD2, "A9"]    # pass-C and own-pass new stars: same rank aage
    same, rec2 = em.prodlib_restake(src, {}, table_stars={"A11"})
    assert same == src and rec2["changed"] == []


@pytest.mark.parametrize("case", ["no_star_set_row", "no_star_set_age", "arrival", "no_restake_row",
                                  "table_star_without_age"])
def test_a_missing_age_stops_before_prodlib(case):
    rows = _m_star_set_toy()
    ages = {STAR_CORR: 4, STAR_RD1: 17, STAR_RD2: 5, STAR_C: 2, "A9": 14}
    with pytest.raises(em.MStop) as e:
        if case == "no_star_set_row":
            em.regen_star_ages([r for r in rows if r["author_id"] != STAR_C], REGEN_TOY)
        elif case == "no_star_set_age":
            em.regen_star_ages([{**r, "academic_age": None} if r["author_id"] == "A9" else r for r in rows], REGEN_TOY)
        elif case == "arrival":
            em.regen_star_ages([{**r, "arrival": 2016} if r["author_id"] == "A9" else r for r in rows], REGEN_TOY)
        elif case == "no_restake_row":
            em.prodlib_restake(_restake_toy(A9=None), ages, table_stars={"A9"})
        else:                       # prodlib's star_set_academic_age mode needs an age for every event star
            em.prodlib_restake(_restake_toy(A11=""), ages, table_stars={"A9", "A11"})
    want = {"no_star_set_row": ("PRODLIB_STAR_AGE_MISSING", [f"{STAR_C}:2017"]),
            "no_star_set_age": ("PRODLIB_STAR_AGE_MISSING", ["A9:2015"]),
            "arrival": ("PRODLIB_STAR_ARRIVAL", ["A9:2015"]),
            "no_restake_row": ("PRODLIB_RESTAKE_ROW_MISSING", ["A9"]),
            "table_star_without_age": ("PRODLIB_RESTAKE_AGE_MISSING", ["A11"])}[case]
    assert (e.value.code, e.value.ids) == want


def _regen_world(tmp_path, monkeypatch, name):
    """Steps.regenerate with regenerate_m / the event tables / the prodlib line reader faked; returns (ctx, seen)."""
    ss = tmp_path / "work" / "star_set_econ_m.parquet"
    ss.parent.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(_m_star_set_toy()), ss)
    restake = tmp_path / "restake_econ_r1.csv"
    restake.write_bytes(_restake_toy())
    stage_cfg = {"restake_csv": restake, "restake_label": "r1 rank tables restake_econ_r1.csv (kind M)",
                 "names_csvs": [restake], "events_root": tmp_path}
    seen = {}

    def fake_regen(root, v2, tables, report, *, stage_cfg, roster, base, first_pub_panel=None):
        seen.update(stage_cfg=stage_cfg, first_pub_panel=first_pub_panel,
                    restake_bytes=pathlib.Path(stage_cfg["restake_csv"]).read_bytes())
        report["regeneration"] = {"prodlib": {"secs": 1.0}}
        return tmp_path / "prodlib.csv", {}

    monkeypatch.setattr(em, "regenerate_m", fake_regen)
    monkeypatch.setattr(em.pa_stage, "event_tables", lambda t, root: (t, "tag"))
    monkeypatch.setattr(em.L, "normalise_prodlib_lines", lambda p, e: ([], {"rows": 0, "persons": 0}))
    monkeypatch.setattr(em, "u3_panel_path", lambda: tmp_path / "derived" / em.U3_PANEL_REL)
    plan = types.SimpleNamespace(regen=REGEN_TOY, m_events=["A11:2005"] + sorted(REGEN_TOY))
    ctx = types.SimpleNamespace(cfg=types.SimpleNamespace(name=name), plan=plan, stage_cfg=stage_cfg,
                                star_set=ss, work=tmp_path / "work", v2=tmp_path, roster=tmp_path / "r.parquet",
                                exclusion_base=None, events_dir=tmp_path, report={})
    return ctx, seen


def test_the_m_regenerate_step_feeds_prodlib_the_m_ages_and_the_0815_rule(tmp_path, monkeypatch):
    ctx, seen = _regen_world(tmp_path, monkeypatch, "M")
    em.Steps().regenerate(ctx)
    assert seen["first_pub_panel"] == str(tmp_path / "derived" / em.U3_PANEL_REL)
    sc = seen["stage_cfg"]
    assert sc["restake_csv"] == tmp_path / "work" / "restake_econ_prodlib_m.csv"
    assert {k: v for k, v in sc.items() if k not in ("restake_csv", "restake_label")} == \
        {k: v for k, v in ctx.stage_cfg.items() if k not in ("restake_csv", "restake_label")}
    assert b"A5028731684,nA5028731684,anu,2009,own,17," in seen["restake_bytes"]
    assert b'A5091326353,"Doe, J.",anu,2009,own,4,' in seen["restake_bytes"]
    rec = ctx.report["regeneration"]
    assert [c["star"] for c in rec["prodlib_restake"]["changed"]] == [STAR_RD1, STAR_CORR]
    rule = rec["age_gap_rule"]
    assert rule["by_event"] == {"A11:2005": "frozen", **{e: "regenerated" for e in REGEN_TOY}}
    assert rule["rules"]["regenerated"] == rule["rules"]["frozen"] == rule["rules"]["dept_only"] == em.AGE_RULE_0815


def test_the_b0_regenerate_step_is_octobers(tmp_path, monkeypatch):
    """B0 (October's plan, the econ920_null proof and the V3-NET oracle): October's restake table and config."""
    ctx, seen = _regen_world(tmp_path, monkeypatch, "B0")
    em.Steps().regenerate(ctx)
    assert seen["stage_cfg"] is ctx.stage_cfg and seen["first_pub_panel"] is None
    assert seen["restake_bytes"] == _restake_toy()
    rec = ctx.report["regeneration"]
    assert "prodlib_restake" not in rec and not (tmp_path / "work" / "restake_econ_prodlib_m.csv").exists()
    assert rec["age_gap_rule"]["rules"]["regenerated"] == em.AGE_RULE_PIECE_A


def test_regenerate_m_switches_the_first_pub_rule_only_when_asked(tmp_path, monkeypatch):
    """regenerate_m's rendered prodlib config: October's as rendered (B0), the 08-15 rule with the switch recorded (M)."""
    st = em.pa_stage
    rendered = {"star_first_pub": {"mode": "works_robust"}, "ego_first_pub": {"mode": "works_robust"},
                "indept": {"mode": "roster_intervals"}, "run_dir": "r"}
    ran = []

    def build_exclusion(stars, out, **kw):
        pq.write_table(pa.Table.from_pylist([{"author_id": "A1"}]), out)
        return {}

    for fn, fake in (("u4_aug_inputs", lambda c: {}), ("event_stars", lambda t: {"econ": ["A1"]}),
                     ("build_exclusion", build_exclusion), ("build_roster_pool", lambda ex, out, src=None: {}),
                     ("school_inst", lambda p: {}), ("build_u4_aug", lambda *a, **k: {}),
                     ("concat_supplements", lambda out: {}), ("assert_stars_in_person_map", lambda s: {}),
                     ("render_config", lambda f, root, run_dir: json.loads(json.dumps(rendered)))):
        monkeypatch.setattr(st, fn, fake)

    def run_prodlib(field, mirror, cfg, report):
        ran.append(json.loads(json.dumps(cfg)))
        report["prodlib"] = {"econ": {"secs": 1.0}}
        return tmp_path / "frame.csv"

    monkeypatch.setattr(st, "run_prodlib", run_prodlib)
    monkeypatch.setattr(em.L, "person_map_path", lambda: tmp_path / "pm.parquet")
    tables = {"econ": tmp_path / "e.csv"}
    tables["econ"].write_text("event_id,star_id\n")
    rep: dict = {}
    em.regenerate_m(tmp_path / "b0", tmp_path, tables, rep, stage_cfg={}, roster=tmp_path / "r", base=None)
    assert ran[-1] == rendered and "first_pub_switch" not in rep["regeneration"]
    rep = {}
    em.regenerate_m(tmp_path / "m", tmp_path, tables, rep, stage_cfg={}, roster=tmp_path / "r", base=None,
                    first_pub_panel="/d/" + em.U3_PANEL_REL)
    assert ran[-1]["star_first_pub"] == {"mode": "star_set_academic_age"}
    assert ran[-1]["ego_first_pub"] == {"mode": "panel_then_wfp"}
    assert ran[-1]["indept"] == {"mode": "roster_intervals", "panel_glob": "/d/" + em.U3_PANEL_REL}
    assert rep["regeneration"]["first_pub_switch"]["old"]["star_first_pub"] == {"mode": "works_robust"}


def frame_line(pid, year, event, channel, dose="0.5", y="1.0"):
    star = event.split(":")[0]
    cells = [pid, str(year), star, event, "true", "true" if year >= int(event.split(":")[1]) else "false",
             "", dose, "false", "3", y, "2", y, "2", y, y, channel]
    return ",".join(cells)


def write_frame(p: pathlib.Path, lines) -> pathlib.Path:
    p.write_text("\n".join([",".join(COLS)] + list(lines)) + "\n", encoding="utf-8")
    return p


def test_union_rows_proof_gets_regen(tmp_path):
    frozen = write_frame(tmp_path / "frozen.csv", [
        frame_line("P_A100", 2005, "A11:2005", "network"), frame_line("P_A101", 2005, "A11:2005", "both"),
        frame_line("P_A102", 2009, D5_OLD, "network")])
    union = write_frame(tmp_path / "union.csv", [
        frame_line("P_A100", 2005, "A11:2005", "network"), frame_line("P_A101", 2005, "A11:2005", "both"),
        frame_line("P_A102", 2009, D5_NEW, "network"), frame_line("P_A103", 2008, A5028731684_NEW, "network"),
        frame_line("P_A104", 2015, "A9:2015", "both")])
    regen = {D5_NEW, A5028731684_NEW, "A9:2015"}
    proof = em.rows_proof_m(frozen, union, regen, None, tmp_path)
    assert proof["closed"] and proof["counts"]["byte_identical"] == 2
    assert proof["counts"]["regenerated:network"] == 2 and proof["counts"]["regenerated:both"] == 1
    assert not em.rows_proof_m(frozen, union, {D5_NEW}, None, tmp_path)["closed"]
    # a V3-NET removed relation rebuilt as dept_only: allowed only through the allowances
    union2 = write_frame(tmp_path / "union2.csv", [
        frame_line("P_A100", 2005, "A11:2005", "network"),
        frame_line("P_A101", 2005, "A11:2005", "dept_only", dose="0.4")])
    assert not em.rows_proof_m(frozen, union2, regen, None, tmp_path)["closed"]
    allow = {"removed": {("P_A101", "A11:2005")}, "to_dept_candidates": {("P_A101", "A11:2005")}}
    proof = em.rows_proof_m(frozen, union2, regen, allow, tmp_path)
    assert proof["closed"] and proof["allowances"]["frozen_rows_set_aside"] == 1


def test_incumbent_star_rows_removed(tmp_path):
    pre = write_frame(tmp_path / "pre_y.csv", [
        frame_line("P_A100", 2005, "A11:2005", "network"), frame_line("P_A9", 2005, "A11:2005", "network"),
        frame_line("P_A9", 2006, "A11:2005", "network"), frame_line("P_A201", 2005, "A11:2005", "dept_only"),
        frame_line("P_A100", 2009, D5_NEW, "both")])
    rel = tmp_path / "relationships.csv"
    rel.write_text("pid,event_id,channel\nA100,A11:2005,network\nA9,A11:2005,network\n"
                   "A201,A11:2005,dept_only\nA100,A5091326353:2009,both\n", encoding="utf-8")
    pmap = tmp_path / "pmap.parquet"
    pq.write_table(pa.table({"author_id": ["A9", "A9b", "A202", "A100"],
                             "person_id": ["P_A9", "P_A9", "P_A201", "P_A100"]}), pmap)
    forms = em.star_person_forms(["A9", "A202"], {"A9": ["A9b"]}, pmap)
    assert forms == {"P_A9", "P_A9b", "P_A202", "P_A201"}                   # alias, U2 person of a fragment
    rec = em.drop_incumbent_stars(pre, rel, forms, tmp_path / "out")
    assert rec["cause"] == "incumbent_is_star_r1"
    assert rec["rows_dropped_by_channel"] == {"network": 2, "dept_only": 1}
    assert rec["relations_dropped"] == 2 and rec["persons"] == ["P_A201", "P_A9"]
    kept = pathlib.Path(rec["output"]["pre_y"]).read_text().splitlines()
    assert kept == pre.read_text().splitlines()[:2] + pre.read_text().splitlines()[5:]
    assert pathlib.Path(rec["output"]["relationships"]).read_text().splitlines() == [
        "pid,event_id,channel", "A100,A11:2005,network", "A100,A5091326353:2009,both"]
    with pytest.raises(em.MStop) as e:                                     # a survivor is a STOP
        em.assert_no_star_incumbents(pre, forms)
    assert e.value.code == "INCUMBENT_STAR_SURVIVOR" and "P_A9" in e.value.ids
    same = em.drop_incumbent_stars(pre, rel, set(), tmp_path / "none")    # no new star: nothing written
    assert same["output"]["pre_y"] == str(pre) and same["rows_dropped"] == 0


def test_incumbent_star_forms_close_over_the_person_maps_sibling_fragments(tmp_path):
    """M review #0 (alias part only): a new star's roster row may carry an unsigned sibling fragment id that the
    person map folds to the star's person; the union writes it as 'P_' + that fragment id, so it must be a star
    form (October's build_exclusion expands fragments the same way). Before the fix P_A9c survived."""
    pre = write_frame(tmp_path / "pre_y.csv", [
        frame_line("P_A100", 2005, "A11:2005", "network"), frame_line("P_A9c", 2005, "A11:2005", "dept_only"),
        frame_line("P_A9c", 2006, "A11:2005", "dept_only"), frame_line("P_A9", 2006, "A11:2005", "network")])
    rel = tmp_path / "relationships.csv"
    rel.write_text("pid,event_id,channel\nA100,A11:2005,network\nA9c,A11:2005,dept_only\nA9,A11:2005,network\n",
                   encoding="utf-8")
    pmap = tmp_path / "pmap.parquet"
    pq.write_table(pa.table({"author_id": ["A9", "A9b", "A9c", "A100", "A7"],
                             "person_id": ["P_A9", "P_A9", "P_A9", "P_A100", "P_A7"]}), pmap)
    forms = em.star_person_forms(["A9"], {"A9": ["A9b"]}, pmap)
    assert forms == {"P_A9", "P_A9b", "P_A9c"}                             # P_A9c: unsigned sibling fragment
    assert "P_A100" not in forms and "P_A7" not in forms                  # other persons untouched
    rec = em.drop_incumbent_stars(pre, rel, forms, tmp_path / "out")
    assert rec["rows_dropped_by_channel"] == {"dept_only": 2, "network": 1}
    assert rec["persons"] == ["P_A9", "P_A9c"] and rec["relations_dropped"] == 2
    assert pathlib.Path(rec["output"]["pre_y"]).read_text().splitlines() == pre.read_text().splitlines()[:2]
    assert pathlib.Path(rec["output"]["relationships"]).read_text().splitlines() == [
        "pid,event_id,channel", "A100,A11:2005,network"]
    assert em.star_person_forms(["A9"], {}, None) == {"P_A9"}            # no person map: the star's own form


def test_provenance_one_row_per_regen_event():
    age = b"author_id,name,school,arrival,dept_id,evidence_url,verdict_source\nA12,n,anu,2013,d,u,s\n"
    regen = {D5_NEW: {"kind": "corrected", "old": D5_OLD, "star": "A5091326353", "school": "uwa", "name": "m"},
             A5028731684_NEW: {"kind": "redated", "old": A5028731684_OLD, "star": "A5028731684", "school": "anu", "name": ""},
             "A9:2015": {"kind": "added", "old": None, "star": "A9", "school": "monash", "name": ""}}
    blob = em.provenance_m(age, regen)
    rows = list(csv.DictReader(io.StringIO(blob.decode())))
    assert [f"{r['author_id']}:{r['arrival']}" for r in rows] == ["A12:2013", "A5028731684:2008",
                                                                   "A5091326353:2009", "A9:2015"]
    assert rows[2]["verdict_source"] == "regenerated_by_prodlib_star_id_correction_2026-10"
    assert len({r["author_id"] for r in rows}) == len(rows)
    with pytest.raises(em.MStop) as e:
        em.provenance_m(age, {"A12:2014": {"kind": "redated", "old": "A12:2013", "star": "A12", "school": "anu"}})
    assert e.value.code == "PROVENANCE_DUPLICATE_STAR" and e.value.ids == ["A12"]


def _snapshot(d: pathlib.Path):
    if not d.exists():
        return None
    return sorted((p.relative_to(d).as_posix(), p.stat().st_mtime_ns) for p in d.rglob("*"))


def toy_products(tmp: pathlib.Path) -> dict:
    d = tmp / "chain"
    d.mkdir()
    out = {}
    for k, name in (("p1_frame", "p1.csv"), ("p2_frame", "p2.csv"), ("ledger", "led.csv"), ("rel", "rel.csv"),
                    ("slim_noev", "s.parquet"), ("slim_ev", "sev.parquet"), ("pairs", "pairs.csv"),
                    ("pre_y", "pre_y.csv"), ("union_build_report", "ub.json"), ("panels23_report", "p23.json"),
                    ("inpost_report", "ip.json"), ("provenance", "prov.csv"), ("star_set", "ss.parquet"),
                    ("g_econ_rebuild", "g.json")):
        (d / name).write_text(f"{k}\n", encoding="utf-8")
        out[k] = d / name
    return out


def test_freeze_m_writes_only_under_out(tmp_path):
    watched = [L.CAL10, REPO / "output" / "cal_intermediates" / "cal2026-10", REPO / "data" / "frames"]
    before = [_snapshot(d) for d in watched]
    prods = toy_products(tmp_path)
    out = tmp_path / "stage_out"
    rep = em.freeze_m(out, prods, {"m": {}}, staging=[{"rel": "x", "sha256": "0"}])
    assert [_snapshot(d) for d in watched] == before
    for rel in ("frames_econ/p1_frame_econ.csv", "frames_econ/p2_becoming_econ.csv",
                "frames_econ/p1_events_ledger_econ.csv", "frames_econ/relationships_econ.csv",
                "frames_econ/p3_slim_econ.parquet", "frames_econ/p3_slim_ev_econ.parquet",
                "frames_econ/MANIFEST.sha256", "afar_econ/pairs_unified.csv", "afar_econ/p1_frame_econ.csv",
                "afar_econ/p2_becoming_econ.csv", "afar_econ/relationships.csv", "pairs/pairs_unified.csv",
                "pairs/becoming_unified.csv", em.BUILD_REPORT):
        assert (out / rel).is_file(), rel
    assert sha(out / "frames_econ/p1_frame_econ.csv") == sha(prods["p1_frame"])
    assert sha(out / "afar_econ/relationships.csv") == sha(prods["rel"])
    assert sha(out / "pairs/becoming_unified.csv") == sha(prods["p2_frame"])
    for ln in (out / "frames_econ/MANIFEST.sha256").read_text().splitlines():
        h, p = ln.split("  ", 1)
        assert p.startswith("frames_econ/") and not p.startswith("/") and h == sha(out / p)
    br = json.loads((out / em.BUILD_REPORT).read_text())
    assert br["m"]["pairs_unified"] == {"sha256": sha(prods["pairs"]), "bytes": prods["pairs"].stat().st_size}
    for bad in (L.CAL10 / "frames_econ_m", REPO / "data" / "frames" / "x", REPO / "analysis" / "expected" / "x"):
        with pytest.raises(em.MStop) as e:
            em.freeze_m(bad, prods, {"m": {}}, staging=[])
        assert e.value.code == "OUT_IN_OCTOBER_ROOT"


def test_hook_order(tmp_path):
    calls = []

    class Fake:
        def __getattr__(self, name):
            def step(ctx):
                calls.append(name)
            return step

    ctx = types.SimpleNamespace(report={})
    em.m_phase(ctx, Fake())
    assert tuple(calls) == em.ORDER
    i = calls.index
    assert i("star_set") < i("regenerate")        # REGEN-AGE: prodlib's restake input takes the M star set's ages
    assert em.ORDER[:5] == ("shadow", "ledger", "star_set", "regenerate", "events_filter")
    assert i("network_freeze") < i("predict") < i("union")          # V3-NET filters the clone's input
    assert i("union") < i("postfilter") < i("rows_proof") < i("agg_missing") < i("dose_exclusion") < i("chain")
    assert i("install_union") < i("rows_proof") and i("chain") < i("freeze")

    calls.clear()

    class StopsAtN3(Fake):
        def agg_missing(self, ctx):
            calls.append("agg_missing")
            raise em.MStop("AGG_MISSING", ["P_A1"], name="agg_missing", written=True)

    with pytest.raises(em.MStop):
        em.m_phase(ctx, StopsAtN3())
    assert "dose_exclusion" not in calls and "chain" not in calls and calls[-1] == "agg_missing"


def test_a_stop_after_v3net_logs_its_counts(capsys):
    """j1a-09: a failed stage's work dir is not uploaded, so a stop after V3-NET prints V3-NET's counts
    (relations by class, rows dropped, events left with zero network rows) to the stage log."""
    nfr = {"parts": {"july": {"relations_by_class": {"deg1": 5, "deg2_frozen": 1, "deg2_unfrozen": 2, "none": 0},
                              "rows_by_class": {"deg1": 55, "deg2_frozen": 11, "deg2_unfrozen": 22, "none": 0},
                              "rows_dropped": 22, "events_left_with_zero_rows": ["A5000000003:2004"]},
                     "fnfix": None,
                     "regenerated": {"relations_by_class": {"deg1": 1, "deg2_frozen": 0, "deg2_unfrozen": 0, "none": 0},
                                     "rows_by_class": {"deg1": 11, "deg2_frozen": 0, "deg2_unfrozen": 0, "none": 0},
                                     "rows_dropped": 0, "events_left_with_zero_rows": []}},
           "graphs": {"july": {"edges_glob": "/somewhere/edges/**/*.parquet"}},
           "relations_removed": 2, "rows_by_part": {"july": 88, "fnfix": 0, "regenerated": 11},
           "rows_in": 99, "rows_out": 77, "sha256": "0" * 64}

    def steps(stop_at, exc, freeze=nfr):
        class S:
            def __getattr__(self, name):
                def step(ctx):
                    if name == "network_freeze":
                        ctx.report["network_freeze"] = freeze
                    if name == stop_at:
                        raise exc
                return step
        return S()

    for exc in (em.MStop("GDOSE_UNEXPLAINED", ["A5000000001"], name="gdose", written=True), RuntimeError("boom")):
        with pytest.raises(type(exc)):
            em.m_phase(types.SimpleNamespace(report={}), steps("union", exc))
        lines = [ln for ln in capsys.readouterr().out.splitlines() if "V3-NET" in ln]
        assert len(lines) == 1
        printed = json.loads(lines[0].split("V3-NET counts at stop ", 1)[1])
        assert printed["parts"]["july"]["rows_dropped"] == 22 and printed["relations_removed"] == 2
        assert printed["parts"]["july"]["relations_by_class"]["deg2_unfrozen"] == 2
        assert printed["parts"]["july"]["events_left_with_zero_rows"] == ["A5000000003:2004"]
        assert printed["parts"]["fnfix"] is None and (printed["rows_in"], printed["rows_out"]) == (99, 77)
        assert "graphs" not in printed and "sha256" not in printed and "/somewhere" not in lines[0]
    # a stop before V3-NET ran says nothing about it; V3-NET switched off says so
    with pytest.raises(em.MStop):
        em.m_phase(types.SimpleNamespace(report={}), steps("ledger", em.MStop("LEDGER_STAGE", [])))
    assert "V3-NET" not in capsys.readouterr().out
    with pytest.raises(em.MStop):
        em.m_phase(types.SimpleNamespace(report={}), steps("union", em.MStop("X", []), freeze=None))
    assert "V3-NET was off" in capsys.readouterr().out
    # a run that does not stop prints nothing about it
    em.m_phase(types.SimpleNamespace(report={}), steps("none", None))
    assert "V3-NET" not in capsys.readouterr().out


# ------------------------------------------------------------------------------------------------ F13 hook
def test_wrapper_installs_the_fixed_file_after_the_proof(tmp_path, monkeypatch):
    pre = write_frame(tmp_path / "pre_y.csv", [frame_line("P_A100", 2005, "A11:2005", "network")])
    rel = tmp_path / "relationships.csv"
    rel.write_text("pid,event_id,channel\nA100,A11:2005,network\n", encoding="utf-8")
    ub = tmp_path / "build_report.json"
    ub.write_text("{}\n", encoding="utf-8")
    fixed_bytes = pre.read_bytes().replace(b",0.5,", b",0.25,")
    seen = {}

    def fake_proof(frozen, union_out, regen):
        seen["proof_sha"] = sha(union_out)
        return {"closed": True, "counts": {}}

    def fake_apply(pre_y, out, *, union_cfg, excludes, addbacks=frozenset(), mode=None):
        seen["dose_input_sha"] = sha(pre_y)
        seen["excludes"], seen["addbacks"], seen["mode"] = excludes, addbacks, mode
        pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(out).write_bytes(fixed_bytes)
        return {"mode": "delta", "path": str(out), "written": True, "affected": [["P_A100", "A11:2005"]],
                "relations": {"changed": 1}}

    monkeypatch.setattr(L, "union_rows_proof", fake_proof)
    monkeypatch.setattr(em.r1_dose_excl, "apply_dose_exclusions", fake_apply)
    monkeypatch.setattr(em.r1_dose_excl, "dose_rows_proof",
                        lambda b, a, aff: {"closed": True, "before_sha256": sha(b), "after_sha256": sha(a)})
    calls = tmp_path / "calls"
    calls.mkdir()
    (calls / "dose_excludes.csv").write_text("person_id,work_id,source\nA100,W1,request_exclude\n")
    (calls / "adds.csv").write_text("person_id,work_id,source\nA100,W2,id_merge\n")
    cfg = types.SimpleNamespace(name="M", switch=lambda s: {"dose_mode": "delta", "agg_missing": "stop"}[s],
                                is_on=lambda s: s in ("dose_excludes", "add_backs"))
    sh = L.fs08.Shadow(tmp_path / "shadow" / "v2_output")
    ctx = types.SimpleNamespace(report={}, cfg=cfg, sh=sh, work=tmp_path / "work", pre_y=pre, rel=rel,
                                union_report=ub, frozen_pre_y=pre, regen={"A9:2015": {}}, allowances=None,
                                union_cfg={"NEW_EVENTS": "x"}, calls_dir=calls)
    steps = em.Steps()
    steps.install_union(ctx)
    unfixed = sha(pre)
    assert sha(sh.path(em.PRE_Y_REL)) == unfixed
    steps.rows_proof(ctx)
    steps.dose_exclusion(ctx)
    assert seen["proof_sha"] == unfixed and seen["dose_input_sha"] == unfixed     # the proof saw the unfixed frame
    assert seen["mode"] == "delta" and seen["excludes"] == frozenset({("A100", "W1")})
    assert seen["addbacks"] == frozenset({("A100", "W2")})
    fixed_sha = hashlib.sha256(fixed_bytes).hexdigest()
    assert sha(sh.path(em.PRE_Y_REL)) == fixed_sha and sha(ctx.pre_y) == fixed_sha
    assert any(e["origin"] == "r1:S6 dose_exclusion (delta)" for e in sh.manifest())
    prods = toy_products(tmp_path)
    prods["pre_y"] = ctx.pre_y
    em.freeze_m(tmp_path / "out", prods, {"m": {}}, staging=sh.manifest())
    assert sha(tmp_path / "out" / "frames_econ" / "p1_pre_y_frame_econ.csv") == fixed_sha


def test_dose_mode_off_never_calls_the_step(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("apply_dose_exclusions called with the switch off")
    monkeypatch.setattr(em.r1_dose_excl, "apply_dose_exclusions", boom)
    sh = L.fs08.Shadow(tmp_path / "shadow" / "v2_output")
    cfg = types.SimpleNamespace(name="B0", switch=lambda s: {"dose_mode": "october"}[s], is_on=lambda s: False)
    pre = write_frame(tmp_path / "pre_y.csv", [frame_line("P_A100", 2005, "A11:2005", "network")])
    ctx = types.SimpleNamespace(report={}, cfg=cfg, sh=sh, work=tmp_path, pre_y=pre, calls_dir=None)
    em.Steps().dose_exclusion(ctx)
    assert ctx.pre_y == pre and ctx.report["dose_exclusion"] == {"mode": "off", "called": False}
    assert not any(e["origin"].startswith("r1:S6") for e in sh.manifest())


def test_cli_refuses_off_host_and_a_b0_config(tmp_path, monkeypatch):
    monkeypatch.delenv("SAR_HOST", raising=False)
    argv = ["--execute", "--config", "config/r1/B0.json", "--events", str(tmp_path), "--rank-tables", str(tmp_path),
            "--calls", str(tmp_path), "--roster-econ", str(tmp_path / "r.parquet"), "--patch-extra",
            str(tmp_path / "p.jsonl"), "--patch-october", str(tmp_path / "o.jsonl"), "--out", str(tmp_path / "o")]
    with pytest.raises(SystemExit) as e:
        em.main(argv)
    assert "R1 rule" in str(e.value)
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    assert em.main(argv) == 3
    assert json.loads((tmp_path / "o" / "stop_report_econ_m.json").read_text())["code"] == "CONFIG_NOT_M"
    for flag in ("--events", "--calls", "--patch-october"):
        bad = list(argv)
        k = bad.index(flag)
        del bad[k:k + 2]
        with pytest.raises(SystemExit) as e:
            em.main(bad)
        assert e.value.code == 2


def test_runs_as_a_staged_copy_under_work(tmp_path):
    """M review #1: J1a runs `"$PY" "$WORK/econ920_m.py"`, a copy run_stages wrote to $WORK, so the repository comes
    from $REPO_DIR and not from the copy's own path. Before the fix the copy died at import: IndexError under
    /work, ModuleNotFoundError 'econ920_lib' under a deeper $WORK such as this one."""
    work = tmp_path / "work"
    work.mkdir()
    copy = work / "econ920_m.py"
    shutil.copyfile(REPO / "pipeline" / "aws" / "r1" / "econ920_m.py", copy)
    env = dict(os.environ, SAR_HOST="ec2-r1-test", PYTHONDONTWRITEBYTECODE="1", REPO_DIR=str(REPO))
    env.pop("SAR_OUT_ROOT", None)
    r = subprocess.run([sys.executable, str(copy), "--help"], cwd=REPO, env=env, capture_output=True, text=True,
                       timeout=300)
    assert r.returncode == 0, r.stderr[-1500:]
    assert "--patch-october" in r.stdout and "--roster-econ" in r.stdout
    env.pop("REPO_DIR")
    r = subprocess.run([sys.executable, str(copy), "--help"], cwd=tmp_path, env=env, capture_output=True, text=True,
                       timeout=300)
    assert r.returncode != 0
    assert "cannot find the repository" in r.stderr and "Traceback" not in r.stderr, r.stderr[-1500:]


# ---- M review #2: the controls' precondition step inside the M sandbox ----------------------------------------
SANDBOX_ROOTS = ("data/cal2026-10", "data/frames", "analysis/expected", "data/cal2026-08-28")   # sandbox.ROOTS


def test_controls_preconditions_survive_the_m_purge(tmp_path, monkeypatch):
    """In J1a the sandbox has moved October's products (the October econ / chemistry / maths event tables and
    restake_econ11_aug) to /work/ref/october before frames_econ920 runs. October's precondition step asserts they
    exist ('October input missing'); the M step checks the base files and the 08-28 canon only."""
    gone = tmp_path / "moved_to_ref"
    monkeypatch.setattr(L, "EVENTS_OCT", gone / "events_econ_cal2026-10.csv")
    monkeypatch.setattr(L, "RESTAKE_OCT", gone / "restake_econ11_aug_2026-10.csv")
    monkeypatch.setattr(L, "CAL10", gone)                  # run_econ920 reads the chem/maths tables as CAL10 / name
    monkeypatch.setattr(L, "assert_pins", lambda v2: {"legacy": "stub"})
    v2 = tmp_path / "v2"
    leg = v2 / "econ_roster_verify_2026-08-09" / "roster_clean_11school_verified.parquet"
    leg.parent.mkdir(parents=True)
    shutil.copyfile(L.ROSTER_920, leg)
    pmap = tmp_path / "person_map.parquet"
    pmap.write_bytes(b"stub")
    monkeypatch.setattr(L, "person_map_path", lambda: pmap)
    monkeypatch.setattr(em.shutil, "which", lambda name: f"/usr/bin/{name}")
    with pytest.raises(AssertionError, match="October input missing"):
        R.preconditions(v2)                                # October's own step needs the purged products
    rec = em.control_preconditions(v2)
    assert set(rec["base_inputs"]) == {"data/cal2026-10/roster_econ_verified_2026-10.parquet",
                                       "data/cal2026-10/edges_supplement_star_id_corrections_2026-10.jsonl",
                                       "data/cal2026-10/star_id_corrections_2026-10.csv"}
    assert "october_inputs" not in rec and "events" not in rec
    assert rec["id_correction"]["events"] == {R.D5_OLD_EVENT: R.D5_NEW_EVENT}
    assert (len(rec["frozen_frames"]), len(rec["golds_0828"]), len(rec["verified_pool"])) == (7, 4, 5)
    monkeypatch.setattr(L, "person_map_path", lambda: tmp_path / "absent.parquet")
    with pytest.raises(em.MStop) as e:                     # a failed check is a STOP code, not a traceback
        em.control_preconditions(v2)
    assert e.value.code == "CONTROL_PRECONDITIONS"


def test_control_preconditions_read_no_sandbox_product():
    """Every repo file the M precondition step checks under the sandbox roots is base / r1_input in
    config/r1/base_inputs.tsv (purge moves products only); October's build tables are products and not read."""
    with open(REPO / "config" / "r1" / "base_inputs.tsv", encoding="utf-8", newline="") as fh:
        classes = {r["path"]: r["class"] for r in csv.DictReader(fh, delimiter="\t")}
    files = [*em.control_base_files(), L.FRAMES_MANIFEST, *(L.FRAMES / n for n in em.CONTROL_FROZEN_FRAMES),
             *(L.EXPECTED / f"{g}.json" for g in em.CONTROL_GOLDS_0828), *L.CHEMMATH_AFAR_INPUTS.values()]
    seen = 0
    for p in files:
        rel = pathlib.Path(p).relative_to(REPO).as_posix()
        if any(rel.startswith(r + "/") for r in SANDBOX_ROOTS):
            assert classes.get(rel) in ("base", "r1_input"), (rel, classes.get(rel))
            seen += 1
    assert seen == len(files) == 3 + 1 + 7 + 4 + 6
    october_build = [L.EVENTS_OCT, L.RESTAKE_OCT, L.CAL10 / "events_chemistry_cal2026-10.csv",
                     L.CAL10 / "events_math_stats_cal2026-10.csv"]
    for p in october_build:
        assert classes[p.relative_to(REPO).as_posix()] == "product" and p not in files


def test_m_controls_run_the_m_precondition_step_and_b0_keeps_octobers(tmp_path, monkeypatch):
    """run_controls (M) calls control_preconditions, never October's step; the B0 switch-off proof passes
    October's own step (it runs outside the sandbox, so B0 stays October's run)."""
    def october_step(v2):
        raise AssertionError("October input missing: (moved to /work/ref/october)")
    monkeypatch.setattr(R, "preconditions", october_step)
    monkeypatch.setattr(em, "control_preconditions", lambda v2: {"m": "control preconditions"})
    monkeypatch.setattr(R, "REPORT", {})
    monkeypatch.setattr(R, "STOPS", [])
    for ph in R.CONTROLS:
        monkeypatch.setattr(R, f"control_{ph}", (lambda p: lambda root, v2: R.set_verdict(p, True))(ph))

    def gdose(root, v2):
        R.REPORT["_gdose_residuals"] = []
        R.REPORT.setdefault("measurements", {})["gdose_population"] = {"n": 0}
    monkeypatch.setattr(R, "measure_gdose", gdose)
    root, out = tmp_path / "root", tmp_path / "out"
    root.mkdir()
    out.mkdir()
    assert em.run_controls(root, tmp_path / "v2", out) == {c: "CLEAR" for c in R.CONTROLS}
    assert json.loads((out / em.CONTROLS_REPORT).read_text())["preconditions"] == {"m": "control preconditions"}
    (tmp_path / "root2").mkdir()
    with pytest.raises(AssertionError, match="October input missing"):
        em.run_controls(tmp_path / "root2", tmp_path / "v2", None, preconditions=R.preconditions)
    import inspect                                                          # noqa: PLC0415
    assert "preconditions=R.preconditions" in inspect.getsource(em.run_october_plan)
    assert "preconditions=" not in inspect.getsource(em.run_m)


# ---- M review #5: after the one fetch round, the still-missing old-event rows stay NA ---------------
def _after_fetch_world(tmp_path, *, bad_rows=4, hard_fail=0, hand=True, authorised_y=""):
    """pre-y: P_A100 (covered), P_A501 (no outcome source after the fetch: 2 old-event rows with papers), P_A600 on
    a prodlib event. 04's written unified frame: P_A501's rows NA (agg_missing, x2 variants in bad_rows)."""
    pre = write_frame(tmp_path / "pre_y.csv", [
        frame_line("P_A100", 2005, "A11:2005", "network"), frame_line("P_A501", 2005, "A11:2005", "dept_only"),
        frame_line("P_A501", 2006, "A11:2005", "dept_only"), frame_line("P_A600", 2015, "A9:2015", "network")])
    p1 = tmp_path / "work" / "m_p1" / "run" / "data"
    p1.mkdir(parents=True)
    written = write_frame(p1 / "analysis_frame_econ920_unified_fullsnap_2026-08-13.csv", [
        frame_line("P_A100", 2005, "A11:2005", "network", y="1.5"),
        frame_line("P_A501", 2005, "A11:2005", "dept_only", y=authorised_y),
        frame_line("P_A501", 2006, "A11:2005", "dept_only", y=""),
        frame_line("P_A600", 2015, "A9:2015", "network", y="")])
    g = {"PASS": False, "C_PC_structural_anchor": {"bad_rows": bad_rows, "pass": False},
         "old_value_reproduction_anchor": {"hard_fail_cells": hard_fail}, "G_D_hand_check_10py": {"pass": hand}}
    (p1 / "g_econ_rebuild.json").write_text(json.dumps(g), encoding="utf-8")
    ch = {"p1_frame": None, "p1_econ": {"status": "FAILED", "error": "run_frames.py p1-econ failed (2)",
                                        "g_econ_rebuild": {"PASS": False, "path": str(p1 / "g_econ_rebuild.json")},
                                        "unified_frame_written": str(written)},
          "p2_frame": tmp_path / "p2.csv", "pairs": tmp_path / "pairs.csv", "panels23_report": tmp_path / "p23.json",
          "slim": {"noev": tmp_path / "s.parquet", "ev": tmp_path / "sev.parquet"}}
    return pre, written, ch


def _chain_ctx(tmp_path, pre, after_fetch):
    sh = L.fs08.Shadow(tmp_path / "shadow" / "v2_output")
    return types.SimpleNamespace(sh=sh, work=tmp_path / "work", shadow_root=tmp_path / "shadow", report={},
                                 prov_bytes=b"author_id,arrival\nA9,2015\n", age_bytes=b"author_id,arrival\n",
                                 pre_y=pre, prov_events={"A9:2015"}, v2=tmp_path / "v2", after_fetch=after_fetch)


def test_chain_tolerates_after_fetch_old_event_na_rows(tmp_path, monkeypatch):
    """AGG_MISSING_AFTER_FETCH lets the build go on with those rows NA, but 04_rebuild_y.py
    (October, unedited) exits 2 on them and the chain stopped with P1_ECON_BLOCKED. The written unified frame is
    installed when 04's only failure is exactly those rows; the count goes to the build report."""
    pre, written, ch = _after_fetch_world(tmp_path)
    monkeypatch.setattr(R, "chain_from_union", lambda *a, **k: dict(ch, p1_econ=dict(ch["p1_econ"])))
    ctx = _chain_ctx(tmp_path, pre, {"persons": ["P_A501"], "rows": 2})
    em.Steps().chain(ctx)
    assert ctx.chain["p1_frame"] == ctx.sh.path(em.P1_UNIFIED_REL) and sha(ctx.chain["p1_frame"]) == sha(written)
    rec = ctx.report["agg_missing_after_fetch_tolerated"]
    assert rec["persons"] == ["P_A501"] and rec["rows"] == 2 and rec["bad_rows"] == 4 and all(rec["checks"].values())
    assert rec["rescan"] == {"rows_written": 4, "rows_pre_y": 4, "authorised_rows": 2, "authorised_rows_na": 2}
    assert ctx.report["chain"]["p1_frame"] == str(ctx.sh.path(em.P1_UNIFIED_REL))


@pytest.mark.parametrize("case", ["round_1", "extra_pc_mismatch", "repro_hard_fail", "hand_check_fail",
                                  "authorised_row_not_na", "outsider_missing"])
def test_chain_still_blocks_anything_but_the_after_fetch_rows(tmp_path, monkeypatch, case):
    kw = {"extra_pc_mismatch": {"bad_rows": 6}, "repro_hard_fail": {"hard_fail": 1}, "hand_check_fail": {"hand": False},
          "authorised_row_not_na": {"authorised_y": "0.7"}}.get(case, {})
    pre, _written, ch = _after_fetch_world(tmp_path, **kw)
    monkeypatch.setattr(R, "chain_from_union", lambda *a, **k: dict(ch, p1_econ=dict(ch["p1_econ"])))
    monkeypatch.setattr(em.missing_persons, "agg_missing_r1",
                        lambda *a, **k: {"old_event_rows_blocking": {"persons": ["P_A501"], "rows": 2}})
    after = {"round_1": None, "outsider_missing": {"persons": ["P_A777"], "rows": 2}}.get(
        case, {"persons": ["P_A501"], "rows": 2})
    ctx = _chain_ctx(tmp_path, pre, after)
    with pytest.raises(em.MStop) as e:
        em.Steps().chain(ctx)
    assert e.value.code == "P1_ECON_BLOCKED" and e.value.ids == ["P_A501"]
    assert ctx.chain["p1_frame"] is None and not ctx.sh.path(em.P1_UNIFIED_REL).exists()


def test_the_agg_missing_step_records_the_after_fetch_rows(tmp_path, monkeypatch):
    """The agg_missing step hands the chain the AGG_MISSING_AFTER_FETCH class old_event_rows_blocking (ids,
    rows); any other code leaves nothing to tolerate."""
    res = {"old_event_rows_blocking": {"rows": 2, "persons": ["P_A501"]},
           "prodlib_event_rows_written_NA": {"rows": 1, "persons": ["P_A600"]}}

    def gate(out, *a, mode, round, **k):                                      # noqa: A002
        code = "AGG_MISSING_AFTER_FETCH" if round >= 2 else "AGG_MISSING"
        body = {"code": code, "persons": ["P_A501", "P_A600"], "n_persons": 2}
        name = "report_agg_missing.json" if code == "AGG_MISSING_AFTER_FETCH" else "stop_report_agg_missing.json"
        (pathlib.Path(out) / name).write_text(json.dumps(body), encoding="utf-8")
        return (0 if code == "AGG_MISSING_AFTER_FETCH" else 3), res
    monkeypatch.setattr(em.missing_persons, "econ_gate", gate)
    monkeypatch.setattr(em, "fetch_round", lambda *a, **k: 2)
    sh = L.fs08.Shadow(tmp_path / "shadow" / "v2_output")
    cfg = types.SimpleNamespace(name="M", switch=lambda s: "stop", raw={"sections": {"patch": {"tags": ["t1"]}}})
    ctx = types.SimpleNamespace(cfg=cfg, out=tmp_path, pre_y=tmp_path / "pre_y.csv", v2=tmp_path, sh=sh,
                                prov_events={"A9:2015"}, patch_r1=None, report={})
    em.Steps().agg_missing(ctx)
    assert ctx.after_fetch == {"persons": ["P_A501"], "rows": 2}
    monkeypatch.setattr(em, "fetch_round", lambda *a, **k: 1)
    with pytest.raises(em.MStop) as e:
        em.Steps().agg_missing(ctx)
    assert e.value.code == "AGG_MISSING" and ctx.after_fetch is None


# ---- M review #6: the fetch round comes from the config's tags, not from the supplement's size ----------------
def _patch_dir(tmp_path, *, data=b"", status="assembled", tags=("t1",), n_empty=2):
    d = tmp_path / "patch_assemble"
    d.mkdir()
    (d / "works_by_author_supplement_r1.jsonl").write_bytes(data)
    rep = {"schema": "sar.r1.patch_assemble.v1", "result": "OK", "status": status, "tags": list(tags),
           "n_rows": 0, "n_persons": n_empty, "n_empty": n_empty, "empty": [f"A{i}" for i in range(n_empty)]}
    (d / "report_patch_assemble.json").write_text(json.dumps(rep), encoding="utf-8")
    return d / "works_by_author_supplement_r1.jsonl"


def _patch_cfg(tags):
    return types.SimpleNamespace(name="M", raw={"sections": {"patch": {"tags": list(tags)}}})


def test_fetch_round_counts_a_completed_fetch_that_returned_no_works(tmp_path):
    """One fetch round, then AGG_MISSING_AFTER_FETCH. A fetch whose every profile came back empty leaves a
    0-byte supplement that patch_assemble reports as 'assembled' with n_empty; it is still round 2 (before the fix:
    round 1, AGG_MISSING again, an endless fetch loop)."""
    sup = _patch_dir(tmp_path)
    assert em.fetch_round(_patch_cfg(["t1"]), sup) == 2
    (tmp_path / "b").mkdir()
    sup = _patch_dir(tmp_path / "b", status="no tags", tags=(), n_empty=0)
    assert em.fetch_round(_patch_cfg([]), sup) == 1                       # before any 3i fetch
    (tmp_path / "c").mkdir()
    sup = _patch_dir(tmp_path / "c", data=b'{"author_id": "A1"}\n', tags=("t1",))
    assert em.fetch_round(_patch_cfg(["t1"]), sup) == 2                   # works came back
    assert em.fetch_round(_patch_cfg([]), None) == 1                      # B0: no R1 supplement


@pytest.mark.parametrize("case", ["data_without_tags", "report_says_no_tags", "tags_differ", "no_report"])
def test_fetch_round_stops_when_the_config_and_patch_assemble_disagree(tmp_path, case):
    kw = {"data_without_tags": {"data": b'{"author_id": "A1"}\n', "status": "no tags", "tags": ()},
          "report_says_no_tags": {"status": "no tags", "tags": ()},
          "tags_differ": {"tags": ("t0",)}}.get(case, {})
    sup = _patch_dir(tmp_path, **kw)
    if case == "no_report":
        (sup.parent / "report_patch_assemble.json").unlink()
    cfg = _patch_cfg([] if case == "data_without_tags" else ["t1"])
    with pytest.raises(em.MStop) as e:
        em.fetch_round(cfg, sup)
    assert e.value.code == "PATCH_ROUND_MISMATCH"


def test_agg_missing_after_an_empty_fetch_is_after_fetch_not_a_stop(tmp_path, monkeypatch):
    """The agg_missing step on a resume after an all-empty fetch: round 2, code AGG_MISSING_AFTER_FETCH, a report
    (not a stop report), and the chain gets the rows to keep NA."""
    sup = _patch_dir(tmp_path)
    res = {"old_event_rows_blocking": {"rows": 3, "persons": ["P_A501"]},
           "prodlib_event_rows_written_NA": {"rows": 0, "persons": []}}
    seen = {}

    def gate(out, *a, mode, round, **k):                                      # noqa: A002
        seen["round"] = round
        code, ids = em.missing_persons.coverage_gate(res, mode, round)
        body = em.missing_persons.summary(res, code, ids, mode=mode, round=round)
        stop = code in em.missing_persons.STOP_CODES
        (pathlib.Path(out) / ("stop_report_agg_missing.json" if stop else "report_agg_missing.json")).write_text(
            json.dumps(body), encoding="utf-8")
        return (3 if stop else 0), res
    monkeypatch.setattr(em.missing_persons, "econ_gate", gate)
    out = tmp_path / "out"
    out.mkdir()
    ctx = types.SimpleNamespace(cfg=types.SimpleNamespace(name="M", switch=lambda s: "stop",
                                                          raw={"sections": {"patch": {"tags": ["t1"]}}}),
                                out=out, pre_y=tmp_path / "pre_y.csv", v2=tmp_path,
                                sh=L.fs08.Shadow(tmp_path / "shadow" / "v2_output"), prov_events=set(), patch_r1=sup,
                                report={})
    em.Steps().agg_missing(ctx)
    assert seen["round"] == 2 and ctx.report["agg_missing"]["round"] == 2
    body = json.loads((out / "report_agg_missing.json").read_text())
    assert body["code"] == "AGG_MISSING_AFTER_FETCH" and body["round"] == 2
    assert not (out / "stop_report_agg_missing.json").exists()
    assert ctx.after_fetch == {"persons": ["P_A501"], "rows": 3}


# ------------------------------------------------------------------------------------------------ V3-NET row groups
# t-big-04 (tests/test_r1_network_freeze_real.py): two October econ relations were UNEXPLAINED. net1 holds three row
# groups built by three builders - the July rows, the 2026-08-15 prodlib rows of the fn-fix events and the REGEN
# block - and the step classified the first two on ONE graph (the July one). The two relations are 08-15 prodlib rows
# whose incumbents exist only in that run's person map (the 07-24 rebuild's 'P_<author id>' singletons, their edges
# only in its snapshot overlay), so no path reached them. Each group is now classified on its builder's graph.
NET_COLS = L.FRAME_COLS            # the 16-column network frame (no channel column)


def net_lines(inc, star, event, arrival) -> list[str]:
    """One relation's two network-frame lines (arrival - 1, arrival), in the shape 01_merge_inputs writes."""
    return [",".join([inc, str(y), star, event, "true", "true" if y >= arrival else "false", "", "0.5", "false",
                      "3.0", "1.25", "2.0", "1.0", "1.0", "0.6", "0.5"]) for y in (arrival - 1, arrival)]


def write_net(p: pathlib.Path, lines) -> pathlib.Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(("\n".join([",".join(NET_COLS)] + list(lines)) + "\n").encode())
    return p


def test_split_net1_parts_rows_by_their_builder(tmp_path):
    july, fnfix, regen = (net_lines("P_I1", "P_S1", "A1:2010", 2010), net_lines("P_X", "P_S2", "A2:2012", 2012),
                          net_lines("P_I3", "P_S3", "A3:2015", 2015))
    src = write_net(tmp_path / "net1.csv", july + fnfix + regen)
    parts = em.split_net1(src, regen={"A3:2015"}, fnfix={"A2:2012", "A9:2001"}, out_dir=tmp_path / "parts")
    assert list(parts) == list(em.FREEZE_PARTS) == ["july", "fnfix", "regenerated"]
    hdr = ",".join(NET_COLS)
    for k, lines in (("july", july), ("fnfix", fnfix), ("regenerated", regen)):
        p, n = parts[k]
        assert p == tmp_path / "parts" / f"net1_{k}_rows.csv" and n == 2
        assert p.read_bytes() == ("\n".join([hdr] + lines) + "\n").encode()          # byte-preserving
    joined = tmp_path / "joined.csv"
    em.join_frames([parts[k][0] for k in em.FREEZE_PARTS], joined)
    assert joined.read_bytes() == src.read_bytes()                     # the parts rejoin in net1's order
    # an event in both sets is a REGEN event (its rows are this run's prodlib rows)
    parts = em.split_net1(src, regen={"A2:2012"}, fnfix={"A2:2012"}, out_dir=tmp_path / "p2")
    assert (parts["july"][1], parts["fnfix"][1], parts["regenerated"][1]) == (4, 0, 2)


def _pq_rows(p: pathlib.Path, cols: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(cols), str(p))


def _edges(p: pathlib.Path, works: dict) -> None:
    """works {work_id: (year, [author ids])} -> <table>/authorship_edges/<dir>/<file> and <table>/works/<dir>/<file>."""
    rows = [(w, a, y) for w, (y, authors) in sorted(works.items()) for a in authors]
    _pq_rows(p, {"work_id": [r[0] for r in rows], "author_id": [r[1] for r in rows],
                 "publication_year": [r[2] for r in rows]})
    _pq_rows(p.parent.parent.parent / "works" / p.parent.name / p.name,
             {"work_id": sorted(works), "publication_year": [works[w][0] for w in sorted(works)]})


def _pm(p: pathlib.Path, m: dict) -> pathlib.Path:
    _pq_rows(p, {"author_id": sorted(m), "person_id": [m[a] for a in sorted(m)]})
    return p


SUP_LINE = json.dumps({"work_id": "WZ", "publication_year": 2001, "type": "article", "authors": ["AZ"]}) + "\n"


def _v3net_world(tmp_path, monkeypatch, *, recorded=None):
    """The October layout in miniature. The July graph = the mirror's edges + the U2 map; the 08-15 graph = its own
    snapshot copy (the mirror's rows + an overlay file holding W2, the only work linking star P_S2 and P_X) and its
    own person map (the U2 map + the singleton P_X). `recorded` = the root the frozen config names instead of this
    host's v2 (the author's machine); None = this host's paths."""
    mirror = tmp_path / "mirror" / "u1"
    base = {"W1": (2005, ["AS1", "AI1"]), "W4": (2006, ["AS1", "AM"]), "W5": (2015, ["AM", "AI2"]),
            "W3": (2010, ["AS3", "AI3"])}
    _edges(mirror / "authorship_edges" / "bucket=000" / "part-0.parquet", base)
    u2 = {"AS1": "P_S1", "AI1": "P_I1", "AM": "P_M", "AI2": "P_I2", "AS2": "P_S2", "AS3": "P_S3", "AI3": "P_I3"}
    pm_mirror = _pm(tmp_path / "mirror" / "u2" / "data.parquet", u2)
    v2 = tmp_path / "v2"
    aug = v2 / "rebuild" / "derived_aug" / "u1"
    _edges(aug / "authorship_edges" / "bucket=000" / "part-0.parquet", base)
    _edges(aug / "authorship_edges" / "overlay" / "part-supplement.parquet", {"W2": (2008, ["AS2", "AX"])})
    _pm(v2 / "rebuild" / "derived_aug" / "u2" / "data.parquet", {**u2, "AX": "P_X"})
    sup = v2 / em.SUP_FNFIX_REL
    sup.parent.mkdir(parents=True)
    sup.write_text(SUP_LINE, encoding="utf-8")
    monkeypatch.setitem(L.LEGACY_PINS, em.SUP_FNFIX_REL, sha(sup))
    (v2 / em.NEW_EVENTS_REL).write_text("author_id,name,school,arrival\nA2,n2,anu,2012\n", encoding="utf-8")
    root = recorded or str(v2)
    cfg = {"snapshot": {"edges_glob": f"{root}/rebuild/derived_aug/u1/authorship_edges/**/*.parquet",
                        "works_glob": f"{root}/rebuild/derived_aug/u1/works/**/*.parquet"},
           "supplement_jsonl": f"{root}/{em.SUP_FNFIX_REL}",
           "person_map": {"mode": "parquet", "path": f"{root}/rebuild/derived_aug/u2/data.parquet"}}
    (v2 / em.FNFIX_CONFIG_REL).parent.mkdir(parents=True)
    (v2 / em.FNFIX_CONFIG_REL).write_text(json.dumps(cfg), encoding="utf-8")
    return {"v2": v2, "mirror": mirror, "pm_mirror": pm_mirror, "aug": aug}


def test_fnfix_graph_is_the_frozen_0815_config_on_this_host(tmp_path, monkeypatch):
    w = _v3net_world(tmp_path, monkeypatch, recorded="/REC/v2_output")
    v2, aug = w["v2"], w["aug"]

    def rebase(cfg):                     # the recorded root -> this host (rebase_recorded_roots' job on EC2)
        return json.loads(json.dumps(cfg).replace("/REC/v2_output", str(v2))), ["snapshot.edges_glob"]
    g, rec = em.fnfix_graph(v2, rebase=rebase)
    assert g == em.nf.Graph(f"{aug}/authorship_edges/**/*.parquet", f"{aug}/works/**/*.parquet",
                            str(v2 / em.SUP_FNFIX_REL), str(v2 / "rebuild" / "derived_aug" / "u2" / "data.parquet"))
    assert rec["config_sha256"] == sha(v2 / em.FNFIX_CONFIG_REL) and rec["roots_rebased"] == ["snapshot.edges_glob"]
    assert (rec["edge_files"], rec["work_files"]) == (2, 2)          # the bucket and the overlay
    # a config whose roots this host does not serve names nothing here: a STOP, never an empty graph
    with pytest.raises(em.MStop) as e:
        em.fnfix_graph(v2, rebase=lambda cfg: (cfg, []))
    assert e.value.code == "FNFIX_GRAPH_MISSING"
    # the supplement must be the pinned frozen file
    monkeypatch.setitem(L.LEGACY_PINS, em.SUP_FNFIX_REL, "0" * 64)
    with pytest.raises(em.MStop) as e:
        em.fnfix_graph(v2, rebase=rebase)
    assert e.value.code == "FNFIX_GRAPH_PIN"
    # no frozen config at all
    (v2 / em.FNFIX_CONFIG_REL).unlink()
    with pytest.raises(em.MStop) as e:
        em.fnfix_graph(v2, rebase=rebase)
    assert e.value.code == "FNFIX_GRAPH_MISSING"


def test_network_freeze_step_classifies_each_row_group_on_its_builders_graph(tmp_path, monkeypatch):
    w = _v3net_world(tmp_path, monkeypatch)
    mirror = w["mirror"]
    monkeypatch.setattr(L, "person_map_path", lambda: w["pm_mirror"])
    shadow = tmp_path / "shadow"
    (shadow / em.SUP_FNFIX_REL).parent.mkdir(parents=True)
    (shadow / em.SUP_FNFIX_REL).write_text(SUP_LINE, encoding="utf-8")
    events = tmp_path / "events"
    events.mkdir()
    (events / "events_econ_cal2026-10.csv").write_text(
        "event_id,arrival_year\nA1:2010,2010\nA2:2012,2012\nA3:2015,2015\n", encoding="utf-8")
    keep_july, drop_july = net_lines("P_I1", "P_S1", "A1:2010", 2010), net_lines("P_I2", "P_S1", "A1:2010", 2010)
    fnfix, regen = net_lines("P_X", "P_S2", "A2:2012", 2012), net_lines("P_I3", "P_S3", "A3:2015", 2015)
    net1 = write_net(tmp_path / "net1.csv", keep_july + drop_july + fnfix + regen)
    prod_cfg = {"snapshot": {"edges_glob": f"{mirror}/authorship_edges/**/*.parquet",
                             "works_glob": f"{mirror}/works/**/*.parquet"},
                "supplement_jsonl": None, "person_map": {"mode": "parquet", "path": str(w["pm_mirror"])}}
    on = types.SimpleNamespace(is_on=lambda s: s == em.nf.SWITCH)
    ctx = types.SimpleNamespace(cfg=on, work=tmp_path / "work", net1=net1, plan=types.SimpleNamespace(
        regen={"A3:2015": {"kind": "added"}}), events_dir=events, prod_cfg=prod_cfg,
        sh=types.SimpleNamespace(path=lambda rel: shadow / rel), v2=w["v2"], report={})
    em.Steps().network_freeze(ctx)
    nfr = ctx.report["network_freeze"]
    zero = {"deg1": 0, "deg2_frozen": 0, "deg2_unfrozen": 0, "none": 0}
    assert nfr["parts"]["july"]["relations_by_class"] == {**zero, "deg1": 1, "deg2_unfrozen": 1}
    assert nfr["parts"]["fnfix"]["relations_by_class"] == {**zero, "deg1": 1}      # was 'none' on the July graph
    assert nfr["parts"]["regenerated"]["relations_by_class"] == {**zero, "deg1": 1}
    assert nfr["rows_by_part"] == {"july": 4, "fnfix": 2, "regenerated": 2}
    assert (nfr["rows_in"], nfr["rows_out"], nfr["relations_removed"]) == (8, 6, 1)
    assert nfr["graphs"]["fnfix"]["config_sha256"] == sha(w["v2"] / em.FNFIX_CONFIG_REL)
    assert ctx.allowances["removed"] == {("P_I2", "A1:2010")}
    assert ctx.net1.read_bytes() == ("\n".join([",".join(NET_COLS)] + keep_july + fnfix + regen) + "\n").encode()
    # the t-big-04 failure in miniature: the 08-15 rows on the July graph -> UNEXPLAINED, naming that relation
    july_graph = em.nf.Graph(prod_cfg["snapshot"]["edges_glob"], prod_cfg["snapshot"]["works_glob"],
                             str(shadow / em.SUP_FNFIX_REL), str(w["pm_mirror"]))
    with pytest.raises(em.nf.NetworkFreezeStop) as e:
        em.nf.apply(on, tmp_path / "work" / "network_freeze" / "net1_fnfix_rows.csv", tmp_path / "old" / "o.csv",
                    graph=july_graph, event_table=events / "events_econ_cal2026-10.csv")
    assert e.value.code == "UNEXPLAINED" and e.value.ids == [("P_X", "A2:2012")]


def test_a_rows_proof_stop_logs_the_proof(tmp_path, monkeypatch, capsys):
    """j1a-11: G_ROW_PROOF said only that a kept network row differs; the counts and the first rows go to
    the stage log (ids and numbers only), since a failed stage's work dir is not uploaded."""
    proof = {"closed": False, "counts": {"byte_identical": 5, "OTHER_DIFFERENCE": 1},
             "channel_moves": {}, "samples": [{"key": ["P_A1", "A2:2011", "2012"], "cols": ["age_gap"]}],
             "dept_only_rebuilt_changed": []}
    monkeypatch.setattr(em, "rows_proof_m", lambda *a, **k: proof)
    ctx = types.SimpleNamespace(frozen_pre_y=None, pre_y=None, regen={}, allowances=None, work=tmp_path, report={})
    with pytest.raises(em.MStop) as e:
        em.Steps().rows_proof(ctx)
    assert e.value.code == "G_ROW_PROOF"
    out = capsys.readouterr().out
    assert "rows proof" in out and "OTHER_DIFFERENCE" in out and "age_gap" in out


def _exstar_line(pid, year, event, *, pce="2", ffe="1.0", pc="2", ff="1.0", dose="0.5", age="3", fm=None, fme=None):
    """A dept_only frame row with the outcome cells settable (ex_star and plain; the means default to ff / ffe)."""
    star = event.split(":")[0]
    cells = [pid, str(year), star, event, "true", "true" if year >= int(event.split(":")[1]) else "false",
             "", dose, "false", age, ff, pc, ffe, pce, ff if fm is None else fm, ffe if fme is None else fme,
             "dept_only"]
    return ",".join(cells)


def test_rows_proof_explains_ex_star_only_changes_of_rebuilt_dept_rows(tmp_path):
    """j1a-12: 869 rebuilt dept_only rows differ from the frozen rows beyond the four columns 04 rewrites.
    A row whose ONLY changed cells are ex_star outcomes counts the same papers; the ex_star set changed
    (M's star set: new stars are stars everywhere, F11) -- explained and counted. Any other change stops."""
    frozen = write_frame(tmp_path / "frozen.csv", [
        _exstar_line("P_A100", 2005, "A11:2005"), _exstar_line("P_A101", 2006, "A11:2005"),
        _exstar_line("P_A102", 2007, "A11:2005")])
    ok = write_frame(tmp_path / "ok.csv", [
        _exstar_line("P_A100", 2005, "A11:2005", pce="1", ffe="0.5"),       # ex_star only
        _exstar_line("P_A101", 2006, "A11:2005"),                            # identical
        _exstar_line("P_A102", 2007, "A11:2005", pce="0")])                  # ex_star only
    proof = em.rows_proof_m(frozen, ok, set(), None, tmp_path)
    assert proof["closed"]
    assert proof["m_explained"]["ex_star_only"] == 2 and proof["m_explained"]["unexplained"] == 0
    for bad in (dict(pc="3"), dict(dose="0.6"), dict(age="4"), dict(pce="1", pc="3")):
        u = write_frame(tmp_path / "bad.csv", [_exstar_line("P_A100", 2005, "A11:2005", **bad)])
        p = em.rows_proof_m(frozen, u, set(), None, tmp_path)
        assert not p["closed"] and p["m_explained"]["unexplained"] == 1, bad


def test_a_rows_proof_stop_logs_the_unexplained_rows(tmp_path, monkeypatch, capsys):
    proof = {"closed": False, "counts": {"dept_only_rebuilt_changed_BEYOND_Y_SWAPPED": 1}, "channel_moves": {},
             "samples": [], "dept_only_rebuilt_changed": [{"key": ["P_A1", "A2:2011", "2012"], "cols": ["dose_topic"]}],
             "m_explained": {"ex_star_only": 0, "unexplained": 1,
                             "unexplained_rows": [{"key": ["P_A1", "A2:2011", "2012"], "cols": ["dose_topic"]}]}}
    monkeypatch.setattr(em, "rows_proof_m", lambda *a, **k: proof)
    ctx = types.SimpleNamespace(frozen_pre_y=None, pre_y=None, regen={}, allowances=None, work=tmp_path, report={})
    with pytest.raises(em.MStop):
        em.Steps().rows_proof(ctx)
    out = capsys.readouterr().out
    assert "rows proof row" in out and "dose_topic" in out


def test_rows_proof_explains_roster_fill_flips_of_rebuilt_dept_rows(tmp_path):
    """j1a-13: the M rosters move some person-years in or out of employment, so a rebuilt dept_only row's
    four outcome cells flip together between empty (not employed) and 0 (employed, no papers). Explained
    and counted by direction; a flip to or from a non-zero value, or one with any other change, stops."""
    zero = dict(pce="0", ffe="0.0", pc="0", ff="0.0", fm="", fme="")    # employed, no papers: means empty
    frozen = write_frame(tmp_path / "frozen.csv", [
        _exstar_line("P_A100", 2005, "A11:2005", **zero),
        _exstar_line("P_A101", 2006, "A11:2005", pce="", ffe="", pc="", ff="")])
    ok = write_frame(tmp_path / "ok.csv", [
        _exstar_line("P_A100", 2005, "A11:2005", pce="", ffe="", pc="", ff=""),            # 0 -> empty
        _exstar_line("P_A101", 2006, "A11:2005", **dict(zero, pce="0.0", pc="0.0"))])     # empty -> 0
    proof = em.rows_proof_m(frozen, ok, set(), None, tmp_path)
    assert proof["closed"]
    m = proof["m_explained"]
    assert m["roster_fill_zero_to_empty"] == 1 and m["roster_fill_empty_to_zero"] == 1 and m["unexplained"] == 0
    for bad in (dict(pce="", ffe="", pc="", ff="", dose="0.6"),                     # flip plus another change
                dict(pce="1", ffe="", pc="", ff="")):                               # a non-zero value
        u = write_frame(tmp_path / "bad.csv", [_exstar_line("P_A100", 2005, "A11:2005", **bad)])
        assert not em.rows_proof_m(frozen, u, set(), None, tmp_path)["closed"], bad


def test_rows_proof_explains_outcomes_the_r1_patch_now_supplies(tmp_path):
    """j1a-16: the clone takes an out-of-U5 incumbent's outcomes from the API patch first and falls back to the
    U1 edges only for people the patch lacks (00_build_frame_econ920_cal.py, v9). October had no patch rows
    for some people, so their frozen cells came from the edges; the R1 fetch now supplies them. A rebuilt
    dept_only row whose changed cells are all outcome cells, for a person of the R1 patch, is explained;
    the same change for anyone else stops."""
    frozen = write_frame(tmp_path / "frozen.csv", [_exstar_line("P_A100", 2015, "A11:2005", pc="6", ff="2.0"),
                                                   _exstar_line("P_A101", 2015, "A11:2005", pc="6", ff="2.0")])
    new = write_frame(tmp_path / "new.csv", [_exstar_line("P_A100", 2015, "A11:2005", pc="4", ff="1.1")])
    need = {"A100", "A101"}                       # the clone's need_outcomes (outside U5's output table)
    p = em.rows_proof_m(frozen, new, set(), None, tmp_path, r1_persons={"A100"}, need_outcomes=need)
    assert p["closed"] and p["m_explained"]["r1_patch_replaces_edges_fallback"] == 1
    other = write_frame(tmp_path / "other.csv", [_exstar_line("P_A101", 2015, "A11:2005", pc="4", ff="1.1")])
    assert not em.rows_proof_m(frozen, other, set(), None, tmp_path, r1_persons={"A100"}, need_outcomes=need)["closed"]
    dose = write_frame(tmp_path / "dose.csv", [_exstar_line("P_A100", 2015, "A11:2005", pc="4", dose="0.7")])
    assert not em.rows_proof_m(frozen, dose, set(), None, tmp_path, r1_persons={"A100"}, need_outcomes=need)["closed"]
    # Codex delta-3 #4: in the R1 patch but inside U5's output table, the clone uses U5, not the patch
    assert not em.rows_proof_m(frozen, new, set(), None, tmp_path, r1_persons={"A100"},
                               need_outcomes={"A101"})["closed"]


def test_r1_patch_persons_reads_the_supplement_ids(tmp_path):
    p = tmp_path / "sup.jsonl"
    p.write_text('{"author_id": "A100", "work_id": "W1"}\n{"author_id": "A100", "work_id": "W2"}\n'
                 '{"author_id": "A102", "work_id": "W3"}\n', encoding="utf-8")
    assert em.r1_patch_persons(p) == {"A100", "A102"}
    assert em.r1_patch_persons(None) == set() and em.r1_patch_persons(tmp_path / "absent.jsonl") == set()


# ---- Codex delta-3 (2026-10-17): the explained classes admit only what they name ------------------------------
def test_a_partial_fill_flip_is_not_a_roster_fill(tmp_path):
    """#3: the clone writes an employed year without papers as fwci_frac / pub_count / their ex_star twins = 0
    and both means empty, and a year outside employment as all six empty. Only a switch between those two
    whole rows is a roster fill; one cell emptied out of a zero row is not."""
    zero = dict(pce="0", ffe="0.0", pc="0", ff="0.0", fm="", fme="")
    frozen = write_frame(tmp_path / "frozen.csv", [_exstar_line("P_A100", 2005, "A11:2005", **zero)])
    for part in (dict(zero, pc=""), dict(zero, pc="", ff=""), dict(zero, fm="0.0")):
        u = write_frame(tmp_path / "part.csv", [_exstar_line("P_A100", 2005, "A11:2005", **part)])
        p = em.rows_proof_m(frozen, u, set(), None, tmp_path)
        assert not p["closed"] and p["m_explained"]["unexplained"] == 1, part


def test_ex_star_only_rejects_impossible_counts(tmp_path):
    """#5: an ex_star count above the row's own count, negative, or not a whole number is not an ex_star change."""
    frozen = write_frame(tmp_path / "frozen.csv", [_exstar_line("P_A100", 2005, "A11:2005")])
    for bad in ("99", "-1", "1.5", "x"):
        u = write_frame(tmp_path / "bad.csv", [_exstar_line("P_A100", 2005, "A11:2005", pce=bad)])
        p = em.rows_proof_m(frozen, u, set(), None, tmp_path)
        assert not p["closed"] and p["m_explained"]["unexplained"] == 1, bad


def test_b0_rows_proof_keeps_octobers_verdict(tmp_path):
    """#1: the M classes never close a B0 proof (B0 has no M star set, rosters or patch)."""
    frozen = write_frame(tmp_path / "frozen.csv", [_exstar_line("P_A100", 2005, "A11:2005")])
    u = write_frame(tmp_path / "u.csv", [_exstar_line("P_A100", 2005, "A11:2005", pce="1", ffe="0.5")])
    assert em.rows_proof_m(frozen, u, set(), None, tmp_path)["closed"]
    p = em.rows_proof_m(frozen, u, set(), None, tmp_path, m_rules=False)
    assert not p["closed"] and p["m_explained"]["ex_star_only"] == 1
