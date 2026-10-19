#!/usr/bin/env python3
r"""draft_2026_09_13_tables.py - the three tables of the 2026-09-13 full draft.

Plan (table section of the full-draft structure): Table 1 panels overview kept with a short note and discipline counts; Table 2 the
three main tables merged (percent row, "with positive dose" and "Incumbents" dropped, event
clusters kept, arrival-year switchers kept); Table 3 robustness with a pass column, a placebo p
on every Panel 1 estimate, no simulation row, and the t-statistic version of the shuffled-years p
in the note. Section 4.1 of the plan moves the Panel 1 route split (roster / network) into Table 3.

Outputs (written ONLY into --out-dir):
  tab_main_results.tex     label tab:main
  tab_robustness.tex       label tab:robustness
  tab_panels_overview.tex  label tab:panels

Inputs (read-only). Default and --ledger-dir: the dated thesis ledgers (the draft's "% src:" aliases
PP / P3 / R / M resolve to them by ledger, not by date):
  thesis_report/data_numbers_2026-10-23_p1p2.json
  thesis_report/data_numbers_2026-10-23_p3afar.json
  thesis_report/data_numbers_2026-10-23_robustness.json
  thesis_report/data_numbers_2026-10-23.json   (main + carried merged)
  (cal2026-10, installed 2026-09-23 from output/paper/data_numbers_{p1p2,p3afar,robustness,main,carried}.json;
   until then the 2026-08-28 / 2026-08-30 / 2026-09-13 ledgers, now in thesis_report/_archive/)
--paper-dir DIR (R1; run_all's staged 3light passes $O/paper): this run's undated ledgers
  DIR/data_numbers_{p1p2,p3afar,robustness}.json and DIR/data_numbers_{main,carried}.json, the last two
  merged as install.py merges them (bodies only; a shared key stops). A missing file stops: never a
  fall-back to the thesis ledgers. The "% src:" names in the tables stay the dated ones, so on equal
  values the bytes equal the --ledger-dir output.
  analysis/expected/P1_econ_fnfix.json, P1_fnfix_chemistry.json, P1_fnfix_math_stats.json
    (spec.filter: the academic-age-gap cap, stated in Section 2.3 of the draft; checked here)

No number is typed by hand. Row definitions and number formats follow tables_p1p2.py,
tables_p3afar.py and tables_robustness.py; this script neither imports nor modifies them (the
official sentinel compares their outputs byte for byte). Every row line ends with a
"% src: <ledger> <key>" comment. New material is wrapped in \REV{}; the panels table keeps its
unmarked original cells; its note is rewritten in full inside \REV{} (2026-09-14).

Pass rule (plan, top of section one): a pre-arrival test (placebo, date shift) passes when
p > 0.05; the shuffled-arrival-years test passes when p < 0.05. Rows that are only an alternative
estimate carry no test and leave the pass column empty.

Layout note: a p{} column whose cell opens with \REV (a \color) needs \leavevmode in its column
prefix, or the label drops one line below the numbers of its row.

Two trees (2026-10-16), chosen by --tree:
  thesis_report    (default) the tables as legacy thesis_report/tables holds them; byte-identical to
                   the output before the switch existed (tools/check_paper.py section B compares them).
  base_2026_10_11  the base manuscript tree: the
                   hand edits of 2026-10-03/04 carried in verbatim - row labels, notes and the TeX
                   comment blocks that record them. Byte target: tests/fixtures/r1_paper/base_tree_2026-10-11 (not shipped).
--ledger-dir names the folder of the dated ledgers (default: legacy thesis_report/); --paper-dir (above)
reads the undated ones instead. The two are exclusive.
October note diagnostics remain as "% cal2026-10 FLAG for the author" comments (both trees).
Table 3's visible n.a., incomplete-run and t-ranking clauses follow the current ledger cells;
the October ledgers still reproduce both trees byte for byte.

Run:  setup/.venv/bin/python analysis/paper/draft_2026_09_13_tables.py --out-dir <dir>
          [--tree {thesis_report,base_2026_10_11}] [--ledger-dir <dir> | --paper-dir <dir>]
Test: setup/.venv/bin/python -m pytest -q tests/test_draft_2026_09_13_tables.py tests/test_r1_tables_base_tree.py
Written 2026-09-13.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from analysis.lib.paths import load_paths

P = load_paths()
TR = P["legacy_thesis"] / "thesis_report"   # the default --ledger-dir
BASE = "base_2026_10_11"
TREES = ("thesis_report", BASE)
LEDGER_DATE = "2026-10-23"   # the cal2026-10 thesis ledgers (was 2026-08-30 p1p2 / 2026-08-28 p3afar + main / 2026-09-13 robustness)
F_PP = f"data_numbers_{LEDGER_DATE}_p1p2.json"
F_P3 = f"data_numbers_{LEDGER_DATE}_p3afar.json"
F_R = f"data_numbers_{LEDGER_DATE}_robustness.json"
F_M = f"data_numbers_{LEDGER_DATE}.json"

F = ("econ", "chemistry", "math_stats")
MKEY = {"econ": "econ", "chemistry": "chem", "math_stats": "math"}   # key prefixes in the merged main ledger (F_M)
ABBR = {"econ": "Econ.", "chemistry": "Chem.", "math_stats": "Math."}
PASS_P = 0.05
P1_EXPECTED = {"econ": "P1_econ_fnfix", "chemistry": "P1_fnfix_chemistry", "math_stats": "P1_fnfix_math_stats"}


# ---------------------------------------------------------------------------
# formatting (identical to the house generators)
# ---------------------------------------------------------------------------
def num(x, d=3):
    s = f"{x:.{d}f}"
    if s.lstrip("-").strip("0.") == "":   # a rounded zero prints as 0.000, never as -0.000
        s = s.lstrip("-")
    return s.replace("-", "$-$")


def big(n):
    return f"{n:,}".replace(",", "{,}")


FAILED = "n.a."   # a test that cannot be computed in the cal2026-10 rebuild (ledger null, never filled in); the Table 3 note says why


def pval(p):
    if p is None:
        return FAILED
    return "$<$0.001" if p < 0.001 else f"{p:.3f}"


# Claims the notes make about numbers (cal2026-10). A claim that no longer holds is NOT reworded here
# (the notes are the author's sentences): it is recorded in NOTE_CHECKS, printed as a
# "% cal2026-10 FLAG for the author" comment above the note, and written to NOTE_CHECKS.json in --out-dir.
NOTE_CHECKS = []


def note_check(table, claim, ok, detail):
    NOTE_CHECKS.append({"table": table, "claim": claim, "holds": bool(ok), "detail": detail})
    return bool(ok)


def flags(table):
    return ["% cal2026-10 FLAG for the author: this note sentence no longer matches the numbers: "
            + c["claim"] + " (" + c["detail"] + ")" for c in NOTE_CHECKS if c["table"] == table and not c["holds"]]


def est_se(e, s):
    return f"{num(e)} ({num(s)})"


def R(s):
    return "\\REV{" + s + "}"


def row(label, cells, src):
    return R(label) + " & " + " & ".join(R(c) if c != "" else "" for c in cells) + " \\\\ % src: " + src


def block(text, ncols):
    return "\\multicolumn{" + str(ncols) + "}{@{}l}{" + R("\\emph{" + text + "}") + "} \\\\"


def passes_in(ps, rule):
    """Disciplines in which a test passes, for the robustness table's last column (a failed run,
    p = None, is neither a pass nor a fail and is left out; its cell prints 'n.a.')."""
    ok = [f for f in F if ps[f] is not None and rule(ps[f])]
    if len(ok) == len(F):
        return "All"
    if not ok:
        return "None"
    return ", ".join(ABBR[f] for f in ok)


def pre_rule(p):
    return p > PASS_P


def perm_rule(p):
    return p < PASS_P


HEAD_DISC = (R("Economics") + " & " + R("Chemistry") + " & \\multicolumn{1}{r}{\\shortstack[r]{"
             + R("Mathematics") + "\\\\ " + R("and statistics") + "}}")


def load(ledger_dir=TR):
    L = json.load(open(ledger_dir / F_PP))
    T = json.load(open(ledger_dir / F_P3))
    RB = json.load(open(ledger_dir / F_R))
    M = json.load(open(ledger_dir / F_M))
    return L, T, RB, M


def load_paper(d):
    """This run's undated output/paper ledgers (R1, review R7 #7). M = the bodies of data_numbers_main.json
    and data_numbers_carried.json merged as install.merged_main merges them (keys starting with '_' left
    out; a key in both stops). A missing file stops: never a fall-back to the thesis ledgers."""
    d = Path(d)

    def j(name):
        p = d / name
        if not p.is_file():
            raise SystemExit(f"--paper-dir: {p} is missing (the thesis ledgers are never read instead)")
        return json.load(open(p))
    L, T, RB = j("data_numbers_p1p2.json"), j("data_numbers_p3afar.json"), j("data_numbers_robustness.json")
    m, c = j("data_numbers_main.json"), j("data_numbers_carried.json")
    body_m = {k: v for k, v in m.items() if not k.startswith("_")}
    body_c = {k: v for k, v in c.items() if not k.startswith("_")}
    clash = sorted(set(body_m) & set(body_c))
    if clash:
        raise SystemExit(f"--paper-dir: data_numbers_main.json and data_numbers_carried.json share keys: {clash}")
    return L, T, RB, {**body_m, **body_c}


# ---------------------------------------------------------------------------
# the base tree (2026-10-11): the author's hand edits, verbatim. The comment blocks are the lines the
# lead writer left in the base tree's tables (they stay in the file, so the installer's copy into the
# base tree changes numbers only); the labels and notes are the edited text.
# ---------------------------------------------------------------------------
BASE_MAIN_COMMENT = [
    "% 2026-10-03 lead writer 2: note only (first-tie rate; raw-rate window one year longer than the",
    "% estimates; the few-clusters remark, which repeats Section 3.1, removed). Numbers untouched.",
    "% 2026-10-03 round 1 (lead writer 2), edited here, TO CARRY INTO THE GENERATOR draft_2026_09_13_tables.py:",
    "%   row label \"Raw rate before arrival (\\% per year)\" -> \"Pre-arrival rate (\\% per year)\" (both rows, gen. lines ~226, ~245);",
    "%   note: \"after which the unit leaves the sample\" -> \"after which the relation leaves the sample\";",
    "%   note: sentence \"Switching relations enter the arrival-year comparison.\" deleted (gen. line ~264).",
    "% 2026-10-04 round 3 (lead writer 2), TO CARRY INTO THE GENERATOR:",
    "%   Panel 3 row label \"Joint test ($p$), pair clusters\" -> \"Joint test ($p$), post-arrival coefficients\""
    " (sub-row \"event clusters\" as in Panels 1-2; pair clusters stay in the s.e. row);",
    "%   note: sentences \"Joint tests cover the post-arrival coefficients and, in Panel 1, the four placebo"
    " coefficients.\" and \"Standard errors are in parentheses.\" deleted (row labels now say both).",
]
BASE_ROB_COMMENT = [
    "% 2026-10-03 lead writer 2: note only (test definitions that repeat Section 3 removed; 500/477 runs,",
    "% the p formula, n.a. and the t-ranking kept). Numbers untouched (generator-owned).",
    "% 2026-10-03 round 1 (lead writer 2), edited here, TO CARRY INTO THE GENERATOR draft_2026_09_13_tables.py:",
    "%   row labels (gen. line ~349, ~356): \"Incumbents on the roster\" -> \"Roster incumbents\";",
    "%   \"Incumbents in the star's network\" -> \"Network incumbents\"; \"Not-yet-exposed comparison pool\""
    " -> \"Comparisons before any exposure\";",
    "%   note: \"An incumbent reached both ways is in both route rows.\" -> \"An incumbent who is both is in both rows.\"",
    "% 2026-10-03 round 2 (lead writer 2), TO CARRY INTO THE GENERATOR (note line):",
    "%   note: \"An incumbent who is both is in both rows.\" -> \"An incumbent on the roster and in the network"
    " appears in both rows.\"",
    "% 2026-10-04 round 3 (lead writer 2), TO CARRY INTO THE GENERATOR:",
    "%   row label \"Comparisons before any exposure\" -> \"Comparisons before any exposure (arrival year to year 3)\""
    " (no comparisons at ell=4,5: battery/P1nex_econ.json k=5,6 n=0);",
    "%   note: t-ranking sentence -> \"Ranked by $t$-statistic instead of estimate, the shuffled $p$ is 0.006 for"
    " mathematics in Panel 2 (now below 0.05) and 0.084 for chemistry in Panel 1 (still above).\"",
]
# row labels: thesis_report text -> base-tree text
BASE_LABEL = {
    "Raw rate before arrival (\\% per year)": "Pre-arrival rate (\\% per year)",
    "Joint test ($p$), pair clusters": "Joint test ($p$), post-arrival coefficients",
    "Incumbents on the roster": "Roster incumbents",
    "Incumbents in the star's network": "Network incumbents",
    "Not-yet-exposed comparison pool": "Comparisons before any exposure (arrival year to year 3)",
}


def lab_for(tree, label):
    return BASE_LABEL.get(label, label) if tree == BASE else label


def age_gap_cap(L):
    """The Panel 1 academic-age-gap cap, read from the spec of the frozen estimation records.

    Section 2.3 of the draft states the cap (60 years); the Table 2 note no longer repeats it, so
    this function is kept as the check that the frozen records still carry that cap.
    """
    import re
    caps = set()
    for f in F:
        d = json.load(open(P["expected"] / (P1_EXPECTED[f] + ".json")))
        u = d["channels"]["union"]   # the record is the run the ledger reports
        assert (round(u["ate"], 3), u["rels"], u["obs"]) == (round(L[f"p1_{f}"]["ate_log"], 3),
                                                    L[f"p1_{f}"]["relations"], L[f"p1_{f}"]["obs"]), f
        m = re.fullmatch(r"\|age_gap\|<=(\d+)", d["spec"]["filter"])
        assert m, (f, d["spec"]["filter"])
        caps.add(int(m.group(1)))
    assert len(caps) == 1, caps
    return caps.pop()


# ===========================================================================
# Table 2: main results, three panels by discipline
# ===========================================================================
def main_table(L, T, M, tree="thesis_report"):
    cap = L["year_cap"]
    assert cap == T["year_cap"], (cap, T["year_cap"])
    p1 = {f: L[f"p1_{f}"] for f in F}
    p2 = {f: L[f"p2_{f}"] for f in F}
    p3 = {f: T[f] for f in F}
    age_cap = age_gap_cap(L)
    if tree != BASE:
        assert age_cap == 60   # the cap Section 2.3 of the draft states (the base note prints age_cap itself)
    lab = lambda s: lab_for(tree, s)   # noqa: E731
    rows1 = {f: M["panel_rows"][MKEY[f]][0] for f in F}
    note_check("tab:main", "Panel 1 incumbent--event--years are below the Panel 1 rows of Table 1",
               all(p1[f]["obs"] < rows1[f] for f in F),
               "; ".join(f"{f} {p1[f]['obs']} vs {rows1[f]}" for f in F))

    def ci(c, k):
        return f"[{num(c[k][0])}, {num(c[k][1])}]"

    o = ["% Table 2 of the 2026-09-13 draft: main results by discipline. GENERATED by",
         f"% analysis/paper/draft_2026_09_13_tables.py from {F_PP} and {F_P3}; do not edit numbers by hand."]
    if tree == BASE:
        o += BASE_MAIN_COMMENT
    o += ["\\begin{table}[tp]", "\\centering",
         "\\caption{" + R("Main estimates by discipline") + "}",
         "\\label{tab:main}", "\\footnotesize\\setlength{\\tabcolsep}{3pt}",
         "\\begin{tabular}{@{}l r r r@{}}", "\\toprule",
         " & " + HEAD_DISC + " \\\\", "\\midrule"]
    s1 = F_PP + " p1_{econ,chemistry,math_stats}."
    o += [block("Output (Panel 1)", 4),
          row("Average change per unit of dose (log points)", [num(p1[f]["ate_log"]) for f in F], s1 + "ate_log"),
          row("\\quad s.e., incumbent clusters", [f"({num(p1[f]['se_person'])})" for f in F], s1 + "se_person"),
          row("\\quad s.e., event clusters", [f"({num(p1[f]['se_event'])})" for f in F], s1 + "se_event"),
          row("95\\% CI, incumbent clusters", [ci(p1[f], "ci95_person") for f in F], s1 + "ci95_person"),
          row("Joint test ($p$), post-arrival coefficients", [pval(p1[f]["p_joint_effects_person"]) for f in F],
              s1 + "p_joint_effects_person"),
          row("\\quad event clusters", [pval(p1[f]["p_joint_effects_event"]) for f in F], s1 + "p_joint_effects_event"),
          row("Joint test ($p$), placebo coefficients", [pval(p1[f]["p_joint_placebo_person"]) for f in F],
              s1 + "p_joint_placebo_person"),
          row("\\quad event clusters", [pval(p1[f]["p_joint_placebo_event"]) for f in F], s1 + "p_joint_placebo_event"),
          "\\addlinespace[2pt]",
          row("Incumbent--event relations", [big(p1[f]["relations"]) for f in F], s1 + "relations"),
          row("Switching relations at $\\ell=0$", [big(p1[f]["switchers_ell0"]) for f in F], s1 + "switchers_ell0"),
          row("Events", [str(p1[f]["events"]) for f in F], s1 + "events"),
          row("Incumbent--event--years", [big(p1[f]["obs"]) for f in F], s1 + "obs"),
          "\\midrule"]
    s2 = F_PP + " p2_{econ,chemistry,math_stats}."
    o += [block("First paper with the star (Panel 2)", 4),
          row("Average post-arrival change (pp per year)", [num(p2[f]["ate_pp"]) for f in F], s2 + "ate_pp"),
          row("\\quad s.e., incumbent clusters", [f"({num(p2[f]['se_person_pp'])})" for f in F], s2 + "se_person_pp"),
          row("\\quad s.e., event clusters", [f"({num(p2[f]['se_event_pp'])})" for f in F], s2 + "se_event_pp"),
          row("95\\% CI, incumbent clusters", [ci(p2[f], "ci95_person_pp") for f in F], s2 + "ci95_person_pp"),
          row("Joint test ($p$), post-arrival coefficients", [pval(p2[f]["p_joint_effects_person"]) for f in F],
              s2 + "p_joint_effects_person"),
          row("\\quad event clusters", [pval(p2[f]["p_joint_effects_event"]) for f in F], s2 + "p_joint_effects_event"),
          row(lab("Raw rate before arrival (\\% per year)"), [num(p2[f]["rate_pre_pp"]) for f in F], s2 + "rate_pre_pp"),
          row(f"Raw rate after arrival, to {cap} (\\% per year)", [num(p2[f]["rate_post_obs_pp"]) for f in F],
              s2 + "rate_post_obs_pp; year_cap"),
          "\\addlinespace[2pt]",
          row("Incumbent--star relations", [big(p2[f]["relations"]) for f in F], s2 + "relations"),
          row("First ties", [big(p2[f]["first_ties"]) for f in F], s2 + "first_ties"),
          row("Switching relations at $\\ell=0$", [big(p2[f]["switchers_ell0"]) for f in F], s2 + "switchers_ell0"),
          row("Events", [str(p2[f]["events"]) for f in F], s2 + "events"),
          row("Relation--years", [big(p2[f]["rows"]) for f in F], s2 + "rows"),
          "\\midrule"]
    s3 = F_P3 + " {econ,chemistry,math_stats}."
    o += [block("First tie between colleagues (Panel 3)", 4),
          row("Average post-arrival change (pp per year)", [num(p3[f]["ate_pp"]) for f in F], s3 + "ate_pp"),
          row("\\quad s.e., pair clusters", [f"({num(p3[f]['se_pair_pp'])})" for f in F], s3 + "se_pair_pp"),
          row("\\quad s.e., event clusters", [f"({num(p3[f]['se_event_pp'])})" for f in F], s3 + "se_event_pp"),
          row("95\\% CI, pair clusters", [ci(p3[f], "ci95_pair_pp") for f in F], s3 + "ci95_pair_pp"),
          row(lab("Joint test ($p$), pair clusters"), [pval(p3[f]["p_joint_effects_pair"]) for f in F],
              s3 + "p_joint_effects_pair"),
          row("\\quad event clusters", [pval(p3[f]["p_joint_effects_event"]) for f in F], s3 + "p_joint_effects_event"),
          row(lab("Raw rate before arrival (\\% per year)"), [num(p3[f]["rate_pre_pp"]) for f in F], s3 + "rate_pre_pp"),
          row(f"Raw rate after arrival, to {cap} (\\% per year)", [num(p3[f]["rate_post_obs_pp"]) for f in F],
              s3 + "rate_post_obs_pp; year_cap"),
          "\\addlinespace[2pt]",
          row("Pairs", [big(p3[f]["pairs"]) for f in F], s3 + "pairs"),
          row("First ties", [big(p3[f]["first_ties"]) for f in F], s3 + "first_ties"),
          row("Events with pairs", [str(p3[f]["events_with_pairs"]) for f in F], s3 + "events_with_pairs"),
          row("Pair--event--years", [big(p3[f]["rows"]) for f in F], s3 + "rows"),
          "\\bottomrule", "\\end{tabular}",
          "\\par\\smallskip", "\\begin{minipage}{0.95\\textwidth}\\footnotesize"]
    notes = (
        "\\emph{Notes}: Each discipline within a panel is one estimation of equation~\\eqref{eq:p1}, "
        "\\eqref{eq:p2} or~\\eqref{eq:p3}, with the estimator of Section~\\ref{sec:baseline} on the samples "
        "of Section~\\ref{sec:panels}. In Panel 1 the outcome is the log of one plus yearly FWCI-weighted "
        "output, and the average change is rescaled to one unit of dose. In Panels 2 and 3 the outcome is "
        "one in the year of the first joint paper, with the star or within the pair, after which the unit "
        "leaves the sample; changes are in percentage points (pp) of the yearly first-tie probability. Joint tests "
        "cover the post-arrival coefficients and, in Panel 1, the four placebo coefficients. Standard "
        "errors are in parentheses; with few events in chemistry and mathematics, "
        "event-clustered ones tend to be too small. Switching relations enter the arrival-year "
        "comparison. Raw rates are shares of relation-years or pair-years with a first tie, with no "
        "comparison group, over the six years before the arrival and over the arrival year and the five "
        f"years after it, up to {cap}. Panel 1 "
        "estimates use only incumbent--event--years with an output value, so their counts are below those in "
        "Table~\\ref{tab:panels} and Section~\\ref{sec:exposure}."
    )
    if tree == BASE:   # the base tree's note (lead writer 2, 2026-10-03/04), verbatim
        notes = (
            "\\emph{Notes}: Each discipline within a panel is one estimation of equation~\\eqref{eq:p1}, "
            "\\eqref{eq:p2} or~\\eqref{eq:p3}, with the estimator of Section~\\ref{sec:baseline} on the samples "
            "of Section~\\ref{sec:panels}. In Panel 1 the outcome is the log of one plus yearly FWCI-weighted "
            "output, and the average change is rescaled to one unit of dose. In Panels 2 and 3 the outcome is "
            "one in the year of the first joint paper, with the star or within the pair, after which the relation "
            "leaves the sample; changes are in percentage points (pp) of the first-tie rate. Raw rates are shares "
            "of relation-years or pair-years with a first tie, with no comparison group, over the six years "
            "before the arrival and over the arrival year and the five years after it (one year more than the "
            f"estimates), up to {cap}. Panel 1 drops relations whose academic-age gap to the star is above "
            f"{age_cap} years or cannot be computed, and years without an output value, so its counts are below "
            "those in Table~\\ref{tab:panels} and Section~\\ref{sec:exposure}."
        )
    o += flags("tab:main") + [R(notes), "\\end{minipage}", "\\end{table}"]
    return "\n".join(o) + "\n"


# ===========================================================================
# Table 3: robustness, with a pass column
# ===========================================================================
def robustness_table(L, T, RB, tree="thesis_report"):
    V = RB["p1_variants"]
    PT = RB["p1_pretrend_by_channel"]
    perm = L["perm_pvalues"]
    p1 = {f: L[f"p1_{f}"] for f in F}

    # consistency between ledgers that describe the same runs
    for f in F:
        assert abs(PT[f]["union"]["p_joint_placebo_person"] - p1[f]["p_joint_placebo_person"]) < 0.0005, f
        assert PT[f]["union"]["p_joint_shifted"] == RB["p1_date_shift"][f]["p_joint_shifted"], f
        assert p1[f]["by_route"]["roster"]["relations"] == PT[f]["dept"]["relations"], f
        assert p1[f]["by_route"]["network"]["relations"] == PT[f]["network"]["relations"], f
        assert T[f]["robustness"]["date_shift_two_years"]["p_joint_shifted"] == RB["p3_date_shift"][f]["p_joint_shifted"], f
        fm = T[f]["robustness"]["former_main_cut"]
        med = RB["p3_cut_grid"][f]["med"]
        assert (fm["ate_pp"], fm["se_pair_pp"], fm["pairs"]) == (med["ate_pp"], med["se_pair_pp"], med["pairs"]), f
        assert V[f]["never_exposed_pool"]["p_joint_placebo"] is None, f   # the pool has no tests
        assert T[f]["randomization_inference"]["permutations"] == perm["B"], f

    B = perm["B"]
    cells = [f"p{i}_{f}" for i in (1, 2) for f in F]
    short = {k: perm[k]["B_ok"] for k in cells if perm[k]["B_ok"] != B}
    b_ok_m2 = perm["p2_math_stats"]["B_ok"]   # the count the note prints (= short['p2_math_stats'] in October)
    # the note names exactly this cell as the one with fewer completed draws (was a hard assert until
    # R1 N10: an October fact, so a FLAG, never a crash and never a reword)
    note_check("tab:robustness",
               f"shuffling: {B} runs ({b_ok_m2} completed for mathematics, Panel 2), the only cell with "
               "fewer completed runs than requested",
               list(short) == ["p2_math_stats"],
               "cells with fewer completed runs than requested: "
               + (", ".join(f"{k} {v}" for k, v in short.items()) or "none"))
    # cells the t-statistic ranking moves below 0.05 while the estimate ranking does not
    flip = [k for k in cells if perm[k]["p_perm_abs_ate"] >= PASS_P and perm[k]["p_perm_abs_t"] < PASS_P]
    t_detail = ("cells where the t-ranked p is below the threshold and the estimate-ranked p is not: "
                + (", ".join(flip) or "none") + "; t-ranked p: "
                + ", ".join(f"{k} {perm[k]['p_perm_abs_t']:.3f}" for k in ("p1_chemistry", "p2_math_stats")))
    if tree == BASE:
        # the base note (2026-10-04): "... 0.006 for mathematics in Panel 2 (now below 0.05) and 0.084 for
        # chemistry in Panel 1 (still above)" - "now" and "still" compare with the estimate ranking
        note_check("tab:robustness",
                   f"ranked by t-statistic, the shuffled p for mathematics in Panel 2 is now below {PASS_P} "
                   "(the estimate-ranked p is not)",
                   perm["p2_math_stats"]["p_perm_abs_t"] < PASS_P <= perm["p2_math_stats"]["p_perm_abs_ate"],
                   t_detail + f"; estimate-ranked p2_math_stats {perm['p2_math_stats']['p_perm_abs_ate']:.3f}")
        note_check("tab:robustness",
                   f"ranked by t-statistic, the shuffled p for chemistry in Panel 1 is still above {PASS_P} "
                   "(as the estimate-ranked p is)",
                   perm["p1_chemistry"]["p_perm_abs_t"] >= PASS_P and perm["p1_chemistry"]["p_perm_abs_ate"] >= PASS_P,
                   t_detail + f"; estimate-ranked p1_chemistry {perm['p1_chemistry']['p_perm_abs_ate']:.3f}")
    else:
        # the note names this one cell and says chemistry Panel 1 is not one (the October rewrite of the
        # note, 2026-09-23; until cal2026-10 the note named both cells, and before that a hard assert)
        note_check("tab:robustness",
                   f"ranked by t-statistic, the shuffled runs also give p<{PASS_P} for mathematics in Panel 2 "
                   "(and for no other cell) but not for chemistry in Panel 1",
                   flip == ["p2_math_stats"] and perm["p1_chemistry"]["p_perm_abs_t"] >= PASS_P,
                   t_detail)

    # the one cell printed 'n.a.' and the reason the note gives for it (supervisor round 4, #46; 2026-10)
    na = [f for f in F if RB["p2_date_shift"][f]["p_joint_shifted"] is None]
    rawm = L["p2_math_stats"]["raw_rate_by_event_time_pp"]
    note_check("tab:robustness", "n.a.: no first ties in those two years (mathematics, Panel 2 date-shift test)",
               na == ["math_stats"] and RB["p2_date_shift"]["math_stats"].get("status") == "AUX_FAILED"
               and rawm["-2"] == 0 and rawm["-1"] == 0,
               f"cells not computed: {na}; mathematics raw first-tie rate at -2/-1: {rawm['-2']}/{rawm['-1']}")

    ncol = 5
    o = ["% Table 3 of the 2026-09-13 draft: robustness checks with a pass column. GENERATED by",
         f"% analysis/paper/draft_2026_09_13_tables.py from {F_R}, {F_PP} and {F_P3}; do not edit numbers by hand."]
    if tree == BASE:
        o += BASE_ROB_COMMENT
    o += ["\\begin{table}[tp]", "\\centering",
         "\\caption{" + R("Robustness checks by panel") + "}",
         "\\label{tab:robustness}", "\\footnotesize\\setlength{\\tabcolsep}{3pt}",
         "\\begin{tabular}{@{}>{\\raggedright\\arraybackslash\\leavevmode}p{0.35\\textwidth} r r r l@{}}",
         "\\toprule",
         " & " + HEAD_DISC + " & " + R("Passes in") + " \\\\", "\\midrule"]

    def test_row(label, ps, rule, src):
        return row(label, [pval(ps[f]) for f in F] + [passes_in(ps, rule)], src)

    def est_row(label, pairs, src):
        return row(label, [est_se(e, s) for e, s in pairs] + [""], src)

    # ---- Panel 1 ----
    sPT = F_R + " p1_pretrend_by_channel.{econ,chemistry,math_stats}."
    sV = F_R + " p1_variants.{econ,chemistry,math_stats}."
    o += [block("Output (Panel 1): log points per unit of dose (standard error), or $p$", ncol),
          est_row("Main specification", [(p1[f]["ate_log"], p1[f]["se_person"]) for f in F],
                  F_PP + " p1_*.ate_log, se_person"),
          test_row("\\quad placebo test", {f: p1[f]["p_joint_placebo_person"] for f in F}, pre_rule,
                   F_PP + " p1_*.p_joint_placebo_person (passes: p>0.05)"),
          test_row("\\quad date-shift test", {f: RB["p1_date_shift"][f]["p_joint_shifted"] for f in F},
                   pre_rule, F_R + " p1_date_shift.*.p_joint_shifted (passes: p>0.05)"),
          test_row("\\quad shuffled arrival years", {f: perm[f"p1_{f}"]["p_perm_abs_ate"] for f in F}, perm_rule,
                   F_PP + " perm_pvalues.p1_*.p_perm_abs_ate (passes: p<0.05)")]
    for route, ch, lab in (("roster", "dept", "Incumbents on the roster"), ("network", "network", "Incumbents in the star's network")):
        o += [est_row(lab_for(tree, lab), [(p1[f]["by_route"][route]["ate_log"], p1[f]["by_route"][route]["se_person"]) for f in F],
                      F_PP + f" p1_*.by_route.{route}.ate_log, se_person"),
              test_row("\\quad placebo test", {f: PT[f][ch]["p_joint_placebo_person"] for f in F}, pre_rule,
                       sPT + f"{ch}.p_joint_placebo_person (passes: p>0.05)"),
              test_row("\\quad date-shift test", {f: PT[f][ch]["p_joint_shifted"] for f in F}, pre_rule,
                       sPT + f"{ch}.p_joint_shifted (passes: p>0.05)")]
    o.append(est_row(lab_for(tree, "Not-yet-exposed comparison pool"),
                     [(V[f]["never_exposed_pool"]["ate_log"], V[f]["never_exposed_pool"]["se_person"]) for f in F],
                     sV + "never_exposed_pool.ate_log, se_person (no tests)"))
    for key, lab in (("missing_as_zero", "Missing output set to zero"),
                     ("missing_as_own_mean", "Missing output set to own mean"),
                     ("post_departure_zeros", "Empty years after leaving set to zero")):
        o += [est_row(lab, [(V[f][key]["ate_log"], V[f][key]["se_person"]) for f in F], sV + f"{key}.ate_log, se_person"),
              test_row("\\quad placebo test", {f: V[f][key]["p_joint_placebo"] for f in F}, pre_rule,
                       sV + f"{key}.p_joint_placebo (passes: p>0.05)")]
    o.append("\\midrule")

    # ---- Panel 2 ----
    o += [block("First paper with the star (Panel 2): percentage points per year (standard error), or $p$", ncol),
          est_row("Main specification", [(L[f"p2_{f}"]["ate_pp"], L[f"p2_{f}"]["se_person_pp"]) for f in F],
                  F_PP + " p2_*.ate_pp, se_person_pp"),
          test_row("\\quad date-shift test", {f: RB["p2_date_shift"][f]["p_joint_shifted"] for f in F},
                   pre_rule, F_R + " p2_date_shift.*.p_joint_shifted (passes: p>0.05)"),
          test_row("\\quad shuffled arrival years", {f: perm[f"p2_{f}"]["p_perm_abs_ate"] for f in F}, perm_rule,
                   F_PP + " perm_pvalues.p2_*.p_perm_abs_ate (passes: p<0.05)"),
          "\\midrule"]

    # ---- Panel 3 ----
    o += [block("First tie between colleagues (Panel 3): percentage points per year (standard error), or $p$", ncol),
          est_row("Main specification", [(T[f]["ate_pp"], T[f]["se_pair_pp"]) for f in F], F_P3 + " *.ate_pp, se_pair_pp"),
          test_row("\\quad date-shift test", {f: RB["p3_date_shift"][f]["p_joint_shifted"] for f in F},
                   pre_rule, F_R + " p3_date_shift.*.p_joint_shifted (passes: p>0.05)"),
          test_row("\\quad shuffled arrival years", {f: T[f]["randomization_inference"]["p_two_sided"] for f in F},
                   perm_rule, F_P3 + " *.randomization_inference.p_two_sided (passes: p<0.05)"),
          est_row("Both incumbents at or above median positive dose",
                  [(RB["p3_cut_grid"][f]["med"]["ate_pp"], RB["p3_cut_grid"][f]["med"]["se_pair_pp"]) for f in F],
                  F_R + " p3_cut_grid.*.med.ate_pp, se_pair_pp (no test)"),
          "\\bottomrule", "\\end{tabular}",
          "\\par\\smallskip", "\\begin{minipage}{0.95\\textwidth}\\footnotesize"]

    t1 = num(perm["p1_chemistry"]["p_perm_abs_t"])
    t2 = num(perm["p2_math_stats"]["p_perm_abs_t"])
    # Keep the historical diagnostic comments above verbatim: the R1 author tree retains them.
    # Only the visible note is conditional. Include every printed date-shift cell and all nine
    # shuffled-years cells, and detect a t-ranking crossing in either direction.
    has_na = (any(RB[f"p{i}_date_shift"][f]["p_joint_shifted"] is None for i in (1, 2, 3) for f in F)
              or any(PT[f][c]["p_joint_shifted"] is None for f in F for c in ("dept", "network")))
    completed = {k: perm[k]["B_ok"] for k in cells}
    completed.update({f"p3_{f}": B - T[f]["randomization_inference"].get("failed_draws", 0) for f in F})

    def cell_label(k, comma=False):
        panel, field = k.split("_", 1)
        name = {"econ": "economics", "chemistry": "chemistry", "math_stats": "mathematics"}[field]
        return name + (", Panel " if comma else " in Panel ") + panel[1:]

    incomplete = [f"{n} completed for {cell_label(k, comma=True)}" for k, n in completed.items() if n < B]
    runs_note = " (" + "; ".join(incomplete) + ")" if incomplete else ""
    crossed = [k for k in cells if perm_rule(perm[k]["p_perm_abs_ate"]) != perm_rule(perm[k]["p_perm_abs_t"])]
    rank_note = ""
    if crossed:
        # Preserve the author's October sentence, including its chemistry comparison, exactly.
        october_ranking = (crossed == ["p2_math_stats"] and perm_rule(perm["p2_math_stats"]["p_perm_abs_t"])
                           and not perm_rule(perm["p1_chemistry"]["p_perm_abs_t"]))
        if october_ranking and tree == BASE:
            rank_note = (f" Ranked by $t$-statistic instead of estimate, the shuffled $p$ is {t2} for mathematics in "
                         f"Panel 2 (now below {PASS_P}) and {t1} for chemistry in Panel 1 (still above).")
        elif october_ranking:
            rank_note = (" Ranked by $t$-statistic instead of estimate, the shuffled runs also give "
                         f"$p<{PASS_P}$ for mathematics in Panel 2 ({t2}) but not for chemistry in Panel 1 ({t1}).")
        else:
            ranked = [f"{pval(perm[k]['p_perm_abs_t'])} for {cell_label(k)} "
                      f"(now {'below' if perm_rule(perm[k]['p_perm_abs_t']) else 'at or above'} {PASS_P})"
                      for k in crossed]
            rank_note = " Ranked by $t$-statistic instead of estimate, the shuffled $p$ is " + " and ".join(ranked) + "."
    na_note = " (n.a.: no first ties in those two years)" if has_na else ""
    notes = (
        "\\emph{Notes}: Standard errors are clustered by incumbent (pair in Panel 3). An incumbent reached "
        "both ways is in both route rows. The placebo test jointly tests the four pre-arrival "
        "coefficients. The date-shift test moves arrivals two years earlier and tests the two shifted "
        f"coefficients before the true arrival{na_note}. Shuffling reassigns "
        "observed arrival years across events "
        f"{B} times{runs_note}; $p=(k+1)/(B+1)$, where "
        "$k$ of $B$ runs give an estimate at least as large in absolute value. The last column lists where "
        f"each test passes: $p>{PASS_P}$, or $p<{PASS_P}$ for shuffled arrival years, which shows that an "
        "estimate depends on when the stars actually arrived but does not test for pre-arrival trends."
        + rank_note
    )
    if tree == BASE:   # the base tree's note (lead writer 2, 2026-10-03/04), verbatim
        na_note = " Date-shift test, n.a.: no first ties in the two shifted years." if has_na else ""
        notes = (
            "\\emph{Notes}: Standard errors are clustered by incumbent (pair in Panel 3). An incumbent on the "
            f"roster and in the network appears in both rows.{na_note} Shuffled arrival years: {B} runs{runs_note}; "
            "$p=(k+1)/(B+1)$, where $k$ of $B$ runs give an estimate at least as large in absolute value. The "
            f"last column lists where each test passes: $p>{PASS_P}$, or $p<{PASS_P}$ for shuffled arrival "
            "years." + rank_note
        )
    o += flags("tab:robustness") + [R(notes), "\\end{minipage}", "\\end{table}"]
    return "\n".join(o) + "\n"


# ===========================================================================
# Table 1: the three panels, with discipline row counts and event counts
# ===========================================================================
def panels_table(L, T, M, tree="thesis_report"):
    rows = {f: M["panel_rows"][MKEY[f]] for f in F}
    ev = {f: M[f"{MKEY[f]}_events"] for f in F}
    inc = {f: M[f"{MKEY[f]}_persons"] for f in F}
    rel = {f: M[f"{MKEY[f]}_relations"]["total"] for f in F}
    for f in F:
        assert rows[f][1] == L[f"p2_{f}"]["rows"], f          # Panel 2 frame rows = estimation rows
        assert ev[f] == L[f"p1_{f}"]["events"] == L[f"p2_{f}"]["events"], f
    o = ["% Table 1 of the 2026-09-13 draft: the three panels. GENERATED by",
         f"% analysis/paper/draft_2026_09_13_tables.py from {F_M} and {F_P3}; do not edit numbers by hand.",
         "\\begin{table}[tp]", "\\centering",
         "\\caption{" + R("Three panels") + "}",
         "\\label{tab:panels}", "\\footnotesize\\setlength{\\tabcolsep}{3pt}",
         "\\begin{tabular}{@{}l >{\\raggedright\\arraybackslash}p{3.0cm} >{\\raggedright\\arraybackslash}p{2.7cm} "
         ">{\\raggedright\\arraybackslash}p{2.0cm} r r r@{}}",
         "\\toprule",
         " & Unit of observation & Outcome & Treatment & \\multicolumn{3}{c}{" + R("Rows") + "} \\\\",
         "\\cmidrule(l){5-7}",
         " & & & & " + R("Econ.") + " & " + R("Chem.") + " & " + R("Math.") + " \\\\",
         "\\midrule",
         "Panel 1 & incumbent $\\times$ event $\\times$ year & FWCI-weighted output & similarity dose $\\times$ " + R("post-arrival") + " & "
         + " & ".join(R(big(rows[f][0])) for f in F) + f" \\\\ % src: {F_M} panel_rows.{{econ,chem,math}}[0]",
         "Panel 2 & incumbent $\\times$ star $\\times$ year & " + R("first paper with the star") + " & star arrival & "
         + " & ".join(R(big(rows[f][1])) for f in F) + f" \\\\ % src: {F_M} panel_rows.{{econ,chem,math}}[1]",
         "Panel 3 & pair $\\times$ event $\\times$ year, " + R("same-topic incumbents outside the star's network")
         + " & " + R("first tie between colleagues") + " & star arrival & "
         + " & ".join(R(big(T[f]["rows"])) for f in F) + f" \\\\ % src: {F_P3} {{econ,chemistry,math_stats}}.rows",
         "\\midrule",
         "\\multicolumn{4}{@{}l}{" + R("Star arrivals (events)") + "} & " + " & ".join(R(str(ev[f])) for f in F)
         + f" \\\\ % src: {F_M} {{econ,chem,math}}_events",
         "\\multicolumn{4}{@{}l}{" + R("Incumbents") + "} & " + " & ".join(R(big(inc[f])) for f in F)
         + f" \\\\ % src: {F_M} {{econ,chem,math}}_persons",
         "\\multicolumn{4}{@{}l}{" + R("Incumbent--event relations") + "} & " + " & ".join(R(big(rel[f])) for f in F)
         + f" \\\\ % src: {F_M} {{econ,chem,math}}_relations.total",
         "\\bottomrule", "\\end{tabular}",
         "\\par\\smallskip", "\\begin{minipage}{0.95\\textwidth}\\footnotesize"]
    notes = (
        # rewritten in plain words 2026-09-14, all \REV; keep digits out of it except "Panel(s) N",
        # or test_every_printed_number_is_accounted_for fails
        "\\emph{Notes}: "
        + R("FWCI (field-weighted citation impact) is a work's citations divided by the average for "
            "works of the same subfield, year and type. The similarity dose compares how the "
            "incumbent's and the star's pre-arrival publications spread across subfields: one means "
            "the same mix; zero means no shared subfield. In Panels 2 and 3 a pair leaves the sample "
            "after the year of its first joint paper. "
            + ("In this table a relation" if tree == BASE else "A relation")   # base tree: the author's 2026-10 edit
            + " is one incumbent--event pair; an "
            "incumbent exposed to two arrivals counts twice in relations and once in incumbents.")
    )
    o += [notes, "\\end{minipage}", "\\end{table}"]
    return "\n".join(o) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--tree", choices=TREES, default="thesis_report",
                    help="thesis_report (default; byte-identical to the pre-N10 output) or base_2026_10_11 "
                         "(the author's 2026-10-11 base tree: hand-edited labels, notes and comment blocks)")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--ledger-dir", type=Path, default=TR,
                     help="folder holding the dated ledgers data_numbers_<date>{,_p1p2,_p3afar,_robustness}.json "
                          "(default: legacy thesis_report/)")
    src.add_argument("--paper-dir", type=Path, default=None,
                     help="this run's output/paper: the undated data_numbers_{p1p2,p3afar,robustness,main,carried}.json "
                          "(run_all's staged 3light; R1)")
    a = ap.parse_args(argv)
    out = a.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    L, T, RB, M = load_paper(a.paper_dir.resolve()) if a.paper_dir is not None else load(a.ledger_dir.resolve())
    files = {"tab_main_results.tex": main_table(L, T, M, a.tree),
             "tab_robustness.tex": robustness_table(L, T, RB, a.tree),
             "tab_panels_overview.tex": panels_table(L, T, M, a.tree)}
    for name, text in files.items():
        (out / name).write_text(text)
    (out / "NOTE_CHECKS.json").write_text(json.dumps(NOTE_CHECKS, indent=1) + "\n")
    print("wrote " + ", ".join(files) + f" into {out}")
    for c in NOTE_CHECKS:
        print(("ok     " if c["holds"] else "FLAG   ") + c["table"] + ": " + c["claim"] + " — " + c["detail"])


if __name__ == "__main__":
    main()
