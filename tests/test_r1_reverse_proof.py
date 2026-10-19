# -*- coding: utf-8 -*-
"""pipeline/aws/r1/reverse_proof_s10.py - R1 J0-MEAS.3j (N2's real-data proof), toy tests.

Every table here is a toy built in tmp_path (pyarrow parquet) and read with an in-memory duckdb; the real
data root and the legacy trees are never opened. The chem/maths driver, the October comparison and the
roster-channel check are replaced by recorders where a test is about the orchestration, so nothing here
runs a builder. The real proof is tests/test_r1_reverse_proof_real.py (big host, batch B4).
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import reverse_proof_s10 as rp   # noqa: E402

FIELDS = ("chemistry", "math_stats")


def _pq(path: pathlib.Path, cols: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(cols), path)


def _table(root: pathlib.Path, *, edges, works, affil, wfp, pop, extra=True) -> pathlib.Path:
    """A toy u1 table: <sub>/bucket=00x/part.parquet, split over two buckets like the real layout. The column
    types come from all rows, then the table is sliced: a one-row subtable leaves bucket=000 empty, and an
    empty Python list would give pyarrow's untyped `null` column, which no real (typed) u1 bucket has."""
    for sub, cols in (("authorship_edges", edges), ("works", works), ("works_affil", affil),
                      ("work_first_pub", wfp), ("fwci_baseline_pop", pop)):
        t = pa.table(cols)
        half = t.num_rows // 2
        for b, part in (("bucket=000", t.slice(0, half)), ("bucket=001", t.slice(half))):
            f = root / sub / b / "part.parquet"
            f.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(part, f)
    if extra:
        _pq(root / "authors" / "bucket=000" / "part.parquet", {"author_id": ["A1", "A2"]})
    (root / "_manifest").mkdir(parents=True, exist_ok=True)
    return root


def _edges(rows):
    return {"work_id": [r[0] for r in rows], "author_id": [r[1] for r in rows],
            "publication_year": [r[2] for r in rows]}


def _works(rows):
    return {"work_id": [r[0] for r in rows], "publication_year": [r[1] for r in rows],
            "subfield_id": [r[2] for r in rows]}


@pytest.fixture
def toy(tmp_path):
    """07-05 holds works W1-W3; the 11-school table holds W1-W5 (a superset) with identical W1-W3 rows."""
    e0705 = [("W1", "A1", 2001), ("W2", "A1", 2003), ("W2", "A2", 2003), ("W3", "A2", 2005)]
    w0705 = [("W1", 2001, "sf/1"), ("W2", 2003, "sf/2"), ("W3", 2005, "sf/1")]
    e11 = e0705 + [("W4", "A3", 2007), ("W5", "A1", 2009)]
    w11 = w0705 + [("W4", 2007, "sf/3"), ("W5", 2009, "sf/2")]
    r0705 = _table(tmp_path / "data" / "derived" / "u1_edges_full_2026-07-05",
                   edges=_edges(e0705), works=_works(w0705),
                   affil={"work_id": ["W1", "W2", "W3"], "inst": ["I1", "I1", "I2"]},
                   wfp={"author_id": ["A1", "A2"], "first_pub_year": [2001, 2003]},
                   pop={"k": ["x", "y"], "v": [1.0, 2.0]})
    r11 = _table(tmp_path / "data" / "derived" / "u1_full_11school_2026-07-16",
                 edges=_edges(e11), works=_works(w11),
                 affil={"work_id": ["W1", "W2", "W3", "W4", "W5"], "inst": ["I1", "I1", "I2", "I3", "I1"]},
                 wfp={"author_id": ["A1", "A2", "A3"], "first_pub_year": [2001, 2003, 2007]},
                 pop={"k": ["x", "y", "z"], "v": [1.0, 2.0, 3.0]})
    out = tmp_path / "stage_out"
    out.mkdir()
    return {"tmp": tmp_path, "r0705": r0705, "r11": r11, "out": out, "con": duckdb.connect()}


def _rows(con, table: pathlib.Path, sub: str, cols: str) -> list:
    return sorted(con.execute(f"SELECT {cols} FROM read_parquet('{table}/{sub}/**/*.parquet', "
                              f"hive_partitioning=0)").fetchall())


