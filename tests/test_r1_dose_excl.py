# -*- coding: utf-8 -*-
"""R1 F13 (W1-DOSEECON): pipeline/aws/r1/r1_dose_excl.py on toy tables.

Every table is written in tmp_path (pyarrow parquet for the u1 edges / works / U2 person map, JSONL
for the supplements and the API patch, a CSV pre-y frame); nothing reads the data disk, the legacy
tree or the October files. Expected values are computed here from explicit subfield count vectors
with the repository's own identity.dose.topic_cos (the clone's cosine), never from the module.
"""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
sys.path.insert(0, str(REPO / "pipeline" / "units" / "u0_foundation" / "src"))
import r1_dose_excl as D            # noqa: E402
from identity.dose import topic_cos  # noqa: E402

COLS = ["incumbent_person_id", "year", "star_person_id", "event_id", "treated", "post",
        "dose_coupling_baseline", "dose_topic", "dose_low_confidence", "age_gap", "fwci_frac",
        "pub_count", "fwci_frac_ex_star", "pub_count_ex_star", "fwci_mean", "fwci_mean_ex_star", "channel"]
X, Y, Z = "2001", "2002", "2003"


def sha(p) -> str:
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def cos(a: dict, b: dict) -> float:
    return topic_cos(a, b)


def clip_delta(stored: float, fixed: float, current: float) -> str:
    return repr(float(min(1.0, max(0.0, stored + (fixed - current)))))


