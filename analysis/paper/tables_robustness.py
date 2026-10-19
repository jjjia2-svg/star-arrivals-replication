#!/usr/bin/env python3
r"""tables_robustness.py — write the Section 4.2 robustness tables from the numbers ledgers.
Inputs: output/paper/data_numbers_robustness.json (analysis/paper/ledger_robustness.py)
        output/paper/data_numbers_p1p2.json       (main Panel 1/2 cells, routes, LOEO, permutation)
        output/paper/data_numbers_p3afar.json     (main Panel 3 cells, date shift, dose cuts,
                                                   no-effect simulation, permutation)
Output: output/paper/tab_robustness.tex  (compact summary, Section 4.2: one test per concern, by panel)
        output/paper/tab_rob_p1.tex      (Panel 1 detail, Appendix)
        output/paper/tab_rob_p2.tex      (Panel 2 detail, Appendix)
        output/paper/tab_rob_p3.tex      (Panel 3 detail, Appendix)
No number in any table is typed by hand. Every cell is wrapped in \REV{} (new material in this
version). Format and helpers mirror tables_p1p2.py. Notes carry technical definitions only; the
identifying idea of each test is in the text.

Written 2026-09-13 for the Section 4.2 exhibits; revised the same day after the independent
review (33 label/note/layout findings, no numeric mismatch in 1,733 comparisons): concern named in
every summary-table row; 'not yet exposed' (the variant's actual rule) instead of 'never exposed';
'incumbent's empty post-departure years'; shifted coefficients printed with their standard errors;
the Panel 1 appendix shows person-years (the sample-size column that reveals the not-yet-exposed
pool's collapse) and both the placebo and the post-arrival joint p; the Panel 3 appendix keeps one
meaning per column; permutation notes state the (k+1)/(B+1) rule and the one cell with 498
completed draws; departure coverage stated from the 25 hand verdicts; negative zero suppressed.
2026-09-23 (cal2026-10, October caliber): the ledgers now carry star-departure cells for all three
disciplines (the 187-event ledger, D6), so the departure rows fill every discipline; the D7 checks
(stars in the top 5 percent; dose in three bins) get rows in the appendix tables where the table
already has the matching population (Panel 1 both routes, Panel 2, Panel 3 A_far) — the all-pairs
Panel 3 D7 cells stay in the ledger only. A cell whose estimation failed prints "failed" and is
never filled in. No caption or note sentence is changed: the notes are the 2026-09-13 text with the
October numbers; where a note's wording no longer describes the October design (the departure
note, the dash note) a TeX comment above the table flags it.
R1 N10 (2026-10-16): --tree {thesis_report (default), base_2026_10_11}. The default writes exactly the
bytes it wrote before the switch existed. base_2026_10_11 is the base manuscript tree: in tab_rob_p1 the "Dose in three bins" row is replaced by
a hand-written 2026-10-04 comment line, verbatim, and the dose-in-three-bins cells (D7 dosebin3, cut in
the R1 rerun) are never read. Byte target: tests/fixtures/r1_paper/base_tree_2026-10-11/tables (not shipped).
The report canon has no star-departure cells. When departure_econ is absent, its departure rows
and note sentence are omitted and an M FLAG comment replaces the October diagnostics. October,
including an October copy in a canon tree, retains its original bytes; missing departure cells in
an October ledger stop the run.
Run:  python3 analysis/paper/tables_robustness.py [--tree {thesis_report,base_2026_10_11}]
"""
import argparse
import json, sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from analysis.lib.paths import load_paths
from analysis.lib import canon

BASE = "base_2026_10_11"
TREES = ("thesis_report", BASE)
_ap = argparse.ArgumentParser(description="write the Section 4.2 robustness tables from the numbers ledgers")
_ap.add_argument("--tree", choices=TREES, default="thesis_report",
                 help="thesis_report (default; the pre-N10 bytes) or base_2026_10_11 (the author's base tree)")
TREE = _ap.parse_args(sys.argv[1:] if __name__ == "__main__" else []).tree
# the author's line in the base tree's tab_rob_p1.tex, where the dose-in-three-bins row was (verbatim)
BASE_DOSE3_LINE = ("% 2026-10-04 author: row \"Dose in three bins\" deleted, because it only rescales the main "
                   "summary (dCDH yearly estimates use zero vs positive dose only); comment #26 met by the "
                   "deletion + Section 3 noise sentence; do not restore.")

