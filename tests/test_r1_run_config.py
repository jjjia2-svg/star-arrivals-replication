# -*- coding: utf-8 -*-
"""pipeline/aws/r1/run_config.py (F23): one step of a run config's chain, inside the F2 sandbox.

Toy chains run in tmp_path against the real config/r1/B0.json (the loader reads a config against the
repository it is committed in); nothing here opens the data disk, runs R or calls AWS."""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import run_config as rc     # noqa: E402
import run_stages as rs     # noqa: E402

B0 = REPO / "config" / "r1" / "B0.json"
CHAIN = REPO / "config" / "r1" / "chain.json"
PLACEHOLDER = re.compile(r"\{[a-z]+(?::[^{}]*)?\}")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture
def box(tmp_path, monkeypatch):
    """An R1-instance-like environment: host set, a stand-in Mac R stack, a toy repo carrying the marker."""
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    rbin = tmp_path / "rstack" / "bin"
    rbin.mkdir(parents=True)
    (rbin / "R_entry").write_text("#!/bin/sh\nexit 0\n")
    monkeypatch.setenv("SAR_RSCRIPT_RMAC", str(rbin / "R_entry"))
    monkeypatch.setenv("SAR_RLIB_RMAC", str(tmp_path / "rstack" / "lib"))
    monkeypatch.setenv("PYTHONHASHSEED", "5")                 # the step must see 0, whatever the caller had
    repo = tmp_path / "toy repo"
    repo.mkdir()
    (repo / ".r1_sandbox.json").write_text(json.dumps({"config": "B0", "commit": "c" * 40,
                                                       "ref": str(tmp_path / "ref"), "tsv_sha256": "0" * 64}))
    work = tmp_path / "work"
    work.mkdir()
    return {"tmp": tmp_path, "repo": repo, "work": work, "rbin": rbin}


def _chain(box, steps, name="chain.json"):
    p = box["tmp"] / name
    p.write_text(json.dumps({"schema": "sar.r1.chain.v1", "b0_chain_paths": [], "steps": steps}))
    return p


def _run(box, chain, step, out=None, *extra, config=B0):
    out = out or box["work"] / "prod" / step
    return rc.main(["--config", str(config), "--chain", str(chain), "--step", step, "--repo", str(box["repo"]),
                    "--work", str(box["work"]), "--out", str(out), *extra])


TOY = {"name": "toy", "configs": ["B0"], "env": {"TOY_GREETING": "hi"},
       "argv": [["{py}", "-c", "import os, pathlib; pathlib.Path('data').mkdir(exist_ok=True); "
                               "pathlib.Path('data/a.txt').write_text(os.environ['TOY_GREETING'] + '\\n')"],
                ["bash", "-c", "mkdir -p data/d && echo two > data/d/b.txt && echo '{cfg:stage.restake_csv}' > {out}/cfg.txt"]],
       "writes": ["data/a.txt", "data/d"]}


def test_step_renders_argv_runs_and_writes_step_report(box):
    chain = _chain(box, [TOY])
    assert _run(box, chain, "toy") == 0
    repo, out = box["repo"], box["work"] / "prod" / "toy"
    assert (repo / "data" / "a.txt").read_text() == "hi\n"                    # step env reached the program, cwd = repo
    # a {cfg:SECTION.KEY} placeholder is the run config's resolved value (B0 stage section = October's restake table)
    assert (out / "cfg.txt").read_text() == str(REPO / "data/cal2026-08-28/restake_2026-08-28.csv") + "\n"
    rep = json.loads((out / "step_report.json").read_text())
    assert rep["step"] == "toy" and rep["rc"] == 0 and rep["config"] == "B0"
    assert isinstance(rep["secs"], (int, float)) and rep["invocations"] == 2
    assert rep["config_sha256"] == _sha(B0.read_bytes())
    assert rep["writes"] == {"data/a.txt": _sha(b"hi\n"), "data/d": rs.digest_of(repo / "data" / "d")}


def test_a_failing_invocation_stops_the_step_and_a_missing_write_fails_it(box):
    fail = {"name": "toy_fail", "argv": [["bash", "-c", "exit 7"], ["bash", "-c", "touch {out}/never"]],
            "writes": ["data/x.txt"]}
    nowrite = {"name": "toy_nowrite", "argv": [["true"]], "writes": ["data/nothing.txt"]}
    chain = _chain(box, [fail, nowrite])
    assert _run(box, chain, "toy_fail") == 7
    out = box["work"] / "prod" / "toy_fail"
    assert not (out / "never").exists()
    assert json.loads((out / "step_report.json").read_text())["rc"] == 7
    assert _run(box, chain, "toy_nowrite") == 1
    rep = json.loads((box["work"] / "prod" / "toy_nowrite" / "step_report.json").read_text())
    assert rep["writes"] == {"data/nothing.txt": None} and rep["missing"] == ["data/nothing.txt"]


