# -*- coding: utf-8 -*-
"""pipeline/aws/r1/run_units.py (P3e F19, unit W1-ROB): statuses, exit codes, controls, thread budget.

A fake Rscript (python, in tmp_path, as tests/test_r1_cells.py) writes the JSON shapes the real drivers
write; no R runs and no frame is read.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import rob_jobs_r1 as rj   # noqa: E402
import run_units as ru     # noqa: E402

FAKE_R = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
a = sys.argv[1:]
drv = pathlib.Path(a[0]).name
lab = a[2] if drv in ("run_p1_variant.R", "run_predate.R") else a[1]
env = {k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                                      "R_DATATABLE_NUM_THREADS", "POLARS_MAX_THREADS")}
open(os.environ["FAKE_R_LOG"], "a").write(json.dumps({"label": lab, "env": env}) + "\n")
act = json.loads(os.environ.get("FAKE_ACT", "{}")).get(lab, "ok")
if act == "rc4": sys.exit(4)
if act == "oom": os.kill(os.getpid(), 9)
if act == "killed": print("Killed"); sys.exit(1)
j = {"label": lab, "status": "OK", "ate": 1.0}
if act == "failed": j["status"] = "FAILED"                                    # P2 shape
if act == "aux": j["predate"] = {"aux_status": "FAILED"}                      # run_predate shape
if act == "union": j = {"label": lab, "channels": {"union": {"status": "FAILED"}}}   # P1 shape
if act == "ate2": j["ate"] = 2.0
json.dump(j, open(os.path.join(os.environ["SAR_OUT"], lab + ".json"), "w"))
'''


@pytest.fixture
def env(tmp_path, monkeypatch):
    rbin = tmp_path / "R" / "bin"
    rbin.mkdir(parents=True)
    (rbin / "Rscript").write_text(FAKE_R.replace("#!/usr/bin/env python3", "#!" + sys.executable, 1))
    (rbin / "Rscript").chmod(0o755)
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    for st in ("RMAC", "RCLOUD"):
        monkeypatch.setenv(f"SAR_RSCRIPT_{st}", str(rbin / "Rscript"))
        monkeypatch.setenv(f"SAR_RLIB_{st}", str(tmp_path / "lib"))
    monkeypatch.setenv("FAKE_R_LOG", str(tmp_path / "r.log"))
    return tmp_path


def _u(name, *, kind="p1", cmd=None, needs="", outdir="cells_out", group="cells"):
    return rj.Unit(group, name, kind, "p1_frame_econ.csv", 4, 1,
                   cmd or f"Rscript analysis/estimation/run_p1.R {name} /x/p1_frame_econ.csv", outdir, needs)


def _run(tmp, units, *, par=1, threads=2, digest=None, extra=()):
    tsv = tmp / "units.tsv"
    sha = rj.write_tsv(units, tsv)
    plan = tmp / "plan.json"
    plan.write_text(json.dumps({"joblist_sha256": digest or sha, "verdict": "OK",
                                "groups": [{"group": "cells", "threads": threads, "par": par, "pred_gib": 1.0}]}))
    code = ru.main(["--units", str(tsv), "--group", "cells", "--plan", str(plan), "--root", str(tmp / "rob"),
                    "--repo", str(REPO), "--out", str(tmp / "out"), *extra])
    rep = json.loads((tmp / "out" / "units_report_cells.json").read_text())
    return code, rep["units"]


def _called(tmp) -> list[str]:
    p = tmp / "r.log"
    return [json.loads(x)["label"] for x in p.read_text().splitlines()] if p.is_file() else []


def test_estimator_failure_is_recorded_and_the_batch_continues(env, monkeypatch):
    monkeypatch.setenv("FAKE_ACT", json.dumps({"A": "failed", "B": "aux", "C": "union"}))
    units = [_u("A", kind="p2", cmd="Rscript analysis/estimation/run_p2.R A /x/p2.csv"),
             _u("B", kind="p2", cmd="Rscript analysis/robustness/predate/run_predate.R p2 B /x/p2.csv 2"),
             _u("C"), _u("D")]
    code, rep = _run(env, units)
    assert code == 0
    assert {n: rep[n]["status"] for n in "ABCD"} == {"A": "ESTIMATE_FAILED", "B": "ESTIMATE_FAILED",
                                                     "C": "ESTIMATE_FAILED", "D": "OK"}
    assert rep["A"]["detail"] == "FAILED" and "aux_status" in rep["B"]["detail"] and "union" in rep["C"]["detail"]
    assert sorted(_called(env)) == ["A", "B", "C", "D"]


def test_nonzero_rc_fails_the_stage_after_the_group(env, monkeypatch):
    monkeypatch.setenv("FAKE_ACT", json.dumps({"A": "rc4"}))
    code, rep = _run(env, [_u("A"), _u("B"), _u("C")])
    assert code == 1
    assert rep["A"]["status"] == "FAIL" and rep["A"]["rc"] == 4
    assert rep["B"]["status"] == rep["C"]["status"] == "OK" and _called(env) == ["A", "B", "C"]


@pytest.mark.parametrize("act", ["oom", "killed"])
def test_oom_stops_at_once(env, monkeypatch, act):
    monkeypatch.setenv("FAKE_ACT", json.dumps({"A": act}))
    code, rep = _run(env, [_u("A"), _u("B"), _u("C")], par=1)
    assert code == 4
    assert rep["A"]["status"] == "OOM" and rep["B"]["status"] == rep["C"]["status"] == "NOT_STARTED"
    assert _called(env) == ["A"]


def test_control_mismatch_stops_dependent_cells(env, monkeypatch):
    ref = env / "ref"
    ref.mkdir()
    (ref / "G.json").write_text(json.dumps({"label": "G", "status": "OK", "ate": 1.0}))
    (ref / "U.json").write_text(json.dumps({"label": "U", "channels": {"union": {"ate": 1.0}, "dept": {"ate": 9.0}}}))
    rob = env / "rob"
    monkeypatch.setenv("FAKE_ACT", json.dumps({"G": "ate2"}))
    units = [_u("G", outdir="ctl"),
             _u("ctl_G", kind="control", cmd=f"compare whole {rob}/ctl/G.json {ref}/G.json", needs="G", outdir="ctl"),
             _u("D1", needs="ctl_G"), _u("D2", needs="ctl_G"), _u("E")]
    code, rep = _run(env, units, par=2)
    assert code == 3
    assert rep["ctl_G"]["status"] == "MISMATCH"
    assert rep["D1"]["status"] == rep["D2"]["status"] == "SKIPPED_CONTROL"
    assert rep["E"]["status"] == "OK"
    assert "D1" not in _called(env) and "D2" not in _called(env) and "E" in _called(env)
    # union_channel compares the union channel only; an EQUAL control lets its dependents run
    (rob / "ctl" / "U.json").parent.mkdir(parents=True, exist_ok=True)
    (rob / "ctl" / "U.json").write_text(json.dumps({"label": "U", "channels": {"union": {"ate": 1.0}}}))
    monkeypatch.setenv("FAKE_ACT", "{}")
    units = [_u("ctl_U", kind="control", cmd=f"compare union_channel {rob}/ctl/U.json {ref}/U.json"),
             _u("D3", needs="ctl_U")]
    code, rep = _run(env, units)
    assert code == 0 and rep["ctl_U"]["status"] == "EQUAL" and rep["D3"]["status"] == "OK"


def test_a_need_from_an_earlier_group_is_read_from_its_report(env):
    prior = env / "prod" / "rob_frames"
    prior.mkdir(parents=True)
    (prior / "units_report_frames.json").write_text(json.dumps(
        {"group": "frames", "units": {"b_ok": {"status": "OK"}, "c_bad": {"status": "MISMATCH"}}}))
    units = [_u("X", needs="b_ok"), _u("Y", needs="c_bad"), _u("Z", needs="nowhere")]
    code, rep = _run(env, units, extra=("--prior", str(env / "prod")))
    assert rep["X"]["status"] == "OK" and rep["Y"]["status"] == "SKIPPED_CONTROL" and rep["Z"]["status"] == "SKIPPED"
    assert code == 1 and _called(env) == ["X"]


def test_thread_budget_and_plan_digest(env):
    with pytest.raises(SystemExit) as e:
        _run(env, [_u("A")], par=20, threads=4)                          # 80 threads > 64 vCPUs
    assert e.value.code == 2 and _called(env) == []
    with pytest.raises(SystemExit) as e:
        _run(env, [_u("A")], digest=hashlib.sha256(b"another job list").hexdigest())
    assert e.value.code == 2 and _called(env) == []
    code, rep = _run(env, [_u("A"), _u("B")], par=2, threads=3)
    assert code == 0
    for line in (env / "r.log").read_text().splitlines():
        assert set(json.loads(line)["env"].values()) == {"3"}           # the plan's threads, every variable


def test_post_units_run_serially_after_the_rest(env):
    units = [_u("P1", kind="post", cmd=f"python3 -c \"open('{env}/order.txt','a').write('P1 ')\""),
             _u("A"),
             _u("P2", kind="post", cmd=f"python3 -c \"open('{env}/order.txt','a').write('P2 ')\"")]
    code, rep = _run(env, units, par=4)
    assert code == 0 and (env / "order.txt").read_text() == "P1 P2 "
    assert rep["P1"]["status"] == rep["P2"]["status"] == "OK"


def test_off_host_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("SAR_HOST", "laptop")
    with pytest.raises(SystemExit):
        ru.main(["--units", "u", "--group", "g", "--plan", "p", "--root", "r", "--repo", str(REPO), "--out", str(tmp_path)])


# ---- j1b-01: memory packing --------------------------------------------------------------------------------
def test_units_are_packed_under_the_memory_budget(tmp_path, monkeypatch):
    """With per-unit predictions (plan groups[].units), run_units starts a unit only while the predicted total
    stays within the budget, so light units run beside heavy ones; never more than `par` at once."""
    import threading
    import time
    preds = {**{f"h{i}": 136.0 for i in range(5)}, **{f"l{i}": 3.5 for i in range(30)}}
    live, peak, lock = {"gib": 0.0, "n": 0}, {"gib": 0.0, "n": 0}, threading.Lock()

    def fake(u, **kw):
        with lock:
            live["gib"] += preds[u["name"]]
            live["n"] += 1
            peak["gib"], peak["n"] = max(peak["gib"], live["gib"]), max(peak["n"], live["n"])
        time.sleep(0.05)
        with lock:
            live["gib"] -= preds[u["name"]]
            live["n"] -= 1
        return {"status": "OK", "rc": 0, "detail": "", "secs": 0.05, "peak_gib": None}

    monkeypatch.setattr(ru, "run_unit", fake)
    units = [{"name": n, "kind": "perm_p1", "needs_control": "", "outdir": "o"} for n in preds]
    res, code = ru.execute(units, par=16, threads=4, root=tmp_path, repo=REPO, out=tmp_path, stacks={},
                           budget_gib=450.0, preds=preds)
    assert code == 0 and all(r["status"] == "OK" for r in res.values())
    assert peak["gib"] <= 450.0 and peak["n"] <= 16
    assert peak["n"] > 3                                  # light units ran beside the heavy ones


def test_plan_units_give_the_runner_its_predictions(tmp_path):
    units = [_u("A"), _u("B")]
    tsv = tmp_path / "units.tsv"
    sha = rj.write_tsv(units, tsv)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"joblist_sha256": sha, "verdict": "OK", "budget_gib": 450.0, "groups": [
        {"group": "cells", "threads": 4, "par": 1, "width": 16, "budget_gib": 450.0, "pred_gib": 200.0,
         "units": [{"name": "A", "pred_gib": 200.0}, {"name": "B", "pred_gib": 2.0}]}]}))
    p = ru.load_plan(plan, tsv, "cells")
    assert p["par"] == 16 and p["budget_gib"] == 450.0 and p["preds"] == {"A": 200.0, "B": 2.0}
    plan.write_text(json.dumps({"joblist_sha256": sha, "verdict": "OK",
                                "groups": [{"group": "cells", "threads": 4, "par": 3, "pred_gib": 1.0}]}))
    p = ru.load_plan(plan, tsv, "cells")                  # an older plan: its par, no packing
    assert p["par"] == 3 and p["preds"] is None


# --- reuse: a perm unit an earlier launch finished is copied, not rerun (j1b-03 died 1 unit short, 2026-10-17).
# Codex review: reuse is bound to the producer's inputs, driver, env pins and file hashes (provenance.json), and
# the producer's sandbox read log travels with it.

PERM_H = "label,mode,perm,seed_used,n_events,n_treated_events,status,ate,se,t,p_joint_effects,p_joint_placebo,secs"
SEED = 20260830


def _sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def _inputs(tmp):
    d = tmp / "in"
    d.mkdir(exist_ok=True)
    (d / "f.parquet").write_bytes(b"frame")
    (d / "ref.json").write_text('{"ate": 0}')
    return d / "f.parquet", d / "ref.json"


def _perm(tmp, name, lab, p0, p1, outdir="cloud/fetch/out_perm"):
    f, ref = _inputs(tmp)
    return rj.Unit("cells", name, "perm_p3tp", "p3_afar_pos_econ.parquet", 4, 1,
                   f"Rscript analysis/robustness/inference/run_perm.R p3tp {lab} {f} {ref} {SEED} {p0} {p1}", outdir, "")


def _kept(reuse, name, lab, p0, p1, *, outdir="cloud/fetch/out_perm", perms=None, exit_status=0, done=True, seed=SEED):
    """One unit's files as an earlier launch left them: logs/<name>.log|.timev, root/<outdir>/<label>_perm_<a>_<b>.csv."""
    logs = reuse / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / f"{name}.timev").write_text(f"\tMaximum resident set size (kbytes): 2097152\n\tExit status: {exit_status}\n")
    (logs / f"{name}.log").write_text(f"\n===== permutation p3tp {lab} events=9 perms={p0}..{p1} seed={seed} =====\n"
                                      + (f"[{lab}] {p0}..{p1} 完成 -> /x/{lab}_perm_{p0}_{p1}.csv\n" if done else ""))
    d = reuse / "root" / outdir
    d.mkdir(parents=True, exist_ok=True)
    rows = "".join(f"{lab},p3tp,{i},{'' if i == 0 else seed + i},9,9,OK,0.1,0.2,0.5,0.3,0.4,1.00\n"
                   for i in (range(p0, p1 + 1) if perms is None else perms))
    (d / f"{lab}_perm_{p0}_{p1}.csv").write_text(PERM_H + "\n" + rows)


