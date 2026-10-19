#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""caliber_2026-08-28/run_supplement.py — Task-2 driver: the star-works supplement fetch for the
five new stars (the ONLY live-API step of the caliber rebuild) and the population bookkeeping that
follows from the rules. Repo-authored launcher (declared in `pipeline.lib.paths.LAUNCHERS`
— it runs no ported script, so it stages nothing); it edits NO ported file and NO frozen artifact.
All products land in `data/cal2026-08-28/`.

    setup/.venv/bin/python "pipeline/stars/caliber_2026-08-28/run_supplement.py" --execute

Phases (each measured, each with a hard STOP on any surprise):

  W  live-fetch the works of A5027778630, A5091826237, A5017222669 and A5090916445 (no frozen cache exists for them),
     A5017222669's four split-ID merge works from A5083852619 by id, and A5062352558's live profile — that author's
     supplement rows come from the FROZEN 227-work cache, the live pass supplying only what the
     cache lacks (the `type` field and post-08-15 additions). STOP when a dossier anchor work is
     missing, a profile total is far off the dossier's 08-27 measure, a merge work is gone, or a
     merge citation count is far off — a moved profile is reported, never improvised around.
  X  apply the per-star cleanups as DATA-driven filters (`cleaned_works.exclusions()`,
     backed by `data/cal2026-08-28/calls_2026-08-28.csv`): A5091826237 −4, A5017222669 −1, A5062352558 −W2002298104.
  S  assemble `edges_supplement_cal2026-08-28.jsonl` the way the ported `70_prep` built each
     variant: the frozen fnfix supplement BYTES + the new stars' rows in 70_prep's exact row shape
     (register order: A5027778630, A5091826237, A5017222669 + merge, A5090916445, A5062352558).
  P  population bookkeeping: `stars_excluded_cal2026-08-28.parquet` = frozen fnfix list ∪ the five
     (A5044432173 deliberately NOT added — the roster row is verified and this author returns to the colleague
     population under the department-exposure, all-roster rule); measure and freeze the row-level
     expectations Task 3 must assert (`colleague_rows_expected_2026-08-28.csv`).
  F  freeze works JSONs + supplement + parquet + expectations + request log + report, and
     regenerate `data/cal2026-08-28/MANIFEST.sha256`.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import os
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))

from pipeline.lib.paths import legacy_thesis, require_readable            # noqa: E402

sys.path.insert(0, str(HERE))
import cleaned_works              # noqa: E402
import supplement_fetch as sf     # noqa: E402

GOLD = "multidisc_gold_2026-08-10"
CAL_DIR = REPO / "data" / "cal2026-08-28"
STAMP = "2026-08-28"

A5044432173_ID = "A5044432173"
A5027778630_ID, A5091826237_ID, A5017222669_ID, A5090916445_ID, A5062352558_ID = ("A5027778630", "A5091826237", "A5017222669",
                                       "A5090916445", "A5062352558")
#: register ruling order — also the append order in the supplement file
FIVE = (A5027778630_ID, A5091826237_ID, A5017222669_ID, A5090916445_ID, A5062352558_ID)
NAMES = {A5027778630_ID: "A5027778630", A5091826237_ID: "A5091826237", A5017222669_ID: "A5017222669",
         A5090916445_ID: "A5090916445", A5062352558_ID: "A5062352558"}
MERGE_ID = cleaned_works.MERGE_SOURCE_ID                                  # A5083852619

#: the dossiers' 2026-08-27 profile totals (works on the OpenAlex profile that day). The live
#: fetch is a day-scale re-measure: a total far off one of these is a moved profile -> STOP.
PROFILE_TOTALS_0827 = {A5027778630_ID: 633, A5091826237_ID: 878, A5090916445_ID: 125, A5062352558_ID: 228}   # A5017222669: no dossier total
#: the dossiers' 2026-08-27 citation counts for A5017222669's merge works (split-ID table)
MERGE_CITES_0827 = {"W1592870802": 5118, "W1214546200": 681,
                    "W2131510173": 1309, "W2167745157": 15}

STOPS: list[str] = []


def _stop(msg: str) -> None:
    STOPS.append(msg)
    print(f"\n*** STOP: {msg}", flush=True)


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _legacy_gold_data() -> pathlib.Path:
    return pathlib.Path(str(require_readable(legacy_thesis() / "v2_output" / GOLD))) / "data"


