#!/usr/bin/env python3
"""ledger_robustness.py — Section 4.2 (robustness) numbers ledger.

Written 2026-09-13 for the Section 4.2 exhibits (tables tab_robustness / tab_rob_p1 / tab_rob_p2 /
tab_rob_p3; thesis ledger data_numbers_2026-09-13_robustness.json). House pattern: ledger_p1p2.py.
It holds ONLY the checks that had no ledger home before this date; the checks already ledgered
elsewhere are read by the table generator from their own ledgers and are NOT duplicated here:
  data_numbers_p1p2.json   : main Panel 1/2 cells, by_route, p1_loeo_econ, p1_doublestar_*,
                             perm_pvalues (T5, Panels 1 and 2)
  data_numbers_p3afar.json : main Panel 3 cells, robustness.date_shift_two_years (dose>0),
                             robustness.cut_grid, null_simulation, randomization_inference

Reads ONLY this package's frozen artifacts — zero hand-typed numbers; every file is sha256-checked
against its freeze MANIFEST before use. Since 2026-09-23 every input is the October (cal2026-10)
product (R = data/cal2026-10/robustness; the dated 2026-08/09 freeze each replaces in brackets):
  R/battery/P1{bnd0,bndmean,lvl,nex}_{field}.json   T2 bounds, T3 levels,       [robustness_2026-08-29]
                                                    T4 never-exposed pool
  R/leaver/P1leave_{field}.json                     T7 post-departure zeros     [robustness_2026-08-31]
  R/predate_p1/P1pd2_{field}.json                   Panel 1 date shift (-2y)    [predate_p1_2026-08-30]
  R/predate/P2pd2_{field}.json                      Panel 2 date shift (-2y)    [predate_2026-08-28]
  R/afar_cuts/predate/P3pos_s2_{field}.json         Panel 3 date shift (-2y)    [robustness_afar_cuts_2026-08-30]
  R/afar_cuts/estimates/P3cut_{spec}_{field}.json   dose cuts, joint tests      [robustness_afar_cuts_2026-08-30]
  R/departure/estimates/P{1,2}dep{A,B}_{field}.json, P3dep{A,B}_pos_{field}_A_far.json
                                                    star departure A/B, ALL THREE disciplines (D6)
                                                    [robustness_2026-08-29_b, robustness_2026-09-10_p3pos: econ only]
  R/departure/departure187_build_report_{field}.json  coverage, from the 187-event ledger
                                                    [departure_build_report.json + dep_match_canon.csv,
                                                    the 25 hand verdicts — no longer used]
  data/departure_verification_2026-09-10/departure_verified_2026-09-10.csv   the 187-event verdicts (not shipped)
  R/nocentre/estimates/P{1,2}nc_{chemistry,math_stats}.json, P3nc_pos_{..}_A_far.json,
                    P3nc_math_stats_full.json, R/nocentre/nocentre_report.json
                                                    [robustness_2026-08-29_b, robustness_2026-09-10_p3pos]
  R/d7/p05/..., R/d7/dosebin3/...                   D7 (NEW): top-5% stars; dose in three bins
  data/cal2026-10/cloud/fetch/out/P3{p05,dose3}_{econ,chemistry}.json   D7 full-panel Panel 3 cloud
                                                    cells, pinned by the cloud custody record
  R/verified_pool/{d4_measure_report.json, estimates/P{1,2}ver_econ.json}  D4 verified pool (NEW block)
  analysis/expected/P1_*.json                       per-channel placebo p and coefficients (gold;
                                                    repo-tracked, read directly as ledger_p1p2.py does)
Writes
  output/paper/data_numbers_robustness.json

Conventions:
- Panel 1 cells are the UNION channel unless the block is explicitly per channel. Estimates are
  log points per unit of dose, rounded to 3 dp as printed; standard errors likewise. p-values
  are stored at full precision (the table generator formats them).
- Panel 2 and Panel 3 estimates are multiplied by 100 (percentage points of the yearly first-tie
  probability) and rounded to 3 dp, matching the P1/P2 and P3 ledgers.
- The levels variant (T3) is in the outcome's own units (FWCI-weighted output per year), not
  comparable in size to the log estimates; it is kept for the appendix only.
- The never-exposed variant (T4) has no joint tests in the frozen artifact (null); nothing is
  invented for it.
- Date-shift blocks store the joint p of the two shifted horizons that fall on genuinely
  pre-arrival years (k=1,2 of the shifted run) and those two coefficients.
- D7 three-bin dose: the Panel 1 treatment is the dose's tercile rank (1/2/3, 0 for zero dose) times
  post, so its estimate is log points PER BIN STEP, not per unit of dose; the Panel 3 "dose3" and
  "p05" full-panel cells are the all-pairs Panel 3 (P3_interconnect, run_p3.R), not the A_far
  population of the paper's Panel 3. A cell whose estimation failed is recorded with its status
  and sample counts and no estimate — nothing is filled in.
Run:  python3 analysis/paper/ledger_robustness.py
"""
import collections, csv, hashlib, json, sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from analysis.lib.paths import load_paths
from analysis.lib import canon
from analysis.paper import _m_checks

