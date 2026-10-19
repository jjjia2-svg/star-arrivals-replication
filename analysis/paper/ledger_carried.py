#!/usr/bin/env python3
"""ledger_carried.py — re-derives the ledger key-groups the thesis's data_numbers_2026-08-16.json
carries forward from a vanished 2026-08-14 generator script.

The thesis's surviving make_numbers_2026-08-16_partA.py writes only its own computed keys
(ported in ledger_main.py); the ~18 further key-groups below were merged into the same file by a
follow-on step whose script no longer exists anywhere. This script re-derives each group from the
concrete surviving source its ledger `_provenance` string names, so equality with the thesis
value is the spec. Nothing here is tuned to match: every derivation is the natural reading of the
named source, and each was checked against the thesis value before being adopted (see the
per-group notes). A group that could not be honestly re-derived would be listed in
UNREPRODUCIBLE and left out of the JSON — as of this writing that dict is empty.

Provenance note (correction): the 08-16 `_provenance` labels four groups "unchanged 08-14"
(centre_added, econ_arc_evidence_people, roster_people, econ_fellow_evidence_rows) and those four
do equal the surviving data_numbers_2026-08-14.json. The OTHER carried groups were REGENERATED
between 08-14 and 08-16 with the fnfix (poaching false-negative fix) inputs — math_units_*_pct,
star_stock, panel_rows, events_by_school_*, chem/math_py_decomp all differ from their 08-14
values — so the vanished generator ran (at least) twice, and this script targets the 08-16 state.

Group-by-group: 08-16 provenance string -> surviving source -> derivation
-------------------------------------------------------------------------
1. chem_units_{nofwci,structural,genuine}_pct   prov: "g_yrebuild_chemistry.json units (fnfix)"
   math_units_{nofwci,structural,genuine}_pct   prov: "g_yrebuild_math_stats.json units (fnfix)"
   Source: legacy_v2_output/multidisc_gold_2026-08-10/data/fnfix/g_yrebuild_{chemistry,math_stats}.json,
   block `fwci_new_na` (units_na, units_total, reasons_by_distinct_work).
   nofwci     = round(100*units_na/units_total, 1)
   structural = round(100*units_na/units_total * excluded/(excluded+other), 1)
   genuine    = round(100*units_na/units_total * other/(excluded+other), 1)
   where excluded = reasons_by_distinct_work["excluded_type"] and other = sum of the remaining
   reasons (mirrors partA's works-level convention: excluded_type = structural, rest = genuine;
   the unit-level NA share is split in proportion to the work-level reason counts). The math
   values (28.8/28.5/0.2) discriminate this formula from the plain 100*excluded/units_total
   reading (which gives 25.2, not 28.5); it reproduces all six thesis values.

2. chem_star_stock, math_star_stock             prov: "restake final + fnfix after_stock"
   Sources: repo data/raw_verified/events_{chemistry,math_stats}_fnfix.csv (the fnfix event
   ledgers: WHICH star-events count, n=35/31) + legacy multidisc_gold_2026-08-10/data/
   star_threshold_restake_final_2026-08-13.csv (column `stock_after`, the 22+20 final-era events)
   and fnfix_restake_2026-08-15.csv (column `after_stock`, the fnfix additions) — the provenance
   string names exactly these two columns. Quartiles are discrete (duckdb quantile_disc; the
   continuous/interpolated variants give 1192.5/4124.5 for chem, not the thesis 1158/4174).

3. chem_centre_added, math_centre_added         prov: "prep_final_report.json (unchanged 08-14)"
   Source: legacy multidisc_gold_2026-08-10/data/final/prep_final_report.json,
   rosters.{chemistry,math_stats}.added_people (134 / 28: research-centre roster supplement).

4. econ_arc_evidence_people                     prov: "econ_roster_verified_all.csv url contains arc.gov.au (unchanged 08-14)"
   Source: legacy_v2_output/econ_roster_verify_2026-08-09/econ_roster_verified_all.csv —
   count of DISTINCT author_id whose evidence_url contains "arc.gov.au" (= 0).

5. roster_people                                prov: "roster parquets (unchanged 08-14)"
   Source: repo data/raw_verified/roster_econ_verified.parquet, roster_gold_chemistry.parquet,
   roster_gold_math_stats.parquet — DISTINCT author_id per parquet (920/518/573; the gold
   parquets hold 533/580 employment spells; distinct people matches prep_final_report's
   people counts).

6. econ_fellow_evidence_rows                    prov: "econ_roster_verified_all.csv contains fellow/DECRA (unchanged 08-14)"
   Same CSV as (4): rows where ANY field contains "fellow" or "decra" (case-insensitive) = 205.
   (notes-only gives 204; case-sensitive whole-row gives 14 — only the any-field
   case-insensitive reading reproduces the thesis 205.)

7. panel_rows                                   prov: "fnfix frames / becoming / pairs_slim"
   Source: repo data/frames — per discipline [P1 frame rows, P2 becoming rows, P3 pairs_slim rows]:
   p1_frame_{econ,chemistry,math_stats}.csv, p2_becoming_*.csv, p3_slim_*.parquet
   (data row counts; the repo copies are the imported fnfix-era frames).

8. events_by_school_{econ,chem,math}            prov: "econ fnfix ledger 117" / "fnfix ledger"
   Sources: repo data/raw_verified/event_ledger_econ79.csv (arrival_year) UNION
   events_econ_new38.csv (arrival) for econ (79+38=117); events_chemistry_fnfix.csv and
   events_math_stats_fnfix.csv (arrival_corrected) for chem/math — school -> sorted year list.

9. chem_py_decomp, math_py_decomp               prov: the fnfix gold frame CSVs
   Source: repo data/frames/p1_frame_{chemistry,math_stats}.csv —
   rows            = all data rows
   y_val           = rows with fwci_frac NOT NULL
   empty_no_record = rows with fwci_frac NULL and pub_count NULL (out of publication record)
   genuine_missing = rows with fwci_frac NULL and pub_count NOT NULL
   pub0_na         = rows with pub_count = 0 and fwci_frac NULL (sanity: 0)
   (cross-check: identical to the g_yrebuild fnfix `transition` blocks — y_val =
   val2val+na2val+zero_fill, empty = row_na, genuine = val2na+na2na+agg_missing.)

Reads:  repo data/frames/ (October), data/raw_verified/ (chem/math rosters), data/cal2026-10/
        (event tables, econ roster + added-roster evidence, chem/math restake, y-rebuild reports,
        build reports — all sha256-pinned); legacy_v2_output/multidisc_gold_2026-08-10/
        (prep_final_report.json; the pre-October star stocks, cross-check only),
        legacy_v2_output/econ_roster_verify_2026-08-09/ (the 2026-08-09 evidence sheet) (read-only)
Writes: output/paper/data_numbers_carried.json

Freeze-wave Task 8 (2026-08-28 caliber): groups 2 and 8 now read the caliber
event tables (events_*_cal2026-08-28.csv: econ 116 / chem 38 / math 33) instead of the pre-caliber
fnfix set, and group 2 layers the caliber restake's after_stock on top of the final+fnfix stocks
for the five admitted stars; groups 5-7 and 9 move automatically with the promoted frames. The
spec is now equality with the thesis's 2026-08-28 successor ledger.
cal2026-10 (2026-09-23, the October caliber is the canon; design items D1-D5). Every group now reads its
October counterpart, sha256-checked against data/cal2026-10/MANIFEST.sha256 (or the file's own
directory MANIFEST) before it is read:
  1. units_*_pct   data/cal2026-10/yrebuild_chemmath/g_yrebuild_{chemistry,math_stats}.json (the
                   October Panel 1 build's own y-rebuild reports; 470 / 481 persons)
  2. star_stock    event set data/cal2026-10/events_{f}_cal2026-10.csv (byte-identical to the
                   08-28 tables: chemistry and mathematics were not re-ranked by D5) x `after_stock`
                   of the October star layer's chem/math verdicts,
                   data/cal2026-10/_invalid_run2/restake_2026-10.csv (the run whose ECONOMICS rows
                   are void; its chemistry/mathematics rows are valid — pipeline/stars/
                   caliber_2026-10/README.md). Cross-checked equal, event by event, to the old
                   layered stocks (final + fnfix + 08-28 restake) when the legacy tree is mounted,
                   in the October canon only (in M the stocks are the M restake's,
                   new stars have no 08-28 stock, and the provenance drops the "equal to" clause).
  3. centre_added  unchanged source (prep_final_report.json): the chemistry and mathematics rosters
                   are not touched by the October caliber (their frames' in-post filter reads
                   data/raw_verified/roster_gold_*.parquet — asserted by sha256 below).
  4/6. econ roster evidence  the 2026-08-09 verification sheet (840 rows, unchanged) PLUS
                   data/cal2026-10/roster_added_2026-10.csv (the 88 entries D3 added, with their
                   2026-09 verification evidence); same any-field / evidence_url rules.
  5. roster_people econ -> data/cal2026-10/roster_econ_verified_2026-10.parquet (920 + 88 = 1,008);
                   chem/math unchanged (roster_gold_*).
  7. panel_rows    the October frames (data/frames), cross-checked against the October build
                   reports' accounting.
  8. events_by_school  data/cal2026-10/events_{econ,chemistry,math_stats}_cal2026-10.csv (113/38/33).
  9. py_decomp     the October frames.
Run:    python3 analysis/paper/ledger_carried.py
"""
import csv
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from analysis.lib.paths import load_paths  # noqa: E402
from analysis.lib import canon  # noqa: E402
from analysis.paper import _m_checks  # noqa: E402

