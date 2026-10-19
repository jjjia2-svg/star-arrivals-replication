# -*- coding: utf-8 -*-
"""R1 V3-NET (C5): pipeline/aws/r1/network_freeze.py on toy graphs (tmp parquet / jsonl, duckdb in a tmp file).

The rule under test: a degree-2 relation counts only if BOTH bridge edges (star-mid, mid-incumbent) have a
joint paper with year <= T-1. Degree 1 is already frozen at T-1 in prodlib; the new part is that prodlib's
deg-2 'unfrozen' arm leaves the network frame. The classifier replicates prodlib.build_subgraph (merged /
pedges) and prodlib.build_pairs:384-449; the toy cases are the ones the plan names (V3-NET tests 1-10).
Nothing here reads the data disk: every table is written under tmp_path.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import network_freeze as nf                          # noqa: E402

FRAME_COLS = ["incumbent_person_id", "year", "star_person_id", "event_id", "treated", "post",
              "dose_coupling_baseline", "dose_topic", "dose_low_confidence", "age_gap", "fwci_frac",
              "pub_count", "fwci_frac_ex_star", "pub_count_ex_star", "fwci_mean", "fwci_mean_ex_star"]


# ---- toy builders ------------------------------------------------------------------------------
def _parquet(path: pathlib.Path, cols: dict) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(cols), str(path))


def make_graph(root: pathlib.Path, works: dict, *, works_table: dict | None = None,
               supplement: list | None = None, person_map: dict | None = None) -> nf.Graph:
    """works: {work_id: (year, [author ids])} -> the snapshot edge table; the works table holds the same
    works with their year unless `works_table` ({work_id: year}) says otherwise."""
    e_w, e_a, e_y = [], [], []
    for w, (y, authors) in sorted(works.items()):
        for a in authors:
            e_w.append(w), e_a.append(a), e_y.append(y)
    _parquet(root / "edges" / "part-0.parquet", {"work_id": e_w, "author_id": e_a, "publication_year": e_y})
    wt = {w: y for w, (y, _a) in works.items()} if works_table is None else dict(works_table)
    ws = sorted(wt)
    _parquet(root / "works" / "part-0.parquet", {
        "work_id": ws, "publication_year": [wt[w] for w in ws], "work_type": ["article"] * len(ws),
        "subfield_id": ["2001"] * len(ws), "cited_by_count": [1] * len(ws), "is_paratext": [False] * len(ws)})
    sup = None
    if supplement is not None:
        sup = root / "supplement.jsonl"
        sup.write_text("".join(json.dumps(r) + "\n" for r in supplement), encoding="utf-8")
    pm = None
    if person_map is not None:
        pm = root / "person_map.parquet"
        aids = sorted(person_map)
        _parquet(pm, {"author_id": aids, "person_id": [person_map[a] for a in aids]})
    return nf.Graph(str(root / "edges" / "*.parquet"), str(root / "works" / "*.parquet"),
                    str(sup) if sup else None, str(pm) if pm else None)


def frame_lines(rels, *, bool_case="True") -> list[str]:
    """rels: [(incumbent, star, event_id, arrival)] -> prodlib-shaped lines, 11 window years each."""
    t, f = (("True", "False") if bool_case == "True" else ("true", "false"))
    out = []
    for inc, star, ev, arr in rels:
        for y in range(arr - 5, arr + 6):
            out.append(",".join([inc, str(y), star, ev, t, t if y >= arr else f, "", "0.5", f, "3.0",
                                 "1.25", "2.0", "1.0", "1.0", "0.6", "0.5"]))
    return out


def write_frame(path: pathlib.Path, rels, **kw) -> pathlib.Path:
    path.write_bytes(("\n".join([",".join(FRAME_COLS)] + frame_lines(rels, **kw)) + "\n").encode())
    return path


def run_classify(tmp_path, graph, events, incumbents):
    import duckdb
    con = duckdb.connect(str(tmp_path / f"cls_{len(list(tmp_path.iterdir()))}.duckdb"))
    try:
        return nf.classify(con, graph, events, incumbents)
    finally:
        con.close()


def ev(eid, star, arrival):
    return nf.Event(eid, star, arrival - 1)


# ---- 1 -------------------------------------------------------------------------------------------
def test_post_arrival_second_bridge_is_unfrozen_and_dropped(tmp_path):
    """S-M 2005, M-I only 2012, S arrives 2010 (t1 = 2009): I is deg2_unfrozen and its rows leave the
    frame; with an extra M-I paper in 2008 the relation is deg2_frozen and kept."""
    works = {"W1": (2005, ["S", "M"]), "W2": (2012, ["M", "I"]), "W0": (2004, ["S", "D"])}
    g = make_graph(tmp_path / "g1", works)
    e = ev("S:uni", "S", 2010)
    cls = run_classify(tmp_path, g, [e], {"S:uni": {"I", "D"}})
    assert cls == {("I", "S:uni"): "deg2_unfrozen", ("D", "S:uni"): "deg1"}

    fin = write_frame(tmp_path / "net.csv", [("D", "S", "S:uni", 2010), ("I", "S", "S:uni", 2010)])
    rep = nf.filter_frame(fin, cls, tmp_path / "net_frozen.csv")
    out = (tmp_path / "net_frozen.csv").read_bytes().decode().splitlines()
    assert [ln.split(",")[0] for ln in out[1:]] == ["D"] * 11
    assert rep["relations_by_class"] == {"deg1": 1, "deg2_frozen": 0, "deg2_unfrozen": 1, "none": 0}
    assert rep["removed_relations"] == [["I", "S:uni"]]

    works["W3"] = (2008, ["M", "I"])
    g2 = make_graph(tmp_path / "g1b", works)
    assert run_classify(tmp_path, g2, [e], {"S:uni": {"I"}}) == {("I", "S:uni"): "deg2_frozen"}


# ---- 2 -------------------------------------------------------------------------------------------
def test_post_arrival_first_bridge_is_unfrozen(tmp_path):
    """S-M 2011 (after arrival), M-I 2003: the star-side bridge is post-arrival -> unfrozen."""
    g = make_graph(tmp_path / "g", {"W1": (2011, ["S", "M"]), "W2": (2003, ["M", "I"])})
    assert run_classify(tmp_path, g, [ev("S:uni", "S", 2010)], {"S:uni": {"I"}}) == \
        {("I", "S:uni"): "deg2_unfrozen"}


# ---- 3 -------------------------------------------------------------------------------------------
def test_direct_prearrival_coauthor_is_deg1_never_deg2(tmp_path):
    """I wrote with S in 2004 AND sits behind a frozen bridge: deg1 (prodlib's banned set). J wrote with S
    only in 2012 but has a frozen bridge: deg2_frozen, not deg1 (degree 1 is frozen at T-1)."""
    g = make_graph(tmp_path / "g", {
        "W1": (2004, ["S", "I"]), "W2": (2003, ["S", "M"]), "W3": (2003, ["M", "I"]),
        "W4": (2012, ["S", "J"]), "W5": (2002, ["M", "J"])})
    cls = run_classify(tmp_path, g, [ev("S:uni", "S", 2010)], {"S:uni": {"I", "J"}})
    assert cls == {("I", "S:uni"): "deg1", ("J", "S:uni"): "deg2_frozen"}


# ---- 4 -------------------------------------------------------------------------------------------
def test_person_map_folds_two_author_ids_identity_does_not(tmp_path):
    """The econ graph folds author ids into U2 persons: A1 and A2 are one person P_X, and A2 wrote with
    the star before arrival, so P_X is deg1. Under the identity map (chem/maths) A1 alone has no path."""
    works = {"W1": (2004, ["AS", "A2"]), "W2": (2006, ["A1", "AZ"])}
    pm = {"AS": "P_S", "A1": "P_X", "A2": "P_X", "AZ": "P_Z"}
    g_pm = make_graph(tmp_path / "pm", works, person_map=pm)
    assert run_classify(tmp_path, g_pm, [ev("AS:2010", "P_S", 2010)], {"AS:2010": {"P_X"}}) == \
        {("P_X", "AS:2010"): "deg1"}
    g_id = make_graph(tmp_path / "id", works)
    assert run_classify(tmp_path, g_id, [ev("AS:uni", "AS", 2010)], {"AS:uni": {"A1"}}) == \
        {("A1", "AS:uni"): "none"}


# ---- 5 -------------------------------------------------------------------------------------------
def test_supplement_work_year_follows_prodlib(tmp_path):
    """A supplement-only edge takes its year from the snapshot works table when the work is there,
    else the jsonl year (prodlib.build_subgraph works_domain / merged)."""
    sup = [{"work_id": "W9", "authors": ["S", "I"], "publication_year": 2003, "type": "article"}]
    base = {"W0": (2001, ["Q", "R"])}
    g_tab = make_graph(tmp_path / "a", base, works_table={"W0": 2001, "W9": 2012}, supplement=sup)
    assert run_classify(tmp_path, g_tab, [ev("S:uni", "S", 2010)], {"S:uni": {"I"}}) == \
        {("I", "S:uni"): "none"}                       # works-table year 2012 > t1: not a frozen coauthor
    g_js = make_graph(tmp_path / "b", base, supplement=sup)
    assert run_classify(tmp_path, g_js, [ev("S:uni", "S", 2010)], {"S:uni": {"I"}}) == \
        {("I", "S:uni"): "deg1"}                       # jsonl year 2003


# ---- 6 -------------------------------------------------------------------------------------------
def test_matches_the_ported_degree2_closure_on_an_uncapped_toy(tmp_path):
    """Against the repo's ported U5 code (m4_dose.candidate_pairs.coauthor_pre_arrival +
    degree2_closure.close_degree2) with caps that cannot bind: the same class for every person."""
    sys.path.insert(0, str(REPO / "pipeline" / "units" / "u5_dose" / "src"))
    from m4_dose import candidate_pairs, degree2_closure

    works = {
        "W01": (2003, ["S", "M1"]), "W02": (2008, ["M1", "I1"]), "W03": (2012, ["M1", "I2"]),
        "W04": (2011, ["S", "M2"]), "W05": (2001, ["M2", "I3"]), "W06": (2005, ["S", "I4"]),
        "W07": (2004, ["M1", "I4"]), "W08": (2009, ["S", "M3"]), "W09": (2009, ["M3", "I5"]),
        "W10": (2015, ["M3", "I6"]), "W11": (2007, ["I7", "I8"]), "W12": (2006, ["M1", "M2", "I9"]),
        "W13": (2013, ["S", "I10"]), "W14": (2002, ["I10", "M3"]),
    }
    t1 = 2009
    pedges = [{"work_id": w, "person_id": a, "publication_year": y}
              for w, (y, authors) in works.items() for a in authors]
    deg1 = candidate_pairs.coauthor_pre_arrival(pedges, "S", t1)
    closed = degree2_closure.close_degree2(tmp_path / "u5.db", pedges, "S", t1, cap_k=10 ** 6,
                                           cap_per_star=10 ** 6, exclude_pids=deg1)
    persons = sorted({a for _y, au in works.values() for a in au} - {"S"})
    want = {}
    for p in persons:
        if p in deg1:
            want[p] = "deg1"
        else:
            hit = [r for r in closed if r["incumbent_person_id"] == p]
            want[p] = ("none" if not hit else "deg2_frozen" if hit[0]["degree2_bridge_frozen"]
                       else "deg2_unfrozen")
    g = make_graph(tmp_path / "g", works)
    got = run_classify(tmp_path, g, [nf.Event("S:uni", "S", t1)], {"S:uni": set(persons)})
    assert {p: got[(p, "S:uni")] for p in persons} == want
    assert set(want.values()) == {"deg1", "deg2_frozen", "deg2_unfrozen", "none"}   # the toy covers all


# ---- 7 -------------------------------------------------------------------------------------------
def test_filter_is_byte_preserving_and_counts(tmp_path):
    """Kept lines are the input lines byte for byte (a CRLF line and the July lowercase bools included),
    in order; the report's counts close; proof_allowances names the dropped relations."""
    rels = [("D", "S", "S:uni", 2010), ("I", "S", "S:uni", 2010), ("K", "T", "T:uni", 2012)]
    lines = frame_lines(rels[:2]) + frame_lines(rels[2:], bool_case="true")
    lines[3] = lines[3] + "\r"
    fin = tmp_path / "in.csv"
    fin.write_bytes(("\n".join([",".join(FRAME_COLS)] + lines) + "\n").encode())
    cls = {("D", "S:uni"): "deg1", ("I", "S:uni"): "deg2_unfrozen", ("K", "T:uni"): "deg2_frozen"}
    rep = nf.filter_frame(fin, cls, tmp_path / "out.csv")
    raw_in = fin.read_bytes().split(b"\n")
    want = [raw_in[0]] + [ln for ln in raw_in[1:-1] if not ln.startswith(b"I,")]
    assert (tmp_path / "out.csv").read_bytes() == b"\n".join(want) + b"\n"
    assert rep["input"]["rows"] == 33 and rep["output"]["rows"] == 22 and rep["rows_dropped"] == 11
    assert rep["rows_by_class"] == {"deg1": 11, "deg2_frozen": 11, "deg2_unfrozen": 11, "none": 0}
    assert sum(rep["rows_by_class"].values()) == rep["input"]["rows"]
    assert rep["per_event"]["S:uni"]["relations"] == {"deg1": 1, "deg2_frozen": 0, "deg2_unfrozen": 1, "none": 0}
    assert rep["per_event"]["S:uni"]["rows_dropped"] == 11 and rep["events_left_with_zero_rows"] == []
    al = nf.proof_allowances(rep)
    assert al == {"removed": {("I", "S:uni")}, "to_dept_candidates": {("I", "S:uni")}}

    # an event whose every relation drops is listed; an id_norm maps the frame's id form to the graph's
    rep2 = nf.filter_frame(fin, {("P_D", "S:uni"): "deg2_unfrozen", ("P_I", "S:uni"): "deg2_unfrozen",
                                 ("P_K", "T:uni"): "deg1"}, tmp_path / "out2.csv", id_norm=lambda p: "P_" + p)
    assert rep2["events_left_with_zero_rows"] == ["S:uni"] and rep2["output"]["rows"] == 11

    # the union output (channel column) is refused: the filter sits BEFORE the union rung
    chan = tmp_path / "union.csv"
    chan.write_bytes((",".join(FRAME_COLS + ["channel"]) + "\n" + lines[0] + ",network\n").encode())
    with pytest.raises(ValueError, match="before the union"):
        nf.filter_frame(chan, cls, tmp_path / "out3.csv")
    assert not (tmp_path / "out3.csv").exists()


