# -*- coding: utf-8 -*-
"""pipeline/aws/r1/sandbox.py (F2): the purge, the read watcher and the end check, on toy git repos.

The watcher uses Linux inotify, so the tests that start it are Linux-only; they run on the AWS test runner
(Ubuntu 24.04, as a non-root user, so chmod a-w really refuses writes).
"""
from __future__ import annotations

import json
import os
import pathlib
import signal
import stat
import subprocess
import sys
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import sandbox as sb  # noqa: E402

linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"),
                                reason="inotify is Linux-only; these tests run on the AWS test runner")

REASON = "toy allowlist row for the sandbox tests (reason longer than thirty characters)"
FILES = {
    "data/cal2026-10/a.csv": "x,y\n1,2\n",                       # base: read by the toy builder
    "data/cal2026-10/p.csv": "X,Y\n1,2\n",                       # product: build.py writes it from a.csv
    "data/cal2026-08-28/ok.csv": "allowed\n",                    # base, allowlisted for B0
    "data/cal2026-08-28/x.csv": "not allowlisted\n",             # base, not allowlisted
    "data/raw_verified/events_econ_cal2026-08-28.csv": "e\n",    # watched (name carries cal2026-08-28)
    "data/raw_verified/other.csv": "o\n",                        # same directory, never logged
    "analysis/expected/P1.json": "{}\n",                         # product
    "data/cal2026-10r1/inputs/add_list_r1.json": "{}\n",         # r1_input
    "build.py": "import pathlib, sys\nr = pathlib.Path(sys.argv[1])\n"
                "(r / 'data/cal2026-10/p.csv').write_text((r / 'data/cal2026-10/a.csv').read_text().upper())\n",
}
CLASSES = {"data/cal2026-10/a.csv": "base", "data/cal2026-10/p.csv": "product",
           "data/cal2026-08-28/ok.csv": "base", "data/cal2026-08-28/x.csv": "base",
           "analysis/expected/P1.json": "product"}
ALLOW = (f"# toy allowlist\n"
         f"data/cal2026-08-28/ok.csv\tB0\t*\t{REASON}\n"
         f"data/raw_verified/*cal2026-08-28*\t*\t*\t{REASON}\n"
         f"ref:analysis/expected/**\tB0\tcells_rmac,cells_rcloud,gate1\t{REASON}\n")


def _w_allow(d):
    p = d / "allow.txt"
    p.write_text(ALLOW, encoding="utf-8")
    return p


def _git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _tsv(repo, path, classes=CLASSES):
    """A base_inputs.tsv for the toy repo, blob ids from git (what the classifier writes)."""
    rows = []
    for ln in _git(repo, "ls-files", "-s").splitlines():
        meta, p = ln.split("\t", 1)
        if p in classes:
            rows.append((p, classes[p], meta.split()[1], "toy", REASON))
    blob = _git(repo, "ls-files", "-s", "data/cal2026-10r1/inputs/add_list_r1.json").split()[1]
    rows.append(("data/cal2026-10r1/inputs/add_list_r1.json", "r1_input", blob, "toy", REASON))
    rows.append(("s3:r1/patch_raw/", "r1_input", "pin:patch_raw", "toy", REASON))
    path.write_text(sb.render_tsv(rows), encoding="utf-8")
    return path


def _table(path, outputs=("repo:data/cal2026-10/p.csv",)):
    path.write_text(json.dumps({"schema": "sar.r1.stages.v1", "job": "toy", "stages": [
        {"name": "build", "owner": "F2", "cmd": "true", "inputs": [], "outputs": list(outputs), "est_min": 1,
         "needs": []}]}), encoding="utf-8")
    return path


def _stop_pidfile(pid_file):
    try:
        os.kill(int(pid_file.read_text().split()[0]), signal.SIGKILL)
    except (OSError, ValueError, IndexError):
        pass


