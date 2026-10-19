# -*- coding: utf-8 -*-
"""pipeline/aws/cal2026-10/ — the runnable launcher for the October cloud batch, tested without AWS.

Five layers, each a control that can fail:
  1. CONTROL against 2026-08-28: `cloudkit.py prep` on the caliber frames reproduces
     data/cal2026-08-28/cloud/payload.md5 line for line, and the serial commands equal the four
     Rscript invocations of data/cal2026-08-28/cloud/driver.sh token for token.
  2. CONTROL against 2026-08-30: on today's pos frames + references the shipped md5s of the
     08-30 batch are reproduced exactly, and its unit grammar (every full chunk of jobs.txt).
  3. driver.sh runs end to end on a fake Rscript / fake time: ALL_DONE iff every unit exits 0.
  4. run_cloud.sh argument parsing + --dry-run on a fake payload: exit 0, no aws call; exit 1 on a
     corrupted payload; usage on missing args.
  5. record + custody on a synthetic run, then tools/verify_cloud_custody.py --custody ->
     CUSTODY_OK, CUSTODY_FAIL after one payload byte changes; the default invocation unchanged.
  6. (2026-09-22 review) run_cloud.sh END TO END on fake `aws`/`ssh`/`scp` binaries, with the
     payload and custody dirs under a path that contains a space (this checkout does): launch,
     ssh, bootstrap, ship + md5, driver, poll, fetch, terminate, record, custody -> exit 0 and
     CUSTODY_OK, one run-instances and one terminate-instances call. The first version of the
     launcher passed the ssh options as one unquoted string and word-split on the space (ssh took
     ".../known_hosts" as the host); the fake ssh refuses any host but ubuntu@10.0.0.1. Plus the
     static guard that every `pgrep -f` pattern is bracketed (`[b]ash ...`): procps pgrep matches
     the invoking shell's own command line, so the plain pattern reported the driver as already
     running and it was never started.
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

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
KIT_DIR = REPO / "pipeline" / "aws" / "cal2026-10"
sys.path.insert(0, str(KIT_DIR))
import cloudkit as ck                                                  # noqa: E402

PY = sys.executable
CAL_CLOUD = REPO / "data" / "cal2026-08-28" / "cloud"
CAL_FRAMES = REPO / "data" / "cal2026-08-28" / "frames"
B0830 = REPO / "data" / "cloud_custody_null_perm_2026-08-30" / "fetch" / "work"
POS_REFS = REPO / "data" / "robustness_afar_cuts_2026-08-30"
# 2026-09-23: data/frames holds the October caliber since 73777aa, and the 2026-08-30 dose>0 parquets
# are frozen nowhere on disk (data/cal2026-08-28/frames predates the 08-30 cuts), so the shipped
# bytes come from the tag that registered them as canonical (their md5s are the B0830/payload.md5
# lines the test below asserts).
POS_TAG = "p3pos-registered-2026-09-10"

needs_cal_frames = pytest.mark.skipif(not (CAL_FRAMES / "p3_slim_econ.parquet").is_file(),
                                      reason="cal2026-08-28 frames not on this checkout")


def _md5(p: pathlib.Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def _md5_lines(p: pathlib.Path) -> set[tuple[str, str]]:
    return {(ln.split()[0], ln.split()[-1]) for ln in p.read_text().splitlines() if ln.strip()}


def _run(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, cwd=REPO, **kw)


# ---------------------------------------------------------------------------------------------
# 1. control against the 2026-08-28 payload
# ---------------------------------------------------------------------------------------------

@needs_cal_frames
def test_prep_on_the_0828_frames_reproduces_the_0828_payload_md5_and_driver_commands(tmp_path):
    out, cust = tmp_path / "payload", tmp_path / "custody"
    r = _run([PY, str(KIT_DIR / "cloudkit.py"), "prep", "--frames", str(CAL_FRAMES),
              "--out", str(out), "--custody", str(cust), "--groups", "p3main,p3evcl"])
    assert r.returncode == 0, r.stdout + r.stderr
    got = _md5_lines(out / "payload.md5")
    want = _md5_lines(CAL_CLOUD / "payload.md5")
    # the six 08-28 lines are reproduced exactly (same bytes -> same md5); the bundle files
    # (bootstrap.sh, driver.sh, driver.env, jobs_*.txt) are the only additions
    assert want <= got, {"missing": want - got}
    extra = {n for _h, n in got - want}
    assert extra == {"bootstrap.sh", "driver.sh", "driver.env", "jobs_serial.txt",
                     "jobs_parallel.txt"}, extra
    # the serial commands are the 08-28 driver's Rscript invocations, token for token
    drv = (CAL_CLOUD / "driver.sh").read_text()
    want_cmds = [re.sub(r'"', "", m.group(1)).split()
                 for m in re.finditer(r"/usr/bin/time -v (Rscript \S+ +\S+ +\S+) ", drv)]
    got_cmds = [c.split() for _n, _o, c in ck.read_jobs(out / "jobs_serial.txt")]
    assert got_cmds == want_cmds
    assert (out / "jobs_parallel.txt").read_text() == ""
    pre = json.loads((cust / "custody_preflight.json").read_text())
    assert set(pre["payloads"]) == {n for _h, n in got}
    assert pre["payload_md5_sha256"] == hashlib.sha256((out / "payload.md5").read_bytes()).hexdigest()
    assert pre["cost_estimate"]["parallel_phase_min"] == 0.0
    # every payload source is recorded, repo-relative
    for name in ("p3_slim_econ.parquet", "run_p3.R"):
        assert pre["payloads"][name]["source"].startswith(("data/", "analysis/"))


# ---------------------------------------------------------------------------------------------
# 2. control against the 2026-08-30 permutation + null batch
# ---------------------------------------------------------------------------------------------

def test_prep_on_the_pos_frames_reproduces_the_0830_shipped_hashes_and_unit_grammar(tmp_path):
    out, cust = tmp_path / "payload", tmp_path / "custody"
    # 2026-09-23: the 08-30 pos frames, taken from POS_TAG (see its note) instead of data/frames
    pos = tmp_path / "pos_frames_2026-08-30"
    pos.mkdir()
    if subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{POS_TAG}^{{commit}}"], cwd=REPO,
                      capture_output=True).returncode != 0:
        # public copy: the 2026-08-30 dose>0 frames exist only in the private repository's history (this
        # tag); the package ships no git history, so this control cannot run here
        pytest.skip(f"needs the private repository's git tag {POS_TAG} (the 2026-08-30 dose>0 frames)")
    for f in ck.FIELDS:
        name = f"p3_afar_pos_{f}.parquet"
        blob = subprocess.run(["git", "show", f"{POS_TAG}:data/frames/{name}"], cwd=REPO,
                              capture_output=True)
        assert blob.returncode == 0, blob.stderr.decode(errors="replace")
        (pos / name).write_bytes(blob.stdout)
    r = _run([PY, str(KIT_DIR / "cloudkit.py"), "prep", "--pos-frames", str(pos),
              "--refs", str(POS_REFS), "--out", str(out), "--custody", str(cust),
              "--groups", "perm,null"])
    assert r.returncode == 0, r.stdout + r.stderr
    got = dict((n, h) for h, n in _md5_lines(out / "payload.md5"))
    want = dict((n, h) for h, n in _md5_lines(B0830 / "payload.md5"))
    for name in ("p3_afar_pos_econ.parquet", "p3_afar_pos_chemistry.parquet",
                 "p3_afar_pos_math_stats.parquet", "P3cut_pos_econ.json", "P3cut_pos_chemistry.json",
                 "P3cut_pos_math_stats.json", "run_perm.R", "run_null.R"):
        assert got[name] == want[name], name

    jobs = ck.read_jobs(out / "jobs_parallel.txt")
    cmds = {c for _n, _o, c in jobs}
    # every 08-30 job line that is a FULL chunk of the batch grammar is generated verbatim
    # (jobs.txt was a resume list: its partial econ chunks are excluded by construction)
    old = [ln.strip() for ln in (B0830 / "jobs.txt").read_text().splitlines() if ln.strip()]
    full = []
    for ln in old:
        t = ln.split()                        # t[0] == "Rscript"
        if t[1] == "run_perm.R":              # run_perm.R p3tp label pq ref seed from to
            a, b = int(t[7]), int(t[8])
            size = 5 if "econ" in t[3] else 50
        else:                                 # run_null.R label pq seed from to outdir
            a, b = int(t[5]), int(t[6])
            size = 5 if "econ" in t[2] else 50
        if (a, b) == (0, 0) or (b - a + 1 == size and (a - 1) % size == 0):
            full.append(ln)
    assert full, "no full-chunk lines recognised in the 08-30 jobs.txt"
    missing = [ln for ln in full if ln not in cmds]
    assert missing == [], missing
    # econ permutations 0..500 exactly once; 200 null simulations per field exactly once
    for f in ck.FIELDS:
        seen = []
        for _n, _o, c in jobs:
            t = c.split()
            if t[1] == "run_perm.R" and t[3] == f"P3cutpos_{f}":
                seen += list(range(int(t[7]), int(t[8]) + 1))
        assert sorted(seen) == list(range(0, 501)), f
        seen = []
        for _n, _o, c in jobs:
            t = c.split()
            if t[1] == "run_null.R" and t[2] == f"NULLpos_{f}":
                seen += list(range(int(t[5]), int(t[6]) + 1))
        assert sorted(seen) == list(range(1, 201)), f
    names = [n for n, _o, _c in jobs]
    assert len(set(names)) == len(names)
    env = (out / "driver.env").read_text()
    assert "MARKER=2026_10C" in env and "PAR=12" in env and "THREADS=4" in env


def test_extra_serial_cells_and_files_ride_along(tmp_path):
    fr = tmp_path / "frames"; fr.mkdir()
    for n in ("p3_slim_econ.parquet", "p3_slim_ev_econ.parquet", "p3_slim_chemistry.parquet",
              "p3_slim_ev_chemistry.parquet"):
        (fr / n).write_bytes(n.encode())
    (tmp_path / "p3_slim_p05_econ.parquet").write_bytes(b"p05")
    out, cust = tmp_path / "payload", tmp_path / "custody"
    r = _run([PY, str(KIT_DIR / "cloudkit.py"), "prep", "--frames", str(fr), "--out", str(out),
              "--custody", str(cust), "--groups", "p3main,predate",
              "--extra-serial", "P3_p05_econ|out_extra|Rscript run_p3.R P3_p05_econ p3_slim_p05_econ.parquet",
              "--extra-file", str(tmp_path / "p3_slim_p05_econ.parquet")])
    assert r.returncode == 0, r.stdout + r.stderr
    jobs = ck.read_jobs(out / "jobs_serial.txt")
    names = [n for n, _o, _c in jobs]
    assert names == ["P3_fnfix_chemistry", "P3_econ_fnfix",
                     "P3_fnfix_chemistry_pd0", "P3pd2_chemistry_full",
                     "P3_econ_fnfix_pd0", "P3pd2_econ_full", "P3_p05_econ"]
    assert (out / "p3_slim_p05_econ.parquet").read_bytes() == b"p05"
    assert "run_predate.R" in {n for _h, n in _md5_lines(out / "payload.md5")}
    # the shift-0 control keeps the MAIN label (compare_json needs label equality) in its own dir
    ctrl = [j for j in jobs if j[0] == "P3_econ_fnfix_pd0"][0]
    assert ctrl[1] == "out_predate_control" and ctrl[2].split()[3] == "P3_econ_fnfix" and ctrl[2].split()[5] == "0"
    # a non-empty payload dir is refused without --force
    r2 = _run([PY, str(KIT_DIR / "cloudkit.py"), "prep", "--frames", str(fr), "--out", str(out),
               "--custody", str(cust), "--groups", "p3main"])
    assert r2.returncode == 1 and "not empty" in r2.stdout


def test_check_md5_names_the_corrupted_file(tmp_path):
    out = tmp_path / "p"; out.mkdir()
    (out / "a.parquet").write_bytes(b"aaa"); (out / "b.R").write_bytes(b"bbb")
    (out / "payload.md5").write_text(f"{_md5(out / 'a.parquet')}  a.parquet\n{_md5(out / 'b.R')}  b.R\n")
    r = _run([PY, str(KIT_DIR / "cloudkit.py"), "check-md5", str(out)])
    assert r.returncode == 0 and "a.parquet: OK" in r.stdout and "b.R: OK" in r.stdout
    (out / "b.R").write_bytes(b"bbc")
    r = _run([PY, str(KIT_DIR / "cloudkit.py"), "check-md5", str(out)])
    assert r.returncode == 1 and "b.R: FAILED" in r.stdout and "a.parquet: OK" in r.stdout


# ---------------------------------------------------------------------------------------------
# 3. driver.sh on a fake Rscript
# ---------------------------------------------------------------------------------------------

def _fake_bin(d: pathlib.Path) -> pathlib.Path:
    """A PATH dir with `Rscript` (writes the JSON/CSV a driver would, fails when the label says so)
    and a `time` that accepts -v and emits the two time -v lines cloudkit reads."""
    d.mkdir(parents=True, exist_ok=True)
    rs = d / "Rscript"
    rs.write_text("""#!/usr/bin/env python3
