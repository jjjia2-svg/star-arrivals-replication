# -*- coding: utf-8 -*-
"""pipeline/aws/r1/events_r1.py (R1 F10 + N16-S14) - the event tables and top-5% subsets, October basenames.

B0 = October's six tables and decision record, rebuilt through verdict_source and refused unless byte-equal to
data/cal2026-10 (proved on the real repo files). M = October's lines minus the DROP stars' events, re-dated in
place (cols 0 and 3 only), A5110738002's 08-28 line restored, the signed add-list ACCEPT rows appended. The M tests
use the real signed lists and the real October / 08-28 tables with toy rank tables (verdict_source M layout), so
everything but the rank numbers is the real input. Repo data only; nothing here reads the data disk."""
from __future__ import annotations

import csv
import io
import json
import pathlib
import shutil
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
R1 = REPO / "pipeline" / "aws" / "r1"
sys.path.insert(0, str(R1))
import events_r1 as ev          # noqa: E402

CAL = REPO / "data" / "cal2026-10"
RV = REPO / "data" / "raw_verified"
INP = REPO / "data" / "cal2026-10r1" / "inputs"
FIELDS = ("econ", "chemistry", "math_stats")
ID_COL = {"econ": 1, "chemistry": 2, "math_stats": 2}
SCHOOL_COL = {"econ": 2, "chemistry": 1, "math_stats": 1}
ARR_COL = {"econ": 3, "chemistry": 4, "math_stats": 4}
ECON_EXTRA = ["rank_pass", "verdict", "verdict_source", "arrival_oct", "event_id_old"]
CM_EXTRA = ["rank_pass", "verdict", "verdict_source", "arrival_oct"]
SIGNED = "signed_add_list_r1_2026-10-12"
RESTORED_STAR = "A5110738002"
REDATED_STAR = "A5028731684"
S14_STAR = "A5071656006"
P05_OUT_STAR = "A5087235620"                                   # fixes_1001 p05_out
DROPPED_EVENTS = {"econ": {"A5082663721:2010", "A5086835452:2017", "A5027077000:2017"},
                  "chemistry": {"A5109260299:monash"},
                  "math_stats": {"A5035138469:monash", "A5068065835:monash", "A5083478373:melbourne",
                                 "A5015471697:unsw", "A5017222669:uq"}}
ABSENT_IN_OCTOBER = {"A5102739182", "A5041849660"}           # DROP stars October had already removed
RANK_ADDS = {"A5102947614": ["A5038398146"], "A5008337457": ["A5109981785"], "A5102954096": ["A5039408031"]}


def _header(p: pathlib.Path) -> list[str]:
    with open(p, newline="", encoding="utf-8") as f:
        return next(csv.reader(f))


ECON_HDR = _header(CAL / "restake_econ11_aug_2026-10.csv")
CM_HDR = _header(CAL / "_invalid_run2" / "verdicts_2026-10.csv")


def _lines(p: pathlib.Path) -> list[str]:
    return [ln for ln in p.read_bytes().decode("utf-8").split("\n") if ln]


def _parse(ln: str) -> list[str]:
    return next(csv.reader([ln]))


def _key(field: str, ln: str) -> str:
    f = _parse(ln)
    return f[0] if field == "econ" else f"{f[2]}:{f[1]}"


def _star(field: str, ln: str) -> str:
    return _parse(ln)[ID_COL[field]]


def _csv_rows(p: pathlib.Path) -> list[dict]:
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _corrections() -> dict:
    return {r["old_id"]: r["new_id"] for r in _csv_rows(CAL / "star_id_corrections_2026-10.csv")}


def _signed():
    flips = json.loads((INP / "flips_r1.json").read_text(encoding="utf-8"))["rows"]
    adds = json.loads((INP / "add_list_r1.json").read_text(encoding="utf-8"))["rows"]
    return flips, adds


