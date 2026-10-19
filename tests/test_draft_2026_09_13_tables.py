# Draft 2026-09-13 tables (analysis/paper/draft_2026_09_13_tables.py): Table 1 panels overview,
# Table 2 merged main results, Table 3 robustness with a pass column.
#
# The generator is run into a temp dir. Every row of every table is rebuilt HERE, independently,
# from the four dated thesis ledgers, and compared cell by cell with the generated file. A second
# check collects every number printed anywhere in each file (cells, labels, notes) and requires the
# multiset to equal the numbers this test expects, so a stray or missing number fails as well.
#
# R1 N10 (2026-10-16): every test runs for both trees of the generator's --tree switch. thesis_report
# (the default) reads the dated ledgers in legacy thesis_report/ as before; base_2026_10_11 (the
# author's 2026-10-11 base tree, with the hand-edited labels and notes) reads the byte-equal fixture
# copies in tests/fixtures/r1_paper/base_tree_2026-10-11/ledgers (not shipped) and is compared with the fixture
# tables of that tree.
import collections
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from analysis.lib.paths import load_paths

P = load_paths()
TR = P["legacy_thesis"] / "thesis_report"
SCRIPT = REPO / "analysis/paper/draft_2026_09_13_tables.py"
# The author's copy of the draft's tables directory (not shipped). Author-only: point
# $SAR_DRAFT_TABLES at it to run the last test; without it that test skips.
DRAFT_TABLES = pathlib.Path(os.environ.get("SAR_DRAFT_TABLES", "") or "/nonexistent-draft-tables")
NAMES = ("tab_main_results.tex", "tab_robustness.tex", "tab_panels_overview.tex")
BASE = "base_2026_10_11"
TREES = ("thesis_report", BASE)
BASE_FIX = REPO / "tests/fixtures/r1_paper/base_tree_2026-10-11"   # not shipped
# row labels the author changed in the base tree (2026-10-03/04, carried into the generator by N10)
BASE_LABELS = {
    "Raw rate before arrival (\\% per year)": "Pre-arrival rate (\\% per year)",
    "Joint test ($p$), pair clusters": "Joint test ($p$), post-arrival coefficients",
    "Incumbents on the roster": "Roster incumbents",
    "Incumbents in the star's network": "Network incumbents",
    "Not-yet-exposed comparison pool": "Comparisons before any exposure (arrival year to year 3)",
}
F = ("econ", "chemistry", "math_stats")
MK = {"econ": "econ", "chemistry": "chem", "math_stats": "math"}
ABBR = {"econ": "Econ.", "chemistry": "Chem.", "math_stats": "Math."}
THRESH = 0.05   # plan: a pre-arrival test passes when p > 0.05; shuffled years pass when p < 0.05

# The generator reads the four dated manuscript ledgers from the author's private manuscript tree
# (config key legacy_thesis). Without that tree every test in this file skips.
pytestmark = pytest.mark.skipif(
    not all((TR / f).is_file() for f in ("data_numbers_2026-08-30_p1p2.json",
                                         "data_numbers_2026-08-28_p3afar.json",
                                         "data_numbers_2026-09-13_robustness.json",
                                         "data_numbers_2026-08-28.json")),
    reason="author-only: the manuscript ledgers (legacy_thesis/thesis_report) are not shipped")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _ledger_dir(tree):
    # thesis_report reads legacy thesis_report/ when the machine has it; otherwise (the small AWS
    # runner, config/r1/input_inventory.tsv) the fixture copies, byte-equal to it (cmp, SOURCE.md)
    if tree == BASE or not TR.is_dir():
        return BASE_FIX / "ledgers"
    return TR


