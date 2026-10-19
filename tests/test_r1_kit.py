# -*- coding: utf-8 -*-
"""pipeline/aws/r1/r1kit.py - the R1 launcher, tested without AWS (fake `aws`, real git)."""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
KIT = REPO / "pipeline" / "aws" / "r1"
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "tools"))
import r1kit                                        # noqa: E402
from r1_fakes import aws_calls, install_fake_aws    # noqa: E402

BASE_SHA = "a" * 64
ENV = {"SAR_S3_BUCKET": "fake-bucket", "AWS_REGION": "us-east-1"}


def _render(job, repo_dir="/srv/My Dir /Research/repo", **kw):
    return r1kit.render_userdata(job, job_id="t-unit-01", commit="c" * 40, repo_dir=repo_dir,
                                 bucket="fake-bucket", base_sha=BASE_SHA, deadline_epoch=1_800_000_000, **kw)


def test_the_hard_fuse_is_armed_before_anything_that_can_hang():
    job = r1kit.load_job("test")
    text = _render(job)
    cmds = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    assert cmds[0] == f"shutdown -h +{job['hard_min']}", cmds[:3]
    unit = next(i for i, c in enumerate(cmds) if c == "systemctl enable --now sar-deadline.service")
    first_net = min(i for i, c in enumerate(cmds) if c.startswith(("snap install", "apt-get", "aws s3")))
    assert unit < first_net
    assert "@@" not in text and "1800000000" in text


def test_userdata_quotes_a_repo_path_with_a_space_and_parses(tmp_path):
    job = r1kit.load_job("test")
    text = _render(job, repo_dir="/srv/My Dir /Research/star arrivals")
    assert 'REPO_DIR="/srv/My Dir /Research/star arrivals"' in text
    steps = r1kit.render_steps_script(job, job_id="t-unit-01", commit="c" * 40,
                                      repo_dir="/srv/My Dir /Research/star arrivals", bucket="fake-bucket")
    for name, body in (("ud.sh", text), ("steps.sh", steps)):
        f = tmp_path / name
        f.write_text(body)
        r = subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True)
        assert r.returncode == 0, (name, r.stderr)


def test_render_refuses_unsafe_values():
    job = r1kit.load_job("test")
    with pytest.raises(r1kit.KitError):
        _render(job, repo_dir='/srv/a"b')
    with pytest.raises(r1kit.KitError):
        r1kit.render_userdata(job, job_id="t-unit-01", commit="c" * 40, repo_dir="/srv/x", bucket="Bad_Bucket!",
                              base_sha=BASE_SHA, deadline_epoch=1)


def test_the_template_names_no_machine_path():
    t = (KIT / "userdata.sh.tmpl").read_text(encoding="utf-8")
    assert ("/Users" + "/") not in t and ("/Volumes" + "/") not in t


def test_every_job_spec_loads_and_keeps_est_below_hard():
    specs = sorted((REPO / "config" / "r1" / "jobs").glob("*.json"))
    assert specs
    for f in specs:
        job = r1kit.load_job(f.stem)
        assert 0 < job["est_min"] < job["hard_min"] <= r1kit.HARD_MIN_MAX
        assert job["hard_min"] <= 600 or f.stem == "j1b", f.stem   # only J1b's perm launch runs past 10 hours


def test_load_job_refuses_a_hard_limit_above_the_kit_maximum(tmp_path):
    job = json.loads((REPO / "config" / "r1" / "jobs" / "test.json").read_text(encoding="utf-8"))
    job["hard_min"] = r1kit.HARD_MIN_MAX + 1
    (tmp_path / "test.json").write_text(json.dumps(job), encoding="utf-8")
    with pytest.raises(r1kit.KitError, match="hard_min"):
        r1kit.load_job("test", jobs_dir=tmp_path)