def _prov(reuse, units, *, reads="rob_perm\t/work/j1a/frames/f.parquet\n"):
    """provenance.json as the producer's disk gave it: unit commands, kept-file, input, driver and env-pin hashes."""
    (reuse / "reads").mkdir(parents=True, exist_ok=True)
    (reuse / "reads" / "rob_perm.tsv").write_text(reads)
    us, ins = {}, {}
    for u in units:
        files = {}
        for rel in (f"logs/{u.name}.log", f"logs/{u.name}.timev"):
            if (reuse / rel).is_file():
                files[rel] = _sha(reuse / rel)
        for c in (reuse / "root" / u.outdir).glob("*.csv") if (reuse / "root" / u.outdir).is_dir() else ():
            if c.name.startswith(u.cmd.split()[3] + "_perm_"):
                files[str(c.relative_to(reuse))] = _sha(c)
        us[u.name] = {"cmd": u.cmd, "outdir": u.outdir, "files": files}
        for a in u.cmd.split():
            if a.startswith("/") and pathlib.Path(a).is_file():
                ins[a] = _sha(a)
    rs = {r: _sha(REPO / r) for r in ("analysis/robustness/inference/run_perm.R", "config/r1/env_pins.json")}
    (reuse / "provenance.json").write_text(json.dumps({
        "schema": "sar.r1.reuse_provenance.v1", "producer": {"job": "j1b-03", "commit": "c" * 40},
        "repo_sha256": rs, "inputs_sha256": ins, "units": us, "reads": {"reads/rob_perm.tsv": _sha(reuse / "reads" / "rob_perm.tsv")}}))


