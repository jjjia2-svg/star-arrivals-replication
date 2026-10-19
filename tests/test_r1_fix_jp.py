# -*- coding: utf-8 -*-
"""FIX-JP: one test per finding of the 2026-10-15 code review of the JP path (the review is not
shipped). Finding 1's table test is
tests/test_r1_cells.py::test_oct29_rcloud_rows_equal_the_october_serial_commands; the gold-side half is here.

Toy data only: a fake R (python) in tmp_path, the fin() function of the rendered boot template run under bash
with a fake `aws` and with every /work path moved into tmp_path, and the committed tables read as text.
No R runs, no AWS call is made, no data disk is opened.
"""
from __future__ import annotations

import ast
import csv
import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for _p in (REPO / "pipeline" / "aws" / "r1",):
    sys.path.insert(0, str(_p))
import r1kit                 # noqa: E402
import run_cells as rc       # noqa: E402

CELLS = REPO / "config" / "r1" / "cells" / "oct29.tsv"
JP = REPO / "config" / "r1" / "stages" / "jp.json"
ENV = {"SAR_S3_BUCKET": "fake-bucket", "AWS_REGION": "us-east-1"}
ACCOUNT = re.compile(r"(?<!\d)\d{12}(?!\d)")


# ---- finding 1: a ref only where the gold was made with one ------------------------------------------
def test_f1_a_ref_is_passed_only_where_the_gold_carries_point_estimate_check():
    """The evcl drivers add point_estimate_check exactly when they get a reference JSON. The 7 rmac evcl golds
    carry it (their October run passed the ref); the 2 rcloud evcl golds do not (October's cloud run passed none)."""
    with open(CELLS, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    assert len(rows) == 29
    for r in rows:
        gold = json.loads((REPO / "analysis" / "expected" / r["out_name"]).read_text(encoding="utf-8"))
        assert ("point_estimate_check" in gold) == (r["ref"] != "-"), (r["label"], r["ref"])


# ---- finding 2: resume fingerprints cover the comparison ---------------------------------------------
def _repo_imports(rel: str) -> set:
    """Repo files a Python file loads through analysis.* / pipeline.* imports, transitively (package __init__ too)."""
    seen, todo = set(), [rel]
    while todo:
        tree = ast.parse((REPO / todo.pop()).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            for m in mods:
                parts = m.split(".")
                if parts[0] not in ("analysis", "pipeline"):
                    continue
                for i in range(1, len(parts) + 1):
                    for cand in ("/".join(parts[:i]) + ".py", "/".join(parts[:i]) + "/__init__.py"):
                        if (REPO / cand).is_file() and cand not in seen:
                            seen.add(cand)
                            todo.append(cand)
    return seen


def _tracked(path: str) -> bool:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "--", path], capture_output=True, text=True, check=True)
    return bool(out.stdout.strip())


def test_f2_jp_fingerprints_cover_the_comparison_code_the_golds_and_the_py_layer():
    """A resumed JP must not reuse an EQUAL/DIFF verdict after compare_json (or anything it imports), the gold tree
    or the py layer changed: those are inputs of both cell stages and of the compare stage."""
    stages = {s["name"]: s for s in json.loads(JP.read_text(encoding="utf-8"))["stages"]}
    cells_code = _repo_imports("pipeline/aws/r1/run_cells.py")
    assert "analysis/lib/compare_json.py" in cells_code
    for name in ("cells_rmac", "cells_rcloud"):
        want = {f"repo:{p}" for p in cells_code} | {"repo:analysis/expected", "env:py"}
        assert want <= set(stages[name]["inputs"]), (name, sorted(want - set(stages[name]["inputs"])))
    compare_code = (_repo_imports("tools/compare_all.py") | _repo_imports("tools/verify_cloud_custody.py")
                    | {"tools/compare_all.py", "tools/verify_cloud_custody.py"})
    assert {"analysis/lib/compare_json.py", "analysis/lib/paths.py"} <= compare_code
    jp_job = json.loads((REPO / "config" / "r1" / "jobs" / "jp.json").read_text(encoding="utf-8"))
    paths_cfg = jp_job["env"]["SAR_PATHS_CONFIG"].replace("$REPO_DIR/", "")
    want = ({f"repo:{p}" for p in compare_code}
            | {"repo:analysis/expected", "repo:data/cal2026-10/cloud", f"repo:{paths_cfg}", "env:py"})
    assert want <= set(stages["compare"]["inputs"]), sorted(want - set(stages["compare"]["inputs"]))
    for s in stages.values():                         # every repo input resolves at the commit (else StageError)
        for tok in s["inputs"]:
            if tok.startswith("repo:"):
                assert _tracked(tok[5:]), (s["name"], tok)


