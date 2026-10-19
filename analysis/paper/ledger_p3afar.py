#!/usr/bin/env python3
"""ledger_p3afar.py — Panel 3 (A_far definition) numbers ledger + figure.

Panel 3 = pairs of department-roster incumbents who both work on the star's topics
(similarity dose >= the discipline's median positive dose, frozen at arrival-1) and who
were both outside the star's two-hop pre-arrival coauthorship network (the 'A_far' cell
of v2_output/p3_topicpair_2026-08-17).

Reads ONLY frozen outputs of v2_output/p3_topicpair_2026-08-17:
  results/out/P3lb_{field}_A_far.json        dCDH estimates (pair- and event-clustered)
  data/pairs_slim_lb_{field}_A_far.parquet   the estimation panel (grp, ev, year, y, D) -> raw rates
  data/lb_counts.csv                          topic cut (median positive dose), pooled counts
  data/speed_bracket.csv                      fitted pre-arrival trend / flat counterfactuals (per 1,000)
  results/out_null/NULL_{field}_A_far.json    no-effect simulation (risk-set depletion only)
Writes
  output/paper/data_numbers_p3afar.json   every number quoted in the text, with its source
  output/paper/fig_p3_afar.pdf             top row: event-time coefficients; bottom row: raw rates

Raw first-tie rates are reported on OBSERVABLE pair-years only: calendar year <= 2024 (the
26 June 2026 snapshot does not contain publications of later years, and 2025-26 are incomplete);
the post-arrival window is the arrival year and the five years after it (tau 0..5), matching the
five reported horizons. The pooled all-years rate from lb_counts.csv is kept in the ledger for reference.

Port note: this is a verbatim port of thesis_report/scripts/p3_afar_numbers_and_figure.py
(2026-08-22 thesis copy). Every computation line is unchanged; only ROOT/SRC/OUT_JSON/OUT_FIG
are re-derived from analysis.lib.paths.load_paths() instead of the thesis's hard-coded ROOT.
Ported 2026-08-23 for the star_arrivals_replication repo (M2/T1).
Freeze-wave Task 8 (2026-08-28, author-approved caliber): the legacy equality cross-check is
retired (the legacy tree is the pre-caliber run and differs by design), and the speed bracket
is no longer computed against the current post rate — it is the frozen PRE-caliber record
data/paper_inputs/speed_bracket_precal_2026-08-22.json, cross-checked against the CALIBER-STALE
CSV and carried with an explicit caliber note, pending a rebuild decision (see the in-line notes).
2026-09-23 (cal2026-10, October caliber): the dated freeze reads are re-pointed to the October
products, each pinned before use —
  no-effect simulation  data/cal2026-10/cloud/null/NULLpos_{field}.json (was data/paper_inputs/),
                        recomputed from its custody-pinned slices (cloud/fetch/out_null) with
                        analysis/robustness/null_sim/merge_null.py and asserted equal;
  permutations          data/cal2026-10/cloud/perm/{raw,control} (was data/inference_afar_pos_2026-08-30/raw),
                        every slice pinned by the custody record, cross-checked against
                        cloud/perm/perm_summary.json (summarize_perm.py's rule);
  dose-cut grid, cut estimates and the two-year date shift
                        data/cal2026-10/robustness/afar_cuts/ (was data/robustness_afar_cuts_2026-08-30/),
                        sha256-checked against that directory's MANIFEST.
R1 N12 (2026-10-16): the permutation p is computed by perm_p(ge, n, full). With the paper-layer switch
p_full_precision off (always, in October) it is stored rounded to 4 dp exactly as before; on (config M,
carried into CANON.json) it is stored unrounded, so the tables' 3-dp print rounds once (econ 0.235 -> 0.236).
R1 FIG567 (2026-10-16): the figure is drawn by analysis/paper/fig_p3_afar.py (draw(), the same figure lines
moved there unchanged), from the ledger built here. --tree {thesis_report (default), base_2026_10_11}: the
default draws the figure as before (the legacy thesis_report tree prints it); base_2026_10_11 draws Figure 7
of the author's base tree (the 2026-10-03 redraw). The ledger JSON is the same for both trees.
Run:  python3 analysis/paper/ledger_p3afar.py [--tree {thesis_report,base_2026_10_11}]
"""
import argparse
import json, csv, os, sys, pathlib, hashlib, importlib.util
from pathlib import Path
import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from analysis.lib.paths import load_paths
from analysis.lib import canon
from analysis.paper import fig_p3_afar

