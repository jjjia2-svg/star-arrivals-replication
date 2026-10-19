# -*- coding: utf-8 -*-
"""R1 N12 (unit W2-N12P): the Panel 3 permutation p without the double rounding (R5), behind the
paper-layer switch p_full_precision.

The p of the shuffled-arrival-years test is (1 + k) / (1 + B). analysis/paper/ledger_p3afar.py stored
it rounded to 4 dp, and the tables print it at 3 dp: rounding twice. Economics in October: 118/501 =
0.23553 prints 0.236, but the stored 0.2355 prints 0.235. The fix is a switch (ruling: off = October
0.2355 / 0.235 byte for byte; on in config M, carried into CANON.json, where 0.235 -> 0.236 is an
expected changed number). Only economics moves: chemistry 51/501 and mathematics 292/501 print the
same digits either way.

1. test_perm_p_full_and_legacy - perm_p(ge, n, full), lifted out of the generator's source (its
   module body runs the whole ledger, so it is not imported), and the two table generators' pval().
2. test_perm_checked_takes_the_switch - perm_checked's p is perm_p(..., <flag>) and the flag is
   canon.switch("p_full_precision") read once at module level; the switch is the registry's N12 one.
3. test_p3afar_switch_on_gives_0236_on_october (big host, legacy) - October copied into an M canon
   with CANON.json switches {p_full_precision: true}: econ p_two_sided == 0.23552894211576847, and
   tab_rob_p3.tex plus the draft's tab_robustness.tex print 0.236; the default (October) run keeps
   0.2355 and the October table bytes.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

LEDGER = REPO / "analysis" / "paper" / "ledger_p3afar.py"
TABLES_ROB = REPO / "analysis" / "paper" / "tables_robustness.py"
DRAFT = REPO / "analysis" / "paper" / "draft_2026_09_13_tables.py"
FIX = REPO / "tests" / "fixtures" / "r1_paper" / "base_tree_2026-10-11"
FIX_LEDGERS = FIX / "ledgers"
FIX_TABLES = FIX / "tables"
DATE = "2026-10-23"
SWITCH = "p_full_precision"
FIELDS = ("econ", "chemistry", "math_stats")


def _lift(path: pathlib.Path, name: str, ns: dict | None = None):
    """One top-level function of a generator, compiled on its own (the generators run at import)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(fns) == 1, f"{path.name}: expected one top-level def {name}, found {len(fns)}"
    env = dict(ns or {})
    exec(compile(ast.Module(body=fns, type_ignores=[]), str(path), "exec"), env)
    return env[name]


# ---------------------------------------------------------------------------------------------
# small runner
# ---------------------------------------------------------------------------------------------
def test_perm_p_full_and_legacy():
    perm_p = _lift(LEDGER, "perm_p")
    # October (switch off): the stored value and its print are exactly today's
    legacy = perm_p(117, 500, False)
    assert legacy == 0.2355
    assert f"{legacy:.3f}" == "0.235"
    # M (switch on): unrounded, so the 3-dp print is rounded once
    full = perm_p(117, 500, True)
    assert full == 118 / 501 == 0.23552894211576847
    assert f"{full:.3f}" == "0.236"
    # the table generators print it at 3 dp through their own pval(), unchanged by this unit
    for gen, failed in ((TABLES_ROB, "failed"), (DRAFT, "n.a.")):
        pval = _lift(gen, "pval", {"FAILED": failed})
        assert pval(legacy) == "0.235", gen.name
        assert pval(full) == "0.236", gen.name
        assert pval(None) == failed, gen.name
    # chemistry and mathematics (October k = 50 and 291 of 500) print the same digits either way
    for ge, shown in ((50, "0.102"), (291, "0.583")):
        assert perm_p(ge, 500, False) == round((1 + ge) / 501, 4)
        assert perm_p(ge, 500, True) == (1 + ge) / 501
        assert f"{perm_p(ge, 500, False):.3f}" == f"{perm_p(ge, 500, True):.3f}" == shown
    # the type of the flag is strict: a truthy non-bool is not a silent "on"
    with pytest.raises(TypeError):
        perm_p(117, 500, "on")