P = load_paths()
XP = P["expected"]
DATA = P["repo_root"] / "data"
CAL = P["cal"]                    # R1 F7: the cal root from config (October data/cal2026-10)
ROBX = CAL / "robustness"
ROB_A = ROBX / "battery"          # was data/robustness_2026-08-29
ROB_L = ROBX / "leaver"           # was data/robustness_2026-08-31
DEP = ROBX / "departure"          # was data/robustness_2026-08-29_b/departure (+ 2026-09-10_p3pos)
NOC = ROBX / "nocentre"           # was data/robustness_2026-08-29_b/nocentre (+ 2026-09-10_p3pos)
PD1 = ROBX / "predate_p1"         # was data/predate_p1_2026-08-30
PD2 = ROBX / "predate"            # was data/predate_2026-08-28
D7 = ROBX / "d7"                  # NEW (D7)
VER = ROBX / "verified_pool"      # NEW block (D4)
CLOUD = CAL / "cloud"
OUT_JSON = P["output"] / "paper" / "data_numbers_robustness.json"
FIELDS = ["econ", "chemistry", "math_stats"]
CHANNELS = ["union", "network", "dept"]


def gold_name(prefix, field):
    return f"{prefix}_{'econ_fnfix' if field == 'econ' else 'fnfix_' + field}.json"


def pinned(freeze_root, rel):
    """Read a freeze file only after its sha256 matches the freeze MANIFEST.
    Three MANIFEST styles exist in the package: repo-root-relative keys (every cal2026-10
    MANIFEST), keys with the data/<dir>/ prefix (the 2026-08 freezes) and bare relative names
    (robustness_2026-08-31). All three are accepted; nothing else is.
    R1 F7: the MANIFEST and the first key come from analysis/lib/canon.py (October: the freeze's own
    MANIFEST and the repo-relative key, as before; an M canon: the cal MANIFEST, '<prefix>/...' keys)."""
    manifest = {}
    for line in canon.freeze_manifest(freeze_root).read_text().splitlines():
        h, _, name = line.partition("  ")
        manifest[name.strip()] = h
    path = freeze_root / rel
    got = hashlib.sha256(path.read_bytes()).hexdigest()
    keys = (canon.key(path), f"data/{freeze_root.name}/{rel}", rel)
    want = next((manifest[k] for k in keys if k in manifest), None)
    assert want is not None, f"{rel}: not listed in {freeze_root.name}/MANIFEST.sha256"
    assert want == got, f"{rel}: sha256 {got} does not match the freeze MANIFEST"
    return path


def jload(path):
    return json.loads(Path(path).read_text())


_M = canon.mode() == "M"


def _cut_in_m(*paths) -> bool:
    """R1: True when an M canon lacks a cell the J1b robustness run does not produce - the F19 cuts
    (dose three bins, verified pool, the full-panel D7 Panel 3 cells, P3nc_math_stats_full) and the
    departure cells (F20, out of scope by the author's ruling of 2026-10-15: the paper prints no
    star-departure robustness). Its block is skipped and its key not written. Always False in
    October, which carries every cell (analysis/lib/canon_reads.tsv kind 'optional')."""
    return _M and not all(Path(x).is_file() for x in paths)


_CUSTODY = jload(CLOUD / "custody_cal2026-10.json")
assert _CUSTODY["ok"] is True and not _CUSTODY["problems"], "cloud custody record is not OK"