_ap = argparse.ArgumentParser(description="Panel 3 (A_far) numbers ledger + figure")
_ap.add_argument("--tree", choices=fig_p3_afar.TREES, default="thesis_report",
                 help="thesis_report (default; the pre-FIG567 figure) or base_2026_10_11 (Figure 7)")
_ap.add_argument("--font-dir", type=Path, action="append",
                 help="base tree: look for TeX Gyre Pagella only here (default: the pinned TeX layer)")
_ap.add_argument("--test-font-fallback", action="store_true",
                 help="TESTS ONLY: base tree drawn in DejaVu Serif when Pagella is absent")
ARGS = _ap.parse_args(sys.argv[1:] if __name__ == "__main__" else [])

P = load_paths()
# Freeze-wave Task 8 (2026-08-28): the legacy run directory holds the PRE-caliber run. Since the
# author-approved caliber freeze the golds in analysis/expected/ are the caliber estimates, so the
# legacy copies legitimately DIFFER and the former equality cross-check no longer applies by
# design — the golds' integrity is guarded by analysis/expected/MANIFEST instead (freeze_expected +
# verify_manifest + the T7 acceptance tests). SRC survives only as the last-resort fallback for a
# no-effect-simulation JSON that is not frozen in data/paper_inputs (none today).
SRC = str(P["legacy_v2_output"] / "p3_topicpair_2026-08-17")
# M3 T8: the four DATA reads below (topic counts, speed bracket, and the three A_far pair-year
# panels) now come from this repository's frozen copies in data/frames, which are byte-identical to
# the legacy files they replace (sha256-pinned in data/MANIFEST.sha256; asserted in
# tests/test_paper_ledgers.py). Before this change the paper's Panel-3 numbers could not be
# regenerated without the author's read-only thesis tree even though the inputs were already in the
# package - the same "the freeze is inert" defect the T4 review found in ledger_funnel.
FR = P["frames"]
# MILESTONE REVIEW, replicator-experience MAJOR: the estimate JSONs this ledger derives from are
# ALSO shipped, as the frozen golds in `analysis/expected/` — the ledger already asserted the legacy
# copy equals them before using it, so reading legacy was strictly redundant and blocked the whole
# paper stage off the author's machine. It now reads `analysis/expected/` and keeps the legacy copy
# as an OPTIONAL cross-check, which is a stronger arrangement than before: the equality is still
# asserted where the legacy tree exists, and nothing is lost where it does not. The two
# no-effect-simulation JSONs (econ 584 B, chemistry 586 B; math_stats has none) are frozen in
# `data/paper_inputs/` with manifest pins.
XP = P["expected"]
CAL = P["cal"]                                      # R1 F7: the cal root from config (October data/cal2026-10)
CLOUD = CAL / "cloud"                               # custody-chained cloud batch (null + permutations)
CUTS = CAL / "robustness" / "afar_cuts"             # was data/robustness_afar_cuts_2026-08-30
OUT_JSON = str(P["output"] / "paper" / "data_numbers_p3afar.json")
OUT_FIG = str(P["output"] / "paper" / "fig_p3_afar.pdf")
FIELDS = [("econ", "Economics"), ("chemistry", "Chemistry"), ("math_stats", "Mathematics & Statistics")]
assert FIELDS == fig_p3_afar.FIELDS                 # the figure's column order is the ledger's
YEAR_CAP = 2024      # last calendar year with complete coverage in the 2026-06-26 snapshot
POST_TAUS = (0, 5)   # arrival year .. five years after



def pinned(freeze_root, rel):
    """Read a freeze file only after its sha256 matches the freeze MANIFEST (repo-root-relative
    key, as in every cal2026-10 MANIFEST; the data/<dir>/<rel> and bare forms are also accepted).
    R1 F7: the MANIFEST and the first key come from analysis/lib/canon.py (October: the freeze's own
    MANIFEST and the repo-relative key, as before; an M canon: the cal MANIFEST, '<prefix>/...' keys)."""
    manifest = {}
    for line in canon.freeze_manifest(freeze_root).read_text().splitlines():
        h, _, name = line.partition("  ")
        manifest[name.strip()] = h
    path = freeze_root / rel
    keys = (canon.key(path), f"data/{freeze_root.name}/{rel}", rel)
    want = next((manifest[k] for k in keys if k in manifest), None)
    got = hashlib.sha256(path.read_bytes()).hexdigest()
    assert want is not None, f"{keys[0]}: not listed in {freeze_root}/MANIFEST.sha256"
    assert want == got, f"{keys[0]}: sha256 {got} does not match the freeze MANIFEST"
    return path