P = load_paths()
ROOT = str(P["output"] / "paper")
R_ = json.load(open(f"{ROOT}/data_numbers_robustness.json"))
L = json.load(open(f"{ROOT}/data_numbers_p1p2.json"))
T = json.load(open(f"{ROOT}/data_numbers_p3afar.json"))
F = ["econ", "chemistry", "math_stats"]
DASH = "--"


def num(x, d=3):
    s = f"{x:.{d}f}"
    if s.lstrip("-").strip("0.") == "":   # a rounded zero prints as 0.000, never as -0.000
        s = s.lstrip("-")
    return s.replace("-", "$-$")


def big(n):
    return f"{n:,}".replace(",", "{,}")


FAILED = "failed"


def pval(p):
    if p is None:
        return FAILED
    return "$<$0.001" if p < 0.001 else f"{p:.3f}"


def est_se(e, s):
    return f"{num(e)} ({num(s)})"


def two(coefs):
    """Two shifted coefficients, each with its standard error."""
    return ", ".join(est_se(c["est"], c["se"]) for c in coefs)


def R(s):
    return "\\REV{" + s + "}"


# the two ledgers must agree on the Panel 3 date-shift joint p (same frozen file, two readers)
for f in F:
    assert T[f]["robustness"]["date_shift_two_years"]["p_joint_shifted"] == R_["p3_date_shift"][f]["p_joint_shifted"], f
    # the P3 ledger rounds to 4 dp and this one to 3: agree to within one unit of the 3rd decimal
    for a, e in zip(T[f]["robustness"]["date_shift_two_years"]["shifted_effects_pp"],
                    R_["p3_date_shift"][f]["shifted_effects_pp"]):
        assert abs(a - e["est"]) <= 0.0006, (f, a, e["est"])

HEADER3 = (" & " + R("Economics") + " & " + R("Chemistry")
           + " & \\multicolumn{1}{r}{\\shortstack[r]{" + R("Mathematics") + "\\\\ "
           + R("\\& Statistics") + "}} \\\\\n\\midrule")


def write_table(fname, caption, label, header, rows, notes, gen_comment, colspec, placement="tp", fit=False):
    """fit=True scales the tabular to the text width (the nine-column appendix tables)."""
    out = [gen_comment,
           "\\begin{table}[" + placement + "]\n\\centering",
           "\\caption{" + R(caption) + "}",
           "\\label{" + label + "}\n\\footnotesize\\setlength{\\tabcolsep}{3pt}",
           ("\\resizebox{\\textwidth}{!}{%\n" if fit else "") + "\\begin{tabular}{" + colspec + "}\n\\toprule",
           header]
    for lab, vals in rows:
        if lab == "MIDRULE":
            out.append("\\midrule"); continue
        if lab == "COMMENT":                 # a verbatim TeX comment line (base tree only)
            out.append(vals); continue
        if lab == "BLOCK":
            out.append("\\multicolumn{" + str(1 + len(vals[0])) + "}{@{}l}{" + R("\\emph{" + vals[1] + "}") + "} \\\\")
            continue
        out.append(R(lab) + " & " + " & ".join(R(v) for v in vals) + " \\\\")
    out += ["\\bottomrule\n\\end{tabular}" + ("}" if fit else ""),
            "\\par\\smallskip\n\\begin{minipage}{0.95\\textwidth}\\footnotesize",
            R(notes),
            "\\end{minipage}\n\\end{table}"]
    open(f"{ROOT}/{fname}", "w").write("\n".join(out) + "\n")


GEN = ("% analysis/paper/tables_robustness.py from data_numbers_2026-09-13_robustness.json, "
       "data_numbers_2026-08-30_p1p2.json and data_numbers_2026-08-28_p3afar.json "
       "\u2014 do not edit numbers by hand.")
# cal2026-10: a TeX comment (not typeset) for the author — the notes below keep their 2026-09-13
# sentences, and two of them no longer describe the October design.
GEN_FLAG = GEN + ("\n% cal2026-10 FLAG for the author: the star-departure note sentence describes the "
                  "2026-08-29 design (25 economics verdicts verified by hand; chemistry and mathematics "
                  "not screened). The October cells use the 187-event ledger for all three disciplines "
                  "(LLM-assisted verdicts, the author's review of 45 rows pending); the numbers printed "
                  "in that sentence are the October economics counts under the same keys "
                  "(data_numbers_robustness.json departure_econ.coverage). The dash note still lists "
                  "star departure outside economics, which is now estimated. A cell reading 'failed' is an "
                  "estimation that failed in the October run (recorded, never filled in).")
