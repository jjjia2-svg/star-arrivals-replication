"""R1 F14 (unit W2-CHEMM): the chemistry / mathematics dose post-step pipeline/aws/r1/dose_chemmath.py.

Toy u1 edges / works parquets and a toy union frame in tmp_path (no real data). The expected doses are
computed by hand here with the same arithmetic identity.dose.topic_cos uses (sorted keys, fsum, sqrt),
then written in each row type's own text: prodlib's float32 for network / both rows, the union builder's
float64 for dept_only rows.

Toy world, t1 = 2009 for both events (arrival 2010):
  S1 (A100, event S1:anu): W7 2004 / W1 2005 subfield 1605, W2 2007 1606, W9 2012 1605 -> {1605:2, 1606:1}
  S2 (A110, event S2:uq):  W10 2004 / W11 2005 1605, W12 2007 1606                        -> {1605:2, 1606:1}
  N1 (A201) W3 2006 1605, W4 2008 1606; N2 (A401) W13 2006 1605; Z1 (A501) W14 2006 2604
  D1 (A301) W5 2006 1605, and its alias A302 (same person_map person) W6 2007 1606
  A109 = a split id of S1 (not folded by the person map): W20 2006 1606
Relations: (A201, S1:anu) network, (A301, S1:anu) dept_only, (A401, S1:anu) network,
(A501, S1:anu) both, (A301, S2:uq) network."""
from __future__ import annotations

import math
import pathlib
import struct
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import dose_chemmath as dc                                               # noqa: E402

OA = "https://openalex.org/"
SA, SB, SC = OA + "subfields/1605", OA + "subfields/1606", OA + "subfields/2604"
E1, E2 = "S1:anu", "S2:uq"
T1 = {E1: 2009, E2: 2009}
HEADER = ("incumbent_person_id,year,star_person_id,event_id,treated,post,dose_coupling_baseline,dose_topic,"
          "dose_low_confidence,age_gap,fwci_frac,pub_count,fwci_frac_ex_star,pub_count_ex_star,fwci_mean,"
          "fwci_mean_ex_star,channel")
EDGES = [  # (work, author, year)
    ("W7", "A100", 2004), ("W1", "A100", 2005), ("W2", "A100", 2007), ("W9", "A100", 2012),
    ("W10", "A110", 2004), ("W11", "A110", 2005), ("W12", "A110", 2007),
    ("W3", "A201", 2006), ("W4", "A201", 2008), ("W13", "A401", 2006), ("W14", "A501", 2006),
    ("W5", "A301", 2006), ("W6", "A302", 2007), ("W20", "A109", 2006)]
WORKS = {"W7": SA, "W1": SA, "W2": SB, "W9": SA, "W10": SA, "W11": SA, "W12": SB, "W3": SA, "W4": SB,
         "W13": SA, "W14": SC, "W5": SA, "W6": SB, "W20": SB}
YEAR = {w: y for w, _a, y in EDGES}


def cos(a: dict, b: dict) -> float:
    keys = sorted(set(a) & set(b))
    dot = math.fsum(float(a[k]) * float(b[k]) for k in keys)
    na = math.sqrt(math.fsum(float(a[k]) * float(a[k]) for k in sorted(a)))
    nb = math.sqrt(math.fsum(float(b[k]) * float(b[k]) for k in sorted(b)))
    return 0.0 if na <= 0.0 or nb <= 0.0 else dot / (na * nb)


def f32(x: float) -> str:
    return repr(struct.unpack("f", struct.pack("f", float(x)))[0])


def f64(x: float) -> str:
    return repr(float(x))


S1 = {"1605": 2.0, "1606": 1.0}
S2 = {"1605": 2.0, "1606": 1.0}
N1 = {"1605": 1.0, "1606": 1.0}
D1_UNION = {"1605": 1.0, "1606": 1.0}
D1_PROD = {"1605": 1.0}
N2 = {"1605": 1.0}
Z1 = {"2604": 1.0}
STORED = {("A201", E1): ("network", "A100", f32(cos(N1, S1))),
          ("A301", E1): ("dept_only", "A100", f64(cos(D1_UNION, S1))),
          ("A401", E1): ("network", "A100", f32(cos(N2, S1))),
          ("A501", E1): ("both", "A100", f32(cos(Z1, S1))),
          ("A301", E2): ("network", "A110", f32(cos(D1_PROD, S2)))}


def _parquet(p: pathlib.Path, cols: dict) -> None:
    import pyarrow as pa                                                 # noqa: PLC0415
    import pyarrow.parquet as pq                                         # noqa: PLC0415
    p.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(cols), p)


def _lines(pid, star, ev, dose, channel, arrival=2010) -> list[str]:
    out = []
    for y in range(arrival - 5, arrival + 6):
        post = "True" if y >= arrival else "False"
        if channel == "dept_only":           # the union builder's pandas rows
            out.append(f"{pid},{y},{star},{ev},True,{post},,{dose},False,3.0,0.0,0,0.0,0,,,dept_only")
        else:                                # prodlib rows: the 07-24 CRLF leftover sits before ',channel'
            out.append(f"{pid},{y},{star},{ev},True,{post},,{dose},False,3.0,0.0,0.0,0.0,0.0,,\r,{channel}")
    return out