def test_perm_checked_takes_the_switch():
    tree = ast.parse(LEDGER.read_text(encoding="utf-8"))
    # the flag: canon.switch("p_full_precision", ...) assigned once at module level
    flags = []
    for n in tree.body:
        if (isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)
                and isinstance(n.value.func.value, ast.Name) and n.value.func.value.id == "canon"
                and n.value.func.attr == "switch" and n.value.args
                and isinstance(n.value.args[0], ast.Constant) and n.value.args[0].value == SWITCH):
            flags.append(n.targets[0].id)
    assert len(flags) == 1, f"expected one module-level <flag> = canon.switch({SWITCH!r}), found {flags}"
    flag = flags[0]
    # perm_checked's p is perm_p(ge, len(draws), <flag>) and nothing else rounds (1 + ge)/(1 + n) there
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "perm_checked")
    p_assigns = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "p" for t in n.targets)]
    assert len(p_assigns) == 1, ast.dump(fn)[:400]
    call = p_assigns[0].value
    assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "perm_p", \
        ast.unparse(p_assigns[0])
    assert len(call.args) == 3 and isinstance(call.args[2], ast.Name) and call.args[2].id == flag, \
        ast.unparse(call)
    rounds = [ast.unparse(n) for n in ast.walk(fn) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Name) and n.func.id == "round" and "ge" in ast.unparse(n)]
    assert rounds == [], f"perm_checked still rounds the p itself: {rounds}"
    # the summary cross-check stays on the unrounded value
    checks = [ast.unparse(n) for n in ast.walk(fn) if isinstance(n, ast.Assert) and "p_perm_abs_ate" in ast.unparse(n)]
    assert len(checks) == 1 and "(1 + ge) / (1 + len(draws))" in checks[0], checks
    # the switch is the frozen registry's N12 switch, off in B0 (October)
    from pipeline.lib import r1_config
    assert r1_config.SWITCHES[SWITCH] == {"off": "off", "on": "on", "owner": "N12"}
    b0 = json.loads((REPO / "config" / "r1" / "B0.json").read_text(encoding="utf-8"))
    row = [s for s in b0["switches"] if s["switch"] == SWITCH]
    assert len(row) == 1 and row[0]["value"] == "off" and row[0]["owner"] == "N12", row


def test_october_mode_reads_the_switch_as_off():
    from analysis.lib import canon
    assert canon.mode() == "october"
    assert canon.switch(SWITCH) is False


# ---------------------------------------------------------------------------------------------
# big host (B4): the real ledger on October, as October and as an M canon with the switch on
# ---------------------------------------------------------------------------------------------
def _legacy_sha() -> dict:
    """The October table pins SOURCE.md records (sha256 of the legacy thesis_report/tables)."""
    out = {}
    for line in (FIX / "SOURCE.md").read_text(encoding="utf-8").splitlines():
        m = re.fullmatch(r"legacy-sha256 ([0-9a-f]{64})  (tab_\w+\.tex)", line.strip())
        if m:
            out[m.group(2)] = m.group(1)
    return out


def _paths_override(tmp: pathlib.Path, output_root: pathlib.Path) -> pathlib.Path:
    """The paths config in force with only `output` moved (the canon keys stay October)."""
    from analysis.lib.paths import config_file
    raw = yaml.safe_load(config_file().read_text(encoding="utf-8"))
    raw["output"] = str(output_root)
    cfg = tmp / "paths_october.yaml"
    cfg.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return cfg


def _run(argv, cfg=None):
    env = {**os.environ, "SOURCE_DATE_EPOCH": "0", "PYTHONHASHSEED": "0", "MPLBACKEND": "Agg"}
    if cfg is not None:
        env["SAR_PATHS_CONFIG"] = str(cfg)
    r = subprocess.run([sys.executable, *map(str, argv)], cwd=REPO, env=env, capture_output=True, text=True)
    assert r.returncode == 0, (argv, r.stdout[-3000:] + r.stderr[-3000:])
    return r


def _tables(out_root: pathlib.Path, cfg: pathlib.Path, ledger: dict, tmp: pathlib.Path, tag: str) -> dict:
    """tables_robustness (default tree) on this ledger plus the October p1p2/robustness ledgers, and
    the draft's three tables (base tree) on the October dated ledgers with this p3afar ledger in."""
    paper = out_root / "paper"
    for short in ("p1p2", "robustness"):
        shutil.copyfile(FIX_LEDGERS / f"data_numbers_{DATE}_{short}.json", paper / f"data_numbers_{short}.json")
    _run([TABLES_ROB], cfg)
    led = tmp / f"ledgers_{tag}"
    shutil.copytree(FIX_LEDGERS, led)
    (led / f"data_numbers_{DATE}_p3afar.json").write_text(json.dumps(ledger, indent=1, ensure_ascii=False),
                                                           encoding="utf-8")
    draft = tmp / f"draft_{tag}"
    _run([DRAFT, "--out-dir", draft, "--tree", "base_2026_10_11", "--ledger-dir", led])
    return {"tab_rob_p3.tex": paper / "tab_rob_p3.tex", "tab_rob_p1.tex": paper / "tab_rob_p1.tex",
            "tab_rob_p2.tex": paper / "tab_rob_p2.tex", "rob_summary": paper / "tab_robustness.tex",
            "draft_tab_robustness": draft / "tab_robustness.tex"}