class World:
    """Toy inputs: edges (author, work, edge year), works (work, subfield, works-table year), person
    map (author -> person), supplements, API patch, the provenance table and an 11-row-per-relation
    pre-y frame. `cfg()` is the union config the module reads (with explicit PMAP/U1E/U1W)."""

    def __init__(self, tmp: pathlib.Path):
        self.tmp = tmp
        self.edges: list[tuple[str, str, int | None]] = []
        self.works: dict[str, tuple[str | None, int | None]] = {}
        self.pmap: list[tuple[str, str]] = []
        self.sup11: list[dict] = []
        self.supfn: list[dict] = []
        self.patch_a: list[dict] = []
        self.patch_b: list[dict] = []
        self.new_events: list[tuple[str, int]] = []
        self.rels: list[tuple[str, str, str, str]] = []     # (pid, event_id, channel, dose cell)

    def edge(self, author, work, yr, sf=None, works_year=None):
        self.edges.append((author, work, yr))
        if work not in self.works or sf is not None:
            self.works[work] = (sf, works_year if works_year is not None else yr)

    def rel(self, pid, event_id, channel, dose):
        self.rels.append((pid, event_id, channel, dose))

    def cfg(self) -> dict:
        t = self.tmp
        pq.write_table(pa.table({"author_id": [e[0] for e in self.edges],
                                 "work_id": [e[1] for e in self.edges],
                                 "publication_year": pa.array([e[2] for e in self.edges], pa.int64())}),
                       t / "edges.parquet")
        ws = sorted(self.works)
        pq.write_table(pa.table({"work_id": ws, "subfield_id": [self.works[w][0] for w in ws],
                                 "publication_year": pa.array([self.works[w][1] for w in ws], pa.int64())}),
                       t / "works.parquet")
        pm = self.pmap or [("A0", "P_A0")]
        pq.write_table(pa.table({"author_id": [p[0] for p in pm], "person_id": [p[1] for p in pm]}),
                       t / "pmap.parquet")
        for name, rows in (("sup11", self.sup11), ("supfn", self.supfn), ("patch_a", self.patch_a),
                           ("patch_b", self.patch_b)):
            (t / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        with open(t / "prov.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["author_id", "name", "school", "arrival"])
            for a, y in self.new_events:
                w.writerow([a, "x", "uni", y])
        return {"SUP11": str(t / "sup11.jsonl"), "SUP_FNFIX": str(t / "supfn.jsonl"),
                "PATCH_A": str(t / "patch_a.jsonl"), "PATCH_B": str(t / "patch_b.jsonl"),
                "NEW_EVENTS": str(t / "prov.csv"), "PMAP": [str(t / "pmap.parquet")],
                "U1E": [str(t / "edges.parquet")], "U1W": [str(t / "works.parquet")]}

    def frame(self) -> pathlib.Path:
        p = self.tmp / "pre_y.csv"
        lines = [",".join(COLS)]
        for pid, ev, ch, dose in self.rels:
            star, t = ev.split(":")[0], int(ev.split(":")[1])
            for y in range(t - 5, t + 6):
                post = "true" if y >= t else "false"
                lines.append(f"P_{pid},{y},P_{star},{ev},true,{post},,{dose},false,8.0,,,,,,,{ch}")
        p.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
        return p


def run(w: World, excludes=frozenset(), addbacks=frozenset(), mode="delta"):
    pre = w.frame()
    cfg = w.cfg()
    out = w.tmp / "out" / "pre_y_fixed.csv"
    rep = D.apply_dose_exclusions(pre, out, union_cfg=cfg, excludes=frozenset(excludes),
                                  addbacks=frozenset(addbacks), mode=mode)
    return pre, out, rep


def dose_cells(p: pathlib.Path, pid: str, ev: str) -> list[str]:
    with open(p, newline="", encoding="utf-8") as f:
        return [r["dose_topic"] for r in csv.DictReader(f)
                if r["incumbent_person_id"] == f"P_{pid}" and r["event_id"] == ev]


def base_world(tmp_path) -> World:
    """Star A100 (event A100:2010) with W1 2008 X, W2 2005 Y, W3 2007 Y; colleague A201 with
    W10 2006 X, W11 2004 Y. current = cos({X:1,Y:2},{X:1,Y:1})."""
    w = World(tmp_path)
    w.edge("A100", "W1", 2008, X)
    w.edge("A100", "W2", 2005, Y)
    w.edge("A100", "W3", 2007, Y)
    w.edge("A201", "W10", 2006, X)
    w.edge("A201", "W11", 2004, Y)
    return w


# ---------------------------------------------------------------------------------------------

def test_excluded_prearrival_work_moves_dose_by_delta(tmp_path):
    w = base_world(tmp_path)
    w.rel("A201", "A100:2010", "network", "0.9")
    pre, out, rep = run(w, {("A100", "W1")})
    cur = cos({X: 1.0, Y: 1.0}, {X: 1.0, Y: 2.0})
    fix = cos({X: 1.0, Y: 1.0}, {Y: 2.0})
    assert dose_cells(out, "A201", "A100:2010") == [clip_delta(0.9, fix, cur)] * 11
    assert rep["mode"] == "delta" and rep["path"] == str(out) and rep["written"] is True
    assert rep["relations"]["total"] == 1 and rep["relations"]["affected"] == 1
    assert rep["relations"]["changed"] == 1 and rep["rows_changed"] == 11
    assert rep["sides"]["delta_nonzero"]["star_only"] == 1
    assert rep["delta_calls"]["n_nonzero"] == 1
    assert rep["delta_calls"]["max_abs"] == pytest.approx(abs(fix - cur), abs=1e-15)
    # the July gap (current - stored) is reported, never applied
    assert rep["delta_rule"]["max_abs"] == pytest.approx(abs(cur - 0.9), abs=1e-15)
    assert rep["excluded_left_in_fixed"] == 0


def test_excluded_postarrival_work_changes_nothing(tmp_path):
    w = base_world(tmp_path)
    w.edge("A100", "W4", 2010, Z)              # edge year = T
    w.rel("A201", "A100:2010", "network", "0.9")
    pre, out, rep = run(w, {("A100", "W4")})
    assert sha(out) == sha(pre)
    assert rep["relations"]["affected"] == 0 and rep["rows_changed"] == 0


def test_call_under_an_alias_id_applies_to_the_person(tmp_path):
    w = base_world(tmp_path)
    w.pmap = [("A100", "P_A100"), ("A100b", "P_A100")]
    w.edge("A100b", "W1", 2008, X)             # the same work again under the alias: multiplicity 2
    w.rel("A201", "A100:2010", "network", "0.5")
    pre, out, rep = run(w, {("A100b", "W1")})
    cur = cos({X: 1.0, Y: 1.0}, {X: 2.0, Y: 2.0})
    fix = cos({X: 1.0, Y: 1.0}, {Y: 2.0})     # every alias edge of W1 goes
    assert dose_cells(out, "A201", "A100:2010") == [clip_delta(0.5, fix, cur)] * 11
    assert rep["excluded_left_in_fixed"] == 0


def test_colleague_side_call_applies(tmp_path):
    w = base_world(tmp_path)
    w.rel("A201", "A100:2010", "network", "0.9")
    pre, out, rep = run(w, {("A201", "W10")})
    cur = cos({X: 1.0, Y: 1.0}, {X: 1.0, Y: 2.0})
    fix = cos({Y: 1.0}, {X: 1.0, Y: 2.0})
    assert dose_cells(out, "A201", "A100:2010") == [clip_delta(0.9, fix, cur)] * 11
    assert rep["sides"]["delta_nonzero"]["colleague_only"] == 1
    assert rep["sides"]["delta_nonzero"]["star_only"] == 0


def test_zero_dose_stays_zero_and_delta_clips(tmp_path):
    w = World(tmp_path)
    # event 1 (A100:2010): star {X:1, Y:1}
    w.edge("A100", "W1", 2008, X)
    w.edge("A100", "W2", 2006, Y)
    # zero: colleague A301 {Z:2}, one Z work excluded -> current 0, fixed 0, '0.0' untouched
    w.edge("A301", "W30", 2005, Z)
    w.edge("A301", "W31", 2006, Z)
    w.rel("A301", "A100:2010", "network", "0.0")
    # clip to 0: colleague A302 {X:1, Z:1}; X excluded -> fixed 0; stored .02 -> 0.0
    w.edge("A302", "W40", 2005, X)
    w.edge("A302", "W41", 2006, Z)
    w.rel("A302", "A100:2010", "network", "0.02")
    # event 2 (A400:2012): gap kept; star {X:1, Y:2}, colleague A303 {X:1, Y:1}; star's X excluded
    w.edge("A400", "W50", 2008, X)
    w.edge("A400", "W51", 2009, Y)
    w.edge("A400", "W52", 2010, Y)
    w.edge("A303", "W60", 2007, X)
    w.edge("A303", "W61", 2003, Y)
    w.rel("A303", "A400:2012", "network", "0.3")
    pre, out, rep = run(w, {("A301", "W30"), ("A302", "W40"), ("A400", "W50")})
    assert dose_cells(out, "A301", "A100:2010") == ["0.0"] * 11
    assert dose_cells(out, "A302", "A100:2010") == ["0.0"] * 11
    cur = cos({X: 1.0, Y: 1.0}, {X: 1.0, Y: 2.0})
    fix = cos({X: 1.0, Y: 1.0}, {Y: 2.0})
    got = dose_cells(out, "A303", "A400:2012")
    assert got == [clip_delta(0.3, fix, cur)] * 11 and 0.0 < float(got[0]) < 0.3
    assert rep["relations"]["stored_positive_to_zero"] == 1
    assert rep["relations"]["current_positive_to_fixed_zero"] == 1
    # the zero relation is affected (a counted row left) but no cell moved
    assert rep["relations"]["affected"] == 3 and rep["relations"]["changed"] == 2


def test_untouched_lines_byte_identical_and_dose_rows_proof_closes(tmp_path):
    w = base_world(tmp_path)
    w.edge("A202", "W20", 2003, Y)
    w.edge("A700", "W70", 2001, Y)
    w.edge("A203", "W80", 2002, Y)
    w.rel("A201", "A100:2010", "network", "0.9")
    w.rel("A202", "A100:2010", "both", "0.95")
    w.rel("A203", "A700:2015", "network", "0.4")      # another event: untouched
    pre, out, rep = run(w, {("A100", "W1")})
    before = pre.read_bytes().split(b"\n")
    after = out.read_bytes().split(b"\n")
    assert len(before) == len(after) and before[0] == after[0]
    dose_i = COLS.index("dose_topic")
    for b, a in zip(before[1:], after[1:]):
        if b"A700:2015" in b:
            assert a == b
        elif a != b:
            bc, ac = b.split(b","), a.split(b",")
            assert [i for i in range(len(bc)) if bc[i] != ac[i]] == [dose_i]
    affected = {tuple(x) for x in rep["affected"]}
    assert affected == {("P_A201", "A100:2010"), ("P_A202", "A100:2010")}
    proof = D.dose_rows_proof(pre, out, affected)
    assert proof["closed"] is True and proof["rewritten_rows"] == 22 and proof["identical"] == 11
    # the proof opens on any other difference
    bad = tmp_path / "bad.csv"
    bad.write_bytes(out.read_bytes().replace(b",0.4,false,8.0", b",0.4,false,9.0", 1))
    assert D.dose_rows_proof(pre, bad, affected)["closed"] is False
    # and on a dose change outside the affected relations
    assert D.dose_rows_proof(pre, out, {("P_A201", "A100:2010")})["closed"] is False


def test_year_comes_from_the_edge_table_not_the_calls_file(tmp_path):
    w = base_world(tmp_path)
    w.edge("A100", "W5", 2010, Z, works_year=2001)   # edge year T; the works row (and a call) say 2001
    w.rel("A201", "A100:2010", "network", "0.9")
    pre, out, rep = run(w, {("A100", "W5")})
    assert sha(out) == sha(pre)


def test_na_dose_stays_na_and_missing_side_is_counted(tmp_path):
    w = base_world(tmp_path)
    w.rel("A201", "A100:2010", "network", "")         # stored NA
    w.rel("A999", "A100:2010", "network", "0.25")     # colleague without any vector
    pre, out, rep = run(w, {("A100", "W1")})
    assert dose_cells(out, "A201", "A100:2010") == [""] * 11
    assert dose_cells(out, "A999", "A100:2010") == ["0.25"] * 11
    assert rep["relations"]["affected_uncomputable"] == 1
    assert rep["relations"]["affected_stored_na"] == 1
    assert sha(out) == sha(pre)


def test_sources_follow_the_clone_precedence(tmp_path):
    w = World(tmp_path)
    # A400 has pedges: its supplement and API rows are ignored
    w.edge("A400", "W1", 2008, X)
    w.edge("A400", "W2", 2007, Y)
    w.sup11.append({"work_id": "W90", "publication_year": 2005, "seed_author": "A400"})
    w.patch_a.append({"author_id": "A400", "work_id": "W91", "publication_year": 2005, "subfield_id": Z})
    w.patch_b.append({"work_id": "W90", "publication_year": 2005, "subfield_id": Z})
    # A500 has no pedges: SUP11 + SUP_FNFIX rows (subfield from PATCH_B, else the u1 works row) + API rows
    w.sup11.append({"work_id": "W92", "publication_year": 2006, "seed_author": "A500"})
    w.supfn.append({"work_id": "W93", "publication_year": 2007, "seed_author": "A500"})
    w.supfn.append({"work_id": "https://openalex.org/W94", "publication_year": 2004, "seed_author": "A500"})
    w.patch_b.append({"work_id": "W92", "publication_year": 2006, "subfield_id": X})
    w.works["W93"] = (Y, 2007)                         # in u1 works only (no edge)
    w.patch_b.append({"work_id": "https://openalex.org/W94", "publication_year": 2004, "subfield_id": Z})
    w.patch_a.append({"author_id": "A500", "work_id": "W95", "publication_year": 2003, "subfield_id": Y})
    # A600: colleague of both events with pedges
    w.edge("A600", "W60", 2004, X)
    w.edge("A600", "W61", 2005, Y)
    w.edge("A600", "W62", 2006, Z)
    col = {X: 1.0, Y: 1.0, Z: 1.0}
    cur400 = cos(col, {X: 1.0, Y: 1.0})
    cur500 = cos(col, {X: 1.0, Y: 2.0, Z: 1.0})
    w.rel("A600", "A400:2010", "dept_only", repr(cur400))   # self-check: stored = the clone's rule
    w.rel("A600", "A500:2010", "dept_only", repr(cur500))
    # the excluded supplement work (URL form in the supplement) leaves A500's vector
    pre, out, rep = run(w, {("A500", "W94"), ("A400", "W91")})
    assert rep["self_check"]["mismatches"] == 0 and rep["self_check"]["relations"] == 2
    assert dose_cells(out, "A600", "A400:2010") == [repr(cur400)] * 11        # API row was never used
    fix500 = cos(col, {X: 1.0, Y: 2.0})
    assert dose_cells(out, "A600", "A500:2010") == [clip_delta(cur500, fix500, cur500)] * 11
    assert rep["sources"]["origin"] == {"pedges": 2, "sup_api": 1}


@pytest.mark.parametrize("case", ["dept_only", "prodlib"])
def test_self_check_stops_when_current_differs_from_stored_on_a_dept_only_or_prodlib_row(tmp_path, case):
    w = base_world(tmp_path)
    if case == "dept_only":
        w.rel("A201", "A100:2010", "dept_only", "0.5")
    else:
        w.new_events.append(("A100", 2010))
        w.rel("A201", "A100:2010", "network", "0.5")
    with pytest.raises(D.DoseRuleMismatch) as ei:
        run(w, {("A100", "W1")})
    assert ei.value.mismatches and ei.value.mismatches[0]["event_id"] == "A100:2010"
    assert not (tmp_path / "out" / "pre_y_fixed.csv").exists()


def test_self_check_passes_on_an_exact_dept_only_row(tmp_path):
    w = base_world(tmp_path)
    cur = cos({X: 1.0, Y: 1.0}, {X: 1.0, Y: 2.0})
    w.new_events.append(("A100", 2010))
    w.rel("A201", "A100:2010", "dept_only", repr(cur))
    pre, out, rep = run(w, {("A100", "W1")})
    sc = rep["self_check"]
    assert (sc["relations"], sc["mismatches"], sc["max_abs_diff"]) == (1, 0, 0.0)
    assert dose_cells(out, "A201", "A100:2010") == [clip_delta(cur, cos({X: 1.0, Y: 1.0}, {Y: 2.0}), cur)] * 11


def test_mode_off_is_a_no_op_and_writes_nothing(tmp_path):
    w = base_world(tmp_path)
    w.rel("A201", "A100:2010", "network", "0.9")
    pre, out, rep = run(w, {("A100", "W1")}, mode="off")
    assert rep["path"] == str(pre) and rep["written"] is False and rep["mode"] == "off"
    assert not out.exists() and not out.parent.exists()


def test_empty_excludes_give_a_byte_identical_file(tmp_path):
    w = base_world(tmp_path)
    w.rel("A201", "A100:2010", "network", "0.9")
    pre, out, rep = run(w, frozenset())
    assert sha(out) == sha(pre) and rep["path"] == str(out)


@pytest.mark.parametrize("mode", ["overwrite", None, "", "DELTA"])
def test_unsigned_mode_is_refused(tmp_path, mode):
    w = base_world(tmp_path)
    w.rel("A201", "A100:2010", "network", "0.9")
    with pytest.raises(ValueError):
        run(w, {("A100", "W1")}, mode=mode)
    with pytest.raises((ValueError, TypeError)):
        D.apply_dose_exclusions(w.frame(), tmp_path / "o.csv", union_cfg=w.cfg(),
                                excludes=frozenset(), addbacks=frozenset())


def test_rank_add_works_enter_only_when_absent(tmp_path):
    w = base_world(tmp_path)
    w.pmap = [("A100", "P_A100"), ("A100b", "P_A100")]
    w.edge("A100b", "W1", 2008, X)             # W1 already in A100's sources through the U2 alias
    w.edge("A999", "W9", 2007, Z)              # a split id the U2 map does not fold
    w.edge("A999", "W8", 2012, Z)              # after T-1: enters the sources, not the vector
    w.rel("A201", "A100:2010", "network", "0.6")
    pre, out, rep = run(w, frozenset(), {("A100", "W1"), ("A100", "W9"), ("A100", "W8")})
    cur = cos({X: 1.0, Y: 1.0}, {X: 2.0, Y: 2.0})
    fix = cos({X: 1.0, Y: 1.0}, {X: 2.0, Y: 2.0, Z: 1.0})
    assert dose_cells(out, "A201", "A100:2010") == [clip_delta(0.6, fix, cur)] * 11
    ab = rep["addbacks"]
    assert ab["entered"] == 2 and ab["already_present"] == 1 and ab["unresolved"] == 0
    assert rep["relations"]["affected"] == 1
    # an add-back of an excluded work never enters
    (tmp_path / "b").mkdir()
    w2 = base_world(tmp_path / "b")
    w2.edge("A999", "W9", 2007, Z)
    w2.rel("A201", "A100:2010", "network", "0.6")
    pre2, out2, rep2 = run(w2, {("A100", "W9")}, {("A100", "W9")})
    assert sha(out2) == sha(pre2) and rep2["addbacks"]["excluded"] == 1


def test_work_and_author_ids_are_normalised(tmp_path):
    w = base_world(tmp_path)
    w.rel("A201", "A100:2010", "network", "0.9")
    pre, out, rep = run(w, {("https://openalex.org/A100", "https://openalex.org/W1")})
    cur = cos({X: 1.0, Y: 1.0}, {X: 1.0, Y: 2.0})
    fix = cos({X: 1.0, Y: 1.0}, {Y: 2.0})
    assert dose_cells(out, "A201", "A100:2010") == [clip_delta(0.9, fix, cur)] * 11
    with pytest.raises(ValueError):
        run(w, {("not-an-author", "W1")})


def test_an_excluded_work_without_an_openalex_id_is_counted_and_cannot_move_a_dose(tmp_path):
    """The October calls hold one judged work with no OpenAlex record (a 1956 proceedings paper, kept
    by its title). No frame work can carry that id, so it changes nothing; it is counted, not refused."""
    w = base_world(tmp_path)
    w.rel("A201", "A100:2010", "network", "0.9")
    title = "1956 | Anticipation of Bottle-Cleaning Difficulties | Proc. Annual Meeting"
    pre, out, rep = run(w, {("A100", title)})
    assert sha(out) == sha(pre)
    assert rep["calls"]["pairs"] == 1 and rep["calls"]["non_openalex_pairs"] == 1
    pre, out, rep = run(w, {("A100", "W1"), ("A100", title)})
    cur = cos({X: 1.0, Y: 1.0}, {X: 1.0, Y: 2.0})
    fix = cos({X: 1.0, Y: 1.0}, {Y: 2.0})
    assert dose_cells(out, "A201", "A100:2010") == [clip_delta(0.9, fix, cur)] * 11
    assert rep["calls"]["pairs"] == 2 and rep["calls"]["ids"] == 1 and rep["calls"]["non_openalex_pairs"] == 1
    with pytest.raises(ValueError):
        run(w, set(), addbacks={("A100", title)})
