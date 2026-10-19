# -*- coding: utf-8 -*-
"""pipeline/aws/r1/rk6b_rank.py - the own-field ranking pieces, on toy authorship tables."""
from __future__ import annotations

import atexit
import json
import os
import pathlib
import shutil
import sys
import tempfile
import types

import pytest

if os.environ.get("SAR_HOST") != "ec2-r1":
    pytest.skip("Ranking import requires the EC2 data-disk guard.", allow_module_level=True)

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
sys.path.insert(0, str(REPO / "pipeline" / "stars" / "caliber_2026-08-28"))
import rk6b_rank as rb          # noqa: E402
import restake_equiv as re_     # noqa: E402


def _screening_with_a_stand_in_disk():
    """run_screening.py resolves its data table at import (require_readable), and on the test runner the
    configured disk is refused (R1 F0: it is read only on ec2-r1) - t-0003, collection error. Point
    $SAR_SSD_ROOT at an empty stand-in for the import only; these tests use L and _POOL_SQL, never the table."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="sar-r1-rk6b-"))
    atexit.register(shutil.rmtree, tmp, ignore_errors=True)
    root = tmp / "openalex_pipeline"
    (root / "derived" / "u1_edges_full_2026-07-05").mkdir(parents=True)
    old = os.environ.get("SAR_SSD_ROOT")
    os.environ["SAR_SSD_ROOT"] = str(root)
    try:
        return re_._screening_modules()
    finally:
        if old is None:
            os.environ.pop("SAR_SSD_ROOT", None)
        else:
            os.environ["SAR_SSD_ROOT"] = old


L, POOL_SQL = _screening_with_a_stand_in_disk()


def test_the_job_runs_a_copy_so_the_in_place_guard_lets_it_read(monkeypatch):
    """Run where it sits (pipeline/aws/r1/), rk6b_rank.py would be stopped by refuse_unstaged_in_place_run()
    at its first require_readable call; the job copies it to /work/ and runs that path."""
    from pipeline.lib import paths as P
    job = json.loads((REPO / "config" / "r1" / "jobs" / "rk6b.json").read_text(encoding="utf-8"))
    assert ["pipeline/aws/r1/rk6b_rank.py", "/work/rk6b_rank.py"] in job["copy_from_tip"]
    assert any('"$PY" /work/rk6b_rank.py' in s for s in job["steps"])
    monkeypatch.setitem(sys.modules, "__main__", types.SimpleNamespace(__file__="/work/rk6b_rank.py"))
    P.refuse_unstaged_in_place_run()                                    # the path the job uses: allowed
    monkeypatch.setitem(sys.modules, "__main__", types.SimpleNamespace(__file__=str(REPO / "pipeline/aws/r1/rk6b_rank.py")))
    with pytest.raises(P.PathUnresolved, match="refusing to run a ported pipeline script"):
        P.refuse_unstaged_in_place_run()


@pytest.fixture
def con(tmp_path):
    c = re_.connect(tmp_path / "tmpdb")
    c.execute("CREATE TEMP TABLE aw_raw(aid VARCHAR, wid VARCHAR, yr INTEGER, c BIGINT, sf VARCHAR)")
    rows = [(f"P{i}", f"W{i}", 2000, 10 * i, "1605") for i in range(1, 41)]
    rows += [("P40", "W900", 2001, 1000, "2002"), ("X", "W1001", 1999, 150, "1605"), ("X", "W1002", 1995, 500, "2002")]
    c.executemany("INSERT INTO aw_raw VALUES (?,?,?,?,?)", rows)
    rb.build_aw(c, "aw_clean", set(), set())
    yield c
    c.close()


def _pool(c, sql, ids=("X", "P40")):
    c.execute(sql.format(Y=2005, GAP=L.ROBUST_FIRST_PUB_MAX_GAP))
    q = ",".join(f"'{i}'" for i in ids)
    return {r[0]: {"stock": r[1], "aage": r[2]} for r in c.execute(f"SELECT aid, stock, aage FROM poolY WHERE aid IN ({q})").fetchall()}


def test_own_pred_keeps_only_four_digit_codes_of_the_field(con):
    con.execute("CREATE TEMP TABLE t(sf VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?)", [("2002",), ("https://openalex.org/subfields/2003",), ("1605",),
                                                 (None,), ("200",), ("20021",)])
    kept = sorted(r[0] for r in con.execute(f"SELECT sf FROM t WHERE {rb.own_pred('20')}").fetchall())
    assert kept == ["2002", "https://openalex.org/subfields/2003"]


def test_star_and_pool_removes_other_field_papers_for_everyone(con):
    rb.build_own_aw(con, "16", "star_and_pool", {"X"})
    got = _pool(con, POOL_SQL)
    assert got["X"]["stock"] == 150 and got["P40"]["stock"] == 400
    assert got["X"]["aage"] == 2005 - 1999


def test_age_from_all_papers_keeps_the_first_publication_year(con):
    rb.build_own_aw(con, "16", "star_and_pool", {"X"})
    got = _pool(con, rb.own_pool_sql(POOL_SQL, "all"))
    assert got["X"]["stock"] == 150 and got["X"]["aage"] == 2005 - 1995


def test_star_only_leaves_the_pool_untouched(con):
    rb.build_own_aw(con, "16", "star_only", {"X"})
    got = _pool(con, POOL_SQL)
    assert got["X"]["stock"] == 150 and got["P40"]["stock"] == 1400


def test_own_pool_sql_refuses_a_changed_pool_query():
    with pytest.raises(RuntimeError, match="_POOL_SQL changed"):
        rb.own_pool_sql(POOL_SQL.replace("FROM aw WHERE yr <= {Y}))", "FROM aw2 WHERE yr <= {Y}))"), "all")
    assert rb.own_pool_sql(POOL_SQL, "own") == POOL_SQL


def test_rank_is_the_production_stats_in_rounds(con):
    rb.build_aw(con, "aw", set(), set())
    cands = [{"key": "a", "author_id": "P20", "field": "chemistry", "arrival_true": 2006},
             {"key": "b", "author_id": "P20", "field": "chemistry", "arrival_true": 2004}]
    rows = rb.rank(con, cands, "t", re_, L, POOL_SQL, {})
    assert [r["key"] for r in rows] == ["a", "b"]
    for r, c in zip(rows, cands):
        d = re_._stats(con, [c], "d", L, POOL_SQL, overrides={})["P20"]
        assert (r["pct"], r["cell_n"], r["aage"], r["stock"]) == (d["pct"], d["cell_n"], d["aage"], d["stock"])


def test_geq_compares_every_field_as_the_csv_wrote_it():
    mine = [{"key": "k1", "author_id": "A1", "stock": 900, "cell": "2002|6-9", "cell_n": 500, "aage": 7, "pct": 0.95, "pass_p10": True, "note": ""},
            {"key": "k2", "author_id": "A2", "stock": None, "cell": None, "cell_n": None, "aage": None, "pct": None, "pass_p10": False, "note": "not_in_pool"}]
    theirs = {"k1": {"author_id": "A1", "stock": "900", "cell": "2002|6-9", "cell_n": "500", "aage": "7", "pct": "0.95", "pass_p10": "True", "note": ""},
              "k2": {"author_id": "A2", "stock": "", "cell": "", "cell_n": "", "aage": "", "pct": "", "pass_p10": "False", "note": "not_in_pool"},
              "CONTROL|A9": {"author_id": "A9"}}
    reqs = [{"key": "k1"}, {"key": "k2"}]
    assert rb.geq_gate(mine, theirs, reqs) == []
    theirs["econ|A3|Y2009"] = {"author_id": "A3"}                     # skipped in RK6b: an id dispute
    assert rb.geq_gate(mine, theirs, reqs, skipped=["A3"]) == []
    assert rb.geq_gate(mine, theirs, reqs) == [("GEQ", "econ|A3|Y2009", "missing in RK6b")]
    del theirs["econ|A3|Y2009"]
    theirs["k1"]["pct"] = "0.9501"
    assert rb.geq_gate(mine, theirs, reqs) == [("GEQ", "k1", "pct", "0.9501", "0.95")]


def test_control_gate_matches_to_four_decimals():
    ctrl = [{"author_id": "A1", "arrival_true": 2010, "ext": "11", "expected_pct": 0.9936},
            {"author_id": "A2", "arrival_true": 2011, "ext": "11", "expected_pct": None}]
    rows = [{"author_id": "A1", "arrival_true": 2010, "pct": 0.99364}, {"author_id": "A2", "arrival_true": 2011, "pct": None}]
    assert rb.control_gate(rows, ctrl, "11") == []
    rows[0]["pct"] = 0.9937
    assert rb.control_gate(rows, ctrl, "11")[0][:3] == ("G1", "11", "A1")


def test_rulings_need_a_signature_a_known_scope_and_allowed_codes(tmp_path):
    good = {"schema": "sar.r1.rulings_p1.v1", "decided": "2026-10-15",
            "own_field": {"scope": "star_and_pool", "age_basis": "all", "field_code": dict(rb.FIELD_CODE)}}
    p = tmp_path / "r.json"
    p.write_text(json.dumps(good))
    assert rb.load_rulings(p)["scope"] == "star_and_pool"
    p.write_text(json.dumps(dict(good, own_field=dict(good["own_field"], field_code={"econ": "2002", "chemistry": "16", "math_stats": "26"}))))
    assert rb.load_rulings(p)["field_code"]["econ"] == "2002"
    for bad in (dict(good, decided=""), dict(good, own_field=dict(good["own_field"], scope="pool_only")),
                dict(good, own_field=dict(good["own_field"], field_code={"econ": "2003", "chemistry": "16", "math_stats": "26"}))):
        p.write_text(json.dumps(bad))
        with pytest.raises(SystemExit, match="refused"):
            rb.load_rulings(p)


def test_flips_compare_the_187_with_october_and_new_people_with_the_unfiltered_rank():
    reqs = [{"key": "k1", "person": "A1", "Y": 2009, "field": "econ", "status": "rank", "src": "G0"},
            {"key": "k2", "person": "A2", "Y": 2014, "field": "chemistry", "status": "rank", "src": "G3"},
            {"key": "k3", "person": "A3", "Y": 2014, "field": "chemistry", "status": "rank", "src": "G3"}]
    a = [{"key": "k1", "pct": 0.95}, {"key": "k2", "pct": 0.93}, {"key": "k3", "pct": 0.80}]
    o = [dict(key=k, pct=p, cell="c", cell_n=50, aage=7, stock=1) for k, p in (("k1", 0.85), ("k2", 0.95), ("k3", 0.91))]
    flips = {f["person_id"]: f for f in rb.make_flips(reqs, a, o, {"A1"}, set(),
                                                      lambda r, arr: r["pct"] >= 0.90, lambda r, arr: r["pct"] >= 0.95)}
    assert flips["A1"]["flip"] == "in->out" and flips["A1"]["flip_vs"] == "october"
    assert flips["A2"]["flip"] == "none" and flips["A2"]["p05_own"] is True
    assert flips["A3"]["flip"] == "out->in" and flips["A3"]["flip_vs"] == "unfiltered"


def test_pass_c_ranks_on_the_cleaned_table_with_every_field(con):
    rb.build_aw(con, "aw_clean", {("X", "W1002")}, set())             # a paper-check exclusion
    rb.use_clean_all_fields(con)
    got = _pool(con, POOL_SQL)
    assert got["X"]["stock"] == 150 and got["X"]["aage"] == 2005 - 1999      # the excluded work is gone
    assert got["P40"]["stock"] == 1400                                        # other fields stay


def test_flips_carry_the_cleaned_all_field_rank():
    reqs = [{"key": "k1", "person": "A1", "Y": 2009, "field": "econ", "status": "rank", "src": "G3"}]
    a, c = [{"key": "k1", "pct": 0.95}], [{"key": "k1", "pct": 0.92}]
    o = [dict(key="k1", pct=0.5, cell="c", cell_n=50, aage=7, stock=1)]
    verdict = lambda r, arr: r["pct"] >= 0.90                           # noqa: E731
    f = rb.make_flips(reqs, a, o, set(), set(), verdict, lambda r, arr: False, rows_c=c)[0]
    assert (f["pct_C"], f["in_C"]) == (0.92, True)
    f = rb.make_flips(reqs, a, o, set(), set(), verdict, lambda r, arr: False)[0]
    assert (f["pct_C"], f["in_C"]) == (None, None)


def test_the_import_paths_reach_the_2026_10_run_caliber_with_pass_p05(monkeypatch):
    """rk6b-01 crashed in make_flips: both caliber layers carry a run_caliber.py, and the 08-28 one, first on
    sys.path, has no pass_p05. The 2026-10 layer must come first."""
    import importlib.util
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.delitem(sys.modules, "run_caliber", raising=False)
    rb.setup_import_paths(REPO)
    origin = pathlib.Path(importlib.util.find_spec("run_caliber").origin)
    assert origin.parent.name == "caliber_2026-10"
    assert "def pass_p05" in origin.read_text(encoding="utf-8")
