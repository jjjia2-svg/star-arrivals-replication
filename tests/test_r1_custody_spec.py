# -*- coding: utf-8 -*-
"""R1 custody: tools/r1_custody_spec.py writes a custody directory from the cells' own input
records (md5 taken at cell time by run_cells), the promoted frames and golds and the cell outputs; the
UNEDITED tools/verify_cloud_custody.py --custody DIR --spec DIR/custody_r1.json must then print
CUSTODY_OK, and CUSTODY_FAIL as soon as one link breaks.

Toy world (tmp_path only; the only repo data read are config/r1/cells/*.tsv and
analysis/expected/MANIFEST.sha256, in the two tests that use the real cell lists):
  <T>/frames/{f1.csv, f2.parquet}, <T>/expected/{A,B,C}.json (byte copies of the cell outputs, as the
  promotion writes them), <repo>/analysis/estimation/run_toy.R, two cell stages (main: A on f1, B on f2;
  evcl: C on f1 with ref A.json, the main stage's own output), the job marker out/RESULT.txt.

A record committed in the repository (--stack rcloud --relative-to REPO) holds only the four rcloud cells and
repo-relative paths, and verifies from the root of a fresh copy of that repository.
"""
from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import json
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import r1_custody_spec as cs                                           # noqa: E402

PY = sys.executable
VERIFY = REPO / "tools" / "verify_cloud_custody.py"
DRV = "analysis/estimation/run_toy.R"
HEADER = ["label", "driver", "frame", "ref", "out_name", "stack"]
SKIPPED = ("P1_econ_fnfix_old79", "P1_econ_fnfix_new37")       # October cells that the R1 cell lists leave out


def _rec(path: pathlib.Path, name: str) -> dict:
    """The input record run_cells writes for one cell input: {name, sha256, md5} of the bytes."""
    b = path.read_bytes()
    return {"name": name, "sha256": hashlib.sha256(b).hexdigest(), "md5": hashlib.md5(b).hexdigest()}


def _tsv(path: pathlib.Path, rows: list) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(HEADER)
        for r in rows:
            w.writerow([r[k] for k in HEADER])
    return path


def _run_stage(stage_dir: pathlib.Path, stack: str, rows: list, *, frames, repo, refs_from, extra_rows=()):
    """What run_cells leaves behind: estimates/<out_name> and cells_report_<stack>.json with inputs."""
    report = {}
    for r in list(rows) + list(extra_rows):
        out = stage_dir / "estimates" / r["out_name"]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"label": r["label"], "ate": -0.001 * (len(report) + 1), "se": 0.0003,
                                   "secs": 12.5}, indent=1) + "\n", encoding="utf-8")
        report[r["label"]] = {
            "rc": 0, "status": "RAN", "secs": 12.5, "peak_gib": 0.1, "first_diff": None,
            "inputs": {"frame": _rec(frames / r["frame"], r["frame"]),
                       "ref": None if r["ref"] == "-" else _rec(refs_from / r["ref"], r["ref"]),
                       "driver": _rec(repo / r["driver"], r["driver"])}}
    (stage_dir / f"cells_report_{stack}.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n",
                                                          encoding="utf-8")
    return report


