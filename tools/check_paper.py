#!/usr/bin/env python3
"""check_paper.py — the paper SENTINEL: cross-checks the thesis against the repo's
generated numbers. Writes output/paper_check.md (one PASS/FAIL line per check, grouped
by section) and exits 1 iff any check FAILs.

Regenerate-or-load: every generated file in output/paper/ is loaded; a MISSING file's
generator is first run via subprocess, in this dependency order (1 must precede 2; the
rest are independent):
  1. analysis/paper/ledger_p3afar.py    -> data_numbers_p3afar.json (+ fig_p3_afar.pdf)
  2. analysis/paper/tables_p3afar.py    -> tab_p3_afar.tex, tab_p3_afar_full.tex (reads 1)
  3. analysis/paper/ledger_main.py      -> data_numbers_main.json
  4. analysis/paper/ledger_carried.py   -> data_numbers_carried.json
  5. analysis/paper/ledger_funnel.py    -> data_numbers_funnel.json
  6. analysis/paper/gaps_zenou.py       -> gaps_zenou.json
  7. analysis/paper/gaps_zero_dose.py   -> gaps_zero_dose.json
  8. analysis/paper/gaps_switchers.R    -> gaps_switchers.json  (Rscript, ~13 s)
  9. analysis/paper/gaps_toy.R          -> gaps_toy.json        (Rscript)
 10. analysis/paper/gaps_switchers_p1p2.R -> gaps_switchers_p1p2.json (Rscript, ~2 min; must
     precede 11 — the P1/P2 switcher counts, rerun gated on the frozen golds)
 11. analysis/paper/ledger_p1p2.py     -> data_numbers_p1p2.json (reads 10)
 12. analysis/paper/tables_p1p2.py     -> tab_p1_main/full.tex, tab_p2_main/full.tex (reads 11)
 13. analysis/paper/fig_p1.py / fig_p2.py -> fig_p1.pdf / fig_p2.pdf (read 11)

Check sections:
  A. Ledger equality — keyed on the THESIS ledgers, both directions: every non-underscore
     key of the thesis's data_numbers_2026-08-28.json must be either generated-and-equal
     (by ledger_main.py or ledger_carried.py) or declared in a generated ledger's
     `_unreproducible` block — a key in neither is a coverage hole and FAILs; the same rule
     ties data_numbers_2026-08-28_p3afar.json to data_numbers_p3afar.json. A generated key
     absent from the thesis ledger also FAILs. Every `_unreproducible` entry (incl.
     ledger_funnel.py's, whose keys live in no thesis ledger) gets its own report line
     "UNREPRODUCIBLE (asserted only): <key> — <reason>"; these count neither PASS nor FAIL,
     and a nonzero count is called out in the summary. The 2026-08-30 P1+P2 exhibits add a
     third pairing: the thesis's data_numbers_2026-08-30_p1p2.json vs data_numbers_p1p2.json.
  B. Table byte-identity — generated tab_p3_afar.tex / tab_p3_afar_full.tex and the four P1/P2
     tables (tab_p1_main/full, tab_p2_main/full) vs the thesis's tables/ copies.
  C. Gap-script integrity — every matches_appendix flag in gaps_switchers.json is true
     (hard-asserted HERE, per the Task-4 review; on the October canon only, since R1 final: the
     flags compare with gaps_switchers.R's October constants, and under an M canon section D's
     'estimator ...' pins check the printed appendix instead), coef_check passed, gaps_zenou UNVERIFIED
     empty; and the paper-stage figure PDFs (fig_p3_afar, fig_exposure_population,
     fig_dose_distribution, fig_p1, fig_p2, fig_hops, and since 2026-09-23 the appendix map
     fig_star_origins) must exist in output/paper/ and exceed 5 KB.
     gaps_switchers_p1p2.json's per-cell gold gates are re-asserted here too.
  D. In-text claims — a hard-coded table of (thesis tex file, regex, expected ledger value)
     for the recon §3(a)-(c) numbers: main.tex (the Section-1 headline restatement of the
     Panel 3 economics result), sec2_data.tex (Zénou worked example, any-reference /
     any-subfield shares, snapshot/benchmark millions, the OpenAlex subfield count, the U1
     ranking-pool millions, the roster spell-start ceilings and the snapshot release date
     (R3, 2026-09-10 — funnel-ledger keys), department counts + arrival spans,
     event/relation/incumbent/roster counts, P3 pair/event prose, topic-cut medians, dose
     bins + NA exclusions, balance std-diffs, FWCI-missing shares, both figure captions),
     sec3_strategy.tex (exact-zero-dose shares, event/cluster counts),
     sec4_p3.tex (the Panel 3 headline prose: ATE/SEs, raw rates, joint tests, chem/math
     estimates + CIs, speed-bracket numbers, raw path, year cap — all vs the p3afar ledger),
     appendix_estimator.tex (per-horizon coefficients vs the frozen gold
     analysis/expected/P1_econ_fnfix.json, switcher counts, average dose, the -0.142/-0.378
     summary prose, toy example), appendix_funnel.tex + appendix_pipeline.tex (full funnel
     table incl. steps 4-8 and notes, tab:na percentages, tab:events totals AND its 33
     per-university arrival-year cells vs events_by_school_*), appendix_robustness.tex
     (tab:balance — high/low/std-diff cell-by-cell, std-diffs compared WITH their printed
     sign, plus the notes' imbalance recap) + appendix_variables.tex (tab:quantiles —
     output/dose p25-median-p75-p95-max per discipline, star-stock note), and the
     hand-typed tables/tab_disciplines.tex + tables/tab_panels_overview.tex.
     The 2026-08-30 P1+P2 exhibits add a table-cell block (section_d_p1p2_tables): every
     number the four P1/P2 tables print, re-derived independently from the p1p2 ledger.
     Comparison modes: plain expected value = numeric equality with the pre-rounded ledger
     value; ("lt", p, thr) = the printed threshold must be the literal thr AND the ledger
     value p must be below it (for "p<0.001" — a "p<0.01" typo no longer passes);
     ("tol", x, t) = |printed - x| <= t (for printed roundings of exact .xx5 ties, where
     Python's round() and the thesis's formatter may legitimately differ);
     ("years", [..]) = the captured tab:events cell, "--" or a comma-separated year list,
     must equal the ledger's per-school arrival-year list.

Flags: --sections-dir DIR / --tables-dir DIR redirect where section D reads the tex from
(default: the thesis tree). They exist so tests can point the sentinel at a perturbed
scratch copy; sections A-C are unaffected. main.tex is read from --sections-dir too when a
main.tex exists in that directory (it lives one level above sections/ in the thesis tree,
so a scratch copy simply places it alongside the section files).

History note: the sentinel's first full run (2026-08-24) caught a real bug — sec2_data.tex
said "7.1 percent" for the economics any-reference share where the ledger derives 4.5 (7.1
came from the superseded 08-14 ledger). The Task-7 errata corrected the thesis the same day
and the sentinel has been fully green since.

2026-09-23 sync: thesis_report took the 2026-09-13 draft's text whole (plan: output/paper/SYNC_PLAN_2026-10.md).
Pins keep their names and ledger expressions; claims_table's SYNC_REANCHOR moves 141 of them to the
sentence or table row of the new text that prints the same ledger key, and SYNC_RETIRE lists the 65
whose number is no longer printed (reported as RETIRED, never graded, while their regex finds
nothing). Eight pins were added for sec4_causal.tex. Section D labels checks on files main.tex no
longer compiles (appendices, tab_disciplines). Section B compares the nine house-generator tables the
thesis still carries, and the draft's three tables against output/paper/draft_2026_09_13/ (written by
analysis/paper/draft_2026_09_13_tables.py); section_d_rob_tables reads tables_robustness.py's
tab_robustness.tex from output/paper/, because the thesis file of that name is now the draft's table.

2026-09-23 REPLACE stage (cal2026-10): the numbers of thesis_report and the draft were replaced from
the October ledgers (the author's re-pin tools, not shipped: old ledgers against output/paper), the
pins were renamed to the October values, and section A now reads the
installed thesis ledgers data_numbers_2026-10-23*.json (THESIS_LEDGERS). Eight pins were added: four
numbers no guard reached (now replaced), four refused spans only a "% src:" key guarded. A pin whose
span the replacement refused (sign flip, p<0.001 no longer met) FAILS until the author rewrites the
sentence -- by design. A cell whose October run FAILED (ledger null) must print 'failed'.

R1 P3 (V3-FINAL.c, N12, F7; 2026-10-16): the sentinel runs on any thesis tree with any ledger date.
Every new flag defaults to today's behaviour (no flag = the paths, ledger names, report, gold and pins
above, byte for byte). configure() rebinds the module paths; main() calls it with the flags:
  --thesis-root DIR      THESIS_REPORT (ledgers + tables of sections A/B, and sections/ + tables/ +
                         main.tex of section D); default <legacy_thesis>/thesis_report
  --ledger-date DATE     the dated thesis ledgers data_numbers_<DATE>*.json (default 2026-10-23)
  --report PATH          the markdown report (default <output>/paper_check.md)
  --json PATH            also a JSON report {n_checks, n_pass, n_fail, checks:[{section, name, ok,
                         retired, unrep, file, detail, note[, kind, anchor_found]}]} (kind 'claim' and
                         anchor_found only on the sentence claims: check())
  --no-regen             do not run the generators of missing output/paper files
  --gold PATH            the frozen P1 gold (default <expected>/P1_econ_fnfix.json)
  --profile thesis|vault|r1 the pin overlay: 'thesis' is the identity; 'vault' applies the measured
                         VAULT_OVERLAY_REANCHOR / _RETIRE (claims_table pins) and _REPHRASE
                         (section_d_r4_claims sentences) for the base tree's rewording (W3-OVERLAY);
                         'r1' adds the author-tree R1_* tables and section_d_r1_claims hook;
                         claims_for_profile(led, profile) gives the repin tools the same pins
  --tree thesis_report|base_2026_10_11
                         base_2026_10_11 also evaluates BASE_TREE_CLAIMS (section_d_base_tree: the
                         Section 2-3 numbers of the author's 2026-10-11 base tree that no common pin
                         covers; analysis/paper/sec23_number_audit.tsv lists every numeral and its pin)
  --tree-root DIR        where section D reads sections/, tables/ and main.tex (not the ledgers);
                         --sections-dir / --tables-dir still override it
The data reads of section D take their roots from config (P["cal"], P["paper_inputs"],
P["expected"]), so an M canon tree replaces them through $SAR_PATHS_CONFIG alone.

Run: python3 tools/check_paper.py
"""
import datetime
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from analysis.lib.paths import load_paths  # noqa: E402
from analysis.lib import canon  # noqa: E402

P = load_paths()
OUT = P["output"] / "paper"
THESIS_REPORT = P["legacy_thesis"] / "thesis_report"
SECTIONS = THESIS_REPORT / "sections"          # overridable via --sections-dir (section D only)
D_TABLES = THESIS_REPORT / "tables"            # overridable via --tables-dir  (section D only)
REPORT = P["output"] / "paper_check.md"

# The tex files section D reads. The author's re-pin tools (not shipped) read these two tuples too,
# so a pin on a new file can never be skipped by them. sec4_causal.tex,
# sec5_conclusion.tex, tab_main_results.tex and tab_robustness.tex joined on 2026-09-23, when
# thesis_report took the 2026-09-13 draft's text (plan: output/paper/SYNC_PLAN_2026-10.md).
D_SECTION_FILES = ("sec2_data.tex", "sec3_strategy.tex", "sec4_p1.tex", "sec4_p2.tex", "sec4_p3.tex",
                   "sec4_robustness.tex", "sec4_causal.tex", "sec5_conclusion.tex",
                   "appendix_estimator.tex", "appendix_funnel.tex", "appendix_pipeline.tex",
                   "appendix_robustness.tex", "appendix_variables.tex")
D_TABLE_FILES = ("tab_disciplines.tex", "tab_panels_overview.tex", "tab_main_results.tex",
                 "tab_robustness.tex")
# Section B. The nine tables the house generators write and the thesis still carries (none of them
# is compiled by the synced main.tex), and the three tables of the 2026-09-13 draft, which
# analysis/paper/draft_2026_09_13_tables.py writes into output/paper/draft_2026_09_13/ (its own
# folder: tables_robustness.py and tables_main.py write other tables under two of the same names).
B_GEN_TABLES = ("tab_p3_afar.tex", "tab_p3_afar_full.tex", "tab_p1_main.tex", "tab_p1_full.tex",
                "tab_p2_main.tex", "tab_p2_full.tex", "tab_rob_p1.tex", "tab_rob_p2.tex", "tab_rob_p3.tex")
DRAFT_TABLES_DIR = "draft_2026_09_13"
B_DRAFT_TABLES = ("tab_main_results.tex", "tab_robustness.tex", "tab_panels_overview.tex")
# A pin whose number the synced text no longer prints carries this tag at the start of its note
# (claims_table's SYNC_RETIRE); section D lists it instead of grading it while its regex finds nothing.
RETIRED_TAG = "RETIRED 2026-09-23"
SYNC_UNMATCHED = []   # SYNC_REANCHOR / SYNC_RETIRE keys that named no pin on the last claims_table() call

# R1 P3 (V3-FINAL.c / N12): the tree, profile, gold and JSON report a run uses; configure() sets them.
TREES = ("thesis_report", "base_2026_10_11")
BASE_TREE = "base_2026_10_11"
# the author's base tree (spec 2026-10-12 "Base tree for the paper"), relative to config `legacy_thesis`;
# a run on it passes --thesis-root / --tree-root, this constant only names it (tests, docs)
BASE_TREE_REL = "base_tree_2026-10-11/thesis_tree"   # in the restricted archive (not shipped)
PROFILES = ("thesis", "vault", "r1")
TREE = "thesis_report"
PROFILE = "thesis"
MAIN_TEX = None       # section D's main.tex when a --tree-root is given (else the thesis root's)
GOLD = P["expected"] / "P1_econ_fnfix.json"
JSON_OUT = None
# The 'vault' profile overlay (V3-FINAL.c): pins whose thesis_report sentence the base tree rewords.
# These three dicts are the overlay IN FORCE: configure(profile='vault') binds copies of the measured
# tables VAULT_OVERLAY_REANCHOR / VAULT_OVERLAY_RETIRE / VAULT_OVERLAY_REPHRASE (defined beside
# apply_profile, filled from the base tree's measured FAIL list, never by hand-guessing); 'r1' adds
# its overrides, while 'thesis' leaves them empty. VAULT_REANCHOR: pin name -> (file, regex) or (file, regex, group);
# VAULT_RETIRE: pin name -> reason (> 30 characters), only for a number the base tree no longer prints
# anywhere; VAULT_REPHRASE: section_d_r4_claims claim name -> (file, sentence) stating the same claim.
VAULT_REANCHOR: dict = {}
VAULT_RETIRE: dict = {}
VAULT_REPHRASE: dict = {}
VAULT_UNMATCHED = []  # overlay keys that named no pin on the last apply_profile() call


def _sync_2026_09_23(T, reanchor, retire):
    """Apply claims_table's 2026-09-23 sync tables: a re-anchored pin gets a new (file, regex, group)
    and keeps its name, ledger expression and note; a retired pin keeps everything and gets the
    RETIRED tag in its note. Keys that name no pin are kept in SYNC_UNMATCHED for section D."""
    both = set(reanchor) & set(retire)
    if both:
        raise ValueError(f"pins both re-anchored and retired: {sorted(both)}")
    names = {t[0] for t in T}
    SYNC_UNMATCHED[:] = sorted((set(reanchor) | set(retire)) - names)
    out = []
    for name, fname, rx, expected, group, note in T:
        if name in reanchor:
            fname, rx, group = reanchor[name]
        elif name in retire:
            note = f"{RETIRED_TAG}: {retire[name]}" + (f"; {note}" if note else "")
        out.append((name, fname, rx, expected, group, note))
    return out

# number token as printed in the tex: optional sign, then EITHER properly grouped digits
# (1-3 leading digits + one or more {,}/,-separated 3-digit groups: 510{,}372{,}821 / 7,543)
# OR a plain digit run (1999 / 119405), with an optional decimal part (-0.208 / 99.7).
# Malformed grouping like 75{,}43 deliberately does NOT parse as one number.
NUM = r"([-+]?(?:[0-9]{1,3}(?:(?:\{,\}|,)[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?)"
# signed number as tex prints it inside \REV cells: $-$0.16 / $+$0.20 (sign compared too)
SNUM = r"(\$[-+]\$(?:[0-9]{1,3}(?:(?:\{,\}|,)[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?)"

GENERATORS = [  # (target files in output/paper — run the generator if ANY is missing, script, runner)
    (("data_numbers_p3afar.json",), "analysis/paper/ledger_p3afar.py", "py"),
    (("tab_p3_afar.tex", "tab_p3_afar_full.tex"), "analysis/paper/tables_p3afar.py", "py"),
    (("data_numbers_main.json",), "analysis/paper/ledger_main.py", "py"),
    (("data_numbers_carried.json",), "analysis/paper/ledger_carried.py", "py"),
    (("data_numbers_funnel.json",), "analysis/paper/ledger_funnel.py", "py"),
    (("gaps_zenou.json",), "analysis/paper/gaps_zenou.py", "py"),
    (("fig_hops.pdf",), "analysis/paper/fig_hops.py", "py"),
    (("fig_star_origins.pdf", "data_numbers_star_origins.json"), "analysis/paper/fig_star_origins.py", "py"),
    (("gaps_zero_dose.json",), "analysis/paper/gaps_zero_dose.py", "py"),
    (("gaps_switchers.json",), "analysis/paper/gaps_switchers.R", "R"),
    (("gaps_toy.json",), "analysis/paper/gaps_toy.R", "R"),
    (("gaps_switchers_p1p2.json",), "analysis/paper/gaps_switchers_p1p2.R", "R"),
    (("data_numbers_p1p2.json",), "analysis/paper/ledger_p1p2.py", "py"),
    (("tab_p1_main.tex", "tab_p1_full.tex", "tab_p2_main.tex", "tab_p2_full.tex"),
     "analysis/paper/tables_p1p2.py", "py"),
    (("fig_p1.pdf",), "analysis/paper/fig_p1.py", "py"),
    (("fig_p2.pdf",), "analysis/paper/fig_p2.py", "py"),
    (("data_numbers_robustness.json",), "analysis/paper/ledger_robustness.py", "py"),
    (("tab_robustness.tex", "tab_rob_p1.tex", "tab_rob_p2.tex", "tab_rob_p3.tex"),
     "analysis/paper/tables_robustness.py", "py"),
]

checks = []  # list of dict(section, name, ok, detail, note, unrep, retired, file)


def check(section, name, ok, detail="", note="", file=None, kind=None, anchor_found=None, retired=False):
    """kind='claim' (R1, review R7 #8): a sentence whose meaning follows the ledgers and that no re-pin tool
    rewrites; anchor_found says whether its sentence (or pattern) was found. The final job's gate 2 sends a
    claim that FAILs with its anchor found to the author, and keeps one whose anchor is gone a hard failure.
    The two keys are written only for such checks (every other record is unchanged)."""
    rec = {"section": section, "name": name, "ok": bool(ok), "detail": detail,
           "note": note, "unrep": False, "retired": bool(retired), "file": file}
    if PROFILE == "r1" and section == "D" and name in R1_CLAIM_RETIRE:
        rec.update(ok=True, retired=True, detail=f"RETIRED (R1 claim): {R1_CLAIM_RETIRE[name]}")
    if kind is not None:
        rec.update(kind=kind, anchor_found=bool(anchor_found))
    checks.append(rec)


def check_retired(name, fname, note, file=None):
    """A pin retired by the 2026-09-23 sync whose regex finds nothing: listed, neither PASS nor FAIL.
    file: the record's tree-relative path (default fname; grade_pins passes 'tables/<name>' for a table)."""
    checks.append({"section": "D", "name": name, "ok": True,
                   "detail": f"RETIRED (not printed in the synced text; regex absent from {fname}): "
                             + note[len(RETIRED_TAG):].lstrip(": "),
                   "note": "", "unrep": False, "retired": True, "file": file or fname})


def check_unreproducible(key, reason, label):
    """An entry a ledger DECLARED unreproducible: surfaced in the report as asserted-only
    (neither PASS nor FAIL), so declaring a key can never silently shrink coverage."""
    checks.append({"section": "A", "name": f"[{label}] {key}", "ok": True,
                   "detail": f"UNREPRODUCIBLE (asserted only): {key} — {reason}",
                   "note": "", "unrep": True, "retired": False, "file": None})


def regenerate_missing():
    rscript = shutil.which("Rscript")
    for targets, script, runner in GENERATORS:
        missing = [t for t in targets if not (OUT / t).exists()]
        if not missing:
            continue
        if runner == "R" and rscript is None:
            print(f"[regen] SKIP {script}: Rscript not on PATH and {missing} is missing")
            continue
        cmd = [sys.executable if runner == "py" else rscript, str(REPO_ROOT / script)]
        print(f"[regen] {missing} missing -> running {script}")
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
        if r.returncode != 0:
            print(f"[regen] {script} FAILED:\n{r.stdout}{r.stderr}")


def load_json(name):
    p = OUT / name
    if not p.exists():
        return None
    return json.loads(p.read_text())


def norm_tex(path):
    """Tex content for layout-proof regex matching: unescaped %-comments stripped
    (so a stale sentence left in a comment can never satisfy a live-text check —
    T6 review MAJOR-1), then all whitespace runs collapsed."""
    text = re.sub(r"(?<!\\)%.*", " ", path.read_text())
    return re.sub(r"\s+", " ", text)


def parse_num(tok):
    tok = tok.replace("$-$", "-").replace("$+$", "+")
    return float(tok.replace("{,}", "").replace(",", ""))


# ---------------------------------------------------------------------------
# A. Ledger equality (keyed on the THESIS ledgers, both directions)
# ---------------------------------------------------------------------------
# The thesis ledgers section A compares with. Since 2026-09-23 (cal2026-10) they are the dated
# data_numbers_2026-10-23*.json frozen from output/paper by the author's install step (not shipped); the
# 2026-08-28 / 2026-08-30 / 2026-09-13 ledgers they replace are in thesis_report/_archive/.
THESIS_LEDGER_DATE = "2026-10-23"
THESIS_LEDGERS = {"main": "data_numbers_2026-10-23.json",            # main + carried, merged
                  "p3afar": "data_numbers_2026-10-23_p3afar.json",
                  "p1p2": "data_numbers_2026-10-23_p1p2.json",
                  "robustness": "data_numbers_2026-10-23_robustness.json"}
assert all(THESIS_LEDGER_DATE in f for f in THESIS_LEDGERS.values())
DEFAULT_LEDGER_DATE = THESIS_LEDGER_DATE


def ledger_names(date: str) -> dict:
    """The thesis ledger names of one install date (the naming of tools/repin_thesis_2026-10/install.py, not shipped)."""
    return {"main": f"data_numbers_{date}.json", "p3afar": f"data_numbers_{date}_p3afar.json",
            "p1p2": f"data_numbers_{date}_p1p2.json", "robustness": f"data_numbers_{date}_robustness.json"}


assert ledger_names(DEFAULT_LEDGER_DATE) == THESIS_LEDGERS


def configure(thesis_root=None, ledger_date=None, report=None, json_out=None, profile="thesis", gold=None,
              tree="thesis_report", tree_root=None, sections_dir=None, tables_dir=None):
    """Rebind the paths a run reads and writes (R1 P3, V3-FINAL.c). With no argument every value is
    today's: <legacy_thesis>/thesis_report, the 2026-10-23 ledgers, <output>/paper_check.md, no JSON,
    the 'thesis' profile, <expected>/P1_econ_fnfix.json and the thesis_report tree. A tree root moves
    only what section D reads (sections/, tables/, main.tex); sections_dir / tables_dir override last.
    The profile also sets the overlay in force: 'vault' binds the measured VAULT_OVERLAY_* tables,
    'r1' adds the author-tree overrides,
    'thesis' leaves VAULT_REANCHOR / VAULT_RETIRE / VAULT_REPHRASE empty (W3-OVERLAY)."""
    global THESIS_REPORT, SECTIONS, D_TABLES, THESIS_LEDGER_DATE, THESIS_LEDGERS, REPORT, JSON_OUT
    global PROFILE, GOLD, TREE, MAIN_TEX
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; expected one of {PROFILES}")
    if tree not in TREES:
        raise ValueError(f"unknown tree {tree!r}; expected one of {TREES}")
    date = DEFAULT_LEDGER_DATE if ledger_date is None else str(ledger_date)
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date):
        raise ValueError(f"ledger date {date!r} is not YYYY-MM-DD")
    datetime.date.fromisoformat(date)          # a real calendar date (ValueError otherwise)
    THESIS_REPORT = Path(thesis_root) if thesis_root else P["legacy_thesis"] / "thesis_report"
    d_root = Path(tree_root) if tree_root else THESIS_REPORT
    SECTIONS = Path(sections_dir) if sections_dir else d_root / "sections"
    D_TABLES = Path(tables_dir) if tables_dir else d_root / "tables"
    MAIN_TEX = d_root / "main.tex" if tree_root else None
    THESIS_LEDGER_DATE, THESIS_LEDGERS = date, ledger_names(date)
    REPORT = Path(report) if report else P["output"] / "paper_check.md"
    JSON_OUT = Path(json_out) if json_out else None
    PROFILE, TREE = profile, tree
    _bind_vault_overlay(profile)
    GOLD = Path(gold) if gold else P["expected"] / "P1_econ_fnfix.json"


def _main_tex():
    """Section D's main.tex: one placed beside a --sections-dir copy wins, then a --tree-root's, then
    the thesis root's (today's rule plus the tree root)."""
    m = SECTIONS / "main.tex"
    if m.exists():
        return m
    return MAIN_TEX if MAIN_TEX is not None else THESIS_REPORT / "main.tex"


def _shown(path):
    """A path for a report line: repo-relative when it is inside the repo (as before), else absolute."""
    for root in (REPO_ROOT, P["repo_root"]):
        try:
            return str(Path(path).relative_to(root))
        except ValueError:
            continue
    return str(path)


def section_a(led):
    t16 = json.loads((THESIS_REPORT / THESIS_LEDGERS["main"]).read_text())
    tp3 = json.loads((THESIS_REPORT / THESIS_LEDGERS["p3afar"]).read_text())
    # Each thesis ledger is covered by one or more generated ledgers jointly. Iterating the
    # THESIS keys (not the generated ones) means a key that silently drops out of a generator
    # — or moves into an _unreproducible block — can never shrink coverage unnoticed.
    tpp = json.loads((THESIS_REPORT / THESIS_LEDGERS["p1p2"]).read_text())
    trb = json.loads((THESIS_REPORT / THESIS_LEDGERS["robustness"]).read_text())
    for tag, thesis, parts in ((f"{THESIS_LEDGER_DATE} ledger", t16, (("main", led["main"]),
                                                      ("carried", led["carried"]))),
                               ("p3afar ledger", tp3, (("p3afar", led["p3afar"]),)),
                               ("p1p2 ledger", tpp, (("p1p2", led["p1p2"]),)),
                               ("robustness ledger", trb, (("robustness", led["robustness"]),))):
        gen_all, unrep, src = {}, {}, {}
        for label, gen in parts:
            if gen is None:
                check("A", f"[{label}] ledger generated", False, "output/paper JSON missing")
                continue
            for k, v in gen.items():
                if k == "_unreproducible":
                    for uk, reason in v.items():
                        unrep[uk], src[uk] = reason, label
                elif not k.startswith("_"):
                    gen_all[k], src[k] = v, label
        for key in sorted(k for k in thesis if not k.startswith("_")):
            if key in gen_all:
                ok = gen_all[key] == thesis[key]
                check("A", f"[{src[key]}] {key}", ok,
                      "equal" if ok else f"generated {gen_all[key]!r} != thesis {thesis[key]!r}")
            elif key in unrep:
                check_unreproducible(key, unrep.pop(key), src[key])
            else:
                check("A", f"[{tag}] {key}", False,
                      "thesis ledger key neither generated nor declared in a "
                      "_unreproducible block — coverage hole")
        for key in sorted(set(gen_all) - set(thesis)):
            check("A", f"[{src[key]}] {key}", False, "key absent from the thesis ledger")
        for key, reason in sorted(unrep.items()):  # declared but not a thesis key: still surfaced
            check_unreproducible(key, reason, src[key])
    # ledger_funnel's keys live in no thesis ledger (its equality is asserted in-script),
    # but any _unreproducible declaration there is surfaced here all the same.
    if led["funnel"]:
        for key, reason in sorted(led["funnel"].get("_unreproducible", {}).items()):
            check_unreproducible(key, reason, "funnel")


# ---------------------------------------------------------------------------
# B. Table byte-identity (the tables the generators own)
# ---------------------------------------------------------------------------
def section_b():
    # Since the 2026-09-23 sync the thesis's tables/tab_robustness.tex is the draft's Table 3
    # (draft_2026_09_13_tables.py), not tables_robustness.py's table of the same name: the latter
    # is no longer in the thesis and its cells are checked in output/paper/ (section_d_rob_tables).
    compiled = compiled_files()
    for name in B_GEN_TABLES:
        gen, ref = OUT / name, THESIS_REPORT / "tables" / name
        note = "" if name in compiled else "not compiled by main.tex"
        if not gen.exists():
            check("B", name, False, "generated table missing", note)
        else:
            ok = gen.read_bytes() == ref.read_bytes()
            check("B", name, ok, "byte-identical" if ok else "differs from the thesis copy", note)
    for name in B_DRAFT_TABLES:
        gen, ref = OUT / DRAFT_TABLES_DIR / name, THESIS_REPORT / "tables" / name
        label = f"{DRAFT_TABLES_DIR}/{name}"
        if not gen.exists():
            check("B", label, False,
                  "generated table missing: run analysis/paper/draft_2026_09_13_tables.py "
                  f"--out-dir output/paper/{DRAFT_TABLES_DIR}")
        else:
            ok = gen.read_bytes() == ref.read_bytes()
            check("B", label, ok, "byte-identical" if ok else "differs from the thesis copy")


def compiled_files(main_tex=None, sections=None):
    """Basenames of the tex files the thesis main.tex compiles: its \\input{}s, plus the tables the
    input sections \\input in turn (comments stripped first, so a commented-out \\input is not one)."""
    main_tex = main_tex or THESIS_REPORT / "main.tex"
    sections = sections or SECTIONS
    out = {"main.tex"}
    for inp in re.findall(r"\\input\{([^}]+)\}", norm_tex(main_tex)):
        base = Path(inp).name if inp.endswith(".tex") else Path(inp).name + ".tex"
        out.add(base)
        sec = sections / base
        if inp.startswith("sections/") and sec.exists():
            for sub in re.findall(r"\\input\{([^}]+)\}", norm_tex(sec)):
                out.add(Path(sub).name if sub.endswith(".tex") else Path(sub).name + ".tex")
    return out


# ---------------------------------------------------------------------------
# C. Gap-script integrity flags
# ---------------------------------------------------------------------------
def section_c(led):
    sw, zen = led["switchers"], led["zenou"]
    if sw is None:
        check("C", "gaps_switchers.json present", False, "missing (Rscript unavailable?)")
    else:
        # R1 final (review finding 6): the appendix constants these flags compare against
        # (APX / APX_TOTAL / APX_WAVG / APX_AVG_DOSE, analysis/paper/gaps_switchers.R:78-79) are the
        # October printed values, so the comparison means something only on the October canon. Under
        # an M canon the printed tab:agg cells and both average-dose sentences are checked against the
        # measured gaps_switchers.json by section D's 'estimator ...' pins (claims_table); the gold
        # coefficient check below stays in every mode. A CanonError here fails closed: main() records
        # it as 'section C completed' FAIL.
        if canon.mode(P) == "october":
            for h in sw["horizons"]:
                check("C", f"switchers ell={h['k'] - 1} matches appendix", h["matches_appendix"],
                      f"measured {h['switchers']} vs appendix {h['appendix_switchers']}")
            check("C", "switchers total matches appendix", sw["switchers_total_matches_appendix"],
                  f"measured {sw['switchers_total']} vs appendix {sw['appendix_switchers_total']}")
            check("C", "weighted avg effect matches appendix", sw["weighted_avg_matches_appendix"],
                  f"measured {round(sw['weighted_avg_effect'], 3)} vs appendix {sw['appendix_weighted_avg']}")
            check("C", "avg dose matches appendix", sw["avg_dose_matches_appendix"],
                  f"measured {round(sw['avg_dose_switchers'], 3)} vs appendix {sw['appendix_avg_dose']}")
        check("C", "switcher rerun reproduces the frozen gold coefficients", sw["coef_check"]["pass"],
              f"ate {sw['coef_check']['ate']} vs expected {sw['coef_check']['expected_ate']}")
    if zen is None:
        check("C", "gaps_zenou.json present", False, "missing")
    else:
        unv = zen.get("UNVERIFIED", [])
        check("C", "Zenou worked example fully verified", unv == [], f"UNVERIFIED={unv}")
    # the three figure PDFs the paper stage generates (fig_p3_afar by ledger_p3afar.py, the
    # other two by their fig_* scripts) must exist and be real PDFs, not stubs
    swp = led["switchers_p1p2"]
    if swp is None:
        check("C", "gaps_switchers_p1p2.json present", False, "missing (Rscript unavailable?)")
    else:
        for panel in ("p1", "p2"):
            for field in ("econ", "chemistry", "math_stats"):
                cc = swp[panel][field]["coef_check"]
                check("C", f"switchers_p1p2 {panel} {field} rerun reproduces the frozen gold",
                      cc["pass"], f"ate {cc['ate']} vs expected {cc['expected_ate']}")
    figs = ("fig_p3_afar.pdf", "fig_exposure_population.pdf", "fig_dose_distribution.pdf",
            "fig_p1.pdf", "fig_p2.pdf", "fig_hops.pdf", "fig_star_origins.pdf")
    if TREE == BASE_TREE:   # the base tree's Section 3.3 prints Figures 3 and 4 (N9 generators)
        figs += ("fig_compare_years.pdf", "fig_comparison_pools.pdf")
    for name in figs:
        if PROFILE == "r1" and name == "fig_comparison_pools.pdf":
            check("C", f"{name} exists (>5 KB)", True,
                  "RETIRED (R1 figure): The author deleted Figure 4 and its caption on 2026-10-19; "
                  "the surviving comparison-pool prose is still checked against its JSON ledger.", retired=True)
            continue
        p = OUT / name
        if not p.exists():
            check("C", f"{name} exists (>5 KB)", False, "missing from output/paper/")
        else:
            size = p.stat().st_size
            check("C", f"{name} exists (>5 KB)", size > 5_000, f"{size:,} bytes")


# ---------------------------------------------------------------------------
# D. In-text claims (thesis tex vs ledger values)
# ---------------------------------------------------------------------------
# R1 P3 N12 part 2 (R4): Section 2.4's empty-row and missing-output shares. Computed exactly like the
# funnel tab:na shares below (na_pct) from the frame-derived econ_py_decomp (main ledger) and
# chem/math_py_decomp (carried ledger), so M values follow M's frames; no new ledger key (section A
# would FAIL on a generated key the thesis ledger lacks). The sentence is the same in thesis_report and
# the base tree. Names carry no number, so the re-pin tools never need to rename them.
SEC2_EMPTY_SHARE_NAMES = ("sec2 empty-by-design share econ", "sec2 no-FWCI share econ",
                          "sec2 empty-by-design share chem", "sec2 no-FWCI share chem",
                          "sec2 empty-by-design share math", "sec2 no-FWCI share math")


