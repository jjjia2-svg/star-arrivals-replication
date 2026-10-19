"""R1 F21 (W2-ORIGINS): Figure 1's inputs for the M event set.

  * tools/star_origins_extract_2026-10.py takes the run's event tables (--events-dir) and an output dir
    (--out-dir), reuses the frozen October extraction where nothing changed (--from-frozen: only new
    stars and raised year caps are scanned; reused rows must be a subset of the frozen rows), and merges
    the human origin overrides: October rows re-keyed through alias_event(), rows of events not in the
    run dropped and listed, r1 rows appended; a re-dated event with an October override needs an r1
    confirmation row (fail closed).
  * analysis/paper/fig_star_origins.py keys the overrides by (discipline, star_id, arrival_year), so an
    override follows its event when rows move; alias_event() maps an October event onto the run's.
  * analysis/paper/fig_star_origins_dots.py takes its event counts from canon.counts(), not literals, and
    keeps each discipline one connected run at R1's counts (a serpentine fill only where the 2026-10-01
    left-to-right fill would split a run; every October block keeps that fill); in the Europe panel a block
    taller than five rows takes rows of 20 and grows west, so R1's UK block leaves England visible.

Toy worlds in tmp_path only (duckdb writes one toy person-map parquet there); the October-mode tests read
the pinned repo inputs. The one full-scan control reads the data disk and is marked ssd (big host, B4)."""
from __future__ import annotations

import copy
import csv
import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import analysis.paper.fig_star_origins as F  # noqa: E402
import analysis.paper.fig_star_origins_dots as D  # noqa: E402

X_PATH = REPO / "tools" / "star_origins_extract_2026-10.py"
FROZEN = REPO / "data" / "paper_inputs" / "star_origins_2026-10"
FOUR = ("star_author_ids.csv", "affiliation_years.csv", "institutions.csv", "destinations.csv")
#: the U1 input October's extraction read (the 2026-09-23 mirror: 120 of 256 11-school works_affil files)
VIEW_0923 = REPO / "config" / "r1" / "star_origins_u1_view_2026-09-23.json"
OCT_COLS = ["discipline", "event_row", "star_id", "school", "arrival_year", "placement", "institution_id",
            "coords_from", "country_code", "human_evidence", "source_docs"]
R1_COLS = OCT_COLS + ["carried_from", "recheck"]
ECON_HDR = ["event_id", "star_id", "school", "arrival_year"]
CM_HDR = ["field", "school", "author_id", "display_name", "arrival_corrected"]


