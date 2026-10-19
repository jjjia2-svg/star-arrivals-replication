# -*- coding: utf-8 -*-
"""pipeline/aws/r1/verdict_source.py (R1 F16+N1) - the one verdict source every event writer reads.

B0 = October's write_events.py semantics byte for byte (proved on the real repo files); M = the signed
rank tables of restake_r1.py, with a STOP for any event star without a row. Toy tables carry the
October headers read from the frozen files, so a header drift fails here too."""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import verdict_source as vs     # noqa: E402

CAL = REPO / "data" / "cal2026-10"
RV = REPO / "data" / "raw_verified"
FIELDS = ("econ", "chemistry", "math_stats")
ECON_EXTRA = ["rank_pass", "verdict", "verdict_source", "arrival_oct", "event_id_old"]
CM_EXTRA = ["rank_pass", "verdict", "verdict_source", "arrival_oct"]


def _header(p: pathlib.Path) -> list[str]:
    with open(p, newline="", encoding="utf-8") as f:
        return next(csv.reader(f))


ECON_HDR = _header(CAL / "restake_econ11_aug_2026-10.csv")
CM_HDR = _header(CAL / "_invalid_run2" / "verdicts_2026-10.csv")


def _write_csv(p: pathlib.Path, header: list[str], rows: list[dict]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: "" for c in header} | r)
    p.write_text(buf.getvalue(), encoding="utf-8")


def _kind(d: pathlib.Path, kind: str) -> None:
    (d / "kind.json").write_text(json.dumps({"schema": "sar.r1.rank_tables.v1", "kind": kind, "inputs": {}}),
                                 encoding="utf-8")


def _b0(tmp: pathlib.Path, aug=(), aug_all=(), cm=()) -> pathlib.Path:
    d = tmp / "b0"
    d.mkdir()
    _write_csv(d / "restake_econ11_aug_2026-10.csv", ECON_HDR, list(aug))
    _write_csv(d / "restake_econ11_aug_all_2026-10.csv", ECON_HDR, list(aug_all))
    _write_csv(d / "verdicts_2026-10.csv", CM_HDR, list(cm))
    _kind(d, "B0")
    return d


def _m(tmp: pathlib.Path, econ=(), cm=(), name="m") -> pathlib.Path:
    d = tmp / name
    d.mkdir()
    _write_csv(d / "restake_econ_r1.csv", ECON_HDR + ECON_EXTRA, list(econ))
    _write_csv(d / "verdicts_chemmath_r1.csv", CM_HDR + CM_EXTRA, list(cm))
    _kind(d, "M")
    return d


def _econ_row(a, verdict, *, keep=None, p05="False", arrival="2009", school="deakin", aage="6",
              pct="0.97", cell_n="24084", rank_pass="own", old=None, arrival_oct=None):
    keep = (verdict != "DROP") if keep is None else keep
    return {"author_id": a, "school": school, "arrival_true": arrival,
            "after_cell_n": cell_n, "after_pct": pct, "after_pass_p05": p05, "aage": aage,
            "event_keep": str(keep), "rank_pass": rank_pass, "verdict": verdict,
            "verdict_source": "flips_r1.json" if verdict != "ACCEPT" else "add_list_r1.json",
            "arrival_oct": arrival if arrival_oct is None else arrival_oct,
            "event_id_old": "" if verdict == "ACCEPT" else (old or f"{a}:{arrival}")}


def _cm_row(a, field, verdict, *, keep=None, p05="False", school="uwa", arrival="2010", aage="9",
            pct="0.98", cell_n="102", rank_pass="own"):
    keep = (verdict != "DROP") if keep is None else keep
    return {"author_id": a, "field": field, "school": school, "arrival_true": arrival,
            "event_id_old": "" if verdict == "ACCEPT" else f"{a}:{school}", "after_pct": pct,
            "after_cell_n": cell_n, "aage": aage, "event_cal2026_10": str(keep), "event_p05": p05,
            "rank_pass": rank_pass, "verdict": verdict,
            "verdict_source": "flips_r1.json" if verdict != "ACCEPT" else "add_list_r1.json",
            "arrival_oct": arrival}