def na_shares(dec):
    """(empty-by-design %, genuinely missing %) of one Panel 1 decomposition, 1 dp (na_pct's rule)."""
    empty = dec.get("empty_out_of_employment", dec.get("empty_no_record"))
    return round(100 * empty / dec["rows"], 1), round(100 * dec["genuine_missing"] / dec["rows"], 1)


def sec2_empty_share_claims(main, carried):
    """The six Section 2.4 pins (sec2_data.tex), in SEC2_EMPTY_SHARE_NAMES order."""
    e_emp, e_mis = na_shares(main["econ_py_decomp"])
    c_emp, c_mis = na_shares(carried["chem_py_decomp"])
    m_emp, m_mis = na_shares(carried["math_py_decomp"])
    shares_rx = (r"The shares are " + NUM + r" and " + NUM + r" percent in chemistry and " + NUM + r" and "
                 + NUM + r" percent in mathematics")
    n = SEC2_EMPTY_SHARE_NAMES
    return [(n[0], "sec2_data.tex", r"In economics, " + NUM + r" percent are empty by design", e_emp, 1, ""),
            (n[1], "sec2_data.tex", r"Another " + NUM + r" percent have publications, but none with an FWCI value",
             e_mis, 1, ""),
            (n[2], "sec2_data.tex", shares_rx, c_emp, 1, ""),
            (n[3], "sec2_data.tex", shares_rx, c_mis, 2, ""),
            (n[4], "sec2_data.tex", shares_rx, m_emp, 3, ""),
            (n[5], "sec2_data.tex", shares_rx, m_mis, 4, "")]


def t_rank_pin_note(perm):
    """The note of the two t-ranked shuffled-years pins: retired (with the reason) when ranking by t moves no Panel 1
    or 2 cell across 0.05, because Table 3's generator then omits the sentence they are anchored on
    (analysis/paper/draft_2026_09_13_tables.py, rank_note); empty otherwise (October: mathematics Panel 2 crosses)."""
    cells = [k for k in perm if k.startswith(("p1_", "p2_"))]
    if any((perm[k]["p_perm_abs_ate"] < 0.05) != (perm[k]["p_perm_abs_t"] < 0.05) for k in cells):
        return ""
    return (RETIRED_TAG + ": ranking by t moves no cell across 0.05, so Table 3 prints no t-ranking sentence")


