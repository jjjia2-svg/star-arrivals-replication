# -*- coding: utf-8 -*-
"""pipeline/aws/r1/calls_lib.py - the work-level call sets of B0 (October) and M (R1 F8), on toy tables.

Every table is built here: an in-memory duckdb `aw_raw` with a few rows, toy paper checks, a toy merged
candidate table. No data disk, no legacy tree, no network."""
from __future__ import annotations

import csv
import json
import pathlib
import re
import sys
import types

import duckdb
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import calls_lib as cl          # noqa: E402
import rk6_requests as rq       # noqa: E402
import rk6b_rank as rb          # noqa: E402

# main A1000001 (a fixes_1001 merge with alias A1000002); A1000003 + A1000004 (a split id,
# a person_overrides merge); A1000005 + A1000006 (a multi-id add-list row); A1000007 (an RK4 min_year cut at 1990);
# A1000008 (an own book review W80 excluded by the paper checks); A1000010 holds W90, which the
# 2026-08-13 split-id adds give to A1000009.
AW = [("A1000001", "W1", 1995), ("A1000001", "W2", 2000), ("A1000001", "W3", 2005),
      ("A1000002", "W20", 2001),
      ("A1000003", "W30", 2002), ("A1000004", "W40", 2003),
      ("A1000005", "W50", 2004), ("A1000006", "W60", 2004),
      ("A1000007", "W70", 1980), ("A1000007", "W71", 1999),
      ("A1000008", "W80", 1998), ("A1000008", "W81", 2001),
      ("A1000010", "W90", 1997)]
MERGED_COLS = ["person_id", "all_ids", "name", "field", "school", "arrival_year", "status", "status_reason", "sources"]


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("CREATE TEMP TABLE aw_raw(aid VARCHAR, wid VARCHAR, yr INTEGER, c BIGINT, sf VARCHAR)")
    c.executemany("INSERT INTO aw_raw VALUES (?,?,?,?,?)", [(a, w, y, 1, "2002") for a, w, y in AW])
    yield c
    c.close()


def _fake_rc(hist_drops=frozenset({("A1000001", "W3")}), hist_adds=frozenset({("A1000009", "W90")}),
             oct_drops=frozenset({("A1000003", "W40")})):
    return types.SimpleNamespace(historical_calls=lambda: (set(hist_drops), set(hist_adds), {"x": "sha"}),
                                 october_calls=lambda: (set(oct_drops), [{"author_id": "A1000003"}]))


def _req(pid, ids=None, excl=(), min_year=None, field="econ", y=2009, checked=False):
    return {"key": f"{field}|{pid}|Y{y}", "person": pid, "ids": list(ids or [pid]), "Y": y, "field": field,
            "exclude_wids": sorted(excl), "min_year": min_year, "cleaning": True, "prior_cleaning": False,
            "paper_checked": checked, "id_corrected": False, "needs_paper_review": False, "reason": "r",
            "src": "G0", "status": "rank", "note": ""}