@pytest.fixture
def toy(tmp_path, monkeypatch):
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    repo, work = tmp_path / "repo", tmp_path / "work"
    for rel, text in FILES.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "toy")
    work.mkdir()
    (work / "status.txt").write_text("2026-10-15T00:00:00Z STAGE frames\n", encoding="utf-8")
    ns = {"repo": repo, "work": work, "ref": tmp_path / "ref" / "october", "out": work / "prod" / "sandbox",
          "tsv": _tsv(repo, tmp_path / "base_inputs.tsv"), "table": _table(tmp_path / "j0.json"),
          "allow": tmp_path / "allow.txt"}
    ns["allow"].write_text(ALLOW, encoding="utf-8")
    yield ns
    _stop_pidfile(work / sb.PID_NAME)
    for root, dirs, files in os.walk(tmp_path):                  # pytest must be able to remove tmp_path
        for name in dirs + files:
            p = pathlib.Path(root) / name
            if not p.is_symlink():
                os.chmod(p, stat.S_IMODE(os.stat(p).st_mode) | stat.S_IWUSR)


def _purge(ns, **over):
    args = {"repo": ns["repo"], "tsv": ns["tsv"], "ref": ns["ref"], "config": "B0", "table": ns["table"],
            "allowlist": ns["allow"], "out": ns["out"], "work": ns["work"], **over}
    return sb.main(["purge", *[x for k, v in args.items() for x in (f"--{k}", str(v))]])


def _check_table(path, between=("frames",)):
    """A stage table whose audited span (strictly between sandbox and sandbox_check) is `between`."""
    names = ["config", "sandbox", *between, "sandbox_check", "gate1"]
    path.write_text(json.dumps({"schema": "sar.r1.stages.v1", "job": "toy", "stages": [{"name": n} for n in names]}),
                    encoding="utf-8")
    return path


def _check_cli(ns, record, config="B0"):
    rec = ns["work"] / "record.json"
    rec.write_text(json.dumps(record), encoding="utf-8")
    out = ns["work"] / "prod" / "sandbox_check"
    rc = sb.main(["check", "--record", str(rec), "--reads", str(ns["work"] / "reads"),
                  "--reads", str(ns["work"] / "resume" / "_reads"), "--allowlist", str(ns["allow"]),
                  "--config", config, "--out", str(out), "--repo", str(ns["repo"]), "--work", str(ns["work"]),
                  "--table", str(_check_table(ns["work"] / "check_table.json"))])
    return rc, json.loads((out / "sandbox_check.json").read_text(encoding="utf-8"))


