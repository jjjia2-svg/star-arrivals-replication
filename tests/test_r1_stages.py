# -*- coding: utf-8 -*-
"""pipeline/aws/r1/run_stages.py, the stage tables and the P4 job specs (fake aws, toy git repo)."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import threading

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for p in (REPO / "pipeline" / "aws" / "r1", REPO / "tests", REPO / "tools"):
    sys.path.insert(0, str(p))
import r1_input_inventory as inv    # noqa: E402
import r1kit                        # noqa: E402
import run_stages as rs             # noqa: E402
from r1_fakes import install_fake_aws   # noqa: E402

P4_JOBS = ("jp", "j0", "j1a", "j1b", "final")
TABLE = {"schema": "sar.r1.stages.v1", "job": "toy", "complete": True, "stages": [
    {"name": "s1", "owner": "F25", "cmd": 'mkdir -p "$STAGE_OUT" && cp "$REPO_DIR/data.txt" "$STAGE_OUT/a.txt"',
     "inputs": ["repo:data.txt"], "outputs": ["work:prod/s1"], "est_min": 1, "needs": []},
    {"name": "s2", "owner": "F25",
     "cmd": '[ ! -e "$WORK/fail_s2" ] || exit 3; mkdir -p "$STAGE_OUT" && { cat "$WORK/prod/s1/a.txt"; echo two; } > "$STAGE_OUT/b.txt"',
     "inputs": ["stage:s1"], "outputs": ["work:prod/s2"], "est_min": 1, "needs": ["s1"]},
    {"name": "s3", "owner": "F25",
     "cmd": 'mkdir -p "$REPO_DIR/output" && { cat "$WORK/prod/s2/b.txt"; echo three; } > "$REPO_DIR/output/c.txt"',
     "inputs": ["stage:s2"], "outputs": ["repo:output/c.txt"], "est_min": 1, "needs": ["s2"]}]}


def _git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def toy(tmp_path, monkeypatch):
    fake = install_fake_aws(tmp_path, monkeypatch)
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    repo = tmp_path / "toy repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "data.txt").write_text("seed\n")
    (repo / "tools").mkdir()
    (repo / "tools" / "hello.sh").write_text('mkdir -p "$STAGE_OUT" && echo hi > "$STAGE_OUT/h.txt"\n')
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "toy")
    return fake, repo, _git(repo, "rev-parse", "HEAD")


def _run(tmp_path, repo, commit, table, work, job="j-unit-01", *extra):
    t = tmp_path / f"{work.name}.table.json"
    t.write_text(json.dumps(table))
    return rs.main(["--table", str(t), "--repo", str(repo), "--commit", commit, "--prefix", f"s3://fake-bucket/r1/runs/{job}",
                    "--work", str(work), "--out", str(work / "out"), *extra])


def test_stages_run_in_order_and_push_products_and_markers(tmp_path, toy):
    fake, repo, commit = toy
    assert _run(tmp_path, repo, commit, TABLE, tmp_path / "w") == 0
    stages = fake["s3root"] / "fake-bucket" / "r1" / "runs" / "j-unit-01" / "stages"
    assert {p.name for p in stages.glob("*.done.json")} == {"s1.done.json", "s2.done.json", "s3.done.json"}
    assert (stages / "s3" / "files" / "repo" / "output" / "c.txt").read_text() == "seed\ntwo\nthree\n"
    s = json.loads((tmp_path / "w" / "out" / "summary.json").read_text())
    assert [x["status"] for x in s["stages"]] == ["ran", "ran", "ran"] and s["result"] == "OK"


def test_a_failing_stage_stops_the_job_and_names_itself(tmp_path, toy):
    fake, repo, commit = toy
    (tmp_path / "w").mkdir()
    (tmp_path / "w" / "fail_s2").touch()
    assert _run(tmp_path, repo, commit, TABLE, tmp_path / "w") == 1
    assert (tmp_path / "w" / "out" / "RESULT.txt").read_text().startswith("STAGE_FAIL s2 rc=3")
    stages = fake["s3root"] / "fake-bucket" / "r1" / "runs" / "j-unit-01" / "stages"
    assert (stages / "s1.done.json").is_file() and not (stages / "s2.done.json").exists()


def test_a_stage_script_is_copied_from_the_commit(tmp_path, toy):
    _, repo, commit = toy
    t = {**TABLE, "stages": [{"name": "h", "owner": "F25", "script": "tools/hello.sh", "cmd": 'bash "$WORK/hello.sh"',
                              "inputs": [], "outputs": ["work:prod/h"], "est_min": 1, "needs": []}]}
    (repo / "tools" / "hello.sh").write_text("exit 9\n")             # the working tree differs from the commit
    assert _run(tmp_path, repo, commit, t, tmp_path / "w") == 0


@pytest.mark.parametrize("bad", [
    lambda t: t["stages"].append(dict(t["stages"][0])),                           # duplicate name
    lambda t: t["stages"][0].update(inputs=["repo:../x"]),
    lambda t: t["stages"][0].update(outputs=["data:r1/derived/"]),
    lambda t: t["stages"][1].update(needs=["s3"]),                                # a need that runs later
    lambda t: t["stages"][0].pop("est_min")])
def test_table_validation_refuses_bad_tables(tmp_path, bad):
    t = json.loads(json.dumps(TABLE))
    bad(t)
    p = tmp_path / "t.json"
    p.write_text(json.dumps(t))
    with pytest.raises(rs.StageError):
        rs.load_table(p)


def test_refuses_off_aws_and_a_prefix_outside_r1_runs(tmp_path, toy, monkeypatch):
    _, repo, commit = toy
    with pytest.raises(SystemExit, match="r1/runs"):
        _run(tmp_path, repo, commit, TABLE, tmp_path / "w", "../rk1")
    monkeypatch.delenv("SAR_HOST")
    with pytest.raises(SystemExit, match="R1 instance"):
        _run(tmp_path, repo, commit, TABLE, tmp_path / "w2")


def test_fingerprint_follows_the_command_and_the_inputs(toy):
    _, repo, commit = toy
    st = TABLE["stages"][0]
    a = rs.fingerprint(st, repo=repo, commit=commit, pins={}, env_pins={}, done={})
    assert a == rs.fingerprint(dict(st), repo=repo, commit=commit, pins={}, env_pins={}, done={})
    assert a != rs.fingerprint(dict(st, cmd=st["cmd"] + " "), repo=repo, commit=commit, pins={}, env_pins={}, done={})
    pins = {"pins": {"r1/derived/": {"manifest_sha256": "1" * 64}}}
    b = rs.fingerprint(dict(st, inputs=["data:r1/derived/"]), repo=repo, commit=commit, pins=pins, env_pins={}, done={})
    pins["pins"]["r1/derived/"]["manifest_sha256"] = "2" * 64
    assert b != rs.fingerprint(dict(st, inputs=["data:r1/derived/"]), repo=repo, commit=commit, pins=pins, env_pins={}, done={})


# ---- the real tables and job specs ----------------------------------------------------------------
def test_every_stage_table_loads_and_jp_is_complete():
    """F30: a table may be flipped to complete only when it carries its REQUIRED_STAGES (no test edit per flip)."""
    for job in P4_JOBS:
        t = rs.load_table(REPO / "config" / "r1" / "stages" / f"{job}.json")
        assert t["job"] == job and t["stages"][0]["name"] in ("verify_inputs", "repo_manifest")
    assert rs.load_table(REPO / "config" / "r1" / "stages" / "jp.json")["complete"] is True
    for p in sorted((REPO / "config" / "r1" / "stages").glob("*.json")):
        t = rs.load_table(p)
        if t.get("complete"):
            missing = set(r1kit.REQUIRED_STAGES[t["job"]]) - {s["name"] for s in t["stages"]}
            assert not missing, (p.name, sorted(missing))


def test_job_data_sync_equals_the_inventory():
    """Every job spec (R1 wave 1 integration: all of config/r1/jobs/, not only the P4 four) syncs exactly
    what `tools/r1_input_inventory.py sync <job>` prints; jobs the scanner cannot see list theirs in JOB_EXTRA."""
    rows = inv.read_tsv(REPO / "config" / "r1" / "input_inventory.tsv")
    jobs = sorted(p.stem for p in (REPO / "config" / "r1" / "jobs").glob("*.json"))
    assert {"j0", "j1a", "j1b", "final", "test_big", "recder", "dossier", "rankrepro", "rankdiff", "merge"} <= set(jobs)
    for job in jobs:
        assert r1kit.load_job(job)["data_sync"] == inv.sync_pairs(rows, job), job



def test_every_job_whose_scripts_reach_run_screening_syncs_the_0705_table():
    """dossier-01 failed at start (W2-INT): dossier_pack calls restake_equiv.connect, and run_screening resolves
    /data/openalex_pipeline/derived/u1_edges_full_2026-07-05 at import, but dossier synced only the 11-school
    sub-tables and the U2 map. Every job whose copied or staged scripts use restake_equiv or run_screening must
    sync that table (whole or its sub-tables)."""
    import re                                                             # noqa: PLC0415
    pat = re.compile(r"restake_equiv\.|import restake_equiv|run_screening\.|import run_screening")
    users = {}
    for p in sorted((REPO / "config" / "r1" / "jobs").glob("*.json")):
        job = r1kit.load_job(p.stem)
        scripts = {src for src, _dst in job["copy_from_tip"]}
        if job.get("stages"):
            scripts |= {s["script"] for s in rs.load_table(REPO / job["stages"])["stages"] if s.get("script")}
        hits = sorted(s for s in scripts if s.endswith(".py") and (REPO / s).is_file()
                      and pat.search((REPO / s).read_text(encoding="utf-8")))
        if hits:
            users[p.stem] = hits
            assert any(src.startswith("u1_edges_full_2026-07-05/") for src, _dst in job["data_sync"]), (p.stem, hits)
    assert {"dossier", "rk6b", "rankrepro", "j1a"} <= set(users)          # the positive control: the rule bites

def test_every_p4_job_renders_under_16kb_and_parses(tmp_path):
    exp = (REPO / "config" / "r1" / "expected_versions.txt").read_text(encoding="utf-8")
    pins = json.loads((REPO / "config" / "r1" / "env_pins.json").read_text(encoding="utf-8"))["layers"]
    for kind in (*P4_JOBS, "pin", "envbuild"):
        job = r1kit.load_job(kind)
        text = r1kit.render_userdata(job, job_id=f"{kind}-99", commit="c" * 40, repo_dir="/srv/My Dir /Research/r",
                                     bucket="fake-bucket", base_sha="a" * 64, deadline_epoch=1_800_000_000,
                                     env_pins=pins, expected_text=exp)
        f = tmp_path / f"{kind}.sh"
        f.write_text(text)
        assert subprocess.run(["bash", "-n", str(f)]).returncode == 0, kind
        assert len(text.encode()) < r1kit.MAX_USERDATA_BYTES, kind
        assert job["sar_host"] == "ec2-r1" and job["hard_min"] <= r1kit.HARD_MIN_MAX


def test_launch_refuses_an_incomplete_stage_table(kit_env_stage, toy_stage_job, capsys):
    """A toy job and table, so the F30 flips of the real tables need no edit here."""
    toy_stage_job["table"] = {**TABLE, "job": "j0", "complete": False}
    with pytest.raises(r1kit.KitError, match="incomplete"):
        r1kit.launch("stagey", "j0-unit-01", "HEAD", env=kit_env_stage, now=1_800_000_000)
    r1kit.launch("stagey", "j0-unit-02", "HEAD", env=kit_env_stage, now=1_800_000_000, dry_run=True)
    assert "INCOMPLETE STAGE TABLE" in capsys.readouterr().out
    toy_stage_job["table"] = {**TABLE, "job": "j0", "complete": True}          # complete, but no sandbox/gate1 rows
    with pytest.raises(r1kit.KitError, match="sandbox"):
        r1kit.launch("stagey", "j0-unit-03", "HEAD", env=kit_env_stage, now=1_800_000_000)
    r1kit.launch("stagey", "j0-unit-04", "HEAD", env=kit_env_stage, now=1_800_000_000, dry_run=True)
    out = capsys.readouterr().out
    assert "INCOMPLETE STAGE TABLE" in out and "gate1" in out and "incomplete (complete=false" not in out


@pytest.fixture
def toy_stage_job(tmp_path, monkeypatch, kit_env_stage):
    d = tmp_path / "jobs"
    d.mkdir()
    spec = json.loads((REPO / "config" / "r1" / "jobs" / "test.json").read_text())
    spec.update(kind="stagey", stages="config/r1/stages/stagey.json")
    (d / "stagey.json").write_text(json.dumps(spec))
    monkeypatch.setattr(r1kit, "JOBS_DIR", d)
    holder = {"table": None}
    monkeypatch.setattr(r1kit, "_git_show", lambda commit, path: json.dumps(holder["table"])
                        if path == "config/r1/stages/stagey.json" else (REPO / path).read_text(encoding="utf-8"))
    return holder


def test_launch_refuses_a_stage_script_missing_at_the_commit():
    t = json.loads((REPO / "config" / "r1" / "stages" / "jp.json").read_text())
    probs = r1kit.check_stage_table({"stages": "config/r1/stages/jp.json"}, "c" * 40,
                                    show=lambda path: json.dumps(t), exists=lambda path: path != "pipeline/aws/r1/run_cells.py")
    assert probs and "run_cells.py" in probs[0]
    assert r1kit.check_stage_table({"stages": "config/r1/stages/jp.json"}, "c" * 40,
                                   show=lambda path: json.dumps(t), exists=lambda path: True) == []


@pytest.fixture
def kit_env_stage(tmp_path, monkeypatch):
    install_fake_aws(tmp_path, monkeypatch)
    monkeypatch.setattr(r1kit, "RUNS_LOCAL", tmp_path / "runs")
    monkeypatch.setattr(r1kit, "LEDGER", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(r1kit, "require_clean_tree", lambda: None)
    monkeypatch.setattr(r1kit, "resolve_commit", lambda ref: "c" * 40)
    monkeypatch.setattr(r1kit, "make_inc_bundle", lambda base, tip, out, **kw: pathlib.Path(out).write_bytes(b"b"))
    monkeypatch.setattr(r1kit, "base_bundle_sha", lambda: "a" * 64)
    monkeypatch.setattr(r1kit, "_git_show", lambda commit, path: (REPO / path).read_text(encoding="utf-8"))
    monkeypatch.setattr(r1kit, "_git_exists", lambda commit, path: (REPO / path).exists())
    return {"SAR_S3_BUCKET": "fake-bucket", "AWS_REGION": "us-east-1"}


def _resume_dir(fake, job, dst):
    shutil.copytree(fake["s3root"] / "fake-bucket" / "r1" / "runs" / job / "stages", dst)
    return dst


def _products(work, repo):
    return {"b": (work / "prod" / "s2" / "b.txt").read_bytes(), "c": (repo / "output" / "c.txt").read_bytes()}


def test_resume_after_a_failed_stage_gives_byte_equal_products(tmp_path, toy):
    fake, repo, commit = toy
    assert _run(tmp_path, repo, commit, TABLE, tmp_path / "a", "j-unit-01") == 0
    whole = _products(tmp_path / "a", repo)
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "fail_s2").touch()
    assert _run(tmp_path, repo, commit, TABLE, tmp_path / "b", "j-unit-02") == 1
    rd = _resume_dir(fake, "j-unit-02", tmp_path / "resume")
    assert _run(tmp_path, repo, commit, TABLE, tmp_path / "c", "j-unit-03", "--resume-dir", str(rd)) == 0
    s = json.loads((tmp_path / "c" / "out" / "summary.json").read_text())
    assert [x["status"] for x in s["stages"]] == ["skipped", "ran", "ran"]
    assert _products(tmp_path / "c", repo) == whole
    assert (fake["s3root"] / "fake-bucket" / "r1" / "runs" / "j-unit-03" / "stages" / "s1.done.json").is_file()


def _statuses(work):
    return [x["status"] for x in json.loads((work / "out" / "summary.json").read_text())["stages"]]


def test_a_changed_command_reruns_its_stage(tmp_path, toy):
    """Ruling R12: the changed stage reruns; later stages rerun only if its outputs changed."""
    fake, repo, commit = toy
    assert _run(tmp_path, repo, commit, TABLE, tmp_path / "a", "j-unit-04") == 0
    rd = _resume_dir(fake, "j-unit-04", tmp_path / "resume")
    same = json.loads(json.dumps(TABLE))
    same["stages"][0]["cmd"] += " && true"                          # new command, same bytes out
    assert _run(tmp_path, repo, commit, same, tmp_path / "c", "j-unit-05", "--resume-dir", str(rd)) == 0
    assert _statuses(tmp_path / "c") == ["ran", "skipped", "skipped"]
    other = json.loads(json.dumps(TABLE))
    other["stages"][0]["cmd"] = 'mkdir -p "$STAGE_OUT" && echo other > "$STAGE_OUT/a.txt"'
    assert _run(tmp_path, repo, commit, other, tmp_path / "d", "j-unit-06", "--resume-dir", str(rd)) == 0
    assert _statuses(tmp_path / "d") == ["ran", "ran", "ran"]
    assert (repo / "output" / "c.txt").read_text() == "other\ntwo\nthree\n"


def test_a_restored_product_that_does_not_match_its_marker_reruns(tmp_path, toy):
    fake, repo, commit = toy
    assert _run(tmp_path, repo, commit, TABLE, tmp_path / "a", "j-unit-07") == 0
    rd = _resume_dir(fake, "j-unit-07", tmp_path / "resume")
    (rd / "s1" / "files" / "work" / "prod" / "s1" / "a.txt").write_text("tampered\n")
    assert _run(tmp_path, repo, commit, TABLE, tmp_path / "c", "j-unit-08", "--resume-dir", str(rd)) == 0
    st = json.loads((tmp_path / "c" / "out" / "summary.json").read_text())["stages"]
    assert st[0]["status"] == "ran" and (tmp_path / "c" / "prod" / "s1" / "a.txt").read_text() == "seed\n"


def test_a_resume_always_stage_reruns_on_resume(tmp_path, toy):
    """Review (P3b): verify_inputs and relink act on the new instance's /data; a resume must run them again."""
    fake, repo, commit = toy
    t = json.loads(json.dumps(TABLE))
    t["stages"][0]["resume"] = "always"
    assert _run(tmp_path, repo, commit, t, tmp_path / "a", "j-unit-11") == 0
    rd = _resume_dir(fake, "j-unit-11", tmp_path / "resume")
    assert _run(tmp_path, repo, commit, t, tmp_path / "c", "j-unit-12", "--resume-dir", str(rd)) == 0
    assert _statuses(tmp_path / "c") == ["ran", "skipped", "skipped"]
    bad = json.loads(json.dumps(TABLE))
    bad["stages"][0]["resume"] = "sometimes"
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(rs.StageError):
        rs.load_table(p)


