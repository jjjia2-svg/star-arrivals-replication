# -*- coding: utf-8 -*-
"""tests/test_aws_cal2026_10_t5.py — the SECOND October cloud batch (T5: Panel 1 / Panel 2 timing
permutations, pipeline/aws/cal2026-10/prep_t5_batch.sh) and the `--extra-parallel` grammar of
cloudkit.py it rides on (2026-09-23). No AWS, no R: frames and references are fake bytes; nothing
is estimated and nothing is launched.

  1. cloudkit `--extra-parallel 'NAME|OUTDIR|COMMAND'`: units are appended to jobs_parallel.txt in
     the given order, every file a command names ships (run_perm.R from the repo, frames from
     --frames, references via --extra-file), a malformed spec, a duplicate name, a file nobody ships
     and an empty batch are each refused; an explicit `--groups ''` selects NO group (the batch is
     the extra units alone) and omitting --groups still selects every group — the first October
     batch's shape (8 serial cells, perm + null units) is unchanged.
  2. prep_t5_batch.sh reproduces run_all_perm.sh's P1/P2 unit table token for token: the six p1/p2
     rows of its CELLS table (read from that file here as well, not retyped), the identity control
     `0 0` first, chunks of CHUNK up to B, seed = config/seeds.yaml permutation_seed ==
     run_all_perm.sh SEED, SAR_OUT=out_perm; jobs_serial.txt empty; run_cloud.sh --dry-run reaches
     "DRY RUN OK" with no aws on PATH and leaves no instance id; the script's only run_cloud.sh call
     carries --dry-run; a non-empty payload dir is refused; a seed disagreement stops the prep.
  3. driver.sh runs an extra-parallel-only payload on a fake Rscript: one out_perm CSV and one
     `PAR` rc line per unit, ALL_DONE, and cloudkit custody accounts for it with no serial cell;
     FAIL when one unit exits non-zero.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
KIT_DIR = REPO / "pipeline" / "aws" / "cal2026-10"
sys.path.insert(0, str(KIT_DIR))
import cloudkit as ck                                                  # noqa: E402

PY = sys.executable
KIT = str(KIT_DIR / "cloudkit.py")
PREP = KIT_DIR / "prep_t5_batch.sh"
PERM_SH = REPO / "analysis" / "robustness" / "inference" / "run_all_perm.sh"
RUN_PERM_R = REPO / "analysis" / "robustness" / "inference" / "run_perm.R"
SEEDS = REPO / "config" / "seeds.yaml"


def _run(args, **kw):
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, cwd=REPO, **kw)


def _md5_lines(p: pathlib.Path) -> set[tuple[str, str]]:
    return {(ln.split()[0], ln.split()[-1]) for ln in p.read_text().splitlines() if ln.strip()}


def perm_cells() -> list[tuple[str, str, str, str]]:
    """The p1/p2 rows of run_all_perm.sh's CELLS table -> (mode, label, frame basename, ref basename)."""
    txt = PERM_SH.read_text(encoding="utf-8")
    block = txt[txt.index("CELLS=("):]
    block = block[:block.index("\n)")]
    return [m.groups() for m in
            re.finditer(r'^\s*"(p[12])\s+(\S+)\s+\$D/(\S+)\s+\$X/(\S+)"\s*$', block, re.M)]


def perm_params() -> tuple[int, int, int]:
    txt = PERM_SH.read_text(encoding="utf-8")
    b = int(re.search(r"^B=\$\{SAR_PERM_B:-(\d+)\}", txt, re.M).group(1))
    chunk = int(re.search(r"^CHUNK=(\d+)", txt, re.M).group(1))
    seed = int(re.search(r"^SEED=(\d+)", txt, re.M).group(1))
    return b, chunk, seed


def seed_yaml(p: pathlib.Path = SEEDS) -> int:
    return int(re.search(r"^permutation_seed:\s*(\d+)", p.read_text(encoding="utf-8"), re.M).group(1))


def expected_units(cells, b: int, chunk: int, seed: int) -> list[tuple[str, str, str]]:
    """What run_all_perm.sh runs, as cloud units: identity `0 0` then chunks of CHUNK up to B."""
    want = []
    for mode, lab, frame, ref in cells:
        for lo, hi in [(0, 0)] + ck.chunks(1, b, chunk):
            want.append((f"{lab}_perm_{lo}_{hi}", "out_perm",
                         f"Rscript run_perm.R {mode} {lab} {frame} {ref} {seed} {lo} {hi}"))
    return want