@linux_only
def test_reading_a_purged_product_gives_file_not_found(toy):
    repo, ref = toy["repo"], toy["ref"]
    assert _purge(toy) == 0
    with pytest.raises(FileNotFoundError):
        open(repo / "data/cal2026-10/p.csv", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        open(repo / "analysis/expected/P1.json", encoding="utf-8")
    kept = ref / "data/cal2026-10/p.csv"
    assert kept.read_text(encoding="utf-8") == FILES["data/cal2026-10/p.csv"]
    assert not os.access(kept, os.W_OK) and not os.access(kept.parent, os.W_OK)
    with pytest.raises(PermissionError):
        open(kept, "a", encoding="utf-8")
    # base and r1 inputs stay in place, write-protected and fingerprinted
    for rel in ("data/cal2026-10/a.csv", "data/cal2026-10r1/inputs/add_list_r1.json"):
        assert (repo / rel).is_file() and not os.access(repo / rel, os.W_OK)
        with pytest.raises(PermissionError):
            open(repo / rel, "a", encoding="utf-8")
    record = json.loads((toy["out"] / "base_record.json").read_text(encoding="utf-8"))
    assert set(record) == {"data/cal2026-10/a.csv", "data/cal2026-08-28/ok.csv", "data/cal2026-08-28/x.csv",
                           "data/cal2026-10r1/inputs/add_list_r1.json"}
    assert record["data/cal2026-10/a.csv"]["sha256"] == sb.sha256_file(repo / "data/cal2026-10/a.csv")
    assert set(record["data/cal2026-10/a.csv"]) == {"sha256", "inode", "mtime_ns", "size"}
    marker = json.loads((repo / ".r1_sandbox.json").read_text(encoding="utf-8"))
    assert marker == {"config": "B0", "commit": _git(repo, "rev-parse", "HEAD"), "ref": str(ref),
                      "tsv_sha256": sb.sha256_file(toy["tsv"])}
    assert (toy["work"] / sb.PID_NAME).is_file()                  # the watcher is up
    # a stage that rebuilds the product from the base input gives the October bytes back
    subprocess.run([sys.executable, str(repo / "build.py"), str(repo)], check=True)
    assert (repo / "data/cal2026-10/p.csv").read_bytes() == kept.read_bytes()


@linux_only
def test_a_rewritten_base_file_gives_stop(toy):
    repo = toy["repo"]
    assert _purge(toy) == 0
    record = json.loads((toy["out"] / "base_record.json").read_text(encoding="utf-8"))
    allow = sb.load_allowlist(toy["allow"])
    assert sb.check(record, [], allow, "B0", repo)["verdict"] == "OK"
    # (i) unprotect and rewrite in place
    a = repo / "data/cal2026-10/a.csv"
    os.chmod(a, 0o644)
    a.write_text("x,y\n9,9\n", encoding="utf-8")
    # (ii) rename-over with the same bytes: a new inode
    ok = repo / "data/cal2026-08-28/ok.csv"
    tmp = ok.with_name("ok.csv.tmp")
    tmp.write_bytes(ok.read_bytes())
    os.replace(tmp, ok)
    res = sb.check(record, [], allow, "B0", repo)
    assert res["verdict"] == "STOP_REWRITE"
    assert ["data/cal2026-10/a.csv", "sha256"] in res["rewritten"]
    assert ["data/cal2026-08-28/ok.csv", "inode"] in res["rewritten"]
    assert ["data/cal2026-08-28/ok.csv", "sha256"] not in res["rewritten"]
    assert not any(p == "data/cal2026-08-28/x.csv" for p, _ in res["rewritten"])


@linux_only
def test_a_non_allowlisted_0828_read_gives_g_read_fail(toy):
    repo, work = toy["repo"], toy["work"]
    toy["ref"].mkdir(parents=True)
    sb.start_watcher(repo=repo, ref=toy["ref"], work=work)
    assert (repo / "data/cal2026-08-28/ok.csv").read_text(encoding="utf-8") == "allowed\n"
    rc, res = _check_cli(toy, {})
    assert rc == 0 and res["verdict"] == "OK" and res["watcher"] == "stopped"
    assert "frames" in res["audited_stages"]

    sb.start_watcher(repo=repo, ref=toy["ref"], work=work)
    (repo / "data/cal2026-08-28/ok.csv").read_text(encoding="utf-8")
    (repo / "data/cal2026-08-28/x.csv").read_text(encoding="utf-8")
    rc, res = _check_cli(toy, {})
    assert rc == 1 and res["verdict"] == "G_READ_FAIL"
    assert res["gread"] == [["frames", "data/cal2026-08-28/x.csv"]]
    assert not (work / sb.PID_NAME).exists()                      # the check stopped the watcher first


@linux_only
def test_a_read_by_a_non_python_process_is_seen(toy):
    repo, work, ref = toy["repo"], toy["work"], toy["ref"]
    (ref / "analysis/expected").mkdir(parents=True)
    (ref / "analysis/expected/P1.json").write_text("{}\n", encoding="utf-8")
    sb.start_watcher(repo=repo, ref=ref, work=work)
    for rel in ("data/cal2026-08-28/x.csv", "data/raw_verified/events_econ_cal2026-08-28.csv",
                "data/raw_verified/other.csv"):
        subprocess.run(["cat", str(repo / rel)], stdout=subprocess.DEVNULL, check=True)
    (work / "status.txt").write_text("2026-10-15T01:00:00Z STAGE cells_rmac\n", encoding="utf-8")
    subprocess.run(["cat", str(ref / "analysis/expected/P1.json")], stdout=subprocess.DEVNULL, check=True)
    subprocess.run(["cp", str(repo / "data/raw_verified/other.csv"), str(repo / "data/cal2026-08-28/new.csv")],
                   check=True)                                    # a file created in the canon counts too
    assert sb.stop_watcher(work / sb.PID_NAME) == "stopped"
    reads, stages = sb.load_reads([work / "reads"])
    assert ("frames", "data/cal2026-08-28/x.csv") in reads
    assert ("frames", "data/raw_verified/events_econ_cal2026-08-28.csv") in reads
    assert not any(p == "data/raw_verified/other.csv" for _, p in reads)
    assert ("cells_rmac", "ref:analysis/expected/P1.json") in reads
    assert ("cells_rmac", "data/cal2026-08-28/new.csv") in reads
    assert {"frames", "cells_rmac"} <= stages


@linux_only
def test_the_run2_quarantine_is_watched_and_the_rest_of_the_october_tree_is_not(toy):
    """data/cal2026-10/_invalid_run2 is base (it stays in the clone) yet holds byte copies of October event
    products, so its reads are logged like the 08-28 canon's (pre-J0 sandbox review 2026-10-16, finding 1);
    the other base files of data/cal2026-10, which the chain reads all the time, are not watched."""
    repo, work, ref = toy["repo"], toy["work"], toy["ref"]
    run2 = repo / "data/cal2026-10/_invalid_run2"
    run2.mkdir(parents=True)
    for name in ("verdicts_2026-10.csv", "events_chemistry_cal2026-10.csv"):
        (run2 / name).write_text(f"{name}\n", encoding="utf-8")
    ref.mkdir(parents=True)
    sb.start_watcher(repo=repo, ref=ref, work=work)
    for rel in ("data/cal2026-10/_invalid_run2/verdicts_2026-10.csv",
                "data/cal2026-10/_invalid_run2/events_chemistry_cal2026-10.csv", "data/cal2026-10/a.csv"):
        subprocess.run(["cat", str(repo / rel)], stdout=subprocess.DEVNULL, check=True)
    assert sb.stop_watcher(work / sb.PID_NAME) == "stopped"
    reads, _stages = sb.load_reads([work / "reads"])
    assert ("frames", "data/cal2026-10/_invalid_run2/verdicts_2026-10.csv") in reads
    assert ("frames", "data/cal2026-10/_invalid_run2/events_chemistry_cal2026-10.csv") in reads
    assert not any(p == "data/cal2026-10/a.csv" for _, p in reads)


def test_allowlist_rows_are_per_config_and_ref_reads_per_stage(tmp_path):
    allow = tmp_path / "allow.txt"
    allow.write_text(ALLOW, encoding="utf-8")
    rows = sb.load_allowlist(allow)
    repo = tmp_path
    canon = [("frames", "data/cal2026-08-28/ok.csv")]
    assert sb.check({}, canon, rows, "B0", repo)["verdict"] == "OK"
    res = sb.check({}, canon, rows, "M", repo)                    # a B0-only row does not cover M
    assert res["verdict"] == "G_READ_FAIL" and res["gread"] == [["frames", "data/cal2026-08-28/ok.csv"]]
    res = sb.check({}, [("frames", "ref:analysis/expected/P1.json")], rows, "B0", repo)
    assert res["verdict"] == "G_READ_FAIL" and res["gread"] == [["frames", "ref:analysis/expected/P1.json"]]
    res = sb.check({}, [("cells_rmac", "ref:analysis/expected/P1.json")], rows, "B0", repo)
    assert res["verdict"] == "OK"
    assert res["unused_allowlist"] == ["data/cal2026-08-28/ok.csv", "data/raw_verified/*cal2026-08-28*"]
    assert res["audited_stages"] == ["cells_rmac"]
    # a reference-copy row must name its stages; configs are B0, M or *
    for bad in (f"ref:analysis/expected/**\tB0\t*\t{REASON}\n", f"data/cal2026-08-28/ok.csv\tB1\t*\t{REASON}\n",
                "data/cal2026-08-28/ok.csv\tB0\t*\ttoo short\n"):
        allow.write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError):
            sb.load_allowlist(allow)