def claims_table(led, profile="thesis"):
    # 2026-09-23: the (file, regex, group) of 141 pins below are overridden, and 65 pins are retired,
    # by the SYNC_REANCHOR / SYNC_RETIRE tables at the end of this function (thesis_report now holds
    # the 2026-09-13 draft's text). Names and ledger expressions are never overridden.
    main, carried, funnel = led["main"], led["carried"], led["funnel"]
    p3, zen, zero, sw, toy = led["p3afar"], led["zenou"], led["zero"], led["switchers"], led["toy"]
    gold = led["gold_p1_union"]  # frozen gold: analysis/expected/P1_econ_fnfix.json channels.union

    sw_row = (r"\\REV\{Switching relations\}" + "".join(r" & \\REV\{" + NUM + r"\}" for _ in range(7)))
    coef_row = (r"\\REV\{Coefficient\}" + "".join(r" & \\REV\{\$" + NUM + r"\$\}" for _ in range(7)))
    ev_row = r"Star set and arrival events[^&]*& \\REV\{" + NUM + r" / " + NUM + r" / " + NUM + r" events"
    panels_row = r"Panels 1--3 & \\REV\{" + NUM + r" to " + NUM + r" rows"
    pools_note = (r"removes " + NUM + r" of " + NUM + r" mathematics pairs and "
                  + NUM + r" of " + NUM + r" chemistry pairs")

    # (name, tex file, regex, expected value, group index, note)
    T = []
    if zen:
        z = [("star percentile 99.7", r"citations placed him at the " + NUM + r"th percentile", zen["star_percentile"]),
             ("roster 60", r"roster for 2016 lists " + NUM + r" incumbents", zen["roster"]),
             ("two-hop network 66", r"network within two hops reaches " + NUM + r" researchers", zen["network"]),
             ("network-only 42", NUM + r" of whom are not on the roster", zen["network_only"]),
             ("union 102", r"the union, " + NUM + r" incumbents", zen["union"]),
             ("dose below 0.1: 26", NUM + r" sit below 0\.1", zen["dose_below_01"]),
             ("dose >= 0.5: 63", NUM + r" at or above 0\.5", zen["dose_ge_05"]),
             ("median dose 0.51", r"the median is " + NUM, zen["dose_median"]),
             ("Panel 2 follows 100", r"Panel 2 follows " + NUM + r" of them", zen["p2_followed"]),
             ("first ties post 6", r"which " + NUM + r" record after his arrival", zen["p2_first_ties_post"]),
             ("outside network 36", NUM + r" are outside the network", zen["outside_network"]),
             ("same-topic outside 36", r"and all " + NUM + r" of these share at least one subfield",
              zen["same_topic_outside"]),
             ("pairs 624", r"they form " + NUM + r" pairs", zen["pairs"]),
             ("possible pairs 630", r"of the " + NUM + r" possible pairs", zen["pairs_possible"])]
        T += [(f"sec2_data Zenou: {n}", "sec2_data.tex", rx, v, 1, "") for n, rx, v in z]
    if main:
        T.append(("sec2_data any-reference share (econ_share_any_ref)", "sec2_data.tex",
                  r"only " + NUM + r" percent of the economics incumbent--event pairs",
                  main["econ_share_any_ref"], 1, ""))
        T.append(("sec2_data any-subfield share (econ_share_any_subfield)", "sec2_data.tex",
                  r"against " + NUM + r" percent that share a subfield",
                  round(main["econ_share_any_subfield"]), 1, ""))
        # 2026-09-28 (supervisor round 4, #15: how many subfields each discipline has): the
        # discipline's own subfields in the extraction table, which equal OpenAlex's full list for
        # fields 20 / 16 / 26 (checked against api.openalex.org/subfields the same day).
        sf_rx = (r"OpenAlex divides economics into " + NUM + r" subfields, chemistry into " + NUM
                 + r" and mathematics into " + NUM)
        T += [(f"sec2_data subfields per discipline: {d}", "sec2_data.tex", sf_rx,
               main[f"{k}_own_field_subfields_in_extraction_table"], g, "")
              for g, (d, k) in enumerate((("econ 3", "econ"), ("chem 6", "chem"),
                                          ("math 10", "math")), start=1)]
    if zero:
        T += [("sec3 zero-dose econ 8%", "sec3_strategy.tex",
               r"\\REV\{" + NUM + r"\} percent of relations in economics",
               round(zero["econ_zero_dose_share_pct"]), 1, ""),
              ("sec3 zero-dose chem 6%", "sec3_strategy.tex",
               r"economics, \\REV\{" + NUM + r"\} in chemistry",
               round(zero["chem_zero_dose_share_pct"]), 1, ""),
              ("sec3 zero-dose math 31%", "sec3_strategy.tex",
               r"chemistry, \\REV\{" + NUM + r"\} in mathematics",
               round(zero["math_zero_dose_share_pct"]), 1, "")]
    if sw:
        for i, h in enumerate(sw["horizons"]):
            T.append((f"estimator switchers ell={i}", "appendix_estimator.tex", sw_row,
                      h["switchers"], i + 1, ""))
        T += [("estimator switchers total 28,473", "appendix_estimator.tex", sw_row,
               sw["switchers_total"], 7, ""),
              ("estimator summary coefficient -0.141", "appendix_estimator.tex", coef_row,
               round(sw["weighted_avg_effect"], 3), 7, ""),
              ("estimator per-unit-of-dose -0.368", "appendix_estimator.tex",
               r"\\REV\{Per unit of dose\} & & & & & & & \\REV\{\$" + NUM + r"\$\}",
               round(sw["coef_check"]["ate"], 3), 1, ""),
              ("estimator avg dose 0.383 (prose)", "appendix_estimator.tex",
               r"Dividing by their average dose, \$" + NUM + r"\$",
               round(sw["avg_dose_switchers"], 3), 1, ""),
              ("estimator avg dose 0.383 (table notes)", "appendix_estimator.tex",
               r"switching relations' average dose, \$" + NUM + r"\$",
               round(sw["avg_dose_switchers"], 3), 1, "")]
    if toy:
        T += [("estimator toy effect ell=0 (-0.208, prose)", "appendix_estimator.tex",
               r"1\(0\)\]/4 = " + NUM + r"\$", round(toy["effect_1"], 3), 1, ""),
              ("estimator toy effect ell=1 (0, prose)", "appendix_estimator.tex",
               r"1\(1\)\]/3 = " + NUM + r"\$", round(toy["effect_2"], 3), 1, ""),
              ("estimator toy weighted average ell=0 (table)", "appendix_estimator.tex",
               r"Weighted average & \$" + NUM + r"\$ & \$\\phantom\{\+\}" + NUM + r"\$",
               round(toy["effect_1"], 3), 1, ""),
              ("estimator toy weighted average ell=1 (table)", "appendix_estimator.tex",
               r"Weighted average & \$" + NUM + r"\$ & \$\\phantom\{\+\}" + NUM + r"\$",
               round(toy["effect_2"], 3), 2, ""),
              ("estimator toy per-unit -0.238", "appendix_estimator.tex",
               r"giving \$" + NUM + r"\$ per unit of dose", round(toy["av_tot_eff"], 3), 1, ""),
              ("estimator toy placebo -0.750", "appendix_estimator.tex",
               r"arrival gives \$" + NUM + r"\$ here", round(toy["placebo_1"], 3), 1, "")]
    if funnel:
        T += [("funnel step 1 snapshot works", "appendix_funnel.tex",
               r"Works in the frozen snapshot & " + NUM, funnel["works_snapshot"], 1, ""),
              ("funnel step 2 benchmarkable works", "appendix_funnel.tex",
               r"\(citation benchmark\) & " + NUM, funnel["works_benchmarkable"], 1, ""),
              ("funnel step 3 articles+reviews", "appendix_funnel.tex",
               r"used for output & " + NUM, funnel["works_articles_reviews"], 1, ""),
              ("pipeline snapshot works", "appendix_pipeline.tex",
               r"authorships & " + NUM + r" works", funnel["works_snapshot"], 1, ""),
              ("pipeline benchmark cells", "appendix_pipeline.tex",
               r"Expected citations per cell & " + NUM + r" cells", funnel["benchmark_cells"], 1, "")]
    if carried:
        T.append(("pipeline verified roster persons", "appendix_pipeline.tex",
                  r"& " + NUM + r" verified persons", sum(carried["roster_people"].values()), 1, ""))
    if main:
        T += [("pipeline events econ", "appendix_pipeline.tex", ev_row, main["econ_events"], 1, ""),
              ("pipeline events chem", "appendix_pipeline.tex", ev_row, main["chem_events"], 2, ""),
              ("pipeline events math", "appendix_pipeline.tex", ev_row, main["math_events"], 3, ""),
              ("pipeline relations total", "appendix_pipeline.tex",
               r"relations with dose & \\REV\{" + NUM + r" relations",
               sum(main[f"{d}_relations"]["total"] for d in ("econ", "chem", "math")), 1, "")]
    if carried:
        T.append(("pipeline panel rows min (math P1)", "appendix_pipeline.tex", panels_row,
                  carried["panel_rows"]["math"][0], 1, ""))
    if p3:
        T.append(("pipeline panel rows max (econ P3)", "appendix_pipeline.tex", panels_row,
                  p3["econ"]["rows"], 2, ""))
        T.append(("funnel step 9 econ P3 rows", "appendix_funnel.tex",
                  r"Panel 3 rows.*?& \\REV\{" + NUM + r"\}",
                  p3["econ"]["rows"], 1, ""))

    # ---- appendix_estimator tab:agg per-horizon coefficients vs the frozen gold (T6 review MINOR-2) ----
    if gold:
        for i, eff in enumerate(gold["effects"]):
            T.append((f"estimator tab:agg coefficient ell={i} (gold P1 union)",
                      "appendix_estimator.tex", coef_row, round(eff["est"], 3), i + 1, ""))

    # ---- sec4_p3.tex: the Panel 3 headline prose vs the p3afar ledger (T6 review MAJOR-2) ----
    if p3:
        E, C, M = p3["econ"], p3["chemistry"], p3["math_stats"]
        # Rewritten 2026-08-30 with the section. The speed bracket is gone from the paper (its
        # counterfactual paths were computed on the 22 August event set and had no rebuilt
        # counterpart), and two new evidence blocks are pinned: randomization inference and the
        # arrival-year spike. Every pin below anchors on a sentence in the new prose.
        H = {h["ell"]: h for h in E["horizons_pp"]}
        HC = {h["ell"]: h for h in C["horizons_pp"]}
        HM = {h["ell"]: h for h in M["horizons_pp"]}
        RI = {f: p3[f].get("randomization_inference") or {} for f in ("econ", "chemistry", "math_stats")}
        DS = {f: p3[f]["robustness"]["date_shift_two_years"] for f in ("econ", "chemistry", "math_stats")}
        GRID = {g["cut_spec"]: g for g in E["robustness"]["cut_grid"]}
        GRIDC = {g["cut_spec"]: g for g in C["robustness"]["cut_grid"]}
        rate_rx = (r"against a pre-arrival rate of " + NUM + r" percent a year")
        chem_rx = (r"a fall of " + NUM + r" percentage points from a pre-arrival rate of " + NUM
                   + r" percent")
        cnt_rx = (r"on " + NUM + r" pairs and " + NUM + r" first ties in " + NUM + r" events")
        math_rx = (r"the estimate is " + NUM + r" percentage points on " + NUM
                   + r" first ties in " + NUM + r" events")
        spike_rx = (r"by " + NUM + r" percentage points in economics, " + NUM + r" in chemistry and "
                    + NUM + r" in mathematics")
        ev_rx = (r"there are " + NUM + r" arrivals contributing pairs in economics, " + NUM
                 + r" in chemistry and " + NUM + r" in mathematics")
        perm_rx = (r"Over " + NUM + r" permutations the answer is " + NUM
                   + r" percent in economics, " + NUM + r" percent in chemistry and " + NUM
                   + r" percent in mathematics")
        path_rx = (r"climbs from " + NUM + r" percent six years before the arrival to " + NUM
                   + r" percent in the year before it, peaks at " + NUM
                   + r" percent in the arrival year, and falls to " + NUM
                   + r" percent by the fifth year")
        NS = {f: p3[f].get("null_simulation") or {} for f in ("econ", "chemistry", "math_stats")}
        null_rx = (r"The average estimate is " + NUM + r" percentage points in economics, more than "
                   + r"the " + NUM + r" reported; \$-\$" + NUM + r" in chemistry")
        null2_rx = (r"and " + NUM + r" in mathematics against a reported " + NUM)
        cut_rx = (r"which leaves " + NUM + r" of the " + NUM
                  + r" economics pairs, moves the estimate to \$-\$" + NUM)
        T += [("p3 econ ATE 0.044pp", "sec4_p3.tex",
               r"is " + NUM + r" percentage points higher after the arrival", E["ate_pp"], 1, ""),
              ("p3 econ SE pair 0.053", "sec4_p3.tex",
               r"standard error " + NUM + r" clustered by pair, " + NUM + r" clustered by event",
               E["se_pair_pp"], 1, ""),
              ("p3 econ SE event 0.093", "sec4_p3.tex",
               r"standard error " + NUM + r" clustered by pair, " + NUM + r" clustered by event",
               E["se_event_pp"], 2, ""),
              ("p3 econ pre rate 0.303", "sec4_p3.tex", rate_rx, E["rate_pre_pp"], 1, ""),
              ("p3 econ headline permutation 24 percent", "sec4_p3.tex",
               r"produce an effect this large " + NUM + r"\s*percent of the time",
               round(100 * RI["econ"].get("p_two_sided", 0)), 1, ""),
              ("p3 chem fall 0.466pp", "sec4_p3.tex", chem_rx, abs(C["ate_pp"]), 1, ""),
              ("p3 chem pre rate 0.708", "sec4_p3.tex", chem_rx, C["rate_pre_pp"], 2, ""),
              ("p3 chem pairs 11,466", "sec4_p3.tex", cnt_rx, C["pairs"], 1, ""),
              ("p3 chem first ties 1,004", "sec4_p3.tex", cnt_rx, C["first_ties"], 2, ""),
              ("p3 chem events 38", "sec4_p3.tex", cnt_rx, C["events_with_pairs"], 3, ""),
              ("p3 chem CI lower 1.047", "sec4_p3.tex",
               r"runs from \$-\$" + NUM + r" to " + NUM + r" and includes zero",
               abs(C["ci95_pair_pp"][0]), 1, ""),
              ("p3 chem CI upper 0.114", "sec4_p3.tex",
               r"runs from \$-\$" + NUM + r" to " + NUM + r" and includes zero",
               C["ci95_pair_pp"][1], 2, ""),
              ("p3 math estimate 0.041pp", "sec4_p3.tex", math_rx, M["ate_pp"], 1, ""),
              ("p3 math first ties 401", "sec4_p3.tex", math_rx, M["first_ties"], 2, ""),
              ("p3 math events 32", "sec4_p3.tex", math_rx, M["events_with_pairs"], 3, ""),
              ("p3 math CI lower 0.039", "sec4_p3.tex",
               r"confidence interval from \$-\$" + NUM + r" to " + NUM + r"\.",
               abs(M["ci95_pair_pp"][0]), 1, ""),
              ("p3 math CI upper 0.122", "sec4_p3.tex",
               r"confidence interval from \$-\$" + NUM + r" to " + NUM + r"\.",
               M["ci95_pair_pp"][1], 2, ""),
              ("p3 math base rate 0.197", "sec4_p3.tex",
               r"a base rate of " + NUM + r" percent", M["rate_pre_pp"], 1, ""),
              # --- the arrival-year spike, all three disciplines (new 2026-08-30) ---
              ("p3 arrival-year spike econ 0.136", "sec4_p3.tex", spike_rx, H[0]["est"], 1, ""),
              ("p3 arrival-year spike chem 0.135", "sec4_p3.tex", spike_rx, HC[0]["est"], 2, ""),
              ("p3 arrival-year spike math 0.174", "sec4_p3.tex", spike_rx, HM[0]["est"], 3, ""),
              ("p3 two-years-after econ 0.028", "sec4_p3.tex",
               r"the coefficient is " + NUM + r" below zero in economics, " + NUM + r" below in chemistry",
               abs(H[2]["est"]), 1, ""),
              ("p3 two-years-after chem 0.243", "sec4_p3.tex",
               r"the coefficient is " + NUM + r" below zero in economics, " + NUM + r" below in chemistry",
               abs(HC[2]["est"]), 2, ""),
              # --- the two over-claims the 2026-08-30 review flagged, fixed 2026-09-10 ---
              ("p3 econ fourth-year reappearance 0.070", "sec4_p3.tex",
               r"in the fourth year, at " + NUM + r" percentage points \(standard error " + NUM + r"\)",
               H[4]["est"], 1, ""),
              ("p3 econ fourth-year se 0.102", "sec4_p3.tex",
               r"in the fourth year, at " + NUM + r" percentage points \(standard error " + NUM + r"\)",
               H[4]["se_pair"], 2, ""),
              ("p3 chem fourth-year coefficient -2.108", "sec4_p3.tex",
               r"the fourth-year coefficient, \$-\$" + NUM + r" percentage points with a standard error of " + NUM,
               abs(HC[4]["est"]), 1, ""),
              ("p3 chem fourth-year se 1.664", "sec4_p3.tex",
               r"the fourth-year coefficient, \$-\$" + NUM + r" percentage points with a standard error of " + NUM,
               HC[4]["se_pair"], 2, ""),
              ("p3 chem fourth-year share of the average 77.5%", "sec4_p3.tex",
               r"supplies " + NUM + r" percent of it", C["post_sum_share_pct_by_ell"]["4"], 1, ""),
              # --- randomization inference (new 2026-08-30) ---
              ("p3 events-with-pairs econ 111", "sec4_robustness.tex", ev_rx, E["events_with_pairs"], 1, ""),
              ("p3 events-with-pairs chem 38", "sec4_robustness.tex", ev_rx, C["events_with_pairs"], 2, ""),
              ("p3 events-with-pairs math 32", "sec4_robustness.tex", ev_rx, M["events_with_pairs"], 3, ""),
              ("p3 perm count 500", "sec4_robustness.tex", perm_rx, RI["econ"].get("permutations"), 1, ""),
              ("p3 perm pct econ 24", "sec4_robustness.tex", perm_rx,
               round(100 * RI["econ"].get("p_two_sided", 0)), 2, ""),
              ("p3 perm pct chem 10", "sec4_robustness.tex", perm_rx,
               round(100 * RI["chemistry"].get("p_two_sided", 0)), 3, ""),
              ("p3 perm pct math 58", "sec4_robustness.tex", perm_rx,
               round(100 * RI["math_stats"].get("p_two_sided", 0)), 4, ""),
              # The sentence says "Over 500 permutations" once and then gives all three
              # percentages, so the count is pinned to economics and cross-checked here: all three
              # disciplines must actually have the same number of draws for that wording to be true.
              ("p3 perm counts equal across disciplines", "sec4_robustness.tex", perm_rx,
               RI["chemistry"].get("permutations"), 1, ""),
              ("p3 perm counts equal math", "sec4_robustness.tex", perm_rx,
               RI["math_stats"].get("permutations"), 1, ""),
              # --- date-shift test ---
              ("p3 date-shift econ k1 0.104", "sec4_p3.tex",
               r"In economics they are not: " + NUM + r" and " + NUM + r" percentage points",
               round(DS["econ"]["shifted_effects_pp"][0], 3), 1, ""),
              ("p3 date-shift econ k2 0.077", "sec4_p3.tex",
               r"In economics they are not: " + NUM + r" and " + NUM + r" percentage points",
               round(DS["econ"]["shifted_effects_pp"][1], 3), 2, ""),
              ("p3 date-shift vs reported 0.044", "sec4_p3.tex",
               r"larger than the " + NUM + r" reported as the effect", E["ate_pp"], 1, ""),
              ("p3 date-shift chem p 0.84", "sec4_p3.tex",
               r"\(\$p=" + NUM + r"\$ and \$p=" + NUM + r"\$\)",
               round(DS["chemistry"]["p_joint_shifted"], 2), 1, ""),
              ("p3 date-shift math p 0.56", "sec4_p3.tex",
               r"\(\$p=" + NUM + r"\$ and \$p=" + NUM + r"\$\)",
               round(DS["math_stats"]["p_joint_shifted"], 2), 2, ""),
              # --- no-effect simulation (new 2026-08-30): what the estimator returns when
              # there is nothing to find. NS below is the ledger's null_simulation block. ---
              ("p3 null-sim count 200", "sec4_robustness.tex",
               r"The check simulates " + NUM + r" panels", NS["econ"]["nsim"], 1, ""),
              # the sentence says "200 panels" once for all three, so all three must have 200
              ("p3 null-sim count equal chem", "sec4_robustness.tex",
               r"The check simulates " + NUM + r" panels", NS["chemistry"]["nsim"], 1, ""),
              ("p3 null-sim count equal math", "sec4_robustness.tex",
               r"The check simulates " + NUM + r" panels", NS["math_stats"]["nsim"], 1, ""),
              ("p3 null-sim econ 0.048", "sec4_robustness.tex", null_rx,
               NS["econ"]["dcdh_ate_pp_no_effect_world"], 1, ""),
              ("p3 null-sim vs reported econ 0.044", "sec4_robustness.tex", null_rx, E["ate_pp"], 2, ""),
              ("p3 null-sim chem 0.244", "sec4_robustness.tex", null_rx,
               abs(NS["chemistry"]["dcdh_ate_pp_no_effect_world"]), 3, ""),
              ("p3 null-sim math 0.035", "sec4_robustness.tex", null2_rx,
               NS["math_stats"]["dcdh_ate_pp_no_effect_world"], 1, ""),
              ("p3 null-sim vs reported math 0.041", "sec4_robustness.tex", null2_rx, M["ate_pp"], 2, ""),
              # --- raw path, economics ---
              ("p3 econ raw path -6 0.205", "sec4_p3.tex", path_rx,
               round(E["raw_rate_by_event_time_pp"]["-6"], 3), 1, ""),
              ("p3 econ raw path -1 0.387", "sec4_p3.tex", path_rx,
               round(E["raw_rate_by_event_time_pp"]["-1"], 3), 2, ""),
              ("p3 econ raw path 0 0.396", "sec4_p3.tex", path_rx,
               round(E["raw_rate_by_event_time_pp"]["0"], 3), 3, ""),
              ("p3 econ raw path 5 0.220", "sec4_p3.tex", path_rx,
               round(E["raw_rate_by_event_time_pp"]["5"], 3), 4, ""),
              # --- topic-cut grid ---
              ("p3 cut med econ pairs 23,758", "sec4_robustness.tex", cut_rx,
               E["robustness"]["former_main_cut"]["pairs"], 1, ""),
              ("p3 cut pos econ pairs 90,325", "sec4_robustness.tex", cut_rx, E["pairs"], 2, ""),
              ("p3 cut med econ ate 0.079", "sec4_robustness.tex", cut_rx,
               abs(E["robustness"]["former_main_cut"]["ate_pp"]), 3, ""),
              ("p3 cut abs04 econ ate 0.151", "sec4_robustness.tex",
               r"a dose of at least 0\.4 gives \$-\$" + NUM + r" on " + NUM + r" pairs",
               round(abs(GRID["abs04"]["ate_pp"]), 3), 1, ""),
              ("p3 cut abs04 econ pairs 17,310", "sec4_robustness.tex",
               r"a dose of at least 0\.4 gives \$-\$" + NUM + r" on " + NUM + r" pairs",
               GRID["abs04"]["pairs"], 2, ""),
              ("p3 cut p75 econ ate 0.068", "sec4_robustness.tex",
               r"the top quarter gives \$-\$" + NUM + r" on " + NUM,
               round(abs(GRID["p75"]["ate_pp"]), 3), 1, ""),
              ("p3 cut p75 econ pairs 7,555", "sec4_robustness.tex",
               r"the top quarter gives \$-\$" + NUM + r" on " + NUM,
               GRID["p75"]["pairs"], 2, ""),
              ("p3 cut med chem ate 0.642", "sec4_robustness.tex",
               r"at \$-\$" + NUM + r" and \$-\$" + NUM + r" on the two middle cells",
               round(abs(GRIDC["med"]["ate_pp"]), 3), 1, ""),
              ("p3 cut abs04 chem ate 0.844", "sec4_robustness.tex",
               r"at \$-\$" + NUM + r" and \$-\$" + NUM + r" on the two middle cells",
               round(abs(GRIDC["abs04"]["ate_pp"]), 3), 2, "")]

    # ---- sec2_data.tex: remaining recon 3(a) prose (T6 review MINOR-1) ----
    if main:
        # The median-positive-dose parenthetical was removed from sec2 on 2026-08-30 with the
        # specification change (the topic condition is now dose > 0), so its three pins are gone and
        # bal2/med_rx with them. The Zenou worked example was NOT removed: it was recomputed on
        # dose > 0 (26 persons / 325 possible / 320 pairs became 35 / 595 / 590) and its pins are
        # live above, repointed at the new sentence. An earlier version of this comment claimed the
        # Zenou sentence had been deleted; it had not, and a pin was dropped on that false premise.
        T += [("sec2 lowest dose bin econ 20%", "sec2_data.tex",
               r"pairs: " + NUM + r" percent of economics pairs fall in the lowest dose bin",
               round(main["econ_dose_bins_pct"]["0"]), 1, ""),
              ("sec2 lowest dose bin chem 24%", "sec2_data.tex",
               r"as do " + NUM + r" percent in chemistry",
               round(main["chem_dose_bins_pct"]["0"]), 1, ""),
              ("sec2 lowest dose bin math 69%", "sec2_data.tex",
               r"specialised, " + NUM + r" percent of pairs sit in that bin",
               round(main["math_dose_bins_pct"]["0"]), 1, ""),
              # 2026-08-30: the body carried this exclusion twice, once in the prose and again in
              # the Figure 2 caption eight lines below, same two numbers on one page. The prose
              # copy is gone (a technical qualifier on how the shares were computed belongs in the
              # note, per N3 and supervisor comment #8), so both pins now watch the caption's wording.
              ("sec2 no-dose exclusions chem 5", "sec2_data.tex",
               r"" + NUM + r" chemistry and " + NUM + r" mathematics relations lack a pre-arrival portfolio",
               main["chem_dose_na_relations"], 1, ""),
              ("sec2 no-dose exclusions math 80", "sec2_data.tex",
               r"" + NUM + r" chemistry and " + NUM + r" mathematics relations lack a pre-arrival portfolio",
               main["math_dose_na_relations"], 2, ""),
              ("sec2 balance econ pub_pre -0.16", "sec2_data.tex",
               r"standardized difference \$-\$" + NUM + r", the difference in means",
               abs(round(main["econ_balance"]["pub_pre"]["std_diff"], 2)), 1, ""),
              ("sec2 balance econ age_gap +0.17", "sec2_data.tex",
               r"academic age \(\$\+\$" + NUM + r"\)",
               round(main["econ_balance"]["age_gap"]["std_diff"], 2), 1, ""),
              ("sec2 balance chem pub_pre +0.20", "sec2_data.tex",
               r"runs the other way \(\$\+\$" + NUM + r"\)",
               round(main["chem_balance"]["pub_pre"]["std_diff"], 2), 1, ""),
              ("sec2 balance math largest 0.14", "sec2_data.tex",
               r"in mathematics the largest difference is " + NUM,
               max(round(abs(main["math_balance"][v]["std_diff"]), 2)
                   for v in ("pub_pre", "y_pre", "age_gap")), 1, ""),
              ("sec2 FWCI-missing econ 27.5%", "sec2_data.tex",
               r"First, " + NUM + r" percent of the distinct works",
               main["econ_works_nofwci_pct"], 1, "")]
        cap_rx = (NUM + r" enter through the roster alone, " + NUM
                  + r" through the network alone, and " + NUM + r" through both, giving " + NUM
                  + r" relations across " + NUM + r" incumbents and " + NUM + r" arrival events")
        T += [(f"sec2 exposure caption {n}", "sec2_data.tex", cap_rx, v, g, "") for n, v, g in (
              ("roster-only 3,983", main["econ_relations"]["dept_only"], 1),
              ("network-only 1,817", main["econ_relations"]["network"], 2),
              ("both 669", main["econ_relations"]["both"], 3),
              ("relations 6,643", main["econ_relations"]["total"], 4),
              ("incumbents 822", main["econ_persons"], 5),
              ("events 113", main["econ_events"], 6))]
        if carried:
            T += [("sec2 FWCI-missing chem 29.8%", "sec2_data.tex",
                   r"chemistry and mathematics, " + NUM + r" and " + NUM + r" percent of the",
                   carried["chem_units_nofwci_pct"], 1, ""),
                  ("sec2 FWCI-missing math 28.8%", "sec2_data.tex",
                   r"chemistry and mathematics, " + NUM + r" and " + NUM + r" percent of the",
                   carried["math_units_nofwci_pct"], 2, ""),
                  ("sec2 genuine missing econ 0.5%", "sec2_data.tex",
                   r"remainder, " + NUM + r" percent in economics and no more than " + NUM
                   + r" percent in the", main["econ_works_genuine_pct"], 1, ""),
                  ("sec2 genuine missing chem/math cap 0.2%", "sec2_data.tex",
                   r"remainder, " + NUM + r" percent in economics and no more than " + NUM
                   + r" percent in the",
                   max(carried["chem_units_genuine_pct"], carried["math_units_genuine_pct"]), 2, ""),
                  ("sec2 fellowship entries 205", "sec2_data.tex",
                   r"population: " + NUM + r" of the " + NUM + r" verified economics roster entries",
                   carried.get("econ_fellow_evidence_rows", float("nan")), 1, ""),
                  ("sec2 verified econ roster 1008", "sec2_data.tex",
                   r"population: " + NUM + r" of the " + NUM + r" verified economics roster entries",
                   carried["roster_people"]["econ"], 2, ""),
                  ("sec2 centre roster added chem 134", "sec2_data.tex",
                   r"adding " + NUM + r" and " + NUM + r" academics respectively",
                   carried.get("chem_centre_added", float("nan")), 1, ""),
                  ("sec2 centre roster added math 28", "sec2_data.tex",
                   r"adding " + NUM + r" and " + NUM + r" academics respectively",
                   carried.get("math_centre_added", float("nan")), 2, "")]
        if p3:
            # How the panel empties out (2026-08-30). The sentence exists to show that leaving at
            # the first joint publication is the SAME rule before and after the arrival, not an
            # extra restriction, so all three groups are pinned and the ledger asserts they
            # partition the panel.
            ES = p3["econ"]["exit_split"]
            exit_rx = (r"In economics " + NUM + r" pairs tie before the arrival and " + NUM
                       + r" after it, and " + NUM + r" never tie at all")
            T += [("sec2 P3 exits before arrival 1,619", "sec2_data.tex", exit_rx,
                   ES["first_tie_before_arrival"], 1, ""),
                  ("sec2 P3 exits after arrival 1,990", "sec2_data.tex", exit_rx,
                   ES["first_tie_after_arrival"], 2, ""),
                  ("sec2 P3 never tie 84,567", "sec2_data.tex", exit_rx,
                   ES["never_tie"], 3, "")]
            T += [("sec2 P3 econ pairs 23,758", "sec2_data.tex",
                   r"gives " + NUM + r" pairs across the " + NUM + r" events",
                   p3["econ"]["pairs"], 1, ""),
                  ("sec2 P3 econ events-with-pairs 86", "sec2_data.tex",
                   r"gives " + NUM + r" pairs across the " + NUM + r" events",
                   p3["econ"]["events_with_pairs"], 2, ""),
                  ("sec2 P3 econ events-without-pairs 30", "sec2_data.tex",
                   r"the other " + NUM + r" events have fewer than two",
                   main["econ_events"] - p3["econ"]["events_with_pairs"], 1, ""),
                  ("sec2 P3 chem pairs 2,466", "sec2_data.tex",
                   r"in chemistry " + NUM + r" pairs in " + NUM + r" events",
                   p3["chemistry"]["pairs"], 1, ""),
                  ("sec2 P3 chem events 33", "sec2_data.tex",
                   r"in chemistry " + NUM + r" pairs in " + NUM + r" events",
                   p3["chemistry"]["events_with_pairs"], 2, ""),
                  ("sec2 P3 math pairs 2,770", "sec2_data.tex",
                   r"in mathematics " + NUM + r" pairs in " + NUM + r" events",
                   p3["math_stats"]["pairs"], 1, ""),
                  ("sec2 P3 math events 31", "sec2_data.tex",
                   r"in mathematics " + NUM + r" pairs in " + NUM + r" events",
                   p3["math_stats"]["events_with_pairs"], 2, "")]

    # ---- appendix_funnel.tex: steps 4-8, notes, tab:na percentages, tab:events (T6 review MINOR-1/2) ----
    if main and carried and p3:
        fun_note = (r"for chemistry the corresponding counts are " + NUM + r" incumbents, " + NUM
                    + r" relations, and " + NUM + r" / " + NUM + r" / " + NUM
                    + r" panel rows; for mathematics, " + NUM + r" incumbents, " + NUM
                    + r" relations, and " + NUM + r" / " + NUM + r" / " + NUM + r" panel rows")
        pairs_note = (r"network\): " + NUM + r" pairs in economics, " + NUM
                      + r" in chemistry and " + NUM + r" in mathematics")
        ev_note = (r"\\REV\{\(" + NUM + r" economics, " + NUM + r" chemistry, " + NUM
                   + r" mathematics\)\.\}")
        na_note = (r"shares are " + NUM + r"\\% / " + NUM + r"\\% / " + NUM
                   + r"\\% for chemistry and " + NUM + r"\\% / " + NUM + r"\\% / " + NUM
                   + r"\\% for mathematics")
        ep = main["econ_py_decomp"]
        na_pct = {}
        for d, dec in (("econ", ep), ("chem", carried["chem_py_decomp"]), ("math", carried["math_py_decomp"])):
            empty = dec.get("empty_out_of_employment", dec.get("empty_no_record"))
            observed = dec["y_val"] + dec.get("zero", 0)
            na_pct[d] = [round(100 * empty / dec["rows"], 1),
                         round(100 * dec["genuine_missing"] / dec["rows"], 1),
                         round(100 * observed / dec["rows"], 1)]
        T += [("funnel step 4 events econ 113", "appendix_funnel.tex",
               r"origin criteria & \\REV\{" + NUM + r" econ\., " + NUM + r" chem\., " + NUM + r" math\.\}",
               main["econ_events"], 1, ""),
              ("funnel step 4 events chem 38", "appendix_funnel.tex",
               r"origin criteria & \\REV\{" + NUM + r" econ\., " + NUM + r" chem\., " + NUM + r" math\.\}",
               main["chem_events"], 2, ""),
              ("funnel step 4 events math 33", "appendix_funnel.tex",
               r"origin criteria & \\REV\{" + NUM + r" econ\., " + NUM + r" chem\., " + NUM + r" math\.\}",
               main["math_events"], 3, ""),
              ("funnel step 5 econ incumbents 822", "appendix_funnel.tex",
               r"two-hop network \(economics\) & \\REV\{" + NUM + r" incumbents\}",
               main["econ_persons"], 1, ""),
              ("funnel step 6 econ relations 6,643", "appendix_funnel.tex",
               r"Incumbent--event relations \(economics\) & \\REV\{" + NUM + r"\}",
               main["econ_relations"]["total"], 1, ""),
              ("funnel step 7 econ P1 rows 73,073", "appendix_funnel.tex",
               r"Panel 1 rows, incumbent \$\\times\$ event \$\\times\$ year \(economics\) & \\REV\{"
               + NUM + r"\}", carried["panel_rows"]["econ"][0], 1, ""),
              ("funnel step 8 econ P2 rows 111,448", "appendix_funnel.tex",
               r"Panel 2 rows, incumbent \$\\times\$ star \$\\times\$ year \(economics\) & \\REV\{"
               + NUM + r"\}", carried["panel_rows"]["econ"][1], 1, "")]
        T += [(f"funnel note {n}", "appendix_funnel.tex", fun_note, v, g, "") for n, v, g in (
              ("chem incumbents 470", main["chem_persons"], 1),
              ("chem relations 2,785", main["chem_relations"]["total"], 2),
              ("chem P1 rows 30,635", carried["panel_rows"]["chem"][0], 3),
              ("chem P2 rows 46,168", carried["panel_rows"]["chem"][1], 4),
              ("chem P3 rows 39,242", p3["chemistry"]["rows"], 5),
              ("math incumbents 481", main["math_persons"], 6),
              ("math relations 1,810", main["math_relations"]["total"], 7),
              ("math P1 rows 19,910", carried["panel_rows"]["math"][0], 8),
              ("math P2 rows 30,314", carried["panel_rows"]["math"][1], 9),
              ("math P3 rows 46,010", p3["math_stats"]["rows"], 10))]
        T += [("funnel note eligible pairs econ 23,758", "appendix_funnel.tex", pairs_note,
               p3["econ"]["pairs"], 1, ""),
              ("funnel note eligible pairs chem 2,466", "appendix_funnel.tex", pairs_note,
               p3["chemistry"]["pairs"], 2, ""),
              ("funnel note eligible pairs math 2,770", "appendix_funnel.tex", pairs_note,
               p3["math_stats"]["pairs"], 3, ""),
              ("funnel tab:events total econ 113", "appendix_funnel.tex", ev_note,
               main["econ_events"], 1, ""),
              ("funnel tab:events total chem 38", "appendix_funnel.tex", ev_note,
               main["chem_events"], 2, ""),
              ("funnel tab:events total math 33", "appendix_funnel.tex", ev_note,
               main["math_events"], 3, ""),
              ("funnel tab:na econ outside-employment 8.1%", "appendix_funnel.tex",
               r"Outside employment years & \\REV\{" + NUM + r"\\%\}", na_pct["econ"][0], 1, ""),
              ("funnel tab:na econ genuinely-missing 5.2%", "appendix_funnel.tex",
               r"no usable output record & \\REV\{" + NUM + r"\\%\}", na_pct["econ"][1], 1, ""),
              ("funnel tab:na econ observed 86.8%", "appendix_funnel.tex",
               r"including true zeros\) & \\REV\{" + NUM + r"\\%\}", na_pct["econ"][2], 1, "")]
        T += [(f"funnel tab:na {n}", "appendix_funnel.tex", na_note, v, g, "") for n, v, g in (
              ("chem outside 6.8%", na_pct["chem"][0], 1),
              ("chem genuine 1.4%", na_pct["chem"][1], 2),
              ("chem observed 91.8%", na_pct["chem"][2], 3),
              ("math outside 10.5%", na_pct["math"][0], 4),
              ("math genuine 5.0%", na_pct["math"][1], 5),
              ("math observed 84.6%", na_pct["math"][2], 6))]
    # R1 P3 N12 part 2: Section 2.4 prints the same empty / missing shares in prose (sec2_data.tex)
    if main and carried:
        T += sec2_empty_share_claims(main, carried)

    # ---- the two hand-typed tables (T6 review MINOR-2) ----
    if main and carried and p3:
        def disc_row(label):
            return (r"\\REV\{" + label + r"\} & \\REV\{" + NUM + r"\} & \\REV\{" + NUM
                    + r"\} & \\REV\{" + NUM + r"\}")   # 2026-09-12: Panel-1 rows column dropped (Table 1 has it)
        for label, d in (("Economics", "econ"), ("Chemistry", "chem"),
                         (r"Mathematics \\& Statistics", "math")):
            T += [(f"tab_disciplines {d} events", "tab_disciplines.tex", disc_row(label),
                   main[f"{d}_events"], 1, ""),
                  (f"tab_disciplines {d} incumbents", "tab_disciplines.tex", disc_row(label),
                   main[f"{d}_persons"], 2, ""),
                  (f"tab_disciplines {d} relations", "tab_disciplines.tex", disc_row(label),
                   main[f"{d}_relations"]["total"], 3, "")]
        panels_note = (r"Row counts are for economics; the corresponding counts are " + NUM
                       + r" / " + NUM + r" / " + NUM + r" for chemistry and " + NUM + r" / "
                       + NUM + r" / " + NUM + r" for mathematics")
        T += [("tab_panels P1 econ rows 73,073", "tab_panels_overview.tex",
               r"similarity dose \$\\times\$ post & \\REV\{" + NUM + r"\}",
               carried["panel_rows"]["econ"][0], 1, ""),
              ("tab_panels P2 econ rows 111,448", "tab_panels_overview.tex",
               r"first coauthorship with the star & star arrival & \\REV\{" + NUM + r"\}",
               carried["panel_rows"]["econ"][1], 1, ""),
              ("tab_panels P3 econ rows 393,007", "tab_panels_overview.tex",
               r"first coauthorship within the pair & star arrival & \\REV\{" + NUM + r"\}",
               p3["econ"]["rows"], 1, "")]
        T += [(f"tab_panels note {n}", "tab_panels_overview.tex", panels_note, v, g, "") for n, v, g in (
              ("chem P1 30,635", carried["panel_rows"]["chem"][0], 1),
              ("chem P2 46,168", carried["panel_rows"]["chem"][1], 2),
              ("chem P3 39,242", p3["chemistry"]["rows"], 3),
              ("math P1 19,910", carried["panel_rows"]["math"][0], 4),
              ("math P2 30,314", carried["panel_rows"]["math"][1], 5),
              ("math P3 46,010", p3["math_stats"]["rows"], 6))]
    # ---- appendix_robustness.tex tab:balance + appendix_variables.tex tab:quantiles (T8 carried MINOR) ----
    if main:
        def bal_row(label):
            # std-diff cells carry their printed $-$/$+$ sign into the comparison (a sign
            # flip in the tex must FAIL — M2 milestone review MINOR-6)
            triple = r" & \\REV\{" + NUM + r"\} & \\REV\{" + NUM + r"\} & \\REV\{" + SNUM + r"\}"
            return r"\\REV\{" + label + r"\}" + triple * 3

        for var, label in (("pub_pre", "Publications per year"),
                            ("y_pre", "FWCI-weighted output"),
                            ("age_gap", r"Age gap to star \(years\)")):
            rx = bal_row(label)
            for i, d in enumerate(("econ", "chem", "math")):
                base = i * 3
                b = main[f"{d}_balance"][var]
                T += [(f"tab_balance {d} {var} high", "appendix_robustness.tex", rx,
                       round(b["hi"], 2), base + 1, ""),
                      (f"tab_balance {d} {var} low", "appendix_robustness.tex", rx,
                       round(b["lo"], 2), base + 2, ""),
                      (f"tab_balance {d} {var} std_diff", "appendix_robustness.tex", rx,
                       round(b["std_diff"], 2), base + 3, "")]
        # the notes' recap of the two motivating imbalances, signed as printed
        note_rx = (r"publication imbalance \(" + SNUM + r" economics, " + SNUM + r" chemistry\)")
        T += [("tab_balance notes econ pub_pre 0.04", "appendix_robustness.tex", note_rx,
               round(main["econ_balance"]["pub_pre"]["std_diff"], 2), 1, ""),
              ("tab_balance notes chem pub_pre +0.26", "appendix_robustness.tex", note_rx,
               round(main["chem_balance"]["pub_pre"]["std_diff"], 2), 2, "")]

        def quant_row(disc_label):
            five = "".join(r" & \\REV\{" + NUM + r"\}" for _ in range(5))
            return (r"\\REV\{" + disc_label + r"\} & \\REV\{Output per person-year\}" + five
                    + r".*?& \\REV\{Similarity dose\}" + five)

        for disc_label, d in (("Economics", "econ"), ("Chemistry", "chem"), ("Mathematics", "math")):
            rx = quant_row(disc_label)
            qo, qd = main[f"{d}_q_output"], main[f"{d}_q_dose"]
            for j, lab in enumerate(("p25", "median", "p75", "p95")):
                T.append((f"tab_quantiles {d} output {lab}", "appendix_variables.tex", rx,
                          qo["q"][j], j + 1, ""))
                T.append((f"tab_quantiles {d} dose {lab}", "appendix_variables.tex", rx,
                          qd["q"][j], j + 6, ""))
            T.append((f"tab_quantiles {d} output max", "appendix_variables.tex", rx, qo["max"], 5, ""))
            T.append((f"tab_quantiles {d} dose max", "appendix_variables.tex", rx, qd["max"], 10, ""))

        if carried:
            ss_rx = (r"similarly skewed \(chemistry median " + NUM + r", quartiles " + NUM + r"--" + NUM
                      + r"; mathematics median " + NUM + r", quartiles " + NUM + r"--" + NUM
                      + r", from the identity-verified records\)")
            cs, ms = carried["chem_star_stock"], carried["math_star_stock"]
            T += [("tab_quantiles note chem median 1,865", "appendix_variables.tex", ss_rx, cs["med"], 1, ""),
                  ("tab_quantiles note chem q25 1,044", "appendix_variables.tex", ss_rx, cs["q25"], 2, ""),
                  ("tab_quantiles note chem q75 4,174", "appendix_variables.tex", ss_rx, cs["q75"], 3, ""),
                  ("tab_quantiles note math median 969", "appendix_variables.tex", ss_rx, ms["med"], 4, ""),
                  ("tab_quantiles note math q25 251", "appendix_variables.tex", ss_rx, ms["q25"], 5, ""),
                  ("tab_quantiles note math q75 1,917", "appendix_variables.tex", ss_rx, ms["q75"], 6, "")]

    # ---- M2 milestone fix wave: main.tex + the remaining unchecked numerals (MAJORs 2-3) ----
    if p3:
        # main.tex Section-1 restatement of the Panel 3 economics headline, printed at 2 dp
        E = p3["econ"]
        main_rx = (r"is " + NUM + r" percentage points higher after the arrival, against a "
                   + r"pre-arrival rate of " + NUM + r" percent a year")
        T += [("main intro P3 econ fall 0.13", "main.tex", main_rx, round(abs(E["ate_pp"]), 2), 1, ""),
              ("main intro P3 econ pre rate 0.40", "main.tex", main_rx, round(E["rate_pre_pp"], 2), 2, ""),
              ("p3 fig caption year cap 2024", "sec4_p3.tex",
               r"on calendar years up to " + NUM, p3["year_cap"], 1, "")]
    if funnel:
        # sec2 prose roundings of the snapshot/benchmark funnel (steps 1-3)
        bench_rx = r"covers " + NUM + r" million works in " + NUM + r" subfield--year--type cells"
        T += [("sec2 snapshot 510 million works", "sec2_data.tex",
               r"contains " + NUM + r" million work records",
               round(funnel["works_snapshot"] / 1e6), 1, ""),
              ("sec2 benchmark 376 million works", "sec2_data.tex", bench_rx,
               round(funnel["works_benchmarkable"] / 1e6), 1, ""),
              ("sec2 benchmark 543,037 cells", "sec2_data.tex", bench_rx,
               funnel["benchmark_cells"], 2, ""),
              ("sec2 articles+reviews 258 million works", "sec2_data.tex",
               r"it covers " + NUM + r" million works",
               round(funnel["works_articles_reviews"] / 1e6), 1, "")]
        # R3 (2026-09-10): the four sec2 numbers that had no source until the funnel ledger gained
        # keys — the OpenAlex subfield count, the U1 ranking-pool size (printed to 0.1 million), the
        # roster spell-start ceilings (the first year with no chemistry spell start = chem max + 1;
        # the mathematics range opens at math max + 1 and "after <math max>"), and the snapshot
        # release date (day and year pinned; the month name is part of the regex, so a changed
        # month reads as pattern-not-found).
        rel = datetime.date.fromisoformat(funnel["snapshot_release_date"])
        rms = funnel["roster_spell_max_start"]
        rel_rx = r"The analysis uses the " + NUM + " " + rel.strftime("%B") + " " + NUM + r" release"
        T += [("sec2 OpenAlex subfields 252", "sec2_data.tex",
               r"there are " + NUM + r" subfields across all of science",
               funnel["openalex_subfields"], 1, ""),
              ("sec2 ranking pool 10.5 million authors", "sec2_data.tex",
               r"extracted universe of " + NUM + r" million authors",
               round(funnel["u1_universe"]["authors"] / 1e6, 1), 1, ""),
              ("sec2 chem roster no spell starts in 2024", "sec2_data.tex",
               r"chemistry rosters record no employment spells beginning in " + NUM,
               rms["chem"] + 1, 1, ""),
              ("sec2 math roster no spell starts from 2021", "sec2_data.tex",
               r"mathematics rosters record none for " + NUM + r"--" + NUM,
               rms["math"] + 1, 1, ""),
              ("sec2 math roster edge after 2020", "sec2_data.tex",
               r"for mathematics after " + NUM, rms["math"], 1, ""),
              ("sec2 chem roster edge nominal in 2024", "sec2_data.tex",
               r"for chemistry in " + NUM + r" and for mathematics after", rms["chem"] + 1, 1, ""),
              ("sec2 snapshot release day 26", "sec2_data.tex", rel_rx, rel.day, 1, ""),
              ("sec2 snapshot release year 2026", "sec2_data.tex", rel_rx, rel.year, 2, "")]
    if carried:
        # department counts + arrival-year spans, derived from the events_by_school_* ledgers
        ebs = {d: carried[f"events_by_school_{d}"] for d in ("econ", "chem", "math")}
        yrs = {d: sorted(y for v in ebs[d].values() for y in v) for d in ebs}
        dept_rx = (r"covers " + NUM + r" economics departments, " + NUM
                   + r" chemistry departments, and " + NUM + r" mathematics and statistics departments")
        span_rx = (r"arrival events spanning " + NUM + r"--" + NUM + r", " + NUM + r"--" + NUM
                   + r", and " + NUM + r"--" + NUM + r" respectively")
        T += [("sec2 departments econ 11", "sec2_data.tex", dept_rx, len(ebs["econ"]), 1, ""),
              ("sec2 departments chem 8", "sec2_data.tex", dept_rx, len(ebs["chem"]), 2, ""),
              ("sec2 departments math 6", "sec2_data.tex", dept_rx, len(ebs["math"]), 3, "")]
        T += [(f"sec2 arrival span {n}", "sec2_data.tex", span_rx, v, g, "") for n, v, g in (
              ("econ first 1999", yrs["econ"][0], 1), ("econ last 2024", yrs["econ"][-1], 2),
              ("chem first 2001", yrs["chem"][0], 3), ("chem last 2023", yrs["chem"][-1], 4),
              ("math first 2002", yrs["math"][0], 5), ("math last 2020", yrs["math"][-1], 6))]
        # the verified-roster sentence
        roster_rx = r"rosters contain " + NUM + r", " + NUM + r", and " + NUM + r" persons"
        T += [("sec2 rosters econ 1008", "sec2_data.tex", roster_rx, carried["roster_people"]["econ"], 1, ""),
              ("sec2 rosters chem 518", "sec2_data.tex", roster_rx, carried["roster_people"]["chem"], 2, ""),
              ("sec2 rosters math 573", "sec2_data.tex", roster_rx, carried["roster_people"]["math"], 3, "")]
        # tab:events, cell by cell: each university's arrival-year list vs events_by_school_*
        ev_cells = (r"\} & \\REV\{([^{}]*)\} & \\REV\{([^{}]*)\} & \\REV\{([^{}]*)\}")
        for tex_label, led_key in (("ANU", "anu"), ("Adelaide", "adelaide"), ("Deakin", "deakin"),
                                    ("Macquarie", "macquarie"), ("Melbourne", "melbourne"),
                                    ("Monash", "monash"), ("Queensland", "uq"), ("Sydney", "sydney"),
                                    ("UNSW", "unsw"), ("UTS", "uts"), ("UWA", "uwa")):
            rx = r"\\REV\{" + tex_label + ev_cells
            for g, d in ((1, "econ"), (2, "chem"), (3, "math")):
                T.append((f"tab:events {tex_label} {d} years", "appendix_funnel.tex", rx,
                          ("years", ebs[d].get(led_key, [])), g, ""))
    if main:
        # event-ledger totals restated in sec2 prose (2.2 and 2.5) and the exposure paragraph
        ev3_rx = (r"event ledgers contain " + NUM + r" events in economics, " + NUM
                  + r" in chemistry, and " + NUM + r" in mathematics")
        # 2026-09-12: the prose recital of the three event counts was replaced by a pointer to
        # Table 2 (author: do not repeat the table in prose); tab_disciplines pins cover them.
        # 2026-08-30: §2.2 recited chemistry's and mathematics' counts in prose while Table 2
        # listed the same six numbers three pages later. The prose copy is gone and the body now
        # points at the table; tab_disciplines' own twelve pins keep every one of these covered.
        zr_rx = r"In " + NUM + r" of the " + NUM + r" economics events the archived roster"
        T += [("sec2 zero-roster events 1", "sec2_data.tex", zr_rx, main["econ_zero_roster_events"], 1, ""),
              ("sec2 zero-roster of 113 events", "sec2_data.tex", zr_rx, main["econ_events"], 2, "")]
        # fig:dose caption: observed-dose counts (total - dose-NA) and the two NA exclusions
        obs_rx = (r"observed dose \(" + NUM + r" economics, " + NUM + r" chemistry, "
                  + NUM + r" mathematics\)")
        T += [(f"sec2 dose caption observed {d}", "sec2_data.tex", obs_rx,
               main[f"{d}_relations"]["total"] - main[f"{d}_dose_na_relations"], g, "")
              for g, d in ((1, "econ"), (2, "chem"), (3, "math"))]
        lack_rx = (r"; " + NUM + r" chemistry and " + NUM + r" mathematics relations lack a "
                   + r"pre-arrival portfolio")
        T += [("sec2 dose caption chem NA 5", "sec2_data.tex", lack_rx,
               main["chem_dose_na_relations"], 1, ""),
              ("sec2 dose caption math NA 80", "sec2_data.tex", lack_rx,
               main["math_dose_na_relations"], 2, "")]
        # §2.5's prose recited 116/38/33 a THIRD time (after §2.2's event-ledger sentence and
        # Table 2 itself) inside an "economics is the anchor" framing. The framing was an opinion
        # in a data section and the counts were duplicates; both are gone, and the three numbers
        # stay covered by the event-ledger pins above and tab_disciplines' own twelve.
        # sec3 inference paragraph: event/cluster counts
        T += [("sec3 econ 113 events", "sec3_strategy.tex",
               r"With \\REV\{" + NUM + r"\} events in economics", main["econ_events"], 1, ""),
              ("sec3 chem 38 events", "sec3_strategy.tex",
               r"with \\REV\{" + NUM + r"\} events in chemistry and \\REV\{" + NUM
               + r"\} in mathematics", main["chem_events"], 1, ""),
              ("sec3 math 33 events", "sec3_strategy.tex",
               r"with \\REV\{" + NUM + r"\} events in chemistry and \\REV\{" + NUM
               + r"\} in mathematics", main["math_events"], 2, "")]
        if p3:
            T.append(("sec3 econ 86 events with pairs", "sec3_strategy.tex",
                      r"\\REV\{\(" + NUM + r" of them contributing pairs to Panel 3\)\}",
                      p3["econ"]["events_with_pairs"], 1, ""))
    if sw:
        # the appendix's summary prose (the tab:agg -0.142 / -0.378 restated in words)
        T += [("estimator prose summary -0.141", "appendix_estimator.tex",
               r"which gives \$" + NUM + r"\$: the average change",
               round(sw["weighted_avg_effect"], 3), 1, ""),
              ("estimator prose per-unit -0.368", "appendix_estimator.tex",
               r"rescales this to \$" + NUM + r"\$ per unit of dose",
               round(sw["coef_check"]["ate"], 3), 1, "")]

    # ---- sec4_p1.tex / sec4_p2.tex: the Panel 1 and Panel 2 prose vs the p1p2 ledger
    #      (2026-08-30 W1b — the two Section 4.1 blocks completing the panel trio) ----
    pp = led["p1p2"]
    if pp:
        PR1 = {d: pp[f"p1_{d}"] for d in ("econ", "chemistry", "math_stats")}
        PR2 = {d: pp[f"p2_{d}"] for d in ("econ", "chemistry", "math_stats")}
        loeo, ds = pp["p1_loeo_econ"], pp["p1_doublestar_econ"]

        def _h(cell, key, ell):
            return next(x["est"] for x in cell[key] if x["ell"] == ell)

        # -- Panel 1, ¶1: weighted-average effects, per-unit ATEs + SEs + percent conversions
        wavg_rx = (r"output falls by " + NUM + r" log points in economics, " + NUM
                   + r" in chemistry and " + NUM + r" in mathematics and statistics")
        T += [(f"p1 prose weighted avg [{sh}]", "sec4_p1.tex", wavg_rx,
               abs(PR1[f]["weighted_avg_effect"]), g, "")
              for g, (f, sh) in enumerate((("econ", "econ"), ("chemistry", "chem"),
                                           ("math_stats", "math")), start=1)]
        # 2026-09-01: the two routes estimated separately. Section 3.3 promises this split and
        # the runs always existed; Section 4.1 used to say the routes were not separated.
        route_rx = (r"the economics fall is\s*" + NUM + r" log points through the network "
                    r"\(standard error " + NUM + r"\) and " + NUM + r" through\s*the roster \("
                    + NUM + r"\)")
        T += [(f"p1 prose by-route {nm}", "sec4_p1.tex", route_rx, val, g, "")
              for g, (nm, val) in enumerate((
                  ("network ate", abs(PR1["econ"]["by_route"]["network"]["ate_log"])),
                  ("network se", PR1["econ"]["by_route"]["network"]["se_person"]),
                  ("roster ate", abs(PR1["econ"]["by_route"]["roster"]["ate_log"])),
                  ("roster se", PR1["econ"]["by_route"]["roster"]["se_person"])), start=1)]
        # 2026-09-01: the same weighted average, converted to percent. Until today the body gave
        # a percentage only for the rescaled dose=1 case (31.5/20.9/11.9), which no incumbent
        # experiences; these are the declines at the doses actually carried.
        wavg_pct_rx = (r"statistics, \\REV\{declines of " + NUM + r", " + NUM + r" and " + NUM
                       + r" percent\}")
        T += [(f"p1 prose weighted avg percent [{sh}]", "sec4_p1.tex", wavg_pct_rx,
               abs(PR1[f]["avg_effect_pct_at_observed_dose"]), g, "")
              for g, (f, sh) in enumerate((("econ", "econ"), ("chemistry", "chem"),
                                           ("math_stats", "math")), start=1)]
        ate_rx = (r"a fall of " + NUM + r" log points in economics \(standard error " + NUM
                  + r" clustered by incumbent, " + NUM + r" by event\), " + NUM
                  + r" in chemistry \(" + NUM + r" and " + NUM + r"\) and " + NUM
                  + r" in mathematics \(" + NUM + r" and " + NUM
                  + r"\), which the table converts to declines of " + NUM + r", " + NUM
                  + r" and " + NUM + r" percent")
        for g, (name, want) in enumerate((
                ("ATE econ", abs(PR1["econ"]["ate_log"])),
                ("se person econ", PR1["econ"]["se_person"]),
                ("se event econ", PR1["econ"]["se_event"]),
                ("ATE chem", abs(PR1["chemistry"]["ate_log"])),
                ("se person chem", PR1["chemistry"]["se_person"]),
                ("se event chem", PR1["chemistry"]["se_event"]),
                ("ATE math", abs(PR1["math_stats"]["ate_log"])),
                ("se person math", PR1["math_stats"]["se_person"]),
                ("se event math", PR1["math_stats"]["se_event"]),
                ("pct econ", abs(PR1["econ"]["ate_pct"])),
                ("pct chem", abs(PR1["chemistry"]["ate_pct"])),
                ("pct math", abs(PR1["math_stats"]["ate_pct"]))), start=1):
            T.append((f"p1 prose {name}", "sec4_p1.tex", ate_rx, want, g, ""))
        T += [("p1 prose joint effects econ p<0.001", "sec4_p1.tex",
               r"is rejected in economics \(\$p<" + NUM + r"\$\) and in chemistry \(\$p=" + NUM + r"\$\)",
               ("lt", PR1["econ"]["p_joint_effects_person"], 0.001), 1, ""),
              ("p1 prose joint effects chem p=0.008", "sec4_p1.tex",
               r"is rejected in economics \(\$p<" + NUM + r"\$\) and in chemistry \(\$p=" + NUM + r"\$\)",
               round(PR1["chemistry"]["p_joint_effects_person"], 3), 2, ""),
              ("p1 prose math CI lo", "sec4_p1.tex",
               r"interval runs from \$-\$" + NUM + r" to " + NUM + r" log points",
               abs(PR1["math_stats"]["ci95_person"][0]), 1, ""),
              ("p1 prose math CI hi", "sec4_p1.tex",
               r"interval runs from \$-\$" + NUM + r" to " + NUM + r" log points",
               PR1["math_stats"]["ci95_person"][1], 2, "")]
        mjt_rx = (r"the joint test is marginal \(\$p=" + NUM
                  + r"\$ with incumbent clusters, \$" + NUM + r"\$ with event clusters\)")
        T += [("p1 prose joint math person p=0.009", "sec4_p1.tex", mjt_rx,
               round(PR1["math_stats"]["p_joint_effects_person"], 3), 1, ""),
              ("p1 prose joint math event p=0.008", "sec4_p1.tex", mjt_rx,
               round(PR1["math_stats"]["p_joint_effects_event"], 3), 2, "")]
        # -- Panel 1, ¶2: the time path
        # 2026-09-12: the figure paragraph now reads the three fifth-year values off the figure
        # and points at Table A4 for the rest (author: pre-period verdict, shape in words, one
        # number); the five other horizon numbers are covered by the tab_p1_full cell pins.
        path_rx = (r"reaching \$-\$" + NUM + r" log points in the fifth year in economics and \$-\$"
                   + NUM + r" in chemistry, while mathematics stays flat until a fifth-year \$-\$" + NUM)
        for g, (name, want) in enumerate((
                ("econ ell=5", abs(_h(PR1["econ"], "horizons", 5))),
                ("chem ell=5", abs(_h(PR1["chemistry"], "horizons", 5))),
                ("math ell=5", abs(_h(PR1["math_stats"], "horizons", 5)))), start=1):
            T.append((f"p1 prose path {name}", "sec4_p1.tex", path_rx, want, g, ""))
        # -- Panel 1, ¶4: the pre-arrival three-piece (placebo tests, LOEO, no-overlap subset)
        plc_rx = (r"passes in chemistry \(\$p=" + NUM + r"\$\) and mathematics \(\$p=" + NUM
                  + r"\$\) but rejects in economics \(\$p=" + NUM + r"\$\)")
        T += [("p1 prose placebo chem p=0.856", "sec4_p1.tex", plc_rx,
               round(PR1["chemistry"]["p_joint_placebo_person"], 3), 1, ""),
              ("p1 prose placebo math p=0.175", "sec4_p1.tex", plc_rx,
               round(PR1["math_stats"]["p_joint_placebo_person"], 3), 2, ""),
              ("p1 prose placebo econ p=0.003", "sec4_p1.tex", plc_rx,
               round(PR1["econ"]["p_joint_placebo_person"], 3), 3, "")]
        loeo_rx = (r"removing each of the " + NUM + r" economics arrivals one at a time leaves "
                   + r"the estimate between \$-\$" + NUM + r" and \$-\$" + NUM
                   + r", and no removal restores the placebo test \(the largest \$p\$ is "
                   + NUM + r"\)")
        T += [("p1 prose loeo removals 113", "sec4_p1.tex", loeo_rx, loeo["n_removals"], 1, ""),
              ("p1 prose loeo ate min", "sec4_p1.tex", loeo_rx, abs(loeo["ate_min"]), 2, ""),
              ("p1 prose loeo ate max", "sec4_p1.tex", loeo_rx, abs(loeo["ate_max"]), 3, ""),
              ("p1 prose loeo max placebo p", "sec4_p1.tex", loeo_rx,
               round(loeo["p_joint_placebo_max"], 3), 4, "")]
        dsc = pp["p1_doublestar_complement_econ"]
        dstar_rx = (r"On the " + NUM + r" overlapped events the placebo test rejects \(\$p=" + NUM
                    + r"\$\) and the estimate is \$-\$" + NUM + r" log points \(standard error " + NUM
                    + r"\); on the " + NUM + r" events with no earlier arrival it passes \(\$p=" + NUM
                    + r"\$\) and the estimate deepens to \$-\$" + NUM + r" \(" + NUM
                    + r"\); the joint post-arrival test rejects in both \(\$p<" + NUM + r"\$\)")
        T += [("p1 prose doublestar complement events 95", "sec4_p1.tex", dstar_rx, dsc["events"], 1, ""),
              ("p1 prose doublestar complement placebo p=0.003", "sec4_p1.tex", dstar_rx,
               round(dsc["p_joint_placebo"], 3), 2, ""),
              ("p1 prose doublestar complement ate 0.380", "sec4_p1.tex", dstar_rx, abs(dsc["ate_log"]), 3, ""),
              ("p1 prose doublestar complement se 0.069", "sec4_p1.tex", dstar_rx, dsc["se_person"], 4, ""),
              ("p1 prose doublestar events kept 18", "sec4_p1.tex", dstar_rx, ds["events_kept"], 5, ""),
              ("p1 prose doublestar placebo p=0.635", "sec4_p1.tex", dstar_rx,
               round(ds["p_joint_placebo"], 3), 6, ""),
              ("p1 prose doublestar ate 0.711", "sec4_p1.tex", dstar_rx, abs(ds["ate_log"]), 7, ""),
              ("p1 prose doublestar se 0.200", "sec4_p1.tex", dstar_rx, ds["se_person"], 8, ""),
              ("p1 prose doublestar effects p<0.001 (both)", "sec4_p1.tex", dstar_rx,
               ("lt", max(ds["p_joint_effects"], dsc["p_joint_effects"]), 0.001), 9, ""),
              ("p1 prose overlap count 95", "sec4_p1.tex",
               r"In economics, " + NUM + r" of the " + NUM + r" arrivals came within five years",
               dsc["events"], 1, ""),
              ("p1 prose overlap of 113", "sec4_p1.tex",
               r"In economics, " + NUM + r" of the " + NUM + r" arrivals came within five years",
               ds["events_dropped"] + ds["events_kept"], 2, ""),
              ("p1 prose bracket low 0.38", "sec4_p1.tex",
               r"between " + NUM + r" and " + NUM + r" log points per unit of dose",
               ("tol", abs(dsc["ate_log"]), 0.005), 1, ""),
              ("p1 prose bracket high 0.71", "sec4_p1.tex",
               r"between " + NUM + r" and " + NUM + r" log points per unit of dose",
               ("tol", abs(ds["ate_log"]), 0.005), 2, ""),
              ("p1 prose doublestar footnote dropped 95", "sec4_p1.tex",
               r"this drops " + NUM + r" of the " + NUM + r" economics arrivals",
               ds["events_dropped"], 1, ""),
              ("p1 prose doublestar footnote of 113", "sec4_p1.tex",
               r"this drops " + NUM + r" of the " + NUM + r" economics arrivals",
               ds["events_dropped"] + ds["events_kept"], 2, ""),
              ("p1 prose doublestar footnote same-year kept 4", "sec4_p1.tex",
               r"Same-year co-arrivals have no earlier member and are kept \(" + NUM
               + r" of the " + NUM + r"\)",
               ds["same_year_co_arrivals_among_kept"], 1, ""),
              ("p1 prose doublestar footnote same-year of 18", "sec4_p1.tex",
               r"Same-year co-arrivals have no earlier member and are kept \(" + NUM
               + r" of the " + NUM + r"\)",
               ds["events_kept"], 2, "")]
        # -- Panel 2, ¶1: ATEs + SEs, raw rates, joint tests
        # 2026-09-12: one standard error per estimate inside the clause; the three
        # event-clustered errors follow in their own sentence (author: one number per bracket).
        p2ate_rx = (r"rises after the\s*arrival by " + NUM
                    + r" percentage points in economics \(standard error " + NUM + r"\),\s*"
                    + NUM + r" in chemistry \(" + NUM + r"\) and " + NUM
                    + r" in mathematics and statistics \(" + NUM + r"\);\s*"
                    + r"event-clustered standard errors are " + NUM + r", " + NUM + r" and " + NUM)
        for g, (name, want) in enumerate((
                ("ATE econ", PR2["econ"]["ate_pp"]),
                ("se person econ", PR2["econ"]["se_person_pp"]),
                ("ATE chem", PR2["chemistry"]["ate_pp"]),
                ("se person chem", PR2["chemistry"]["se_person_pp"]),
                ("ATE math", PR2["math_stats"]["ate_pp"]),
                ("se person math", PR2["math_stats"]["se_person_pp"]),
                ("se event econ", PR2["econ"]["se_event_pp"]),
                ("se event chem", PR2["chemistry"]["se_event_pp"]),
                ("se event math", PR2["math_stats"]["se_event_pp"])), start=1):
            T.append((f"p2 prose {name}", "sec4_p2.tex", p2ate_rx, want, g, ""))
        raw_rx = (r"a first tie formed in only " + NUM + r"\s*percent of exposed incumbent--star "
                  + r"pairs in a given year in economics, " + NUM + r"\s*in chemistry and " + NUM
                  + r" in mathematics; over the arrival year and the five\s*years after it the raw "
                  + r"rate is " + NUM + r", " + NUM + r" and " + NUM + r" percent, several times\s*"
                  + r"the pre-arrival rate\.\\footnote\{Raw rates count only relation-years\s*"
                  + r"observable in the data, calendar years up to " + NUM)
        for g, (name, want) in enumerate((
                ("raw pre econ", PR2["econ"]["rate_pre_pp"]),
                ("raw pre chem", PR2["chemistry"]["rate_pre_pp"]),
                ("raw pre math", PR2["math_stats"]["rate_pre_pp"]),
                ("raw post econ", PR2["econ"]["rate_post_obs_pp"]),
                ("raw post chem", PR2["chemistry"]["rate_post_obs_pp"]),
                ("raw post math", PR2["math_stats"]["rate_post_obs_pp"]),
                ("year cap", pp["year_cap"])), start=1):
            T.append((f"p2 prose {name}", "sec4_p2.tex", raw_rx, want, g, ""))
        # 2026-09-12: the p-value chain is gone; the sentence names which clustering rejects.
        # "p<0.001 in both" is pinned on the larger of the two event-clustered ps; the mathematics
        # person-clustered p (0.025) is the only in-text p for the all-three claim.
        p2j_rx = (r"rejects in all three disciplines\s*with incumbent clusters \(mathematics \$p="
                  + NUM + r"\$\); with event clusters it\s*rejects in economics and chemistry "
                  + r"\(\$p<" + NUM + r"\$ in both\) but not in\s*mathematics \(\$p=" + NUM + r"\$\)")
        T += [("p2 prose joint math person p=0.066", "sec4_p2.tex", p2j_rx,
               round(PR2["math_stats"]["p_joint_effects_person"], 3), 1, ""),
              ("p2 prose joint econ+chem event p<0.001", "sec4_p2.tex", p2j_rx,
               ("lt", max(PR2["econ"]["p_joint_effects_event"], PR2["chemistry"]["p_joint_effects_event"]), 0.001), 2, ""),
              ("p2 prose joint math event p=0.109", "sec4_p2.tex", p2j_rx,
               round(PR2["math_stats"]["p_joint_effects_event"], 3), 3, "")]
        # -- Panel 2, ¶2: the time path + the figure caption's year cap
        p2path_rx = (r"the change is " + NUM + r" percentage points in the arrival year, peaks at "
                     + NUM + r" in the second year after, and eases to " + NUM
                     + r" by the fourth; chemistry reaches " + NUM
                     + r" in the fourth year; mathematics peaks at " + NUM + r" in the second")
        for g, (name, want) in enumerate((
                ("econ ell=0", _h(PR2["econ"], "horizons_pp", 0)),
                ("econ ell=2", _h(PR2["econ"], "horizons_pp", 2)),
                ("econ ell=4", _h(PR2["econ"], "horizons_pp", 4)),
                ("chem ell=4", _h(PR2["chemistry"], "horizons_pp", 4)),
                ("math ell=2", _h(PR2["math_stats"], "horizons_pp", 2))), start=1):
            T.append((f"p2 prose path {name}", "sec4_p2.tex", p2path_rx, want, g, ""))
        T.append(("p2 fig caption year cap 2024", "sec4_p2.tex",
                  r"by years since arrival, on calendar years up to " + NUM,
                  pp["year_cap"], 1, ""))
        # -- main.tex Section-1 findings: the Panel 2 economics magnitude, printed at 2 dp
        # 2026-08-30: the em dash was removed and the sentence split in two
        # (rules/thesis-writing.md S5 — a dash must not carry the main clause),
        # so the pinned wording moved with it. Same two numbers, same order.
        intro_rx = (r"first publish with the star by " + NUM
                    + r" percentage points, against a pre-arrival rate of " + NUM
                    + r" percent a year")
        # 2026-09-26 (supervisor round 4, #7: report the main Panel 1 result in the introduction,
        # as a percent): the economics full-overlap fall, 100*(exp(ate_log)-1) = -30.8, printed as
        # a whole percent (the SE's first nonzero digit is in the units place).
        intro_p1_rx = (r"In economics output is about " + NUM
                       + r" percent lower for an incumbent whose topics match the star's exactly")
        T += [("main intro P1 econ fall pct 31", "main.tex", intro_p1_rx,
               round(abs(pp["p1_econ"]["ate_pct"])), 1, "")]
        T += [("main intro P2 econ rise 0.20", "main.tex", intro_rx,
               round(PR2["econ"]["ate_pp"], 2), 1, ""),
              ("main intro P2 econ pre rate 0.060", "main.tex", intro_rx,
               PR2["econ"]["rate_pre_pp"], 2, "")]

    # ---- 2026-09-11: Section 1 scope sentence (Harvard "quick preview of the data") ----------
    # "in 25 Australian university departments that recorded 187 star arrivals between 1999 and
    # 2024": departments and years from the events_by_school_* ledgers, arrivals from the event
    # ledger totals; the two sources must also agree with each other on the arrival count.
    if carried and main:
        ebs_all = {d: carried[f"events_by_school_{d}"] for d in ("econ", "chem", "math")}
        yrs_all = sorted(y for d in ebs_all for v in ebs_all[d].values() for y in v)
        n_ev = main["econ_events"] + main["chem_events"] + main["math_events"]
        scope_rx = (r"in " + NUM + r" Australian university departments that recorded " + NUM
                    + r" star arrivals between " + NUM + r" and " + NUM)
        T += [("main scope departments 25", "main.tex", scope_rx,
               sum(len(v) for v in ebs_all.values()), 1, ""),
              ("main scope arrivals 187", "main.tex", scope_rx, n_ev, 2,
               "events_by_school_* lists hold %d arrival years" % len(yrs_all)),
              ("main scope arrivals agree across ledgers", "main.tex", scope_rx, len(yrs_all), 2, ""),
              ("main scope first year 1999", "main.tex", scope_rx, yrs_all[0], 3, ""),
              ("main scope last year 2024", "main.tex", scope_rx, yrs_all[-1], 4, "")]

    # ---- 2026-09-11: the opening paragraph's external statistic ----------------------------
    # The hook quotes the ABS higher-education R&D release. The figure is not derived from this
    # project's data, so there is no ledger to compare against; instead it is frozen with its
    # source, reference period, release date and the quoted sentence in
    # data/paper_inputs/external_stats_2026-09-11.json (pinned in that directory's MANIFEST),
    # and what main.tex prints is checked against that record. A retyped or drifted figure fails.
    ext_path = P["paper_inputs"] / "external_stats_2026-09-11.json"   # R1 F7: root from config
    if ext_path.exists():
        H = json.loads(ext_path.read_text(encoding="utf-8"))["herd_2024"]
        herd_rx = (r"spent \\\$" + NUM + r" billion performing research in\s*" + NUM)
        T += [("main hook ABS HERD 16.4 billion", "main.tex", herd_rx,
               H["total_aud_billion_1dp"], 1,
               "ABS release " + H["released"] + "; source prints $%d million" % H["total_aud_million"]),
              ("main hook ABS reference year 2024", "main.tex", herd_rx,
               int(H["reference_period"]), 2, "")]

    # sec4_causal.tex (new with the sync) restates seven shuffled-years p-values and one topic-cut
    # estimate; each sits under a "% src:" key, so each gets a pin (added 2026-09-23).
    if pp:
        PERM = pp["perm_pvalues"]
        c_p1c = (r"support the fall only weakly \(\$p=" + NUM + r"\$, or " + NUM
                 + r" when runs are ranked by \$t\$-statistic\)")
        c_p2 = r"shuffled arrival years also support the rise \(\$p=" + NUM + r"\$ and " + NUM + r"\)"
        c_p2m = (r"arrival years give \$p=" + NUM + r"\$, or " + NUM
                 + r" when runs are ranked by \$t\$-statistic")
        T += [("causal P1 econ shuffled-years p 0.018", "sec4_causal.tex",
               r"shuffled arrival years support the fall \(\$p=" + NUM + r"\$\)",
               round(PERM["p1_econ"]["p_perm_abs_ate"], 3), 1, ""),
              ("causal P1 chem shuffled-years p 0.144", "sec4_causal.tex", c_p1c,
               round(PERM["p1_chemistry"]["p_perm_abs_ate"], 3), 1, ""),
              ("causal P1 chem shuffled-years p by t-statistic 0.084", "sec4_causal.tex", c_p1c,
               round(PERM["p1_chemistry"]["p_perm_abs_t"], 3), 2, t_rank_pin_note(PERM)),
              ("causal P2 econ shuffled-years p 0.084", "sec4_causal.tex", c_p2,
               round(PERM["p2_econ"]["p_perm_abs_ate"], 3), 1, ""),
              ("causal P2 chem shuffled-years p 0.012", "sec4_causal.tex", c_p2,
               round(PERM["p2_chemistry"]["p_perm_abs_ate"], 3), 2, ""),
              ("causal P2 math shuffled-years p 0.146", "sec4_causal.tex", c_p2m,
               round(PERM["p2_math_stats"]["p_perm_abs_ate"], 3), 1, ""),
              ("causal P2 math shuffled-years p by t-statistic 0.006", "sec4_causal.tex", c_p2m,
               round(PERM["p2_math_stats"]["p_perm_abs_t"], 3), 2, t_rank_pin_note(PERM))]
    rbl = led.get("robustness")
    if rbl:
        T.append(("causal P3 econ median-dose cut 0.079", "sec4_causal.tex",
                  r"topic condition also turns the estimate negative \(\$-\$" + NUM
                  + r" percentage points\)",
                  abs(rbl["p3_cut_grid"]["econ"]["med"]["ate_pp"]), 1, ""))

    # 2026-09-23 REPLACE stage (cal2026-10): four numbers of the synced text that neither a pin nor a
    # same-line "% src:" key guarded, so the ledger-driven number replacement could not reach them.
    # Each prints a ledger value; each now has a pin (added with the pre-October value in the name;
    # the author's re-pin tool renamed them to the October value like every other pin).
    if main:
        T.append(("sec2 P3 no-pair arrivals: economics events 113", "sec2_data.tex",
                  r"In " + NUM + r" of the " + NUM + r" economics arrivals and " + NUM + r" of the " + NUM
                  + r" mathematics arrivals, fewer than two colleagues qualify", main["econ_events"], 2, ""))
    if pp:
        T += [("rob overlap: economics events on all 113", "sec4_robustness.tex",
               r"In economics, " + NUM + r" of the " + NUM + r" arrivals follow an earlier star",
               pp["p1_econ"]["events"], 2, ""),
              ("rob overlap: 95 events with an earlier arrival", "sec4_robustness.tex",
               r"Both groups show a fall after the arrival, of " + NUM + r" log points per unit of dose among the " + NUM,
               pp["p1_doublestar_econ"]["events_dropped"], 2, ""),
              ("p2 prose path math ell=2 se 0.153", "sec4_p2.tex",
               r"peaks two years after the arrival in economics \(" + NUM + r" percentage points, "
               + r"standard error " + NUM + r"\) and mathematics \(" + NUM + r", " + NUM + r"\)",
               round(next(h for h in pp["p2_math_stats"]["horizons_pp"] if h["ell"] == 2)["se_person"], 3), 4, "")]
    # Four more numbers of the synced text that only a "% src:" key guarded (no pin), and whose
    # October value the replacement had to refuse (a p<0.001 threshold the new p no longer meets; an
    # unsigned number whose new value is negative): pinned so the sentinel reports them until the
    # author rewrites the sentence (2026-09-23 REPLACE stage).
    if rbl:
        T += [("p3 date-shift econ joint p<0.001", "sec4_p3.tex",
               r"exceed the estimate, and the joint test rejects \(\$p<" + NUM + r"\$\)",
               ("lt", rbl["p3_date_shift"]["econ"]["p_joint_shifted"], 0.001), 1, ""),
              ("rob P1 network date-shift econ p<0.001", "sec4_robustness.tex",
               r"the roster of the department the star joins: in economics \(\$p<" + NUM + r"\$\)",
               ("lt", rbl["p1_pretrend_by_channel"]["econ"]["network"]["p_joint_shifted"], 0.001), 1, ""),
              ("rob P3 date-shift econ fails p<0.001", "sec4_robustness.tex",
               r"and fails in economics \(\$p<" + NUM + r"\$\)",
               ("lt", rbl["p3_date_shift"]["econ"]["p_joint_shifted"], 0.001), 1, ""),
              ("rob P3 topic cut econ from 0.044", "sec4_robustness.tex",
               r"The economics estimate turns from " + NUM + r" to \$-\$" + NUM + r" percentage points",
               rbl["p3_cut_grid"]["econ"]["pos"]["ate_pp"], 1, "")]

    # ---- 2026-09-23 sync: thesis_report now carries the 2026-09-13 draft's text ----------------
    # (plan: output/paper/SYNC_PLAN_2026-10.md). The draft rewrote or deleted most of the sentences the
    # pins above were written against. Nothing above is edited: every pin keeps its name, its
    # ledger expression and its capture pattern (NUM). SYNC_REANCHOR moves a pin to the sentence
    # (or table row) of the synced text that prints the same ledger key -- only (file, regex,
    # group) change. SYNC_RETIRE lists the pins whose number is no longer printed anywhere in the
    # compiled text: they stay in this table, section D reports them as RETIRED (listed, never
    # graded), and a retired pin whose regex matches again is graded as usual. Both tables are
    # keyed by pin name, so the author's re-pin tool renames their keys together with
    # the pins; _sync_2026_09_23() reports a key that names no pin as a FAIL.
    tm_p1 = r"\\emph\{Output \(Panel 1\)\}.*?"                      # tab_main_results.tex blocks
    tm_p2 = r"\\emph\{First paper with the star \(Panel 2\)\}.*?"
    tm_p3 = r"\\emph\{First tie between colleagues \(Panel 3\)\}.*?"

    def row3(label, cell=NUM):
        return (r"\\REV\{" + label + r"\} & \\REV\{" + cell + r"\} & \\REV\{" + cell
                + r"\} & \\REV\{" + cell + r"\}")
    se_ev = row3(r"\\quad s\.e\., event clusters", r"\(" + NUM + r"\)")
    zen_rx = {"union": r"exposure population for this event is therefore " + NUM + r" incumbents",
              "median": r"with a median similarity dose of " + NUM,  # supervisor round 4, B17b (2026-09-23)
              "post": r"and " + NUM + r" first publish with him after his arrival",
              "same": r"and all " + NUM + r" share at least one subfield with him",
              "pairs": r"possible pairs, and Panel 3 follows " + NUM,
              "possible": r"They form " + NUM + r" possible pairs"}
    s2_p3pairs = (r"Panel 3 has " + NUM + r" pairs in economics, " + NUM + r" in chemistry and "
                  + NUM + r" in mathematics")
    s2_bins = (r"has published, the share below 0\.1 is " + NUM + r" percent in economics, " + NUM
               + r" percent in chemistry and " + NUM + r" percent in mathematics")
    s2_net = (r"in economics, " + NUM + r" of the " + NUM
              + r" incumbent--event pairs enter through the network alone")
    s2_rost = r"the verified rosters hold " + NUM + r", " + NUM + r" and " + NUM + r" author identifiers"
    s2_centre = r"The centre lists add " + NUM + r" academics in chemistry and " + NUM + r" in mathematics"
    s2_nopairs = (r"In " + NUM + r" of the " + NUM + r" economics arrivals and " + NUM + r" of the "
                  + NUM + r" mathematics arrivals, fewer than two colleagues qualify")
    s2_zr = r"For " + NUM + r" of the " + NUM + r" economics events the staff lists do not reach"
    s2_edge = r"show no one starting in " + NUM + r" in chemistry or after " + NUM + r" in mathematics"
    p3_ate = (r"probability that two such colleagues first publish together is " + NUM
              + r" percentage points higher after the arrival")
    p3_perm = r"at least this far from zero " + NUM + r" percent of the time"
    p3_chci = r"The confidence interval, \$-\$" + NUM + r" to " + NUM + r", includes zero"
    p3_math = (r"In mathematics the estimate, " + NUM + r" percentage points, has an interval of \$-\$"
               + NUM + r" to " + NUM)
    p3_spike = r"in every discipline \(" + NUM + r", " + NUM + r" and " + NUM + r" percentage points\)"
    p3_e4 = r"positive again four years after \(" + NUM + r", standard error " + NUM + r"\)"
    p3_c4 = (r"The coefficient four years after the arrival \(\$-\$" + NUM + r", standard error " + NUM
             + r"\) alone supplies " + NUM + r" percent of the average")
    p3_shift = r"years before the star arrived, are " + NUM + r" and " + NUM + r" percentage points"
    cap_rx = r"Lower row: the raw first-tie rate, without a comparison group, up to " + NUM
    p1_ate = (r"output is lower by " + NUM + r" log points in economics and " + NUM
              + r" in chemistry \(standard errors " + NUM + r" and " + NUM + r", clustered by incumbent\)")
    p1_math = (r"The mathematics estimate, \$-\$" + NUM + r" \(" + NUM + r"\), cannot be distinguished "
               + r"from zero, its interval running from \$-\$" + NUM + r" to " + NUM + r" log points")
    p1_joint = r"coefficients are zero rejects in both \(\$p<" + NUM + r"\$ and \$p=" + NUM + r"\$\)"
    p1_mjt = (r"joint test is \\REV\{borderline\} \(\$p=" + NUM + r"\$ with incumbent clusters, " + NUM
              + r" with event clusters\)")
    p1_ovl = r"In " + NUM + r" of the " + NUM + r" economics events another star had arrived"
    rb_loeo = (r"dropping each of the " + NUM + r" events in turn never restores the placebo test "
               + r"\(largest \$p=" + NUM)
    # 2026-09-29 (supervisor round 4, #38): 4.2.1 "Four and five years" block merged into one paragraph
    rb_first = (r"In economics, " + NUM + r" of the " + NUM
                + r" arrivals follow an earlier star at the same department within five years")
    rb_those = r"On those " + NUM + r" events the placebo test rejects \(\$p=" + NUM + r"\$\)"
    rb_kept = r"on the " + NUM + r" with no earlier star it passes \(\$p=" + NUM + r"\$\)"
    rb_both = (r"Both groups show a fall after the arrival, of " + NUM
               + r" log points per unit of dose among the " + NUM + r" and " + NUM
               + r" \(standard error " + NUM + r"\) among the " + NUM
               + r", so the direction of the economics estimate is the same in both groups")
    p2_ate = (r"The rise is " + NUM + r" percentage points in economics \(standard error " + NUM + r"\), "
              + NUM + r" in chemistry \(" + NUM + r"\) and " + NUM + r" in mathematics and statistics \("
              + NUM + r"\)")
    p2_raw = (r"The pre-arrival rates are " + NUM + r", " + NUM + r" and " + NUM + r" percent a year\. "
              + r"Over the arrival year and the five years after it, up to " + NUM + r", the raw rates are "
              + NUM + r", " + NUM + r" and " + NUM + r" percent")
    p2_peak = (r"peaks two years after the arrival in economics \(" + NUM + r" percentage points, "
               + r"standard error " + NUM + r"\) and mathematics \(" + NUM + r", " + NUM + r"\)")
    p2_c4 = r"in the last estimated year, four years after \(" + NUM + r", " + NUM + r"\)"
    mi_p2 = (r"the yearly rate at which they first publish with the star is " + NUM + r" percentage points "
             + r"higher after the arrival, against a pre-arrival rate of " + NUM + r" percent a year")
    mi_p3 = (r"the yearly rate at which two such colleagues first publish together is " + NUM
             + r" percentage points higher after the arrival, against a pre-arrival rate of " + NUM
             + r" percent a year")
    mi_scope = (r"Australian university departments that respectively recorded " + NUM + r", " + NUM + r" and " + NUM
                + r" star arrivals between " + NUM + r" and " + NUM)  # "respectively": supervisor round 4, B05b (2026-09-23)
    tp_p1 = r"similarity dose \$\\times\$ " + row3(r"post-arrival")
    tp_p2 = row3(r"first paper with the star").replace(r"\} & \\REV\{", r"\} & star arrival & \\REV\{", 1)
    tp_p3 = row3(r"first tie between colleagues").replace(r"\} & \\REV\{", r"\} & star arrival & \\REV\{", 1)
    tr_route = lambda lab: r"\\REV\{" + lab + r"\} & \\REV\{\$-\$" + NUM + r" \(" + NUM + r"\)\}"
    s2, s3, p1, p2, p3, rb = ("sec2_data.tex", "sec3_strategy.tex", "sec4_p1.tex", "sec4_p2.tex",
                              "sec4_p3.tex", "sec4_robustness.tex")
    tmr, tpo, trb = "tab_main_results.tex", "tab_panels_overview.tex", "tab_robustness.tex"
    SYNC_REANCHOR = {  # pin name: (file, regex, group) in the synced text
        # sec2_data.tex -- Zenou worked example
        "sec2_data Zenou: union 102": (s2, zen_rx["union"], 1),
        "sec2_data Zenou: median dose 0.51": (s2, zen_rx["median"], 1),
        "sec2_data Zenou: first ties post 6": (s2, zen_rx["post"], 1),
        "sec2_data Zenou: same-topic outside 36": (s2, zen_rx["same"], 1),
        "sec2_data Zenou: pairs 624": (s2, zen_rx["pairs"], 1),
        "sec2_data Zenou: possible pairs 630": (s2, zen_rx["possible"], 1),
        # sec2_data.tex -- data section
        "sec2 lowest dose bin econ 20%": (s2, s2_bins, 1),
        "sec2 lowest dose bin chem 24%": (s2, s2_bins, 2),
        "sec2 lowest dose bin math 69%": (s2, s2_bins, 3),
        "sec2 exposure caption network-only 1,817": (s2, s2_net, 1),
        "sec2 exposure caption relations 6,643": (s2, s2_net, 2),
        "sec2 verified econ roster 1008": (s2, s2_rost, 1),
        "sec2 rosters econ 1008": (s2, s2_rost, 1),
        "sec2 rosters chem 518": (s2, s2_rost, 2),
        "sec2 rosters math 573": (s2, s2_rost, 3),
        "sec2 centre roster added chem 134": (s2, s2_centre, 1),
        "sec2 centre roster added math 28": (s2, s2_centre, 2),
        "sec2 zero-roster events 1": (s2, s2_zr, 1),
        "sec2 zero-roster of 113 events": (s2, s2_zr, 2),
        "sec2 articles+reviews 258 million works": (
            s2, r"cells, of which " + NUM + r" million are the journal articles and reviews", 1),
        "sec2 ranking pool 10.5 million authors": (s2, r"The ranking pool, " + NUM + r" million extracted authors", 1),
        "sec2 chem roster no spell starts in 2024": (s2, s2_edge, 1),
        "sec2 chem roster edge nominal in 2024": (s2, s2_edge, 1),
        "sec2 math roster edge after 2020": (s2, s2_edge, 2),
        "sec2 P3 econ pairs 23,758": (s2, s2_p3pairs, 1),
        "sec2 P3 chem pairs 2,466": (s2, s2_p3pairs, 2),
        "sec2 P3 math pairs 2,770": (s2, s2_p3pairs, 3),
        "p3 cut pos econ pairs 90,325": (s2, s2_p3pairs, 1),
        "p3 chem pairs 11,466": (s2, s2_p3pairs, 2),
        "sec2 P3 econ events-without-pairs 30": (s2, s2_nopairs, 1),
        # sec4_p1.tex
        "p1 prose ATE econ": (p1, p1_ate, 1),
        "p1 prose ATE chem": (p1, p1_ate, 2),
        "p1 prose se person econ": (p1, p1_ate, 3),
        "p1 prose se person chem": (p1, p1_ate, 4),
        "p1 prose joint effects econ p<0.001": (p1, p1_joint, 1),
        "p1 prose joint effects chem p=0.008": (p1, p1_joint, 2),
        "p1 prose ATE math": (p1, p1_math, 1),
        "p1 prose se person math": (p1, p1_math, 2),
        "p1 prose math CI lo": (p1, p1_math, 3),
        "p1 prose math CI hi": (p1, p1_math, 4),
        "p1 prose joint math person p=0.009": (p1, p1_mjt, 1),
        "p1 prose joint math event p=0.008": (p1, p1_mjt, 2),
        "p1 prose doublestar footnote dropped 95": (p1, p1_ovl, 1),
        "p1 prose doublestar footnote of 113": (p1, p1_ovl, 2),
        # sec4_robustness.tex -- Panel 1 pre-arrival paragraph
        "p1 prose loeo removals 113": (rb, rb_loeo, 1),
        "p1 prose loeo max placebo p": (rb, rb_loeo, 2),
        "p1 prose overlap count 95": (rb, rb_first, 1),
        "p1 prose overlap of 113": (rb, rb_first, 2),
        "p1 prose doublestar complement events 95": (rb, rb_those, 1),
        "p1 prose doublestar complement placebo p=0.003": (rb, rb_those, 2),
        "p1 prose doublestar events kept 18": (rb, rb_kept, 1),
        "p1 prose doublestar placebo p=0.635": (rb, rb_kept, 2),
        "p1 prose doublestar ate 0.711": (rb, rb_both, 3),
        "p1 prose doublestar se 0.200": (rb, rb_both, 4),
        "p1 prose doublestar footnote same-year of 18": (rb, rb_both, 5),
        "p1 prose doublestar complement ate 0.380": (rb, rb_both, 1),
        "p1 prose bracket low 0.38": (rb, rb_both, 1),
        "p1 prose bracket high 0.71": (rb, rb_both, 3),
        # sec4_robustness.tex -- estimator and Panel 3 topic cut
        "p3 perm count 500": (rb, r"runs the estimator again, " + NUM + r" times", 1),
        "p3 perm counts equal across disciplines": (rb, r"runs the estimator again, " + NUM + r" times", 1),
        "p3 perm counts equal math": (rb, r"runs the estimator again, " + NUM + r" times", 1),
        "p3 cut med econ ate 0.079": (
            rb, r"The economics estimate turns from " + NUM + r" to \$-\$" + NUM + r" percentage points", 2),
        # sec4_p2.tex
        "p2 prose ATE econ": (p2, p2_ate, 1),
        "p2 prose se person econ": (p2, p2_ate, 2),
        "p2 prose ATE chem": (p2, p2_ate, 3),
        "p2 prose se person chem": (p2, p2_ate, 4),
        "p2 prose ATE math": (p2, p2_ate, 5),
        "p2 prose se person math": (p2, p2_ate, 6),
        "p2 prose raw pre econ": (p2, p2_raw, 1),
        "p2 prose raw pre chem": (p2, p2_raw, 2),
        "p2 prose raw pre math": (p2, p2_raw, 3),
        "p2 prose year cap": (p2, p2_raw, 4),
        "p2 prose raw post econ": (p2, p2_raw, 5),
        "p2 prose raw post chem": (p2, p2_raw, 6),
        "p2 prose raw post math": (p2, p2_raw, 7),
        "p2 prose path econ ell=2": (p2, p2_peak, 1),
        "p2 prose path math ell=2": (p2, p2_peak, 3),
        "p2 prose path chem ell=4": (p2, p2_c4, 1),
        "p2 fig caption year cap 2024": (p2, cap_rx, 1),
        # sec4_p3.tex
        "p3 date-shift vs reported 0.044": (p3, p3_ate, 1),
        "p3 null-sim vs reported econ 0.044": (p3, p3_ate, 1),
        "p3 econ SE pair 0.053": (
            p3, r"higher after the arrival \(standard error " + NUM + r", clustered by pair\)", 1),
        "p3 econ headline permutation 24 percent": (p3, p3_perm, 1),
        "p3 perm pct econ 24": (p3, p3_perm, 1),
        "p3 chem CI lower 1.047": (p3, p3_chci, 1),
        "p3 chem CI upper 0.114": (p3, p3_chci, 2),
        "p3 chem fourth-year coefficient -2.108": (p3, p3_c4, 1),
        "p3 chem fourth-year se 1.664": (p3, p3_c4, 2),
        "p3 chem fourth-year share of the average 77.5%": (p3, p3_c4, 3),
        "p3 math estimate 0.041pp": (p3, p3_math, 1),
        "p3 null-sim vs reported math 0.041": (p3, p3_math, 1),
        "p3 math CI lower 0.039": (p3, p3_math, 2),
        "p3 math CI upper 0.122": (p3, p3_math, 3),
        "p3 math base rate 0.197": (p3, r"about a fifth of the " + NUM + r" percent base rate", 1),
        "p3 arrival-year spike econ 0.136": (p3, p3_spike, 1),
        "p3 arrival-year spike chem 0.135": (p3, p3_spike, 2),
        "p3 arrival-year spike math 0.174": (p3, p3_spike, 3),
        "p3 econ fourth-year reappearance 0.070": (p3, p3_e4, 1),
        "p3 econ fourth-year se 0.102": (p3, p3_e4, 2),
        "p3 date-shift econ k1 0.104": (p3, p3_shift, 1),
        "p3 date-shift econ k2 0.077": (p3, p3_shift, 2),
        "p3 fig caption year cap 2024": (p3, cap_rx, 1),
        # main.tex
        "main intro P2 econ rise 0.20": ("main.tex", mi_p2, 1),
        "main intro P2 econ pre rate 0.060": ("main.tex", mi_p2, 2),
        "main intro P3 econ fall 0.13": ("main.tex", mi_p3, 1),
        "main intro P3 econ pre rate 0.40": ("main.tex", mi_p3, 2),
        "main scope first year 1999": ("main.tex", mi_scope, 4),
        "main scope last year 2024": ("main.tex", mi_scope, 5),
        # tables/tab_panels_overview.tex (generator-owned since the sync: draft_2026_09_13_tables.py)
        "tab_panels P1 econ rows 73,073": (tpo, tp_p1, 1),
        "tab_panels note chem P1 30,635": (tpo, tp_p1, 2),
        "tab_panels note math P1 19,910": (tpo, tp_p1, 3),
        "tab_panels P2 econ rows 111,448": (tpo, tp_p2, 1),
        "tab_panels note chem P2 46,168": (tpo, tp_p2, 2),
        "tab_panels note math P2 30,314": (tpo, tp_p2, 3),
        "tab_panels P3 econ rows 393,007": (tpo, tp_p3, 1),
        "tab_panels note chem P3 39,242": (tpo, tp_p3, 2),
        "tab_panels note math P3 46,010": (tpo, tp_p3, 3),
        "sec2 exposure caption incumbents 822": (tpo, r"\{\\REV\{Incumbents\}\} & \\REV\{" + NUM + r"\}", 1),
        "sec2 exposure caption events 113": (tpo, r"\{\\REV\{Star arrivals \(events\)\}\} & \\REV\{" + NUM + r"\}", 1),
        # tables/tab_main_results.tex (Table tab:main; the value is printed only there)
        "p1 prose se event econ": (tmr, tm_p1 + se_ev, 1),
        "p1 prose se event chem": (tmr, tm_p1 + se_ev, 2),
        "p1 prose se event math": (tmr, tm_p1 + se_ev, 3),
        "p2 prose se event econ": (tmr, tm_p2 + se_ev, 1),
        "p2 prose se event chem": (tmr, tm_p2 + se_ev, 2),
        "p2 prose se event math": (tmr, tm_p2 + se_ev, 3),
        "p3 econ SE event 0.093": (tmr, tm_p3 + se_ev, 1),
        "p3 chem first ties 1,004": (tmr, tm_p3 + row3(r"First ties"), 2),
        "p3 math first ties 401": (tmr, tm_p3 + row3(r"First ties"), 3),
        "p3 events-with-pairs econ 111": (tmr, tm_p3 + row3(r"Events with pairs"), 1),
        "sec2 P3 econ events-with-pairs 86": (tmr, tm_p3 + row3(r"Events with pairs"), 1),
        "p3 chem events 38": (tmr, tm_p3 + row3(r"Events with pairs"), 2),
        "p3 events-with-pairs chem 38": (tmr, tm_p3 + row3(r"Events with pairs"), 2),
        "sec2 P3 chem events 33": (tmr, tm_p3 + row3(r"Events with pairs"), 2),
        "p3 math events 32": (tmr, tm_p3 + row3(r"Events with pairs"), 3),
        "p3 events-with-pairs math 32": (tmr, tm_p3 + row3(r"Events with pairs"), 3),
        "sec2 P3 math events 31": (tmr, tm_p3 + row3(r"Events with pairs"), 3),
        # tables/tab_robustness.tex (Table tab:robustness of the draft)
        "p1 prose by-route roster ate": (trb, tr_route("Incumbents on the roster"), 1),
        "p1 prose by-route roster se": (trb, tr_route("Incumbents on the roster"), 2),
        "p1 prose by-route network ate": (trb, tr_route("Incumbents in the star's network"), 1),
        "p1 prose by-route network se": (trb, tr_route("Incumbents in the star's network"), 2),
        "p3 cut med chem ate 0.642": (
            trb, r"\\REV\{Both incumbents at or above median positive dose\} & \\REV\{[^{}]*\} & \\REV\{\$-\$"
            + NUM + r" \(", 1),
    }
    SYNC_RETIRE = {  # pin name: why its number is no longer printed in the compiled text
        "main intro P1 econ fall pct 31": "dose-1 percent conversion deleted from the introduction "
                                          "(author 2026-10-01, read-through: dose 1 is not the typical dose)",
        "sec2_data Zenou: dose below 0.1: 26": "Zenou dose-bin clause cut (the only 26 left is the snapshot date)",
        "sec2_data Zenou: dose >= 0.5: 63": "Zenou dose-bin clause cut",
        "sec2_data any-reference share (econ_share_any_ref)": "reference-overlap shares cut; Section 2.4 keeps the limitation in words",
        "sec2_data any-subfield share (econ_share_any_subfield)": "reference-overlap shares cut; Section 2.4 keeps the limitation in words",
        "sec2 no-dose exclusions chem 5": "dose-NA exclusion counts cut (kept in a % comment only)",
        "sec2 no-dose exclusions math 80": "dose-NA exclusion counts cut (kept in a % comment only)",
        "sec2 balance econ pub_pre -0.16": "balance sentence removed from Section 2",
        "sec2 balance econ age_gap +0.17": "balance sentence removed from Section 2",
        "sec2 balance chem pub_pre +0.20": "balance sentence removed from Section 2",
        "sec2 balance math largest 0.14": "balance sentence removed from Section 2",
        "sec2 FWCI-missing econ 27.5%": "FWCI-coverage sentence replaced by the Section 2.4 empty/missing shares",
        "sec2 FWCI-missing chem 29.8%": "FWCI-coverage sentence replaced by the Section 2.4 empty/missing shares",
        "sec2 FWCI-missing math 28.8%": "FWCI-coverage sentence replaced by the Section 2.4 empty/missing shares",
        "sec2 genuine missing econ 0.5%": "FWCI-coverage sentence replaced by the Section 2.4 empty/missing shares",
        "sec2 genuine missing chem/math cap 0.2%": "FWCI-coverage sentence replaced by the Section 2.4 empty/missing shares",
        "sec2 exposure caption roster-only 3,983": "fig:pop (exposure population figure) removed",
        "sec2 exposure caption both 669": "fig:pop (exposure population figure) removed",
        "sec2 fellowship entries 205": "fellowship-count sentence cut",
        "sec2 P3 exits before arrival 1,619": "Panel 3 exit-split sentence cut",
        "sec2 P3 exits after arrival 1,990": "Panel 3 exit-split sentence cut",
        "sec2 P3 never tie 84,567": "Panel 3 exit-split sentence cut",
        "sec2 OpenAlex subfields 252": "subfield-count clause cut",
        "sec2 math roster no spell starts from 2021": "roster-edge footnote now says 'after 2020' only",
        "sec2 dose caption observed econ": "fig:dose removed (the 10,763 left is the relation total, another expression)",
        "sec2 dose caption observed chem": "fig:dose removed",
        "sec2 dose caption observed math": "fig:dose removed",
        "sec2 dose caption chem NA 5": "fig:dose removed",
        "sec2 dose caption math NA 80": "fig:dose removed",
        "p3 two-years-after econ 0.028": "two-years-after values no longer printed (the 0.028 left is the ell=4 standard error)",
        "p3 two-years-after chem 0.243": "two-years-after values no longer printed",
        "p3 date-shift chem p 0.84": "printed now as p=0.844 (3 dp, sec4_robustness.tex, R p3_date_shift), not at 2 dp",
        "p3 date-shift math p 0.56": "printed now as p=0.560 (3 dp, sec4_robustness.tex, R p3_date_shift), not at 2 dp",
        "p3 perm pct chem 10": "printed now as p=0.102 (sec4_p3.tex, tab:robustness), not as a percent",
        "p3 perm pct math 58": "printed now as p=0.583 (sec4_p3.tex, tab:robustness), not as a percent",
        "p3 null-sim count 200": "no-effect simulation deleted from the text",
        "p3 null-sim count equal chem": "no-effect simulation deleted from the text",
        "p3 null-sim count equal math": "no-effect simulation deleted from the text",
        "p3 null-sim econ 0.048": "no-effect simulation deleted from the text",
        "p3 null-sim chem 0.244": "no-effect simulation deleted from the text",
        "p3 null-sim math 0.035": "no-effect simulation deleted from the text",
        "p3 cut med econ pairs 23,758": "topic-cut pair counts no longer printed",
        "p3 cut abs04 econ ate 0.151": "abs04 / p75 topic cuts no longer printed",
        "p3 cut abs04 econ pairs 17,310": "abs04 / p75 topic cuts no longer printed",
        "p3 cut p75 econ ate 0.068": "abs04 / p75 topic cuts no longer printed",
        "p3 cut p75 econ pairs 7,555": "abs04 / p75 topic cuts no longer printed",
        "p3 cut abs04 chem ate 0.844": "abs04 topic cut no longer printed (the 0.844 left is the chemistry date-shift p)",
        "p1 prose weighted avg [econ]": "Section 3.1 economics worked example cut 2026-09-28 (supervisor round 4, #20); Section 3 prints no result numbers",
        "p1 prose weighted avg [chem]": "the weighted average is printed for no discipline (Section 3.1 economics example cut 2026-09-28)",
        "p1 prose weighted avg [math]": "the weighted average is printed for no discipline (Section 3.1 economics example cut 2026-09-28)",
        "p1 prose weighted avg percent [econ]": "percent conversions no longer printed",
        "p1 prose weighted avg percent [chem]": "percent conversions no longer printed",
        "p1 prose weighted avg percent [math]": "percent conversions no longer printed",
        "p1 prose pct econ": "percent conversions no longer printed (percent row dropped from Table tab:main)",
        "p1 prose pct chem": "percent conversions no longer printed (percent row dropped from Table tab:main)",
        "p1 prose pct math": "percent conversions no longer printed (percent row dropped from Table tab:main)",
        "p1 prose loeo ate min": "leave-one-out range no longer printed (only the largest placebo p)",
        "p1 prose loeo ate max": "leave-one-out range no longer printed (only the largest placebo p)",
        "p1 prose doublestar complement se 0.069": "no longer printed",
        "p1 prose doublestar effects p<0.001 (both)": "double-star post-arrival joint test no longer printed",
        "p1 prose doublestar footnote same-year kept 4": "same-year co-arrival footnote cut",
        "p2 prose path econ ell=0": "Panel 2 path now reports the peak years only",
        "p2 prose path econ ell=4": "Panel 2 path now reports the peak years only",
        "main scope departments 25": "Section 1 scope now prints per-discipline counts (11, 8 and 6 departments)",
        "main scope arrivals 187": "Section 1 scope now prints per-discipline counts (116, 38 and 33 arrivals)",
        "main scope arrivals agree across ledgers": "Section 1 scope now prints per-discipline counts",
    }
    T = _sync_2026_09_23(T, SYNC_REANCHOR, SYNC_RETIRE)

    # ---- 2026-09-23 sentence rewrites (cal2026-10) ----------------------------------------------
    # The October numbers left sentences their words contradicted (data/cal2026-10/paper_layer/
    # replace_report.json refusals, verify_text_numbers.json findings; tests/_paper_author_pending.py;
    # these records are not shipped). The sentence rewrites (sentence_proposals_2026-10.json, applied by
    # tools/apply_sentence_proposals_2026-10.py; both not shipped) move the pins below to the new wording.
    # SENT_REANCHOR: pin name -> (file, regex, group, expected); expected None keeps the pin's own
    # ledger expression. It is replaced only where the words now carry what the number used to: a
    # sign ("lower" by X means the ledger holds -X; a printed $-$ sign is compared as printed) or a
    # p printed as its value where the sentence used to print "p<0.001". SENT_RETIRE: pins whose
    # number the rewrite no longer prints. SENT_ADD: numbers the rewrite prints for the first time.
    # Names are kept, so tests/_paper_author_pending.py (keyed on names; not shipped) sees these pins turn PASS.
    # (the names p3 / p1 / p2 / rb above now hold file names, so the ledgers are read from led)
    l_p3, l_pp, l_rb = led["p3afar"], led["p1p2"], led.get("robustness")
    if l_p3 and l_pp and l_rb:
        e3, rb3 = l_p3["econ"], l_rb["p3_date_shift"]["econ"]
        h3 = {f: {h["ell"]: h for h in l_p3[f]["horizons_pp"]} for f in ("econ", "chemistry", "math_stats")}
        p2p = {f: l_pp[f"p2_{f}"] for f in ("econ", "chemistry", "math_stats")}
        s_p3_ate = (r"probability that two such colleagues first publish together is " + NUM
                    + r" percentage points lower after the arrival")
        s_p3_spike = (r"in chemistry and mathematics \(" + NUM + r" and " + NUM
                      + r" percentage points\) but not in economics \(" + SNUM + r"\)")
        s_p3_e4 = r"still negative four years after \(" + SNUM + r", standard error " + NUM + r"\)"
        s_p3_shift = r"years before the star arrived, are " + SNUM + r" and " + NUM + r" percentage points"
        s_p3_joint = r"further from zero than the estimate, and the joint test rejects \(\$p=" + NUM + r"\$\)"
        s_rb_cut = r"The economics estimate moves from " + SNUM + r" to " + SNUM + r" percentage points"
        s_mi_p3 = (r"the yearly rate at which two such colleagues first publish together is " + NUM
                   + r" percentage points lower after the arrival, against a pre-arrival rate of " + NUM
                   + r" percent a year")
        s_p1_mjt = (r"joint test \\REV\{rejects\} \(\$p=" + NUM + r"\$ with incumbent clusters, " + NUM
                    + r" with event clusters\)")
        s_p2j = (r"rejects in\s*economics and chemistry with incumbent clusters, but not in mathematics \(\$p="
                 + NUM + r"\$\); with event clusters it rejects in economics and chemistry \(\$p=" + NUM
                 + r"\$ and \$p<" + NUM + r"\$\) but not in mathematics \(\$p=" + NUM + r"\$\)")
        s_c_p1c = (r"cannot show that the fall depends on when the stars actually arrived \(\$p=" + NUM
                   + r"\$, or " + NUM + r" when runs are ranked by \$t\$-statistic\)")
        s_rb_fill_plac = (r"the placebo test still rejects under both fillings \(\$p<" + NUM + r"\$ and \$p="
                          + NUM + r"\$\), so neither filling removes the pre-arrival gap")
        # Section 4.2.2 grades the shuffled-years p in two tiers at 0.05 (supervisor round 4, #39)
        s_rb_perm_dep = (r"the chemistry estimate of Panel 2 depend on when the stars actually arrived \(\$p="
                         + NUM + r"\$ and " + NUM + r"\)")
        s_rb_perm_no = (r"The check cannot show this dependence for the economics estimate of Panel 2 \(\$p="
                        + NUM + r"\$\), the chemistry estimate of Panel 1 \(\$p=" + NUM + r"\$\)")
        rb, p3f, ca = "sec4_robustness.tex", "sec4_p3.tex", "sec4_causal.tex"
        SENT_REANCHOR = {
            # sec4_p3.tex (S1, S2, S4, S5)
            "p3 econ ATE 0.044pp": (p3f, s_p3_ate, 1, -e3["ate_pp"]),
            "p3 date-shift vs reported 0.044": (p3f, s_p3_ate, 1, -e3["ate_pp"]),
            "p3 null-sim vs reported econ 0.044": (p3f, s_p3_ate, 1, -e3["ate_pp"]),
            "p3 econ SE pair 0.053": (
                p3f, r"lower after the arrival \(standard error " + NUM + r", clustered by pair\)", 1, None),
            "p3 arrival-year spike chem 0.135": (p3f, s_p3_spike, 1, None),
            "p3 arrival-year spike math 0.174": (p3f, s_p3_spike, 2, None),
            "p3 arrival-year spike econ 0.136": (p3f, s_p3_spike, 3, h3["econ"][0]["est"]),
            "p3 econ fourth-year reappearance 0.070": (p3f, s_p3_e4, 1, h3["econ"][4]["est"]),
            "p3 econ fourth-year se 0.102": (p3f, s_p3_e4, 2, h3["econ"][4]["se_pair"]),
            "p3 date-shift econ k1 0.104": (p3f, s_p3_shift, 1, rb3["shifted_effects_pp"][0]["est"]),
            "p3 date-shift econ k2 0.077": (p3f, s_p3_shift, 2, rb3["shifted_effects_pp"][1]["est"]),
            "p3 date-shift econ joint p<0.001": (p3f, s_p3_joint, 1, round(rb3["p_joint_shifted"], 3)),
            # sec4_robustness.tex (R1, R2, R-1)
            "rob P3 date-shift econ fails p<0.001": (
                rb, r"and fails in economics \(\$p=" + NUM + r"\$\)", 1, round(rb3["p_joint_shifted"], 3)),
            "rob P1 network date-shift econ p<0.001": (
                rb, r"the roster of the department the star joins: in economics \(\$p=" + NUM + r"\$\)", 1,
                round(l_rb["p1_pretrend_by_channel"]["econ"]["network"]["p_joint_shifted"], 3)),
            "rob P3 topic cut econ from 0.044": (rb, s_rb_cut, 1, l_rb["p3_cut_grid"]["econ"]["pos"]["ate_pp"]),
            "p3 cut med econ ate 0.079": (rb, s_rb_cut, 2, l_rb["p3_cut_grid"]["econ"]["med"]["ate_pp"]),
            # sec4_causal.tex (C2, C-3, C-5)
            "causal P3 econ median-dose cut 0.079": (
                ca, r"topic condition keeps it negative \(\$-\$" + NUM + r" percentage points\)", 1, None),
            "causal P1 econ shuffled-years p 0.018": (
                ca, r"[Ss]huffled arrival years show that the fall depends on when the stars actually arrived \(\$p="
                + NUM + r"\$\)", 1, None),
            "causal P1 chem shuffled-years p 0.144": (ca, s_c_p1c, 1, None),
            "causal P1 chem shuffled-years p by t-statistic 0.084": (ca, s_c_p1c, 2, None),
            "causal P2 chem shuffled-years p 0.012": (
                ca, r"In chemistry shuffled arrival years also show that the rise depends on when the stars "
                r"actually arrived \(\$p=" + NUM + r"\$\)", 1, None),
            "causal P2 econ shuffled-years p 0.084": (
                ca, r"in economics they cannot show this dependence \(\$p=" + NUM + r"\$\)", 1, None),
            # main.tex (M5)
            "main intro P3 econ fall 0.13": ("main.tex", s_mi_p3, 1, round(-e3["ate_pp"], 2)),
            "main intro P3 econ pre rate 0.40": ("main.tex", s_mi_p3, 2, None),
            # sec4_p1.tex (P1-1)
            "p1 prose joint math person p=0.009": ("sec4_p1.tex", s_p1_mjt, 1, None),
            "p1 prose joint math event p=0.008": ("sec4_p1.tex", s_p1_mjt, 2, None),
            # sec4_p2.tex (P2-1): this pin now covers the chemistry cell only; economics is SENT_ADD
            "p2 prose joint math person p=0.066": ("sec4_p2.tex", s_p2j, 1, None),
            "p2 prose joint econ+chem event p<0.001": (
                "sec4_p2.tex", s_p2j, 3, ("lt", p2p["chemistry"]["p_joint_effects_event"], 0.001)),
            "p2 prose joint math event p=0.109": ("sec4_p2.tex", s_p2j, 4, None),
            # appendix_robustness.tex (B-1)
            "tab_balance notes chem pub_pre +0.26": (
                "appendix_robustness.tex", r"publication imbalance in chemistry \(" + SNUM + r"\)", 1, None),
        }
        SENT_RETIRE = {
            "tab_balance notes econ pub_pre 0.04": "economics no longer named in the balance note "
                                                   "(+0.04 is below the note's 0.1 balance line)",
        }
        PERM_L = l_pp["perm_pvalues"]
        pe = p2p["econ"]["p_joint_effects_event"]   # R1 M: the draft generator's rule for this printed p (M: $<$0.001)
        SENT_ADD = [
            ("p2 prose joint econ event p=0.003", "sec4_p2.tex", s_p2j,
             ("lt", pe, 0.001) if pe < 0.001 else round(pe, 3), 2, ""),
            ("rob shuffled-years P1 econ p 0.018", rb, s_rb_perm_dep,
             round(PERM_L["p1_econ"]["p_perm_abs_ate"], 3), 1, ""),
            ("rob shuffled-years P2 chem p 0.012", rb, s_rb_perm_dep,
             round(PERM_L["p2_chemistry"]["p_perm_abs_ate"], 3), 2, ""),
            ("rob shuffled-years P2 econ p 0.084", rb, s_rb_perm_no,
             round(PERM_L["p2_econ"]["p_perm_abs_ate"], 3), 1, ""),
            ("rob shuffled-years P1 chem p 0.144", rb, s_rb_perm_no,
             round(PERM_L["p1_chemistry"]["p_perm_abs_ate"], 3), 2, ""),
            # Section 4.2.4 missing output: the econ placebo p under both fillings (supervisor round 4, #43)
            ("rob missing-output econ placebo p, zero filling <0.001", rb, s_rb_fill_plac,
             ("lt", l_rb["p1_variants"]["econ"]["missing_as_zero"]["p_joint_placebo"], 0.001), 1, ""),
            ("rob missing-output econ placebo p, own-mean filling 0.004", rb, s_rb_fill_plac,
             round(l_rb["p1_variants"]["econ"]["missing_as_own_mean"]["p_joint_placebo"], 3), 2, ""),
            # Section 4.2.6 "Star threshold" and Section 5 third issue (supervisor round 4, #49, D7 top 5%)
            ("rob star threshold econ placebo p 0.025", rb,
             r"In economics the placebo test still rejects \(\$p=" + NUM + r"\$\)",
             round(l_rb["d7"]["top5"]["econ"]["p1"]["p_joint_placebo"], 3), 1, ""),
            ("rob star threshold math P2 first ties 25", rb,
             r"where the estimator fails on the remaining sample, which has " + NUM + r" first ties",
             l_rb["d7"]["top5"]["math_stats"]["p2"]["first_ties"], 1, ""),
            ("rob star threshold top 5 [5]", rb,
             r"in the top " + NUM + r" rather than " + NUM + r" percent by citations", 5, 1,
             "design constant: analysis/robustness/threshold_p05 (run_caliber pass_p05)"),
            ("rob star threshold top 5 rather than 10 [10]", rb,
             r"in the top " + NUM + r" rather than " + NUM + r" percent by citations", 10, 2,
             "main threshold, as printed in sec2_data.tex"),
            ("concl star threshold 5 rather than 10 [5]", "sec5_conclusion.tex",
             r"in the top " + NUM + r" rather than " + NUM + r" percent by citations", 5, 1, "design constant"),
            ("concl star threshold 5 rather than 10 [10]", "sec5_conclusion.tex",
             r"in the top " + NUM + r" rather than " + NUM + r" percent by citations", 10, 2,
             "main threshold, as printed in sec2_data.tex"),
        ]
        SYNC_UNMATCHED.extend(sorted((set(SENT_REANCHOR) | set(SENT_RETIRE)) - {t[0] for t in T}))
        moved = []
        for name, fname, rx, expected, group, note in T:
            if name in SENT_REANCHOR:
                fname, rx, group, new_expected = SENT_REANCHOR[name]
                if new_expected is not None:
                    expected = new_expected
            elif name in SENT_RETIRE:
                note = f"{RETIRED_TAG}: {SENT_RETIRE[name]}" + (f"; {note}" if note else "")
            moved.append((name, fname, rx, expected, group, note))
        T = moved + SENT_ADD
    # Phase 2b: these new network-only counts appear only in the R1 author tree.
    # Pass the profile explicitly so a previous R1 binding cannot leak into other callers.
    if profile == "r1" and main:
        T += [("r1 sec2 chemistry network-only relations", "sec2_data.tex", _R1_EXPOSURE,
               main["chem_relations"]["network"], 3, "data_numbers main: chem_relations.network"),
              ("r1 sec2 mathematics network-only relations", "sec2_data.tex", _R1_EXPOSURE,
               main["math_relations"]["network"], 5, "data_numbers main: math_relations.network")]
    return T