def test_input_custody_stages_always_rerun_in_the_real_tables():
    for job in P4_JOBS:
        for s in rs.load_table(REPO / "config" / "r1" / "stages" / f"{job}.json")["stages"]:
            if s["name"] in ("verify_inputs", "relink", "repo_manifest"):
                assert s.get("resume") == "always", (job, s["name"])


def test_cell_reports_reach_the_summary_and_the_out_dir_has_a_manifest(tmp_path, toy):
    """Review (P3b): a JP DIFF must be readable from summary.json; other files need MANIFEST.sha256 for a fetch."""
    fake, repo, commit = toy
    t = {**TABLE, "stages": [{"name": "cells_rmac", "owner": "F25",
                              "cmd": 'mkdir -p "$STAGE_OUT" && echo \'{"A": {"status": "DIFF", "first_diff": "ATE: 1 != 2"}}\' > "$STAGE_OUT/cells_report_rmac.json"',
                              "inputs": [], "outputs": ["work:prod/cells_rmac"], "est_min": 1, "needs": []}]}
    assert _run(tmp_path, repo, commit, t, tmp_path / "w") == 0
    s = json.loads((tmp_path / "w" / "out" / "summary.json").read_text())
    assert s["reports"]["cells_rmac"]["cells_report_rmac.json"]["A"]["status"] == "DIFF"
    man = (tmp_path / "w" / "out" / "MANIFEST.sha256").read_text()
    assert "  summary.json" in man and "  logs/cells_rmac.log" in man