def _world(tmp: pathlib.Path, marker_text: str = "OK\n") -> dict:
    T = tmp / "T"
    frames, expected, repo = T / "frames", T / "expected", tmp / "repo"
    frames.mkdir(parents=True)
    expected.mkdir(parents=True)
    (frames / "f1.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (frames / "f2.parquet").write_bytes(b"PAR1\x00toy\x01PAR1")
    (repo / DRV).parent.mkdir(parents=True)
    (repo / DRV).write_text("# toy driver\n", encoding="utf-8")
    main_rows = [dict(label="P1_a", driver=DRV, frame="f1.csv", ref="-", out_name="A.json", stack="rmac"),
                 dict(label="P1_b", driver=DRV, frame="f2.parquet", ref="-", out_name="B.json", stack="rmac")]
    evcl_rows = [dict(label="P1evcl_a", driver=DRV, frame="f1.csv", ref="A.json", out_name="C.json", stack="rmac")]
    cells_main = _tsv(tmp / "cells" / "M.tsv", main_rows)
    cells_evcl = _tsv(tmp / "cells" / "M_evcl.tsv", evcl_rows)
    j1a = tmp / "j1a"
    st_main, st_evcl = j1a / "cells_rmac", j1a / "cells_rmac_evcl"
    _run_stage(st_main, "rmac", main_rows, frames=frames, repo=repo, refs_from=None)
    # the evcl cells read the main stage's own output as their reference (same run)
    _run_stage(st_evcl, "rmac", evcl_rows, frames=frames, repo=repo, refs_from=st_main / "estimates")
    # promotion: the golds are byte copies of the cell outputs
    for st in (st_main, st_evcl):
        for p in sorted((st / "estimates").glob("*.json")):
            shutil.copyfile(p, expected / p.name)
    marker = j1a / "out" / "RESULT.txt"
    marker.parent.mkdir(parents=True)
    marker.write_text(marker_text, encoding="utf-8")
    out = tmp / "custody"
    argv = ["--cells", str(cells_main), str(cells_evcl), "--reports", str(st_main), str(st_evcl),
            "--est", str(st_main), str(st_evcl), "--frames-dir", str(frames), "--gold-dir", str(expected),
            "--drivers-root", str(repo), "--marker", str(marker), "--out", str(out)]
    return dict(T=T, frames=frames, expected=expected, repo=repo, st_main=st_main, st_evcl=st_evcl,
                marker=marker, out=out, argv=argv)


def _verify(cust: pathlib.Path, root: pathlib.Path | None = None):
    cmd = [PY, str(VERIFY), "--custody", str(cust), "--spec", str(cust / "custody_r1.json")]
    if root is not None:
        cmd += ["--root", str(root)]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)


def _lines(stdout: str, prefix: str) -> list:
    return [ln for ln in stdout.splitlines() if ln.startswith(prefix)]


# ---------------------------------------------------------------------------------------------

def test_spec_then_verify_gives_custody_ok(tmp_path):
    w = _world(tmp_path)
    assert cs.main(w["argv"]) == 0
    out = w["out"]
    # payload.md5: one line per distinct frame, driver and ref basename, md5 from the cells' records
    rep_main = json.loads((w["st_main"] / "cells_report_rmac.json").read_text())
    rep_evcl = json.loads((w["st_evcl"] / "cells_report_rmac.json").read_text())
    want = {"f1.csv": rep_main["P1_a"]["inputs"]["frame"]["md5"],
            "f2.parquet": rep_main["P1_b"]["inputs"]["frame"]["md5"],
            "run_toy.R": rep_main["P1_a"]["inputs"]["driver"]["md5"],
            "A.json": rep_evcl["P1evcl_a"]["inputs"]["ref"]["md5"]}
    lines = [ln for ln in (out / "payload.md5").read_text().splitlines() if ln.strip()]
    assert len(lines) == 4
    assert {ln.split("  ")[1]: ln.split("  ")[0] for ln in lines} == want
    # fetch/: byte copies of the cell outputs (not of the golds) and of the marker
    for name, st in (("A.json", w["st_main"]), ("B.json", w["st_main"]), ("C.json", w["st_evcl"])):
        assert (out / "fetch" / name).read_bytes() == (st / "estimates" / name).read_bytes()
    assert (out / "fetch" / "RESULT.txt").read_bytes() == w["marker"].read_bytes()
    spec = json.loads((out / "custody_r1.json").read_text())
    assert spec["task"] == "r1 rebuild custody" and spec["ok"] is True
    v = spec["verify"]
    assert v["require_marker"] == "OK"
    assert v["gold_dir"] == str(w["expected"].resolve())
    assert sorted(map(tuple, v["fetched_pairs"])) == [("A.json", "A.json"), ("B.json", "B.json"), ("C.json", "C.json")]
    assert all(pathlib.Path(local).is_absolute() for local, _ in v["frame_pairs"])
    assert sorted(map(tuple, v["frame_pairs"])) == sorted([
        (str((w["frames"] / "f1.csv").resolve()), "f1.csv"),
        (str((w["frames"] / "f2.parquet").resolve()), "f2.parquet"),
        (str((w["repo"] / DRV).resolve()), "run_toy.R"),
        (str((w["expected"] / "A.json").resolve()), "A.json")])
    r = _verify(out)
    assert r.returncode == 0 and r.stdout.rstrip().endswith("CUSTODY_OK"), r.stdout + r.stderr
    assert _lines(r.stdout, "BAD") == []
    assert len(_lines(r.stdout, "OK ")) == 1 + 4 + 3              # marker + 4 payload pairs + 3 fetched cells
    # verify_block joins ROOT with each path: absolute paths must not depend on ROOT (pathlib resets on an
    # absolute part), so the same spec verifies with ROOT pointed at an empty unrelated directory
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    r2 = _verify(out, root=elsewhere)
    assert r2.returncode == 0 and r2.stdout.rstrip().endswith("CUSTODY_OK"), r2.stdout + r2.stderr
    assert len(_lines(r2.stdout, "OK ")) == 8


