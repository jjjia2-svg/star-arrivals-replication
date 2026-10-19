# Panel 1 + Panel 2 exhibits (2026-08-30): ledger, tables, figures, switcher gap script.
# Style of tests/test_paper_ledgers.py: red-first equality tests against the thesis copies,
# double-run determinism, PLOTTED_VALUES-vs-ledger for the figures, and source assertions
# that the generators read ONLY this package's frozen artifacts (no legacy tree, no
# hand-typed numbers).
import importlib.util
import json, pathlib, shutil, subprocess, sys
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from analysis.lib.paths import load_paths

P = load_paths()
THESIS_REPORT = P["legacy_thesis"] / "thesis_report"
RSCRIPT = shutil.which("Rscript")
OUT = P["output"] / "paper"

P1P2_TABLES = ["tab_p1_main.tex", "tab_p1_full.tex", "tab_p2_main.tex", "tab_p2_full.tex"]


def _run(script):
    r = subprocess.run([sys.executable, str(REPO / "analysis/paper" / script)],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def _run_r(script):
    r = subprocess.run([RSCRIPT, str(REPO / "analysis/paper" / script)],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def _ensure_gaps():
    """gaps_switchers_p1p2.json (switcher counts, R rerun gated on the frozen golds), or a
    loud skip when Rscript is unavailable and no generated copy exists."""
    out = OUT / "gaps_switchers_p1p2.json"
    if not out.exists():
        if RSCRIPT is None:
            pytest.skip("Rscript unavailable and gaps_switchers_p1p2.json has not been generated")
        _run_r("gaps_switchers_p1p2.R")
    return out


def _ensure_ledger():
    _ensure_gaps()
    _run("ledger_p1p2.py")
    return OUT / "data_numbers_p1p2.json"


# ---------------------------------------------------------------------------
# gaps_switchers_p1p2.R — switcher counts for all six headline cells, rerun from the
# frozen frames and gated on equality with the frozen golds (gaps_switchers.R pattern)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(RSCRIPT is None, reason="Rscript not on PATH")
def test_gaps_switchers_p1p2_r():
    _run_r("gaps_switchers_p1p2.R")
    got = json.loads((OUT / "gaps_switchers_p1p2.json").read_text())
    for field in ("econ", "chemistry", "math_stats"):
        p1 = got["p1"][field]
        assert p1["coef_check"]["pass"] is True, f"P1 {field}: rerun does not replicate the gold"
        assert len(p1["horizons"]) == 6 and len(p1["placebos"]) == 4
        for h in p1["horizons"] + p1["placebos"]:
            assert {"k", "ell", "switchers", "n"} <= set(h)
        assert p1["switchers_total"] == sum(h["switchers"] for h in p1["horizons"])
        p2 = got["p2"][field]
        assert p2["coef_check"]["pass"] is True, f"P2 {field}: rerun does not replicate the gold"
        assert len(p2["horizons"]) == 5
        assert p2["switchers_total"] == sum(h["switchers"] for h in p2["horizons"])
        # every n must equal the frozen gold's n — proof the switcher counts belong to the
        # same estimation the paper reports
        gold1 = json.loads((P["expected"] / f"P1_{'econ_fnfix' if field == 'econ' else 'fnfix_' + field}.json").read_text())
        assert [h["n"] for h in p1["horizons"]] == [e["n"] for e in gold1["channels"]["union"]["effects"]]
        gold2 = json.loads((P["expected"] / f"P2_{'econ_fnfix' if field == 'econ' else 'fnfix_' + field}.json").read_text())
        assert [h["n"] for h in p2["horizons"]] == [e["n"] for e in gold2["effects"]]


# ---------------------------------------------------------------------------
# ledger_p1p2.py — every number from the frozen artifacts; thesis-equality; determinism
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not THESIS_REPORT.is_dir(), reason="thesis tree not available on this machine")
def test_p1p2_ledger_equals_thesis():
    _ensure_ledger()
    got = json.loads((OUT / "data_numbers_p1p2.json").read_text())
    want = json.loads((THESIS_REPORT / "data_numbers_2026-10-23_p1p2.json").read_text())
    got.pop("_source_note", None)
    want.pop("_source_note", None)
    assert got == want


def test_p1p2_ledger_double_run_deterministic():
    p = _ensure_ledger()
    first = p.read_bytes()
    _run("ledger_p1p2.py")
    assert p.read_bytes() == first, "ledger_p1p2.py is not deterministic across runs"


def test_p1p2_ledger_headline_values_match_frozen_golds():
    """The ledger's headline cells re-derived here, independently of the generator, from the
    same frozen artifacts (a mis-mapped key in the generator cannot survive this)."""
    ledger = json.loads(_ensure_ledger().read_text())
    for field, lab1, lab2 in (("econ", "P1_econ_fnfix", "P2_econ_fnfix"),
                              ("chemistry", "P1_fnfix_chemistry", "P2_fnfix_chemistry"),
                              ("math_stats", "P1_fnfix_math_stats", "P2_fnfix_math_stats")):
        g1 = json.loads((P["expected"] / f"{lab1}.json").read_text())["channels"]["union"]
        e1 = json.loads((P["expected"] / f"P1evcl_{field}.json").read_text())["channels"]["union"]
        c = ledger[f"p1_{field}"]
        assert c["ate_log"] == round(g1["ate"], 3)
        assert c["se_person"] == round(g1["se"], 3)
        assert c["se_event"] == round(e1["se"], 3)
        assert c["p_joint_effects_person"] == g1["p_joint_effects"]
        assert c["p_joint_placebo_person"] == g1["p_joint_placebo"]
        assert c["obs"] == g1["obs"] and c["events"] == g1["events"]
        assert [h["est"] for h in c["horizons"]] == [round(x["est"], 3) for x in g1["effects"]]
        assert [h["est"] for h in c["placebos"]] == [round(x["est"], 3) for x in g1["placebos"]]
        g2 = json.loads((P["expected"] / f"{lab2}.json").read_text())
        e2 = json.loads((P["expected"] / f"P2evcl_{field}.json").read_text())
        d = ledger[f"p2_{field}"]
        assert d["ate_pp"] == round(100 * g2["ate"], 3)
        assert d["se_person_pp"] == round(100 * g2["se"], 3)
        assert d["se_event_pp"] == round(100 * e2["se"], 3)
        assert d["first_ties"] == g2["first_ties"] and d["events"] == g2["events"]
        assert g2["p_joint_placebo"] is None, "P2 placebo is structural — the ledger must not invent one"


def test_p1p2_ledger_robustness_blocks_match_freezes():
    import csv as _csv
    ledger = json.loads(_ensure_ledger().read_text())
    # 2026-09-23 (cal2026-10): ledger_p1p2.py reads the October products (its ROB_BAT / ROB_DS / CLOUD_T5,
    # each sha256-checked against its MANIFEST or custody record), which replaced the 2026-08-29 freezes:
    #   data/robustness_2026-08-29/loeo_ranked.csv         -> data/cal2026-10/robustness/battery/loeo_ranked.csv
    #   data/robustness_2026-08-29_b/doublestar/...        -> data/cal2026-10/robustness/doublestar/...
    #   data/robustness_2026-08-29_b/perm/perm_summary.json -> data/cal2026-10/cloud_t5/perm/perm_summary.json
    # One leave-one-out removal per economics event: 113 on the October event set (116 on the 08-28
    # caliber), read here from the frozen October gold rather than typed twice.
    n_econ_events = json.loads((P["expected"] / "P1_econ_fnfix.json").read_text())["channels"]["union"]["events"]
    assert n_econ_events == 113
    rows = list(_csv.DictReader(open(REPO / "data/cal2026-10/robustness/battery/loeo_ranked.csv")))
    assert ledger["p1_loeo_econ"]["n_removals"] == len(rows) == n_econ_events
    ates = [float(r["ate"]) for r in rows]
    assert ledger["p1_loeo_econ"]["ate_min"] == round(min(ates), 3)
    assert ledger["p1_loeo_econ"]["ate_max"] == round(max(ates), 3)
    pmax = max(float(r["p_joint_placebo"]) for r in rows)
    assert ledger["p1_loeo_econ"]["p_joint_placebo_max"] == pmax
    ds = json.loads((REPO / "data/cal2026-10/robustness/doublestar/estimates/P1ds_econ.json").read_text())
    rep = json.loads((REPO / "data/cal2026-10/robustness/doublestar/doublestar_build_report.json").read_text())
    assert ledger["p1_doublestar_econ"]["events_kept"] == rep["econ"]["kept"] == ds["channels"]["union"]["events"]
    assert ledger["p1_doublestar_econ"]["ate_log"] == round(ds["channels"]["union"]["ate"], 3)
    assert ledger["p1_doublestar_econ"]["p_joint_placebo"] == ds["channels"]["union"]["p_joint_placebo"]
    perm = json.loads((REPO / "data/cal2026-10/cloud_t5/perm/perm_summary.json").read_text())
    cells = {c["label"]: c for c in perm["cells"]}
    for field, lab1, lab2 in (("econ", "P1_econ_fnfix", "P2_econ_fnfix"),
                              ("chemistry", "P1_fnfix_chemistry", "P2_fnfix_chemistry"),
                              ("math_stats", "P1_fnfix_math_stats", "P2_fnfix_math_stats")):
        assert ledger["perm_pvalues"][f"p1_{field}"]["p_perm_abs_ate"] == cells[lab1]["p_perm_abs_ate"]
        assert ledger["perm_pvalues"][f"p1_{field}"]["p_perm_abs_t"] == cells[lab1]["p_perm_abs_t"]
        assert ledger["perm_pvalues"][f"p2_{field}"]["p_perm_abs_ate"] == cells[lab2]["p_perm_abs_ate"]
        assert ledger["perm_pvalues"][f"p2_{field}"]["p_perm_abs_t"] == cells[lab2]["p_perm_abs_t"]


def test_p1p2_ledger_reads_frozen_artifacts_only():
    """No legacy-tree read, no hand-typed number source: the generator's inputs are this
    package's analysis/expected, data/frames, data/robustness freezes and the gated R
    rerun's output — nothing else (the "freeze is inert" defect class, T4/T8 reviews)."""
    src = (REPO / "analysis/paper/ledger_p1p2.py").read_text(encoding="utf-8")
    for gone in ("legacy_v2_output", "legacy_thesis", "v2_output"):
        assert gone not in src, f"ledger_p1p2.py reads the legacy tree: {gone}"
    for need in ('P["expected"]', 'P["frames"]', "robustness_2026-08-29", "gaps_switchers_p1p2.json"):
        assert need in src, f"ledger_p1p2.py no longer names its frozen input: {need}"


# ---------------------------------------------------------------------------
# tables_p1p2.py — byte-equality with the thesis copies
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not THESIS_REPORT.is_dir(), reason="thesis tree not available on this machine")
def test_p1p2_tables_byte_equal():
    _ensure_ledger()
    _run("tables_p1p2.py")
    for name in P1P2_TABLES:
        got = (OUT / name).read_bytes()
        want = (THESIS_REPORT / "tables" / name).read_bytes()
        assert got == want, name