def test_cut_keeps_exactly_the_0705_works(toy):
    con = toy["con"]
    info = rp.cut(toy["r0705"], toy["r11"], toy["out"], con)
    cut_dir = pathlib.Path(toy["out"]) / "cut" / "u1_cut"
    assert pathlib.Path(info["dir"]) == cut_dir
    # every filtered subtable is written as <sub>/bucket=000/part-0.parquet
    for sub in ("authorship_edges", "works", "works_affil", "work_first_pub", "fwci_baseline_pop"):
        assert [p.relative_to(cut_dir / sub).as_posix() for p in (cut_dir / sub).rglob("*.parquet")] \
            == ["bucket=000/part-0.parquet"], sub
    assert info["works_W"] == 3
    # the cut rows are the 11-school rows whose work_id is in W = 07-05 works U edges
    assert _rows(con, cut_dir, "authorship_edges", "*") == _rows(con, toy["r0705"], "authorship_edges", "*")
    assert _rows(con, cut_dir, "works", "*") == _rows(con, toy["r0705"], "works", "*")
    assert _rows(con, cut_dir, "works_affil", "work_id") == [("W1",), ("W2",), ("W3",)]
    # work_first_pub is filtered by the 07-05 authors; pop is copied whole from the 11-school table
    assert _rows(con, cut_dir, "work_first_pub", "author_id") == [("A1",), ("A2",)]
    assert _rows(con, cut_dir, "fwci_baseline_pop", "k") == [("x",), ("y",), ("z",)]
    # a subtable the chem/maths readers never read is linked to the 11-school one, not copied
    assert (cut_dir / "authors").is_symlink()
    assert os.path.realpath(cut_dir / "authors") == os.path.realpath(toy["r11"] / "authors")
    assert info["subtables"]["authors"]["how"] == "link_unread"
    assert info["subtables"]["authorship_edges"] == {"how": "filter_work_id", "rows": 4}
    assert info["subtables"]["work_first_pub"]["how"] == "filter_author_id"
    assert info["subtables"]["fwci_baseline_pop"]["how"] == "copy_whole"
    # the premise holds on this toy: the cut equals the 07-05 table by content
    prem = rp.premise(cut_dir, toy["r0705"], con)
    assert prem["verdict"] == "PREMISE_OK" and prem["ok"]
    assert prem["works_0705_not_in_11"] == 0
    for sub in rp.PREMISE_SUBTABLES:
        s = prem["subtables"][sub]
        assert (s["only_in_0705"], s["only_in_cut"], s["columns_equal"]) == (0, 0, True), sub
    # a second cut into the same out refuses rather than overwriting
    with pytest.raises(FileExistsError):
        rp.cut(toy["r0705"], toy["r11"], toy["out"], con)


def test_cut_records_a_0705_subtable_without_data_that_the_11_school_table_lacks(toy):
    """t-big-03 (B4) failed on setup: "the 11-school table lacks ['canonical_id_map']". The real 07-05
    canonical_id_map has 0 rows (U1 wrote only its provenance.json) and the 11-school table on S3 has none.
    The cut records it as absent_empty_in_0705 and links nothing; the edge-table shadow over the cut then
    accepts it (the same rule, edge_table._subtables_with_data). A 07-05 subtable WITH a parquet file that
    the 11-school table lacks still refuses (positive control)."""
    import edge_table as et                                                 # noqa: PLC0415
    cim = toy["r0705"] / "canonical_id_map"
    cim.mkdir()
    (cim / "provenance.json").write_text('{"row_count": 0, "table": "canonical_id_map"}\n')
    info = rp.cut(toy["r0705"], toy["r11"], toy["out"], toy["con"])
    cut_dir = pathlib.Path(info["dir"])
    assert info["subtables"]["canonical_id_map"] == {"how": "absent_empty_in_0705"}
    assert not os.path.lexists(cut_dir / "canonical_id_map")
    rp.check_ids_counts(info["subtables"])
    mf = et.build_ssd_shadow(toy["tmp"] / "data", toy["tmp"] / "shadow_cut", cut_dir)
    assert mf["table_0705_subtables_without_data"] == ["canonical_id_map"]
    _pq(cim / "bucket=000" / "part.parquet", {"raw_id": ["A9"], "canonical_id": ["A1"]})
    with pytest.raises(ValueError, match="canonical_id_map"):
        rp.cut(toy["r0705"], toy["r11"], toy["tmp"] / "out2", toy["con"])


def test_premise_reports_a_missing_work_and_a_differing_row(tmp_path):
    e0705 = [("W1", "A1", 2001), ("W2", "A1", 2003), ("W9", "A2", 2004)]       # W9 only in 07-05
    w0705 = [("W1", 2001, "sf/1"), ("W2", 2003, "sf/2"), ("W9", 2004, "sf/9")]
    e11 = [("W1", "A1", 2001), ("W2", "A1", 2002), ("W4", "A3", 2007)]          # W2 edge: other year
    w11 = [("W1", 2001, "sf/1"), ("W2", 2003, "sf/2"), ("W4", 2007, "sf/3")]
    common = dict(affil={"work_id": ["W1", "W2"], "inst": ["I1", "I1"]},
                  wfp={"author_id": ["A1", "A2"], "first_pub_year": [2001, 2004]},
                  pop={"k": ["x", "y"], "v": [1.0, 2.0]})
    r0705 = _table(tmp_path / "d" / "u1_edges_full_2026-07-05", edges=_edges(e0705), works=_works(w0705),
                   **common)
    r11 = _table(tmp_path / "d" / "u1_full_11school_2026-07-16", edges=_edges(e11), works=_works(w11),
                 **common)
    out = tmp_path / "out"
    out.mkdir()
    con = duckdb.connect()
    info = rp.cut(r0705, r11, out, con)
    prem = rp.premise(pathlib.Path(info["dir"]), r0705, con)
    assert prem["verdict"] == "PREMISE_FAIL" and not prem["ok"]
    assert prem["works_0705_not_in_11"] == 1
    assert prem["works_0705_not_in_11_sample"] == ["W9"]
    edges = prem["subtables"]["authorship_edges"]
    assert edges["only_in_0705"] == 2          # (W2, A1, 2003) and (W9, A2, 2004)
    assert edges["only_in_cut"] == 1           # (W2, A1, 2002)
    assert edges["decides"] is True
    assert "W2" in edges["sample_ids_only_in_cut"]
    assert prem["subtables"]["works"]["only_in_0705"] == 1
    # the 11-school pop is copied whole and is not read by the chem/maths chain: reported, not deciding
    assert prem["subtables"]["fwci_baseline_pop"]["decides"] is False