@linux_only
def test_purge_refuses_a_stale_tsv_and_an_output_covering_a_base_input(toy, tmp_path):
    repo, ref = toy["repo"], toy["ref"]
    good = toy["tsv"].read_text(encoding="utf-8")
    blob = _git(repo, "ls-files", "-s", "data/cal2026-10/a.csv").split()[1]

    def nothing_moved():
        assert (repo / "data/cal2026-10/p.csv").is_file() and (repo / "analysis/expected/P1.json").is_file()
        assert not ref.exists() and not (repo / ".r1_sandbox.json").exists()
        assert os.access(repo / "data/cal2026-10/a.csv", os.W_OK)
        assert not (toy["work"] / sb.PID_NAME).exists()

    toy["tsv"].write_text(good.replace(blob, "0" * 40), encoding="utf-8")         # a blob that is not HEAD's
    assert _purge(toy) == 1
    assert json.loads((toy["out"] / "stop_report_sandbox.json").read_text(encoding="utf-8"))["code"] == "TSV_STALE"
    nothing_moved()
    toy["tsv"].write_text("".join(ln for ln in good.splitlines(True) if "/x.csv\t" not in ln), encoding="utf-8")
    assert _purge(toy) == 1                                                        # a tracked file with no row
    nothing_moved()

    toy["tsv"].write_text(good, encoding="utf-8")
    assert _purge(toy, table=_table(tmp_path / "wide.json", ("repo:data/cal2026-10",))) == 1
    assert json.loads((toy["out"] / "stop_report_sandbox.json").read_text(encoding="utf-8"))["code"] == "OUTPUT_COVERS_BASE"
    nothing_moved()