_CUSTODY = json.loads((CLOUD / "custody_cal2026-10.json").read_text())
assert _CUSTODY["ok"] is True and not _CUSTODY["problems"], "cloud custody record is not OK"


def custody_pinned(path, key):
    """A cloud product is read only after its sha256 matches the custody record's fetch_sha256."""
    want = _CUSTODY["fetch_sha256"].get(key)
    got = hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
    assert want is not None, f"{key}: not in the custody fetch_sha256"
    assert want == got, f"{path}: sha256 {got} does not match the custody record ({key})"
    return path


_spec = importlib.util.spec_from_file_location(
    "merge_null", P["repo_root"] / "analysis" / "robustness" / "null_sim" / "merge_null.py")
merge_null = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(merge_null)


def null_checked(field):
    """The merged no-effect simulation for one discipline, recomputed from its custody-pinned slices
    and asserted equal to the committed merge; None when the discipline has no simulation."""
    nf = CLOUD / "null" / f"NULLpos_{field}.json"
    if not nf.is_file():
        return None
    nj = json.load(open(nf))
    slice_dir = CLOUD / "fetch" / "out_null"
    for sl in sorted(slice_dir.glob(f"NULLpos_{field}_null_*.csv")):
        custody_pinned(sl, f"out_null/{sl.name}")
    again = json.loads(json.dumps(merge_null.merge(slice_dir, f"NULLpos_{field}", nj["nsim"])))
    assert again == nj, f"NULLpos_{field}: the committed merge differs from its pinned slices"
    return nj


# R1 N12 (R5): the permutation p used to be stored rounded to 4 dp and then printed at 3 dp by the
# table generators - a double rounding. Economics in October: 118/501 = 0.23553 should print 0.236,
# but the stored 0.2355 prints 0.235. The fix is the paper-layer switch p_full_precision: always off
# in October (canon.switch is False there, so this file writes 0.2355 byte for byte as before); in an
# M canon its CANON.json value, and an undeclared switch is a CanonError, never a silent default.
P_FULL_PRECISION = canon.switch("p_full_precision", P)


def perm_p(ge, n, full: bool):
    """Two-sided permutation p = (1 + #{|ate_perm| >= |ate_obs|}) / (1 + #perms).
    full=True stores it unrounded, so the 3-dp print rounds once; full=False keeps October's
    round(..., 4)."""
    if not isinstance(full, bool):
        raise TypeError(f"perm_p: full must be a bool, got {full!r}")
    p = (1 + ge) / (1 + n)
    return p if full else round(p, 4)


def perm_checked(field, obs_ate):
    """Permutation draws for the Panel 3 main cell: custody-pinned raw slices + identity control."""
    summ = {c["label"]: c for c in json.load(open(CLOUD / "perm" / "perm_summary.json"))["cells"]}
    lab = f"P3cutpos_{field}"
    by_perm, ident, failed = {}, None, 0
    files = sorted((CLOUD / "perm" / "raw").glob(f"{lab}_perm_*.csv")) + \
        sorted((CLOUD / "perm" / "control").glob(f"{lab}_perm_0_0.csv"))
    for pf in files:
        for row in csv.DictReader(open(custody_pinned(pf, f"out_perm/{pf.name}"))):
            if int(row["perm"]) == 0:
                ident = float(row["ate"])
                continue
            # Keyed by permutation index, not appended: a permutation appearing in two slice files
            # would inflate the denominator of the p-value silently.
            assert int(row["perm"]) not in by_perm, f"{lab}: permutation {row['perm']} appears twice"
            if row["status"] != "OK" or row.get("ate") in ("", "NA", None):
                failed += 1
                by_perm[int(row["perm"])] = None
                continue
            by_perm[int(row["perm"])] = 100 * float(row["ate"])
    assert sorted(by_perm) == list(range(1, len(by_perm) + 1)), f"{lab}: permutation indices have gaps"
    assert ident is not None and abs(ident - obs_ate) < 1e-8, f"{lab}: identity {ident} != gold {obs_ate}"
    draws = [v for v in by_perm.values() if v is not None]
    obs = 100 * obs_ate          # full precision, not the 3-dp value the paper prints
    ge = sum(1 for x in draws if abs(x) >= abs(obs))
    p = perm_p(ge, len(draws), P_FULL_PRECISION)
    c = summ[lab]
    assert c["B_ok"] == len(draws) and c["B_failed"] == failed, f"{lab}: draw counts differ from the summary"
    assert abs(c["p_perm_abs_ate"] - (1 + ge) / (1 + len(draws))) < 1e-6, f"{lab}: p differs from the summary"
    return {"permutations": len(draws), "p_two_sided": p, "n_at_least_as_large": ge,
            "identity_control_ate_pp": round(100 * ident, 4), "failed_draws": failed,
            "requested": len(by_perm)}


