#!/usr/bin/env python3
"""ledger_funnel.py — snapshot/benchmark funnel counts + pre-topic-cut pair pools.

Covers the appendix numbers that live in NEITHER thesis ledger:
appendix_funnel.tex steps 1-3 and the pre-topic-cut pool note, plus appendix_pipeline.tex's
snapshot/benchmark rows. Nothing here is ever recomputed by scanning the 510M-row snapshot:
every value is read from a surviving pipeline manifest, and equality with the thesis appendix
value is ASSERTED (THESIS_VALUES below) — a mismatch is a finding to report, not a tuning
target. A count with no surviving manifest source would be listed in UNREPRODUCIBLE (with the
reason) and left out of the JSON; as of this writing that dict is empty — all six key-groups
have manifest sources.

key -> source (all read-only, under legacy_v2_output)
-----------------------------------------------------
works_snapshot          fwci_baseline_fullsnapshot_2026-08-09/data/scan_manifest.json
                        `total_lines_read` (cross-checked == `manifest_record_count` and
                        == gate_a_reconcile.json's lines_read/manifest_record_count)
works_benchmarkable     scan_manifest.json `sum_work_count` (works with subfield+year+type,
                        i.e. assignable to a benchmark cell; gate_a agrees)
benchmark_cells         scan_manifest.json `n_cells` (gate_a agrees)
works_articles_reviews  gate_a_reconcile.json `work_type_breakdown_of_cellable`: works of
                        type 'article' (254,202,810) + 'review' (4,197,419) = 258,400,229 —
                        the publication-count restriction of funnel step 3
pairs_pool_pre_cut      p3_topicpair_2026-08-17/data/dose_context.json `{field}.pairs_total`
                        (cross-checked == attrition.csv `pairs_panel`)
pairs_dropped_no_dose   p3_topicpair_2026-08-17/data/attrition.csv `dropped_no_dose`
                        (cross-checked == pairs_total - pairs_both_dose in dose_context.json)

R3 (2026-09-10) — four sec2_data.tex numbers that had no key anywhere (H6: script first, pin
second). Sources are frozen repo files except (2), whose only on-disk record is a legacy audit:
openalex_subfields      data/fwci/fwci_baseline_pop_full.parquet: count(DISTINCT subfield_id) of
                        the full-snapshot cell table (cross-checked == the same count in
                        fwci_expected_fullsnapshot_2026-08-09.parquet). OpenAlex documents 252
                        subfields as the third of its four topic levels
                        (https://docs.openalex.org/api-entities/topics); the frozen table shows
                        every one of them occurs in the snapshot.
snapshot_release_date   data/fwci/scan_manifest.json `snapshot_manifest_date` (cross-checked ==
                        gate_a_reconcile.json's) — the OpenAlex release the whole project reads.
u1_universe             the U1 extraction's works/authors table sizes and their share of the
                        snapshot (sec2 footnote "10.5 million authors"; an internal 2026-08-09 code audit
                        of the FWCI design, not shipped). The U1
                        run_manifest itself sits on the data disk
                        (<ssd_root>/derived/u1_edges_full_2026-07-05/_manifest/, not mounted
                        here); the surviving on-disk record is the read-only legacy
                        multiplex_pipeline/_handoff_2026-07-05_hist_roster/step0_review/
                        a fact-check sheet (legacy record, not shipped), the 2026-07-05 step-0 audit that
                        re-verified the run_manifest row counts item by item (rows "U1 row counts of the ten tables"
                        and "reconciliation statement"). Parsed by regex; the reconcile identity it records
                        (expected = kept + skipped + failed) is asserted against the frozen
                        scan_manifest's works_snapshot, which ties the legacy record to the
                        repo's own frozen count. Read-only, never edited.
roster_spell_max_start  data/raw_verified/roster_econ_verified.parquet,
                        roster_gold_chemistry.parquet, roster_gold_math_stats.parquet (the
                        rosters the frame builder reads; tools/import_frozen.py maps the gold
                        pair from multidisc_gold_2026-08-10/data/fnfix/): max(year_start) per
                        discipline. Cross-check asserted on roster_chemmath_verified.parquet
                        (every verified chem/math spell): no chemistry spell starts in 2024
                        and no math_stats spell starts in 2021-2024, so the sec2 sentence holds
                        in the wider verified roster too, not only in the frame inputs.

cal2026-10 (2026-09-23, the October caliber is the canon). Steps 1-3, the subfield count, the
snapshot date and the U1 universe describe the snapshot and the extraction, which the October
caliber does not touch: same sources, same values. roster_spell_max_start reads the October
economics roster (data/cal2026-10/roster_econ_verified_2026-10.parquet, 920 + 88 entries,
sha256-pinned) — chemistry and mathematics rosters are unchanged. The two pre-topic-cut pair-pool
groups (pairs_pool_pre_cut, pairs_dropped_no_dose) have NO October counterpart and are declared in
UNREPRODUCIBLE: their only producer is the full p3_topicpair dose build of 2026-08-17 (its
dose_context.json / attrition.csv, built on the 2026-08-22 event set), and the October Panel 3
sweep ran the lb stage only (data/cal2026-10/frames_afar/afar_run_report.json: lb_counts /
lb_manifest / lb_tau_profile, no pool accounting). Neither group is printed anywhere in the thesis
or the 2026-09-13 draft (the appendix note that quoted them was removed on 2026-08-30).

P3 rows 394,221 (funnel step 9) is NOT produced here — it is `econ.rows` in the p3afar
ledger (analysis/paper/ledger_p3afar.py); the sentinel wires the appendix claim to that key.

Writes: output/paper/data_numbers_funnel.json
Run:    python3 analysis/paper/ledger_funnel.py
"""
import csv
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from analysis.lib.paths import load_paths  # noqa: E402
from analysis.lib import canon  # noqa: E402
from analysis.paper import _m_checks  # noqa: E402