# ---- the sandbox read audit through run_stages (J0 review #5 / #7, accepted in part 2026-10-16) ----------
R1DIR = REPO / "pipeline" / "aws" / "r1"
linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"),
                                reason="the sandbox watcher is inotify (Linux); these run on the AWS test runner")
WATCH_HELPER = '''import pathlib, sys
sys.path.insert(0, sys.argv[1])
import sandbox
work = pathlib.Path(sys.argv[3])
if sys.argv[2] == "start":
    sandbox.start_watcher(repo=sys.argv[4], ref=sys.argv[5], work=work)
else:
    sys.exit(0 if sandbox.stop_watcher(work / sandbox.PID_NAME) == "stopped" else 1)
'''


@pytest.fixture
def watchers(tmp_path):
    """Kill any watcher a failed test left behind."""
    yield
    for pid_file in tmp_path.glob("*/sandbox_watch.pid"):
        try:
            os.kill(int(pid_file.read_text().split()[0]), signal.SIGKILL)
        except (OSError, ValueError, IndexError):
            pass


def _watched_table(tmp_path, repo):
    """sandbox starts the real watcher (as purge does), s1 and s2 read a watched 08-28 file, sandbox_check stops it."""
    helper = tmp_path / "watch_helper.py"
    helper.write_text(WATCH_HELPER, encoding="utf-8")
    ref = tmp_path / "ref"
    ref.mkdir(exist_ok=True)
    (repo / "data" / "cal2026-08-28").mkdir(parents=True, exist_ok=True)
    (repo / "data" / "cal2026-08-28" / "x.csv").write_text("x\n")
    h = f'"$PY" "{helper}" "{R1DIR}"'
    read = 'cat "$REPO_DIR/data/cal2026-08-28/x.csv" > /dev/null && mkdir -p "$STAGE_OUT" && echo {n} > "$STAGE_OUT/{n}.txt"'
    return {"schema": "sar.r1.stages.v1", "job": "toy", "complete": True, "stages": [
        {"name": "sandbox", "owner": "F2", "cmd": f'{h} start "$WORK" "$REPO_DIR" "{ref}" && mkdir -p "$STAGE_OUT"',
         "inputs": [], "outputs": ["work:prod/sandbox"], "est_min": 1, "needs": [], "resume": "always"},
        {"name": "s1", "owner": "F25", "cmd": read.format(n="s1"), "inputs": [], "outputs": ["work:prod/s1"],
         "est_min": 1, "needs": ["sandbox"]},
        {"name": "s2", "owner": "F25", "cmd": read.format(n="s2"), "inputs": ["stage:s1"], "outputs": ["work:prod/s2"],
         "est_min": 1, "needs": ["s1"]},
        {"name": "sandbox_check", "owner": "F2", "cmd": f'{h} stop "$WORK" && mkdir -p "$STAGE_OUT"', "inputs": [],
         "outputs": ["work:prod/sandbox_check"], "est_min": 1, "needs": ["s2"], "resume": "always"}]}