def test_premise_casts_categoricals_to_varchar(tmp_path):
    """A pandas categorical (dictionary) column on one side and plain VARCHAR on the other compare equal."""
    con = duckdb.connect()
    cols = dict(affil={"work_id": ["W1"], "inst": ["I1"]},
                wfp={"author_id": ["A1"], "first_pub_year": [2001]}, pop={"k": ["x"], "v": [1.0]})
    works = _works([("W1", 2001, "sf/1")])
    r0705 = _table(tmp_path / "d" / "u1_edges_full_2026-07-05", edges=_edges([("W1", "A1", 2001)]),
                   works=works, extra=False, **cols)
    cat = pa.table({"work_id": pa.array(["W1"]).dictionary_encode(),
                    "author_id": pa.array(["A1"]).dictionary_encode(),
                    "publication_year": [2001]})
    for b in ("bucket=000", "bucket=001"):
        f = r0705 / "authorship_edges" / b / "part.parquet"
        pq.write_table(cat if b == "bucket=000" else cat.slice(0, 0), f)
    r11 = _table(tmp_path / "d" / "u1_full_11school_2026-07-16", edges=_edges([("W1", "A1", 2001)]),
                 works=works, extra=False, **cols)
    out = tmp_path / "out"
    out.mkdir()
    info = rp.cut(r0705, r11, out, con)
    prem = rp.premise(pathlib.Path(info["dir"]), r0705, con)
    assert prem["subtables"]["authorship_edges"]["only_in_0705"] == 0
    assert prem["ok"], prem


# ---- orchestration: driver, compare and roster check replaced by recorders --------------------------

class _Recorder:
    """A fake chem/maths driver: records (label, target) and returns a stage_out with no products."""

    def __init__(self):
        self.calls = []

    def __call__(self, label, target, out):
        d = pathlib.Path(out) / label / "stage_out"
        d.mkdir(parents=True)
        for f in FIELDS:     # a driver report carrying a display name must never reach the summary
            (d / f"frames_{f}").mkdir()
            (d / f"frames_{f}" / f"build_report_{f}.json").write_text(
                json.dumps({"star": "Jane Q. Example", "author_id": "A1"}), encoding="utf-8")
        self.calls.append((label, pathlib.Path(target).name))
        return {"label": label, "rc": 0, "secs": 0.0, "stage_out": d, "target_name": pathlib.Path(target).name}


def _cmp(ok):
    return {"ok": ok, "fields": {f: {"ok": ok, "files": {f"relationships_{f}.csv": {
        "status": "BYTE_EQUAL" if ok else "NOT_EQUAL", "ok": ok}}} for f in FIELDS}}


def _roster(ok):
    return {"ok": ok, "fields": {f: {"ok": ok, "n_unexplained": 0 if ok else 1,
                                     "unexplained": [] if ok else [["A7", "A9:monash"]]} for f in FIELDS}}


def _prove(toy, monkeypatch, *, premise_ok, cmp_by_label, roster_ok, drv=None):
    drv = drv or _Recorder()
    monkeypatch.setattr(rp, "premise", lambda cut_dir, r0705, con: {
        "ok": premise_ok, "verdict": "PREMISE_OK" if premise_ok else "PREMISE_FAIL",
        "subtables": {}, "works_0705_not_in_11": 0 if premise_ok else 3,
        "works_0705_not_in_11_sample": [] if premise_ok else ["W9"]})
    seen = []

    def fake_compare(products, ref_dir, fields, scratch):
        label = pathlib.Path(products).parent.name
        seen.append(label)
        return _cmp(cmp_by_label[label])
    monkeypatch.setattr(rp, "compare", fake_compare)
    monkeypatch.setattr(rp, "roster_channel", lambda on, ref, fields, **kw: _roster(roster_ok))
    s = rp.prove(toy["r0705"], toy["r11"], toy["out"], toy["tmp"] / "ref", fields=FIELDS, driver=drv,
                 con=toy["con"])
    return s, drv, seen


def test_verdict_logic(toy, monkeypatch, tmp_path):
    # premise ok + products equal + roster channel unchanged -> REVERSE_PROOF_OK; no wiring run
    s, drv, seen = _prove(toy, monkeypatch, premise_ok=True, cmp_by_label={"cut": True}, roster_ok=True)
    assert s["verdict"] == "REVERSE_PROOF_OK" and s["ok"]
    assert [c[0] for c in drv.calls] == ["cut", "on"]
    assert drv.calls[1][1] == "u1_full_11school_2026-07-16"     # the roster check runs on the full table
    assert seen == ["cut"]
    assert (toy["out"] / "RESULT.txt").read_text(encoding="utf-8").strip() == "RESULT REVERSE_PROOF_OK"

    # pure verdict table
    assert rp.verdict(premise_ok=True, products_ok=True, roster_ok=True) == "REVERSE_PROOF_OK"
    assert rp.verdict(premise_ok=False, products_ok=True, roster_ok=True) == "PREMISE_FAIL+WIRING_OK"
    assert rp.verdict(premise_ok=True, products_ok=False, roster_ok=True) == "DIFF"
    assert rp.verdict(premise_ok=False, products_ok=False, roster_ok=False) == "DIFF"
    assert rp.verdict(premise_ok=True, products_ok=True, roster_ok=False) == "ROSTER_CHANNEL_DIFF"
    assert rp.verdict(premise_ok=False, products_ok=True, roster_ok=False) == "ROSTER_CHANNEL_DIFF"


