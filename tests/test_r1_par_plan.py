# -*- coding: utf-8 -*-
"""pipeline/aws/r1/par_plan.py (N8): the memory-aware parallel-width planner J1b runs first.

Toy inputs only: the frames are small parquet/CSV files written in tmp_path, the unit TSV and the
mem_probe / cells reports are written by the tests. Nothing runs R and no real frame is read; the row
counts the planner sees are either the toy files' own or numbers passed straight to plan().
"""
from __future__ import annotations

import hashlib
import json
import math
import pathlib
import random
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import par_plan as pp   # noqa: E402

COLS = ("group", "name", "kind", "frame", "threads", "est_min", "cmd", "outdir", "needs_control")


def _unit(group, name, kind, frame, threads=4, est_min=10):
    return {"group": group, "name": name, "kind": kind, "frame": frame, "threads": str(threads),
            "est_min": str(est_min), "cmd": f"Rscript x.R {name}", "outdir": f"out/{group}", "needs_control": "0"}


def _tsv(path: pathlib.Path, units) -> pathlib.Path:
    lines = ["\t".join(COLS)] + ["\t".join(u[c] for c in COLS) for u in units]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _parquet(p: pathlib.Path, n: int) -> None:
    pq.write_table(pa.table({"pair": list(range(n)), "y": [0] * n}), p)


def _mem_report(path: pathlib.Path, field="econ", rows=1_500_000, perm=10.0, null=27.7) -> pathlib.Path:
    rep = {"schema": "sar.r1.mem_probe.v1", "stack": "rcloud", "threads": 4, "seed": 20260830, "status": "OK",
           "fields": {field: {"status": "OK", "rows": {"p3_afar_pos": rows}, "absent": [],
                              "units": {"perm": {"rc": 0, "status": "OK", "peak_gib": perm, "wall_s": 60.0},
                                        "null": {"rc": 0, "status": "OK", "peak_gib": null, "wall_s": 90.0}}}}}
    path.write_text(json.dumps(rep), encoding="utf-8")
    return path


def test_toy_rows_give_the_expected_par():
    units = [_unit("p3tp_econ", f"P3tp_{i:02d}", "p3tp", "p3_afar_pos_econ.parquet") for i in range(20)]
    out = pp.plan(units, {"p3_afar_pos_econ.parquet": 2_000_000}, {})
    assert out["verdict"] == "OK"
    (g,) = out["groups"]
    assert g["group"] == "p3tp_econ"
    assert g["pred_gib"] == pytest.approx(50.0)
    assert g["threads"] == 4
    assert g["par"] == 9          # min(20 units, 64 // 4 = 16, 450 // 50 = 9)
    assert g["peak_total_gib"] == pytest.approx(450.0)
    assert out["calib_used"]["p3tp"]["source"] == "default"


def test_one_oversized_unit_stops(tmp_path, monkeypatch):
    frames = tmp_path / "frames"
    frames.mkdir()
    _parquet(frames / "p3_afar_pos_econ.parquet", 5)
    _parquet(frames / "p3_afar_pos_chemistry.parquet", 5)
    units = [_unit("null_econ", "NULLpos_econ", "null", "p3_afar_pos_econ.parquet"),
             _unit("null_chem", "NULLpos_chemistry", "null", "p3_afar_pos_chemistry.parquet")]
    rows = {"p3_afar_pos_econ.parquet": 15_000_000, "p3_afar_pos_chemistry.parquet": 1_000_000}
    out = pp.plan(units, rows, {})
    assert out["verdict"] == "STOP"
    (s,) = out["stops"]
    assert s["unit"] == "NULLpos_econ" and s["group"] == "null_econ" and s["reason"] == "MEMORY"
    assert s["pred_gib"] == pytest.approx(480.0)        # 32 GiB per million rows x 15M
    assert [g["group"] for g in out["groups"]] == ["null_chem"]

    # The CLI: exit 3 and nothing for the stopped group in plan.json.
    tsv = _tsv(tmp_path / "units.tsv", units)
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    monkeypatch.setattr(pp, "rows_of", lambda p: rows[pathlib.Path(p).name])
    rc = pp.main(["--jobs", str(tsv), "--frames", str(frames), "--calib", str(_mem_report(tmp_path / "m.json", null=None)),
                  "--out", str(tmp_path / "out")])
    assert rc == 3
    written = json.loads((tmp_path / "out" / "plan.json").read_text())
    assert written["verdict"] == "STOP"
    assert "null_econ" not in [g["group"] for g in written["groups"]]
    assert "NULLpos_econ" in json.dumps(written["stops"])


