# -*- coding: utf-8 -*-
"""pipeline/aws/r1/promote_r1.py (F4, ruling: a NEW packaging script; October's promote.py untouched).

Toy trees in tmp_path only: a toy assembled frames dir, toy cell JSONs, toy cells TSVs and a toy
read-only October reference copy. The real repo is read for three things only: config/r1/cells/oct29.tsv
(and M.tsv / M_evcl.tsv once W1-CELLSM is merged) for the gold-row list, analysis/expected/MANIFEST.sha256
for the 29 October gold names, and a stat of the October trees (never written)."""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO / "pipeline" / "aws" / "r1") not in sys.path:
    sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import promote_r1 as P   # noqa: E402

CELLS_DIR = REPO / "config" / "r1" / "cells"
C10 = ("P1_econ_fnfix_old79", "P1_econ_fnfix_new37")
HDR = "label\tdriver\tframe\tref\tout_name\tstack\n"
REPORT_KEYS = {"gate", "verdict", "codes", "counts", "rows_frames", "rows_expected"}


def _sha(p) -> str:
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def _w(p: pathlib.Path, data) -> pathlib.Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    (p.write_bytes if isinstance(data, bytes) else lambda t: p.write_text(t, encoding="utf-8"))(data)
    return p


def _manifest(d: pathlib.Path) -> None:
    names = sorted(p.name for p in d.iterdir() if p.name != "MANIFEST.sha256")
    (d / "MANIFEST.sha256").write_text("".join(f"{_sha(d / n)}  {n}\n" for n in names), encoding="utf-8")


def _tree(tmp_path: pathlib.Path) -> dict:
    """frames (3 files + MANIFEST), estimates for 3 gold rows (P1_econ_fnfix unchanged vs October,
    P3_econ_fnfix changed, P1evcl_econ new), one C10 row with no estimate, October ref copies."""
    t = {"frames": tmp_path / "work" / "frames", "est": tmp_path / "work" / "estimates_m",
         "golds": tmp_path / "ref" / "october" / "analysis" / "expected",
         "ofr": tmp_path / "ref" / "october" / "data" / "frames", "out": tmp_path / "work" / "promote"}
    _w(t["frames"] / "p1_frame_econ.csv", "a,b\n1,2\n")
    _w(t["frames"] / "p3_slim_econ.parquet", b"PAR1\x00\x01toy\x00PAR1")
    _w(t["frames"] / "assembly_2026-10.json", '{"files": {}}\n')
    _manifest(t["frames"])
    _w(t["est"] / "P1_econ_fnfix.json", '{"beta": -0.133}\n')
    _w(t["est"] / "P3_econ_fnfix.json", '{"beta": -0.050}\n')
    _w(t["est"] / "P1evcl_econ.json", '{"beta": -0.133, "point_estimate_check": "MATCH"}\n')
    _w(t["golds"] / "P1_econ_fnfix.json", '{"beta": -0.133}\n')
    _w(t["golds"] / "P3_econ_fnfix.json", '{"beta": -0.062}\n')
    _w(t["golds"] / "P1_econ_fnfix_old79.json", '{"beta": -0.3}\n')
    _w(t["ofr"] / "p1_frame_econ.csv", "a,b\n1,2\n")
    _w(t["ofr"] / "p3_slim_econ.parquet", b"PAR1\x00\x00october\x00PAR1")
    t["m"] = _w(tmp_path / "cfg" / "M.tsv", HDR
                + "P1_econ_fnfix\tanalysis/estimation/run_p1.R\tp1_frame_econ.csv\t-\tP1_econ_fnfix.json\trmac\n"
                + "P1_econ_fnfix_old79\tanalysis/estimation/run_p1.R\tp1_frame_econ_old79.csv\t-\tP1_econ_fnfix_old79.json\trmac\n"
                + "P3_econ_fnfix\tanalysis/estimation/run_p3.R\tp3_slim_econ.parquet\t-\tP3_econ_fnfix.json\trcloud\n")
    t["mev"] = _w(tmp_path / "cfg" / "M_evcl.tsv", HDR
                  + "P1evcl_econ\tanalysis/estimation/run_p1_evcl.R\tp1_frame_econ.csv\tP1_econ_fnfix.json\tP1evcl_econ.json\trmac\n")
    return t


def _run_argv(t, out=None, est=None) -> list[str]:
    return ["run", "--frames", str(t["frames"]), "--estimates", *(est or [str(t["est"])]),
            "--cells", str(t["m"]), str(t["mev"]), "--october-golds", str(t["golds"]),
            "--october-frames", str(t["ofr"]), "--out", str(out or t["out"])]