# ---- 8 -------------------------------------------------------------------------------------------
def test_unexplained_relation_stops(tmp_path):
    """A frame relation with no path to the star -> NetworkFreezeStop listing ids only; nothing written."""
    g = make_graph(tmp_path / "g", {"W1": (2004, ["S", "D"]), "W2": (2004, ["X", "Y"])})
    fin = write_frame(tmp_path / "in.csv", [("D", "S", "S:uni", 2010), ("X", "S", "S:uni", 2010)])
    events = nf.events_from_frame(fin, None)
    cls = run_classify(tmp_path, g, events, nf.incumbents_from_frame(fin))
    assert cls[("X", "S:uni")] == "none"
    with pytest.raises(nf.NetworkFreezeStop) as ei:
        nf.filter_frame(fin, cls, tmp_path / "out.csv")
    assert ei.value.code == "UNEXPLAINED" and ei.value.ids == [("X", "S:uni")]
    assert "X" in str(ei.value) and not (tmp_path / "out.csv").exists()
    with pytest.raises(nf.NetworkFreezeStop) as ei2:                     # a relation classify never saw
        nf.filter_frame(fin, {("D", "S:uni"): "deg1"}, tmp_path / "out.csv")
    assert ei2.value.code == "UNCLASSIFIED" and ei2.value.ids == [("X", "S:uni")]