def world(tmp: pathlib.Path, stored=None) -> tuple[pathlib.Path, "dc.RuleInputs"]:
    _parquet(tmp / "edges" / "p0" / "part.parquet",
             {"work_id": [w for w, _a, _y in EDGES], "author_id": [a for _w, a, _y in EDGES],
              "publication_year": [y for _w, _a, y in EDGES]})
    _parquet(tmp / "works" / "p0" / "part.parquet",
             {"work_id": list(WORKS), "publication_year": [YEAR[w] for w in WORKS],
              "subfield_id": [WORKS[w] for w in WORKS]})
    _parquet(tmp / "pmap.parquet", {"author_id": ["A301", "A302"], "person_id": ["P1", "P1"]})
    rows = []
    for (pid, ev), (ch, star, dose) in (stored or STORED).items():
        rows += _lines(pid, star, ev, dose, ch)
    frame = tmp / "union_frame.csv"
    frame.write_bytes(("\n".join([HEADER] + rows) + "\n").encode("utf-8"))
    ri = dc.RuleInputs(edges_glob=str(tmp / "edges" / "**" / "*.parquet"),
                       works_glob=str(tmp / "works" / "**" / "*.parquet"), supplement_jsonl=None,
                       person_map=str(tmp / "pmap.parquet"), union_stars=frozenset({"A100", "A110"}))
    return frame, ri


def doses(path: pathlib.Path) -> dict:
    """(pid, event) -> set of dose_topic texts."""
    out: dict = {}
    lines = path.read_bytes().decode("utf-8").split("\n")
    for ln in lines[1:]:
        if ln:
            c = ln.split(",")
            out.setdefault((c[0], c[3]), set()).add(c[7])
    return out


def run(tmp, excludes=(), addbacks=(), stored=None, **kw):
    frame, ri = world(tmp, stored)
    out = tmp / "fixed.csv"
    rep = dc.apply(frame, out, rule_inputs=ri, excludes=frozenset(excludes), addbacks=frozenset(addbacks),
                   t1_by_event=T1, **kw)
    return frame, out, rep


def test_excluded_prearrival_work_is_removed_from_the_star_vector(tmp_path):
    _f, out, rep = run(tmp_path, excludes={("A100", "W7")})        # 2004 <= t1 2009
    s1 = {"1605": 1.0, "1606": 1.0}
    d = doses(out)
    assert d[("A201", E1)] == {f32(cos(N1, s1))} != {STORED[("A201", E1)][2]}
    assert d[("A401", E1)] == {f32(cos(N2, s1))}
    assert d[("A301", E1)] == {f64(cos(D1_UNION, s1))}
    assert d[("A301", E2)] == {STORED[("A301", E2)][2]}             # the other star's event is untouched
    assert rep["relations"]["affected"] == 4
    assert rep["relations"]["affected_by_cause"]["dose_exclusion"] == 4
    assert ["A201", E1] in rep["affected"] and ["A301", E2] not in rep["affected"]


def test_excluded_postarrival_work_changes_nothing(tmp_path):
    frame, out, rep = run(tmp_path, excludes={("A100", "W9")})     # 2012 > t1 2009
    assert out.read_bytes() == frame.read_bytes()
    assert rep["relations"]["affected"] == 0 and rep["rows_changed"] == 0


def test_call_filed_under_an_alias_id_applies_to_the_person(tmp_path):
    _f, out, rep = run(tmp_path, excludes={("A302", "W6")})        # filed under D1's alias id
    d = doses(out)
    assert d[("A301", E1)] == {f64(cos({"1605": 1.0}, S1))}         # union rule: the person loses W6
    assert d[("A301", E2)] == {STORED[("A301", E2)][2]}             # prodlib rule: W6 was never in it
    assert rep["changed"] == [["A301", E1]]


def test_call_on_the_colleague_side_is_applied(tmp_path):
    _f, out, rep = run(tmp_path, excludes={("A201", "W4")})        # the incumbent's own 2008 work
    assert doses(out)[("A201", E1)] == {f32(cos({"1605": 1.0}, S1))}
    assert rep["changed"] == [["A201", E1]]
    assert rep["relations"]["affected_by_cause"]["dose_exclusion"] == 1


def test_zero_dose_stays_zero(tmp_path):
    _f, out, rep = run(tmp_path, excludes={("A501", "W14"), ("A100", "W1")})
    d = doses(out)
    assert d[("A501", E1)] == {f32(0.0)} == {STORED[("A501", E1)][2]}
    for pid, ev in rep["affected"]:
        if STORED[(pid, ev)][2] in (f32(0.0), f64(0.0)):
            assert d[(pid, ev)] <= {f32(0.0), f64(0.0)}
    assert rep["relations"]["n_to_zero"] == 0