def _ledgers(tree="thesis_report"):
    # the dated thesis ledgers the generator reads (cal2026-10: data_numbers_2026-10-23*.json since
    # 2026-09-23; the file names are the generator's, the rebuild of every row below is independent)
    import importlib.util
    spec = importlib.util.spec_from_file_location("draft_tables_gen", SCRIPT)
    g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
    d = _ledger_dir(tree)
    L = json.load(open(d / g.F_PP))
    T = json.load(open(d / g.F_P3))
    RB = json.load(open(d / g.F_R))
    M = json.load(open(d / g.F_M))
    return L, T, RB, M


def _lab(tree, label):
    return BASE_LABELS.get(label, label) if tree == BASE else label


def _gen(out, tree="thesis_report"):
    args = ["--tree", tree] if tree == BASE else []
    if _ledger_dir(tree) != TR:
        args += ["--ledger-dir", str(_ledger_dir(tree))]
    r = subprocess.run([sys.executable, str(SCRIPT), "--out-dir", str(out), *args],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    return {n: (out / n).read_text() for n in NAMES}


@pytest.fixture(scope="module", params=TREES)
def tree(request):
    return request.param


@pytest.fixture(scope="module")
def tables(tmp_path_factory, tree):
    return _gen(tmp_path_factory.mktemp("draft_tables_" + tree), tree)


def f3(x):
    s = f"{x:.3f}"
    return s.lstrip("-") if float(s) == 0 else s


def p3(p):
    if p is None:          # a test not computed in the cal2026-10 rebuild (ledger null); Table 3 prints n.a.
        return "n.a."
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def n(x):
    return f"{x:,}"


def es(e, s):
    return f"{f3(e)} ({f3(s)})"


def ci(lo_hi):
    return f"[{f3(lo_hi[0])}, {f3(lo_hi[1])}]"


def unrev(s):
    while True:
        i = s.find("\\REV{")
        if i < 0:
            return s
        j, depth = i + 5, 1
        while depth:
            depth += {"{": 1, "}": -1}.get(s[j], 0)
            j += 1
        s = s[:i] + s[i + 5:j - 1] + s[j:]


def norm(s):
    s = re.sub(r"^\s*\\multicolumn\{\d\}\{(?:[^{}]|\{\})*\}\{(.*)\}\s*$", r"\1", s)   # a spanned label cell (spec may hold @{})
    return unrev(s).replace("$-$", "-").replace("$<$", "<").replace("{,}", ",").strip()


def body(tex):
    """The file without comment lines and without trailing % src comments."""
    out = []
    for line in tex.splitlines():
        if line.lstrip().startswith("%"):
            continue
        out.append(re.split(r"(?<!\\)%", line, maxsplit=1)[0])
    return "\n".join(out)


def data_rows(tex):
    rows = []
    for line in body(tex).splitlines():
        s = line.rstrip()
        if "&" not in s or not s.endswith("\\\\"):
            continue
        cells = [norm(c) for c in re.split(r"(?<!\\)&", s[:-2])]
        if cells[0] == "":          # header rows start with an empty cell
            continue
        rows.append((cells[0], cells[1:]))
    return rows


NONDATA = [r"\\begin\{tabular\}\{[^\n]*", r"\\setlength\{\\tabcolsep\}\{[^}]*\}", r"\{0\.95\\textwidth\}",
           r"\\addlinespace\[[^\]]*\]", r"\\multicolumn\{\d\}", r"\\cmidrule\(l\)\{\d-\d\}",
           r"\\label\{[^}]*\}", r"\\(?:eq)?ref\{[^}]*\}", r"Panels? \d(?: and \d)?", r"\$\\ell=0\$",
           r"\$(?:p=)?\(k\+1\)/\(B\+1\)\$"]   # the permutation-p formula is notation, not a ledger number
NUMRX = re.compile(r"\d[\d,]*(?:\.\d+)?")


def strip_nondata(s):
    for rx in NONDATA:
        s = re.sub(rx, " ", s)
    return s


def numbers(s):
    return collections.Counter(NUMRX.findall(strip_nondata(s).replace("{,}", ",")))


def expected_numbers(rows, extra=()):
    c = collections.Counter()
    for lab, cells in rows:
        c += numbers(lab)
        for x in cells:
            c += numbers(x)
    c += collections.Counter(extra)
    return c


# ---------------------------------------------------------------------------
# expected rows, rebuilt from the ledgers
# ---------------------------------------------------------------------------
def expected_main(tree="thesis_report"):
    L, T, _, _ = _ledgers(tree)
    cap = L["year_cap"]
    a = {f: L[f"p1_{f}"] for f in F}
    b = {f: L[f"p2_{f}"] for f in F}
    c = {f: T[f] for f in F}
    return [(_lab(tree, lab), cells) for lab, cells in [
        ("Average change per unit of dose (log points)", [f3(a[f]["ate_log"]) for f in F]),
        ("\\quad s.e., incumbent clusters", [f"({f3(a[f]['se_person'])})" for f in F]),
        ("\\quad s.e., event clusters", [f"({f3(a[f]['se_event'])})" for f in F]),
        ("95\\% CI, incumbent clusters", [ci(a[f]["ci95_person"]) for f in F]),
        ("Joint test ($p$), post-arrival coefficients", [p3(a[f]["p_joint_effects_person"]) for f in F]),
        ("\\quad event clusters", [p3(a[f]["p_joint_effects_event"]) for f in F]),
        ("Joint test ($p$), placebo coefficients", [p3(a[f]["p_joint_placebo_person"]) for f in F]),
        ("\\quad event clusters", [p3(a[f]["p_joint_placebo_event"]) for f in F]),
        ("Incumbent--event relations", [n(a[f]["relations"]) for f in F]),
        ("Switching relations at $\\ell=0$", [n(a[f]["switchers_ell0"]) for f in F]),
        ("Events", [str(a[f]["events"]) for f in F]),
        ("Incumbent--event--years", [n(a[f]["obs"]) for f in F]),
        ("Average post-arrival change (pp per year)", [f3(b[f]["ate_pp"]) for f in F]),
        ("\\quad s.e., incumbent clusters", [f"({f3(b[f]['se_person_pp'])})" for f in F]),
        ("\\quad s.e., event clusters", [f"({f3(b[f]['se_event_pp'])})" for f in F]),
        ("95\\% CI, incumbent clusters", [ci(b[f]["ci95_person_pp"]) for f in F]),
        ("Joint test ($p$), post-arrival coefficients", [p3(b[f]["p_joint_effects_person"]) for f in F]),
        ("\\quad event clusters", [p3(b[f]["p_joint_effects_event"]) for f in F]),
        ("Raw rate before arrival (\\% per year)", [f3(b[f]["rate_pre_pp"]) for f in F]),
        (f"Raw rate after arrival, to {cap} (\\% per year)", [f3(b[f]["rate_post_obs_pp"]) for f in F]),
        ("Incumbent--star relations", [n(b[f]["relations"]) for f in F]),
        ("First ties", [n(b[f]["first_ties"]) for f in F]),
        ("Switching relations at $\\ell=0$", [n(b[f]["switchers_ell0"]) for f in F]),
        ("Events", [str(b[f]["events"]) for f in F]),
        ("Relation--years", [n(b[f]["rows"]) for f in F]),
        ("Average post-arrival change (pp per year)", [f3(c[f]["ate_pp"]) for f in F]),
        ("\\quad s.e., pair clusters", [f"({f3(c[f]['se_pair_pp'])})" for f in F]),
        ("\\quad s.e., event clusters", [f"({f3(c[f]['se_event_pp'])})" for f in F]),
        ("95\\% CI, pair clusters", [ci(c[f]["ci95_pair_pp"]) for f in F]),
        ("Joint test ($p$), pair clusters", [p3(c[f]["p_joint_effects_pair"]) for f in F]),
        ("\\quad event clusters", [p3(c[f]["p_joint_effects_event"]) for f in F]),
        ("Raw rate before arrival (\\% per year)", [f3(c[f]["rate_pre_pp"]) for f in F]),
        (f"Raw rate after arrival, to {T['year_cap']} (\\% per year)", [f3(c[f]["rate_post_obs_pp"]) for f in F]),
        ("Pairs", [n(c[f]["pairs"]) for f in F]),
        ("First ties", [n(c[f]["first_ties"]) for f in F]),
        ("Events with pairs", [str(c[f]["events_with_pairs"]) for f in F]),
        ("Pair--event--years", [n(c[f]["rows"]) for f in F]),
    ]]


def _passes(ps, rule):
    ok = [f for f in F if ps[f] is not None and rule(ps[f])]
    return "All" if len(ok) == 3 else "None" if not ok else ", ".join(ABBR[f] for f in ok)


def expected_robustness(tree="thesis_report"):
    L, T, RB, _ = _ledgers(tree)
    V, PT, perm = RB["p1_variants"], RB["p1_pretrend_by_channel"], L["perm_pvalues"]
    pre = lambda p: p > THRESH       # noqa: E731
    shuf = lambda p: p < THRESH      # noqa: E731

    def test(label, ps, rule):
        return (label, [p3(ps[f]) for f in F] + [_passes(ps, rule)])

    def est(label, pairs):
        return (label, [es(e, s) for e, s in pairs] + [""])

    rows = [
        est("Main specification", [(L[f"p1_{f}"]["ate_log"], L[f"p1_{f}"]["se_person"]) for f in F]),
        test("\\quad placebo test", {f: L[f"p1_{f}"]["p_joint_placebo_person"] for f in F}, pre),
        test("\\quad date-shift test", {f: RB["p1_date_shift"][f]["p_joint_shifted"] for f in F}, pre),
        test("\\quad shuffled arrival years", {f: perm[f"p1_{f}"]["p_perm_abs_ate"] for f in F}, shuf),
    ]
    for route, ch, lab in (("roster", "dept", "Incumbents on the roster"), ("network", "network", "Incumbents in the star's network")):
        rows += [est(lab, [(L[f"p1_{f}"]["by_route"][route]["ate_log"], L[f"p1_{f}"]["by_route"][route]["se_person"]) for f in F]),
                 test("\\quad placebo test", {f: PT[f][ch]["p_joint_placebo_person"] for f in F}, pre),
                 test("\\quad date-shift test", {f: PT[f][ch]["p_joint_shifted"] for f in F}, pre)]
    rows.append(est("Not-yet-exposed comparison pool",
                    [(V[f]["never_exposed_pool"]["ate_log"], V[f]["never_exposed_pool"]["se_person"]) for f in F]))
    for key, lab in (("missing_as_zero", "Missing output set to zero"),
                     ("missing_as_own_mean", "Missing output set to own mean"),
                     ("post_departure_zeros", "Empty years after leaving set to zero")):
        rows += [est(lab, [(V[f][key]["ate_log"], V[f][key]["se_person"]) for f in F]),
                 test("\\quad placebo test", {f: V[f][key]["p_joint_placebo"] for f in F}, pre)]
    rows += [
        est("Main specification", [(L[f"p2_{f}"]["ate_pp"], L[f"p2_{f}"]["se_person_pp"]) for f in F]),
        test("\\quad date-shift test", {f: RB["p2_date_shift"][f]["p_joint_shifted"] for f in F}, pre),
        test("\\quad shuffled arrival years", {f: perm[f"p2_{f}"]["p_perm_abs_ate"] for f in F}, shuf),
        est("Main specification", [(T[f]["ate_pp"], T[f]["se_pair_pp"]) for f in F]),
        test("\\quad date-shift test", {f: RB["p3_date_shift"][f]["p_joint_shifted"] for f in F}, pre),
        test("\\quad shuffled arrival years", {f: T[f]["randomization_inference"]["p_two_sided"] for f in F}, shuf),
        est("Both incumbents at or above median positive dose",
            [(RB["p3_cut_grid"][f]["med"]["ate_pp"], RB["p3_cut_grid"][f]["med"]["se_pair_pp"]) for f in F]),
    ]
    # note numbers: shuffles requested and completed, the 0.05 rule stated three times, and the two
    # t-statistic p-values the plan names (chemistry Panel 1, mathematics Panel 2)
    note = [str(perm["B"]), str(perm["p2_math_stats"]["B_ok"]), "0.05", "0.05", "0.05",
            f3(perm["p1_chemistry"]["p_perm_abs_t"]), f3(perm["p2_math_stats"]["p_perm_abs_t"])]
    # (the base tree's note prints the same multiset: "(now below 0.05)" is its third "0.05")
    return [(_lab(tree, lab), cells) for lab, cells in rows], note


def expected_panels(tree="thesis_report"):
    L, T, _, M = _ledgers(tree)
    return [
        ("Panel 1", ["incumbent $\\times$ event $\\times$ year", "FWCI-weighted output", "similarity dose $\\times$ post-arrival"]
         + [n(M["panel_rows"][MK[f]][0]) for f in F]),
        ("Panel 2", ["incumbent $\\times$ star $\\times$ year", "first paper with the star", "star arrival"]
         + [n(M["panel_rows"][MK[f]][1]) for f in F]),
        ("Panel 3", ["pair $\\times$ event $\\times$ year, same-topic incumbents outside the star's network",
                     "first tie between colleagues", "star arrival"] + [n(T[f]["rows"]) for f in F]),
        ("Star arrivals (events)", [str(M[f"{MK[f]}_events"]) for f in F]),
        ("Incumbents", [n(M[f"{MK[f]}_persons"]) for f in F]),
        ("Incumbent--event relations", [n(M[f"{MK[f]}_relations"]["total"]) for f in F]),
    ]


def main_note_numbers(tree="thesis_report"):
    """Numbers in the Table 2 note: the year cap of the raw rates. The Panel 1 age-gap cap moved to
    Section 2.3 of the draft on 2026-09-16, so the thesis_report note no longer prints it; the
    generator still asserts the frozen records carry that cap. The base tree's note (author,
    2026-10-04) prints it again ("above 60 years"), read from the same frozen records."""
    L, _, _, _ = _ledgers(tree)
    caps = {re.fullmatch(r"\|age_gap\|<=(\d+)", json.load(open(P["expected"] / f"{x}.json"))["spec"]["filter"]).group(1)
            for x in ("P1_econ_fnfix", "P1_fnfix_chemistry", "P1_fnfix_math_stats")}
    assert caps == {"60"}, caps
    return [str(L["year_cap"])] + (sorted(caps) if tree == BASE else [])


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------
def test_main_table_rows_equal_ledger(tables, tree):
    assert data_rows(tables["tab_main_results.tex"]) == expected_main(tree)


def test_robustness_rows_equal_ledger(tables, tree):
    rows, _ = expected_robustness(tree)
    assert data_rows(tables["tab_robustness.tex"]) == rows


def test_panels_rows_equal_ledger(tables, tree):
    assert data_rows(tables["tab_panels_overview.tex"]) == expected_panels(tree)


def test_every_printed_number_is_accounted_for(tables, tree):
    rows, note = expected_robustness(tree)
    for name, exp in (("tab_main_results.tex", expected_numbers(expected_main(tree), main_note_numbers(tree))),
                      ("tab_robustness.tex", expected_numbers(rows, note)),
                      ("tab_panels_overview.tex", expected_numbers(expected_panels(tree)))):
        got = numbers(body(tables[name]))
        assert got == exp, (name, got - exp, exp - got)


def test_known_values_spot_check(tables, tree):
    """A few cells typed from the cal2026-10 ledgers (2026-09-23; the pre-October values were
    -0.378 (0.062), 0.010/0.387/0.312, 0.004/0.062/0.551, 116 events, 1,043 incumbents, 10,763
    relations), as a guard against a ledger swap."""
    rob = dict((lab, cells) for lab, cells in data_rows(tables["tab_robustness.tex"])[:4])
    assert rob["Main specification"][0] == "-0.368 (0.066)"
    assert rob["\\quad placebo test"] == ["0.003", "0.856", "0.175", "Chem., Math."]
    assert rob["\\quad shuffled arrival years"] == ["0.018", "0.144", "0.766", "Econ."]
    pan = data_rows(tables["tab_panels_overview.tex"])
    assert pan[-3] == ("Star arrivals (events)", ["113", "38", "33"])
    assert pan[-2] == ("Incumbents", ["822", "470", "481"])
    assert pan[-1] == ("Incumbent--event relations", ["6,643", "2,785", "1,810"])
    note = body(tables["tab_main_results.tex"])
    assert "up to 2024." in note and "Switching pairs" not in note
    t = body(tables["tab_robustness.tex"])
    if tree == BASE:
        assert "above 60 years" in note and "(one year more than the estimates)" in note
        assert "0.006 for mathematics in Panel 2 (now below 0.05)" in t
        assert "0.084 for chemistry in Panel 1 (still above)" in t
        assert "In this table a relation is one" in body(tables["tab_panels_overview.tex"])
    else:
        assert "above 60 years" not in note
        assert "(0.084)" in t and "(0.006)" in t


def test_labels_refs_and_deleted_material(tables):
    want = {"tab_main_results.tex": "tab:main", "tab_robustness.tex": "tab:robustness",
            "tab_panels_overview.tex": "tab:panels"}
    allowed_refs = {"sec:baseline", "sec:panels", "sec:exposure", "tab:main", "tab:panels", "eq:p1", "eq:p2", "eq:p3"}
    for name, tex in tables.items():
        b = body(tex)
        assert re.findall(r"\\label\{([^}]*)\}", b) == [want[name]], name
        assert set(re.findall(r"\\(?:eq)?ref\{([^}]*)\}", b)) <= allowed_refs, name
        low = b.lower()
        for gone in ("appendix", "simulat", "percent change", "with positive dose", "tab_disciplines"):
            assert gone not in low, (name, gone)
    assert not any(lab == "Incumbents" for lab, _ in data_rows(tables["tab_main_results.tex"]))


def test_style_rules(tables):
    banned = ["delve", "landscape", "crucial", "comprehensive", "furthermore", "notably", "leverage",
              "pivotal", "shed light", "underscore", "robust", "we", "our"]
    for name, tex in tables.items():
        b = body(tex)
        assert "---" not in b, name
        text = re.sub(r"\\[A-Za-z]+", " ", b).lower()
        for w in banned:
            assert not re.search(r"\b" + re.escape(w) + r"\b", text), (name, w)


def test_deterministic_and_writes_only_its_three_files(tmp_path, tree):
    official = sorted((P["output"] / "paper").glob("tab_*.tex"))
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in official}
    a = _gen(tmp_path / "a", tree)
    b = _gen(tmp_path / "b", tree)
    assert a == b
    assert sorted(x.name for x in (tmp_path / "a").iterdir()) == sorted(NAMES + ("NOTE_CHECKS.json",))
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in official}
    assert before == after


def test_draft_copies_match_a_fresh_generation(tables, tree):
    # base tree: the fixture copies of the author's 2026-10-11 tree (in git, so never skipped);
    # thesis_report: the 2026-09-13 draft folder, when this machine has it (skipped on AWS today)
    target = BASE_FIX / "tables" if tree == BASE else DRAFT_TABLES
    if not target.is_dir():
        pytest.skip("draft folder not present on this machine")
    for name in NAMES:
        assert (target / name).read_text() == tables[name], name