def custody_pinned(rel):
    """A cloud product (path under data/cal2026-10/cloud/fetch/) is read only after its sha256
    matches the custody record's fetch_sha256 entry."""
    path = CLOUD / "fetch" / rel
    want = _CUSTODY["fetch_sha256"].get(rel)
    got = hashlib.sha256(path.read_bytes()).hexdigest()
    assert want is not None, f"{rel}: not in the cloud custody fetch_sha256"
    assert want == got, f"{rel}: sha256 {got} does not match the cloud custody record"
    return path


def r3(x):
    return None if x is None else round(x, 3)


def pp(x):
    return None if x is None else round(100 * x, 3)


def p1_cell(ch):
    """Union-channel summary of a Panel 1 variant run, in the P1/P2 ledger's units."""
    return {"ate_log": r3(ch["ate"]), "se_person": r3(ch["se"]),
            "ci95_log": [r3(ch["lb"]), r3(ch["ub"])],
            "p_joint_effects": ch.get("p_joint_effects"), "p_joint_placebo": ch.get("p_joint_placebo"),
            "obs": ch["obs"], "relations": ch["rels"], "persons": ch["persons"], "events": ch["events"]}


def p2_cell(d):
    """A Panel 2 run in percentage points; a FAILED run keeps its status and counts, no estimate."""
    if d["status"] != "OK":
        return {"status": d["status"], "rows": d["rows"], "relations": d["rels"],
                "events": d["events"], "first_ties": d["first_ties"]}
    return {"ate_pp": pp(d["ate"]), "se_person_pp": pp(d["se"]),
            "p_joint_effects": d["p_joint_effects"], "rows": d["rows"], "relations": d["rels"],
            "events": d["events"], "first_ties": d["first_ties"]}


def p3pos_cell(d):
    """An A_far (dose > 0) Panel 3 run: pair- and event-clustered, percentage points."""
    pc, ec = d["pair_cluster"], d["event_cluster"]
    assert abs(pc["ate"] - ec["ate"]) < 1e-12, f"{d['label']}: pair/event point estimates differ"
    return {"ate_pp": pp(pc["ate"]), "se_pair_pp": pp(pc["se"]), "se_event_pp": pp(ec["se"]),
            "p_joint_effects_pair": pc["p_joint_effects"], "p_joint_effects_event": ec["p_joint_effects"],
            "rows": d["rows"], "pairs": d["grps"], "events": d["events"], "first_ties": d["first_ties"]}


def p3full_cell(d):
    """An all-pairs Panel 3 run (P3_interconnect, run_p3.R), percentage points; FAILED kept as such."""
    if d["status"] != "OK":
        return {"status": d["status"], "rows": d.get("rows"), "pairs": d.get("grps"),
                "first_ties": d.get("first_ties")}
    assert d["panel"] == "P3_interconnect", d["label"]
    return {"panel": "all incumbent pairs (P3_interconnect), not the A_far population",
            "ate_pp": pp(d["ate"]), "se_pair_pp": pp(d["se"]),
            "ci95_pp": [pp(d["lb"]), pp(d["ub"])], "p_joint_effects": d["p_joint_effects"],
            "rows": d["rows"], "pairs": d["grps"], "first_ties": d["first_ties"]}


# R1 M: the roots and the run come from the canon and the custody record (October: its note word for word)
led = {
    "_source_note": _m_checks.rob_source_note(canon.key(ROBX), canon.key(CLOUD), _m_checks.rob_run(_CUSTODY)),
}

# ---------------------------------------------------------------------------
# Panel 1 variants: T2 bounds (missing output as zero / as own mean), T3 levels,
# T4 never-exposed comparison pool, T7 post-departure years as zero
# ---------------------------------------------------------------------------
VARIANTS = {  # ledger key -> (freeze dir, file prefix, extra count field in the artifact)
    "missing_as_zero": (ROB_A, "P1bnd0", "filled_rows"),
    "missing_as_own_mean": (ROB_A, "P1bndmean", "filled_rows"),
    "levels": (ROB_A, "P1lvl", None),
    "never_exposed_pool": (ROB_A, "P1nex", "rows_kept"),
    "post_departure_zeros": (ROB_L, "P1leave", "leave_filled_rows"),
}
VARIANT_RULE = {"missing_as_zero": "fill0", "missing_as_own_mean": "fillmean", "levels": "levels",
                "never_exposed_pool": "neverexp", "post_departure_zeros": "fill0leave"}
