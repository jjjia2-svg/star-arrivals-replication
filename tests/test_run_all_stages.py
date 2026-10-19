# -*- coding: utf-8 -*-
"""tests/test_run_all_stages.py - analysis/run_all.sh and analysis/lib/run_all_stages.py.

Stubs only. run_all.sh runs in a toy skeleton (a tmp directory holding a copy of the script) with
`python3`, `Rscript` and `Rscript_rcloud` stubs first on PATH. The stubs log their argv as JSON lines
and run nothing, except that the python3 stub hands analysis/lib/run_all_stages.py (and, when a test
asks for it, tools/compare_all.py) to the real interpreter. Those read only the toy canons built in
tmp_path, the cell lists in config/r1/cells and the bytes of the R drivers, or resolve the October
roots without opening a data file. Every run's output root lies in tmp_path: an October paths config
with its output moved there, or a toy canon's. No R runs, no estimation runs, no real frame is read
and nothing is written inside the clone.

The default run (no flags) of the October version must make the stage 2 calls the oct29.tsv rows give,
in their order; tests/test_r1_cells.py holds the 25 cells run_all.sh ran when it still listed them
itself, so the two together pin today's commands without any git history.
"""
from __future__ import annotations

import csv
import hashlib
import json
import lzma
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(REPO), str(REPO / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from analysis.lib import canon  # noqa: E402
from analysis.lib import run_all_stages as ras  # noqa: E402
from analysis.lib.paths import load_paths  # noqa: E402
import r1_canon  # noqa: E402
import r1_custody_spec  # noqa: E402

SCRIPT = REPO / "analysis" / "run_all.sh"
HELPER = REPO / "analysis" / "lib" / "run_all_stages.py"
CELLS_DIR = REPO / "config" / "r1" / "cells"
TIMEOUT = 300

# ---- stubs ------------------------------------------------------------------------------------------
STUB = r'''
import json, os, sys
tool, argv = sys.argv[1], sys.argv[2:]
with open(os.environ["STUB_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps([tool] + argv) + "\n")
fail = os.environ.get("STUB_FAIL", "")
if fail and fail in " ".join(argv):
    sys.exit(1)
out = os.environ.get("STUB_OUT") or "output"
def gap(script):
    stem = os.path.splitext(os.path.basename(script))[0]
    d = os.path.join(out, "paper")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, stem + ".json"), "w") as fh:
        fh.write(json.dumps({"stub": stem}) + "\n")
def real(rel):
    py = os.environ["STUB_REAL_PY"]
    os.execv(py, [py, os.path.join(os.environ["STUB_REAL_REPO"], *rel.split("/"))] + argv[1:])
if tool == "python3":
    if argv[:1] == ["-"]:
        sys.stdin.read()
        sys.exit(0)
    if argv[:1] == ["-c"]:
        print(os.environ.get("STUB_LEGACY", "/nonexistent/stub-root"))
        sys.exit(0)
    if argv and argv[0].endswith("run_all_stages.py"):
        real("analysis/lib/run_all_stages.py")
    base = os.path.basename(argv[0]) if argv else ""
    if base == "compare_all.py" and os.environ.get("STUB_REAL_COMPARE"):
        real("tools/compare_all.py")
    if base == "check_paper.py":
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "paper_check.md"), "w") as fh:
            fh.write("1 checks: 1 PASS, 0 FAIL\n")
    elif base.startswith("gaps_"):
        gap(argv[0])
    sys.exit(0)
# Rscript, and Rscript_rcloud (the second R stack)
if argv[:1] == ["-e"]:
    sys.stdout.write("4.4.0")
    sys.exit(0)
if os.environ.get("STUB_ENV_LOG"):
    keys = ("R_LIBS", "R_PROFILE_USER", "R_DATATABLE_NUM_THREADS", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
            "POLARS_MAX_THREADS")
    env = {k: os.environ.get(k) for k in keys}
    env["PATH0"] = os.environ.get("PATH", "").split(os.pathsep)[0]
    with open(os.environ["STUB_ENV_LOG"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps([tool, argv[1] if len(argv) > 1 else "", env]) + "\n")
script = argv[0] if argv else ""
if "estimation" in script.split("/"):
    with open(os.path.join(os.environ["SAR_OUT"], argv[1] + ".json"), "w") as fh:
        fh.write(json.dumps({"label": argv[1]}) + "\n")
elif os.path.basename(script).startswith("gaps_"):
    gap(script)
sys.exit(0)
'''
TOOLS = ("python3", "Rscript", "Rscript_rcloud")


def _stubs(tmp_path: pathlib.Path) -> pathlib.Path:
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True)
    (bindir / "stub.py").write_text(STUB, encoding="utf-8")
    for tool in TOOLS:
        p = bindir / tool
        p.write_text(f'#!/bin/bash\nexec "$STUB_REAL_PY" "$STUB_DIR/stub.py" {tool} "$@"\n', encoding="utf-8")
        p.chmod(0o755)
    return bindir


def _skeleton(tmp_path: pathlib.Path, text: str | None = None) -> pathlib.Path:
    sk = tmp_path / "sk"
    if sk.exists():
        shutil.rmtree(sk)
    (sk / "analysis").mkdir(parents=True)
    (sk / "analysis" / "run_all.sh").write_text(text if text is not None else SCRIPT.read_text(encoding="utf-8"),
                                                 encoding="utf-8")
    return sk


def _write_cfg(d: dict, out: pathlib.Path) -> pathlib.Path:
    """A paths yaml, every value a double-quoted string (r1_canon.write_paths_yaml's form)."""
    out.write_text("".join(f"{k}: {json.dumps(str(v), ensure_ascii=False)}\n" for k, v in d.items()), encoding="utf-8")
    return out


def october_cfg(tmp_path: pathlib.Path, output=None) -> pathlib.Path:
    """config/paths_october.yaml with its output root moved into tmp_path (the six canon keys untouched)."""
    d = yaml.safe_load((REPO / "config" / "paths_october.yaml").read_text(encoding="utf-8"))
    d["output"] = str(pathlib.Path(output) if output is not None else tmp_path / "oct_out")
    return _write_cfg(d, tmp_path / "paths_october_tmp.yaml")


class Toy:
    """A skeleton + stubs; .run(args, cfg=..., out=..., fail=..., cwd=...) -> (CompletedProcess, [log rows]).
    Without cfg the run reads the October version with its output root in tmp_path (never the clone's); without
    cwd it starts in the skeleton."""

    def __init__(self, tmp_path: pathlib.Path, text: str | None = None):
        self.tmp = tmp_path
        self.bindir = _stubs(tmp_path)
        self.sk = _skeleton(tmp_path, text)
        self.log = tmp_path / "stub.log"
        self.oct_out = tmp_path / "oct_out"
        self.oct_cfg = october_cfg(tmp_path, self.oct_out)
        self.legacy = tmp_path / "legacy"
        (self.legacy / "thesis_report").mkdir(parents=True, exist_ok=True)

    def run(self, args, cfg=None, out=None, fail=None, extra_env=None, cwd=None):
        if self.log.exists():
            self.log.unlink()
        self.log.touch()
        env = dict(os.environ)
        env.update(PATH=f"{self.bindir}{os.pathsep}{env.get('PATH', '')}", STUB_LOG=str(self.log),
                   STUB_DIR=str(self.bindir), STUB_REAL_PY=sys.executable, STUB_REAL_REPO=str(REPO),
                   STUB_LEGACY=str(self.legacy), SAR_PATHS_CONFIG=str(cfg if cfg is not None else self.oct_cfg))
        for k in ("STUB_OUT", "STUB_FAIL", "STUB_REAL_COMPARE", "STUB_ENV_LOG", "RUN_PAPER", "RUN_CLOUD_CELLS",
                  "SAR_RSCRIPT_RCLOUD", "SAR_RLIB_RCLOUD"):
            env.pop(k, None)
        if out is not None:
            env["STUB_OUT"] = str(out)
        if fail is not None:
            env["STUB_FAIL"] = fail
        env.update(extra_env or {})
        r = subprocess.run(["bash", str(self.sk / "analysis" / "run_all.sh"), *args], cwd=cwd or self.sk,
                           env=env, capture_output=True, text=True, timeout=TIMEOUT)
        rows = [json.loads(ln) for ln in self.log.read_text(encoding="utf-8").splitlines() if ln.strip()]
        return r, rows