# ---------------------------------------------------------------------------
# The measured 'vault' overlay (R1 P3 V3-FINAL.c, W3-OVERLAY, 2026-10-16). The base tree
# (BASE_TREE_REL) rewords Sections 4.1-4.3 (supervisor round 4, the 10-03..10-11 rewrites, \BOR{Model}
# wrappers). Measured read-only on the October ledgers: claims_table's pins are 0 FAIL on thesis_report
# and 78 FAIL ("pattern not found") on the base tree; section_d_r4_claims has 7 "sentence not found".
# Each FAIL is re-anchored on the base tree's sentence or table row that prints the SAME ledger number
# (75; each grades PASS there), retired because the base tree prints the number nowhere (3), or
# re-phrased to the base tree's sentence stating the same claim (7). Names and ledger expressions never
# change. tests/test_r1_vault_overlay.py holds the overlay to that list on a byte copy of the base tree
# (tests/fixtures/r1_paper/base_tree_2026-10-11/, not shipped); finalb0's vault sentinel_pre run confirms it on AWS.
# ---------------------------------------------------------------------------
_V_P3_ATE = (r"the first-tie rate between two such colleagues is " + NUM
             + r" percentage points below that of comparison pairs")
_V_P3_CHEM = (r"In chemistry the estimate is " + NUM + r" percentage points below comparison pairs, two thirds "
              r"of the " + NUM + r" percent pre-arrival rate")
