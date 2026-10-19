# -*- coding: utf-8 -*-
"""Task 2 of the caliber rebuild: the star-works supplement fetch for the five new stars and the
population bookkeeping that follows (author-signed rulings 1-5 + the population caliber).

Products under test (frozen in `data/cal2026-08-28/`, written by
`pipeline/stars/caliber_2026-08-28/run_supplement.py`):

* `edges_supplement_cal2026-08-28.jsonl` — the frozen fnfix supplement BYTES + the five new stars'
  works in `70_prep`'s exact row shape, with the signed cleanups applied as data-driven filters;
* `works_*_2026-08-28.json` — the per-star fetch records (incl. the split-ID merge works of
  A5017222669 with their citation counts);
* `stars_excluded_cal2026-08-28.parquet` — fnfix ∪ the five (A5044432173 NOT added: no longer a
  star, and back in the colleague population under the signed all-roster department-exposure
  caliber);
* `colleague_rows_expected_2026-08-28.csv` — the row-level expectations handed to Task 3;
* `api_request_log_2026-08-28.jsonl` + `supplement_report_2026-08-28.json` — the request custody.
"""
from __future__ import annotations

import csv
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
CAL_CODE = REPO / "pipeline" / "stars" / "caliber_2026-08-28"
if str(CAL_CODE) not in sys.path:
    sys.path.insert(0, str(CAL_CODE))

import cleaned_works                                                     # noqa: E402
import supplement_fetch                                                  # noqa: E402

from analysis.lib.paths import load_paths                                # noqa: E402

P = load_paths()
CAL = REPO / "data" / "cal2026-08-28"
GOLD = P["legacy_thesis"] / "v2_output" / "multidisc_gold_2026-08-10"
ECON_FNFIX = P["legacy_thesis"] / "v2_output" / "econ_fnfix_2026-08-15"

needs_legacy_thesis = pytest.mark.skipif(
    not (P["legacy_thesis"] / "v2_output").is_dir(),
    reason="byte/row comparison against the frozen legacy artifacts needs the read-only tree")

AGE0_STAR = "A5044432173"   # econ star removed by the caliber's academic-age gate
CHEM_NEW1, CHEM_NEW2, MATH_NEW1, MATH_NEW2, CHEM_2003 = ("A5027778630", "A5091826237", "A5017222669",
                                                         "A5090916445", "A5062352558")
FIVE = (CHEM_NEW1, CHEM_NEW2, CHEM_2003, MATH_NEW1, MATH_NEW2)

SUP = CAL / "edges_supplement_cal2026-08-28.jsonl"
EXCL_PARQUET = CAL / "stars_excluded_cal2026-08-28.parquet"
EXPECT_CSV = CAL / "colleague_rows_expected_2026-08-28.csv"
REQ_LOG = CAL / "api_request_log_2026-08-28.jsonl"
REPORT = CAL / "supplement_report_2026-08-28.json"

#: the evidence dossier's live citation counts for MATH_NEW1's four merged works (the split-ID
#: table of that private dossier, measured 2026-08-27). The fetch is a day-scale re-measure: citations only creep,
#: so the frozen counts must sit within a tight band of these.
MERGE_CITES_DOSSIER = {"W1592870802": 5118, "W1214546200": 681,
                       "W2131510173": 1309, "W2167745157": 15}


def _report() -> dict:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def _appended_lines() -> list[str]:
    """The cal supplement's NEW lines (everything after the frozen fnfix prefix), split so that
    each element still carries its trailing newline — the byte-shape tests need it."""
    n_fnfix = _report()["supplement"]["fnfix_lines"]
    text = SUP.read_bytes().decode("utf-8")
    lines = text.splitlines(keepends=True)
    return lines[n_fnfix:]


