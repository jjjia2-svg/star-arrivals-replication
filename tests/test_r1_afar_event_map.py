# -*- coding: utf-8 -*-
"""R1 F6 - analysis/robustness/sensitivity/afar_event_map.py reads the run's frames and pairs from the
directories passed in (--frames-dir / --pairs-dir), and its default call stays October's.

Toy frames in tmp_path only (an in-memory duckdb maps them); the default-call test reads the tracked
October frozen frame data/frames/p3_afar_pos_chemistry.parquet and nothing else. No disk, no R.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib

import pandas as pd
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "analysis/robustness/sensitivity/afar_event_map.py"
FIELDS = ("chemistry", "math_stats", "econ")


def _mod():
    spec = importlib.util.spec_from_file_location("afar_event_map_r1_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# two events, a few persons: (a,b)@E1 and (a,d)@E2 survive; (a,c)@E1 has dose 0, (a,e)@E1 a pre-arrival
# tie, (a,b)@E2 a network member -> all three dropped by the A_far pos predicate
P1 = ("event_id,incumbent_person_id,dose_topic\n"
      "E1,P_a,0.5\nE1,P_b,0.2\nE1,P_c,0.0\nE1,P_e,0.7\nE2,P_a,0.3\nE2,P_b,0.4\nE2,P_d,0.6\n")
P2 = ("event_id,pid,channel,y,tau\n"
      "E1,P_a,dept_only,0,-1\nE1,P_b,dept_only,0,1\nE1,P_c,dept_only,0,0\nE1,P_e,dept_only,1,-2\n"
      "E2,P_a,dept_only,0,-1\nE2,P_b,network,0,0\nE2,P_d,dept_only,0,1\n")
PAIRS = pd.DataFrame({
    "event_id": ["E1", "E1", "E1", "E1", "E2", "E2", "E2"],
    "i_id": ["a", "a", "a", "a", "a", "a", "a"],
    "j_id": ["b", "b", "c", "e", "d", "d", "b"],
    "year": [2000, 2001, 2000, 2000, 2002, 2003, 2002],
    "y_any": [0, 1, 0, 0, 0, 0, 0],
    "post": [0, 1, 0, 0, 0, 1, 0]})
# worked by hand: grp = dense rank of 'a_b@E1' < 'a_d@E2'; ev = dense rank of the event id
FROZEN = pd.DataFrame({"grp": [0, 0, 1, 1], "ev": [1, 1, 2, 2], "year": [2000, 2001, 2002, 2003],
                       "y": [0, 1, 0, 0], "D": [0, 1, 0, 1]})
MAP = "ev,event_id\n1,E1\n2,E2\n"


def _toy(tmp_path: pathlib.Path) -> dict:
    fd, econ, out = tmp_path / "frames", tmp_path / "econ_chain", tmp_path / "out"
    fd.mkdir()
    econ.mkdir()
    for f in FIELDS:
        (fd / f"p1_frame_{f}.csv").write_text(P1, encoding="utf-8")
        (fd / f"p2_becoming_{f}.csv").write_text(P2, encoding="utf-8")
        FROZEN.to_parquet(fd / f"p3_afar_pos_{f}.parquet", index=False)
    for f in ("chemistry", "math_stats"):
        PAIRS.to_parquet(fd / f"pairs_none_{f}.parquet", index=False)
    PAIRS.to_csv(econ / "pairs_unified.csv", index=False)
    (econ / "becoming_unified.csv").write_bytes((fd / "p2_becoming_econ.csv").read_bytes())
    argv = ["--spec", "pos", "--frames-dir", str(fd), "--pairs-dir", str(fd),
            "--pairs-econ", str(econ / "pairs_unified.csv"), "--outdir", str(out),
            "--tmpdir", str(tmp_path / "duck_tmp"), "--threads", "1", "--memory-limit", "1GB"]
    return {"fd": fd, "econ": econ, "out": out, "argv": argv}


def _rc(mod, argv) -> int:
    try:
        return mod.main(argv)
    except SystemExit as e:  # argparse refusals
        return e.code


def _files(d: pathlib.Path) -> list[str]:
    return sorted(p.name for p in d.rglob("*") if p.is_file()) if d.exists() else []


def test_frames_dir_mode_maps_and_proves_on_a_toy_dir(tmp_path, capsys):
    mod, t = _mod(), _toy(tmp_path)
    assert _rc(mod, t["argv"]) == 0
    assert "AFAR_MAP_OK" in capsys.readouterr().out
    for f in FIELDS:
        assert (t["out"] / f"afar_event_map_{f}.csv").read_text(encoding="utf-8") == MAP, f
    rep = json.loads((t["out"] / "afar_event_map_report.json").read_text(encoding="utf-8"))
    assert rep["spec"] == "pos" and rep["frames_dir"] == str(t["fd"])
    assert rep["econ_becoming_sha_check"] == "BYTE_EQUAL"
    for f in FIELDS:
        proof = rep["fields"][f]
        assert proof["content_equal_to_frozen"] is True and proof["events"] == 2 and proof["rows"] == 4
        frozen = t["fd"] / f"p3_afar_pos_{f}.parquet"
        assert proof["frozen_frame"] == str(frozen) and proof["frozen_frame_sha256"] == _sha(frozen)
    for f in ("chemistry", "math_stats"):
        p = t["fd"] / f"pairs_none_{f}.parquet"
        assert rep["pairs"][f] == {"path": str(p), "sha256": _sha(p)}
    pe = t["econ"] / "pairs_unified.csv"
    assert rep["pairs"]["econ"] == {"path": str(pe), "sha256": _sha(pe)}
    assert rep["econ_pairs_sha256"] == _sha(pe)
    assert rep["duckdb"] == {"threads": 1, "memory_limit": "1GB"}


def test_a_changed_frozen_row_fails_the_proof(tmp_path):
    mod, t = _mod(), _toy(tmp_path)
    bad = FROZEN.copy()
    bad.loc[1, "y"] = 0
    bad.to_parquet(t["fd"] / "p3_afar_pos_chemistry.parquet", index=False)
    with pytest.raises(AssertionError, match="NOT content-equal"):
        mod.main(t["argv"])
    assert _files(t["out"]) == []        # no map, no report


@pytest.mark.parametrize("gone", ["pairs_none_math_stats.parquet", "p3_afar_pos_econ.parquet",
                                  "p1_frame_chemistry.csv", "p2_becoming_math_stats.csv"])
def test_missing_pairs_file_is_a_stop(tmp_path, capsys, gone):
    mod, t = _mod(), _toy(tmp_path)
    (t["fd"] / gone).unlink()
    assert _rc(mod, t["argv"]) == 2
    out = capsys.readouterr().out
    assert f"AFAR_MAP_STOP missing {t['fd'] / gone}" in out
    assert _files(t["out"]) == []


def test_missing_econ_pairs_is_a_stop(tmp_path, capsys):
    mod, t = _mod(), _toy(tmp_path)
    i = t["argv"].index("--pairs-econ")
    argv = t["argv"][:i] + t["argv"][i + 2:]
    assert _rc(mod, argv) == 2
    assert "AFAR_MAP_STOP missing --pairs-econ" in capsys.readouterr().out
    (t["econ"] / "pairs_unified.csv").unlink()
    assert _rc(mod, t["argv"]) == 2
    assert f"AFAR_MAP_STOP missing {t['econ'] / 'pairs_unified.csv'}" in capsys.readouterr().out
    assert _files(t["out"]) == []


def test_default_call_reads_the_october_paths(tmp_path, monkeypatch):
    mod = _mod()
    calls, sql = [], []

    def fake_map(con, field, pairs, spec="med", frames_dir=None):
        calls.append((field, pairs, spec, frames_dir))
        return pd.DataFrame({"ev": [1], "event_id": ["X"]}), {"content_equal_to_frozen": True}

    class Con:
        def execute(self, q, *a):
            sql.append(q)
            return self

    monkeypatch.setattr(mod, "map_field", fake_map)
    monkeypatch.setattr(mod.duckdb, "connect", lambda *a, **k: Con())
    out, tmp = tmp_path / "out", tmp_path / "duck"
    assert mod.main(["--spec", "pos", "--outdir", str(out), "--tmpdir", str(tmp)]) == 0
    assert calls == [(f, str(REPO / f"data/cal2026-08-28/frames/pairs_none_{f}.parquet"), "pos", None)
                     for f in ("chemistry", "math_stats")]
    assert sql == ["PRAGMA threads=6", "PRAGMA memory_limit='10GB'", f"PRAGMA temp_directory='{tmp}'"]
    rep = json.loads((out / "afar_event_map_report.json").read_text(encoding="utf-8"))
    assert set(rep) == {"generated", "fields", "spec", "econ"}          # October's keys, nothing added
    assert rep["generated"] == "2026-09-10" and rep["econ"].startswith("NOT BUILT")


def test_map_field_default_reads_data_frames_and_the_frozen_constant(monkeypatch):
    """map_field without frames_dir: the SQL names REPO/data/frames/{p1,p2} and the proof reads the
    tracked FROZEN_FRAME['pos'] - the October inputs, in October's order."""
    mod = _mod()
    frozen = pd.read_parquet(REPO / "data/frames/p3_afar_pos_chemistry.parquet")
    rebuilt = frozen.assign(event_id=frozen.ev.astype(str))
    sql = []

    class Res:
        def fetchone(self):
            return (0.5,)

        def df(self):
            return rebuilt

    class Con:
        def execute(self, q, *a):
            sql.append(q)
            return Res()

    pairs = str(REPO / "data/cal2026-08-28/frames/pairs_none_chemistry.parquet")
    mp, proof = mod.map_field(Con(), "chemistry", pairs, "pos")
    assert str(REPO / "data/frames/p1_frame_chemistry.csv") in sql[0]
    assert str(REPO / "data/frames/p2_becoming_chemistry.csv") in sql[1]
    assert all(pairs in q for q in sql[3:])
    assert proof == {"cut": 0.0, "rows": len(frozen), "events": int(frozen.ev.nunique()),
                     "content_equal_to_frozen": True, "predicate": "dmin > 0",
                     "frozen_frame": "data/frames/p3_afar_pos_chemistry.parquet"}