def _reused(rep):
    return {n for n, r in rep.items() if r["detail"].startswith("REUSED")}


def test_finished_perm_units_are_copied_and_the_rest_rerun(env):
    reuse = env / "reuse"
    _kept(reuse, "A", "LA", 1, 5)                            # finished
    _kept(reuse, "Z", "LZ", 0, 0)                            # the identity control unit, finished
    _kept(reuse, "B", "LB", 1, 5, perms=[1, 2, 3])           # cut off after 3 of 5 permutations
    _kept(reuse, "D", "LD", 1, 5, exit_status=1)             # the driver failed
    _kept(reuse, "E", "LE", 1, 5, done=False)                # no completion line
    units = [_perm(env, "A", "LA", 1, 5), _perm(env, "Z", "LZ", 0, 0), _perm(env, "B", "LB", 1, 5),
             _perm(env, "C", "LC", 1, 5), _perm(env, "D", "LD", 1, 5), _perm(env, "E", "LE", 1, 5)]
    _prov(reuse, units)
    code, rep = _run(env, units, extra=("--reuse", str(reuse)))
    assert code == 0 and _reused(rep) == {"A", "Z"} and all(r["status"] == "OK" for r in rep.values())
    assert len(_called(env)) == 4                             # B, C, D, E ran again
    got = env / "rob" / "cloud/fetch/out_perm" / "LA_perm_1_5.csv"
    assert got.read_bytes() == (reuse / "root" / "cloud/fetch/out_perm" / "LA_perm_1_5.csv").read_bytes()
    assert (env / "out" / "logs" / "A.timev").read_text().endswith("Exit status: 0\n")
    assert rep["A"]["peak_gib"] == 2.0
    full = json.loads((env / "out" / "units_report_cells.json").read_text())
    assert full["reused"] == ["A", "Z"] and full["reuse_producer"] == {"job": "j1b-03", "commit": "c" * 40}
    # the producer's sandbox read log travels with the reused units, for sandbox_check
    assert (env / "out" / "reuse_reads" / "j1b-03_rob_perm.tsv").read_text() == "rob_perm\t/work/j1a/frames/f.parquet\n"