def test_p1p2_tables_every_cell_wrapped_and_no_ghosts():
    _ensure_ledger()
    _run("tables_p1p2.py")
    for name in P1P2_TABLES:
        tex = (OUT / name).read_text()
        assert "\\REV{" in tex
        # ghost-number ban: the pre-caliber era's headline digits must not appear
        for ghost in ("117 events", "0{,}204", "41{,}376", "$-$0.371", "$-$0.139", "0.374"):
            assert ghost not in tex, f"{name}: pre-caliber ghost {ghost!r}"


# ---------------------------------------------------------------------------
# fig_p1.py / fig_p2.py — real PDFs, every plotted number from the ledger
# ---------------------------------------------------------------------------

def _load_fig_module(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "analysis/paper" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _check_nested_plotted_values(mod, ledger_path):
    ledger = json.loads(ledger_path.read_text())
    assert mod.PLOTTED_VALUES, "PLOTTED_VALUES is empty"
    for cell, sub in mod.PLOTTED_VALUES.items():
        assert cell in ledger, f"PLOTTED_VALUES cell {cell!r} not in the ledger"
        for key, val in sub.items():
            assert val == ledger[cell][key], (
                f"mismatch on {cell}.{key}: plotted {val!r} != ledger {ledger[cell][key]!r}")


def test_fig_p1():
    ledger_path = _ensure_ledger()
    _run("fig_p1.py")
    pdf = OUT / "fig_p1.pdf"
    assert pdf.exists() and pdf.stat().st_size > 5_000
    mod = _load_fig_module("fig_p1")
    _check_nested_plotted_values(mod, ledger_path)
    for cell in ("p1_econ", "p1_chemistry", "p1_math_stats"):
        assert cell in mod.PLOTTED_VALUES
        assert "placebos" in mod.PLOTTED_VALUES[cell], "P1 figure must show the REAL placebos"


def test_fig_p2():
    ledger_path = _ensure_ledger()
    _run("fig_p2.py")
    pdf = OUT / "fig_p2.pdf"
    assert pdf.exists() and pdf.stat().st_size > 5_000
    mod = _load_fig_module("fig_p2")
    _check_nested_plotted_values(mod, ledger_path)
    for cell in ("p2_econ", "p2_chemistry", "p2_math_stats"):
        assert cell in mod.PLOTTED_VALUES
        assert "raw_rate_by_event_time_pp" in mod.PLOTTED_VALUES[cell], (
            "P2 figure's lower row must be the raw first-tie-with-star rate by event time")


# ---------------------------------------------------------------------------
# sentinel wiring — the new exhibits are inside tools/check_paper.py's inventory
# ---------------------------------------------------------------------------

def test_sentinel_names_the_p1p2_exhibits():
    src = (REPO / "tools/check_paper.py").read_text(encoding="utf-8")
    for need in ("data_numbers_p1p2.json", "data_numbers_2026-10-23_p1p2.json",
                 "tab_p1_main.tex", "tab_p1_full.tex", "tab_p2_main.tex", "tab_p2_full.tex",
                 "fig_p1.pdf", "fig_p2.pdf", "gaps_switchers_p1p2"):
        assert need in src, f"tools/check_paper.py does not wire in {need}"


@pytest.mark.skipif(not THESIS_REPORT.is_dir(), reason="thesis tree not available on this machine")
def test_sentinel_all_green_and_grew_past_395():
    # 2026-09-23 (cal2026-10): RED BY DESIGN and deliberately not relaxed -- 12 sentences wait for the
    # author (tests/_paper_author_pending.py, not shipped); see the added test below for the exact expected FAIL set.
    # 2026-09-23 (later): GREEN again -- the author's sentence rewrites were applied
    # (by a private manuscript tool, not shipped): 1003 checks, 1003 PASS, 0 FAIL. Unchanged, still strict.
    if RSCRIPT is None and not (OUT / "gaps_switchers.json").exists():
        pytest.skip("Rscript unavailable and the R gap outputs are absent")
    r = subprocess.run([sys.executable, str(REPO / "tools/check_paper.py")],
                       capture_output=True, text=True, cwd=REPO)
    report = (P["output"] / "paper_check.md").read_text()
    lines = [ln for ln in report.splitlines() if ln.startswith("- PASS") or ln.startswith("- FAIL")]
    fails = [ln for ln in lines if ln.startswith("- FAIL")]
    assert r.returncode == 0, f"sentinel not green:\n" + "\n".join(fails)
    assert len(lines) > 395, f"check count did not grow past 395 (got {len(lines)})"


def _load_author_pending():
    # the registry describes the author's working manuscript; it is not shipped in the public package
    if not (REPO / "tests/_paper_author_pending.py").is_file():   # not shipped in the public copy
        return None
    spec = importlib.util.spec_from_file_location("paper_author_pending", REPO / "tests/_paper_author_pending.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(not THESIS_REPORT.is_dir(), reason="thesis tree not available on this machine")
def test_sentinel_fails_are_exactly_the_author_pending_spans_and_grew_past_395():
    # 2026-09-23 (cal2026-10), ADDED next to test_sentinel_all_green_and_grew_past_395, which stays strict
    # and red until the author rewrites the spans the October re-pin refused. The precise expected
    # state meanwhile: the FAIL lines are exactly the
    # registered author-pending lines of tests/_paper_author_pending.py (not shipped; set equality, exact text), the
    # exit code is 1 iff that registry is non-empty, and the inventory still grew past 395 checks.
    # 2026-09-23 (after the author's sentence rewrites were applied): the registry is EMPTY, so this now
    # asserts the registry is empty, the sentinel is all green (no FAIL, exit 0), and the twelve formerly
    # registered pins (RESOLVED_2026_09_23) are each still graded and PASS, with their old FAIL lines gone.
    if RSCRIPT is None and not (OUT / "gaps_switchers.json").exists():
        pytest.skip("Rscript unavailable and the R gap outputs are absent")
    pending = _load_author_pending()
    if pending is None:
        pytest.skip("the registry of author-pending manuscript spans (tests/_paper_author_pending.py) is not shipped")
    assert pending.AUTHOR_PENDING_FAIL_LINES == frozenset() and len(pending.RESOLVED_NAMES) == 12
    r = subprocess.run([sys.executable, str(REPO / "tools/check_paper.py")],
                       capture_output=True, text=True, cwd=REPO)
    report = (P["output"] / "paper_check.md").read_text()
    lines = [ln for ln in report.splitlines() if ln.startswith("- PASS") or ln.startswith("- FAIL")]
    fails = [ln for ln in lines if ln.startswith("- FAIL")]
    assert set(fails) == pending.AUTHOR_PENDING_FAIL_LINES and len(fails) == len(set(fails)), (
        "sentinel FAILs differ from the registered author-pending spans:\n  unexpected: "
        + "\n  ".join(sorted(set(fails) - pending.AUTHOR_PENDING_FAIL_LINES)) + "\n  no longer failing: "
        + "\n  ".join(sorted(pending.AUTHOR_PENDING_FAIL_LINES - set(fails))))
    assert r.returncode == (1 if pending.AUTHOR_PENDING_FAIL_LINES else 0)
    assert not fails and r.returncode == 0, "\n".join(fails)
    problems = pending.resolved_problems(report)
    assert not problems, "\n".join(problems)
    assert len(lines) > 395, f"check count did not grow past 395 (got {len(lines)})"