# ---- findings 3 and 7: run_cells ----------------------------------------------------------------------
THREAD_VARS = ("POLARS_MAX_THREADS", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "R_DATATABLE_NUM_THREADS")
FAKE_R = r'''#!/usr/bin/env python3
import json, os, sys
label = sys.argv[2]
log = os.environ.get("FAKE_ENV_LOG")
if log:
    open(log, "a").write(json.dumps({k: os.environ.get(k) for k in %r}) + "\n")
body = {"label": label, "ate": 1.0}
body.update(json.loads(os.environ.get("FAKE_BODY_" + label, "{}")))
json.dump(body, open(os.path.join(os.environ["SAR_OUT"], label + ".json"), "w"))
''' % (THREAD_VARS,)
BODIES = {"TOPFAIL": {"status": "FAILED"},
          "NESTFAIL": {"status": "OK", "pair_cluster": {"status": "OK"}, "event_cluster": {"status": "FAILED_event"}},
          "UNIONFAIL": {"channels": {"dept_only": {"status": "OK"}, "union": {"status": "FAILED_pair"}}}}


@pytest.fixture
def toy_cells(tmp_path, monkeypatch):
    rbin = tmp_path / "R" / "bin"
    rbin.mkdir(parents=True)
    (rbin / "fakeR").write_text(FAKE_R.replace("#!/usr/bin/env python3", "#!" + sys.executable, 1))
    (rbin / "fakeR").chmod(0o755)
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    monkeypatch.setenv("SAR_RSCRIPT_RMAC", str(rbin / "fakeR"))
    monkeypatch.setenv("SAR_RLIB_RMAC", str(tmp_path / "lib"))
    for k in THREAD_VARS:
        monkeypatch.delenv(k, raising=False)
    gold = tmp_path / "gold"
    gold.mkdir()
    lines = ["label\tdriver\tframe\tref\tout_name\tstack"]
    for lab in ("OKCELL", *BODIES):
        monkeypatch.setenv(f"FAKE_BODY_{lab}", json.dumps(BODIES.get(lab, {})))
        # the gold equals what the cell writes, so the old runner would have called every failed cell EQUAL
        (gold / f"{lab}.json").write_text(json.dumps({"label": lab, "ate": 1.0, **BODIES.get(lab, {})}))
        lines.append(f"{lab}\tanalysis/estimation/run_p1.R\tf.csv\t-\t{lab}.json\trmac")
    tsv = tmp_path / "cells.tsv"
    tsv.write_text("\n".join(lines) + "\n")
    return tmp_path, gold, tsv


def _run(tmp_path, gold, tsv, *extra):
    return rc.main(["--cells", str(tsv), "--stack", "rmac", "--repo", str(REPO), "--frames", str(tmp_path / "frames"),
                    "--gold-dir", str(gold), "--out", str(tmp_path / "out"), *extra])


