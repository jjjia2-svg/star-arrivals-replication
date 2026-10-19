#!/usr/bin/env python3
"""ledger_p1p2.py — Panel 1 (output) and Panel 2 (first tie with the star) numbers ledger.

Written 2026-08-30 for the Panel 1 + Panel 2 exhibits (tables tab_p1_*/tab_p2_*, figures
fig_p1/fig_p2, thesis ledger data_numbers_2026-08-30_p1p2.json). House pattern: ledger_p3afar.py.

Reads ONLY this package's frozen artifacts — zero hand-typed numbers:
  analysis/expected/P1_{econ_fnfix,fnfix_chemistry,fnfix_math_stats}.json   dCDH person-clustered
  analysis/expected/P1evcl_*.json                                            same cells, event-clustered
  analysis/expected/P2_*.json + P2evcl_*.json                                Panel 2, both clusterings
  data/frames/p2_becoming_{field}.csv                    raw first-tie-with-star rates (year <= 2024)
  output/paper/gaps_switchers_p1p2.json                  switcher counts (R rerun GATED on equality
                                                         with the frozen golds — gaps_switchers_p1p2.R;
                                                         run it first)
  data/cal2026-10/robustness/battery/loeo_ranked.csv     leave-one-event-out battery (T1), econ P1
  data/cal2026-10/robustness/doublestar/                 double-star-window subsample (T6), econ P1,
                                                         and its complement (complement/estimates/)
  data/cal2026-10/cloud_t5/perm/perm_summary.json        permutation inference (T5), all six cells
Every robustness input is sha256-checked against its freeze MANIFEST before use (the October
MANIFESTs key files by their repo-root-relative path, which pinned() accepts). The T5 permutation
summary is a derived file with no MANIFEST line: its raw draws and identity controls are pinned
against the cloud custody record (data/cal2026-10/cloud_t5/custody_cal2026-10.json, fetch_sha256),
and the summary is recomputed from them with summarize_perm.py's rule and asserted equal.

2026-09-23 (cal2026-10, October caliber): every dated 2026-08/09 freeze read is re-pointed to the
October products under data/cal2026-10/ (map: the author's working notes, private). The
counts that were hard-coded for the 08-28 event set (116 LOEO removals, 98 double-star drops) are
now taken from the golds / build reports.
Writes
  output/paper/data_numbers_p1p2.json

Conventions (mirroring the Panel 3 ledger and Section 3 of the thesis):
- Panel 1 cells are the UNION channel (the paper's exposure population). The headline `ate_log`
  is the estimator's average post-arrival effect per unit of dose, in log points; `ate_pct` is
  its percent conversion 100*(e^ate - 1). Per-horizon estimates are the estimator's Effects rows
  (the average change in log output among switchers at their own dose). Panel 1 placebos are REAL
  (unlike Panels 2-3) and are reported.
- Panel 2 numbers are in percentage points (x100) of the yearly first-tie probability; its
  placebo is structural (p_joint_placebo = null in the frozen gold) and no placebo p is invented.
- Raw Panel 2 rates use OBSERVABLE relation-years only: calendar year <= 2024 (the 26 June 2026
  snapshot has no complete later year); post window = tau 0..5, matching Panel 3's convention.
Run:  python3 analysis/paper/ledger_p1p2.py   (after Rscript analysis/paper/gaps_switchers_p1p2.R)
"""
import csv, hashlib, json, math, sys
from pathlib import Path
import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from analysis.lib.paths import load_paths
from analysis.lib import canon

P = load_paths()
XP = P["expected"]
FR = P["frames"]
CAL = P["cal"]                                  # R1 F7: the cal root from config (October data/cal2026-10)
ROB_BAT = CAL / "robustness" / "battery"        # was data/robustness_2026-08-29 (LOEO)
ROB_DS = CAL / "robustness" / "doublestar"      # was data/robustness_2026-08-29_b/doublestar and
                                                #     data/robustness_2026-09-12_dscomp (complement/)