# The authoritative list of carried key-groups (every 08-16 ledger key NOT computed by partA).
CARRIED_KEYS = [
    "chem_units_nofwci_pct", "chem_units_structural_pct", "chem_units_genuine_pct",
    "math_units_nofwci_pct", "math_units_structural_pct", "math_units_genuine_pct",
    "chem_star_stock", "math_star_stock",
    "chem_centre_added", "math_centre_added",
    "econ_arc_evidence_people",
    "roster_people",
    "econ_fellow_evidence_rows",
    "panel_rows",
    "events_by_school_econ", "events_by_school_chem", "events_by_school_math",
    "chem_py_decomp", "math_py_decomp",
]

# key -> precise reason a group could not be re-derived from surviving sources.
# Empty: every carried group above has an October (cal2026-10) source. build() adds the keys of groups 3 and 4/6
# when the data in force does not match those sources (the R1 rosters) and writes them as the JSON's _unreproducible.
UNREPRODUCIBLE: dict[str, str] = {}
# the M run config: its pins name the R1 rosters and their no-research-centre twins (group 3's reason)
M_CONFIG = REPO_ROOT / "config" / "r1" / "M.json"


def _sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pinned_cal10(path: Path, key: str | None = None) -> Path:
    """Return `path` (a file under the cal root) only after its sha256 matches a MANIFEST: the cal
    root's MANIFEST.sha256 first, else the MANIFEST.sha256 of the file's own directory.
    Keys are repo-root-relative (`data/cal2026-10/...`); `key` overrides the key looked up (the
    _invalid_run2 MANIFEST records its files under the paths they were written to, one level up).
    R1 F7: root, MANIFEST and key come from analysis/lib/canon.py. In an M canon the MANIFEST is
    written from the files themselves ('<prefix>/...' keys), so the October alias `key` does not apply."""
    rel = (key if canon.mode() == "october" else None) or canon.key(path)
    for man in (canon.manifest("cal"), path.parent / "MANIFEST.sha256"):
        if not man.is_file():
            continue
        pins = dict((ln.split("  ", 1)[1].strip(), ln.split("  ", 1)[0])
                    for ln in man.read_text().splitlines() if ln.strip())
        if rel in pins:
            got = _sha(path)
            assert got == pins[rel], f"{path}: sha256 {got} != {man} pin {pins[rel]} ({rel})"
            return path
    raise AssertionError(f"{rel}: not pinned in {canon.key(canon.manifest('cal'))} nor in {path.parent}/MANIFEST.sha256")