@pytest.mark.parametrize("compare", [True, False])
def test_f3_a_failed_estimate_inside_the_driver_fails_the_cell_stage(toy_cells, compare):
    """The drivers catch estimator errors, write status FAILED / FAILED_* and exit 0. Such a cell must fail the
    stage (nonzero, so run_stages writes no done marker), never become a reusable DIFF or EQUAL."""
    tmp_path, gold, tsv = toy_cells
    assert _run(tmp_path, gold, tsv, *(["--compare"] if compare else [])) == 1
    rep = json.loads((tmp_path / "out" / "cells_report_rmac.json").read_text())
    assert rep["OKCELL"]["status"] == ("EQUAL" if compare else "RAN")
    for lab, where in (("TOPFAIL", "status"), ("NESTFAIL", "event_cluster"), ("UNIONFAIL", "union")):
        assert rep[lab]["status"] == "FAIL", lab
        assert any(where in s and "FAILED" in s for s in rep[lab]["estimate_failed"]), rep[lab]
        assert not (tmp_path / "out" / "estimates" / f"{lab}.json").exists(), lab     # never published as a result
        assert (tmp_path / "out" / "failed" / f"{lab}.json").is_file(), lab           # kept for diagnosis
    assert (tmp_path / "out" / "estimates" / "OKCELL.json").is_file()


def test_f7_run_cells_caps_polars_threads(toy_cells, monkeypatch):
    """--threads must cap Polars too (every estimator loads it), alongside the data.table/OpenMP/OpenBLAS limits."""
    tmp_path, gold, tsv = toy_cells
    log = tmp_path / "env.log"
    monkeypatch.setenv("FAKE_ENV_LOG", str(log))
    tsv.write_text("\n".join(tsv.read_text().splitlines()[:2]) + "\n")          # the OKCELL row only
    assert _run(tmp_path, gold, tsv, "--threads", "3", "--compare") == 0
    seen = [json.loads(ln) for ln in log.read_text().splitlines()]
    assert seen and all(e == {k: "3" for k in THREAD_VARS} for e in seen), seen


# ---- findings 4 and 5: the boot template's fin() -------------------------------------------------------
FAKE_AWS = """#!/bin/sh
echo "$*" >> "$FAKE_AWS_LOG"
if [ -n "$FAKE_AWS_FAIL" ]; then
  case "$*" in *"$FAKE_AWS_FAIL"*) echo "upload failed: s3://fake-bucket/r1/x arn:aws:iam::123456789012:role/r1" >&2; exit 1;; esac
fi
exit 0
"""
BOOT_LOG = ("+ B=s3://fake-bucket\n"
            "+ aws s3 cp --only-show-errors /tmp/sar-st s3://fake-bucket/r1/runs/t-unit-77/status.txt\n"
            "An error occurred (AccessDenied): User arn:aws:iam::123456789012:role/sar-r1 in account 123456789012 "
            "may not write s3://fake-bucket.backup/x\n"
            "+ st RUN\n")


def _fin(tmp_path: pathlib.Path, *, fail: str = "", fail_tar: bool = False) -> dict:
    """Run the rendered template's fin() under bash with /work and the boot log moved into tmp_path."""
    job = r1kit.load_job("test")
    text = r1kit.render_userdata(job, job_id="t-unit-77", commit="c" * 40, repo_dir="/srv/r", bucket="fake-bucket",
                                 base_sha="a" * 64, deadline_epoch=1_800_000_000)
    m = re.search(r"^fin\(\) \{\n.*?^\}$", text, re.M | re.S)
    assert m, "fin() not found in the rendered boot script"
    T = tmp_path / "box"
    (T / "work" / "out").mkdir(parents=True)
    (T / "work" / "out" / "RESULT.txt").write_text("OK all stages\n")
    (T / "boot.log").write_text(BOOT_LOG)
    fin = m.group(0).replace("/var/log/sar-r1-boot.log", f"{T}/boot.log").replace("/work", f"{T}/work")
    bindir = T / "bin"
    bindir.mkdir()
    (bindir / "aws").write_text(FAKE_AWS)
    (bindir / "aws").chmod(0o755)
    if fail_tar:
        (bindir / "tar").write_text("#!/bin/sh\nexit 2\n")
        (bindir / "tar").chmod(0o755)
    script = T / "driver.sh"
    script.write_text("\n".join([
        "#!/bin/bash",
        'B="s3://fake-bucket"', 'JOB="t-unit-77"', 'P="$B/r1/runs/$JOB"',
        f'export PATH="{bindir}:$PATH"',
        f'st() {{ echo "$*" >> "{T}/status.txt"; }}',
        f'shutdown() {{ echo "shutdown $*" >> "{T}/shutdown.txt"; }}',
        fin,
        "trap fin EXIT",
        "exit 0", ""]))
    env = dict(os.environ, FAKE_AWS_LOG=str(T / "aws.log"), FAKE_AWS_FAIL=fail)
    subprocess.run(["bash", str(script)], cwd=T, env=env, capture_output=True, text=True, timeout=120)
    read = lambda n: (T / n).read_text() if (T / n).is_file() else ""   # noqa: E731
    return {"status": read("status.txt"), "shutdown": read("shutdown.txt"), "aws": read("aws.log"),
            "boot": read("work/out/boot.log")}