# R1 M: the M ledger has no departure cells (F20, author ruling 2026-10-15); October always has them.
# Without them the departure rows and the notes' departure sentence are left out; the author sentences
# that still name star departure stay word for word, and an M FLAG comment replaces the October ones.
HAS_DEP = "departure_econ" in R_
if canon.mode() == "october":
    assert HAS_DEP, "the October robustness ledger has no star-departure cells (departure_econ)"
M_FLAG = "\n% R1 M FLAG for the author: this ledger has no star-departure cells (author ruling 2026-10-15), "
M_FAILED = " A cell reading 'failed' is an estimation that failed in this run (recorded, never filled in)."
if not HAS_DEP:
    GEN_FLAG = GEN + M_FLAG + ("so the two star-departure rows and the notes' star-departure sentence are left "
                               "out. The dash note still lists star departure outside economics, which this "
                               "table no longer has." + M_FAILED)
GEN_FLAG_P3 = GEN_FLAG + ("" if HAS_DEP else " Here the block 'Treatment coding and roster' now holds the "
                          "roster row only.")

V = R_["p1_variants"]
PT = R_["p1_pretrend_by_channel"]
perm = L["perm_pvalues"]
D = R_["departure_econ"] if HAS_DEP else None
DF = {f: R_[f"departure_{f}"] for f in F} if HAS_DEP else {}   # cal2026-10: departure cells for all three disciplines
NC = R_["no_centre_roster"]
D7 = R_["d7"]
cov = D["coverage"] if HAS_DEP else None
lo = L["p1_loeo_econ"]

# permutation bookkeeping: every P1/P2 cell's completed draws, so the notes can say exactly
# how many reassignments each p rests on (the mathematics Panel 2 cell completed 498 of 500)
B_req = perm["B"]
b_ok = {f"p{k}_{f}": perm[f"p{k}_{f}"]["B_ok"] for k in (1, 2) for f in F}
b_short = {k: v for k, v in b_ok.items() if v != B_req}
assert B_req == 500 and all(v <= B_req for v in b_ok.values()), b_ok
assert all(T[f]["randomization_inference"]["permutations"] == 500 for f in F)
NAME = {"p1_econ": "Panel 1 economics", "p1_chemistry": "Panel 1 chemistry", "p1_math_stats": "Panel 1 mathematics",
        "p2_econ": "Panel 2 economics", "p2_chemistry": "Panel 2 chemistry", "p2_math_stats": "Panel 2 mathematics"}
short_txt = ("" if not b_short else " (" + "; ".join(f"{NAME[k]}: {v} completed draws" for k, v in b_short.items()) + ")")
PERM_DEF = ("The permutation rows reassign the observed arrival years across events " + str(B_req)
            + " times, everything else fixed, and report $(k+1)/(B+1)$, where $k$ is the number of "
            "reassignments giving an estimate at least as large in absolute value as the reported one "
            "and $B$ the number of completed reassignments" + short_txt + ".")
nsim = {T[f]["null_simulation"]["nsim"] for f in F}; assert len(nsim) == 1; NSIM = nsim.pop()
SIM_DEF = ("The simulation row is the mean estimate over " + str(NSIM) + " panels in which the yearly chance "
           "of a first tie depends only on how many years the pair has been in the panel and on the calendar "
           "year, at rates fitted to the real panel. Every pair enters six years before its star arrives, so "
           "years in the panel move with years since the arrival and the fitted rates carry whatever change "
           "the arrivals brought; the simulated panels are not panels without an arrival effect.")
NEX_DEF = ("The not-yet-exposed pool keeps, for comparison, only person-years before an incumbent's "
           "first exposure to any arrival; it has no joint tests.")
LEAVE_DEF = ("Empty post-departure years are the years after an incumbent leaves the roster in which "
             "they published nothing; the main sample leaves them empty and this row fills them with zeros.")
