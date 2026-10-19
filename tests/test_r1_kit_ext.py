# -*- coding: utf-8 -*-
"""R1 P3 kit extensions (W1-KIT: F2, F23, F30, J0-MEAS.shell, J0-MEAS.3i, V3-FINAL): the read-log sync, name-free
stage reports (also for a failed stage), the summary's commit, REQUIRED_STAGES for complete tables, the
--baseline-from guard and restore_upstream.py. Fake `aws`, toy git repo, toy stage sets; nothing leaves tmp_path."""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for p in (REPO / "pipeline" / "aws" / "r1", REPO / "tests"):
    sys.path.insert(0, str(p))
import r1kit                                       # noqa: E402
import restore_upstream as ru                      # noqa: E402
import run_stages as rs                            # noqa: E402
from r1_fakes import aws_calls, install_fake_aws   # noqa: E402

TABLE = {"schema": "sar.r1.stages.v1", "job": "toy", "complete": True, "stages": [
    {"name": "s1", "owner": "F25", "cmd": 'mkdir -p "$STAGE_OUT" && cp "$REPO_DIR/data.txt" "$STAGE_OUT/a.txt"',
     "inputs": ["repo:data.txt"], "outputs": ["work:prod/s1"], "est_min": 1, "needs": []},
    {"name": "s2", "owner": "F25",
     "cmd": 'mkdir -p "$STAGE_OUT/sub" && { cat "$WORK/prod/s1/a.txt"; echo two; } > "$STAGE_OUT/b.txt" && echo x > "$STAGE_OUT/sub/x.txt"',
     "inputs": ["stage:s1"], "outputs": ["work:prod/s2"], "est_min": 1, "needs": ["s1"]},
    {"name": "s3", "owner": "F25",
     "cmd": 'mkdir -p "$REPO_DIR/output" && { cat "$WORK/prod/s2/b.txt"; echo three; } > "$REPO_DIR/output/c.txt"',
     "inputs": ["stage:s2"], "outputs": ["repo:output/c.txt"], "est_min": 1, "needs": ["s2"]}]}
PID = "P_A5046503193"


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
    rep = repo / "reports"
    (rep / "g1").mkdir(parents=True)
    (rep / "stop").mkdir()
    (rep / "g1" / "gate_report_1.json").write_text(json.dumps(
        {"verdict": "PASS", "gate": "gate1", "detail": "Yves Zenou kept at Monash", "ids": [PID, "Zenou"],
         "counts": {"cells": 29, "Zenou Yves": 1}}))
    (rep / "g1" / "final_report_gate2.json").write_text(json.dumps(
        {"verdict": "PENDING_AUTHOR", "codes": ["WORDS_OVER"], "why": "the Zenou sentence"}))
    (rep / "g1" / "report_restore.json").write_text(json.dumps({"result": "OK", "n_rows": 3, "name": "Yves Zenou"}))
    (rep / "stop" / "stop_report_agg_missing.json").write_text(json.dumps(
        {"code": "AGG_MISSING", "ids": [PID], "persons": ["Yves Zenou"], "n_persons": 1}))
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "toy")
    return fake, repo, _git(repo, "rev-parse", "HEAD")


def _run(tmp_path, repo, commit, table, work, job="j-unit-01", *extra):
    t = tmp_path / f"{work.name}.table.json"
    t.write_text(json.dumps(table))
    return rs.main(["--table", str(t), "--repo", str(repo), "--commit", commit, "--prefix", f"s3://fake-bucket/r1/runs/{job}",
                    "--work", str(work), "--out", str(work / "out"), *extra])


def _summary(work):
    return json.loads((work / "out" / "summary.json").read_text())


# ---- run_stages: the read logs (F2) ----------------------------------------------------------------
def _reads_syncs(calls, job):
    return [i for i, c in enumerate(calls) if c[:2] == ["s3", "sync"]
            and c[-1] == f"s3://fake-bucket/r1/runs/{job}/stages/_reads/"]


