# -*- coding: utf-8 -*-
"""final review #5: gaps_zero_dose.py under an M canon (small runner, toy data only).

The §3 zero-dose shares (sec3_strategy.tex "8 percent of relations in economics, 6 in chemistry, 31 in
mathematics") are asserted against the October thesis integers in the October canon only. Under an M
canon the generator reports each share next to its October value (`_october`, `_diff_vs_october`,
underscore metadata that tools/r1_number_diff.py skips) and exits 0, so the sentinel D pins and
replace.py repin the sentence (the gaps_zenou N11 pattern). An M frame with no non-NULL dose is
'MISSING INPUT', exit 1, no JSON.

The M tests build a tiny canon in tmp (CANON.json, cal/counts.json, the prefix MANIFESTs written by
tools/r1_canon.py), select it with $SAR_PATHS_CONFIG and re-root `output` into tmp. The October test
copies the generator and analysis/lib/{paths,canon}.py into a tmp tree (load_paths() always takes the
repo root from the module's own location, so the tmp tree IS the repo root there) with the six October
roots under it. Nothing under the real October roots is read or written. October byte identity on the
real frames is tests/test_r1_canon_generators.py (big host) and
tests/test_paper_ledgers.py::test_gaps_zero_dose_rounds_to_thesis.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from analysis.lib import canon  # noqa: E402

GEN = REPO / "analysis" / "paper" / "gaps_zero_dose.py"
TOOL = REPO / "tools" / "r1_canon.py"
_spec = importlib.util.spec_from_file_location("r1_canon_tool_zero_dose", TOOL)
r1c = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(r1c)   # type: ignore[union-attr]

FIELDS = {"econ": "econ", "chem": "chemistry", "math": "math_stats"}
OCTOBER = {"econ": 8, "chem": 6, "math": 31}
# relations (person, event, dose); every relation is written for two years, so DISTINCT matters.
# econ: 1 of 4 non-NULL relations at zero (P_E has no dose) = 25.0; chem 0 of 2 = 0.0; math 1 of 2 = 50.0
REL = {"econ": [("P_A", "E1", 0.0), ("P_B", "E1", 0.4), ("P_C", "E1", 0.7), ("P_D", "E2", 0.2),
                ("P_E", "E2", None)],
       "chem": [("P_A", "E1", 0.3), ("P_B", "E1", 0.5)],
       "math": [("P_A", "E1", 0.0), ("P_B", "E1", 0.9)]}
TOY = {"econ": 25.0, "chem": 0.0, "math": 50.0}


def _frames(frames_dir: pathlib.Path, rel=None) -> None:
    frames_dir.mkdir(parents=True, exist_ok=True)
    for d, f in FIELDS.items():
        with open(frames_dir / f"p1_frame_{f}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(["event_id", "incumbent_person_id", "year", "dose_topic"])
            for pid, ev, dose in (rel or REL)[d]:
                for yr in (2015, 2016):
                    w.writerow([ev, pid, yr, "" if dose is None else dose])


def build_m(tmp_path, rel=None):
    """A toy M canon at tmp/canon plus a paths yaml selecting it (output re-rooted to tmp/out)."""
    root = tmp_path / "canon"
    for k in canon.KEYS:
        (root / k).mkdir(parents=True, exist_ok=True)
    (root / "CANON.json").write_text(json.dumps(
        {"schema": "sar.r1.canon.v1", "canon": "M", "prefix": {k: k for k in canon.KEYS}, "switches": {}},
        indent=1), encoding="utf-8")
    (root / "cal" / "counts.json").write_text(json.dumps(
        {"schema": "sar.r1.counts.v1", "config": "M", "events": {"econ": 2, "chemistry": 1, "math_stats": 1},
         "events_total": 4, "candidates": 187}), encoding="utf-8")
    _frames(root / "frames", rel)
    r1c.write_manifests(root)
    out = tmp_path / "out"
    cfg = r1c.write_paths_yaml(root, tmp_path / "paths_m.yaml", output=out)
    return root, cfg, out


def run(script: pathlib.Path, cfg: pathlib.Path | None, cwd: pathlib.Path = REPO):
    env = {**os.environ, "PYTHONHASHSEED": "0"}
    env.pop("SAR_PATHS_CONFIG", None)    # cfg None: the script's tree reads its own config/paths.yaml
    if cfg is not None:
        env["SAR_PATHS_CONFIG"] = str(cfg)
    return subprocess.run([sys.executable, str(script)], cwd=cwd, env=env, capture_output=True, text=True,
                          timeout=900)


def _ledger(out: pathlib.Path) -> pathlib.Path:
    return out / "paper" / "gaps_zero_dose.json"


# ---- tests -----------------------------------------------------------------------------------------------
def test_m_mode_reports_diffs_not_mismatches(tmp_path):
    _root, cfg, out = build_m(tmp_path)
    r = run(GEN, cfg)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "MISMATCH" not in r.stderr, r.stderr
    got = json.loads(_ledger(out).read_text(encoding="utf-8"))
    assert {d: got[f"{d}_zero_dose_share_pct"] for d in FIELDS} == TOY
    assert got["_october"] == OCTOBER
    assert got["_diff_vs_october"] == {
        f"{d}_zero_dose_share_pct": {"october": OCTOBER[d], "new": TOY[d], "changed": True} for d in FIELDS}
    assert got["_pre_october_thesis_pct"] == {"econ": 15, "chem": 10, "math": 33}
    for d in FIELDS:
        assert f"CHANGED {d}_zero_dose_share_pct: october {OCTOBER[d]} -> new {TOY[d]}" in r.stdout, r.stdout


def test_m_all_null_dose_is_fatal(tmp_path):
    rel = {**REL, "chem": [("P_A", "E1", None), ("P_B", "E1", None)]}
    _root, cfg, out = build_m(tmp_path, rel)
    r = run(GEN, cfg)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "MISSING INPUT chem" in r.stderr and "frames/p1_frame_chemistry.csv" in r.stderr, r.stderr
    assert "Traceback" not in r.stderr, r.stderr
    assert not _ledger(out).exists(), "a missing input must not leave a ledger behind"


def test_october_mismatch_still_exits_1(tmp_path):
    """October canon (a tmp tree that is its own repo root, the six keys at their October roots) with
    frames that do not round to 8/6/31: exit 1 with MISMATCH, and the JSON carries October's keys in
    October's order and nothing of the M branch."""
    tree = tmp_path / "tree"
    for rel in ("analysis/lib/__init__.py", "analysis/lib/paths.py", "analysis/lib/canon.py",
                "analysis/paper/gaps_zero_dose.py"):
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, tree / rel)
    (tree / "config").mkdir()
    (tree / "config" / "paths.yaml").write_text(
        'repo_root: "."\noutput: output\n' + "".join(f"{k}: {v}\n" for k, v in canon.OCTOBER.items()),
        encoding="utf-8")
    for k, v in canon.OCTOBER.items():
        (tree / v).mkdir(parents=True, exist_ok=True)
    _frames(tree / canon.OCTOBER["frames"])
    r = run(tree / "analysis" / "paper" / "gaps_zero_dose.py", None, cwd=tree)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    for d in FIELDS:
        assert f"MISMATCH {d}: derived {TOY[d]}% does not round to the thesis's {OCTOBER[d]}" in r.stderr, r.stderr
    assert "CHANGED" not in r.stdout, r.stdout
    got = json.loads(_ledger(tree / "output").read_text(encoding="utf-8"))
    assert list(got) == ["_provenance", "econ_zero_dose_share_pct", "chem_zero_dose_share_pct",
                         "math_zero_dose_share_pct", "_pre_october_thesis_pct"], list(got)
    assert {d: got[f"{d}_zero_dose_share_pct"] for d in FIELDS} == TOY