DEP_DEF = ("The star-departure rows use the " + str(cov["verified_verdicts"]) + " economics stars whose "
           "departure status was verified by hand (" + str(cov["departed_verdicts"]) + " left, "
           + str(cov["rule_A_events_dropped"]) + " of them within the window, so rule A drops "
           + str(cov["rule_A_events_dropped"]) + " events and rule B recodes " + str(cov["rule_B_events_recoded"])
           + "); the other " + str(cov["econ_events_without_hand_verdict"]) + " economics events are treated as "
           "not known to have left, and chemistry and mathematics were not screened.") if HAS_DEP else None
DEP_SENT = DEP_DEF + " " if HAS_DEP else ""   # the sentence and its space, or nothing (R1 M)
DASH_DEF = ("A dash marks a test not run for that discipline (star departure outside economics, the "
            "research-centre roster in economics), a test the design does not provide (joint tests in the "
            "not-yet-exposed pool), or a cell the row does not have.")

# ===========================================================================
# Main text: one test per concern, by panel
# ===========================================================================
SHIFT = "Selective hiring and anticipation: arrivals moved two years earlier, joint $p$ of the two pre-arrival horizons"
PERM = "Estimator: arrival years shuffled across events, permutation $p$"
rows = [
    ("BLOCK", (F, "Panel 1: output, log points per unit of dose (standard error)")),
    ("Main specification", [est_se(L[f"p1_{f}"]["ate_log"], L[f"p1_{f}"]["se_person"]) for f in F]),
    (SHIFT, [pval(R_["p1_date_shift"][f]["p_joint_shifted"]) for f in F]),
    (PERM, [pval(perm[f"p1_{f}"]["p_perm_abs_ate"]) for f in F]),
    ("Exposure boundary: comparison pool limited to not-yet-exposed relations",
     [est_se(V[f]["never_exposed_pool"]["ate_log"], V[f]["never_exposed_pool"]["se_person"]) for f in F]),
    ("Measurement: missing output set to zero",
     [est_se(V[f]["missing_as_zero"]["ate_log"], V[f]["missing_as_zero"]["se_person"]) for f in F]),
    ("Measurement: missing output set to the incumbent's own mean",
     [est_se(V[f]["missing_as_own_mean"]["ate_log"], V[f]["missing_as_own_mean"]["se_person"]) for f in F]),
    ("Treatment coding: incumbent's empty post-departure years set to zero",
     [est_se(V[f]["post_departure_zeros"]["ate_log"], V[f]["post_departure_zeros"]["se_person"]) for f in F]),
    ("MIDRULE", None),
    ("BLOCK", (F, "Panel 2: first coauthorship with the star, percentage points per year (standard error)")),
    ("Main specification", [est_se(L[f"p2_{f}"]["ate_pp"], L[f"p2_{f}"]["se_person_pp"]) for f in F]),
    (SHIFT, [pval(R_["p2_date_shift"][f]["p_joint_shifted"]) for f in F]),
    (PERM, [pval(perm[f"p2_{f}"]["p_perm_abs_ate"]) for f in F]),
    ("MIDRULE", None),
    ("BLOCK", (F, "Panel 3: first ties among same-topic incumbents outside the network, percentage points per year (standard error)")),
    ("Main specification", [est_se(T[f]["ate_pp"], T[f]["se_pair_pp"]) for f in F]),
    (SHIFT, [pval(R_["p3_date_shift"][f]["p_joint_shifted"]) for f in F]),
    (PERM, [pval(T[f]["randomization_inference"]["p_two_sided"]) for f in F]),
    ("Estimator: mean estimate in panels simulated from pair-age and calendar-year rates",
     [num(T[f]["null_simulation"]["dcdh_ate_pp_no_effect_world"]) for f in F]),
    ("Exposure boundary: both incumbents at or above the median positive dose",
     [est_se(T[f]["robustness"]["former_main_cut"]["ate_pp"], T[f]["robustness"]["former_main_cut"]["se_pair_pp"]) for f in F]),
]
notes = (
    "\\emph{Notes}: Each row names the concern of Section~\\ref{sec:identify} it tests. Cells are the "
    "estimator of Section~\\ref{sec:baseline} on the sample named in the row: the average post-arrival "
    "effect in the panel's unit, with the standard error in parentheses clustered by incumbent (Panels 1 "
    "and 2) or by pair (Panel 3), or a $p$-value. Panel 1 rows pool both routes into the exposure "
    "population. The date-shift rows move every arrival two years earlier and report the joint test that "
    "the first two coefficients of the shifted run, which fall on years before the star arrived, are zero. "
    + PERM_DEF + " " + SIM_DEF + " " + NEX_DEF + " The missing-output rows fill every person-year with no "
    "output value as zero, or as the incumbent's own mean over observed years. " + LEAVE_DEF
    + " The median-dose row keeps pairs in which both incumbents are at or above the discipline's median "
    "positive dose. The star-departure tests (economics only) and the remaining checks are in Appendix "
    "Tables~\\ref{tab:rob_p1}--\\ref{tab:rob_p3}, which report every check with sample sizes."
)
GEN_FLAG_SUMMARY = GEN + ("\n% cal2026-10 FLAG for the author: the notes' closing sentence says the "
                          "star-departure tests are economics only; the October ledger estimates them for all "
                          "three disciplines (Appendix tables). A cell reading 'failed' is an estimation that "
                          "failed in the October run (Panel 2 mathematics date shift: the auxiliary joint-test "
                          "run), recorded and never filled in.")