def test_kept_files_from_another_command_are_not_reused(env):
    reuse = env / "reuse"
    _kept(reuse, "A", "LA", 1, 5, seed=SEED + 1)                    # another seed
    _kept(reuse, "B", "LB", 1, 5, outdir="cloud_t5/fetch/out_perm")  # another output dir
    _kept(reuse, "C", "LX", 1, 5)                                   # another label
    units = [_perm(env, "A", "LA", 1, 5), _perm(env, "B", "LB", 1, 5), _perm(env, "C", "LC", 1, 5)]
    _prov(reuse, units)
    code, rep = _run(env, units, extra=("--reuse", str(reuse)))
    assert code == 0 and len(_called(env)) == 3 and not _reused(rep)


def test_reuse_is_bound_to_the_producers_inputs_and_files(env):
    reuse = env / "reuse"
    for n in ("A", "B", "C"):
        _kept(reuse, n, "L" + n, 1, 5)
    units = [_perm(env, n, "L" + n, 1, 5) for n in ("A", "B", "C")]
    _prov(reuse, units)
    p = json.loads((reuse / "provenance.json").read_text())
    p["units"]["B"]["cmd"] = p["units"]["B"]["cmd"].replace(" 1 5", " 1 6")          # the producer ran another command
    (reuse / "provenance.json").write_text(json.dumps(p))
    (reuse / "root" / "cloud/fetch/out_perm" / "LC_perm_1_5.csv").write_text(
        (reuse / "root" / "cloud/fetch/out_perm" / "LC_perm_1_5.csv").read_text() + "\n")  # altered after the producer
    code, rep = _run(env, units, extra=("--reuse", str(reuse)))
    assert code == 0 and _reused(rep) == {"A"}
    (env / "in" / "f.parquet").write_bytes(b"another frame")                        # the input changed since
    code, rep = _run(env, units, extra=("--reuse", str(reuse)))
    assert code == 0 and not _reused(rep)