def test_par_times_threads_never_exceeds_the_vcpus():
    rng = random.Random(20261015)
    kinds = ("p1", "p2", "p3tp", "perm_p1", "perm_p3tp", "null", "p3full", "build")
    for trial in range(200):
        units, rows = [], {}
        for g in range(rng.randint(1, 6)):
            frame = f"f{trial}_{g}.parquet"
            rows[frame] = rng.randint(0, 14_000_000)
            threads = rng.choice((1, 2, 4, 8, 16, 32, 64))
            for i in range(rng.randint(1, 40)):
                units.append(_unit(f"g{g}", f"u{g}_{i}", rng.choice(kinds), frame, threads=threads,
                                   est_min=rng.randint(1, 30)))
        out = pp.plan(units, rows, {})
        for grp in out["groups"]:
            assert grp["par"] >= 1
            assert grp["par"] * grp["threads"] <= 64
            assert grp["par"] * grp["pred_gib"] <= 450 + 1e-9
            assert grp["par"] <= grp["n_units"]


def test_calibration_replaces_the_default(tmp_path):
    calib = pp.calibrate(mem_report=json.loads(_mem_report(tmp_path / "m.json").read_text()))
    coef, src = pp.coefficient("null", calib)
    assert coef == pytest.approx(27.7 / 1.5 * 1.25, abs=1e-6)          # 23.08 GiB per million rows
    assert round(coef, 2) == 23.08
    assert src.startswith("mem_probe")
    assert pp.predict_gib("null", 1_500_000, calib) == pytest.approx(27.7 * 1.25)
    # the perm unit calibrates perm_p3tp only
    assert pp.coefficient("perm_p3tp", calib)[0] == pytest.approx(10.0 / 1.5 * 1.25)
    # without a measurement: the default, 32 for the heavy kinds, 25 otherwise
    assert pp.coefficient("null", {}) == (32.0, "default")
    assert pp.coefficient("p3full", {}) == (32.0, "default")
    assert pp.coefficient("p3tp", calib) == (25.0, "default")
    out = pp.plan([_unit("n", "NULLpos_econ", "null", "f.parquet")], {"f.parquet": 1_500_000}, calib)
    assert out["calib_used"]["null"]["source"].startswith("mem_probe")
    assert out["groups"][0]["pred_gib"] == pytest.approx(34.625)

    # A larger measurement per million rows wins (max over fields and reports).
    rep = json.loads(_mem_report(tmp_path / "m.json").read_text())
    rep["fields"]["chemistry"] = {"status": "OK", "rows": {"p3_afar_pos": 500_000}, "absent": [],
                                  "units": {"null": {"rc": 0, "status": "OK", "peak_gib": 12.0, "wall_s": 9.0},
                                            "perm": {"rc": 1, "status": "FAIL", "peak_gib": 50.0, "wall_s": 9.0}}}
    calib2 = pp.calibrate(mem_report=rep)
    assert pp.coefficient("null", calib2)[0] == pytest.approx(12.0 / 0.5 * 1.25)
    assert pp.coefficient("perm_p3tp", calib2)[0] == pytest.approx(10.0 / 1.5 * 1.25)   # failed unit ignored

    # Full-panel cells from cells_report_rcloud.json calibrate p3full, rows from the frame named in inputs.
    frames = tmp_path / "frames"
    frames.mkdir()
    _parquet(frames / "p3_slim_econ.parquet", 4)
    cells = {"P3_econ_fnfix": {"rc": 0, "status": "RAN", "secs": 1.0, "peak_gib": 8.8,
                               "inputs": {"frame": {"name": "p3_slim_econ.parquet"},
                                          "driver": {"name": "analysis/estimation/run_p3.R"}, "ref": None}}}
    calib3 = pp.calibrate(cells_report=cells, frames=frames, rows_fn=lambda p: 1_000_000)
    coef3, src3 = pp.coefficient("p3full", calib3)
    assert coef3 == pytest.approx(8.8 * 1.25) and src3.startswith("cells_rcloud")
    with pytest.raises(ValueError):
        pp.calibrate(mem_report={"schema": "something.else"})


