# -*- coding: utf-8 -*-
"""pipeline/aws/r1/run_tests_r1.py - the instance-side test runner, on a toy git repo."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import run_tests_r1 as rt   # noqa: E402

FAILING = "def test_one():\n    assert 1 == 2\n"
PASSING = "def test_one():\n    assert 1 == 1\n"
TWO_FAIL = "def test_one():\n    assert 1 == 2\n\n\ndef test_two():\n    assert 0\n"


def _git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def toy(tmp_path):
    repo = tmp_path / "toy repo"                      # a space, like the real checkout
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    shas = {}
    for label, body in (("red", FAILING), ("green", PASSING), ("worse", TWO_FAIL)):
        (repo / "test_toy.py").write_text(body)
        _git(repo, "add", "test_toy.py")
        _git(repo, "commit", "-qm", label)
        shas[label] = _git(repo, "rev-parse", "HEAD")
    return repo, shas


def _run(tmp_path, repo, rows, *extra):
    tmp_path.mkdir(parents=True, exist_ok=True)
    spec = tmp_path / "tests.tsv"
    spec.write_text("".join("\t".join(r) + "\n" for r in rows))
    out = tmp_path / "out"
    rc = rt.main(["--spec", str(spec), "--repo", str(repo), "--out", str(out), "--python", sys.executable, *extra])
    return rc, json.loads((out / "results.json").read_text()), (out / "RESULT.txt").read_text().strip()


def test_red_fails_green_passes_and_the_run_is_ok(tmp_path, toy):
    repo, s = toy
    rc, res, result = _run(tmp_path, repo, [("red", s["red"], "fail", "-q test_toy.py", "-"),
                                            ("green", s["green"], "pass", "-q test_toy.py", "-")])
    assert rc == 0 and result == "OK" and [r["ok"] for r in res] == [True, True]
    assert res[0]["rc"] == 1 and res[1]["rc"] == 0


def test_an_unmet_expectation_makes_the_run_a_mismatch(tmp_path, toy):
    repo, s = toy
    rc, res, result = _run(tmp_path, repo, [("red", s["red"], "pass", "-q test_toy.py", "-")])
    assert rc == 1 and result == "MISMATCH" and res[0]["ok"] is False


def test_no_tests_collected_is_never_a_pass(tmp_path, toy):
    repo, s = toy
    rc, res, _ = _run(tmp_path, repo, [("empty", s["green"], "pass", "-q -k nothing_matches_this", "-")])
    assert rc == 1 and res[0]["rc"] == 5 and "no tests collected" in res[0]["why"]


def test_a_missing_test_file_is_not_a_red_fail(tmp_path, toy):
    repo, s = toy
    rc, res, _ = _run(tmp_path, repo, [("red", s["red"], "fail", "-q test_absent.py", "-")])
    assert rc == 1 and res[0]["ok"] is False


def test_noregress_accepts_old_failures_and_rejects_new_ones(tmp_path, toy):
    repo, s = toy
    rc, res, _ = _run(tmp_path, repo, [("base", s["red"], "record", "-q test_toy.py", "-"),
                                       ("same", s["red"], "noregress", "-q test_toy.py", "@base"),
                                       ("worse", s["worse"], "noregress", "-q test_toy.py", "@base")])
    assert [r["ok"] for r in res] == [True, True, False]
    assert "test_two" in res[2]["why"] and rc == 1


def test_the_checkout_is_restored_after_the_run(tmp_path, toy):
    repo, s = toy
    head = _git(repo, "rev-parse", "HEAD")
    _run(tmp_path, repo, [("red", s["red"], "fail", "-q test_toy.py", "-")])
    assert _git(repo, "rev-parse", "HEAD") == head


def test_spec_errors_are_refused(tmp_path, toy):
    repo, s = toy
    for rows in ([("a", s["red"], "maybe", "-q", "-")],
                 [("a", s["red"], "noregress", "-q", "-")],
                 [("a", s["red"], "record", "-q", "-"), ("a", s["green"], "record", "-q", "-")],
                 [("a", s["red"], "noregress", "-q", "@nope")]):
        with pytest.raises(SystemExit):
            _run(tmp_path, repo, rows)


def test_refuses_off_aws_and_refuses_the_mac_checkout(tmp_path, toy, monkeypatch):
    """`git clean -fdxq` on the Mac checkout would delete local.env, setup/.venv and the progress ledger."""
    repo, s = toy
    rows = [("green", s["green"], "pass", "-q test_toy.py", "-")]
    monkeypatch.delenv("SAR_HOST", raising=False)
    with pytest.raises(SystemExit, match="only on an R1 AWS instance"):
        _run(tmp_path, repo, rows)
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    (repo / "config" / "r1").mkdir(parents=True)
    (repo / "config" / "r1" / "local.env").write_text("SAR_S3_BUCKET=x\n")
    with pytest.raises(SystemExit, match="local.env"):
        _run(tmp_path, repo, rows)


SYNTAX = "def test_one(:\n    pass\n"
MISSING = "import not_written_yet\n\ndef test_one():\n    assert not_written_yet.f()\n"


@pytest.fixture
def toy2(toy):
    repo, shas = toy
    for label, body in (("syntax", SYNTAX), ("missing", MISSING)):
        (repo / "test_toy.py").write_text(body)
        _git(repo, "commit", "-qam", label)
        shas[label] = _git(repo, "rev-parse", "HEAD")
    return repo, shas


def test_a_missing_module_is_a_red_fail_and_a_syntax_error_is_not(tmp_path, toy2):
    repo, s = toy2
    rc, res, _ = _run(tmp_path, repo, [("m", s["missing"], "fail", "-q test_toy.py", "-"),
                                       ("x", s["syntax"], "fail", "-q test_toy.py", "-")])
    assert [r["ok"] for r in res] == [True, False] and "SyntaxError" in res[1]["why"]


def test_noregress_needs_at_least_the_baseline_test_count(tmp_path, toy):
    repo, s = toy
    rc, res, _ = _run(tmp_path, repo, [("base", s["worse"], "record", "-q test_toy.py", "-"),
                                       ("fewer", s["green"], "noregress", "-q test_toy.py", "@base")])
    assert res[1]["ok"] is False and "collected 1 < baseline 2" in res[1]["why"]


SKIPPING = ("import pytest\n\n"
            "@pytest.mark.skip(reason='no data')\ndef test_one():\n    pass\n")


def test_noregress_fails_when_a_test_that_passed_in_the_baseline_is_skipped_now(tmp_path, toy):
    """Review (P3b): gate 1b must not pass with every data test skipped."""
    repo, s = toy
    (repo / "test_toy.py").write_text(SKIPPING)
    _git(repo, "commit", "-qam", "skip")
    skip = _git(repo, "rev-parse", "HEAD")
    rc, res, _ = _run(tmp_path, repo, [("base", s["green"], "record", "-q test_toy.py", "-"),
                                       ("now", skip, "noregress", "-q test_toy.py", "@base")])
    assert res[1]["ok"] is False and "skipped now" in res[1]["why"] and res[1]["n_skipped"] == 1


def test_red_selection_by_node_id_or_dot_slash_path_counts_as_selected():
    assert rt._selected("-q ./tests/test_x.py::test_a tests/") == ["tests/test_x.py", "tests"]


OVERLAY_READER = ("import pathlib\n\n\ndef test_one():\n"
                  "    assert pathlib.Path('output/cal/pairs.csv').read_text() == 'pairs\\n'\n")


def test_an_overlay_is_laid_into_the_checkout_after_every_git_clean(tmp_path, toy):
    """B4 (t-big-04): each line's `git clean -fdxq` deletes git-ignored inputs placed in the checkout before the
    runner starts (J0's output/cal_intermediates), so --overlay DIR copies DIR's tree into the checkout after
    every clean. Without it the same test fails (the clean removed the file: positive control); an overlay
    path that git tracks is refused, never overwritten."""
    repo, s = toy
    (repo / "test_toy.py").write_text(OVERLAY_READER)
    _git(repo, "commit", "-qam", "reads an ignored input")
    sha = _git(repo, "rev-parse", "HEAD")
    ov = tmp_path / "overlay"
    (ov / "output" / "cal").mkdir(parents=True)
    (ov / "output" / "cal" / "pairs.csv").write_text("pairs\n")
    (repo / "output" / "cal").mkdir(parents=True)
    (repo / "output" / "cal" / "pairs.csv").write_text("pairs\n")        # untracked: the first clean removes it
    rows = [("a", sha, "pass", "-q test_toy.py", "-"), ("b", sha, "pass", "-q test_toy.py", "-")]
    rc, res, result = _run(tmp_path / "with", repo, rows, "--overlay", str(ov))
    assert rc == 0 and result == "OK" and [r["ok"] for r in res] == [True, True]
    assert [r["overlay_files"] for r in res] == [1, 1]
    rc, res, _ = _run(tmp_path / "without", repo, rows[:1])
    assert rc == 1 and res[0]["ok"] is False
    (ov / "test_toy.py").write_text(PASSING)
    with pytest.raises(SystemExit, match="tracked"):
        _run(tmp_path / "tracked", repo, rows[:1], "--overlay", str(ov))
    assert _git(repo, "status", "--porcelain") == ""                         # nothing overwritten, nothing left
    with pytest.raises(SystemExit, match="overlay"):
        _run(tmp_path / "absent", repo, rows[:1], "--overlay", str(tmp_path / "no_such_dir"))