CLOUD_T5 = CAL / "cloud_t5"                     # was data/robustness_2026-08-29_b/perm (T5)
OUT_JSON = P["output"] / "paper" / "data_numbers_p1p2.json"
GAPS = P["output"] / "paper" / "gaps_switchers_p1p2.json"
FIELDS = ["econ", "chemistry", "math_stats"]
YEAR_CAP = 2024      # last calendar year with complete coverage in the 2026-06-26 snapshot
P2_POST_TAUS = (0, 5)  # arrival year .. five years after (Panel 3's raw-rate convention)
TOL = 1e-8


def gold_name(prefix, field):
    return f"{prefix}_{'econ_fnfix' if field == 'econ' else 'fnfix_' + field}.json"


def pinned(freeze_root, rel):
    """Read a robustness-freeze file only after its sha256 matches the freeze MANIFEST.
    Accepted MANIFEST keys: the repo-root-relative path (the October cal2026-10 MANIFESTs), the
    data/<dir>/<rel> form of the 2026-08 freezes, or the bare relative name. Nothing else.
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


def custody_pinned(cloud_root, path, key):
    """A cloud product is read only after its sha256 matches the custody record's fetch_sha256
    entry (the chain local sha256 -> instance md5 -> fetched sha256 of the cal2026-10 batches)."""
    cust = json.loads((cloud_root / "custody_cal2026-10.json").read_text())
    assert cust["ok"] is True and not cust["problems"], f"{cloud_root}: custody not OK"
    want = cust["fetch_sha256"].get(key)
    got = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    assert want is not None, f"{key}: not in {cloud_root.name}/custody fetch_sha256"
    assert want == got, f"{path}: sha256 {got} does not match the custody record ({key})"
    return path


def perm_summary_checked(cloud_root):
    """Read <cloud_root>/perm/perm_summary.json and recompute every cell from its custody-pinned
    raw draws and identity controls with summarize_perm.py's rule (FAILED draws out of both
    numerator and denominator; p = (1 + #{|x_b| >= |x_obs|}) / (B_ok + 1)); assert equality."""
    summ = json.loads((cloud_root / "perm" / "perm_summary.json").read_text())
    raw = {}
    for f in sorted((cloud_root / "perm" / "raw").glob("*_perm_*.csv")):
        for r in csv.DictReader(open(custody_pinned(cloud_root, f, f"out_perm/{f.name}"))):
            raw.setdefault(r["label"], []).append(r)
    ctl = {}
    for f in sorted((cloud_root / "perm" / "control").glob("*_perm_0_0.csv")):
        for r in csv.DictReader(open(custody_pinned(cloud_root, f, f"out_perm/{f.name}"))):
            if r["perm"] == "0":
                ctl[r["label"]] = r
    assert {c["label"] for c in summ["cells"]} == set(ctl), "perm summary cells != identity controls"
    for c in summ["cells"]:
        rows = raw[c["label"]]
        assert sorted(int(r["perm"]) for r in rows) == list(range(1, len(rows) + 1)), c["label"]
        ok = [r for r in rows if r["status"] == "OK"]
        a0, s0 = float(ctl[c["label"]]["ate"]), float(ctl[c["label"]]["se"])
        t0 = a0 / s0
        n_a = sum(1 for r in ok if abs(float(r["ate"])) >= abs(a0))
        n_t = sum(1 for r in ok if abs(float(r["t"])) >= abs(t0))
        again = {"B_requested": len(rows), "B_ok": len(ok), "B_failed": len(rows) - len(ok),
                 "ate_obs": a0, "p_perm_abs_ate": round((1 + n_a) / (len(ok) + 1), 6),
                 "p_perm_abs_t": round((1 + n_t) / (len(ok) + 1), 6)}
        for k, v in again.items():
            assert c[k] == v, f"perm {c['label']}: summary {k}={c[k]} but the pinned raw gives {v}"
        c["n_at_least_as_large_abs_ate"] = n_a
    return summ


if not GAPS.is_file():
    sys.exit(f"missing {GAPS} — run: Rscript analysis/paper/gaps_switchers_p1p2.R")
gaps = json.loads(GAPS.read_text())
for f in FIELDS:  # the R script already refuses to write on a failed gate; assert anyway
    assert gaps["p1"][f]["coef_check"]["pass"] is True, f"P1 {f}: switcher rerun not gold-equal"
    assert gaps["p2"][f]["coef_check"]["pass"] is True, f"P2 {f}: switcher rerun not gold-equal"

con = duckdb.connect()


def p2_rates(field):
    """Raw first-tie-with-star rates from the frozen becoming frame — the Panel 3 ledger's
    observable-years discipline (year <= YEAR_CAP), on the frame's own tau column."""
    fp = str(FR / f"p2_becoming_{field}.csv")
    q = lambda w: con.execute(f"SELECT count(*), sum(y) FROM read_csv_auto('{fp}') WHERE {w}").fetchone()
    pre = q(f"tau BETWEEN -6 AND -1 AND year <= {YEAR_CAP}")
    post_obs = q(f"tau BETWEEN {P2_POST_TAUS[0]} AND {P2_POST_TAUS[1]} AND year <= {YEAR_CAP}")
    by_tau = con.execute(
        f"SELECT tau, count(*) n, sum(y) t FROM read_csv_auto('{fp}') "
        f"WHERE tau BETWEEN -6 AND 5 AND year <= {YEAR_CAP} GROUP BY tau ORDER BY tau").fetchall()
    years = con.execute(
        f"SELECT min(year), max(year), sum(CASE WHEN year > {YEAR_CAP} AND post = 1 THEN 1 ELSE 0 END) "
        f"FROM read_csv_auto('{fp}')").fetchone()
    pct = lambda r: round(100 * r[1] / r[0], 3) if r[0] else None
    return {"rate_pre_pp": pct(pre), "pre_rows": pre[0], "pre_ties": int(pre[1]),
            "rate_post_obs_pp": pct(post_obs), "post_obs_rows": post_obs[0], "post_obs_ties": int(post_obs[1]),
            "post_rows_after_cap": int(years[2]), "panel_years": [int(years[0]), int(years[1])],
            "raw_rate_by_event_time_pp": {int(t): (round(100 * ties / n, 3) if n else None) for t, n, ties in by_tau},
            "rows_by_event_time": {int(t): int(n) for t, n, _ in by_tau}}


led = {"_source_note": (
    "Panels 1 and 2, union exposure population. Panel 1 estimates from analysis/expected/"
    "P1_{econ_fnfix|fnfix_chemistry|fnfix_math_stats}.json channels.union (dCDH, effects=6, "
    "placebo=4, person x event groups, incumbent-clustered SEs) and P1evcl_*.json (same cells, "
    "event-clustered; point estimates asserted equal). ate_log = average post-arrival effect per "
    "unit of dose in log points; ate_pct = 100*(e^ate-1); per-horizon estimates are the "
    "estimator's Effects rows (the average change among switchers at their own dose); Panel 1 "
    "placebo coefficients are real and reported. Panel 2 estimates from P2_*.json / P2evcl_*.json "
    "(dCDH, effects=5, placebo=4, person x star-rel groups), in percentage points; its placebo is "
    "structural (p_joint_placebo = null) and none is invented. Switcher counts from "
    "output/paper/gaps_switchers_p1p2.json (analysis/paper/gaps_switchers_p1p2.R: rerun from the "
    f"frozen frames, gated on equality with the golds). Raw Panel 2 first-tie rates recomputed "
    f"from data/frames/p2_becoming_*.csv on observable relation-years (calendar year <= {YEAR_CAP}); "
    f"post window = tau {P2_POST_TAUS[0]}..{P2_POST_TAUS[1]} (Panel 3's convention). Robustness "
    "blocks from the October (cal2026-10) products, each input sha256-checked against its MANIFEST: "
    "p1_loeo_econ from data/cal2026-10/robustness/battery/loeo_ranked.csv (T1 leave-one-event-out, "
    "one removal per economics event); p1_doublestar_econ from data/cal2026-10/robustness/doublestar/ "
    "(T6, arrivals with an earlier same-department arrival within 5 years dropped) and "
    "p1_doublestar_complement_econ from its complement/ subdirectory; perm_pvalues from "
    "data/cal2026-10/cloud_t5/perm/perm_summary.json (T5 permutation inference, B=500; raw draws "
    "pinned by the cloud custody record and the summary recomputed from them). "
    "Script: analysis/paper/ledger_p1p2.py. Zero hand-typed numbers."),
    "year_cap": YEAR_CAP,
    "p1_post_window_ell": [0, 5],
    "p2_post_window_tau": list(P2_POST_TAUS)}

for f in FIELDS:
    # ---------------- Panel 1, union channel ----------------
    g = json.loads((XP / gold_name("P1", f)).read_text())
    u = g["channels"]["union"]
    ev = json.loads((XP / f"P1evcl_{f}.json").read_text())
    assert ev["point_estimate_check"]["union"] == "MATCH", f"P1evcl_{f}: point estimates drifted"
    e = ev["channels"]["union"]
    for a, b in zip(u["effects"], e["effects"]):
        assert a["k"] == b["k"] and abs(a["est"] - b["est"]) < TOL, f"P1 {f}: evcl effect k={a['k']} differs"
    for a, b in zip(u["placebos"], e["placebos"]):
        assert a["k"] == b["k"] and abs(a["est"] - b["est"]) < TOL, f"P1 {f}: evcl placebo k={a['k']} differs"
    sw1 = gaps["p1"][f]
    assert [h["n"] for h in sw1["horizons"]] == [x["n"] for x in u["effects"]], f"P1 {f}: switcher N drifted"
    assert [h["n"] for h in sw1["placebos"]] == [x["n"] for x in u["placebos"]], f"P1 {f}: placebo N drifted"
    d = {"channel": "union",
         "ate_log": round(u["ate"], 3), "ate_pct": round(100 * (math.exp(u["ate"]) - 1), 1),
         "se_person": round(u["se"], 3), "se_event": round(e["se"], 3),
         "ci95_person": [round(u["lb"], 3), round(u["ub"], 3)],
         "p_joint_effects_person": u["p_joint_effects"], "p_joint_effects_event": e["p_joint_effects"],
         "p_joint_placebo_person": u["p_joint_placebo"], "p_joint_placebo_event": e["p_joint_placebo"],
         "horizons": [{"ell": x["k"] - 1, "est": round(x["est"], 3), "se_person": round(x["se"], 3),
                       "se_event": round(xe["se"], 3), "n": x["n"], "switchers": int(h["switchers"])}
                      for x, xe, h in zip(u["effects"], e["effects"], sw1["horizons"])],
         "placebos": [{"ell": x["k"] - 1, "est": round(x["est"], 3), "se_person": round(x["se"], 3),
                       "se_event": round(xe["se"], 3), "n": x["n"], "switchers": int(h["switchers"])}
                      for x, xe, h in zip(u["placebos"], e["placebos"], sw1["placebos"])],
         "obs": u["obs"], "relations": u["rels"], "relations_with_dose": u["rels_with_dose"],
         "persons": u["persons"], "events": u["events"],
         "switchers_ell0": int(sw1["horizons"][0]["switchers"]),
         "switchers_total": int(sw1["switchers_total"]),
         "weighted_avg_effect": round(sw1["weighted_avg_effect"], 3),
         "avg_dose_switchers": round(sw1["avg_dose_switchers"], 3),
         # 2026-09-01: ate_pct above is the change for a relation whose dose is ONE, and no
         # relation carries a dose that high (switcher averages are ~0.375/0.391/0.200). This is
         # the same change at the doses switchers actually carry: the switcher-weighted mean of
         # the six post-arrival coefficients is already in log points at those doses, converted
         # the same way. Reported so the body can give a magnitude a reader can feel
         # (thesis-writing.md 3.7 — economic significance, not only statistical significance).
         "avg_effect_pct_at_observed_dose":
             round(100 * (math.exp(sw1["weighted_avg_effect"]) - 1), 1),
         # 2026-09-01: the two routes into the exposure population, estimated separately.
         # Section 3.3 promises "Every Panel 1 estimate is reported separately for incumbents who
         # enter the population through the roster only, through the network only, and for their
         # union" — the runs exist (run_p1.R estimates all three channels) but only the union
         # reached the ledger, and Section 4.1 said the routes were not separated. The two
         # subsamples OVERLAP: an incumbent reached both ways belongs to each.
         "by_route": {
             "network": {"ate_log": round(g["channels"]["network"]["ate"], 3),
                         "se_person": round(g["channels"]["network"]["se"], 3),
                         "relations": g["channels"]["network"]["rels"]},
             "roster":  {"ate_log": round(g["channels"]["dept"]["ate"], 3),
                         "se_person": round(g["channels"]["dept"]["se"], 3),
                         "relations": g["channels"]["dept"]["rels"]}},
         "rows_raw": g["rows_raw"], "rows_kept": g["rows_kept"]}
    led[f"p1_{f}"] = d

    # ---------------- Panel 2 ----------------
    g2 = json.loads((XP / gold_name("P2", f)).read_text())
    ev2 = json.loads((XP / f"P2evcl_{f}.json").read_text())
    assert ev2["point_estimate_check"] == "MATCH", f"P2evcl_{f}: point estimates drifted"
    for a, b in zip(g2["effects"], ev2["effects"]):
        assert a["k"] == b["k"] and abs(a["est"] - b["est"]) < TOL, f"P2 {f}: evcl effect k={a['k']} differs"
    assert g2["p_joint_placebo"] is None, f"P2 {f}: placebo is expected to be structural"
    sw2 = gaps["p2"][f]
    assert [h["n"] for h in sw2["horizons"]] == [x["n"] for x in g2["effects"]], f"P2 {f}: switcher N drifted"
    d2 = {"ate_pp": round(100 * g2["ate"], 3),
          "se_person_pp": round(100 * g2["se"], 3), "se_event_pp": round(100 * ev2["se"], 3),
          "ci95_person_pp": [round(100 * g2["lb"], 3), round(100 * g2["ub"], 3)],
          "p_joint_effects_person": g2["p_joint_effects"], "p_joint_effects_event": ev2["p_joint_effects"],
          "placebo": ("structurally zero (a pair enters the comparison for cohort a only if still "
                      "unconnected at a); p_joint_placebo = null"),
          "horizons_pp": [{"ell": x["k"] - 1, "est": round(100 * x["est"], 3),
                           "se_person": round(100 * x["se"], 3), "se_event": round(100 * xe["se"], 3),
                           "n": x["n"], "switchers": int(h["switchers"])}
                          for x, xe, h in zip(g2["effects"], ev2["effects"], sw2["horizons"])],
          "rows": g2["rows"], "relations": g2["rels"], "persons": g2["persons"],
          "events": g2["events"], "first_ties": g2["first_ties"],
          "switchers_ell0": int(sw2["horizons"][0]["switchers"]),
          "switchers_total": int(sw2["switchers_total"])}
    d2.update(p2_rates(f))
    led[f"p2_{f}"] = d2

# ---------------- robustness blocks (October cal2026-10 products) ----------------
canon_p1_econ = json.loads((XP / "P1_econ_fnfix.json").read_text())["channels"]["union"]

# T1: leave-one-event-out, econ P1 union — one single-event removal per event of the ONE event set
# (116 on the 08-28 caliber; the count now comes from the gold, 113 on cal2026-10)
loeo_rows = list(csv.DictReader(open(pinned(ROB_BAT, "loeo_ranked.csv"))))
assert len(loeo_rows) == canon_p1_econ["events"], "LOEO must cover every event exactly once"
assert len({r["event_id"] for r in loeo_rows}) == len(loeo_rows), "LOEO: an event is removed twice"
for r in loeo_rows:
    assert int(r["events"]) == canon_p1_econ["events"] - 1, "each LOEO cell must drop exactly one event"
    assert abs(float(r["ate"]) - float(r["delta_ate_vs_canon"]) - canon_p1_econ["ate"]) < 1e-6, \
        f"LOEO {r['event_id']}: ate/delta inconsistent with the canon estimate"
ates = [float(r["ate"]) for r in loeo_rows]
pps = [float(r["p_joint_placebo"]) for r in loeo_rows]
imax = max(range(len(loeo_rows)), key=lambda i: pps[i])
led["p1_loeo_econ"] = {
    "n_removals": len(loeo_rows),
    "ate_min": round(min(ates), 3), "ate_max": round(max(ates), 3),
    "p_joint_placebo_max": pps[imax], "p_joint_placebo_max_event": loeo_rows[imax]["event_id"],
    "n_placebo_p_above_05": sum(1 for x in pps if x > 0.05),
    "p_joint_effects_max": max(float(r["p_joint_effects"]) for r in loeo_rows)}

# T6: double-star subsample, econ P1 union — arrivals with an earlier same-department arrival
# within 5 years dropped (same-year pairs kept, counts disclosed in the build report)
ds = json.loads(pinned(ROB_DS, "estimates/P1ds_econ.json").read_text())["channels"]["union"]
rep = json.loads(pinned(ROB_DS, "doublestar_build_report.json").read_text())["econ"]
assert ds["events"] == rep["kept"], "double-star: estimated events != build-report kept events"
assert rep["kept"] + rep["dropped"] == rep["events"] == canon_p1_econ["events"]
# Same-year co-arrivals among the KEPT events (the build report's same_year_pair_events_kept
# counts same-year events over ALL 116, dropped ones included): rederived from the freeze's
# drop list and the frozen events ledger. W1c MINOR-3 — disclosed in the sec4_p1 footnote.
drop_rows = list(csv.DictReader(open(pinned(ROB_DS, "doublestar_drops.csv"))))
kept_ids = {r["event_id"] for r in drop_rows if r["field"] == "econ" and r["dropped"] == "False"}
assert len(kept_ids) == rep["kept"]
ev_rows = list(csv.DictReader(open(FR / "p1_events_ledger_econ.csv")))
assert len(ev_rows) == rep["events"]
n_at = {}
for r in ev_rows:
    key = (r["school"], r["arrival_year"])
    n_at[key] = n_at.get(key, 0) + 1
same_year_kept = sum(1 for r in ev_rows if r["event_id"] in kept_ids
                     and n_at[(r["school"], r["arrival_year"])] > 1)
led["p1_doublestar_econ"] = {
    "events_kept": rep["kept"], "events_dropped": rep["dropped"],
    "same_year_pair_events_kept": rep["same_year_pair_events_kept"],
    "same_year_co_arrivals_among_kept": same_year_kept,
    "ate_log": round(ds["ate"], 3), "ate_pct": round(100 * (math.exp(ds["ate"]) - 1), 1),
    "se_person": round(ds["se"], 3), "ci95_person": [round(ds["lb"], 3), round(ds["ub"], 3)],
    "p_joint_effects": ds["p_joint_effects"], "p_joint_placebo": ds["p_joint_placebo"],
    "obs": ds["obs"], "relations": ds["rels"], "persons": ds["persons"]}

# 2026-09-12: the OVERLAPPED half of the same split (the events dropped above: 98 on the 08-28
# caliber, 95 on cal2026-10), estimated on its own by the verbatim driver
# (analysis/robustness/sensitivity/run_doublestar_complement.sh).
# Section 4.1 explains the failed placebo test by overlapping arrival windows; this cell is the
# direct test (placebo should reject here and pass on the clean kept events).
dsc = json.loads(pinned(ROB_DS, "complement/estimates/P1dsC_econ.json").read_text())["channels"]["union"]
dsc_rep = json.loads(pinned(ROB_DS, "complement/dscomp_build_report.json").read_text())
assert dsc["events"] == rep["dropped"] == dsc_rep["events_in_complement"], (dsc["events"], rep["dropped"])
assert dsc_rep["events_excluded_clean"] == rep["kept"], (dsc_rep["events_excluded_clean"], rep["kept"])
led["p1_doublestar_complement_econ"] = {
    "events": dsc["events"], "ate_log": round(dsc["ate"], 3),
    "ate_pct": round(100 * (math.exp(dsc["ate"]) - 1), 1),
    "se_person": round(dsc["se"], 3), "ci95_person": [round(dsc["lb"], 3), round(dsc["ub"], 3)],
    "p_joint_effects": dsc["p_joint_effects"], "p_joint_placebo": dsc["p_joint_placebo"],
    "obs": dsc["obs"], "relations": dsc["rels"]}

# T5: permutation inference — arrival years permuted across events, B=500 per cell (October batch
# data/cal2026-10/cloud_t5; its identity controls must reproduce the October golds)
perm = perm_summary_checked(CLOUD_T5)
cells = {c["label"]: c for c in perm["cells"]}
_B = {c["B_requested"] for c in perm["cells"]}
assert _B == {500}, f"T5: permutations requested per cell {_B}, the design is 500"
pv = {"B": _B.pop(), "seed_key": perm["seed_key"]}
for f in FIELDS:
    for panel, prefix in (("p1", "P1"), ("p2", "P2")):
        c = cells[gold_name(prefix, f)[:-5]]
        gold_ate = (json.loads((XP / gold_name(prefix, f)).read_text())["channels"]["union"]["ate"]
                    if panel == "p1" else json.loads((XP / gold_name(prefix, f)).read_text())["ate"])
        assert abs(c["ate_obs"] - gold_ate) < 5e-8, f"perm {panel}_{f}: ate_obs drifted from the gold"
        assert c["B_requested"] == 500
        assert c["n_events"] == (json.loads((XP / gold_name(prefix, f)).read_text())["channels"]["union"]["events"]
                                 if panel == "p1" else json.loads((XP / gold_name(prefix, f)).read_text())["events"]), \
            f"perm {panel}_{f}: n_events differs from the gold"
        pv[f"{panel}_{f}"] = {"p_perm_abs_ate": c["p_perm_abs_ate"], "p_perm_abs_t": c["p_perm_abs_t"],
                              "B_ok": c["B_ok"], "n_events": c["n_events"]}
led["perm_pvalues"] = pv

OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
json.dump(led, open(OUT_JSON, "w"), indent=1, ensure_ascii=False)
print("wrote", OUT_JSON)
for f in FIELDS:
    a, b = led[f"p1_{f}"], led[f"p2_{f}"]
    print(f"{f:11s} P1 ate {a['ate_log']} ({a['ate_pct']}%) se {a['se_person']}/{a['se_event']} "
          f"placebo p {a['p_joint_placebo_person']:.4g} | P2 ate {b['ate_pp']}pp "
          f"se {b['se_person_pp']}/{b['se_event_pp']} pre {b['rate_pre_pp']} post {b['rate_post_obs_pp']}")
print("loeo", led["p1_loeo_econ"], "\nds", {k: led['p1_doublestar_econ'][k] for k in ('events_kept', 'ate_log', 'p_joint_placebo')})
