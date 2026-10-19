#!/usr/bin/env python3
r"""tables_p1p2.py — write the four Panel 1 / Panel 2 LaTeX tables from the numbers ledger.
Input : output/paper/data_numbers_p1p2.json (made by analysis/paper/ledger_p1p2.py)
Output: output/paper/tab_p1_main.tex   (compact, Section 4.1)
        output/paper/tab_p1_full.tex   (every horizon incl. the REAL placebos, Appendix)
        output/paper/tab_p2_main.tex   (compact, with the raw first-tie-rate rows)
        output/paper/tab_p2_full.tex   (every horizon, Appendix)
No number in any table is typed by hand. Every cell is wrapped in \REV{} (new material in this
version). Format and helpers mirror tables_p3afar.py (the house pattern); notes follow the
author's spec — variable definitions, size, significance and clustering conventions stated,
quoting Section 2/3's own variable descriptions.

Written 2026-08-30 for the Panel 1 + Panel 2 exhibits.
Run:  python3 analysis/paper/tables_p1p2.py
"""
import json, sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from analysis.lib.paths import load_paths

P = load_paths()
ROOT = str(P["output"] / "paper")
L = json.load(open(f"{ROOT}/data_numbers_p1p2.json"))
F = [("econ", "Economics"), ("chemistry", "Chemistry"), ("math_stats", "Mathematics \\& Statistics")]
CAP = L["year_cap"]

def num(x, d=3):
    return f"{x:.{d}f}".replace("-", "$-$")
def big(n): return f"{n:,}".replace(",", "{,}")
def pval(p): return "$<$0.001" if p < 0.001 else f"{p:.3f}"
def R(s): return "\\REV{" + s + "}"

HEADER = (" & " + R("Economics") + " & " + R("Chemistry")
          + " & \\multicolumn{1}{r}{\\shortstack[r]{" + R("Mathematics") + "\\\\ "
          + R("\\& Statistics") + "}} \\\\\n\\midrule")

def write_table(fname, caption, label, rows, notes, gen_comment, colspec="@{}l r r r@{}"):
    out = []
    out.append(gen_comment[0])
    out.append(gen_comment[1])
    out.append("\\begin{table}[ht]\n\\centering")
    out.append("\\caption{" + R(caption) + "}")
    out.append("\\label{" + label + "}\n\\footnotesize\\setlength{\\tabcolsep}{3pt}")
    out.append("\\begin{tabular}{" + colspec + "}\n\\toprule")
    out.append(HEADER)
    for lab, vals in rows:
        if lab == "MIDRULE":
            out.append("\\midrule"); continue
        out.append(R(lab) + " & " + " & ".join(R(v) for v in vals) + " \\\\")
    out.append("\\bottomrule\n\\end{tabular}")
    out.append("\\par\\smallskip\n\\begin{minipage}{0.95\\textwidth}\\footnotesize")
    out.append(R(notes))
    out.append("\\end{minipage}\n\\end{table}")
    open(f"{ROOT}/{fname}", "w").write("\n".join(out) + "\n")

GEN = ["% analysis/paper/tables_p1p2.py from data_numbers_2026-08-30_p1p2.json — do not edit numbers by hand."]