led["p1_variants"] = {}
for f in FIELDS:
    block = {}
    for key, (root, prefix, extra) in VARIANTS.items():
        d = jload(pinned(root, f"{prefix}_{f}.json"))
        assert d["channels"]["union"]["status"] == "OK", f"{prefix}_{f}: union status not OK"
        assert d["variant"] == VARIANT_RULE[key], f"{prefix}_{f}: variant {d['variant']!r} is not {VARIANT_RULE[key]!r}"
        cell = p1_cell(d["channels"]["union"])
        cell["variant"] = d["variant"]
        if extra:
            cell[extra] = d[extra]
        if key == "never_exposed_pool":
            cell["rows_before_restriction"] = d["rows_before_restriction"]
            cell["second_exposure_switcher_rels"] = d["second_exposure_switcher_rels"]
        if key == "missing_as_own_mean":
            cell["all_missing_persons_dropped"] = d.get("all_na_persons")
        if key == "levels":  # outcome in its own units: keep the label so no reader mixes units
            cell["units"] = "FWCI-weighted output per year (levels, not log)"
        block[key] = cell
    led["p1_variants"][f] = block

# ---------------------------------------------------------------------------
# Panel 1 pre-arrival evidence by channel: gold placebo p + coefficients, and the date shift
# ---------------------------------------------------------------------------
led["p1_pretrend_by_channel"] = {}
led["p1_date_shift"] = {}
for f in FIELDS:
    gold = jload(XP / gold_name("P1", f))
    pd = jload(pinned(PD1, f"P1pd2_{f}.json"))
    assert pd["predate"]["shift"] == 2
    assert all(pd["channels"][ch]["status"] == "OK" for ch in CHANNELS), f"P1pd2_{f}: a channel is not OK"
    per = {}
    for ch in CHANNELS:
        g = gold["channels"][ch]
        se = pd["predate"]["shifted_effects"][ch]
        assert [e["k"] for e in se] == [1, 2]
        per[ch] = {
            "p_joint_placebo_person": g["p_joint_placebo"],
            "p_joint_effects_person": g["p_joint_effects"],
            # placebo index k maps to event time ell = k - 1 (k=-1 is ell=-2), as in ledger_p1p2.py
            "placebos_log": [{"ell": e["k"] - 1, "est": r3(e["est"]), "se": r3(e["se"]), "n": e["n"]}
                             for e in g["placebos"]],
            "p_joint_shifted": pd["predate"]["p_joint_shifted"][ch],
            "shifted_effects_log": [{"k": e["k"], "est": r3(e["est"]), "se": r3(e["se"]), "n": e["n"]}
                                    for e in se],
            "obs": g["obs"], "relations": g["rels"], "events": g["events"],
        }
    led["p1_pretrend_by_channel"][f] = per
    led["p1_date_shift"][f] = {"p_joint_shifted": pd["predate"]["p_joint_shifted"]["union"],
                               "shifted_effects_log": per["union"]["shifted_effects_log"],
                               "shift_years": 2,
                               "note": ("arrivals moved two years earlier; the shifted run's "
                                        "horizons k=1,2 fall on years before the star arrived "
                                        "and should be zero under no anticipation")}

# ---------------------------------------------------------------------------
# Panel 2 date shift (-2 years)
# ---------------------------------------------------------------------------
led["p2_date_shift"] = {}
for f in FIELDS:
    d = jload(pinned(PD2, f"P2pd2_{f}.json"))
    assert d["status"] == "OK" and d["predate"]["shift"] == 2
    if d["predate"].get("aux_status") == "FAILED":
        # the auxiliary effects=2 run that yields the joint test of the two shifted pre-arrival
        # horizons failed (October: mathematics); recorded as such, nothing is filled in
        assert "p_joint_shifted" not in d["predate"] and "shifted_effects" not in d["predate"]
        led["p2_date_shift"][f] = {"status": "AUX_FAILED", "p_joint_shifted": None,
                                   "shifted_effects_pp": [], "rows": d["rows"], "relations": d["rels"],
                                   "events": d["events"], "shift_years": 2,
                                   "note": ("the auxiliary effects=2 run of the shifted panel failed; "
                                            "no joint test of the two shifted horizons exists")}
        continue
    se = d["predate"]["shifted_effects"]
    assert [e["k"] for e in se] == [1, 2]
    led["p2_date_shift"][f] = {"p_joint_shifted": d["predate"]["p_joint_shifted"],
                               "shifted_effects_pp": [{"k": e["k"], "est": pp(e["est"]),
                                                       "se": pp(e["se"]), "n": e["n"]} for e in se],
                               "rows": d["rows"], "relations": d["rels"], "events": d["events"],
                               "shift_years": 2}