import json, os, sys
try:
    sys.stdin.read()          # a real R process may read stdin; the driver must not hand it the job list
except Exception:
    pass
a = sys.argv[1:]
out = os.environ.get("SAR_OUT", "out")
os.makedirs(out, exist_ok=True)
script = a[0]
if script == "run_predate.R":
    label = a[2]
elif script == "run_perm.R":
    label = a[2]; open(os.path.join(out, f"{label}_perm_{a[6]}_{a[7]}.csv"), "w").write("label,perm\\n" + "".join(f"{label},{i}\\n" for i in range(int(a[6]), int(a[7]) + 1))); sys.exit(0)
elif script == "run_null.R":
    label = a[1]; out = a[6]; os.makedirs(out, exist_ok=True); open(os.path.join(out, f"{label}_null_{a[4]}_{a[5]}.csv"), "w").write("label,sim\\n" + "".join(f"{label},{i}\\n" for i in range(int(a[4]), int(a[5]) + 1))); sys.exit(0)
else:
    label = a[1]
if "FAILME" in label:
    print("boom"); sys.exit(7)
json.dump({"label": label, "status": "OK", "secs": 1.5, "ate": 0.25, "se": 0.1,
           "effects": [{"k": 1, "est": 0.25}]}, open(os.path.join(out, label + ".json"), "w"))