def _toy_plain(tmp_path):
    e = [("W1", "A1", 2001), ("W2", "A2", 2003)]
    w = [("W1", 2001, "sf/1"), ("W2", 2003, "sf/2")]
    kw = dict(affil={"work_id": ["W1", "W2"], "inst": ["I1", "I1"]},
              wfp={"author_id": ["A1", "A2"], "first_pub_year": [2001, 2003]},
              pop={"k": ["x", "y"], "v": [1.0, 2.0]})
    r0705 = _table(tmp_path / "data" / "derived" / "u1_edges_full_2026-07-05", edges=_edges(e), works=_works(w),
                   **kw)
    r11 = _table(tmp_path / "data" / "derived" / "u1_full_11school_2026-07-16", edges=_edges(e),
                 works=_works(w), **kw)
    out = tmp_path / "stage_out"
    out.mkdir()
    return {"tmp": tmp_path, "r0705": r0705, "r11": r11, "out": out, "con": duckdb.connect()}


@pytest.mark.parametrize("wiring_ok,want", [(True, "PREMISE_FAIL+WIRING_OK"), (False, "DIFF")])
def test_premise_fail_requests_a_wiring_run_that_decides(tmp_path, monkeypatch, wiring_ok, want):
    toy = _toy_plain(tmp_path)
    s, drv, seen = _prove(toy, monkeypatch, premise_ok=False,
                          cmp_by_label={"cut": False, "wiring": wiring_ok}, roster_ok=True)
    assert [c[0] for c in drv.calls] == ["cut", "on", "wiring"]
    assert drv.calls[2][1] == "u1_0705_copy"                    # the re-materialised 07-05 copy
    assert seen == ["cut", "wiring"]
    assert s["verdict"] == want
    assert s["compare"]["cut"]["ok"] is False                     # recorded, not deciding, on a premise fail
    rem = toy["out"] / "wiring" / "u1_0705_copy"
    con = toy["con"]
    for sub in ("authorship_edges", "works", "works_affil", "work_first_pub", "fwci_baseline_pop"):
        assert _rows(con, rem, sub, "*") == _rows(con, toy["r0705"], sub, "*"), sub
    assert (rem / "authors").is_symlink()


def test_roster_channel_diff_outside_the_guard(toy, monkeypatch):
    s, _drv, _seen = _prove(toy, monkeypatch, premise_ok=True, cmp_by_label={"cut": True}, roster_ok=False)
    assert s["verdict"] == "ROSTER_CHANNEL_DIFF" and not s["ok"]
    assert s["roster_channel"]["fields"]["chemistry"]["unexplained"] == [["A7", "A9:monash"]]


class _StopsOnCut(_Recorder):
    """A driver whose 'cut' run exits non-zero: make_driver's ReverseProofStop with the run record attached."""

    RUN = {"label": "cut", "rc": 3, "secs": 1.5, "target_name": "u1_cut", "swapped_name": "u1_edges_full_2026-07-05",
           "edge_target": None, "stop_code": "PRODLIB_EXIT", "stop_ids": ["chemistry"], "n_stop_ids": 1}

    def __call__(self, label, target, out):
        if label == "cut":
            self.calls.append((label, pathlib.Path(target).name))
            raise rp.ReverseProofStop("driver run 'cut' failed rc=3: STOP PRODLIB_EXIT", run=dict(self.RUN))
        return super().__call__(label, target, out)


def test_premise_fail_records_a_stopped_cut_run_and_the_wiring_run_decides(tmp_path, monkeypatch):
    """t-big-04: the cut run exited rc=3 and the proof stopped there, before the wiring run. On PREMISE_FAIL the
    cut is not the 07-05 table, so (module docstring) its run is recorded and does not decide: rc and STOP code
    go into the summary, compare.cut is null, and the wiring run on the re-materialised 07-05 copy decides."""
    toy = _toy_plain(tmp_path)
    s, drv, seen = _prove(toy, monkeypatch, premise_ok=False, cmp_by_label={"wiring": True}, roster_ok=True,
                          drv=_StopsOnCut())
    assert [c[0] for c in drv.calls] == ["cut", "on", "wiring"] and seen == ["wiring"]
    assert s["verdict"] == "PREMISE_FAIL+WIRING_OK" and s["ok"] and s["compare"]["cut"] is None
    assert s["runs"]["cut"] == {"rc": 3, "secs": 1.5, "target": "u1_cut", "stop_code": "PRODLIB_EXIT",
                                "stop_ids": ["chemistry"]}
    assert s["runs"]["on"]["rc"] == 0 and s["runs"]["on"]["stop_code"] is None
    assert json.loads((toy["out"] / rp.SUMMARY_NAME).read_text(encoding="utf-8")) == s


def test_a_stopped_cut_run_on_premise_ok_stops_the_proof_and_names_the_premise(toy, monkeypatch):
    """With the premise holding, a cut-run failure is a wiring failure: the proof STOPs (RESULT STOP), and the
    stop text carries the driver's message plus the premise verdict."""
    with pytest.raises(rp.ReverseProofStop) as e:
        _prove(toy, monkeypatch, premise_ok=True, cmp_by_label={}, roster_ok=True, drv=_StopsOnCut())
    msg = str(e.value)
    assert "STOP PRODLIB_EXIT" in msg and "premise PREMISE_OK" in msg and e.value.run["rc"] == 3
    assert (toy["out"] / "RESULT.txt").read_text(encoding="utf-8") == "RESULT STOP\n"
    assert "premise PREMISE_OK" in (toy["out"] / "stop.txt").read_text(encoding="utf-8")
    assert not (toy["out"] / rp.SUMMARY_NAME).exists()


# ---- the roster-channel check and the age-gap guard explanation, on toy products ------------------