def test_a_lost_event_queue_fails_closed(tmp_path):
    repo, reads, status = tmp_path / "repo", tmp_path / "reads", tmp_path / "status.txt"
    status.write_text("2026-10-15T00:00:00Z STAGE frames\n", encoding="utf-8")
    w = sb.Watcher(repo=repo, ref=tmp_path / "ref", status=status, reads=reads)
    w.wds[7] = ("repo", "data/cal2026-08-28")
    name = b"x.csv\0\0\0"
    w.feed(sb.EVENT.pack(7, sb.IN_OPEN, 0, len(name)) + name
           + sb.EVENT.pack(7, sb.IN_OPEN | sb.IN_ISDIR, 0, 0)                     # the directory itself: ignored
           + sb.EVENT.pack(-1, sb.IN_Q_OVERFLOW, 0, 0))
    w.close()
    got, stages = sb.load_reads([reads])
    assert got == [("frames", "data/cal2026-08-28/x.csv"), ("frames", sb.LOST)] and stages == {"frames"}
    allow = [sb.AllowRow("data/cal2026-08-28/x.csv", ("*",), None, REASON)]
    assert sb.check({}, got, allow, "B0", repo)["verdict"] == "AUDIT_LOST"
    assert sb.check({}, got[:1], allow, "B0", repo)["verdict"] == "OK"


def test_a_resumed_job_carries_skipped_stage_logs_forward(tmp_path):
    live, prior = tmp_path / "reads", tmp_path / "resume" / "_reads"
    live.mkdir()
    prior.mkdir(parents=True)
    (live / "frames.tsv").write_text("frames\tdata/cal2026-08-28/ok.csv\n", encoding="utf-8")     # ran here
    (prior / "frames.tsv").write_text("frames\tdata/cal2026-08-28/x.csv\n", encoding="utf-8")     # an older run
    (prior / "write_events.tsv").write_text("write_events\tdata/raw_verified/events_econ_cal2026-08-28.csv\n",
                                            encoding="utf-8")                                    # skipped here
    assert sb.carry_forward([live, prior]) == ["write_events"]
    assert (live / "frames.tsv").read_text(encoding="utf-8") == "frames\tdata/cal2026-08-28/ok.csv\n"
    assert (live / "write_events.tsv").read_bytes() == (prior / "write_events.tsv").read_bytes()
    assert sb.carry_forward([live, prior]) == [] and sb.carry_forward([live]) == []
    assert sb.carry_forward([live, tmp_path / "absent"]) == []


# ---- complete audits on a resumed job (J0 review #5, accepted in part 2026-10-16) ---------------------------
def _status_event(w, status, text):
    """Rewrite the status file and feed the watcher the close-write event run_stages' write would raise."""
    status.write_text(text, encoding="utf-8")
    name = status.name.encode() + b"\0\0"
    w.feed(sb.EVENT.pack(w.status_wd, sb.IN_CLOSE_WRITE, 0, len(name)) + name)