def test_frames_dir_refuses_spec_med_and_regen_econ(tmp_path, monkeypatch):
    mod, t = _mod(), _toy(tmp_path)

    def no_regen(*a, **k):
        raise AssertionError("regen_econ_pairs must not run in frames-dir mode")

    monkeypatch.setattr(mod, "regen_econ_pairs", no_regen)
    argv = t["argv"]
    med = [a if a != "pos" else "med" for a in argv]
    assert _rc(mod, med) == 2
    i = argv.index("--spec")
    assert _rc(mod, argv[:i] + argv[i + 2:]) == 2                       # default spec is med
    assert _rc(mod, argv + ["--regen-econ"]) == 2
    for flag in ("--pairs-dir", "--outdir", "--tmpdir"):                # frames-dir mode names every path
        j = argv.index(flag)
        assert _rc(mod, argv[:j] + argv[j + 2:]) == 2, flag
    assert _files(t["out"]) == []


def test_econ_becoming_mismatch_or_absence_stops_in_frames_dir_mode(tmp_path, capsys):
    mod, t = _mod(), _toy(tmp_path)
    b = t["econ"] / "becoming_unified.csv"
    b.write_text(P2.replace("E2,P_d,dept_only,0,1", "E2,P_d,dept_only,1,1"), encoding="utf-8")
    assert _rc(mod, t["argv"]) == 2
    out = capsys.readouterr().out
    assert "AFAR_MAP_STOP" in out and "BYTE_EQUAL" in out
    b.unlink()
    assert _rc(mod, t["argv"]) == 2
    out = capsys.readouterr().out
    assert f"AFAR_MAP_STOP missing {b}" in out and "SKIPPED" not in out
    assert _files(t["out"]) == []