def test_reads_are_synced_after_a_ran_and_a_skipped_stage(tmp_path, toy):
    fake, repo, commit = toy
    (tmp_path / "a" / "reads").mkdir(parents=True)
    (tmp_path / "a" / "reads" / "s1.tsv").write_text("s1\tdata/cal2026-08-28/x.csv\n")
    assert _run(tmp_path, repo, commit, TABLE, tmp_path / "a", "j-unit-21") == 0
    calls = aws_calls(fake["log"])
    syncs = _reads_syncs(calls, "j-unit-21")
    assert len(syncs) == 3                                              # one after each pushed stage
    assert all(calls[i][-2] == f"{tmp_path / 'a' / 'reads'}/" for i in syncs)
    stages = fake["s3root"] / "fake-bucket" / "r1" / "runs" / "j-unit-21" / "stages"
    assert (stages / "_reads" / "s1.tsv").read_text() == "s1\tdata/cal2026-08-28/x.csv\n"

    rd = tmp_path / "resume"                                            # the --resume-from pull of stages/
    shutil.copytree(stages, rd)
    assert (rd / "_reads" / "s1.tsv").is_file()                         # restored to /work/resume/_reads
    (tmp_path / "c" / "reads").mkdir(parents=True)
    n0 = len(calls)
    assert _run(tmp_path, repo, commit, TABLE, tmp_path / "c", "j-unit-22", "--resume-dir", str(rd)) == 0
    assert [x["status"] for x in _summary(tmp_path / "c")["stages"]] == ["skipped", "skipped", "skipped"]
    calls = aws_calls(fake["log"])[n0:]
    syncs = _reads_syncs(calls, "j-unit-22")
    assert len(syncs) == 3
    for name, i in zip(("s1", "s2", "s3"), syncs):                     # each right after that stage's marker push
        assert calls[i - 1][-1] == f"s3://fake-bucket/r1/runs/j-unit-22/stages/{name}.done.json"


def test_no_reads_dir_means_no_sync(tmp_path, toy):
    fake, repo, commit = toy
    assert _run(tmp_path, repo, commit, TABLE, tmp_path / "w", "j-unit-23") == 0
    assert _reads_syncs(aws_calls(fake["log"]), "j-unit-23") == []


# ---- run_stages: name-free reports and the summary (F23, J0-MEAS.3i) ----------------------------------
def _report_table():
    cp = 'mkdir -p "$STAGE_OUT" && cp "$REPO_DIR"/reports/{d}/*.json "$STAGE_OUT"/'
    return {**TABLE, "stages": [
        {"name": "g1", "owner": "F23", "cmd": cp.format(d="g1"), "inputs": [], "outputs": ["work:prod/g1"],
         "est_min": 1, "needs": []},
        {"name": "agg", "owner": "J0-MEAS.3i", "cmd": cp.format(d="stop") + " && exit 3", "inputs": [],
         "outputs": ["work:prod/agg"], "est_min": 1, "needs": ["g1"]}]}


def test_gate_report_stop_and_final_reports_reach_the_summary_name_free_also_for_a_failed_stage(tmp_path, toy):
    _, repo, commit = toy
    assert _run(tmp_path, repo, commit, _report_table(), tmp_path / "w") == 1
    s = _summary(tmp_path / "w")
    assert s["result"] == "STAGE_FAIL" and s["stages"][-1]["status"] == "failed"
    g = s["reports"]["g1"]
    assert g["gate_report_1.json"] == {"verdict": "PASS", "gate": "gate1", "ids": [PID], "counts": {"cells": 29}}
    assert g["final_report_gate2.json"] == {"verdict": "PENDING_AUTHOR", "codes": ["WORDS_OVER"]}
    assert g["report_restore.json"] == {"result": "OK", "n_rows": 3}
    assert s["reports"]["agg"]["stop_report_agg_missing.json"] == {"code": "AGG_MISSING", "ids": [PID], "n_persons": 1}
    assert "Zenou" not in (tmp_path / "w" / "out" / "summary.json").read_text()


def test_summary_has_commit(tmp_path, toy):
    _, repo, commit = toy
    assert _run(tmp_path, repo, commit, TABLE, tmp_path / "w") == 0
    assert _summary(tmp_path / "w")["commit"] == commit and len(commit) == 40