def test_missing_config_key_or_unknown_step_stops(box):
    steps = [{"name": "nokey", "argv": [["touch", "{out}/ran_{cfg:stage.no_such_key}"]], "writes": []},
             {"name": "for_m", "configs": ["M"], "argv": [["touch", "{out}/ran"]], "writes": []},
             {"name": "odd", "argv": [["touch", "{out}/ran_{bogus}"]], "writes": []}]
    chain = _chain(box, steps)
    with pytest.raises(SystemExit, match="MISSING_KEY"):
        _run(box, chain, "nokey")
    with pytest.raises(SystemExit, match="UNKNOWN_STEP"):
        _run(box, chain, "no_such_step")
    with pytest.raises(SystemExit, match="NOT_FOR_CONFIG"):
        _run(box, chain, "for_m")
    with pytest.raises(SystemExit, match="PLACEHOLDER"):
        _run(box, chain, "odd")
    prod = box["work"] / "prod"
    assert not prod.exists() or not list(prod.rglob("ran*"))               # nothing ran before the STOP
    for bad in ({"name": "up", "argv": [["true"]], "writes": ["../outside.txt"]},
                {"name": "abs", "argv": [["true"]], "writes": ["/etc/x"]},
                {"name": "envclash", "env": {"SAR_OUT_ROOT": "/tmp/x"}, "argv": [["true"]], "writes": []},
                {"name": "typo", "argv": [["true"]], "writes": [], "wirtes": []}):
        with pytest.raises(SystemExit, match="BAD_CHAIN"):
            _run(box, _chain(box, [bad], f"bad_{bad['name']}.json"), bad["name"])


def test_refuses_without_sandbox_marker_and_off_aws(box, monkeypatch):
    chain = _chain(box, [{"name": "s", "argv": [["touch", "{out}/ran"]], "writes": []}])
    marker = box["repo"] / ".r1_sandbox.json"
    keep = marker.read_text()
    marker.unlink()
    with pytest.raises(SystemExit, match="SANDBOX"):
        _run(box, chain, "s")
    marker.write_text(json.dumps({**json.loads(keep), "config": "M"}))      # a clone purged for another config
    with pytest.raises(SystemExit, match="SANDBOX"):
        _run(box, chain, "s")
    marker.write_text(keep)
    monkeypatch.delenv("SAR_RSCRIPT_RMAC")
    with pytest.raises(SystemExit, match="NO_RMAC"):
        _run(box, chain, "s")
    monkeypatch.delenv("SAR_HOST")
    with pytest.raises(SystemExit, match="R1 instance"):
        _run(box, chain, "s")
    assert not (box["work"] / "prod" / "s" / "ran").exists()


def test_rmac_rscript_is_first_on_path_and_sar_out_root_is_fresh(box):
    probe = {"name": "probe", "argv": [["bash", "-c",
             'echo "$PATH" > {out}/path.txt; echo "$SAR_OUT_ROOT" > {out}/root.txt; ls -A "$SAR_OUT_ROOT" > {out}/ls.txt; '
             'touch "$SAR_OUT_ROOT/left_behind"; echo "$SAR_R1_CONFIG" > {out}/cfg.txt; '
             'echo "$PYTHONHASHSEED" > {out}/seed.txt; echo "$R_LIBS" > {out}/rlibs.txt']], "writes": []}
    chain = _chain(box, [probe])
    w = box["work"]
    for out in (w / "a", w / "b"):                    # the second run must not see the first run's leftovers
        assert _run(box, chain, "probe", out) == 0
        assert (out / "path.txt").read_text().split(":")[0] == str(box["rbin"])
        root = pathlib.Path((out / "root.txt").read_text().strip())
        assert root.is_relative_to(w / "tmp" / "probe") and root.is_absolute()
        assert (out / "ls.txt").read_text() == ""
        assert (out / "cfg.txt").read_text().strip() == str(B0.resolve())
        assert (out / "seed.txt").read_text().strip() == "0"
        assert (out / "rlibs.txt").read_text().strip() == str(box["tmp"] / "rstack" / "lib")


def test_a_step_reads_only_the_config_name_unless_an_argument_needs_a_value(box):
    """Inside the sandbox B0.json's `inputs` (October's event tables, the aug restake table) are absent until
    restake/write_events rebuild them, so the full loader would STOP MISSING_INPUT on a correct clone: a step
    reads the config's name and sha256 only, and loads it fully only for a {cfg:...} argument."""
    cfgdir = box["tmp"] / "purged clone" / "config" / "r1"
    cfgdir.mkdir(parents=True)
    raw = json.loads(B0.read_text(encoding="utf-8"))
    raw["inputs"] = ["repo:data/cal2026-10/events_econ_cal2026-10.csv"]          # purged: the full load would STOP
    cfg = cfgdir / "B0.json"
    cfg.write_text(json.dumps(raw))
    steps = [{"name": "plain", "argv": [["bash", "-c", "echo ran > {out}/ran.txt"]], "writes": []},
             {"name": "needs_value", "argv": [["bash", "-c", "echo '{cfg:stage.restake_csv}' > {out}/v.txt"]],
              "writes": []}]
    chain = _chain(box, steps)
    assert _run(box, chain, "plain", config=cfg) == 0
    rep = json.loads((box["work"] / "prod" / "plain" / "step_report.json").read_text())
    assert rep["config"] == "B0" and rep["config_sha256"] == _sha(cfg.read_bytes())
    with pytest.raises(SystemExit, match="BAD_CONFIG|CONFIG"):
        _run(box, chain, "needs_value", config=cfg)
    assert not (box["work"] / "prod" / "needs_value" / "v.txt").exists()
    bad = cfgdir / "not_a_config.json"
    bad.write_text(json.dumps({"schema": "something else", "config": "B0"}))
    with pytest.raises(SystemExit, match="BAD_CONFIG"):
        _run(box, chain, "plain", config=bad)


