# -*- coding: utf-8 -*-
"""pipeline/aws/r1/restake_r1.py - the rank tables every event writer reads: B0 = October's frozen
tables byte for byte; M = the signed verdicts joined to the gated rank run, after_* from the admitting
pass and the top-5% flag of author decision 4."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import pathlib
import shutil
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import restake_r1 as rs         # noqa: E402

CAL = REPO / "data" / "cal2026-10"
RANK_COLS = ["key", "author_id", "field", "arrival_true", "Y", "stock", "cell", "cell_n", "aage", "pct", "pass_p10", "note"]
FLIP_COLS = ["person_id", "key", "field", "status", "src", "arrival", "pct_A", "in_A", "pct_own", "cell_own", "cell_n_own",
             "aage_own", "stock_own", "in_own", "p05_own", "october_event", "october_p05", "flip", "flip_vs", "pct_C", "in_C"]
MACH = rs.machine(REPO)


@pytest.fixture(autouse=True)
def _on_the_runner(monkeypatch):
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")


def _sha(p) -> str:
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def _w(p, cols, rows):
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


# ------------------------------------------------------------------------------------------------ toy M inputs
def _star(pid, field, y, *, own=("0.95", "40", "8", "True"), c=("0.96", "40", "8", "True"), p05_own="False",
          a_pct="0.97", src="G0", own_missing=False):
    """One rank request: (pct, cell_n, aage, in) for the own and C passes."""
    key = f"{field}|{pid}|Y{y}"
    def rank(pct, cell_n, aage):
        return {"key": key, "author_id": pid, "field": field, "arrival_true": str(y + 1), "Y": str(y), "stock": "500",
                "cell": "2002|6-9", "cell_n": cell_n, "aage": aage, "pct": pct, "pass_p10": "True", "note": ""}
    flip = {"person_id": pid, "key": key, "field": field, "status": "rank", "src": src, "arrival": str(y + 1),
            "pct_A": a_pct, "in_A": "True", "pct_own": "" if own_missing else own[0], "cell_own": "2002|6-9",
            "cell_n_own": own[1], "aage_own": own[2], "stock_own": "500", "in_own": "" if own_missing else own[3],
            "p05_own": p05_own, "october_event": "True", "october_p05": "False", "flip": "none", "flip_vs": "october",
            "pct_C": c[0], "in_C": c[3]}
    return {"A": rank(a_pct, "40", own[2]), "own": None if own_missing else rank(*own[:3]), "C": rank(*c[:3]), "flip": flip}


def _rk(tmp_path, stars, name="rk"):
    d, i = tmp_path / name, 0
    while d.exists():
        i += 1
        d = tmp_path / f"{name}{i}"
    d.mkdir()
    _w(d / "ranks_A.csv", RANK_COLS, [s["A"] for s in stars])
    _w(d / "ranks_own.csv", RANK_COLS, [s["own"] for s in stars if s["own"]])
    _w(d / "ranks_C.csv", RANK_COLS, [s["C"] for s in stars])
    _w(d / "flips.csv", FLIP_COLS, [s["flip"] for s in stars])
    (d / "RESULT.txt").write_text("OK\n", encoding="utf-8")
    return d


def _signed(flips=(), accept=(), persons=None, nine=(), redates=None):
    return {"flips": [dict(person_id=p, name=f"N {p}", field=f, verdict=v, flip="none", pct_own=po) for p, f, v, po in flips],
            "accept": [dict(person_id=p, all_ids=p, name=f"N {p}", field=f, school="anu", dept_key=f"anu_{f}",
                            arrival_year=y, verdict="ACCEPT", pct_own=po) for p, f, y, po in accept],
            "persons": persons or {}, "nine": set(nine), "redates": redates or {}, "add_list_result": "OK"}


def _october(cands=()):
    return {"cands": {a: {"author_id": a, "name": f"N {a}", "field": f, "school": "monash", "arrival_true": str(y),
                          "event_id_old": f"{a}:{y}"} for a, f, y in cands},
            "econ_header": rs.read_header(CAL / rs.B0_ECON), "cm_header": rs.read_header(CAL / "_invalid_run2" / rs.B0_CM)}


def _build(tmp_path, stars, signed, october):
    return rs.build_m(rs.load_rank(_rk(tmp_path, stars)), signed, october, MACH)


# ------------------------------------------------------------------------------------------------ B0
def test_b0_copies_the_october_tables_byte_for_byte(tmp_path):
    out = tmp_path / "b0"
    assert rs.main(["b0", "--cal", str(CAL), "--out", str(out)]) == 0
    srcs = {rs.B0_ECON: CAL / rs.B0_ECON, rs.B0_ECON_ALL: CAL / rs.B0_ECON_ALL, rs.B0_CM: CAL / "_invalid_run2" / rs.B0_CM}
    main_man = dict(reversed(ln.split("  ", 1)) for ln in (CAL / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines())
    run2_man = dict(reversed(ln.split("  ", 1)) for ln in (CAL / "_invalid_run2" / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines())
    for name, src in srcs.items():
        assert (out / name).read_bytes() == src.read_bytes(), name
    assert main_man["data/cal2026-10/restake_econ11_aug_2026-10.csv"] == _sha(out / rs.B0_ECON)
    assert main_man["data/cal2026-10/restake_econ11_aug_all_2026-10.csv"] == _sha(out / rs.B0_ECON_ALL)
    assert run2_man["data/cal2026-10/verdicts_2026-10.csv"] == _sha(out / rs.B0_CM)       # one level up, as recorded
    kind = json.loads((out / "kind.json").read_text(encoding="utf-8"))
    assert kind["schema"] == "sar.r1.rank_tables.v1" and kind["kind"] == "B0"
    assert kind["inputs"] == {n: _sha(s) for n, s in srcs.items()}
    assert (out / "RESULT.txt").read_text(encoding="utf-8").strip() == "OK"


def test_b0_stops_on_a_file_that_differs_from_its_manifest(tmp_path):
    cal = tmp_path / "cal"
    (cal / "_invalid_run2").mkdir(parents=True)
    for rel in (rs.B0_ECON, rs.B0_ECON_ALL, "MANIFEST.sha256", f"_invalid_run2/{rs.B0_CM}", "_invalid_run2/MANIFEST.sha256"):
        shutil.copyfile(CAL / rel, cal / rel)
    assert rs.main(["b0", "--cal", str(cal), "--out", str(tmp_path / "ok")]) == 0
    for rel in (rs.B0_ECON_ALL, f"_invalid_run2/{rs.B0_CM}"):
        bad = tmp_path / ("bad_" + rel.replace("/", "_"))
        shutil.copytree(cal, bad)
        b = bytearray((bad / rel).read_bytes())
        b[-2] ^= 1
        (bad / rel).write_bytes(bytes(b))
        with pytest.raises(SystemExit, match=rel.rsplit("/", 1)[-1]):
            rs.main(["b0", "--cal", str(bad), "--out", str(tmp_path / f"o_{bad.name}")])
        assert not (tmp_path / f"o_{bad.name}" / "kind.json").exists()


# ------------------------------------------------------------------------------------------------ M
def test_m_verdicts_come_from_the_signed_lists_not_the_rank(tmp_path):
    stars = [_star("A1", "econ", 2009, own=("0.97", "40", "8", "True")),                      # ranks in, signed out
             _star("A2", "econ", 2011, own=("0.85", "40", "8", "False"), c=("0.93", "40", "8", "True")),   # label fix
             _star("A5083769806", "math_stats", 2003, own=("0.80", "40", "8", "False"), c=("0.80", "40", "8", "False"))]
    signed = _signed(flips=[("A1", "econ", "DROP", "0.97"), ("A2", "econ", "KEEP", "0.85"),
                            ("A5083769806", "math_stats", "DROP", "0.80")],
                     persons={"A1": {"verdict": "out"}, "A2": {"verdict": "in"}, "A5083769806": {"verdict": "out"}})
    october = _october([("A1", "econ", 2010), ("A2", "econ", 2012), ("A5083769806", "math_stats", 2004)])
    econ, cm, counts, problems = _build(tmp_path, stars, signed, october)
    assert problems == []
    e = {r["author_id"]: r for r in econ}
    assert (e["A1"]["event_keep"], e["A1"]["verdict"], e["A1"]["verdict_source"]) == (False, "DROP", "flips_r1")
    assert (e["A2"]["event_keep"], e["A2"]["rank_pass"], e["A2"]["after_pct"]) == (True, "C", "0.93")
    assert e["A2"]["before_pct"] == "0.97"                                     # before_* = pass A
    drop_star = next(r for r in cm if r["author_id"] == "A5083769806")
    assert drop_star["event_cal2026_10"] is False                                # no October AUTHOR_KEEP in M
    assert counts["econ"]["stars"] == 1 and counts["econ"]["label_fix"] == 1 and counts["econ"]["drop_187"] == 1


def test_m_stops_when_a_star_has_no_rank_row_or_no_passing_pass(tmp_path):
    stars = [_star("A1", "econ", 2009, own=("0.85", "40", "8", "False"), c=("0.85", "40", "8", "False"))]
    october = _october([("A1", "econ", 2010)])
    signed = _signed(flips=[("A1", "econ", "KEEP", "0.85")], persons={"A1": {"verdict": "in"}},
                     accept=[("A7", "chemistry", 2015, "0.99")])
    _e, _c, _n, problems = _build(tmp_path, stars, signed, october)
    assert any(p.startswith("A1:") and "no passing pass" in p for p in problems), problems
    assert any(p.startswith("A7:") and "0 rank rows" in p for p in problems), problems
    two = [_star("A3", "econ", 2009), _star("A3", "econ", 2011)]
    _e, _c, _n, problems = _build(tmp_path, two,
                                  _signed(flips=[("A3", "econ", "KEEP", "0.95")]), _october([("A3", "econ", 2010)]))
    assert any(p.startswith("A3:") and "2 rank rows" in p for p in problems), problems


def test_by_rule_rows_must_agree_with_the_rank(tmp_path):
    stars = [_star("A1", "econ", 2009, own=("0.85", "40", "8", "False"), c=("0.95", "40", "8", "True")),
             _star("A2", "econ", 2009, own=("0.9512", "40", "8", "True"))]
    october = _october([("A1", "econ", 2010), ("A2", "econ", 2010)])
    signed = _signed(flips=[("A1", "econ", "KEEP", "0.85"), ("A2", "econ", "KEEP", "0.9513")])
    _e, _c, _n, problems = _build(tmp_path, stars, signed, october)
    assert any(p.startswith("A1:") and "by rule" in p for p in problems), problems           # KEEP by rule, in_own False
    assert any(p.startswith("A2:") and "pct_own" in p for p in problems), problems           # 0.9513 vs 0.9512
    signed = _signed(flips=[("A1", "econ", "KEEP", "0.85"), ("A2", "econ", "KEEP", "0.95124")],
                     persons={"A1": {"verdict": "in"}})                                          # A1 signed by name
    _e, _c, _n, problems = _build(tmp_path, stars, signed, october)
    assert problems == []


def test_p05_is_decision_4_for_label_fix_stars():
    assert MACH.L.P05 == 0.05 and MACH.rc.pass_p05 is not None and MACH.caliber.MIN_ACADEMIC_AGE == 2
    label = {"in_own": "False", "in_C": "True", "p05_own": "False"}
    def p05(pct, cell_n, aage, arrival=2010):
        return rs.p05_for("C", label, {"pct": pct, "cell_n": cell_n, "aage": aage}, arrival, MACH)
    assert p05("0.95", "30", "5") is True
    assert p05("0.96", "30", "5") is True
    assert p05("0.9499", "30", "5") is False
    assert p05("0.96", "29", "5") is False
    assert p05("0.96", "30", "1") is False
    assert p05("0.96", "30", "5", arrival=2025) is False
    assert p05("", "", "") is False
    own = {"in_own": "True", "in_C": "True"}
    for flag, want in (("True", True), ("False", False), ("", False)):
        assert rs.p05_for("own", dict(own, p05_own=flag), {"pct": "0.99", "cell_n": "100", "aage": "9"}, 2010, MACH) is want
    assert rs.admit_pass({"in_own": "True", "in_C": "False"}) == "own"
    assert rs.admit_pass({"in_own": "False", "in_C": "True"}) == "C"
    assert rs.admit_pass({"in_own": "", "in_C": "True"}) == "C"
    assert rs.admit_pass({"in_own": "False", "in_C": "False"}) is None


def test_p05_flags_follow_the_admitting_pass(tmp_path):
    stars = [_star("A1", "chemistry", 2009, own=("0.85", "40", "8", "False"), c=("0.96", "30", "8", "True")),
             _star("A2", "chemistry", 2009, own=("0.99", "40", "8", "True"), c=("0.50", "40", "8", "False"), p05_own="True")]
    signed = _signed(flips=[("A1", "chemistry", "KEEP", "0.85"), ("A2", "chemistry", "KEEP", "0.99")],
                     persons={"A1": {"verdict": "in"}})
    _e, cm, counts, problems = _build(tmp_path, stars, signed, _october([("A1", "chemistry", 2010), ("A2", "chemistry", 2010)]))
    assert problems == []
    r = {x["author_id"]: x for x in cm}
    assert (r["A1"]["rank_pass"], r["A1"]["event_p05"], r["A1"]["after_pct"]) == ("C", True, "0.96")
    assert (r["A2"]["rank_pass"], r["A2"]["event_p05"], r["A2"]["after_pct"]) == ("own", True, "0.99")
    assert counts["chemistry"]["p05"] == 2 and counts["chemistry"]["label_fix"] == 1 and counts["chemistry"]["own"] == 1


def test_arrival_equals_october_or_a_signed_redate(tmp_path):
    stars = [_star("A5028731684", "econ", 2007), _star("A2", "econ", 2008), _star("A3", "econ", 2014),
             _star("A4", "chemistry", 2012)]
    october = _october([("A5028731684", "econ", 2010), ("A2", "econ", 2010), ("A3", "econ", 2015)])
    persons = {p: {"verdict": "in"} for p in ("A5028731684", "A2", "A3", "A4")}
    signed = _signed(flips=[("A5028731684", "econ", "KEEP", "0.95"), ("A2", "econ", "KEEP", "0.95"), ("A3", "econ", "KEEP", "0.95")],
                     accept=[("A4", "chemistry", 2014, "0.95")], persons=persons,
                     redates={"A5028731684": ("2008", "fixes_1001 redate")})
    econ, cm, _n, problems = _build(tmp_path, stars, signed, october)
    assert problems == [p for p in problems if p.startswith(("A2:", "A4:"))] and len(problems) == 2, problems
    assert any("arrival 2009" in p and "October 2010" in p for p in problems if p.startswith("A2:"))
    assert any("arrival 2013" in p and "add list 2014" in p for p in problems if p.startswith("A4:"))
    m = next(r for r in econ if r["author_id"] == "A5028731684")
    assert (m["arrival_true"], m["arrival_oct"], m["event_id_old"]) == (2008, "2010", "A5028731684:2010")
    a3 = next(r for r in econ if r["author_id"] == "A3")
    assert (a3["arrival_true"], a3["arrival_oct"]) == (2015, "2015")
    # a redate row must be met exactly: the rank still at the October year is a STOP
    signed["redates"]["A3"] = ("2013", "person_overrides arrival_year")
    _e, _c, _n, problems = _build(tmp_path, stars, signed, october)
    assert any(p.startswith("A3:") for p in problems), problems


def test_aage_is_the_same_in_both_passes(tmp_path):
    stars = [_star("A1", "econ", 2009, own=("0.97", "40", "8", "True"), c=("0.97", "40", "9", "True"))]
    _e, _c, _n, problems = _build(tmp_path, stars, _signed(flips=[("A1", "econ", "KEEP", "0.97")]),
                                  _october([("A1", "econ", 2010)]))
    assert any(p.startswith("A1:") and "aage" in p for p in problems), problems


def test_m_tables_keep_the_october_headers_as_a_prefix(tmp_path):
    october = rs.load_october(REPO)
    econ_h = rs.read_header(CAL / "restake_econ11_aug_2026-10.csv")
    cm_h = rs.read_header(CAL / "_invalid_run2" / "verdicts_2026-10.csv")
    assert october["econ_header"] == econ_h and october["cm_header"] == cm_h
    assert rs.econ_columns(october)[:len(econ_h)] == econ_h
    assert rs.cm_columns(october)[:len(cm_h)] == cm_h
    assert rs.econ_columns(october)[len(econ_h):] == ["rank_pass", "verdict", "verdict_source", "arrival_oct", "event_id_old"]
    assert rs.cm_columns(october)[len(cm_h):] == ["rank_pass", "verdict", "verdict_source", "arrival_oct"]
    assert rs.restake_columns(MACH) == ["author_id", "name", "field", "school", "arrival_true", "before_stock", "before_cell",
                                        "before_pct", "before_pass", "after_stock", "after_cell", "after_cell_n", "after_pct",
                                        "after_pass", "note", "aage"]


def test_signed_counts_are_173_97_107():
    signed = rs.load_signed(REPO)
    counts = rs.signed_counts(signed)
    assert {f: (c["keep_187"], c["accept"], c["stars"]) for f, c in counts.items()} == \
        {"econ": (111, 62, 173), "chemistry": (37, 60, 97), "math_stats": (28, 79, 107)}
    assert {f: c["drop_187"] for f, c in counts.items()} == {"econ": 5, "chemistry": 1, "math_stats": 5}
    assert len(signed["flips"]) == 187 and len(signed["accept"]) == 201
    assert "A5028731684" in signed["redates"] and signed["redates"]["A5028731684"][0] == "2008"
    assert {p for p in ("A5076284681", "A5085296117", "A5081851920") if p in signed["redates"]} == \
        {"A5076284681", "A5085296117", "A5081851920"}                         # the three overrides (2024, 2009, 2007)
    assert {"A5034046891", "A5000188305", "A5083576143", "A5000517659"} <= signed["nine"]


def test_m_end_to_end_writes_the_tables_and_counts(tmp_path):
    """A toy repo with the signed files in their real shapes: every file written, counts equal the signed lists."""
    repo = tmp_path / "repo"
    inp = repo / "data" / "cal2026-10r1" / "inputs"
    run2 = repo / "data" / "cal2026-10" / "_invalid_run2"
    inp.mkdir(parents=True)
    run2.mkdir(parents=True)
    (repo / "pipeline").symlink_to(REPO / "pipeline", target_is_directory=True)      # the code; the data is the toy
    shutil.copyfile(CAL / rs.B0_ECON, repo / "data" / "cal2026-10" / rs.B0_ECON)
    shutil.copyfile(CAL / "_invalid_run2" / rs.B0_CM, run2 / rs.B0_CM)
    _w(run2 / "candidates_2026-10.csv", ["author_id", "name", "field", "school", "arrival_true", "event_id_old"],
       [{"author_id": "A1", "name": "N A1", "field": "econ", "school": "anu", "arrival_true": "2010", "event_id_old": "A1:2010"},
        {"author_id": "A2", "name": "N A2", "field": "math_stats", "school": "unsw", "arrival_true": "2006", "event_id_old": "A2:2006"}])
    (inp / "flips_r1.json").write_text(json.dumps({"schema": "sar.r1.flips.v1", "rows": [
        {"person_id": "A1", "name": "N A1", "field": "econ", "verdict": "KEEP", "flip": "none", "pct_own": "0.97", "decided": "x"},
        {"person_id": "A2", "name": "N A2", "field": "math_stats", "verdict": "DROP", "flip": "in->out", "pct_own": "0.5", "decided": "x"}]}))
    (inp / "add_list_r1.json").write_text(json.dumps({"schema": "sar.r1.add_list.v1", "rows": [
        {"person_id": "A3", "all_ids": "A3|A9", "name": "N A3", "field": "chemistry", "school": "anu", "dept_key": "anu_chem",
         "arrival_year": 2015, "verdict": "ACCEPT", "basis": "own-discipline top 10% (R-Rank)", "decided": "x", "pct_own": "0.96", "sources": "G3"},
        {"person_id": "A4", "all_ids": "A4", "name": "N A4", "field": "econ", "school": "anu", "dept_key": "anu_econ",
         "arrival_year": 2015, "verdict": "REJECT", "basis": "fails (by rule)", "decided": "x", "pct_own": "0.5", "sources": "G3"}]}))
    (inp / "add_list_r1_summary.json").write_text(json.dumps({"result": "ROSTER_GAP"}))
    (inp / "p2_decisions.json").write_text(json.dumps({"schema": "sar.r1.p2_decisions.v1", "decided": "x", "persons": {}}))
    (inp / "author_rulings_p1.json").write_text(json.dumps({"schema": "sar.r1.author_rulings_p1.v1", "rules_for_the_nine": {}}))
    (inp / "fixes_1001.csv").write_text("author_id,fix,value,decided,evidence\n")
    (inp / "person_overrides.csv").write_text("author_id,action,value,reason,source\n")
    stars = [_star("A1", "econ", 2009, own=("0.97", "40", "8", "True"), p05_own="True"),
             _star("A2", "math_stats", 2005, own=("0.5", "40", "8", "False"), c=("0.5", "40", "8", "False")),
             _star("A3", "chemistry", 2014, own=("0.96", "40", "8", "True"), src="G3"),
             _star("A4", "econ", 2014, own=("0.5", "40", "8", "False"), c=("0.5", "40", "8", "False"), src="G3")]
    rk = _rk(tmp_path, stars)
    out = tmp_path / "out"
    assert rs.main(["m", "--rk", str(rk), "--repo", str(repo), "--out", str(out)]) == 0
    assert (out / "RESULT.txt").read_text(encoding="utf-8").strip() == "OK"
    kind = json.loads((out / "kind.json").read_text(encoding="utf-8"))
    assert kind["kind"] == "M" and kind["inputs"]["rank:flips.csv"] == _sha(rk / "flips.csv")
    with open(out / rs.M_ECON, encoding="utf-8", newline="") as f:
        econ = list(csv.DictReader(f))
    assert [r["author_id"] for r in econ] == ["A1"]                         # REJECT A4 is not written
    with open(out / rs.M_CM, encoding="utf-8", newline="") as f:
        cm = {r["author_id"]: r for r in csv.DictReader(f)}
    assert (cm["A2"]["event_cal2026_10"], cm["A2"]["reason_if_out"]) == ("False", "signed_drop")
    assert (cm["A3"]["event_cal2026_10"], cm["A3"]["verdict"], cm["A3"]["arrival_oct"]) == ("True", "ACCEPT", "")
    with open(out / rs.M_RESTAKE, encoding="utf-8", newline="") as f:
        assert sorted(r["author_id"] for r in csv.DictReader(f)) == ["A1", "A2", "A3"]
    with open(out / rs.M_P05, encoding="utf-8", newline="") as f:
        p05 = {r["star_id"]: r for r in csv.DictReader(f)}
    assert set(p05) == {"A1", "A3"} and (p05["A1"]["p05"], p05["A1"]["basis"]) == ("True", "own")
    counts = json.loads((out / "counts.json").read_text(encoding="utf-8"))
    assert counts["econ"]["stars"] == 1 and counts["chemistry"]["accept"] == 1 and counts["math_stats"]["drop_187"] == 1
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["result"] == "OK" and summary["add_list_result"] == "ROSTER_GAP"
    assert "N A1" not in (out / "summary.json").read_text(encoding="utf-8")   # counts and ids only
    # a STOP writes no table and exits 1
    (inp / "fixes_1001.csv").write_text("author_id,fix,value,decided,evidence\nA1,redate,2007,x,y\n")
    out2 = tmp_path / "out2"
    assert rs.main(["m", "--rk", str(rk), "--repo", str(repo), "--out", str(out2)]) == 1
    assert (out2 / "RESULT.txt").read_text(encoding="utf-8").strip() == "STOP"
    assert not (out2 / rs.M_ECON).exists()
    assert collections.Counter(p.split(":")[0] for p in json.loads((out2 / "summary.json").read_text())["problems"]) == {"A1": 1}


def test_refuses_off_aws(tmp_path, monkeypatch):
    monkeypatch.setenv("SAR_HOST", "mac")
    with pytest.raises(SystemExit, match="R1 AWS instance"):
        rs.main(["b0", "--cal", str(CAL), "--out", str(tmp_path / "o")])
