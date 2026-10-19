# -*- coding: utf-8 -*-
"""pipeline/aws/r1/mem_probe.py (J0-MEAS.3k): fake /usr/bin/time and fake Rscript, toy parquet frames.

No R runs and no real frame is read: the 'frames' are three-row parquet files written in tmp_path.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import mem_probe as mp   # noqa: E402

FIELDS = ("econ", "chemistry", "math_stats")

FAKE_TIME = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
args = sys.argv[1:]
assert args[0] == "-v", args
open(os.environ["FAKE_TIME_LOG"], "a").write(json.dumps(args[1:]) + "\n")
rc = subprocess.run(args[1:]).returncode
sys.stderr.write("\tCommand being timed: \"x\"\n")
sys.stderr.write("\tElapsed (wall clock) time (h:mm:ss or m:ss): " + os.environ.get("FAKE_ELAPSED", "1:02.50") + "\n")
sys.stderr.write("\tMaximum resident set size (kbytes): " + os.environ.get("FAKE_PEAK_KB", "1048576") + "\n")
sys.exit(rc)
'''

FAKE_R = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
a = sys.argv[1:]
keep = ("R_DATATABLE_NUM_THREADS", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "R_LIBS", "SAR_OUT")
open(os.environ["FAKE_R_LOG"], "a").write(json.dumps({"argv": a, "cwd": os.getcwd(),
                                                       "env": {k: os.environ.get(k) for k in keep}}) + "\n")
drv = os.path.basename(a[0])
lab = a[2] if drv == "run_perm.R" else a[1]
if lab == os.environ.get("FAKE_R_FAIL"):
    sys.exit(3)
if drv == "run_perm.R":
    out = pathlib.Path(os.environ["SAR_OUT"]) / f"{lab}_perm_{a[6]}_{a[7]}.csv"
else:
    out = pathlib.Path(a[6]) / f"{lab}_null_{a[4]}_{a[5]}.csv"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("perm,ate\n1,0.0\n")
'''


def _exe(p: pathlib.Path, src: str) -> pathlib.Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src.replace("#!/usr/bin/env python3", "#!" + sys.executable, 1))
    p.chmod(0o755)
    return p


def _parquet(p: pathlib.Path, n: int) -> None:
    pq.write_table(pa.table({"ev": list(range(n)), "y": [0] * n}), p)


@pytest.fixture
def probe(tmp_path, monkeypatch):
    frames = tmp_path / "frames"
    frames.mkdir()
    for i, f in enumerate(FIELDS):
        _parquet(frames / f"p3_afar_pos_{f}.parquet", 10 + i)
        _parquet(frames / f"p3_slim_{f}.parquet", 20 + i)
        _parquet(frames / f"p3_slim_ev_{f}.parquet", 30 + i)
    _parquet(frames / "pairs_none_chemistry.parquet", 7)
    rscript = _exe(tmp_path / "R" / "bin" / "Rscript", FAKE_R)
    time_bin = _exe(tmp_path / "bin" / "time", FAKE_TIME)
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    monkeypatch.setenv("SAR_RSCRIPT_RCLOUD", str(rscript))
    monkeypatch.setenv("SAR_RLIB_RCLOUD", str(tmp_path / "rlib"))
    monkeypatch.setenv("FAKE_R_LOG", str(tmp_path / "r.log"))
    monkeypatch.setenv("FAKE_TIME_LOG", str(tmp_path / "time.log"))
    monkeypatch.delenv("FAKE_R_FAIL", raising=False)
    return tmp_path, frames, time_bin


def _main(tmp_path, frames, time_bin, *extra):
    return mp.main(["--frames", str(frames), "--repo", str(REPO), "--stack", "rcloud", "--threads", "4",
                    "--seed", "20260830", "--out", str(tmp_path / "out"), "--time-bin", str(time_bin), *extra])


def _report(tmp_path):
    return json.loads((tmp_path / "out" / "mem_report.json").read_text())


def test_peak_and_wall_are_parsed_from_time_v(probe):
    tmp_path, frames, time_bin = probe
    assert mp.parse_time_v("\tElapsed (wall clock) time (h:mm:ss or m:ss): 1:02:03\n"
                           "\tMaximum resident set size (kbytes): 2097152\n") == (2.0, 3723.0)
    assert mp.parse_time_v("nothing here") == (None, None)
    assert _main(tmp_path, frames, time_bin, "--fields", "econ") == 0
    rep = _report(tmp_path)
    assert rep["schema"] == "sar.r1.mem_probe.v1" and rep["stack"] == "rcloud" and rep["threads"] == 4
    for kind in ("perm", "null"):
        u = rep["fields"]["econ"]["units"][kind]
        assert u["rc"] == 0 and u["status"] == "OK" and u["peak_gib"] == 1.0 and u["wall_s"] == 62.5
    summ = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert summ["status"] == "OK" and summ["units_run"] == 2 and summ["units_failed"] == 0
    assert summ["peak_gib_max"] == 1.0


def test_rows_come_from_parquet_metadata(probe):
    tmp_path, frames, time_bin = probe
    rows, absent = mp.frame_rows(frames, "chemistry")
    assert rows == {"p3_afar_pos": 11, "p3_slim": 21, "p3_slim_ev": 31, "p3_slim_dosebin3": None,
                    "p3_slim_p05": None, "pairs": 7}
    assert absent == ["p3_slim_dosebin3", "p3_slim_p05"]
    assert _main(tmp_path, frames, time_bin) == 0
    rep = _report(tmp_path)
    assert [rep["fields"][f]["rows"]["p3_afar_pos"] for f in FIELDS] == [10, 11, 12]
    assert rep["fields"]["econ"]["rows"]["pairs"] is None and "pairs" in rep["fields"]["econ"]["absent"]
    # a missing p3_afar_pos is an error: no unit runs for that field and the probe returns 1
    (frames / "p3_afar_pos_math_stats.parquet").unlink()
    with pytest.raises(mp.FrameMissing):
        mp.frame_rows(frames, "math_stats")
    assert _main(tmp_path, frames, time_bin) == 1
    rep = _report(tmp_path)
    assert rep["status"] == "FAIL" and rep["fields"]["math_stats"]["status"] == "FAIL"
    assert rep["fields"]["math_stats"]["units"] == {}
    assert rep["fields"]["econ"]["status"] == "OK"


def _october(f, seed):
    spec = importlib.util.spec_from_file_location("ck", REPO / "pipeline" / "aws" / "cal2026-10" / "cloudkit.py")
    ck = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ck)
    jobs = ck.parallel_jobs({"perm", "null"}, (f,), 1, 1, seed, seed, {f"perm_{f}": 1, f"null_{f}": 1})
    got = {}
    for name, _outdir, cmd in jobs:
        if name.endswith("_1_1"):
            got["perm" if "_perm_" in name else "null"] = cmd.split()
    return got


@pytest.mark.parametrize("f", FIELDS)
def test_unit_commands_follow_the_october_grammar(probe, f):
    tmp_path, frames, _ = probe
    ref = tmp_path / "out" / "stub_ref.json"
    built = mp.unit_argv(f, rscript="/opt/r/bin/Rscript", repo=REPO, frames=frames, ref=ref, seed=20260830)
    oct_ = _october(f, 20260830)
    assert set(built) == set(oct_) == {"perm", "null"}

    def norm(argv, label, ref_tok=None):
        out = [os.path.basename(t) for t in argv]
        out[out.index(label)] = "<LABEL>"
        if ref_tok is not None:
            out[out.index(ref_tok)] = "<REF>"
        return out

    assert norm(built["perm"], f"PROBE_{f}", ref.name) == norm(oct_["perm"], f"P3cutpos_{f}", f"P3cut_pos_{f}.json")
    assert norm(built["null"], f"NULLPROBE_{f}") == norm(oct_["null"], f"NULLpos_{f}")
    assert built["perm"][1] == str(REPO / "analysis/robustness/inference/run_perm.R")
    assert built["null"][1] == str(REPO / "analysis/robustness/null_sim/run_null.R")
    assert built["perm"][4] == str(frames / f"p3_afar_pos_{f}.parquet") == built["null"][3]
    assert built["perm"][-2:] == ["1", "1"]                  # never perm 0 (the identity control)


def test_threads_and_stack_env_reach_every_unit(probe):
    tmp_path, frames, time_bin = probe
    assert _main(tmp_path, frames, time_bin, "--fields", "chemistry") == 0
    calls = [json.loads(l) for l in (tmp_path / "r.log").read_text().splitlines()]
    assert len(calls) == 2
    for c in calls:
        e = c["env"]
        assert e["R_DATATABLE_NUM_THREADS"] == e["OMP_NUM_THREADS"] == e["OPENBLAS_NUM_THREADS"] == "4"
        assert e["R_LIBS"] == str(tmp_path / "rlib")
        assert pathlib.Path(c["cwd"]).resolve().is_relative_to((tmp_path / "out").resolve())
    timed = [json.loads(l) for l in (tmp_path / "time.log").read_text().splitlines()]
    assert [t[0] for t in timed] == [os.environ["SAR_RSCRIPT_RCLOUD"]] * 2


def test_failed_unit_gives_rc1_and_status_fail(probe, monkeypatch):
    tmp_path, frames, time_bin = probe
    monkeypatch.setenv("FAKE_R_FAIL", "NULLPROBE_econ")
    assert _main(tmp_path, frames, time_bin) == 1
    rep = _report(tmp_path)
    assert rep["status"] == "FAIL"
    assert rep["fields"]["econ"]["units"]["null"]["status"] == "FAIL"
    assert rep["fields"]["econ"]["units"]["null"]["rc"] == 3
    assert rep["fields"]["econ"]["units"]["perm"]["status"] == "OK"
    assert rep["fields"]["chemistry"]["status"] == "OK"
    summ = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert summ["status"] == "FAIL" and summ["units_failed"] == 1 and summ["units_run"] == 6


def test_refuses_off_instance_and_never_reads_the_october_golds(probe, monkeypatch):
    tmp_path, frames, time_bin = probe
    monkeypatch.delenv("SAR_HOST")
    with pytest.raises(SystemExit):
        _main(tmp_path, frames, time_bin)
    assert not (tmp_path / "out").exists()
    monkeypatch.setenv("SAR_HOST", "laptop")
    with pytest.raises(SystemExit):
        _main(tmp_path, frames, time_bin)
    monkeypatch.setenv("SAR_HOST", "ec2-r1")
    with pytest.raises(SystemExit):                          # --out inside the October golds is refused
        mp.main(["--frames", str(frames), "--repo", str(REPO), "--stack", "rcloud", "--threads", "4",
                 "--seed", "20260830", "--out", str(REPO / "analysis" / "expected" / "probe"),
                 "--time-bin", str(time_bin)])
    assert not (REPO / "analysis" / "expected" / "probe").exists()
    assert _main(tmp_path, frames, time_bin, "--fields", "econ") == 0
    stub = tmp_path / "out" / "stub_ref.json"
    assert json.loads(stub.read_text()) == {"pair_cluster": {"ate": 0}, "event_cluster": {"se": 0}}
    perm = [json.loads(l)["argv"] for l in (tmp_path / "r.log").read_text().splitlines()][0]
    assert perm[4] == str(stub)
    assert not any("analysis/expected" in t or "cal2026-10" in t for t in perm)