# ---------------------------------------------------------------------------
# Panel 3 (dose>0) date shift: the P3 ledger stores the joint p and the two shifted point
# estimates; this block adds their standard errors and cell sizes for the appendix table,
# read from the same frozen files, and the generator asserts the two ledgers agree.
# ---------------------------------------------------------------------------
CUTS = ROBX / "afar_cuts"         # was data/robustness_afar_cuts_2026-08-30
led["p3_date_shift"] = {}
for f in FIELDS:
    d = jload(pinned(CUTS, f"predate/P3pos_s2_{f}.json"))
    assert d["predate"]["shift"] == 2
    se = d["predate"]["shifted_effects"]
    assert [e["k"] for e in se] == [1, 2]
    led["p3_date_shift"][f] = {"p_joint_shifted": d["predate"]["p_joint_shifted"],
                               "shifted_effects_pp": [{"k": e["k"], "est": pp(e["est"]),
                                                       "se": pp(e["se"]), "n": e["n"]} for e in se],
                               "rows": d["rows"], "pairs": d["grps"], "events": d["events"],
                               "shift_years": 2}

# ---------------------------------------------------------------------------
# Panel 3 dose cuts: the P3 ledger stores each cut's estimate, standard error and pair count;
# this block adds the joint test and the event count from the same frozen files, and the
# generator asserts the two ledgers agree on the estimate.
# ---------------------------------------------------------------------------
led["p3_cut_grid"] = {}
for f in FIELDS:
    block = {}
    for spec in ("pos", "med", "abs04", "p75"):
        d = jload(pinned(CUTS, f"estimates/P3cut_{spec}_{f}.json"))
        pc = d["pair_cluster"]
        block[spec] = {"ate_pp": pp(pc["ate"]), "se_pair_pp": pp(pc["se"]),
                       "p_joint_effects_pair": pc["p_joint_effects"],
                       "pairs": d["grps"], "events": d["events"], "first_ties": d["first_ties"]}
    led["p3_cut_grid"][f] = block