def test_rows_come_from_metadata(tmp_path, monkeypatch):
    p = tmp_path / "toy.parquet"
    _parquet(p, 37)

    def boom(*a, **k):
        raise AssertionError("a data scan was attempted")
    monkeypatch.setattr(pq, "read_table", boom)
    monkeypatch.setattr(pq.ParquetFile, "read", boom)
    monkeypatch.setattr(pq.ParquetFile, "iter_batches", boom)
    assert pp.rows_of(p) == 37

    c = tmp_path / "toy.csv"
    c.write_text("a,b\n1,2\n3,4\n5,6\n", encoding="utf-8")
    assert pp.rows_of(c) == 3
    c2 = tmp_path / "noeol.csv"
    c2.write_text("a,b\n1,2\n3,4", encoding="utf-8")
    assert pp.rows_of(c2) == 2
    (tmp_path / "hdr.csv").write_text("a,b\n", encoding="utf-8")
    assert pp.rows_of(tmp_path / "hdr.csv") == 0
    with pytest.raises(ValueError):
        pp.rows_of(tmp_path / "x.feather")


def test_derived_units_use_their_parent_frame_rows():
    rows = {"p1_frame_econ.csv": 100_000, "p3_afar_pos_chemistry.parquet": 1_000_000}
    units = [_unit("d7", "P1_d7_p05_econ", "p1", "p1_frame_econ.csv"),
             _unit("cut", "P3pos_s2_chemistry", "p3tp", "p3_afar_pos_chemistry.parquet"),
             _unit("nc", "P3nc_pos_chemistry", "p3tp", "p3_afar_pos_chemistry.parquet"),
             _unit("post", "loeo_rank", "post", "-", threads=1)]
    out = pp.plan(units, rows, {})
    by = {u["name"]: u for g in out["groups"] for u in g["units"]}
    assert by["P1_d7_p05_econ"]["rows"] == 100_000
    assert by["P1_d7_p05_econ"]["pred_gib"] == pytest.approx(2.5)
    assert by["P3pos_s2_chemistry"]["rows"] == 1_000_000
    assert by["P3pos_s2_chemistry"]["pred_gib"] == pytest.approx(25.0)
    assert by["P3nc_pos_chemistry"]["rows"] == 1_200_000                 # nocentre: 1.2 x parent rows
    assert by["P3nc_pos_chemistry"]["basis"] == "nocentre_1.2x_parent"
    assert by["P3nc_pos_chemistry"]["pred_gib"] == pytest.approx(30.0)
    assert by["loeo_rank"]["rows"] == 0 and by["loeo_rank"]["pred_gib"] == pytest.approx(pp.MIN_GIB)
    # a parent frame the plan cannot count is a STOP, never a guess
    out2 = pp.plan([_unit("x", "P2_d7_p05_econ", "p2", "p2_becoming_econ.csv")], rows, {})
    assert out2["verdict"] == "STOP" and out2["stops"][0]["reason"] == "FRAME_MISSING"