def _fake_t5_inputs(base: pathlib.Path):
    cells = perm_cells()
    assert len(cells) == 6 and [c[0] for c in cells] == ["p1"] * 3 + ["p2"] * 3, cells
    fr, refs = base / "frames", base / "refs"
    fr.mkdir(); refs.mkdir()
    for _m, _l, frame, ref in cells:
        (fr / frame).write_bytes(("FRAME " + frame).encode())
        (refs / ref).write_bytes(("REF " + ref).encode())
    return cells, fr, refs


def _prep_t5(fr, refs, payload, cust, *extra, env=None):
    return subprocess.run(["bash", str(PREP), "--frames", str(fr), "--refs", str(refs),
                           "--payload", str(payload), "--custody", str(cust), *extra],
                          capture_output=True, text=True, cwd=REPO, env=env, timeout=300)


# ---------------------------------------------------------------------------------------------
# 1. the --extra-parallel grammar and the --groups '' switch
# ---------------------------------------------------------------------------------------------

def test_extra_parallel_units_ride_along_and_groups_empty_means_none(tmp_path):
    fr = tmp_path / "frames"; fr.mkdir()
    (fr / "p1_frame_econ.csv").write_bytes(b"frame bytes")
    ref = tmp_path / "P1_econ_fnfix.json"; ref.write_bytes(b'{"channels": {"union": {}}}')
    units = ["A_perm_0_0|out_perm|Rscript run_perm.R p1 A p1_frame_econ.csv P1_econ_fnfix.json 7 0 0",
             "A_perm_1_2|out_perm|Rscript run_perm.R p1 A p1_frame_econ.csv P1_econ_fnfix.json 7 1 2"]

    def prep(out, *extra):
        return _run([PY, KIT, "prep", "--frames", fr, "--out", out, "--custody", tmp_path / "cust",
                     "--groups", "", "--extra-file", ref, *extra])

    out = tmp_path / "p1"
    r = prep(out, "--extra-parallel", units[0], "--extra-parallel", units[1])
    assert r.returncode == 0, r.stdout + r.stderr
    assert ck.read_jobs(out / "jobs_serial.txt") == []
    assert ck.read_jobs(out / "jobs_parallel.txt") == [tuple(u.split("|")) for u in units]
    shipped = {n for _h, n in _md5_lines(out / "payload.md5")}
    assert shipped == {"run_perm.R", "p1_frame_econ.csv", "P1_econ_fnfix.json", "bootstrap.sh",
                       "driver.sh", "driver.env", "jobs_serial.txt", "jobs_parallel.txt"}
    assert (out / "run_perm.R").read_bytes() == RUN_PERM_R.read_bytes()
    assert (out / "p1_frame_econ.csv").read_bytes() == b"frame bytes"
    assert (out / "P1_econ_fnfix.json").read_bytes() == ref.read_bytes()
    pre = json.loads((tmp_path / "cust" / "custody_preflight.json").read_text())
    assert pre["groups"] == [] and pre["jobs_serial"] == [] and pre["jobs_parallel_n"] == 2
    assert pre["payloads"]["run_perm.R"]["source"] == "analysis/robustness/inference/run_perm.R"
    assert pre["payloads"]["P1_econ_fnfix.json"]["md5_before"] == hashlib.md5(ref.read_bytes()).hexdigest()
    assert pre["cost_estimate"]["parallel_phase_min"] > 0
    # a malformed spec, a duplicate name, an unshipped file and an empty batch are each refused
    r = prep(tmp_path / "p2", "--extra-parallel", "no pipes here")
    assert r.returncode == 1 and "--extra-parallel needs" in r.stdout, r.stdout
    r = prep(tmp_path / "p3", "--extra-parallel", units[0], "--extra-parallel", units[0])
    assert r.returncode == 1 and "duplicate parallel job names" in r.stdout, r.stdout
    r = prep(tmp_path / "p4", "--extra-parallel",
             "B_perm_0_0|out_perm|Rscript run_perm.R p2 B p2_becoming_econ.csv P1_econ_fnfix.json 7 0 0")
    assert r.returncode == 1 and "p2_becoming_econ.csv" in r.stdout, r.stdout
    r = prep(tmp_path / "p5")
    assert r.returncode == 1 and "nothing to run" in r.stdout, r.stdout