con = duckdb.connect()
# 2026-08-30 SPECIFICATION CHANGE (author-signed). Panel 3's main specification is now
# "both incumbents share at least one subfield with the star" (dose > 0). The former cut — both
# at or above the discipline's median positive dose — becomes a robustness cell. A design-history
# search found no recorded argument for the median cut, and the grid built on 2026-08-30 showed
# the economics sign turns on it. Both specifications are carried here: SPEC_MAIN feeds the text,
# SPEC_ROB feeds the robustness paragraph.
SPEC_MAIN, SPEC_ROB = "pos", "med"
_by_spec = list(csv.DictReader(open(FR / "p3_afar_counts_by_spec.csv")))
counts     = {r["field"]: r for r in _by_spec if r["spec"] == SPEC_MAIN}
counts_rob = {r["field"]: r for r in _by_spec if r["spec"] == SPEC_ROB}
# The speed bracket is GONE as of 2026-08-30. It was computed on the pre-caliber event set
# (87/30/29 A_far events), its capped cells have no caliber builder (NOT_REPRODUCIBLE row 9), and
# the specification change moves the population again (23,758 -> 88,176 econ pairs). Keeping it
# would mean describing one population with another population's ratio. Deleted rather than
# disclosed; the paragraph it fed is removed from sec4_p3.