def test_scratch_reports_are_kept_with_the_stage_files(box):
    """A step's run / STOP reports in its SAR_OUT_ROOT reach STAGE_OUT/scratch_reports/ (pushed to S3), also when
    the step fails; data files and subdirectories stay behind."""
    make = ('echo \'{"stops": ["x"]}\' > "$SAR_OUT_ROOT/run_report.json"; mkdir -p "$SAR_OUT_ROOT/sub"; '
            'echo 1 > "$SAR_OUT_ROOT/sub/inner.json"; echo a,b > "$SAR_OUT_ROOT/big.csv"; exit 3')
    chain = _chain(box, [{"name": "fails", "argv": [["bash", "-c", make]], "writes": []}])
    assert _run(box, chain, "fails") == 3
    out = box["work"] / "prod" / "fails"
    assert sorted(p.name for p in (out / "scratch_reports").iterdir()) == ["run_report.json"]
    assert json.loads((out / "step_report.json").read_text())["scratch_reports"] == ["run_report.json"]


def test_copy_frames_post_copies_the_assembled_dir_with_its_manifest(box):
    make = ("mkdir -p data/fr && printf 'a,b\\n1,2\\n' > data/fr/x.csv && "
            "printf 'h  data/fr/x.csv\\n' > data/fr/MANIFEST.sha256")
    steps = [{"name": "frames", "argv": [["bash", "-c", make]], "writes": ["data/fr"], "post": "copy_frames",
              "frames_dir": "data/fr"},
             {"name": "frames_nomanifest", "argv": [["bash", "-c", "mkdir -p data/fq && echo 1 > data/fq/x.csv"]],
              "writes": ["data/fq"], "post": "copy_frames", "frames_dir": "data/fq"}]
    chain = _chain(box, steps)
    assert _run(box, chain, "frames") == 0
    dst = box["work"] / "prod" / "frames"
    for name in ("x.csv", "MANIFEST.sha256"):
        assert (dst / name).read_bytes() == (box["repo"] / "data" / "fr" / name).read_bytes()
    assert json.loads((dst / "step_report.json").read_text())["post"]["copied"] == 2
    with pytest.raises(SystemExit, match="NO_MANIFEST"):
        _run(box, chain, "frames_nomanifest")
    bad = dict(steps[0], name="frames_bad", frames_dir="data/elsewhere")      # frames_dir must be one of the writes
    with pytest.raises(SystemExit, match="BAD_CHAIN"):
        _run(box, _chain(box, [bad], "bad_frames.json"), "frames_bad")


def test_plan_runs_nothing(box, capsys):
    chain = _chain(box, [{"name": "s", "argv": [["touch", "{repo}/planned_only"]], "writes": []}])
    assert rc.main(["--plan", "--config", str(B0), "--chain", str(chain), "--repo", str(box["repo"]),
                    "--work", str(box["work"])]) == 0
    assert not (box["repo"] / "planned_only").exists()
    assert str(box["repo"] / "planned_only") in capsys.readouterr().out


def test_plan_renders_every_b0_step_with_no_placeholder_left(capsys, monkeypatch):
    monkeypatch.delenv("SAR_HOST", raising=False)                            # a plan runs nothing: no host needed
    assert rc.main(["--plan", "--config", str(B0), "--chain", str(CHAIN), "--repo", "/srv/sar repo",
                    "--work", "/work"]) == 0
    text = capsys.readouterr().out
    steps = [s["name"] for s in json.loads(CHAIN.read_text())["steps"]]
    for name in steps:
        assert f"## {name}" in text, name
    assert not PLACEHOLDER.search(text), PLACEHOLDER.search(text)
    # October's own values, as recorded (README run lines, the build reports, assembly_2026-10.json, the build log)
    for want in ("SAR_ECON_CONVENTION=aug", "SAR_ECON_ALL=1", "--override-gdose-gate",
                 "data/cal2026-10/patch_supplement_2026-10/works_by_author_supplement_2026-10.jsonl",
                 "--controls-report /work/prod/frames_econ920/controls_report_econ920.json",
                 "--october-ref /work/ref/october",
                 "/work/tmp/afar/afar_econ/relationships.csv",
                 "data/cal2026-10/frames_econ/build_report_econ920_2026-10.json#october.pairs_unified"):
        assert want in text, want