ECON_SRC_HDR = "event_id,star_id,school,arrival_year,arrival_source,arrival_evidence"
CM_SRC_HDR = "field,school,author_id,display_name,arrival_corrected,evidence_grade,evidence_url,signature"


def _econ_src(*stars) -> str:
    return "\n".join([ECON_SRC_HDR] + [f"{a}:{y},{a},{s},{y},official_roster,strong" for a, y, s in stars]) + "\n"


def _cm_src(field, *stars) -> str:
    return "\n".join([CM_SRC_HDR] + [f"{field},{s},{a},name {a},{y},strong,,signed_by_author_2026-07-24"
                                     for a, y, s in stars]) + "\n"


def _real_corrections() -> dict:
    with open(CAL / "star_id_corrections_2026-10.csv", newline="", encoding="utf-8") as f:
        return {r["old_id"]: r["new_id"] for r in csv.DictReader(f)}


# --------------------------------------------------------------------------------------------- B0 = October

def test_b0_rebuilds_the_six_october_event_tables_byte_for_byte(tmp_path):
    """The switch-off proof: restake_r1's B0 copy + verdict_source B0 + the lifted October loop rebuild the
    six frozen event tables of data/cal2026-10 byte for byte, and October's decision record."""
    import restake_r1                                                    # W1-RANK (pipeline/aws/r1)
    out = tmp_path / "rank_tables"
    out.mkdir()
    restake_r1.copy_october(CAL, out)
    src = vs.load(out)
    assert src.kind == "B0"
    corr = _real_corrections()
    assert corr == vs.read_corrections(CAL / "star_id_corrections_2026-10.csv")
    decision = json.loads((CAL / "events_decision_2026-10.json").read_text(encoding="utf-8"))
    dropped_all = []
    for field, n, n05 in (("econ", 113, 79), ("chemistry", 38, 31), ("math_stats", 33, 22)):
        text = (RV / f"events_{field}_cal2026-08-28.csv").read_bytes().decode("utf-8")
        lines, lines05, dropped = vs.filter_october_rows(field, text, corr, src)
        assert (len(lines) - 1, len(lines05) - 1) == (n, n05), field
        assert ("\n".join(lines) + "\n").encode("utf-8") == (CAL / f"events_{field}_cal2026-10.csv").read_bytes(), field
        assert ("\n".join(lines05) + "\n").encode("utf-8") == (CAL / f"events_{field}_cal2026-10_p05.csv").read_bytes(), field
        assert decision["p05"][field] == {"events": n, "p05_events": n05}
        dropped_all += dropped
    assert dropped_all == decision["dropped"]
    assert src.kept_by_author_ruling == decision["kept_by_author_ruling"]
    assert all(src.new_events(f) == [] for f in FIELDS)


def test_author_keep_is_october_s():
    spec = importlib.util.spec_from_file_location(
        "_oct_write_events", REPO / "pipeline" / "stars" / "caliber_2026-10" / "write_events.py")
    we = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(we)                                           # type: ignore[union-attr]
    assert vs.AUTHOR_KEEP == we.AUTHOR_KEEP


def test_b0_keeps_an_unlisted_econ_star_and_reads_p05_from_aug_all(tmp_path):
    d = _b0(tmp_path,
            aug=[{"author_id": "A2", "event_keep": "False", "aage": "6", "arrival_true": "2009", "school": "deakin"}],
            aug_all=[{"author_id": "A1", "after_pass_p05": "True", "event_keep": "True", "arrival_true": "2006",
                      "school": "adelaide", "aage": "7"},
                     {"author_id": "A3", "after_pass_p05": "True", "event_keep": "False"}])
    src = vs.load(d)
    assert src.keep("econ", "A1") and src.keep("econ", "A3") and src.keep("econ", "A9")
    assert not src.keep("econ", "A2")
    assert src.p05("econ", "A1")
    assert not src.p05("econ", "A3")                                      # aug_all event_keep False
    assert not src.p05("econ", "A9")                                      # no aug_all row
    lines, lines05, dropped = vs.filter_october_rows("econ", _econ_src(("A1", 2006, "adelaide"), ("A2", 2009, "deakin"),
                                                                       ("A9", 2012, "uq")), {}, src)
    assert [ln.split(",")[1] for ln in lines[1:]] == ["A1", "A9"]
    assert [ln.split(",")[1] for ln in lines05[1:]] == ["A1"]
    assert dropped == [{"field": "econ", "event": "A2:2009", "star": "A2"}]