def test_a_changed_driver_or_env_pin_reuses_nothing(env):
    reuse = env / "reuse"
    _kept(reuse, "A", "LA", 1, 5)
    units = [_perm(env, "A", "LA", 1, 5)]
    _prov(reuse, units)
    p = json.loads((reuse / "provenance.json").read_text())
    p["repo_sha256"]["config/r1/env_pins.json"] = "0" * 64
    (reuse / "provenance.json").write_text(json.dumps(p))
    code, rep = _run(env, units, extra=("--reuse", str(reuse)))
    assert code == 0 and not _reused(rep) and len(_called(env)) == 1


def test_reuse_without_sound_provenance_or_read_log_is_refused(env):
    reuse = env / "reuse"
    _kept(reuse, "A", "LA", 1, 5)
    units = [_perm(env, "A", "LA", 1, 5)]
    with pytest.raises(SystemExit) as e:                                            # no provenance.json
        _run(env, units, extra=("--reuse", str(reuse)))
    assert e.value.code == 2 and _called(env) == []
    _prov(reuse, units, reads="rob_perm\t__LOST__\n")                               # the producer's audit lost reads
    with pytest.raises(SystemExit) as e:
        _run(env, units, extra=("--reuse", str(reuse)))
    assert e.value.code == 2 and _called(env) == []
    _prov(reuse, units)
    (reuse / "reads" / "rob_perm.tsv").write_text("rob_perm\t/elsewhere\n")         # read log altered after the producer
    with pytest.raises(SystemExit) as e:
        _run(env, units, extra=("--reuse", str(reuse)))
    assert e.value.code == 2 and _called(env) == []


def test_only_perm_units_are_ever_reused(env):
    reuse = env / "reuse"
    (reuse / "logs").mkdir(parents=True)
    (reuse / "logs" / "X.timev").write_text("\tExit status: 0\n")
    (reuse / "logs" / "X.log").write_text("done\n")
    _prov(reuse, [])
    code, rep = _run(env, [_u("X")], extra=("--reuse", str(reuse)))
    assert code == 0 and _called(env) == ["X"] and rep["X"]["detail"] == ""


def test_without_reuse_nothing_is_copied(env):
    reuse = env / "reuse"
    _kept(reuse, "A", "LA", 1, 5)
    units = [_perm(env, "A", "LA", 1, 5)]
    _prov(reuse, units)
    code, rep = _run(env, units)
    assert code == 0 and len(_called(env)) == 1 and rep["A"]["detail"] == ""