def test_the_watcher_ends_a_stage_log_when_it_leaves_the_stage_or_stops_cleanly(tmp_path):
    """Events are handled in queue order, so every read of a stage precedes its end line; a watcher killed
    outright leaves none, and 'no stage' (run_stages' IDLE between stages) gets none."""
    repo, reads, status = tmp_path / "repo", tmp_path / "reads", tmp_path / "status.txt"
    status.write_text("2026-10-16T00:00:00Z STAGE write_events\n", encoding="utf-8")
    w = sb.Watcher(repo=repo, ref=tmp_path / "ref", status=status, reads=reads)
    w.wds[7], w.status_wd = ("repo", "data/cal2026-10/_invalid_run2"), 9
    name = b"verdicts_2026-10.csv\0\0\0\0"
    w.feed(sb.EVENT.pack(7, sb.IN_OPEN, 0, len(name)) + name)
    _status_event(w, status, "2026-10-16T00:01:00Z IDLE\n")
    _status_event(w, status, "2026-10-16T00:02:00Z STAGE frames\n")
    _status_event(w, status, "2026-10-16T00:02:01Z STAGE frames\n")             # the same stage again: no end
    w.end_stage()                                                                # what a clean SIGTERM drain does
    w.close()
    assert (reads / "write_events.tsv").read_text(encoding="utf-8").splitlines() == [
        "write_events\tdata/cal2026-10/_invalid_run2/verdicts_2026-10.csv", f"write_events\t{sb.END}"]
    assert (reads / "frames.tsv").read_text(encoding="utf-8").splitlines() == [f"frames\t{sb.END}"]
    assert (reads / f"{sb.NO_STAGE}.tsv").read_text(encoding="utf-8") == ""
    assert sb.ended_logs(reads) == {"write_events", "frames"}


def test_the_audited_span_is_the_tables_stages_between_sandbox_and_sandbox_check(tmp_path):
    t = _check_table(tmp_path / "t.json", between=("write_events", "frames"))
    assert sb.audited_span(t) == ["write_events", "frames"]
    j0 = REPO / "config" / "r1" / "stages" / "j0.json"
    names = [s["name"] for s in json.loads(j0.read_text(encoding="utf-8"))["stages"]]
    assert sb.audited_span(j0) == names[names.index("sandbox") + 1:names.index("sandbox_check")]
    assert len(sb.audited_span(j0)) == 11
    row = next(s for s in json.loads(j0.read_text(encoding="utf-8"))["stages"] if s["name"] == "sandbox_check")
    assert '--table "$REPO_DIR/config/r1/stages/j0.json"' in row["cmd"]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"stages": [{"name": "sandbox_check"}, {"name": "sandbox"}]}), encoding="utf-8")
    with pytest.raises(ValueError):
        sb.audited_span(bad)


def test_a_rerun_stages_fresh_log_supersedes_its_resumed_one(tmp_path):
    """Before: every *.tsv of every --reads dir was loaded, so the obsolete prior log of a stage that reran here
    still counted (a false G_READ_FAIL on every resume). Now each stage has exactly one log: the live one, or the
    resumed one carry_forward copied in."""
    allow = sb.load_allowlist(_w_allow(tmp_path))
    live, prior = tmp_path / "reads", tmp_path / "resume" / "_reads"
    live.mkdir()
    prior.mkdir(parents=True)
    (prior / "frames.tsv").write_text(f"frames\tdata/cal2026-08-28/x.csv\nframes\t{sb.END}\n", encoding="utf-8")
    (live / "frames.tsv").write_text(f"frames\tdata/cal2026-08-28/ok.csv\nframes\t{sb.END}\n", encoding="utf-8")
    (prior / "write_events.tsv").write_text(f"write_events\t{sb.END}\n", encoding="utf-8")          # restored here
    reads, stages, ended, carried = sb.collect_reads([live, prior])
    assert carried == ["write_events"] and stages == {"frames", "write_events"} and ended == stages
    assert ("frames", "data/cal2026-08-28/x.csv") not in reads
    res = sb.check({}, reads, allow, "B0", tmp_path, stages=stages, expected=["write_events", "frames"], ended=ended)
    assert res["verdict"] == "OK" and res["gread"] == [] and res["audit_missing"] == res["audit_unterminated"] == []