def test_corrected_ids_are_rewritten_in_the_event_id_and_star_columns(tmp_path):
    src = vs.load(_b0(tmp_path))
    text = _econ_src(("OLD1", 2009, "uwa"), ("A5", 2011, "uq"))
    lines, _, _ = vs.filter_october_rows("econ", text, {"OLD1": "NEW1"}, src)
    assert lines[1] == "NEW1:2009,NEW1,uwa,2009,official_roster,strong"
    assert lines[2] == "A5:2011,A5,uq,2011,official_roster,strong"
    cm_text = _cm_src("chemistry", ("OLD2", 2016, "adelaide"))
    lines, _, _ = vs.filter_october_rows("chemistry", cm_text, {"OLD2": "NEW2"}, src)
    assert lines[1].split(",")[2] == "NEW2" and lines[1].split(",")[0] == "chemistry"


# --------------------------------------------------------------------------------------------- M = signed tables

def test_m_stops_on_an_event_star_without_a_row(tmp_path):
    m = vs.load(_m(tmp_path, econ=[_econ_row("A1", "KEEP")], cm=[_cm_row("C1", "chemistry", "KEEP")]))
    b0 = vs.load(_b0(tmp_path))
    text = _econ_src(("A1", 2009, "deakin"), ("A3", 2012, "uq"))
    with pytest.raises(vs.VerdictMissing) as e:
        vs.filter_october_rows("econ", text, {}, m)
    assert "econ" in str(e.value) and "A3" in str(e.value)
    assert (e.value.field, e.value.author_id) == ("econ", "A3")
    lines, _, dropped = vs.filter_october_rows("econ", text, {}, b0)     # October: unlisted econ star kept
    assert [ln.split(",")[1] for ln in lines[1:]] == ["A1", "A3"] and dropped == []
    with pytest.raises(vs.VerdictMissing, match="math_stats.*C1|C1.*math_stats"):
        m.keep("math_stats", "C1")                                        # a chemistry row is not a maths verdict
    with pytest.raises(vs.VerdictMissing):
        m.p05("chemistry", "C9")
    with pytest.raises(vs.VerdictMissing):
        m.row("econ", "A3")


def test_m_does_not_apply_the_october_author_keep(tmp_path):
    drop_star = "A5083769806"
    m = vs.load(_m(tmp_path, cm=[_cm_row(drop_star, "math_stats", "DROP")]))
    text = _cm_src("math_stats", (drop_star, 2010, "uwa"))
    lines, _, dropped = vs.filter_october_rows("math_stats", text, {}, m)
    assert lines[1:] == []
    assert dropped == [{"field": "math_stats", "event": f"{drop_star}:uwa", "star": drop_star}]
    assert m.kept_by_author_ruling == []
    b0 = vs.load(_b0(tmp_path, cm=[{"author_id": drop_star, "field": "math_stats", "school": "uwa",
                                    "arrival_true": "2010", "after_pct": "0.7941",
                                    "event_cal2026_10": "False", "event_p05": "False"}]))
    lines, _, dropped = vs.filter_october_rows("math_stats", text, {}, b0)
    assert len(lines) == 2 and dropped == []
    assert b0.kept_by_author_ruling == [{"star": drop_star, "why": vs.AUTHOR_KEEP[drop_star], "machine_pct": "0.7941"}]