""")
    rs.chmod(rs.stat().st_mode | stat.S_IEXEC)
    tm = d / "time"
    tm.write_text("""#!/bin/bash
# fake GNU time: time -v CMD... -> run CMD, print the two lines cloudkit parses to stderr
shift   # -v
"$@"; rc=$?
echo "	Elapsed (wall clock) time (h:mm:ss or m:ss): 0:01.00" >&2
echo "	Maximum resident set size (kbytes): 1048576" >&2
exit $rc
""")
    tm.chmod(tm.stat().st_mode | stat.S_IEXEC)
    md = d / "md5sum"
    md.write_text(f"#!/bin/bash\nexec '{PY}' '{KIT_DIR / 'cloudkit.py'}' check-md5 .\n")
    md.chmod(md.stat().st_mode | stat.S_IEXEC)
    return d


def _payload_for_driver(tmp_path, extra_serial=()):
    fr = tmp_path / "frames"; fr.mkdir(exist_ok=True)
    for n in ("p3_slim_econ.parquet", "p3_slim_ev_econ.parquet", "p3_slim_chemistry.parquet",
              "p3_slim_ev_chemistry.parquet", "p3_afar_pos_econ.parquet", "P3cut_pos_econ.json"):
        (fr / n).write_bytes(n.encode())
    out, cust = tmp_path / "payload", tmp_path / "custody"
    args = [PY, str(KIT_DIR / "cloudkit.py"), "prep", "--frames", str(fr), "--pos-frames", str(fr),
            "--refs", str(fr), "--out", str(out), "--custody", str(cust), "--fields", "econ",
            "--perm-b", "10", "--null-n", "10", "--parallel", "3"]
    for e in extra_serial:
        args += ["--extra-serial", e]
    r = _run(args)
    assert r.returncode == 0, r.stdout + r.stderr
    return out, cust


def _run_driver(tmp_path, payload):
    work = tmp_path / "work"
    shutil.copytree(payload, work)
    fake = _fake_bin(tmp_path / "bin")
    env = dict(os.environ, SAR_WORK=str(work), TIME_BIN=str(fake / "time"),
               MD5SUM=str(fake / "md5sum"), PATH=f"{fake}:{os.environ['PATH']}", HOME=str(tmp_path))
    r = subprocess.run(["bash", str(work / "driver.sh")], capture_output=True, text=True, env=env,
                       cwd=work, stdin=subprocess.DEVNULL)
    return work, r


def test_driver_runs_every_unit_and_marks_all_done_only_when_all_exit_zero(tmp_path):
    payload, _cust = _payload_for_driver(tmp_path)
    work, r = _run_driver(tmp_path, payload)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (work / "RESULT.txt").read_text().strip() == "ALL_DONE_MARKER_2026_10C"
    prog = (work / "progress.log").read_text()
    nser = len(ck.read_jobs(payload / "jobs_serial.txt"))
    npar = len(ck.read_jobs(payload / "jobs_parallel.txt"))
    assert len(re.findall(r"^SERIAL \S+ rc=0", prog, re.M)) == nser
    assert len(re.findall(r"^PAR u\d{3}_\S+ rc=0", prog, re.M)) == npar
    assert (work / "md5check.log").read_text().count(": OK") == len(
        _md5_lines(payload / "payload.md5"))
    # results where cloudkit expects them
    for n in ("out/P3_econ_fnfix.json", "out/P3evcl_econ.json", "out_predate/P3pd2_econ_full.json",
              "out_predate_control/P3_econ_fnfix.json", "out_perm/P3cutpos_econ_perm_0_0.csv",
              "out_null/NULLpos_econ_null_1_5.csv", "timev/P3_econ_fnfix.txt"):
        assert (work / n).is_file(), n
    log = (work / "driver.log").read_text()
    assert "MD5_OK" in log and "units=" in log and "failed=0" in log


def test_driver_fails_loudly_when_one_unit_exits_nonzero(tmp_path):
    payload, _cust = _payload_for_driver(
        tmp_path, extra_serial=["FAILME_cell|out_extra|Rscript run_p3.R FAILME_cell p3_slim_econ.parquet"])
    work, r = _run_driver(tmp_path, payload)
    assert (work / "RESULT.txt").read_text().strip() == "FAIL_MARKER_2026_10C"
    prog = (work / "progress.log").read_text()
    assert re.search(r"^SERIAL FAILME_cell rc=7", prog, re.M), prog
    # the other units still ran (salvage everything, the rule) and reported 0
    assert re.search(r"^SERIAL P3_econ_fnfix rc=0", prog, re.M)
    assert "failed=1" in (work / "driver.log").read_text()


def test_driver_refuses_to_start_on_a_bad_md5(tmp_path):
    payload, _cust = _payload_for_driver(tmp_path)
    (payload / "p3_slim_econ.parquet").write_bytes(b"tampered")
    work, r = _run_driver(tmp_path, payload)
    assert r.returncode == 1
    assert (work / "RESULT.txt").read_text().strip() == "FAIL_MARKER_2026_10C"
    assert "MD5_FAIL" in (work / "driver.log").read_text()
    assert not (work / "out").exists()


# ---------------------------------------------------------------------------------------------
# 4. run_cloud.sh argument parsing and --dry-run (no aws)
# ---------------------------------------------------------------------------------------------

def test_run_cloud_usage_and_dry_run(tmp_path):
    payload, cust = _payload_for_driver(tmp_path)
    sh = KIT_DIR / "run_cloud.sh"
    r = _run(["bash", str(sh)])
    assert r.returncode == 2 and "--payload and --custody are required" in r.stderr
    r = _run(["bash", str(sh), "--payload", str(payload), "--custody", str(cust), "--bogus"])
    assert r.returncode == 2 and "unknown argument" in r.stderr
    # a PATH with no aws at all: --dry-run must still succeed, printing the commands as text
    nobin = tmp_path / "nobin"; nobin.mkdir()
    env = dict(os.environ, PATH=f"{nobin}:/usr/bin:/bin")
    r = subprocess.run(["bash", str(sh), "--payload", str(payload), "--custody", str(cust),
                        "--dry-run"], capture_output=True, text=True, env=env, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DRY RUN OK" in r.stdout
    assert "[dry-run] aws --region us-east-1 ec2 run-instances" in r.stdout
    assert "ami-052355af2a014bd2c" in r.stdout and "r6i.16xlarge" in r.stdout
    assert "sg-047b8db2bb9452695" in r.stdout and "openalex-run" in r.stdout
    assert "shutdown -h +600" in r.stdout
    assert "[dry-run] aws --region us-east-1 ec2 terminate-instances" in r.stdout
    assert "$4.032/h" in r.stdout and "estimate" in r.stdout
    assert re.search(r"payload.md5.*: OK|p3_slim_econ.parquet: OK", r.stdout)
    assert (cust / "userdata.txt").read_text() == "#!/bin/bash\nshutdown -h +600\n"
    assert not (cust / "state" / "instance_id").exists()
    # the money-spending calls are all routed through aws_cli()
    body = sh.read_text()
    assert body.count("aws_cli ec2 run-instances") == 2          # dry-run echo + the real one
    bare = re.findall(r"^\s*aws .*$", body, re.M)
    assert bare == ['  aws --region "$REGION" "$@"'], f"bare aws command(s) outside aws_cli(): {bare}"


def test_run_cloud_dry_run_refuses_a_corrupted_payload(tmp_path):
    payload, cust = _payload_for_driver(tmp_path)
    (payload / "run_p3.R").write_bytes(b"# tampered\n")
    r = _run(["bash", str(KIT_DIR / "run_cloud.sh"), "--payload", str(payload), "--custody",
              str(cust), "--dry-run"])
    assert r.returncode == 1
    assert "run_p3.R: FAILED" in r.stdout and "refusing to ship" in r.stderr
    (payload / "driver.sh").unlink()
    r = _run(["bash", str(KIT_DIR / "run_cloud.sh"), "--payload", str(payload), "--custody",
              str(cust), "--dry-run"])
    assert r.returncode == 1 and "payload incomplete" in r.stderr


def test_bootstrap_carries_the_0828_recipe_plus_fixest():
    old = (CAL_CLOUD / "bootstrap.sh").read_text()
    new = (KIT_DIR / "bootstrap.sh").read_text()
    for line in ("add_cranapt_noble.sh", "sh.rustup.rs", 'install.packages("polars"',
                 "r-cran-didmultiplegtdyn", "free -g", "BOOTSTRAP_DONE"):
        assert line in old and line in new, line
    assert "r-cran-fixest" in new and "library(fixest)" in new
    assert "shutdown" not in new                       # the fuse is user-data, not bootstrap


# ---------------------------------------------------------------------------------------------
# 5. record + custody + the generalised verifier
# ---------------------------------------------------------------------------------------------

def _synthetic_run(tmp_path):
    """prep -> fake driver run -> 'fetch' = the work dir -> state files -> record -> custody."""
    payload, cust = _payload_for_driver(tmp_path)
    work, r = _run_driver(tmp_path, payload)
    assert r.returncode == 0, r.stdout + r.stderr
    shutil.rmtree(cust / "fetch", ignore_errors=True)
    shutil.copytree(work, cust / "fetch")
    st = cust / "state"; st.mkdir(exist_ok=True)
    (st / "instance_id").write_text("i-0fake00000000001\n")
    (cust / "launch_time_utc.txt").write_text("2026-10-01T01:00:00Z\n")
    (cust / "terminate_time_utc.txt").write_text("2026-10-01T02:30:00Z\n")
    (cust / "describe_launch.json").write_text(json.dumps(
        {"InstanceId": "i-0fake00000000001", "InstanceType": "r6i.16xlarge",
         "ImageId": "ami-052355af2a014bd2c", "Placement": {"AvailabilityZone": "us-east-1c"},
         "LaunchTime": "2026-10-01T01:00:00.000Z"}))
    (cust / "termination_proof.json").write_text(json.dumps(
        {"InstanceId": "i-0fake00000000001", "State": {"Code": 48, "Name": "terminated"}}))
    return payload, cust


def test_record_writes_the_launch_record_and_the_cost_line(tmp_path):
    payload, cust = _synthetic_run(tmp_path)
    r = _run([PY, str(KIT_DIR / "cloudkit.py"), "record", "--custody", str(cust)])
    assert r.returncode == 0, r.stdout + r.stderr
    rec = json.loads((cust / "launch_record.json").read_text())
    assert rec["instance_id"] == "i-0fake00000000001" and rec["az"] == "us-east-1c"
    assert rec["billed_minutes"] == 90.0 and rec["cost_usd_actual"] == round(1.5 * 4.032, 2)
    assert rec["termination_state"] == "terminated" and rec["rate_usd_per_h"] == 4.032
    assert "COST_LINE" in r.stdout and "90.0min x $4.032/h = $6.05" in r.stdout
    # the sanity checks: no terminate time -> stop; terminate before launch -> stop
    (cust / "terminate_time_utc.txt").write_text("2026-10-01T00:59:00Z\n")
    r = _run([PY, str(KIT_DIR / "cloudkit.py"), "record", "--custody", str(cust)])
    assert r.returncode == 1 and "precedes launch" in r.stdout


def test_custody_then_verify_cloud_custody_generalised(tmp_path):
    payload, cust = _synthetic_run(tmp_path)
    _run([PY, str(KIT_DIR / "cloudkit.py"), "record", "--custody", str(cust)])
    gold = tmp_path / "gold"; gold.mkdir()
    for n in ("P3_econ_fnfix.json", "P3evcl_econ.json"):
        shutil.copyfile(cust / "fetch" / "out" / n, gold / n)
    r = _run([PY, str(KIT_DIR / "cloudkit.py"), "custody", "--custody", str(cust), "--payload",
              str(payload), "--gold-dir", str(gold)])
    assert r.returncode == 0, r.stdout + r.stderr
    c = json.loads((cust / "custody_cal2026-10.json").read_text())
    assert c["ok"] is True and c["problems"] == []
    assert c["result_marker"] == "ALL_DONE_MARKER_2026_10C"
    assert c["units"]["nonzero"] == {} and c["units"]["absent"] == []
    assert c["units"]["expected"] == c["units"]["reported"] > 0
    assert set(c["remote_md5_ok"]) == set(c["payloads_before"])
    assert c["cells"]["P3_econ_fnfix"]["job_exit"] == 0
    assert c["cells"]["P3_econ_fnfix"]["peak_rss_gib"] == 1.0
    assert c["predate_controls"]["P3_econ_fnfix"] == "EQUAL"
    assert c["parallel_outputs"]["P3cutpos_econ"]["rows"] == 11      # perms 0..10
    assert c["parallel_outputs"]["NULLpos_econ"]["rows"] == 10
    assert c["cost_usd_actual"] == round(1.5 * 4.032, 2)
    # the shift-0 control result carries the main label, so it is paired with the same gold
    assert {tuple(x) for x in c["verify"]["fetched_pairs"]} == {
        ("out/P3_econ_fnfix.json", "P3_econ_fnfix.json"), ("out/P3evcl_econ.json", "P3evcl_econ.json"),
        ("out_predate_control/P3_econ_fnfix.json", "P3_econ_fnfix.json")}
    assert {x[1] for x in c["verify"]["frame_pairs"]} >= {"p3_slim_econ.parquet", "run_p3.R",
                                                           "run_predate.R", "P3cut_pos_econ.json"}

    ver = REPO / "tools" / "verify_cloud_custody.py"
    r = _run([PY, str(ver), "--custody", str(cust)])
    assert r.returncode == 0 and "CUSTODY_OK" in r.stdout, r.stdout
    assert "OK  RESULT.txt" in r.stdout and "vs" in r.stdout
    # one byte in a payload source changes -> the chain breaks, and it says which file
    (tmp_path / "frames" / "p3_slim_econ.parquet").write_bytes(b"moved under us")
    r = _run([PY, str(ver), "--custody", str(cust)])
    assert r.returncode == 1 and "CUSTODY_FAIL" in r.stdout
    assert re.search(r"^BAD .*p3_slim_econ.parquet", r.stdout, re.M), r.stdout
    # a gold that differs -> BAD with the differing key
    j = json.loads((gold / "P3_econ_fnfix.json").read_text()); j["ate"] = 0.26
    (gold / "P3_econ_fnfix.json").write_text(json.dumps(j))
    r = _run([PY, str(ver), "--custody", str(cust)])
    assert "ate: 0.25 != 0.26" in r.stdout


def test_custody_reports_a_failed_unit_and_a_missing_remote_md5_line(tmp_path):
    payload, cust = _synthetic_run(tmp_path)
    _run([PY, str(KIT_DIR / "cloudkit.py"), "record", "--custody", str(cust)])
    prog = cust / "fetch" / "progress.log"
    prog.write_text(prog.read_text().replace("SERIAL P3evcl_econ rc=0", "SERIAL P3evcl_econ rc=137"))
    (cust / "fetch" / "RESULT.txt").write_text("FAIL_MARKER_2026_10C\n")
    md = cust / "fetch" / "md5check.log"
    md.write_text(md.read_text().replace("run_p3.R: OK", "run_p3.R: FAILED"))
    dl = cust / "fetch" / "driver.log"
    dl.write_text(dl.read_text().replace("run_p3.R: OK", "run_p3.R: FAILED"))
    r = _run([PY, str(KIT_DIR / "cloudkit.py"), "custody", "--custody", str(cust), "--payload",
              str(payload)])
    assert r.returncode == 1
    c = json.loads((cust / "custody_cal2026-10.json").read_text())
    assert c["ok"] is False
    assert any("P3evcl_econ" in p and "137" in p for p in c["problems"]), c["problems"]
    assert any("run_p3.R" in p for p in c["problems"])
    assert any("FAIL_MARKER" in p for p in c["problems"])
    r = _run([PY, str(REPO / "tools" / "verify_cloud_custody.py"), "--custody", str(cust)])
    assert r.returncode == 1 and "recorded problems" in r.stdout


def test_default_verify_cloud_custody_is_unchanged():
    r = _run([PY, str(REPO / "tools" / "verify_cloud_custody.py")])
    assert r.returncode == 0 and r.stdout.rstrip().endswith("CUSTODY_OK"), r.stdout[-600:]
    # 2026-09-23: the default block checks the shipped 08-28 payload against the FROZEN 08-28
    # frames (data/frames is the October caliber since 73777aa)
    assert "data/cal2026-08-28/frames/p3_slim_econ.parquet" in r.stdout
    assert r.stdout.count("OK ") == 10                      # 6 payload lines + 4 fetched golds


def test_october_custody_dir_is_unchanged():
    """R1 F26 switch-off: tools/verify_cloud_custody.py is not edited for the R1 custody spec, and the
    October path (the one tools/compare_all.py checks) still verifies, in the same launch as the default block."""
    r = _run([PY, str(REPO / "tools" / "verify_cloud_custody.py"), "--custody", "data/cal2026-10/cloud"])
    assert r.returncode == 0 and r.stdout.rstrip().endswith("CUSTODY_OK"), r.stdout[-600:]
    lines = r.stdout.splitlines()
    assert [ln for ln in lines if ln.startswith("BAD")] == []
    spec = json.loads((REPO / "data/cal2026-10/cloud/custody_cal2026-10.json").read_text())["verify"]
    # the marker line + one line per payload pair + one per fetched cell
    assert sum(ln.startswith("OK ") for ln in lines) == 1 + len(spec["frame_pairs"]) + len(spec["fetched_pairs"])


# ---------------------------------------------------------------------------------------------
# 6. run_cloud.sh end to end on fake aws / ssh / scp, under a path with a space (2026-09-22 review)
# ---------------------------------------------------------------------------------------------

FAKE_IID, FAKE_HOST = "i-0fake0000000000f", "ubuntu@10.0.0.1"


def _fake_cloud_bin(d: pathlib.Path) -> pathlib.Path:
    """`aws` (answers the six calls run_cloud.sh makes, logs every argv), `ssh` (runs the command
    locally with HOME=$FAKE_RHOME; refuses any host but ubuntu@10.0.0.1 — the space-in-path
    defect surfaced exactly there), `scp` (copies into $FAKE_RHOME), a fast `sleep`."""
    d = _fake_bin(d)                               # Rscript, time, md5sum
    aws = d / "aws"
    aws.write_text(f"""#!/usr/bin/env python3