P1_HDR = ("incumbent_person_id,year,star_person_id,event_id,treated,post,dose_coupling_baseline,dose_topic,"
          "dose_low_confidence,age_gap,fwci_frac,pub_count,fwci_frac_ex_star,pub_count_ex_star,fwci_mean,"
          "fwci_mean_ex_star,channel\n")


def _products(d: pathlib.Path, field: str, rels: list, p1: list, dropped: list, n_dropped=None) -> None:
    """rels: (pid, event, channel); p1: (pid, event, age_gap, channel), one line per relation (enough here)."""
    f = d / f"frames_{field}"
    f.mkdir(parents=True, exist_ok=True)
    (f / f"relationships_{field}.csv").write_text(
        "pid,event_id,channel\n" + "".join(f"{p},{e},{c}\n" for p, e, c in rels), encoding="utf-8")
    (f / f"p1_frame_{field}.csv").write_text(P1_HDR + "".join(
        f"{p},2010,{e.split(':')[0]},{e},True,False,,0.1,False,{g},0.0,0,0.0,0,,,{c}\r\n"
        for p, e, g, c in p1), encoding="utf-8")
    (f / f"union_build_report_{field}.json").write_text(json.dumps({
        "fp_gap": 10, "age_gap_guard_max": 60,
        "age_gap_guard": {"new_rel_dropped": len(dropped) if n_dropped is None else n_dropped,
                          "dropped_examples": [[p, e, str(g)] for p, e, g in dropped]}}), encoding="utf-8")


def test_roster_channel_explains_only_age_gap_guard_drops(tmp_path):
    ref, on = tmp_path / "ref", tmp_path / "on"
    oct_rels = [("P1", "S1:uq", "dept_only"), ("P2", "S1:uq", "both"), ("P3", "S1:uq", "dept_only"),
                ("P4", "S2:uq", "dept_only"), ("P5", "S2:uq", "dept_only"), ("P1", "S2:uq", "dept_only"),
                ("P5", "S1:uq", "dept_only"), ("P8", "S2:uq", "dept_only"), ("P8", "S1:uq", "dept_only"),
                ("P9", "S1:uq", "network")]
    oct_p1 = [("P1", "S1:uq", 10.0, "dept_only"), ("P2", "S1:uq", 999.0, "both"),
              ("P3", "S1:uq", 12.0, "dept_only"), ("P4", "S2:uq", 5.0, "dept_only"),
              ("P5", "S2:uq", 50.0, "dept_only"), ("P1", "S2:uq", 3.0, "dept_only"),
              ("P5", "S1:uq", 57.0, "dept_only"), ("P8", "S2:uq", 23.0, "dept_only"),
              ("P8", "S1:uq", 30.0, "dept_only"), ("P9", "S1:uq", 999.0, "network")]
    # ON (the full 11-school table): lost P3@S1 (no ON relation left: underivable), P4@S2 (listed by the ON
    # guard), P5@S2 (derived through P5@S1 and P1: -55 - 7 = -62 -> |gap| > 60), P8@S2 (derived 30 - 7 = 23,
    # inside the guard -> unexplained); gained P6@S1 (listed by the October guard).
    on_rels = [("P1", "S1:uq", "dept_only"), ("P2", "S1:uq", "both"), ("P1", "S2:uq", "dept_only"),
               ("P5", "S1:uq", "dept_only"), ("P6", "S1:uq", "dept_only"), ("P8", "S1:uq", "dept_only"),
               ("P9", "S1:uq", "network"), ("P10", "S2:uq", "network")]
    on_p1 = [("P1", "S1:uq", 10.0, "dept_only"), ("P1", "S2:uq", 3.0, "dept_only"),
             ("P2", "S1:uq", 999.0, "both"), ("P5", "S1:uq", -55.0, "dept_only"),
             ("P6", "S1:uq", 20.0, "dept_only"), ("P8", "S1:uq", 30.0, "dept_only"),
             ("P9", "S1:uq", 999.0, "network"), ("P10", "S2:uq", -999.0, "network")]
    for f in FIELDS:
        _products(ref, f, oct_rels, oct_p1, dropped=[("P6", "S1:uq", 75.0)])
        _products(on, f, on_rels, on_p1, dropped=[("P4", "S2:uq", 66.0)], n_dropped=3)
    r = rp.roster_channel(on, ref, FIELDS)
    c = r["fields"]["chemistry"]
    assert (c["oct"], c["on"], c["lost"], c["gained"]) == (9, 6, 4, 1)   # network rows never counted
    assert c["explained"] == {"dropped_example": 2, "derived": 1, "direct": 0}
    assert sorted(map(tuple, c["unexplained"])) == [("P3", "S1:uq"), ("P8", "S2:uq")]
    assert c["n_unexplained"] == 2 and not c["ok"] and not r["ok"]
    assert c["guard_count_exceeded"] is False

    # the same lost relations against an ON report that dropped only one: the count cannot close
    for f in FIELDS:
        (on / f"frames_{f}").rename(on / f"old_{f}")
        _products(on, f, on_rels, on_p1, dropped=[("P4", "S2:uq", 66.0)], n_dropped=1)
    c = rp.roster_channel(on, ref, FIELDS)["fields"]["chemistry"]
    assert c["guard_count_exceeded"] is True and not c["ok"]

    # with every lost / gained relation explained the field is OK
    good_on = [r_ for r_ in on_rels] + [("P3", "S1:uq", "dept_only"), ("P8", "S2:uq", "dept_only")]
    good_p1 = on_p1 + [("P3", "S1:uq", 12.0, "dept_only"), ("P8", "S2:uq", 23.0, "dept_only")]
    on2 = tmp_path / "on2"
    for f in FIELDS:
        _products(on2, f, good_on, good_p1, dropped=[("P4", "S2:uq", 66.0)], n_dropped=3)
    r = rp.roster_channel(on2, ref, FIELDS)
    assert r["ok"] and r["fields"]["math_stats"]["n_unexplained"] == 0