# ---------------------------------------------------------------------------
# Star departure, rules A (drop events whose star left within the window) and B (treatment
# off from the departure year). October (D6): ALL THREE disciplines, from the 187-event departure
# ledger (data/departure_verification_2026-09-10, not shipped: LLM-assisted verdicts from public
# records, 45 listed rows flagged for a manual check). The 2026-08-29 design — economics only, 79 events
# machine-screened, 25 verdicts verified by hand (dep_match_canon.csv) — no longer applies.
# Economics keeps the key departure_econ; chemistry and mathematics get departure_<field>.
# The coverage keys that fed the 2026-09-13 table note are kept under their old names with their
# closest October meaning (see each comment); the note's wording predates this design.
# ---------------------------------------------------------------------------
DEPV = DATA / "departure_verification_2026-09-10"   # not shipped (restricted deposit)
_DEP_FIELDS = [] if _cut_in_m(DEP / "departure187_build_report_econ.json") else FIELDS   # F20 out of scope
_dep_rows = list(csv.DictReader(open(pinned(DEPV, "departure_verified_2026-09-10.csv")))) if _DEP_FIELDS else []
_KNOWN = ("stayed_through_window", "left_within_window", "left_after_window")
import duckdb as _duckdb
_con = _duckdb.connect()
for f in _DEP_FIELDS:
    rep = jload(pinned(DEP, f"departure187_build_report_{f}.json"))
    assert rep["noop_control"] == "BYTE_EQUAL", f"departure {f}: no-op control not byte-equal"
    rows = [r for r in _dep_rows if r["discipline"] == f]
    assert len(rows) == rep["rows"], f"departure {f}: ledger rows != build report"
    assert dict(collections.Counter(r["verdict"] for r in rows)) == rep["verdicts"], f"departure {f}: verdicts"
    frame_ev = {r[0] for r in _con.execute(
        f"SELECT DISTINCT event_id FROM read_csv_auto('{P['frames'] / f'p1_frame_{f}.csv'}', all_varchar=true)"
    ).fetchall()}
    assert len(frame_ev) == rep["events_in_frame"], f"departure {f}: frame events != build report"
    in_frame = [r for r in rows if r["event_id"] in frame_ev]
    vf = collections.Counter(r["verdict"] for r in in_frame)
    known = sum(vf[v] for v in _KNOWN)
    cov = {
        "ledger": rep["ledger"], "ledger_rows": rep["rows"],
        "verdicts_ledger": rep["verdicts"], "confidence_ledger": rep["confidence"],
        "verdict_source": rep["note"], "hand_verified": False,
        "author_review_flagged_rows_all_fields": sum(r["author_review_flag"] == "True" for r in _dep_rows),
        "events_in_frame": rep["events_in_frame"],
        "ledger_rows_in_frame": len(in_frame),
        "frame_events_without_ledger_row": sorted(frame_ev - {r["event_id"] for r in rows}),
        "ledger_rows_not_in_frame": sorted({r["event_id"] for r in rows} - frame_ev),
        "verdicts_in_frame": dict(vf),
        "unparseable_departure_years": len(rep["unparseable_departure_years"]),
        "afar": {k: rep["afar"][k] for k in ("events_in_afar", "A_dropped_in_afar", "B_recoded_in_afar")},
        # --- the 2026-09-13 keys, October meaning ---
        "canon_events": rep["events_in_frame"],                  # events in the estimation frame
        "verified_verdicts": known,                              # in-frame events with a verdict (LLM-assisted, not by hand)
        "departed_verdicts": vf["left_within_window"] + vf["left_after_window"],   # in frame, left at any time
        "still_there_verdicts": vf["stayed_through_window"],    # in frame
        "events_without_verdict": rep["events_in_frame"] - known,                  # in frame, unknown or no ledger row
        "rule_A_events_dropped": len(rep["A_dropped_in_frame"]),
        "rule_B_events_recoded": len(rep["B_recoded_in_frame"]),
    }
    if f == "econ":
        cov["econ_events_without_hand_verdict"] = cov["events_without_verdict"]   # the 2026-09-13 key
        cov["chemistry_math_screened"] = True                                      # the 2026-09-13 key
    blk = {"coverage": cov, "p1": {}, "p2": {}, "p3_pos": {}}
    for rule in ("A", "B"):
        d = jload(pinned(DEP, f"estimates/P1dep{rule}_{f}.json"))
        assert d["channels"]["union"]["status"] == "OK", f"P1dep{rule}_{f}: union status not OK"
        blk["p1"][rule] = p1_cell(d["channels"]["union"])
        d = jload(pinned(DEP, f"estimates/P2dep{rule}_{f}.json"))
        assert d["status"] in ("OK", "FAILED"), f"P2dep{rule}_{f}: status {d['status']}"
        blk["p2"][rule] = p2_cell(d)   # October: P2depA_math_stats FAILED — kept as FAILED
        blk["p3_pos"][rule] = p3pos_cell(jload(pinned(DEP, f"estimates/P3dep{rule}_pos_{f}_A_far.json")))
    assert blk["p1"]["A"]["events"] == rep["events_in_frame"] - len(rep["A_dropped_in_frame"]), \
        f"departure {f}: rule A estimate events != frame events - dropped"
    led[f"departure_{f}"] = blk

# ---------------------------------------------------------------------------
# Research-centre rosters removed (chemistry and mathematics; economics has no centre roster)
# ---------------------------------------------------------------------------
led["no_centre_roster"] = {}
_ncrep = jload(pinned(NOC, "nocentre_report.json"))
assert _ncrep["status"] == "DONE" and not _ncrep["stops"], "nocentre report is not DONE"
for f in ("chemistry", "math_stats"):
    d1 = jload(pinned(NOC, f"estimates/P1nc_{f}.json"))
    d2 = jload(pinned(NOC, f"estimates/P2nc_{f}.json"))
    d3 = jload(pinned(NOC, f"estimates/P3nc_pos_{f}_A_far.json"))
    assert d1["channels"]["union"]["status"] == "OK" and d2["status"] == "OK"
    for lab in (f"P1nc_{f}", f"P2nc_{f}"):   # the report's cell hashes are the pinned estimates
        c = _ncrep["cells"][lab]
        assert c["status"] == "OK" and _m_checks.cell_is(c, pinned(NOC, f"estimates/{lab}.json")), lab
    rel = _ncrep["population"][f]["relationships"]
    led["no_centre_roster"][f] = {
        "p1": p1_cell(d1["channels"]["union"]),
        "p2": p2_cell(d2),
        "p3_pos": p3pos_cell(d3),
        "population": {"relations_canon": rel["relations_canon"], "relations_variant": rel["relations_variant"],
                       "persons_canon": rel["persons_canon"], "persons_variant": rel["persons_variant"],
                       "persons_removed": rel["persons_removed"], "events": rel["events_variant"]},
    }