def test_m_keep_and_p05_follow_the_tables(tmp_path):
    m = vs.load(_m(tmp_path,
                   econ=[_econ_row("E1", "KEEP", p05="True"), _econ_row("E2", "KEEP", p05="False"),
                         _econ_row("E3", "DROP", p05="True"), _econ_row("E4", "ACCEPT", p05="True")],
                   cm=[_cm_row("C1", "chemistry", "KEEP", p05="True"), _cm_row("C2", "chemistry", "DROP", p05="True"),
                       _cm_row("M1", "math_stats", "ACCEPT", p05="False"), _cm_row("M2", "math_stats", "KEEP", p05="True")]))
    assert [m.keep("econ", a) for a in ("E1", "E2", "E3", "E4")] == [True, True, False, True]
    assert [m.p05("econ", a) for a in ("E1", "E2", "E3", "E4")] == [True, False, False, True]
    assert (m.keep("chemistry", "C1"), m.p05("chemistry", "C1")) == (True, True)
    assert (m.keep("chemistry", "C2"), m.p05("chemistry", "C2")) == (False, False)  # never p05 when dropped
    assert (m.keep("math_stats", "M1"), m.p05("math_stats", "M1")) == (True, False)
    assert (m.keep("math_stats", "M2"), m.p05("math_stats", "M2")) == (True, True)
    lines, lines05, dropped = vs.filter_october_rows(
        "chemistry", _cm_src("chemistry", ("C1", 2016, "uwa"), ("C2", 2015, "uwa")), {}, m)
    assert [ln.split(",")[2] for ln in lines[1:]] == ["C1"]
    assert [ln.split(",")[2] for ln in lines05[1:]] == ["C1"]
    assert dropped == [{"field": "chemistry", "event": "C2:uwa", "star": "C2"}]


def test_m_refuses_a_table_whose_keep_disagrees_with_its_signed_verdict(tmp_path):
    with pytest.raises(ValueError, match="E1"):
        vs.load(_m(tmp_path, econ=[_econ_row("E1", "DROP", keep=True)]))
    with pytest.raises(ValueError, match="C1"):
        vs.load(_m(tmp_path, cm=[_cm_row("C1", "chemistry", "KEEP", keep=False)], name="b"))
    with pytest.raises(ValueError, match="REJECT"):
        vs.load(_m(tmp_path, econ=[_econ_row("E2", "REJECT", keep=False)], name="c"))


def test_a_dropped_october_star_comes_back_through_its_0828_row(tmp_path):
    restored_star = "A5110738002"
    m = vs.load(_m(tmp_path,
                   econ=[_econ_row(restored_star, "KEEP", arrival="2009", school="deakin"),
                         _econ_row("A7", "KEEP", arrival="2011", school="uq"),
                         _econ_row("N1", "ACCEPT", arrival="2015", school="monash", aage="12", pct="0.981"),
                         _econ_row("N2", "ACCEPT", arrival="2019", school="anu", rank_pass="C")],
                   cm=[_cm_row("NC", "chemistry", "ACCEPT", school="monash", arrival="2005")]))
    text = _econ_src((restored_star, 2009, "deakin"), ("A7", 2011, "uq"))
    lines, _, dropped = vs.filter_october_rows("econ", text, {}, m)
    assert lines == [ln for ln in text.split("\n") if ln] and dropped == []
    new = m.new_events("econ")
    assert [e["author_id"] for e in new] == ["N1", "N2"]
    assert restored_star not in {e["author_id"] for e in new}
    assert (new[0]["arrival_true"], new[0]["school"], new[0]["aage"], new[0]["rank_pass"]) == (2015, "monash", 12, "own")
    assert (new[1]["arrival_true"], new[1]["school"], new[1]["rank_pass"]) == (2019, "anu", "C")
    assert all(e["field"] == "econ" and e["event_id_old"] is None for e in new)
    nc = m.new_events("chemistry")
    assert [(e["author_id"], e["arrival_true"], e["school"]) for e in nc] == [("NC", 2005, "monash")]
    assert m.new_events("math_stats") == []
    b0 = vs.load(_b0(tmp_path, aug=[{"author_id": restored_star, "event_keep": "False", "arrival_true": "2009",
                                     "school": "deakin", "aage": "6"}]))
    lines, _, dropped = vs.filter_october_rows("econ", text, {}, b0)  # October removed him
    assert dropped == [{"field": "econ", "event": f"{restored_star}:2009", "star": restored_star}]


