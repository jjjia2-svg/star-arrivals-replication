import importlib.util
import json, pathlib, shutil, subprocess, sys
import pytest
REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from analysis.lib.paths import load_paths

P = load_paths()
THESIS_REPORT = P["legacy_thesis"] / "thesis_report"
RSCRIPT = shutil.which("Rscript")


def _run(script):
    r = subprocess.run([sys.executable, str(REPO / "analysis/paper" / script)],
                        capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    return r


@pytest.mark.skipif(not THESIS_REPORT.is_dir(), reason="thesis tree not available on this machine")
def test_p3afar_ledger_equals_thesis():
    _run("ledger_p3afar.py")
    got = json.loads((P["output"] / "paper/data_numbers_p3afar.json").read_text())
    want = json.loads((THESIS_REPORT / "data_numbers_2026-10-23_p3afar.json").read_text())
    got.pop("_source_note", None)
    want.pop("_source_note", None)
    assert got == want


@pytest.mark.skipif(not THESIS_REPORT.is_dir(), reason="thesis tree not available on this machine")
def test_p3afar_tables_byte_equal():
    _run("tables_p3afar.py")
    for name in ["tab_p3_afar.tex", "tab_p3_afar_full.tex"]:
        got = (P["output"] / "paper" / name).read_bytes()
        want = (THESIS_REPORT / "tables" / name).read_bytes()
        assert got == want, name


def _load_computed_keys():
    spec = importlib.util.spec_from_file_location("ledger_main", REPO / "analysis/paper/ledger_main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # cheap: computation is under __main__ (M2 fix wave)
    return mod.COMPUTED_KEYS


def _load_carried_module():
    spec = importlib.util.spec_from_file_location("ledger_carried", REPO / "analysis/paper/ledger_carried.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # cheap: computation is under __main__
    return mod


@pytest.mark.skipif(not THESIS_REPORT.is_dir(), reason="thesis tree not available on this machine")
def test_ledger_carried_matches_thesis():
    mod = _load_carried_module()
    carried_keys, unreproducible = list(mod.CARRIED_KEYS), dict(mod.UNREPRODUCIBLE)
    assert len(carried_keys) == len(set(carried_keys)), "CARRIED_KEYS has duplicates"

    want = json.loads((THESIS_REPORT / "data_numbers_2026-10-23.json").read_text())
    missing_in_thesis = [k for k in carried_keys if k not in want]
    assert not missing_in_thesis, f"CARRIED_KEYS not in the thesis ledger: {missing_in_thesis}"

    _run("ledger_carried.py")
    got = json.loads((P["output"] / "paper/data_numbers_carried.json").read_text())
    got_keys = {k for k in got if not k.startswith("_")}

    # nothing silently skipped: derived ∪ UNREPRODUCIBLE == the authoritative carried list, disjointly
    assert got_keys & set(unreproducible) == set(), "a key is both derived and UNREPRODUCIBLE"
    assert got_keys | set(unreproducible) == set(carried_keys), (
        f"coverage drift: extra={got_keys | set(unreproducible) - set(carried_keys)} "
        f"missing={set(carried_keys) - got_keys - set(unreproducible)}")
    for reason in unreproducible.values():
        assert isinstance(reason, str) and reason.strip(), "UNREPRODUCIBLE reason must be a non-empty string"

    for key in sorted(got_keys):
        assert got[key] == want[key], f"mismatch on key {key!r}: got {got[key]!r} != thesis {want[key]!r}"


@pytest.mark.skipif(not THESIS_REPORT.is_dir(), reason="thesis tree not available on this machine")
def test_ledger_main_matches_thesis_keys():
    computed_keys = _load_computed_keys()
    assert len(computed_keys) >= 20, "COMPUTED_KEYS looks too small for what partA computes"
    assert len(computed_keys) == len(set(computed_keys)), "COMPUTED_KEYS has duplicates"

    _run("ledger_main.py")
    got = json.loads((P["output"] / "paper/data_numbers_main.json").read_text())
    want = json.loads((THESIS_REPORT / "data_numbers_2026-10-23.json").read_text())

    missing = [k for k in computed_keys if k not in got]
    assert not missing, f"ledger_main.py did not write these COMPUTED_KEYS: {missing}"

    for key in computed_keys:
        assert got[key] == want[key], f"mismatch on key {key!r}: got {got[key]!r} != thesis {want[key]!r}"


# ---------------------------------------------------------------------------
# Task 4 — the four number gaps (Zénou worked example, zero-dose shares,
# switcher counts, toy estimator example)
# ---------------------------------------------------------------------------

# The §2.2 worked-example sentence block (sec2_data.tex, Zénou→Monash 2016):
# 2026-09-23 (cal2026-10): thesis_report took the 2026-09-13 draft's text (sync) and then the October
# numbers (the author's re-pin record, not shipped,
# "Zénou, 208-215"). Every value below is typed again from the synced sec2_data.tex sentence it quotes,
# independently of gaps_zenou.py; the pre-October thesis values were 99.7 / 59 / 118 / 94 / 153 / 26 /
# 63 / 0.42 / 151 / 11 / 35 / 35 / 590 / 595 / 5 (kept in gaps_zenou.json["_pre_october_thesis"]).
ZENOU_THESIS = {
    "star_percentile": 99.7,          # "citations placed him at the 99.7th percentile"
    "roster": 60,                      # "The Monash economics roster for 2016 lists 60 incumbents"
    "network": 66,                     # "his coauthorship network within two hops reaches 66 researchers"
    "network_only": 42,                # "42 of whom are not on the roster"
    "union": 102,                      # "The exposure population for this event is therefore 102 incumbents"
    # 2026-09-23: the synced text no longer prints the dose-bin clause (check_paper SYNC_RETIRE
    # "Zenou dose-bin clause cut"), so the thesis-side source of these two facts is the October ledger
    # frozen into the thesis tree, thesis_report/data_numbers_2026-10-23_gaps_zenou.json (3 and 52).
    "dose_below_01": 3,                # data_numbers_2026-10-23_gaps_zenou.json dose_below_01
    "dose_ge_05": 52,                  # data_numbers_2026-10-23_gaps_zenou.json dose_ge_05
    "dose_median": 0.51,               # "with a median dose of 0.51"
    "p2_followed": 100,                # "Panel 2 follows 100 of them"
    "p2_first_ties_post": 6,           # "and 6 first publish with him after his arrival"
    "outside_network": 36,             # "Of the 60 on the roster, 36 are outside the network"
    # 2026-08-30: the Panel 3 topic condition became dose > 0 (both incumbents share at least one
    # subfield with the star); the median cut is now a robustness cell. gaps_zenou.py was
    # recomputed on the new condition and the thesis sentence rewritten with it. The retired cut
    # still returns 26 / 325 / 320, which is the control that the query is otherwise unchanged.
    # 2026-09-23 (cal2026-10): on the October frames the retired median cut (0.3402) gives 25
    # (gaps_zenou.json _provenance.same_topic_outside).
    "same_topic_outside": 36,          # "and all 36 share at least one subfield with him"
    "pairs": 624,                      # "and Panel 3 follows 624"
    "pairs_possible": 630,             # "They form 630 possible pairs"
    "pairs_excluded_prewindow": 6,     # "(the other six had already published together before 2010)"
}


@pytest.mark.skipif(not THESIS_REPORT.is_dir(), reason="thesis tree not available on this machine")
def test_gaps_zenou_matches_thesis():
    _run("gaps_zenou.py")
    got = json.loads((P["output"] / "paper/gaps_zenou.json").read_text())
    assert got.get("UNVERIFIED", []) == [], f"unverified keys: {got['UNVERIFIED']}"
    for key, want in ZENOU_THESIS.items():
        assert got[key] == want, f"mismatch on {key!r}: got {got[key]!r} != thesis {want!r}"


def test_gaps_zero_dose_rounds_to_thesis():
    # sec3_strategy.tex: dose exactly zero = 15 / 10 / 33 percent (econ/chem/math) — the
    # 2026-08-28 caliber values (freeze-wave Task 8; pre-caliber thesis printed 16/9/32)
    # 2026-09-23 (cal2026-10): the synced sec3_strategy.tex now prints "(they share no subfield with the
    # star: 8 percent of relations in economics, 6 in chemistry, 31 in mathematics)" -- the October
    # values the re-pin wrote (the author's re-pin record, not shipped: "sec3_strategy.tex,
    # 8 numbers ... 66-67: zero-dose shares 15/10/33→8/6/31"); typed here from the sentence.
    _run("gaps_zero_dose.py")
    got = json.loads((P["output"] / "paper/gaps_zero_dose.json").read_text())
    for d, want in (("econ", 8), ("chem", 6), ("math", 31)):
        share = got[f"{d}_zero_dose_share_pct"]
        assert round(share) == want, f"{d}: {share} does not round to the thesis's {want}"


def _run_r(script):
    out = P["output"] / "paper"
    r = subprocess.run([RSCRIPT, str(REPO / "analysis/paper" / script)],
                        capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    return out


@pytest.mark.skipif(RSCRIPT is None, reason="Rscript not on PATH")
def test_gaps_switchers_r():
    out = _run_r("gaps_switchers.R") / "gaps_switchers.json"
    assert out.exists()
    got = json.loads(out.read_text())
    assert len(got["horizons"]) == 6
    for h in got["horizons"]:
        assert {"k", "switchers", "n", "appendix_switchers", "matches_appendix"} <= set(h)
    assert got["coef_check"]["pass"] is True          # replication of the frozen gold succeeded
    assert "avg_dose_switchers" in got and "avg_dose_field" in got
    assert isinstance(got["switchers_total_matches_appendix"], bool)
    assert isinstance(got["avg_dose_matches_appendix"], bool)


@pytest.mark.skipif(RSCRIPT is None, reason="Rscript not on PATH")
def test_gaps_toy_r():
    out = _run_r("gaps_toy.R") / "gaps_toy.json"
    assert out.exists()
    got = json.loads(out.read_text())
    # appendix_estimator.tex prints these at 4-5 dp; the R script asserts them, we re-assert here
    assert round(got["effect_1"], 5) == -0.20833
    assert round(got["effect_2"], 5) == 0.0
    assert round(got["av_tot_eff"], 5) == -0.23810
    assert round(got["placebo_1"], 5) == -0.75
    assert round(got["delta_D_avg_total"], 4) == 1.4286


# ---------------------------------------------------------------------------
# Task 5 — the two orphaned figures (exposure-population Venn, dose-distribution
# bars). No thesis-equality assertion here (these are fresh scripts, not ports):
# the spec is (1) a real PDF > 5 KB lands in output/paper/, and (2) every number
# the figure draws is read from the generated main ledger, not hand-typed --
# proven by importing the module and comparing its PLOTTED_VALUES dict against
# the same ledger JSON the test loads independently.
# ---------------------------------------------------------------------------

def _ensure_main_ledger():
    """The generated main ledger, or a loud skip.

    MILESTONE REVIEW, replicator-experience MAJOR: the two figure tests called this, `ledger_main.py`
    read the legacy tree, and a fresh clone's documented `pytest` therefore FAILED rather than
    skipping. The figures are checked against the ledger, and without the ledger there is nothing to
    check — which is a missing input, not a defect.
    """
    ledger = P["output"] / "paper" / "data_numbers_main.json"
    if not ledger.exists():
        if not THESIS_REPORT.is_dir() or not P["legacy_v2_output"].is_dir():
            pytest.skip(
                f"the main ledger has not been generated and cannot be here: `ledger_main.py` reads "
                f"the read-only legacy trees, which this package does not ship "
                f"({P['legacy_v2_output']}). Run `RUN_PAPER=1 bash analysis/run_all.sh` on a machine that has "
                f"them (config keys legacy_thesis / legacy_v2_output); the paper layer is author-only.")
        _run("ledger_main.py")
    return ledger


def _load_fig_module(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "analysis/paper" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _check_plotted_values_against_ledger(mod, ledger_path):
    ledger = json.loads(ledger_path.read_text())
    assert mod.PLOTTED_VALUES, "PLOTTED_VALUES is empty"
    for key, val in mod.PLOTTED_VALUES.items():
        assert key in ledger, f"PLOTTED_VALUES key {key!r} not in the ledger"
        assert val == ledger[key], f"mismatch on {key!r}: plotted {val!r} != ledger {ledger[key]!r}"


def test_fig_exposure_population():
    ledger_path = _ensure_main_ledger()
    _run("fig_exposure_population.py")
    pdf = P["output"] / "paper" / "fig_exposure_population.pdf"
    assert pdf.exists()
    assert pdf.stat().st_size > 5_000, f"{pdf} looks too small to be a real PDF"

    mod = _load_fig_module("fig_exposure_population")
    _check_plotted_values_against_ledger(mod, ledger_path)
    for key in ("econ_relations", "econ_persons", "econ_events"):
        assert key in mod.PLOTTED_VALUES, f"expected {key!r} among the plotted values"


def test_fig_dose_distribution():
    ledger_path = _ensure_main_ledger()
    _run("fig_dose_distribution.py")
    pdf = P["output"] / "paper" / "fig_dose_distribution.pdf"
    assert pdf.exists()
    assert pdf.stat().st_size > 5_000, f"{pdf} looks too small to be a real PDF"

    mod = _load_fig_module("fig_dose_distribution")
    _check_plotted_values_against_ledger(mod, ledger_path)
    for d in ("econ", "chem", "math"):
        for suffix in ("dose_bins_pct", "relations", "dose_na_relations"):
            assert f"{d}_{suffix}" in mod.PLOTTED_VALUES, f"expected {d}_{suffix} among the plotted values"


# ---------------------------------------------------------------------------
# Task 6 — funnel/pipeline counts ledger + the paper sentinel (check_paper)
# ---------------------------------------------------------------------------

# The thesis values the funnel ledger must reproduce, hard-coded here independently
# of the script: appendix_funnel.tex steps 1-3 + the pre-topic-cut pool note, and
# appendix_pipeline.tex's snapshot/benchmark rows.
FUNNEL_THESIS = {
    "works_snapshot": 510_372_821,
    "works_benchmarkable": 375_548_859,
    "works_articles_reviews": 258_400_229,
    "benchmark_cells": 543_037,
    "pairs_pool_pre_cut": {"econ": 724_002, "chemistry": 269_168, "math_stats": 78_478},
    "pairs_dropped_no_dose": {"econ": 0, "chemistry": 659, "math_stats": 6_379},
    # R3 (2026-09-10): the four sec2_data.tex numbers that had no source until now. Values typed
    # here from the manuscript / the records, independently of the script.
    "openalex_subfields": 252,                       # sec2 footnote "252 subfields across all of science"
    "snapshot_release_date": "2026-06-26",           # sec2 "the 26 June 2026 release"
    "u1_universe": {"works": 46_504_474, "authors": 10_497_390, "share_of_snapshot_pct": 9.1},
    "roster_spell_max_start": {"econ": 2025, "chem": 2023, "math": 2020},   # sec2 "no spells beginning in 2024" / "none for 2021--2024"
}


def _load_funnel_module():
    spec = importlib.util.spec_from_file_location("ledger_funnel", REPO / "analysis/paper/ledger_funnel.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # cheap: computation is under __main__
    return mod


@pytest.mark.skipif(not THESIS_REPORT.is_dir(), reason="thesis tree not available on this machine")
def test_ledger_funnel_equals_thesis():
    mod = _load_funnel_module()
    funnel_keys, unreproducible = list(mod.FUNNEL_KEYS), dict(mod.UNREPRODUCIBLE)
    assert set(funnel_keys) == set(FUNNEL_THESIS), "FUNNEL_KEYS drifted from the thesis appendix inventory"

    _run("ledger_funnel.py")
    got = json.loads((P["output"] / "paper/data_numbers_funnel.json").read_text())
    got_keys = {k for k in got if not k.startswith("_")}

    # nothing silently skipped: derived + UNREPRODUCIBLE == the key list, disjointly
    assert got_keys & set(unreproducible) == set(), "a key is both derived and UNREPRODUCIBLE"
    assert got_keys | set(unreproducible) == set(funnel_keys), (
        f"coverage drift: extra={got_keys | set(unreproducible) - set(funnel_keys)} "
        f"missing={set(funnel_keys) - got_keys - set(unreproducible)}")
    for reason in unreproducible.values():
        assert isinstance(reason, str) and reason.strip(), "UNREPRODUCIBLE reason must be a non-empty string"

    for key in sorted(got_keys):
        assert got[key] == FUNNEL_THESIS[key], (
            f"mismatch on key {key!r}: got {got[key]!r} != thesis {FUNNEL_THESIS[key]!r}")


def _run_sentinel(extra_args=()):
    r = subprocess.run([sys.executable, str(REPO / "tools/check_paper.py"), *extra_args],
                       capture_output=True, text=True, cwd=REPO)
    report = (P["output"] / "paper_check.md").read_text()
    lines = [ln for ln in report.splitlines() if ln.startswith("- PASS") or ln.startswith("- FAIL")]
    fails = [ln for ln in lines if ln.startswith("- FAIL")]
    return r, lines, fails


def _load_author_pending():
    """tests/_paper_author_pending.py (not shipped): the sentinel FAILs registered 2026-09-23 as waiting for the
    author's rewrite of the manuscript (the spans the October re-pin refused). The registry describes the
    author's working manuscript and is not shipped in the public package; without it (and without the
    manuscript tree) the tests that need it skip. Loaded by path: tests/ is not a package."""
    if not (REPO / "tests/_paper_author_pending.py").is_file():   # not shipped in the public copy
        return None
    spec = importlib.util.spec_from_file_location("paper_author_pending", REPO / "tests/_paper_author_pending.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PENDING = _load_author_pending()
needs_pending = pytest.mark.skipif(PENDING is None, reason="the registry of author-pending manuscript "
                                   "spans (tests/_paper_author_pending.py) is not shipped")


def _assert_only_author_pending(r, fails):
    """The live sentinel's state since 2026-09-23: its FAIL lines are EXACTLY the registered
    author-pending lines (set equality: a new FAIL and a stale registry entry both fail), and it
    exits 1 iff that set is non-empty. Used where a test's precondition used to be "all green"; the
    strict all-green tests themselves are unchanged and stay red until the author rewrites the spans.
    2026-09-23 (after the sentence rewrites were applied): the registry is empty, so this now requires
    zero FAILs and exit 0 -- "all green" again."""
    assert set(fails) == PENDING.AUTHOR_PENDING_FAIL_LINES and len(fails) == len(set(fails)), (
        "sentinel FAILs differ from the registered author-pending spans:\n  unexpected: "
        + "\n  ".join(sorted(set(fails) - PENDING.AUTHOR_PENDING_FAIL_LINES)) + "\n  no longer failing: "
        + "\n  ".join(sorted(PENDING.AUTHOR_PENDING_FAIL_LINES - set(fails))))
    assert r.returncode == (1 if PENDING.AUTHOR_PENDING_FAIL_LINES else 0), r.stdout[-2000:] + r.stderr[-2000:]


@pytest.mark.skipif(not THESIS_REPORT.is_dir(), reason="thesis tree not available on this machine")
@needs_pending
def test_check_paper_catches_comment_shadowed_edit(tmp_path):
    # T6 review MAJOR-1 regression: editing a checked sentence while leaving the OLD wording
    # in a % comment must NOT keep the sentinel green — norm_tex strips unescaped comments
    # before matching, so the live (wrong) number is what gets checked. Runs the sentinel
    # against a perturbed scratch copy via --sections-dir (NIT-1).
    if RSCRIPT is None and not (P["output"] / "paper/gaps_switchers.json").exists():
        pytest.skip("Rscript unavailable and the R gap outputs are absent")
    for f in (THESIS_REPORT / "sections").glob("*.tex"):
        shutil.copy(f, tmp_path / f.name)
    tex = tmp_path / "sec2_data.tex"
    body = tex.read_text()
    # 2026-09-23 (cal2026-10): the synced sec2_data.tex prints the October roster count (60, not 59;
    # gaps_zenou.json roster) and wraps the sentence after "2016", so the raw text has a newline where
    # the old one had a space; the pin is renamed "sec2_data Zenou: roster 60" (repin.py).
    live = "roster for 2016\nlists 60 incumbents"
    assert body.count(live) == 1
    tex.write_text("% old: The Monash economics roster for 2016 lists 60 incumbents; his\n"
                   + body.replace(live, "roster for 2016\nlists 61 incumbents"))

    r, lines, fails = _run_sentinel(["--sections-dir", str(tmp_path)])
    assert r.returncode == 1
    # 2026-09-23: the scratch copy carries the live text's registered author-pending FAILs too
    # (tests/_paper_author_pending.py, not shipped); the shadowed roster FAIL must be the ONE line on top of them.
    # 2026-09-23 (after the sentence rewrites): that registry is empty, so the shadowed roster FAIL
    # must be the ONLY FAIL.
    assert not PENDING.AUTHOR_PENDING_FAIL_LINES, "the author-pending registry is expected to be empty"
    extra = set(fails) - PENDING.AUTHOR_PENDING_FAIL_LINES
    assert PENDING.AUTHOR_PENDING_FAIL_LINES <= set(fails) and len(fails) == len(set(fails)), (
        "the registered author-pending FAILs changed:\n" + "\n".join(fails))
    assert len(extra) == 1, "expected exactly the shadowed roster FAIL:\n" + "\n".join(sorted(extra))
    assert any("Zenou: roster 60" in ln for ln in extra), (
        "comment-shadowed edit was NOT caught (false PASS):\n" + "\n".join(fails))


@pytest.mark.skipif(not THESIS_REPORT.is_dir(), reason="thesis tree not available on this machine")
def test_check_paper_sentinel_all_green():
    # NOTE (flipped by Task 7): before the errata this test asserted exit 1 with exactly
    # one FAIL — the stale "7.1 percent" any-reference sentence in sec2_data.tex, which
    # the current ledger contradicted (econ_share_any_ref = 4.5). Task 7 corrected the
    # thesis sentence (7.1 -> 4.5, \REV-marked), so the sentinel must now be fully green.
    # 2026-09-23 (cal2026-10): RED BY DESIGN, and deliberately NOT relaxed. The October numbers left 12
    # sentences the author must rewrite (the spans the re-pin refused: sign flips, p<0.001 no longer
    # met). This test turns green only when they are
    # rewritten; until then test_check_paper_fails_are_exactly_the_author_pending_spans below pins the
    # exact FAIL set (tests/_paper_author_pending.py, not shipped).
    # 2026-09-23 (later): GREEN again -- the author's sentence rewrites were applied
    # (by a private manuscript tool, not shipped): 1003 checks, 1003 PASS, 0 FAIL. Unchanged, still strict.
    if RSCRIPT is None and not (P["output"] / "paper/gaps_switchers.json").exists():
        pytest.skip("Rscript unavailable and the R gap outputs are absent")
    r, lines, fails = _run_sentinel()
    assert r.returncode == 0, f"expected exit 0 (errata applied): {r.stdout}{r.stderr}"
    # The M2 milestone fix wave (main.tex, tab:events cells, spans, figure PDFs, ...) pushed
    # the count from 313 to 395; raise the floor so a future regression that silently drops
    # a whole check block is still caught, while leaving headroom for legitimate additions.
    assert len(lines) >= 380, f"only {len(lines)} checks ran; expected the full inventory (>=380)"
    assert not fails, "expected zero FAILs after the Task-7 errata:\n" + "\n".join(fails)


@pytest.mark.skipif(not THESIS_REPORT.is_dir(), reason="thesis tree not available on this machine")
@needs_pending
def test_check_paper_fails_are_exactly_the_author_pending_spans():
    # 2026-09-23 (cal2026-10), ADDED next to test_check_paper_sentinel_all_green, which stays strict and
    # red: this one states the precise expected state while the author has not yet rewritten the
    # refused spans. Every FAIL is a registered author-pending line (exact text: name, printed literal,
    # October ledger value), every registered line still FAILs, each belongs to a span the committed
    # record lists as refused, and the inventory is still the full one (the same >=380 floor).
    # 2026-09-23 (after the author's sentence rewrites were applied): the registry is EMPTY and the
    # sentinel all green. So this now asserts exactly that -- no registered line, no FAIL, exit 0 -- and
    # that the twelve formerly registered pins (RESOLVED_2026_09_23) are each still graded and PASS on the
    # live text, their old FAIL lines are gone, and their spans are still refusals of the record.
    if RSCRIPT is None and not (P["output"] / "paper/gaps_switchers.json").exists():
        pytest.skip("Rscript unavailable and the R gap outputs are absent")
    r, lines, fails = _run_sentinel()
    assert len(lines) >= 380, f"only {len(lines)} checks ran; expected the full inventory (>=380)"
    assert PENDING.AUTHOR_PENDING_FAIL_LINES == frozenset() and PENDING.AUTHOR_PENDING_NAMES == frozenset()
    assert len(PENDING.RESOLVED_NAMES) == 12
    _assert_only_author_pending(r, fails)
    assert not fails and r.returncode == 0, "\n".join(fails)
    problems = PENDING.resolved_problems((P["output"] / "paper_check.md").read_text())
    assert not problems, "\n".join(problems)
    refusals = PENDING.record_refusals()
    for name in PENDING.AUTHOR_PENDING_NAMES:
        anchor = PENDING.REFUSAL_ANCHOR[name]
        assert any(x.startswith(anchor + " ") for x in refusals), (
            f"{name}: its span {anchor} is not a refusal in {PENDING.RECORD.relative_to(REPO)}")


R3_SEC2_PINS = ("sec2 OpenAlex subfields 252", "sec2 ranking pool 10.5 million authors",
                "sec2 chem roster no spell starts in 2024", "sec2 math roster no spell starts from 2021",
                "sec2 math roster edge after 2020", "sec2 chem roster edge nominal in 2024",
                "sec2 snapshot release day 26", "sec2 snapshot release year 2026")
# 2026-09-23 (sync): the two of them the synced sec2_data.tex no longer prints (tools/check_paper.py
# claims_table SYNC_RETIRE: "subfield-count clause cut" / "roster-edge footnote now says 'after 2020' only")
R3_SEC2_RETIRED = ("sec2 OpenAlex subfields 252", "sec2 math roster no spell starts from 2021")


@pytest.mark.skipif(not THESIS_REPORT.is_dir(), reason="thesis tree not available on this machine")
def test_robustness_ledger_equals_thesis():
    # 2026-09-13: the Section 4.2 ledger (bounds, levels, never-exposed pool, post-departure zeros,
    # Panel 1/2/3 date shifts, departure A/B, research-centre rosters) regenerates from the frozen
    # artifacts (each sha256-pinned) and equals the thesis copy key for key.
    _run("ledger_robustness.py")
    got = json.loads((P["output"] / "paper/data_numbers_robustness.json").read_text())
    want = json.loads((THESIS_REPORT / "data_numbers_2026-10-23_robustness.json").read_text())
    got.pop("_source_note", None); want.pop("_source_note", None)
    assert got == want
    # the same frozen file read by two ledgers gives one number
    p3 = json.loads((P["output"] / "paper/data_numbers_p3afar.json").read_text())
    for f in ("econ", "chemistry", "math_stats"):
        assert got["p3_date_shift"][f]["p_joint_shifted"] == p3[f]["robustness"]["date_shift_two_years"]["p_joint_shifted"]


@pytest.mark.skipif(not THESIS_REPORT.is_dir(), reason="thesis tree not available on this machine")
def test_robustness_tables_byte_equal(tmp_path):
    _run("tables_robustness.py")
    for name in ("tab_rob_p1.tex", "tab_rob_p2.tex", "tab_rob_p3.tex"):
        got = (P["output"] / "paper" / name).read_bytes()
        want = (THESIS_REPORT / "tables" / name).read_bytes()
        assert got == want, name
    # 2026-09-23 (cal2026-10 sync): the thesis's tables/tab_robustness.tex is now the 2026-09-13 draft's
    # Table 3, written by analysis/paper/draft_2026_09_13_tables.py (run_all's paper_draft_tables stage;
    # tools/check_paper.py section B, B_DRAFT_TABLES), not tables_robustness.py's appendix table of the
    # same name, which the thesis no longer carries (install.py did not copy it; its cells are checked
    # one by one in output/paper by check_paper's section_d_rob_tables). So the thesis copy is compared
    # with a fresh run of the generator that now produces it.
    r = subprocess.run([sys.executable, str(REPO / "analysis/paper/draft_2026_09_13_tables.py"),
                        "--out-dir", str(tmp_path)], capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    name = "tab_robustness.tex"
    assert (tmp_path / name).read_bytes() == (THESIS_REPORT / "tables" / name).read_bytes(), name


ROB_TABLE_PINS = ("rob P1 main [econ] est", "rob P1 date-shift p [econ]", "rob P1 not-yet-exposed [chem] se",
                  "rob P2 permutation p [math]", "rob P3 null sim [chem]", "rob P3 median cut [econ] est",
                  "rob A1 departure A [econ] est", "rob A1 no-centre [math] est", "rob A1 levels [econ] se",
                  "rob A1 roster route joint p [econ]", "rob A1 shifted coefficients [econ]",
                  "rob A2 shifted coefficients [chem]", "rob A3 departure B pairs [econ]",
                  "rob A3 median cut joint p [chem]")


@pytest.mark.skipif(not THESIS_REPORT.is_dir(), reason="thesis tree not available on this machine")
@needs_pending
def test_check_paper_pins_robustness_table_cells(tmp_path):
    # Every cell pin on the Section 4.2 tables must PASS on the live tables and FAIL when the
    # printed cell is perturbed in a scratch copy of tables/ (a pin that cannot go red is not a pin).
    if RSCRIPT is None and not (P["output"] / "paper/gaps_switchers.json").exists():
        pytest.skip("Rscript unavailable and the R gap outputs are absent")
    r, lines, fails = _run_sentinel()
    # 2026-09-23 (cal2026-10): the live baseline is "exactly the registered author-pending FAILs"
    # (tests/_paper_author_pending.py, not shipped), none of which is a table cell; it used to be all green.
    # 2026-09-23 (after the sentence rewrites): that registry is empty, so the baseline is all green again.
    _assert_only_author_pending(r, fails)
    for name in ROB_TABLE_PINS:
        assert any(ln.startswith("- PASS") and name in ln for ln in lines), f"pin missing: {name}"
    for f in (THESIS_REPORT / "tables").glob("*.tex"):
        shutil.copy(f, tmp_path / f.name)
    # 2026-09-23 (cal2026-10): every cell below is the October value the table prints now (the
    # pre-October cells were -0.378 (0.062), 0.005, -0.058 (0.203), 0.347, -0.244, -0.133 (0.049),
    # -0.387 (0.062), -0.191 (0.145), -0.820 (1.420), 0.016 / <0.001, the 0.021 and 0.114 standard
    # errors, 88,176 and 0.240). The six "rob P1/P2/P3" pins read tables_robustness.py's
    # tab_robustness.tex from output/paper/, NOT from --tables-dir: since the sync the thesis file of
    # that name is the draft's Table 3 (check_paper section_d_rob_tables). So that file is perturbed in
    # place and restored in `finally` (the pattern of test_check_paper_fails_on_dropped_ledger_key); the
    # three appendix tables are still read from the tables dir and are perturbed in the scratch copy.
    out_edits = (("\\REV{$-$0.368 (0.066)}", "\\REV{$-$0.369 (0.066)}"),                  # P1 main econ est
                 ("\\REV{0.199} & \\REV{0.590}", "\\REV{0.198} & \\REV{0.590}"),          # P1 date-shift p econ
                 ("\\REV{$-$0.157 (0.198)}", "\\REV{$-$0.157 (0.199)}"),                  # P1 not-yet-exposed chem se
                 ("\\REV{0.084} & \\REV{0.012} & \\REV{0.146}",
                  "\\REV{0.084} & \\REV{0.012} & \\REV{0.147}"),                          # P2 permutation p math
                 ("\\REV{0.006} & \\REV{$-$0.249}", "\\REV{0.006} & \\REV{$-$0.250}"),    # P3 null sim chem
                 ("\\REV{$-$0.079 (0.038)}", "\\REV{$-$0.080 (0.038)}"))                  # P3 median cut econ
    edits = {"tab_rob_p1.tex": (
                 ("\\REV{$-$0.387 (0.079)}", "\\REV{$-$0.386 (0.079)}"),                  # departure A econ
                 ("\\REV{$-$0.125 (0.156)}", "\\REV{$-$0.126 (0.156)}"),                  # no-centre math
                 ("\\REV{$-$3.456 (0.871)}", "\\REV{$-$3.456 (0.872)}"),                  # levels econ se
                 ("\\REV{$-$0.355 (0.078)} & \\REV{0.024 / $<$0.001}",
                  "\\REV{$-$0.355 (0.078)} & \\REV{0.024 / 0.002}"),                      # roster-route joint p econ
                 ("\\REV{$-$0.035 (0.020), $-$0.037 (0.026)}",
                  "\\REV{$-$0.035 (0.020), $-$0.037 (0.027)}")),                          # shifted coefficients econ
             "tab_rob_p2.tex": (
                 ("\\REV{0.072 (0.083), $-$0.227 (0.190)}",
                  "\\REV{0.072 (0.083), $-$0.227 (0.191)}"),),                            # P2 shifted, chemistry
             "tab_rob_p3.tex": (
                 ("\\REV{$-$0.065 (0.057)} & \\REV{$<$0.001} & \\REV{90{,}325}",
                  "\\REV{$-$0.065 (0.057)} & \\REV{$<$0.001} & \\REV{90{,}326}"),          # departure B pairs econ
                 ("\\REV{$-$0.642 (0.293)} & \\REV{0.207}",
                  "\\REV{$-$0.642 (0.293)} & \\REV{0.208}"))}                             # median cut joint p chem

    def perturb(body, pairs, fname):
        for a, b in pairs:
            assert body.count(a) >= 1, (fname, a)
            body = body.replace(a, b, 1)
        return body
    for fname, pairs in edits.items():
        (tmp_path / fname).write_text(perturb((tmp_path / fname).read_text(), pairs, fname))
    out_tab = P["output"] / "paper" / "tab_robustness.tex"
    original = out_tab.read_bytes()
    try:
        out_tab.write_text(perturb(original.decode(), out_edits, "output/paper/tab_robustness.tex"))
        r, lines, fails = _run_sentinel(["--tables-dir", str(tmp_path)])
    finally:
        out_tab.write_bytes(original)
    assert r.returncode == 1
    failed = {name for name in ROB_TABLE_PINS if any(name in ln for ln in fails)}
    assert failed == set(ROB_TABLE_PINS), (
        f"pins that stayed green under perturbation: {set(ROB_TABLE_PINS) - failed}\n" + "\n".join(fails))


@pytest.mark.skipif(not THESIS_REPORT.is_dir(), reason="thesis tree not available on this machine")
@needs_pending
def test_check_paper_pins_the_four_unsourced_sec2_numbers(tmp_path):
    # R3 (2026-09-10): the four sec2_data.tex numbers that had no ledger key (252 subfields, the
    # 10.5 million-author ranking pool, the roster spell-start ceilings 2024 / 2021--2024 / after
    # 2020, the 26 June 2026 snapshot) are now funnel-ledger keys with sentinel pins. Every pin
    # must be present and PASS on the live text, and each must FAIL when its number is perturbed
    # in a scratch copy — a pin that cannot go red is not a pin.
    if RSCRIPT is None and not (P["output"] / "paper/gaps_switchers.json").exists():
        pytest.skip("Rscript unavailable and the R gap outputs are absent")
    r, lines, fails = _run_sentinel()
    # 2026-09-23 (cal2026-10): the live baseline is "exactly the registered author-pending FAILs"
    # (tests/_paper_author_pending.py, not shipped; none is in sec2_data.tex); it used to be all green.
    # 2026-09-23 (after the sentence rewrites): that registry is empty, so the baseline is all green again.
    _assert_only_author_pending(r, fails)
    report = (P["output"] / "paper_check.md").read_text()
    # 2026-09-23 (sync): the synced sec2_data.tex no longer prints two of the eight numbers; check_paper's
    # SYNC_RETIRE lists them ("subfield-count clause cut"; "roster-edge footnote now says 'after 2020'
    # only"). A retired pin is reported RETIRED while its regex finds nothing and is graded again as soon
    # as its sentence reappears -- so for those two, "present" means listed as RETIRED (never silently
    # dropped) and "can go red" means a reappearing sentence with a wrong number FAILs (proved below,
    # with a control that the right number PASSes). The other six are printed and must PASS.
    for name in R3_SEC2_PINS:
        if name in R3_SEC2_RETIRED:
            assert any(ln.startswith(f"- RETIRED {name} — ") for ln in report.splitlines()), f"not listed as retired: {name}"
            assert not any(name in ln for ln in lines), f"a retired pin was graded on the live text: {name}"
        else:
            assert any(ln.startswith("- PASS") and name in ln for ln in lines), f"pin missing: {name}"

    for f in (THESIS_REPORT / "sections").glob("*.tex"):
        shutil.copy(f, tmp_path / f.name)
    tex = tmp_path / "sec2_data.tex"
    live = tex.read_text()
    # 2026-09-23: the synced wording (sec2_data.tex): "The ranking pool, 10.5 million extracted authors",
    # "staff lists show no one starting in 2024 in chemistry or after 2020 in / mathematics" (one regex,
    # both chemistry pins read its first number), "The / analysis uses the 26 June 2026 release".
    edits = (("The ranking pool, 10.5 million extracted authors", "The ranking pool, 10.6 million extracted authors"),
             ("show no one starting in 2024 in chemistry", "show no one starting in 2025 in chemistry"),
             ("in chemistry or after 2020 in", "in chemistry or after 2019 in"),
             ("analysis uses the 26 June 2026 release", "analysis uses the 27 July 2025 release"))
    body = live
    for a, b in edits:
        assert body.count(a) == 1, a
        body = body.replace(a, b)

    def with_retired_sentences(text, subfields, first_year):
        # the two retired sentences, re-printed at the end of the section in their check_paper regex form
        return (text + f"\nOpenAlex says there are {subfields} subfields across all of science, and the"
                f"\nmathematics rosters record none for {first_year}--2024.\n")
    tex.write_text(with_retired_sentences(body, 253, 2022))            # wrong numbers
    r, lines, fails = _run_sentinel(["--sections-dir", str(tmp_path)])
    assert r.returncode == 1
    failed = {name for name in R3_SEC2_PINS if any(name in ln for ln in fails)}
    assert failed == set(R3_SEC2_PINS), (
        f"pins that stayed green under perturbation: {set(R3_SEC2_PINS) - failed}\n" + "\n".join(fails))
    # nothing but the eight pins and the registered author-pending lines (which the copy still carries;
    # 2026-09-23 after the rewrites: none, so exactly the eight pins)
    assert {n for n in map(PENDING.fail_name, fails)} == set(R3_SEC2_PINS) | PENDING.AUTHOR_PENDING_NAMES
    assert len(fails) == len(R3_SEC2_PINS) + len(PENDING.AUTHOR_PENDING_FAIL_LINES), (
        "unexpected extra FAILs:\n" + "\n".join(fails))
    # control: the same two sentences with the ledger's numbers are graded PASS, so the red above came
    # from the numbers, not from the sentences' mere reappearance
    tex.write_text(with_retired_sentences(live, 252, 2021))
    r, lines, fails = _run_sentinel(["--sections-dir", str(tmp_path)])
    _assert_only_author_pending(r, fails)
    for name in R3_SEC2_RETIRED:
        assert any(ln.startswith("- PASS") and name in ln for ln in lines), f"re-printed retired pin not graded: {name}"


@pytest.mark.skipif(not THESIS_REPORT.is_dir(), reason="thesis tree not available on this machine")
def test_check_paper_fails_on_dropped_ledger_key(tmp_path):
    # M2 milestone review MAJOR-1 (and the T3-review global-union test that was never
    # implemented): section A iterates the THESIS ledgers' keys, so a key that vanishes from
    # a generated ledger — e.g. quietly moved into an _unreproducible block by a future edit,
    # or dropped outright — must FAIL as a coverage hole, never shrink the count silently.
    if RSCRIPT is None and not (P["output"] / "paper/gaps_switchers.json").exists():
        pytest.skip("Rscript unavailable and the R gap outputs are absent")
    ledger = P["output"] / "paper" / "data_numbers_carried.json"
    if not ledger.exists():
        _run("ledger_carried.py")
    original = ledger.read_bytes()
    try:
        mutated = json.loads(original)
        assert "chem_centre_added" in mutated
        del mutated["chem_centre_added"]          # drop a generated key; declare nothing
        ledger.write_text(json.dumps(mutated))
        r, lines, fails = _run_sentinel()
        assert r.returncode == 1, "sentinel stayed green with a generated ledger key missing"
        assert any("chem_centre_added" in ln and "coverage hole" in ln for ln in fails), (
            "the dropped key was not reported as a coverage hole:\n" + "\n".join(fails))
    finally:
        ledger.write_bytes(original)


# ---------------------------------------------------------------------------
# M3 Task 8 — the Panel-3 ledger reads this package's frozen frames
# ---------------------------------------------------------------------------

def test_t8_p3afar_ledger_reads_the_frozen_frames_not_the_legacy_run_directory():
    """The same defect the T4 review named "the freeze is inert", one ledger further on.

    `ledger_p3afar.py` used to read its topic counts, its speed bracket and all three A_far
    pair-year panels out of `legacy_v2_output/p3_topicpair_2026-08-17/data/` — four files that were
    already in this package, byte for byte, as `data/frames/p3_afar_*`. So the paper's whole Panel-3
    block needed the author's read-only thesis tree to regenerate even though nothing in it was
    missing from the package.

    Two halves, both falsifiable: the pointer moved (source assertion, runs anywhere), and the
    frozen copies really are the legacy bytes (sha256, only where the legacy tree is present). The
    numbers cannot move as a result — that is what byte-identical means — and
    `test_p3afar_ledger_equals_thesis` above still compares every value with the thesis ledger.
    """
    src = (REPO / "analysis/paper/ledger_p3afar.py").read_text(encoding="utf-8")
    assert 'FR = P["frames"]' in src, (
        "ledger_p3afar no longer reads the frozen frames - the freeze is inert again")
    # 2026-08-30: the Panel 3 main specification became dose > 0, so the counts file the ledger
    # reads is the per-spec one and the panel it reads is named by SPEC_MAIN. The speed bracket
    # read is GONE, not renamed: the exhibit was deleted from Section 4.1 because its
    # counterfactual paths were computed on the 22 August event set and had no rebuilt
    # counterpart under the corrected one.
    assert 'FR / "p3_afar_counts_by_spec.csv"' in src
    assert 'str(FR / f"p3_afar_{SPEC_MAIN}_{field}.parquet")' in src
    assert 'FR / "p3_afar_speed_bracket.csv"' not in src, (
        "the speed bracket was deleted from the paper; the ledger must not read it again")
    for gone in ("{SRC}/data/lb_counts.csv", "{SRC}/data/speed_bracket.csv",
                 "{SRC}/data/pairs_slim_lb_",
                 # freeze-wave Task 8: the legacy estimate cross-check is retired too — the
                 # legacy run directory is the PRE-caliber run and differs from the caliber
                 # golds by design, so an equality read of it must NOT survive either
                 "{SRC}/results/out/P3lb_",
                 # 2026-08-30: the no-effect simulation was rebuilt on the current specification
                 # at nsim=200 and frozen in data/paper_inputs, so the last-resort legacy fallback
                 # is gone as well. The ledger now names the legacy tree NOWHERE.
                 "{SRC}/results/out_null/NULL_"):
        assert gone not in src, f"a legacy data read survived: {gone}"
    assert "{SRC}" not in src, (
        "ledger_p3afar reached back into the legacy tree; since 2026-08-30 it is fully "
        "self-contained on data/frames, data/paper_inputs and analysis/expected")

    # the byte-identity half. Before the 2026-08-28 freeze the shipped frames were byte-identical
    # to the legacy p3_topicpair run directory; since the freeze they are byte-identical to the
    # CALIBER artifacts in data/cal2026-08-28/frames/ — except the speed bracket, which has no cal
    # builder and stays the pre-caliber legacy file (CALIBER-STALE, NOT_REPRODUCIBLE row 9).
    # 2026-09-23 (cal2026-10 promotion): the canon caliber is now October. pipeline/frames/cal2026-10/
    # promote.py copies data/cal2026-10/frames/ into data/frames/ (data/MANIFEST.sha256 regenerated), and
    # the Panel-3 files in data/cal2026-10/frames/ are the October A_far build's own output,
    # data/cal2026-10/frames_afar/ (pipeline/frames/cal2026-10/run_cal_afar.py; afar_run_report.json). So
    # the comparison moves from the 08-28 artifacts to both October copies, and it now also covers the
    # files the ledger reads since 2026-08-30 (the per-spec counts and the SPEC_MAIN = "pos" panels).
    # The speed bracket still has no cal builder: data/cal2026-10/frames/ carries the same legacy file.
    import hashlib
    cal_canon = REPO / "data" / "cal2026-10" / "frames"
    cal_build = REPO / "data" / "cal2026-10" / "frames_afar"
    for frozen_name in ("p3_afar_counts.csv", "p3_afar_econ.parquet",
                        "p3_afar_chemistry.parquet", "p3_afar_math_stats.parquet",
                        "p3_afar_counts_by_spec.csv", "p3_afar_pos_econ.parquet",
                        "p3_afar_pos_chemistry.parquet", "p3_afar_pos_math_stats.parquet"):
        a = hashlib.sha256((P["frames"] / frozen_name).read_bytes()).hexdigest()
        for cal in (cal_canon, cal_build):
            b = hashlib.sha256((cal / frozen_name).read_bytes()).hexdigest()
            assert a == b, (
                f"{frozen_name} is NOT byte-identical to the promoted caliber artifact in "
                f"{cal.relative_to(REPO)}; the paper's Panel-3 numbers would not be the approved caliber numbers")
    assert (P["frames"] / "p3_afar_speed_bracket.csv").read_bytes() == \
        (cal_canon / "p3_afar_speed_bracket.csv").read_bytes()
    legacy = P["legacy_v2_output"] / "p3_topicpair_2026-08-17" / "data"
    if not legacy.is_dir():
        pytest.skip("[needs legacy tree] the speed-bracket byte-identity half of this check")
    a = hashlib.sha256((P["frames"] / "p3_afar_speed_bracket.csv").read_bytes()).hexdigest()
    b = hashlib.sha256((legacy / "speed_bracket.csv").read_bytes()).hexdigest()
    assert a == b, (
        "p3_afar_speed_bracket.csv is NOT byte-identical to the pre-caliber legacy file it is "
        "documented (NOT_REPRODUCIBLE row 9) as still being — its register entry is now wrong")


# ---------------------------------------------------------------------------
# final review #3 — ledger_main's econ cross-check under the incumbent-star rule
# ---------------------------------------------------------------------------
# In M, J1a's econ build publishes the in-post report from BEFORE the incumbent-star drop and the
# accounting from AFTER it, so the October equalities (in-post kept == after-post-filter total, rows kept
# == pre_y_frame_rows) would stop the paper stage whenever a new M star was an in-post colleague. The
# cross-check now subtracts the report's own drop record; with October's reports (no drop keys) every
# delta is 0 / [] and the check is today's 822 / 113 / 6643 / 73073.

def _load_main_module():
    spec = importlib.util.spec_from_file_location("ledger_main", REPO / "analysis/paper/ledger_main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # cheap: computation is under build()/main()
    return mod


def test_econ_report_expectations_on_the_october_reports_are_todays_equalities():
    fe = REPO / "data" / "cal2026-10" / "frames_econ"
    inpost = json.loads((fe / "inpost_report_econ.json").read_text(encoding="utf-8"))
    b_econ = json.loads((fe / "build_report_econ920_2026-10.json").read_text(encoding="utf-8"))
    assert "incumbent_stars" not in b_econ["october"], "the October report carries no incumbent-star drop"
    got = _load_main_module().econ_report_expectations(inpost, b_econ)
    want = got["want"]
    assert want["econ_persons"] == 822
    assert want["econ_events"] == 113
    assert want["econ_relations"]["total"] == 6643
    assert want["econ_relations"] == {
        "total": 6643, **b_econ["october"]["accounting"]["relationships"]["after_post_filter_by_channel"]}
    assert got["rows"] == 73073


def _toy_econ_reports(*, rows_dropped=20, with_accounting_delta=True):
    """In-post report before the drop (10 persons, 12 relations, 100 rows, events E1-E3) and the econ
    build report after it: incumbent P_X (2 relations, 20 rows, events E1 and E2) removed; E2 had only
    P_X, so it has no relation left and is absent from the final per-event accounting."""
    inpost = {"persons_by_class": {"kept": 10}, "relations_by_class": {"kept": 12},
              "rows_by_class": {"kept": 100}, "events_left_with_zero_rows": [],
              "per_event": {"E1": {"kept": 50}, "E2": {"kept": 10}, "E3": {"kept": 40}}}
    rel = {"after_post_filter_by_channel": {"both": 1, "dept_only": 3, "network": 6},
           "after_post_filter_total": 10}
    rows = {"pre_y_frame_rows": 80}
    if with_accounting_delta:
        rel["relations_dropped_incumbent_is_star_r1"] = 2
        rows["minus_incumbent_is_star_r1"] = -20
    b_econ = {"october": {
        "accounting": {"relationships": rel, "rows": rows,
                       "per_event": {"E1": {"relations": 3, "p1_rows": 40},
                                     "E3": {"relations": 7, "p1_rows": 40}}},
        "incumbent_stars": {"cause": "incumbent_is_star_r1", "forms": 1, "persons": ["P_X"],
                            "events": ["E1", "E2"], "relations_dropped": 2,
                            "relationships_lines_dropped": 2, "rows_dropped": rows_dropped}}}
    return inpost, b_econ


def test_econ_report_expectations_subtract_the_incumbent_star_drop():
    inpost, b_econ = _toy_econ_reports()
    got = _load_main_module().econ_report_expectations(inpost, b_econ)
    assert got["want"] == {"econ_relations": {"total": 10, "both": 1, "dept_only": 3, "network": 6},
                           "econ_persons": 9, "econ_events": 2}
    assert got["rows"] == 80


@pytest.mark.parametrize("case", ["rows_dropped_19", "no_accounting_delta"])
def test_econ_report_expectations_refuse_an_inconsistent_drop_record(case):
    if case == "rows_dropped_19":
        inpost, b_econ = _toy_econ_reports(rows_dropped=19)
    else:
        inpost, b_econ = _toy_econ_reports(with_accounting_delta=False)
    with pytest.raises(AssertionError):
        _load_main_module().econ_report_expectations(inpost, b_econ)