def test_groups_omitted_still_selects_every_group(tmp_path):
    fr = tmp_path / "frames"; fr.mkdir()
    for n in ("p3_slim_econ.parquet", "p3_slim_ev_econ.parquet", "p3_slim_chemistry.parquet",
              "p3_slim_ev_chemistry.parquet", "p3_afar_pos_econ.parquet", "P3cut_pos_econ.json"):
        (fr / n).write_bytes(n.encode())
    out, cust = tmp_path / "payload", tmp_path / "custody"
    r = _run([PY, KIT, "prep", "--frames", fr, "--pos-frames", fr, "--refs", fr, "--out", out,
              "--custody", cust, "--fields", "econ", "--perm-b", "10", "--null-n", "10"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert [n for n, _o, _c in ck.read_jobs(out / "jobs_serial.txt")] == [
        "P3_fnfix_chemistry", "P3_econ_fnfix", "P3evcl_chemistry", "P3evcl_econ",
        "P3_fnfix_chemistry_pd0", "P3pd2_chemistry_full", "P3_econ_fnfix_pd0", "P3pd2_econ_full"]
    assert [n for n, _o, _c in ck.read_jobs(out / "jobs_parallel.txt")] == [
        "P3cutpos_econ_perm_0_0", "P3cutpos_econ_perm_1_5", "P3cutpos_econ_perm_6_10",
        "NULLpos_econ_null_1_5", "NULLpos_econ_null_6_10"]
    pre = json.loads((cust / "custody_preflight.json").read_text())
    assert pre["groups"] == sorted(ck.GROUPS)
    r = _run([PY, KIT, "prep", "--frames", fr, "--out", tmp_path / "x", "--custody", cust,
              "--groups", "p3main,bogus"])
    assert r.returncode == 1 and "unknown group" in r.stdout


# ---------------------------------------------------------------------------------------------
# 2. prep_t5_batch.sh == run_all_perm.sh's P1/P2 units, dry-run only
# ---------------------------------------------------------------------------------------------

def test_prep_t5_batch_mirrors_run_all_perm_and_dry_runs_without_launching(tmp_path):
    base = tmp_path / "with space"; base.mkdir()
    cells, fr, refs = _fake_t5_inputs(base)
    payload, cust = base / "payload_t5", base / "cloud_t5"
    nobin = base / "nobin"; nobin.mkdir()
    env = dict(os.environ, PATH=f"{nobin}:/usr/bin:/bin")        # no aws anywhere on PATH
    r = _prep_t5(fr, refs, payload, cust, env=env)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    assert "DRY RUN OK" in r.stdout and "PREPARED, NOT LAUNCHED" in r.stdout
    assert "[dry-run] aws --region us-east-1 ec2 run-instances" in r.stdout
    assert not (cust / "state" / "instance_id").exists()
    assert (cust / "userdata.txt").read_text() == "#!/bin/bash\nshutdown -h +600\n"

    b, chunk, seed_sh = perm_params()
    seed = seed_yaml()
    assert seed == seed_sh, (seed, seed_sh)
    want = expected_units(cells, b, chunk, seed)
    got = ck.read_jobs(payload / "jobs_parallel.txt")
    assert got == want
    assert len(got) == 6 * (1 + -(-b // chunk))                 # 66 at B=500, CHUNK=50
    assert ck.read_jobs(payload / "jobs_serial.txt") == []
    for _m, lab, _f, _r in cells:                                # 0..B exactly once per cell
        seen = []
        for _n, _o, c in got:
            t = c.split()
            if t[3] == lab:
                seen += list(range(int(t[7]), int(t[8]) + 1))
        assert sorted(seen) == list(range(0, b + 1)), lab
    shipped = {n for _h, n in _md5_lines(payload / "payload.md5")}
    assert shipped == {"run_perm.R", *(c[2] for c in cells), *(c[3] for c in cells),
                       "bootstrap.sh", "driver.sh", "driver.env", "jobs_serial.txt", "jobs_parallel.txt"}
    for _m, _l, frame, ref in cells:
        assert (payload / frame).read_bytes() == (fr / frame).read_bytes()
        assert (payload / ref).read_bytes() == (refs / ref).read_bytes()
    assert (payload / "run_perm.R").read_bytes() == RUN_PERM_R.read_bytes()
    pre = json.loads((cust / "custody_preflight.json").read_text())
    assert pre["groups"] == [] and pre["seeds"]["perm"] == seed and pre["jobs_parallel_n"] == len(want)
    assert pre["payloads"]["run_perm.R"]["source"] == "analysis/robustness/inference/run_perm.R"
    env_txt = (payload / "driver.env").read_text()
    assert "PAR=12" in env_txt and "THREADS=4" in env_txt and "MARKER=2026_10C" in env_txt
    # the script's defaults are the October canon and golds, and it can only ever dry-run
    body = PREP.read_text(encoding="utf-8")
    assert "FRAMES=data/frames" in body and "REFS=analysis/expected" in body
    assert "CUSTODY=data/cal2026-10/cloud_t5" in body and "PAYLOAD=/private/tmp/cal2026-10_payload_t5" in body
    calls = [ln for ln in body.splitlines() if re.match(r"^\s*bash .*run_cloud\.sh", ln)]
    assert calls and all("--dry-run" in ln for ln in calls), calls
    assert not re.search(r"^\s*aws ", body, re.M)
    # a payload is frozen bytes: a second prep into the same dir is refused without --force
    r2 = _prep_t5(fr, refs, payload, cust, "--skip-dry-run", env=env)
    assert r2.returncode == 1 and "not empty" in r2.stdout, r2.stdout + r2.stderr


def test_prep_t5_batch_stops_on_a_seed_disagreement(tmp_path):
    cells, fr, refs = _fake_t5_inputs(tmp_path)
    bad = tmp_path / "seeds.yaml"; bad.write_text("permutation_seed: 1\n")
    r = _prep_t5(fr, refs, tmp_path / "p", tmp_path / "c", "--skip-dry-run",
                 env=dict(os.environ, SAR_SEEDS_YAML=str(bad)))
    assert r.returncode == 1 and "SEED DISAGREEMENT" in r.stderr, r.stdout + r.stderr
    assert not (tmp_path / "p").exists()


# ---------------------------------------------------------------------------------------------
# 3. driver.sh + custody on an extra-parallel-only payload (fake Rscript)
# ---------------------------------------------------------------------------------------------

def _fake_bin(d: pathlib.Path) -> pathlib.Path:
    """`Rscript` that writes the CSV run_perm.R would (fails when the label says so), a `time`
    that accepts -v, and a `md5sum` that is cloudkit's own check-md5."""
    d.mkdir(parents=True, exist_ok=True)
    rs = d / "Rscript"
    rs.write_text("""#!/usr/bin/env python3
import os, sys
try:
    sys.stdin.read()
except Exception:
    pass
a = sys.argv[1:]
assert a[0] == "run_perm.R", a
out = os.environ.get("SAR_OUT", "out"); os.makedirs(out, exist_ok=True)
label, lo, hi = a[2], int(a[6]), int(a[7])
if "FAILME" in label:
    print("boom"); sys.exit(9)
with open(os.path.join(out, f"{label}_perm_{lo}_{hi}.csv"), "w") as f:
    f.write("label,mode,perm\\n" + "".join(f"{label},{a[1]},{i}\\n" for i in range(lo, hi + 1)))
""")
    rs.chmod(rs.stat().st_mode | stat.S_IEXEC)
    tm = d / "time"
    tm.write_text('#!/bin/bash\nshift\n"$@"; rc=$?\n'
                  'echo "\tElapsed (wall clock) time (h:mm:ss or m:ss): 0:01.00" >&2\n'
                  'echo "\tMaximum resident set size (kbytes): 1048576" >&2\nexit $rc\n')
    tm.chmod(tm.stat().st_mode | stat.S_IEXEC)
    md = d / "md5sum"
    md.write_text(f"#!/bin/bash\nexec '{PY}' '{KIT}' check-md5 .\n")
    md.chmod(md.stat().st_mode | stat.S_IEXEC)
    return d


def _run_driver(tmp_path: pathlib.Path, payload: pathlib.Path):
    work = tmp_path / "work"
    shutil.copytree(payload, work)
    fake = _fake_bin(tmp_path / "bin")
    env = dict(os.environ, SAR_WORK=str(work), TIME_BIN=str(fake / "time"),
               MD5SUM=str(fake / "md5sum"), PATH=f"{fake}:{os.environ['PATH']}", HOME=str(tmp_path))
    r = subprocess.run(["bash", str(work / "driver.sh")], capture_output=True, text=True, env=env,
                       cwd=work, stdin=subprocess.DEVNULL, timeout=600)
    return work, r


def test_driver_and_custody_on_an_extra_parallel_only_payload(tmp_path):
    cells, fr, refs = _fake_t5_inputs(tmp_path)
    payload, cust = tmp_path / "payload", tmp_path / "custody"
    r = _prep_t5(fr, refs, payload, cust, "--skip-dry-run", "--parallel", "3",
                 env=dict(os.environ, SAR_PERM_B="4"))          # SAR_PERM_B: as run_all_perm.sh
    assert r.returncode == 0, r.stdout + r.stderr
    _b, chunk, _s = perm_params()
    want = expected_units(cells, 4, chunk, seed_yaml())
    jobs = ck.read_jobs(payload / "jobs_parallel.txt")
    assert jobs == want and len(jobs) == 12                      # (0,0) + (1,4) per cell
    work, r = _run_driver(tmp_path, payload)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (work / "RESULT.txt").read_text().strip() == "ALL_DONE_MARKER_2026_10C"
    prog = (work / "progress.log").read_text()
    assert len(re.findall(r"^PAR u\d{3}_\S+_perm_\d+_\d+ rc=0", prog, re.M)) == 12
    assert not re.search(r"^SERIAL ", prog, re.M)
    for name, _o, _c in jobs:
        assert (work / "out_perm" / f"{name}.csv").is_file(), name
    assert (work / "out_perm" / "P2_fnfix_math_stats_perm_1_4.csv").read_text().count("\n") == 5
    # custody on the fetched work dir: no serial cell, 12 units, rows per label = perms 0..4
    shutil.rmtree(cust / "fetch", ignore_errors=True)
    shutil.copytree(work, cust / "fetch")
    st = cust / "state"; st.mkdir(exist_ok=True)
    (st / "instance_id").write_text("i-0fake00000000t5\n")
    (cust / "launch_time_utc.txt").write_text("2026-10-01T01:00:00Z\n")
    (cust / "terminate_time_utc.txt").write_text("2026-10-01T01:30:00Z\n")
    (cust / "termination_proof.json").write_text(json.dumps(
        {"InstanceId": "i-0fake00000000t5", "State": {"Code": 48, "Name": "terminated"}}))
    r = _run([PY, KIT, "record", "--custody", cust])
    assert r.returncode == 0, r.stdout + r.stderr
    r = _run([PY, KIT, "custody", "--custody", cust, "--payload", payload])
    assert r.returncode == 0, r.stdout + r.stderr
    c = json.loads((cust / "custody_cal2026-10.json").read_text())
    assert c["ok"] is True and c["problems"] == [] and c["cells"] == {}
    assert c["units"] == {"expected": 12, "reported": 12, "nonzero": {}, "absent": []}
    assert {k: v["rows"] for k, v in c["parallel_outputs"].items()} == {lab: 5 for _m, lab, _f, _r in cells}
    assert {x[1] for x in c["verify"]["frame_pairs"]} >= {"run_perm.R", *(c_[2] for c_ in cells)}
    r = _run([PY, REPO / "tools" / "verify_cloud_custody.py", "--custody", cust])
    assert r.returncode == 0 and "CUSTODY_OK" in r.stdout, r.stdout


def test_driver_refuses_all_done_when_an_extra_parallel_unit_fails(tmp_path):
    fr = tmp_path / "frames"; fr.mkdir()
    (fr / "p1_frame_econ.csv").write_bytes(b"frame")
    ref = tmp_path / "P1_econ_fnfix.json"; ref.write_bytes(b"{}")
    payload, cust = tmp_path / "payload", tmp_path / "custody"
    r = _run([PY, KIT, "prep", "--frames", fr, "--out", payload, "--custody", cust, "--groups", "",
              "--extra-file", ref, "--parallel", "2",
              "--extra-parallel", "OK_perm_0_0|out_perm|Rscript run_perm.R p1 OK p1_frame_econ.csv P1_econ_fnfix.json 7 0 0",
              "--extra-parallel", "FAILME_perm_0_0|out_perm|Rscript run_perm.R p1 FAILME p1_frame_econ.csv P1_econ_fnfix.json 7 0 0"])
    assert r.returncode == 0, r.stdout + r.stderr
    work, _r = _run_driver(tmp_path, payload)
    assert (work / "RESULT.txt").read_text().strip() == "FAIL_MARKER_2026_10C"
    prog = (work / "progress.log").read_text()
    assert re.search(r"^PAR u002_FAILME_perm_0_0 rc=9", prog, re.M), prog
    assert re.search(r"^PAR u001_OK_perm_0_0 rc=0", prog, re.M), prog
    assert (work / "out_perm" / "OK_perm_0_0.csv").is_file()
    assert "failed=1" in (work / "driver.log").read_text()