def test_threads_and_memory_reach_duckdb(tmp_path, monkeypatch):
    mod, t = _mod(), _toy(tmp_path)
    real_connect = mod.duckdb.connect
    seen = {}

    class Rec:
        def __init__(self):
            self.con, self.sql = real_connect(), []
            seen["rec"] = self

        def execute(self, q, *a):
            self.sql.append(q)
            return self.con.execute(q, *a)

    monkeypatch.setattr(mod.duckdb, "connect", lambda *a, **k: Rec())
    argv = list(t["argv"])
    argv[argv.index("--threads") + 1] = "2"
    argv[argv.index("--memory-limit") + 1] = "512MB"
    assert _rc(mod, argv) == 0
    rec = seen["rec"]
    assert rec.sql[:3] == ["PRAGMA threads=2", "PRAGMA memory_limit='512MB'",
                           f"PRAGMA temp_directory='{tmp_path / 'duck_tmp'}'"]
    assert int(rec.con.execute("SELECT current_setting('threads')").fetchone()[0]) == 2
    for bad in ("0", "-1"):
        a2 = list(t["argv"])
        a2[a2.index("--threads") + 1] = bad
        assert _rc(mod, a2) == 2, bad
    a3 = list(t["argv"])
    a3[a3.index("--memory-limit") + 1] = "1GB'; SELECT 1; --"
    assert _rc(mod, a3) == 2