import datetime, json, os, sys
a = sys.argv[1:]
open(os.environ["FAKE_LOG"], "a").write("AWS " + " ".join(a) + "\\n")
def opt(n):
    return a[a.index(n) + 1] if n in a else ""
verb = a[a.index("ec2") + 1]
if verb == "run-instances":
    assert opt("--key-name") == "openalex-run" and opt("--instance-type") == "r6i.16xlarge", a
    ud = opt("--user-data"); assert ud.startswith("file://"), ud
    assert "shutdown -h +600" in open(ud[7:]).read(), ud
    print("{FAKE_IID}")
elif verb == "wait":
    pass
elif verb == "describe-instances":
    assert opt("--instance-ids") == "{FAKE_IID}", a
    q, out = opt("--query"), opt("--output")
    t0 = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=90)
    lt = t0.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if out == "text":
        print("10.0.0.1" if q.endswith("PublicIpAddress") else lt)
    elif "StateTransitionReason" in q:
        print(json.dumps({{"InstanceId": "{FAKE_IID}", "State": {{"Code": 48, "Name": "terminated"}},
                          "StateTransitionReason": "User initiated", "InstanceType": "r6i.16xlarge",
                          "Placement": "us-east-1c", "LaunchTime": lt}}))
    else:
        print(json.dumps({{"InstanceId": "{FAKE_IID}", "InstanceType": "r6i.16xlarge",
                          "ImageId": "ami-052355af2a014bd2c",
                          "Placement": {{"AvailabilityZone": "us-east-1c"}}, "LaunchTime": lt,
                          "PublicIpAddress": "10.0.0.1", "State": {{"Code": 16, "Name": "running"}}}}))