def build() -> dict:
    import duckdb  # deferred so importing the module for the constants stays cheap

    P = load_paths()
    GOLD = P["legacy_v2_output"] / "multidisc_gold_2026-08-10" / "data"
    ROSTER_CSV = P["legacy_v2_output"] / "econ_roster_verify_2026-08-09" / "econ_roster_verified_all.csv"
    RAW = P["raw_verified"]
    FRAMES = P["frames"]
    CAL10 = P["cal"]   # R1 F7: the cal root from config (October data/cal2026-10, or an M canon's cal/)
    FIELDS = {"econ": "econ", "chem": "chemistry", "math": "math_stats"}
    # the October build reports (cross-checks for groups 3, 5 and 7)
    B_ECON = json.load(open(pinned_cal10(CAL10 / "frames_econ" / "build_report_econ920_2026-10.json")))
    B_CM = {d: json.load(open(pinned_cal10(CAL10 / f"frames_{f}" / f"build_report_{f}.json")))
            for d, f in (("chem", "chemistry"), ("math", "math_stats"))}

    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    N = {"_provenance": {}}
    unrep = dict(UNREPRODUCIBLE)   # plus this run's keys with no source in force (M: groups 3 and 4/6)

    def rec(key, val, src):
        N[key] = val
        N["_provenance"][key] = src

    # ---- 1. units_*_pct from the October g_yrebuild JSONs (cal2026-10) ----
    for d, f in (("chem", "chemistry"), ("math", "math_stats")):
        src = pinned_cal10(CAL10 / "yrebuild_chemmath" / f"g_yrebuild_{f}.json")
        na = json.load(open(src))["fwci_new_na"]
        share = 100 * na["units_na"] / na["units_total"]
        reasons = na["reasons_by_distinct_work"]
        excl = reasons["excluded_type"]
        other = sum(v for k, v in reasons.items() if k != "excluded_type")
        tag = f"{canon.key(src)} fwci_new_na"
        rec(f"{d}_units_nofwci_pct", round(share, 1), tag)
        rec(f"{d}_units_structural_pct", round(share * excl / (excl + other), 1), tag)
        rec(f"{d}_units_genuine_pct", round(share * other / (excl + other), 1), tag)

    # ---- 2. star_stock: October event set x the October star layer's chem/math `after_stock` ----
    # cal2026-10: D5 re-verified ECONOMICS stars only; chemistry and mathematics keep their event
    # tables byte for byte (events_{f}_cal2026-10.csv == events_{f}_cal2026-08-28.csv) and their
    # verdicts come from run 2 of pipeline/stars/caliber_2026-10/run_caliber.py, whose chem/math
    # rows are valid (its README; the economics rows of that run are void, hence the folder name).
    oct_restake = pinned_cal10(CAL10 / "_invalid_run2" / "restake_2026-10.csv",
                               key=canon.key(CAL10 / "restake_2026-10.csv"))
    fin = GOLD / "star_threshold_restake_final_2026-08-13.csv"
    fnx = GOLD / "fnfix_restake_2026-08-15.csv"
    calx = P["repo_root"] / "data" / "cal2026-08-28" / "restake_2026-08-28.csv"
    oct_mode = canon.mode() == "october"   # final review #4: the 08-28 stock cross-check is October-only
    for d, f in (("chem", "chemistry"), ("math", "math_stats")):
        ev = pinned_cal10(CAL10 / f"events_{f}_cal2026-10.csv")
        stocks = _m_checks.star_stocks(con, oct_restake, f)
        evset = [(a, int(y)) for a, y in con.execute(
            f"SELECT author_id, arrival_corrected FROM read_csv_auto('{ev}')").fetchall()]
        missing = [k for k in evset if k not in stocks]
        assert not missing, f"{d}: October events without an October restake stock: {missing}"
        vals = [stocks[k] for k in evset]
        # cross-check: the pre-October layered stocks (final + fnfix + 08-28), where mounted.
        # final review #4: October canon only. In M the stocks are the M restake's (new ACCEPT stars have
        # no 08-28 stock, KEEPs may move); the coverage assert above and the sha256 pin are its checks.
        if oct_mode and fin.is_file() and fnx.is_file():
            old = {}
            for a, y, s_ in con.execute(f"SELECT author_id, arrival, stock_after FROM read_csv_auto('{fin}') WHERE field='{f}'").fetchall():
                old[(a, int(y))] = int(s_)
            for src_ in (fnx, calx):
                for a, y, s_ in con.execute(f"SELECT author_id, arrival_true, after_stock FROM read_csv_auto('{src_}') WHERE field='{f}'").fetchall():
                    old[(a, int(y))] = int(s_)
            diff = [(k, old.get(k), stocks[k]) for k in evset if old.get(k) != stocks[k]]
            assert not diff, f"{d}: October restake stock differs from the 08-28 layered stock: {diff}"
        q25, med, q75 = con.execute(
            "SELECT quantile_disc(x,[0.25,0.5,0.75]) FROM (SELECT unnest($1::BIGINT[]) x)", [vals]).fetchone()[0]
        src_stock = f"{canon.key(oct_restake)} after_stock (chem/math rows, valid), events_{f}_cal2026-10.csv"
        if oct_mode:      # the October string, byte for byte; M ran no 08-28 cross-check (review #4)
            src_stock += " (equal to the 08-28 layered stocks)"
        rec(f"{d}_star_stock",
            {"q25": int(q25), "med": int(med), "q75": int(q75), "max": max(vals), "n": len(vals)},
            src_stock)

    # ---- 3. centre_added from prep_final_report.json ----
    # cal2026-10: the chem/math in-post filter reads the same roster parquets as before (unchanged)
    for d, f in (("chem", "chemistry"), ("math", "math_stats")):
        sp = B_CM[d]["october"]["inpost"]["spells"]
        assert sp["roster_sha256"] == _sha(RAW / f"roster_gold_{f}.parquet"), \
            f"{f}: the October in-post filter read another roster than roster_gold_{f}.parquet"
    prep = json.load(open(GOLD / "final" / "prep_final_report.json"))
    # M audit: the report counts the 2026-08-10 rosters. Its added_people is used only while the roster in
    # force has the same people and spells (October); otherwise the key has no source and is listed.
    cm_same = True
    for d, f in (("chem", "chemistry"), ("math", "math_stats")):
        pq = RAW / f"roster_gold_{f}.parquet"
        n_people, n_spells = _m_checks.roster_counts(con, pq)
        blk = prep["rosters"][f]
        if _m_checks.report_describes_roster(blk, n_people, n_spells):
            rec(f"{d}_centre_added", blk["added_people"], "prep_final_report.json rosters")
        else:
            cm_same = False
            # review 0: the key stays listed (whether the footnote prints the M number is the author's call),
            # and the reason says what the M no-centre roster pinned beside the roster in force gives
            pins = json.loads(M_CONFIG.read_text(encoding="utf-8")).get("pins") or {}
            nc = _m_checks.nocentre_roster(pq, pins, REPO_ROOT)
            why = (f"prep_final_report.json (2026-08-10) counts another {f} roster ({blk.get('people', 0):,} people, "
                   f"{blk.get('spells', 0):,} spells) than the one in force ({canon.key(pq)}: {n_people:,} people, "
                   f"{n_spells:,} spells). ")
            if nc is None:
                why += (f"{canon.key(M_CONFIG)} pins no no-research-centre roster beside the roster in force, so "
                        "no source in force marks the research-centre entries")
            else:
                n_nc = _m_checks.roster_counts(con, nc)[0]
                left = _m_checks.people_left_out(con, pq, nc)
                why += (f"The no-research-centre roster {canon.key(M_CONFIG)} pins beside it ({canon.key(nc)}: "
                        f"{n_nc:,} people) leaves out {left:,} of those {n_people:,} people; whether the footnote "
                        "prints that number is the author's call")
            unrep[f"{d}_centre_added"] = why

    # ---- 4./6. econ roster evidence: arc.gov.au urls; fellow/DECRA rows ----
    # cal2026-10 (D3): the October roster = the 920 entries verified in 2026-08-09 (unchanged rows,
    # evidence in the 2026-08-09 verification sheet) + 88 entries added from the 2026-09 two-round
    # check (evidence in roster_added_2026-10.csv). Same rules applied to both evidence sheets.
    added_csv = pinned_cal10(CAL10 / "roster_added_2026-10.csv")
    added_rd = csv.DictReader(open(added_csv))
    added = list(added_rd)
    # M audit: the rules need the evidence columns of October's added sheet. R1's added sheet is a spell table
    # with none, and the 2026-08-09 sheet predates the roster in force, so the two keys have no source.
    if _m_checks.added_sheet_has_evidence(added_rd.fieldnames):
        rows = list(csv.DictReader(open(ROSTER_CSV)))
        assert len(added) == 88, f"roster_added_2026-10.csv has {len(added)} rows, the merge report says 88"
        def is_fellow(r):
            return any(("fellow" in str(v).lower()) or ("decra" in str(v).lower()) for v in r.values())
        arc_people = {r["author_id"] for r in rows + added if "arc.gov.au" in (r.get("evidence_url") or "")}
        rec("econ_arc_evidence_people", len(arc_people),
            f"{ROSTER_CSV.name} + roster_added_2026-10.csv: evidence_url contains arc.gov.au")
        fellow = sum(1 for r in rows if is_fellow(r)) + sum(1 for r in added if is_fellow(r))
        rec("econ_fellow_evidence_rows", fellow,
            f"{ROSTER_CSV.name} ({sum(1 for r in rows if is_fellow(r))}) + roster_added_2026-10.csv "
            f"({sum(1 for r in added if is_fellow(r))}): any field contains fellow/DECRA (ci)")
    else:
        why = (f"{canon.key(added_csv)} has no evidence columns (no evidence_url): the added roster in force "
               "is a spell table, and the 2026-08-09 evidence sheet predates that roster")
        unrep["econ_arc_evidence_people"] = why
        unrep["econ_fellow_evidence_rows"] = why

    # ---- 5. roster_people: distinct people per verified roster parquet ----
    def people(pq):
        return con.execute(f"SELECT count(DISTINCT author_id) FROM parquet_scan('{pq}')").fetchone()[0]
    roster_oct = pinned_cal10(CAL10 / "roster_econ_verified_2026-10.parquet")
    n_econ, n_econ_rows = _m_checks.roster_counts(con, roster_oct)
    pool = B_ECON["october"]["regeneration"]["roster_pool"]   # the roster the October econ build read
    # M audit: the pool counts rows (one per spell; R1 has several per person); the ledger records people
    assert pool["source_sha256"] == _sha(roster_oct) and pool["rows_in"] == n_econ_rows, \
        f"econ roster: {n_econ_rows} rows vs the October build's roster pool {pool['rows_in']}"
    rec("roster_people",
        {"econ": n_econ,
         "chem": people(RAW / "roster_gold_chemistry.parquet"),
         "math": people(RAW / "roster_gold_math_stats.parquet")},
        f"roster parquets, distinct author_id (econ: {canon.key(roster_oct)}; "
        f"chem/math: {canon.key(RAW)}/roster_gold_*.parquet" + (", unchanged in October)" if cm_same else ")"))

    # ---- 7. panel_rows: [P1 frame, P2 becoming, P3 pairs_slim] row counts ----
    def n_csv(p):
        return con.execute(f"SELECT count(*) FROM read_csv_auto('{p}')").fetchone()[0]
    def n_parquet(p):
        return con.execute(f"SELECT count(*) FROM parquet_scan('{p}')").fetchone()[0]
    pr = {}
    for d, f in (("econ", "econ"), ("chem", "chemistry"), ("math", "math_stats")):
        pr[d] = [n_csv(FRAMES / f"p1_frame_{f}.csv"),
                 n_csv(FRAMES / f"p2_becoming_{f}.csv"),
                 n_parquet(FRAMES / f"p3_slim_{f}.parquet")]
    # cal2026-10: the October build reports' own accounting must agree
    acc_e = B_ECON["october"]["accounting"]
    want = {"econ": [acc_e["rows"]["pre_y_frame_rows"], acc_e["p2_rows"], acc_e["slim"]["rows"]]}
    for d in ("chem", "math"):
        a = B_CM[d]["accounting"]
        want[d] = [a["p1_frame"]["rows_new"], a["p2_becoming"]["rows_new"], a["slim"]["slim"]["rows"]]
    assert pr == want, f"panel_rows {pr} != October build reports {want}"
    rec("panel_rows", pr, "data/frames p1_frame/p2_becoming/p3_slim row counts (October; == the "
        "frames_*/build_report accounting)")

    # ---- 8. events_by_school from the October event tables (cal2026-10: econ 113 — D5 dropped
    # three events whose star fell below the top 10% after cleaning, and A5091326353's event keeps its
    # year under the corrected id; chemistry 38 / mathematics 33, byte-identical to 08-28) ----
    def by_school(pairs):
        d = {}
        for s_, y in pairs:
            d.setdefault(s_, []).append(int(y))
        return {k: sorted(v) for k, v in sorted(d.items())}
    econ_ev = pinned_cal10(CAL10 / "events_econ_cal2026-10.csv")
    # the October econ table carries free-text evidence columns duckdb's sniffer rejects: csv module
    econ_pairs = [(r["school"], r["arrival_year"]) for r in csv.DictReader(open(econ_ev, newline="", encoding="utf-8"))]
    # R1 F9/F7: the count is the run's (October config/r1/counts_B0.json = 113; M <canon>/cal/counts.json)
    n_econ_events = canon.counts()["events"]["econ"]
    assert len(econ_pairs) == n_econ_events, \
        f"events_econ_cal2026-10.csv has {len(econ_pairs)} events, not {n_econ_events}"
    rec("events_by_school_econ", by_school(econ_pairs), canon.key(econ_ev))
    for d, f in (("chem", "chemistry"), ("math", "math_stats")):
        ev = pinned_cal10(CAL10 / f"events_{f}_cal2026-10.csv")
        pairs = con.execute(f"SELECT school, arrival_corrected FROM read_csv_auto('{ev}')").fetchall()
        rec(f"events_by_school_{d}", by_school(pairs), canon.key(ev))

    # ---- 9. py_decomp from the P1 frames ----
    for d, f in (("chem", "chemistry"), ("math", "math_stats")):
        fp = FRAMES / f"p1_frame_{f}.csv"
        r = con.execute(f"""SELECT count(*),
            sum(CASE WHEN fwci_frac IS NOT NULL THEN 1 ELSE 0 END),
            sum(CASE WHEN fwci_frac IS NULL AND pub_count IS NULL THEN 1 ELSE 0 END),
            sum(CASE WHEN fwci_frac IS NULL AND pub_count IS NOT NULL THEN 1 ELSE 0 END),
            sum(CASE WHEN pub_count=0 AND fwci_frac IS NULL THEN 1 ELSE 0 END)
            FROM read_csv_auto('{fp}')""").fetchone()
        rec(f"{d}_py_decomp",
            {"rows": int(r[0]), "y_val": int(r[1]), "empty_no_record": int(r[2]),
             "genuine_missing": int(r[3]), "pub0_na": int(r[4])},
            f"{fp.name} fwci_frac/pub_count decomposition")

    derived = set(N) - {"_provenance"}
    assert derived | set(unrep) == set(CARRIED_KEYS) and not derived & set(unrep), (
        f"coverage drift: extra={derived - set(CARRIED_KEYS)} "
        f"missing={set(CARRIED_KEYS) - derived - set(unrep)}")
    if unrep:
        N["_unreproducible"] = unrep
    return N


def main():
    P = load_paths()
    out = P["output"] / "paper" / "data_numbers_carried.json"
    N = build()
    unrep = N.get("_unreproducible", {})
    out.parent.mkdir(parents=True, exist_ok=True)
    json.dump(N, open(out, "w"), ensure_ascii=False, indent=1)
    for k, v in N.items():
        if k.startswith("_"):
            continue
        print(k, "=", json.dumps(v, ensure_ascii=False)[:150])
    print(f"wrote {out}  ({len(N) - 1 - ('_unreproducible' in N)} keys derived, "
          f"{len(unrep)} unreproducible)")


if __name__ == "__main__":
    main()