def rates(field):
    fp = str(FR / f"p3_afar_{SPEC_MAIN}_{field}.parquet")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE d AS
        SELECT p.*, p.year - a.arrival AS tau FROM read_parquet('{fp}') p
        JOIN (SELECT ev, min(year) AS arrival FROM read_parquet('{fp}') WHERE D=1 GROUP BY ev) a USING (ev)""")
    q = lambda w: con.execute(f"SELECT count(*), sum(y) FROM d WHERE {w}").fetchone()
    pre = q("tau BETWEEN -6 AND -1")
    post_all = q("tau >= 0")
    post_obs = q(f"tau BETWEEN {POST_TAUS[0]} AND {POST_TAUS[1]} AND year <= {YEAR_CAP}")
    by_tau = con.execute(f"SELECT tau, count(*) n, sum(y) t FROM d WHERE tau BETWEEN -6 AND 5 AND year <= {YEAR_CAP} GROUP BY tau ORDER BY tau").fetchall()
    years = con.execute("SELECT min(year), max(year), sum(CASE WHEN year > %d AND D=1 THEN 1 ELSE 0 END) FROM d" % YEAR_CAP).fetchone()
    # How the panel empties out, for the Section 2.3 sentence that explains the follow-and-exit
    # rule. A pair leaves in the year of its first joint publication whether that year is before
    # the arrival or after it, so the three groups below partition the panel exactly; the assert
    # is what makes "exit at first tie" a checked property of the frame rather than a claim.
    exits = con.execute("""SELECT
        count(DISTINCT grp),
        count(DISTINCT CASE WHEN y=1 AND D=0 THEN grp END),
        count(DISTINCT CASE WHEN y=1 AND D=1 THEN grp END) FROM d""").fetchone()
    stragglers = con.execute("""SELECT count(*) FROM (
        SELECT grp FROM d GROUP BY grp
        HAVING max(CASE WHEN y=1 THEN year END) IS NOT NULL
           AND max(year) <> max(CASE WHEN y=1 THEN year END))""").fetchone()[0]
    assert stragglers == 0, f"{field}: {stragglers} pair(s) have rows after their first tie"
    n_pairs, tie_pre, tie_post = int(exits[0]), int(exits[1]), int(exits[2])
    pct = lambda r: round(100 * r[1] / r[0], 3) if r[0] else None
    return {"exit_split": {"pairs": n_pairs, "first_tie_before_arrival": tie_pre,
                           "first_tie_after_arrival": tie_post,
                           "never_tie": n_pairs - tie_pre - tie_post},
            "rate_pre_pp": pct(pre), "pre_rows": pre[0], "pre_ties": int(pre[1]),
            "rate_post_obs_pp": pct(post_obs), "post_obs_rows": post_obs[0], "post_obs_ties": int(post_obs[1]),
            "rate_post_allyears_pp": pct(post_all), "post_all_rows": post_all[0], "post_all_ties": int(post_all[1]),
            "post_rows_after_cap": int(years[2]), "panel_years": [int(years[0]), int(years[1])],
            "raw_rate_by_event_time_pp": {int(t): (round(100 * ties / n, 3) if n else None) for t, n, ties in by_tau},
            "rows_by_event_time": {int(t): int(n) for t, n, _ in by_tau}}

led = {"_source_note": ("Panel 3: pairs of department-roster incumbents who were both outside the star's two-hop "
                        "pre-arrival network and who BOTH share at least one subfield with the star (dose > 0 — the "
                        "main specification since the author-signed change of 2026-08-30; the former cut, both at or "
                        "above the discipline's median positive dose, is carried under 'robustness'). Estimates from "
                        "analysis/expected/P3pos_{field}_A_far.json (dCDH, effects=5, placebo=4, pair x event groups; "
                        "pair- and event-clustered SEs). Raw rates recomputed from data/frames/p3_afar_pos_{field}.parquet "
                        f"on observable pair-years (calendar year <= {YEAR_CAP}); post window = tau {POST_TAUS[0]}..{POST_TAUS[1]}. "
                        "Counts from data/frames/p3_afar_counts_by_spec.csv. No-effect simulation rebuilt at "
                        "nsim=200 on this specification, October (cal2026-10) cloud batch: data/cal2026-10/cloud/null/"
                        "NULLpos_{field}.json, recomputed from its custody-pinned slices. Permutations (B=500): "
                        "data/cal2026-10/cloud/perm/{raw,control}, custody-pinned, cross-checked against perm_summary.json. "
                        "Dose-cut grid and the two-year date shift: data/cal2026-10/robustness/afar_cuts/ (MANIFEST-pinned). "
                        "The speed bracket has "
                        "been REMOVED: it was pre-caliber, its capped cells have no caliber builder, and the specification "
                        "change moves the population again. Script: analysis/paper/ledger_p3afar.py."),
       "year_cap": YEAR_CAP, "post_window_tau": list(POST_TAUS)}

for col, (f, title) in enumerate(FIELDS):
    # the SHIPPED gold is the source. Post-freeze there is NO legacy equality cross-check: the
    # legacy run directory is the pre-caliber run and differs by design (see the SRC note above);
    # the M2 gate's job ("nothing stale can silently feed the ledger") is done by the expected
    # manifest, which pins these golds to the author-approved caliber estimates.
    j = json.load(open(XP / f"P3{SPEC_MAIN}_{f}_A_far.json"))
    pc, ec = j["pair_cluster"], j["event_cluster"]
    c = counts[f]
    r = rates(f)
    d = {"events_with_pairs": j["events"], "pairs": j["grps"], "first_ties": j["first_ties"], "rows": j["rows"],
         "ate_pp": round(100 * pc["ate"], 3), "se_pair_pp": round(100 * pc["se"], 3), "se_event_pp": round(100 * ec["se"], 3),
         "ci95_pair_pp": [round(100 * pc["lb"], 3), round(100 * pc["ub"], 3)],
         "p_joint_effects_pair": pc["p_joint_effects"], "p_joint_effects_event": ec["p_joint_effects"],
         "placebo": "structurally zero (pairs in the comparison for cohort a are unconnected at a); p_joint_placebo = null",
         "horizons_pp": [{"ell": e["k"] - 1, "est": round(100 * e["est"], 3), "se_pair": round(100 * e["se"], 3),
                          "se_event": round(100 * ee["se"], 3), "n": e["n"], "switchers": e["switchers"]}
                         for e, ee in zip(pc["effects"], ec["effects"])],
         "topic_rule": "both incumbents share at least one subfield with the star (dose > 0)",
         "lb_counts_pooled": {"rate_pre_pp": round(float(c["rate_pre_pp"]), 3), "rate_post_pp_allyears": round(float(c["rate_post_pp"]), 3)}}
    # Share of the switcher-weighted post-arrival sum that each horizon contributes (2026-09-10): the
    # reported average is sum_l w_l * est_l / sum_l w_l with w = switchers, so a single noisy year can
    # carry most of it (chemistry: the fourth year). Percent, one decimal; printed in sec4_p3.tex.
    _tot = sum(h["switchers"] * h["est"] for h in d["horizons_pp"])
    d["post_sum_share_pct_by_ell"] = {str(h["ell"]): (round(100 * h["switchers"] * h["est"] / _tot, 1) if _tot else None)
                                      for h in d["horizons_pp"]}
    d.update(r)
    # No-effect simulation, REBUILT 2026-08-30 on the new main specification, nsim=200 (the
    # frozen pre-caliber pair ran nsim=3 on a population two calibrations old). Driver:
    # analysis/robustness/null_sim/run_null.R, the slice-aware version of the 2026-08-17
    # B0_null_test.R; slices merged by analysis/robustness/null_sim/merge_null.py.
    nj = null_checked(f)
    if nj is not None:
        null_pp = nj["null_mean"]["dcdh_ate_pp"]
        d["null_simulation"] = {
            "nsim": nj["nsim"], "dcdh_ate_pp_no_effect_world": round(null_pp, 3),
            "share_of_real_estimate": round(null_pp / d["ate_pp"], 3) if d["ate_pp"] else None,
            "note": (
                "first-tie hazards depend only on pair age and calendar year, estimated from the real "
                "panel, so this is an upper bound on the mechanical share; exit at first tie. "
                "MEASURED 2026-08-30, correcting an earlier note in this file: the no-effect world does "
                "NOT only bias the estimate downward, so depletion interacting with the not-yet-treated "
                "comparison can manufacture the sign as well as the size. The earlier claim that "
                "depletion 'can only push the estimate DOWN' was reasoning, not measurement, and this "
                f"simulation refutes it: the no-effect mean here is {round(null_pp, 3):+} pp against a "
                f"reported {d['ate_pp']:+}.")}

    # Randomization inference, 2026-08-30. Treatment varies at the ARRIVAL, and there are only
    # 108 / 38 / 32 arrivals contributing pairs, so cluster-robust errors on pairs can overstate
    # precision. run_perm.R reassigns the observed arrival years across the observed events and
    # re-estimates; perm 0 is the identity control and is excluded from the reference distribution.
    # Two-sided p = (1 + #{|ate_perm| >= |ate_obs|}) / (1 + #perms), the standard finite-sample form.
    # October (cal2026-10): the draws come from the custody-chained cloud batch; the identity
    # permutation (perm 0, in perm/control) must reproduce the gold estimate.
    ri = perm_checked(f, pc["ate"])
    if ri["permutations"]:
        d["randomization_inference"] = {
            "permutations": ri["permutations"], "p_two_sided": ri["p_two_sided"],
            "n_at_least_as_large": ri["n_at_least_as_large"],
            "identity_control_ate_pp": ri["identity_control_ate_pp"],
            "failed_draws": ri["failed_draws"],
            "note": ("arrival years permuted across events, everything else frozen; the identity "
                     "permutation must reproduce the reported estimate.")}

    # ---- robustness: the topic cut the main specification replaced, plus the whole grid -------
    cr = counts_rob.get(f)
    jr = json.load(open(XP / f"P3{SPEC_ROB}_{f}_A_far.json"))
    rob = {"former_main_cut": {
              "rule": "both incumbents at or above the discipline's median positive dose",
              "cut": float(cr["cut"]) if cr and cr.get("cut") else None,
              "pairs": jr["grps"], "first_ties": jr["first_ties"], "events": jr["events"],
              "ate_pp": round(100 * jr["pair_cluster"]["ate"], 3),
              "se_pair_pp": round(100 * jr["pair_cluster"]["se"], 3),
              "rate_pre_pp": round(float(cr["rate_pre_pp"]), 3) if cr else None,
              "rate_post_pp": round(float(cr["rate_post_pp"]), 3) if cr else None}}
    grid_f = CUTS / "afar_cut_grid.csv"
    if grid_f.is_file():
        pinned(CUTS, "afar_cut_grid.csv")
        # The grid CSV stores the estimate already rounded to 4 dp, and rounding that a second time
        # to the 3 dp the paper prints is a DOUBLE ROUNDING: chemistry at the median cut is
        # -0.60448, which is -0.604, but the CSV's -0.6045 rounds up to -0.605 and that wrong digit
        # reached the manuscript. Take the estimate from the full-precision run JSON whenever it is
        # on disk, and keep the CSV only for the pair count and the threshold.
        est_dir = CUTS / "estimates"   # October products (the 2026-08-30 freeze until 2026-09-23)
        rows = []
        for r in csv.DictReader(open(grid_f)):
            if r["field"] != f:
                continue
            ate, se = float(r["ate_pp"]), float(r["se_pair_pp"])
            ej = est_dir / f"P3cut_{r['cut_spec']}_{f}.json"
            if ej.is_file():
                pc = json.load(open(pinned(CUTS, f"estimates/P3cut_{r['cut_spec']}_{f}.json")))["pair_cluster"]
                ate, se = 100 * pc["ate"], 100 * pc["se"]
            rows.append({"cut_spec": r["cut_spec"],
                         "cut": (float(r["cut"]) if r["cut"] else None),
                         "pairs": int(r["pairs"] or 0),
                         # 6 dp, not 4: anything the paper prints at 3 dp must be rounded ONCE,
                         # from a value carrying more digits than the print precision.
                         "ate_pp": round(ate, 6), "se_pair_pp": round(se, 6)})
        rob["cut_grid"] = rows
    pdf_ = CUTS / "predate" / f"P3pos_s2_{f}.json"   # October products (the 2026-08-30 freeze until 2026-09-23)
    if pdf_.is_file():
        pj = json.load(open(pinned(CUTS, f"predate/P3pos_s2_{f}.json"))).get("predate", {})
        rob["date_shift_two_years"] = {
            "p_joint_shifted": pj.get("p_joint_shifted"),
            "shifted_effects_pp": [round(100 * e["est"], 4) for e in (pj.get("shifted_effects") or [])],
            "note": "horizons k=1,2 fall on years before the star arrived; under no anticipation they should be zero"}
    d["robustness"] = rob
    led[f] = d
# ---- the figure: top row event-time coefficients, bottom row raw rates (fig_p3_afar.draw, per --tree)
try:
    _fig = fig_p3_afar.draw(led, ARGS.tree, OUT_FIG, font_fallback=ARGS.test_font_fallback,
                            font_search_dirs=ARGS.font_dir)
except fig_p3_afar.FontStop as e:
    print(e, file=sys.stderr)
    raise SystemExit(2)
json.dump(led, open(OUT_JSON, "w"), indent=1, ensure_ascii=False)
print("wrote", OUT_JSON, "and", OUT_FIG)
if ARGS.tree != "thesis_report":
    print(f"   figure: base tree Figure 7, font {_fig['font']['family']}"
          f"{' (TEST FALLBACK)' if _fig['font']['fallback'] else ''}; clipped interval ends {_fig['clipped']}")
for f, _ in FIELDS:
    d = led[f]
    print(f, "ate", d["ate_pp"], "se", d["se_pair_pp"], d["se_event_pp"], "CI", d["ci95_pair_pp"], "p", round(d["p_joint_effects_pair"], 4),
          "| pre", d["rate_pre_pp"], "post_obs", d["rate_post_obs_pp"], "post_all", d["rate_post_allyears_pp"], "rows>cap", d["post_rows_after_cap"],
          "| null share", d.get("null_simulation", {}).get("share_of_real_estimate"),
          "| rob(med)", d["robustness"]["former_main_cut"]["ate_pp"])
    print("   by tau:", d["raw_rate_by_event_time_pp"])
