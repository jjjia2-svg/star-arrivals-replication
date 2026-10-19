# -*- coding: utf-8 -*-
"""pipeline/aws/r1/run_cells.py and config/r1/cells/oct29.tsv (fake Rscript, toy golds)."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import pathlib
import re
import stat
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import run_cells as rc   # noqa: E402

CELLS = REPO / "config" / "r1" / "cells" / "oct29.tsv"


def _rows():
    with open(CELLS, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def test_oct29_has_the_29_golds_25_rmac_and_4_rcloud():
    rows = _rows()
    assert sorted(r["out_name"] for r in rows) == sorted(p.name for p in (REPO / "analysis" / "expected").glob("*.json"))
    assert sum(r["stack"] == "rmac" for r in rows) == 25 and sum(r["stack"] == "rcloud" for r in rows) == 4


#: the 25 local cells analysis/run_all.sh ran, in its order, while it still listed them itself (before it read
#: the canon's cell lists): (label, driver, frame, ref, out_name). The P3cut cells were renamed to the gold's name.
RUN_ALL_25 = [
    ("P1_econ_fnfix", "analysis/estimation/run_p1.R", "p1_frame_econ.csv", "-", "P1_econ_fnfix.json"),
    ("P1_fnfix_chemistry", "analysis/estimation/run_p1.R", "p1_frame_chemistry.csv", "-", "P1_fnfix_chemistry.json"),
    ("P1_fnfix_math_stats", "analysis/estimation/run_p1.R", "p1_frame_math_stats.csv", "-", "P1_fnfix_math_stats.json"),
    ("P1_econ_fnfix_old79", "analysis/estimation/run_p1.R", "p1_frame_econ_old79.csv", "-", "P1_econ_fnfix_old79.json"),
    ("P1_econ_fnfix_new37", "analysis/estimation/run_p1.R", "p1_frame_econ_new37.csv", "-", "P1_econ_fnfix_new37.json"),
    ("P2_econ_fnfix", "analysis/estimation/run_p2.R", "p2_becoming_econ.csv", "-", "P2_econ_fnfix.json"),
    ("P2_fnfix_chemistry", "analysis/estimation/run_p2.R", "p2_becoming_chemistry.csv", "-", "P2_fnfix_chemistry.json"),
    ("P2_fnfix_math_stats", "analysis/estimation/run_p2.R", "p2_becoming_math_stats.csv", "-", "P2_fnfix_math_stats.json"),
    ("P3_fnfix_math_stats", "analysis/estimation/run_p3.R", "p3_slim_math_stats.parquet", "-", "P3_fnfix_math_stats.json"),
    ("P1evcl_econ", "analysis/estimation/run_p1_evcl.R", "p1_frame_econ.csv", "P1_econ_fnfix.json", "P1evcl_econ.json"),
    ("P1evcl_chemistry", "analysis/estimation/run_p1_evcl.R", "p1_frame_chemistry.csv", "P1_fnfix_chemistry.json",
     "P1evcl_chemistry.json"),
    ("P1evcl_math_stats", "analysis/estimation/run_p1_evcl.R", "p1_frame_math_stats.csv", "P1_fnfix_math_stats.json",
     "P1evcl_math_stats.json"),
    ("P2evcl_econ", "analysis/estimation/run_p2_evcl.R", "p2_becoming_econ.csv", "P2_econ_fnfix.json", "P2evcl_econ.json"),
    ("P2evcl_chemistry", "analysis/estimation/run_p2_evcl.R", "p2_becoming_chemistry.csv", "P2_fnfix_chemistry.json",
     "P2evcl_chemistry.json"),
    ("P2evcl_math_stats", "analysis/estimation/run_p2_evcl.R", "p2_becoming_math_stats.csv", "P2_fnfix_math_stats.json",
     "P2evcl_math_stats.json"),
    ("P3evcl_math_stats", "analysis/estimation/run_p3_evcl.R", "p3_slim_ev_math_stats.parquet", "P3_fnfix_math_stats.json",
     "P3evcl_math_stats.json"),
    ("P3lb_math_stats_A_far", "analysis/estimation/run_p3_tp.R", "p3_afar_math_stats.parquet", "-",
     "P3lb_math_stats_A_far.json"),
    ("P3lb_chemistry_A_far", "analysis/estimation/run_p3_tp.R", "p3_afar_chemistry.parquet", "-",
     "P3lb_chemistry_A_far.json"),
    ("P3lb_econ_A_far", "analysis/estimation/run_p3_tp.R", "p3_afar_econ.parquet", "-", "P3lb_econ_A_far.json"),
    ("P3cut_pos_math_stats", "analysis/estimation/run_p3_tp.R", "p3_afar_pos_math_stats.parquet", "-",
     "P3pos_math_stats_A_far.json"),
    ("P3cut_med_math_stats", "analysis/estimation/run_p3_tp.R", "p3_afar_med_math_stats.parquet", "-",
     "P3med_math_stats_A_far.json"),
    ("P3cut_pos_chemistry", "analysis/estimation/run_p3_tp.R", "p3_afar_pos_chemistry.parquet", "-",
     "P3pos_chemistry_A_far.json"),
    ("P3cut_med_chemistry", "analysis/estimation/run_p3_tp.R", "p3_afar_med_chemistry.parquet", "-",
     "P3med_chemistry_A_far.json"),
    ("P3cut_pos_econ", "analysis/estimation/run_p3_tp.R", "p3_afar_pos_econ.parquet", "-", "P3pos_econ_A_far.json"),
    ("P3cut_med_econ", "analysis/estimation/run_p3_tp.R", "p3_afar_med_econ.parquet", "-", "P3med_econ_A_far.json"),
]


def test_oct29_rmac_rows_are_the_25_cells_run_all_ran_before_it_read_the_cell_lists():
    got = [(r["label"], r["driver"], r["frame"], r["ref"], r["out_name"]) for r in _rows() if r["stack"] == "rmac"]
    assert got == RUN_ALL_25
    # run_all.sh now runs the canon's cell lists and lists no cell of its own
    sh = (REPO / "analysis" / "run_all.sh").read_text(encoding="utf-8")
    assert "run_all_stages.py cells" in sh
    assert not re.search(r"^\s*run \S+\s+Rscript \S*(?:\$E/|estimation/)", sh, re.M), "run_all.sh holds a cell of its own"


def test_oct29_rcloud_rows_equal_the_october_serial_commands():
    """JP review #1 (FIX-JP): the rcloud rows are the commands October's cloud batch actually ran -
    cloudkit.serial_jobs, `Rscript <driver> <label> <frame>` with NO reference argument. A ref here would make
    run_p3_evcl.R add point_estimate_check, a key the two frozen cloud golds lack, so JP would report a
    spurious DIFF (compare_json rejects extra keys)."""
    spec = importlib.util.spec_from_file_location("ck", REPO / "pipeline" / "aws" / "cal2026-10" / "cloudkit.py")
    ck = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ck)
    want = set()
    for lab, _outdir, cmd in ck.serial_jobs({"p3main", "p3evcl"}, False, []):
        argv = cmd.split()
        assert argv[0] == "Rscript" and argv[2] == lab and len(argv) in (4, 5), cmd
        want.add((lab, f"analysis/estimation/{argv[1]}", argv[3],
                  pathlib.PurePosixPath(argv[4]).name if len(argv) == 5 else "-"))
    assert len(want) == 4
    assert {(r["label"], r["driver"], r["frame"], r["ref"]) for r in _rows() if r["stack"] == "rcloud"} == want


FAKE_R = r'''#!/usr/bin/env python3
import json, os, sys
open(os.environ["FAKE_R_LOG"], "a").write(json.dumps(sys.argv[1:]) + "\n")
label = sys.argv[2]
if os.environ.get("FAKE_R_TOUCH"): open(sys.argv[3], "a").write("touched by the cell\n")
if label == "BOOM": sys.exit(4)
json.dump({"label": label, "ATE": float(os.environ.get("FAKE_ATE", "1.0"))}, open(os.path.join(os.environ["SAR_OUT"], label + ".json"), "w"))
'''


@pytest.fixture
def cells(tmp_path, monkeypatch):
    rbin = tmp_path / "R" / "bin"
    rbin.mkdir(parents=True)
    (rbin / "Rscript").write_text(FAKE_R.replace("#!/usr/bin/env python3", "#!" + sys.executable, 1))
    (rbin / "Rscript").chmod(0o755)
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    monkeypatch.setenv("SAR_RSCRIPT_RMAC", str(rbin / "Rscript"))
    monkeypatch.setenv("SAR_RLIB_RMAC", str(tmp_path / "lib"))
    monkeypatch.setenv("FAKE_R_LOG", str(tmp_path / "r.log"))
    gold = tmp_path / "gold"
    gold.mkdir()
    for lab, out in (("A", "A.json"), ("P3cut_pos_econ", "P3pos_econ_A_far.json")):
        (gold / out).write_text(json.dumps({"label": lab, "ATE": 1.0}))
    tsv = tmp_path / "cells.tsv"
    tsv.write_text("label\tdriver\tframe\tref\tout_name\tstack\n"
                   "A\tanalysis/estimation/run_p1.R\tf.csv\t-\tA.json\trmac\n"
                   "P3cut_pos_econ\tanalysis/estimation/run_p3_tp.R\tg.parquet\tA.json\tP3pos_econ_A_far.json\trmac\n"
                   "C\tanalysis/estimation/run_p3.R\th.parquet\t-\tC.json\trcloud\n")
    return tmp_path, gold, tsv


def _main(tmp_path, gold, tsv, *extra):
    return rc.main(["--cells", str(tsv), "--stack", "rmac", "--repo", str(REPO), "--frames", str(tmp_path / "frames"),
                    "--gold-dir", str(gold), "--out", str(tmp_path / "out"), "--compare", *extra])


def test_cells_run_rename_compare_and_skip_the_other_stack(cells, monkeypatch):
    tmp_path, gold, tsv = cells
    assert _main(tmp_path, gold, tsv) == 0
    rep = json.loads((tmp_path / "out" / "cells_report_rmac.json").read_text())
    assert set(rep) == {"A", "P3cut_pos_econ"} and all(v["status"] == "EQUAL" for v in rep.values())
    assert (tmp_path / "out" / "estimates" / "P3pos_econ_A_far.json").is_file()
    calls = [json.loads(l) for l in (tmp_path / "r.log").read_text().splitlines()]
    assert calls[1][-1] == str(gold / "A.json") and len(calls[0]) == 3       # ref only when not '-'


def test_a_diff_is_reported_and_require_equal_fails(cells, monkeypatch):
    tmp_path, gold, tsv = cells
    monkeypatch.setenv("FAKE_ATE", "2.0")
    assert _main(tmp_path, gold, tsv) == 0
    assert json.loads((tmp_path / "out" / "cells_report_rmac.json").read_text())["A"]["status"] == "DIFF"
    assert _main(tmp_path, gold, tsv, "--require-equal") == 1


def _hashes(path):
    b = pathlib.Path(path).read_bytes()
    return hashlib.sha256(b).hexdigest(), hashlib.md5(b).hexdigest()


def test_cell_report_records_input_sha256_and_md5(cells, monkeypatch):
    """F23/F26: gate 1 custody and the R1 custody spec read each cell's inputs, hashed BEFORE the R call."""
    tmp_path, gold, tsv = cells
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "f.csv").write_text("a,b\n1,2\n")
    (frames / "g.parquet").write_bytes(b"PAR1 toy bytes")
    before = {n: _hashes(frames / n) for n in ("f.csv", "g.parquet")}
    monkeypatch.setenv("FAKE_R_TOUCH", "1")                         # the cell rewrites its frame after the hash
    assert _main(tmp_path, gold, tsv) == 0
    rep = json.loads((tmp_path / "out" / "cells_report_rmac.json").read_text())
    assert _hashes(frames / "f.csv") != before["f.csv"]
    a, p = rep["A"]["inputs"], rep["P3cut_pos_econ"]["inputs"]
    assert a["frame"] == {"name": "f.csv", "sha256": before["f.csv"][0], "md5": before["f.csv"][1]}
    assert a["ref"] is None
    assert p["frame"] == {"name": "g.parquet", "sha256": before["g.parquet"][0], "md5": before["g.parquet"][1]}
    sha, md5 = _hashes(gold / "A.json")
    assert p["ref"] == {"name": "A.json", "sha256": sha, "md5": md5}
    sha, md5 = _hashes(REPO / "analysis" / "estimation" / "run_p1.R")
    assert a["driver"] == {"name": "analysis/estimation/run_p1.R", "sha256": sha, "md5": md5}
    assert p["driver"]["name"] == "analysis/estimation/run_p3_tp.R" and len(p["driver"]["sha256"]) == 64
    (frames / "f.csv").unlink()                                     # a missing input is recorded, never invented
    monkeypatch.delenv("FAKE_R_TOUCH")
    assert _main(tmp_path, gold, tsv) == 0
    rep = json.loads((tmp_path / "out" / "cells_report_rmac.json").read_text())
    assert rep["A"]["inputs"]["frame"] == {"name": "f.csv", "sha256": None, "md5": None}


def test_a_cell_that_fails_fails_the_stage(cells):
    tmp_path, gold, tsv = cells
    tsv.write_text(tsv.read_text() + "BOOM\tanalysis/estimation/run_p1.R\tf.csv\t-\tBOOM.json\trmac\n")
    assert _main(tmp_path, gold, tsv) == 1
    assert json.loads((tmp_path / "out" / "cells_report_rmac.json").read_text())["BOOM"]["status"] == "FAIL"