def test_run_stages_and_the_watcher_agree_on_their_file_names():
    import sandbox as sb
    assert (rs.WATCH_PID, rs.END, rs.READS_DIR) == (sb.PID_NAME, sb.END, "reads")


@linux_only
def test_each_audited_stage_ends_its_log_and_binds_it_to_its_marker(tmp_path, toy, watchers):
    """Before: a stage's marker said nothing about its read log, and nothing waited for the watcher to finish
    with the stage before the log was pushed."""
    fake, repo, commit = toy
    t = _watched_table(tmp_path, repo)
    assert _run(tmp_path, repo, commit, t, tmp_path / "a", "j-unit-31") == 0, (tmp_path / "a" / "out" / "RESULT.txt").read_text()
    reads = tmp_path / "a" / "reads"
    assert (reads / "s1.tsv").read_text().splitlines() == ["s1\tdata/cal2026-08-28/x.csv", f"s1\t{rs.END}"]
    for s in ("sandbox", "s2", "sandbox_check"):
        assert (reads / f"{s}.tsv").read_text().splitlines()[-1] == f"{s}\t{rs.END}", s
    stages = fake["s3root"] / "fake-bucket" / "r1" / "runs" / "j-unit-31" / "stages"
    for s in ("sandbox", "s1", "s2"):
        m = json.loads((stages / f"{s}.done.json").read_text())
        assert m["reads_sha256"] == rs.sha256_file(reads / f"{s}.tsv") == rs.sha256_file(stages / "_reads" / f"{s}.tsv")
    assert "reads_sha256" not in json.loads((stages / "sandbox_check.done.json").read_text())   # watcher gone by then