# ---- 9 -------------------------------------------------------------------------------------------
def test_t1_from_frame_must_match_the_event_table(tmp_path):
    """t1 = min(year | post true) - 1 from the frame; the event table's arrival - 1 must agree (the M
    table carries re-dates). Both table shapes are read; an event without post rows falls back to the
    table and is recorded."""
    fin = write_frame(tmp_path / "in.csv", [("D", "S", "S:uni", 2010), ("E", "T", "T:2012", 2012)])
    tab = tmp_path / "events_chem.csv"
    tab.write_text("field,school,author_id,display_name,arrival_corrected\n"
                   "chemistry,uni,S,x,2010\n", encoding="utf-8")
    tab2 = tmp_path / "events_econ.csv"
    tab2.write_text("event_id,star_id,arrival_year\nT:2012,T,2012\nS:uni,S,2010\n", encoding="utf-8")
    rec: dict = {}
    got = nf.events_from_frame(fin, tab2, record=rec)
    assert got == [nf.Event("S:uni", "S", 2009), nf.Event("T:2012", "T", 2011)]
    assert rec["crosschecked"] == 2 and rec["fallback_to_table"] == []

    with pytest.raises(nf.NetworkFreezeStop) as ei:                      # T:2012 is not in the chem table
        nf.events_from_frame(fin, tab)
    assert ei.value.code == "NOT_IN_TABLE" and ei.value.ids == ["T:2012"]

    tab2.write_text("event_id,star_id,arrival_year\nT:2012,T,2013\nS:uni,S,2010\n", encoding="utf-8")
    with pytest.raises(nf.NetworkFreezeStop) as ei:                      # a re-date the frame did not take
        nf.events_from_frame(fin, tab2)
    assert ei.value.code == "T1_MISMATCH" and ei.value.ids == ["T:2012"]

    pre = tmp_path / "pre_only.csv"                                      # no post rows for S:uni
    pre.write_bytes(("\n".join([",".join(FRAME_COLS)]
                               + [ln for ln in frame_lines([("D", "S", "S:uni", 2010)])
                                  if ln.split(",")[5] == "False"]) + "\n").encode())
    rec = {}
    assert nf.events_from_frame(pre, tab, record=rec) == [nf.Event("S:uni", "S", 2009)]
    assert rec["fallback_to_table"] == ["S:uni"]
    with pytest.raises(nf.NetworkFreezeStop) as ei:
        nf.events_from_frame(pre, None)
    assert ei.value.code == "NO_T1"