def _write_csv(p, cols, rows):
    with open(p, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    return p


def _paper_checks(base, people):
    """people: {pid: (round1 exclude_wids, works list)} - both rounds agree."""
    root = base / "paper_checks"
    works = base / "rk6a" / "review_pack" / "works"
    for d in (root / "round1", root / "round2", works):
        d.mkdir(parents=True, exist_ok=True)
    for pid, (excl, wids) in people.items():
        (root / "round1" / f"{pid}.json").write_text(json.dumps({
            "schema": "sar.r1.paper_read.v1", "person_id": pid, "id_ok": True, "correct_ids": [], "merge_ids": [],
            "exclude_wids": list(excl), "uncertain_wids": [], "first_pub_year": 1990, "summary": "s",
            "sources": ["https://example.org/a"], "agent": "reader-1"}))
        (root / "round2" / f"{pid}.json").write_text(json.dumps({
            "schema": "sar.r1.paper_check2.v1", "person_id": pid, "verdict": "agree", "id_ok": True, "correct_ids": [],
            "wrongly_excluded_wids": [], "missed_wids": [], "merge_ids_add": [], "merge_ids_drop": [], "note": "n",
            "sources": ["https://example.org/b"], "agent": "checker-1"}))
        (works / f"{pid}.json").write_text(json.dumps({"person_id": pid, "ids": [pid], "Y": 2009,
                                                       "works": [{"wid": w} for w in wids]}))
    return root, works


def _links_files(base):
    ov = _write_csv(base / "person_overrides.csv", ["author_id", "action", "value", "reason", "source"], [
        {"author_id": "A1000003", "action": "merge_ids", "value": "A1000004", "reason": "split id", "source": "SW:1"},
        {"author_id": "A1000007", "action": "arrival_year", "value": "2007", "reason": "a re-date", "source": "P2"}])
    fx = _write_csv(base / "fixes_1001.csv", ["author_id", "fix", "value", "decided", "evidence"], [
        {"author_id": "A1000001", "fix": "merge_ids", "value": "A1000002", "decided": "author", "evidence": "e"},
        {"author_id": "A1000008", "fix": "redate", "value": "2008", "decided": "author", "evidence": "e"}])
    al = base / "add_list_r1.json"
    al.write_text(json.dumps({"schema": "s", "rows": [
        {"person_id": "A1000005", "all_ids": "A1000005|A1000006", "verdict": "ACCEPT"},
        {"person_id": "A1999990", "all_ids": "A1999990|A1999991", "verdict": "REJECT"}]}))
    return ov, fx, al


def _keep(base, rows):
    return _write_csv(base / "dose_keep_r1.csv", ["person_id", "work_id", "why", "source"],
                      [dict(r, why="own book review, citations conflated", source="paper_checks/round1/x.json") for r in rows])


# ------------------------------------------------------------------------------------------------------------
def test_b0_sets_are_the_october_restake_inputs(tmp_path):
    """B0 = October: drops = historical calls | October calls, adds = the 08-13 split-id adds, nothing leaves the
    dose. The in-stage control holds B0 to the recovered RK1 inputs (the 10-02 run that reproduced all 187)."""
    rc = _fake_rc()
    cs = cl.b0(rc)
    assert cs.name == "B0"
    assert cs.drops == frozenset({("A1000001", "W3"), ("A1000003", "W40")})
    assert cs.adds == frozenset({("A1000009", "W90")})
    assert cs.dose_excludes == frozenset() and cs.rank_adds == {}
    cl.b0_control(cs, {("A1000001", "W3"), ("A1000003", "W40")}, {("A1000009", "W90")})      # equal: passes
    with pytest.raises(SystemExit, match="STOP B0 drops differ from RK1"):
        cl.b0_control(cs, {("A1000001", "W3")}, {("A1000009", "W90")})
    with pytest.raises(SystemExit, match="STOP B0 adds differ from RK1"):
        cl.b0_control(cs, set(cs.drops), set())


def test_m_adds_paper_check_exclusions_merges_and_fixes(tmp_path, con, monkeypatch):
    calls = []
    real = rq.load_paper_checks

    def spy(*a, **k):
        calls.append(a)
        return real(*a, **k)
    monkeypatch.setattr(rq, "load_paper_checks", spy)
    pc, works = _paper_checks(tmp_path, {"A1000001": (["W2"], ["W1", "W2"]), "A1000008": (["W80"], ["W80", "W81"])})
    merged = _write_csv(tmp_path / "candidates_merged.csv", MERGED_COLS, [
        {"person_id": "A1000001", "all_ids": "A1000001|A1000002", "field": "econ", "arrival_year": "2010", "status": "rank", "sources": "G0"},
        {"person_id": "A1000003", "all_ids": "A1000003|A1000004", "field": "econ", "arrival_year": "2010", "status": "rank", "sources": "G1"},
        {"person_id": "A1000005", "all_ids": "A1000005|A1000006", "field": "chemistry", "arrival_year": "2010", "status": "rank", "sources": "G1"},
        {"person_id": "A1000007", "all_ids": "A1000007", "field": "math_stats", "arrival_year": "2010", "status": "rank", "sources": "G0"},
        {"person_id": "A1000008", "all_ids": "A1000008", "field": "econ", "arrival_year": "2010", "status": "rank", "sources": "G0"}])
    rk4 = [{"key": "k", "ids": ["A1000007"], "exclude_wids": [], "min_year": 1990, "cleaning": True, "reason": "namesake"}]
    reqs, skipped, checks = cl.fold_requests(merged, rk4, pc, works)
    assert len(calls) == 1, "load_paper_checks parsed the checks more than once"
    assert skipped == [] and set(checks) == {"A1000001", "A1000008"}
    base = cl.b0(_fake_rc())
    links = cl.merge_links(*_links_files(tmp_path))
    cs = cl.m(base, reqs, con, keep_rows=[], links=links)
    excl = {(a, w) for q in reqs for a in q["ids"] for w in q["exclude_wids"]}
    assert cs.name == "M"
    assert cs.drops >= base.drops | excl
    assert {("A1000001", "W2"), ("A1000002", "W2"), ("A1000008", "W80")} <= cs.drops
    assert cs.rank_adds == {"A1000001": ("A1000002",), "A1000003": ("A1000004",), "A1000005": ("A1000006",)}
    assert ("A1000001", "W20") in cs.adds and ("A1000005", "W60") in cs.adds
    assert base.adds <= cs.adds
    assert cs.dose_excludes == cs.drops - cs.adds


def test_merge_links_must_be_in_the_rank_requests(tmp_path, con):
    """A person_overrides / fixes_1001 / add-list merge that the requests carry only half of is a STOP; a merge
    of someone the requests never rank is only listed."""
    links = cl.merge_links(*_links_files(tmp_path))
    assert ("A1000003", "A1000004", "person_overrides") in links and ("A1000001", "A1000002", "fixes_1001") in links
    assert ("A1000005", "A1000006", "add_list") in links and not any(a == "A1999990" for a, _, _ in links)
    reqs = [_req("A1000001", ["A1000001", "A1000002"]), _req("A1000003")]
    with pytest.raises(SystemExit, match="STOP merge link not in the rank requests: A1000003 A1000004"):
        cl.m(cl.b0(_fake_rc()), reqs, con, links=links)
    unranked = cl.check_links([_req("A1000001", ["A1000001", "A1000002"])], links)
    assert unranked == ["A1000003", "A1000005"]


def test_rank_adds_never_reach_dose_excludes(con):
    """An add pair (incl. every pair a merged alias brings) is never in dose_excludes, even when an old call
    named it: the ranking counts it, so the dose keeps it."""
    base = cl.b0(_fake_rc(hist_drops={("A1000009", "W90"), ("A1000003", "W40")}, oct_drops=set()))
    reqs = [_req("A1000003", ["A1000003", "A1000004"])]
    cs = cl.m(base, reqs, con)
    assert ("A1000009", "W90") in cs.adds and ("A1000009", "W90") in cs.drops
    assert cs.rank_adds == {"A1000003": ("A1000004",)}
    assert ("A1000003", "W40") in cs.adds and ("A1000003", "W40") in cs.drops     # an old call under the main id
    assert not (cs.adds & cs.dose_excludes)
    for main, aliases in cs.rank_adds.items():
        for alias in aliases:
            for a, w, _ in AW:
                if a == alias:
                    assert (alias, w) not in cs.dose_excludes and (main, w) not in cs.dose_excludes


def test_an_alias_without_works_and_an_add_without_its_work_are_recorded(con, tmp_path):
    """j1a-03: 96 merged aliases have no works in the 11-school table the ranking's pass B reads, so the merge
    adds nothing to the ranking (which reproduced its signed reference) or to the dose. That is recorded, not a
    STOP; an add pair whose work is absent is a real inconsistency and still stops."""
    cs = cl.CallSet(name="M", drops=frozenset(), adds=frozenset(), rank_adds={"A1000003": ("A1999999",)},
                    dose_excludes=frozenset())
    assert cl.expand(con, cs) == (["A1999999"], [])
    # j1a-04: an add whose work is not in aw_raw is dropped by the ranking's own join (run_caliber
    # restake_with_adds: addt JOIN aw_raw ON wid), so it is recorded the same way, not a STOP
    cs = cl.CallSet(name="M", drops=frozenset(), adds=frozenset({("A1000009", "W999")}), rank_adds={},
                    dose_excludes=frozenset())
    assert cl.expand(con, cs) == ([], [("A1000009", "W999")])
    cs = cl.m(cl.b0(_fake_rc()), [_req("A1000003", ["A1000003", "A1999999"])], con)
    assert cs.aliases_without_works == frozenset({"A1999999"}) and cs.adds_without_work == frozenset()
    s = cl.write_outputs(cs, tmp_path / "out")
    assert s["counts"]["rank_add_aliases_without_works"] == 1 and s["ids"]["rank_add_aliases_without_works"] == ["A1999999"]
    assert s["counts"]["adds_without_work"] == 0


def test_min_year_cut_is_expanded_into_drops_and_dose(con, monkeypatch):
    seen = []
    real = rb.pass_b_cleaning

    def spy(c, reqs, drops):
        seen.append(len(reqs))
        return real(c, reqs, drops)
    monkeypatch.setattr(rb, "pass_b_cleaning", spy)
    cs = cl.m(cl.b0(_fake_rc()), [_req("A1000007", min_year=1990)], con)
    assert seen, "the min_year cut was not expanded by rk6b_rank.pass_b_cleaning"
    assert ("A1000007", "W70") in cs.drops and ("A1000007", "W70") in cs.dose_excludes
    assert ("A1000007", "W71") not in cs.drops
    assert "min_year" in cs.drop_src[("A1000007", "W70")]
    # RK4 min_year reasons: a namesake reason passes, no reason is listed, any other reason is a STOP
    rk4 = [{"ids": ["A1000007"], "min_year": 1990, "cleaning": True, "reason": "namesake: a 1980 chemist"},
           {"ids": ["A1000011"], "min_year": 1985, "cleaning": True}]
    assert cl.check_min_year(rk4) == {"namesake": ["A1000007"], "no_reason": ["A1000011"]}
    with pytest.raises(SystemExit, match="STOP min_year cut without a namesake reason: A1000012"):
        cl.check_min_year(rk4 + [{"ids": ["A1000012"], "min_year": 1990, "cleaning": True, "reason": "career gap"}])


def test_dose_keep_rows_stay_in_drops_but_leave_dose(tmp_path, con):
    reqs = [_req("A1000008", excl=["W80"])]
    keep = cl.load_dose_keep(_keep(tmp_path, [{"person_id": "A1000008", "work_id": "W80"}]))
    cs = cl.m(cl.b0(_fake_rc()), reqs, con, keep_rows=keep)
    assert ("A1000008", "W80") in cs.drops and ("A1000008", "W80") not in cs.dose_excludes
    assert cs.dose_kept == frozenset({("A1000008", "W80")})
    bad = cl.load_dose_keep(_keep(tmp_path, [{"person_id": "A1000008", "work_id": "W81"}]))
    with pytest.raises(SystemExit, match="STOP dose_keep row not among the person's exclusions: A1000008 W81"):
        cl.m(cl.b0(_fake_rc()), reqs, con, keep_rows=bad)
    off = cl.m(cl.b0(_fake_rc()), reqs, con, keep_rows=keep, dose_on=False)
    assert off.dose_excludes == frozenset() and ("A1000008", "W80") in off.drops


def test_the_committed_dose_keep_file_is_well_formed():
    rows = cl.load_dose_keep(REPO / "data" / "cal2026-10r1" / "inputs" / "dose_keep_r1.csv")
    assert ("A5010870813", "W1546006912") in {(r["person_id"], r["work_id"]) for r in rows}
    assert ("A5010870813", "W1481080069") in {(r["person_id"], r["work_id"]) for r in rows}
    assert all(r["why"].strip() and (REPO / r["source"]).is_file() for r in rows)


def test_adjudication_and_paper_check_gates(tmp_path, con):
    reqs = [_req("A1000008", excl=["W80"], checked=True), _req("A1000001", checked=True)]
    cs = cl.m(cl.b0(_fake_rc(hist_drops=set(), oct_drops=set())), reqs, con)
    adj = {"works": [{"person_id": "A1000008", "wid": "W80", "final": "exclude"},
                     {"person_id": "A1000001", "wid": "W1", "final": "keep"}]}
    assert cl.gate_adjudication(cs, reqs, adj) == {"exclude": 1, "keep": 1}
    with pytest.raises(SystemExit, match="STOP adjudication 'exclude' not in dose_excludes: A1000001 W2"):
        cl.gate_adjudication(cs, reqs, {"works": [{"person_id": "A1000001", "wid": "W2", "final": "exclude"}]})
    with pytest.raises(SystemExit, match="STOP adjudication 'keep' in dose_excludes: A1000008 W80"):
        cl.gate_adjudication(cs, reqs, {"works": [{"person_id": "A1000008", "wid": "W80", "final": "keep"}]})
    checks = {"A1000008": {}, "A1000001": {}}
    assert cl.gate_paper_checked(checks, reqs, [], expect=2) == 2
    with pytest.raises(SystemExit, match="STOP paper-checked persons 2, expected 209"):
        cl.gate_paper_checked(checks, reqs, [], expect=209)
    with pytest.raises(SystemExit, match="STOP paper-checked person neither ranked nor skipped: A1000020"):
        cl.gate_paper_checked(dict(checks, A1000020={}), reqs, [], expect=3)


def test_written_files_are_sorted_and_id_only(tmp_path, con):
    pc, works = _paper_checks(tmp_path, {"A1000008": (["W80"], ["W80", "W81"])})
    reqs = [_req("A1000001", ["A1000001", "A1000002"], excl=["W2"]), _req("A1000007", min_year=1990),
            _req("A1000008", excl=["W80"], checked=True), _req("A1000003", ["A1000003", "A1000004"])]
    keep = cl.load_dose_keep(_keep(tmp_path, [{"person_id": "A1000008", "work_id": "W80"}]))
    outs = []
    for k in ("a", "b"):
        cs = cl.m(cl.b0(_fake_rc()), list(reversed(reqs)) if k == "b" else reqs, con, keep_rows=keep)
        out = tmp_path / k
        cl.write_outputs(cs, out, ids={"skipped": [], "min_year_persons": ["A1000007"]}, counts={"paper_checked": 1})
        outs.append(out)
    names = ("drops.csv", "dose_excludes.csv", "adds.csv", "rank_adds.json", "summary.json")
    for n in names:
        assert (outs[0] / n).read_bytes() == (outs[1] / n).read_bytes(), n
    for n in ("drops.csv", "dose_excludes.csv", "adds.csv"):
        rows = list(csv.reader(open(outs[0] / n, encoding="utf-8", newline="")))
        assert rows[0] == ["person_id", "work_id", "source"]
        assert rows[1:] == sorted(rows[1:]) and len(rows) > 1
        assert all(re.fullmatch(r"A\d+", r[0]) and re.fullmatch(r"W\d+", r[1]) for r in rows[1:])
        assert b"\r\n" not in (outs[0] / n).read_bytes()
    assert json.loads((outs[0] / "rank_adds.json").read_text()) == {"A1000001": ["A1000002"], "A1000003": ["A1000004"]}
    summ = json.loads((outs[0] / "summary.json").read_text())
    assert summ["result"] == "OK" and summ["name"] == "M"

    def leaves(x):
        if isinstance(x, dict):
            for v in x.values():
                yield from leaves(v)
        elif isinstance(x, list):
            for v in x:
                yield from leaves(v)
        else:
            yield x
    for v in leaves({k: v for k, v in summ.items() if k not in ("result", "name")}):
        assert isinstance(v, int) or re.fullmatch(r"[AW]\d+", str(v)), v
    assert summ["counts"]["dose_kept"] == 1 and summ["counts"]["paper_checked"] == 1


def test_main_refuses_off_an_r1_instance(monkeypatch, tmp_path):
    monkeypatch.delenv("SAR_HOST", raising=False)
    with pytest.raises(SystemExit, match="runs only on an R1 AWS instance"):
        cl.main(["--config", "x", "--repo", str(REPO), "--requests", "x", "--recovered", "x", "--merged", "x",
                 "--rk6a", "x", "--paper-checks", "x", "--adjudication", "x", "--dose-keep", "x",
                 "--overrides", "x", "--fixes", "x", "--add-list", "x", "--expect-paper-checked", "209",
                 "--out", str(tmp_path / "o")])
    assert not (tmp_path / "o").exists()