def _anchor_ids(aid: str) -> list[str]:
    return [r["work_id"] for r in cleaned_works.load_calls()
            if r["author_id"] == aid and r["action"] == "first_pub_anchor"]


def check_profile(aid: str, recs: list[dict]) -> None:
    """The moved-profile tripwires: dossier anchor works present, profile total near 08-27."""
    ids = {r["work_id"] for r in recs}
    for a in _anchor_ids(aid):
        if a not in ids:
            _stop(f"{NAMES[aid]} ({aid}): dossier first_pub anchor {a} is NOT in the live "
                  f"profile — the profile moved since 08-27")
    want = PROFILE_TOTALS_0827.get(aid)
    if want is not None:
        tol = max(40, int(want * 0.05))
        if abs(len(recs) - want) > tol:
            _stop(f"{NAMES[aid]} ({aid}): live profile has {len(recs)} works vs the dossier's "
                  f"{want} on 08-27 (tolerance ±{tol}) — the profile moved")


def measure_expectations(con) -> list[dict]:
    """The row-level accounting handed to Task 3, MEASURED from the frozen frames and the frozen
    legacy intermediates — never hand-typed."""
    gold_data = _legacy_gold_data()
    econ_fnfix = pathlib.Path(str(require_readable(
        legacy_thesis() / "v2_output" / "econ_fnfix_2026-08-15"))) / "data"
    frames = REPO / "data" / "frames"
    field_of = {A5027778630_ID: "chemistry", A5091826237_ID: "chemistry", A5062352558_ID: "chemistry",
                A5017222669_ID: "math_stats", A5090916445_ID: "math_stats"}
    q = lambda sql: con.execute(sql).fetchone()[0]                        # noqa: E731
    rows: list[dict] = []

    def add(aid, layer, source, n, expectation, note=""):
        rows.append({"author_id": aid, "name": NAMES.get(aid, "A5044432173"),
                     "field": field_of.get(aid, "econ"), "layer": layer,
                     "source": source, "rows": n, "task3_expectation": expectation,
                     "note": note})

    for aid in FIVE:
        fld = field_of[aid]
        p1 = (frames / f"p1_frame_{fld}.csv").as_posix()
        p2 = (frames / f"p2_becoming_{fld}.csv").as_posix()
        rel = (gold_data / "fnfix" / f"union_frame_{fld}" / "relationships.csv").as_posix()
        pairs = (gold_data / "fnfix" / f"panels23_{fld}_gold" / "pairs_none.parquet").as_posix()
        n_rel = q(f"SELECT count(*) FROM read_csv_auto('{rel}') WHERE pid LIKE '%{aid}%'")
        n_p1 = q(f"SELECT count(*) FROM read_csv_auto('{p1}') WHERE incumbent_person_id='{aid}'")
        n_p2 = q(f"SELECT count(*) FROM read_csv_auto('{p2}') WHERE pid='{aid}'")
        n_pr = q(f"SELECT count(*) FROM read_parquet('{pairs}') "
                 f"WHERE i_id LIKE '%{aid}%' OR j_id LIKE '%{aid}%'")
        if n_p1 != 11 * n_rel or n_p2 != 17 * n_rel:
            _stop(f"{aid}: frame rows are not the structural 11×/17× of the relation rows "
                  f"(rel {n_rel}, p1 {n_p1}, p2 {n_p2}) — the accounting premise broke")
        add(aid, "rel_fnfix", f"legacy fnfix union_frame_{fld}/relationships.csv", n_rel,
            "removed", "person×event relations; new star leaves the colleague population")
        add(aid, "p1_frame", f"data/frames/p1_frame_{fld}.csv (incumbent_person_id)", n_p1,
            "removed", "= 11 x rel rows")
        add(aid, "p2_becoming", f"data/frames/p2_becoming_{fld}.csv (pid)", n_p2,
            "removed", "= 17 x rel rows")
        add(aid, "pairs_legacy", f"legacy fnfix panels23_{fld}_gold/pairs_none.parquet "
            f"(i_id or j_id)", n_pr, "removed",
            "pair layer is int-anonymised in data/frames; assert via builder reports")

    p1e = (frames / "p1_frame_econ.csv").as_posix()
    p2e = (frames / "p2_becoming_econ.csv").as_posix()
    pairs_e = (econ_fnfix / "pairs_unified.csv").as_posix()
    add(A5044432173_ID, "p1_star_side", "data/frames/p1_frame_econ.csv (star_person_id=P_...)",
        q(f"SELECT count(*) FROM read_csv_auto('{p1e}') WHERE star_person_id='P_{A5044432173_ID}'"),
        "removed", "her event A5044432173:2006 leaves with the D-A ruling (T1)")
    add(A5044432173_ID, "p1_colleague_side", "data/frames/p1_frame_econ.csv (incumbent_person_id=P_...)",
        q(f"SELECT count(*) FROM read_csv_auto('{p1e}') WHERE incumbent_person_id='P_{A5044432173_ID}'"),
        "persists", "roster melbourne_econ 2007-2011: she stays a colleague (系暴露 all-roster)")
    add(A5044432173_ID, "p2_star_side", "data/frames/p2_becoming_econ.csv (star)",
        q(f"SELECT count(*) FROM read_csv_auto('{p2e}') WHERE star='{A5044432173_ID}'"), "removed")
    add(A5044432173_ID, "p2_colleague_side", "data/frames/p2_becoming_econ.csv (pid)",
        q(f"SELECT count(*) FROM read_csv_auto('{p2e}') WHERE pid='{A5044432173_ID}'"), "persists")
    add(A5044432173_ID, "pairs_event_side", "legacy econ_fnfix pairs_unified.csv (event_id=A5044432173:*)",
        q(f"SELECT count(*) FROM read_csv_auto('{pairs_e}') WHERE event_id LIKE '{A5044432173_ID}%'"),
        "removed")
    add(A5044432173_ID, "pairs_member_side", "legacy econ_fnfix pairs_unified.csv (i_id/j_id, other events)",
        q(f"SELECT count(*) FROM read_csv_auto('{pairs_e}') "
          f"WHERE (i_id LIKE '%{A5044432173_ID}%' OR j_id LIKE '%{A5044432173_ID}%') "
          f"AND event_id NOT LIKE '{A5044432173_ID}%'"), "persists")
    return rows