def test_a_missing_or_unterminated_log_in_the_audited_span_is_audit_lost(tmp_path):
    """Before: a stage restored with no log, or with the partial log of a watcher killed mid-stage, passed."""
    allow = sb.load_allowlist(_w_allow(tmp_path))
    exp = ["write_events", "frames"]
    live, prior = tmp_path / "reads", tmp_path / "resume" / "_reads"
    live.mkdir()
    prior.mkdir(parents=True)
    (live / "frames.tsv").write_text(f"frames\tdata/cal2026-08-28/ok.csv\nframes\t{sb.END}\n", encoding="utf-8")
    reads, stages, ended, _ = sb.collect_reads([live, prior])
    res = sb.check({}, reads, allow, "B0", tmp_path, stages=stages, expected=exp, ended=ended)
    assert res["verdict"] == "AUDIT_LOST" and res["audit_missing"] == ["write_events"]
    (prior / "write_events.tsv").write_text("write_events\tdata/cal2026-08-28/ok.csv\n", encoding="utf-8")   # no end
    reads, stages, ended, _ = sb.collect_reads([live, prior])
    res = sb.check({}, reads, allow, "B0", tmp_path, stages=stages, expected=exp, ended=ended)
    assert res["verdict"] == "AUDIT_LOST" and res["audit_missing"] == [] and res["audit_unterminated"] == ["write_events"]
    assert res["gread"] == []                                                    # the read itself is allowlisted
    # outside the audited span nothing is required, and the end rows are never matched against the allowlist
    assert sb.check({}, reads, allow, "B0", tmp_path, stages=stages)["verdict"] == "OK"


def test_check_refuses_to_run_without_the_stage_table(tmp_path, monkeypatch):
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    with pytest.raises(SystemExit, match="--table"):
        sb.main(["check", "--record", "r", "--reads", str(tmp_path), "--allowlist", "a", "--config", "B0",
                 "--out", str(tmp_path / "o"), "--repo", str(tmp_path), "--work", str(tmp_path)])
    assert not (tmp_path / "o").exists()


@linux_only
def test_a_clean_stop_ends_the_running_stages_log(toy):
    repo, work, ref = toy["repo"], toy["work"], toy["ref"]
    ref.mkdir(parents=True)
    sb.start_watcher(repo=repo, ref=ref, work=work)
    subprocess.run(["cat", str(repo / "data/cal2026-08-28/ok.csv")], stdout=subprocess.DEVNULL, check=True)
    (work / "status.txt").write_text("2026-10-16T01:00:00Z STAGE cells_rmac\n", encoding="utf-8")
    deadline = time.monotonic() + 30
    while not (work / "reads" / "cells_rmac.tsv").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert sb.stop_watcher(work / sb.PID_NAME) == "stopped"
    assert (work / "reads" / "frames.tsv").read_text(encoding="utf-8").splitlines() == [
        "frames\tdata/cal2026-08-28/ok.csv", f"frames\t{sb.END}"]
    assert (work / "reads" / "cells_rmac.tsv").read_text(encoding="utf-8").splitlines() == [f"cells_rmac\t{sb.END}"]


def test_refuses_off_aws(tmp_path, monkeypatch):
    monkeypatch.delenv("SAR_HOST", raising=False)
    ref = tmp_path / "ref"
    for argv in (["purge", "--repo", str(tmp_path), "--tsv", "t", "--ref", str(ref), "--config", "B0", "--table", "x",
                  "--allowlist", "a", "--out", str(tmp_path / "o"), "--work", str(tmp_path)],
                 ["check", "--record", "r", "--reads", str(tmp_path), "--allowlist", "a", "--config", "B0",
                  "--out", str(tmp_path / "o"), "--repo", str(tmp_path), "--work", str(tmp_path)]):
        with pytest.raises(SystemExit, match="SAR_HOST"):
            sb.main(argv)
    assert not ref.exists() and not (tmp_path / "o").exists()