def test_f4_fin_reports_upload_fail_unless_every_transfer_succeeded(tmp_path):
    ok = _fin(tmp_path / "ok")
    assert ok["status"].startswith("DONE rc=0 OK all stages"), ok
    assert ok["aws"].count("s3 cp") == 2 and "s3 sync" in ok["aws"] and ok["shutdown"].strip() == "shutdown -h now"
    for case, kw in (("sync", {"fail": "s3 sync"}), ("tarball", {"fail": "out.tar.gz"}),
                     ("hash", {"fail": "out.sha256"}), ("tar", {"fail_tar": True})):
        r = _fin(tmp_path / case, **kw)
        assert r["status"].startswith("UPLOAD_FAIL rc=0"), (case, r)
        assert "DONE" not in r["status"], (case, r)
        assert r["shutdown"].strip() == "shutdown -h now", (case, r)          # the power-off stays unconditional


def test_f5_the_uploaded_boot_log_carries_no_bucket_and_no_account_id(tmp_path):
    r = _fin(tmp_path)
    assert r["boot"], "fin() must still copy the boot log into the result"
    assert "fake-bucket" not in r["boot"], r["boot"]
    assert not ACCOUNT.search(r["boot"]), r["boot"]
    assert "AccessDenied" in r["boot"] and "st RUN" in r["boot"]                # sanitised, not dropped


# ---- finding 6: the watch CLI ---------------------------------------------------------------------------
def test_f6_the_watch_cli_redacts_the_status_it_returns(monkeypatch, capsys):
    """watch() redacts what it prints while polling, but main() printed its raw return value."""
    def fake_watch(job, **kw):
        r1kit.use_env(ENV)
        return ("2027-01-15T08:30:00Z DONE rc=1 STAGE_FAIL push failed s3://fake-bucket/r1/runs/x "
                "arn:aws:iam::123456789012:role/r1 account 123456789012")
    monkeypatch.setattr(r1kit, "watch", fake_watch)
    assert r1kit.main(["watch", "t-unit-40"]) == 0
    out = capsys.readouterr().out
    assert "DONE rc=1 STAGE_FAIL" in out
    assert "fake-bucket" not in out and not ACCOUNT.search(out), out


def test_boot_gives_the_step_user_an_empty_zshrc():
    """j0-01 died in run_econ920 c1b: a ported October script opens ~/.zshrc (optional API key) and
    /home/ubuntu/.zshrc did not exist. The boot script must create it empty, before the steps run."""
    tmpl = (REPO / "pipeline" / "aws" / "r1" / "userdata.sh.tmpl").read_text()
    make = "install -m 600 -o ubuntu -g ubuntu /dev/null /home/ubuntu/.zshrc"
    assert make in tmpl
    assert tmpl.index(make) < tmpl.index("runuser -u ubuntu -- bash /work/steps.sh")
    assert "OPENALEX_API_KEY" not in tmpl