def test_a_frame_changed_after_the_cells_gives_custody_fail(tmp_path):
    # (a) changed after the spec was written
    w = _world(tmp_path / "a")
    assert cs.main(w["argv"]) == 0
    with open(w["frames"] / "f2.parquet", "ab") as fh:
        fh.write(b"\x00")
    r = _verify(w["out"])
    assert r.returncode == 1 and r.stdout.rstrip().endswith("CUSTODY_FAIL"), r.stdout
    bad = _lines(r.stdout, "BAD")
    assert len(bad) == 1 and "f2.parquet" in bad[0]
    # (b) changed after the cells but BEFORE the spec: the writer takes the md5 recorded at cell time and
    # never re-hashes the frame, so the change is still caught
    w = _world(tmp_path / "b")
    (w["frames"] / "f1.csv").write_text("a,b\n1,3\n", encoding="utf-8")
    assert cs.main(w["argv"]) == 0
    r = _verify(w["out"])
    assert r.returncode == 1 and "CUSTODY_FAIL" in r.stdout
    assert any("f1.csv" in ln for ln in _lines(r.stdout, "BAD"))
    # (c) the driver changed between the cells and the check
    w = _world(tmp_path / "c")
    assert cs.main(w["argv"]) == 0
    (w["repo"] / DRV).write_text("# edited driver\n", encoding="utf-8")
    r = _verify(w["out"])
    assert r.returncode == 1 and any("run_toy.R" in ln for ln in _lines(r.stdout, "BAD"))


def test_a_gold_not_equal_to_the_fetched_cell_gives_custody_fail(tmp_path):
    w = _world(tmp_path / "a")
    assert cs.main(w["argv"]) == 0
    gold = json.loads((w["expected"] / "B.json").read_text())
    gold["ate"] = gold["ate"] + 1e-12
    (w["expected"] / "B.json").write_text(json.dumps(gold, indent=1) + "\n", encoding="utf-8")
    r = _verify(w["out"])
    assert r.returncode == 1 and r.stdout.rstrip().endswith("CUSTODY_FAIL"), r.stdout
    bad = _lines(r.stdout, "BAD")
    assert len(bad) == 1 and bad[0].startswith("BAD fetched") and "B.json" in bad[0]
    # a gold that is missing altogether
    w = _world(tmp_path / "b")
    assert cs.main(w["argv"]) == 0
    (w["expected"] / "C.json").unlink()
    r = _verify(w["out"])
    assert r.returncode == 1 and any("C.json missing" in ln for ln in _lines(r.stdout, "BAD"))
    # a gold that differs only in the ignored wall-clock key stays OK (the comparison is compare_json's)
    w = _world(tmp_path / "c")
    assert cs.main(w["argv"]) == 0
    gold = json.loads((w["expected"] / "A.json").read_text())
    gold["secs"] = 999.0
    (w["expected"] / "A.json").write_text(json.dumps(gold) + "\n", encoding="utf-8")
    # A.json is also the evcl reference: its md5 now differs from the record, so custody must FAIL on the
    # payload side while the fetched comparison stays OK
    r = _verify(w["out"])
    assert r.returncode == 1
    bad = _lines(r.stdout, "BAD")
    assert len(bad) == 1 and "expected/A.json" in bad[0] and not bad[0].startswith("BAD fetched")


