# -*- coding: utf-8 -*-
"""R1 P3 V3-FINAL.c + F7 (W2-SENTINEL): the paper sentinel works on any thesis tree, any ledger date.

tools/check_paper.py gains configure() and the flags --thesis-root, --ledger-date, --report, --json,
--no-regen, --profile, --gold, --tree, --tree-root. With no flag it must take exactly today's paths,
ledger names, report location, gold and pins (the switch-off pin below). The vault profile overlay
(VAULT_REANCHOR / VAULT_RETIRE) starts empty; apply_profile() is the identity under 'thesis'.

Small runner: every test builds a toy tree under tmp_path and points $SAR_PATHS_CONFIG at a tmp copy of
the paths config whose `output` is an empty tmp dir, so nothing under the repo or the legacy trees is
read or written. No generator runs (--no-regen; subprocess.run is replaced where main() runs in-process).
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from analysis.lib.paths import load_paths  # noqa: E402

CHECK_PAPER = REPO / "tools" / "check_paper.py"
LEDGER_KINDS = ("main", "p3afar", "p1p2", "robustness")


def _tmp_config(tmp_path: Path) -> Path:
    """The paths config in force, written absolute, with `output` moved to an empty tmp dir."""
    cfg = {k: str(v) for k, v in load_paths().items()}
    cfg["repo_root"] = "."
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    cfg["output"] = str(out)
    p = tmp_path / "paths_tmp.yaml"
    p.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return p


@pytest.fixture
def cp(tmp_path, monkeypatch):
    """A fresh tools/check_paper.py module loaded under the tmp config."""
    monkeypatch.setenv("SAR_PATHS_CONFIG", str(_tmp_config(tmp_path)))
    spec = importlib.util.spec_from_file_location("check_paper_tree_mod", CHECK_PAPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)   # type: ignore[union-attr]
    return mod


def _toy_tree(root: Path, date: str = "2026-10-23") -> Path:
    """An empty thesis-shaped tree: main.tex, sections/, tables/ and '{}' dated ledgers."""
    (root / "sections").mkdir(parents=True)
    (root / "tables").mkdir()
    (root / "main.tex").write_text("", encoding="utf-8")
    for kind in LEDGER_KINDS:
        name = f"data_numbers_{date}.json" if kind == "main" else f"data_numbers_{date}_{kind}.json"
        (root / name).write_text("{}", encoding="utf-8")
    return root


# ---- configure() -----------------------------------------------------------------------------------
def test_configure_rebinds_tree_paths_ledger_names_report_and_gold(cp, tmp_path):
    tree, r, j, g = tmp_path / "tree", tmp_path / "r.md", tmp_path / "r.json", tmp_path / "gold.json"
    cp.configure(thesis_root=tree, ledger_date="2027-01-05", report=r, json_out=j, gold=g)
    assert cp.THESIS_REPORT == tree
    assert cp.SECTIONS == tree / "sections" and cp.D_TABLES == tree / "tables"
    assert cp.THESIS_LEDGER_DATE == "2027-01-05"
    assert cp.THESIS_LEDGERS == {"main": "data_numbers_2027-01-05.json",
                                 "p3afar": "data_numbers_2027-01-05_p3afar.json",
                                 "p1p2": "data_numbers_2027-01-05_p1p2.json",
                                 "robustness": "data_numbers_2027-01-05_robustness.json"}
    assert cp.REPORT == r and cp.JSON_OUT == j and cp.GOLD == g
    assert cp.PROFILE == "thesis" and cp.TREE == "thesis_report"
    # --sections-dir / --tables-dir still override after a thesis root
    cp.configure(thesis_root=tree, sections_dir=tmp_path / "s", tables_dir=tmp_path / "t")
    assert cp.SECTIONS == tmp_path / "s" and cp.D_TABLES == tmp_path / "t" and cp.THESIS_REPORT == tree
    # a tree root moves only what section D reads (sections, tables, main.tex)
    cp.configure(tree_root=tmp_path / "base", tree="base_2026_10_11")
    assert cp.SECTIONS == tmp_path / "base" / "sections" and cp.D_TABLES == tmp_path / "base" / "tables"
    assert cp.MAIN_TEX == tmp_path / "base" / "main.tex" and cp.TREE == "base_2026_10_11"
    assert cp.THESIS_REPORT == load_paths()["legacy_thesis"] / "thesis_report"
    for bad in ({"ledger_date": "2027-1-5"}, {"ledger_date": "2027-02-30"}, {"profile": "draft"},
                {"tree": "thesis"}):
        with pytest.raises(ValueError):
            cp.configure(**bad)


def test_configure_without_arguments_keeps_the_october_defaults(cp):
    P = load_paths()
    for _ in range(2):          # the module defaults, then an explicit no-argument configure()
        assert cp.THESIS_REPORT == P["legacy_thesis"] / "thesis_report"
        assert cp.SECTIONS == cp.THESIS_REPORT / "sections" and cp.D_TABLES == cp.THESIS_REPORT / "tables"
        assert cp.MAIN_TEX is None
        assert cp.REPORT == P["output"] / "paper_check.md" and cp.JSON_OUT is None
        assert cp.THESIS_LEDGER_DATE == "2026-10-23"
        assert cp.THESIS_LEDGERS == {"main": "data_numbers_2026-10-23.json",
                                     "p3afar": "data_numbers_2026-10-23_p3afar.json",
                                     "p1p2": "data_numbers_2026-10-23_p1p2.json",
                                     "robustness": "data_numbers_2026-10-23_robustness.json"}
        assert cp.PROFILE == "thesis" and cp.TREE == "thesis_report"
        assert cp.GOLD == P["expected"] / "P1_econ_fnfix.json"
        assert cp.GOLD == (REPO / "analysis" / "expected" / "P1_econ_fnfix.json").resolve()
        assert cp.VAULT_REANCHOR == {} and cp.VAULT_RETIRE == {}
        cp.configure()


# ---- the CLI on a toy tree ---------------------------------------------------------------------------
def test_a_toy_tree_run_writes_report_and_json_where_told(tmp_path):
    cfg = _tmp_config(tmp_path)
    tree = _toy_tree(tmp_path / "T")
    r, j = tmp_path / "rep" / "R.md", tmp_path / "rep" / "J.json"
    env = {**os.environ, "SAR_PATHS_CONFIG": str(cfg)}
    res = subprocess.run([sys.executable, str(CHECK_PAPER), "--thesis-root", str(tree), "--ledger-date",
                          "2026-10-23", "--report", str(r), "--json", str(j), "--no-regen"],
                         capture_output=True, text=True, cwd=REPO, env=env)
    assert res.returncode == 1, res.stdout[-2000:] + res.stderr[-2000:]
    assert r.is_file() and j.is_file()
    data = json.loads(j.read_text(encoding="utf-8"))
    assert data["n_fail"] > 0 and data["n_checks"] == data["n_pass"] + data["n_fail"]
    assert data["checks"] and all({"section", "name", "ok", "retired", "unrep", "file", "detail"} <= set(c)
                                  for c in data["checks"])
    assert {c["section"] for c in data["checks"]} <= {"A", "B", "C", "D"}
    assert not (tmp_path / "out" / "paper_check.md").exists()          # the default report is untouched
    assert f"wrote {r}" in res.stdout and f"wrote {j}" in res.stdout
    assert r.read_text(encoding="utf-8").splitlines()[0].startswith("# paper_check")


def test_no_regen_runs_no_generator(cp, tmp_path, monkeypatch):
    tree = _toy_tree(tmp_path / "T")

    def boom(*a, **k):
        raise AssertionError("a generator was run despite --no-regen")
    monkeypatch.setattr(cp.subprocess, "run", boom)
    rc = cp.main(["--thesis-root", str(tree), "--report", str(tmp_path / "R.md"), "--no-regen"])
    assert rc == 1 and (tmp_path / "R.md").is_file()
    # without --no-regen the same run does reach a generator (the toy output dir is empty)
    with pytest.raises(AssertionError, match="generator was run"):
        cp.main(["--thesis-root", str(tree), "--report", str(tmp_path / "R2.md")])


def test_checks_carry_their_file(cp, tmp_path):
    cp.checks.clear()
    cp.check("D", "x", True, "d", file="sec2_data.tex")
    cp.check("A", "y", False, "d")
    cp.check_retired("z", "sec3_strategy.tex", cp.RETIRED_TAG + ": gone")
    assert [c["file"] for c in cp.checks] == ["sec2_data.tex", None, "sec3_strategy.tex"]


# ---- the vault profile overlay -----------------------------------------------------------------------
def test_vault_profile_touches_only_overlay_pins(cp, monkeypatch):
    pins = [("pin a", "sec2_data.tex", r"a " + cp.NUM, 1.0, 1, ""),
            ("pin b", "sec3_strategy.tex", r"b " + cp.NUM, 2.0, 1, "note b"),
            ("pin c", "sec4_p3.tex", r"c " + cp.NUM, 3.0, 2, "")]
    assert cp.apply_profile(pins, "thesis") is pins and cp.VAULT_UNMATCHED == []
    monkeypatch.setattr(cp, "VAULT_REANCHOR", {"pin a": ("sec2_data.tex", r"A new " + cp.NUM),
                                               "pin c": ("sec4_causal.tex", r"C " + cp.NUM + " " + cp.NUM, 1),
                                               "no such pin": ("sec2_data.tex", r"z")})
    monkeypatch.setattr(cp, "VAULT_RETIRE", {"pin b": "the base tree no longer prints this number anywhere"})
    assert cp.apply_profile(pins, "thesis") is pins            # thesis: the overlay is never applied
    out = cp.apply_profile(pins, "vault")
    assert out is not pins and len(out) == 3
    a, b, c = out
    assert a == ("pin a", "sec2_data.tex", r"A new " + cp.NUM, 1.0, 1, "")          # group kept
    assert c == ("pin c", "sec4_causal.tex", r"C " + cp.NUM + " " + cp.NUM, 3.0, 1, "")
    assert b[:5] == pins[1][:5] and b[5].startswith(cp.RETIRED_TAG) and b[5].endswith("; note b")
    assert cp.VAULT_UNMATCHED == ["no such pin"]
    # an unknown overlay name becomes a FAIL line in section D's way of reporting it
    cp.checks.clear()
    cp.report_vault_unmatched()
    assert [(c["section"], c["name"], c["ok"]) for c in cp.checks] == [("D", "vault overlay entry 'no such pin'", False)]
    # a retirement needs a real reason, and a pin cannot be moved and retired at once
    monkeypatch.setattr(cp, "VAULT_RETIRE", {"pin b": "short"})
    with pytest.raises(ValueError):
        cp.apply_profile(pins, "vault")
    monkeypatch.setattr(cp, "VAULT_RETIRE", {"pin a": "the base tree no longer prints this number anywhere"})
    with pytest.raises(ValueError):
        cp.apply_profile(pins, "vault")
    with pytest.raises(ValueError):
        cp.apply_profile(pins, "draft")


# ---- F7: the sentinel takes the October roots from config only ---------------------------------------
def test_check_paper_builds_no_literal_october_root():
    spec = importlib.util.spec_from_file_location("t_r1_canon_scan", REPO / "tests" / "test_r1_canon.py")
    scan = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scan)   # type: ignore[union-attr]
    src = CHECK_PAPER.read_text(encoding="utf-8")
    assert scan.october_root_literals(src) == []
    # the two data reads, the ABS record and the gold come from the config keys
    for need in ('P["cal"] / "robustness/predate/P2pd2_math_stats.json"',
                 'P["cal"] / "new_numbers/data_numbers_new_2026-10.json"',
                 'P["paper_inputs"] / "external_stats_2026-09-11.json"',
                 'P["expected"] / "P1_econ_fnfix.json"'):
        assert need in src, need


# ---- review R7 #10: a section-D check on the tree's tables/ names its file 'tables/<name>' -------------
FIX = REPO / "tests" / "fixtures" / "r1_paper" / "base_tree_2026-10-11"
#: one printed cell per table, changed (old, new): each makes exactly that table's check FAIL
BREAK = {"tab_p1_main.tex": ("(log points)} & \\REV{$-$0.368}", "(log points)} & \\REV{$-$0.369}"),
         "tab_p2_main.tex": ("(pp per year)} & \\REV{0.195}", "(pp per year)} & \\REV{0.196}"),
         "tab_p1_full.tex": ("\\REV{0} & \\REV{$-$0.041}", "\\REV{0} & \\REV{$-$0.042}"),
         "tab_p2_full.tex": ("\\REV{0} & \\REV{0.065}", "\\REV{0} & \\REV{0.066}"),
         "tab_rob_p1.tex": ("rows)} & \\REV{$-$3.456 (0.871)}", "rows)} & \\REV{$-$3.457 (0.871)}"),
         "tab_rob_p2.tex": ("dropped} & \\REV{0.216 (0.093)}", "dropped} & \\REV{0.217 (0.093)}"),
         "tab_rob_p3.tex": ("dose} & \\REV{$-$0.079 (0.038)}", "dose} & \\REV{$-$0.078 (0.038)}")}


def _fixture_ledgers() -> dict:
    d = FIX / "ledgers"
    return {k: json.loads((d / f"data_numbers_2026-10-23_{k}.json").read_text(encoding="utf-8"))
            for k in ("p1p2", "p3afar", "robustness")}


def test_grade_pins_names_table_pins_by_their_tree_path(cp):
    pins = [("tab pin", "tab_main_results.tex", r"rate " + cp.NUM, 1.0, 1, ""),
            ("sec pin", "sec2_data.tex", r"rate " + cp.NUM, 2.0, 1, ""),
            ("gone tab pin", "tab_disciplines.tex", r"absent " + cp.NUM, 3.0, 1, cp.RETIRED_TAG + ": not printed")]
    cp.checks.clear()
    cp.grade_pins(pins, {"tab_main_results.tex": "rate 1.5", "sec2_data.tex": "rate 2.5", "tab_disciplines.tex": ""},
                  {"tab_main_results.tex", "sec2_data.tex"})
    assert [(c["name"], c["ok"], c["file"]) for c in cp.checks] == [
        ("tab pin", False, "tables/tab_main_results.tex"), ("sec pin", False, "sec2_data.tex"),
        ("gone tab pin", True, "tables/tab_disciplines.tex")]


def test_table_cell_checks_name_their_tree_path_and_gate2_explains_them(cp, tmp_path):
    led = _fixture_ledgers()
    paper = tmp_path / "out" / "paper"                  # tables_robustness.py's own table (section D reads it)
    paper.mkdir(parents=True)
    for k, v in led.items():
        (paper / f"data_numbers_{k}.json").write_text(json.dumps(v), encoding="utf-8")
    r = subprocess.run([sys.executable, str(REPO / "analysis" / "paper" / "tables_robustness.py")], cwd=REPO,
                       env=dict(os.environ), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    tables = tmp_path / "tables"
    tables.mkdir()
    for name, (old, new) in BREAK.items():
        text = (FIX / "tables" / name).read_text(encoding="utf-8")
        assert text.count(old) == 1, name
        (tables / name).write_text(text.replace(old, new), encoding="utf-8")
    cp.configure(tables_dir=tables)
    cp.checks.clear()
    cp.section_d_p1p2_tables(led)
    p1p2 = list(cp.checks)
    cp.checks.clear()
    cp.section_d_rob_tables(led)
    rob = list(cp.checks)
    assert p1p2 and {c["file"] for c in p1p2} == {f"tables/{n}" for n in ("tab_p1_main.tex", "tab_p1_full.tex",
                                                                           "tab_p2_main.tex", "tab_p2_full.tex")}
    appendix = [c for c in rob if c["name"].startswith("rob A")]
    assert appendix and {c["file"] for c in appendix} == {"tables/tab_rob_p1.tex", "tables/tab_rob_p2.tex",
                                                          "tables/tab_rob_p3.tex"}
    # tables_robustness.py's own table (output/paper; its name is also a thesis table's) and the ledger
    # identities never carry a thesis tables/ path
    other = [c for c in rob if not c["name"].startswith("rob A")]
    assert other and not [c for c in other if str(c["file"] or "").startswith("tables/")]
    fails = [c for c in p1p2 + rob if not c["ok"]]
    assert {c["file"] for c in fails} == {f"tables/{n}" for n in BREAK}, [(c["name"], c["file"]) for c in fails]
    sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
    import final_stage as fs
    _, _, det = fs.gate2({"pre": fails, "post": [], "number_diff": [], "changed_tables": sorted(BREAK), "edits": []},
                         "M", None)
    assert det["unexplained"] == [] and det["missing"] == []
    _, _, det = fs.gate2({"pre": fails, "post": [], "number_diff": [], "changed_tables": [], "edits": []}, "M", None)
    assert len(det["unexplained"]) == len(fails)


# ---- final-path review finding 6: section C's appendix flags are October-only -------------------------
# analysis/paper/gaps_switchers.R:78-79 hard-codes the October printed appendix values (APX, APX_TOTAL,
# APX_AVG_DOSE, APX_WAVG) and records the comparison as the JSON's *matches_appendix flags. Under an M
# canon those constants are stale, so the four section C 'matches appendix' checks would FAIL before
# and after the repin and gate 2 would end in SECTION_C_FAIL. They are graded only on the October canon;
# in M the printed tab:agg cells and both average-dose sentences are checked against the measured
# gaps_switchers.json by section D's 'estimator ...' pins. The gold coefficient check stays in every mode.
from analysis.lib import canon as canon_mod  # noqa: E402

APPENDIX_FLAG_NAMES = tuple(f"switchers ell={i} matches appendix" for i in range(6)) + (
    "switchers total matches appendix", "weighted avg effect matches appendix", "avg dose matches appendix")
COEF_CHECK = "switcher rerun reproduces the frozen gold coefficients"


def _switchers(coef_pass=True, apx_match=False):
    """A gaps_switchers.json-shaped dict (analysis/paper/gaps_switchers.R `res`) with toy values."""
    sw = [5301 - 40 * i for i in range(6)]
    apx = [5264, 4944, 4840, 4668, 4475, 4282]
    return {"horizons": [{"k": i + 1, "switchers": sw[i], "n": 9000 + i, "appendix_switchers": apx[i],
                          "matches_appendix": apx_match} for i in range(6)],
            "switchers_total": sum(sw), "appendix_switchers_total": 28473,
            "switchers_total_matches_appendix": apx_match,
            "weighted_avg_effect": -0.15312, "appendix_weighted_avg": -0.141,
            "weighted_avg_matches_appendix": apx_match,
            "avg_dose_switchers": 0.39871, "appendix_avg_dose": 0.383,
            "avg_dose_matches_appendix": apx_match,
            "coef_check": {"pass": coef_pass, "ate": -0.38404,
                           "expected_ate": -0.38404 if coef_pass else -0.368}}


def _c_led(**kw):
    return {"switchers": _switchers(**kw), "zenou": {"UNVERIFIED": []}, "switchers_p1p2": None}


def _c_checks(cp):
    return {c["name"]: c["ok"] for c in cp.checks if c["section"] == "C"}


def test_section_c_october_grades_every_appendix_flag(cp):
    # the tmp paths config keeps the six canon keys at their October roots
    assert canon_mod.mode(cp.P) == "october"
    cp.checks.clear()
    cp.section_c(_c_led(coef_pass=True, apx_match=False))
    got = _c_checks(cp)
    for name in APPENDIX_FLAG_NAMES:
        assert got.get(name) is False, name          # graded, and FAIL on a mismatch (today's behaviour)
    assert got[COEF_CHECK] is True
    assert got["Zenou worked example fully verified"] is True
    cp.checks.clear()
    cp.section_c(_c_led(coef_pass=True, apx_match=True))
    got = _c_checks(cp)
    assert all(got.get(name) is True for name in APPENDIX_FLAG_NAMES)


def _force_mode(monkeypatch, value):
    """Replace analysis.lib.canon.mode (the object check_paper's `canon` names) for one test."""
    calls = []

    def fake(P=None):
        calls.append(P)
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr(canon_mod, "mode", fake)
    return calls


def test_section_c_m_canon_skips_the_october_appendix_flags(cp, monkeypatch):
    calls = _force_mode(monkeypatch, "M")
    cp.checks.clear()
    cp.section_c(_c_led(coef_pass=True, apx_match=False))
    assert calls, "section_c must ask the canon resolver which canon is in force"
    got = _c_checks(cp)
    assert not [n for n in got if "matches appendix" in n], got
    assert got[COEF_CHECK] is True                    # the gold coefficient check is kept in M
    assert got["Zenou worked example fully verified"] is True
    assert got["gaps_switchers_p1p2.json present"] is False   # the other C checks are untouched
    assert "fig_p1.pdf exists (>5 KB)" in got


def test_section_c_m_canon_keeps_the_gold_coefficient_check(cp, monkeypatch):
    _force_mode(monkeypatch, "M")
    cp.checks.clear()
    cp.section_c(_c_led(coef_pass=False, apx_match=False))
    got = _c_checks(cp)
    assert got[COEF_CHECK] is False                   # input validation still fails closed in M
    assert not [n for n in got if "matches appendix" in n]


def test_section_c_canon_error_fails_closed(cp, monkeypatch):
    _force_mode(monkeypatch, canon_mod.CanonError("mixed canon roots"))
    cp.checks.clear()
    with pytest.raises(canon_mod.CanonError):        # main() turns this into 'section C completed' FAIL
        cp.section_c(_c_led(coef_pass=True, apx_match=True))
    assert not [c for c in cp.checks if c["section"] == "C" and "matches appendix" in c["name"]]


def test_section_d_estimator_pins_still_check_the_printed_appendix(cp, tmp_path, monkeypatch):
    # in M these D pins are what compares the printed tab:agg cells and the average-dose sentences with
    # the measured gaps_switchers.json; they must stay built (ungated, unretired) whenever it exists
    monkeypatch.setitem(cp.P, "paper_inputs", tmp_path / "no_paper_inputs")   # no data read
    sw = _switchers()
    led = {k: None for k in ("main", "carried", "funnel", "p3afar", "zenou", "zero", "toy",
                             "gold_p1_union", "p1p2", "robustness")}
    led["switchers"] = sw
    for mode in ("october", "M"):
        _force_mode(monkeypatch, mode)
        by = {t[0]: t for t in cp.claims_table(led)}
        for i, h in enumerate(sw["horizons"]):
            _name, fname, _rx, want, group, note = by[f"estimator switchers ell={i}"]
            assert (fname, want, group) == ("appendix_estimator.tex", h["switchers"], i + 1)
            assert not note.startswith(cp.RETIRED_TAG)

        def one(prefix, suffix=""):
            hit = [t for n, t in by.items() if n.startswith(prefix) and n.endswith(suffix)]
            assert len(hit) == 1, (prefix, suffix, sorted(by))
            assert hit[0][1] == "appendix_estimator.tex" and not hit[0][5].startswith(cp.RETIRED_TAG)
            return hit[0][3]
        assert one("estimator switchers total") == sw["switchers_total"]
        assert one("estimator summary coefficient") == round(sw["weighted_avg_effect"], 3)
        assert one("estimator per-unit-of-dose") == round(sw["coef_check"]["ate"], 3)
        assert one("estimator avg dose", "(prose)") == round(sw["avg_dose_switchers"], 3)
        assert one("estimator avg dose", "(table notes)") == round(sw["avg_dose_switchers"], 3)
    # and the sentinel source still builds them inside claims_table
    src = CHECK_PAPER.read_text(encoding="utf-8")
    body = src[src.index("def claims_table(led"):src.index("def _bind_vault_overlay(")]   # signature may take a profile (R1 author tree)
    for need in ('f"estimator switchers ell={i}"', '"estimator switchers total', '"estimator summary coefficient',
                 '"estimator per-unit-of-dose', '"estimator avg dose', "(prose)", "(table notes)"):
        assert need in body, need


# ---- R1 M (final-03 audit, 2026-10-18): the sentinel on the M ledgers ---------------------------------
# The M robustness ledger has no departure_<field> blocks (F20; the author's ruling of 2026-10-15), and the
# M mathematics Panel 2 date-shift run succeeded (its artifact has no aux_status). October keeps every check.
DEP_KEYS = ("departure_econ", "departure_chemistry", "departure_math_stats")
NO_DEP_ROWS = tuple(f"rob {t} no star-departure rows (no departure cells in the ledger)" for t in ("A1", "A3", "A2"))
ART_OCT = "r4 4.3 math P2 date-shift artifact: shifted k=2 estimate 0 with no SE, joint-test run failed"
ART_M = "r4 4.3 math P2 date-shift artifact: joint-test status and p match the robustness ledger"


def _m_ledgers() -> dict:
    led = _fixture_ledgers()
    for k in DEP_KEYS:
        del led["robustness"][k]
    return led


def _m_cfg(tmp_path: Path) -> Path:
    """The tmp config with the six canon keys moved under a tiny M canon (CANON.json; empty key dirs)."""
    from analysis.lib import canon
    cfg = yaml.safe_load(_tmp_config(tmp_path).read_text(encoding="utf-8"))
    root = tmp_path / "canon_m"
    for k in canon.KEYS:
        (root / k).mkdir(parents=True, exist_ok=True)
        cfg[k] = str(root / k)
    (root / canon.CANON_JSON).write_text(json.dumps({"schema": canon.SCHEMA, "canon": "M",
                                                     "prefix": {k: k for k in canon.KEYS}, "switches": {}}))
    p = tmp_path / "paths_m.yaml"
    p.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return p


def _rob_tables(tmp_path: Path, led: dict, cfg: Path) -> Path:
    """tables_robustness.py on these ledgers, written into the sentinel's output/paper (tmp_path/out)."""
    paper = tmp_path / "out" / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    for k, v in led.items():
        (paper / f"data_numbers_{k}.json").write_text(json.dumps(v), encoding="utf-8")
    r = subprocess.run([sys.executable, str(REPO / "analysis" / "paper" / "tables_robustness.py")], cwd=REPO,
                       env=dict(os.environ, SAR_PATHS_CONFIG=str(cfg)), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return paper


def test_rob_tables_m_ledger_without_departure_cells(tmp_path, cp):
    oct_led, m_led = _fixture_ledgers(), _m_ledgers()
    _rob_tables(tmp_path, oct_led, _tmp_config(tmp_path))   # October summary table in output/paper
    cp.configure(tables_dir=FIX / "tables")              # October appendix tables, October ledgers
    cp.checks.clear()
    cp.section_d_rob_tables(oct_led)
    october = {c["name"]: c for c in cp.checks}
    assert not set(NO_DEP_ROWS) & set(october)            # October: no new check
    assert october["rob ledger departure coverage arithmetic"]["ok"]

    paper = _rob_tables(tmp_path, m_led, _m_cfg(tmp_path))   # the M appendix tables (no departure rows)
    cp.configure(tables_dir=paper)
    cp.checks.clear()
    cp.section_d_rob_tables(m_led)                        # no KeyError on the missing cells
    m = {c["name"]: c for c in cp.checks}
    dep = {n for n in october if "departure A" in n or "departure B" in n or "departure coverage" in n}
    assert dep and set(m) == (set(october) - dep) | set(NO_DEP_ROWS), sorted(set(m) ^ set(october))
    assert all(c["ok"] for c in m.values()), [c for c in m.values() if not c["ok"]]
    assert [m[n]["file"] for n in NO_DEP_ROWS] == ["tables/tab_rob_p1.tex", "tables/tab_rob_p3.tex",
                                                   "tables/tab_rob_p2.tex"]


def test_rob_tables_m_ledger_with_departure_rows_printed_fails(tmp_path, cp):
    cp.configure(tables_dir=FIX / "tables")              # October tables, which print the departure rows
    _rob_tables(tmp_path, _m_ledgers(), _m_cfg(tmp_path))
    cp.checks.clear()
    cp.section_d_rob_tables(_m_ledgers())
    m = {c["name"]: c for c in cp.checks}
    for n in NO_DEP_ROWS:
        assert not m[n]["ok"] and "2 star-departure rows" in m[n]["detail"], m[n]
    assert [c["name"] for c in cp.checks if not c["ok"]] == list(NO_DEP_ROWS)


def _r4(cp, led):
    cp.configure(thesis_root=FIX, ledger_date="2026-10-23", profile="vault", tree="base_2026_10_11")
    cp.checks.clear()
    cp.section_d_r4_claims(led)
    return {c["name"]: c for c in cp.checks}


def _m_artifact(tmp_path: Path, cp) -> dict:
    """An M-shaped math Panel 2 date-shift artifact (the run succeeded: p_joint_shifted, no aux_status) under
    a tmp cal root; returns the robustness ledger block that run gives."""
    src = json.loads((load_paths()["cal"] / "robustness/predate/P2pd2_math_stats.json").read_text(encoding="utf-8"))
    assert src["predate"]["aux_status"] == "FAILED"       # October: the joint-test run failed
    eff = [{"k": 1, "est": 0.000319, "se": 0.000392, "n": 900}, {"k": 2, "est": 0.0000405, "se": 0.000269, "n": 880}]
    src["predate"] = {k: v for k, v in src["predate"].items() if k != "aux_status"}
    src["predate"].update(p_joint_shifted=0.71545441, shifted_effects=eff)
    src["effects"] = [dict(e, est=0.0001) if e["k"] == 2 else e for e in src["effects"]]
    art = tmp_path / "cal" / "robustness" / "predate" / "P2pd2_math_stats.json"
    art.parent.mkdir(parents=True)
    art.write_text(json.dumps(src), encoding="utf-8")
    cp.P["cal"] = tmp_path / "cal"                        # this module's config only (a fresh module per test)
    return {"p_joint_shifted": 0.71545441, "shifted_effects_pp": [], "rows": 1, "relations": 1, "events": 1,
            "shift_years": 2}


def test_math_p2_date_shift_artifact_check_is_october_only(tmp_path, cp, monkeypatch):
    october = _r4(cp, _fixture_ledgers())
    assert october[ART_OCT]["ok"] and ART_M not in october

    led = _fixture_ledgers()
    led["robustness"]["p2_date_shift"]["math_stats"] = _m_artifact(tmp_path, cp)
    _force_mode(monkeypatch, "M")
    m = _r4(cp, led)                                      # no KeyError on the missing aux_status
    assert ART_OCT not in m
    assert m[ART_M]["ok"], m[ART_M]
    assert "0.71545441" in m[ART_M]["detail"]
    assert "section D completed" not in m


def test_math_p2_date_shift_m_check_fails_when_ledger_and_artifact_disagree(tmp_path, cp, monkeypatch):
    led = _fixture_ledgers()                              # the ledger still says AUX_FAILED (October)
    _m_artifact(tmp_path, cp)
    _force_mode(monkeypatch, "M")
    m = _r4(cp, led)
    assert not m[ART_M]["ok"], m[ART_M]
    ok_led = _fixture_ledgers()
    ok_led["robustness"]["p2_date_shift"]["math_stats"] = dict(_m_artifact(tmp_path / "b", cp), p_joint_shifted=0.7)
    assert not _r4(cp, ok_led)[ART_M]["ok"]               # same status, different p