def test_potentials_derive_a_gap_through_other_relations():
    pot = rp.Potentials([("P1", "E1", 10.0), ("P1", "E2", 3.0), ("P2", "E2", 70.0)])
    # S(E1) - P(P2) = (S(E1) - P(P1)) - (S(E2) - P(P1)) + (S(E2) - P(P2)) = 10 - 3 + 70
    assert pot.gap("P2", "E1") == 77.0
    assert pot.gap("P1", "E1") == 10.0
    assert pot.gap("P3", "E1") is None                  # never seen
    bad = rp.Potentials([("P1", "E1", 1.0), ("P1", "E2", 2.0), ("P2", "E1", 5.0), ("P2", "E2", 9.0)])
    assert bad.gap("P1", "E1") is None                  # inconsistent component -> no derivation


def test_direct_first_pub_explains_a_person_who_lost_every_relation(tmp_path):
    """The direct route (person's robust first year from the edge table, folded through the person map),
    accepted only when >= 2 anchor persons of the event agree with the builder's own gaps."""
    con = duckdb.connect()
    table = tmp_path / "d" / "u1_full_11school_2026-07-16"
    # A1: an isolated 1880 work, then 2000 -> the 1880 lead is dropped (gap 120 > 10) -> 2000.
    # A5's alias A5b holds 1930 and 1935 (gap 5 <= 10) -> 1930, through the person map.
    e = [("W0", "A1", 1880), ("W1", "A1", 2000), ("W2", "A1", 2002), ("W3", "A2", 2004), ("W4", "A2", 2005),
         ("W5", "A5b", 1930), ("W6", "A5b", 1935), ("W7", "A5", 2001)]
    _table(table, edges=_edges(e), works=_works([(w, y, "sf/1") for w, _a, y in e]),
           affil={"work_id": ["W1"], "inst": ["I1"]}, wfp={"author_id": ["A1"], "first_pub_year": [2000]},
           pop={"k": ["x"], "v": [1.0]}, extra=False)
    pmap = tmp_path / "pmap.parquet"
    pq.write_table(pa.table({"person_id": ["Q5", "Q5"], "author_id": ["A5", "A5b"]}), pmap)
    pf = rp.first_pub_direct(con, table, pmap, ["A1", "A2", "A5", "A0"], fp_gap=10)
    assert pf == {"A1": 2000, "A2": 2004, "A5": 1930, "A0": None}
    # the builder's gaps for event S9:uq with star first year 2010: A1 -> 10, A2 -> 6 (agree with pf)
    triples = [("A1", "S9:uq", 10.0), ("A2", "S9:uq", 6.0)]
    out = rp.explain_direct([("A5", "S9:uq")], triples, pf, guard_max=60, stars={"S9"})
    assert out[("A5", "S9:uq")] == {"how": "direct", "gap": 80.0}
    # a disagreeing anchor voids the event
    out = rp.explain_direct([("A5", "S9:uq")], [("A1", "S9:uq", 10.0), ("A2", "S9:uq", 9.0)], pf,
                            guard_max=60, stars={"S9"})
    assert out[("A5", "S9:uq")]["how"] == "void_control"
    # one anchor is not a control
    out = rp.explain_direct([("A5", "S9:uq")], triples[:1], pf, guard_max=60, stars={"S9"})
    assert out[("A5", "S9:uq")]["how"] == "void_control"
    # a star person carries supplement works the edge table lacks -> never derived directly
    out = rp.explain_direct([("A5", "S9:uq")], triples, pf, guard_max=60, stars={"S9", "A5"})
    assert out[("A5", "S9:uq")]["how"] == "void_star"


# ---- the October acceptance rules, ORDER_ONLY ------------------------------------------------------

def test_csv_order_only_is_accepted_and_a_changed_row_is_not(tmp_path):
    a, b, c = tmp_path / "a.csv", tmp_path / "b.csv", tmp_path / "c.csv"
    a.write_bytes(b"pid,event_id,channel\nP1,E1,network\nP2,E1,both\r\n")
    b.write_bytes(b"pid,event_id,channel\nP2,E1,both\r\nP1,E1,network\n")
    c.write_bytes(b"pid,event_id,channel\nP2,E1,both\r\nP1,E1,dept_only\n")
    assert rp.csv_status(a, a) == "BYTE_EQUAL"
    assert rp.csv_status(b, a) == "ORDER_ONLY"
    assert rp.csv_status(c, a) == "NOT_EQUAL"
    d = tmp_path / "d.csv"
    d.write_bytes(b"pid,channel,event_id\nP2,both,E1\r\nP1,network,E1\n")
    assert rp.csv_status(d, a) == "NOT_EQUAL"            # a header change is never order-only


# ---- the summary and the write boundary --------------------------------------------------------

def test_summary_has_ids_and_counts_only(toy, monkeypatch):
    s, _drv, _seen = _prove(toy, monkeypatch, premise_ok=False,
                            cmp_by_label={"cut": False, "wiring": True}, roster_ok=False)
    text = (toy["out"] / rp.SUMMARY_NAME).read_text(encoding="utf-8")
    assert json.loads(text) == s
    assert "Jane" not in text and "Example" not in text
    assert str(toy["tmp"]) not in text                    # no paths either: labels and basenames only
    rp.check_ids_counts(s)                                 # the writer's own validator passes
    for bad in ({"x": "Jane Q. Example"}, {"x": ["A1", "Ana María"]}, {"x": {"y": "/work/out/a b"}},
                {"Jane Doe": 1}):
        with pytest.raises(ValueError):
            rp.check_ids_counts(bad)