def test_untouched_lines_are_byte_identical(tmp_path):
    frame, out, rep = run(tmp_path, excludes={("A201", "W4")})
    a = frame.read_bytes().split(b"\n")
    b = out.read_bytes().split(b"\n")
    assert len(a) == len(b) and a[0] == b[0]
    n_changed = 0
    for x, y in zip(a[1:], b[1:]):
        if x.startswith(b"A201,"):
            cx, cy = x.split(b","), y.split(b",")
            assert [c for i, c in enumerate(cx) if i != 7] == [c for i, c in enumerate(cy) if i != 7]
            assert cx[15] == cy[15] == b"\r"                       # the CRLF leftover is kept
            n_changed += cx[7] != cy[7]
        else:
            assert x == y
    assert n_changed == 11 == rep["rows_changed"]


def test_addback_split_id_work_enters_the_star_vector_once(tmp_path):
    # W20 sits under the split id A109; W2 is already S1's own work and must not count twice
    _f, out, rep = run(tmp_path, addbacks={("A100", "W20"), ("A100", "W2")})
    s1 = {"1605": 2.0, "1606": 2.0}
    d = doses(out)
    assert d[("A401", E1)] == {f32(cos(N2, s1))}
    assert d[("A401", E1)] != {f32(cos(N2, {"1605": 2.0, "1606": 3.0}))}
    assert d[("A301", E1)] == {f64(cos(D1_UNION, s1))}
    assert d[("A301", E2)] == {STORED[("A301", E2)][2]}
    assert rep["addbacks"]["entered"] >= 1 and rep["addbacks"]["already_present"] >= 1
    assert rep["relations"]["affected_by_cause"]["dose_addback"] == 4


def test_network_rows_use_the_prodlib_rule_and_dept_rows_the_union_rule(tmp_path):
    _f, out, _rep = run(tmp_path, excludes={("A100", "W7"), ("A110", "W10")})
    one_one = {"1605": 1.0, "1606": 1.0}
    d = doses(out)
    # the same person: its dept_only row counts the alias's W6, its network row does not
    assert d[("A301", E1)] == {f64(cos(D1_UNION, one_one))}
    assert d[("A301", E2)] == {f32(cos(D1_PROD, one_one))}
    assert cos(D1_UNION, one_one) != cos(D1_PROD, one_one)


def test_control_mismatch_stops(tmp_path):
    stored = dict(STORED)
    stored[("A201", E1)] = ("network", "A100", "0.5")
    with pytest.raises(dc.DoseChemmathStop) as e:
        run(tmp_path, excludes={("A201", "W4")}, stored=stored)
    assert e.value.code == "CONTROL_MISMATCH"
    assert ("A201", E1) in e.value.ids
    assert not (tmp_path / "fixed.csv").exists()


def test_accounting_closes_on_a_toy_frame(tmp_path):
    frame, out, rep = run(tmp_path, excludes={("A201", "W4")}, addbacks={("A100", "W20")})
    n = frame.read_bytes().count(b"\n") - 1
    assert rep["rows_in"] == rep["rows_out"] == n == len(STORED) * 11
    assert sum(rep["rows_changed_by_cause"].values()) == rep["rows_changed"]
    assert rep["rows_changed"] == 11 * rep["relations"]["changed"]
    assert rep["accounting_closed"] is True
    assert rep["relations"]["affected_by_cause"]["both"] == 1      # (A201, S1:anu): both sides moved
    assert rep["control"]["mismatches"] == 0


def test_switch_off_returns_the_input_bytes(tmp_path):
    frame, out, rep = run(tmp_path)
    assert out.read_bytes() == frame.read_bytes() and rep["identity_copy"] is True
    out.unlink()
    frame2, ri = world(tmp_path)
    rep = dc.apply(frame2, out, rule_inputs=ri, excludes=frozenset({("A100", "W7")}), addbacks=frozenset(),
                   t1_by_event=T1, mode="off")
    assert out.read_bytes() == frame2.read_bytes() and rep["mode"] == "off"


def test_an_excluded_work_without_an_openalex_id_is_counted_and_changes_nothing(tmp_path):
    """M delta review #1: the historical calls hold one judged work with no OpenAlex record (a 1956
    proceedings paper kept by its title). No frame work can carry that id: it is set aside and counted
    (calls.non_openalex_excludes), never applied or refused; add-backs stay strict."""
    title = "1956 | Anticipation of Bottle-Cleaning Difficulties | Proc. Annual Meeting"
    frame, out, rep = run(tmp_path, excludes={("A100", title)})
    assert out.read_bytes() == frame.read_bytes()
    assert rep["calls"]["non_openalex_excludes"] == 1
    _f2, out2, rep2 = run(tmp_path / "b", excludes={("A100", "W7"), ("A100", title)})
    _f3, out3, rep3 = run(tmp_path / "c", excludes={("A100", "W7")})
    assert out2.read_bytes() == out3.read_bytes() and rep2["calls"]["non_openalex_excludes"] == 1
    with pytest.raises(ValueError):
        run(tmp_path / "d", addbacks={("A100", title)})
