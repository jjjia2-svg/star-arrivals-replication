#!/usr/bin/env python3
"""ledger_main.py — the main paper numbers ledger (the keys make_numbers_2026-08-16_partA.py computes).

Computes, per discipline (econ/chem/math) from the P1 analysis frames:
  {d}_relations, {d}_persons, {d}_events, {d}_zero_roster_events,
  {d}_dose_bins_pct, {d}_dose_na_relations, {d}_balance, {d}_q_output, {d}_q_dose
plus (econ only, needs the coupling-dose column): econ_share_any_ref, econ_share_any_subfield
plus, from g_econ_rebuild.json / g_yrebuild_{chemistry,math_stats}.json:
  econ_works_nofwci_pct, econ_works_structural_pct, econ_works_genuine_pct,
  chem_yrebuild_keys, math_yrebuild_keys, econ_py_decomp

These are exactly the keys the thesis's make_numbers_2026-08-16_partA.py writes into
data_numbers_2026-08-16.json (whose 2026-08-28 caliber successor, data_numbers_2026-08-28.json,
is built by the thesis's make_numbers_2026-08-28.py from THIS script's output plus
ledger_carried.py's) — NOT the full file, which also carries forward ~18 key-groups
from a vanished 08-14 generator script (chem/math_units_*_pct, star_stock, centre_added,
roster_people, panel_rows, events_by_school_*, ...). Those are re-derived separately
(analysis/paper/ledger_carried.py, a different task) and merged on top; this script writes
only what it computes.

Reads (since cal2026-10, 2026-09-23; nothing from the legacy tree any more):
  data/frames/p1_frame_{econ,chemistry,math_stats}.csv   (the October frames; byte copies of
    data/cal2026-10/frames_{econ,chemistry,math_stats}/p1_frame_*.csv, pinned in data/MANIFEST.sha256)
  data/cal2026-10/frames_econ/g_econ_rebuild_econ.json                    (was legacy g_econ_rebuild.json)
  data/cal2026-10/yrebuild_chemmath/g_yrebuild_{chemistry,math_stats}.json (was legacy fnfix g_yrebuild_*)
  data/cal2026-10/frames_econ/{inpost_report_econ,build_report_econ920_2026-10}.json,
  data/cal2026-10/frames_{chemistry,math_stats}/build_report_*.json      (cross-checks only)
  data/cal2026-10/new_numbers/data_numbers_new_2026-10.json               (the six NEW key-groups)
Writes:
  output/paper/data_numbers_main.json

Port note: verbatim port of thesis_report/scripts/make_numbers_2026-08-16_partA.py (2026-08-16
thesis copy). Every computation line is unchanged; only input/output paths are re-derived from
analysis.lib.paths.load_paths() instead of the thesis's os.chdir + relative paths, and the
carry-forward merge (which wrote the other ~18 key-groups into the same file) is NOT ported here.
Ported 2026-08-24 for the star_arrivals_replication repo (M2/T2). The computation lives in
build()/main() (M2 milestone fix wave), so importing the module for COMPUTED_KEYS is free of
side effects, mirroring ledger_carried.py.
cal2026-10 (2026-09-23, the October caliber is the canon): the frames under data/frames are the
October frames (113 / 38 / 33 events; network channel = verified-roster members in post at arrival,
design D1-D4), so every frame-computed key moves with them. The two non-frame inputs move to their
October counterparts, each sha256-checked before it is read:
  g_econ_rebuild.json          -> data/cal2026-10/frames_econ/g_econ_rebuild_econ.json
                                  (pinned in data/cal2026-10/MANIFEST.sha256)
  g_yrebuild_{chem,math}.json  -> data/cal2026-10/yrebuild_chemmath/g_yrebuild_{chemistry,math_stats}.json
                                  (the October chain's own reports, frozen 2026-09-23; see that README)
The frame-computed counts are cross-checked against the October build reports (econ
frames_econ/inpost_report_econ.json + build_report_econ920_2026-10.json; chem/math
frames_{field}/build_report_{field}.json `accounting`): a disagreement stops the run. The econ
check subtracts the incumbent-star drop the build report records, because the in-post report
predates it (econ_report_expectations; with October's reports every delta is zero).
Six NEW key-groups per discipline (the supervisor's 2026-09-21 round), read from the pinned ledger
data/cal2026-10/new_numbers/data_numbers_new_2026-10.json (analysis/paper/ledger_new_2026_10.py;
it needs the data disk, so its frozen output is read here after checking that it was computed on
exactly these frames): {d}_subfields_in_dose_support, {d}_subfields_in_dose_support_own_field,
{d}_own_field_subfields_in_extraction_table, {d}_share_onehop_network_channel,
{d}_share_onehop_all, {d}_n_incumbent_event_pairs.
Run:  python3 analysis/paper/ledger_main.py
"""
import hashlib, json, math, statistics, sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from analysis.lib.paths import load_paths
from analysis.lib import canon

