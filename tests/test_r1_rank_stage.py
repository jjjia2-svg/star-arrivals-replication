# -*- coding: utf-8 -*-
"""pipeline/aws/r1/rank_r1.py - the gate that holds M's own-field ranking (the unedited RK6b code on
pinned inputs) to the pinned rk6b reference, the named asserts, and the rankrepro / rankdiff job specs."""
from __future__ import annotations

import csv
import json
import pathlib
import re
import shutil
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import r1kit                    # noqa: E402
import rank_r1 as rr            # noqa: E402

INPUTS = REPO / "data" / "cal2026-10r1" / "inputs"
ASSERTS = REPO / "config" / "r1" / "rank_named_asserts.json"
RANK_COLS = ["key", "author_id", "field", "arrival_true", "Y", "stock", "cell", "cell_n", "aage", "pct", "pass_p10", "note"]
FLIP_COLS = ["person_id", "key", "field", "status", "src", "arrival", "pct_A", "in_A", "pct_own", "cell_own", "cell_n_own",
             "aage_own", "stock_own", "in_own", "p05_own", "october_event", "october_p05", "flip", "flip_vs", "pct_C", "in_C"]


def _w(p, cols, rows):
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def _rank(key, pct, cell_n="40", aage="8"):
    field, pid, y = key.split("|")
    return {"key": key, "author_id": pid, "field": field, "arrival_true": str(int(y[1:]) + 1), "Y": y[1:],
            "stock": "500", "cell": "2002|6-9", "cell_n": cell_n, "aage": aage, "pct": pct, "pass_p10": "True", "note": ""}


def _flip(key, pct_own, in_own, pct_c, in_c, p05_own="False"):
    field, pid, y = key.split("|")
    return {"person_id": pid, "key": key, "field": field, "status": "rank", "src": "G0", "arrival": str(int(y[1:]) + 1),
            "pct_A": pct_c, "in_A": in_c, "pct_own": pct_own, "cell_own": "2002|6-9", "cell_n_own": "40",
            "aage_own": "8", "stock_own": "500", "in_own": in_own, "p05_own": p05_own, "october_event": "True",
            "october_p05": "False", "flip": "none", "flip_vs": "october", "pct_C": pct_c, "in_C": in_c}


TOY = [("econ|A1|Y2007", "0.974", "True", "0.98", "True"),
       ("econ|A2|Y2009", "0.8718", "False", "0.9373", "True"),
       ("chemistry|A3|Y2012", "0.95", "True", "0.96", "True")]


def _run(d, *, result="OK", gates=None, requests=None, toy=TOY):
    d = pathlib.Path(d)
    d.mkdir(parents=True, exist_ok=True)
    rows = [_rank(k, po) for k, po, _io, _pc, _ic in toy]
    _w(d / "ranks_A.csv", RANK_COLS, [_rank(k, pc) for k, _po, _io, pc, _ic in toy])
    _w(d / "ranks_own.csv", RANK_COLS, rows)
    _w(d / "ranks_C.csv", RANK_COLS, [_rank(k, pc) for k, _po, _io, pc, _ic in toy])
    _w(d / "flips.csv", FLIP_COLS, [_flip(*t) for t in toy])
    g = {"G1_0705": 0, "G1_11": 0, "GEQ": 0} if gates is None else gates
    (d / "summary.json").write_text(json.dumps({"result": result, "gates": g, "flips": {},
                                                "requests": len(toy) if requests is None else requests}), encoding="utf-8")
    (d / "RESULT.txt").write_text(result + "\n", encoding="utf-8")
    (d / "boot.log").write_text("never read\n", encoding="utf-8")
    return d