if not HAS_DEP:
    GEN_FLAG_SUMMARY = GEN + M_FLAG + ("but the notes' closing sentence still says the star-departure tests "
                                       "(economics only) are in the Appendix tables, which no longer print "
                                       "them." + M_FAILED)
write_table("tab_robustness.tex", "Robustness checks: one test per concern, by panel", "tab:robustness",
            HEADER3, rows, notes, GEN_FLAG_SUMMARY, "@{}p{0.55\\textwidth} r r r@{}")

# ===========================================================================
# Appendix: Panel 1 detail (estimate (SE) | placebo p / joint p | person-years, per discipline)
# ===========================================================================
def hdr9(c1, c2, c3):
    return (" & \\multicolumn{3}{c}{" + R("Economics") + "} & \\multicolumn{3}{c}{" + R("Chemistry")
            + "} & \\multicolumn{3}{c}{" + R("Mathematics \\& Statistics") + "} \\\\\n"
            "\\cmidrule(lr){2-4}\\cmidrule(lr){5-7}\\cmidrule(lr){8-10}\n"
            " & " + " & ".join([R(c1), R(c2), R(c3)] * 3) + " \\\\\n\\midrule")


def pp_(p):
    return pval(p) if p is not None else DASH


def cell3(est_txt, p_txt, n):
    return [est_txt, p_txt, big(n) if n is not None else DASH]


def p1row(label, cells):
    """cells: per field, (est, se, placebo_p, joint_p, obs); est None -> dashes."""
    vals = []
    for e, s, pl, pj, n in cells:
        if e is None:
            vals += [DASH, DASH, DASH]
        else:
            vals += cell3(est_se(e, s), f"{pp_(pl)} / {pp_(pj)}", n)
    return (label, vals)


def var(f, key):
    c = V[f][key]
    return (c["ate_log"], c["se_person"], c["p_joint_placebo"], c["p_joint_effects"], c["obs"])


rows1 = [
    p1row("Main specification (both routes)",
          [(L[f"p1_{f}"]["ate_log"], L[f"p1_{f}"]["se_person"], L[f"p1_{f}"]["p_joint_placebo_person"],
            L[f"p1_{f}"]["p_joint_effects_person"], L[f"p1_{f}"]["obs"]) for f in F]),
    p1row("Reached through the roster",
          [(L[f"p1_{f}"]["by_route"]["roster"]["ate_log"], L[f"p1_{f}"]["by_route"]["roster"]["se_person"],
            PT[f]["dept"]["p_joint_placebo_person"], PT[f]["dept"]["p_joint_effects_person"], PT[f]["dept"]["obs"]) for f in F]),
    p1row("Reached through the network",
          [(L[f"p1_{f}"]["by_route"]["network"]["ate_log"], L[f"p1_{f}"]["by_route"]["network"]["se_person"],
            PT[f]["network"]["p_joint_placebo_person"], PT[f]["network"]["p_joint_effects_person"], PT[f]["network"]["obs"]) for f in F]),
    ("MIDRULE", None),
    ("BLOCK", (range(9), "Arrivals moved two years earlier: the two shifted pre-arrival coefficients (standard errors), joint $p$")),
]
for ch, lab in (("union", "Both routes"), ("dept", "Roster"), ("network", "Network")):
    vals = []
    for f in F:
        c = PT[f][ch]
        vals += cell3(two(c["shifted_effects_log"]), f"{pval(c['p_joint_shifted'])} / {DASH}", c["obs"])
    rows1.append((lab, vals))