# ---------------------------------------------------------------------------
# Panel 1, compact
# ---------------------------------------------------------------------------
rows = [
    ("Average effect per unit of dose (log points)", [num(L[f"p1_{f}"]["ate_log"]) for f, _ in F]),
    ("\\quad s.e., incumbent clusters", [f"({num(L[f'p1_{f}']['se_person'])})" for f, _ in F]),
    ("\\quad s.e., event clusters", [f"({num(L[f'p1_{f}']['se_event'])})" for f, _ in F]),
    ("95\\% CI, incumbent clusters",
     [f"[{num(L[f'p1_{f}']['ci95_person'][0])}, {num(L[f'p1_{f}']['ci95_person'][1])}]" for f, _ in F]),
    ("Percent change per unit of dose, $100(e^{b}-1)$", [num(L[f"p1_{f}"]["ate_pct"], 1) for f, _ in F]),
    ("Joint test ($p$), post-arrival coefficients", [pval(L[f"p1_{f}"]["p_joint_effects_person"]) for f, _ in F]),
    ("\\quad event clusters", [pval(L[f"p1_{f}"]["p_joint_effects_event"]) for f, _ in F]),
    ("Joint test ($p$), placebo coefficients", [pval(L[f"p1_{f}"]["p_joint_placebo_person"]) for f, _ in F]),
    ("\\quad event clusters", [pval(L[f"p1_{f}"]["p_joint_placebo_event"]) for f, _ in F]),
    ("MIDRULE", None),
    ("Incumbent--event relations", [big(L[f"p1_{f}"]["relations"]) for f, _ in F]),
    ("\\quad with positive dose", [big(L[f"p1_{f}"]["relations_with_dose"]) for f, _ in F]),
    ("Switching relations at $\\ell=0$", [big(L[f"p1_{f}"]["switchers_ell0"]) for f, _ in F]),
    ("Incumbents", [big(L[f"p1_{f}"]["persons"]) for f, _ in F]),
    ("Events", [str(L[f"p1_{f}"]["events"]) for f, _ in F]),
    ("Incumbent--event--years", [big(L[f"p1_{f}"]["obs"]) for f, _ in F]),
]
notes = ("\\emph{Notes}: Each column is one estimation of equation~\\eqref{eq:p1} with the estimator of "
         "Section~\\ref{sec:baseline}, on the full exposure population (the department roster in the arrival "
         "year together with the star's two-hop pre-arrival coauthorship network); relations with an "
         "academic-age gap to the star above 60 years are excluded. The outcome is the log of one plus the "
         "incumbent's yearly output: the sum over the incumbent's journal articles and reviews of each "
         "work's FWCI, weighted by the incumbent's share of authorship. The treatment is the similarity "
         "dose --- the cosine similarity between the incumbent's and the star's subfield publication "
         "portfolios, frozen one year before arrival --- interacted with the post-arrival years; relations "
         "with a dose of exactly zero are the untreated comparison in every year. The average effect is the "
         "switcher-weighted sum of the post-arrival changes divided by the switcher-weighted sum of doses: "
         "the average post-arrival effect per unit of dose, in log points; the percent row converts it as "
         "$100(e^{b}-1)$. The joint tests are of the six post-arrival coefficients and of the four "
         "pre-arrival placebo coefficients (two to five years before arrival); in Panels 2 and 3 these are "
         "zero by construction, while this panel estimates them from the data, and Table~\\ref{tab:p1_full} reports them. Standard errors "
         "are in parentheses, clustered by incumbent (the main convention of Section~\\ref{sec:baseline}) "
         f"and by event; with {L['p1_chemistry']['events']} and {L['p1_math_stats']['events']} events the "
         "event clusters in chemistry and mathematics are few, and few-cluster standard errors tend to be "
         "too small (Section~\\ref{sec:baseline}). Switching relations at $\\ell=0$ is the number of "
         "positive-dose relations entering the arrival-year comparison. Horizon-by-horizon estimates are in "
         "Table~\\ref{tab:p1_full}.")
write_table("tab_p1_main.tex", "Research output after a star's arrival (Panel 1)", "tab:p1_main",
            rows, notes,
            ["% Table: Panel 1 (research output), compact. GENERATED by"] + GEN)

# ---------------------------------------------------------------------------
# Panel 1, every horizon (placebos included — they are real in this panel)
# ---------------------------------------------------------------------------
o = []
o.append("% Table: Panel 1 (research output), every horizon incl. placebos. GENERATED by")
o.append(GEN[0])
o.append("\\begin{table}[ht]\n\\centering")
o.append("\\caption{" + R("Panel 1 horizon by horizon (research output)") + "}")
o.append("\\label{tab:p1_full}\n\\small")
o.append("\\begin{tabular}{@{}l r r r r r@{}}\n\\toprule")
o.append(" & ".join(R(h) for h in ["Years since arrival $\\ell$", "Estimate (log points)", "s.e., incumbent",
                                   "s.e., event", "Observations", "Switchers"]) + " \\\\")
for f, name in F:
    c = L[f"p1_{f}"]
    o.append("\\midrule")
    o.append("\\multicolumn{6}{@{}l}{" + R(f"\\emph{{{name}}}: {big(c['relations'])} relations, "
             f"{big(c['relations_with_dose'])} with positive dose, {c['events']} events") + "} \\\\")
    for h in sorted(c["placebos"], key=lambda x: x["ell"]) + c["horizons"]:
        o.append(" & ".join(R(v) for v in [str(h["ell"]), num(h["est"]), f"({num(h['se_person'])})",
                                           f"({num(h['se_event'])})", big(h["n"]), big(h["switchers"])]) + " \\\\")
    o.append(" & ".join(R(v) for v in ["Average (switcher-weighted)", num(c["weighted_avg_effect"]),
                                       "", "", "", big(c["switchers_total"])]) + " \\\\")
    o.append(" & ".join(R(v) for v in ["Per unit of dose", num(c["ate_log"]),
                                       f"({num(c['se_person'])})", f"({num(c['se_event'])})", "", ""]) + " \\\\")