def test_name_free_drops_names_keeps_ids():
    obj = {"result": "STOP", "code": "AGG_MISSING", "commit": "c" * 40, "secs": 12,
           "ids": [PID, "A5065862323:2008", "P_A123456:monash", "Yves Zenou", "A12", "B5065862323", "zenou"],
           "detail": "Yves Zenou moved", "why": "Zenou",
           "persons": {"Zenou": 3, PID: {"name": "Yves Zenou", "n_rows": 2}, "Yves Zenou": {"n_rows": 1}},
           "counts": {"econ": 3, "Zenou Yves": 1, "math_stats": {"n_events": 2, "who": "Zenou"}},
           "rows_by_class": {"old_event": 4}, "n_missing": 5, "worst_ulp": 3, "path": "data/cal2026-10/frames/p1.csv",
           "cells": [{"label": "P1_econ", "status": "EQUAL", "note": "Zenou"}], "missing": ["frames/p1.csv"]}
    got = rs.name_free(obj)
    assert "Zenou" not in json.dumps(got) and "zenou" not in json.dumps(got)
    assert got["ids"] == [PID, "A5065862323:2008", "P_A123456:monash"]
    assert got["persons"] == {PID: {"n_rows": 2}}
    assert got["counts"] == {"econ": 3, "math_stats": {"n_events": 2}}
    for k in ("result", "code", "commit", "secs", "rows_by_class", "n_missing", "worst_ulp", "path", "missing"):
        assert got[k] == obj[k], k
    assert got["cells"] == [{"label": "P1_econ", "status": "EQUAL"}]
    assert "detail" not in got and "why" not in got
    assert rs.name_free("Yves Zenou") is None and rs.name_free(7) == 7 and rs.name_free([PID, "Zenou"]) == []


# ---- r1kit: REQUIRED_STAGES (F30, V3-FINAL) and --baseline-from ---------------------------------------
def _toy_table(job, names, complete):
    return {"schema": rs.SCHEMA, "job": job, "complete": complete, "stages": [
        {"name": n, "owner": "F30", "cmd": "true", "inputs": [], "outputs": [f"work:prod/{n}"], "est_min": 1, "needs": []}
        for n in names]}


def _check(table):
    return r1kit.check_stage_table({"stages": f"config/r1/stages/{table['job']}.json"}, "c" * 40,
                                   show=lambda p: json.dumps(table), exists=lambda p: True)


def test_required_stages_are_the_signed_lists():
    assert r1kit.REQUIRED_STAGES == {
        "j0": ("verify_inputs", "relink", "config", "sandbox", "frames_econ920", "pairs_pin", "frames", "cells_rmac",
               "cells_rcloud", "sandbox_check", "gate1"),
        "j1a": ("verify_inputs", "relink", "config", "sandbox", "gate1_link", "rank_gate", "rank_tables", "events",
                "frames", "cells_rmac", "cells_rcloud", "estimates_m", "promote", "sandbox_check"),
        "j1b": ("verify_inputs", "config", "restore_j1a", "sandbox", "sandbox_check"),
        "final": ("verify_inputs", "config", "canon", "custody", "sentinel_pre", "sentinel_post", "gate2"),
        "finalb0": ("verify_inputs", "config", "sentinel_pre", "sentinel_post", "gate2"),
        "jp": ("repo_manifest", "cells_rmac", "cells_rcloud", "compare")}


def test_a_complete_table_must_carry_its_required_stages():
    full = list(r1kit.REQUIRED_STAGES["j0"])
    assert _check(_toy_table("j0", full, True)) == []
    for gone in ("sandbox", "gate1"):
        probs = _check(_toy_table("j0", [n for n in full if n != gone], True))
        assert len(probs) == 1 and gone in probs[0] and "incomplete" not in probs[0], probs
    probs = _check(_toy_table("j0", [n for n in full if n not in ("sandbox", "gate1")], False))
    assert len(probs) == 1 and "incomplete" in probs[0]                  # an incomplete table: only that line
    probs = _check(_toy_table("j9", ["verify_inputs"], True))            # a complete table no list covers
    assert probs and "REQUIRED_STAGES" in probs[0]
    for job, names in r1kit.REQUIRED_STAGES.items():                     # every list is satisfiable as written
        assert _check(_toy_table(job, list(names), True)) == [], job


def test_the_real_jp_table_carries_its_required_stages():
    t = json.loads((REPO / "config" / "r1" / "stages" / "jp.json").read_text(encoding="utf-8"))
    assert t["complete"] is True and _check(t) == []


@pytest.fixture
def runs(tmp_path, monkeypatch):
    monkeypatch.setattr(r1kit, "RUNS_LOCAL", tmp_path / "runs")
    monkeypatch.setattr(r1kit, "LEDGER", tmp_path / "ledger.jsonl")
    for job, kind in (("t-0007", "test"), ("t-big-01", "test_big")):
        d = tmp_path / "runs" / job
        d.mkdir(parents=True)
        (d / "launch_record.json").write_text(json.dumps({"schema": "sar.r1.launch.v1", "job": job, "kind": kind}))
    return tmp_path / "runs"