FIELDS = ("econ", "chemistry", "math_stats")

FUNNEL_KEYS = [
    "works_snapshot",
    "works_benchmarkable",
    "works_articles_reviews",
    "benchmark_cells",
    "pairs_pool_pre_cut",
    "pairs_dropped_no_dose",
    # R3 (2026-09-10): the four sec2 numbers that had no source
    "openalex_subfields",
    "snapshot_release_date",
    "u1_universe",
    "roster_spell_max_start",
]

# The legacy audit record that carries the U1 extraction's table sizes (see the docstring).
U1_FACT_SHEET = ("_handoff_2026-07-05_hist_roster/step0_review/"
                 "事实速查表_实测复核_2026-07-05.md")   # legacy record, not shipped

# key -> precise reason a count could not be read from any surviving manifest.
# cal2026-10: the two pre-topic-cut pair-pool groups have no October producer (see the docstring).
_NO_OCT_POOL = ("no October (cal2026-10) counterpart: the only producer is the full p3_topicpair dose "
                "build of 2026-08-17 (dose_context.json / attrition.csv on the 2026-08-22 event set); the "
                "October Panel 3 sweep ran the lb stage only (data/cal2026-10/frames_afar/"
                "afar_run_report.json), which writes no pre-topic-cut pool accounting. Pre-October value "
                "{old}; not printed in the thesis or the 2026-09-13 draft.")
UNREPRODUCIBLE: dict[str, str] = {
    "pairs_pool_pre_cut": _NO_OCT_POOL.format(old="econ 724,002 / chemistry 269,168 / math_stats 78,478"),
    "pairs_dropped_no_dose": _NO_OCT_POOL.format(old="econ 0 / chemistry 659 / math_stats 6,379"),
}