o.append("\\bottomrule\n\\end{tabular}")
o.append("\\par\\smallskip\n\\begin{minipage}{0.95\\textwidth}\\footnotesize")
avg_doses = ", ".join(f"{L[f'p1_{f}']['avg_dose_switchers']:.3f}" for f, _ in F)
o.append(R("\\emph{Notes}: Per-horizon rows are the estimator's event-study coefficients: the average "
           "change in log output among switching relations at their own dose, relative to the year before "
           "arrival ($\\ell=-1$, normalized to zero); $\\ell=0$ is the arrival year, and the rows with "
           "$\\ell\\le-2$ are the pre-arrival placebo coefficients, which this panel estimates from the data "
           "(in Panels 2 and 3 they are zero by construction). Observations is the number of incumbent--event--years entering the comparison "
           "at that horizon, and switchers the number of positive-dose relations entering it (relations "
           "whose event has a not-yet-treated comparison at that horizon); later horizons rest on earlier "
           "cohorts. The average row is the switcher-weighted mean of the six post-arrival coefficients, in "
           "the same units as the per-horizon rows; the per-unit-of-dose row is the summary of "
           "Table~\\ref{tab:p1_main}, which divides by the switchers' average dose "
           f"({avg_doses} in the three disciplines). Standard errors clustered by incumbent and by event. "
           "Sample definition as in Table~\\ref{tab:p1_main}."))
o.append("\\end{minipage}\n\\end{table}")
open(f"{ROOT}/tab_p1_full.tex", "w").write("\n".join(o) + "\n")

# ---------------------------------------------------------------------------
# Panel 2, compact
# ---------------------------------------------------------------------------
rows = [
    ("Average post-arrival effect (pp per year)", [num(L[f"p2_{f}"]["ate_pp"]) for f, _ in F]),
    ("\\quad s.e., incumbent clusters", [f"({num(L[f'p2_{f}']['se_person_pp'])})" for f, _ in F]),
    ("\\quad s.e., event clusters", [f"({num(L[f'p2_{f}']['se_event_pp'])})" for f, _ in F]),
    ("95\\% CI, incumbent clusters",
     [f"[{num(L[f'p2_{f}']['ci95_person_pp'][0])}, {num(L[f'p2_{f}']['ci95_person_pp'][1])}]" for f, _ in F]),
    ("Joint test ($p$), post-arrival coefficients", [pval(L[f"p2_{f}"]["p_joint_effects_person"]) for f, _ in F]),
    ("\\quad event clusters", [pval(L[f"p2_{f}"]["p_joint_effects_event"]) for f, _ in F]),
    ("MIDRULE", None),
    ("Raw rate before arrival (\\% per year)", [num(L[f"p2_{f}"]["rate_pre_pp"]) for f, _ in F]),
    (f"Raw rate after arrival, to {CAP} (\\% per year)", [num(L[f"p2_{f}"]["rate_post_obs_pp"]) for f, _ in F]),
    ("MIDRULE", None),
    ("Incumbent--star relations", [big(L[f"p2_{f}"]["relations"]) for f, _ in F]),
    ("First ties", [big(L[f"p2_{f}"]["first_ties"]) for f, _ in F]),
    ("Switching relations at $\\ell=0$", [big(L[f"p2_{f}"]["switchers_ell0"]) for f, _ in F]),
    ("Incumbents", [big(L[f"p2_{f}"]["persons"]) for f, _ in F]),
    ("Events", [str(L[f"p2_{f}"]["events"]) for f, _ in F]),
    ("Relation--years", [big(L[f"p2_{f}"]["rows"]) for f, _ in F]),
]
notes = ("\\emph{Notes}: Each column is one estimation of equation~\\eqref{eq:p2} with the estimator of "
         "Section~\\ref{sec:baseline}, on the full exposure population (the department roster in the "
         "arrival year together with the star's two-hop pre-arrival coauthorship network); incumbents who "
         "had already published with the star before the arrival are excluded. The outcome is an indicator "
         "equal to one in the year the incumbent first publishes with the star of the event, and the "
         "incumbent--star pair leaves the sample after that year, so the outcome is a discrete-time hazard: "
         "coefficients are changes in the yearly probability of a first coauthorship with the star, in "
         "percentage points (pp) --- first ties counts every first tie recorded in the window, before or "
         "after arrival. The average effect is the switcher-weighted mean of the five post-arrival "
         "coefficients; the joint test is of the five post-arrival coefficients. The pre-arrival placebo "
         "coefficients are zero by construction in this panel and are not reported "
         "(Section~\\ref{sec:baseline}); the date-shift test of Section~\\ref{sec:robustness} takes their "
         "place. Standard errors are in parentheses, clustered by incumbent (the main convention of "
         f"Section~\\ref{{sec:baseline}}) and by event; with {L['p2_chemistry']['events']} and "
         f"{L['p2_math_stats']['events']} events the event clusters in chemistry and mathematics are few, "
         "and few-cluster standard errors tend to be too small (Section~\\ref{sec:baseline}). Raw "
         "first-tie rates are the share of relation-years with a first tie, without any comparison group, "
         "over the six pre-arrival years and over the arrival year and the five years after it, restricted "
         f"to calendar years up to {CAP} because later years are incompletely covered by the 26 June 2026 "
         "snapshot. Horizon-by-horizon estimates are in Table~\\ref{tab:p2_full}.")