def _places() -> dict:
    """(field, star) -> (school, arrival) from the 08-28 event tables with October's id corrections."""
    corr, out = _corrections(), {}
    for f in FIELDS:
        for row in list(csv.reader(io.StringIO((RV / f"events_{f}_cal2026-08-28.csv").read_text(encoding="utf-8"))))[1:]:
            sid = corr.get(row[ID_COL[f]], row[ID_COL[f]])
            out[(f, sid)] = (row[SCHOOL_COL[f]], int(row[ARR_COL[f]]))
    return out


def _redates(fixes_text: str, overrides_text: str) -> dict:
    out = {r["author_id"]: int(r["value"]) for r in csv.DictReader(io.StringIO(fixes_text)) if r["fix"] == "redate"}
    out.update({r["author_id"]: int(r["value"]) for r in csv.DictReader(io.StringIO(overrides_text))
                if r["action"] == "arrival_year"})
    return out


def _write_csv(p: pathlib.Path, header: list[str], rows: list[dict]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: "" for c in header} | r)
    p.write_text(buf.getvalue(), encoding="utf-8")


def _m_tables(d: pathlib.Path, *, flips, adds, redates, p05=lambda f, a: False, places=None) -> pathlib.Path:
    """Toy M rank tables in verdict_source's layout: one row per signed star, verdicts and arrivals as the signed
    lists and redate rows give them, rank numbers made up."""
    places = places or _places()
    d.mkdir(parents=True)
    econ, cm = [], []
    for r in flips:
        f, a, v = r["field"], r["person_id"], r["verdict"]
        school, arr_oct = places[(f, a)]
        arr, keep = redates.get(a, arr_oct), v != "DROP"
        old = f"{a}:{arr_oct}" if f == "econ" else f"{a}:{school}"
        row = {"author_id": a, "name": r["name"], "school": school, "arrival_true": str(arr), "after_pct": "0.97",
               "after_cell_n": "100", "aage": "6", "rank_pass": "own" if keep else "", "verdict": v,
               "verdict_source": "flips_r1", "arrival_oct": str(arr_oct), "event_id_old": old}
        if f == "econ":
            econ.append(row | {"after_pass_p05": str(bool(p05(f, a)) and keep), "event_keep": str(keep)})
        else:
            cm.append(row | {"field": f, "event_cal2026_10": str(keep), "event_p05": str(bool(p05(f, a)) and keep)})
    for r in adds:
        if r["verdict"] != "ACCEPT":
            continue
        f, a = r["field"], r["person_id"]
        row = {"author_id": a, "name": r["name"], "school": r["school"], "arrival_true": str(r["arrival_year"]),
               "after_pct": "0.98", "after_cell_n": "100", "aage": "8", "rank_pass": "own", "verdict": "ACCEPT",
               "verdict_source": "add_list_r1", "arrival_oct": "", "event_id_old": ""}
        if f == "econ":
            econ.append(row | {"after_pass_p05": str(bool(p05(f, a))), "event_keep": "True"})
        else:
            cm.append(row | {"field": f, "event_cal2026_10": "True", "event_p05": str(bool(p05(f, a)))})
    _write_csv(d / "restake_econ_r1.csv", ECON_HDR + ECON_EXTRA, sorted(econ, key=lambda r: r["author_id"]))
    _write_csv(d / "verdicts_chemmath_r1.csv", CM_HDR + CM_EXTRA, sorted(cm, key=lambda r: (r["field"], r["author_id"])))
    (d / "kind.json").write_text(json.dumps({"schema": "sar.r1.rank_tables.v1", "kind": "M", "inputs": {}}),
                                 encoding="utf-8")
    return d


