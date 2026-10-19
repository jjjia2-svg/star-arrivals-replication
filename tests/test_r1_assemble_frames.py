# -*- coding: utf-8 -*-
"""R1 F3 part 5 / F29: pipeline/frames/cal2026-10/assemble_frames.py takes every source explicitly,
so J0 (the October directories) and J1a (the M stage directories) run the same code, and checks the
economics pairs table against a pin before anything is staged.

Toy trees only: the module's REPO is pointed at tmp_path/'repo' (the cwd, as J0 runs it with
cwd=REPO), so the base carry-over data/frames/p3_afar_speed_bracket.csv and the pairs staging
directory output/cal_intermediates/ are toy paths too. Nothing in the checkout is written.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
LAYER = REPO / "pipeline" / "frames" / "cal2026-10"
OCTOBER_ASSEMBLY = REPO / "data" / "cal2026-10" / "frames" / "assembly_2026-10.json"
FIELDS = ("econ", "chemistry", "math_stats")
REQUIRED = ("--econ-dir", "--econ-p1-dir", "--chem-dir", "--math-dir", "--afar-dir", "--variants-dir",
            "--pairs-econ", "--pairs-pin", "--out")
SOURCES = {
    "src/econ": ["p2_becoming_econ.csv", "p3_slim_econ.parquet", "p3_slim_ev_econ.parquet",
                 "p1_events_ledger_econ.csv", "relationships_econ.csv"],
    "src/econ_p1": ["p1_frame_econ.csv", "p1_frame_econ_old79.csv", "p1_frame_econ_new37.csv"],
    "src/chem": [f"{k}_chemistry.{x}" for k, x in (("p1_frame", "csv"), ("p2_becoming", "csv"), ("p3_slim", "parquet"),
                                                   ("p3_slim_ev", "parquet"), ("pairs_none", "parquet"))],
    "src/math": [f"{k}_math_stats.{x}" for k, x in (("p1_frame", "csv"), ("p2_becoming", "csv"), ("p3_slim", "parquet"),
                                                    ("p3_slim_ev", "parquet"), ("pairs_none", "parquet"))],
    "src/afar": [n for f in FIELDS for n in (f"p3_afar_{f}.parquet", f"p3_afar_pos_{f}.parquet", f"p3_afar_med_{f}.parquet")]
                + ["p3_afar_counts.csv", "p3_afar_counts_by_spec.csv", "p3_afar_tau_profile.csv"],
    "src/variants": [n for f in FIELDS for n in (f"p3_slim_{f}_p05.parquet", f"p3_slim_{f}_dosebin3.parquet")],
    "data/frames": ["p3_afar_speed_bracket.csv"],
}
VARIANTS = SOURCES["src/variants"]
PAIRS = "pairs/pairs_unified.csv"
PIN_REPORT = "pin/build_report.json"


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def toy(tmp_path, monkeypatch):
    """(module, repo) — a fresh assemble_frames whose REPO is a toy repo holding every source."""
    repo = (tmp_path / "repo").resolve()
    for d, names in SOURCES.items():
        (repo / d).mkdir(parents=True)
        for n in names:
            (repo / d / n).write_bytes(f"{d}/{n}\n".encode())
    # src/econ carries its own MANIFEST (October's frames_econ did): its files report source_manifest OK
    (repo / "src/econ/MANIFEST.sha256").write_text(
        "".join(f"{sha(repo / 'src/econ' / n)}  data/cal2026-10/frames_econ/{n}\n" for n in SOURCES["src/econ"]),
        encoding="utf-8")
    (repo / "pairs").mkdir()
    (repo / PAIRS).write_bytes(b"pid_a,pid_b,event\nA1,A2,S:2010\n")
    _pin(repo, sha(repo / PAIRS), (repo / PAIRS).stat().st_size)
    spec = importlib.util.spec_from_file_location("_assemble_frames_r1", LAYER / "assemble_frames.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                                          # type: ignore[union-attr]
    monkeypatch.setattr(mod, "REPO", repo)
    monkeypatch.chdir(repo)
    return mod, repo


def _pin(repo: pathlib.Path, sha256: str, size: int) -> None:
    (repo / "pin").mkdir(exist_ok=True)
    (repo / PIN_REPORT).write_text(json.dumps({"october": {"pairs_unified": {
        "path": "output/cal_intermediates/cal2026-10/pairs_unified.csv", "sha256": sha256, "bytes": size,
        "note": "toy"}}}, indent=1) + "\n", encoding="utf-8")


def _argv(out="out/frames", **drop) -> list[str]:
    vals = {"--econ-dir": "src/econ", "--econ-p1-dir": "src/econ_p1", "--chem-dir": "src/chem",
            "--math-dir": "src/math", "--afar-dir": "src/afar", "--variants-dir": "src/variants",
            "--pairs-econ": PAIRS, "--pairs-pin": f"{PIN_REPORT}#october.pairs_unified", "--out": out}
    argv = []
    for k, v in vals.items():
        if k not in drop.get("without", ()):
            argv += [k, v]
    return argv


def _nothing_written(repo: pathlib.Path) -> None:
    assert not (repo / "out").exists(), "frames were written"
    assert not (repo / "output").exists(), "the pairs table was staged"


def test_every_flag_is_required(toy, capsys):
    af, repo = toy
    for flag in REQUIRED:
        with pytest.raises(SystemExit) as e:
            af.main(_argv(without=(flag,)) + ["--execute"])
        assert e.value.code == 2, flag
        err = capsys.readouterr().err
        assert "required" in err and flag in err, (flag, err)
    _nothing_written(repo)


def test_a_malformed_pin_is_a_usage_error(toy, capsys):
    af, repo = toy
    argv = _argv(without=("--pairs-pin",)) + ["--pairs-pin", PIN_REPORT, "--execute"]
    with pytest.raises(SystemExit) as e:
        af.main(argv)
    assert e.value.code == 2 and "REPORT#KEY" in capsys.readouterr().err
    _nothing_written(repo)


@pytest.mark.parametrize("bad", ["sha256", "bytes", "key"])
def test_a_pin_mismatch_stops_before_anything_is_staged(toy, capsys, bad):
    af, repo = toy
    good_sha, good_size = sha(repo / PAIRS), (repo / PAIRS).stat().st_size
    if bad == "sha256":
        _pin(repo, "0" * 64, good_size)
    elif bad == "bytes":
        _pin(repo, good_sha, good_size + 1)
    argv = _argv() + ["--execute"]
    if bad == "key":
        argv[argv.index("--pairs-pin") + 1] = f"{PIN_REPORT}#october.no_such_key"
    assert af.main(argv) == 1
    assert "PAIRS_PIN_MISMATCH" in capsys.readouterr().out
    _nothing_written(repo)
    assert af.main(argv[:-1]) == 1, "the dry run must stop on the pin too"


def test_a_missing_pairs_table_is_a_pin_mismatch(toy, capsys):
    af, repo = toy
    (repo / PAIRS).unlink()
    assert af.main(_argv() + ["--execute"]) == 1
    assert "PAIRS_PIN_MISMATCH" in capsys.readouterr().out
    _nothing_written(repo)


def test_toy_dirs_are_assembled_with_a_manifest_and_the_sources_as_passed(toy):
    af, repo = toy
    assert af.main(_argv() + ["--execute"]) == 0
    out = repo / "out" / "frames"
    names = [n for ns in SOURCES.values() for n in ns]
    assert len(names) == 37
    for d, ns in SOURCES.items():
        for n in ns:
            assert (out / n).read_bytes() == (repo / d / n).read_bytes(), n
    rep = json.loads((out / "assembly_2026-10.json").read_text(encoding="utf-8"))
    october = json.loads(OCTOBER_ASSEMBLY.read_text(encoding="utf-8"))
    assert list(rep) == list(october), "assembly record keys differ from October's"
    assert set(rep["files"]) == set(october["files"]) == set(names)
    for d, ns in SOURCES.items():
        for n in ns:
            r = rep["files"][n]
            assert list(r) == list(october["files"][n])
            assert r["source"] == f"{d}/{n}" and r["sha256"] == sha(repo / d / n)
            assert r["source_manifest"] == ("OK" if d == "src/econ" else "not_in_source_manifest"), n
    assert rep["missing"] == [] and rep["manifest_mismatch"] == []
    # the pairs table: staged, recorded exactly as passed (relative), not shipped
    assert rep["pairs_unified_econ"] == {"source": PAIRS, "sha256": sha(repo / PAIRS),
                                         "staged_to": "output/cal_intermediates/pairs_unified.csv", "shipped": False}
    assert list(rep["pairs_unified_econ"]) == list(october["pairs_unified_econ"])
    assert (repo / "output/cal_intermediates/pairs_unified.csv").read_bytes() == (repo / PAIRS).read_bytes()
    # MANIFEST over the assembled directory, repo-relative as October's data/cal2026-10/frames/MANIFEST.sha256
    files = sorted(p for p in out.iterdir() if p.is_file() and p.name != "MANIFEST.sha256")
    assert len(files) == 38
    assert (out / "MANIFEST.sha256").read_text(encoding="utf-8") == "".join(
        f"{sha(p)}  out/frames/{p.name}\n" for p in files)


def test_an_out_dir_outside_the_repo_gets_a_manifest_relative_to_itself(toy, tmp_path):
    af, repo = toy
    stage_out = tmp_path / "stage_out"
    assert af.main(_argv(out=str(stage_out)) + ["--execute"]) == 0
    files = sorted(p for p in stage_out.iterdir() if p.is_file() and p.name != "MANIFEST.sha256")
    assert len(files) == 38
    assert (stage_out / "MANIFEST.sha256").read_text(encoding="utf-8") == "".join(
        f"{sha(p)}  {p.name}\n" for p in files)


def test_allow_missing_covers_absent_variant_slims_and_nothing_else(toy, capsys):
    af, repo = toy
    for n in VARIANTS:
        (repo / "src/variants" / n).unlink()
    assert af.main(_argv() + ["--execute"]) == 1          # absent and not allowed: STOP, nothing written
    assert "STOP" in capsys.readouterr().out
    _nothing_written(repo)
    assert af.main(_argv() + ["--allow-missing", *VARIANTS, "--execute"]) == 0
    out = repo / "out" / "frames"
    rep = json.loads((out / "assembly_2026-10.json").read_text(encoding="utf-8"))
    assert sorted(m["name"] for m in rep["missing"]) == sorted(VARIANTS)
    assert all(m["source"] == f"src/variants/{m['name']}" for m in rep["missing"])
    assert not any((out / n).exists() for n in VARIANTS)
    assert len([p for p in out.iterdir() if p.name not in ("MANIFEST.sha256", "assembly_2026-10.json")]) == 37 - 6


def test_the_dry_run_writes_nothing(toy, capsys):
    af, repo = toy
    assert af.main(_argv()) == 0
    assert json.loads(capsys.readouterr().out)["would_assemble"] == 37
    _nothing_written(repo)


def test_readmes_show_the_required_flags():
    readme = (LAYER / "README.md").read_text(encoding="utf-8").splitlines()
    assemble = [ln for ln in readme if "assemble_frames.py" in ln and all(f in ln for f in REQUIRED)]
    assert assemble, "no README usage line for assemble_frames.py shows every required flag"
    assert any("run_econ920.py" in ln and "--controls-report" in ln for ln in readme), \
        "no README usage line for run_econ920.py shows --controls-report"
    doc = (LAYER / "assemble_frames.py").read_text(encoding="utf-8").split('"""', 2)[1]
    assert all(f in doc for f in REQUIRED), [f for f in REQUIRED if f not in doc]
    doc = (LAYER / "econ920" / "run_econ920.py").read_text(encoding="utf-8").split('"""', 2)[1]
    assert "--controls-report" in doc
