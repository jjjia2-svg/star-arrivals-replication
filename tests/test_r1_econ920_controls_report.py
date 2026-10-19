# -*- coding: utf-8 -*-
"""R1 F5: pipeline/frames/cal2026-10/econ920/run_econ920.py writes its controls report ONLY to the
new file named by --controls-report, never to the October record
data/cal2026-10/controls_report_econ920_2026-09-23.json (MANIFEST-pinned).

Every phase is a fake and the data-disk entry point (econ920_lib's real_v2) is monkeypatched: in the
refusal tests it raises, so a refusal that came after the data disk would fail loudly; in the run
tests it returns a tmp_path dir. econ920_lib's CAL10 points at tmp_path/'cal10' as the positive
control: the old code wrote the controls report there whenever every control was CLEAR.

Assertions are on stderr text, not only on exit code 2: argparse also exits 2 on an unknown flag.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
LAYER = REPO / "pipeline" / "frames" / "cal2026-10" / "econ920"
OCTOBER_CONTROLS = REPO / "data" / "cal2026-10" / "controls_report_econ920_2026-09-23.json"
OCTOBER_ROOTS = (REPO / "data" / "cal2026-10", REPO / "data" / "frames", REPO / "analysis" / "expected")


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def ru(tmp_path, monkeypatch):
    """A fresh run_econ920 module (clean STOPS / REPORT) with every phase faked."""
    spec = importlib.util.spec_from_file_location("_run_econ920_f5", LAYER / "run_econ920.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                                          # type: ignore[union-attr]
    monkeypatch.setenv(mod.OUT_ROOT_ENV, str(tmp_path / "root"))
    mod.preconditions = lambda v2: {"stub": True}
    for phase in mod.CONTROLS:
        setattr(mod, f"control_{phase}", (lambda ph: lambda root, v2: mod.set_verdict(ph, True))(phase))
    mod.measure_gdose = lambda root, v2: None
    mod.october = lambda root, v2: None
    (tmp_path / "frames_econ").mkdir()
    mod.FRAMES_OUT = tmp_path / "frames_econ"
    (tmp_path / "cal10").mkdir()
    monkeypatch.setattr(mod.L, "CAL10", tmp_path / "cal10")

    def disk():
        raise AssertionError("reached the data disk")

    monkeypatch.setattr(mod.L, "real_v2", disk)
    return mod


@pytest.fixture
def disk_ok(ru, tmp_path, monkeypatch):
    (tmp_path / "v2").mkdir()
    monkeypatch.setattr(ru.L, "real_v2", lambda: tmp_path / "v2")
    return ru


def _refused(ru, argv, capsys) -> str:
    with pytest.raises(SystemExit) as e:
        ru.main(argv)
    assert e.value.code == 2
    return capsys.readouterr().err


def test_a_control_phase_without_controls_report_is_refused_before_the_data_disk(ru, tmp_path, capsys):
    err = _refused(ru, ["--execute", "--only", "c1a"], capsys)
    assert "--controls-report" in err and "required" in err
    assert not (tmp_path / "root").exists(), "SAR_OUT_ROOT was touched before the refusal"
    # the full default run (every phase) needs it too
    err = _refused(ru, ["--execute"], capsys)
    assert "--controls-report" in err and "required" in err


def test_controls_report_without_a_control_phase_is_a_usage_error(ru, tmp_path, capsys):
    target = tmp_path / "ctl.json"
    err = _refused(ru, ["--execute", "--only", "october", "--controls-report", str(target)], capsys)
    assert "no control phase" in err
    assert not target.exists() and not (tmp_path / "root").exists()


def test_an_existing_controls_report_is_refused_and_left_byte_equal(ru, tmp_path, capsys):
    ctl = tmp_path / "ctl.json"
    ctl.write_text('{"earlier": "run"}\n', encoding="utf-8")
    before = sha(ctl)
    err = _refused(ru, ["--execute", "--controls-report", str(ctl)], capsys)
    assert "refusing to overwrite" in err
    assert sha(ctl) == before
    assert not (tmp_path / "root").exists()


def test_a_path_inside_an_october_root_is_refused(ru, tmp_path, capsys):
    link = tmp_path / "link"
    link.symlink_to(REPO / "data" / "cal2026-10", target_is_directory=True)
    probes = [root / "f5_probe.json" for root in OCTOBER_ROOTS]
    probes += [REPO / "data" / "cal2026-10" / "frames_econ" / "f5_probe.json",   # below a root
               link / "f5_probe.json"]                                         # a root reached by a symlink
    for probe in probes:
        assert not probe.exists(), probe
        err = _refused(ru, ["--execute", "--controls-report", str(probe)], capsys)
        assert "October root" in err, (probe, err)
        assert not probe.exists(), probe
    assert not (tmp_path / "root").exists()


def test_a_missing_parent_directory_is_refused(ru, tmp_path, capsys):
    err = _refused(ru, ["--execute", "--controls-report", str(tmp_path / "no_such_dir" / "ctl.json")], capsys)
    assert "--controls-report" in err and "does not exist" in err


def test_a_fresh_path_is_written_once_and_the_october_path_is_untouched(disk_ok, tmp_path, capsys):
    ru = disk_ok
    (tmp_path / "out").mkdir()
    target = tmp_path / "out" / "ctl.json"
    argv = ["--execute", "--only", "c1a", "gdose", "c1b", "c2", "c3", "--controls-report", str(target)]
    assert ru.main(argv) == 0
    ctl = json.loads(target.read_text(encoding="utf-8"))
    assert {c: ctl["controls"][c]["verdict"] for c in ru.CONTROLS} == {c: "CLEAR" for c in ru.CONTROLS}
    assert ctl["preconditions"] == {"stub": True}
    assert set(ctl) <= set(json.loads(OCTOBER_CONTROLS.read_text(encoding="utf-8")))
    assert target.read_text(encoding="utf-8").endswith("}\n")
    assert list((tmp_path / "cal10").iterdir()) == [], "the old October target was written"
    capsys.readouterr()
    before = sha(target)
    err = _refused(ru, argv, capsys)
    assert "refusing to overwrite" in err
    assert sha(target) == before


def test_a_failed_control_writes_no_controls_report(disk_ok, tmp_path):
    ru = disk_ok
    ru.control_c1b = lambda root, v2: ru.set_verdict("c1b", False, "toy failure")
    (tmp_path / "out").mkdir()
    target = tmp_path / "out" / "ctl.json"
    assert ru.main(["--execute", "--only", "c1a", "c1b", "c2", "c3", "--controls-report", str(target)]) == 1
    assert not target.exists()
    assert list((tmp_path / "cal10").iterdir()) == []


def test_october_only_needs_no_flag_and_writes_no_controls_report(disk_ok, tmp_path):
    ru = disk_ok
    root = tmp_path / "root"
    root.mkdir()
    (root / ru.REPORT_NAME).write_text(json.dumps(
        {"controls": {c: {"verdict": "CLEAR"} for c in ru.CONTROLS}, "stops": [], "deviations": []}) + "\n",
        encoding="utf-8")
    assert ru.main(["--execute", "--only", "october"]) == 0
    assert (tmp_path / "frames_econ" / "build_report_econ920_2026-10.json").is_file()   # the run did finish
    assert sorted(p.name for p in tmp_path.rglob("controls_report*")) == []
    assert list((tmp_path / "cal10").iterdir()) == []


def test_the_october_controls_report_is_no_longer_a_write_target():
    src = (LAYER / "run_econ920.py").read_text(encoding="utf-8")
    assert "controls_report_econ920_2026-09-23.json" not in src.split('"""', 2)[2], \
        "run_econ920.py still names the October controls report outside its docstring"