_V_P3_CHEM_CI = r"Its interval, \$-\$" + NUM + r" to " + NUM + r", includes zero, although"
_V_P3_Y4 = (r"the coefficient is \$-\$" + NUM + r" percentage points \(standard error " + NUM
            + r"\); this one year supplies " + NUM + r" percent of the average")
_V_P3_RAW = (r"from " + NUM + r" percent six years before to " + NUM + r" percent in the year before; it peaks at "
             + NUM + r" percent in the arrival year and falls to " + NUM + r" percent by the fifth year")
_V_P3_DS = r"the two shifted coefficients are " + SNUM + r" and " + NUM + r" percentage points"
_V_P3_DS_P = r"and the test fails \(\$p=" + NUM + r"\$\)"
_V_PERM_RUNS = r"re-estimate the model " + NUM + r" times"
_V_T_RANKED = (r"the shuffled \$p\$ is " + NUM + r" for mathematics in Panel 2 \([^)]*\) and " + NUM
               + r" for chemistry in Panel 1")
_V_ROUTE_NET = r"\\REV\{Network incumbents\} & \\REV\{\$-\$" + NUM + r" \(" + NUM + r"\)\}"
_V_ROUTE_ROS = r"\\REV\{Roster incumbents\} & \\REV\{\$-\$" + NUM + r" \(" + NUM + r"\)\}"
_V_P1_JOINT_MATH = (r"but the joint test rejects \(\$p=" + NUM + r"\$ with incumbent clusters, " + NUM
                    + r" with event clusters\)")
_V_P1_PLACEBO = (r"passes in chemistry \(\$p=" + NUM + r"\$\) and mathematics \(\$p=" + NUM
                 + r"\$\) but fails in economics \(\$p=" + NUM + r"\$\)")
_V_P1_OVERLAP = r"On those " + NUM + r" events the placebo test fails \(\$p=" + NUM + r"\$\)"
_V_P1_BOTH = (r"Both groups show a fall after the arrival, of " + NUM + r" log points per unit of dose among the "
              + NUM + r" and " + NUM + r" \(" + NUM + r"\) among the " + NUM + r"\.")
_V_P1_EARLIER = r"In economics, " + NUM + r" of the " + NUM + r" arrivals follow an earlier star"
_V_P2_ATE = (r"The yearly first-tie rate is " + NUM + r" percentage points higher than that of comparison relations "
             r"in economics \(standard error " + NUM + r"\), " + NUM + r" in chemistry \(" + NUM + r"\) and " + NUM
             + r" in mathematics and statistics \(" + NUM + r"\)")
_V_P2_RAW = (r"The pre-arrival rates are " + NUM + r", " + NUM + r" and " + NUM + r" percent a year\. Over the "
             r"arrival year and the five years after it, the raw rates up to " + NUM + r" are " + NUM + r", " + NUM
             + r" and " + NUM + r" percent")
_V_P2_JOINT_MATH = r"but not in mathematics \(\$p=" + NUM + r"\$ and " + NUM + r"\)"
# R1 M: a p cell of Table 2 as the draft generator prints it ('$<$0.001' below 0.001, else the number), with a
# non-capturing prefix so the group numbers stay October's; the pattern reads Table 2's Panel 2 block only
# (from its title, never past a \midrule), since Panels 1 and 3 have rows of the same shape
_V_PCELL = r"\\REV\{(?:\$<\$)?" + NUM + r"\}"
_V_P2_JOINT_TABLE = (r"\\emph\{First paper with the star \(Panel 2\)\}(?:(?!\\midrule).)*?"
                     r"\\REV\{Joint test \(\$p\$\), post-arrival coefficients\} & " + _V_PCELL + r" & " + _V_PCELL
                     + r" & " + _V_PCELL + r" \\\\ \\REV\{\\quad event clusters\} & " + _V_PCELL + r" & " + _V_PCELL
                     + r" & " + _V_PCELL)
_V_ROB_PERM_PASS = (r"the chemistry estimate of Panel 2 depend on when the stars actually arrived \(\$p=" + NUM
                    + r"\$ and " + NUM + r";")
_V_ROB_PERM_FAIL = (r"The check cannot show the same for the economics estimate of Panel 2 \(\$p=" + NUM
                    + r"\$\), the chemistry estimate of Panel 1 \(\$p=" + NUM + r"\$\)")
_V_ROB_FILL = (r"In economics the placebo test still fails under both fillings \(\$p<" + NUM + r"\$ and \$p="
               + NUM + r"\$\)")

VAULT_OVERLAY_REANCHOR = {
    # sec4_p3.tex: the Panel 3 paragraph (the date-shift result moved here from Section 4.2)
    "p3 econ ATE 0.044pp": ("sec4_p3.tex", _V_P3_ATE),
    "p3 date-shift vs reported 0.044": ("sec4_p3.tex", _V_P3_ATE),
    "p3 null-sim vs reported econ 0.044": ("sec4_p3.tex", _V_P3_ATE),
    "p3 econ SE pair 0.053": ("sec4_p3.tex", r"below that of comparison pairs \(standard error " + NUM
                              + r", clustered by pair\)"),
    "p3 econ pre rate 0.303": ("sec4_p3.tex", r"a gap of about a fifth of the " + NUM + r" percent pre-arrival rate"),
    "p3 chem fall 0.466pp": ("sec4_p3.tex", _V_P3_CHEM),
    "p3 chem pre rate 0.708": ("sec4_p3.tex", _V_P3_CHEM),
    "p3 chem CI lower 1.047": ("sec4_p3.tex", _V_P3_CHEM_CI),
    "p3 chem CI upper 0.114": ("sec4_p3.tex", _V_P3_CHEM_CI),
    "p3 math base rate 0.197": ("sec4_p3.tex", r"rules out falls larger than about a fifth of the " + NUM
                                + r" percent pre-arrival rate"),
    "p3 chem fourth-year coefficient -2.108": ("sec4_p3.tex", _V_P3_Y4),
    "p3 chem fourth-year se 1.664": ("sec4_p3.tex", _V_P3_Y4),
    "p3 chem fourth-year share of the average 77.5%": ("sec4_p3.tex", _V_P3_Y4),
    "p3 date-shift econ k1 0.104": ("sec4_p3.tex", _V_P3_DS),
    "p3 date-shift econ k2 0.077": ("sec4_p3.tex", _V_P3_DS),
    "p3 date-shift econ joint p<0.001": ("sec4_p3.tex", _V_P3_DS_P),
    "rob P3 date-shift econ fails p<0.001": ("sec4_p3.tex", _V_P3_DS_P),
    "p3 econ raw path -6 0.205": ("sec4_p3.tex", _V_P3_RAW),
    "p3 econ raw path -1 0.387": ("sec4_p3.tex", _V_P3_RAW),
    "p3 econ raw path 0 0.396": ("sec4_p3.tex", _V_P3_RAW),
    "p3 econ raw path 5 0.220": ("sec4_p3.tex", _V_P3_RAW),
    # the Panel 3 figure caption now refers to Figure p2's notes; the Panel 3 year cap is printed in Table 2
    "p3 fig caption year cap 2024": ("tab_main_results.tex", r"First tie between colleagues \(Panel 3\).*?"
                                     r"Raw rate after arrival, to " + NUM, 1),
    # the shuffled-years run count moved from Section 4.2 to Section 3
    "p3 perm count 500": ("sec3_strategy.tex", _V_PERM_RUNS, 1),
    "p3 perm counts equal across disciplines": ("sec3_strategy.tex", _V_PERM_RUNS, 1),
    "p3 perm counts equal math": ("sec3_strategy.tex", _V_PERM_RUNS, 1),
    # tab_robustness.tex: shorter row labels; the t-ranked shuffled p-values moved into the notes
    "p1 prose by-route network ate": ("tab_robustness.tex", _V_ROUTE_NET),
    "p1 prose by-route network se": ("tab_robustness.tex", _V_ROUTE_NET),
    "p1 prose by-route roster ate": ("tab_robustness.tex", _V_ROUTE_ROS),
    "p1 prose by-route roster se": ("tab_robustness.tex", _V_ROUTE_ROS),
    "causal P1 chem shuffled-years p by t-statistic 0.084": ("tab_robustness.tex", _V_T_RANKED, 2),
    "causal P2 math shuffled-years p by t-statistic 0.006": ("tab_robustness.tex", _V_T_RANKED, 1),
    # sec4_p1.tex
    "p1 prose joint math person p=0.009": ("sec4_p1.tex", _V_P1_JOINT_MATH),
    "p1 prose joint math event p=0.008": ("sec4_p1.tex", _V_P1_JOINT_MATH),
    "p1 prose placebo chem p=0.856": ("sec4_p1.tex", _V_P1_PLACEBO),
    "p1 prose placebo math p=0.175": ("sec4_p1.tex", _V_P1_PLACEBO),
    "p1 prose placebo econ p=0.003": ("sec4_p1.tex", _V_P1_PLACEBO),
    # sec4_robustness.tex: the earlier-star split (Section 4.1's footnote moved here)
    "p1 prose doublestar complement events 95": ("sec4_robustness.tex", _V_P1_OVERLAP),
    "p1 prose doublestar complement placebo p=0.003": ("sec4_robustness.tex", _V_P1_OVERLAP),
    "p1 prose doublestar complement ate 0.380": ("sec4_robustness.tex", _V_P1_BOTH),
    "p1 prose doublestar ate 0.711": ("sec4_robustness.tex", _V_P1_BOTH),
    "p1 prose doublestar se 0.200": ("sec4_robustness.tex", _V_P1_BOTH),
    "p1 prose bracket low 0.38": ("sec4_robustness.tex", _V_P1_BOTH),
    "p1 prose bracket high 0.71": ("sec4_robustness.tex", _V_P1_BOTH),
    "p1 prose doublestar footnote same-year of 18": ("sec4_robustness.tex", _V_P1_BOTH),
    "p1 prose doublestar footnote dropped 95": ("sec4_robustness.tex", _V_P1_EARLIER, 1),
    "p1 prose doublestar footnote of 113": ("sec4_robustness.tex", _V_P1_EARLIER, 2),
    # sec4_p2.tex
    "p2 prose ATE econ": ("sec4_p2.tex", _V_P2_ATE),
    "p2 prose se person econ": ("sec4_p2.tex", _V_P2_ATE),
    "p2 prose ATE chem": ("sec4_p2.tex", _V_P2_ATE),
    "p2 prose se person chem": ("sec4_p2.tex", _V_P2_ATE),
    "p2 prose ATE math": ("sec4_p2.tex", _V_P2_ATE),
    "p2 prose se person math": ("sec4_p2.tex", _V_P2_ATE),
    "p2 prose raw pre econ": ("sec4_p2.tex", _V_P2_RAW),
    "p2 prose raw pre chem": ("sec4_p2.tex", _V_P2_RAW),
    "p2 prose raw pre math": ("sec4_p2.tex", _V_P2_RAW),
    "p2 prose year cap": ("sec4_p2.tex", _V_P2_RAW),
    "p2 prose raw post econ": ("sec4_p2.tex", _V_P2_RAW),
    "p2 prose raw post chem": ("sec4_p2.tex", _V_P2_RAW),
    "p2 prose raw post math": ("sec4_p2.tex", _V_P2_RAW),
    "p2 prose joint math person p=0.066": ("sec4_p2.tex", _V_P2_JOINT_MATH, 1),
    "p2 prose joint math event p=0.109": ("sec4_p2.tex", _V_P2_JOINT_MATH, 2),
    # the event-clustered joint p-values of economics and chemistry are printed only in Table 2
    "p2 prose joint econ event p=0.003": ("tab_main_results.tex", _V_P2_JOINT_TABLE, 4),
    "p2 prose joint econ+chem event p<0.001": ("tab_main_results.tex", _V_P2_JOINT_TABLE, 5),
    "p2 prose path chem ell=4": ("sec4_p2.tex", r"In chemistry it is largest four years after \(" + NUM + r", "
                                 + NUM + r"\)"),
    "p2 fig caption year cap 2024": ("sec4_p2.tex", r"Lower row: raw rate to " + NUM + r"\."),
    # sec4_causal.tex
    "causal P1 chem shuffled-years p 0.144": ("sec4_causal.tex", r"cannot show that the fall depends on when the "
                                              r"stars actually arrived \(\$p=" + NUM + r"\$\)"),
    "causal P2 math shuffled-years p 0.146": ("sec4_causal.tex", r"rejects with neither cluster choice, and shuffled "
                                              r"arrival years give \$p=" + NUM + r"\$"),
    # sec4_robustness.tex
    "rob P1 network date-shift econ p<0.001": ("sec4_robustness.tex", r"The date-shift test also passes for network "
                                               r"incumbents in all three disciplines \(\$p=" + NUM),
    "rob shuffled-years P1 econ p 0.018": ("sec4_robustness.tex", _V_ROB_PERM_PASS),
    "rob shuffled-years P2 chem p 0.012": ("sec4_robustness.tex", _V_ROB_PERM_PASS),
    "rob shuffled-years P2 econ p 0.084": ("sec4_robustness.tex", _V_ROB_PERM_FAIL),
    "rob shuffled-years P1 chem p 0.144": ("sec4_robustness.tex", _V_ROB_PERM_FAIL),
    "rob missing-output econ placebo p, zero filling <0.001": ("sec4_robustness.tex", _V_ROB_FILL),
    "rob missing-output econ placebo p, own-mean filling 0.004": ("sec4_robustness.tex", _V_ROB_FILL),
    "rob star threshold econ placebo p 0.025": ("sec4_robustness.tex", r"fails on the remaining sample\. In economics "
                                                r"the placebo test still fails \(\$p=" + NUM + r"\$\)"),
}
_V_PERM_AS_P = ("the base tree prints the economics Panel 3 shuffled-years result as a p-value (sec4_p3.tex and "
                "tab_robustness.tex), no longer as a percent of runs; the base-tree claim 'base sec4_p3 shuffled "
                "arrival years p (econ)' (N12) pins that p-value")
VAULT_OVERLAY_RETIRE = {
    "p3 econ headline permutation 24 percent": _V_PERM_AS_P,
    "p3 perm pct econ 24": _V_PERM_AS_P,
    "rob star threshold math P2 first ties 25": ("the base tree's star-threshold check (sec4_robustness.tex) no "
                                                 "longer gives the number of first ties in the failed mathematics "
                                                 "Panel 2 sample, and no other base-tree file prints it"),
}
VAULT_OVERLAY_REPHRASE = {
    "r4 4.2 top-5% within one SE (8 cells)": (
        "sec4_robustness.tex",
        "Every estimate stays within one standard error of the main estimate, except in mathematics Panel 2"),
    "r4 4.3 econ P1 placebo rejects (all, roster, network), roster date-shift passes": (
        "sec4_causal.tex", "But the placebo test fails only because of the gaps four and five years before the arrival"),
    "r4 4.3 math P2 no first ties at -2/-1, date-shift not computed": (
        "sec4_robustness.tex",
        "in mathematics the test cannot be computed, because no incumbent first publishes with the star in the "
        "two shifted years"),
    "r4 4.3 math P2 joint tests do not reject": (
        "sec4_causal.tex", "The joint test of the post-arrival coefficients rejects with neither cluster choice"),
    "r4 4.3 P3 lead: every interval includes zero": ("sec4_causal.tex", "every main Panel 3 interval includes zero"),
    # the base tree's Section 3 dropped this footnote; Table 3's note states the same fact
    "r4 3.1 footnote: math P2 date-shift not computable (no first ties at -2/-1)": (
        "tab_robustness.tex", "Date-shift test, n.a.: no first ties in the two shifted years"),
    "r4 4.1 P3 econ raw rate rising before the arrival": (
        "sec4_p3.tex", "The raw rate (Figure~\\ref{fig:p3afar}, lower row) was already rising before the arrival"),
}


# Author tree (2026-10-19), measured by final-12 sentinel_r1: 91 D failures, plus Table 3's
# generated note in B. Keys remain the October names: repin.NAME_KEYED_TABLES renames the two
# pin tables along with claims_table. Reanchors keep the original expected ledger quantity.
_R1_CHEM = (r"In chemistry the estimate is " + NUM + r" percentage points below comparison pairs, "
           r"about a sixth of the " + NUM + r" percent pre-arrival rate\. Its interval, \$-\$" + NUM
           + r" to " + SNUM + r", excludes zero")
_R1_SHIFT = (r"the two economics shifted coefficients are " + SNUM + r" and " + SNUM
            + r" percentage points")
_R1_EXPOSURE = (r"The network adds researchers who are not on the roster: " + NUM + r" of the " + NUM
               + r" incumbent--event pairs in economics, " + NUM + r" of " + NUM + r" in chemistry and "
               + NUM + r" of " + NUM + r" in mathematics enter through the network alone\.")
_R1_MATH = (r"The mathematics estimate, \$-\$" + NUM + r" \(" + NUM
           + r"\), can also be distinguished from zero, its interval running from \$-\$" + NUM
           + r" to " + SNUM + r" log points")
