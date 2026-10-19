# -*- coding: utf-8 -*-
"""R1 F0 guard functions. No side effects here: the repo-root sar_f0_plugin.py installs them.

Design v3 §4 and §5.4: every computation runs on AWS and the tests run on a small AWS machine.
design_final.md §(f) F0: nothing a default test run does may touch the external data disk.
"""
from __future__ import annotations

import os
import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
ALLOWED_HOSTS = ("ec2-r1-test", "ec2-r1")
DATA_HOST = "ec2-r1"
GUARDED_EVENTS = frozenset({"open", "os.listdir", "os.scandir", "os.mkdir", "os.remove",
                            "os.rename", "os.rmdir", "shutil.rmtree"})


def host_ok(env=None) -> bool:
    """True only on the AWS test runner or the EC2 rerun host."""
    env = os.environ if env is None else env
    return str(env.get("SAR_HOST", "")).strip() in ALLOWED_HOSTS


def configured_ssd_root(config_file=None):
    """`ssd_root` exactly as config/paths.yaml names it - the physical data disk. A $SAR_SSD_ROOT
    override (tests point it at tmp dirs; instances at /data/openalex_pipeline) is ignored on
    purpose: the guard protects the disk, not whatever root a test chose."""
    path = pathlib.Path(config_file) if config_file else REPO / "config" / "paths.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    value = str(cfg.get("ssd_root", "") or "").strip()
    m = re.fullmatch(r"\$\{(\w+):-(.*)\}", value)       # public copy: "${SAR_SSD_ROOT:-<default>}"
    if m:
        value = os.environ.get(m.group(1)) or m.group(2)
        if value and not os.path.isabs(value):
            value = str((REPO / value).resolve())
    value = value.rstrip("/")
    return value or None


def make_guard(roots):
    """An audit hook raising PermissionError for a guarded event on a path under any root."""
    exact = tuple(str(r).rstrip("/") for r in roots)
    prefixes = tuple(r + "/" for r in exact)

    def hook(event, args):
        if event not in GUARDED_EVENTS or not args:
            return None
        target = args[0]
        if target is None or isinstance(target, int):
            return None
        try:
            path = os.path.abspath(os.fsdecode(target))
        except (TypeError, ValueError):
            return None
        if path in exact or path.startswith(prefixes):
            raise PermissionError(f"F0 guard: {path} is under ssd_root; tests may touch the data disk "
                                  f"only on $SAR_HOST={DATA_HOST} (design v3 §4)")
        return None

    return hook


# ---- R1 P3b F0 (2026-10-13): markers applied by the plugin, the risk pattern, the meta-test logic ----
import glob
import re

RISK = re.compile(r"ssd_root|derived_root|Extreme SSD|SAR_SSD_ROOT|duckdb|real_v2|Rscript|run_all\.sh")
TEST_GLOBS = ("tests/test_*.py", "pipeline/units/*/tests/test_*.py")
MODULE_MARK = re.compile(r"^pytestmark\s*=.*pytest\.mark\.(ssd|estimate|legacy|live)\b", re.M)
#: node id (or a whole test file) -> (marker, reason). Applied by sar_f0_plugin before `-m` deselects, so a
#: ported file never needs an edit. ssd/estimate/legacy run only in the big-host mode (P3b Task 10).
F0_MARKS: dict[str, tuple[str, str]] = {
    "tests/test_paper_ledgers.py::test_gaps_switchers_r":
        ("estimate", "re-runs the dCDH estimate on the frozen P1/P2 frames through Rscript (gaps_switchers.R)"),
    "tests/test_paper_ledgers.py::test_gaps_toy_r":
        ("estimate", "runs analysis/paper/gaps_toy.R through Rscript; needs the pinned R stack"),
    "tests/test_paper_p1p2.py::test_gaps_switchers_p1p2_r":
        ("estimate", "re-runs the dCDH estimate for the six headline cells through Rscript (gaps_switchers_p1p2.R)"),
    "pipeline/units/u4_output_star/tests/test_roster_v3_wiring.py":
        ("ssd", "reads the real registry_v3 roster tables under the derived root (skips only when they are absent)"),
    # R1 wave 1 (W1-PTABLES): the one big-host node of an otherwise small-runner file
    "tests/test_r1_tables_base_tree.py::test_all_13_base_tables_from_the_real_chain":
        ("legacy", "runs run_all's paper ledger/gaps stages (incl. the R gap scripts) and reads legacy "
                   "thesis_report tables via tables_main.py; big host B4"),
}


def marker_for(nodeid: str):
    for key, (marker, _why) in F0_MARKS.items():
        if nodeid == key or nodeid.startswith(key + "[") or ("::" not in key and nodeid.split("::", 1)[0] == key):
            return marker
    return None


def unreviewed(root, globs, reviewed, marks) -> list:
    """Test files that match RISK yet carry no module marker, no F0_MARKS entry and no review."""
    root = pathlib.Path(root)
    out = []
    for pattern in globs:
        for f in sorted(glob.glob(str(root / pattern))):
            rel = pathlib.Path(f).relative_to(root).as_posix()
            text = pathlib.Path(f).read_text(encoding="utf-8")
            marked = MODULE_MARK.search(text) or any(k.split("::")[0] == rel for k in marks)
            if RISK.search(text) and not marked and rel not in reviewed:
                out.append(rel)
    return out