@linux_only
def test_a_restored_stage_needs_its_bound_log_and_keeps_it(tmp_path, toy, watchers):
    """Before: a restored stage's products were checked against its marker, its read log never; a missing or
    edited log still let it be restored."""
    fake, repo, commit = toy
    t = _watched_table(tmp_path, repo)
    assert _run(tmp_path, repo, commit, t, tmp_path / "a", "j-unit-32") == 0
    rd = _resume_dir(fake, "j-unit-32", tmp_path / "resume")
    assert _run(tmp_path, repo, commit, t, tmp_path / "b", "j-unit-33", "--resume-dir", str(rd)) == 0
    assert _statuses(tmp_path / "b") == ["ran", "skipped", "skipped", "ran"]
    for s in ("s1", "s2"):                                           # the authenticated prior audit travels on
        assert (tmp_path / "b" / "reads" / f"{s}.tsv").read_bytes() == (rd / "_reads" / f"{s}.tsv").read_bytes()
    rd2 = _resume_dir(fake, "j-unit-33", tmp_path / "resume2")
    log = rd2 / "_reads" / "s1.tsv"
    log.write_text(log.read_text().replace("s1\tdata/cal2026-08-28/x.csv\n", ""))     # a read dropped after the fact
    assert _run(tmp_path, repo, commit, t, tmp_path / "c", "j-unit-34", "--resume-dir", str(rd2)) == 0
    assert _statuses(tmp_path / "c") == ["ran", "ran", "skipped", "ran"]
    assert (tmp_path / "c" / "reads" / "s1.tsv").read_text().splitlines() == ["s1\tdata/cal2026-08-28/x.csv",
                                                                              f"s1\t{rs.END}"]