def test_payload_sha_file_lists_every_file(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("x")
    b = tmp_path / "b.bin"
    b.write_bytes(b"\0\1")
    r1kit.write_payload(tmp_path / "in", {"a.txt": a, "b.bin": b})
    lines = (tmp_path / "in" / "payload.sha256").read_text().splitlines()
    assert [ln.split("  ")[1] for ln in lines] == ["a.txt", "b.bin"]
    for ln in lines:
        sha, name = ln.split("  ")
        assert r1kit.sha256_file(tmp_path / "in" / name) == sha
    with pytest.raises(r1kit.KitError):
        r1kit.write_payload(tmp_path / "in2", {"../x": a})


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def test_base_plus_incremental_bundle_reaches_every_new_commit_in_a_dir_with_a_space(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _git(src, "init", "-q", "-b", "main")
    _git(src, "config", "user.email", "t@t")
    _git(src, "config", "user.name", "t")
    (src / "f.txt").write_text("base\n")
    _git(src, "add", "f.txt")
    _git(src, "commit", "-qm", "base")
    base = _git(src, "rev-parse", "HEAD")
    _git(src, "bundle", "create", str(tmp_path / "base.bundle"), "refs/heads/main")
    _git(src, "switch", "-qc", "r1-code")
    (src / "f.txt").write_text("red\n")
    _git(src, "commit", "-qam", "red")
    red = _git(src, "rev-parse", "HEAD")
    (src / "f.txt").write_text("green\n")
    _git(src, "commit", "-qam", "green")
    green = _git(src, "rev-parse", "HEAD")
    r1kit.make_inc_bundle(base, green, tmp_path / "inc.bundle", cwd=src)
    dst = tmp_path / "My Dir /Research" / "repo"
    dst.parent.mkdir(parents=True)
    _git(tmp_path, "clone", "-q", str(tmp_path / "base.bundle"), str(dst))
    _git(dst, "fetch", "-q", str(tmp_path / "inc.bundle"), "+refs/heads/*:refs/remotes/inc/*")
    for c, want in ((red, "red\n"), (green, "green\n")):
        _git(dst, "-c", "advice.detachedHead=false", "checkout", "-q", c)
        assert (dst / "f.txt").read_text() == want
    with pytest.raises(r1kit.KitError):
        r1kit.make_inc_bundle(green, base, tmp_path / "x.bundle", cwd=src)


@pytest.fixture
def kit_env(tmp_path, monkeypatch):
    fake = install_fake_aws(tmp_path, monkeypatch)
    monkeypatch.setattr(r1kit, "RUNS_LOCAL", tmp_path / "runs")
    monkeypatch.setattr(r1kit, "LEDGER", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(r1kit, "require_clean_tree", lambda: None)
    monkeypatch.setattr(r1kit, "resolve_commit", lambda ref: "c" * 40)
    monkeypatch.setattr(r1kit, "make_inc_bundle", lambda base, tip, out, **kw: pathlib.Path(out).write_bytes(b"bundle"))
    monkeypatch.setattr(r1kit, "base_bundle_sha", lambda: BASE_SHA)
    monkeypatch.setattr(r1kit, "_git_show", lambda commit, path: _committed(path))
    monkeypatch.setattr(r1kit, "_git_exists", lambda commit, path: (REPO / path).exists())
    return fake


PY_PIN = {"layers": {"py": {"key": "r1/env/py-0123456789abcdef.tar.gz", "sha256": "e" * 64, "bytes": 1}}}


def _committed(path):
    if path == "config/r1/env_pins.json":
        return json.dumps(PY_PIN)
    return (REPO / path).read_text(encoding="utf-8")


def test_launch_runs_one_tagged_terminating_instance_and_reserves_cost(kit_env, tmp_path):
    spec = tmp_path / "tests.tsv"
    spec.write_text("green\tHEAD\tpass\t-q\t-\n")
    rec = r1kit.launch("test", "t-unit-02", "HEAD", in_files={"tests.tsv": spec}, env=ENV, now=1_800_000_000)
    run = [c for c in aws_calls(kit_env["log"]) if c[:2] == ["ec2", "run-instances"]]
    assert len(run) == 1
    argv = run[0]
    for want in ("--instance-initiated-shutdown-behavior", "terminate", "HttpTokens=required,HttpEndpoint=enabled",
                 "m6i.xlarge", f"Name={r1kit.load_kit()['iam_instance_profile']}", "ami-052355af2a014bd2c"):
        assert want in argv, want
    bdm = json.loads(argv[argv.index("--block-device-mappings") + 1])
    assert bdm[0]["Ebs"]["Encrypted"] is True and bdm[0]["Ebs"]["DeleteOnTermination"] is True
    tags = " ".join(a for a in argv if a.startswith("ResourceType="))
    assert "Key=Project,Value=sar-r1" in tags and "Key=DeadlineUtc,Value=" in tags and "ResourceType=volume" in tags
    up = kit_env["s3root"] / "fake-bucket" / "r1" / "runs" / "t-unit-02" / "in"
    assert sorted(p.name for p in up.iterdir()) == ["inc.bundle", "payload.sha256", "tests.tsv"]
    saved = (tmp_path / "runs" / "t-unit-02" / "launch_record.json").read_text()
    assert "fake-bucket" not in saved and "$SAR_S3_BUCKET" in saved
    led = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert led[-1]["event"] == "reserve" and led[-1]["job"] == "t-unit-02" and led[-1]["reserved_usd"] > 0
    assert rec["instance_id"] == "i-0fake0000000000001"


def test_launch_refuses_while_the_kit_cap_of_r1_instances_is_live(kit_env, monkeypatch):
    cap = int(r1kit.load_kit().get("max_live_instances", 1))
    monkeypatch.setenv("FAKE_LIVE", " ".join(f"i-0alive{i}" for i in range(cap)))
    with pytest.raises(r1kit.KitError, match="live"):
        r1kit.launch("test", "t-unit-03", "HEAD", env=ENV, now=1_800_000_000)
    assert not [c for c in aws_calls(kit_env["log"]) if c[:2] == ["ec2", "run-instances"]]


def test_kit_max_live_instances_allows_a_second_instance_and_no_more(kit_env, monkeypatch):
    """Author 2026-10-15 (maximum speed): kit.json max_live_instances = 2 lets one light job run beside J0."""
    base = r1kit.load_kit()
    monkeypatch.setattr(r1kit, "load_kit", lambda: dict(base, max_live_instances=2))
    monkeypatch.setenv("FAKE_LIVE", "i-0alive")
    r1kit.launch("test", "t-unit-31", "HEAD", env=ENV, now=1_800_000_000)
    assert [c for c in aws_calls(kit_env["log"]) if c[:2] == ["ec2", "run-instances"]]
    monkeypatch.setenv("FAKE_LIVE", "i-0alive i-0alive2")
    with pytest.raises(r1kit.KitError, match="live"):
        r1kit.launch("test", "t-unit-32", "HEAD", env=ENV, now=1_800_000_000)


def test_launch_refuses_a_job_id_twice(kit_env):
    r1kit.launch("test", "t-unit-04", "HEAD", env=ENV, now=1_800_000_000)
    with pytest.raises(r1kit.KitError, match="already"):
        r1kit.launch("test", "t-unit-04", "HEAD", env=ENV, now=1_800_000_000)


def test_dry_run_makes_no_aws_call(kit_env, capsys):
    r1kit.launch("test", "t-unit-05", "HEAD", env=ENV, now=1_800_000_000, dry_run=True)
    assert aws_calls(kit_env["log"]) == []
    assert "DRY-RUN aws ec2 run-instances" in capsys.readouterr().out


def test_watch_returns_on_done(kit_env):
    r1kit.launch("test", "t-unit-06", "HEAD", env=ENV, now=1_800_000_000)
    st = kit_env["s3root"] / "fake-bucket" / "r1" / "runs" / "t-unit-06" / "status.txt"
    st.write_text("2027-01-15T08:00:00Z DONE rc=0 OK\n")
    out = r1kit.watch("t-unit-06", env=ENV, now_fn=lambda: 1_800_000_100, sleep_fn=lambda s: None)
    assert out.split()[1] == "DONE"


def test_watch_terminates_an_instance_past_its_hard_deadline(kit_env, monkeypatch):
    r1kit.launch("test", "t-unit-07", "HEAD", env=ENV, now=1_800_000_000)
    monkeypatch.setenv("FAKE_DESCRIBE", "running")
    r1kit.watch("t-unit-07", env=ENV, now_fn=lambda: 1_800_000_000 + 10 * 3600, sleep_fn=lambda s: None)
    assert any(c[:2] == ["ec2", "terminate-instances"] and "i-0fake0000000000001" in c
               for c in aws_calls(kit_env["log"]))


def test_settle_turns_launch_and_end_times_into_dollars(kit_env, monkeypatch):
    r1kit.launch("test", "t-unit-08", "HEAD", env=ENV, now=1_800_000_000)
    monkeypatch.setenv("FAKE_DESCRIBE", json.dumps(
        ["2027-01-15T08:00:00+00:00", "terminated", "User initiated (2027-01-15 09:30:00 GMT)"]))
    e = r1kit.settle("t-unit-08", env=ENV)
    job, kit = r1kit.load_job("test"), r1kit.load_kit()
    assert e["hours"] == 1.5
    assert e["actual_usd"] == round(1.5 * (job["price_hr"] + job["root_gb"] * kit["ebs_usd_per_gb_month"] / 730.0), 4)
    tot = r1kit.ledger_totals()
    assert tot["open_reservations_usd"] == 0 and tot["actual_usd"] == round(e["actual_usd"], 2)


def test_the_ledger_never_refuses_on_cost(kit_env):
    """v3 §4 / C9: no cost cap. Huge spend still launches; the ledger only reports."""
    r1kit.ledger_append({"event": "manual", "job": "huge", "actual_usd": 10_000.0, "note": "test"})
    r1kit.launch("test", "t-unit-09", "HEAD", env=ENV, now=1_800_000_000)
    assert r1kit.ledger_totals()["actual_usd"] >= 10_000


def test_spec_lines_wire_red_green_and_the_noregress_suite():
    """base and suite run the root suite AND the ported units (testpaths alone is only tests/)."""
    lines = r1kit.spec_lines_for_test(base="b" * 40, red="d" * 40, green="e" * 40, select="tests/test_x.py")
    assert lines == [f"base\t{'b' * 40}\trecord\t-q tests pipeline/units\t-",
                     f"red\t{'d' * 40}\tfail\t-q tests/test_x.py\t-",
                     f"green\t{'e' * 40}\tpass\t-q tests/test_x.py\t-",
                     f"suite\t{'e' * 40}\tnoregress\t-q tests pipeline/units\t@base"]


def test_userdata_stays_under_the_ec2_16kb_limit():
    job = r1kit.load_job("test")
    assert len(_render(job).encode("utf-8")) < r1kit.MAX_USERDATA_BYTES == 16384
    with pytest.raises(r1kit.KitError, match="16 KB"):
        _render(dict(job, steps=["echo " + "x" * 17000]))


def test_no_job_runs_a_script_where_it_sits_under_pipeline():
    """paths.refuse_unstaged_in_place_run() stops a non-launcher script under pipeline/ at its first data
    read, so every job copies its script to /work/ (copy_from_tip) and runs the copy."""
    for f in sorted((REPO / "config" / "r1" / "jobs").glob("*.json")):
        for step in r1kit.load_job(f.stem)["steps"]:
            assert not re.search(r'\$REPO_DIR/pipeline/[^"\s]*\.py', step), (f.name, step)


def test_launch_refuses_a_dirty_tree_but_not_an_ignored_file(tmp_path):
    """Every other kit test stubs require_clean_tree; this one runs it on a real repo."""
    repo = tmp_path / "toy"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / ".gitignore").write_text("local.env\n")
    (repo / "f.txt").write_text("x\n")
    _git(repo, "add", ".gitignore", "f.txt")
    _git(repo, "commit", "-qm", "base")
    r1kit.require_clean_tree(cwd=repo)
    (repo / "local.env").write_text("SAR_S3_BUCKET=x\n")             # ignored: fine
    r1kit.require_clean_tree(cwd=repo)
    (repo / "plan.md").write_text("untracked\n")                     # untracked: refused
    with pytest.raises(r1kit.KitError, match="not clean"):
        r1kit.require_clean_tree(cwd=repo)
    (repo / "plan.md").unlink()
    (repo / "f.txt").write_text("changed\n")                         # modified: refused
    with pytest.raises(r1kit.KitError, match="not clean"):
        r1kit.require_clean_tree(cwd=repo)


def _boot_snippet(tmp_path, pairs):
    body = "\n".join(["set -u", 'B="s3://fake-bucket"', 'st() { echo "$*" >> "%s"; }' % (tmp_path / "st.log"),
                      r1kit._sync_lines(pairs), "echo REACHED"])
    f = tmp_path / "snippet.sh"
    f.write_text(body + "\n")
    return subprocess.run(["bash", str(f)], capture_output=True, text=True)


def test_a_pull_that_brings_nothing_stops_the_boot(kit_env, tmp_path):
    """`aws s3 sync` of a prefix that does not exist exits 0; the boot must not carry on with an empty dir."""
    r = _boot_snippet(tmp_path, [("r1/evidence/", str(tmp_path / "dst" / "evidence") + "/")])
    assert r.returncode == 1 and "REACHED" not in r.stdout
    assert "FAIL empty pull r1/evidence/" in (tmp_path / "st.log").read_text()


def test_a_pulled_upstream_run_must_have_passed(kit_env, tmp_path):
    up = kit_env["s3root"] / "fake-bucket" / "r1" / "runs" / "merge-02" / "out" / "files"
    up.mkdir(parents=True)
    (up / "RESULT.txt").write_text("COUNT_FAIL\n")
    pair = [("r1/runs/merge-02/out/files/", str(tmp_path / "merged") + "/")]
    r = _boot_snippet(tmp_path, pair)
    assert r.returncode == 1 and "FAIL upstream not OK r1/runs/merge-02/out/files/" in (tmp_path / "st.log").read_text()
    (up / "RESULT.txt").write_text("OK\n")
    (tmp_path / "st.log").unlink()
    shutil.rmtree(tmp_path / "merged")
    r = _boot_snippet(tmp_path, pair)
    assert r.returncode == 0 and "REACHED" in r.stdout


@pytest.fixture
def toy_jobs(tmp_path, monkeypatch):
    d = tmp_path / "jobs"
    d.mkdir()
    spec = json.loads((REPO / "config" / "r1" / "jobs" / "test.json").read_text())
    spec.update(kind="needy", required_dests=["/work/merged/"])
    (d / "needy.json").write_text(json.dumps(spec))
    monkeypatch.setattr(r1kit, "JOBS_DIR", d)
    return d


def test_launch_needs_every_required_pull(kit_env, toy_jobs):
    with pytest.raises(r1kit.KitError, match="/work/merged/"):
        r1kit.launch("needy", "t-unit-10", "HEAD", env=ENV, now=1_800_000_000)
    r1kit.launch("needy", "t-unit-11", "HEAD", env=ENV, now=1_800_000_000,
                 extra_pulls=[("r1/runs/merge-01/out/files/", "/work/merged/")])


def test_dry_run_and_aws_errors_never_print_the_bucket(kit_env, capsys, monkeypatch):
    r1kit.launch("test", "t-unit-12", "HEAD", env=ENV, now=1_800_000_000, dry_run=True)
    out = capsys.readouterr().out
    assert "fake-bucket" not in out and "s3://$SAR_S3_BUCKET/r1/runs/t-unit-12/in/" in out
    monkeypatch.setenv("FAKE_FAIL_WITH_ARGS", "1")
    with pytest.raises(r1kit.KitError) as e:
        r1kit.aws(["s3", "ls", "s3://fake-bucket/r1/"])
    assert "fake-bucket" not in str(e.value) and "$SAR_S3_BUCKET" in str(e.value)


def test_s3_writes_outside_r1_are_refused(kit_env, tmp_path):
    r1kit.use_env(ENV)
    f = tmp_path / "x.txt"
    f.write_text("x")
    for dst in ("s3://fake-bucket/rk1/20261002/x.txt", "s3://fake-bucket/u1_full_11school_2026-07-16/x", "s3://other-test-bucket/r1/x"):
        with pytest.raises(r1kit.KitError, match="only under"):
            r1kit.aws(["s3", "cp", str(f), dst])
    assert aws_calls(kit_env["log"]) == []
    r1kit.aws(["s3", "cp", str(f), "s3://fake-bucket/r1/runs/x/x.txt"])          # under r1/: allowed
    r1kit.aws(["s3", "cp", "s3://fake-bucket/r1/runs/x/x.txt", "-"])             # a read: allowed


def test_settle_books_an_instance_that_aws_no_longer_lists(kit_env, monkeypatch):
    """AWS shows a terminated instance for about an hour; after that describe-instances says NotFound."""
    r1kit.launch("test", "t-unit-13", "HEAD", env=ENV, now=1_800_000_000)
    st = kit_env["s3root"] / "fake-bucket" / "r1" / "runs" / "t-unit-13" / "status.txt"
    st.write_text("2027-01-15T09:00:00Z DONE rc=0 OK\n")
    monkeypatch.setenv("FAKE_DESCRIBE_GONE", "1")
    e = r1kit.settle("t-unit-13", env=ENV)
    assert e["end_source"] == "status (instance gone)" and e["launch_utc"] == r1kit.iso(1_800_000_000)
    assert e["hours"] == 1.05                                                    # 08:00 launch .. 09:00 DONE + 3 min


def test_settle_retries_until_the_instance_is_terminated(kit_env, monkeypatch):
    r1kit.launch("test", "t-unit-14", "HEAD", env=ENV, now=1_800_000_000)
    monkeypatch.setenv("FAKE_DESCRIBE", json.dumps(["2027-01-15T08:00:00+00:00", "shutting-down", ""]))
    naps = []
    with pytest.raises(r1kit.KitError, match="SETTLE PENDING"):
        r1kit.settle_until_terminated("t-unit-14", env=ENV, tries=3, wait_s=7, sleep_fn=naps.append)
    assert naps == [7, 7]
    monkeypatch.setenv("FAKE_DESCRIBE", json.dumps(
        ["2027-01-15T08:00:00+00:00", "terminated", "User initiated (2027-01-15 08:30:00 GMT)"]))
    assert r1kit.settle_until_terminated("t-unit-14", env=ENV, tries=3, sleep_fn=naps.append)["hours"] == 0.5


def _fin_harness(tmp_path, result_text, status):
    """Run the template's fin() with stubbed aws/shutdown and /work moved under tmp_path."""
    text = _render(r1kit.load_job("test"))
    fin = text[text.index("fin() {"):]
    fin = fin[:fin.index("\n}\n") + 3]
    work = tmp_path / "work"
    (work / "out").mkdir(parents=True)
    if result_text is not None:
        (work / "out" / "RESULT.txt").write_text(result_text)
    log = tmp_path / "boot.log"
    log.write_text("boot\n")
    fin = fin.replace("/work", str(work)).replace("/var/log/sar-r1-boot.log", str(log))
    script = ("aws() { :; }\nshutdown() { :; }\n"
              f"st() {{ echo \"$*\" > '{tmp_path}/status'; }}\n" + fin + f"\n( exit {status} ); fin\n")
    subprocess.run(["bash", "-c", script], check=True, capture_output=True, text=True)
    return (work / "out" / "RESULT.txt").read_text().strip(), (tmp_path / "status").read_text().strip()


def test_a_failed_later_step_overrides_an_earlier_ok(tmp_path):
    """Review I-2: a step that wrote OK must not survive a later step's failure (rk6a: rk1.py writes OK,
    then summarize - the 187 recount - could crash and leave OK for the next job's boot gate)."""
    res, st = _fin_harness(tmp_path / "a", "OK\n", 3)
    assert res.startswith("STEP_FAIL rc=3") and "(was: OK" in res and st.startswith("DONE rc=3 STEP_FAIL")
    res, _ = _fin_harness(tmp_path / "b", None, 2)
    assert res == "NO_RESULT rc=2"
    res, st = _fin_harness(tmp_path / "c", "OK\n", 0)
    assert res == "OK" and st == "DONE rc=0 OK"


def test_printed_aws_errors_never_carry_the_account_id():
    """Global constraint: bucket name and account id never in printed output (review: account id was not redacted)."""
    r1kit.use_env(ENV)
    out = r1kit._redact("User: arn:aws:iam::123456789012:user/x is not authorized on s3://fake-bucket/rk1/ (acct 123456789012)")
    assert not re.search(r"(?<!\d)\d{12}(?!\d)", out) and "fake-bucket" not in out
    assert "arn:aws:iam" not in out


def test_fetch_copies_the_allowlist_and_needs_an_author_ok_for_anything_else(kit_env, tmp_path):
    files = kit_env["s3root"] / "fake-bucket" / "r1" / "runs" / "f-unit-01" / "out" / "files"
    files.mkdir(parents=True)
    (files / "summary.json").write_text('{"n": 1}\n')
    (files / "main.pdf").write_bytes(b"%PDF")
    import hashlib
    (files / "MANIFEST.sha256").write_text(f"{hashlib.sha256(b'%PDF').hexdigest()}  main.pdf\n")
    (tmp_path / "runs" / "f-unit-01").mkdir(parents=True)
    got = r1kit.fetch("f-unit-01", tmp_path / "to", names=("summary.json",), env=ENV)
    assert [p.name for p in got] == ["summary.json"]
    with pytest.raises(r1kit.KitError, match="author OK"):
        r1kit.fetch("f-unit-01", tmp_path / "to", names=("main.pdf",), env=ENV)
    r1kit.fetch("f-unit-01", tmp_path / "to", names=("main.pdf",), author_ok="2026-10-12: ok", env=ENV)
    (files / "main.pdf").write_bytes(b"%PDX")
    with pytest.raises(r1kit.KitError, match="sha"):
        r1kit.fetch("f-unit-01", tmp_path / "to2", names=("main.pdf",), author_ok="2026-10-12: x", env=ENV)



def test_fetch_of_a_job_without_stages_verifies_against_the_tarball(kit_env, tmp_path):
    """W2-INT, KIT regression (rostermatch-02 failed with a 404 on MANIFEST.sha256): a job that does not use
    run_stages writes no files/MANIFEST.sha256, so an author-OK'd name is checked against the job's out.tar.gz,
    itself checked against out/out.sha256 (both written by the boot script's fin). A stage job - or a job with
    no launch record on this Mac - still needs the MANIFEST."""
    import hashlib
    import io
    import tarfile
    run = kit_env["s3root"] / "fake-bucket" / "r1" / "runs" / "rm-unit-02"
    files = run / "out" / "files"
    files.mkdir(parents=True)
    (files / "summary.json").write_text('{"n": 1}\n')
    (files / "match.csv").write_bytes(b"a,b\n1,2\n")

    def pack(content):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for name, data in (("out/summary.json", b'{"n": 1}\n'), ("out/match.csv", content)):
                ti = tarfile.TarInfo(name)
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
        (run / "out" / "out.tar.gz").write_bytes(buf.getvalue())
        (run / "out" / "out.sha256").write_text(f"{hashlib.sha256(buf.getvalue()).hexdigest()}  out.tar.gz\n")

    pack(b"a,b\n1,2\n")
    rec = tmp_path / "runs" / "rm-unit-02"
    rec.mkdir(parents=True)
    (rec / "launch_record.json").write_text(json.dumps({"schema": "sar.r1.launch.v1", "job": "rm-unit-02",
                                                        "kind": "rostermatch"}))
    got = r1kit.fetch("rm-unit-02", tmp_path / "to", names=("match.csv",), author_ok="2026-10-16: test", env=ENV)
    assert [p.name for p in got] == ["match.csv"] and got[0].read_bytes() == b"a,b\n1,2\n"
    assert json.loads((rec / "fetch_record.json").read_text())[-1]["verified_by"] == "out.tar.gz"
    pack(b"a,b\n1,3\n")                                          # the file differs from the archived bytes
    with pytest.raises(r1kit.KitError, match="sha"):
        r1kit.fetch("rm-unit-02", tmp_path / "to2", names=("match.csv",), author_ok="x", env=ENV)
    assert not (tmp_path / "to2" / "match.csv").exists()
    pack(b"a,b\n1,2\n")
    (run / "out" / "out.sha256").write_text("0" * 64 + "  out.tar.gz\n")    # not the archive fin recorded
    with pytest.raises(r1kit.KitError, match="out.sha256"):
        r1kit.fetch("rm-unit-02", tmp_path / "to3", names=("match.csv",), author_ok="x", env=ENV)
    pack(b"a,b\n1,2\n")
    with pytest.raises(r1kit.KitError, match="not in the job's out.tar.gz"):
        r1kit.fetch("rm-unit-02", tmp_path / "to4", names=("other.csv",), author_ok="x", env=ENV)
    # a stage job keeps the strict check: run_stages always writes files/MANIFEST.sha256
    (rec / "launch_record.json").write_text(json.dumps({"schema": "sar.r1.launch.v1", "job": "rm-unit-02",
                                                        "kind": "j1a"}))
    with pytest.raises(r1kit.KitError, match="MANIFEST"):
        r1kit.fetch("rm-unit-02", tmp_path / "to5", names=("match.csv",), author_ok="x", env=ENV)
    (rec / "launch_record.json").unlink()                       # unknown kind: strict as well
    with pytest.raises(r1kit.KitError, match="MANIFEST"):
        r1kit.fetch("rm-unit-02", tmp_path / "to6", names=("match.csv",), author_ok="x", env=ENV)


def test_s3_guard_reads_the_destination_not_the_last_word(kit_env, tmp_path):
    r1kit.use_env(ENV)
    with pytest.raises(r1kit.KitError, match="only under"):
        r1kit.aws(["s3", "sync", str(tmp_path), "s3://fake-bucket/rk1/x/", "--exclude", "duck_*"])
    with pytest.raises(r1kit.KitError, match="only under"):
        r1kit.aws(["s3", "rm", "s3://fake-bucket/u1_full_11school_2026-07-16/x"])
    src = kit_env["s3root"] / "fake-bucket" / "r1" / "a"
    src.parent.mkdir(parents=True)
    src.write_text("a")
    r1kit.aws(["s3", "cp", "s3://fake-bucket/r1/a", str(tmp_path / "b"), "--exclude", "s3://fake-bucket/x"])
    assert (tmp_path / "b").read_text() == "a"
    assert not [c for c in aws_calls(kit_env["log"]) if "rk1" in " ".join(c)]


def test_watch_returns_when_the_instance_is_gone(kit_env, monkeypatch):
    r1kit.launch("test", "t-unit-15", "HEAD", env=ENV, now=1_800_000_000)
    monkeypatch.setenv("FAKE_DESCRIBE_GONE", "1")
    out = r1kit.watch("t-unit-15", env=ENV, now_fn=lambda: 1_800_000_100, sleep_fn=lambda s: None, max_polls=20)
    assert out.startswith("GONE")
    monkeypatch.delenv("FAKE_DESCRIBE_GONE")
    monkeypatch.setenv("FAKE_DESCRIBE", "terminated")
    r1kit.launch("test", "t-unit-16", "HEAD", env=ENV, now=1_800_000_000)
    assert r1kit.watch("t-unit-16", env=ENV, now_fn=lambda: 1_800_000_100, sleep_fn=lambda s: None, max_polls=20).startswith("GONE")


def test_settle_books_a_fused_run_that_wrote_no_done(kit_env, monkeypatch):
    rec = r1kit.launch("test", "t-unit-17", "HEAD", env=ENV, now=1_800_000_000)
    st = kit_env["s3root"] / "fake-bucket" / "r1" / "runs" / "t-unit-17" / "status.txt"
    st.write_text("2027-01-15T08:30:00Z RUN\n")
    monkeypatch.setenv("FAKE_DESCRIBE", json.dumps([rec["launch_utc"], "terminated",
                                                    "Client.InstanceInitiatedShutdown: Instance initiated shutdown"]))
    e = r1kit.settle("t-unit-17", env=ENV)
    job = r1kit.load_job("test")
    assert e["end_source"].startswith("fuse") and e["hours"] == round((job["hard_min"] + 5) / 60, 4)


def test_userdata_out_refuses_a_path_inside_the_repo(kit_env, tmp_path):
    with pytest.raises(r1kit.KitError, match="outside the repo"):
        r1kit.launch("test", "t-unit-18", "HEAD", env=ENV, now=1_800_000_000, dry_run=True,
                     userdata_out=REPO / "data" / "ud.sh")
    out = tmp_path / "ud.sh"
    r1kit.launch("test", "t-unit-19", "HEAD", env=ENV, now=1_800_000_000, dry_run=True, userdata_out=out)
    assert out.stat().st_mode & 0o077 == 0


def test_apply_patch_dry_runs_first_and_refuses_a_patch_that_does_not_fit(tmp_path):
    t = tmp_path / "tree"
    (t / "sec").mkdir(parents=True)
    (t / "sec" / "a.tex").write_text("one\ntwo\n")
    good = tmp_path / "good.patch"
    good.write_text("--- a/sec/a.tex\n+++ b/sec/a.tex\n@@ -1,2 +1,2 @@\n one\n-two\n+2\n")
    r1kit.apply_patch(good, t)
    assert (t / "sec" / "a.tex").read_text() == "one\n2\n"
    with pytest.raises(r1kit.KitError, match="does not apply"):
        r1kit.apply_patch(good, t)                                 # already applied: --forward refuses
    assert (t / "sec" / "a.tex").read_text() == "one\n2\n"


def test_launch_resume_from_pulls_the_prior_stages_and_sets_the_resume_dir(kit_env, toy_jobs, tmp_path):
    ud = tmp_path / "ud.sh"
    r1kit.launch("needy", "t-unit-20", "HEAD", env=ENV, now=1_800_000_000, dry_run=True, resume_from="j0-01",
                 extra_pulls=[("r1/runs/merge-01/out/files/", "/work/merged/")], userdata_out=ud)
    text = ud.read_text()
    assert '"$B/r1/runs/j0-01/stages/" "/work/resume/"' in text and "SAR_RESUME_DIR=/work/resume" in text
    pull = text[text.index('"$B/r1/runs/j0-01/stages/"'):].split("\n")[:4]
    assert not any("upstream not OK" in ln for ln in pull)


def test_a_pulled_stage_set_from_another_job_must_have_passed(kit_env, tmp_path):
    up = kit_env["s3root"] / "fake-bucket" / "r1" / "runs" / "j1a-01"
    (up / "stages").mkdir(parents=True)
    (up / "stages" / "frames.done.json").write_text("{}")
    (up / "out" / "files").mkdir(parents=True)
    (up / "out" / "files" / "RESULT.txt").write_text("STAGE_FAIL frames rc=1\n")
    r = _boot_snippet(tmp_path, [("r1/runs/j1a-01/stages/", str(tmp_path / "j1a") + "/")])
    assert r.returncode == 1 and "FAIL upstream not OK r1/runs/j1a-01/stages/" in (tmp_path / "st.log").read_text()


def test_big_mode_lines_select_everything_but_live():
    assert r1kit.spec_lines_for_big(green="e" * 40, markers="not live") == [
        f"big\t{'e' * 40}\trecord\t-q -m \"not live\" tests pipeline/units\t-"]
    assert r1kit.spec_lines_for_big(green="e" * 40, markers="not live", baseline="/work/bigbase/big.xml")[0].split("\t")[2:] == [
        "noregress", '-q -m "not live" tests pipeline/units', "/work/bigbase/big.xml"]
    for bad in ("live", "ssd or live", "not ssd"):
        with pytest.raises(r1kit.KitError, match="live"):
            r1kit.spec_lines_for_big(green="e" * 40, markers=bad)


def test_test_big_runs_on_the_data_host_with_the_uploaded_inputs():
    big = r1kit.load_job("test_big")
    assert big["sar_host"] == "ec2-r1" and set(big["env_layers"]) == set(r1kit.ENV_LAYERS)
    assert big["env"]["SAR_PATHS_CONFIG"] == "$REPO_DIR/config/r1/paths_aws.yaml"
    import r1_input_inventory as inv
    assert big["data_sync"] == inv.sync_pairs(inv.read_tsv(REPO / "config" / "r1" / "input_inventory.tsv"), "test_big")
    assert r1kit.load_job("test")["env_layers"] == ["py"]


def test_test_big_prepares_the_j0_overlay_the_relinks_and_the_v3net_spec_before_the_suite(tmp_path):
    """B4 (t-big-04; t-big-03 failed 26 ways, several on setup): (1) the U3 panel is synced (econ920_null proof);
    (2) the legacy v2_output symlinks are recreated as in J0/J1a; (3) J0's git-ignored pair tables are laid out from
    the pulled stage set (digest vs the J0 markers, sha vs October's pin) into /work/overlay, which run_tests_r1
    copies into the checkout after each git clean; (4) the V3-NET oracle spec is built (never fatal: a failed part
    leaves the oracle test to name it); (5) the suite runs, and the oracle summary is kept under /work/out whatever
    the suite's result. The rendered boot script parses and stays under EC2's 16 KB."""
    big = r1kit.load_job("test_big")
    assert ["u3_panel_11school_2026-07-16/", "/data/openalex_pipeline/derived/u3_panel_11school_2026-07-16/"] \
        in big["data_sync"]
    assert big["required_dests"] == ["/work/j0/"] and big["est_min"] < big["hard_min"] <= 600
    cft = {src: dst for src, dst in big["copy_from_tip"]}
    for s in ("run_tests_r1.py", "verify_inputs.py", "restore_upstream.py", "check_pin.py", "v3net_oracle_spec.py"):
        assert cft[f"pipeline/aws/r1/{s}"] == f"/work/{s}" and (KIT / s).is_file(), s
    relink, restore, spec, suite = big["steps"]
    j0 = json.loads((REPO / "config" / "r1" / "stages" / "j0.json").read_text(encoding="utf-8"))
    j0_relink = next(s["cmd"] for s in j0["stages"] if s["name"] == "relink")
    assert relink.split(" > ")[0] == j0_relink.split(" > ")[0].replace('"$WORK/verify_inputs.py"', "/work/verify_inputs.py")
    lay = json.loads((REPO / "config" / "r1" / "layouts" / "test_big_from_j0.json").read_text(encoding="utf-8"))
    outs = {s["name"]: s["outputs"] for s in j0["stages"]}
    for row in lay["rows"]:
        f = row["from"]
        assert f["job"] == "j0" and f["token"] in outs[f["stage"]] and f["token"] == "repo:" + row["dest"], row
        assert row["dest"].startswith("output/cal_intermediates/")                       # git-ignored
        assert f"--file /work/overlay/{row['dest']} " in restore                         # each one pin-checked
    assert "--stages /work/j0 " in restore and "--dest /work/overlay " in restore and restore.count("check_pin.py") == 2
    assert 'build_report_econ920_2026-10.json" --key october.pairs_unified' in restore
    assert "v3net_oracle_spec.py build" in spec and '--spec "$SAR_V3NET_ORACLE"' in spec and "|| echo" in spec
    assert big["env"]["SAR_V3NET_ORACLE"] == "/work/v3net/spec.json"
    assert not big["env"]["SAR_V3NET_ORACLE_OUT"].startswith("/work/out")                # big duckdb files stay off S3
    assert suite.startswith('"$PY" /work/run_tests_r1.py ') and "--overlay /work/overlay;" in suite
    assert suite.endswith('exit "$rc"') and '"$SAR_V3NET_ORACLE_OUT/summary.json"' in suite
    text = _render(big, extra_pulls=[("r1/runs/t-big-01/out/files/", "/work/bigbase/"),
                                     ("r1/runs/j0-02/stages/", "/work/j0/")])
    f = tmp_path / "ud.sh"
    f.write_text(text)
    assert subprocess.run(["bash", "-n", str(f)], capture_output=True).returncode == 0
    assert len(text.encode("utf-8")) < r1kit.MAX_USERDATA_BYTES
    assert "FAIL upstream not OK r1/runs/j0-02/stages/" in text


def test_watch_and_result_redact_what_the_instance_wrote(kit_env, capsys):
    """Review (P3b): a failed push puts the bucket name into status.txt / RESULT.txt."""
    r1kit.launch("test", "t-unit-30", "HEAD", env=ENV, now=1_800_000_000)
    run = kit_env["s3root"] / "fake-bucket" / "r1" / "runs" / "t-unit-30"
    (run / "out" / "files").mkdir(parents=True)
    (run / "status.txt").write_text("2027-01-15T08:30:00Z DONE rc=1 FAIL push s3://fake-bucket/r1/x\n")
    (run / "out" / "files" / "RESULT.txt").write_text("STAGE_FAIL s1 aws s3 cp failed: s3://fake-bucket/r1/x\n")
    r1kit.watch("t-unit-30", env=ENV, now_fn=lambda: 1_800_000_100, sleep_fn=lambda s: None, max_polls=1)
    r1kit.result("t-unit-30", env=ENV)
    assert "fake-bucket" not in capsys.readouterr().out


def test_env_pins_come_from_the_launched_commit(kit_env, tmp_path):
    """Review (P3b): fingerprints read the commit's env_pins.json, so the boot restore must use the same file."""
    ud = tmp_path / "ud.sh"
    r1kit.launch("test", "t-unit-31", "HEAD", env=ENV, now=1_800_000_000, dry_run=True, userdata_out=ud)
    assert "r1/env/py-0123456789abcdef.tar.gz" in ud.read_text()