# the all-pairs Panel 3 (P3_interconnect) no-centre cell exists for mathematics only (the
# chemistry all-pairs cells are cloud cells and were not part of the no-centre run)
if not _cut_in_m(NOC / "estimates" / "P3nc_math_stats_full.json"):     # F19 cut
    led["no_centre_roster"]["math_stats"]["p3_full"] = p3full_cell(jload(pinned(NOC, "estimates/P3nc_math_stats_full.json")))
led["no_centre_roster"]["econ"] = {"note": "economics has no research-centre roster variant: "
                                           "its centres were inside the department rosters by the "
                                           "2026-08-10 ruling"}

# ---------------------------------------------------------------------------
# D7 (NEW, 2026-09-22 design D7): (a) only arrivals whose star is in the top 5 percent (the event
# subsets data/cal2026-10/events_<field>_cal2026-10_p05.csv), (b) the similarity dose in three
# equal-sized bins. Local cells from R/d7/, the economics and chemistry all-pairs Panel 3 cells from
# the custody-chained cloud batch. A FAILED cell is recorded as FAILED, never filled in.
# ---------------------------------------------------------------------------
_flt = jload(pinned(D7, "p05/filter_report_p05.json"))
d7 = {"_note": ("top5: events restricted to arrivals whose star is in the top 5 percent; p1 union "
                "channel in log points per unit of dose; p2 in percentage points; p3_pos = the A_far "
                "(dose > 0) Panel 3 of the paper, pp; p3_full = the all-pairs Panel 3 "
                "(P3_interconnect), pp. dosebin3: the dose replaced by its tercile rank among positive "
                "doses (1/2/3; 0 for zero dose), so p1 is log points PER BIN STEP, not per unit of dose; "
                "p3_full = the all-pairs Panel 3 on the three-bin frame, pp."),
      "top5": {}, "dosebin3": {}}
for f in FIELDS:
    t = {"events_kept": _flt["frames"][f"events_{f}"],
         "events_of": _flt["frames"][f"p1_frame_{f}.csv"]["events_in"]}
    d = jload(pinned(D7, f"p05/estimates/P1p05_{f}.json"))
    assert d["channels"]["union"]["status"] == "OK", f"P1p05_{f}: union not OK"
    t["p1"] = p1_cell(d["channels"]["union"])
    assert t["p1"]["events"] == t["events_kept"], f"P1p05_{f}: events != the p05 subset"
    t["p2"] = p2_cell(jload(pinned(D7, f"p05/estimates/P2p05_{f}.json")))
    t["p3_pos"] = p3pos_cell(jload(pinned(D7, f"p05/estimates/P3p05pos_{f}_A_far.json")))
    if not _cut_in_m(CLOUD / "fetch" / "out" / f"P3p05_{f}.json" if f != "math_stats"
                     else D7 / "p05" / "estimates" / "P3p05_math_stats.json"):     # F19 cut (full-panel D7 P3)
        t["p3_full"] = p3full_cell(jload(custody_pinned(f"out/P3p05_{f}.json")) if f != "math_stats"
                                   else jload(pinned(D7, "p05/estimates/P3p05_math_stats.json")))
    d7["top5"][f] = t
    if _cut_in_m(D7 / "dosebin3" / f"P1dosebin3_{f}.json"):     # F19 cut (dose three bins)
        continue
    d = jload(pinned(D7, f"dosebin3/P1dosebin3_{f}.json"))
    assert d["variant"] == "dosebin3" and d["channels"]["union"]["status"] == "OK", f"P1dosebin3_{f}"
    b = {"p1": p1_cell(d["channels"]["union"])}
    b["p1"]["units"] = "log points per dose-bin step (bins 1/2/3), not per unit of dose"
    b["p1"]["dose_bin_cuts"] = [round(x, 6) for x in d["dose_bins"]["cuts"]]
    b["p1"]["relations_per_bin"] = d["dose_bins"]["relations_per_bin"]
    b["p3_full"] = p3full_cell(jload(custody_pinned(f"out/P3dose3_{f}.json")) if f != "math_stats"
                               else jload(pinned(D7, "dosebin3/P3dose3_math_stats.json")))
    d7["dosebin3"][f] = b