def test_run_stages_waits_for_the_watchers_acknowledgement(tmp_path, toy, monkeypatch):
    """J0 review #7: with a watcher up, a stage runs only after the watcher has taken in its status line
    (it creates reads/<stage>.tsv then). Here s1 leaves a pid file and closes its own log, but no watcher exists:
    s2 must stop at its boundary and never run."""
    fake, repo, commit = toy
    monkeypatch.setattr(rs, "WATCH_WAIT_SECS", 0.5)
    t = {**TABLE, "stages": [
        {"name": "s1", "owner": "F2", "cmd": 'mkdir -p "$STAGE_OUT" "$WORK/reads" && printf \'s1\\t__END__\\n\' >> '
                                             '"$WORK/reads/s1.tsv" && echo 999999 > "$WORK/sandbox_watch.pid"',
         "inputs": [], "outputs": ["work:prod/s1"], "est_min": 1, "needs": []},
        {"name": "s2", "owner": "F25", "cmd": 'touch "$WORK/ran_s2" && mkdir -p "$STAGE_OUT"', "inputs": ["stage:s1"],
         "outputs": ["work:prod/s2"], "est_min": 1, "needs": ["s1"]}]}
    assert _run(tmp_path, repo, commit, t, tmp_path / "w", "j-unit-35") == 1
    result = (tmp_path / "w" / "out" / "RESULT.txt").read_text()
    assert result.startswith("STAGE_FAIL s2 ") and "did not acknowledge the stage boundary" in result
    assert not (tmp_path / "w" / "ran_s2").exists()
    assert _statuses(tmp_path / "w") == ["ran", "failed"]