def verify_rosters(con, report: dict) -> None:
    """The population-caliber evidence: A5044432173's econ roster row (she returns to the colleague
    population), and each new star's arrival inside their roster spell (70_prep's own hard
    check, replicated)."""
    rv = REPO / "data" / "raw_verified"
    roster_rows = con.execute(
        f"SELECT dept_key, year_start, year_end, human_verified, confidence, id_issue "
        f"FROM read_parquet('{(rv / 'roster_econ_verified.parquet').as_posix()}') "
        f"WHERE author_id='{A5044432173_ID}'").fetchall()
    if len(roster_rows) != 1 or not roster_rows[0][3]:
        _stop(f"A5044432173's econ roster row is missing or unverified: {roster_rows}")
        return
    report["population_caliber"] = {
        "authority": "the author's decision record of 2026-08-28 (private archive) + the signed 系暴露 "
                     "all-roster population caliber (2026-07-31)",
        "A5044432173": {"decision": "returns to the colleague population; NOT added to any exclusion "
                             "list; her event was removed by Task 1 (D-A, aage=0)",
                 "roster_row": {"dept_key": roster_rows[0][0], "year_start": int(roster_rows[0][1]),
                                "year_end": int(roster_rows[0][2]), "human_verified": True,
                                "confidence": roster_rows[0][4], "id_issue": roster_rows[0][5]},
                 "econ_mechanism": "the econ chain has NO stars_excluded artifact; its colleague "
                                   "population is the relationships table, where her rows already "
                                   "sit (88 p1 / 136 p2 frame rows persist); her star side leaves "
                                   "with the event",
                 "econ_supplement": "data/raw_verified/edges_supplement_econ_fnfix.jsonl is left "
                                    "UNTOUCHED (her 257 seed rows stay in the works domain): the "
                                    "econ works domain already includes full-API works for "
                                    "non-stars (the 133-rescue and 108+4-patch cohorts), so "
                                    "removing hers would impoverish her record below the chain's "
                                    "own footing — and it is a frozen input this task may not "
                                    "edit"}}
    arrivals, spells = {}, {}
    for name in ("events_chemistry_cal.csv", "events_math_stats_cal.csv"):
        with open(CAL_DIR / name, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                arrivals[r["author_id"]] = int(r["arrival_corrected"])
    for row in con.execute(
            f"SELECT author_id, school, year_start, year_end FROM read_parquet("
            f"'{(rv / 'roster_chemmath_verified.parquet').as_posix()}') WHERE author_id IN "
            + "(" + ",".join(f"'{a}'" for a in FIVE) + ")").fetchall():
        spells[row[0]] = {"school": row[1], "year_start": int(row[2]), "year_end": int(row[3])}
    for aid in FIVE:
        if aid not in arrivals:
            _stop(f"{NAMES[aid]} ({aid}) is not in the cal event tables — Task 1 output moved?")
            continue
        if aid not in spells:
            _stop(f"{NAMES[aid]} ({aid}) has no chem/math roster row")
            continue
        s = spells[aid]
        if not (s["year_start"] <= arrivals[aid] <= s["year_end"]):
            _stop(f"{NAMES[aid]} ({aid}): arrival {arrivals[aid]} outside roster spell "
                  f"{s['year_start']}-{s['year_end']} (70_prep's hard check)")
    report["population_caliber"]["new_stars_roster_check"] = {
        aid: {"arrival": arrivals.get(aid), **spells.get(aid, {})} for aid in FIVE}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--execute", action="store_true",
                    help="required: ~15-20 live OpenAlex API requests (the rebuild's only live step)")
    args = ap.parse_args(argv)
    if not args.execute:
        print("This makes ~15-20 live OpenAlex API requests (five author profiles + A5017222669's four "
              "merge works) and freezes the results. Re-run with --execute.", file=sys.stderr)
        return 2

    import duckdb
    report: dict = {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
                    "authority": "the author's decision record of 2026-08-28 (private archive)",
                    "select_note": "wire protocol = 70_prep's; select adds doi,cited_by_count for "
                                   "the frozen works records only — supplement rows carry exactly "
                                   "70_prep's five keys"}
    gold_data = _legacy_gold_data()
    frozen_sup_p = gold_data / "edges_supplement_fnfix.jsonl"
    frozen_excl_p = gold_data / "stars_excluded_fnfix.parquet"
    cache_p = gold_data / "_star_works_cache" / f"{A5062352558_ID}.json"
    for p in (frozen_sup_p, frozen_excl_p, cache_p):
        if not p.is_file():
            raise FileNotFoundError(p)
    report["frozen_inputs_sha256"] = {p.name: _sha(p)
                                      for p in (frozen_sup_p, frozen_excl_p, cache_p)}

    key = sf.api_key()
    report["api_key_present"] = bool(key)
    if not key:
        print("[run_supplement] WARNING: no $OPENALEX_API_KEY found — proceeding mailto-only")
    log = sf.RequestLog()
    excl = cleaned_works.exclusions()

    # ---- phase W: the fetches -------------------------------------------------------------------
    t0 = time.time()
    fetched: dict[str, list[dict]] = {}
    for aid in (A5027778630_ID, A5091826237_ID, A5017222669_ID, A5090916445_ID):
        fetched[aid] = sf.fetch_author_works(aid, key, log)
        print(f"[run_supplement] W {NAMES[aid]} ({aid}): {len(fetched[aid])} works")
        check_profile(aid, fetched[aid])

    merge_ids = cleaned_works.merge_works(A5017222669_ID)
    merge_recs = sf.fetch_works_by_id(merge_ids, key, log, seed=MERGE_ID)
    got_merge = {r["work_id"] for r in merge_recs}
    print(f"[run_supplement] W merge {MERGE_ID}: {sorted(got_merge)}")
    for wid in merge_ids:
        if wid not in got_merge:
            _stop(f"A5017222669 merge work {wid} is gone from the live API (merged away or deleted) — "
                  f"the split profile moved since 08-27")
    merge_author_obs = {}
    for r in merge_recs:
        holders = [a for a in (MERGE_ID, A5017222669_ID) if a in r["authors"]]
        merge_author_obs[r["work_id"]] = holders or r["authors"][:5]
        if not holders:
            _stop(f"merge work {r['work_id']}: neither {MERGE_ID} nor {A5017222669_ID} among its authors "
                  f"({r['authors'][:8]}) — contradicts the signed merge ruling")
        want = MERGE_CITES_0827[r["work_id"]]
        if not (want - 30 <= (r["cited_by_count"] or 0) <= want * 1.10 + 30):
            _stop(f"merge work {r['work_id']}: cited_by_count {r['cited_by_count']} far off the "
                  f"dossier's {want} (08-27)")
    report["A5017222669_merge"] = {
        "source_profile": MERGE_ID, "works": {r["work_id"]: r["cited_by_count"]
                                              for r in merge_recs},
        "citations_recovered": sum(r["cited_by_count"] or 0 for r in merge_recs),
        "author_id_observed_on_each": merge_author_obs}

    a5062352558_live = sf.fetch_author_works(A5062352558_ID, key, log)
    print(f"[run_supplement] W {NAMES[A5062352558_ID]} ({A5062352558_ID}): live {len(a5062352558_live)} works")
    check_profile(A5062352558_ID, a5062352558_live)
    cache = json.loads(cache_p.read_text(encoding="utf-8"))
    if len(cache) != 227:
        _stop(f"A5062352558's frozen cache has {len(cache)} works, not the documented 227")
    a5062352558_recs, recon = sf.a5062352558_rows_from_cache(cache, a5062352558_live)
    if recon["missing_from_live"]:
        _stop(f"A5062352558: cached works vanished from her live profile: "
              f"{recon['missing_from_live']} — the profile moved since 08-15/08-27")
    fetched[A5062352558_ID] = a5062352558_recs
    print(f"[run_supplement] W A5062352558 reconciliation: cache {recon['cache_works']}, live "
          f"{recon['live_works']}, live-only added {recon['live_only_added']}, "
          f"field diffs (cache kept) {len(recon['field_diffs_cache_kept'])}")

    # ---- phase X: the signed cleanup filters ----------------------------------------------------
    cleaned: dict[str, list[dict]] = {}
    exclusions_applied = []
    for aid in FIVE:
        drop = {w for (a, w) in excl if a == aid}
        cleaned[aid] = [r for r in fetched[aid] if r["work_id"] not in drop]
        present = {r["work_id"] for r in fetched[aid]}
        for w in sorted(drop):
            exclusions_applied.append({"author_id": aid, "work_id": w, "dropped": w in present})
            if w not in present:
                print(f"[run_supplement] X NOTE {aid}: excluded work {w} was not in the fetch "
                      f"(already detached upstream) — filter is a recorded no-op")
    # A5017222669: merge works appended AFTER his own profile rows; a server-side merge that already
    # put one into his profile must not duplicate it
    already = {r["work_id"] for r in cleaned[A5017222669_ID]} & set(merge_ids)
    if already:
        print(f"[run_supplement] X NOTE A5017222669: merge works already on his profile (server-side "
              f"merge since 08-27): {sorted(already)} — not appended twice")
    cleaned[A5017222669_ID] = cleaned[A5017222669_ID] + [r for r in merge_recs if r["work_id"] not in already]
    report["A5017222669_merge"]["already_on_profile"] = sorted(already)
    report["exclusions_applied"] = exclusions_applied

    # ---- phase P: population bookkeeping (measured BEFORE anything is frozen) -------------------
    con = duckdb.connect()
    n_fnfix_excl = con.execute(
        f"SELECT count(*) FROM read_parquet('{frozen_excl_p.as_posix()}')").fetchone()[0]
    in_already = {t[0] for t in con.execute(
        f"SELECT author_id FROM read_parquet('{frozen_excl_p.as_posix()}') WHERE author_id IN "
        + "(" + ",".join(f"'{a}'" for a in FIVE + (A5044432173_ID,)) + ")").fetchall()}
    if in_already & set(FIVE):
        _stop(f"new star(s) already in stars_excluded_fnfix: {in_already & set(FIVE)}")
    if A5044432173_ID in in_already:
        _stop("A5044432173 is in stars_excluded_fnfix — the premise that she was never on the chem/math "
              "exclusion list is wrong; reconcile before proceeding")
    expectations = measure_expectations(con)
    verify_rosters(con, report)

    report["stars"] = {}
    for aid in FIVE:
        report["stars"][aid] = {
            "name": NAMES[aid],
            "works_fetched_or_cached": len(fetched[aid]),
            "supplement_rows": len(cleaned[aid]),
            **({"reconciliation": recon} if aid == A5062352558_ID else {})}
    report["request_total"] = len(log.entries)
    report["fetch_seconds"] = round(time.time() - t0, 1)

    if STOPS:
        print(f"[run_supplement] {len(STOPS)} STOP condition(s) — NOTHING frozen. Report and stop.")
        failed = pathlib.Path(os.environ.get("SAR_OUT_ROOT") or "/private/tmp") / \
            f"supplement_report_FAILED_{datetime.datetime.now():%Y%m%d_%H%M%S}.json"
        failed.parent.mkdir(parents=True, exist_ok=True)
        failed.write_text(json.dumps({**report, "stops": STOPS}, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        print(f"[run_supplement] failure report -> {failed}")
        return 1

    # ---- phase S+F: assemble and freeze ---------------------------------------------------------
    frozen_bytes = frozen_sup_p.read_bytes()
    assert frozen_bytes.endswith(b"\n"), "frozen fnfix supplement does not end with a newline"
    report["supplement"] = {"fnfix_lines": frozen_bytes.decode("utf-8").count("\n"),
                            "appended_rows": sum(len(cleaned[a]) for a in FIVE)}
    with open(CAL_DIR / "edges_supplement_cal2026-08-28.jsonl", "wb") as f:
        f.write(frozen_bytes)
        for aid in FIVE:
            for r in cleaned[aid]:
                f.write(sf.supplement_line(r, aid).encode("utf-8"))

    for aid, name in ((A5027778630_ID, f"works_{A5027778630_ID}_{STAMP}.json"),
                      (A5091826237_ID, f"works_{A5091826237_ID}_{STAMP}.json"),
                      (A5017222669_ID, f"works_{A5017222669_ID}_{STAMP}.json"),
                      (A5090916445_ID, f"works_{A5090916445_ID}_{STAMP}.json")):
        (CAL_DIR / name).write_text(
            json.dumps(fetched[aid], ensure_ascii=False) + "\n", encoding="utf-8")
    (CAL_DIR / f"works_{A5062352558_ID}_live_{STAMP}.json").write_text(
        json.dumps(a5062352558_live, ensure_ascii=False) + "\n", encoding="utf-8")
    (CAL_DIR / f"works_{MERGE_ID}_merge_{STAMP}.json").write_text(
        json.dumps(merge_recs, ensure_ascii=False) + "\n", encoding="utf-8")

    excl_out = CAL_DIR / f"stars_excluded_cal{STAMP}.parquet"
    con.execute(
        f"COPY (SELECT author_id FROM read_parquet('{frozen_excl_p.as_posix()}') "
        f"UNION SELECT * FROM (VALUES " + ",".join(f"('{a}')" for a in FIVE)
        + f") t(author_id) ORDER BY author_id) TO '{excl_out.as_posix()}' (FORMAT PARQUET)")
    n_cal_excl = con.execute(
        f"SELECT count(*) FROM read_parquet('{excl_out.as_posix()}')").fetchone()[0]
    assert n_cal_excl == n_fnfix_excl + 5, (n_fnfix_excl, n_cal_excl)
    report["stars_excluded"] = {"fnfix": n_fnfix_excl, "cal": n_cal_excl,
                                "added": list(FIVE), "not_added": [A5044432173_ID],
                                "order_note": "ORDER BY author_id for determinism; consumers read "
                                              "it as a set (20_rebuild_y_gold excl_authors)"}
    print(f"[run_supplement] P stars_excluded {n_fnfix_excl} -> {n_cal_excl}")

    exp_cols = ["author_id", "name", "field", "layer", "source", "rows", "task3_expectation",
                "note"]
    with open(CAL_DIR / f"colleague_rows_expected_{STAMP}.csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=exp_cols)
        w.writeheader()
        w.writerows(expectations)

    log.write(CAL_DIR / f"api_request_log_{STAMP}.jsonl")
    logged = (CAL_DIR / f"api_request_log_{STAMP}.jsonl").read_bytes().decode("utf-8")
    assert "api_key" not in logged and (not key or key not in logged), "api key leaked into the log"
    (CAL_DIR / f"supplement_report_{STAMP}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest = "".join(f"{_sha(f)}  data/cal2026-08-28/{f.name}\n"
                       for f in sorted(CAL_DIR.iterdir())
                       if f.is_file() and f.name != "MANIFEST.sha256")
    (CAL_DIR / "MANIFEST.sha256").write_text(manifest, encoding="utf-8")
    print(f"[run_supplement] frozen {manifest.count(chr(10))} files + MANIFEST into {CAL_DIR}")
    print(f"[run_supplement] done: {report['request_total']} API requests in "
          f"{report['fetch_seconds']} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