# The thesis appendix values (appendix_funnel.tex steps 1-3 + note; appendix_pipeline.tex).
# Equality is the spec: build() asserts each derived value equals this.
THESIS_VALUES = {
    "works_snapshot": 510_372_821,
    "works_benchmarkable": 375_548_859,
    "works_articles_reviews": 258_400_229,
    "benchmark_cells": 543_037,
    # cal2026-10: the two pool groups below are the PRE-October values of the (now unreproducible)
    # keys, kept so build() can prove its declared reasons quote what the pre-October inputs say.
    "pairs_pool_pre_cut": {"econ": 724_002, "chemistry": 269_168, "math_stats": 78_478},
    "pairs_dropped_no_dose": {"econ": 0, "chemistry": 659, "math_stats": 6_379},
    # R3: sec2_data.tex footnote (252), "26 June 2026 release", footnote "10.5 million authors"
    # (exact values from the 2026-08-09 audit: 46,504,474 works / 10,497,390 authors = 9.1%),
    # and the roster spell-start ceilings behind "no employment spells beginning in 2024"
    # (chemistry) / "none for 2021--2024" + "after 2020" (mathematics).
    "openalex_subfields": 252,
    "snapshot_release_date": "2026-06-26",
    "u1_universe": {"works": 46_504_474, "authors": 10_497_390, "share_of_snapshot_pct": 9.1},
    "roster_spell_max_start": {"econ": 2025, "chem": 2023, "math": 2020},
}