def _diff_lines(a: pathlib.Path, b: pathlib.Path) -> list[tuple[str, str]]:
    la, lb = a.read_text(encoding="utf-8").splitlines(), b.read_text(encoding="utf-8").splitlines()
    assert len(la) == len(lb), (a, b)
    return [(x, y) for x, y in zip(la, lb) if x != y]


@pytest.mark.legacy
def test_p3afar_switch_on_gives_0236_on_october(tmp_path):
    # --- October (default canon, switch off), output moved to tmp
    oct_out = tmp_path / "out_october"
    (oct_out / "paper").mkdir(parents=True)
    cfg_oct = _paths_override(tmp_path, oct_out)
    _run([LEDGER], cfg_oct)
    jo = json.loads((oct_out / "paper" / "data_numbers_p3afar.json").read_text(encoding="utf-8"))

    # --- October copied into an M canon with the switch on
    canon_root = tmp_path / "canon_m"
    m_out = tmp_path / "out_m"
    (m_out / "paper").mkdir(parents=True)
    cfg_m = tmp_path / "paths_m.yaml"
    _run([REPO / "tools" / "r1_canon.py", "copy-october", canon_root, "--switch", f"{SWITCH}=true",
          "--paths-out", cfg_m, "--output", m_out])
    assert json.loads((canon_root / "CANON.json").read_text())["switches"] == {SWITCH: True}
    _run([LEDGER], cfg_m)
    jm = json.loads((m_out / "paper" / "data_numbers_p3afar.json").read_text(encoding="utf-8"))

    # the numbers: on = (1 + k)/(1 + B) unrounded, off = rounded to 4 dp (October)
    ro, rm = jo["econ"]["randomization_inference"], jm["econ"]["randomization_inference"]
    assert (ro["n_at_least_as_large"], ro["permutations"]) == (117, 500)
    assert ro["p_two_sided"] == 0.2355
    assert rm["p_two_sided"] == 0.23552894211576847 == 118 / 501
    fix = json.loads((FIX_LEDGERS / f"data_numbers_{DATE}_p3afar.json").read_text(encoding="utf-8"))
    for f in FIELDS:
        o, m = jo[f]["randomization_inference"], jm[f]["randomization_inference"]
        assert o == fix[f]["randomization_inference"], f          # October values unchanged
        exact = (1 + o["n_at_least_as_large"]) / (1 + o["permutations"])
        assert m["p_two_sided"] == exact and o["p_two_sided"] == round(exact, 4), f
    # nothing else in the ledger moves
    back = copy.deepcopy(jm)
    for f in FIELDS:
        back[f]["randomization_inference"]["p_two_sided"] = jo[f]["randomization_inference"]["p_two_sided"]
    assert back == jo

    # the printed tables
    to = _tables(oct_out, cfg_oct, jo, tmp_path, "october")
    tm = _tables(m_out, cfg_m, jm, tmp_path, "m")
    pins = _legacy_sha()
    for name in ("tab_rob_p1.tex", "tab_rob_p2.tex", "tab_rob_p3.tex"):
        assert hashlib.sha256(to[name].read_bytes()).hexdigest() == pins[name], name   # October bytes kept
    assert to["draft_tab_robustness"].read_bytes() == (FIX_TABLES / "tab_robustness.tex").read_bytes()
    for name in ("tab_rob_p1.tex", "tab_rob_p2.tex"):
        assert tm[name].read_bytes() == to[name].read_bytes(), name

    d3 = _diff_lines(to["tab_rob_p3.tex"], tm["tab_rob_p3.tex"])
    assert len(d3) == 1, d3
    o_line, m_line = d3[0]
    assert "permutation $p$" in o_line and "\\REV{0.235}" in o_line and "\\REV{0.236}" in m_line
    assert o_line.replace("\\REV{0.235}", "\\REV{0.236}") == m_line

    dd = _diff_lines(to["draft_tab_robustness"], tm["draft_tab_robustness"])
    assert len(dd) == 1, dd
    o_line, m_line = dd[0]
    assert "shuffled arrival years" in o_line and f"data_numbers_{DATE}_p3afar.json" in o_line
    assert "\\REV{0.235}" in o_line and o_line.replace("\\REV{0.235}", "\\REV{0.236}") == m_line
    assert "\\REV{None}" in m_line                                # the pass column does not move

    ds = _diff_lines(to["rob_summary"], tm["rob_summary"])
    assert all(a.replace("0.235", "0.236") == b for a, b in ds), ds
    assert len(ds) <= 1, ds
