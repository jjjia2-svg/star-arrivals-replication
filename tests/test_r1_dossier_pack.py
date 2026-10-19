# -*- coding: utf-8 -*-
"""pipeline/aws/r1/dossier_pack.py - J0-MEAS.3e dossiers: who needs one, and what each one holds.

Toy inputs only: paper-check files, RK4 derivation files and a duckdb database, all in tmp_path."""
from __future__ import annotations

import csv
import json
import pathlib
import sys

import duckdb
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import dossier_pack as dp   # noqa: E402

TARGETS = REPO / "data" / "cal2026-10r1" / "inputs" / "j0_dossier_targets.json"


def _write(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _rounds(d, pid, exclude=(), missed=(), wrongly=(), merge=()):
    _write(d / "round1" / f"{pid}.json", {"schema": "sar.r1.paper_read.v1", "person_id": pid, "id_ok": True,
                                          "correct_ids": [], "merge_ids": list(merge), "exclude_wids": list(exclude),
                                          "agent": "reader-1"})
    _write(d / "round2" / f"{pid}.json", {"schema": "sar.r1.paper_check2.v1", "person_id": pid, "id_ok": True,
                                          "correct_ids": [], "wrongly_excluded_wids": list(wrongly),
                                          "missed_wids": list(missed), "merge_ids_add": [], "merge_ids_drop": [],
                                          "agent": "checker-1"})


def _derived(d, prefix="derived/rk1"):
    base = d / prefix
    _write(base / "rk4in" / "requests.json", [
        {"key": "econ|b two", "ids": ["A2000002"], "Y": 2009, "field": "econ", "exclude_wids": ["W77"],
         "min_year": 1990, "cleaning": True},
        {"key": "econ|d four", "ids": ["A2000004", "A2000044"], "Y": 2011, "field": "econ", "exclude_wids": [],
         "min_year": None, "cleaning": True}])                    # a bare merge: cleaning flag, no two-round check
    _write(base / "papers" / "cleaning_final.json", {"econ|b two": {"mark": ["W77"], "check": "agree"}})
    return d


def _add(pid, verdict="ACCEPT", arrival=2012, ids=None, field="econ", name="Jane Secret"):
    return {"person_id": pid, "all_ids": ids or pid, "name": name, "field": field, "school": "x", "dept_key": "",
            "arrival_year": arrival, "verdict": verdict, "basis": "own-discipline top 10% (R-Rank)", "decided": "d",
            "pct_own": "", "sources": "G1"}


def _flip(pid, field="econ"):
    return {"person_id": pid, "name": "Star Secret", "field": field, "verdict": "KEEP", "flip": "none",
            "pct_own": "0.9", "decided": "d"}


@pytest.fixture
def world(tmp_path):
    pc = tmp_path / "paper_checks"
    _rounds(pc, "A1000001")
    _rounds(pc, "A9000001")                                      # a named G0 star who was checked already
    der = _derived(tmp_path / "derived")
    adds = [_add("A1000001"), _add("A2000002"), _add("A3000003"), _add("A2000004", ids="A2000004|A2000044"),
            _add("A5000005", verdict="REJECT")]
    flips = [_flip("A9000001"), _flip("A9000002"), _flip("A9000003")]
    return {"pc": pc, "der": der, "adds": adds, "flips": flips}


@pytest.mark.parametrize("prefix", ["derived/rk1", "rk1"])
def test_accept_rows_are_classified_by_their_prior_check(tmp_path, prefix):
    pc = tmp_path / "paper_checks"
    _rounds(pc, "A1000001")
    der = _derived(tmp_path / "derived", prefix)
    adds = [_add("A1000001"), _add("A2000002"), _add("A3000003"), _add("A2000004", ids="A2000004|A2000044"),
            _add("A5000005", verdict="REJECT")]
    assert dp.classify(adds, pc, der) == {"A1000001": "r1_rounds", "A2000002": "rk4_two_round",
                                          "A3000003": "no_check", "A2000004": "no_check"}
    tg = dp.targets(adds, [], pc, der, [])
    assert [t["person_id"] for t in tg] == ["A2000004", "A3000003"]
    assert all(t["reasons"] == ["accept_no_check"] and t["prior_check"] == "no_check" for t in tg)
    by = {t["person_id"]: t for t in tg}
    assert by["A3000003"]["Y"] == 2011 and by["A3000003"]["checks"] == ["two_round"]
    assert by["A2000004"]["ids"] == ["A2000004", "A2000044"]


def test_an_unknown_cleaning_layout_or_a_missing_derivation_stops(tmp_path):
    pc = tmp_path / "paper_checks"
    der = _derived(tmp_path / "derived")
    _write(der / "derived" / "rk1" / "papers" / "cleaning_final.json", {"no sweep keys": 1})
    with pytest.raises(SystemExit, match="cleaning_final.json"):
        dp.classify([_add("A3000003")], pc, der)
    with pytest.raises(SystemExit, match="rk4in/requests.json"):
        dp.classify([_add("A3000003")], pc, tmp_path / "empty")


def test_named_targets_are_always_included_with_their_reason(world, tmp_path):
    named = [{"person_id": "A9000001", "reason": "h8_A5087235620", "check": "two_round"},
             {"person_id": "A9000002", "reason": "h10", "check": "material"},
             {"person_id": "A9000003", "reason": "u2_A5001177483", "check": "coverage", "ids": ["A9000033"],
              "flag_wids": ["W2990425360"]},
             {"person_id": "A3000003", "reason": "u2_A5008470795", "check": "coverage"}]
    _write(tmp_path / "t.json", {"schema": "sar.r1.dossier_targets.v1", "targets": named})
    tg = dp.targets(world["adds"], world["flips"], world["pc"], world["der"], dp.load_named(tmp_path / "t.json"))
    by = {t["person_id"]: t for t in tg}
    assert by["A9000001"]["reasons"] == ["h8_A5087235620"] and by["A9000001"]["prior_check"] == "r1_rounds"
    assert by["A9000002"]["reasons"] == ["h10"] and by["A9000002"]["checks"] == ["material"]
    assert by["A9000002"]["Y"] is None                            # a G0 star: Y comes from RK6a later
    assert by["A9000003"]["ids"] == ["A9000003", "A9000033"] and by["A9000003"]["flag_wids"] == ["W2990425360"]
    assert by["A3000003"]["reasons"] == ["accept_no_check", "u2_A5008470795"]
    assert by["A3000003"]["checks"] == ["two_round", "coverage"] and by["A3000003"]["Y"] == 2011
    assert "A1000001" not in by and "A2000002" not in by
    with pytest.raises(SystemExit, match="A7777777"):             # named, but in neither the 187 nor the add list
        dp.targets(world["adds"], world["flips"], world["pc"], world["der"],
                   [{"person_id": "A7777777", "reason": "h10", "check": "identity"}])


def test_the_committed_target_list_holds_ids_and_codes_only():
    named = dp.load_named(TARGETS)
    got = {(n["person_id"], n["reason"], n["check"]) for n in named}
    assert got == {("A5087235620", "h8_A5087235620", "two_round"),
                   ("A5082727271", "h10", "identity"), ("A5073639630", "h10", "identity"),
                   ("A5059554264", "h10", "material"), ("A5024973435", "h10", "material"),
                   ("A5001177483", "u2_A5001177483", "coverage"), ("A5008470795", "u2_A5008470795", "coverage")}
    u2_target = next(n for n in named if n["reason"] == "u2_A5001177483")
    assert u2_target["flag_wids"] == ["W2990425360", "W3133654284", "W3145273755"]
    flips = {r["person_id"] for r in json.loads((TARGETS.parent / "flips_r1.json").read_text(encoding="utf-8"))["rows"]}
    assert {n["person_id"] for n in named} <= flips                 # every named target is one of the 187
    with pytest.raises(SystemExit, match="name"):
        dp.check_named({"schema": "sar.r1.dossier_targets.v1",
                        "targets": [{"person_id": "A5087235620", "reason": "h8_A5087235620", "check": "two_round",
                                     "name": "someone"}]})


def _con(tmp_path, name="toy.duckdb"):
    con = duckdb.connect(str(tmp_path / name))
    con.execute("CREATE TEMP TABLE aw_raw(aid VARCHAR, wid VARCHAR, yr INTEGER, c BIGINT, sf VARCHAR)")
    con.executemany("INSERT INTO aw_raw VALUES (?,?,?,?,?)", [
        ("A1", "W1", 2005, 10, "2002"), ("A1", "W2", 2008, 3, "3312"), ("A1", "W3", 2010, None, None),
        ("A1", "W4", 2011, 99, "2002"),                             # after Y: dropped
        ("A2", "W5", 2009, 7, "2002"), ("A2", "W6", 2004, 1, "2002"),
        ("X", "W7", 2006, 50, "2002")])                             # someone else: never listed
    con.execute("CREATE TEMP TABLE work_text(work_id VARCHAR, title VARCHAR)")
    con.executemany("INSERT INTO work_text VALUES (?,?)", [("W1", "SECRET TITLE one"), ("W2", "two"), ("W5", "five")])
    con.execute("CREATE TEMP TABLE pm(author_id VARCHAR, person_id VARCHAR)")
    con.executemany("INSERT INTO pm VALUES (?,?)", [("A1", "P1"), ("A2", "P1"), ("X", "P2")])
    return con


def test_works_for_keeps_works_up_to_y_and_marks_prior_exclusions(tmp_path):
    pc = tmp_path / "paper_checks"
    _rounds(pc, "A1", exclude=["W2", "W5"], missed=["W3"], wrongly=["W5"])
    _write(pc / "extra" / "A1.json", {"schema": "sar.r1.paper_extra.v1", "person_id": "A1", "profile_ids": ["A2"],
                                      "merge_ids": ["A2"], "exclude_wids": ["W6"], "decided": "d", "agent": "x"})
    excl = dp.prior_exclusions(pc, "A1")
    assert excl == {"W2", "W3", "W6"}                               # round 2 restored W5
    rows = dp.works_for(_con(tmp_path), ["A1", "A2"], 2010, excluded=excl)
    assert [(r["aid"], r["yr"], r["wid"]) for r in rows] == [
        ("A1", 2005, "W1"), ("A1", 2008, "W2"), ("A1", 2010, "W3"), ("A2", 2004, "W6"), ("A2", 2009, "W5")]
    assert {r["wid"]: r["prior_excluded"] for r in rows} == {"W1": False, "W2": True, "W3": True, "W6": True,
                                                            "W5": False}
    w1 = rows[0]
    assert (w1["c"], w1["sf"], w1["title"]) == (10, "2002", "SECRET TITLE one")
    assert rows[2]["c"] is None and rows[2]["title"] is None
    cut = dp.works_for(_con(tmp_path, "cut.duckdb"), ["A1"], 2010, excluded=set(),
                       min_year=2006)                               # an RK4 min_year cut marks the earlier works
    assert {r["wid"]: r["prior_excluded"] for r in cut} == {"W1": True, "W2": False, "W3": False}


def _run(tmp_path, tg, rk6a=None):
    out = tmp_path / "out"
    rk6a = rk6a or tmp_path / "rk6a"
    con = _con(tmp_path)
    dp.expand(con, tg, rk6a)
    result = dp.write_dossiers(con, tg, {"r1_rounds": 3, "rk4_two_round": 1, "no_check": 1}, out)
    return out, result


def _rk6a(tmp_path, rows):
    d = tmp_path / "rk6a"
    (d / "review_pack" / "works").mkdir(parents=True)
    with open(d / "ranks_11_A.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["key", "author_id", "pct"])
        for key in rows:
            w.writerow([key, key.split("|")[1], "0.95"])
    return d


def test_summary_has_counts_and_ids_only(tmp_path):
    rk6a = _rk6a(tmp_path, ["econ|A1|Y2010", "CONTROL|A1"])
    _write(rk6a / "review_pack" / "works" / "A1.json", {"person_id": "A1", "ids": ["A1"], "Y": 2010, "works": []})
    tg = [{"person_id": "A1", "field": "econ", "Y": None, "ids": ["A1"], "reasons": ["u2_A5008470795"],
           "checks": ["coverage"], "prior_check": "r1_rounds", "flag_wids": ["W1", "W99"],
           "excluded_wids": ["W2"], "min_year": None}]
    out, result = _run(tmp_path, tg, rk6a)
    assert result == "OK" and (out / "RESULT.txt").read_text() == "OK\n"
    dos = json.loads((out / "dossiers" / "A1.json").read_text(encoding="utf-8"))
    assert dos["Y"] == 2010 and dos["ids"] == ["A1", "A2"] and dos["u2_extra_ids"] == ["A2"]
    assert [w["wid"] for w in dos["works"]] == ["W1", "W2", "W3", "W6", "W5"]
    assert dos["works"][0]["title"] == "SECRET TITLE one"            # titles live in the dossier ...
    text = (out / "summary.json").read_text(encoding="utf-8")
    assert "SECRET" not in text and "Secret" not in text            # ... never in the summary
    s = json.loads(text)
    assert set(s) == {"result", "accept_classes", "targets", "by_reason", "by_check", "no_y", "not_in_rk6a_pack",
                      "no_works", "rows"}
    assert s["accept_classes"] == {"r1_rounds": 3, "rk4_two_round": 1, "no_check": 1}
    assert s["rows"] == [{"person_id": "A1", "reasons": ["u2_A5008470795"], "checks": ["coverage"],
                          "prior_check": "r1_rounds", "Y": 2010, "n_ids": 2, "n_u2_extra": 1, "n_works": 5,
                          "n_prior_excluded": 1, "flag_wids_found": 1, "in_rk6a_pack": True}]
    for v in json.loads(text)["rows"][0].values():
        assert not isinstance(v, str) or v in ("A1", "r1_rounds")
    rows = list(csv.DictReader(open(out / "targets.csv", encoding="utf-8")))
    assert rows[0]["person_id"] == "A1" and "SECRET" not in (out / "targets.csv").read_text(encoding="utf-8")


def test_a_target_without_y_fails_the_run_and_only_u2_targets_widen(tmp_path):
    rk6a = _rk6a(tmp_path, ["econ|A1|Y2010", "econ|A1|Y2012"])     # two Y for one person: ambiguous
    tg = [{"person_id": "A1", "field": "econ", "Y": None, "ids": ["A1"], "reasons": ["h10"], "checks": ["identity"],
           "prior_check": "no_check", "flag_wids": [], "excluded_wids": [], "min_year": None},
          {"person_id": "A2", "field": "econ", "Y": 2009, "ids": ["A2"], "reasons": ["h10"],
           "checks": ["identity"], "prior_check": "no_check", "flag_wids": [], "excluded_wids": [], "min_year": None}]
    out, result = _run(tmp_path, tg, rk6a)
    assert result == "DOSSIER_FAIL" and (out / "RESULT.txt").read_text() == "DOSSIER_FAIL\n"
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert s["no_y"] == ["A1"] and s["not_in_rk6a_pack"] == ["A1", "A2"]
    assert not (out / "dossiers" / "A1.json").exists()
    a2 = json.loads((out / "dossiers" / "A2.json").read_text(encoding="utf-8"))
    assert a2["ids"] == ["A2"] and a2["u2_extra_ids"] == []           # h10 is not a U2 target: A1 is not pulled in
    assert [w["wid"] for w in a2["works"]] == ["W6", "W5"]


def test_refuses_off_an_r1_instance(monkeypatch, tmp_path):
    args = []
    for name in ("--repo", "--targets", "--add-list", "--flips", "--paper-checks", "--derived", "--rk6a", "--out"):
        args += [name, str(tmp_path / name.strip("-"))]
    monkeypatch.setenv("SAR_HOST", "mac")
    with pytest.raises(SystemExit, match="R1 AWS instance"):
        dp.main(args)
    monkeypatch.delenv("SAR_HOST")
    with pytest.raises(SystemExit, match="R1 AWS instance"):
        dp.main(args)
    assert not (tmp_path / "out").exists()


def test_the_job_runs_a_copy_with_the_derivation_and_rk6a_pulled():
    job = json.loads((REPO / "config" / "r1" / "jobs" / "dossier.json").read_text(encoding="utf-8"))
    assert job["kind"] == "dossier" and job["instance_type"] == "r6i.8xlarge" and job["sar_host"] == "ec2-r1"
    assert ["pipeline/aws/r1/dossier_pack.py", "/work/dossier_pack.py"] in job["copy_from_tip"]
    assert ["pipeline/aws/r1/rk6b_rank.py", "/work/rk6b_rank.py"] in job["copy_from_tip"]
    assert set(job["required_dests"]) == {"/work/derived/", "/work/rk6a/"}
    assert job["env"] == {"SAR_SSD_ROOT": "/data/openalex_pipeline"}
    step = " ".join(job["steps"])
    assert '"$PY" /work/dossier_pack.py' in step and "j0_dossier_targets.json" in step
    assert "--derived /work/derived" in step and "--rk6a /work/rk6a" in step


def test_require_readable_guards_only_directories_in_dossier_pack():
    """require_readable() fails on a file path ('is not a directory'): dossier-02 died on the u2 person-map
    parquet. Every guarded location in dossier_pack must be a directory; files are joined after the guard."""
    import ast
    src = (REPO / "pipeline" / "aws" / "r1" / "dossier_pack.py").read_text()
    consts = {t.id: n.value.value for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Assign)
              for t in n.targets if isinstance(t, ast.Name) and isinstance(n.value, ast.Constant)
              and isinstance(n.value.value, str)}
    for call in (n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "require_readable"):
        for name in (x.id for x in ast.walk(call.args[0]) if isinstance(x, ast.Name)):
            assert not str(consts.get(name, "")).endswith((".parquet", ".csv", ".json")), \
                f"require_readable() is given the file constant {name}={consts[name]!r}"