elif verb == "terminate-instances":
    assert opt("--instance-ids") == "{FAKE_IID}", a
    print(json.dumps({{"TerminatingInstances": [{{"InstanceId": "{FAKE_IID}"}}]}}))
else:
    sys.exit("fake aws: unexpected verb " + verb)
""")
    aws.chmod(aws.stat().st_mode | stat.S_IEXEC)
    ssh = d / "ssh"
    ssh.write_text(f"""#!/bin/bash
# fake ssh: consume options, check the host, run the command locally in the fake instance home
while [ $# -gt 0 ]; do case "$1" in -i|-o) shift 2 ;; -*) shift ;; *) break ;; esac; done
host="$1"; shift
echo "SSH host=$host cmd=$*" >> "$FAKE_LOG"
[ "$host" = "{FAKE_HOST}" ] || {{ echo "fake ssh: unexpected host '$host'" >&2; exit 255; }}
[ $# -gt 0 ] || exit 0
cmd="$*"
case "$cmd" in
  *"bash ~/bootstrap.sh"*)      # never run the real recipe (apt/rustup); pretend it finished
    mkdir -p "$FAKE_RHOME/work"
    echo "R 4.6.1 DIDmultiplegtDYN 2.4.0 fixest 0.12.1 (fake)" > "$FAKE_RHOME/work/versions.txt"
    echo BOOTSTRAP_DONE > "$FAKE_RHOME/work/bootstrap_ready.txt"; exit 0 ;;
esac
cd "$FAKE_RHOME" && HOME="$FAKE_RHOME" exec bash -c "$cmd"
""")
    ssh.chmod(ssh.stat().st_mode | stat.S_IEXEC)
    scp = d / "scp"
    scp.write_text(f"""#!/bin/bash
# fake scp: every non-option operand but the last is a local source; the last is user@host:~/dest
n=0; while [ $# -gt 0 ]; do case "$1" in -i|-o) shift 2 ;; -*) shift ;; *) n=$((n+1)); eval "s$n=\\"\\$1\\""; shift ;; esac; done
eval "dest=\\"\\$s$n\\""
echo "SCP n=$n dest=$dest" >> "$FAKE_LOG"
case "$dest" in "{FAKE_HOST}:~/"*) ;; *) echo "fake scp: unexpected destination '$dest'" >&2; exit 1 ;; esac
d="$FAKE_RHOME/${{dest#{FAKE_HOST}:~/}}"
case "$d" in */) mkdir -p "$d" ;; *) mkdir -p "$(dirname "$d")" ;; esac
i=1; while [ $i -lt $n ]; do eval "src=\\"\\$s$i\\""; [ -e "$src" ] || {{ echo "fake scp: no such source '$src'" >&2; exit 1; }}; cp -R "$src" "$d"; i=$((i+1)); done
""")
    scp.chmod(scp.stat().st_mode | stat.S_IEXEC)
    sl = d / "sleep"
    sl.write_text("#!/bin/bash\n/bin/sleep 0.05\n")      # the launcher's waits, 200x faster
    sl.chmod(sl.stat().st_mode | stat.S_IEXEC)
    return d


def test_run_cloud_end_to_end_on_fake_aws_under_a_path_with_a_space(tmp_path):
    base = tmp_path / "with space"; base.mkdir()
    payload, cust = _payload_for_driver(base)
    fake = _fake_cloud_bin(base / "bin")
    rhome = base / "instance_home"; rhome.mkdir()
    key = base / "fake.pem"; key.write_text("not a key\n")
    log = base / "calls.log"
    env = dict(os.environ, PATH=f"{fake}:{os.environ['PATH']}", FAKE_LOG=str(log),
               FAKE_RHOME=str(rhome), TIME_BIN=str(fake / "time"), MD5SUM=str(fake / "md5sum"))
    cmd = ["bash", str(KIT_DIR / "run_cloud.sh"), "--payload", str(payload), "--custody", str(cust),
           "--key", str(key), "--poll-secs", "1"]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=REPO, timeout=600)
    watcher = (cust / "watcher.log").read_text() if (cust / "watcher.log").is_file() else ""
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:] + watcher[-2000:]
    calls = log.read_text()
    assert len(re.findall(r"^AWS .*ec2 run-instances", calls, re.M)) == 1
    assert len(re.findall(r"^AWS .*ec2 terminate-instances", calls, re.M)) == 1
    assert "unexpected host" not in r.stderr and "unexpected host" not in watcher
    for step in ("launched", "ssh_up", "bootstrapped", "md5_ok", "driver_started", "run_done",
                 "fetched", "terminated"):
        assert (cust / "state" / step).is_file(), step
    assert (cust / "fetch" / "RESULT.txt").read_text().strip() == "ALL_DONE_MARKER_2026_10C"
    assert (cust / "fetch" / "versions.txt").is_file() and (cust / "fetch" / "md5check.log").is_file()
    assert (cust / "fetch" / "out" / "P3_econ_fnfix.json").is_file()
    assert (cust / "md5check.log").read_text().count(": OK") == len(_md5_lines(payload / "payload.md5"))
    rec = json.loads((cust / "launch_record.json").read_text())
    assert rec["instance_id"] == FAKE_IID and rec["termination_state"] == "terminated"
    assert 0 < rec["billed_minutes"] < 30 and rec["cost_usd_actual"] < 2.1
    c = json.loads((cust / "custody_cal2026-10.json").read_text())
    assert c["ok"] is True and c["problems"] == [], c["problems"]
    assert "CUSTODY_OK" in watcher and "TERMINATED " + FAKE_IID in watcher
    # every serial cell really ran on the "instance" (the job list was not eaten through stdin)
    nser = len(ck.read_jobs(payload / "jobs_serial.txt"))
    assert len(re.findall(r"^SERIAL \S+ rc=0", (cust / "fetch" / "progress.log").read_text(), re.M)) == nser
    # the launcher refuses to run a second time against the same custody dir without --resume
    r2 = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=REPO, timeout=120)
    assert r2.returncode == 1 and "pass --resume" in r2.stderr
    assert len(re.findall(r"^AWS .*ec2 run-instances", log.read_text(), re.M)) == 1


def test_run_cloud_process_probes_cannot_match_their_own_shell():
    """procps `pgrep -f PATTERN` matches every process whose command line contains PATTERN — and
    the remote `bash -c '... pgrep -f "bash driver.sh" ...'` contains it. The bracket idiom
    (`[b]ash`) matches the driver's `bash driver.sh` and not the probe's own line."""
    body = (KIT_DIR / "run_cloud.sh").read_text()
    probes = re.findall(r'pgrep -f "([^"]+)"', body)
    assert probes, "no pgrep probes found"
    for pat in probes:
        assert re.match(r"^\[.\]", pat), f"pgrep pattern {pat!r} would match the shell that runs it"
    assert "SSH_OPTS" not in body, "ssh options must be passed quoted through rssh()/rscp()"
    assert "--ignore-failed-read" not in body, "GNU-only tar flag (the fetch must also run on BSD tar)"
