# -*- coding: utf-8 -*-
"""R1 V3-FINAL.d (unit W3-B0EXP): config/r1/final_b0_expected.json declares exactly the October-data
differences that finalb0's B0 gate (pipeline/aws/r1/final_stage.py gate2 --mode B0) allows.

Rule (plan V3-FINAL.d, ruling 1): a declaration names a difference a planned item causes, with its owner
item and the reason. A difference no item explains is a defect for its owner unit, never a declaration.

Each declared set is derived here from the code and the fixtures that cause it, so a declaration that
no item supports, or an item difference left undeclared, fails:
  N10 (W1-PTABLES)  the base_2026_10_11 table variants that run_all's staged 3light writes in place of the
                    default ones: the base-tree tables whose bytes differ from the legacy pins
                    (tests/fixtures/r1_paper/base_tree_2026-10-11/SOURCE.md), plus the draft generator's
                    NOTE_CHECKS.json (the base tree registers its own t-statistic note checks). The legacy
                    thesis_report sentinel's section B fails exactly those tables.
  N9 (W1-FIG34)     Figures 3 and 4: two new PDFs and their figure-data JSONs in output/paper; in the
                    scratch tree install.py exhibits replaces the vault-printed PDFs (which carry a
                    CreationDate) with generated ones (SAVE_KW sets none).
  F22 (W2-RUNALL)   the 3est seal, which staged mode writes into output/paper.
N12's p fix is behind p_full_precision, off in October, and N11's side keys exist only in M: neither
declares anything here.

The October output/paper snapshot (/data/ref/october/output_paper, uploaded 2026-10-13 from the Mac's
output/paper) is listed below by name; its count is checked against the upload record.

Small runner: reads repo text and fixtures only (analysis/run_all.sh is read as text, never run).
"""
from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for _p in (REPO / "pipeline" / "aws" / "r1", REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import final_stage as fs  # noqa: E402

EXPECTED = REPO / "config" / "r1" / "final_b0_expected.json"
PAPER_CFG = REPO / "config" / "r1" / "final_paper.json"
FIX = REPO / "tests" / "fixtures" / "r1_paper" / "base_tree_2026-10-11"
UPLOAD = REPO / "data" / "cal2026-10r1" / "aws" / "uploads" / "v3up_2026-10-13.json"
RUN_ALL = REPO / "analysis" / "run_all.sh"
CHECK_PAPER = REPO / "tools" / "check_paper.py"
DRAFT_GEN = REPO / "analysis" / "paper" / "draft_2026_09_13_tables.py"
N9_GENS = (REPO / "analysis" / "paper" / "fig_compare_years.py",
           REPO / "analysis" / "paper" / "fig_comparison_pools.py")
FIG34_STYLE = REPO / "analysis" / "paper" / "_fig34_style.py"
LEDGER_P3AFAR = REPO / "analysis" / "paper" / "ledger_p3afar.py"

N9, N10, F22 = "N9 (W1-FIG34)", "N10 (W1-PTABLES)", "F22 (W2-RUNALL)"
FIG567 = "FIG567 (Figures 5-7, base tree)"
DECL = "current tree: declarations edits (2026-10-16)"
OWNERS = {N9, N10, F22, FIG567, DECL}
#: the October -> current red runs: the AI-use line now names Codex, and the Replication paragraph gives the
#: repository URL (the current tree's only text edits against October; red_diff's own text step, measured)
DECL_RED_RUNS = {"Anthropic; Codex, OpenAI).", "is",
                 "available at \\url{https://github.com/jjjia2-svg/star-arrivals-replication}."}
FIG567_NAMES = ("fig_p1", "fig_p2", "fig_p3_afar")

#: the 42 files of the October output/paper snapshot (r1/ref/october/output_paper/, key repo_output of
#: data/cal2026-10r1/aws/uploads/v3up_2026-10-13.json), relative to output/paper
OCTOBER_OUTPUT_PAPER = (
    "LEDGER_DIFF_main_funnel.md", "LEDGER_DIFF_p1p2_p3_rob.md", "SYNC_PLAN_2026-10.md",
    "SYNC_PLAN_2026-10_reanchor.json", "data_numbers_carried.json", "data_numbers_funnel.json",
    "data_numbers_main.json", "data_numbers_p1p2.json", "data_numbers_p3afar.json",
    "data_numbers_robustness.json", "data_numbers_star_origins.json", "draft_2026_09_13/NOTE_CHECKS.json",
    "draft_2026_09_13/tab_main_results.tex", "draft_2026_09_13/tab_panels_overview.tex",
    "draft_2026_09_13/tab_robustness.tex", "fig_dose_distribution.pdf", "fig_exposure_population.pdf",
    "fig_hops.pdf", "fig_hops.png", "fig_p1.pdf", "fig_p2.pdf", "fig_p3_afar.pdf", "fig_star_origins.pdf",
    "fig_star_origins.png", "gaps_switchers.json", "gaps_switchers_p1p2.json", "gaps_toy.json",
    "gaps_zenou.json", "gaps_zero_dose.json", "star_origins_2026-10.csv",
    "star_origins_crosscheck_2026-10.json", "tab_disciplines.tex", "tab_p1_full.tex", "tab_p1_main.tex",
    "tab_p2_full.tex", "tab_p2_main.tex", "tab_p3_afar.tex", "tab_p3_afar_full.tex", "tab_rob_p1.tex",
    "tab_rob_p2.tex", "tab_rob_p3.tex", "tab_robustness.tex")

#: differences finalb0 will show that NO planned item causes (static reading of the code at the r1-code
#: tip this unit was cut from; finalb0-01 measures them). Each is a defect for its owner, so none may
#: ever be declared: wall-clock PDF CreationDate in October generators, absolute Mac paths in provenance
#: strings, and October one-off tool outputs no run_all stage writes. Their owner, the FINALJOB
#: comparison, now handles each (review R7 #13-#15): final_stage.same_file masks the PDF render date,
#: rooted_equal maps the repo root in B0_ROOTED, and the one-off files are the pinned, one-direction
#: 'output_paper_reference_only' list of final_b0_expected.json (outside the output_paper section).
NEVER_DECLARED_OUTPUT = (
    "fig_dose_distribution.pdf", "fig_exposure_population.pdf", "fig_hops.pdf",
    "data_numbers_main.json", "gaps_zenou.json", "gaps_zero_dose.json",
    "LEDGER_DIFF_main_funnel.md", "LEDGER_DIFF_p1p2_p3_rob.md", "SYNC_PLAN_2026-10.md",
    "SYNC_PLAN_2026-10_reanchor.json", "star_origins_crosscheck_2026-10.json")
NEVER_DECLARED_SCRATCH = (
    "figures/fig_dose_distribution.pdf", "figures/fig_exposure_population.pdf", "figures/fig_hops.pdf",
    "data_numbers_2026-10-23.json", "data_numbers_2026-10-23_gaps_zenou.json",
    "data_numbers_2026-10-23_gaps_zero_dose.json")


# ---- helpers ---------------------------------------------------------------------------------------
def _exp() -> dict:
    return fs.load_expected_b0(EXPECTED)


def _keys(sec: str, owner: str | None = None) -> set:
    key = fs.B0_SECTIONS[sec]
    return {r[key] for r in _exp()[sec] if owner is None or r["owner"] == owner}


def _literal(path: pathlib.Path, name: str):
    """The value of a module-level `NAME = <literal>` assignment, read without importing the module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{path.name}: no module-level {name} literal")


def _legacy_pins() -> dict:
    out = {}
    for line in (FIX / "SOURCE.md").read_text(encoding="utf-8").splitlines():
        m = re.fullmatch(r"legacy-sha256 ([0-9a-f]{64})  (tab_\w+\.tex)", line.strip())
        if m:
            out[m.group(2)] = m.group(1)
    assert len(out) == 13, sorted(out)
    return out


def _n10_tables() -> set:
    """Base-tree tables whose bytes differ from today's legacy thesis_report tables (= October output)."""
    pins = _legacy_pins()
    return {n for n, sha in pins.items()
            if hashlib.sha256((FIX / "tables" / n).read_bytes()).hexdigest() != sha}


def _output_path(table: str) -> str:
    """Where run_all's staged 3light writes a table (and the label check_paper section B gives it)."""
    draft_dir = _literal(CHECK_PAPER, "DRAFT_TABLES_DIR")
    if table in _literal(CHECK_PAPER, "B_DRAFT_TABLES"):
        return f"{draft_dir}/{table}"
    assert table in _literal(CHECK_PAPER, "B_GEN_TABLES"), table
    return table


def _n9_names() -> list:
    return [_literal(p, "NAME") for p in N9_GENS]


# ---- the file as a whole ---------------------------------------------------------------------------
def test_every_declaration_names_a_planned_item_and_a_reason():
    exp = _exp()
    rows = [(sec, r) for sec in fs.B0_SECTIONS for r in exp[sec]]
    assert rows, "final_b0_expected.json declares nothing, but N9/N10/F22 change October's output/paper"
    for sec, r in rows:
        assert r["owner"] in OWNERS, (sec, r)
        assert len(r["reason"]) > 40 and len(r["what"]) > 10, (sec, r)
    for sec in fs.B0_SECTIONS:
        names = [r[fs.B0_SECTIONS[sec]] for r in exp[sec]]
        assert len(names) == len(set(names)), (sec, names)
        assert names == sorted(names), (sec, "keep each section sorted by its key")


def test_october_snapshot_list_matches_the_upload_record():
    if not UPLOAD.is_file():   # public copy: the R1 run records are not shipped
        pytest.skip("needs the R1 upload record under data/cal2026-10r1/ (not shipped)")
    rec = json.loads(UPLOAD.read_text(encoding="utf-8"))
    row = [r for r in rec if r.get("key") == "repo_output"]
    assert len(row) == 1 and row[0]["prefix"] == "r1/ref/october/output_paper/", row
    assert row[0]["files"] == len(OCTOBER_OUTPUT_PAPER) == len(set(OCTOBER_OUTPUT_PAPER)) == 42


# ---- per item --------------------------------------------------------------------------------------
def test_n10_declares_the_base_variant_tables_and_their_note_checks():
    if not FIX.is_dir():   # public copy: the manuscript fixtures are not shipped
        pytest.skip("needs the manuscript fixtures in tests/fixtures/r1_paper/ (not shipped)")
    tables = _n10_tables()
    assert tables == {"tab_main_results.tex", "tab_panels_overview.tex", "tab_robustness.tex", "tab_rob_p1.tex"}
    draft_dir = _literal(CHECK_PAPER, "DRAFT_TABLES_DIR")
    want = {_output_path(t) for t in tables} | {f"{draft_dir}/NOTE_CHECKS.json"}
    assert _keys("output_paper", N10) == want
    assert want <= set(OCTOBER_OUTPUT_PAPER)            # changed files, not new ones
    # the legacy thesis_report sentinel: section B compares output/paper with thesis_report/tables
    assert _keys("thesis_report_sentinel_fail") == _keys("thesis_report_sentinel_fail", N10) \
        == {_output_path(t) for t in tables}
    # run_all's staged 3light writes the base variants (the default ones are swapped out)
    txt = RUN_ALL.read_text(encoding="utf-8")
    assert re.search(r"^staged paper_tables_rob_base .*tables_robustness\.py --tree base_2026_10_11$", txt, re.M)
    assert re.search(r"^staged paper_draft_tables_base .*draft_2026_09_13_tables\.py --tree base_2026_10_11 ",
                     txt, re.M)
    swapped = re.search(r'^SWAPPED="([^"]*)"', txt, re.M).group(1).split()
    assert {"paper_tables_rob", "paper_draft_tables"} <= set(swapped)


def test_staged_draft_tables_read_this_runs_ledgers():
    """review R7 #7: staged 3light (final and finalb0) reads this run's $O/paper ledgers, never the dated
    October thesis ledgers; the no-flag run keeps its default (legacy thesis_report). On October data the
    values are equal (finalb0's vault sentinel section A), so the declared base-variant bytes stay."""
    txt = RUN_ALL.read_text(encoding="utf-8")
    staged = re.findall(r"^staged paper_draft_tables_base .*$", txt, re.M)
    assert len(staged) == 1 and re.search(
        r'draft_2026_09_13_tables\.py --tree base_2026_10_11 --paper-dir "\$O/paper" --out-dir '
        r'"\$O/paper/draft_2026_09_13"$', staged[0]), staged
    noflag = re.findall(r"^run paper_draft_tables .*$", txt, re.M)
    assert len(noflag) == 1 and "--paper-dir" not in noflag[0] and "--ledger-dir" not in noflag[0], noflag


def test_n10_note_checks_differ_by_tree():
    """NOTE_CHECKS.json changes because robustness_table registers tree-specific note checks."""
    tree = ast.parse(DRAFT_GEN.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "robustness_table")

    def calls(nodes):
        return [c for n in nodes for c in ast.walk(n)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "note_check"]
    branches = [n for n in ast.walk(fn) if isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
                and isinstance(n.test.left, ast.Name) and n.test.left.id == "tree"
                and isinstance(n.test.ops[0], ast.Eq)]
    assert any(calls(b.body) and calls(b.orelse) and len(calls(b.body)) != len(calls(b.orelse))
               for b in branches)


def test_n9_declares_two_new_figures_and_the_scratch_figures_they_replace():
    names = _n9_names()
    assert names == ["fig_compare_years", "fig_comparison_pools"]
    want = {f"{n}.{ext}" for n in names for ext in ("pdf", "json")}
    assert _keys("output_paper", N9) == want
    assert not want & set(OCTOBER_OUTPUT_PAPER)           # new files
    txt = RUN_ALL.read_text(encoding="utf-8")
    for p in N9_GENS:
        assert re.search(rf"^staged paper_fig_\w+ +\"\$PY\" \$PP/{p.name}", txt, re.M), p.name
    # install.py exhibits copies them into the scratch tree; the generated PDFs carry no CreationDate,
    # the base tree's vault-printed PDFs do (2026-10-03), so the bytes differ by construction
    assert set(names) <= set(json.loads(PAPER_CFG.read_text(encoding="utf-8"))["figures"])
    assert _literal(FIG34_STYLE, "SAVE_KW")["metadata"] == {"CreationDate": None}
    assert _keys("scratch_edits", N9) == {f"figures/{n}.pdf" for n in names}


def test_fig567_declares_figures_5_to_7_in_the_base_tree_form():
    """FIG567: staged 3light draws Figures 5-7 in the base tree's 2026-10-03 form (labels, size, TeX Gyre
    Pagella, no CreationDate), so output/paper's three PDFs differ from the October snapshot's, and
    install.py exhibits replaces the tree's vault-printed PDFs (Palatino, Matplotlib 3.10.8)."""
    txt = RUN_ALL.read_text(encoding="utf-8")
    for gen in ("fig_p1.py", "fig_p2.py", "ledger_p3afar.py"):
        assert re.search(rf"^staged paper_\w+_base +\"\$PY\" \$PP/{gen} --tree base_2026_10_11", txt, re.M), gen
    swapped = re.search(r'^SWAPPED="([^"]*)"', txt, re.M).group(1).split()
    assert {"paper_ledger_p3afar", "paper_fig_p1", "paper_fig_p2"} <= set(swapped)
    assert set(FIG567_NAMES) <= set(json.loads(PAPER_CFG.read_text(encoding="utf-8"))["figures"])
    assert _keys("output_paper", FIG567) == {f"{n}.pdf" for n in FIG567_NAMES}
    assert {f"{n}.pdf" for n in FIG567_NAMES} <= set(OCTOBER_OUTPUT_PAPER)      # changed, not new
    assert _keys("scratch_edits", FIG567) == {f"figures/{n}.pdf" for n in FIG567_NAMES}
    assert _keys("scratch_edits") == _keys("scratch_edits", N9) | _keys("scratch_edits", FIG567)


def test_f22_declares_the_3est_seal():
    m = re.search(r'^SEAL="\$O/paper/([^"/]+)"$', RUN_ALL.read_text(encoding="utf-8"), re.M)
    assert m, "run_all's seal path"
    assert _keys("output_paper", F22) == {m.group(1)} == {"3est.seal.json"}
    assert m.group(1) not in OCTOBER_OUTPUT_PAPER


def test_output_paper_is_exactly_the_items_declared():
    assert _keys("output_paper") == _keys("output_paper", N9) | _keys("output_paper", N10) | \
        _keys("output_paper", F22) | _keys("output_paper", FIG567)


def test_switches_off_in_october_declare_nothing():
    """N12's p fix is behind p_full_precision (always off in October); the vault sentinel then has no
    item-caused FAIL and the October -> scratch red diff no item-caused run."""
    src = LEDGER_P3AFAR.read_text(encoding="utf-8")
    assert 'canon.switch("p_full_precision"' in src
    assert _keys("vault_sentinel_fail") == set()
    assert _keys("red_runs") == _keys("red_runs", DECL) == DECL_RED_RUNS
    assert not any("N12" in r["owner"] or "N11" in r["owner"] for sec in fs.B0_SECTIONS for r in _exp()[sec])


def test_non_item_differences_are_never_declared():
    assert not _keys("output_paper") & set(NEVER_DECLARED_OUTPUT)
    assert not _keys("scratch_edits") & set(NEVER_DECLARED_SCRATCH)
    assert set(NEVER_DECLARED_OUTPUT) <= set(OCTOBER_OUTPUT_PAPER)


# ---- review R7 #15: the October snapshot files no staged run_all stage writes ---------------------------
ONE_OFF = ("LEDGER_DIFF_main_funnel.md", "LEDGER_DIFF_p1p2_p3_rob.md", "SYNC_PLAN_2026-10.md",
           "SYNC_PLAN_2026-10_reanchor.json", "star_origins_crosscheck_2026-10.json")
PAPER_LAYER_MANIFEST = REPO / "data" / "cal2026-10" / "paper_layer" / "MANIFEST.sha256"


def _ref_only() -> list:
    return _exp()["output_paper_reference_only"]


def test_reference_only_names_are_the_snapshot_files_no_staged_stage_writes():
    names = [r["path"] for r in _ref_only()]
    assert names == sorted(names) and len(names) == len(set(names)) == 6
    assert set(names) == set(ONE_OFF) | {"fig_hops.png"} and set(names) <= set(OCTOBER_OUTPUT_PAPER)
    # fig_hops.png: run_all calls fig_hops.py without --png, and fig_hops.py writes the PNG only with it
    run_all = RUN_ALL.read_text(encoding="utf-8")
    calls = re.findall(r"^\s*(?:run|staged) \S+ .*fig_hops\.py(.*)$", run_all, re.M)
    assert calls and not any("--png" in c for c in calls), calls
    assert "--png" in (REPO / "analysis" / "paper" / "fig_hops.py").read_text(encoding="utf-8")
    # the crosscheck JSON comes from a check tool run_all never calls
    assert "star_origins_crosscheck" not in run_all
    assert "star_origins_crosscheck_2026-10.json" in \
        (REPO / "tools" / "star_origins_crosscheck_2026-10.py").read_text(encoding="utf-8")
    # no generator under analysis/ (all run_all stages run from there) names the four 09-23 workflow files
    srcs = [p for p in (REPO / "analysis").rglob("*") if p.suffix in (".py", ".R", ".sh") and p.is_file()]
    for name in ONE_OFF[:4]:
        assert not [p for p in srcs if name in p.read_text(encoding="utf-8", errors="replace")], name


def test_reference_only_is_apart_from_the_declarations():
    names = {r["path"] for r in _ref_only()}
    assert "output_paper_reference_only" not in fs.B0_SECTIONS
    assert not names & _keys("output_paper") and not set(NEVER_DECLARED_OUTPUT) & _keys("output_paper")
    for r in _ref_only():
        assert set(r) == {"path", "sha256", "what", "owner", "reason"}, r
        assert re.fullmatch(r"[0-9a-f]{64}", r["sha256"]) and len(r["reason"]) > 40, r
        assert r["owner"] == "F1 (October output/paper snapshot)", r


def test_reference_only_pins_equal_the_archived_copies():
    pins = {}
    for line in PAPER_LAYER_MANIFEST.read_text(encoding="utf-8").splitlines():
        m = re.fullmatch(r"([0-9a-f]{64})\s+\*?(.+)", line.strip())
        if m:
            pins[pathlib.PurePosixPath(m.group(2)).name] = m.group(1)
    archived = [r for r in _ref_only() if r["path"] in pins]
    assert {r["path"] for r in archived} == {"LEDGER_DIFF_main_funnel.md", "LEDGER_DIFF_p1p2_p3_rob.md",
                                             "SYNC_PLAN_2026-10.md"}
    for r in archived:
        assert r["sha256"] == pins[r["path"]], r["path"]


# ---- through the gate ------------------------------------------------------------------------------
def _chk(section, name, ok=False, file=""):
    return {"section": section, "name": name, "ok": ok, "retired": False, "unrep": False, "file": file,
            "detail": ""}


@pytest.fixture
def b0_measured():
    """finalb0 inputs showing exactly the declared differences (October data, nothing else moved)."""
    return {
        "pre": [_chk("A", "[main] econ_events", ok=True)], "post": [_chk("A", "[main] econ_events", ok=True)],
        "number_diff": [], "changed_tables": [], "renamed": {},
        "edits": [{"pin": "p1 econ n 113", "file": "sections/sec4_p1.tex", "status": "ALREADY_NEW"}],
        "bor_equal": True, "compile": {t: {"ok": True} for t in fs.COMPILE_TARGETS},
        "draft_hits": {"october": {}, "new": {}}, "words": {"october": 12038, "new": 12038, "reference": 12038},
        "words_limit": 12000, "reports_missing": [], "deliverables_missing": [], "pack_ok": True,
        "main_clean_invariant": True, "numbers_rc": 0,
        "red": {"build_ok": True, "verify_ok": True, "reference_equal": True, "red_runs": sorted(_keys("red_runs"))},
        "output_paper_diff": sorted(_keys("output_paper")),
        "thesis_default": [_chk("B", n) for n in sorted(_keys("thesis_report_sentinel_fail"))],
        "thesis_root": [_chk("B", n) for n in sorted(_keys("thesis_report_sentinel_fail"))],
        "scratch_diff": sorted(_keys("scratch_edits")),
        # NOTE_CHECKS.json's reason in final_b0_expected.json: all claims hold on October ledgers (R7 #16)
        "note_checks": [{"table": "tab:robustness", "claim": "a note claim", "holds": True, "detail": "October"}],
    }


def test_the_declared_differences_pass_the_b0_gate(b0_measured):
    verdict, codes, det = fs.gate2(b0_measured, "B0", _exp())
    assert (verdict, codes) == ("B0_PASS", []), det


@pytest.mark.parametrize("change,code", [
    ({"output_paper_diff": "add:fig_hops.pdf"}, "B0_OUTPUT_DIFF"),           # a date-stamped October PDF
    ({"output_paper_diff": "add:gaps_zenou.json"}, "B0_OUTPUT_DIFF"),        # an absolute provenance path
    ({"output_paper_diff": "drop:3est.seal.json"}, "B0_OUTPUT_DIFF"),        # declared but absent
    ({"scratch_diff": "add:figures/fig_hops.pdf"}, "B0_SCRATCH_DIFF"),
    ({"scratch_diff": "drop:figures/fig_compare_years.pdf"}, "B0_SCRATCH_DIFF"),
])
def test_a_non_item_or_missing_difference_fails_the_b0_gate(b0_measured, change, code):
    (field, op), = change.items()
    act, _, name = op.partition(":")
    vals = set(b0_measured[field])
    vals = vals | {name} if act == "add" else vals - {name}
    verdict, codes, _ = fs.gate2(dict(b0_measured, **{field: sorted(vals)}), "B0", _exp())
    assert verdict == "B0_FAIL" and code in codes, codes


# ---- finalb0-03: the October PDF compiled on EC2 against the author's reference PDF --------------------
#: what red_diff's explain_reference_diff found there (pages 1-based, printed page numbers as labels): the
#: author's TinyTeX build ended one pass early ("Label(s) may have changed"), so its contents numbers from
#: Section 2.4 on are one low, and it set typewriter text in bitmap fonts (no cm-super)
REFERENCE_EXPLAINED = {
    "explained": True, "contents_page": 4,
    "stale_contents_entries": [
        {"entry": e, "reference": r, "bw": b, "heading_page": b} for e, r, b in (
            ("Limitations of the Data", "10", "11"), ("Empirical Strategy", "11", "12"),
            ("Comparison, Models, and Estimation", "11", "12"),
            ("Assumptions, Concerns, and What the Estimates Do Not Identify", "16", "17"),
            ("How the Coefficients Are Computed: The 2016 Arrivals", "20", "21"))],
    "bitmap_typewriter_pages": [11, 40, 42], "bitmap_typewriter_glyphs": 625, "unexplained": []}


def test_the_reference_pdf_difference_is_explained_not_declared(b0_measured):
    """It is a check of the two PDFs, the same in M and B0 (both compile the October tree against the same
    reference), never a B0 declaration: final_b0_expected.json has no section for it, and any difference the
    explanation does not cover still fails the gate (REFERENCE_PDF_DIFF)."""
    assert [k for k in _exp() if "reference" in k] == ["output_paper_reference_only"]
    rv = {"checks": {"bw_same_pages_words_positions_as_reference": False,
                     "bw_same_as_reference_except_explained_differences": True},
          "bw_vs_reference_explained": REFERENCE_EXPLAINED}
    red = dict(b0_measured["red"], reference_equal=fs.reference_equal(rv), reference_explained=REFERENCE_EXPLAINED)
    verdict, codes, det = fs.gate2(dict(b0_measured, red=red), "B0", _exp())
    assert (verdict, codes) == ("B0_PASS", []), det
    assert det["reference_explained"] == REFERENCE_EXPLAINED
    rv["bw_vs_reference_explained"] = dict(REFERENCE_EXPLAINED, explained=False,
                                           unexplained=["page 20: the words differ"])
    rv["checks"]["bw_same_as_reference_except_explained_differences"] = False
    red = dict(red, reference_equal=fs.reference_equal(rv))
    verdict, codes, _ = fs.gate2(dict(b0_measured, red=red), "B0", _exp())
    assert verdict == "B0_FAIL" and "REFERENCE_PDF_DIFF" in codes