def test_baseline_from_refuses_a_non_test_big_job(runs, capsys):
    assert r1kit.baseline_pulls("t-big-01") == [("r1/runs/t-big-01/out/files/", "/work/bigbase/")]
    with pytest.raises(r1kit.KitError, match="test_big"):
        r1kit.baseline_pulls("t-0007")
    with pytest.raises(r1kit.KitError, match="no launch record"):
        r1kit.baseline_pulls("t-big-77")
    with pytest.raises(r1kit.KitError):
        r1kit.baseline_pulls("../t-big-01")
    rc = r1kit.main(["test", "t-big-09", "--kind", "test_big", "--green", "HEAD", "--markers", "not live",
                     "--baseline-from", "t-0007", "--dry-run"])
    assert rc == 2 and "test_big" in capsys.readouterr().err
    assert not (runs / "t-big-09").exists()


def test_test_passes_pulls_and_test_big_needs_the_j0_stage_set(runs, monkeypatch):
    """B4 (t-big-04): the big-host suite reads J0's git-ignored products (output/cal_intermediates/*.csv,
    laid out from the stage set by restore_upstream), so test_big requires a J0 stage set at /work/j0/ (the
    J1a convention) and `r1kit.py test` passes --pull through to the launch, after --baseline-from's pull.
    A malformed --pull stops before anything is launched."""
    assert r1kit.load_job("test_big")["required_dests"] == ["/work/j0/"]
    seen = {}
    monkeypatch.setattr(r1kit, "load_kit", lambda: {"repo_base_commit": "b" * 40})
    monkeypatch.setattr(r1kit, "resolve_commit", lambda ref: "c" * 40)
    monkeypatch.setattr(r1kit, "launch", lambda kind, job, commit, **kw: seen.update(kind=kind, job=job, **kw))
    rc = r1kit.main(["test", "t-big-09", "--kind", "test_big", "--green", "HEAD", "--markers", "not live",
                     "--baseline-from", "t-big-01", "--pull", "r1/runs/j0-02/stages/=/work/j0/", "--dry-run"])
    assert rc == 0 and seen["kind"] == "test_big" and seen["job"] == "t-big-09"
    assert seen["extra_pulls"] == [("r1/runs/t-big-01/out/files/", "/work/bigbase/"),
                                   ("r1/runs/j0-02/stages/", "/work/j0/")]
    seen.clear()
    assert r1kit.main(["test", "t-0099", "--green", "HEAD", "--pull", "no-equals-sign", "--dry-run"]) == 2
    assert seen == {}


# ---- restore_upstream.py (V3-FINAL, W2-TJ1B / W2-FINALJOB) -------------------------------------------
@pytest.fixture
def stage_set(tmp_path, toy):
    """A real stage set: the toy table run by run_stages, then pulled (copied) like r1/runs/<job>/stages/."""
    fake, repo, commit = toy
    assert _run(tmp_path, repo, commit, TABLE, tmp_path / "up", "j1a-77") == 0
    sd = tmp_path / "j1a_stages"
    shutil.copytree(fake["s3root"] / "fake-bucket" / "r1" / "runs" / "j1a-77" / "stages", sd)
    layout = {"schema": "sar.r1.layout.v1", "rows": [
        {"dest": "frames/a.txt", "from": {"job": "j1a", "stage": "s1", "token": "work:prod/s1", "rel": "a.txt"}},
        {"dest": "s2", "from": {"job": "j1a", "stage": "s2", "token": "work:prod/s2", "rel": ""}},
        {"dest": "out/c.txt", "from": {"job": "j1a", "stage": "s3", "token": "repo:output/c.txt", "rel": ""}},
        {"dest": "carried/data.txt", "from": {"repo": "data.txt"}}]}
    return sd, layout, repo


def _restore(tmp_path, sd, layout, repo, tag, *extra):
    lay = tmp_path / f"layout_{tag}.json"
    lay.write_text(json.dumps(layout))
    dest, out = tmp_path / f"dest_{tag}", tmp_path / f"out_{tag}"
    rc = ru.main(["--stages", str(sd), "--layout", str(lay), "--dest", str(dest), "--out", str(out), "--repo", str(repo),
                  *extra])
    rep = json.loads((out / "report_restore.json").read_text()) if (out / "report_restore.json").is_file() else None
    return rc, dest, rep