_DISCIPLINES = ("econ", "chem", "math")
_PER_DISCIPLINE_KEYS = ("relations", "persons", "events", "zero_roster_events",
                         "dose_bins_pct", "dose_na_relations", "balance", "q_output", "q_dose")
# cal2026-10: the two numbers the supervisor's 2026-09-21 round asked for (one-hop share, dose-support
# subfields), per discipline, from the pinned new-numbers ledger (see the module docstring).
NEW_2026_10_KEYS = ("subfields_in_dose_support", "subfields_in_dose_support_own_field",
                    "own_field_subfields_in_extraction_table", "share_onehop_network_channel",
                    "share_onehop_all", "n_incumbent_event_pairs")
_FIELD = {"econ": "econ", "chem": "chemistry", "math": "math_stats"}
COMPUTED_KEYS = [f"{d}_{k}" for d in _DISCIPLINES for k in _PER_DISCIPLINE_KEYS] + [
    "econ_share_any_ref", "econ_share_any_subfield",
    "econ_works_nofwci_pct", "econ_works_structural_pct", "econ_works_genuine_pct",
    "chem_yrebuild_keys", "math_yrebuild_keys",
    "econ_py_decomp",
] + [f"{d}_{k}" for d in _DISCIPLINES for k in NEW_2026_10_KEYS]


def _sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pinned_cal10(path: Path) -> Path:
    """Return `path` (a file under the cal root) only after its sha256 matches a MANIFEST: the cal
    root's MANIFEST.sha256 first, else the MANIFEST.sha256 of the file's own directory.
    R1 F7: root, MANIFEST and key come from analysis/lib/canon.py - in October the repo-root-relative
    keys (`data/cal2026-10/...`) exactly as before; in an M canon the '<prefix>/...' keys."""
    rel = canon.key(path)
    for man in (canon.manifest("cal"), path.parent / "MANIFEST.sha256"):
        if not man.is_file():
            continue
        pins = dict((ln.split("  ", 1)[1].strip(), ln.split("  ", 1)[0])
                    for ln in man.read_text().splitlines() if ln.strip())
        if rel in pins:
            got = _sha(path)
            assert got == pins[rel], f"{rel}: sha256 {got} != {man} pin {pins[rel]}"
            return path
    raise AssertionError(f"{rel}: not pinned in {canon.key(canon.manifest('cal'))} nor in {path.parent}/MANIFEST.sha256")


def econ_report_expectations(inpost: dict, b_econ: dict) -> dict:
    """What the econ P1 frame must hold according to the econ build reports: {"want": {econ_relations,
    econ_persons, econ_events}, "rows": pre-y frame rows}. Asserts the reports agree with each other.

    The in-post report (`inpost`) is written BEFORE the incumbent-star rule
    (a new M star who is an in-post colleague loses every row and relation, all events), the build
    report's accounting AFTER it. The drop record (`october.incumbent_stars`, its accounting deltas
    `relationships.relations_dropped_incumbent_is_star_r1` and `rows.minus_incumbent_is_star_r1`) is
    therefore subtracted, after checking that it is self-consistent. It keys off the counters' presence,
    not the canon mode: October's reports carry none of them, every delta is 0 / [], and the checks are
    the October equalities (822 persons / 113 events / 6643 relations / 73073 rows)."""
    oct_b = b_econ["october"]
    acc = oct_b["accounting"]
    rel_e = acc["relationships"]
    ist = oct_b.get("incumbent_stars") or {}
    d_rel = rel_e.get("relations_dropped_incumbent_is_star_r1", 0)
    d_rows = -acc["rows"].get("minus_incumbent_is_star_r1", 0)
    gone_p = list(ist.get("persons", []))
    # the report's own drop record is self-consistent
    assert d_rel == ist.get("relations_dropped", 0) == ist.get("relationships_lines_dropped", d_rel), \
        f"econ incumbent-star drop: relations {d_rel} (accounting) vs {ist.get('relations_dropped', 0)} / " \
        f"{ist.get('relationships_lines_dropped', d_rel)} (incumbent_stars)"
    assert d_rows == ist.get("rows_dropped", 0), \
        f"econ incumbent-star drop: rows {d_rows} (accounting) vs {ist.get('rows_dropped', 0)} (incumbent_stars)"
    assert (d_rel == 0) == (d_rows == 0) == (not gone_p), \
        f"econ incumbent-star drop: relations {d_rel}, rows {d_rows}, persons {gone_p} disagree"
    # events the drop emptied: no relation left in the final per-event accounting
    emptied = [e for e in ist.get("events", []) if acc["per_event"].get(e, {}).get("relations", 0) == 0]
    assert set(emptied) <= set(inpost["per_event"]), \
        f"econ incumbent-star drop emptied events the in-post report does not hold: {sorted(set(emptied) - set(inpost['per_event']))}"
    # relations
    assert inpost["relations_by_class"]["kept"] == rel_e["after_post_filter_total"] + d_rel
    # rows
    rows_want = inpost["rows_by_class"]["kept"] - d_rows
    assert rows_want == acc["rows"]["pre_y_frame_rows"], \
        f"econ in-post rows {inpost['rows_by_class']['kept']} - incumbent-star rows {d_rows} != " \
        f"pre_y_frame_rows {acc['rows']['pre_y_frame_rows']}"
    want = {"econ_relations": {"total": rel_e["after_post_filter_total"], **rel_e["after_post_filter_by_channel"]},
            "econ_persons": inpost["persons_by_class"]["kept"] - len(gone_p),
            "econ_events": len(inpost["per_event"]) - len(emptied)}
    return {"want": want, "rows": rows_want}