_R1_P1_PATH = (r"reaching \$-\$" + NUM + r" log points in the fifth year in economics, \$-\$" + NUM
               + r" in chemistry and \$-\$" + NUM + r" in mathematics")
_R1_PLACEBO = (r"The joint placebo test passes in economics \(\$p=" + NUM
              + r"\$\) and chemistry \(\$p=" + NUM + r"\$\) but fails in mathematics \(\$p<0\.001\$\)")
_R1_LOEO = (r"Dropping each of the " + NUM + r" economics events in turn leaves the placebo test passing in "
            + NUM + r" runs \(largest \$p=" + NUM + r"\$\)")
_R1_OVERLAP = (r"After the arrival, output falls by " + NUM + r" log points per unit of dose among the "
               + NUM + r"; among the " + NUM + r" the estimate, \$\+\$" + NUM + r" \(" + NUM
               + r"\), cannot be distinguished from zero")
_R1_P2_JOINT = (r"rejects in all three disciplines with incumbent and with event clusters "
                r"\(in mathematics \$p=" + NUM + r"\$ and " + NUM + r"\)")
_R1_P2_PATH = (r"the rise peaks two years after the arrival in economics \(" + NUM
               + r" percentage points, standard error " + NUM + r"\), chemistry \(" + NUM + r", "
               + NUM + r"\) and mathematics \(" + NUM + r", " + NUM + r"\)")
_R1_P2_PERM = (r"In economics and chemistry shuffled arrival years also show that the rise depends on "
               r"when the stars actually arrived \(\$p=" + NUM + r"\$ and \$" + NUM + r"\$\)")
_R1_ROB_PERM = (r"Shuffled arrival years show that the Panel 1 and Panel 2 estimates in economics \(\$p="
                + NUM + r"\$ and " + NUM + r"\) and chemistry \(\$p=" + NUM + r"\$ and " + NUM
                + r"\) depend on when the stars actually arrived")

R1_OVERLAY_REANCHOR = {
    "sec2_data Zenou: same-topic outside 36": (
        "sec2_data.tex", r"are outside the network, and " + NUM + r" of these share at least one subfield with him", 1),
    "p3 chem fall 0.466pp": ("sec4_p3.tex", _R1_CHEM, 1),
    "p3 chem pre rate 0.708": ("sec4_p3.tex", _R1_CHEM, 2),
    "p3 chem CI lower 1.047": ("sec4_p3.tex", _R1_CHEM, 3),
    "p3 chem CI upper 0.114": ("sec4_p3.tex", _R1_CHEM, 4),
    "p3 date-shift econ k1 0.104": ("sec4_p3.tex", _R1_SHIFT, 1),
    "p3 date-shift econ k2 0.077": ("sec4_p3.tex", _R1_SHIFT, 2),
    "sec2 exposure caption network-only 1,817": ("sec2_data.tex", _R1_EXPOSURE, 1),
    "sec2 exposure caption relations 6,643": ("sec2_data.tex", _R1_EXPOSURE, 2),
    "sec3 econ 86 events with pairs": (
        "sec3_strategy.tex", r"With \\REV\{" + NUM + r"\} events in economics \\REV\{the event-clustered errors", 1),
    "p1 prose ATE math": ("sec4_p1.tex", _R1_MATH, 1),
    "p1 prose se person math": ("sec4_p1.tex", _R1_MATH, 2),
    "p1 prose math CI lo": ("sec4_p1.tex", _R1_MATH, 3),
    "p1 prose math CI hi": ("sec4_p1.tex", _R1_MATH, 4),
    "p1 prose joint effects econ p<0.001": (
        "sec4_p1.tex", r"The joint test that the six post-arrival coefficients are zero rejects in both "
        r"\(\$p<" + NUM + r"\$ in each\)", 1),
    "p1 prose path econ ell=5": ("sec4_p1.tex", _R1_P1_PATH, 1),
    "p1 prose path chem ell=5": ("sec4_p1.tex", _R1_P1_PATH, 2),
    "p1 prose path math ell=5": ("sec4_p1.tex", _R1_P1_PATH, 3),
    "p1 prose placebo chem p=0.856": ("sec4_p1.tex", _R1_PLACEBO, 2),
    "p1 prose placebo econ p=0.003": ("sec4_p1.tex", _R1_PLACEBO, 1),
    "p1 prose loeo removals 113": ("sec4_robustness.tex", _R1_LOEO, 1),
    "p1 prose loeo max placebo p": ("sec4_robustness.tex", _R1_LOEO, 3),
    "p1 prose doublestar complement ate 0.380": ("sec4_robustness.tex", _R1_OVERLAP, 1),
    "p1 prose doublestar ate 0.711": ("sec4_robustness.tex", _R1_OVERLAP, 4),
    "p1 prose doublestar se 0.200": ("sec4_robustness.tex", _R1_OVERLAP, 5),
    "p1 prose bracket low 0.38": ("sec4_robustness.tex", _R1_OVERLAP, 1),
    "p1 prose bracket high 0.71": ("sec4_robustness.tex", _R1_OVERLAP, 4),
    "p1 prose doublestar footnote same-year of 18": ("sec4_robustness.tex", _R1_OVERLAP, 3),
    "p2 prose joint math person p=0.066": ("sec4_p2.tex", _R1_P2_JOINT, 1),
    "p2 prose joint math event p=0.109": ("sec4_p2.tex", _R1_P2_JOINT, 2),
    "p2 prose path econ ell=2": ("sec4_p2.tex", _R1_P2_PATH, 1),
    "p2 prose path math ell=2": ("sec4_p2.tex", _R1_P2_PATH, 5),
    "p2 prose path math ell=2 se 0.153": ("sec4_p2.tex", _R1_P2_PATH, 6),
    "causal P1 chem shuffled-years p 0.144": (
        "sec4_causal.tex", r"In chemistry the placebo test passes on the full sample and both tests pass for "
        r"network incumbents, but the date-shift test fails on the full sample and both tests fail for roster "
        r"incumbents\. Shuffled arrival years show that the fall depends on when the stars actually arrived "
        r"\(\$p=" + NUM + r"\$\)", 1),
    "causal P2 econ shuffled-years p 0.084": ("sec4_causal.tex", _R1_P2_PERM, 1),
    "causal P2 chem shuffled-years p 0.012": ("sec4_causal.tex", _R1_P2_PERM, 2),
    "causal P2 math shuffled-years p 0.146": (
        "sec4_causal.tex", r"In mathematics the joint test of the post-arrival coefficients rejects with both "
        r"cluster choices, but shuffled arrival years cannot show this dependence \(\$p=" + NUM + r"\$\)", 1),
    "causal P3 econ median-dose cut 0.079": (
        "sec4_causal.tex", r"In economics a tighter topic condition keeps the estimate negative \(\$-\$"
        + NUM + r" percentage points\)", 1),
    "rob overlap: 95 events with an earlier arrival": ("sec4_robustness.tex", _R1_OVERLAP, 2),
    "p3 date-shift econ joint p<0.001": (
        "sec4_p3.tex", r"The test fails in economics \(\$p=" + NUM + r"\$\), chemistry \(\$p<0\.001\$\)", 1),
    "rob P3 date-shift econ fails p<0.001": (
        "sec4_p3.tex", r"The test fails in economics \(\$p=" + NUM + r"\$\), chemistry \(\$p<0\.001\$\)", 1),
    "rob P1 network date-shift econ p<0.001": (
        "sec4_robustness.tex", r"The date-shift test passes for network incumbents in all three disciplines "
        r"\(\$p=" + NUM + r"\$, 0\.821 and 0\.124\)", 1),
    "rob shuffled-years P1 econ p 0.018": ("sec4_robustness.tex", _R1_ROB_PERM, 1),
    "rob shuffled-years P2 econ p 0.084": ("sec4_robustness.tex", _R1_ROB_PERM, 2),
    "rob shuffled-years P1 chem p 0.144": ("sec4_robustness.tex", _R1_ROB_PERM, 3),
    "rob shuffled-years P2 chem p 0.012": ("sec4_robustness.tex", _R1_ROB_PERM, 4),
    "rob missing-output econ placebo p, own-mean filling 0.004": (
        "sec4_robustness.tex", r"In economics the placebo test fails under both fillings \(\$p=0\.001\$ and \$p="
        + NUM + r"\$\), unlike on the main sample", 1),
    "rob star threshold econ placebo p 0.025": (
        "sec4_robustness.tex", r"The placebo test passes in economics \(\$p=" + NUM
        + r"\$\) and fails in chemistry \(\$p=0\.048\$\) and mathematics \(\$p<0\.001\$\)", 1),
}
R1_OVERLAY_RETIRE = {
    "p3 chem pairs 11,466": "The author deleted the Section 2 Panel 3 pair-count sentence and its pair-per-arrival footnote in phase 2b.",
    "p3 cut pos econ pairs 90,325": "The author deleted the Section 2 Panel 3 pair-count sentence and its pair-per-arrival footnote in phase 2b.",
    "sec2 P3 econ pairs 23,758": "The author deleted the Section 2 Panel 3 pair-count sentence and its pair-per-arrival footnote in phase 2b.",
    "sec2 P3 chem pairs 2,466": "The author deleted the Section 2 Panel 3 pair-count sentence and its pair-per-arrival footnote in phase 2b.",
    "sec2 P3 math pairs 2,770": "The author deleted the Section 2 Panel 3 pair-count sentence and its pair-per-arrival footnote in phase 2b.",
    "sec2 centre roster added chem 134": "Author decision 4 deleted the research-centre count footnote in sec2_data.tex.",
    "sec2 centre roster added math 28": "Author decision 4 deleted the research-centre count footnote in sec2_data.tex.",
    "sec2 chem roster no spell starts in 2024": "Author decision 4 deleted the roster-edge footnote in sec2_data.tex.",
    "sec2 math roster edge after 2020": "Author decision 4 deleted the roster-edge footnote in sec2_data.tex.",
    "sec2 chem roster edge nominal in 2024": "Author decision 4 deleted the roster-edge footnote in sec2_data.tex.",
    "sec2 zero-roster events 1": "Author decision 4 deleted the zero-roster footnote in sec2_data.tex.",
    "sec2 zero-roster of 113 events": "Author decision 4 deleted the zero-roster footnote, including its event denominator.",
    "sec2 P3 econ events-without-pairs 30": "The economics no-pair sentence was deleted: every R1 economics arrival contributes pairs.",
    "sec2 P3 no-pair arrivals: economics events 113": "The economics no-pair sentence and its denominator were deleted; only chemistry loses an arrival in R1.",
    "p1 prose joint effects chem p=0.008": "The exact p is no longer printed; replaced by r1 P1 joint effects econ and chem below 0.001.",
    "p1 prose joint math person p=0.009": "The exact p is no longer printed; replaced by r1 P1 math joint tests below 0.001.",
    "p1 prose joint math event p=0.008": "The exact p is no longer printed; replaced by r1 P1 math joint tests below 0.001.",
    "p1 prose placebo math p=0.175": "The exact p is no longer printed; replaced by r1 P1 math placebo below 0.001.",
    "p2 prose path chem ell=4": "The fourth-year chemistry value was deleted; replaced by r1 P2 peaks two years after arrival.",
    "causal P1 chem shuffled-years p by t-statistic 0.084": "The author deleted the Table 3 t-ranking sentence: no R1 cell crosses 0.05 when ranked by t.",
    "causal P2 math shuffled-years p by t-statistic 0.006": "The author deleted the Table 3 t-ranking sentence: no R1 cell crosses 0.05 when ranked by t.",
    "rob missing-output econ placebo p, zero filling <0.001": "The less-than premise is false under R1; replaced by r1 missing-output econ placebo rounds to 0.001.",
}
# Base-tree and r4 claims with unchanged predicates; r4 entries are bound as sentence rephrases.
R1_BASE_REANCHOR = {
    "base sec3 example Models 2-3 none left at the fifth year": (
        "sec3_strategy.tex", "2021, so none is left."),
    "base sec3 math Panel 3 events with pairs": (
        "sec3_strategy.tex", r"events in chemistry and \\REV\{" + NUM
        + r"\} in mathematics \\REV\{\(all but one chemistry event contribute pairs to Panel 3\)", 1),
    "r4 5 top-5% within one SE (econ, chem)": (
        "sec5_conclusion.tex", "citations leaves every estimate within one standard error of the main one"),
    "r4 4.3 P2 date-shift passes econ, chem": (
        "sec4_causal.tex", "In all three disciplines the date-shift test passes"),
    "r4 4.3 P3 econ estimate negative, tighter topic condition too": (
        "sec4_causal.tex", "In economics a tighter topic condition keeps the estimate negative"),
    "r4 5 overlap: placebo rejects only after an earlier star": (
        "sec5_conclusion.tex", "In economics the placebo test rejects among arrivals that follow an earlier "
        "star but not among the 16 that do not"),
}
R1_CLAIM_RETIRE = {
    "r4 4.2 top-5% within one SE (8 cells)": "The exception is gone under R1; replaced by r1 top-5% all nine estimates within one SE.",
    "r4 4.2 top-5% math P2 estimator fails": "The estimator succeeds under R1; replaced by r1 top-5% all nine estimates within one SE.",
    "r4 4.3 chem fillings differ by more than 1.5": "The author strengthened the comparison; replaced by r1 chemistry fillings differ by more than two.",
    "r4 4.3 chem P1 six pre-arrival tests pass": "The October predicate is false; replaced by r1 chemistry P1 pre-arrival tests.",
    "r4 4.3 econ P1 placebo rejects (all, roster, network), roster date-shift passes": "The October predicate is false; replaced by r1 economics P1 pre-arrival tests.",
    "r4 4.3 P2 grades: chem shuffled p<0.05 (relatively high), econ not (some)": "Both disciplines now pass; replaced by r1 P2 econ and chem shuffled-years confidence.",
    "r4 4.3 math P2 no first ties at -2/-1, date-shift not computed": "R1 has first ties and a computed test; replaced by r1 P2 date-shift passes all three disciplines.",
    "r4 4.3 math P2 joint tests do not reject": "Both tests reject under R1; replaced by r1 math P2 joint tests reject.",
    "r4 Table 3 math P2 date-shift prints n.a.": "The R1 test is computed; replaced by r1 Table 3 P2 date-shift cells are numeric.",
    "r4 4.3 P1 lead": "Mathematics now also lies below zero; replaced by r1 P1 lead all three output intervals below zero.",
    "r4 4.3 P2 lead": "Mathematics now spans zero; replaced by r1 P2 lead econ and chem positive math spans zero.",
    "r4 4.3 P3 lead: every interval includes zero": "The October predicate is false; replaced by r1 P3 lead econ and chem negative math spans zero.",
    "r4 5 P3 summary": "The October predicate is false; replaced by r1 conclusion P3 intervals and date-shift failures.",
    "r4 4.1 P2 event-clustered interval: econ includes zero, chem and math exclude it": "The October interval pattern is false; replaced by r1 P2 only the math incumbent interval spans zero.",
    "r4 intro staff vs all: no gap 2-3 years before in both, gap 4-5 years before in all three groups": "The October timing predicate is false; replaced by r1 intro placebo passes but date-shift fails.",
    "r4 3.1 footnote: math P2 date-shift not computable (no first ties at -2/-1)": "The obsolete n.a. footnote was deleted; replaced by r1 P2 date-shift passes all three disciplines.",
    "r4 4.1 P3 econ raw rate rising before the arrival": "R1 does not rise monotonically; replaced by r1 P3 econ raw pre-arrival endpoints rise.",
    "base sec2 P3 no-pair math arrivals": "The mathematics no-pair sentence was deleted: every R1 mathematics arrival contributes pairs.",
    "base sec2 P3 math arrivals (of all)": "The mathematics no-pair sentence and denominator were deleted; only chemistry loses an arrival in R1.",
    "base sec2 Zenou Panel 3 pre-window pairs (word)": "The number is now printed in digits; replaced by r1 Zenou P3 pre-window pairs 1026.",
    "base sec2 Zenou all same-topic outside (word)": "The all-incumbents premise is false; replaced by r1 Zenou same-topic outside is a subset.",
}


def _bind_vault_overlay(profile):
    """Bind copies of the vault tables, plus author-tree overrides under 'r1'; 'thesis' stays empty."""
    global VAULT_REANCHOR, VAULT_RETIRE, VAULT_REPHRASE
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; expected one of {PROFILES}")
    on = profile in ("vault", "r1")
    VAULT_REANCHOR = dict(VAULT_OVERLAY_REANCHOR) if on else {}
    VAULT_RETIRE = dict(VAULT_OVERLAY_RETIRE) if on else {}
    VAULT_REPHRASE = dict(VAULT_OVERLAY_REPHRASE) if on else {}
    if profile == "r1":
        both = set(R1_OVERLAY_REANCHOR) & set(R1_OVERLAY_RETIRE)
        if both:
            raise ValueError(f"pins both re-anchored and retired in the R1 overlay: {sorted(both)}")
        short = sorted(k for k, why in R1_CLAIM_RETIRE.items()
                       if not isinstance(why, str) or len(why.strip()) < 30)
        if short:
            raise ValueError(f"R1 claim retirements need a replacement reason of at least 30 characters: {short}")
        VAULT_REANCHOR.update(R1_OVERLAY_REANCHOR)
        VAULT_RETIRE.update(R1_OVERLAY_RETIRE)
        VAULT_REPHRASE.update({k: v for k, v in R1_BASE_REANCHOR.items() if k.startswith("r4 ")})
        for name in R1_OVERLAY_REANCHOR:
            VAULT_RETIRE.pop(name, None)
        for name in R1_OVERLAY_RETIRE:
            VAULT_REANCHOR.pop(name, None)


def claims_for_profile(led, profile):
    """claims_table(led) under a profile's overlay, for tools that use the pins outside main() (the repin
    tools, not shipped: tools/repin_thesis_2026-10/repin_lib.pins_from_set must call this with 'vault' on the base
    tree, or a re-anchored pin is 'not applicable' there). Binds the profile's overlay, as configure does."""
    _bind_vault_overlay(profile)
    return apply_profile(claims_table(led, profile=profile), profile)


def apply_profile(pins, profile):
    """The pin overlay of a profile (V3-FINAL.c). 'thesis' returns `pins` itself (the identity, so the
    default run is today's). 'vault' moves the pins named in VAULT_REANCHOR to a new (file, regex[, group])
    and tags the pins named in VAULT_RETIRE with RETIRED_TAG (graded again if the regex matches); names,
    ledger expressions and notes are never changed. An overlay key that names no pin is kept in
    VAULT_UNMATCHED and becomes a FAIL line (report_vault_unmatched), as SYNC_UNMATCHED does."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; expected one of {PROFILES}")
    VAULT_UNMATCHED[:] = []
    if profile == "thesis":
        return pins
    both = set(VAULT_REANCHOR) & set(VAULT_RETIRE)
    if both:
        raise ValueError(f"pins both re-anchored and retired in the vault overlay: {sorted(both)}")
    short = sorted(k for k, why in VAULT_RETIRE.items() if len(str(why).strip()) <= 30)
    if short:
        raise ValueError(f"vault retirements need a reason of more than 30 characters: {short}")
    names = {t[0] for t in pins}
    VAULT_UNMATCHED[:] = sorted((set(VAULT_REANCHOR) | set(VAULT_RETIRE)) - names)
    out = []
    for name, fname, rx, expected, group, note in pins:
        if name in VAULT_REANCHOR:
            spec = tuple(VAULT_REANCHOR[name])
            if len(spec) == 2:
                fname, rx = spec
            else:
                fname, rx, group = spec
        elif name in VAULT_RETIRE:
            note = f"{RETIRED_TAG}: {VAULT_RETIRE[name]}" + (f"; {note}" if note else "")
        out.append((name, fname, rx, expected, group, note))
    return out


def report_vault_unmatched():
    for key in VAULT_UNMATCHED:
        check("D", f"vault overlay entry {key!r}", False,
              "VAULT_REANCHOR / VAULT_RETIRE key names no pin (renamed pin, or its ledger is missing)")


def grade_pins(pins, tex, compiled, section="D"):
    """Grade (name, file, regex, expected, group, note) pins against normalised tex {file: text}: a
    retired pin whose regex finds nothing is listed; a pin on a file main.tex does not compile says so.
    A pin on one of the tree's tables (D_TABLE_FILES) records file 'tables/<name>' (review R7 #10: the final
    job's gate 2 explains a table-cell FAIL by the tables install changed); a section pin its bare name."""
    for name, fname, rx, expected, group, note in pins:
        rec = f"tables/{fname}" if fname in D_TABLE_FILES else fname
        m = re.search(rx, tex[fname])
        if note.startswith(RETIRED_TAG) and not m:
            check_retired(name, fname, note, file=rec)
            continue
        if fname not in compiled:
            note = "not compiled by main.tex" + (f"; {note}" if note else "")
        if not m:
            check(section, name, False, f"pattern not found in {fname}", note, file=rec)
            continue
        if isinstance(expected, tuple) and expected[0] == "years":
            cell = m.group(group).strip()
            got_years = [] if set(cell) <= set("-– ") else [int(t) for t in re.findall(r"[0-9]{4}", cell)]
            want = list(expected[1])
            ok = got_years == want
            detail = (f"{fname} prints {cell!r} == ledger {want}" if ok
                      else f"{fname} prints {cell!r}; ledger expects {want}")
            check(section, name, ok, detail, note, file=rec)
            continue
        got = parse_num(m.group(group))
        if isinstance(expected, tuple) and expected[0] == "lt":
            _, ledger_p, printed = expected
            ok = abs(got - printed) < 1e-12 and ledger_p < printed
            detail = (f"{fname} prints threshold {m.group(group)} (expected the literal {printed:g}); "
                      f"ledger value {ledger_p:g} is "
                      + ("below it" if ledger_p < got else "NOT below it"))
        elif isinstance(expected, tuple) and expected[0] == "tol":
            ok = abs(got - float(expected[1])) <= expected[2]
            detail = (f"{fname} prints {m.group(group)} vs ledger {expected[1]} "
                      f"(|diff| {'<=' if ok else '>'} {expected[2]:g})")
        else:
            ok = abs(got - float(expected)) < 1e-9
            detail = (f"{fname} prints {m.group(group)} == ledger {expected}" if ok
                      else f"{fname} prints {m.group(group)}; ledger expects {expected}")
        check(section, name, ok, detail, note, file=rec)


def section_d(led):
    tex = {f: norm_tex(SECTIONS / f) for f in D_SECTION_FILES}
    tex.update({f: norm_tex(D_TABLES / f) for f in D_TABLE_FILES})
    # main.tex sits one level above sections/ in the thesis tree; a scratch --sections-dir
    # copy may place a perturbed main.tex alongside the section files and it will be used
    # (else a --tree-root's main.tex, else the thesis root's: _main_tex()).
    main_tex = _main_tex()
    tex["main.tex"] = norm_tex(main_tex)
    # The appendices and tab_disciplines are still pinned but no longer compiled (the 2026-09-13
    # draft dropped them): their checks say so, so a green run is not read as coverage of the PDF.
    compiled = compiled_files(main_tex, SECTIONS)
    # R1 P3 (V3-FINAL.c): the profile overlay; 'thesis' (the default) is the identity
    pins = apply_profile(claims_table(led, profile=PROFILE), PROFILE)
    for key in SYNC_UNMATCHED:
        check("D", f"sync table entry {key!r}", False,
              "SYNC_REANCHOR / SYNC_RETIRE key names no pin (renamed pin, or its ledger is missing)")
    report_vault_unmatched()
    grade_pins(pins, tex, compiled)
    # Section 4.2.4 prints the ratio of the two economics fillings as a word (supervisor round 4, #43).
    l_rb = led.get("robustness")
    if l_rb:
        v = l_rb["p1_variants"]["econ"]
        ratio = v["missing_as_zero"]["ate_log"] / v["missing_as_own_mean"]["ate_log"]
        m = re.search(r"so its direction does not depend on how missing output is treated, but its size "
                      r"does: the two economics estimates are about (\w+) times apart", tex["sec4_robustness.tex"])
        words = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
        ok = bool(m) and words.get(m.group(1)) == round(ratio)
        check("D", "rob missing-output econ fillings ratio (about three times)", ok,
              (f"sec4_robustness.tex prints 'about {m.group(1)} times'" if m else "pattern not found")
              + f"; ledger ratio {ratio:.2f}", kind="claim", anchor_found=bool(m))


# ---------------------------------------------------------------------------
# D (continued). The four P1/P2 tables, cell by cell, vs the p1p2 ledger — an INDEPENDENT
# re-derivation of every number the tables print (2026-08-30 P1+P2 exhibits). Section B's
# byte-identity proves repo table == thesis table; these checks prove each printed cell equals
# the ledger quantity its row label claims, so a generator that mapped a wrong ledger key into
# a row could not stay green even with both copies sharing the bug.
# ---------------------------------------------------------------------------
def _cellval(cell):
    """Parse one printed table cell: '$-$0.378' / '(0.062)' / '10{,}564' / '116' -> float."""
    return parse_num(cell.strip().strip("()").strip())


def _p1p2_row(tex, label_rx, fname, name, expected3, transform=lambda c: c, file=None):
    """One three-column table row: capture the three \\REV cells after the label, compare each
    (after `transform`, e.g. stripping parens) with the expected ledger values. file: the records'
    tree path ('tables/<name>' for a table read from D_TABLES; review R7 #10), None otherwise."""
    m = re.search(r"\\REV\{" + label_rx + r"\}" + r" & \\REV\{(.*?)\} & \\REV\{(.*?)\} & \\REV\{(.*?)\} \\\\", tex)
    if not m:
        check("D", name, False, f"row pattern not found in {fname}", file=file)
        return
    for got_cell, (col, want) in zip(m.groups(), expected3):
        _p1p2_cell(f"{name} [{col}]", fname, transform(got_cell), want, file=file)


def _p1p2_cell(name, fname, cell, want, file=None):
    cell = cell.strip()
    if isinstance(want, tuple) and want[0] == "failed":   # the ledger records a FAILED run (null)
        ok = cell == "failed"
        check("D", name, ok, f"{fname} prints {cell!r}; the ledger records a failed run (null), printed 'failed'",
              file=file)
        return
    if isinstance(want, tuple) and want[0] == "lt":       # printed '$<$0.001', ledger p below it
        ok = cell == "$<$0.001" and want[1] < 0.001
        check("D", name, ok, f"{fname} prints {cell!r}; ledger p {want[1]:g} "
                             + ("< 0.001" if want[1] < 0.001 else "NOT < 0.001"), file=file)
        return
    try:
        got = _cellval(cell)
    except Exception:
        check("D", name, False, f"{fname} cell {cell!r} did not parse as a number", file=file)
        return
    ok = abs(got - float(want)) < 1e-9
    check("D", name, ok, (f"{fname} prints {cell!r} == ledger {want}" if ok
                          else f"{fname} prints {cell!r}; ledger expects {want}"), file=file)


def _pv(p):
    """Expected form for a printed p-value cell: the 'lt' marker below 0.001, else the rounding; a
    run that FAILED in the cal2026-10 rebuild (the ledger holds null) prints 'failed' (2026-09-23)."""
    if p is None:
        return ("failed",)
    return ("lt", p) if p < 0.001 else round(p, 3)


def section_d_p1p2_tables(led):
    p = led["p1p2"]
    if p is None:
        check("D", "p1p2 table cells", False, "data_numbers_p1p2.json missing")
        return
    tex = {f: norm_tex(D_TABLES / f)
           for f in ("tab_p1_main.tex", "tab_p1_full.tex", "tab_p2_main.tex", "tab_p2_full.tex")}
    FF = [("econ", "econ"), ("chemistry", "chem"), ("math_stats", "math")]

    # ---- tab_p1_main ----
    t = tex["tab_p1_main.tex"]
    P1 = {f: p[f"p1_{f}"] for f, _ in FF}
    rows = [
        (r"Average effect per unit of dose \(log points\)", "P1 ATE (log points)",
         lambda c: c["ate_log"], lambda x: x),
        (r"\\quad s\.e\., incumbent clusters", "P1 s.e. incumbent", lambda c: c["se_person"], lambda x: x),
        (r"\\quad s\.e\., event clusters", "P1 s.e. event", lambda c: c["se_event"], lambda x: x),
        (r"Percent change per unit of dose, \$100\(e\^\{b\}-1\)\$", "P1 percent change",
         lambda c: c["ate_pct"], lambda x: x),
        (r"Incumbent--event relations", "P1 relations", lambda c: c["relations"], lambda x: x),
        (r"\\quad with positive dose", "P1 relations with dose", lambda c: c["relations_with_dose"], lambda x: x),
        (r"Switching relations at \$\\ell=0\$", "P1 switchers ell=0", lambda c: c["switchers_ell0"], lambda x: x),
        (r"Incumbents", "P1 incumbents", lambda c: c["persons"], lambda x: x),
        (r"Events", "P1 events", lambda c: c["events"], lambda x: x),
        (r"Incumbent--event--years", "P1 obs", lambda c: c["obs"], lambda x: x),
    ]
    for label_rx, name, get, _tr in rows:
        _p1p2_row(t, label_rx, "tab_p1_main.tex", f"tab_p1_main {name}",
                  [(sh, get(P1[f])) for f, sh in FF], file="tables/tab_p1_main.tex")
    m = re.findall(r"Joint test \(\$p\$\), post-arrival coefficients\} & \\REV\{(.*?)\} & \\REV\{(.*?)\} & "
                   r"\\REV\{(.*?)\} \\\\ \\REV\{\\quad event clusters\} & \\REV\{(.*?)\} & \\REV\{(.*?)\} & "
                   r"\\REV\{(.*?)\} \\\\ \\REV\{Joint test \(\$p\$\), placebo coefficients\} & \\REV\{(.*?)\} & "
                   r"\\REV\{(.*?)\} & \\REV\{(.*?)\} \\\\ \\REV\{\\quad event clusters\} & \\REV\{(.*?)\} & "
                   r"\\REV\{(.*?)\} & \\REV\{(.*?)\} \\\\", t)
    if not m:
        check("D", "tab_p1_main joint-test block", False, "pattern not found in tab_p1_main.tex",
              file="tables/tab_p1_main.tex")
    else:
        cells = m[0]
        keys = ["p_joint_effects_person", "p_joint_effects_event",
                "p_joint_placebo_person", "p_joint_placebo_event"]
        for r_i, key in enumerate(keys):
            for c_i, (f, sh) in enumerate(FF):
                _p1p2_cell(f"tab_p1_main P1 {key} [{sh}]", "tab_p1_main.tex",
                           cells[r_i * 3 + c_i], _pv(P1[f][key]), file="tables/tab_p1_main.tex")
    ci = re.search(r"95\\% CI, incumbent clusters\} & \\REV\{(.*?)\} & \\REV\{(.*?)\} & \\REV\{(.*?)\} \\\\", t)
    if not ci:
        check("D", "tab_p1_main CI row", False, "pattern not found", file="tables/tab_p1_main.tex")
    else:
        for got_cell, (f, sh) in zip(ci.groups(), FF):
            lo, hi = got_cell.strip("[]").split(",")
            _p1p2_cell(f"tab_p1_main P1 CI lo [{sh}]", "tab_p1_main.tex", lo, P1[f]["ci95_person"][0],
                       file="tables/tab_p1_main.tex")
            _p1p2_cell(f"tab_p1_main P1 CI hi [{sh}]", "tab_p1_main.tex", hi, P1[f]["ci95_person"][1],
                       file="tables/tab_p1_main.tex")

    # ---- tab_p2_main ----
    t = tex["tab_p2_main.tex"]
    P2 = {f: p[f"p2_{f}"] for f, _ in FF}
    rows = [
        (r"Average post-arrival effect \(pp per year\)", "P2 ATE (pp)", lambda c: c["ate_pp"]),
        (r"\\quad s\.e\., incumbent clusters", "P2 s.e. incumbent", lambda c: c["se_person_pp"]),
        (r"\\quad s\.e\., event clusters", "P2 s.e. event", lambda c: c["se_event_pp"]),
        (r"Raw rate before arrival \(\\% per year\)", "P2 raw rate pre", lambda c: c["rate_pre_pp"]),
        (r"Raw rate after arrival, to " + str(p["year_cap"]) + r" \(\\% per year\)",
         "P2 raw rate post", lambda c: c["rate_post_obs_pp"]),
        (r"Incumbent--star relations", "P2 relations", lambda c: c["relations"]),
        (r"First ties", "P2 first ties", lambda c: c["first_ties"]),
        (r"Switching relations at \$\\ell=0\$", "P2 switchers ell=0", lambda c: c["switchers_ell0"]),
        (r"Incumbents", "P2 incumbents", lambda c: c["persons"]),
        (r"Events", "P2 events", lambda c: c["events"]),
        (r"Relation--years", "P2 rows", lambda c: c["rows"]),
    ]
    for label_rx, name, get in rows:
        _p1p2_row(t, label_rx, "tab_p2_main.tex", f"tab_p2_main {name}",
                  [(sh, get(P2[f])) for f, sh in FF], file="tables/tab_p2_main.tex")
    m = re.search(r"Joint test \(\$p\$\), post-arrival coefficients\} & \\REV\{(.*?)\} & \\REV\{(.*?)\} & "
                  r"\\REV\{(.*?)\} \\\\ \\REV\{\\quad event clusters\} & \\REV\{(.*?)\} & \\REV\{(.*?)\} & "
                  r"\\REV\{(.*?)\} \\\\", t)
    if not m:
        check("D", "tab_p2_main joint-test block", False, "pattern not found in tab_p2_main.tex",
              file="tables/tab_p2_main.tex")
    else:
        for r_i, key in enumerate(["p_joint_effects_person", "p_joint_effects_event"]):
            for c_i, (f, sh) in enumerate(FF):
                _p1p2_cell(f"tab_p2_main P2 {key} [{sh}]", "tab_p2_main.tex",
                           m.groups()[r_i * 3 + c_i], _pv(P2[f][key]), file="tables/tab_p2_main.tex")
    ci = re.search(r"95\\% CI, incumbent clusters\} & \\REV\{(.*?)\} & \\REV\{(.*?)\} & \\REV\{(.*?)\} \\\\", t)
    if not ci:
        check("D", "tab_p2_main CI row", False, "pattern not found", file="tables/tab_p2_main.tex")
    else:
        for got_cell, (f, sh) in zip(ci.groups(), FF):
            lo, hi = got_cell.strip("[]").split(",")
            _p1p2_cell(f"tab_p2_main P2 CI lo [{sh}]", "tab_p2_main.tex", lo, P2[f]["ci95_person_pp"][0],
                       file="tables/tab_p2_main.tex")
            _p1p2_cell(f"tab_p2_main P2 CI hi [{sh}]", "tab_p2_main.tex", hi, P2[f]["ci95_person_pp"][1],
                       file="tables/tab_p2_main.tex")

    # ---- the two full tables, block by block, row by row ----
    ROW_RX = (r"\\REV\{(-?\d+)\} & \\REV\{(.*?)\} & \\REV\{\((.*?)\)\} & \\REV\{\((.*?)\)\} & "
              r"\\REV\{(.*?)\} & \\REV\{(.*?)\} \\\\")
    for fname, panel, cells_by_field, horizon_key in (
            ("tab_p1_full.tex", "P1", P1, None), ("tab_p2_full.tex", "P2", P2, "horizons_pp")):
        t, tf = tex[fname], f"tables/{fname}"
        for (f, sh), disc in zip(FF, ("Economics", "Chemistry", "Mathematics \\\\& Statistics")):
            blk = re.search(r"\\emph\{" + disc + r"\}.*?(?=\\emph\{|\\bottomrule)", t)
            if not blk:
                check("D", f"{fname} {sh} block", False, "discipline block not found", file=tf)
                continue
            c = cells_by_field[f]
            by_ell = {h["ell"]: h for h in (c["horizons"] + c["placebos"] if panel == "P1"
                                            else c[horizon_key])}
            found = re.findall(ROW_RX, blk.group(0))
            want_rows = len(by_ell)
            if len(found) != want_rows:
                check("D", f"{fname} {sh} row count", False,
                      f"{len(found)} horizon rows found; ledger has {want_rows}", file=tf)
            for ell_s, est, se_p, se_e, n, sw in found:
                h = by_ell.get(int(ell_s))
                if h is None:
                    check("D", f"{fname} {sh} ell={ell_s}", False, "ell not in the ledger", file=tf)
                    continue
                for name2, got_cell, want in (("est", est, h["est"]), ("se_person", se_p, h["se_person"]),
                                              ("se_event", se_e, h["se_event"]), ("n", n, h["n"]),
                                              ("switchers", sw, h["switchers"])):
                    _p1p2_cell(f"{fname} {sh} ell={ell_s} {name2}", fname, got_cell, want, file=tf)
            if panel == "P1":
                mm = re.search(r"Average \(switcher-weighted\)\} & \\REV\{(.*?)\} & \\REV\{\} & \\REV\{\} & "
                               r"\\REV\{\} & \\REV\{(.*?)\} \\\\ \\REV\{Per unit of dose\} & \\REV\{(.*?)\} & "
                               r"\\REV\{\((.*?)\)\} & \\REV\{\((.*?)\)\}", blk.group(0))
                if not mm:
                    check("D", f"{fname} {sh} summary rows", False, "pattern not found", file=tf)
                else:
                    for name2, got_cell, want in (
                            ("weighted avg", mm.group(1), c["weighted_avg_effect"]),
                            ("switchers total", mm.group(2), c["switchers_total"]),
                            ("ate per unit of dose", mm.group(3), c["ate_log"]),
                            ("se incumbent", mm.group(4), c["se_person"]),
                            ("se event", mm.group(5), c["se_event"])):
                        _p1p2_cell(f"{fname} {sh} {name2}", fname, got_cell, want, file=tf)
            else:
                mm = re.search(r"Average\} & \\REV\{(.*?)\} & \\REV\{\((.*?)\)\} & \\REV\{\((.*?)\)\} & "
                               r"\\REV\{\} & \\REV\{(.*?)\} \\\\", blk.group(0))
                if not mm:
                    check("D", f"{fname} {sh} average row", False, "pattern not found", file=tf)
                else:
                    for name2, got_cell, want in (
                            ("average (pp)", mm.group(1), c["ate_pp"]),
                            ("se incumbent", mm.group(2), c["se_person_pp"]),
                            ("se event", mm.group(3), c["se_event_pp"]),
                            ("switchers total", mm.group(4), c["switchers_total"])):
                        _p1p2_cell(f"{fname} {sh} {name2}", fname, got_cell, want, file=tf)