# ---- cell lists and toy M canons -----------------------------------------------------------------------
FIELDS = ("econ", "chemistry", "math_stats")
FRAMES = [f"p1_frame_{f}.csv" for f in FIELDS] + [f"p2_becoming_{f}.csv" for f in FIELDS] + ["relationships_econ.csv"]
GOLDS = ["P1_econ_fnfix.json", "P1_fnfix_chemistry.json", "P1_fnfix_math_stats.json",
         "P2_econ_fnfix.json", "P2_fnfix_chemistry.json", "P2_fnfix_math_stats.json"]
CAL = ["frames_econ/build_report_econ920_2026-10.json", "frames_econ/star_set_econ_cal2026-10.parquet"]
GAPS = ("gaps_zenou", "gaps_switchers", "gaps_toy", "gaps_switchers_p1p2")
COUNTS_M = {"schema": "sar.r1.counts.v1", "config": "M", "events": {"econ": 2, "chemistry": 1, "math_stats": 1},
            "events_total": 4, "candidates": 5}
PACKED_REL = "cal_intermediates/pairs_unified.csv"


def cell_rows(*names) -> list[dict]:
    rows = []
    for n in names:
        with open(CELLS_DIR / n, encoding="utf-8", newline="") as fh:
            rows += list(csv.DictReader(fh, delimiter="\t"))
    return rows


def oct_rows() -> list[dict]:
    return cell_rows("oct29.tsv")


def m_rows() -> list[dict]:
    return cell_rows("M.tsv", "M_evcl.tsv")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _rec(path: pathlib.Path, name: str) -> dict:
    """The input record pipeline/aws/r1/run_cells.py keeps for one cell input."""
    b = path.read_bytes()
    return {"name": name, "sha256": _sha(b), "md5": hashlib.md5(b).hexdigest()}