def build() -> dict:
    P = load_paths()
    # M3 T4 review MINOR-5: these two scan records are frozen in the repo (sha256-pinned in
    # data/MANIFEST.sha256, byte-identical to the legacy originals). Reading the frozen copies is
    # what makes the freeze mean something - before this, every funnel number still required the
    # author's read-only legacy tree to be mounted.
    FW = P["fwci"]
    TP = P["legacy_v2_output"] / "p3_topicpair_2026-08-17" / "data"

    scan = json.load(open(FW / "scan_manifest.json"))
    gate_a = json.load(open(FW / "gate_a_reconcile.json"))
    # MILESTONE REVIEW: these two are 753 B and 272 B and are now frozen in data/paper_inputs/ with
    # manifest pins — the same treatment T4 gave this generator's FWCI inputs. Legacy is the
    # fallback, so a machine that has it is unaffected.
    PIN = P["paper_inputs"]   # R1 F7: from config (October data/paper_inputs)
    _dose = PIN / "dose_context.json" if (PIN / "dose_context.json").is_file() else TP / "dose_context.json"
    _attr = PIN / "attrition.csv" if (PIN / "attrition.csv").is_file() else TP / "attrition.csv"
    dose = json.load(open(_dose))
    attr = {r["field"]: r for r in csv.DictReader(open(_attr))}

    N = {"_provenance": {}}

    def rec(key, val, src):
        N[key] = val
        N["_provenance"][key] = src

    # ---- works counts + benchmark cells, from the fwci-baseline scan manifests ----
    assert (scan["total_lines_read"] == scan["manifest_record_count"]
            == gate_a["lines_read"] == gate_a["manifest_record_count"]), \
        "snapshot scan does not reconcile with its own manifest"
    assert scan["bad_lines"] == 0 and scan["lines_read_equals_manifest"]
    rec("works_snapshot", scan["total_lines_read"],
        "scan_manifest.json total_lines_read (== manifest_record_count; gate_a agrees)")

    assert scan["sum_work_count"] == gate_a["sum_work_count"]
    rec("works_benchmarkable", scan["sum_work_count"],
        "scan_manifest.json sum_work_count (works with subfield+year+type; gate_a agrees)")

    assert scan["n_cells"] == gate_a["n_cells"]
    rec("benchmark_cells", scan["n_cells"], "scan_manifest.json n_cells (gate_a agrees)")

    by_type = {r["work_type"]: r["works"] for r in gate_a["work_type_breakdown_of_cellable"]}
    rec("works_articles_reviews", by_type["article"] + by_type["review"],
        "gate_a_reconcile.json work_type_breakdown_of_cellable: article + review works")

    # ---- pre-topic-cut pair pools + no-dose drops: UNREPRODUCIBLE since cal2026-10 (docstring) ----
    # The pre-October inputs are still read and self-checked, so the declared "pre-October value"
    # in the reason string can never drift from what those files say.
    for f in FIELDS:
        assert dose[f]["pairs_total"] == int(attr[f]["pairs_panel"]), \
            f"{f}: dose_context pairs_total != attrition pairs_panel"
        assert int(attr[f]["dropped_no_dose"]) == dose[f]["pairs_total"] - dose[f]["pairs_both_dose"]
    pre_oct = {"pairs_pool_pre_cut": {f: dose[f]["pairs_total"] for f in FIELDS},
               "pairs_dropped_no_dose": {f: int(attr[f]["dropped_no_dose"]) for f in FIELDS}}
    for k, v in pre_oct.items():
        assert v == THESIS_VALUES[k], f"{k}: pre-October inputs {v} != recorded {THESIS_VALUES[k]}"
        assert all(f"{n:,}" in UNREPRODUCIBLE[k] for n in v.values()), k

    # ---- R3: the four sec2 numbers that had no source ----
    import duckdb  # deferred: only these two groups need it
    con = duckdb.connect()

    # (1) subfields present in the full-snapshot cell table (== the expected table's)
    n_sub = con.execute("SELECT count(DISTINCT subfield_id) FROM parquet_scan(?)",
                        [str(FW / "fwci_baseline_pop_full.parquet")]).fetchone()[0]
    n_sub_exp = con.execute("SELECT count(DISTINCT subfield_id) FROM parquet_scan(?)",
                            [str(FW / "fwci_expected_fullsnapshot_2026-08-09.parquet")]).fetchone()[0]
    assert n_sub == n_sub_exp, f"subfield count differs between the two frozen FWCI tables: {n_sub} vs {n_sub_exp}"
    rec("openalex_subfields", int(n_sub),
        "fwci_baseline_pop_full.parquet count(DISTINCT subfield_id) (== expected table; OpenAlex "
        "documents 252 subfields: https://docs.openalex.org/api-entities/topics)")

    # (4) the snapshot release the scan read
    assert scan["snapshot_manifest_date"] == gate_a["snapshot_manifest_date"], \
        "scan_manifest and gate_a disagree on the snapshot date"
    rec("snapshot_release_date", scan["snapshot_manifest_date"],
        "scan_manifest.json snapshot_manifest_date (gate_a agrees)")

    # (2) the U1 extraction universe, from the 2026-07-05 audit record of its run_manifest
    fact = P["legacy_multiplex"] / U1_FACT_SHEET
    if not fact.is_file():
        raise FileNotFoundError(
            f"u1_universe needs the read-only legacy record {fact} (the U1 run_manifest itself is "
            "on the unmounted data disk); mount the legacy tree or leave this key unpinned")
    txt = fact.read_text(encoding="utf-8")
    m_rows = re.search(r"works ([0-9,]+) / authorship [0-9,]+ / refs [0-9,]+ / works_affil [0-9,]+ / "
                       r"work_text [0-9,]+ / authors ([0-9,]+) /", txt)
    m_rec = re.search(r"expected ([0-9,]+) = kept ([0-9,]+) \+ skipped ([0-9,]+) \+ failed ([0-9,]+)", txt)
    assert m_rows and m_rec, f"the U1 row-count / reconcile rows were not found in {fact.name}"
    u1_works, u1_authors = (int(x.replace(",", "")) for x in m_rows.groups())
    expected, kept, skipped, failed = (int(x.replace(",", "")) for x in m_rec.groups())
    assert kept == u1_works, f"U1 record: kept {kept} != works table rows {u1_works}"
    assert kept + skipped + failed == expected, "U1 record: reconcile identity does not balance"
    assert expected == scan["total_lines_read"], \
        f"U1 record expects {expected} snapshot works; the frozen scan_manifest read {scan['total_lines_read']}"
    rec("u1_universe",
        {"works": u1_works, "authors": u1_authors,
         "share_of_snapshot_pct": round(100 * u1_works / expected, 1)},
        f"legacy multiplex_pipeline/{U1_FACT_SHEET} rows 'U1 十张表行数' + '对账单' (2026-07-05 audit of "
        "the run_manifest; expected == frozen scan_manifest total_lines_read)")

    # (3) roster spell-start ceilings, from the rosters the frames read
    RAW = P["raw_verified"]
    def max_start(pq, where=""):
        return con.execute(f"SELECT max(year_start) FROM parquet_scan(?) {where}", [str(RAW / pq)]).fetchone()[0]
    # cal2026-10: the economics roster is the October one (920 + 88 entries; pinned)
    # R1 F7: root, MANIFEST and key from analysis/lib/canon.py (October: data/cal2026-10, as before)
    roster_oct = P["cal"] / "roster_econ_verified_2026-10.parquet"
    pins = dict((ln.split("  ", 1)[1].strip(), ln.split("  ", 1)[0]) for ln in
                canon.manifest("cal").read_text().splitlines() if ln.strip())
    import hashlib
    assert hashlib.sha256(roster_oct.read_bytes()).hexdigest() == \
        pins[canon.key(roster_oct)], "October econ roster sha256 != its pin"
    ceil = {"econ": int(con.execute("SELECT max(year_start) FROM parquet_scan(?)", [str(roster_oct)]).fetchone()[0]),
            "chem": int(max_start("roster_gold_chemistry.parquet")),
            "math": int(max_start("roster_gold_math_stats.parquet"))}
    # cross-check on every verified chem/math spell (not only the frame inputs): the years the
    # sentence calls absent must be absent there too
    absent = {d: [int(y) for (y,) in con.execute(
        "SELECT DISTINCT year_start FROM parquet_scan(?) WHERE field = ? AND year_start > ?",
        [str(RAW / "roster_chemmath_verified.parquet"), f, ceil[d]]).fetchall()]
        for d, f in (("chem", "chemistry"), ("math", "math_stats"))}
    assert not [y for y in absent["chem"] if y <= 2024], \
        f"roster_chemmath_verified has chemistry spells starting after {ceil['chem']}: {absent['chem']}"
    assert not [y for y in absent["math"] if y <= 2024], \
        f"roster_chemmath_verified has math_stats spells starting after {ceil['math']}: {absent['math']}"
    rec("roster_spell_max_start", ceil,
        f"max(year_start) of {canon.key(roster_oct)} / roster_gold_chemistry / "
        "roster_gold_math_stats " + _m_checks.spell_start_note(ceil))

    # Freeze-wave Task 8 (2026-08-28) kept the two pair-pool groups as PRE-caliber numbers; since
    # cal2026-10 they are declared UNREPRODUCIBLE (no October producer; not printed anywhere).
    # The snapshot/benchmark counts (steps 1-3) are caliber-independent.
    N["_caliber_note"] = ("cal2026-10: pairs_pool_pre_cut and pairs_dropped_no_dose have no October "
                          "counterpart and are declared in _unreproducible (pre-October values kept "
                          "in the reason); steps 1-3, subfields, snapshot date and U1 universe are "
                          "caliber-independent; roster_spell_max_start reads the October econ roster")

    # ---- coverage + equality with the thesis appendix (the spec; never tuned to fit) ----
    derived = {k for k in N if not k.startswith("_")}   # _provenance/_caliber_note are metadata
    assert derived | set(UNREPRODUCIBLE) == set(FUNNEL_KEYS) and not derived & set(UNREPRODUCIBLE), (
        f"coverage drift: extra={derived - set(FUNNEL_KEYS)} "
        f"missing={set(FUNNEL_KEYS) - derived - set(UNREPRODUCIBLE)}")
    _m_checks.check_thesis_values(N, THESIS_VALUES, derived, canon.mode())
    return N


def main():
    P = load_paths()
    out = P["output"] / "paper" / "data_numbers_funnel.json"
    N = build()
    if UNREPRODUCIBLE:
        N["_unreproducible"] = UNREPRODUCIBLE
    out.parent.mkdir(parents=True, exist_ok=True)
    json.dump(N, open(out, "w"), ensure_ascii=False, indent=1)
    for k, v in N.items():
        if k.startswith("_"):
            continue
        print(k, "=", json.dumps(v, ensure_ascii=False))
    print(f"wrote {out}  ({len(N) - 1 - ('_unreproducible' in N)} keys derived, "
          f"{len(UNREPRODUCIBLE)} unreproducible)")


if __name__ == "__main__":
    main()