def _check_argv(t, out=None, est=None) -> list[str]:
    return ["check", "--frames", str(t["frames"]), "--estimates", *(est or [str(t["est"])]),
            "--cells", str(t["m"]), str(t["mev"]), "--out", str(out or t["out"])]


def _files(root: pathlib.Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): _sha(p) for p in sorted(root.rglob("*")) if p.is_file()} if root.exists() else {}


def _october_stat() -> dict:
    """Name, size and mtime of every file in the repo's October trees (cheap: no hashing of big frames)."""
    out = {}
    for rel in P.OCTOBER_TREES:
        d = REPO / rel
        for p in sorted(d.rglob("*")) if d.is_dir() else []:
            if p.is_file():
                st = p.stat()
                out[p.relative_to(REPO).as_posix()] = (st.st_size, st.st_mtime_ns)
    return out


@pytest.fixture
def host(monkeypatch):
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")


def _report(out: pathlib.Path) -> dict:
    return json.loads((out / "gate_report_postpromote.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------

def test_required_flags(tmp_path, host, monkeypatch):
    t = _tree(tmp_path)
    for argv in (_run_argv(t), _check_argv(t)):
        flags = [a for a in argv if a.startswith("--")]
        for f in flags:
            i = argv.index(f)
            j = i + 1
            while j < len(argv) and not argv[j].startswith("--"):
                j += 1
            with pytest.raises(SystemExit) as e:
                P.main(argv[:i] + argv[j:])
            assert e.value.code == 2, f"{argv[0]} without {f}"
    with pytest.raises(SystemExit) as e:
        P.main([])
    assert e.value.code == 2
    monkeypatch.delenv("SAR_HOST")
    with pytest.raises(SystemExit) as e:          # off an R1 instance: refused before anything is read
        P.main(_run_argv(t))
    assert "R1 rule" in str(e.value.code)
    assert not t["out"].exists()


def test_writes_only_under_out(tmp_path, host, capsys):
    t = _tree(tmp_path)
    before = {k: v for k, v in _files(tmp_path).items() if not k.startswith("work/promote/")}
    oct_before = _october_stat()
    assert P.main(_run_argv(t)) == 0
    after = _files(tmp_path)
    assert {k: v for k, v in after.items() if not k.startswith("work/promote/")} == before
    assert _october_stat() == oct_before
    got = sorted(_files(t["out"]))
    assert got == ["expected/MANIFEST.sha256", "expected/P1_econ_fnfix.json", "expected/P1evcl_econ.json",
                   "expected/P3_econ_fnfix.json", "expected/SOURCES.md", "expected_refreeze_r1.json",
                   "frames/MANIFEST.sha256", "frames/assembly_2026-10.json", "frames/p1_frame_econ.csv",
                   "frames/p3_slim_econ.parquet", "report_promote.json"]
    for n in ("p1_frame_econ.csv", "p3_slim_econ.parquet", "assembly_2026-10.json"):
        assert _sha(t["out"] / "frames" / n) == _sha(t["frames"] / n)
    for n in ("P1_econ_fnfix.json", "P3_econ_fnfix.json", "P1evcl_econ.json"):
        assert _sha(t["out"] / "expected" / n) == _sha(t["est"] / n)
    # MANIFESTs: bare names, cell order for the golds (as freeze_expected), and they pass the repo tool
    assert (t["out"] / "expected" / "MANIFEST.sha256").read_text().split() == [
        _sha(t["est"] / "P1_econ_fnfix.json"), "P1_econ_fnfix.json", _sha(t["est"] / "P3_econ_fnfix.json"),
        "P3_econ_fnfix.json", _sha(t["est"] / "P1evcl_econ.json"), "P1evcl_econ.json"]
    for sub in ("frames", "expected"):
        assert P.verify_manifest(t["out"] / sub / "MANIFEST.sha256")
    src = (t["out"] / "expected" / "SOURCES.md").read_text(encoding="utf-8")
    assert "P1evcl_econ" in src and "old79" not in src
    # the refreeze record: October side from the reference copy, new side from the promoted files
    rec = json.loads((t["out"] / "expected_refreeze_r1.json").read_text(encoding="utf-8"))
    assert rec["frames"]["p1_frame_econ.csv"] == {"october_sha256": _sha(t["ofr"] / "p1_frame_econ.csv"),
                                                  "new_sha256": _sha(t["frames"] / "p1_frame_econ.csv")}
    assert rec["frames"]["p3_slim_econ.parquet"]["october_sha256"] == _sha(t["ofr"] / "p3_slim_econ.parquet")
    assert rec["frames"]["assembly_2026-10.json"]["october_sha256"] is None
    e = rec["expected"]
    assert sorted(e) == ["P1_econ_fnfix.json", "P1evcl_econ.json", "P3_econ_fnfix.json"]
    assert e["P1_econ_fnfix.json"]["changed"] is False
    assert e["P1_econ_fnfix.json"]["october_sha256"] == _sha(t["golds"] / "P1_econ_fnfix.json")
    assert e["P3_econ_fnfix.json"]["changed"] is True
    assert e["P3_econ_fnfix.json"]["october_sha256"] == _sha(t["golds"] / "P3_econ_fnfix.json")
    assert e["P1evcl_econ.json"]["october_sha256"] is None and e["P1evcl_econ.json"]["changed"] is True
    assert rec["cells_tsv_sha256"] == {str(t["m"]): _sha(t["m"]), str(t["mev"]): _sha(t["mev"])}
    rep = json.loads((t["out"] / "report_promote.json").read_text(encoding="utf-8"))
    assert rep["counts"] == {"n_frames": 3, "n_golds": 3, "n_golds_changed": 2, "n_frames_new_in_m": 1}
    # a second promotion into the same directory is refused and changes nothing
    snap = _files(t["out"])
    capsys.readouterr()
    assert P.main(_run_argv(t)) == 1
    assert "STOP" in capsys.readouterr().out
    assert _files(t["out"]) == snap


def test_out_inside_an_october_tree_is_refused(tmp_path, host, capsys):
    t = _tree(tmp_path)
    golds_before, ofr_before = _files(t["golds"]), _files(t["ofr"])
    for out in (t["golds"] / "r1", t["ofr"], t["golds"].parent.parent, REPO / "data" / "frames" / "r1_promote_test",
                REPO / "analysis" / "expected" / "r1_promote_test", REPO / "data" / "cal2026-10" / "r1_promote_test"):
        assert P.main(_run_argv(t, out=out)) == 1, out
        assert "STOP" in capsys.readouterr().out
        assert not (out / "frames").exists() and not (out / "expected_refreeze_r1.json").exists()
    assert not (REPO / "data" / "frames" / "r1_promote_test").exists()
    assert _files(t["golds"]) == golds_before and _files(t["ofr"]) == ofr_before


def test_missing_estimate_stops(tmp_path, host, capsys):
    t = _tree(tmp_path)
    (t["est"] / "P1evcl_econ.json").unlink()
    assert P.main(_run_argv(t)) == 1
    assert "STOP" in capsys.readouterr().out
    assert not t["out"].exists()                      # nothing written
    # the same out_name in two estimate dirs is a STOP too
    _w(t["est"] / "P1evcl_econ.json", '{"beta": 1}\n')
    other = _w(tmp_path / "work" / "est2" / "P1evcl_econ.json", '{"beta": 1}\n').parent
    assert P.main(_run_argv(t, est=[str(t["est"]), str(other)])) == 1
    assert "STOP" in capsys.readouterr().out
    assert not t["out"].exists()
    # a source frames MANIFEST that does not describe the files beside it
    _w(t["frames"] / "p1_frame_econ.csv", "a,b\n1,3\n")
    assert P.main(_run_argv(t)) == 1
    assert "STOP" in capsys.readouterr().out
    assert not t["out"].exists()
    # a frame name that exists at the repo root (verify_manifest.py would read that file instead)
    _w(t["frames"] / "p1_frame_econ.csv", "a,b\n1,2\n")
    _w(t["frames"] / "README.md", "toy\n")
    _manifest(t["frames"])
    assert P.main(_run_argv(t)) == 1
    assert "STOP" in capsys.readouterr().out
    assert not t["out"].exists()


def test_cell_list_is_the_27_gold_rows(tmp_path):
    october = [ln.split()[1] for ln in (REPO / "analysis" / "expected" / "MANIFEST.sha256").read_text().splitlines()
               if ln.strip().endswith(".json")]
    assert len(october) == 29
    want = sorted(n for n in october if not any(c + ".json" == n for c in C10))
    assert len(want) == 27
    rows = P.gold_rows([CELLS_DIR / "oct29.tsv"])
    assert sorted(r["out_name"] for r in rows) == want
    assert not any(r["label"] in C10 or "old79" in r["out_name"] or "new37" in r["out_name"] for r in rows)
    m, mev = CELLS_DIR / "M.tsv", CELLS_DIR / "M_evcl.tsv"
    if m.is_file() and mev.is_file():                  # W1-CELLSM's M cell list (after integration)
        mrows = P.gold_rows([m, mev])
        assert len(mrows) == 27 and sorted(r["out_name"] for r in mrows) == want
    # a TSV with a kind column: kind decides (robust rows are not golds), an unknown kind is refused
    k = _w(tmp_path / "k.tsv", "label\tdriver\tframe\tref\tout_name\tstack\tkind\n"
           "A1\td.R\tf.csv\t-\tA1.json\trmac\tgold\n"
           "B1\td.R\tf.csv\t-\tB1.json\trmac\trobust\n"
           "P1_econ_fnfix_old79\td.R\tf.csv\t-\tP1_econ_fnfix_old79.json\trmac\tgold\n")
    assert [r["label"] for r in P.gold_rows([k])] == ["A1", "P1_econ_fnfix_old79"]
    _w(k, "label\tdriver\tframe\tref\tout_name\tstack\tkind\nA1\td.R\tf.csv\t-\tA1.json\trmac\tmaybe\n")
    with pytest.raises(P.Stop):
        P.gold_rows([k])
    dup = _w(tmp_path / "dup.tsv", HDR + "A1\td.R\tf.csv\t-\tA1.json\trmac\nA2\td.R\tf.csv\t-\tA1.json\trmac\n")
    with pytest.raises(P.Stop):
        P.gold_rows([dup])


def test_postpromote_passes_then_one_stale_frame_fails(tmp_path, host):
    t = _tree(tmp_path)
    assert P.main(_run_argv(t)) == 0
    assert P.main(_check_argv(t)) == 0
    rep = _report(t["out"])
    assert rep["verdict"] == "PASS" and rep["codes"] == []
    assert rep["counts"] == {"n_frames": 3, "n_frames_ok": 3, "n_golds": 3, "n_golds_ok": 3}
    assert set(rep) <= REPORT_KEYS

    def variant(name, mutate, code, est=None):
        out = tmp_path / "variants" / name
        shutil.copytree(t["out"], out)
        (out / "gate_report_postpromote.json").unlink()
        mutate(out)
        assert P.main(_check_argv(t, out=out, est=est)) == 1, name
        r = _report(out)
        assert r["verdict"] == "FAIL" and code in r["codes"], (name, r["codes"])
        assert set(r) <= REPORT_KEYS
        return r

    r = variant("stale", lambda o: _w(o / "frames" / "p1_frame_econ.csv", "a,b\n9,9\n"), "FRAME_STALE")
    assert {"path": "p1_frame_econ.csv", "status": "STALE"} in r["rows_frames"]
    assert "MANIFEST_FAIL" in r["codes"]
    variant("missing", lambda o: (o / "frames" / "p3_slim_econ.parquet").unlink(), "FRAME_MISSING")
    variant("extra", lambda o: _w(o / "frames" / "p9_extra.csv", "x\n"), "FRAME_EXTRA")
    variant("extra_gold", lambda o: _w(o / "expected" / "P9_extra.json", "{}\n"), "EXPECTED_EXTRA")
    variant("gold_missing", lambda o: (o / "expected" / "P3_econ_fnfix.json").unlink(), "GOLD_MISSING")

    est2 = tmp_path / "variants" / "est_rerun"
    shutil.copytree(t["est"], est2)
    _w(est2 / "P3_econ_fnfix.json", '{"beta": -0.051}\n')     # the cell output just run differs from the gold
    r = variant("gold_diff", lambda o: None, "GOLD_DIFF", est=[str(est2)])
    assert {"label": "P3_econ_fnfix", "path": "P3_econ_fnfix.json", "status": "GOLD_DIFF"} in r["rows_expected"]

    def bad_manifest(o):
        m = o / "expected" / "MANIFEST.sha256"
        lines = m.read_text().splitlines()
        lines[0] = "0" * 64 + lines[0][64:]
        m.write_text("\n".join(lines) + "\n")
    variant("manifest", bad_manifest, "MANIFEST_FAIL")

    def short_manifest(o):                                     # a MANIFEST that skips a file still verifies
        m = o / "frames" / "MANIFEST.sha256"
        m.write_text("".join(ln + "\n" for ln in m.read_text().splitlines() if "assembly" not in ln))
    r = variant("manifest_rows", short_manifest, "MANIFEST_ROWS")
    assert "MANIFEST_FAIL" not in r["codes"]

    def stale_record(o):
        rec = json.loads((o / "expected_refreeze_r1.json").read_text())
        rec["expected"]["P3_econ_fnfix.json"]["new_sha256"] = "0" * 64
        (o / "expected_refreeze_r1.json").write_text(json.dumps(rec))
    variant("record", stale_record, "REFREEZE_STALE")


def test_check_refuses_off_host_and_reports_unreadable_inputs(tmp_path, host, monkeypatch):
    t = _tree(tmp_path)
    assert P.main(_run_argv(t)) == 0
    bad = _check_argv(t)
    bad[bad.index("--frames") + 1] = str(tmp_path / "nowhere")
    assert P.main(bad) == 1
    assert _report(t["out"])["codes"] == ["INPUT_STOP"]
    monkeypatch.delenv("SAR_HOST")
    with pytest.raises(SystemExit) as e:
        P.main(_check_argv(t))
    assert "R1 rule" in str(e.value.code)