def test_marker_not_ok_gives_custody_fail(tmp_path):
    w = _world(tmp_path / "a", marker_text="STAGE_FAIL cells_rmac_evcl boom\n")
    assert cs.main(w["argv"]) == 0
    r = _verify(w["out"])
    assert r.returncode == 1 and r.stdout.rstrip().endswith("CUSTODY_FAIL"), r.stdout
    bad = _lines(r.stdout, "BAD")
    assert len(bad) == 1 and "RESULT.txt" in bad[0]
    # no marker at all: the writer refuses and writes nothing
    w = _world(tmp_path / "b")
    w["marker"].unlink()
    assert cs.main(w["argv"]) == 1
    assert not w["out"].exists()


def test_writer_refuses_two_md5s_for_one_payload_name_and_a_missing_input_record(tmp_path, capsys):
    def refused(w, code):
        capsys.readouterr()
        assert cs.main(w["argv"]) == 1
        err = capsys.readouterr().err
        assert code in err, err
        assert not w["out"].exists()                       # nothing is written on a refusal

    def edit_report(path, fn):
        rep = json.loads(path.read_text())
        fn(rep)
        path.write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")

    # one payload name, two md5s: the evcl cell recorded other bytes for f1.csv than the main cell
    w = _world(tmp_path / "two")
    edit_report(w["st_evcl"] / "cells_report_rmac.json",
                lambda rep: rep["P1evcl_a"]["inputs"]["frame"].update(md5="0" * 32))
    refused(w, "TWO_MD5")
    # a gold row with no report entry
    w = _world(tmp_path / "noentry")
    edit_report(w["st_evcl"] / "cells_report_rmac.json", lambda rep: rep.pop("P1evcl_a"))
    refused(w, "MISSING_RECORD")
    # an entry without an inputs record (a report from before the run_cells change)
    w = _world(tmp_path / "noinputs")
    edit_report(w["st_main"] / "cells_report_rmac.json", lambda rep: rep["P1_b"].pop("inputs"))
    refused(w, "MISSING_RECORD")
    # a record with a null md5 (run_cells writes null hashes for a missing file)
    w = _world(tmp_path / "nullmd5")
    edit_report(w["st_main"] / "cells_report_rmac.json",
                lambda rep: rep["P1_a"]["inputs"]["driver"].update(md5=None, sha256=None))
    refused(w, "MISSING_RECORD")
    # the evcl ref record is missing although the row names a ref
    w = _world(tmp_path / "noref")
    edit_report(w["st_evcl"] / "cells_report_rmac.json", lambda rep: rep["P1evcl_a"]["inputs"].update(ref=None))
    refused(w, "MISSING_RECORD")
    # a record for another input than the cell list names
    w = _world(tmp_path / "name")
    edit_report(w["st_main"] / "cells_report_rmac.json",
                lambda rep: rep["P1_b"]["inputs"]["frame"].update(name="other.parquet"))
    refused(w, "NAME_MISMATCH")
    # a failed cell, and a cell whose output is missing
    w = _world(tmp_path / "failed")
    edit_report(w["st_main"] / "cells_report_rmac.json", lambda rep: rep["P1_b"].update(status="FAIL", rc=1))
    refused(w, "CELL_FAILED")
    w = _world(tmp_path / "noest")
    (w["st_main"] / "estimates" / "B.json").unlink()
    refused(w, "MISSING_ESTIMATE")
    # a non-empty --out is never written into
    w = _world(tmp_path / "exists")
    w["out"].mkdir()
    (w["out"] / "stale.json").write_text("{}", encoding="utf-8")
    capsys.readouterr()
    assert cs.main(w["argv"]) == 1
    assert "OUT_EXISTS" in capsys.readouterr().err
    assert sorted(p.name for p in w["out"].iterdir()) == ["stale.json"]