# ---------------------------------------------------------------------------
# D (2026-09-13). Section 4.2 tables: each printed cell of tab_robustness.tex equals the ledger
# quantity its row label claims (byte-identity in section B proves repo == thesis; this proves
# the generator mapped the right key into the right row). A few appendix rows are pinned the same
# way where a mapping slip would be invisible (econ-only / chem-math-only rows, the levels row).
# ---------------------------------------------------------------------------
def _rob_cells(tex, label, fname, name, file=None):
    """Return the three printed cells of the row whose label is `label` (LaTeX as printed)."""
    m = re.search(r"\\REV\{" + re.escape(label) + r"\}" + r" & \\REV\{(.*?)\} & \\REV\{(.*?)\} & \\REV\{(.*?)\} \\\\", tex)
    if not m:
        check("D", name, False, f"row {label!r} not found in {fname}", file=file)
        return None
    return m.groups()


def _rob_num(x, d=3):
    """Mirror tables_robustness.py's num(): a rounded zero prints as 0.000, never as -0.000."""
    t = f"{x:.{d}f}"
    if t.lstrip("-").strip("0.") == "":
        t = t.lstrip("-")
    return t.replace("-", "$-$")


def _rob_est_se(name, fname, cell, est, se, file=None):
    mm = re.match(r"^(.*?) \((.*?)\)$", cell.strip())
    if not mm:
        check("D", name, False, f"{fname} cell {cell!r} is not 'estimate (se)'", file=file)
        return
    _p1p2_cell(name + " est", fname, mm.group(1), est, file=file)
    _p1p2_cell(name + " se", fname, mm.group(2), se, file=file)

def section_d_rob_tables(led):
    rb, pp_, p3 = led["robustness"], led["p1p2"], led["p3afar"]
    if rb is None or pp_ is None or p3 is None:
        check("D", "robustness table cells", False, "a ledger JSON is missing")
        return
    FF = [("econ", "econ"), ("chemistry", "chem"), ("math_stats", "math")]
    fname = "tab_robustness.tex"
    # 2026-09-23 sync: the thesis's tables/tab_robustness.tex is now the draft's Table 3 (another
    # generator, byte-checked in section B), so tables_robustness.py's table, which the thesis no
    # longer prints, is checked cell by cell in its own output. tab_rob_p1-3 below are still read
    # from the thesis tables/ (kept there, not compiled).
    t = norm_tex(OUT / fname)
    V = rb["p1_variants"]
    perm = pp_["perm_pvalues"]
    # the label "Main specification" appears once per panel block: slice the text at the block titles
    b1 = t.index("Panel 1: output"); b2 = t.index("Panel 2: first coauthorship"); b3 = t.index("Panel 3: first ties")
    T1, T2, T3 = t[b1:b2], t[b2:b3], t[b3:]
    SHIFT = "Selective hiring and anticipation: arrivals moved two years earlier, joint $p$ of the two pre-arrival horizons"
    PERM = "Estimator: arrival years shuffled across events, permutation $p$"
    est_rows = [  # (block text, label, name, per-field (est, se))
        (T1, "Main specification", "rob P1 main", lambda f: (pp_[f"p1_{f}"]["ate_log"], pp_[f"p1_{f}"]["se_person"])),
        (T1, "Exposure boundary: comparison pool limited to not-yet-exposed relations", "rob P1 not-yet-exposed",
         lambda f: (V[f]["never_exposed_pool"]["ate_log"], V[f]["never_exposed_pool"]["se_person"])),
        (T1, "Measurement: missing output set to zero", "rob P1 missing=0",
         lambda f: (V[f]["missing_as_zero"]["ate_log"], V[f]["missing_as_zero"]["se_person"])),
        (T1, "Measurement: missing output set to the incumbent's own mean", "rob P1 missing=own mean",
         lambda f: (V[f]["missing_as_own_mean"]["ate_log"], V[f]["missing_as_own_mean"]["se_person"])),
        (T1, "Treatment coding: incumbent's empty post-departure years set to zero", "rob P1 post-departure zeros",
         lambda f: (V[f]["post_departure_zeros"]["ate_log"], V[f]["post_departure_zeros"]["se_person"])),
        (T2, "Main specification", "rob P2 main", lambda f: (pp_[f"p2_{f}"]["ate_pp"], pp_[f"p2_{f}"]["se_person_pp"])),
        (T3, "Main specification", "rob P3 main", lambda f: (p3[f]["ate_pp"], p3[f]["se_pair_pp"])),
        (T3, "Exposure boundary: both incumbents at or above the median positive dose", "rob P3 median cut",
         lambda f: (p3[f]["robustness"]["former_main_cut"]["ate_pp"], p3[f]["robustness"]["former_main_cut"]["se_pair_pp"])),
    ]
    for block, label, name, want in est_rows:
        cells = _rob_cells(block, label, fname, name)
        if cells:
            for cell, (f, sh) in zip(cells, FF):
                _rob_est_se(f"{name} [{sh}]", fname, cell, *want(f))
    p_rows = [  # (block, label, name, per-field p)
        (T1, SHIFT, "rob P1 date-shift p", lambda f: rb["p1_date_shift"][f]["p_joint_shifted"]),
        (T1, PERM, "rob P1 permutation p", lambda f: perm[f"p1_{f}"]["p_perm_abs_ate"]),
        (T2, SHIFT, "rob P2 date-shift p", lambda f: rb["p2_date_shift"][f]["p_joint_shifted"]),
        (T2, PERM, "rob P2 permutation p", lambda f: perm[f"p2_{f}"]["p_perm_abs_ate"]),
        (T3, SHIFT, "rob P3 date-shift p", lambda f: rb["p3_date_shift"][f]["p_joint_shifted"]),
        (T3, PERM, "rob P3 permutation p", lambda f: p3[f]["randomization_inference"]["p_two_sided"]),
    ]
    for block, label, name, want in p_rows:
        cells = _rob_cells(block, label, fname, name)
        if cells:
            for cell, (f, sh) in zip(cells, FF):
                _p1p2_cell(f"{name} [{sh}]", fname, cell, _pv(want(f)))
    cells = _rob_cells(T3, "Estimator: mean estimate in panels simulated from pair-age and calendar-year rates", fname, "rob P3 null sim")
    if cells:
        for cell, (f, sh) in zip(cells, FF):
            _p1p2_cell(f"rob P3 null sim [{sh}]", fname, cell, p3[f]["null_simulation"]["dcdh_ate_pp_no_effect_world"])
    # cross-ledger identity: the same frozen files read by two ledgers must give one number
    for f, sh in FF:
        a, b = p3[f]["robustness"]["date_shift_two_years"]["p_joint_shifted"], rb["p3_date_shift"][f]["p_joint_shifted"]
        check("D", f"rob P3 date-shift p: p3afar ledger == robustness ledger [{sh}]", a == b, f"{a} vs {b}")
        for g in p3[f]["robustness"]["cut_grid"]:
            c = rb["p3_cut_grid"][f][g["cut_spec"]]
            ok = abs(round(g["ate_pp"], 3) - c["ate_pp"]) <= 0.0006 and c["pairs"] == g["pairs"]
            check("D", f"rob P3 cut {g['cut_spec']}: p3afar ledger == robustness ledger [{sh}]", ok,
                  f"{g['ate_pp']} / {g['pairs']} vs {c['ate_pp']} / {c['pairs']}")
    # the departure coverage sentence must state the hand verdicts, not the machine screen. R1 M: the ledger
    # has no departure cells (F20, author ruling 2026-10-15), so the departure checks are skipped and the
    # appendix tables must print no departure row instead (end of this function); October always has them
    D = rb.get("departure_econ")
    if D is not None:
        cov = D["coverage"]
        check("D", "rob ledger departure coverage arithmetic",
              cov["departed_verdicts"] + cov["still_there_verdicts"] == cov["verified_verdicts"]
              and cov["econ_events_without_hand_verdict"] == cov["canon_events"] - cov["verified_verdicts"]
              and cov["rule_A_events_dropped"] <= cov["departed_verdicts"],
              f"{cov}")

    # ---- appendix rows where a mapping slip would be silent ----
    NC = rb["no_centre_roster"]
    # the appendix tables are read from the tree's tables/: every check below names that path (R7 #10)
    F1, F2, F3 = "tables/tab_rob_p1.tex", "tables/tab_rob_p2.tex", "tables/tab_rob_p3.tex"

    def nine(tex, label, name, file=None):
        cell = r"\\REV\{((?:[^{}]|\{[^{}]*\})*)\}"   # one cell, allowing one brace level ({,} in counts)
        m = re.search(r"\\REV\{" + re.escape(label) + r"\}" + r"((?: & " + cell + r"){9}) \\\\", tex)
        if not m:
            check("D", name, False, f"row {label!r} not found", file=file); return None
        return re.findall(cell, m.group(1))
    def two_p(cell):
        """The Panel 1 appendix p column holds 'placebo p / joint p'."""
        parts = [x.strip() for x in cell.split("/")]
        return parts if len(parts) == 2 else [cell, cell]
    DEPA = "Star departure, rule A: events whose star left within the window dropped"
    DEPB = "Star departure, rule B: treatment switched off from the departure year"
    CENTRE = "Research-centre staff removed from the roster"
    t1 = norm_tex(D_TABLES / "tab_rob_p1.tex")
    c = nine(t1, DEPA, "rob A1 departure A", file=F1) if D is not None else None
    if c:
        _rob_est_se("rob A1 departure A [econ]", "tab_rob_p1.tex", c[0], D["p1"]["A"]["ate_log"], D["p1"]["A"]["se_person"], file=F1)
        _p1p2_cell("rob A1 departure A person-years [econ]", "tab_rob_p1.tex", c[2], D["p1"]["A"]["obs"], file=F1)
        if "departure_chemistry" in rb and "departure_math_stats" in rb:
            # cal2026-10 (D6): star departure is estimated for all three disciplines (187-event ledger)
            for i, (f, sh) in ((1, ("chemistry", "chem")), (2, ("math_stats", "math"))):
                DF = rb[f"departure_{f}"]["p1"]["A"]
                _rob_est_se(f"rob A1 departure A [{sh}]", "tab_rob_p1.tex", c[3 * i], DF["ate_log"], DF["se_person"], file=F1)
                _p1p2_cell(f"rob A1 departure A person-years [{sh}]", "tab_rob_p1.tex", c[3 * i + 2], DF["obs"], file=F1)
        else:
            check("D", "rob A1 departure A [chem, math] blank", c[3] == "--" and c[6] == "--", "chemistry/mathematics not screened", file=F1)
    c = nine(t1, CENTRE, "rob A1 no-centre", file=F1)
    if c:
        check("D", "rob A1 no-centre [econ] blank", c[0] == "--", "economics has no centre roster", file=F1)
        _rob_est_se("rob A1 no-centre [chem]", "tab_rob_p1.tex", c[3], NC["chemistry"]["p1"]["ate_log"], NC["chemistry"]["p1"]["se_person"], file=F1)
        _rob_est_se("rob A1 no-centre [math]", "tab_rob_p1.tex", c[6], NC["math_stats"]["p1"]["ate_log"], NC["math_stats"]["p1"]["se_person"], file=F1)
    c = nine(t1, "Output in levels (own units, not comparable to the log rows)", "rob A1 levels", file=F1)
    if c:
        for i, (f, sh) in enumerate(FF):
            _rob_est_se(f"rob A1 levels [{sh}]", "tab_rob_p1.tex", c[3 * i], V[f]["levels"]["ate_log"], V[f]["levels"]["se_person"], file=F1)
    c = nine(t1, "Reached through the roster", "rob A1 roster route", file=F1)
    if c:
        for i, (f, sh) in enumerate(FF):
            _rob_est_se(f"rob A1 roster route [{sh}]", "tab_rob_p1.tex", c[3 * i],
                        pp_[f"p1_{f}"]["by_route"]["roster"]["ate_log"], pp_[f"p1_{f}"]["by_route"]["roster"]["se_person"], file=F1)
            pl, pj = two_p(c[3 * i + 1])
            _p1p2_cell(f"rob A1 roster route placebo p [{sh}]", "tab_rob_p1.tex", pl,
                       _pv(rb["p1_pretrend_by_channel"][f]["dept"]["p_joint_placebo_person"]), file=F1)
            _p1p2_cell(f"rob A1 roster route joint p [{sh}]", "tab_rob_p1.tex", pj,
                       _pv(rb["p1_pretrend_by_channel"][f]["dept"]["p_joint_effects_person"]), file=F1)
    c = nine(t1, "Both routes", "rob A1 shifted both routes", file=F1)
    if c:
        for i, (f, sh) in enumerate(FF):
            want = ", ".join(f"{_rob_num(x['est'])} ({_rob_num(x['se'])})"
                             for x in rb["p1_pretrend_by_channel"][f]["union"]["shifted_effects_log"])
            check("D", f"rob A1 shifted coefficients [{sh}]", c[3 * i].strip() == want,
                  f"tab_rob_p1.tex prints {c[3 * i]!r}; ledger expects {want!r}", file=F1)
    t3 = norm_tex(D_TABLES / "tab_rob_p3.tex")
    c = nine(t3, DEPB, "rob A3 departure B", file=F3) if D is not None else None
    if c:
        _rob_est_se("rob A3 departure B [econ]", "tab_rob_p3.tex", c[0], D["p3_pos"]["B"]["ate_pp"], D["p3_pos"]["B"]["se_pair_pp"], file=F3)
        _p1p2_cell("rob A3 departure B pairs [econ]", "tab_rob_p3.tex", c[2], D["p3_pos"]["B"]["pairs"], file=F3)
    c = nine(t3, CENTRE, "rob A3 no-centre", file=F3)
    if c:
        _rob_est_se("rob A3 no-centre [chem]", "tab_rob_p3.tex", c[3], NC["chemistry"]["p3_pos"]["ate_pp"], NC["chemistry"]["p3_pos"]["se_pair_pp"], file=F3)
        _p1p2_cell("rob A3 no-centre pairs [chem]", "tab_rob_p3.tex", c[5], NC["chemistry"]["p3_pos"]["pairs"], file=F3)
    c = nine(t3, "At or above the discipline's median positive dose", "rob A3 median cut", file=F3)
    if c:
        for i, (f, sh) in enumerate(FF):
            cut = rb["p3_cut_grid"][f]["med"]
            _rob_est_se(f"rob A3 median cut [{sh}]", "tab_rob_p3.tex", c[3 * i], cut["ate_pp"], cut["se_pair_pp"], file=F3)
            _p1p2_cell(f"rob A3 median cut joint p [{sh}]", "tab_rob_p3.tex", c[3 * i + 1], _pv(cut["p_joint_effects_pair"]), file=F3)
    t2 = norm_tex(D_TABLES / "tab_rob_p2.tex")
    c = nine(t2, DEPA, "rob A2 departure A", file=F2) if D is not None else None
    if c:
        _rob_est_se("rob A2 departure A [econ]", "tab_rob_p2.tex", c[0], D["p2"]["A"]["ate_pp"], D["p2"]["A"]["se_person_pp"], file=F2)
    c = nine(t2, "Arrivals moved two years earlier: the two shifted coefficients (standard errors), joint $p$",
             "rob A2 shifted", file=F2)
    if c:
        for i, (f, sh) in enumerate(FF):   # the only printed use of the Panel 2 x100 conversion
            want = ", ".join(f"{_rob_num(x['est'])} ({_rob_num(x['se'])})"
                             for x in rb["p2_date_shift"][f]["shifted_effects_pp"])
            if rb["p2_date_shift"][f].get("status", "OK") != "OK":   # cal2026-10: a FAILED run prints 'failed'
                want = "failed"
            check("D", f"rob A2 shifted coefficients [{sh}]", c[3 * i].strip() == want,
                  f"tab_rob_p2.tex prints {c[3 * i]!r}; ledger expects {want!r}", file=F2)
    if D is None:   # R1 M: no departure cells in the ledger, so no appendix table may print a departure row
        for tex, file, tab in ((t1, F1, "A1"), (t3, F3, "A3"), (t2, F2, "A2")):
            n = tex.count("\\REV{Star departure, rule ")
            check("D", f"rob {tab} no star-departure rows (no departure cells in the ledger)", n == 0,
                  f"{file} prints {n} star-departure rows", file=file)


# ---------------------------------------------------------------------------
TAB3_MATH_P2_NA = "r4 Table 3 math P2 date-shift prints n.a."
#: Table 3's Panel 2 date-shift row with n.a. in the mathematics cell, whatever the economics and chemistry
#: p values print (review R7 #8: the October literal '0.697 & 0.156' would be 'not found' once M moves them)
TAB3_MATH_P2_NA_RX = (r"\\REV\{\\quad date-shift test\} & \\REV\{[^}]*\} & \\REV\{[^}]*\} & "
                      r"\\REV\{n\.a\.\}")


def claim_tab3_math_p2_na(tab_text, status):
    """The Table 3 n.a. claim: the row's structure is the anchor; it holds while the ledger records the
    mathematics Panel 2 date-shift run as AUX_FAILED (the reason the cell is n.a.)."""
    found = re.search(TAB3_MATH_P2_NA_RX, tab_text) is not None
    if not found:
        check("D", TAB3_MATH_P2_NA, False, "sentence not found in tab_robustness.tex: the Panel 2 date-shift row "
              "with n.a. in mathematics", file="tab_robustness.tex", kind="claim", anchor_found=False)
    else:
        check("D", TAB3_MATH_P2_NA, status == "AUX_FAILED", "", file="tab_robustness.tex", kind="claim",
              anchor_found=True)


def section_d_r4_claims(led):
    """supervisor round 4 (#45-#51) rewrite of Sections 4.2 (Star threshold), 4.3 and 5: each
    qualitative claim is a ledger inequality, checked while its sentence is printed (a claim whose
    sentence disappears FAILs, so the check cannot go silently stale)."""
    pp, rb, p3 = led["p1p2"], led["robustness"], led["p3afar"]
    F = ("econ", "chemistry", "math_stats")
    tx = {f: norm_tex(SECTIONS / f) for f in ("sec4_causal.tex", "sec4_robustness.tex", "sec5_conclusion.tex",
                                              "sec2_data.tex", "sec4_p2.tex", "sec3_strategy.tex",
                                              "sec4_p3.tex")}
    tx["main.tex"] = norm_tex(_main_tex())
    tx["tab_robustness.tex"] = norm_tex(D_TABLES / "tab_robustness.tex")

    rephrase = VAULT_REPHRASE if PROFILE in ("vault", "r1") else {}   # W3-OVERLAY: the base tree's wording
    claimed = set()

    def claim(name, fname, phrase, ok, detail=""):
        claimed.add(name)
        if name in rephrase:
            fname, phrase = rephrase[name]
        if phrase not in tx[fname]:
            check("D", name, False, f"sentence not found in {fname}: {phrase!r}", file=fname, kind="claim",
                  anchor_found=False)
        else:
            check("D", name, bool(ok), detail, file=fname, kind="claim", anchor_found=True)

    def spans0(lo, hi):
        return lo < 0 < hi

    perm = pp["perm_pvalues"]
    t5 = rb["d7"]["top5"]
    cells = ([(f"P1 {f}", t5[f]["p1"]["ate_log"], pp[f"p1_{f}"]["ate_log"], pp[f"p1_{f}"]["se_person"]) for f in F]
             + [(f"P2 {f}", t5[f]["p2"]["ate_pp"], pp[f"p2_{f}"]["ate_pp"], pp[f"p2_{f}"]["se_person_pp"])
                for f in ("econ", "chemistry")]
             + [(f"P3 {f}", t5[f]["p3_pos"]["ate_pp"], p3[f]["ate_pp"], p3[f]["se_pair_pp"]) for f in F])
    det = "; ".join(f"{n}: |{a}-({m})| = {abs(a - m):.3f} vs SE {s}" for n, a, m, s in cells)
    claim("r4 4.2 top-5% within one SE (8 cells)", "sec4_robustness.tex",
          "Every estimate stays within one standard error of the main one, except in mathematics Panel 2",
          all(abs(a - m) < s for _, a, m, s in cells), det)
    claim("r4 4.2 top-5% math P2 estimator fails", "sec4_robustness.tex",
          "except in mathematics Panel 2, where the estimator fails on the remaining sample",
          t5["math_stats"]["p2"].get("status") == "FAILED")
    claim("r4 5 top-5% within one SE (econ, chem)", "sec5_conclusion.tex",
          "leaves every economics and chemistry estimate within one standard error of the main one",
          all(abs(a - m) < s for n, a, m, s in cells if not n.endswith("math_stats")), det)
    V = rb["p1_variants"]
    fills = {f: (V[f]["missing_as_zero"]["ate_log"], V[f]["missing_as_own_mean"]["ate_log"]) for f in ("econ", "chemistry")}
    claim("r4 5 filling changes the size (econ, chem)", "sec5_conclusion.tex",
          "the size of the output fall depends on how missing output is filled",
          all(z < 0 and o < 0 and z / o > 1.5 for z, o in fills.values()),
          "; ".join(f"{f}: {z}/{o} = {z / o:.2f}" for f, (z, o) in fills.items()))
    z, o = fills["chemistry"]
    claim("r4 4.3 chem fillings differ by more than 1.5", "sec4_causal.tex",
          "differ by a factor of more than one and a half", z < 0 and o < 0 and z / o > 1.5, f"{z / o:.2f}")
    PT = rb["p1_pretrend_by_channel"]
    chem6 = [pp["p1_chemistry"]["p_joint_placebo_person"], rb["p1_date_shift"]["chemistry"]["p_joint_shifted"]] + [
        PT["chemistry"][c][k] for c in ("dept", "network") for k in ("p_joint_placebo_person", "p_joint_shifted")]
    claim("r4 4.3 chem P1 six pre-arrival tests pass", "sec4_causal.tex",
          "placebo and date-shift tests pass on the full sample and for roster and network incumbents",
          all(p > 0.05 for p in chem6), str([round(p, 3) for p in chem6]))
    econ_pl = [pp["p1_econ"]["p_joint_placebo_person"], PT["econ"]["dept"]["p_joint_placebo_person"],
               PT["econ"]["network"]["p_joint_placebo_person"]]
    claim("r4 4.3 econ P1 placebo rejects (all, roster, network), roster date-shift passes", "sec4_causal.tex",
          "But the placebo test rejects: a gap appears four and five years before",
          all(p < 0.05 for p in econ_pl) and PT["econ"]["dept"]["p_joint_shifted"] > 0.05,
          str([round(p, 3) for p in econ_pl]))
    DS2 = rb["p2_date_shift"]
    claim("r4 4.3 P2 date-shift passes econ, chem", "sec4_causal.tex",
          "In economics and chemistry the date-shift test passes",
          all(DS2[f]["p_joint_shifted"] > 0.05 for f in ("econ", "chemistry")))
    claim("r4 4.3 P2 grades: chem shuffled p<0.05 (relatively high), econ not (some)", "sec4_causal.tex",
          "so there one can have a relatively high degree of confidence that the estimated effect is causal; "
          "in economics they cannot show this dependence",
          perm["p2_chemistry"]["p_perm_abs_ate"] < 0.05 <= perm["p2_econ"]["p_perm_abs_ate"])
    raw, m2 = pp["p2_math_stats"]["raw_rate_by_event_time_pp"], pp["p2_math_stats"]
    claim("r4 4.3 math P2 no first ties at -2/-1, date-shift not computed", "sec4_causal.tex",
          "In mathematics no incumbent first publishes with the star in the two years before the arrival, "
          "so the date-shift test cannot be computed",
          raw["-2"] == 0 and raw["-1"] == 0 and DS2["math_stats"].get("status") == "AUX_FAILED")
    art = P["cal"] / "robustness/predate/P2pd2_math_stats.json"   # R1 F7: root from config
    if art.exists():
        a = json.loads(art.read_text())
        if canon.mode(P) == "october":   # the October run failed; an M run may succeed (J1b: it did)
            k2 = [e for e in a["effects"] if e["k"] == 2]
            check("D", "r4 4.3 math P2 date-shift artifact: shifted k=2 estimate 0 with no SE, joint-test run failed",
                  a["predate"]["aux_status"] == "FAILED" and len(k2) == 1 and k2[0]["est"] == 0
                  and k2[0]["se"] is None, _shown(art))
        else:   # R1 M: the ledger records what the artifact says (the run failed, or the same joint p)
            fa, pa = a["predate"].get("aux_status") == "FAILED", a["predate"].get("p_joint_shifted")
            fl, pl = DS2["math_stats"].get("status") == "AUX_FAILED", DS2["math_stats"].get("p_joint_shifted")
            check("D", "r4 4.3 math P2 date-shift artifact: joint-test status and p match the robustness ledger",
                  fa == fl and pa == pl, f"{_shown(art)}: joint-test run {'failed' if fa else 'ok'}, p {pa}; "
                  f"ledger {'AUX_FAILED' if fl else 'ok'}, p {pl}")
    else:
        check("D", "r4 4.3 math P2 date-shift artifact present", False, f"missing: {art}")
    claim("r4 4.3 math P2 joint tests do not reject", "sec4_causal.tex",
          "Neither joint test of the post-arrival coefficients rejects",
          m2["p_joint_effects_person"] > 0.05 and m2["p_joint_effects_event"] > 0.05)
    claimed.add(TAB3_MATH_P2_NA)                   # checked by the row's structure (review R7 #8)
    claim_tab3_math_p2_na(tx["tab_robustness.tex"], DS2["math_stats"].get("status"))
    claim("r4 4.3 P1 lead", "sec4_causal.tex", "implies that in economics and chemistry an arrival lowers the output",
          pp["p1_econ"]["ci95_person"][1] < 0 and pp["p1_chemistry"]["ci95_person"][1] < 0
          and spans0(*pp["p1_math_stats"]["ci95_person"]))
    claim("r4 4.3 P2 lead", "sec4_causal.tex", "implies that in all three disciplines an arrival raises",
          all(pp[f"p2_{f}"]["ci95_person_pp"][0] > 0 for f in F))
    p3ci = all(spans0(*p3[f]["ci95_pair_pp"]) and spans0(p3[f]["ate_pp"] - 1.96 * p3[f]["se_event_pp"],
                                                        p3[f]["ate_pp"] + 1.96 * p3[f]["se_event_pp"]) for f in F)
    claim("r4 4.3 P3 lead: every interval includes zero", "sec4_causal.tex",
          "every Panel 3 confidence interval includes zero", p3ci)
    claim("r4 4.3 P3 econ estimate negative, tighter topic condition too", "sec4_causal.tex",
          "In economics the estimate is negative, and a tighter topic condition keeps it negative",
          p3["econ"]["ate_pp"] < 0 and rb["p3_cut_grid"]["econ"]["med"]["ate_pp"] < 0)
    claim("r4 5 P3 summary", "sec5_conclusion.tex",
          "no main estimate can be distinguished from zero, and the economics estimate also fails the date-shift test",
          p3ci and rb["p3_date_shift"]["econ"]["p_joint_shifted"] < 0.05)
    # 2026-10-01 read-through fixes
    P2 = {f: pp[f"p2_{f}"] for f in F}
    ev_ci = {f: (P2[f]["ate_pp"] - 1.96 * P2[f]["se_event_pp"], P2[f]["ate_pp"] + 1.96 * P2[f]["se_event_pp"]) for f in F}
    claim("r4 4.1 P2 event-clustered interval: econ includes zero, chem and math exclude it", "sec4_p2.tex",
          "with event clusters the economics interval includes zero",
          spans0(*ev_ci["econ"]) and not spans0(*ev_ci["chemistry"]) and not spans0(*ev_ci["math_stats"])
          and all(P2[f]["ci95_person_pp"][0] > 0 for f in F),
          "; ".join(f"{f}: [{lo:.3f}, {hi:.3f}]" for f, (lo, hi) in ev_ci.items()))
    PTE = rb["p1_pretrend_by_channel"]["econ"]
    claim("r4 intro staff vs all: no gap 2-3 years before in both, gap 4-5 years before in all three groups",
          "main.tex", "and neither does that of incumbents as a whole; but both, like the star's wider "
          "coauthorship network, were falling behind four and five years before the star came",
          all(PTE[c]["p_joint_shifted"] > 0.05 for c in ("union", "dept"))
          and all(PTE[c]["p_joint_placebo_person"] < 0.05 for c in ("union", "dept", "network"))
          and all(e["est"] > 0 for c in ("union", "dept", "network") for e in PTE[c]["placebos_log"] if e["ell"] in (-4, -5)),
          str({c: (round(PTE[c]["p_joint_shifted"], 3), round(PTE[c]["p_joint_placebo_person"], 3)) for c in PTE}))
    claim("r4 3.1 footnote: math P2 date-shift not computable (no first ties at -2/-1)", "sec3_strategy.tex",
          "In mathematics it cannot be computed for Panel 2: no incumbent first publishes with the star in the two "
          "years before an arrival",
          raw["-2"] == 0 and raw["-1"] == 0 and DS2["math_stats"].get("status") == "AUX_FAILED")
    r3 = p3["econ"]["raw_rate_by_event_time_pp"]
    claim("r4 4.1 P3 econ raw rate rising before the arrival", "sec4_p3.tex",
          "The raw rate was already rising before the star came",
          all(r3[str(k)] < r3[str(k + 1)] for k in range(-6, -1)), str({k: r3[k] for k in ("-6", "-3", "-1")}))
    nn = P["cal"] / "new_numbers/data_numbers_new_2026-10.json"   # R1 F7: root from config
    m2 = re.search(r"In economics " + NUM + r" percent of network pairs are second-hop links", tx["sec2_data.tex"])
    if nn.exists():
        share = json.loads(nn.read_text())["econ"]["share_twohop_network_channel"]
        check("D", "r4 sec2 footnote econ two-hop share 99 percent", bool(m2) and float(m2.group(1)) == round(100 * share),
              (f"sec2_data.tex prints {m2.group(1)}" if m2 else "pattern not found") + f"; ledger {share} -> {round(100 * share)}",
              kind="claim", anchor_found=bool(m2))
    else:
        check("D", "r4 sec2 footnote econ two-hop share ledger present", False, f"missing: {nn}")
    claim("r4 5 overlap: placebo rejects only after an earlier star", "sec5_conclusion.tex",
          "the placebo test rejects only among arrivals that follow an earlier star",
          pp["p1_doublestar_complement_econ"]["p_joint_placebo"] < 0.05
          and pp["p1_doublestar_econ"]["p_joint_placebo"] > 0.05)
    for key in sorted(set(rephrase) - claimed):   # W3-OVERLAY: a rephrase key that names no claim FAILs
        check("D", f"vault overlay entry {key!r}", False,
              "VAULT_REPHRASE key names no section_d_r4_claims claim (renamed claim?)")


# ---------------------------------------------------------------------------
# D (R1 P3 N12 part 3). BASE_TREE_CLAIMS: Section 2-3 numbers of the author's base tree
# (BASE_TREE_REL, spec 2026-10-12) that no common pin covers. analysis/paper/sec23_number_audit.tsv
# lists every numeral the base tree's sec2_data.tex / sec3_strategy.tex print; its key_needs_pin rows
# name these claims. They run only under --tree base_2026_10_11: some sentences exist only in the base
# tree, and thesis_report must stay 0 FAIL. A claim whose ledger is missing is a FAIL ("not
# evaluated"), never a silent skip. The cohort year of the Section 3.3 example (2016) and the window
# arithmetic around it are design constants (analysis/paper/_fig34_style.G, guarded by N11); the years
# that depend on which economics arrival years exist (the comparison pools) are pinned to
# fig_comparison_pools.json, the N9 generator's own output.
# ---------------------------------------------------------------------------
BASE_TREE_SEC3_NEWPIN_LINES = (175, 184, 186, 188, 190, 211, 232, 234, 260, 276, 322, 337,
                               461, 463, 472, 480, 488, 492, 495, 508, 509, 510)
BASE_TREE_ZENOU_CLAIMS = (
    "base sec2 hops caption Zenou arrival year", "base sec2 window footnote example arrival year",
    "base sec2 window footnote first followed year", "base sec2 window footnote followed-from year (second mention)",
    "base sec2 Zenou arrival year", "base sec2 Zenou roster year", "base sec2 Zenou Panel 1 follows all (union)",
    "base sec2 Zenou Panel 2 pre-window year", "base sec2 Zenou roster count (second mention)",
    "base sec2 Zenou Panel 3 pre-window year", "base sec2 Zenou Panel 2 pre-window count (word)",
    "base sec2 Zenou Panel 3 pre-window pairs (word)",
    "base sec3 example subsection title year", "base sec3 example arrivals year",
    "base sec3 example ell=0 year", "base sec3 example ell=-1 year",
    "base sec2 Zenou all same-topic outside (word)")
BASE_TREE_DOSE_CLAIMS = ("base sec3 average dose of switching relations econ",
                         "base sec3 average dose of switching relations chem",
                         "base sec3 average dose of switching relations math")