def _setup_m(tmp: pathlib.Path, *, summary_result="OK", summary_path=None, flips=None, adds=None, table_flips=None,
             table_adds=None, fixes_text=None, overrides_text=None, checks=None, rank_adds=None,
             p05=lambda f, a: False, places=None, table_redates=None, name="run") -> tuple[list[str], pathlib.Path]:
    """argv for an M run in tmp/name, and its out dir. Defaults = the real signed inputs."""
    base = tmp / name
    base.mkdir()
    real_flips, real_adds = _signed()
    flips_rows = real_flips if flips is None else flips
    add_rows = real_adds if adds is None else adds
    fixes_text = (INP / "fixes_1001.csv").read_text(encoding="utf-8") if fixes_text is None else fixes_text
    overrides_text = (INP / "person_overrides.csv").read_text(encoding="utf-8") if overrides_text is None else overrides_text
    (base / "flips_r1.json").write_text(json.dumps({"schema": "sar.r1.flips.v1", "rows": flips_rows}, ensure_ascii=False),
                                        encoding="utf-8")
    (base / "add_list_r1.json").write_text(json.dumps({"schema": "sar.r1.add_list.v1", "rows": add_rows},
                                                      ensure_ascii=False), encoding="utf-8")
    (base / "fixes_1001.csv").write_text(fixes_text, encoding="utf-8")
    (base / "person_overrides.csv").write_text(overrides_text, encoding="utf-8")
    if summary_path is None:
        s = json.loads((INP / "add_list_r1_summary.json").read_text(encoding="utf-8"))
        s["result"] = summary_result
        summary_path = base / "add_list_r1_summary.json"
        summary_path.write_text(json.dumps(s), encoding="utf-8")
    if checks is None:
        checks_dir = INP / "arrival_checks"
    else:
        checks_dir = base / "arrival_checks"
        checks_dir.mkdir()
        for c in checks:
            (checks_dir / f"{c['person_id']}.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    calls = base / "calls"
    calls.mkdir()
    (calls / "rank_adds.json").write_text(json.dumps(RANK_ADDS if rank_adds is None else rank_adds), encoding="utf-8")
    redates = _redates(fixes_text, overrides_text) if table_redates is None else table_redates
    rt = _m_tables(base / "rank_tables", flips=flips_rows if table_flips is None else table_flips,
                   adds=add_rows if table_adds is None else table_adds, redates=redates, p05=p05, places=places)
    out = base / "out"
    argv = ["--mode", "m", "--repo", str(REPO), "--rank-tables", str(rt), "--raw-0828", str(RV),
            "--corrections", str(CAL / "star_id_corrections_2026-10.csv"), "--october", str(CAL), "--out", str(out),
            "--flips", str(base / "flips_r1.json"), "--add-list", str(base / "add_list_r1.json"),
            "--addlist-summary", str(summary_path), "--fixes", str(base / "fixes_1001.csv"),
            "--overrides", str(base / "person_overrides.csv"), "--calls", str(calls), "--arrival-checks", str(checks_dir)]
    return argv, out


@pytest.fixture
def on_aws(monkeypatch):
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")


def _no_s14_row(text: str) -> str:
    return "".join(ln for ln in text.splitlines(keepends=True) if not ln.startswith(f"{S14_STAR},arrival_year,"))


def _check(verified, claimed=2000, **kw) -> dict:
    return {"schema": "sar.r1.arrival_check.v1", "person_id": S14_STAR, "event_id": f"{S14_STAR}:{claimed}",
            "claimed_year": claimed, "verified_year": verified, "rule": "first post that counts",
            "evidence": [{"url": "https://example.org/x", "quote": "toy"}], "checker": "toy drafter",
            "second_checker": "toy checker", "agree": True, "decided": "toy ruling"} | kw


# --------------------------------------------------------------------------------------------- B0 = October

def test_b0_is_byte_equal_to_october(tmp_path, on_aws):
    """The switch-off proof on the real repo files: October's rank inputs + verdict_source B0 rebuild the six
    October tables and events_decision_2026-10.json byte for byte, under October's basenames."""
    rt = tmp_path / "b0"
    rt.mkdir()
    for name, src in (("restake_econ11_aug_2026-10.csv", CAL / "restake_econ11_aug_2026-10.csv"),
                      ("restake_econ11_aug_all_2026-10.csv", CAL / "restake_econ11_aug_all_2026-10.csv"),
                      ("verdicts_2026-10.csv", CAL / "_invalid_run2" / "verdicts_2026-10.csv")):
        shutil.copyfile(src, rt / name)
    (rt / "kind.json").write_text(json.dumps({"schema": "sar.r1.rank_tables.v1", "kind": "B0", "inputs": {}}),
                                  encoding="utf-8")
    out = tmp_path / "out"
    argv = ["--mode", "b0", "--repo", str(REPO), "--rank-tables", str(rt), "--raw-0828", str(RV),
            "--corrections", str(CAL / "star_id_corrections_2026-10.csv"), "--october", str(CAL), "--out", str(out)]
    assert ev.main(argv) == 0
    names = [f"events_{f}_cal2026-10{s}.csv" for f in FIELDS for s in ("", "_p05")] + ["events_decision_2026-10.json"]
    for n in names:
        assert (out / n).read_bytes() == (CAL / n).read_bytes(), n
    assert json.loads((out / "summary.json").read_text(encoding="utf-8"))["result"] == "OK"
    with pytest.raises(SystemExit):                                       # b0 takes no M input
        ev.main(argv + ["--fixes", str(INP / "fixes_1001.csv")])


def test_refuses_off_aws(monkeypatch, tmp_path):
    monkeypatch.delenv("SAR_HOST", raising=False)
    with pytest.raises(SystemExit, match="SAR_HOST"):
        ev.main(["--mode", "b0", "--repo", str(REPO), "--rank-tables", str(tmp_path), "--raw-0828", str(RV),
                 "--corrections", str(CAL / "star_id_corrections_2026-10.csv"), "--october", str(CAL),
                 "--out", str(tmp_path / "o")])


# --------------------------------------------------------------------------------------------- M

def test_m_counts_on_the_signed_lists(tmp_path, on_aws):
    argv, out = _setup_m(tmp_path)
    assert ev.main(argv) == 0
    counts = json.loads((out / "counts.json").read_text(encoding="utf-8"))
    assert counts["schema"] == "sar.r1.counts.v1" and counts["config"] == "M"
    assert counts["events"] == {"econ": 173, "chemistry": 97, "math_stats": 107}
    assert counts["events_total"] == 377 and counts["candidates"] == 187
    assert counts["events_p05"] == {f: 0 for f in FIELDS}                 # toy rank: no p05
    decision =json.loads((out / "events_decision_2026-10.json").read_text(encoding="utf-8"))
    redated = {r["old_event"] for r in decision["redated"]}
    assert f"{REDATED_STAR}:2010" in redated
    for f in FIELDS:
        oct_lines, new = _lines(CAL / f"events_{f}_cal2026-10.csv"), _lines(out / f"events_{f}_cal2026-10.csv")
        assert new[0] == oct_lines[0]
        kept = [ln for ln in oct_lines[1:] if _key(f, ln) not in DROPPED_EVENTS[f]]
        for o, n in zip(kept, new[1:1 + len(kept)]):
            if _key(f, o) in redated:
                assert _star(f, o) == _star(f, n)
            else:
                assert o == n, _key(f, o)                                     # byte-identical, October order
        tail = new[1 + len(kept):]
        if f == "econ":
            restored = [ln for ln in _lines(RV / "events_econ_cal2026-08-28.csv")[1:] if _star(f, ln) == RESTORED_STAR]
            assert tail[0] == restored[0]                                      # restored byte for byte, first
            tail = tail[1:]
        _, adds = _signed()
        assert [_star(f, ln) for ln in tail] == [r["person_id"] for r in adds
                                                 if r["verdict"] == "ACCEPT" and r["field"] == f]
        assert _lines(out / f"events_{f}_cal2026-10_p05.csv") == [new[0]]
    assert [r["star"] for r in decision["restored"]] == [RESTORED_STAR]
    assert len(decision["added"]) == 201
    with open(out / "star_aliases_r1.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert [(r["person_id"], r["alias_id"]) for r in rows] == sorted((k, a) for k, v in RANK_ADDS.items() for a in v)
    assert all(r["source"] for r in rows)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["result"] == "OK" and (out / "RESULT.txt").read_text().strip() == "OK"


def test_m_refuses_an_addlist_summary_that_is_not_ok(tmp_path, on_aws):
    committed = INP / "add_list_r1_summary.json"
    s = json.loads(committed.read_text(encoding="utf-8"))
    path = committed
    if s.get("result") == "OK":                                           # once the P3a rosters pass, keep the probe
        s["result"] = "ROSTER_GAP"
        path = tmp_path / "gap_summary.json"
        path.write_text(json.dumps(s), encoding="utf-8")
    argv, out = _setup_m(tmp_path, summary_path=path)
    with pytest.raises(SystemExit, match="STOP.*ROSTER_GAP"):
        ev.main(argv)
    assert not (out / "events_econ_cal2026-10.csv").exists()
    assert json.loads((out / "summary.json").read_text(encoding="utf-8"))["result"] == "STOP"


def test_redate_rewrites_only_event_id_and_arrival(tmp_path, on_aws):
    argv, out = _setup_m(tmp_path)
    assert ev.main(argv) == 0
    oct_line = [ln for ln in _lines(CAL / "events_econ_cal2026-10.csv") if _star("econ", ln) == REDATED_STAR][0]
    new_line = [ln for ln in _lines(out / "events_econ_cal2026-10.csv") if _star("econ", ln) == REDATED_STAR][0]
    o, n = _parse(oct_line), _parse(new_line)
    assert (o[0], o[3]) == (f"{REDATED_STAR}:2010", "2010") and (n[0], n[3]) == (f"{REDATED_STAR}:2008", "2008")
    assert [x for i, x in enumerate(o) if i not in (0, 3)] == [x for i, x in enumerate(n) if i not in (0, 3)]
    assert oct_line.split(",", 4)[4] == new_line.split(",", 4)[4]          # every later byte unchanged

    # a second redate row (the S14 path) changes only its own line
    other = "A5080057811"                                                 # October econ event :2006, KEEP
    text = (INP / "person_overrides.csv").read_text(encoding="utf-8") + f"{other},arrival_year,2007,toy,TEST\n"
    argv2, out2 = _setup_m(tmp_path, overrides_text=text, name="run2")
    assert ev.main(argv2) == 0
    a, b = _lines(out / "events_econ_cal2026-10.csv"), _lines(out2 / "events_econ_cal2026-10.csv")
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    assert len(a) == len(b) and len(diff) == 1
    assert _parse(diff[0][1])[0] == f"{other}:2007" and _parse(diff[0][1])[3] == "2007"
    for f in ("chemistry", "math_stats"):
        assert (out / f"events_{f}_cal2026-10.csv").read_bytes() == (out2 / f"events_{f}_cal2026-10.csv").read_bytes()


def test_each_redate_row_hits_exactly_one_line():
    hdr = "event_id,star_id,school,arrival_year,arrival_source,arrival_evidence,reason"
    tables = {"econ": [hdr, "X:2005,X,uq,2005,official_roster,strong,a", "X:2009,X,uwa,2009,official_roster,strong,b",
                       "Y:2004,Y,anu,2004,official_roster,strong,\"c, d\""],
              "chemistry": ["field,school,author_id,display_name,arrival_corrected,evidence_grade",
                            "chemistry,uwa,C,\"Doe, J\",2010,strong"],
              "math_stats": ["field,school,author_id,display_name,arrival_corrected,evidence_grade"]}
    with pytest.raises(ev.Stop, match="X"):
        ev.apply_redates(tables, [{"star": "X", "year": 2006, "source": "toy"}])      # two hits
    with pytest.raises(ev.Stop, match="Z"):
        ev.apply_redates(tables, [{"star": "Z", "year": 2006, "source": "toy"}])      # no hit
    new, recs = ev.apply_redates(tables, [{"star": "Y", "year": 2003, "source": "toy"},
                                          {"star": "C", "year": 2011, "source": "toy"}])
    assert new["econ"][3] == "Y:2003,Y,anu,2003,official_roster,strong,\"c, d\""
    assert new["chemistry"][1] == "chemistry,uwa,C,\"Doe, J\",2011,strong"
    assert new["econ"][:3] == tables["econ"][:3]
    assert [(r["old_event"], r["new_event"]) for r in recs] == [("Y:2004", "Y:2003"), ("C:uwa", "C:uwa")]
    assert ev.redates_from_inputs([{"author_id": "Y", "fix": "redate", "value": "2003"}], [], tables) == {"Y:2004": "Y:2003"}


def test_dropped_events_are_exactly_the_drop_stars(tmp_path, on_aws):
    argv, out = _setup_m(tmp_path)
    assert ev.main(argv) == 0
    decision = json.loads((out / "events_decision_2026-10.json").read_text(encoding="utf-8"))
    got = {f: {r["event"] for r in decision["dropped"] if r["field"] == f} for f in FIELDS}
    assert got == DROPPED_EVENTS
    assert {r["star"] for r in decision["absent_in_october"]} == ABSENT_IN_OCTOBER

    # a DROP star with no October event that October did not drop either -> STOP
    flips, adds = _signed()
    fake = {"person_id": "A5999999999", "name": "Toy Drop", "field": "econ", "verdict": "DROP", "flip": "in->out",
            "pct_own": "0.5", "decided": "toy"}
    places = _places() | {("econ", "A5999999999"): ("uq", 2012)}
    argv2, _ = _setup_m(tmp_path, flips=flips + [fake], places=places, name="run2")
    with pytest.raises(SystemExit, match="STOP.*A5999999999"):
        ev.main(argv2)


def test_every_event_star_has_a_signed_verdict(tmp_path, on_aws):
    flips, adds = _signed()
    gone = next(r for r in adds if r["verdict"] == "ACCEPT" and r["field"] == "econ")
    argv, _ = _setup_m(tmp_path, adds=[r for r in adds if r is not gone], table_adds=adds, name="a")
    with pytest.raises(SystemExit, match=f"STOP.*{gone['person_id']}"):  # a star in no signed list
        ev.main(argv)
    acc = next(r for r in adds if r["verdict"] == "ACCEPT" and r["field"] == "math_stats")
    both = {"person_id": acc["person_id"], "name": acc["name"], "field": "math_stats", "verdict": "KEEP",
            "flip": "none", "pct_own": "0.99", "decided": "toy"}
    places = _places() | {("math_stats", acc["person_id"]): (acc["school"], acc["arrival_year"])}
    argv, _ = _setup_m(tmp_path, flips=flips + [both], table_flips=flips, places=places, name="b")
    with pytest.raises(SystemExit, match=f"STOP.*{acc['person_id']}"):   # in both lists
        ev.main(argv)
    undecided = [dict(r) for r in flips]
    undecided[5]["decided"] = "  "
    argv, _ = _setup_m(tmp_path, flips=undecided, name="c")
    with pytest.raises(SystemExit, match=f"STOP.*{undecided[5]['person_id']}"):
        ev.main(argv)


def test_new_rows_shape(tmp_path, on_aws):
    argv, out = _setup_m(tmp_path)
    assert ev.main(argv) == 0
    _, adds = _signed()
    accept = {r["person_id"]: r for r in adds if r["verdict"] == "ACCEPT"}
    hdr = _header(CAL / "events_econ_cal2026-10.csv")
    econ = {r["star_id"]: r for r in _csv_rows(out / "events_econ_cal2026-10.csv")}
    named = {"event_id", "star_id", "school", "arrival_year", "arrival_source", "arrival_evidence", "reason",
             "evidence_source"}
    n_comma = 0
    for pid, a in accept.items():
        if a["field"] != "econ":
            continue
        r = econ[pid]
        assert r["event_id"] == f"{pid}:{a['arrival_year']}" and r["arrival_year"] == str(a["arrival_year"])
        assert r["school"] == a["dept_key"].split("_", 1)[0] == a["school"]
        assert (r["arrival_source"], r["arrival_evidence"]) == (SIGNED, "strong")
        assert r["reason"] == "R1 add list ACCEPT: " + a["basis"][:200]
        assert r["evidence_source"] == "data/cal2026-10r1/inputs/add_list_r1.json"
        assert all(r[c] == "" for c in hdr if c not in named)                 # 08-28 statistic columns empty
        n_comma += "," in r["reason"]
    assert n_comma > 0                                                        # csv quoting exercised
    raw = [ln for ln in _lines(out / "events_econ_cal2026-10.csv") if ln.startswith("A5008337457:")]
    assert len(raw) == 1 and '"R1 add list ACCEPT: ' in raw[0]
    for f in ("chemistry", "math_stats"):
        rows = {r["author_id"]: r for r in _csv_rows(out / f"events_{f}_cal2026-10.csv")}
        for pid, a in accept.items():
            if a["field"] != f:
                continue
            r = rows[pid]
            assert (r["field"], r["school"], r["display_name"], r["arrival_corrected"]) == \
                (f, a["dept_key"].split("_", 1)[0], a["name"], str(a["arrival_year"]))
            assert (r["evidence_grade"], r["evidence_url"], r["signature"]) == ("strong", "", SIGNED)


def test_new_rows_end_like_their_table(tmp_path, on_aws):
    """j1a-17: October's tables are CRLF; new rows were written LF, so a table mixed line ends and the CSV
    sniffer of prodlib (and of the econ union) could not read it. Every line events_r1 writes (a new or a
    rewritten row) ends like its table's header; October's own lines keep their bytes."""
    argv, out = _setup_m(tmp_path)
    assert ev.main(argv) == 0
    for f in FIELDS:
        old = set(_lines(CAL / f"events_{f}_cal2026-10.csv"))
        lines = _lines(out / f"events_{f}_cal2026-10.csv")
        eol = lines[0].endswith("\r")
        written = [ln for ln in lines if ln not in old]
        assert written, f
        assert all(ln.endswith("\r") == eol for ln in written), f


def test_p05_follows_the_source(tmp_path, on_aws):
    pick = lambda f, a: a[-1] in "2468"                                      # noqa: E731  (P05_OUT_STAR ends in 0)
    argv, out = _setup_m(tmp_path, p05=pick)
    assert ev.main(argv) == 0
    counts = json.loads((out / "counts.json").read_text(encoding="utf-8"))
    for f in FIELDS:
        main = _lines(out / f"events_{f}_cal2026-10.csv")
        p05 = _lines(out / f"events_{f}_cal2026-10_p05.csv")
        assert p05 == [main[0]] + [ln for ln in main[1:] if pick(f, _star(f, ln))]
        assert counts["events_p05"][f] == len(p05) - 1 > 0


def test_fixes_asserts(tmp_path, on_aws):
    argv, _ = _setup_m(tmp_path, p05=lambda f, a: a == P05_OUT_STAR, name="a")
    with pytest.raises(SystemExit, match=f"STOP.*{P05_OUT_STAR}"):            # fixes_1001 p05_out yet p05 True
        ev.main(argv)
    fixes = (INP / "fixes_1001.csv").read_text(encoding="utf-8")
    keep_star = "A5080057811"
    argv, _ = _setup_m(tmp_path, fixes_text=fixes + f"{keep_star},drop,,toy,toy\n", name="b")
    with pytest.raises(SystemExit, match=f"STOP.*{keep_star}"):           # a 'drop' that is not a flips DROP
        ev.main(argv)
    argv, _ = _setup_m(tmp_path, fixes_text=fixes + "A5999999998,below_cut_1001,,toy,toy\n", name="c")
    with pytest.raises(SystemExit, match="STOP.*A5999999998"):            # below_cut id without a flips verdict
        ev.main(argv)
    argv, _ = _setup_m(tmp_path, fixes_text=fixes + f"{keep_star},teleport,,toy,toy\n", name="d")
    with pytest.raises(SystemExit, match="STOP.*teleport"):
        ev.main(argv)


# --------------------------------------------------------------------------------------------- S14

def test_s14_keeps_2000_when_verified(tmp_path, on_aws):
    text = _no_s14_row((INP / "person_overrides.csv").read_text(encoding="utf-8"))
    argv, out = _setup_m(tmp_path, overrides_text=text, checks=[_check(2000)])
    assert ev.main(argv) == 0
    oct_line = [ln for ln in _lines(CAL / "events_econ_cal2026-10.csv") if _star("econ", ln) == S14_STAR]
    new_line = [ln for ln in _lines(out / "events_econ_cal2026-10.csv") if _star("econ", ln) == S14_STAR]
    assert new_line == oct_line and _parse(oct_line[0])[0] == f"{S14_STAR}:2000"
    decision = json.loads((out / "events_decision_2026-10.json").read_text(encoding="utf-8"))
    assert S14_STAR not in {r["star"] for r in decision["redated"]}
    # a verified 2000 with a redate row anyway is a contradiction
    argv, _ = _setup_m(tmp_path, checks=[_check(2000)], name="b")
    with pytest.raises(SystemExit, match=f"STOP.*{S14_STAR}"):
        ev.main(argv)


def test_s14_redate_row_changes_only_that_event(tmp_path, on_aws):
    text = (INP / "person_overrides.csv").read_text(encoding="utf-8")
    base = _no_s14_row(text)
    argv0, out0 = _setup_m(tmp_path, overrides_text=base, checks=[_check(2000)], name="keep")
    assert ev.main(argv0) == 0
    with_row = base + f"{S14_STAR},arrival_year,2001,toy S14,S14\n"
    argv1, out1 = _setup_m(tmp_path, overrides_text=with_row, checks=[_check(2001)], name="redate")
    assert ev.main(argv1) == 0
    for suffix in ("", "_p05"):
        a = _lines(out0 / f"events_econ_cal2026-10{suffix}.csv")
        b = _lines(out1 / f"events_econ_cal2026-10{suffix}.csv")
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        assert len(a) == len(b)
        if suffix == "_p05" and not any(_star("econ", x) == S14_STAR for x in a):
            assert diff == []
            continue
        assert len(diff) == 1
        o, n = _parse(diff[0][0]), _parse(diff[0][1])
        assert (o[0], o[3], n[0], n[3]) == (f"{S14_STAR}:2000", "2000", f"{S14_STAR}:2001", "2001")
        assert diff[0][0].split(",", 4)[4] == diff[0][1].split(",", 4)[4]
    decision = json.loads((out1 / "events_decision_2026-10.json").read_text(encoding="utf-8"))
    assert {(r["old_event"], r["new_event"]) for r in decision["redated"]} >= {(f"{S14_STAR}:2000",
                                                                                f"{S14_STAR}:2001")}
    # a check that says 2001 with no override row: STOP (the redate goes through person_overrides only)
    argv2, _ = _setup_m(tmp_path, overrides_text=base, checks=[_check(2001)], table_redates=None, name="norow")
    with pytest.raises(SystemExit, match=f"STOP.*{S14_STAR}"):
        ev.main(argv2)
    # the committed check file and override row agree (verified 2001, inside 1999-2024)
    real = json.loads((INP / "arrival_checks" / f"{S14_STAR}.json").read_text(encoding="utf-8"))
    assert real["schema"] == "sar.r1.arrival_check.v1" and real["agree"] is True and real["decided"]
    assert (real["event_id"], real["claimed_year"]) == (f"{S14_STAR}:2000", 2000)
    rows = [r for r in csv.DictReader(io.StringIO(text)) if r["author_id"] == S14_STAR]
    assert [(r["action"], r["value"]) for r in rows] == [("arrival_year", str(real["verified_year"]))]


def test_s14_out_of_window_stops(tmp_path, on_aws):
    base = _no_s14_row((INP / "person_overrides.csv").read_text(encoding="utf-8"))
    row = base + f"{S14_STAR},arrival_year,1998,toy,S14\n"
    argv, out = _setup_m(tmp_path, overrides_text=row, checks=[_check(1998)])
    with pytest.raises(SystemExit, match=f"STOP.*{S14_STAR}.*author"):
        ev.main(argv)
    assert not (out / "events_econ_cal2026-10.csv").exists()
    argv, _ = _setup_m(tmp_path, overrides_text=row, checks=[], name="nocheck")   # the window holds without a check
    with pytest.raises(SystemExit, match=f"STOP.*{S14_STAR}.*author"):
        ev.main(argv)