def _works(name: str) -> list[dict]:
    return json.loads((CAL / name).read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------------
# the supplement file: 70_prep's shape, the frozen prefix, the signed filters
# ------------------------------------------------------------------------------------------------

@needs_legacy_thesis
def test_supplement_extends_the_frozen_fnfix_bytes():
    """`70_prep` built each variant supplement as <predecessor bytes> + appended rows; the cal
    variant does the same on top of the frozen fnfix file, byte for byte."""
    frozen = (GOLD / "data" / "edges_supplement_fnfix.jsonl").read_bytes()
    cal = SUP.read_bytes()
    assert cal.startswith(frozen)
    assert len(cal) > len(frozen)
    assert _report()["supplement"]["fnfix_lines"] == frozen.decode("utf-8").count("\n")


def test_appended_rows_are_exactly_70_preps_row_shape():
    lines = _appended_lines()
    assert lines, "no appended supplement rows"
    for ln in lines:
        d = json.loads(ln)
        assert tuple(d.keys()) == supplement_fetch.SUPPLEMENT_KEYS, ln[:120]
        assert isinstance(d["work_id"], str) and d["work_id"].startswith("W")
        assert d["publication_year"] is None or isinstance(d["publication_year"], int)
        assert d["type"] is None or isinstance(d["type"], str)
        assert d["seed_author"] in FIVE
        assert isinstance(d["authors"], list)
        assert all(isinstance(a, str) and a for a in d["authors"])
        # byte-shape round trip: the line IS what 70_prep's json.dumps would have written
        assert ln == supplement_fetch.supplement_line(
            {"work_id": d["work_id"], "publication_year": d["publication_year"],
             "type": d["type"], "authors": d["authors"]}, d["seed_author"])


def test_every_new_star_contributes_rows_and_counts_match_the_report():
    lines = _appended_lines()
    by_seed: dict[str, int] = {}
    for ln in lines:
        by_seed[json.loads(ln)["seed_author"]] = by_seed.get(json.loads(ln)["seed_author"], 0) + 1
    rep = _report()["stars"]
    assert set(by_seed) == set(FIVE)
    for aid in FIVE:
        assert by_seed[aid] == rep[aid]["supplement_rows"], aid
        assert by_seed[aid] > 0


def test_signed_exclusions_are_absent_from_the_supplement():
    """The dossier-mandated per-star cleanups, applied as DATA-driven filters (the calls table),
    never hand-deletion: CHEM_NEW2 −4, MATH_NEW1 −1, CHEM_2003 −W2002298104 (the 24th call)."""
    excl = cleaned_works.exclusions()
    assert len(excl) == 6
    for ln in _appended_lines():
        d = json.loads(ln)
        assert (d["seed_author"], d["work_id"]) not in excl, ln[:120]
    # and the named CHEM_2003 contaminant is gone under that seed specifically
    chem2003_ids = {json.loads(ln)["work_id"] for ln in _appended_lines()
                 if json.loads(ln)["seed_author"] == CHEM_2003}
    assert "W2002298104" not in chem2003_ids


def test_exclusion_filter_accounting_in_the_report():
    rep = _report()
    applied = rep["exclusions_applied"]
    assert {(e["author_id"], e["work_id"]) for e in applied} == cleaned_works.exclusions()
    for e in applied:
        assert e["dropped"] in (True, False)


def test_math_new1_merge_works_present_with_their_citation_counts():
    """Register ruling 3 / the 2026-08-10 split-ID precedent: A5083852619's four works are merged
    INTO MATH_NEW1's supplement (seed_author = MATH_NEW1). They have NO rows in the snapshot edges
    (T1 review NIT-1), so the merge MUST come from this live fetch."""
    merge_ids = cleaned_works.merge_works(MATH_NEW1)
    assert set(merge_ids) == set(MERGE_CITES_DOSSIER)
    math_new1_rows = {json.loads(ln)["work_id"]: json.loads(ln) for ln in _appended_lines()
                   if json.loads(ln)["seed_author"] == MATH_NEW1}
    for wid in merge_ids:
        assert wid in math_new1_rows, f"merge work {wid} missing from MATH_NEW1's supplement rows"
    merged = {r["work_id"]: r for r in _works("works_A5083852619_merge_2026-08-28.json")}
    assert set(merged) == set(merge_ids)
    for wid, expected in MERGE_CITES_DOSSIER.items():
        got = merged[wid]["cited_by_count"]
        assert expected - 30 <= got <= expected * 1.10 + 30, (
            f"{wid}: fetched cited_by_count {got} is far off the dossier's {expected}")


def test_first_pub_anchor_works_are_in_their_stars_fetch():
    """The dossier-verified earliest OWN works (calls action=first_pub_anchor) must exist in the
    live profiles — their absence would mean a profile moved since 08-27 (a driver STOP)."""
    for aid, name in ((CHEM_NEW1, f"works_{CHEM_NEW1}_2026-08-28.json"),
                      (CHEM_NEW2, f"works_{CHEM_NEW2}_2026-08-28.json"),
                      (MATH_NEW1, f"works_{MATH_NEW1}_2026-08-28.json"),
                      (MATH_NEW2, f"works_{MATH_NEW2}_2026-08-28.json")):
        anchors = [r["work_id"] for r in cleaned_works.load_calls()
                   if r["author_id"] == aid and r["action"] == "first_pub_anchor"]
        ids = {w["work_id"] for w in _works(name)}
        for a in anchors:
            assert a in ids, f"{aid}: anchor work {a} not in the fetched profile"


# ------------------------------------------------------------------------------------------------
# CHEM_2003: cache-first sourcing (the only star with a frozen works cache)
# ------------------------------------------------------------------------------------------------

@needs_legacy_thesis
def test_chem_2003_rows_come_from_the_frozen_cache_plus_live_additions():
    cache = json.loads((GOLD / "data" / "_star_works_cache" / f"{CHEM_2003}.json")
                       .read_text(encoding="utf-8"))
    assert len(cache) == 227
    rep = _report()["stars"][CHEM_2003]
    chem2003_ids = [json.loads(ln)["work_id"] for ln in _appended_lines()
                 if json.loads(ln)["seed_author"] == CHEM_2003]
    # every cached work except the signed exclusion is present, cache order first
    cache_ids = [c["work_id"] for c in cache if c["work_id"] != "W2002298104"]
    assert chem2003_ids[:len(cache_ids)] == cache_ids
    # plus exactly the works the live profile gained since 08-15
    assert chem2003_ids[len(cache_ids):] == rep["reconciliation"]["live_only_added"]
    assert rep["supplement_rows"] == 227 - 1 + len(rep["reconciliation"]["live_only_added"])
    # nothing frozen in the cache left the live profile (else the driver STOPs)
    assert rep["reconciliation"]["missing_from_live"] == []


# ------------------------------------------------------------------------------------------------
# population bookkeeping: stars_excluded + the row-level expectations handed to Task 3
# ------------------------------------------------------------------------------------------------

def _excluded_ids() -> set[str]:
    import duckdb
    con = duckdb.connect()
    return {t[0] for t in con.execute(
        f"SELECT author_id FROM read_parquet('{EXCL_PARQUET.as_posix()}')").fetchall()}


def test_stars_excluded_cal_is_fnfix_plus_exactly_the_five():
    ids = _excluded_ids()
    assert len(ids) == 1832 + 5 == 1837
    for aid in FIVE:
        assert aid in ids
    assert AGE0_STAR not in ids, ("A5044432173 must NOT be excluded: no longer a star, back in the "
                                  "colleague population (signed all-roster department-exposure caliber)")


@needs_legacy_thesis
def test_stars_excluded_cal_is_a_superset_union_of_the_frozen_fnfix_list():
    import duckdb
    con = duckdb.connect()
    frozen = {t[0] for t in con.execute(
        "SELECT author_id FROM read_parquet(?)",
        [(GOLD / "data" / "stars_excluded_fnfix.parquet").as_posix()]).fetchall()}
    assert len(frozen) == 1832
    assert _excluded_ids() == frozen | set(FIVE)


def _expectations() -> dict[tuple[str, str], dict]:
    with open(EXPECT_CSV, newline="", encoding="utf-8") as f:
        return {(r["author_id"], r["layer"]): r for r in csv.DictReader(f)}


#: measured against the PRE-caliber frozen frames — the colleague-side rows of the five new stars
#: as the T2 expectations CSV recorded them. CHEM_2003's p1 187 / p2 289 are the counts the
#: completeness report documented; the p1 = 11×rel and p2 = 17×rel identities are structural.
#: NOTE (2026-08-28 freeze): `data/frames/` now holds the CALIBER frames, in which these rows are
#: partially removed per the channel-split ruling (T3's pinned deviation table), so the live
#: recount below runs against the LEGACY fnfix frames — the exact bytes `data/frames/` held when
#: T2 measured the expectations (they were imported byte-identical, private repository tag `pre-cal-freeze`).
FIVE_REMOVALS = {
    CHEM_NEW1: {"p1_frame": 220, "p2_becoming": 340},
    CHEM_NEW2: {"p1_frame": 198, "p2_becoming": 306},
    CHEM_2003: {"p1_frame": 187, "p2_becoming": 289},
    MATH_NEW1: {"p1_frame": 55, "p2_becoming": 85},
    MATH_NEW2: {"p1_frame": 22, "p2_becoming": 34},
}
FIELD_OF = {CHEM_NEW1: "chemistry", CHEM_NEW2: "chemistry", CHEM_2003: "chemistry",
            MATH_NEW1: "math_stats", MATH_NEW2: "math_stats"}


def _legacy_frame(fld: str, which: str) -> pathlib.Path:
    """The PRE-caliber frozen frame — the byte-identical legacy source of the pre-freeze
    `data/frames/` copy (see tools/import_frozen.py's pre-freeze mapping)."""
    if fld == "econ":
        return ECON_FNFIX / "data" / ("analysis_frame_econ920_unified_fullsnap_2026-08-13.csv"
                                      if which == "p1" else "becoming_unified.csv")
    if which == "p1":
        return GOLD / "data" / "fnfix" / f"analysis_frame_{fld}_new_gold_2026-08-10.csv"
    return GOLD / "data" / "fnfix" / f"panels23_{fld}_gold" / "becoming_none.csv"


@needs_legacy_thesis
def test_expected_colleague_row_removals_for_task3_are_pinned_and_true():
    """The expectations CSV must agree with BOTH the pinned literals here and a live recount of
    the PRE-caliber frozen frames it was measured against — so Task 3's row-level accounting had a
    checked baseline. (Post-freeze, `data/frames/` holds the caliber result of those expectations:
    the network-channel rows gone, the dept-channel seats persisting — pinned value-by-value in
    tests/test_cal_frames_2026_08_28.py.)"""
    import duckdb
    con = duckdb.connect()
    exp = _expectations()
    for aid, want in FIVE_REMOVALS.items():
        fld = FIELD_OF[aid]
        p1 = con.execute(f"SELECT count(*) FROM read_csv_auto('{_legacy_frame(fld, 'p1').as_posix()}') "
                         f"WHERE incumbent_person_id='{aid}'").fetchone()[0]
        p2 = con.execute(f"SELECT count(*) FROM read_csv_auto('{_legacy_frame(fld, 'p2').as_posix()}') "
                         f"WHERE pid='{aid}'").fetchone()[0]
        assert (p1, p2) == (want["p1_frame"], want["p2_becoming"]), aid
        for layer, n in (("p1_frame", p1), ("p2_becoming", p2)):
            row = exp[(aid, layer)]
            assert int(row["rows"]) == n
            assert row["task3_expectation"] == "removed"
    # and none of the five appears as a star in the PRE-caliber frames (they enter only under cal);
    # in the promoted data/frames they now DO — asserted the other way round on the caliber side
    for aid, fld in FIELD_OF.items():
        n = con.execute(f"SELECT count(*) FROM read_csv_auto('{_legacy_frame(fld, 'p1').as_posix()}') "
                        f"WHERE star_person_id LIKE '%{aid}%'").fetchone()[0]
        assert n == 0, aid
    import csv as _csv
    for fld, new_ids in (("chemistry", (CHEM_NEW1, CHEM_NEW2, CHEM_2003)), ("math_stats", (MATH_NEW1, MATH_NEW2))):
        stars = {r["star_person_id"] for r in _csv.DictReader(
            (REPO / "data/frames" / f"p1_frame_{fld}.csv").open(encoding="utf-8"))}
        for aid in new_ids:
            assert any(aid in s for s in stars), (fld, aid, "not a star in the promoted frames")


AGE0_EXPECT = {                       # (rows, task3_expectation) in the PRE-caliber econ frames
    "p1_star_side": (1012, "removed"),        # star_person_id P_A5044432173 / event A5044432173:2006
    "p1_colleague_side": (88, "persists"),    # incumbent_person_id P_A5044432173
    "p2_star_side": (1547, "removed"),        # star = A5044432173
    "p2_colleague_side": (136, "persists"),   # pid  = A5044432173
}


@needs_legacy_thesis
def test_age0_star_exposure_rows_expectations_recomputed_from_the_frozen_econ_frames():
    """Measured against the PRE-caliber frames (the T2 baseline, see the FIVE_REMOVALS note);
    the promoted data/frames are then asserted to be the caliber RESULT of these expectations:
    star-side rows gone, colleague-side rows persisting exactly."""
    import duckdb
    con = duckdb.connect()
    p1 = _legacy_frame("econ", "p1").as_posix()
    p2 = _legacy_frame("econ", "p2").as_posix()
    got = {
        "p1_star_side": con.execute(
            f"SELECT count(*) FROM read_csv_auto('{p1}') WHERE star_person_id='P_{AGE0_STAR}'").fetchone()[0],
        "p1_colleague_side": con.execute(
            f"SELECT count(*) FROM read_csv_auto('{p1}') WHERE incumbent_person_id='P_{AGE0_STAR}'").fetchone()[0],
        "p2_star_side": con.execute(
            f"SELECT count(*) FROM read_csv_auto('{p2}') WHERE star='{AGE0_STAR}'").fetchone()[0],
        "p2_colleague_side": con.execute(
            f"SELECT count(*) FROM read_csv_auto('{p2}') WHERE pid='{AGE0_STAR}'").fetchone()[0],
    }
    exp = _expectations()
    for layer, (rows, what) in AGE0_EXPECT.items():
        assert got[layer] == rows, layer
        row = exp[(AGE0_STAR, layer)]
        assert int(row["rows"]) == rows and row["task3_expectation"] == what, layer
    # her star-side p1 rows and her event rows are the same rows (one event, 2006)
    n_ev = con.execute(
        f"SELECT count(*) FROM read_csv_auto('{p1}') WHERE event_id='{AGE0_STAR}:2006'").fetchone()[0]
    assert n_ev == AGE0_EXPECT["p1_star_side"][0]
    # and the 2026-08-28 caliber frames carry the OUTCOME of the expectations
    # (2026-09-23: data/frames/ was promoted to the October caliber, so the 08-28 result is read from its
    # frozen copy data/cal2026-08-28/frames/ — the exact bytes data/frames/ held until the promotion, tag
    # cal-2026-08-28; A5044432173's October rows are a different caliber's fact and are not asserted here)
    cp1 = (REPO / "data/cal2026-08-28/frames/p1_frame_econ.csv").as_posix()
    cp2 = (REPO / "data/cal2026-08-28/frames/p2_becoming_econ.csv").as_posix()
    assert con.execute(f"SELECT count(*) FROM read_csv_auto('{cp1}') "
                       f"WHERE star_person_id='P_{AGE0_STAR}'").fetchone()[0] == 0
    assert con.execute(f"SELECT count(*) FROM read_csv_auto('{cp1}') "
                       f"WHERE incumbent_person_id='P_{AGE0_STAR}'").fetchone()[0] == 88
    assert con.execute(f"SELECT count(*) FROM read_csv_auto('{cp2}') "
                       f"WHERE star='{AGE0_STAR}'").fetchone()[0] == 0
    assert con.execute(f"SELECT count(*) FROM read_csv_auto('{cp2}') "
                       f"WHERE pid='{AGE0_STAR}'").fetchone()[0] == 136


@needs_legacy_thesis
def test_legacy_pair_layer_expectations_for_task3():
    """The P3 pair panels are int-anonymised in the frozen repo frames, so the pair-layer
    expectations are measured against the legacy fnfix intermediates and recorded for Task 3's
    builder-report accounting."""
    import duckdb
    con = duckdb.connect()
    exp = _expectations()
    for aid, fld in FIELD_OF.items():
        p = (GOLD / "data" / "fnfix" / f"panels23_{fld}_gold" / "pairs_none.parquet").as_posix()
        n = con.execute(f"SELECT count(*) FROM read_parquet('{p}') "
                        f"WHERE i_id LIKE '%{aid}%' OR j_id LIKE '%{aid}%'").fetchone()[0]
        row = exp[(aid, "pairs_legacy")]
        assert int(row["rows"]) == n and row["task3_expectation"] == "removed", aid
    pairs = (ECON_FNFIX / "data" / "pairs_unified.csv").as_posix()
    ev = con.execute(f"SELECT count(*) FROM read_csv_auto('{pairs}') "
                     f"WHERE event_id LIKE '{AGE0_STAR}%'").fetchone()[0]
    mem = con.execute(f"SELECT count(*) FROM read_csv_auto('{pairs}') "
                      f"WHERE (i_id LIKE '%{AGE0_STAR}%' OR j_id LIKE '%{AGE0_STAR}%') "
                      f"AND event_id NOT LIKE '{AGE0_STAR}%'").fetchone()[0]
    assert int(exp[(AGE0_STAR, "pairs_event_side")]["rows"]) == ev
    assert exp[(AGE0_STAR, "pairs_event_side")]["task3_expectation"] == "removed"
    assert int(exp[(AGE0_STAR, "pairs_member_side")]["rows"]) == mem
    assert exp[(AGE0_STAR, "pairs_member_side")]["task3_expectation"] == "persists"


# ------------------------------------------------------------------------------------------------
# request custody
# ------------------------------------------------------------------------------------------------

def test_request_log_is_complete_and_carries_no_key():
    raw = REQ_LOG.read_bytes().decode("utf-8")
    assert "api_key" not in raw
    key = supplement_fetch.api_key()
    if key:
        assert key not in raw
    lines = [json.loads(ln) for ln in raw.splitlines() if ln]
    assert lines, "empty request log"
    for e in lines:
        assert e["endpoint"] == "https://api.openalex.org/works"
        assert e["status"] == 200 or e["attempt"] < 5      # non-200s allowed only as retried attempts
    assert len(lines) == _report()["request_total"]


def test_report_totals_are_consistent():
    """The exact per-star identity: supplement rows = works fetched (or cache-sourced) − the
    signed exclusions that were actually present, + (MATH_NEW1 only) the merge works not already on
    that profile."""
    rep = _report()
    assert rep["request_total"] >= 5                     # at least one page per star
    dropped = {}
    for e in rep["exclusions_applied"]:
        if e["dropped"]:
            dropped[e["author_id"]] = dropped.get(e["author_id"], 0) + 1
    # the public report keys this block by author id (`<MATH_NEW1>_merge`)
    merge_block = rep[f"{MATH_NEW1}_merge"]
    merged_in = len(cleaned_works.merge_works(MATH_NEW1)) - len(merge_block["already_on_profile"])
    for aid in FIVE:
        s = rep["stars"][aid]
        want = s["works_fetched_or_cached"] - dropped.get(aid, 0) + (
            merged_in if aid == MATH_NEW1 else 0)
        assert s["supplement_rows"] == want, (aid, s, dropped.get(aid, 0))
        assert s["supplement_rows"] > 0


def test_manifest_covers_the_task2_files():
    man = (CAL / "MANIFEST.sha256").read_text(encoding="utf-8")
    for name in (SUP.name, EXCL_PARQUET.name, EXPECT_CSV.name, REQ_LOG.name, REPORT.name,
                 f"works_{CHEM_NEW1}_2026-08-28.json", f"works_{CHEM_NEW2}_2026-08-28.json",
                 f"works_{MATH_NEW1}_2026-08-28.json", f"works_{MATH_NEW2}_2026-08-28.json",
                 f"works_{CHEM_2003}_live_2026-08-28.json", "works_A5083852619_merge_2026-08-28.json"):
        assert f"data/cal2026-08-28/{name}" in man, name