def _m_cell_lists(tmp: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """config/r1/cells/M.tsv + M_evcl.tsv. oct29.tsv cannot stand in for them: its two rcloud evcl rows carry no
    ref (October's cloud run passed none), while the M_evcl.tsv rows read their main cell."""
    m, e = REPO / "config/r1/cells/M.tsv", REPO / "config/r1/cells/M_evcl.tsv"
    assert m.is_file() and e.is_file()
    return m, e


def test_spec_lists_exactly_the_27_gold_rows(tmp_path):
    with open(REPO / "config/r1/cells/oct29.tsv", encoding="utf-8", newline="") as fh:
        oct29 = list(csv.DictReader(fh, delimiter="\t"))
    assert {r["label"] for r in oct29} >= set(SKIPPED)
    m_tsv, evcl_tsv = _m_cell_lists(tmp_path)
    with open(m_tsv, encoding="utf-8", newline="") as fh:
        m_rows = list(csv.DictReader(fh, delimiter="\t"))
    with open(evcl_tsv, encoding="utf-8", newline="") as fh:
        e_rows = list(csv.DictReader(fh, delimiter="\t"))
    gold_rows = m_rows + e_rows
    assert len(gold_rows) == 27
    paper = {ln.split()[-1] for ln in (REPO / "analysis/expected/MANIFEST.sha256").read_text().splitlines()
             if ln.strip().endswith(".json")}
    skipped_names = {r["out_name"] for r in oct29 if r["label"] in SKIPPED}
    assert {r["out_name"] for r in gold_rows} == paper - skipped_names

    # a toy world for every oct29 cell, the two skipped cells included (they ran, as in October), so the writer
    # must take its rows from the cell lists and nothing else
    T = tmp_path / "T"
    frames, expected, repo = T / "frames", T / "expected", tmp_path / "repo"
    frames.mkdir(parents=True)
    expected.mkdir(parents=True)
    for r in oct29:
        if not (frames / r["frame"]).exists():
            (frames / r["frame"]).write_text(f"toy {r['frame']}\n", encoding="utf-8")
        if not (repo / r["driver"]).exists():
            (repo / r["driver"]).parent.mkdir(parents=True, exist_ok=True)
            (repo / r["driver"]).write_text(f"# toy {r['driver']}\n", encoding="utf-8")
    stages, est = [], []
    evcl_labels = {r["label"] for r in e_rows}
    for stack in ("rmac", "rcloud"):
        # main: every oct29 cell of the stack but the M evcl ones (the skipped two included); evcl: the M evcl rows,
        # whose ref is the same run's main cell (oct29's rcloud evcl rows carry none)
        main = [r for r in oct29 if r["stack"] == stack and r["label"] not in evcl_labels]
        evcl = [r for r in e_rows if r["stack"] == stack]
        st_main, st_evcl = tmp_path / "j1a" / f"cells_{stack}", tmp_path / "j1a" / f"cells_{stack}_evcl"
        _run_stage(st_main, stack, main, frames=frames, repo=repo, refs_from=None)
        _run_stage(st_evcl, stack, evcl, frames=frames, repo=repo, refs_from=st_main / "estimates")
        stages += [st_main, st_evcl]
    gold_names = {r["out_name"] for r in gold_rows}
    for st in stages:                                       # the promotion copies only the 27 gold rows
        for p in sorted((st / "estimates").glob("*.json")):
            if p.name in gold_names:
                shutil.copyfile(p, expected / p.name)
    marker = tmp_path / "j1a" / "out" / "RESULT.txt"
    marker.parent.mkdir(parents=True)
    marker.write_text("OK\n", encoding="utf-8")
    out = tmp_path / "custody"
    argv = ["--cells", str(m_tsv), str(evcl_tsv), "--reports", *map(str, stages), "--est", *map(str, stages),
            "--frames-dir", str(frames), "--gold-dir", str(expected), "--drivers-root", str(repo),
            "--marker", str(marker), "--out", str(out)]
    assert cs.main(argv) == 0

    spec = json.loads((out / "custody_r1.json").read_text())
    fetched = [tuple(p) for p in spec["verify"]["fetched_pairs"]]
    assert len(fetched) == 27 and {a for a, _ in fetched} == gold_names and all(a == b for a, b in fetched)
    assert sorted(p.name for p in (out / "fetch").iterdir()) == sorted(gold_names | {"RESULT.txt"})
    want_payload = ({r["frame"] for r in gold_rows} | {pathlib.Path(r["driver"]).name for r in gold_rows}
                    | {r["ref"] for r in gold_rows if r["ref"] != "-"})
    payload = {ln.split()[-1] for ln in (out / "payload.md5").read_text().splitlines() if ln.strip()}
    assert payload == want_payload
    assert {name for _, name in spec["verify"]["frame_pairs"]} == want_payload
    blob = (out / "custody_r1.json").read_text() + (out / "payload.md5").read_text()
    assert "old79" not in blob and "new37" not in blob
    r = _verify(out)
    assert r.returncode == 0 and r.stdout.rstrip().endswith("CUSTODY_OK"), r.stdout + r.stderr
    assert len(_lines(r.stdout, "OK ")) == 1 + len(spec["verify"]["frame_pairs"]) + 27


# ---------------------------------------------------------------------------------------------
# The record committed in the repository: only the rcloud cells, paths relative to the repository root

def _read_tsv(path: pathlib.Path) -> list:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def _verify_from_root(repo: pathlib.Path, custody_rel: str) -> subprocess.CompletedProcess:
    """The real `verify_cloud_custody.py --custody <rel> --spec <rel>/custody_r1.json` command, run from the root of
    the repository at `repo`. --root points the script at that repository, as if the script lived there."""
    cmd = [PY, str(VERIFY), "--root", str(repo), "--custody", custody_rel, "--spec", f"{custody_rel}/custody_r1.json"]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=repo)