led["d7"] = d7

# ---------------------------------------------------------------------------
# D4 verified pool (economics): on the October caliber the pool IS the verified roster, so the
# 2026-09-13 exclusion rule drops nobody and the verified-pool cells equal the main cells.
# ---------------------------------------------------------------------------
if not _cut_in_m(VER / "d4_measure_report.json"):   # F19 cut the verified-pool cells
    _d4 = jload(pinned(VER, "d4_measure_report.json"))
    _v1 = jload(pinned(VER, "estimates/P1ver_econ.json"))["channels"]["union"]
    _v2 = jload(pinned(VER, "estimates/P2ver_econ.json"))
    _g1 = jload(XP / gold_name("P1", "econ"))["channels"]["union"]
    _g2 = jload(XP / gold_name("P2", "econ"))
    assert _v1["ate"] == _g1["ate"] and _v1["se"] == _g1["se"] and _v1["obs"] == _g1["obs"], "P1ver != main"
    assert _v2["ate"] == _g2["ate"] and _v2["se"] == _g2["se"] and _v2["rows"] == _g2["rows"], "P2ver != main"
    led["verified_pool_econ"] = {
        "persons_not_on_verified_roster_p1": _d4["panel1"]["vs_roster_2026-10"]["persons_not_on_roster"],
        "persons_not_on_verified_roster_p2": _d4["panel2"]["vs_roster_2026-10"]["persons_not_on_roster"],
        "rows_dropped_p1": _d4["panel1"]["vs_roster_2026-10"]["rows_of_persons_not_on_roster"],
        "rows_dropped_p2": _d4["panel2"]["vs_roster_2026-10"]["rows_of_persons_not_on_roster"],
        "p1_equals_main": True, "p2_equals_main": True,
        "note": ("D4: the October network pool is the verified roster, so the 2026-09-13 rule "
                 "(drop incumbents not on the verified economics roster) removes nobody; the "
                 "verified-pool cells are the main cells")}

OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
json.dump(led, open(OUT_JSON, "w"), indent=1, ensure_ascii=False)
print(f"wrote {OUT_JSON}")
for f in FIELDS:
    v = led["p1_variants"][f]
    print(f"  P1 {f:10s} zero {v['missing_as_zero']['ate_log']:+.3f} ({v['missing_as_zero']['se_person']:.3f})"
          f"  own-mean {v['missing_as_own_mean']['ate_log']:+.3f}  nex {v['never_exposed_pool']['ate_log']:+.3f}"
          f" ({v['never_exposed_pool']['se_person']:.3f})  leave {v['post_departure_zeros']['ate_log']:+.3f}"
          f"  shift-p {led['p1_date_shift'][f]['p_joint_shifted']:.4g}  P2 shift-p "
          + (f"{led['p2_date_shift'][f]['p_joint_shifted']:.3f}" if led['p2_date_shift'][f]['p_joint_shifted'] is not None
             else led['p2_date_shift'][f]["status"]))
for f in FIELDS:
    t, b = led["d7"]["top5"][f], led["d7"]["dosebin3"].get(f)
    tf = t.get("p3_full", {"status": "CUT_IN_M"})
    print(f"  D7 {f:10s} top5 ev {t['events_kept']}/{t['events_of']}  P1 {t['p1']['ate_log']:+.3f}"
          f"  P2 {t['p2'].get('ate_pp', t['p2'].get('status'))}  P3pos {t['p3_pos']['ate_pp']:+.3f}"
          f"  P3full {tf.get('ate_pp', tf.get('status'))} | bin3 "
          + (f"P1 {b['p1']['ate_log']:+.3f}  P3full {b['p3_full'].get('ate_pp', b['p3_full'].get('status'))}"
             if b is not None else "CUT_IN_M"))