BASE_TREE_P3_CLAIMS = ("base sec3 math Panel 3 events with pairs", "base sec4_p3 shuffled arrival years p (econ)")
BASE_TREE_PP_CLAIMS = ("base sec3 shuffled runs", "base sec3 econ arrivals after an earlier star",
                       "base sec3 econ arrivals (of all)")
BASE_TREE_MAIN_CLAIMS = ("base sec2 P3 no-pair math arrivals", "base sec2 P3 math arrivals (of all)")
BASE_TREE_FUNNEL_CLAIMS = ("base sec2 opening release day", "base sec2 opening release year",
                           "base sec2 P1 footnote release day", "base sec2 P1 footnote release year",
                           "base sec2 P1 footnote first-half year")
BASE_TREE_POOL_CLAIMS = (
    "base sec3 example M1 2018 comparisons (first year)", "base sec3 example M1 2018 comparisons (last year)",
    "base sec3 example M1 2016 comparisons from", "base sec3 example M1 2016 comparisons to",
    "base sec3 example M1 2019 comparisons",
    "base sec3 example placebo comparisons (first year)", "base sec3 example placebo comparisons (last year)",
    "base sec3 example placebo comparisons followed from (first)",
    "base sec3 example placebo comparisons followed from (last)",
    "base sec3 example M2 2018 comparisons from", "base sec3 example M2 2018 comparisons to",
    "base sec3 example M2 estimates stop", "base sec3 example M2 last comparisons arrival year",
    "base sec3 example M2 last comparisons followed from", "base sec3 example M2 last comparisons treated from",
    "base sec3 example M3 2018 comparisons from", "base sec3 example M3 2018 comparisons to",
    "base sec3 example M1 four and five years after: zero-dose only",
    "base sec3 example M1 placebos 2012/2011 not followed back",
    "base sec3 example Models 2-3 none left at the fifth year")
BASE_TREE_CLAIM_NAMES = (BASE_TREE_ZENOU_CLAIMS + BASE_TREE_DOSE_CLAIMS + BASE_TREE_P3_CLAIMS
                         + BASE_TREE_PP_CLAIMS + BASE_TREE_MAIN_CLAIMS + BASE_TREE_FUNNEL_CLAIMS
                         + BASE_TREE_POOL_CLAIMS)
assert len(set(BASE_TREE_CLAIM_NAMES)) == len(BASE_TREE_CLAIM_NAMES)
#: ledger keys the base-tree claims print that reach base_tree_claims untraced (int() of _event, a 3-dp
#: float of the p, a parsed date) or as number words, by repin_lib logical ledger: the final job's printed
#: column (pipeline/aws/r1/final_stage._printed_keys) adds them to the keys the traced pins carry (R7 #8)
BASE_TREE_PRINTED_KEYS = {
    "zenou": ("_event", "union", "roster", "p2_followed", "pairs_excluded_prewindow"),
    "funnel": ("snapshot_release_date",),
    "p3afar": ("econ.randomization_inference.p_two_sided",),
}
# the Panels 2-3 pre-arrival window (-6/+10, signed; _fig34_style.M23_LO) and Model 1's (+-5)
_PRE23, _PRE1 = 6, 5
_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
          "nine": 9, "ten": 10}


def _nan_unless(cond, value):
    return value if cond else float("nan")


def base_tree_claims(led):
    """(numeric pins, word pins, phrase claims) of the base tree, from the ledgers present in `led`.
    numeric: (name, file, regex, expected, group, note) graded by grade_pins; word: (name, file, regex
    whose group 1 is a number word, expected int); phrase: (name, file, phrase, ok, detail)."""
    s2, s3, s4 = "sec2_data.tex", "sec3_strategy.tex", "sec4_p3.tex"
    num, words, phrases = [], [], []
    zen, swp, p3, pp = led.get("zenou"), led.get("switchers_p1p2"), led.get("p3afar"), led.get("p1p2")
    main, funnel, pools = led.get("main"), led.get("funnel"), led.get("pools")
    if zen:
        Y = int(str(zen["_event"]).rsplit(":", 1)[1])          # the Zenou arrival (gaps_zenou.json _event)
        fn_rx = (r"For an arrival in " + NUM + r", as in the Z\\'enou example below, pairs are followed from "
                 + NUM)
        n = BASE_TREE_ZENOU_CLAIMS
        num += [(n[0], s2, r"the counts are for Yves Z\\'enou's " + NUM + r" arrival at Monash", Y, 1, ""),
                (n[1], s2, fn_rx, Y, 1, ""),
                (n[2], s2, fn_rx, Y - _PRE23, 2, "Panels 2-3 window -6/+10 (design constant)"),
                (n[3], s2, r"is followed from " + NUM + r" to " + NUM + r" and then leaves", Y - _PRE23, 1,
                 "the hypothetical tie year (2013) is a design constant"),
                (n[4], s2, r"joined Monash University in " + NUM + r" from outside Australia", Y, 1, ""),
                (n[5], s2, r"The Monash economics roster for " + NUM + r" lists", Y, 1, ""),
                (n[6], s2, r"Panel 1 follows all " + NUM, zen["union"], 1, ""),
                (n[7], s2, r"had already published with him before " + NUM, Y - _PRE23, 1, ""),
                (n[8], s2, r"Of the " + NUM + r" on the roster, " + NUM + r" are outside the network",
                 zen["roster"], 1, ""),
                (n[9], s2, r"had already published together before " + NUM, Y - _PRE23, 1, ""),
                (n[12], s3, r"How the Coefficients Are Computed: The " + NUM + r" Arrivals", Y, 1, ""),
                (n[13], s3, r"the economics arrivals of " + NUM + r", among them", Y, 1, ""),
                (n[14], s3, r"For these arrivals " + NUM + r" is \$\\ell=0\$ and " + NUM
                 + r", the year before arrival", Y, 1, ""),
                (n[15], s3, r"For these arrivals " + NUM + r" is \$\\ell=0\$ and " + NUM
                 + r", the year before arrival", Y - 1, 2, "")]
        words += [(n[10], s2, r"Panel 2 follows [0-9,{}]+ of them \((\w+) had already published with him",
                   zen["union"] - zen["p2_followed"]),
                  (n[11], s2, r"Panel 3 follows [0-9,{}]+ \(the other (\w+) had already published together",
                   zen["pairs_excluded_prewindow"])]
        # "N are outside the network, and all M share at least one subfield": 'all' holds only while M == N
        same, out_net = zen.get("same_topic_outside"), zen.get("outside_network")
        phrases += [(n[16], s2, "are outside the network, and all", same is not None and same == out_net,
                     f"same_topic_outside {same} vs outside_network {out_net}")]
    if swp:
        dose_rx = (r"relations' average dose \(" + NUM + r" in economics, " + NUM + r" in chemistry, " + NUM
                   + r" in mathematics\)")
        num += [(name, s3, dose_rx, round(swp["p1"][f]["avg_dose_switchers"], 2), g,
                 "gaps_switchers_p1p2.json p1.<field>.avg_dose_switchers, rounded once")
                for g, (name, f) in enumerate(zip(BASE_TREE_DOSE_CLAIMS, ("econ", "chemistry", "math_stats")),
                                              start=1)]
    if p3:
        p_two = p3["econ"]["randomization_inference"]["p_two_sided"]
        num += [(BASE_TREE_P3_CLAIMS[0], s3, r"in mathematics \\REV\{\(" + NUM + r" in Panel 3\)\}",
                 p3["math_stats"]["events_with_pairs"], 1, ""),
                (BASE_TREE_P3_CLAIMS[1], s4, r"Shuffled arrival years give \$p=" + NUM + r"\$",
                 float(f"{p_two:.3f}"), 1, "the ledger p printed at 3 dp, as the table generators print it")]
    if pp:
        dbl_rx = r"As " + NUM + r" of the " + NUM + r" economics arrivals follow an earlier star"
        num += [(BASE_TREE_PP_CLAIMS[0], s3, r"re-estimate the model " + NUM + r" times", pp["perm_pvalues"]["B"], 1, ""),
                (BASE_TREE_PP_CLAIMS[1], s3, dbl_rx, pp["p1_doublestar_econ"]["events_dropped"], 1, ""),
                (BASE_TREE_PP_CLAIMS[2], s3, dbl_rx, pp["p1_econ"]["events"], 2, "")]
    if main and p3:
        nop_rx = (r"In " + NUM + r" of the " + NUM + r" economics arrivals and " + NUM + r" of the " + NUM
                  + r" mathematics arrivals, fewer than two colleagues qualify")
        num += [(BASE_TREE_MAIN_CLAIMS[0], s2, nop_rx, main["math_events"] - p3["math_stats"]["events_with_pairs"], 3, ""),
                (BASE_TREE_MAIN_CLAIMS[1], s2, nop_rx, main["math_events"], 4, "")]
    if funnel:
        rel = datetime.date.fromisoformat(funnel["snapshot_release_date"])
        mon = rel.strftime("%B")
        open_rx = r"fixed " + NUM + " " + mon + " " + NUM + r" release of OpenAlex"
        p1_rx = r"and the " + NUM + " " + mon + " " + NUM + r" release covers only the first half of " + NUM
        n = BASE_TREE_FUNNEL_CLAIMS
        num += [(n[0], s2, open_rx, rel.day, 1, ""), (n[1], s2, open_rx, rel.year, 2, ""),
                (n[2], s2, p1_rx, rel.day, 1, ""), (n[3], s2, p1_rx, rel.year, 2, ""),
                (n[4], s2, p1_rx, rel.year, 3, "")]
    if pools:
        PM1, PM23, cells = pools["pools"]["M1_pos"], pools["pools"]["M23"], pools["cells"]

        def yrs(d, y):
            return sorted(int(a) for a in (d.get(str(y)) or {}).get("arrival_years", []))

        def pick(lst, i, k):                      # the i-th of exactly k printed years
            return _nan_unless(len(lst) == k, lst[i] if len(lst) == k else 0)

        def span(lst, end):                       # "a to b": a contiguous run of years
            ok = bool(lst) and lst == list(range(lst[0], lst[-1] + 1))
            return _nan_unless(ok, (lst[0] if end == 0 else lst[-1]) if lst else 0)
        n = BASE_TREE_POOL_CLAIMS
        m1_18, m1_16, m1_19 = yrs(PM1, 2018), yrs(PM1, 2016), yrs(PM1, 2019)
        pla = sorted(set(m1_18) | set(m1_19))     # the comparisons of the 2018 and 2019 effects
        m23_18 = yrs(PM23, 2018)
        live = [int(t) for t, r in PM23.items() if (r or {}).get("arrival_years")]
        stop = max(live) if live else None
        last = yrs(PM23, stop) if stop is not None else []
        m1_rx = r"zero-dose relations and relations whose star arrives in " + NUM + r" or " + NUM
        m116_rx = (r"The " + NUM + r" coefficient can use relations whose star arrives in " + NUM + r" to " + NUM
                   + r", the " + NUM + r" coefficient only those of " + NUM)
        pla_rx = (r"with stars arriving in " + NUM + r" or " + NUM + r", are followed only from " + NUM + r" or "
                  + NUM + r", not back to")
        m2_rx = r"minus that of comparison relations, whose star arrives in " + NUM + r" to " + NUM
        last_rx = r"relations whose star arrives in " + NUM + r" \(followed from " + NUM + r"\)"
        m3_rx = r"at departments whose star arrives in " + NUM + r" to " + NUM
        note = "fig_comparison_pools.json (N9 generator)"
        num += [(n[0], s3, m1_rx, pick(m1_18, 0, 2), 1, note), (n[1], s3, m1_rx, pick(m1_18, 1, 2), 2, note),
                (n[2], s3, m116_rx, span(m1_16, 0), 2, note), (n[3], s3, m116_rx, span(m1_16, 1), 3, note),
                (n[4], s3, m116_rx, pick(m1_19, 0, 1), 5, note),
                (n[5], s3, pla_rx, pick(pla, 0, 2), 1, note), (n[6], s3, pla_rx, pick(pla, 1, 2), 2, note),
                (n[7], s3, pla_rx, pick(pla, 0, 2) - _PRE1, 3, note + "; Model 1 window +-5"),
                (n[8], s3, pla_rx, pick(pla, 1, 2) - _PRE1, 4, note + "; Model 1 window +-5"),
                (n[9], s3, m2_rx, span(m23_18, 0), 1, note), (n[10], s3, m2_rx, span(m23_18, 1), 2, note),
                (n[11], s3, r"The estimates stop at " + NUM, _nan_unless(stop is not None, stop or 0), 1, note),
                (n[12], s3, last_rx, pick(last, 0, 1), 1, note),
                (n[13], s3, last_rx, pick(last, 0, 1) - _PRE23, 2, note + "; Panels 2-3 window -6/+10"),
                (n[14], s3, r"are treated from " + NUM + r", so none is left", pick(last, 0, 1), 1, note),
                (n[15], s3, m3_rx, span(m23_18, 0), 1, note), (n[16], s3, m3_rx, span(m23_18, 1), 2, note)]
        M1c, M23c = cells["M1_pos"], cells["M23"]
        phrases += [(n[17], s3, "four and five years after the arrival, only zero-dose comparisons remain",
                     M1c.get("2020") == "none" and M1c.get("2021") == "none",
                     f"M1_pos cells 2020/2021: {M1c.get('2020')}/{M1c.get('2021')}"),
                    (n[18], s3, "not back to 2012 or 2011",
                     M1c.get("2012") == "none" and M1c.get("2011") == "none",
                     f"M1_pos cells 2012/2011: {M1c.get('2012')}/{M1c.get('2011')}"),
                    (n[19], s3, "so none is left (Figure~\\ref{fig:comparison_pools})",
                     M23c.get("2021") == "no_estimate", f"M23 cell 2021: {M23c.get('2021')}")]
    return num, words, phrases


def _r1_base_reanchors(rows):
    """Move a base claim's anchor without changing its ledger value, predicate or name."""
    if PROFILE != "r1" or not R1_BASE_REANCHOR:
        return rows
    out = []
    for row in rows:
        spec = R1_BASE_REANCHOR.get(row[0])
        if spec is None:
            out.append(row)
            continue
        if len(spec) not in (2, 3) or (len(spec) == 3 and len(row) != 6):
            raise ValueError(f"invalid R1 base reanchor for {row[0]!r}: {spec!r}")
        moved = list(row)
        moved[1:3] = spec[:2]
        if len(spec) == 3:
            moved[4] = spec[2]
        out.append(tuple(moved))
    return out


def section_d_base_tree(led):
    """Grade BASE_TREE_CLAIMS on the base tree's sections (only under --tree base_2026_10_11)."""
    if TREE != BASE_TREE:
        return
    num, words, phrases = base_tree_claims(led)
    num, words, phrases = (_r1_base_reanchors(rows) for rows in (num, words, phrases))
    files = sorted({t[1] for t in num} | {t[1] for t in words} | {t[1] for t in phrases}
                   | {"sec2_data.tex", "sec3_strategy.tex", "sec4_p3.tex"})
    tex = {f: norm_tex(SECTIONS / f) for f in files}
    grade_pins(num, tex, set(files))
    for name, fname, rx, want in words:
        m = re.search(rx, tex[fname])
        if not m:
            check("D", name, False, f"pattern not found in {fname}", file=fname, kind="claim", anchor_found=False)
            continue
        got = _WORDS.get(m.group(1).lower())
        check("D", name, got == want, f"{fname} prints {m.group(1)!r}; ledger {want}", file=fname, kind="claim",
              anchor_found=True)
    for name, fname, phrase, ok, detail in phrases:
        if phrase not in tex[fname]:
            check("D", name, False, f"sentence not found in {fname}: {phrase!r}", file=fname, kind="claim",
                  anchor_found=False)
        else:
            check("D", name, bool(ok), detail, file=fname, kind="claim", anchor_found=True)
    done = {t[0] for t in num} | {t[0] for t in words} | {t[0] for t in phrases}
    if PROFILE == "r1":
        for key in sorted({k for k in R1_BASE_REANCHOR if not k.startswith("r4 ")} - done):
            check("D", f"r1 base overlay entry {key!r}", False,
                  "R1_BASE_REANCHOR key names no evaluated base-tree claim")
    for group, ledger in ((BASE_TREE_ZENOU_CLAIMS, "gaps_zenou.json"), (BASE_TREE_DOSE_CLAIMS, "gaps_switchers_p1p2.json"),
                          (BASE_TREE_P3_CLAIMS, "data_numbers_p3afar.json"), (BASE_TREE_PP_CLAIMS, "data_numbers_p1p2.json"),
                          (BASE_TREE_MAIN_CLAIMS, "data_numbers_main.json + data_numbers_p3afar.json"),
                          (BASE_TREE_FUNNEL_CLAIMS, "data_numbers_funnel.json"),
                          (BASE_TREE_POOL_CLAIMS, "fig_comparison_pools.json")):
        for name in group:
            if name not in done:
                fname = ("sec4_p3.tex" if name.startswith("base sec4_p3")
                         else "sec2_data.tex" if name.startswith("base sec2") else "sec3_strategy.tex")
                check("D", name, False, f"not evaluated: {ledger} missing from output/paper", file=fname)


def section_d_r1_claims(led):
    """Rewritten author claims, from r1_claims_spec.py, checked against this run's ledgers.

    Literal phrases are from the 2026-10-19 tree after norm_tex. Neither the October predicates
    nor their profiles change. Numeric reanchors above separately check the printed magnitudes.
    """
    if PROFILE != "r1":
        return
    pp, rb, p3, zen = (led[k] for k in ("p1p2", "robustness", "p3afar", "zenou"))
    F = ("econ", "chemistry", "math_stats")
    tx = {f: norm_tex(SECTIONS / f) for f in ("sec2_data.tex", "sec4_p1.tex", "sec4_p2.tex", "sec4_p3.tex",
                                              "sec4_robustness.tex", "sec4_causal.tex", "sec5_conclusion.tex")}
    tx["main.tex"] = norm_tex(_main_tex())
    tx["tab_robustness.tex"] = norm_tex(D_TABLES / "tab_robustness.tex")

    def claim(name, fname, phrase, ok, detail=""):
        text = tx[fname]
        if fname == "tab_robustness.tex":
            # The other panels have date-shift rows too; only Panel 2 can satisfy this claim.
            _, heading, block = text.partition(r"\emph{First paper with the star (Panel 2):")
            text = block.split(r"\midrule", 1)[0] if heading else ""
        found = phrase in text
        check("D", name, found and bool(ok), detail if found else f"sentence not found in {fname}: {phrase!r}",
              file=fname, kind="claim", anchor_found=found)

    def spans0(ci):
        return ci[0] < 0 < ci[1]

    PT, V, perm = rb["p1_pretrend_by_channel"], rb["p1_variants"], pp["perm_pvalues"]
    DS1, DS2, DS3 = (rb[f"p{i}_date_shift"] for i in (1, 2, 3))
    claim("r1 P3 chemistry interval below zero", "sec4_p3.tex",
          "$-$0.240 to $-$0.010, excludes zero", p3["chemistry"]["ci95_pair_pp"][1] < 0)
    claim("r1 P1 joint effects econ and chem below 0.001", "sec4_p1.tex",
          "zero rejects in both ($p<0.001$ in each)",
          max(pp[f"p1_{f}"]["p_joint_effects_person"] for f in ("econ", "chemistry")) < 0.0005)
    claim("r1 P1 math interval below zero", "sec4_p1.tex",
          "running from $-$0.467 to $-$0.171 log points", pp["p1_math_stats"]["ci95_person"][1] < 0)
    claim("r1 P1 math joint tests below 0.001", "sec4_p1.tex",
          "joint test rejects ($p<0.001$ with incumbent and with event clusters)",
          max(pp["p1_math_stats"][f"p_joint_effects_{c}"] for c in ("person", "event")) < 0.0005)
    claim("r1 P1 math placebo below 0.001", "sec4_p1.tex", "but fails in mathematics ($p<0.001$)",
          pp["p1_math_stats"]["p_joint_placebo_person"] < 0.0005)
    ds = pp["p1_doublestar_econ"]
    claim("r1 P1 no-earlier-star estimate positive but uncertain", "sec4_robustness.tex",
          "estimate, $+$0.034 (0.170), cannot be distinguished from zero",
          ds["ate_log"] > 0 and spans0((ds["ate_log"] - 1.96 * ds["se_person"],
                                       ds["ate_log"] + 1.96 * ds["se_person"])))
    claim("r1 missing-output econ placebo rounds to 0.001", "sec4_robustness.tex",
          "($p=0.001$ and $p=0.003$)",
          round(V["econ"]["missing_as_zero"]["p_joint_placebo"], 3) == 0.001
          and round(V["econ"]["missing_as_own_mean"]["p_joint_placebo"], 3) == 0.003)
    t5 = rb["d7"]["top5"]
    cells = ([(t5[f]["p1"], "ate_log", pp[f"p1_{f}"], "se_person") for f in F]
             + [(t5[f]["p2"], "ate_pp", pp[f"p2_{f}"], "se_person_pp") for f in F]
             + [(t5[f]["p3_pos"], "ate_pp", p3[f], "se_pair_pp") for f in F])
    within = all(alt.get("status", "OK") == "OK" and alt.get(key) is not None
                 and abs(alt[key] - main[key]) < main[se] for alt, key, main, se in cells)
    claim("r1 top-5% all nine estimates within one SE", "sec4_robustness.tex",
          "Every estimate stays within one standard error of the main estimate.", within)
    claim("r1 conclusion top-5% all nine estimates within one SE", "sec5_conclusion.tex",
          "citations leaves every estimate within one standard error of the main one.", within)
    claim("r1 chemistry P1 pre-arrival tests", "sec4_causal.tex",
          "but the date-shift test fails on the full sample and both tests fail for roster incumbents",
          pp["p1_chemistry"]["p_joint_placebo_person"] > 0.05
          and DS1["chemistry"]["p_joint_shifted"] < 0.05
          and all(PT["chemistry"]["dept"][k] < 0.05 < PT["chemistry"]["network"][k]
                  for k in ("p_joint_placebo_person", "p_joint_shifted")))
    claim("r1 economics P1 pre-arrival tests", "sec4_causal.tex",
          "In economics the placebo test with incumbent clusters passes for every group of incumbents",
          all(p > 0.05 for p in (pp["p1_econ"]["p_joint_placebo_person"],
                                PT["econ"]["dept"]["p_joint_placebo_person"],
                                PT["econ"]["network"]["p_joint_placebo_person"]))
          and PT["econ"]["dept"]["p_joint_shifted"] < 0.05 and DS1["econ"]["p_joint_shifted"] < 0.05
          and PT["econ"]["network"]["p_joint_shifted"] > 0.05)
    z, o = (V["chemistry"][k]["ate_log"] for k in ("missing_as_zero", "missing_as_own_mean"))
    claim("r1 chemistry fillings differ by more than two", "sec4_causal.tex",
          "fillings of missing output differ by a factor of more than two", z < 0 and o < 0 and z / o > 2)
    claim("r1 P2 date-shift passes all three disciplines", "sec4_causal.tex",
          "In all three disciplines the date-shift test passes",
          all(DS2[f].get("status", "OK") == "OK" and DS2[f].get("p_joint_shifted") is not None
              and DS2[f]["p_joint_shifted"] > 0.05 for f in F))
    claim("r1 P2 econ and chem shuffled-years confidence", "sec4_causal.tex",
          "In economics and chemistry shuffled arrival years also show that the rise depends",
          all(perm[f"p2_{f}"]["p_perm_abs_ate"] < 0.05 and DS2[f]["p_joint_shifted"] > 0.05
              for f in ("econ", "chemistry")))
    claim("r1 math P2 joint tests reject", "sec4_causal.tex",
          "coefficients rejects with both cluster choices, but shuffled arrival years cannot show",
          all(pp["p2_math_stats"][f"p_joint_effects_{c}"] < 0.05 for c in ("person", "event"))
          and perm["p2_math_stats"]["p_perm_abs_ate"] >= 0.05)
    claim("r1 Table 3 P2 date-shift cells are numeric", "tab_robustness.tex",
          r"\REV{\quad date-shift test} & \REV{0.525} & \REV{0.633} & \REV{0.715} & \REV{All}",
          all(DS2[f].get("status", "OK") == "OK" and DS2[f].get("p_joint_shifted") is not None
              and round(DS2[f]["p_joint_shifted"], 3) == p for f, p in zip(F, (0.525, 0.633, 0.715))))
    claim("r1 P1 lead all three output intervals below zero", "sec4_causal.tex",
          "implies that in all three disciplines an arrival lowers the output",
          all(pp[f"p1_{f}"]["ci95_person"][1] < 0 for f in F))
    p2ci = (all(pp[f"p2_{f}"]["ci95_person_pp"][0] > 0 for f in ("econ", "chemistry"))
            and spans0(pp["p2_math_stats"]["ci95_person_pp"]))
    claim("r1 P2 lead econ and chem positive math spans zero", "sec4_causal.tex",
          "implies that in economics and chemistry an arrival raises the first-tie rate with the star; "
          "in mathematics the rise cannot be distinguished from zero", p2ci)
    p3ci = (all(p3[f]["ci95_pair_pp"][1] < 0 for f in ("econ", "chemistry"))
            and spans0(p3["math_stats"]["ci95_pair_pp"]))
    claim("r1 P3 lead econ and chem negative math spans zero", "sec4_causal.tex",
          "where both intervals with pair clusters lie below zero; in mathematics the estimate cannot be "
          "distinguished from zero", p3ci)
    claim("r1 conclusion P3 intervals and date-shift failures", "sec5_conclusion.tex",
          "become less frequent in economics and chemistry and do not change in mathematics, but all three "
          "estimates fail the date-shift test", p3ci and all(DS3[f]["p_joint_shifted"] < 0.05 for f in F))
    claim("r1 P2 only the math incumbent interval spans zero", "sec4_p2.tex",
          "zero except the incumbent-clustered mathematics interval", p2ci
          and all(pp[f"p2_{f}"]["ate_pp"] - 1.96 * pp[f"p2_{f}"]["se_event_pp"] > 0 for f in F))
    claim("r1 intro placebo passes but date-shift fails", "main.tex",
          "nor does that of incumbents as a whole; but both were falling behind in the three years just before "
          "the star came, as were incumbents in chemistry and mathematics",
          all(PT["econ"][c]["p_joint_placebo_person"] > 0.05 > PT["econ"][c]["p_joint_shifted"]
              for c in ("union", "dept")) and all(DS1[f]["p_joint_shifted"] < 0.05 for f in ("chemistry", "math_stats")))
    raw = p3["econ"]["raw_rate_by_event_time_pp"]
    claim("r1 P3 econ raw pre-arrival endpoints rise", "sec4_p3.tex",
          "already rising before the arrival, from 0.186 percent six years before to 0.316 percent in the year before",
          raw["-1"] > raw["-6"])
    claim("r1 Zenou P3 pre-window pairs 1026", "sec2_data.tex",
          "(the other 1{,}026 had already published", zen["pairs_excluded_prewindow"] == 1026)
    claim("r1 Zenou same-topic outside is a subset", "sec2_data.tex",
          "and 103 of these share at least one subfield with him",
          zen["same_topic_outside"] == 103 < zen["outside_network"])
    h2 = {f: next(h for h in pp[f"p2_{f}"]["horizons_pp"] if h["ell"] == 2) for f in F}
    claim("r1 P2 peaks two years after arrival", "sec4_p2.tex",
          r"the rise peaks two years after the arrival in economics (0.490 percentage points, standard error "
          r"0.082), chemistry (1.106, 0.200) and mathematics (0.145, 0.060)",
          all(h2[f]["est"] == max(h["est"] for h in pp[f"p2_{f}"]["horizons_pp"]) for f in F)
          and round(h2["chemistry"]["est"], 3) == 1.106 and round(h2["chemistry"]["se_person"], 3) == 0.200)


def write_report():
    titles = {"A": "A. Ledger equality (thesis data_numbers keys vs generated)",
              "B": "B. Table byte-identity (generator output vs the thesis tables/)",
              "C": "C. Gap-script integrity flags + figure PDFs",
              "D": "D. In-text claims (thesis tex vs ledgers)"}
    graded = [c for c in checks if not c["unrep"] and not c["retired"]]
    unreps = [c for c in checks if c["unrep"]]
    retired = [c for c in checks if c["retired"]]
    n_pass = sum(c["ok"] for c in graded)
    n_fail = len(graded) - n_pass
    lines = [f"# paper_check — thesis vs generated ({datetime.date.today().isoformat()})", ""]
    for s in ("A", "B", "C", "D"):
        rows = [c for c in checks if c["section"] == s]
        lines += [f"## {titles[s]}", ""]
        for c in rows:
            note = f"  ({c['note']})" if c["note"] else ""
            if c["unrep"]:
                lines.append(f"- {c['detail']}{note}")
            elif c["retired"]:
                lines.append(f"- RETIRED {c['name']} — {c['detail']}{note}")
            else:
                status = "PASS" if c["ok"] else "FAIL"
                lines.append(f"- {status} {c['name']} — {c['detail']}{note}")
        lines.append("")
    uncompiled = [c for c in graded if "not compiled by main.tex" in c["note"]]
    lines += ["## Summary", "",
              f"{len(graded)} checks: {n_pass} PASS, {n_fail} FAIL."]
    if uncompiled:
        lines.append(f"NOTE: {len(uncompiled)} of these checks read files main.tex does not compile "
                     "(the appendices, tab_disciplines and the nine old generator tables): they keep "
                     "those files consistent but say nothing about the PDF.")
    if retired:
        lines.append(f"NOTE: {len(retired)} pin(s) are RETIRED: their number is no longer printed in "
                     "the synced text (2026-09-23); listed in section D, neither PASS nor FAIL.")
    if unreps:
        lines.append(f"NOTE: {len(unreps)} ledger key(s) are UNREPRODUCIBLE (asserted only, "
                     "never generator-verified) — this is the recorded state, not a failure:")
        lines += [f"- {c['detail']}" for c in unreps]
    if n_fail:
        lines.append("Failing:")
        lines += [f"- {c['name']} — {c['detail']}" + (f"  ({c['note']})" if c["note"] else "")
                  for c in graded if not c["ok"]]
    lines.append("")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines))
    if JSON_OUT is not None:   # R1 P3 (V3-FINAL.c): the same checks, machine-readable
        JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
        JSON_OUT.write_text(json.dumps({
            "schema": "sar.r1.paper_check.v1", "tree": TREE, "profile": PROFILE,
            "thesis_root": str(THESIS_REPORT), "ledger_date": THESIS_LEDGER_DATE,
            "n_checks": len(graded), "n_pass": n_pass, "n_fail": n_fail,
            "n_retired": len(retired), "n_unrep": len(unreps),
            "checks": [{"section": c["section"], "name": c["name"], "ok": c["ok"], "retired": c["retired"],
                        "unrep": c["unrep"], "file": c.get("file"), "detail": c["detail"], "note": c["note"],
                        **({"kind": c["kind"], "anchor_found": c["anchor_found"]} if "kind" in c else {})}
                       for c in checks]}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return n_fail


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="paper sentinel: thesis vs generated numbers")
    ap.add_argument("--sections-dir", type=Path, default=None,
                    help="read section D's sections/*.tex from this dir instead of the thesis "
                         "(self-test flag: point it at a perturbed scratch copy); a main.tex "
                         "placed in this dir is used too, else the thesis main.tex")
    ap.add_argument("--tables-dir", type=Path, default=None,
                    help="read section D's hand-typed tables from this dir instead of the thesis")
    # R1 P3 (V3-FINAL.c / N12): every flag below defaults to today's behaviour
    ap.add_argument("--thesis-root", type=Path, default=None,
                    help="the thesis tree (ledgers, tables, sections, main.tex); default "
                         "<legacy_thesis>/thesis_report")
    ap.add_argument("--ledger-date", default=None,
                    help=f"date of the thesis ledgers data_numbers_<DATE>*.json (default {DEFAULT_LEDGER_DATE})")
    ap.add_argument("--report", type=Path, default=None, help="markdown report (default <output>/paper_check.md)")
    ap.add_argument("--json", type=Path, default=None, dest="json_out", help="also write a JSON report here")
    ap.add_argument("--no-regen", action="store_true",
                    help="do not run the generators of missing output/paper files")
    ap.add_argument("--profile", choices=PROFILES, default="thesis",
                    help="pin overlay: thesis (identity), vault, or r1 (vault plus author-tree overrides)")
    ap.add_argument("--gold", type=Path, default=None,
                    help="the frozen P1 gold JSON (default <expected>/P1_econ_fnfix.json)")
    ap.add_argument("--tree", choices=TREES, default="thesis_report",
                    help="base_2026_10_11 also checks BASE_TREE_CLAIMS (the base tree's Section 2-3 numbers)")
    ap.add_argument("--tree-root", type=Path, default=None,
                    help="where section D reads sections/, tables/ and main.tex (not the ledgers)")
    args = ap.parse_args(argv)
    configure(thesis_root=args.thesis_root, ledger_date=args.ledger_date, report=args.report,
              json_out=args.json_out, profile=args.profile, gold=args.gold, tree=args.tree,
              tree_root=args.tree_root, sections_dir=args.sections_dir, tables_dir=args.tables_dir)
    checks.clear()
    if not THESIS_REPORT.is_dir():
        print(f"thesis tree not found at {THESIS_REPORT}; the sentinel needs it", file=sys.stderr)
        return 2
    if not args.no_regen:
        regenerate_missing()
    led = {"main": load_json("data_numbers_main.json"),
           "carried": load_json("data_numbers_carried.json"),
           "funnel": load_json("data_numbers_funnel.json"),
           "p3afar": load_json("data_numbers_p3afar.json"),
           "zenou": load_json("gaps_zenou.json"),
           "zero": load_json("gaps_zero_dose.json"),
           "switchers": load_json("gaps_switchers.json"),
           "toy": load_json("gaps_toy.json"),
           "p1p2": load_json("data_numbers_p1p2.json"),
           "switchers_p1p2": load_json("gaps_switchers_p1p2.json"),
           "robustness": load_json("data_numbers_robustness.json"),
           # the frozen gold P1 econ union channel (repo-tracked): per-horizon coefficients
           "gold_p1_union": (json.loads(GOLD.read_text())["channels"]["union"] if GOLD.is_file() else None)}
    if led["gold_p1_union"] is None:
        check("C", "P1 gold present", False, f"missing: {GOLD}")
    if TREE == BASE_TREE:       # the N9 generator's comparison pools (base-tree claims only)
        led["pools"] = load_json("fig_comparison_pools.json")
    for short, fname in (("zero", "gaps_zero_dose.json"), ("toy", "gaps_toy.json"),
                         ("funnel", "data_numbers_funnel.json")):
        if led[short] is None:
            check("C", f"{fname} present", False, "missing")
    # A crash in any section (e.g. a claims-table KeyError after a ledger key vanished) must
    # become an explicit FAIL with the report still written — never a bare traceback that
    # leaves a stale report on disk.
    sections = (("A", section_a, (led,)), ("B", section_b, ()),
                ("C", section_c, (led,)), ("D", section_d, (led,)),
                ("D", section_d_p1p2_tables, (led,)),
                ("D", section_d_rob_tables, (led,)),
                ("D", section_d_r4_claims, (led,)),
                ("D", section_d_base_tree, (led,)))   # base tree only (N12)
    if PROFILE == "r1":
        sections += (("D", section_d_r1_claims, (led,)),)
    for section, fn, args in sections:
        try:
            fn(*args)
        except Exception as e:  # noqa: BLE001 — any crash is a sentinel failure
            check(section, f"section {section} completed", False, f"crashed: {e!r}")
    n_fail = write_report()
    print(REPORT.read_text())
    print(f"wrote {REPORT}")
    if JSON_OUT is not None:
        print(f"wrote {JSON_OUT}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