def _files(d):
    return sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()) if d.is_dir() else []


def test_restore_upstream_copies_on_matching_digests_and_refuses_tampered_missing_marker_or_row(tmp_path, stage_set):
    sd, layout, repo = stage_set
    rc, dest, rep = _restore(tmp_path, sd, layout, repo, "ok", "--manifest")
    assert rc == 0 and rep["result"] == "OK"
    assert (dest / "frames" / "a.txt").read_text() == "seed\n"
    assert (dest / "s2" / "b.txt").read_text() == "seed\ntwo\n" and (dest / "s2" / "sub" / "x.txt").read_text() == "x\n"
    assert (dest / "out" / "c.txt").read_text() == "seed\ntwo\nthree\n"
    assert (dest / "carried" / "data.txt").read_text() == "seed\n"
    assert rep["counts"] == {"rows": 4, "stage_rows": 3, "repo_rows": 1, "tokens_checked": 3, "files": 5, "manifests": 4}
    man = (dest / "s2" / "MANIFEST.sha256").read_text().splitlines()
    assert man == [f"{rs.sha256_file(dest / 's2' / r)}  {r}" for r in ("b.txt", "sub/x.txt")]
    two = json.loads(json.dumps(layout))                                # FINAL: one stage set per job, JOB=DIR
    two["rows"][1]["from"]["job"] = "j1b"
    rc, dest2, rep2 = _restore(tmp_path, f"j1a={sd}", two, repo, "named", "--stages", f"j1b={sd}")
    assert rc == 0 and rep2["counts"]["manifests"] == 0
    assert _files(dest2) == ["carried/data.txt", "frames/a.txt", "out/c.txt", "s2/b.txt", "s2/sub/x.txt"]
    rc, _, rep2 = _restore(tmp_path, f"j1a={sd}", two, repo, "named_missing")   # j1b has no stage set
    assert rc == 1 and rep2["code"] == "BAD_ROW"

    def refused(tag, mutate_layout=None, mutate_set=None, code=None):
        lay = json.loads(json.dumps(layout))
        if mutate_layout:
            mutate_layout(lay["rows"])
        work_set = tmp_path / f"set_{tag}"
        shutil.copytree(sd, work_set)
        if mutate_set:
            mutate_set(work_set)
        rc, d, r = _restore(tmp_path, work_set, lay, repo, tag)
        assert rc == 1 and r["result"] == "STOP" and r["code"] == code, (tag, r)
        assert _files(d) == [], tag                                     # nothing is copied before every check passed

    refused("tampered", mutate_set=lambda s: (s / "s1" / "files" / "work" / "prod" / "s1" / "a.txt").write_text("x\n"),
            code="DIGEST_MISMATCH")
    refused("tampered_extra", mutate_set=lambda s: (s / "s2" / "files" / "work" / "prod" / "s2" / "extra.txt").write_text("x"),
            code="DIGEST_MISMATCH")
    refused("no_marker", mutate_set=lambda s: (s / "s3.done.json").unlink(), code="MISSING_MARKER")
    refused("no_token", mutate_layout=lambda rows: rows[0]["from"].update(token="work:prod/elsewhere"), code="MISSING_TOKEN")
    refused("no_file", mutate_layout=lambda rows: rows[0]["from"].update(rel="nope.txt"), code="MISSING_FILE")
    refused("no_repo_file", mutate_layout=lambda rows: rows[3]["from"].update(repo="nope.txt"), code="MISSING_FILE")
    refused("up", mutate_layout=lambda rows: rows[0].update(dest="../escape.txt"), code="BAD_PATH")
    refused("abs", mutate_layout=lambda rows: rows[0].update(dest="/tmp/escape.txt"), code="BAD_PATH")
    refused("rel_up", mutate_layout=lambda rows: rows[0]["from"].update(rel="../../s2/b.txt"), code="BAD_PATH")
    refused("dup", mutate_layout=lambda rows: rows.append(dict(rows[0])), code="BAD_ROW")
    refused("job", mutate_layout=lambda rows: rows[0]["from"].update(job="j1b"), code="BAD_ROW")   # one plain DIR, two jobs


def test_restore_upstream_refuses_off_aws(tmp_path, stage_set, monkeypatch):
    sd, layout, repo = stage_set
    monkeypatch.delenv("SAR_HOST")
    with pytest.raises(SystemExit, match="R1 instance"):
        _restore(tmp_path, sd, layout, repo, "off")