def test_refuses_to_write_outside_the_stage_out(toy, tmp_path):
    out = toy["out"]
    with pytest.raises(PermissionError):
        rp.write_json(tmp_path / "elsewhere.json", {"a": 1}, out=out)
    with pytest.raises(PermissionError):
        rp.write_json(out / ".." / "escape.json", {"a": 1}, out=out)
    link = out / "link_out"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(PermissionError):
        rp.write_json(link / "via_link.json", {"a": 1}, out=out)
    assert not (tmp_path / "elsewhere.json").exists() and not (tmp_path / "escape.json").exists()
    assert not (tmp_path / "via_link.json").exists()
    rp.write_json(out / "sub" / "ok.json", {"a": 1}, out=out)
    assert json.loads((out / "sub" / "ok.json").read_text(encoding="utf-8")) == {"a": 1}
    # an out inside either input table (or the reverse) is refused before anything is written
    with pytest.raises(ValueError):
        rp.cut(toy["r0705"], toy["r11"], toy["r11"] / "nested_out", toy["con"])
    with pytest.raises(ValueError):
        rp.cut(toy["r0705"], toy["r11"], toy["r0705"].parent, toy["con"])
    assert not (toy["r11"] / "nested_out").exists()


# ---- the driver call (S10 steps 2 and 4): one chemmath_m.py --mode b0 --edge-proof argv -------------------------

def _fake_shadow(monkeypatch, seen):
    def ensure_shadow(real_root, out_dir, target, base_paths):
        out_dir = pathlib.Path(out_dir)
        out_dir.mkdir(parents=True)
        pf = out_dir / "paths_edge_table.yaml"
        pf.write_text("ssd_root: x\n", encoding="utf-8")
        seen.append(("shadow", pathlib.Path(target).name))
        return {"swapped_name": "u1_edges_full_2026-07-05", "target_realpath": str(target)}, pf
    monkeypatch.setattr(rp.et, "ensure_shadow", ensure_shadow)


def _fake_run(monkeypatch, seen, *, report_target=None, rc=0):
    """subprocess.run stand-in: records argv/env and leaves the name-free report chemmath_m.py --edge-proof
    writes (its edge_proof.target = the table behind the 07-05 name)."""
    class Proc:
        returncode = rc

    def run(argv, cwd, env, stdout, stderr):
        seen.append(("run", list(argv), dict(env)))
        out = pathlib.Path(argv[argv.index("--out") + 1])
        tgt = report_target or env["_TOY_TARGET"]
        (out / "report_chemmath_m.json").write_text(json.dumps(
            {"mode": "b0", "result": "OK", "edge_proof": {"target": tgt}}), encoding="utf-8")
        return Proc()
    monkeypatch.setattr(rp.subprocess, "run", run)


def test_driver_runs_chemmath_m_b0_edge_proof_with_one_fields_string_and_the_october_root(tmp_path, monkeypatch):
    """Bugs found by reading (2026-10-16): the driver passed `--fields chemistry math_stats` (chemmath_m takes ONE
    comma-separated string: argparse rejects the second word), no --october-ref (mode b0 requires it), and plain
    b0 refuses the edge-table shadow (EDGE_ENV) and stops on any October difference (B0_NOT_OCTOBER) before its
    products are frozen. The argv now parses in chemmath_m's own parser as b0 + --edge-proof with the October
    root, and the env carries the shadow paths file."""
    import chemmath_m as cm                                                 # noqa: PLC0415
    seen: list = []
    _fake_shadow(monkeypatch, seen)
    _fake_run(monkeypatch, seen)
    monkeypatch.delenv("SAR_SSD_ROOT", raising=False)
    oct_root = tmp_path / "oct_root"
    drv = rp.make_driver(repo=REPO, py="python3", config=REPO / "config" / "r1" / "B0.json", fields=FIELDS,
                         real_ssd_root=tmp_path / "real", base_paths=tmp_path / "paths.yaml", october_ref=oct_root,
                         env={"_TOY_TARGET": "u1_cut"})
    out = tmp_path / "out"
    out.mkdir()
    rec = drv("cut", tmp_path / "cut" / "u1_cut", out)
    (_s, (_r, argv, env)) = seen
    assert argv[1].endswith("pipeline/aws/r1/chemmath_m.py")
    a = cm.parse(argv[2:])
    assert (a.mode, a.edge_proof, a.fields) == ("b0", True, "chemistry,math_stats")
    assert pathlib.Path(a.october_ref) == oct_root and pathlib.Path(a.config).name == "B0.json"
    assert pathlib.Path(a.out) == out / "cut" / "stage_out"
    assert env["SAR_PATHS_CONFIG"].endswith("paths_edge_table.yaml")
    assert rec["rc"] == 0 and rec["edge_target"] == "u1_cut"
    # a driver whose edge proof ran on another table than the one asked for is a STOP (the wiring control)
    seen.clear()
    _fake_run(monkeypatch, seen, report_target="u1_full_11school_2026-07-16")
    with pytest.raises(rp.ReverseProofStop, match="u1_full_11school_2026-07-16"):
        drv("wiring", tmp_path / "wiring" / "u1_0705_copy", out)