def _edit(p, key, col, value, keycol="key"):
    with open(p, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
        cols = list(rows[0].keys())
    for r in rows:
        if r[keycol] == key:
            r[col] = value
    _w(p, cols, rows)


TOY_ASSERTS = {"schema": "sar.r1.rank_named.v1", "reference": "toy", "asserts": [
    {"person_id": "A1", "field": "econ", "arrival": 2008, "pass": "own", "pct": 0.974, "in": True, "source": "toy"},
    {"person_id": "A2", "field": "econ", "pass": "own", "pct": 0.8718, "in": False, "source": "toy"},
    {"person_id": "A2", "field": "econ", "pass": "C", "pct": 0.9373, "in": True, "source": "toy"}]}


def _gate(tmp_path, new, ref, asserts=None):
    a = tmp_path / "asserts.json"
    a.write_text(json.dumps(asserts or TOY_ASSERTS), encoding="utf-8")
    out = tmp_path / "gate_out"
    rc = rr.main(["gate", "--new", str(new), "--ref", str(ref), "--asserts", str(a), "--out", str(out)])
    return rc, json.loads((out / "summary.json").read_text(encoding="utf-8")), \
        json.loads((out / "report.json").read_text(encoding="utf-8")), (out / "RESULT.txt").read_text(encoding="utf-8").strip()


@pytest.fixture(autouse=True)
def _on_the_runner(monkeypatch):
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")


def test_gate_passes_on_equal_runs_and_records_byte_equality(tmp_path):
    ref, new = _run(tmp_path / "ref"), _run(tmp_path / "new")
    rc, s, rep, res = _gate(tmp_path, new, ref)
    assert (rc, res, s["result"]) == (0, "OK", "OK")
    assert s["diffs"] == {f: 0 for f in rr.CSV_FILES}
    assert s["byte_equal"] == {f: True for f in rr.CSV_FILES}
    assert s["named"] == "3/3" and rep["diffs"] == []
    # same content, other row order: content-equal, not byte-equal, still OK
    with open(new / "ranks_C.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    _w(new / "ranks_C.csv", RANK_COLS, rows[::-1])
    rc, s, _rep, res = _gate(tmp_path, new, ref)
    assert (rc, res) == (0, "OK") and s["byte_equal"]["ranks_C.csv"] is False and s["diffs"]["ranks_C.csv"] == 0


def test_gate_names_file_key_and_column_of_a_difference(tmp_path):
    ref, new = _run(tmp_path / "ref"), _run(tmp_path / "new")
    _edit(new / "ranks_own.csv", "econ|A1|Y2007", "pct", "0.9741")
    assert rr.compare(rr.load_rows(ref, "ranks_own.csv"), rr.load_rows(new, "ranks_own.csv"), "ranks_own.csv") == \
        [("ranks_own.csv", "econ|A1|Y2007", "pct", "0.974", "0.9741")]
    _edit(new / "flips.csv", "chemistry|A3|Y2012", "p05_own", "True")
    rc, s, rep, res = _gate(tmp_path, new, ref, asserts={"schema": "sar.r1.rank_named.v1", "asserts": []})
    assert (rc, res, s["result"]) == (1, "RANK_REPRO_FAIL", "RANK_REPRO_FAIL")
    assert s["diffs"]["ranks_own.csv"] == 1 and s["diffs"]["flips.csv"] == 1 and s["diffs"]["ranks_A.csv"] == 0
    assert ["ranks_own.csv", "econ|A1|Y2007", "pct"] in rep["diffs"]
    assert ["flips.csv", "chemistry|A3|Y2012", "p05_own"] in rep["diffs"]


def test_gate_refuses_missing_and_extra_keys(tmp_path):
    ref, new = _run(tmp_path / "ref"), _run(tmp_path / "new")
    with open(new / "ranks_C.csv", encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["key"] != "econ|A2|Y2009"]
    _w(new / "ranks_C.csv", RANK_COLS, rows)
    with open(new / "flips.csv", encoding="utf-8", newline="") as f:
        frows = list(csv.DictReader(f))
    _w(new / "flips.csv", FLIP_COLS, frows + [_flip("math_stats|A9|Y2015", "0.99", "True", "0.99", "True")])
    # the extra person is a fourth request of the new run, so the run still passes its own gates (one flips
    # row per request, check_run) and the gate reaches the comparison this test is about
    summ = json.loads((new / "summary.json").read_text(encoding="utf-8"))
    (new / "summary.json").write_text(json.dumps({**summ, "requests": 4}), encoding="utf-8")
    assert rr.check_run(new) == [] and rr.check_run(ref) == []
    d = rr.compare(rr.load_rows(ref, "ranks_C.csv"), rr.load_rows(new, "ranks_C.csv"), "ranks_C.csv")
    assert d == [("ranks_C.csv", "econ|A2|Y2009", "key", "present", "missing")]
    d = rr.compare(rr.load_rows(ref, "flips.csv"), rr.load_rows(new, "flips.csv"), "flips.csv")
    assert d == [("flips.csv", "math_stats|A9|Y2015", "key", "missing", "present")]
    rc, s, rep, res = _gate(tmp_path, new, ref, asserts={"schema": "sar.r1.rank_named.v1", "asserts": []})
    assert (rc, res, rep["run_fails"]) == (1, "RANK_REPRO_FAIL", [])
    assert s["diffs"] == {"ranks_A.csv": 0, "ranks_own.csv": 0, "ranks_C.csv": 1, "flips.csv": 1}
    assert ["ranks_C.csv", "econ|A2|Y2009", "key"] in rep["diffs"]
    assert ["flips.csv", "math_stats|A9|Y2015", "key"] in rep["diffs"]


def test_gate_refuses_a_run_whose_own_gates_failed(tmp_path):
    ref = _run(tmp_path / "ref")
    assert rr.check_run(ref) == []
    for i, kw in enumerate(({"result": "GATE_FAIL"}, {"gates": {"G1_0705": 0, "G1_11": 1, "GEQ": 0}},
                            {"gates": {"G1_0705": 0, "G1_11": 0, "GEQ": 2}}, {"gates": {"G1_0705": 0, "G1_11": 0}},
                            {"requests": 4})):
        new = _run(tmp_path / f"new{i}", **kw)
        assert rr.check_run(new), kw
        rc, s, rep, res = _gate(tmp_path, new, ref)
        assert (rc, res) == (1, "RANK_REPRO_FAIL"), kw
        assert rep["run_fails"] and rep["diffs"] == [] and s["diffs"] == {}, kw     # stopped before any comparison


def test_gate_reads_only_the_named_files(tmp_path):
    ref, new = _run(tmp_path / "ref"), _run(tmp_path / "new")
    (new / "boot.log").write_text("other bytes\n", encoding="utf-8")
    (new / "rk6b_report.json").write_text("{}", encoding="utf-8")
    rc, s, _rep, _res = _gate(tmp_path, new, ref)
    assert rc == 0 and set(s["byte_equal"]) == set(rr.CSV_FILES)
    assert rr.NAMED_FILES == ("ranks_A.csv", "ranks_own.csv", "ranks_C.csv", "flips.csv", "summary.json", "RESULT.txt")


#: the rank reference since the 3e paper checks (ruling R1P3-20): rk6b-06 on rec-01 + merge-04 + rk6a-04
RK6B_REF = "rk6b-06"


def test_the_rk6b_reference_is_named_alike_everywhere():
    """W3-MPIN: the named asserts, M's rk6b data_ref, both jobs that sync /data/ref/r1/rk6b/ and the inventory's REF4
    (what pin-02 pins) name the same rk6b run, and REF4's other three prefixes are the runs that rk6b run pulled."""
    prefix = f"r1/runs/{RK6B_REF}/out/files/"
    rec = json.loads((REPO / "data" / "cal2026-10r1" / "aws" / "runs" / RK6B_REF / "launch_record.json").read_text(encoding="utf-8"))
    assert sorted(src for src, _d in rec["extra_pulls"]) == sorted(s for s, _d in REF4 if s != prefix)
    assert json.loads(ASSERTS.read_text(encoding="utf-8"))["reference"] == RK6B_REF
    m = json.loads((REPO / "config" / "r1" / "M.json").read_text(encoding="utf-8"))
    assert m["data_refs"]["rk6b"]["prefix"] == prefix
    for job in ("rankrepro", "j1a"):
        assert [s for s, d in r1kit.load_job(job)["data_sync"] if d == "/data/ref/r1/rk6b/"] == [prefix], job
    if str(REPO / "tools") not in sys.path:
        sys.path.insert(0, str(REPO / "tools"))
    import r1_input_inventory as inv                                        # noqa: PLC0415
    assert [list(p) for p in inv.REF4] == REF4


def test_named_asserts_are_the_rk6b06_values():
    """C2 re-derived for rk6b-06. Own-field values are tied to flips_r1.json (addlist-04 installed it from rk6b-06).
    No git file carries rk6b-06's pass-C percentiles: a pass-C value is the rk6b-06 run output, checked by the gate on
    the run itself; its in-flag must equal the signed basis in p2_decisions.json, and its source must name both the
    run output and the rk6b-05 basis number p2_decisions.json keeps (a signed file, not edited)."""
    spec = json.loads(ASSERTS.read_text(encoding="utf-8"))
    assert spec["schema"] == "sar.r1.rank_named.v1" and spec["reference"] == RK6B_REF
    flips = {r["person_id"]: r for r in json.loads((INPUTS / "flips_r1.json").read_text(encoding="utf-8"))["rows"]}
    persons = json.loads((INPUTS / "p2_decisions.json").read_text(encoding="utf-8"))["persons"]
    seen = set()
    for a in spec["asserts"]:
        pid = a["person_id"]
        assert a["source"].strip() and a["pass"] in ("own", "C")
        assert flips[pid]["field"] == a["field"]
        if a["pass"] == "own":
            assert abs(float(flips[pid]["pct_own"]) - a["pct"]) < 5e-5, a
            assert a["in"] == (flips[pid]["flip"] != "in->out"), a          # an in->out flip is a failed own pass
            assert "flips_r1.json" in a["source"] and RK6B_REF in a["source"], a
        else:
            m = re.search(r"cleaned all-field rank ([0-9.]+) in_C=(True|False)", persons[pid]["basis"])
            assert m and (m.group(2) == "True") == a["in"], a                 # the signed verdict basis still holds
            assert f"{RK6B_REF} run output flips.csv pct_C {a['pct']} in_C={a['in']}" in a["source"], a
            assert f"cleaned all-field rank {m.group(1)} in_C={m.group(2)}" in a["source"], a
        seen.add((pid, a["pass"]))
    assert seen == {("A5028731684", "own"), ("A5001177483", "own"), ("A5001177483", "C"),
                    ("A5008470795", "own"), ("A5008470795", "C")}
    redated_star = next(a for a in spec["asserts"] if a["person_id"] == "A5028731684")
    assert (redated_star["arrival"], redated_star["pct"], redated_star["in"]) == (2008, 0.974, True)     # not ~0.92 at 2010 (C2)
    with open(INPUTS / "fixes_1001.csv", encoding="utf-8", newline="") as f:
        redate = {r["author_id"]: r["value"] for r in csv.DictReader(f) if r["fix"] == "redate"}
    assert redate["A5028731684"] == "2008"


def test_named_asserts_fail_on_a_wrong_value_a_missing_row_or_two_rows(tmp_path):
    run = _run(tmp_path / "run")
    assert rr.check_named(run, TOY_ASSERTS) == []
    wrong = json.loads(json.dumps(TOY_ASSERTS))
    wrong["asserts"][0]["pct"] = 0.92
    assert len(rr.check_named(run, wrong)) == 1
    late = json.loads(json.dumps(TOY_ASSERTS))
    late["asserts"][0]["arrival"] = 2010
    assert len(rr.check_named(run, late)) == 1
    flipped = json.loads(json.dumps(TOY_ASSERTS))
    flipped["asserts"][1]["in"] = True
    assert len(rr.check_named(run, flipped)) == 1
    missing = {"schema": "sar.r1.rank_named.v1", "asserts": [dict(TOY_ASSERTS["asserts"][0], person_id="A7")]}
    assert len(rr.check_named(run, missing)) == 1
    two = _run(tmp_path / "two", toy=TOY + [("econ|A1|Y2009", "0.97", "True", "0.98", "True")])
    fails = rr.check_named(two, TOY_ASSERTS)
    assert len(fails) == 1 and "A1" in fails[0]


def test_compare_skips_allowed_ids_and_rounds_only_when_asked(tmp_path):
    ref, new = _run(tmp_path / "ref"), _run(tmp_path / "new")
    _edit(new / "ranks_own.csv", "econ|A2|Y2009", "pct", "0.9")
    _edit(new / "ranks_own.csv", "econ|A1|Y2007", "pct", "0.97401")
    a, b = rr.load_rows(ref, "ranks_own.csv"), rr.load_rows(new, "ranks_own.csv")
    assert {d[1] for d in rr.compare(a, b, "ranks_own.csv")} == {"econ|A1|Y2007", "econ|A2|Y2009"}
    assert rr.compare(a, b, "ranks_own.csv", allowed_ids=frozenset({"A2"}), dp=4) == []
    assert rr.compare(a, b, "ranks_own.csv", allowed_ids=frozenset({"A2"})) == \
        [("ranks_own.csv", "econ|A1|Y2007", "pct", "0.974", "0.97401")]


def _diff(tmp_path, new, ref, allowed):
    f = tmp_path / "allowed.txt"
    f.write_text("# persons whose paper checks changed\n" + "".join(f"{a}\n" for a in allowed), encoding="utf-8")
    out = tmp_path / "diff_out"
    rc = rr.main(["diff", "--new", str(new), "--ref", str(ref), "--allowed-ids", str(f), "--out", str(out)])
    return rc, json.loads((out / "summary.json").read_text(encoding="utf-8")), (out / "RESULT.txt").read_text(encoding="utf-8").strip()


#: the allowed-ids file holds OpenAlex author ids (rank_r1.AID: 'A' and at least six digits, as in dossier_pack and
#: calls_lib), so the diff tests use toy ids of that form: A1 -> A1000001, A2 -> A1000002, A3 -> A1000003
LONG = [(k.replace("|A", "|A100000", 1), *rest) for k, *rest in TOY]


def test_the_allowed_ids_file_holds_openalex_ids(tmp_path):
    f = tmp_path / "allowed.txt"
    f.write_text("# changed checks, e.g. A5001177483 (a comment: never read)\nA5028731684\n\n  A1000002  \nA2\n",
                 encoding="utf-8")
    assert rr.read_allowed(f) == frozenset({"A5028731684", "A1000002"})     # 'A2' is not an OpenAlex id


def test_diff_stops_only_outside_the_allowed_ids(tmp_path):
    ref = _run(tmp_path / "ref", toy=LONG)
    new = _run(tmp_path / "new", toy=[LONG[0], ("econ|A1000002|Y2010", "0.91", "True", "0.95", "True"), LONG[2]])
    _edit(new / "ranks_own.csv", "econ|A1000001|Y2007", "pct", "0.97401")          # equal at 4 dp
    rc, s, res = _diff(tmp_path, new, ref, ["A1000002"])
    assert (rc, res, s["result"]) == (0, "OK", "OK") and s["moved"] == ["A1000002"] and s["allowed"] == 1
    _edit(new / "ranks_C.csv", "chemistry|A1000003|Y2012", "cell_n", "41")
    rc, s, res = _diff(tmp_path, new, ref, ["A1000002"])
    assert (rc, res) == (1, "RANK_DIFF_STOP") and s["diffs"]["ranks_C.csv"] == 1
    bad = _run(tmp_path / "bad", result="GATE_FAIL", toy=LONG)
    rc, _s, res = _diff(tmp_path, bad, ref, ["A1000002"])
    assert (rc, res) == (1, "RANK_DIFF_STOP")


def test_refuses_off_aws(tmp_path, monkeypatch):
    monkeypatch.setenv("SAR_HOST", "mac")
    with pytest.raises(SystemExit, match="R1 AWS instance"):
        rr.main(["gate", "--new", str(tmp_path), "--ref", str(tmp_path), "--asserts", str(ASSERTS), "--out", str(tmp_path / "o")])


def test_collect_needs_every_stage_ok(tmp_path):
    for name, res in (("rank_gate", "OK"), ("rank_tables", "OK")):
        d = tmp_path / name
        d.mkdir()
        (d / "RESULT.txt").write_text(res + "\n", encoding="utf-8")
        (d / "summary.json").write_text(json.dumps({"result": res, "counts": {"econ": 1}}), encoding="utf-8")
    out = tmp_path / "out"
    assert rr.main(["collect", "--stage", str(tmp_path / "rank_gate"), "--stage", str(tmp_path / "rank_tables"), "--out", str(out)]) == 0
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert s["result"] == "OK" and s["stages"]["rank_tables"]["counts"] == {"econ": 1}
    (tmp_path / "rank_tables" / "RESULT.txt").write_text("STOP\n", encoding="utf-8")
    assert rr.main(["collect", "--stage", str(tmp_path / "rank_gate"), "--stage", str(tmp_path / "rank_tables"), "--out", str(out)]) == 1
    assert (out / "RESULT.txt").read_text(encoding="utf-8").strip() == "RANKREPRO_FAIL"
    shutil.rmtree(tmp_path / "rank_tables")
    assert rr.main(["collect", "--stage", str(tmp_path / "rank_gate"), "--stage", str(tmp_path / "rank_tables"), "--out", str(out)]) == 1


# ---------------------------------------------------------------------------------------------------- job specs
#: rk6b-06 and the upstream runs it pulled (data/cal2026-10r1/aws/runs/rk6b-06/launch_record.json)
REF4 = [["r1/recovered/rec-01/", "/data/ref/r1/rec/"], ["r1/runs/merge-04/out/files/", "/data/ref/r1/merge/"],
        ["r1/runs/rk6a-04/out/files/", "/data/ref/r1/rk6a/"], ["r1/runs/rk6b-06/out/files/", "/data/ref/r1/rk6b/"]]
NAMED7 = ("ranks_A.csv", "ranks_own.csv", "ranks_C.csv", "flips.csv", "rk6b_report.json", "summary.json", "RESULT.txt")


def test_rankrepro_runs_the_rank_stages_on_pinned_inputs():
    job = r1kit.load_job("rankrepro")
    assert (job["instance_type"], job["sar_host"], job["env_layers"]) == ("r6i.8xlarge", "ec2-r1", ["py"])
    assert job["env"]["WORK"] == "/work"
    whole = [["u1_edges_full_2026-07-05/", "/data/openalex_pipeline/derived/u1_edges_full_2026-07-05/"],
             ["u1_full_11school_2026-07-16/", "/data/openalex_pipeline/derived/u1_full_11school_2026-07-16/"]]
    assert job["data_sync"] == sorted(REF4 + whole)
    assert job["pulls"] == [] and job["required_dests"] == []
    scripts = {s for s, _d in job["copy_from_tip"]}
    assert scripts == {f"pipeline/aws/r1/{n}" for n in ("verify_inputs.py", "rk6_requests.py", "rk6b_rank.py", "rank_r1.py", "restake_r1.py")}
    assert all(d == "/work/" + s.rsplit("/", 1)[1] for s, d in job["copy_from_tip"])
    steps = job["steps"]
    order = ["verify_inputs.py\" data", "rk6_requests.py\" build", "rk6b_rank.py\"", "rank_r1.py\" gate", "restake_r1.py\" m",
             "rank_r1.py\" collect"]
    at = [next(i for i, s in enumerate(steps) if o in s) for o in order]
    assert at == sorted(at), at
    for name in ("verify_inputs", "rank_requests", "rank_m", "rank_gate", "rank_tables"):
        assert sum(f"STAGE_OUT=/work/prod/{name} " in s for s in steps) == 1, name
    req = steps[at[1]]
    for flag in ("--merged /data/ref/r1/merge/candidates_merged.csv", "--recovered /data/ref/r1/rec",
                 "--rk6a-out /data/ref/r1/rk6a", "--out \"$STAGE_OUT/in6\"", "recovered_pins.json", "rulings_p1.json",
                 "inputs/paper_checks"):
        assert flag in req, flag
    m = steps[at[2]]
    assert 'RK_IN="$WORK/prod/rank_requests/in6"' in m and 'RK_OUT="$WORK/tmp/rank_m"' in m
    assert 'rm -rf "$WORK/tmp/rank_m"' in m                                   # the duck_* dbs never reach out/
    assert re.search(r"for f in ([^;]+); do", m).group(1).split() == list(NAMED7)
    gate = steps[at[3]]
    assert "--ref /data/ref/r1/rk6b " in gate and "--new \"$WORK/prod/rank_m\"" in gate
    assert "config/r1/rank_named_asserts.json" in gate
    tables = steps[at[4]]
    assert "--rk \"$WORK/prod/rank_m\"" in tables and "--repo \"$REPO_DIR\"" in tables
    # no step writes a person-level file to out/ except through the stage dirs; the boot log is never read
    assert not any("boot.log" in s for s in steps)


def test_rankdiff_compares_two_pulled_runs():
    job = r1kit.load_job("rankdiff")
    assert (job["instance_type"], job["sar_host"]) == ("m6i.large", "ec2-r1")
    assert sorted(job["required_dests"]) == ["/work/new/", "/work/ref/"]
    assert ["pipeline/aws/r1/rank_r1.py", "/work/rank_r1.py"] in job["copy_from_tip"]
    step = " ".join(job["steps"])
    assert "rank_r1.py diff --new /work/new --ref /work/ref --allowed-ids /work/in/allowed_ids.txt --out /work/out" in step
    assert job["data_sync"] == []