def build() -> dict:
    import duckdb  # deferred so importing the module for the constants stays cheap

    P = load_paths()
    CAL10 = P["cal"]   # R1 F7: the cal root from config (October data/cal2026-10, or an M canon's cal/)
    # cal2026-10: the October counterparts of the legacy g_econ_rebuild.json / g_yrebuild_*.json
    G_ECON = pinned_cal10(CAL10 / "frames_econ" / "g_econ_rebuild_econ.json")
    G_Y = {f: pinned_cal10(CAL10 / "yrebuild_chemmath" / f"g_yrebuild_{f}.json")
           for f in ("chemistry", "math_stats")}

    # the three P1 frames: repo copies (sha256-identical to the legacy originals — see port note above)
    FR = {"econ": str(P["frames"] / "p1_frame_econ.csv"),
          "chem": str(P["frames"] / "p1_frame_chemistry.csv"),
          "math": str(P["frames"] / "p1_frame_math_stats.csv")}

    con = duckdb.connect(); con.execute("PRAGMA threads=8"); con.execute("PRAGMA memory_limit='14GB'")
    N = {"_provenance": {}}
    def rec(key, val, src):
        N[key] = val; N["_provenance"][key] = src

    # ---- A/B/C: relations, channels, zero-roster events, dose bins, balance ----
    for d, fp in FR.items():
        con.execute(f"CREATE OR REPLACE TEMP TABLE f AS SELECT * FROM read_csv_auto('{fp}')")
        rel = con.execute("""SELECT channel, count(*) FROM (
            SELECT DISTINCT incumbent_person_id, event_id, channel FROM f) GROUP BY 1 ORDER BY 1""").fetchall()
        ch = {k: v for k, v in rel}
        tot = sum(ch.values())
        ppl, ev = con.execute("SELECT count(DISTINCT incumbent_person_id), count(DISTINCT event_id) FROM f").fetchone()
        rec(f"{d}_relations", {"total": tot, **ch}, fp)
        rec(f"{d}_persons", ppl, fp); rec(f"{d}_events", ev, fp)
        zero = con.execute("""SELECT count(*) FROM (
            SELECT event_id, sum(CASE WHEN channel IN ('dept_only','both') THEN 1 ELSE 0 END) nd
            FROM (SELECT DISTINCT incumbent_person_id, event_id, channel FROM f) GROUP BY 1) WHERE nd=0""").fetchone()[0]
        rec(f"{d}_zero_roster_events", zero, fp)
        bins = con.execute("""SELECT LEAST(CAST(FLOOR(dose_topic*10) AS INT),9) b, count(*)
            FROM (SELECT DISTINCT incumbent_person_id, event_id, dose_topic FROM f WHERE dose_topic IS NOT NULL)
            GROUP BY 1 ORDER BY 1""").fetchall()
        tb = sum(v for _, v in bins)
        rec(f"{d}_dose_bins_pct", {int(b): round(100*v/tb, 1) for b, v in bins}, fp)
        rec(f"{d}_dose_na_relations", tot - tb, fp)
        # Balance (replicates the economics definition: grouping by the positive-dose median)
        med = con.execute("SELECT median(dose_topic) FROM (SELECT DISTINCT incumbent_person_id,event_id,dose_topic FROM f WHERE dose_topic>0)").fetchone()[0]
        bal = {}
        for var, sql in (("pub_pre", "avg(pub_count)"), ("y_pre", "avg(fwci_frac)"), ("age_gap", "any_value(age_gap)")):
            rows = con.execute(f"""
              SELECT CASE WHEN dose_topic>{med} THEN 'hi' ELSE 'lo' END g, incumbent_person_id||event_id rel, {sql} v
              FROM f WHERE post=false AND dose_topic IS NOT NULL {"AND fwci_frac IS NOT NULL" if var=="y_pre" else ""}
              GROUP BY 1,2""").fetchall()
            hi = [v for g, _, v in rows if g == "hi" and v is not None]; lo = [v for g, _, v in rows if g == "lo" and v is not None]
            if len(hi) > 2 and len(lo) > 2:
                mh, ml = statistics.mean(hi), statistics.mean(lo)
                sd = math.sqrt((statistics.pstdev(hi)**2 + statistics.pstdev(lo)**2) / 2)
                bal[var] = {"hi": round(mh, 3), "lo": round(ml, 3), "std_diff": round((mh-ml)/sd, 3) if sd else None,
                            "n_hi": len(hi), "n_lo": len(lo)}
        rec(f"{d}_balance", {"dose_median_positive": round(med, 3), **bal}, fp+" (正剂量中位分组，pre窗，关系级)")
        # Quantiles: output / dose
        q = lambda col, cond="": con.execute(f"SELECT quantile_cont({col},[0.25,0.5,0.75,0.95]), max({col}) FROM f WHERE {col} IS NOT NULL {cond}").fetchone()
        qs, mx = q("fwci_frac"); rec(f"{d}_q_output", {"q": [round(x, 2) for x in qs], "max": round(mx, 1)}, fp)
        qs2, mx2 = con.execute("SELECT quantile_cont(dose_topic,[0.25,0.5,0.75,0.95]), max(dose_topic) FROM (SELECT DISTINCT incumbent_person_id,event_id,dose_topic FROM f WHERE dose_topic IS NOT NULL)").fetchone()
        rec(f"{d}_q_dose", {"q": [round(x, 3) for x in qs2], "max": round(mx2, 3)}, fp)
        # Coupling-dose share (economics has a coupling column)
        if d == "econ":
            cp = con.execute("""SELECT
              sum(CASE WHEN dose_coupling_baseline>0 THEN 1 ELSE 0 END),
              sum(CASE WHEN dose_topic>0 THEN 1 ELSE 0 END), count(*)
              FROM (SELECT DISTINCT incumbent_person_id,event_id,dose_coupling_baseline,dose_topic FROM f)""").fetchone()
            rec("econ_share_any_ref", round(100*cp[0]/cp[2], 1), fp)
            rec("econ_share_any_subfield", round(100*cp[1]/cp[2], 1), fp)

    # ---- E: FWCI NA decomposition (works level) ----
    ge = json.load(open(G_ECON))
    mw = ge["main_population"]; pw = ge["patch"]
    w_tot = mw["distinct_works"] + pw["distinct_works"]
    w_ex = mw["new_fwci_na_reasons_by_work"]["excluded_type"] + pw["new_fwci_na_reasons"]["excluded_type"]
    w_ms = sum(v for k, v in mw["new_fwci_na_reasons_by_work"].items() if k != "excluded_type") + sum(v for k, v in pw["new_fwci_na_reasons"].items() if k != "excluded_type")
    src_e = canon.key(G_ECON)
    rec("econ_works_nofwci_pct", round(100*(w_ex+w_ms)/w_tot, 1), src_e)
    rec("econ_works_structural_pct", round(100*w_ex/w_tot, 1), src_e)
    rec("econ_works_genuine_pct", round(100*w_ms/w_tot, 1), src_e)
    for d, f in (("chem", "chemistry"), ("math", "math_stats")):
        gj = json.load(open(G_Y[f]))
        assert gj["frame_persons"] == N[f"{d}_persons"], \
            f"{f}: g_yrebuild frame_persons {gj['frame_persons']} != frame persons {N[f'{d}_persons']}"
        rec(f"{d}_yrebuild_keys", [k for k in gj][:10], canon.key(G_Y[f]))

    # ---- F: person-year NA vs empty structure (econ, frame-based since the 2026-08-28 freeze) ----
    # Freeze-wave Task 8: the transition block in g_econ_rebuild.json describes the PRE-caliber
    # frame (119,405 rows) and has no caliber counterpart, so mixing it with the promoted frame's
    # row count would put two calibers in one ratio. The decomposition is instead computed from
    # the frame itself, exactly as ledger_carried.py does for chemistry/mathematics — a derivation
    # MEASURED equivalent on the pre-caliber frame before the switch: frame-based
    # {empty 18,361 / genuine 5,429 / observed 95,615} == transition-based
    # {row_na 18,361 / na2na+val2na+py_missing 5,429 / val2val+na2val+zero_fill 88,255+7,360}.
    # (The y_val/zero split inside "observed" is not derivable from the frame and is not needed:
    # every consumer reads observed = y_val + zero.)
    r = con.execute(f"""SELECT count(*),
        sum(CASE WHEN fwci_frac IS NOT NULL THEN 1 ELSE 0 END),
        sum(CASE WHEN fwci_frac IS NULL AND pub_count IS NULL THEN 1 ELSE 0 END),
        sum(CASE WHEN fwci_frac IS NULL AND pub_count IS NOT NULL THEN 1 ELSE 0 END),
        sum(CASE WHEN pub_count=0 AND fwci_frac IS NULL THEN 1 ELSE 0 END)
        FROM read_csv_auto('{FR["econ"]}')""").fetchone()
    rec("econ_py_decomp",
        {"rows": int(r[0]), "y_val": int(r[1]), "empty_no_record": int(r[2]),
         "genuine_missing": int(r[3]), "pub0_na": int(r[4])},
        f"{FR['econ']} fwci_frac/pub_count decomposition (frame-based; measured equivalent to the "
        "pre-caliber transition block before the 2026-08-28 caliber switch)")

    # ---- cal2026-10: frame counts vs the October build reports (a disagreement stops the run) ----
    inpost = json.load(open(pinned_cal10(CAL10 / "frames_econ" / "inpost_report_econ.json")))
    b_econ = json.load(open(pinned_cal10(CAL10 / "frames_econ" / "build_report_econ920_2026-10.json")))
    # the in-post report predates the incumbent-star drop; see econ_report_expectations
    exp = econ_report_expectations(inpost, b_econ)
    want = exp["want"]
    assert r[0] == exp["rows"], \
        f"econ P1 rows {r[0]} != October in-post report"
    for d, f in (("chem", "chemistry"), ("math", "math_stats")):
        acc = json.load(open(pinned_cal10(CAL10 / f"frames_{f}" / f"build_report_{f}.json")))["accounting"]["relationships"]
        want[f"{d}_relations"] = {"total": acc["relations_new"], **acc["by_channel_new"]}
        want[f"{d}_persons"] = acc["persons_new"]
        want[f"{d}_events"] = acc["events_new"]
    for k, v in want.items():
        assert N[k] == v, f"{k}: frame-derived {N[k]} != October build report {v}"

    # ---- cal2026-10 NEW keys: one-hop share + dose-support subfields (supervisor, 2026-09-21) ----
    new_path = pinned_cal10(CAL10 / "new_numbers" / "data_numbers_new_2026-10.json")
    new = json.load(open(new_path))
    for d, f in _FIELD.items():
        blk = new[f]
        # computed on exactly these frames: same P1 frame bytes, same relations by channel
        assert blk["_inputs"]["p1_sha256"] == _sha(FR[d]), f"{f}: new-numbers ledger was computed on another P1 frame"
        assert blk["n_incumbent_event_pairs"] == N[f"{d}_relations"]["total"]
        assert blk["channel_counts"] == {k: v for k, v in N[f"{d}_relations"].items() if k != "total"}
        assert blk["n_incumbents"] == N[f"{d}_persons"] and blk["n_events"] == N[f"{d}_events"]
        for k in NEW_2026_10_KEYS:
            rec(f"{d}_{k}", blk[k], f"{canon.key(new_path)} {f}.{k} "
                f"(analysis/paper/ledger_new_2026_10.py; P1 frame sha256 checked equal)")

    assert set(N) - {"_provenance"} == set(COMPUTED_KEYS), \
        f"N vs COMPUTED_KEYS drift: extra={set(N)-{'_provenance'}-set(COMPUTED_KEYS)} missing={set(COMPUTED_KEYS)-set(N)}"
    return N


def main():
    P = load_paths()
    out_json = P["output"] / "paper" / "data_numbers_main.json"
    N = build()
    out_json.parent.mkdir(parents=True, exist_ok=True)
    json.dump(N, open(out_json, "w"), ensure_ascii=False, indent=1)
    for k, v in N.items():
        if k == "_provenance":
            continue
        print(k, "=", json.dumps(v, ensure_ascii=False)[:150])
    print("wrote", out_json)


if __name__ == "__main__":
    main()