def _custody(root: pathlib.Path) -> None:
    """<root>/custody for the four rcloud cells, written by tools/r1_custody_spec.py from toy cell records
    (the cells' outputs are the golds, byte for byte; the drivers are this repository's)."""
    rec = root.parent / f"{root.name}_cell_records"
    report = {}
    for r in (r for r in m_rows() if r["stack"] == "rcloud"):
        est = rec / "estimates" / r["out_name"]
        est.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / "expected" / r["out_name"], est)
        report[r["label"]] = {"rc": 0, "status": "RAN", "inputs": {
            "frame": _rec(root / "frames" / r["frame"], r["frame"]),
            "ref": None if r["ref"] == "-" else _rec(root / "expected" / r["ref"], r["ref"]),
            "driver": _rec(REPO / r["driver"], r["driver"])}}
    (rec / "cells_report_rcloud.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    marker = rec / "RESULT.txt"
    marker.write_text("OK\n", encoding="utf-8")
    argv = ["--cells", str(CELLS_DIR / "M.tsv"), str(CELLS_DIR / "M_evcl.tsv"), "--stack", "rcloud",
            "--reports", str(rec), "--est", str(rec), "--frames-dir", str(root / "frames"),
            "--gold-dir", str(root / "expected"), "--drivers-root", str(REPO), "--marker", str(marker),
            "--out", str(root / "custody")]
    assert r1_custody_spec.main(argv) == 0


def toy_canon(tmp_path: pathlib.Path, name: str = "canon_a", output=None, ssd_root=None, cells=False, packed=None):
    """An out-of-repo M canon with tiny toy files, cal/counts.json, its MANIFESTs and a paths yaml selecting it.
    cells=True adds every frame and gold of the M cell lists (an rmac gold is what the Rscript stub writes) and
    the custody folder of the four rcloud cells; packed=<bytes> ships cal_intermediates/pairs_unified.csv
    xz-compressed and listed in PACKED.tsv, as the committed canon does. Returns (canon root, paths yaml, output)."""
    root = tmp_path / name
    for k in canon.KEYS:
        (root / k).mkdir(parents=True)
    frames = {f: f"toy frame {f}\n" for f in FRAMES}
    golds = {g: json.dumps({"toy": g}) + "\n" for g in GOLDS}
    if cells:
        for r in m_rows():
            frames.setdefault(r["frame"], f"toy frame {r['frame']}\n")
            golds[r["out_name"]] = (json.dumps({"label": r["label"]}) + "\n" if r["stack"] == "rmac"
                                    else json.dumps({"label": r["label"], "ate": -0.25}, indent=1) + "\n")
    for f, text in frames.items():
        (root / "frames" / f).write_text(text, encoding="utf-8")
    for g, text in golds.items():
        (root / "expected" / g).write_text(text, encoding="utf-8")
    for c in CAL:
        (root / "cal" / c).parent.mkdir(parents=True, exist_ok=True)
        (root / "cal" / c).write_text(f"toy {c}\n", encoding="utf-8")
    (root / "cal" / canon.COUNTS).write_text(json.dumps(COUNTS_M) + "\n", encoding="utf-8")
    if packed is not None:
        (root / PACKED_REL).write_bytes(packed)
    (root / canon.CANON_JSON).write_text(json.dumps({"schema": canon.SCHEMA, "canon": "M",
                                                     "prefix": dict(canon.DEFAULT_PREFIX), "switches": {}}) + "\n",
                                         encoding="utf-8")
    r1_canon.write_manifests(root)
    if packed is not None:      # the MANIFEST pins the csv; the canon ships its xz copy and PACKED.tsv
        (root / (PACKED_REL + ".xz")).write_bytes(lzma.compress(packed))
        (root / PACKED_REL).unlink()
        (root / "PACKED.tsv").write_text(f"path\tpacked\tsha256\n{PACKED_REL}\t{PACKED_REL}.xz\t{_sha(packed)}\n",
                                         encoding="utf-8")
    if cells:
        _custody(root)
    out = pathlib.Path(output) if output is not None else tmp_path / f"{name}_out"
    cfg = r1_canon.write_paths_yaml(root, tmp_path / f"{name}.yaml", output=out)
    if ssd_root is not None:
        d = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        d["ssd_root"] = str(ssd_root)
        cfg.write_text(yaml.safe_dump(d, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return root, cfg, out


# ---- log helpers ----------------------------------------------------------------------------------------
def _idx(rows, pred, start=0):
    for i in range(start, len(rows)):
        if pred(rows[i]):
            return i
    raise AssertionError(f"no matching stub call after row {start} in {rows}")


def _ras(rows, sub):
    return lambda r: r[0] == "python3" and len(r) > 2 and r[1].endswith("run_all_stages.py") and r[2] == sub


def _py(name):
    return lambda r: r[0] == "python3" and len(r) > 1 and os.path.basename(r[1]) == name


def _base(r):
    return os.path.basename(r[1]) if len(r) > 1 else ""


def _gen_calls(rows):
    """The generator calls (paper/estimation scripts, the sentinel) as (tool, basename, rest)."""
    out = []
    for r in rows:
        if len(r) < 2 or r[1] in ("-", "-c", "-e") or r[1].endswith("run_all_stages.py"):
            continue
        out.append((r[0], _base(r), r[2:]))
    return out


def _helpers(rows):
    return [r[2] for r in rows if r[0] == "python3" and len(r) > 2 and r[1].endswith("run_all_stages.py")]


def _cells_run(rows):
    """The estimation calls (Rscript or the second stack's Rscript_rcloud on an analysis/estimation driver)."""
    return [r for r in rows if r[0] in ("Rscript", "Rscript_rcloud") and len(r) > 1 and "estimation" in r[1].split("/")]


def _cmd(tool, row, ex):
    """The stage 2 call of one cell row: <tool> <driver> <label> <D>/<frame> [<X>/<ref>]."""
    return [tool, row["driver"], row["label"], f"{ex['D']}/{row['frame']}"] + (
        [] if row["ref"] == "-" else [f"{ex['X']}/{row['ref']}"])


def _status_lines(stdout):
    return [ln.split()[0] for ln in stdout.splitlines()
            if ln.split()[:1] and ln.split()[0] in ("EQUAL", "DIFF", "MISSING", "VERIFIED_NOT_RERUN")]


# ==== 1. no flags: stages 1 and 2 of the canon in force ====================================================
def test_no_flag_runs_stages_1_and_2_of_the_october_canon_from_the_oct29_rows(tmp_path):
    toy = Toy(tmp_path)
    r, rows = toy.run([])
    assert r.returncode == 0, (r.stdout[-3000:], r.stderr[-3000:])
    lines = r.stdout.splitlines()
    # the canon and its event counts come first
    assert lines[0].startswith("== canon: october"), lines[:3]
    assert lines[1].strip() == "events: 184 (economics 113, chemistry 38, mathematics and statistics 33)", lines[:3]
    assert _helpers(rows) == ["env", "describe", "cells"]
    # stage 1: the two October MANIFESTs; stage 2: the 25 rmac rows of oct29.tsv in their order, then compare_all
    ex = ras.exports(load_paths(toy.oct_cfg))
    rmac = [x for x in oct_rows() if x["stack"] == "rmac"]
    assert _cells_run(rows) == [_cmd("Rscript", x, ex) for x in rmac] and len(rmac) == 25
    names = [b for _t, b, _a in _gen_calls(rows)]
    assert names == ["verify_manifest.py", "verify_manifest.py"] + [pathlib.Path(x["driver"]).name for x in rmac] \
        + ["compare_all.py"], names
    # each result is saved under its row's out_name (the P3cut cells are renamed to the gold's name)
    assert sorted(p.name for p in (toy.oct_out / "estimates").iterdir()) == sorted(x["out_name"] for x in rmac)
    # the four large cells are announced, not run; the paper stage is opt-in
    for x in (x for x in oct_rows() if x["stack"] == "rcloud"):
        assert f"== {x['label']}: " in r.stdout, x["label"]
    assert "RUN_PAPER=1" in r.stdout
    assert not any(b in ("check_paper.py", "ledger_p3afar.py") for b in names)


def test_run_paper_adds_the_paper_stage_after_stages_1_and_2(tmp_path):
    toy = Toy(tmp_path)
    r, rows = toy.run([], extra_env={"RUN_PAPER": "1"})
    assert r.returncode == 0, (r.stdout[-3000:], r.stderr[-3000:])
    names = [b for _t, b, _a in _gen_calls(rows)]
    body = SCRIPT.read_text(encoding="utf-8").split('echo "== paper =="', 1)[1]
    want = [os.path.basename(m.group(1)) for m in
            re.finditer(r'^run paper_\w+\s+(?:"\$PY"|Rscript)\s+(\S+)', body, re.M)]
    assert want[0] == "ledger_p3afar.py" and want[-1] == "check_paper.py"
    assert names[names.index("compare_all.py") + 1:] == want
    assert not any("--tree" in a for _t, _b, a in _gen_calls(rows))
    assert "fig_compare_years.py" not in names and "fig_comparison_pools.py" not in names


#: the generators whose default tree reads cells a canon tree does not hold; there only the base tree runs
BASE_TREE_ONLY = ("ledger_p3afar.py", "fig_p1.py", "fig_p2.py", "tables_robustness.py", "draft_2026_09_13_tables.py")


def test_run_paper_on_a_canon_tree_runs_stages_3est_3light_and_4check(tmp_path):
    """On a canon tree the October form of the paper stage cannot run (the robustness tables' default tree
    reads cells the canon does not hold), so RUN_PAPER=1 runs the staged form, as --stages 1,2,3est,3light,4check."""
    root, cfg, out = toy_canon(tmp_path)
    toy = Toy(tmp_path)
    r, rows = toy.run([], cfg=cfg, out=out, extra_env={"RUN_PAPER": "1"})
    calls = _gen_calls(rows)
    for _t, b, a in calls:
        if b in BASE_TREE_ONLY:
            assert a[:2] == ["--tree", "base_2026_10_11"], (b, a)
    assert r.returncode == 0, (r.stdout[-3000:], r.stderr[-3000:])
    helpers = _helpers(rows)
    assert helpers == ["env", "describe", "unpack", "verify-manifests", "cells", "seal", "check-no-ssd",
                       "check-seal"], helpers
    names = [b for _t, b, _a in calls]
    assert names.index("compare_all.py") < names.index("gaps_zenou.py") and names[-1] == "check_paper.py", names
    assert "== stages: 1 2 3est 3light 4check ==" in r.stdout.splitlines()
    # exactly the calls of the staged run
    r2, rows2 = toy.run(["--stages", "1,2,3est,3light,4check"], cfg=cfg, out=out)
    assert r2.returncode == 0, (r2.stdout[-3000:], r2.stderr[-3000:])
    assert calls == _gen_calls(rows2) and helpers == _helpers(rows2)


def test_a_paper_stage_without_the_manuscript_tree_stops_before_stage_1(tmp_path):
    root, cfg, out = toy_canon(tmp_path)
    toy = Toy(tmp_path)
    gone = {"STUB_LEGACY": str(tmp_path / "no_such_tree")}
    for args, c, o, extra in (([], None, None, {"RUN_PAPER": "1"}), (["--stages", "3est"], cfg, out, {}),
                              (["--stages", "1,4check"], cfg, out, {})):
        r, rows = toy.run(args, cfg=c, out=o, extra_env={**gone, **extra})
        assert r.returncode == 4, (args, r.stdout[-2000:], r.stderr[-2000:])
        assert "MISSING" in r.stdout and "manuscript" in r.stdout, args
        assert _gen_calls(rows) == [], (args, _gen_calls(rows))
        assert "verify-manifests" not in _helpers(rows) and "unpack" not in _helpers(rows), args
    # stages 1 and 2 need no manuscript; RUN_PAPER does not apply to --stages
    r, rows = toy.run(["--stages", "1"], extra_env={**gone, "RUN_PAPER": "1"})
    assert r.returncode == 0, (r.stdout[-2000:], r.stderr[-2000:])
    assert [b for _t, b, _a in _gen_calls(rows)] == ["verify_manifest.py", "verify_manifest.py"]


def test_a_relative_paths_config_is_read_from_the_directory_the_run_starts_in(tmp_path):
    """SAR_PATHS_CONFIG may be relative to where the run starts (run_all.sh then changes to the repository);
    a value that names no file stops the run with a message that says so, never a traceback."""
    toy = Toy(tmp_path)
    start = toy.oct_cfg.parent.resolve()   # tmp_path, spelled as bash's $PWD: not the repository
    r, rows = toy.run(["--stages", "1"], cwd=start, extra_env={"SAR_PATHS_CONFIG": toy.oct_cfg.name})
    assert r.returncode == 0, (r.stdout[-2000:], r.stderr[-2000:])
    assert r.stdout.splitlines()[0].startswith("== canon: october"), r.stdout[:300]
    assert [b for _t, b, _a in _gen_calls(rows)] == ["verify_manifest.py", "verify_manifest.py"]
    for bad in ("no_such_paths.yaml", str(start / "no_such_paths.yaml")):
        r, rows = toy.run(["--stages", "1"], cwd=start, extra_env={"SAR_PATHS_CONFIG": bad})
        assert r.returncode == 6, (bad, r.stdout[-2000:], r.stderr[-2000:])
        assert "PATHS_CONFIG_ERROR" in r.stdout and "SAR_PATHS_CONFIG" in r.stdout and "CANON_ERROR" not in r.stdout, \
            (bad, r.stdout)
        assert str(start / "no_such_paths.yaml") in r.stderr and "Traceback" not in r.stderr, (bad, r.stderr)
        assert _gen_calls(rows) == [] and _helpers(rows) == ["env"], (bad, rows)
    # the helper itself refuses a relative or missing value with that message (exit 3), not a traceback
    for bad, why in (("config/paths_october.yaml", "absolute"), (str(start / "no_such_paths.yaml"), "does not exist")):
        cli = subprocess.run([sys.executable, str(HELPER), "env"], env={**os.environ, "SAR_PATHS_CONFIG": bad},
                             cwd=REPO, capture_output=True, text=True)
        assert cli.returncode == 3 and cli.stdout == "", (bad, cli.stdout, cli.stderr)
        assert cli.stderr.startswith("PATHS_CONFIG_ERROR") and why in cli.stderr and "Traceback" not in cli.stderr, \
            (bad, cli.stderr)


# ==== 2. subset order and unknown names ==================================================================
@pytest.mark.parametrize("args", [["--stages", "1,bogus"], ["--stages"], ["--stages", ""], ["--stages", "1,,3est"],
                                  ["--frobnicate"], ["--stages", "3"]])
def test_unknown_stage_or_argument_gives_usage_and_exit_2_before_anything_runs(tmp_path, args):
    toy = Toy(tmp_path)
    r, rows = toy.run(args)
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert "usage" in r.stderr.lower()
    assert rows == [], "nothing may run before the arguments are accepted"


def test_stages_subset_keeps_order_and_unknown_stage_is_refused(tmp_path):
    toy = Toy(tmp_path)
    r, rows = toy.run(["--stages", "1,bogus"])
    assert r.returncode == 2 and "usage" in r.stderr.lower() and rows == []

    root, cfg, out = toy_canon(tmp_path)
    r, rows = toy.run(["--stages", "4check,3est,1"], cfg=cfg, out=out)
    assert r.returncode == 0, (r.stdout[-3000:], r.stderr[-3000:])
    i_env = _idx(rows, _ras(rows, "env"))
    i_un = _idx(rows, _ras(rows, "unpack"), i_env)
    i_vm = _idx(rows, _ras(rows, "verify-manifests"), i_un)
    i_cc = _idx(rows, lambda x: x[0] == "python3" and len(x) > 2 and x[1].endswith("r1_canon.py") and x[2] == "check", i_vm)
    assert rows[i_cc][3] == str(root.resolve())
    i_gaps = [_idx(rows, lambda x, g=g: os.path.splitext(_base(x))[0] == g, i_cc) for g in GAPS]
    i_seal = _idx(rows, _ras(rows, "seal"), max(i_gaps))
    i_chk = _idx(rows, _py("check_paper.py"), i_seal)
    assert i_env < i_un < i_vm < i_cc < min(i_gaps) and max(i_gaps) < i_seal < i_chk
    names = [b for _t, b, _a in _gen_calls(rows)]
    for absent in ("run_p1.R", "run_p2.R", "run_p3_tp.R", "compare_all.py", "verify_manifest.py",
                   "ledger_p3afar.py", "ledger_main.py", "tables_robustness.py", "draft_2026_09_13_tables.py"):
        assert absent not in names, absent
    assert not any(_ras(rows, s)(x) for x in rows for s in ("check-seal", "check-no-ssd", "cells"))


# ==== 3. stage 2 on a canon tree: 23 cells re-run, 4 custody-checked ===========================================
def test_m_stage_2_reruns_23_cells_and_custody_checks_the_4_large_ones(tmp_path):
    pairs = b"author_a,author_b,year\nA5000000001,A5000000002,2006\n"
    root, cfg, out = toy_canon(tmp_path, cells=True, packed=pairs)
    (out / "estimates").mkdir(parents=True)
    (out / "estimates" / "P3_econ_fnfix.json").write_text('{"stale": "left by an earlier run"}\n', encoding="utf-8")
    (out / "estimates" / "old_cell.json").write_text("{}\n", encoding="utf-8")
    toy = Toy(tmp_path)
    r, rows = toy.run([], cfg=cfg, out=out, extra_env={"STUB_REAL_COMPARE": "1"})
    assert r.returncode == 0, (r.stdout[-4000:], r.stderr[-3000:])
    lines = r.stdout.splitlines()
    assert lines[0].startswith("== canon: M") and str(root.resolve()) in lines[0], lines[:3]
    assert lines[1].strip() == "events: 4 (economics 2, chemistry 1, mathematics and statistics 1)", lines[:3]
    # stage 1 unpacks first, then the MANIFESTs and the canon check
    assert _helpers(rows)[:5] == ["env", "describe", "unpack", "verify-manifests", "cells"], _helpers(rows)
    assert (root / PACKED_REL).read_bytes() == pairs
    i_cc = _idx(rows, lambda x: x[0] == "python3" and len(x) > 2 and x[1].endswith("r1_canon.py") and x[2] == "check")
    assert _idx(rows, _ras(rows, "verify-manifests")) < i_cc < _idx(rows, _ras(rows, "cells"))
    # stage 2: the 23 rmac rows of M.tsv then M_evcl.tsv, from the canon's frames and recorded estimates
    ex = ras.exports(load_paths(cfg))
    rmac = [x for x in m_rows() if x["stack"] == "rmac"]
    assert _cells_run(rows) == [_cmd("Rscript", x, ex) for x in rmac] and len(rmac) == 23
    i_ca = _idx(rows, _py("compare_all.py"))
    assert i_ca > max(i for i, x in enumerate(rows) if x in _cells_run(rows))
    # compare_all: 23 EQUAL, the 4 large cells VERIFIED_NOT_RERUN through their custody record
    st = _status_lines(r.stdout)
    assert len(st) == 27 and st.count("EQUAL") == 23 and st.count("VERIFIED_NOT_RERUN") == 4, st
    assert "ALL_EQUAL" in lines
    assert "CUSTODY_OK" in (out / "logs" / "custody.log").read_text(encoding="utf-8")
    # the stale results are gone: only this run's 23 results are in the output folder
    assert sorted(p.name for p in (out / "estimates").iterdir()) == sorted(x["out_name"] for x in rmac)
    rep = (out / "compare_report.md").read_text(encoding="utf-8")
    assert "| P3_econ_fnfix.json | VERIFIED_NOT_RERUN |" in rep
    for x in (x for x in m_rows() if x["stack"] == "rcloud"):
        assert f"== {x['label']}: " in r.stdout, x["label"]
    assert not any(_base(x) == "check_paper.py" for x in rows)

    # --stages 2 alone runs too (no refusal on a canon tree)
    r, rows = toy.run(["--stages", "2"], cfg=cfg, out=out, extra_env={"STUB_REAL_COMPARE": "1"})
    assert r.returncode == 0 and "ALL_EQUAL" in r.stdout.splitlines(), (r.stdout[-3000:], r.stderr[-2000:])
    assert len(_cells_run(rows)) == 23 and "unpack" not in _helpers(rows)


def test_a_result_left_in_the_output_folder_is_never_compared(tmp_path):
    """Without the clean start a stale large-cell result would be compared (DIFF) instead of custody-checked."""
    root, cfg, out = toy_canon(tmp_path, cells=True)
    toy = Toy(tmp_path)
    (out / "estimates").mkdir(parents=True)
    stale = out / "estimates" / "P3evcl_econ.json"
    stale.write_text('{"label": "P3evcl_econ", "ate": 9}\n', encoding="utf-8")
    r, _ = toy.run(["--stages", "2"], cfg=cfg, out=out, extra_env={"STUB_REAL_COMPARE": "1"})
    assert r.returncode == 0, (r.stdout[-3000:], r.stderr[-2000:])
    assert not stale.exists()
    assert "| P3evcl_econ.json | VERIFIED_NOT_RERUN |" in (out / "compare_report.md").read_text(encoding="utf-8")


# ==== 4. the large cells under the second R stack ============================================================
def test_run_cloud_cells_needs_the_second_r_stack(tmp_path):
    toy = Toy(tmp_path)
    lib = tmp_path / "rlib"
    lib.mkdir()
    rs = str(toy.bindir / "Rscript_rcloud")
    for extra in ({}, {"SAR_RSCRIPT_RCLOUD": rs}, {"SAR_RLIB_RCLOUD": str(lib)},
                  {"SAR_RSCRIPT_RCLOUD": str(tmp_path / "no_such_Rscript"), "SAR_RLIB_RCLOUD": str(lib)},
                  {"SAR_RSCRIPT_RCLOUD": rs, "SAR_RLIB_RCLOUD": str(tmp_path / "no_such_lib")}):
        r, rows = toy.run([], extra_env={"RUN_CLOUD_CELLS": "1", **extra})
        assert r.returncode == 7, (extra, r.stdout[-2000:], r.stderr[-2000:])
        assert "SAR_RSCRIPT_RCLOUD" in r.stderr and "SAR_RLIB_RCLOUD" in r.stderr, (extra, r.stderr)
        assert rows == [], "nothing may run before the second R stack is found"
    # only stage 2 needs it
    r, _ = toy.run(["--stages", "1"], extra_env={"RUN_CLOUD_CELLS": "1"})
    assert r.returncode == 0, (r.stdout[-2000:], r.stderr[-2000:])
    # RUN_CLOUD_CELLS and RUN_PAPER take 0 or 1
    for k in ("RUN_CLOUD_CELLS", "RUN_PAPER"):
        r, rows = toy.run([], extra_env={k: "yes"})
        assert r.returncode == 2 and k in r.stderr and rows == [], (k, r.stderr)


def test_run_cloud_cells_reruns_the_four_large_cells_under_the_second_stack(tmp_path):
    toy = Toy(tmp_path)
    lib = tmp_path / "rlib_rcloud"
    lib.mkdir()
    env_log = tmp_path / "env.log"
    # the caller's own R settings, set here so the test does not depend on the host's (t-0058: the AWS test
    # host exports R_PROFILE_USER=/dev/null, and the local-stack cells inherit it, as they should)
    caller = {"R_PROFILE_USER": str(tmp_path / "caller_Rprofile"), "R_LIBS": str(tmp_path / "caller_rlib")}
    r, rows = toy.run([], extra_env={"RUN_CLOUD_CELLS": "1", "SAR_RSCRIPT_RCLOUD": str(toy.bindir / "Rscript_rcloud"),
                                     "SAR_RLIB_RCLOUD": str(lib), "STUB_ENV_LOG": str(env_log), **caller})
    assert r.returncode == 0, (r.stdout[-3000:], r.stderr[-3000:])
    ex = ras.exports(load_paths(toy.oct_cfg))
    want = [_cmd("Rscript" if x["stack"] == "rmac" else "Rscript_rcloud", x, ex) for x in oct_rows()]
    assert _cells_run(rows) == want and len(want) == 29
    envs = [json.loads(ln) for ln in env_log.read_text(encoding="utf-8").splitlines()]
    stack = {x["label"]: x["stack"] for x in oct_rows()}
    assert sorted(lab for _t, lab, _e in envs) == sorted(stack)
    for tool, label, e in envs:
        if stack[label] == "rcloud":
            # as pipeline/aws/r1/run_cells.py runs a cell: that stack's library only, no profile, 32 threads
            assert tool == "Rscript_rcloud" and e["R_LIBS"] == str(lib) and e["R_PROFILE_USER"] == "/dev/null", e
            assert all(e[k] == "32" for k in ("R_DATATABLE_NUM_THREADS", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                                              "POLARS_MAX_THREADS")), e
            assert e["PATH0"] == str(toy.bindir), e
        else:
            # the local stack runs with the caller's environment untouched
            assert tool == "Rscript" and (e["R_PROFILE_USER"], e["R_LIBS"]) == (caller["R_PROFILE_USER"], caller["R_LIBS"]), e
    assert sorted(p.name for p in (toy.oct_out / "estimates").iterdir()) == sorted(x["out_name"] for x in oct_rows())


# ==== 5. 3light needs the 3est outputs ====================================================================
def test_3light_refuses_missing_3est_outputs(tmp_path):
    root, cfg, out = toy_canon(tmp_path)
    toy = Toy(tmp_path)
    r, rows = toy.run(["--stages", "3light"], cfg=cfg, out=out)
    assert r.returncode == 4, (r.stdout, r.stderr)
    assert any(_ras(rows, "check-seal")(x) for x in rows)
    assert not any(_base(x) == "ledger_p3afar.py" for x in rows), "a 3light generator ran without a seal"

    r, _ = toy.run(["--stages", "3est"], cfg=cfg, out=out)
    assert r.returncode == 0, (r.stdout, r.stderr)
    seal = out / "paper" / "3est.seal.json"
    assert seal.is_file()
    (out / "paper" / "gaps_toy.json").unlink()
    r, rows = toy.run(["--stages", "3light"], cfg=cfg, out=out)
    assert r.returncode == 4, (r.stdout, r.stderr)
    assert not any(_base(x) == "ledger_p3afar.py" for x in rows)

    # a seal that does not hold every required 3est output is refused as well
    P = load_paths(cfg)
    gaps = [out / "paper" / f"{g}.json" for g in GAPS]
    gaps[2].write_text("{}\n")
    inputs = [root / "frames" / f for f in FRAMES]
    ras.seal(seal, gaps[:2] + gaps[3:], inputs, P=P)
    probs = ras.check_seal(seal, require=gaps, P=P)
    assert any("gaps_toy" in p for p in probs), probs
    ras.seal(seal, gaps, inputs, P=P)
    assert ras.check_seal(seal, require=gaps, P=P) == []
    with pytest.raises(ras.SealError):
        ras.seal(seal, gaps + [out / "paper" / "no_such.json"], inputs, P=P)


def test_3light_runs_the_light_generators_in_the_no_flag_order(tmp_path):
    root, cfg, out = toy_canon(tmp_path)
    toy = Toy(tmp_path)
    r, rows = toy.run(["--stages", "3est,3light"], cfg=cfg, out=out)
    assert r.returncode == 0, (r.stdout[-3000:], r.stderr[-3000:])
    i_ssd = _idx(rows, _ras(rows, "check-no-ssd"))
    i_chk = _idx(rows, _ras(rows, "check-seal"), i_ssd)
    assert i_ssd > _idx(rows, _ras(rows, "seal"))
    light = [(b, a) for _t, b, a in _gen_calls(rows[i_chk + 1:])]
    O = pathlib.Path(load_paths(cfg)["output"]).resolve()
    base = ["--tree", "base_2026_10_11"]   # ledger_p3afar / fig_p1 / fig_p2 draw the base tree's Figures 7, 5, 6
    assert light == [
        ("ledger_p3afar.py", base), ("tables_p3afar.py", []), ("ledger_main.py", []), ("ledger_carried.py", []),
        ("fig_compare_years.py", []), ("fig_comparison_pools.py", []),
        ("gaps_zero_dose.py", []), ("ledger_funnel.py", []), ("fig_exposure_population.py", []),
        ("fig_dose_distribution.py", []), ("fig_hops.py", []), ("fig_star_origins.py", []), ("tables_main.py", []),
        ("ledger_p1p2.py", []), ("tables_p1p2.py", []), ("fig_p1.py", base), ("fig_p2.py", base),
        ("ledger_robustness.py", []), ("tables_robustness.py", ["--tree", "base_2026_10_11"]),
        ("draft_2026_09_13_tables.py", ["--tree", "base_2026_10_11", "--paper-dir", str(O / "paper"),
                                        "--out-dir", str(O / "paper" / "draft_2026_09_13")]),
    ], light
    est = [b for _t, b, _a in _gen_calls(rows[:i_ssd])]
    assert est == ["gaps_zenou.py", "gaps_switchers.R", "gaps_toy.R", "gaps_switchers_p1p2.R"], est


def test_keep_going_runs_every_light_generator_and_names_each_failure(tmp_path):
    """final-02 (M) stopped at its first failing generator, and that generator's log stayed on the instance. With
    KEEP_GOING=1 the later generators still run and the run exits 2 at the end, naming every failed step; without
    it the first failure stops the run, as before."""
    root, cfg, out = toy_canon(tmp_path)
    toy = Toy(tmp_path)
    r, rows = toy.run(["--stages", "3est,3light"], cfg=cfg, out=out, fail="ledger_carried.py")
    names = [b for _t, b, _a in _gen_calls(rows)]
    assert r.returncode == 2 and "FAILED, see output/logs/paper_ledger_carried.log" in r.stdout
    assert names[-1] == "ledger_carried.py", names
    r, rows = toy.run(["--stages", "3est,3light"], cfg=cfg, out=out, fail="ledger_carried.py",
                      extra_env={"KEEP_GOING": "1"})
    names = [b for _t, b, _a in _gen_calls(rows)]
    assert r.returncode == 2 and names[-1] == "draft_2026_09_13_tables.py", (r.stdout[-2000:], names)
    assert "FAILED_STEPS paper_ledger_carried" in r.stdout.splitlines()


# ==== 6. a stale seal or one from another canon ============================================================
def test_3light_refuses_a_stale_or_other_canon_seal(tmp_path):
    root, cfg, out = toy_canon(tmp_path, "canon_a")
    root_b, cfg_b, _ = toy_canon(tmp_path, "canon_b", output=out)   # same content and output, another canon
    toy = Toy(tmp_path)

    def est():
        r, _ = toy.run(["--stages", "3est"], cfg=cfg, out=out)
        assert r.returncode == 0, (r.stdout, r.stderr)

    def light(c=cfg):
        r, rows = toy.run(["--stages", "3light"], cfg=c, out=out)
        return r.returncode, rows

    est()
    rc, rows = light()
    assert rc == 0 and any(_base(x) == "ledger_p3afar.py" for x in rows)

    (out / "paper" / "gaps_switchers.json").write_text('{"edited": "after the seal"}\n')     # output edited
    rc, rows = light()
    assert rc == 4 and not any(_base(x) == "ledger_p3afar.py" for x in rows)

    est()
    frame = root / "frames" / "p1_frame_econ.csv"
    orig = frame.read_bytes()
    frame.write_bytes(orig + b"one more row\n")                                             # frame edited
    rc, _ = light()
    assert rc == 4
    frame.write_bytes(orig)

    est()
    rc, rows = light(cfg_b)                                                                   # another canon
    assert rc == 4 and not any(_base(x) == "ledger_p3afar.py" for x in rows)
    probs = ras.check_seal(out / "paper" / "3est.seal.json", P=load_paths(cfg_b))
    assert any("canon" in p for p in probs), probs

    cj = root / canon.CANON_JSON                                                              # same root, new CANON.json
    meta = json.loads(cj.read_text())
    meta["switches"] = {"p_full_precision": True}
    cj.write_text(json.dumps(meta) + "\n")
    rc, _ = light()
    assert rc == 4


# ==== 7. data-disk roots ===================================================================================
def test_3light_refuses_data_disk_paths(tmp_path, monkeypatch):
    toy = Toy(tmp_path)
    # the canon itself on the configured data disk
    root = tmp_path / "canon_a"
    _, cfg, out = toy_canon(tmp_path, "canon_a", ssd_root=root)
    r, rows = toy.run(["--stages", "3est,3light"], cfg=cfg, out=out)
    assert r.returncode == 5, (r.stdout, r.stderr)
    assert not any(_base(x) == "ledger_p3afar.py" for x in rows)
    probs = ras.check_no_ssd(load_paths(cfg))
    assert {p.split()[0] for p in probs} >= {"CANON", "D", "X"}, probs

    # the output root under /Volumes (refused before the seal is even looked at)
    vol = pathlib.Path("/Volumes") / "sar-r1-test-no-such-disk" / "out"
    _, cfg_v, _ = toy_canon(tmp_path, "canon_v", output=vol)
    r, rows = toy.run(["--stages", "3light"], cfg=cfg_v)
    assert r.returncode == 5, (r.stdout, r.stderr)
    assert not any(_ras(rows, "check-seal")(x) for x in rows)
    assert [p.split()[0] for p in ras.check_no_ssd(load_paths(cfg_v))] == ["O"]

    # $SAR_SSD_ROOT counts as the data disk too
    _, cfg_e, _ = toy_canon(tmp_path, "canon_e")
    assert ras.check_no_ssd(load_paths(cfg_e)) == []
    monkeypatch.setenv("SAR_SSD_ROOT", str(tmp_path))
    assert {p.split()[0] for p in ras.check_no_ssd(load_paths(cfg_e))} >= {"CANON", "D", "X", "O"}
    monkeypatch.delenv("SAR_SSD_ROOT")
    assert ras.check_no_ssd(load_paths()) == []      # the October roots of this clone


# ==== 8. stage 1 ==========================================================================================
def test_stage_1_checks_the_canon_manifests(tmp_path):
    toy = Toy(tmp_path)
    # October: the two MANIFESTs the default run checks, nothing else (nothing is packed)
    r, rows = toy.run(["--stages", "1"])
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert [(b, a) for _t, b, a in _gen_calls(rows)] == [
        ("verify_manifest.py", []), ("verify_manifest.py", ["analysis/expected/MANIFEST.sha256"])]
    assert "unpack" not in _helpers(rows)
    r, rows = toy.run(["--stages", "1"], fail="analysis/expected/MANIFEST.sha256")
    assert r.returncode == 1 and "MANIFEST_FAIL" in r.stdout

    # M: unpack, then every line of the MANIFEST of each of the six canon key folders, then tools/r1_canon.py check
    root, cfg, out = toy_canon(tmp_path)
    P = load_paths(cfg)
    assert ras.verify_manifests(P) == []      # raw_verified, paper_inputs, cal_intermediates empty: nothing to pin
    toys = ("raw_verified/rosters/toy_roster.csv", "paper_inputs/toy_input.json", "cal_intermediates/toy_pairs.csv")
    for rel in toys:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(f"toy {rel}\n", encoding="utf-8")
    r1_canon.write_manifests(root)
    r, rows = toy.run(["--stages", "1"], cfg=cfg, out=out)
    assert r.returncode == 0, (r.stdout, r.stderr)
    i_un = _idx(rows, _ras(rows, "unpack"))
    i_vm = _idx(rows, _ras(rows, "verify-manifests"), i_un)
    i_cc = _idx(rows, lambda x: len(x) > 2 and x[1].endswith("r1_canon.py") and x[2] == "check", i_vm)
    assert rows[i_cc][3:] == [str(root.resolve())]
    assert not any(_base(x) == "verify_manifest.py" for x in rows)
    log = (toy.sk / "output" / "logs" / "manifest.log").read_text(encoding="utf-8")
    assert log.splitlines()[-1] == "MANIFEST_OK " + " ".join(canon.KEYS), log
    assert ras.verify_manifests(P) == []

    # a changed file in any key folder stops the run, also one that no analysis/lib/canon_reads.tsv row names
    for rel in ("frames/p2_becoming_chemistry.csv", "expected/P2_fnfix_math_stats.json",
                "cal/frames_econ/build_report_econ920_2026-10.json") + toys:
        f = root / rel
        orig = f.read_bytes()
        f.write_bytes(orig[:-1] + bytes([orig[-1] ^ 1]))
        r, rows = toy.run(["--stages", "1"], cfg=cfg, out=out)
        assert r.returncode == 1 and "MANIFEST_FAIL" in r.stdout, rel
        assert not any(len(x) > 1 and x[1].endswith("r1_canon.py") for x in rows), rel
        assert any(rel in p for p in ras.verify_manifests(P)), rel
        f.write_bytes(orig)
    assert ras.verify_manifests(P) == []

    for key in ("expected", "paper_inputs"):             # a missing MANIFEST
        (root / key / canon.MANIFEST).unlink()
        r, _ = toy.run(["--stages", "1"], cfg=cfg, out=out)
        assert r.returncode == 1, key
        assert any(p.startswith(f"{key}: no MANIFEST") for p in ras.verify_manifests(P)), key
        r1_canon.write_manifests(root)

    r1_canon.write_manifests(root)
    r, _ = toy.run(["--stages", "1"], cfg=cfg, out=out, fail="r1_canon.py")
    assert r.returncode == 1 and "CANON_FAIL" in r.stdout


# ==== 9. unpack ==============================================================================================
def test_unpack_restores_the_packed_files_and_refuses_a_wrong_sha256(tmp_path):
    pairs = b"author_a,author_b,year\nA5000000001,A5000000002,2006\n"
    root, cfg, out = toy_canon(tmp_path, packed=pairs)
    P = load_paths(cfg)
    dest, xz, packed = root / PACKED_REL, root / (PACKED_REL + ".xz"), root / "PACKED.tsv"
    good, xzb = packed.read_text(encoding="utf-8"), xz.read_bytes()

    def leftovers():
        return sorted(p.name for p in dest.parent.iterdir() if p.name not in (dest.name, xz.name, canon.MANIFEST))

    assert not dest.exists()
    msgs = ras.unpack(P)
    assert dest.read_bytes() == pairs and len(msgs) == 1 and msgs[0].startswith("UNPACKED"), msgs
    assert leftovers() == []
    # the restored file is the one the canon's own MANIFEST pins
    assert canon.read_manifest(root / "cal_intermediates" / canon.MANIFEST)[PACKED_REL] == canon.sha256(dest)
    assert ras.unpack(P)[0].startswith("KEPT")
    dest.write_bytes(b"edited by hand\n")                        # a changed copy is replaced by the checked one
    assert ras.unpack(P)[0].startswith("UNPACKED") and dest.read_bytes() == pairs

    # a wrong sha256 in PACKED.tsv: refused, nothing renamed into place, no temporary file left
    dest.unlink()
    packed.write_text(good.replace(_sha(pairs), "0" * 64), encoding="utf-8")
    with pytest.raises(ras.UnpackError, match="sha256"):
        ras.unpack(P)
    assert not dest.exists() and leftovers() == []
    cli = subprocess.run([sys.executable, str(HELPER), "unpack"], env={**os.environ, "SAR_PATHS_CONFIG": str(cfg)},
                         capture_output=True, text=True)
    assert cli.returncode == 1 and "UNPACK_FAIL" in cli.stdout, (cli.stdout, cli.stderr)
    # run_all.sh stage 1 stops there, before it reads a MANIFEST
    toy = Toy(tmp_path)
    r, rows = toy.run(["--stages", "1"], cfg=cfg, out=out)
    assert r.returncode == 1 and "UNPACK_FAIL" in r.stdout, (r.stdout, r.stderr)
    assert "verify-manifests" not in _helpers(rows)

    # a damaged or missing xz copy, a path outside the canon, a malformed header
    packed.write_text(good, encoding="utf-8")
    xz.write_bytes(xzb[: len(xzb) // 2])
    with pytest.raises(ras.UnpackError):
        ras.unpack(P)
    assert not dest.exists() and leftovers() == []
    xz.unlink()
    with pytest.raises(ras.UnpackError, match="missing"):
        ras.unpack(P)
    xz.write_bytes(xzb)
    for bad in (good.replace(f"\n{PACKED_REL}\t", "\n../outside.csv\t"), good.replace(f"\n{PACKED_REL}\t", "\n/abs.csv\t"),
                good.replace(".csv.xz\t", ".csv.gz\t"), "path\tsha256\n", good.replace(_sha(pairs), "not-a-sha")):
        packed.write_text(bad, encoding="utf-8")
        with pytest.raises(ras.UnpackError):
            ras.unpack(P)
    assert not dest.exists() and not (root.parent / "outside.csv").exists()
    packed.write_text(good, encoding="utf-8")
    assert ras.unpack(P)[0].startswith("UNPACKED") and dest.read_bytes() == pairs

    # nothing listed: nothing to do; the October version ships nothing packed
    packed.unlink()
    assert ras.unpack(P) == []
    assert ras.unpack(load_paths(october_cfg(tmp_path))) == []


def test_unpack_accepts_the_final_job_pack_and_checks_both_sizes_and_hashes(tmp_path):
    pairs = b"author_a,author_b,year\nA5000000001,A5000000002,2006\n"
    root, cfg, _ = toy_canon(tmp_path, packed=pairs)
    P = load_paths(cfg)
    dest, xz = root / PACKED_REL, root / (PACKED_REL + ".xz")
    packed = root / "PACKED.tsv"
    xzb = xz.read_bytes()
    header = "path\tsha256\tbytes\txz_sha256\txz_bytes\n"
    row = [PACKED_REL, _sha(pairs), str(len(pairs)), _sha(xzb), str(len(xzb))]

    def write(values):
        packed.write_text(header + "\t".join(values) + "\n", encoding="utf-8")

    write(row)
    assert ras.packed_rows(root)[0]["src"] == xz
    assert ras.unpack(P)[0].startswith("UNPACKED") and dest.read_bytes() == pairs
    dest.unlink()
    for col, bad in ((1, "0" * 64), (2, str(len(pairs) + 1)), (3, "0" * 64),
                     (4, str(len(xzb) + 1)), (2, "-1"), (4, "bad")):
        values = row.copy()
        values[col] = bad
        write(values)
        with pytest.raises(ras.UnpackError):
            ras.unpack(P)
        assert not dest.exists() and not dest.with_name(dest.name + ".unpacking").exists()
    write(row)
    assert ras.unpack(P)[0].startswith("UNPACKED")


def test_shipped_packed_table_has_the_final_job_schema():
    root = REPO / "data" / "report"
    rows = ras.packed_rows(root)
    assert len(rows) == 1 and rows[0]["path"] == PACKED_REL
    assert rows[0]["bytes"] == 481997636
    assert rows[0]["xz_bytes"] == rows[0]["src"].stat().st_size


def test_pipeline_defaults_to_the_october_paths_config():
    text = (REPO / "pipeline" / "run_all.sh").read_text(encoding="utf-8")
    line = 'export SAR_PATHS_CONFIG="${SAR_PATHS_CONFIG:-$REPO/config/paths_october.yaml}"'
    assert line in text
    assert text.index(line) < text.index('SSD_ROOT=')


# ==== 10. the unpacked copies stay out of git =================================================================
#: (target, xz copy) of the report canon's packed files; its PACKED.tsv lists them once data/report is committed
PACKED_IN_REPO = (
    ("data/report/cal_intermediates/pairs_unified.csv", "data/report/cal_intermediates/pairs_unified.csv.xz"),
)


def _git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)


def _ignored(rel: str) -> bool:
    r = _git("check-ignore", "--no-index", "-q", "--", rel)
    assert r.returncode in (0, 1), (rel, r.stderr)
    return r.returncode == 0


def test_an_unpacked_copy_is_ignored_by_git_and_its_xz_copy_is_not():
    """Stage 1 writes each PACKED.tsv target into the committed canon tree. That file is packed because it is
    too large to commit, so no `git add` may ever stage it; the .xz copy it is restored from is committed."""
    if _git("rev-parse", "--is-inside-work-tree").returncode != 0:
        pytest.skip("not a git work tree")
    pairs = set(PACKED_IN_REPO)
    for rel in filter(None, _git("ls-files", "-z", "--", ":(glob)data/**/PACKED.tsv").stdout.split("\0")):
        for r in ras.packed_rows((REPO / rel).parent):
            pairs.add((r["dest"].relative_to(REPO).as_posix(), r["src"].relative_to(REPO).as_posix()))
    for target, xz in sorted(pairs):
        assert _ignored(target), f"{target} (restored by stage 1) is not ignored by git"
        assert _ignored(target + ".unpacking"), f"{target}.unpacking (an interrupted unpack) is not ignored by git"
        assert not _ignored(xz), f"{xz} (the committed copy) is ignored by git"
    # the rest of the canon tree is committed
    for rel in ("data/report/PACKED.tsv", "data/report/CANON.json", "data/report/frames/p1_frame_econ.csv",
                "data/report/cal_intermediates/MANIFEST.sha256", "data/report/expected/P1_econ_fnfix.json",
                "data/report/raw_verified/MANIFEST.sha256"):
        assert not _ignored(rel), f"{rel} is ignored by git"


# ==== the helper's commands ===================================================================================
def test_env_exports_the_canon_roots(tmp_path):
    oct_ = ras.exports(load_paths())
    assert oct_["CANON_NAME"] == "october"
    assert oct_["D"] == str(canon.root("frames")) and oct_["X"] == str(canon.root("expected"))
    assert oct_["CANON"] == str(canon.root("cal").parent)
    root, cfg, out = toy_canon(tmp_path)
    m = ras.exports(load_paths(cfg))
    assert m == {"D": str((root / "frames").resolve()), "X": str((root / "expected").resolve()),
                 "CAL": str((root / "cal").resolve()), "O": str(out.resolve()),
                 "CANON": str(root.resolve()), "CANON_NAME": "M"}
    r = subprocess.run([sys.executable, str(HELPER), "env"],
                       env={**os.environ, "SAR_PATHS_CONFIG": str(cfg)}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = subprocess.run(["bash", "-c", r.stdout + '\nprintf "%s|%s|%s" "$D" "$CANON" "$CANON_NAME"'],
                         capture_output=True, text=True).stdout
    assert got == f"{m['D']}|{m['CANON']}|M"


def test_cells_lists_the_rows_of_the_canon_in_force(tmp_path, monkeypatch):
    assert ras.cells(load_paths(october_cfg(tmp_path))) == oct_rows() and len(oct_rows()) == 29
    root, cfg, out = toy_canon(tmp_path)
    m = ras.cells(load_paths(cfg))
    assert m == m_rows()
    assert sum(x["stack"] == "rmac" for x in m) == 23 and sum(x["stack"] == "rcloud" for x in m) == 4
    r = subprocess.run([sys.executable, str(HELPER), "cells"], env={**os.environ, "SAR_PATHS_CONFIG": str(cfg)},
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["\t".join(ras.CELL_COLUMNS)] + ["\t".join(x[c] for c in ras.CELL_COLUMNS) for x in m]

    # a malformed cell list stops the run (CANON_ERROR, exit 6)
    good = (CELLS_DIR / "oct29.tsv").read_text(encoding="utf-8")
    header, first = good.splitlines()[:2]
    bad_dir = tmp_path / "bad_cells"
    bad_dir.mkdir()
    monkeypatch.setattr(ras, "CELLS_DIR", bad_dir)
    P = load_paths(october_cfg(tmp_path))
    for bad in (good.replace("\trmac\n", "\tgpu\n", 1), good.replace(header, header.replace("out_name", "out")),
                good + first + "\n", good.replace("analysis/estimation/run_p1.R", "../run_p1.R", 1),
                good.replace("\tp1_frame_econ.csv\t", "\tdata/p1_frame_econ.csv\t", 1),
                good.replace("analysis/estimation/run_p1.R", "analysis/estimation/no_such.R", 1),
                good.replace("\tP1_econ_fnfix.json\trmac", "\tP1 econ.json\trmac", 1)):
        (bad_dir / "oct29.tsv").write_text(bad, encoding="utf-8")
        with pytest.raises(canon.CanonError):
            ras.cells(P)
    r = subprocess.run([sys.executable, "-c", "import sys; sys.argv = ['x', 'cells']; "
                        "from analysis.lib import run_all_stages as r; import pathlib; "
                        f"r.CELLS_DIR = pathlib.Path({str(bad_dir)!r}); sys.exit(r.main())"],
                       env={**os.environ, "SAR_PATHS_CONFIG": str(october_cfg(tmp_path))}, cwd=REPO,
                       capture_output=True, text=True)
    assert r.returncode == 6 and "CANON_ERROR" in r.stderr, (r.stdout, r.stderr)


def test_describe_names_the_canon_and_its_event_counts(tmp_path):
    lines = ras.describe(load_paths(october_cfg(tmp_path)))
    assert lines[0].startswith("== canon: october") and lines[1].strip() == \
        "events: 184 (economics 113, chemistry 38, mathematics and statistics 33)", lines
    root, cfg, out = toy_canon(tmp_path)
    lines = ras.describe(load_paths(cfg))
    assert lines[0].startswith("== canon: M") and str(root.resolve()) in lines[0], lines
    assert lines[1].strip() == "events: 4 (economics 2, chemistry 1, mathematics and statistics 1)", lines
    (root / "cal" / canon.COUNTS).unlink()
    with pytest.raises(canon.CanonError):
        ras.describe(load_paths(cfg))


def test_compare_all_reads_the_same_cell_lists_and_canon_rule(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("compare_all_t", REPO / "tools" / "compare_all.py")
    ca = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ca)   # type: ignore[union-attr]
    assert ca.CELL_LISTS == ras.CELL_LISTS
    oct_P = load_paths(october_cfg(tmp_path))
    root, cfg, out = toy_canon(tmp_path)
    for P in (oct_P, load_paths(cfg)):
        assert ca.mode(P) == canon.mode(P)
        assert ca.cloud_only(P) == {x["out_name"] for x in ras.cells(P) if x["stack"] == "rcloud"}
    assert ca.cloud_only(oct_P) == {"P3_econ_fnfix.json", "P3_fnfix_chemistry.json", "P3evcl_econ.json",
                                    "P3evcl_chemistry.json"}


def test_stage_2_spells_repo_paths_relative_to_the_repository():
    """Inside the clone the cell commands keep today's spelling (data/frames/..., analysis/expected/...)."""
    text = SCRIPT.read_text(encoding="utf-8")
    m = re.search(r"^rel\(\) \{.*\}$", text, re.M)
    assert m, "run_all.sh defines rel() on one line"
    probe = (m.group(0) + '\nREPO_P=/r/repo\nrel /r/repo/data/frames; rel /r/repo2/x; rel /elsewhere/frames; '
             'rel /r/repo/analysis/expected\n')
    got = subprocess.run(["bash", "-c", probe], capture_output=True, text=True).stdout.splitlines()
    assert got == ["data/frames", "/r/repo2/x", "/elsewhere/frames", "analysis/expected"], got


def test_the_entry_points_carry_no_internal_ids():
    tooling = REPO / "tools" / "public_export"
    if not (tooling / "scan_public.py").is_file():
        pytest.skip("needs the export tooling (tools/public_export), which the public copy does not ship")
    sys.path.insert(0, str(tooling))
    import scan_public   # noqa: PLC0415
    more = re.compile(r"\bF\d{1,2}\b|FIG567|\bN\d{1,2}\b|\bR\d #|MILESTONE REVIEW|\bR1 P3\b|\bW\d\b")
    for rel in sorted(scan_public.ENTRY_POINTS):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert not scan_public.PROCID_RX.findall(text), (rel, scan_public.PROCID_RX.findall(text))
        assert not more.findall(text), (rel, more.findall(text))
        assert not [mk for mk in scan_public.MARKERS if mk in text], rel