def test_a_failed_driver_run_carries_its_stop_code_detail_and_the_log_tail(tmp_path, monkeypatch):
    """t-big-04: 'driver run cut failed rc=3; see .../driver.log' - and driver.log stayed on the instance. The
    ReverseProofStop (the junit failure text) now carries the driver's STOP code, ids and detail and the last
    DRIVER_LOG_TAIL lines of driver.log; its run record (rc, stop_code, stop_ids) rides on the exception."""
    seen: list = []
    _fake_shadow(monkeypatch, seen)
    monkeypatch.delenv("SAR_SSD_ROOT", raising=False)

    class Proc:
        returncode = 3

    def run(argv, cwd, env, stdout, stderr):
        stdout.write("".join(f"line-{i:03d}\n" for i in range(80)).encode())
        out = pathlib.Path(argv[argv.index("--out") + 1])
        (out / "RESULT.txt").write_text("STOP PRODLIB_EVENTS\n", encoding="utf-8")
        (out / "stop_report_chemmath_m.json").write_text(json.dumps(
            {"result": "STOP", "code": "PRODLIB_EVENTS", "mode": "b0", "ids": ["chemistry"], "n_ids": 1,
             "pairs": []}), encoding="utf-8")
        (out / "chemmath_m_run_report.json").write_text(json.dumps(
            {"stop": {"code": "PRODLIB_EVENTS", "ids": ["chemistry"],
                      "detail": "prodlib read 5 events, the table holds 6"}}), encoding="utf-8")
        return Proc()
    monkeypatch.setattr(rp.subprocess, "run", run)
    drv = rp.make_driver(repo=REPO, py="python3", config=REPO / "config" / "r1" / "B0.json", fields=FIELDS,
                         real_ssd_root=tmp_path / "real", base_paths=tmp_path / "paths.yaml",
                         october_ref=tmp_path / "oct_root")
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(rp.ReverseProofStop) as e:
        drv("cut", tmp_path / "cut" / "u1_cut", out)
    msg = str(e.value)
    assert "rc=3" in msg and "STOP PRODLIB_EVENTS" in msg and "['chemistry']" in msg
    assert "prodlib read 5 events, the table holds 6" in msg
    assert f"last {rp.DRIVER_LOG_TAIL} lines of driver.log" in msg
    assert "line-079" in msg and f"line-{80 - rp.DRIVER_LOG_TAIL:03d}" in msg
    assert f"line-{80 - rp.DRIVER_LOG_TAIL - 1:03d}" not in msg
    run = e.value.run
    assert (run["rc"], run["stop_code"], run["stop_ids"], run["target_name"]) == (3, "PRODLIB_EVENTS", ["chemistry"],
                                                                                   "u1_cut")
    assert "stage_out" not in run
    rec = json.loads((out / "cut" / "run.json").read_text(encoding="utf-8"))
    assert rec["result"] == "STOP PRODLIB_EVENTS" and rec["stop_detail"].startswith("prodlib read 5")
    # a driver that died without writing anything still names that in the message
    monkeypatch.setattr(rp.subprocess, "run", lambda argv, cwd, env, stdout, stderr: Proc())
    with pytest.raises(rp.ReverseProofStop, match="no RESULT.txt") as e:
        drv("wiring", tmp_path / "wiring" / "u1_0705_copy", out)
    assert e.value.run["stop_code"] is None


def test_october_root_is_the_root_above_data_cal2026_10(tmp_path):
    """chemmath_m.py --october-ref takes the root holding data/cal2026-10/frames_<field>/ (in place: the repo root);
    the proof's own ref dir is that root's data/cal2026-10 (the paths key `cal`)."""
    assert rp.october_root(REPO / "data" / "cal2026-10") == REPO
    assert rp.october_root(tmp_path / "x" / "data" / "cal2026-10") == tmp_path / "x"
    with pytest.raises(ValueError, match="cal2026-10"):
        rp.october_root(tmp_path / "frames_chemistry")


def test_prove_from_config_hands_the_driver_the_october_root(tmp_path, monkeypatch):
    import analysis.lib.paths as lp                                         # noqa: PLC0415
    monkeypatch.setattr(lp, "config_file", lambda: tmp_path / "paths.yaml")
    monkeypatch.setattr(lp, "load_paths", lambda base=None: {
        "ssd_root": tmp_path / "ssd" / "openalex_pipeline", "cal": tmp_path / "root" / "data" / "cal2026-10",
        "legacy_thesis": tmp_path / "legacy"})
    got: dict = {}

    def fake_make_driver(**kw):
        got["driver"] = kw
        return "DRV"

    def fake_prove(r0705, r11, out, ref, **kw):
        got["prove"] = (ref, kw)
        return {"ok": True}
    monkeypatch.setattr(rp, "make_driver", fake_make_driver)
    monkeypatch.setattr(rp, "prove", fake_prove)
    rp.prove_from_config(tmp_path / "out")
    assert got["driver"]["october_ref"] == tmp_path / "root"
    assert tuple(got["driver"]["fields"]) == FIELDS
    assert got["prove"][0] == tmp_path / "root" / "data" / "cal2026-10"
    assert got["prove"][1]["driver"] == "DRV"


def test_cli_runs_only_on_an_r1_host(monkeypatch, tmp_path):
    monkeypatch.delenv("SAR_HOST", raising=False)
    with pytest.raises(SystemExit) as e:
        rp.main(["prove", "--out", str(tmp_path / "o"), "--ref", str(tmp_path)])
    assert "R1 rule" in str(e.value)