def _x():
    spec = importlib.util.spec_from_file_location("star_origins_extract", X_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _wcsv(p: pathlib.Path, header, rows) -> pathlib.Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    return p


def _events_dir(d: pathlib.Path, econ, chem=(), maths=()) -> pathlib.Path:
    """econ: [(star, school, year)]; chem / maths: [(star, school, year)] -> October-layout event tables."""
    _wcsv(d / "events_econ_cal2026-10.csv", ECON_HDR, [(f"{s}:{y}", s, sc, y) for s, sc, y in econ])
    for f, rows in (("chemistry", chem), ("math_stats", maths)):
        _wcsv(d / f"events_{f}_cal2026-10.csv", CM_HDR, [(f, sc, s, "Toy", y) for s, sc, y in rows])
    return d


def _ovr(disc, row, star, school, year, *, carried_from=None, recheck=None, iid="I1", cc="US"):
    r = {"discipline": disc, "event_row": str(row), "star_id": star, "school": school, "arrival_year": str(year),
         "placement": "human_institution", "institution_id": iid, "coords_from": "", "country_code": cc,
         "human_evidence": "Toy University", "source_docs": "repo:toy"}
    if carried_from is not None:
        r.update(carried_from=carried_from, recheck=recheck or "")
    return r


# ---------------------------------------------------------------------------------------------------
# a toy world for the incremental path: everything is reused, so no snapshot partition is ever opened
# ---------------------------------------------------------------------------------------------------
def _toy_world(tmp: pathlib.Path, X) -> dict:
    ssd = tmp / "disk" / "openalex_pipeline"
    pm = ssd / "derived" / "u2_person_map_11school_2026-07-16" / "person_map" / "data.parquet"
    pm.parent.mkdir(parents=True)
    import duckdb
    duckdb.connect().execute(
        "COPY (SELECT * FROM (VALUES ('P1', 'A100'), ('P2', 'A900')) t(person_id, author_id)) "
        f"TO '{pm}' (FORMAT PARQUET)")
    snap = ssd / "snapshot"
    for k in ("authors", "institutions"):
        (snap / k).mkdir(parents=True)
        (snap / k / "manifest.json").write_text(json.dumps({"toy": k}), encoding="utf-8")
    fz_ev = _events_dir(tmp / "frozen_events", [("A100", "anu", 2010)], [("A200", "monash", 2012)])
    fz = tmp / "frozen"
    _wcsv(fz / "star_author_ids.csv", ["field", "star_id", "author_id", "role"],
          [("chemistry", "A200", "A200", "star"), ("econ", "A100", "A100", "star")])
    aff = [("A100", "I1", y, "US", "1") for y in range(2005, 2011)] + [("A200", "I2", 2011, "GB", "2")]
    _wcsv(fz / "affiliation_years.csv", ["author_id", "institution_id", "year", "country_code_aff", "n_works"], aff)
    inst = [("I1", "Toy U", "US", "education", "Boston", "42.3", "-71.1", "1"),
            ("I2", "Toy C", "GB", "education", "London", "51.5", "-0.1", "1")]
    inst += [(iid, f"Dest {s}", "AU", "education", "Sydney", "-33.9", "151.2", "1") for s, iid in X.SCHOOL_INST.items()]
    _wcsv(fz / "institutions.csv", ["institution_id", "display_name", "country_code", "type", "city", "latitude",
                                    "longitude", "in_snapshot"], sorted(inst))
    _wcsv(fz / "destinations.csv", ["school", "institution_id"], sorted(X.SCHOOL_INST.items()))
    rep = {"inputs_sha256": {f"toy/events_{f}_cal2026-10.csv": _sha(fz_ev / f"events_{f}_cal2026-10.csv")
                             for f in ("econ", "chemistry", "math_stats")},
           "snapshot_manifest_sha256": {k: _sha(snap / k / "manifest.json") for k in ("authors", "institutions")}}
    (fz / "extract_report.json").write_text(json.dumps(rep), encoding="utf-8")
    (fz / "MANIFEST.sha256").write_text("".join(f"{_sha(fz / n)}  toy/frozen/{n}\n" for n in sorted(
        ("star_author_ids.csv", "affiliation_years.csv", "institutions.csv", "destinations.csv",
         "extract_report.json"))), encoding="utf-8")
    corr = _wcsv(tmp / "corrections.csv", ["old_id", "new_id", "field", "school", "arrival", "evidence"], [])
    octo = _wcsv(tmp / "october_overrides.csv", OCT_COLS, [])
    r1 = _wcsv(tmp / "r1_overrides.csv", R1_COLS, [])
    return {"ssd": ssd, "frozen": fz, "frozen_events": fz_ev, "aff": aff, "corr": corr, "october": octo, "r1": r1}


def _paths(world):
    return lambda *a, **k: {"ssd_root": world["ssd"], "cal": REPO / "data" / "cal2026-10"}


def test_earlier_redate_drops_exactly_the_later_years(tmp_path, monkeypatch):
    """Frozen rows for a star capped 2010; the run's event is 2008 -> its rows are exactly the frozen rows with
    year <= 2008, nothing is scanned (no snapshot partition exists in the toy world)."""
    X = _x()
    w = _toy_world(tmp_path, X)
    ev = _events_dir(tmp_path / "events", [("A100", "anu", 2008)], [("A200", "monash", 2012)])
    dec = tmp_path / "events_decision.json"
    dec.write_text(json.dumps({"id_corrected": {}, "redated": [
        {"field": "econ", "star": "A100", "old_event": "A100:2010", "new_event": "A100:2008",
         "old_year": 2010, "new_year": 2008, "source": "toy"}]}), encoding="utf-8")
    out, report = tmp_path / "out", tmp_path / "report_star_origins.json"
    monkeypatch.setattr(X, "load_paths", _paths(w))
    X.main(["--events-dir", str(ev), "--out-dir", str(out), "--from-frozen", str(w["frozen"]),
            "--frozen-events", str(w["frozen_events"]), "--id-corrections", str(w["corr"]),
            "--events-decision", str(dec), "--october-overrides", str(w["october"]),
            "--r1-overrides", str(w["r1"]), "--report", str(report), "--workers", "1"])
    got = list(csv.reader(open(out / "affiliation_years.csv", newline="", encoding="utf-8")))[1:]
    want = [[a, i, str(y), c, n] for a, i, y, c, n in w["aff"] if a != "A100" or y <= 2008]
    assert sorted(got) == sorted(want)
    assert {r[2] for r in got if r[0] == "A100"} == {"2005", "2006", "2007", "2008"}
    rep = json.loads(report.read_text(encoding="utf-8"))
    assert rep["scanned"]["ids"] == [] and sorted(rep["reused"]["ids"]) == ["A100", "A200"]
    assert rep["counts"]["n_authors_scanned"] == 0 and rep["counts"]["n_institutions_scanned"] == 0
    # the merged override table exists (nothing pending) and carries the r1 columns
    with open(out / "human_origin_overrides.csv", newline="", encoding="utf-8") as fh:
        assert next(csv.reader(fh)) == R1_COLS
    for name in FOUR:
        assert (out / name).is_file(), name


def test_scan_only_new_stars_and_raised_caps():
    X = _x()
    new_sa = {"S1": {("A1", "star")}, "S2": {("A2", "star")}, "S3": {("A3", "star")},
              "S4": {("A4", "star"), ("A44", "u2_fragment")}}
    new_cap = {"A1": 2008, "A2": 2015, "A3": 2012, "A4": 2009, "A44": 2009}
    frozen_sa = {"S1": {("A1", "star")}, "S2": {("A2", "star")}, "S4": {("A4", "star")}}
    frozen_cap = {"A1": 2010, "A2": 2010, "A4": 2010}
    plan = X.plan_reuse(new_sa, new_cap, frozen_sa, frozen_cap)
    assert plan["reuse_stars"] == ["S1"]                      # same ids, earlier cap
    assert plan["scan_stars"] == ["S2", "S3", "S4"]           # raised cap, new star, changed id set
    assert plan["reuse_ids"] == ["A1"] and plan["scan_ids"] == ["A2", "A3", "A4", "A44"]
    frozen = {("A1", "I1", y): ("US", "1") for y in range(2005, 2011)}
    frozen[("A2", "I2", 2009)] = ("GB", "3")
    rows = X.reuse_rows(frozen, plan["reuse_ids"], new_cap)
    assert sorted(rows) == [("A1", "I1", y) for y in range(2005, 2009)]
    X.check_reused(rows, plan["reuse_ids"], frozen)                       # a subset: passes
    bad = dict(rows)
    bad[("A1", "I9", 2007)] = ("FR", "1")                                 # injected extra row
    with pytest.raises(AssertionError):
        X.check_reused(bad, plan["reuse_ids"], frozen)
    bad = dict(rows)
    bad[("A1", "I1", 2007)] = ("US", "5")                                 # a changed value is not a subset either
    with pytest.raises(AssertionError):
        X.check_reused(bad, plan["reuse_ids"], frozen)


def test_override_follows_its_event_when_rows_move():
    """Insert an event at the top of the economics table: every later event_row moves by one, and every human
    override still lands on its own event (keyed by star and year, not by row)."""
    inp = F.load_inputs()
    ev0, L0 = F.compute(inp)
    moved = dict(inp)
    fake = {"field": "econ", "prefix": "econ", "event_row": 1, "school": "adelaide", "star": "A0000000001",
            "arrival": 2006}
    shifted = [dict(e, event_row=e["event_row"] + 1) if e["field"] == "econ" else e for e in inp["events"]]
    moved["events"] = [fake] + shifted
    ev1, L1 = F.compute(moved)
    before = {(r["discipline"], r["event_row"]): r for r in ev0}
    after = {(r["discipline"], r["event_row"] - (r["discipline"] == "econ")): r for r in ev1}
    assert after.pop(("econ", 0))["origin_status"] == "unknown"
    assert set(after) == set(before)
    for k, r in before.items():
        a = after[k]
        assert (a.get("origin_source"), a.get("origin_institution_id"), a.get("origin_country")) == (
            r.get("origin_source"), r.get("origin_institution_id"), r.get("origin_country")), k
    assert L1["pooled_origin_source_human"] == L0["pooled_origin_source_human"] == 89


def test_alias_event_id_correction_and_redate():
    X = _x()
    corr = {"A5090515599": "A5091326353"}
    assert F.alias_event("A5090515599", 2009, corrections=corr, redates={}) == ("A5091326353", 2009)
    assert F.alias_event("A5028731684", 2010, corrections=corr,
                         redates={("A5028731684", 2010): 2008}) == ("A5028731684", 2008)
    assert F.alias_event("A1", 2001, corrections={}, redates={}) == ("A1", 2001)
    # through the corrected id: the redate is keyed by the id the run uses
    assert F.alias_event("A5090515599", 2009, corrections=corr,
                         redates={("A5091326353", 2009): 2010}) == ("A5091326353", 2010)
    with pytest.raises(SystemExit, match="cycle"):
        F.alias_event("A1", 2001, corrections={"A1": "A2", "A2": "A1"}, redates={})

    # the run: B moved up one row (an event inserted before it), R re-dated 2010 -> 2008, G not in the run
    events = [{"field": "econ", "star_id": "A9", "school": "uwa", "arrival": 2015, "event_row": 1},
              {"field": "econ", "star_id": "A5091326353", "school": "uwa", "arrival": 2009, "event_row": 2},
              {"field": "econ", "star_id": "A5028731684", "school": "anu", "arrival": 2008, "event_row": 3}]
    october = [_ovr("econ", 1, "A5090515599", "uwa", 2009),
               _ovr("econ", 2, "A5028731684", "anu", 2010),
               _ovr("chemistry", 7, "A777", "monash", 2011)]
    red = {("A5028731684", 2010): 2008}
    with pytest.raises(SystemExit, match="A5028731684:2008"):
        X.merge_overrides(october, [], events, corrections=corr, redates=red, strict=True)
    soft = X.merge_overrides(october, [], events, corrections=corr, redates=red, strict=False)
    assert soft["unconfirmed"] == ["A5028731684:2008"] and soft["dropped"] == ["A777:2011"]
    conf = _ovr("econ", "", "A5028731684", "anu", 2008, carried_from="october:econ:A5028731684:2010",
                recheck="claude drafter + checker agree", iid="I5", cc="GB")
    m = X.merge_overrides(october, [conf], events, corrections=corr, redates=red, strict=True)
    assert m["unconfirmed"] == [] and m["dropped"] == ["A777:2011"]
    by = {(r["discipline"], r["star_id"], r["arrival_year"]): r for r in m["rows"]}
    assert set(by) == {("econ", "A5091326353", "2009"), ("econ", "A5028731684", "2008")}
    b = by[("econ", "A5091326353", "2009")]
    assert b["event_row"] == "2" and b["carried_from"] == "october:econ:A5090515599:2009" and b["recheck"] == ""
    r = by[("econ", "A5028731684", "2008")]
    assert (r["event_row"], r["institution_id"], r["country_code"]) == ("3", "I5", "GB")
    assert all(list(row) == R1_COLS for row in m["rows"])
    # an r1 row for an event that is not in the run, or naming an October row that does not exist, stops
    with pytest.raises(SystemExit, match="A8"):
        X.merge_overrides(october, [_ovr("econ", "", "A8", "uwa", 2001, carried_from="", recheck="x")], events,
                          corrections=corr, redates=red, strict=True)
    with pytest.raises(SystemExit, match="october:econ:A1:1999"):
        X.merge_overrides(october, [dict(conf, carried_from="october:econ:A1:1999")], events,
                          corrections=corr, redates=red, strict=True)
    # a second row for one event stops
    dup = _ovr("econ", "", "A5091326353", "uwa", 2009, carried_from="", recheck="x")
    with pytest.raises(SystemExit, match="duplicate"):
        X.merge_overrides(october, [conf, dup], events, corrections=corr, redates=red, strict=True)


def test_dots_counts_come_from_the_events(monkeypatch):
    """The dots module's counts come from canon.counts() (October: 113 / 38 / 33), not from literals: a toy
    run of 5 events passes check_events, and a count that disagrees with the events fails."""
    assert D.expected_counts() == {"econ": 113, "chemistry": 38, "math_stats": 33}
    toy = {"schema": "sar.r1.counts.v1", "config": "M", "events": {"econ": 3, "chemistry": 1, "math_stats": 1},
           "events_total": 5, "candidates": 5}
    monkeypatch.setattr(D.canon, "counts", lambda *a, **k: copy.deepcopy(toy))
    assert D.expected_counts() == {"econ": 3, "chemistry": 1, "math_stats": 1}
    ev = [{"discipline": d, "event_row": k, "origin_status": "found", "origin_country": cc}
          for d, k, cc in (("econ", 1, "US"), ("econ", 2, "GB"), ("econ", 3, "US"), ("chemistry", 1, "US"),
                           ("math_stats", 1, "DE"))]
    L = {"econ_country_counts": {"US": 2, "GB": 1}, "chem_country_counts": {"US": 1},
         "math_country_counts": {"DE": 1}, "pooled_country_counts": {"US": 3, "GB": 1, "DE": 1}}
    rows = D.check_events(ev, L)
    assert len(rows) == 5 and [r["discipline"] for r in rows] == ["econ"] * 3 + ["chemistry", "math_stats"]
    toy["events"]["econ"], toy["events_total"] = 4, 6
    with pytest.raises(AssertionError):
        D.check_events(ev, L)


def _disc(econ: int, chem: int, maths: int) -> list[str]:
    return ["econ"] * econ + ["chemistry"] * chem + ["math_stats"] * maths


def test_dot_blocks_keep_each_discipline_one_run():
    """Figure 1's blocks: a block that the 2026-10-01 fill (10 per row, left to right, bottom row first) keeps in
    one connected run per discipline is filled exactly that way (every October block, e.g. 34/3/14 and 27/15/7);
    one it splits (R1 counts: CA 10/2/9, NZ 9/7/1, CH 5/4/4, DE 7/12/10, FR 5/2/6) is filled serpentine (odd rows
    right to left), which keeps any run of consecutive dots connected. The white backing covers exactly the
    filled cells, and make_blocks no longer stops on an R1 count."""
    left_to_right = lambda n: [(k % D.ROW, k // D.ROW) for k in range(n)]   # noqa: E731
    for counts in ((34, 3, 14), (27, 15, 7), (4, 2, 3), (6, 1, 2), (5, 1, 2), (4, 3, 1), (4, 2, 0)):
        disc = _disc(*counts)
        assert D.block_fill(disc) is False, counts
        assert D.fill_cells(len(disc), False) == D.fill_cells(len(disc)) == left_to_right(len(disc))
    for counts in ((10, 2, 9), (9, 7, 1), (5, 4, 4), (7, 12, 10), (5, 2, 6)):
        disc = _disc(*counts)
        with pytest.raises(AssertionError, match="split"):
            D.assert_runs_connected("XX", disc, False)
        assert D.block_fill(disc) is True, counts
    for e in range(25):
        for c in range(25):
            for m in range(25):
                disc = _disc(e, c, m)
                if not disc:
                    continue
                serp = D.block_fill(disc)
                D.assert_runs_connected("XX", disc, serp)
                cells = D.fill_cells(len(disc), serp)
                spans = D.backing_spans(len(disc), serp)
                covered = [(i, j) for c0, c1, r0, r1 in spans for j in range(r0, r1) for i in range(c0, c1)]
                assert sorted(covered) == sorted(cells) and len(set(covered)) == len(covered), (e, c, m)
    group = [{"discipline": d, "origin_lon": -100.0, "origin_lat": 50.0} for d in _disc(10, 2, 9)]
    B = D.make_blocks({"CA": group}, D.w_proj, 0.3, {})
    assert B[0]["serp"] is True and len(D.dot_centres(B[0], 0.3)) == 21


def _october_layout():
    """October's events and solve_layout (computed from the pinned repo inputs; nothing is drawn)."""
    ev, L = F.compute()
    rows = D.check_events(ev, L)
    return rows, D.solve_layout(rows, D.load_land())


def test_big_europe_block_takes_rows_of_twenty_and_leaves_england_visible():
    """Figure 1's Europe panel (R1 counts): a block may be at most EU_MAX_ROWS = 5 rows tall (October's tallest
    there, the UK's 49 dots, keeps rows of ten and its place exactly); a larger one takes rows of 20 (30, ...) and
    keeps the east edge a ten-wide block would have, growing west, away from the continent. At R1's 96 UK dots
    (37/37/22) a ten-wide block (10 rows) covers York and Sheffield at its target; twenty wide (5 rows) it covers
    Aberdeen and leaves the five named cities clear. The world map keeps rows of ten at any height (R1's US block,
    101 dots, passes every world check in 11 rows)."""
    assert D.EU_MAX_ROWS == 5
    assert [D.block_row(n) for n in (1, 51, 101, 500)] == [10] * 4
    assert [D.block_row(n, 5) for n in (1, 49, 50, 51, 96, 100, 101)] == [10, 10, 10, 20, 20, 20, 30]
    _rows, S = _october_layout()
    u = S["u_e"]
    assert all(b["row"] == D.ROW for b in S["Bw"] + S["Be"])
    assert D.block_rules(S["Bw"] + S["Be"]) == {"serpentine": [], "wide": {}}
    gb = {b["cc"]: b for b in S["Be"]}["GB"]
    tx, ty = (float(v) for v in D.eu_proj(*D.EU_TARGET["GB"][1:]))
    assert (gb["cols"], gb["rows"], gb["ax"], gb["ay"]) == (10, 5, tx, ty)
    big = [{"discipline": d, "origin_lon": -0.13, "origin_lat": 51.5} for d in _disc(37, 37, 22)]

    def covers(b, lon, lat):
        x, y = D.eu_proj(lon, lat)
        return abs(float(x) - b["ax"]) <= b["hw"] and abs(float(y) - b["ay"]) <= b["hh"]
    ten = D.make_blocks({"GB": big}, D.eu_proj, u, D.EU_TARGET)[0]
    assert (ten["cols"], ten["rows"]) == (10, 10) and covers(ten, *D.UK_VISIBLE["York"])
    wide = D.make_blocks({"GB": big}, D.eu_proj, u, D.EU_TARGET, max_rows=D.EU_MAX_ROWS)[0]
    assert (wide["cols"], wide["rows"], wide["row"]) == (20, 5, 20)
    assert abs((wide["ax"] + wide["hw"]) - (ten["ax"] + ten["hw"])) < 1e-12
    assert not any(covers(wide, *ll) for ll in D.UK_VISIBLE.values())
    assert all(covers(wide, *ll) for ll in D.UK_COVERED.values())
    assert D.block_rules([wide]) == {"serpentine": [], "wide": {"GB": 20}}
    cells = D.fill_cells(96, wide["serp"], 20)
    assert len(D.dot_centres(wide, u)) == 96 and max(i for i, _j in cells) == 19
    for n in range(1, 130):                    # rows of 20: the backing still covers exactly the filled cells
        for serp in (False, True):
            spans = D.backing_spans(n, serp, 20)
            covered = [(i, j) for c0, c1, r0, r1 in spans for j in range(r0, r1) for i in range(c0, c1)]
            assert sorted(covered) == sorted(D.fill_cells(n, serp, 20)), (n, serp)


def test_figure_rule_names_the_r1_block_exceptions():
    """The ledger's _figure_rule keeps October's words when no block is serpentine or widened, and otherwise
    names the blocks that are."""
    base = {"texts": [], "size_cm": (15.0, 12.0), "nudge_mm": {}}
    october = F.figure_ledger(base)["_figure_rule"]
    assert F.figure_ledger({**base, "block_rules": {"serpentine": [], "wide": {}}})["_figure_rule"] == october
    r = F.figure_ledger({**base, "block_rules": {"serpentine": ["CA", "DE"], "wide": {"GB": 20}}})["_figure_rule"]
    assert r.startswith(october) and "GB 20 per row" in r and "CA, DE" in r and r != october


def test_figure_ledger_lists_the_block_exceptions_as_a_key_only_when_there_are_any():
    """Codex STOP 2: rows of 20 make the caption's 'grouped in rows of ten' false, and the exceptions sat only in
    _figure_rule's words, which nothing reads. They are a structured ledger key (figure_block_exceptions: the base
    row width, the serpentine blocks, the widened blocks with their dots per row) that gate 2 reads, written only
    when a block leaves the 2026-10-01 fill: October's ledger keeps its four figure keys, unchanged."""
    base = {"texts": [], "size_cm": (15.0, 12.0), "nudge_mm": {}}
    october = F.figure_ledger(base)
    assert F.FIGURE_EXCEPTIONS_KEY == "figure_block_exceptions"
    assert set(october) == {"_figure_rule", "figure_text", "figure_size_cm", "figure_destination_nudge_mm"}
    assert F.figure_ledger({**base, "block_rules": {"serpentine": [], "wide": {}}}) == october
    m = F.figure_ledger({**base, "block_rules": {"serpentine": ["CA", "CH", "DE", "FR", "NZ"], "wide": {"GB": 20}}})
    assert m[F.FIGURE_EXCEPTIONS_KEY] == {"rows_of": 10, "serpentine": ["CA", "CH", "DE", "FR", "NZ"], "wide": {"GB": 20}}
    assert set(m) == set(october) | {F.FIGURE_EXCEPTIONS_KEY}
    serp = F.figure_ledger({**base, "block_rules": {"serpentine": ["CA"], "wide": {}}})
    assert serp[F.FIGURE_EXCEPTIONS_KEY] == {"rows_of": 10, "serpentine": ["CA"], "wide": {}}


def test_out_dir_rules(tmp_path, monkeypatch):
    """--out-dir is required for a run's events and may not be October's frozen folder; October's own events
    may write there (the default)."""
    X = _x()
    w = _toy_world(tmp_path, X)
    ev = _events_dir(tmp_path / "events", [("A100", "anu", 2008)])
    monkeypatch.setattr(X, "load_paths", _paths(w))
    common = ["--id-corrections", str(w["corr"]), "--october-overrides", str(w["october"]),
              "--r1-overrides", str(w["r1"]), "--events-decision", str(tmp_path / "none.json")]
    with pytest.raises(SystemExit, match="--out-dir"):
        X.main(["--events-dir", str(ev)] + common)
    with pytest.raises(SystemExit, match="star_origins_2026-10"):
        X.main(["--events-dir", str(ev), "--out-dir", str(FROZEN)] + common)
    with pytest.raises(SystemExit, match="--frozen-events"):
        X.main(["--events-dir", str(ev), "--out-dir", str(tmp_path / "o"), "--from-frozen", str(w["frozen"])]
               + common)
    with pytest.raises(SystemExit, match="October"):         # merge flags make no sense for October's events
        X.main(["--out-dir", str(tmp_path / "o2"), "--r1-overrides", str(w["r1"])])


def _u1_toy(root: pathlib.Path, n: int = 4) -> pathlib.Path:
    """<root>/derived/<both U1 tables>/<works_affil, authorship_edges>/bucket=00k/part-00000.parquet holding
    k+1 dummy bytes: the input guard lists files and sizes and never opens one."""
    X = _x()
    for d in X.U1_DIRS:
        for sub in X.U1_SUBTABLES:
            for k in range(n):
                f = root / "derived" / d / sub / f"bucket={k:03d}" / "part-00000.parquet"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(b"P" * (k + 1))
    return root / "derived"


def test_u1_input_guard_refuses_a_partial_table_and_reads_a_recorded_view_exactly(tmp_path):
    """t-big-03: October's n_works were counted on a mirror holding 120 of the 11-school works_affil's 256 bucket
    files (a killed aws s3 sync: 116 empty bucket directories, 20 unfinished temp files that the '**/*.parquet'
    glob skipped), so a complete-table rerun counts more works. The extractor now lists its U1 inputs before the
    count: an unfinished temp file, an empty bucket directory or a bucket set unlike the sibling subtable's is a
    STOP; a recorded view (--u1-view) is read file for file with its sizes checked."""
    X = _x()
    derived = _u1_toy(tmp_path)
    src, rec = X.u1_sources(derived, None)
    assert set(src) == {(d, s) for d in X.U1_DIRS for s in X.U1_SUBTABLES}
    assert all(len(v) == 4 for v in src.values())
    assert rec["u1_full_11school_2026-07-16/works_affil"] == {"source": "glob", "files": 4, "bytes": 10,
                                                              "bucket_dirs": 4}
    wa = derived / "u1_full_11school_2026-07-16" / "works_affil"
    (wa / "bucket=003" / "part-00000.parquet").rename(wa / "bucket=003" / "part-00000.parquet.a1B2c3D4")
    with pytest.raises(SystemExit, match="U1_PARTIAL .*works_affil"):
        X.u1_sources(derived, None)
    view = {"schema": X.VIEW_SCHEMA, "tables": {"u1_full_11school_2026-07-16": {"works_affil": {
        "files": {"bucket=000/part-00000.parquet": 1, "bucket=002/part-00000.parquet": 3}}}}}
    src, rec = X.u1_sources(derived, view)
    assert [p.relative_to(wa).as_posix() for p in src[("u1_full_11school_2026-07-16", "works_affil")]] == \
        ["bucket=000/part-00000.parquet", "bucket=002/part-00000.parquet"]
    assert rec["u1_full_11school_2026-07-16/works_affil"] == {"source": "view", "files": 2, "bytes": 4}
    assert len(src[("u1_full_11school_2026-07-16", "authorship_edges")]) == 4     # not in the view: read whole
    bad = copy.deepcopy(view)
    bad["tables"]["u1_full_11school_2026-07-16"]["works_affil"]["files"]["bucket=002/part-00000.parquet"] = 9
    with pytest.raises(SystemExit, match="U1_VIEW_MISMATCH"):
        X.u1_sources(derived, bad)
    (wa / "bucket=003" / "part-00000.parquet.a1B2c3D4").unlink()                   # leaves an empty bucket dir
    with pytest.raises(SystemExit, match="U1_PARTIAL"):
        X.u1_sources(derived, None)
    shutil.rmtree(wa / "bucket=003")                                               # 3 buckets vs the edges' 4
    with pytest.raises(SystemExit, match="U1_PARTIAL"):
        X.u1_sources(derived, None)
    with pytest.raises(SystemExit, match="view"):
        X.check_view({"schema": X.VIEW_SCHEMA, "tables": {"u1_full_11school_2026-07-16": {"works": {"files": {}}}}})


def test_the_recorded_september_view_is_the_partial_works_affil():
    X = _x()
    v = json.loads(VIEW_0923.read_text(encoding="utf-8"))
    X.check_view(v)
    t = v["tables"]["u1_full_11school_2026-07-16"]["works_affil"]
    assert len(t["files"]) == 120 and t["n_bucket_dirs"] == 256 and len(t["unfinished_temp_files"]) == 20
    assert sorted(t["files"]) == [f"bucket={b}/part-00000.parquet" for b in t["buckets_present"]]
    assert sum(t["files"].values()) == 5_398_503_077
    assert set(v["tables"]) == {"u1_full_11school_2026-07-16"}                      # nothing else was partial


def _full_scan(out: pathlib.Path, *extra: str) -> dict:
    workers = str(max(1, min(32, os.cpu_count() or 1)))
    r = subprocess.run([sys.executable, str(X_PATH), "--out-dir", str(out), "--workers", workers, *extra],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-4000:]
    return json.loads((out / "extract_report.json").read_text(encoding="utf-8"))


@pytest.mark.ssd
def test_full_scan_of_october_events_reproduces_frozen(tmp_path):
    """Big host (B4, r1/snapshot/{authors,institutions} synced): the extractor run on October's events without
    --from-frozen, reading the U1 input October read (--u1-view: the 120 of 256 11-school works_affil files on
    the 2026-09-23 mirror, config/r1/star_origins_u1_view_2026-09-23.json), rewrites the four frozen CSVs byte
    for byte. t-big-03 ran it on the complete table: n_works differed at byte 86 (A5000292946 x I130343225 x
    2008: frozen 0, complete 1)."""
    rep = _full_scan(tmp_path / "full", "--u1-view", str(VIEW_0923))
    assert rep["u1_inputs"]["u1_full_11school_2026-07-16/works_affil"]["files"] == 120
    for name in FOUR:
        assert (tmp_path / "full" / name).read_bytes() == (FROZEN / name).read_bytes(), name


@pytest.mark.ssd
def test_full_scan_on_the_complete_u1_tables_only_adds_works(tmp_path):
    """The same scan on the complete tables (no view; the guard passes): ids, institutions and destinations
    are October's byte for byte and the affiliation rows are October's; only n_works moves, and only up (the
    136 missing buckets hid works and added none)."""
    out = tmp_path / "complete"
    rep = _full_scan(out)
    assert rep["u1_inputs"]["u1_full_11school_2026-07-16/works_affil"]["files"] == 256
    for name in ("star_author_ids.csv", "institutions.csv", "destinations.csv"):
        assert (out / name).read_bytes() == (FROZEN / name).read_bytes(), name

    def rows(p):
        with open(p, newline="", encoding="utf-8") as fh:
            return {(r["author_id"], r["institution_id"], r["year"], r["country_code_aff"]): int(r["n_works"])
                    for r in csv.DictReader(fh)}
    new, old = rows(out / "affiliation_years.csv"), rows(FROZEN / "affiliation_years.csv")
    assert set(new) == set(old)
    assert all(new[k] >= old[k] for k in old)
    assert sum(new[k] > old[k] for k in old) >= 1