def test_m_new_events_exclude_dropped_and_old_rows(tmp_path):
    m = vs.load(_m(tmp_path, econ=[_econ_row("A1", "KEEP"), _econ_row("A2", "DROP")]))
    assert m.new_events("econ") == []
    bad = _econ_row("N1", "ACCEPT")
    bad["event_id_old"] = "N1:2009"
    with pytest.raises(ValueError, match="N1"):
        vs.load(_m(tmp_path, econ=[bad], name="x"))


def test_row_exposes_the_admitting_rank(tmp_path):
    m = vs.load(_m(tmp_path,
                   econ=[_econ_row("A5028731684", "KEEP", arrival="2008", arrival_oct="2010", aage="8", pct="0.974",
                                   school="anu", old="A5028731684:2010"),
                         _econ_row("A5001177483", "KEEP", rank_pass="C", pct="0.9373", aage="", cell_n="")],
                   cm=[_cm_row("C1", "chemistry", "KEEP", rank_pass="own", pct="0.991", cell_n="88", aage="14")]))
    r = m.row("econ", "A5028731684")
    assert r == {"aage": 8, "after_pct": 0.974, "after_cell_n": 24084, "arrival_true": 2008, "school": "anu",
                 "rank_pass": "own", "event_id_old": "A5028731684:2010"}
    assert type(r["aage"]) is int and type(r["after_pct"]) is float and type(r["arrival_true"]) is int
    r = m.row("econ", "A5001177483")
    assert (r["rank_pass"], r["after_pct"], r["aage"], r["after_cell_n"]) == ("C", 0.9373, None, None)
    r = m.row("chemistry", "C1")
    assert r == {"aage": 14, "after_pct": 0.991, "after_cell_n": 88, "arrival_true": 2010, "school": "uwa",
                 "rank_pass": "own", "event_id_old": "C1:uwa"}

    # B0 economics: the restake_econ11_aug row first (aage exactly as econ920's rekeyed_star_set reads it,
    # int(row["aage"])), else the aug_all row; chemistry/maths: the run-2 verdict row.
    b0d = tmp_path / "b0real"
    b0d.mkdir()
    for name, src in (("restake_econ11_aug_2026-10.csv", CAL / "restake_econ11_aug_2026-10.csv"),
                      ("restake_econ11_aug_all_2026-10.csv", CAL / "restake_econ11_aug_all_2026-10.csv"),
                      ("verdicts_2026-10.csv", CAL / "_invalid_run2" / "verdicts_2026-10.csv")):
        (b0d / name).write_bytes(src.read_bytes())
    _kind(b0d, "B0")
    b0 = vs.load(b0d)
    with open(CAL / "restake_econ11_aug_2026-10.csv", newline="", encoding="utf-8") as f:
        aug = {x["author_id"]: x for x in csv.DictReader(f)}
    ma = b0.row("econ", "A5091326353")
    assert ma["aage"] == int(aug["A5091326353"]["aage"]) == 4
    assert (ma["arrival_true"], ma["school"], ma["rank_pass"]) == (2009, "uwa", None)
    um = b0.row("econ", "A5080057811")                                   # in aug_all only
    assert (um["aage"], um["arrival_true"], um["school"], um["after_pct"]) == (7, 2006, "adelaide", 0.9936)
    se = b0.row("math_stats", "A5083769806")
    assert (se["aage"], se["event_id_old"], se["school"]) == (9, "A5083769806:uwa", "uwa")
    with pytest.raises(vs.VerdictMissing):
        b0.row("chemistry", "A5083769806")                                # his row is a maths row


def test_load_refuses_a_dir_that_is_not_a_rank_tables_dir(tmp_path):
    with pytest.raises(FileNotFoundError):
        vs.load(tmp_path)
    (tmp_path / "kind.json").write_text(json.dumps({"schema": "sar.r1.rank_tables.v1", "kind": "X"}), encoding="utf-8")
    with pytest.raises(ValueError, match="kind"):
        vs.load(tmp_path)
    (tmp_path / "kind.json").write_text(json.dumps({"schema": "other", "kind": "B0"}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        vs.load(tmp_path)
    with pytest.raises(ValueError, match="field"):
        vs.load(_b0(tmp_path)).keep("physics", "A1")