def test_plan_records_the_joblist_digest_and_a_split(tmp_path, monkeypatch):
    frames = tmp_path / "frames"
    frames.mkdir()
    _parquet(frames / "a.parquet", 10)
    units = [_unit("g1", f"a{i}", "perm_p3tp", "a.parquet", threads=4, est_min=100) for i in range(32)] + \
            [_unit("g2", f"b{i}", "perm_p3tp", "a.parquet", threads=4, est_min=100) for i in range(32)] + \
            [_unit("g3", f"c{i}", "perm_p3tp", "a.parquet", threads=4, est_min=100) for i in range(16)]
    tsv = _tsv(tmp_path / "units.tsv", units)
    monkeypatch.setenv("SAR_HOST", "ec2-r1")
    rc = pp.main(["--jobs", str(tsv), "--frames", str(frames), "--calib", str(_mem_report(tmp_path / "m.json")),
                  "--out", str(tmp_path / "out"), "--overhead-min", "0"])
    assert rc == 0
    plan = json.loads((tmp_path / "out" / "plan.json").read_text())
    assert plan["joblist_sha256"] == hashlib.sha256(tsv.read_bytes()).hexdigest()
    # each group: par 16 (64 // 4; memory is tiny), ceil(n/16) x 100 min -> 200 + 200 + 100 = 500 <= 540: no split
    # (no launch overhead here: --overhead-min 0; with J1b's real overhead see test_stage_overhead_counts_toward_the_split)
    assert [g["par"] for g in plan["groups"]] == [16, 16, 16]
    assert plan["wall_min_total"] == 500 and plan["split_after"] is None
    assert plan["launches"] == [["g1", "g2", "g3"]]

    # 4 more units in g3: 200 + 200 + 200 = 600 > 540 -> split after g2, two launches (R11)
    units += [_unit("g3", f"d{i}", "perm_p3tp", "a.parquet", threads=4, est_min=100) for i in range(4)]
    out = pp.plan(units, {"a.parquet": 10}, {}, joblist_sha256="abc")
    assert out["verdict"] == "OK" and out["joblist_sha256"] == "abc"
    assert out["wall_min_total"] == 600
    assert out["split_after"] == "g2"
    assert out["launches"] == [["g1", "g2"], ["g3"]]
    assert all(math.ceil(g["n_units"] / g["par"]) * g["est_min"] == g["wall_min"] for g in out["groups"])

    # More than two launches' worth cannot be joined by one --resume-from: STOP, named.
    big = [_unit(f"h{k}", f"h{k}_{i}", "perm_p3tp", "a.parquet", threads=64, est_min=300) for k in range(4)
           for i in range(1)]
    out3 = pp.plan(big, {"a.parquet": 10}, {})
    assert out3["verdict"] == "STOP" and any(s["reason"] == "WALL" for s in out3["stops"])


def test_refuses_off_the_r1_hosts(tmp_path, monkeypatch):
    tsv = _tsv(tmp_path / "units.tsv", [_unit("g", "u", "p1", "-")])
    monkeypatch.delenv("SAR_HOST", raising=False)
    with pytest.raises(SystemExit) as e:
        pp.main(["--jobs", str(tsv), "--frames", str(tmp_path), "--calib", str(_mem_report(tmp_path / "m.json")),
                 "--out", str(tmp_path / "out")])
    assert "SAR_HOST" in str(e.value)
    assert not (tmp_path / "out").exists()


def test_october_stage_tables_do_not_reference_par_plan():
    for job in ("jp", "j0"):
        text = (REPO / "config" / "r1" / "stages" / f"{job}.json").read_text(encoding="utf-8")
        assert "par_plan" not in text, job


# ---- M review #12: the wall model follows run_units.execute and the launch overhead ---------------------------
def test_post_units_run_one_at_a_time():
    """run_units runs kind-post units at width 1 after the rest; the planner gave them par = n (2 min, not 22)."""
    units = [_unit("post", f"p{i}", "post", "-", threads=1, est_min=2) for i in range(11)]
    (g,) = pp.plan(units, {}, {}, overhead_min=0)["groups"]
    assert g["wall_min"] == 22


def test_control_chain_sets_the_floor():
    """A needs_control chain inside a group waits: nocentre_build (25) -> nocentre_pos_build (5) is 30 min even
    with par 16 (before: 25)."""
    units = [_unit("frames", "A", "build", "-", est_min=25),
             dict(_unit("frames", "B", "build", "-", est_min=5), needs_control="A"),
             dict(_unit("frames", "C", "build", "-", est_min=5), needs_control="not_in_this_group")]
    (g,) = pp.plan(units, {}, {}, overhead_min=0)["groups"]
    assert g["par"] == 3 and g["wall_min"] == 30