# ---- 10 ------------------------------------------------------------------------------------------
class _Cfg:
    def __init__(self, on):
        self.on, self.asked = on, []

    def is_on(self, name):
        self.asked.append(name)
        return self.on


def test_switch_off_writes_nothing(tmp_path):
    """Switch row 'network_freeze' off -> the hook returns the input path, writes nothing and never
    reads the graph; on -> the filtered frame (positive control). The October drivers never import it."""
    g = make_graph(tmp_path / "g", {"W1": (2004, ["S", "D"]), "W2": (2005, ["S", "M"]),
                                    "W3": (2012, ["M", "I"])})
    fin = write_frame(tmp_path / "in.csv", [("D", "S", "S:uni", 2010), ("I", "S", "S:uni", 2010)])
    out_dir = tmp_path / "stage"
    out_dir.mkdir()
    before = fin.read_bytes()
    off = _Cfg(False)
    bad_graph = nf.Graph(str(tmp_path / "missing" / "*.parquet"), str(tmp_path / "missing" / "*.parquet"))
    path, rep = nf.apply(off, fin, out_dir / "net_v3.csv", graph=bad_graph, event_table=None,
                         report_path=out_dir / "rep.json")
    assert (path, rep) == (fin, None) and off.asked == ["network_freeze"]
    assert list(out_dir.iterdir()) == [] and fin.read_bytes() == before

    on = _Cfg(True)
    path, rep = nf.apply(on, fin, out_dir / "net_v3.csv", graph=g, event_table=None,
                         report_path=out_dir / "rep.json")
    assert path == out_dir / "net_v3.csv" and rep["rows_dropped"] == 11
    assert json.loads((out_dir / "rep.json").read_text())["rows_dropped"] == 11
    assert sorted(p.name for p in out_dir.iterdir()) == ["net_v3.csv", "rep.json"]

    for src in ("pipeline/frames/cal2026-10/run_cal_frames_chemmath.py",
                "pipeline/frames/cal2026-10/econ920/run_econ920.py",
                "pipeline/frames/cal2026-10/econ920/econ920_lib.py",
                "pipeline/frames/cal2026-10/stage.py"):
        assert "network_freeze" not in (REPO / src).read_text(encoding="utf-8"), src