@linux_only
def test_a_stalled_watcher_cannot_charge_a_read_to_the_next_stage(tmp_path, toy, watchers, monkeypatch):
    """J0 review #7: the watcher reads the status file when it handles a status event, not when the event
    was queued. Stalled across a boundary, it charged one stage's reads to the next - here frames' read of an
    October gold would land on cells_rmac, which may read it. The watcher is stopped just before 'STAGE frames' is
    written and resumed 1.5 s later: run_stages must wait, and the read stays frames' (G_READ_FAIL)."""
    import sandbox as sb
    fake, repo, commit = toy
    monkeypatch.setattr(rs, "WATCH_WAIT_SECS", 10)
    helper = tmp_path / "watch_helper.py"
    helper.write_text(WATCH_HELPER, encoding="utf-8")
    ref = tmp_path / "ref"
    (ref / "analysis" / "expected").mkdir(parents=True)
    (ref / "analysis" / "expected" / "P1.json").write_text("{}\n")
    h = f'"$PY" "{helper}" "{R1DIR}"'
    out = 'mkdir -p "$STAGE_OUT"'
    t = {"schema": "sar.r1.stages.v1", "job": "toy", "complete": True, "stages": [
        {"name": "sandbox", "owner": "F2", "cmd": f'{h} start "$WORK" "$REPO_DIR" "{ref}" && {out}', "inputs": [],
         "outputs": ["work:prod/sandbox"], "est_min": 1, "needs": [], "resume": "always"},
        {"name": "frames", "owner": "F25", "cmd": f'cat "{ref}/analysis/expected/P1.json" > /dev/null && {out}',
         "inputs": [], "outputs": ["work:prod/frames"], "est_min": 1, "needs": ["sandbox"]},
        {"name": "cells_rmac", "owner": "F25", "cmd": out, "inputs": ["stage:frames"], "outputs": ["work:prod/cells_rmac"],
         "est_min": 1, "needs": ["frames"]},
        {"name": "sandbox_check", "owner": "F2", "cmd": f'{h} stop "$WORK" && {out}', "inputs": [],
         "outputs": ["work:prod/sandbox_check"], "est_min": 1, "needs": ["cells_rmac"], "resume": "always"}]}
    work = tmp_path / "w"
    real = rs._status_local

    def stall_then_write(w, text):
        if text == "STAGE frames":
            pid = int((work / sb.PID_NAME).read_text().split()[0])
            os.kill(pid, signal.SIGSTOP)
            threading.Timer(1.5, os.kill, (pid, signal.SIGCONT)).start()
        return real(w, text)

    monkeypatch.setattr(rs, "_status_local", stall_then_write)
    assert _run(tmp_path, repo, commit, t, work, "j-unit-36") == 0, (work / "out" / "RESULT.txt").read_text()
    reads, stages, ended, _ = sb.collect_reads([work / "reads"])
    assert ("frames", "ref:analysis/expected/P1.json") in reads
    assert not any(p.startswith("ref:") for s, p in reads if s != "frames")
    allow = tmp_path / "allow.txt"
    allow.write_text("ref:analysis/expected/**\tB0\tcells_rmac\tthe toy gold the toy cells stage may read from the "
                     "reference copy\n", encoding="utf-8")
    res = sb.check({}, reads, sb.load_allowlist(allow), "B0", repo, stages=stages, expected=["frames", "cells_rmac"],
                   ended=ended)
    assert res["verdict"] == "G_READ_FAIL" and res["gread"] == [["frames", "ref:analysis/expected/P1.json"]]