rows1 += [("MIDRULE", None), ("BLOCK", (range(9), "Alternative samples and outcomes (both routes)"))]
for key, lab in (("never_exposed_pool", "Comparison pool limited to not-yet-exposed relations"),
                 ("missing_as_zero", "Missing output set to zero"),
                 ("missing_as_own_mean", "Missing output set to the incumbent's own mean"),
                 ("post_departure_zeros", "Incumbent's empty post-departure years set to zero"),
                 ("levels", "Output in levels (own units, not comparable to the log rows)")):
    rows1.append(p1row(lab, [var(f, key) for f in F]))
rows1.append(p1row("Stars in the top 5 percent only",
                   [(D7["top5"][f]["p1"]["ate_log"], D7["top5"][f]["p1"]["se_person"], D7["top5"][f]["p1"]["p_joint_placebo"],
                     D7["top5"][f]["p1"]["p_joint_effects"], D7["top5"][f]["p1"]["obs"]) for f in F]))
if TREE == BASE:   # the author deleted the row on 2026-10-04; the cells are not read
    rows1.append(("COMMENT", BASE_DOSE3_LINE))
else:
    rows1.append(p1row("Dose in three bins of equal size (per bin, not per unit of dose)",
                       [(D7["dosebin3"][f]["p1"]["ate_log"], D7["dosebin3"][f]["p1"]["se_person"],
                         D7["dosebin3"][f]["p1"]["p_joint_placebo"], D7["dosebin3"][f]["p1"]["p_joint_effects"],
                         D7["dosebin3"][f]["p1"]["obs"]) for f in F]))
for rule, lab in (("A", "Star departure, rule A: events whose star left within the window dropped"),
                  ("B", "Star departure, rule B: treatment switched off from the departure year")) if HAS_DEP else ():
    rows1.append(p1row(lab, [(DF[f]["p1"][rule]["ate_log"], DF[f]["p1"][rule]["se_person"],
                              DF[f]["p1"][rule]["p_joint_placebo"], DF[f]["p1"][rule]["p_joint_effects"],
                              DF[f]["p1"][rule]["obs"]) for f in F]))
rows1.append(p1row("Research-centre staff removed from the roster",
                   [(None,) * 5] + [(NC[f]["p1"]["ate_log"], NC[f]["p1"]["se_person"], NC[f]["p1"]["p_joint_placebo"],
                                     NC[f]["p1"]["p_joint_effects"], NC[f]["p1"]["obs"]) for f in ("chemistry", "math_stats")]))
rows1.append(("Leave one event out (" + str(lo["n_removals"]) + " re-estimations): range of estimates, largest placebo $p$",
              [f"{num(lo['ate_min'])} to {num(lo['ate_max'])}", f"{pval(lo['p_joint_placebo_max'])} / {DASH}", DASH] + [DASH] * 6))
rows1.append(("Arrival years shuffled across events: permutation $p$",
              sum([[DASH, f"{DASH} / {pval(perm[f'p1_{f}']['p_perm_abs_ate'])}", DASH] for f in F], [])))
notes1 = (
    "\\emph{Notes}: Estimates are average post-arrival effects per unit of dose in log points, "
    "standard errors clustered by incumbent; the levels row is in the outcome's own units "
    "(FWCI-weighted output per year) and is not comparable in size to the log rows. The $p$ column "
    "gives the joint test that the four pre-arrival placebo coefficients are zero, then the joint test "
    "that the post-arrival coefficients are zero; in the date-shift rows it gives the joint test of the "
    "two shifted coefficients, in the leave-one-out row the largest placebo $p$ over the re-estimations, "
    "and in the permutation row the permutation $p$. Person-years are the estimation sample. The roster "
    "and network rows estimate on the incumbents reached through that route; an incumbent reached both "
    "ways belongs to each. Shifted coefficients are the first two horizons of a run in which every "
    "arrival is moved two years earlier, so they fall on years before the star arrived. " + NEX_DEF
    + " Missing output is filled in either as zero or as the incumbent's own mean over observed years. "
    + LEAVE_DEF + " " + DEP_SENT + "Economics has no research-centre roster. " + PERM_DEF + " " + DASH_DEF
)
write_table("tab_rob_p1.tex", "Panel 1 robustness checks in full", "tab:rob_p1",
            hdr9("Estimate (SE)", "Placebo $p$ / joint $p$", "Person-years"), rows1, notes1, GEN_FLAG,
            "@{}p{0.34\\textwidth} r r r r r r r r r@{}", fit=True)