def test_stage_overhead_counts_toward_the_split():
    """Groups summing to 500 unit-minutes plus J1b's ~83 min of other stages exceed the 540 budget: split (before:
    None, and the 600-min fuse would fire)."""
    units = [_unit(f"g{k}", f"u{k}_{i}", "perm_p3tp", "a.parquet", threads=4, est_min=100)
             for k, n in ((1, 32), (2, 32), (3, 16)) for i in range(n)]
    out = pp.plan(units, {"a.parquet": 10}, {}, overhead_min=83)
    assert out["wall_min_total"] == 500 and out["overhead_min"] == 83
    assert out["split_after"] == "g2" and out["launches"] == [["g1", "g2"], ["g3"]]
    assert pp.plan(units, {"a.parquet": 10}, {}, overhead_min=0)["split_after"] is None
    assert pp.plan(units, {"a.parquet": 10}, {})["overhead_min"] == pp.OVERHEAD_MIN     # the default is J1b's


def test_overhead_default_is_j1b_s_non_unit_stages():
    """OVERHEAD_MIN = the est_min of config/r1/stages/j1b.json's stages that are not a run_units group stage."""
    cfg = json.loads((REPO / "config" / "r1" / "robustness_r1.json").read_text(encoding="utf-8"))
    groups = {s for g, s in cfg["stage_of_group"].items() if g != "jobs"}
    stages = json.loads((REPO / "config" / "r1" / "stages" / "j1b.json").read_text(encoding="utf-8"))["stages"]
    assert groups <= {s["name"] for s in stages}
    assert sum(s["est_min"] for s in stages if s["name"] not in groups) == pp.OVERHEAD_MIN


# ---- j1b-01: memory packing (a group's heaviest unit no longer sets everyone's width) -----------------------
def test_light_units_run_beside_heavy_ones():
    """j1b-01 stopped (WALL, 926 min): every group ran at the width of its heaviest unit, so 66 light
    permutation units (~4 GiB) ran 3 at a time beside 101 heavy ones (~136 GiB). The group width is now the
    thread limit, and the runner packs units by predicted memory under the budget; the wall is simulated."""
    heavy = [_unit("perm", f"h{i}", "perm_p3tp", "big.parquet", est_min=7) for i in range(9)]
    light = [_unit("perm", f"l{i}", "perm_p1", "small.csv", est_min=6) for i in range(39)]
    out = pp.plan(heavy + light, {"big.parquet": 5_440_000, "small.csv": 140_000}, {}, overhead_min=0)
    (g,) = out["groups"]
    assert g["par"] == 3                                  # the heaviest unit's width, as before
    assert g["width"] == 16 and g["budget_gib"] == 450.0  # 64 // 4 threads; the run-time memory budget
    assert {u["name"]: u["pred_gib"] for u in g["units"]}["l0"] == pytest.approx(3.5)
    # t=0: 3 heavy (408 GiB) + 12 light (42 GiB); light waves at 6, 12, 18; heavy waves at 7, 14 -> done at 24
    assert g["wall_min"] == 24
    assert g["wall_min"] < math.ceil(48 / 3) * 7          # 112 min when every unit ran at width 3


def test_uniform_groups_keep_their_wall():
    """Units of one prediction: packing gives the old width, so the wall is still ceil(n / par) x est_min."""
    units = [_unit("g", f"u{i}", "p3tp", "a.parquet", est_min=10) for i in range(20)]
    (g,) = pp.plan(units, {"a.parquet": 2_000_000}, {}, overhead_min=0)["groups"]
    assert g["par"] == 9 and g["width"] == 16
    assert g["wall_min"] == math.ceil(20 / 9) * 10


def test_units_ending_together_free_their_memory_together():
    """Codex delta-3 #7: run_units sees every unit that finished by the same time at once; the simulation does
    too. A and B (225 GiB) end at 10; H (450) then runs alone; D (needs H) and L start at 20 and L ends at 120."""
    def u(name, gib, est, needs=""):
        return {"name": name, "kind": "perm_p1", "pred_gib": gib, "est_min": est, "needs_control": needs}
    recs = [u("A", 225, 10), u("B", 225, 10), u("H", 450, 10), u("D", 1, 100, needs="H"), u("L", 225, 100)]
    assert pp.group_wall(recs, 5, 450.0) == 120
