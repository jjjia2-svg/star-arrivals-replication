# -*- coding: utf-8 -*-
"""R1 F3 part 8 - build_doublestar.py names every input by a required flag (--events-dir, --frames-dir,
--pairs-none-math), and the October values reproduce the frozen October drop table byte for byte.

Toy tables in tmp_path, plus the tracked October event tables and econ ledger (small CSVs). The frame
surgery runs only on toy frames; the P3 full maths re-slim (a subprocess) is never reached here.
(The F20 departure-ledger test of the brief is out of scope since 2026-10-15: no star-departure
robustness is printed.)
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pandas as pd
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
S = REPO / "analysis/robustness/sensitivity"
B0 = {"events": "data/cal2026-10", "frames": "data/frames",
      "pairs_math": "data/cal2026-08-28/frames/pairs_none_math_stats.parquet"}
FROZEN_DROPS = REPO / "data/cal2026-10/robustness/doublestar/doublestar_drops.csv"


def _mod():
    spec = importlib.util.spec_from_file_location("build_doublestar_r1_test", S / "build_doublestar.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rc(mod, argv) -> int:
    try:
        return mod.main(argv)
    except SystemExit as e:
        return e.code


def _toy_events(d: pathlib.Path) -> None:
    """Same school: chemistry arrivals 2000 / 2003 (the second is dropped), maths 2000 / 2010 (both kept);
    econ 2001 / 2004 / 2004 at one school (the two 2004 events are dropped and are a same-year pair)."""
    d.mkdir(parents=True, exist_ok=True)
    hdr = "field,school,author_id,display_name,arrival_corrected\n"
    (d / "events_chemistry_cal2026-10.csv").write_text(
        hdr + "chemistry,uX,A1,One,2000\nchemistry,uX,A2,Two,2003\n", encoding="utf-8")
    (d / "events_math_stats_cal2026-10.csv").write_text(
        hdr + "math_stats,uY,A3,Three,2000\nmath_stats,uY,A4,Four,2010\n", encoding="utf-8")


def _toy_ledger(d: pathlib.Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "p1_events_ledger_econ.csv").write_text(
        "event_id,star_id,school,arrival_year\nE5:2001,E5,uZ,2001\nE6:2004,E6,uZ,2004\nE7:2004,E7,uZ,2004\n",
        encoding="utf-8")


def test_doublestar_reads_events_from_the_dir_given(tmp_path):
    mod = _mod()
    _toy_events(tmp_path)
    _toy_ledger(tmp_path)
    ch = mod.canon_events("chemistry", events_dir=tmp_path, frames_dir=tmp_path)
    assert list(ch.event_id) == ["A1:uX", "A2:uX"] and list(ch.arrival) == [2000, 2003]
    ec = mod.canon_events("econ", events_dir=tmp_path, frames_dir=tmp_path)
    assert list(ec.event_id) == ["E5:2001", "E6:2004", "E7:2004"] and list(ec.school) == ["uZ"] * 3
    assert mod.dropset(ch) == (["A2:uX"], [])
    assert mod.dropset(ec) == (["E6:2004", "E7:2004"], ["E6:2004", "E7:2004"])
    # the October dirs give exactly the frozen October drop table
    out = tmp_path / "out_b0"
    rows = []
    for f in mod.FIELDS:
        ev = mod.canon_events(f, events_dir=REPO / B0["events"], frames_dir=REPO / B0["frames"])
        drops, _ = mod.dropset(ev)
        rows += [{"field": f, "event_id": e, "dropped": True} for e in drops]
        rows += [{"field": f, "event_id": e, "dropped": False} for e in ev.event_id if e not in set(drops)]
    out.mkdir()
    pd.DataFrame(rows).to_csv(out / "drops.csv", index=False)
    assert (out / "drops.csv").read_bytes() == FROZEN_DROPS.read_bytes()


def test_b0_flags_reproduce_the_frozen_october_drop_table(tmp_path, monkeypatch):
    mod = _mod()
    out = tmp_path / "ds_out"
    monkeypatch.setenv("SAR_ROBUST_OUTDIR", str(out))
    monkeypatch.delenv("SAR_PAIRS_MATH_STATS", raising=False)
    argv = ["--spec", "pos", "--stage", str(tmp_path / "stage"), "--fields", "",
            "--events-dir", B0["events"], "--frames-dir", B0["frames"], "--pairs-none-math", B0["pairs_math"]]
    assert _rc(mod, argv) == 0
    assert (out / "doublestar_drops.csv").read_bytes() == FROZEN_DROPS.read_bytes()
    rep = json.loads((out / "doublestar_build_report.json").read_text(encoding="utf-8"))
    assert {f: rep[f]["events"] for f in mod.FIELDS} == {"econ": 113, "chemistry": 38, "math_stats": 33}
    assert set(rep) == {"rule", "spec", "afar_frame", "fields_built", "fields_NOT_built", "econ", "chemistry",
                        "math_stats", "staged_sha256"}               # no new report key


def test_doublestar_frame_surgery_reads_the_frames_dir_given(tmp_path, monkeypatch):
    mod = _mod()
    ev, fd, mp, out, st = (tmp_path / n for n in ("events", "frames", "maps", "out", "stage"))
    _toy_events(ev)
    _toy_ledger(fd)
    hdr = "event_id,incumbent_person_id,y\n"
    body = "A1:uX,P_1,0\nA1:uX,P_2,1\nA2:uX,P_1,0\n"
    (fd / "p1_frame_chemistry.csv").write_text(hdr + body, encoding="utf-8")
    (fd / "p2_becoming_chemistry.csv").write_text(hdr + body, encoding="utf-8")
    pd.DataFrame({"grp": [0, 1], "ev": [1, 2], "year": [2001, 2004], "y": [0, 1], "D": [1, 1]}).to_parquet(
        fd / "p3_afar_pos_chemistry.parquet", index=False)
    mp.mkdir()
    (mp / "afar_event_map_chemistry.csv").write_text("ev,event_id\n1,A1:uX\n2,A2:uX\n", encoding="utf-8")
    monkeypatch.setenv("SAR_ROBUST_OUTDIR", str(out))
    monkeypatch.setenv("SAR_AFAR_MAP_DIR", str(mp))
    monkeypatch.delenv("SAR_PAIRS_MATH_STATS", raising=False)
    argv = ["--spec", "pos", "--stage", str(st), "--fields", "chemistry", "--events-dir", str(ev),
            "--frames-dir", str(fd), "--pairs-none-math", str(tmp_path / "unused.parquet")]
    assert _rc(mod, argv) == 0
    assert (st / "p1_ds_chemistry.csv").read_text(encoding="utf-8") == hdr + "A1:uX,P_1,0\nA1:uX,P_2,1\n"
    assert (st / "p2_ds_chemistry.csv").read_text(encoding="utf-8") == hdr + "A1:uX,P_1,0\nA1:uX,P_2,1\n"
    af = pd.read_parquet(st / "p3_afar_ds_chemistry.parquet")
    assert list(af.ev) == [1]
    rep = json.loads((out / "doublestar_build_report.json").read_text(encoding="utf-8"))
    assert rep["chemistry"]["afar"] == {"events_in_afar": 2, "dropped_in_afar": 1, "rows_kept": 1}
    assert rep["econ"]["dropped"] == 2 and rep["math_stats"]["dropped"] == 0


def test_doublestar_requires_every_path_flag_and_refuses_the_old_env(tmp_path, monkeypatch):
    mod = _mod()
    monkeypatch.setenv("SAR_ROBUST_OUTDIR", str(tmp_path / "out"))
    monkeypatch.delenv("SAR_PAIRS_MATH_STATS", raising=False)
    full = ["--spec", "pos", "--stage", str(tmp_path / "st"), "--fields", "",
            "--events-dir", B0["events"], "--frames-dir", B0["frames"], "--pairs-none-math", B0["pairs_math"]]
    for flag in ("--events-dir", "--frames-dir", "--pairs-none-math"):
        i = full.index(flag)
        assert _rc(mod, full[:i] + full[i + 2:]) == 2, flag
    monkeypatch.setenv("SAR_PAIRS_MATH_STATS", B0["pairs_math"])
    assert _rc(mod, full) == 2                       # replaced by --pairs-none-math: never read silently
    assert not (tmp_path / "out" / "doublestar_drops.csv").exists()


def test_callers_pass_octobers_values():
    want_sh = ("--events-dir data/cal2026-10 --frames-dir data/frames "
               "--pairs-none-math data/cal2026-08-28/frames/pairs_none_math_stats.parquet")
    for sh in ("run_all_sensitivity.sh", "run_p3pos_sensitivity.sh"):
        lines = [ln for ln in (S / sh).read_text(encoding="utf-8").splitlines()
                 if "build_doublestar.py" in ln and not ln.lstrip().startswith("#")]
        assert len(lines) == 1 and want_sh in lines[0], (sh, lines)
    py = (S / "run_sensitivity_cal2026_10.py").read_text(encoding="utf-8")
    call = py[py.index('HERE / "build_doublestar.py", "--spec"'):]
    call = call[:call.index("logs / \"build_doublestar.log\"")]
    assert '"--events-dir", REPO / "data/cal2026-10"' in call
    assert '"--frames-dir", FRAMES' in call and '"--pairs-none-math", PAIRS_0828_MATH' in call
    assert 'FRAMES = REPO / "data/frames"' in py
    assert 'PAIRS_0828_MATH = REPO / "data/cal2026-08-28/frames/pairs_none_math_stats.parquet"' in py