# ===========================================================================
# Appendix: Panel 2 detail (estimate (SE) | joint p | relation-years)
# ===========================================================================
P2S = R_["p2_date_shift"]


def p2c(c):
    """A Panel 2 cell (estimate (SE) | joint p | relation-years); a FAILED run prints 'failed'."""
    if c.get("status", "OK") != "OK":
        return [FAILED, DASH, big(c["rows"])]
    return cell3(est_se(c["ate_pp"], c["se_person_pp"]), pval(c["p_joint_effects"]), c["rows"])


def p2shift(c):
    if c.get("status", "OK") != "OK":      # the auxiliary joint-test run failed (October: mathematics)
        return [FAILED, FAILED, big(c["rows"])]
    return cell3(two(c["shifted_effects_pp"]), pval(c["p_joint_shifted"]), c["rows"])


rows2 = [
    ("Main specification", sum([cell3(est_se(L[f"p2_{f}"]["ate_pp"], L[f"p2_{f}"]["se_person_pp"]),
                                      pval(L[f"p2_{f}"]["p_joint_effects_person"]), L[f"p2_{f}"]["rows"]) for f in F], [])),
    ("Arrivals moved two years earlier: the two shifted coefficients (standard errors), joint $p$",
     sum([p2shift(P2S[f]) for f in F], [])),
    ("Arrival years shuffled across events: permutation $p$",
     sum([[DASH, pval(perm[f"p2_{f}"]["p_perm_abs_ate"]), DASH] for f in F], [])),
    ("Stars in the top 5 percent only", sum([p2c(D7["top5"][f]["p2"]) for f in F], [])),
] + ([
    ("Star departure, rule A: events whose star left within the window dropped",
     sum([p2c(DF[f]["p2"]["A"]) for f in F], [])),
    ("Star departure, rule B: treatment switched off from the departure year",
     sum([p2c(DF[f]["p2"]["B"]) for f in F], [])),
] if HAS_DEP else []) + [
    ("Research-centre staff removed from the roster",
     [DASH] * 3 + sum([cell3(est_se(NC[f]["p2"]["ate_pp"], NC[f]["p2"]["se_person_pp"]), pval(NC[f]["p2"]["p_joint_effects"]), NC[f]["p2"]["rows"])
                       for f in ("chemistry", "math_stats")], [])),
]
notes2 = (
    "\\emph{Notes}: Estimates are average post-arrival effects on the yearly probability of a first "
    "coauthorship with the star, in percentage points, standard errors clustered by incumbent. The $p$ "
    "column is the joint test that the post-arrival coefficients are zero, except in the date-shift row, "
    "where it tests the two shifted pre-arrival coefficients, and the permutation row. Relation-years "
    "are the estimation sample. The estimator's own placebo is zero by construction in this panel "
    "(Section~\\ref{sec:baseline}). " + PERM_DEF + " " + DEP_SENT + "Economics has no research-centre "
    "roster. " + DASH_DEF
)
write_table("tab_rob_p2.tex", "Panel 2 robustness checks in full", "tab:rob_p2",
            hdr9("Estimate (SE)", "Joint $p$", "Relation-years"), rows2, notes2, GEN_FLAG,
            "@{}p{0.34\\textwidth} r r r r r r r r r@{}", fit=True)