write_table("tab_p2_main.tex", "First coauthorship with the star (Panel 2)", "tab:p2_main",
            rows, notes,
            ["% Table: Panel 2 (first coauthorship with the star), compact. GENERATED by"] + GEN)

# ---------------------------------------------------------------------------
# Panel 2, every horizon
# ---------------------------------------------------------------------------
o = []
o.append("% Table: Panel 2 (first coauthorship with the star), every horizon. GENERATED by")
o.append(GEN[0])
o.append("\\begin{table}[ht]\n\\centering")
o.append("\\caption{" + R("Panel 2 horizon by horizon (first coauthorship with the star)") + "}")
o.append("\\label{tab:p2_full}\n\\small")
o.append("\\begin{tabular}{@{}l r r r r r@{}}\n\\toprule")
o.append(" & ".join(R(h) for h in ["Years since arrival $\\ell$", "Estimate (pp)", "s.e., incumbent",
                                   "s.e., event", "Relation--years", "Switchers"]) + " \\\\")
for f, name in F:
    c = L[f"p2_{f}"]
    o.append("\\midrule")
    o.append("\\multicolumn{6}{@{}l}{" + R(f"\\emph{{{name}}}: {big(c['relations'])} relations, "
             f"{big(c['first_ties'])} first ties, {c['events']} events") + "} \\\\")
    for h in c["horizons_pp"]:
        o.append(" & ".join(R(v) for v in [str(h["ell"]), num(h["est"]), f"({num(h['se_person'])})",
                                           f"({num(h['se_event'])})", big(h["n"]), big(h["switchers"])]) + " \\\\")
    o.append(" & ".join(R(v) for v in ["Average", num(c["ate_pp"]), f"({num(c['se_person_pp'])})",
                                       f"({num(c['se_event_pp'])})", "", big(c["switchers_total"])]) + " \\\\")
o.append("\\bottomrule\n\\end{tabular}")
o.append("\\par\\smallskip\n\\begin{minipage}{0.95\\textwidth}\\footnotesize")
o.append(R("\\emph{Notes}: Coefficients $\\gamma_\\ell$ of equation~\\eqref{eq:p2}, in percentage points "
           "of the yearly probability of a first coauthorship with the star, with $\\ell=-1$ normalized to "
           "zero; $\\ell=0$ is the arrival year. Relation--years is the number of observations entering the "
           "comparison at that horizon, and switchers the number of treated relations entering it "
           "(relations whose star has arrived, compared with not-yet-treated relations in the same calendar "
           "year); later horizons rest on earlier cohorts. The average is the switcher-weighted mean of the "
           "five horizons. Pre-arrival placebo coefficients are zero by construction and omitted "
           "(Section~\\ref{sec:baseline}). Sample definition as in Table~\\ref{tab:p2_main}."))
o.append("\\end{minipage}\n\\end{table}")
open(f"{ROOT}/tab_p2_full.tex", "w").write("\n".join(o) + "\n")

print("wrote tab_p1_main.tex, tab_p1_full.tex, tab_p2_main.tex and tab_p2_full.tex")