def _refused(argv) -> str:
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert cs.main(argv) == 1
    return err.getvalue()


def test_relative_rcloud_record_verifies_from_the_root_of_a_fresh_copy(tmp_path):
    m_tsv, evcl_tsv = REPO / "config/r1/cells/M.tsv", REPO / "config/r1/cells/M_evcl.tsv"
    m_rows, e_rows = _read_tsv(m_tsv), _read_tsv(evcl_tsv)
    rcloud = [r for r in m_rows + e_rows if r["stack"] == "rcloud"]
    assert len(m_rows + e_rows) == 27 and len(rcloud) == 4

    # the repository as committed: canon frames and golds under data/report, the drivers at their usual paths
    repo = tmp_path / "repo"
    frames, expected = repo / "data/report/frames", repo / "data/report/expected"
    frames.mkdir(parents=True)
    expected.mkdir(parents=True)
    for r in m_rows + e_rows:
        if not (frames / r["frame"]).exists():
            (frames / r["frame"]).write_text(f"toy {r['frame']}\n", encoding="utf-8")
        if not (repo / r["driver"]).exists():
            (repo / r["driver"]).parent.mkdir(parents=True, exist_ok=True)
            (repo / r["driver"]).write_text(f"# toy {r['driver']}\n", encoding="utf-8")
    # the fetched cell records, outside the repository; all 27 cells ran
    fetched = tmp_path / "fetched"
    stages = {}
    for stack in ("rmac", "rcloud"):
        st_main, st_evcl = fetched / f"cells_{stack}", fetched / f"cells_{stack}_evcl"
        _run_stage(st_main, stack, [r for r in m_rows if r["stack"] == stack], frames=frames, repo=repo,
                   refs_from=None)
        _run_stage(st_evcl, stack, [r for r in e_rows if r["stack"] == stack], frames=frames, repo=repo,
                   refs_from=st_main / "estimates")
        stages[stack] = [st_main, st_evcl]
    all_stages = stages["rmac"] + stages["rcloud"]
    for st in all_stages:                                      # the golds are byte copies of the cell outputs
        for p in sorted((st / "estimates").glob("*.json")):
            shutil.copyfile(p, expected / p.name)
    marker = fetched / "out" / "RESULT.txt"
    marker.parent.mkdir(parents=True)
    marker.write_text("OK\n", encoding="utf-8")
    custody_rel = "data/report/custody"
    out = repo / custody_rel
    argv = ["--cells", str(m_tsv), str(evcl_tsv), "--stack", "rcloud", "--relative-to", str(repo),
            "--reports", *map(str, all_stages), "--est", *map(str, all_stages), "--frames-dir", str(frames),
            "--gold-dir", str(expected), "--drivers-root", str(repo), "--marker", str(marker), "--out", str(out)]
    assert cs.main(argv) == 0

    spec = json.loads((out / "custody_r1.json").read_text())
    v = spec["verify"]
    # only the rcloud cells
    names = sorted(r["out_name"] for r in rcloud)
    assert sorted(a for a, _ in v["fetched_pairs"]) == names and all(a == b for a, b in v["fetched_pairs"])
    assert sorted(p.name for p in (out / "fetch").iterdir()) == sorted(names + ["RESULT.txt"])
    assert spec["n_cells"] == 4
    # repo-relative paths: frames and refs under data/report, the drivers at their repository paths
    assert v["gold_dir"] == "data/report/expected"
    want_pairs = ({(f"data/report/frames/{r['frame']}", r["frame"]) for r in rcloud}
                  | {(r["driver"], pathlib.PurePosixPath(r["driver"]).name) for r in rcloud}
                  | {(f"data/report/expected/{r['ref']}", r["ref"]) for r in rcloud if r["ref"] != "-"})
    assert len(want_pairs) == 8                                # 4 frames, 2 drivers, 2 refs
    assert sorted(map(tuple, v["frame_pairs"])) == sorted(want_pairs)
    blob = (out / "custody_r1.json").read_text() + (out / "payload.md5").read_text()
    assert str(tmp_path) not in blob and str(tmp_path.resolve()) not in blob
    # payload md5s are the rcloud cells' own records
    recorded = {}
    for st in stages["rcloud"]:
        for entry in json.loads((st / "cells_report_rcloud.json").read_text()).values():
            for rec in entry["inputs"].values():
                if rec is not None:
                    recorded[pathlib.PurePosixPath(rec["name"]).name] = rec["md5"]
    payload = {ln.split("  ")[1]: ln.split("  ")[0]
               for ln in (out / "payload.md5").read_text().splitlines() if ln.strip()}
    assert payload == recorded

    # a fresh copy of the repository, with the original tree and the fetched records gone
    clone = tmp_path / "clone"
    shutil.copytree(repo, clone)
    shutil.rmtree(repo)
    shutil.rmtree(fetched)
    res = _verify_from_root(clone, custody_rel)
    assert res.returncode == 0 and res.stdout.rstrip().endswith("CUSTODY_OK"), res.stdout + res.stderr
    assert _lines(res.stdout, "BAD") == []
    assert len(_lines(res.stdout, "OK ")) == 1 + 8 + 4           # marker + 8 payload pairs + 4 fetched cells
    # the paths point into the copy: one changed byte there fails
    frame = next(r["frame"] for r in rcloud)
    with open(clone / "data/report/frames" / frame, "ab") as fh:
        fh.write(b"\x00")
    res = _verify_from_root(clone, custody_rel)
    assert res.returncode == 1 and res.stdout.rstrip().endswith("CUSTODY_FAIL"), res.stdout + res.stderr
    bad = _lines(res.stdout, "BAD")
    assert len(bad) == 1 and f"data/report/frames/{frame}" in bad[0]


def test_relative_and_stack_refusals_write_nothing(tmp_path):
    # the toy world's frames and golds lie outside its repository
    w = _world(tmp_path / "outside")
    assert "NOT_IN_REPO" in _refused(w["argv"] + ["--relative-to", str(w["repo"])])
    assert not w["out"].exists()
    # no row of the cell lists has that stack
    w = _world(tmp_path / "nostack")
    assert "BAD_CELLS" in _refused(w["argv"] + ["--stack", "rcloud"])
    assert not w["out"].exists()