# ===========================================================================
# Appendix: Panel 3 detail (estimate (SE) | joint p | pairs) — one meaning per column
# ===========================================================================
P3S = R_["p3_date_shift"]
rows3 = [
    ("Main specification: both incumbents share at least one subfield with the star",
     sum([cell3(est_se(T[f]["ate_pp"], T[f]["se_pair_pp"]), pval(T[f]["p_joint_effects_pair"]), T[f]["pairs"]) for f in F], [])),
    ("\\quad standard error and joint $p$ clustered by event",
     sum([[f"({num(T[f]['se_event_pp'])})", pval(T[f]["p_joint_effects_event"]), DASH] for f in F], [])),
    ("Arrivals moved two years earlier: the two shifted coefficients (standard errors), joint $p$",
     sum([cell3(two(P3S[f]["shifted_effects_pp"]), pval(P3S[f]["p_joint_shifted"]), P3S[f]["pairs"]) for f in F], [])),
    ("Arrival years shuffled across events: permutation $p$",
     sum([[DASH, pval(T[f]["randomization_inference"]["p_two_sided"]), DASH] for f in F], [])),
    ("Mean estimate in panels simulated from pair-age and calendar-year rates",
     sum([[num(T[f]["null_simulation"]["dcdh_ate_pp_no_effect_world"]), DASH, DASH] for f in F], [])),
    ("Stars in the top 5 percent only",
     sum([cell3(est_se(D7["top5"][f]["p3_pos"]["ate_pp"], D7["top5"][f]["p3_pos"]["se_pair_pp"]),
                pval(D7["top5"][f]["p3_pos"]["p_joint_effects_pair"]), D7["top5"][f]["p3_pos"]["pairs"]) for f in F], [])),
    ("MIDRULE", None), ("BLOCK", (range(9), "Topic condition drawn more tightly (both incumbents)")),
]
CUTLAB = {"med": "At or above the discipline's median positive dose", "abs04": "Dose of at least 0.4",
          "p75": "In the top quarter of the discipline's positive doses"}
CUT = R_["p3_cut_grid"]
for f in F:  # the two ledgers read the same frozen cut files; they must agree on every estimate
    for g in T[f]["robustness"]["cut_grid"]:
        c = CUT[f][g["cut_spec"]]
        assert abs(round(g["ate_pp"], 3) - c["ate_pp"]) <= 0.0006 and c["pairs"] == g["pairs"], (f, g["cut_spec"])
for spec in ("med", "abs04", "p75"):
    vals = []
    for f in F:
        c = CUT[f][spec]
        vals += cell3(est_se(c["ate_pp"], c["se_pair_pp"]), pval(c["p_joint_effects_pair"]), c["pairs"])
    rows3.append((CUTLAB[spec], vals))
rows3 += [("MIDRULE", None), ("BLOCK", (range(9), "Treatment coding and roster"))]
for rule, lab in (("A", "Star departure, rule A: events whose star left within the window dropped"),
                  ("B", "Star departure, rule B: treatment switched off from the departure year")) if HAS_DEP else ():
    rows3.append((lab, sum([cell3(est_se(DF[f]["p3_pos"][rule]["ate_pp"], DF[f]["p3_pos"][rule]["se_pair_pp"]),
                                  pval(DF[f]["p3_pos"][rule]["p_joint_effects_pair"]), DF[f]["p3_pos"][rule]["pairs"])
                            for f in F], [])))
rows3.append(("Research-centre staff removed from the roster",
              [DASH] * 3 + sum([cell3(est_se(NC[f]["p3_pos"]["ate_pp"], NC[f]["p3_pos"]["se_pair_pp"]), pval(NC[f]["p3_pos"]["p_joint_effects_pair"]), NC[f]["p3_pos"]["pairs"])
                                for f in ("chemistry", "math_stats")], [])))
notes3 = (
    "\\emph{Notes}: Estimates are average post-arrival effects on the yearly probability that two "
    "incumbents first publish together, in percentage points, standard errors clustered by pair except "
    "in the row that says event. The $p$ column is the joint test that the post-arrival coefficients are "
    "zero, except in the date-shift row, where it tests the two shifted pre-arrival coefficients, and the "
    "permutation row. Pairs are the estimation sample; the number of events contributing pairs is in "
    "Table~\\ref{tab:p3afar}. " + PERM_DEF + " " + SIM_DEF + " The dose cuts are applied to both incumbents "
    "of a pair, and the median and the top quarter are defined within the discipline. " + DEP_SENT
    + "Economics has no research-centre roster. " + DASH_DEF
)
write_table("tab_rob_p3.tex", "Panel 3 robustness checks in full", "tab:rob_p3",
            hdr9("Estimate (SE)", "Joint $p$", "Pairs"), rows3, notes3, GEN_FLAG_P3,
            "@{}p{0.34\\textwidth} r r r r r r r r r@{}", fit=True)
print("wrote tab_robustness.tex, tab_rob_p1.tex, tab_rob_p2.tex, tab_rob_p3.tex")
