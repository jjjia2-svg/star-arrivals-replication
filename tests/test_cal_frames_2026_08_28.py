# -*- coding: utf-8 -*-
"""cal2026-08-28 Task 3 — the frames rebuild under the author-signed caliber.

Written red-first: the artifact tests fail until `run_cal_frames.py --execute` has produced
`data/cal2026-08-28/frames/`. The pins come from three places, each named at the assert:
  * T1/T2's frozen cal tables (event counts, the Task-3 expectations CSV);
  * the frozen frames themselves (row counts, the removed econ star's / the five's measured rows);
  * the driver's own frozen run report (controls, accounting closure, pin evaluation) — the
    report is DATA here, so a test cannot pass without the run having really happened.
"""
from __future__ import annotations

import csv
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO / "tests") not in sys.path:
    sys.path.insert(0, str(REPO / "tests"))
from _cal_paths import cal_frame, cal_frame_rel, pinned_sha  # noqa: E402
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))
sys.path.insert(0, str(REPO / "pipeline/stars/caliber_2026-08-28"))

import frames_stage as fs                                             # noqa: E402

CAL = REPO / "data" / "cal2026-08-28"
OUT = CAL / "frames"
#: the econ star the caliber removed (academic-age gate) and that event
AGE0_STAR, AGE0_EVENT = "A5044432173", "A5044432173:2006"
REPORT_P = OUT / "frames_run_report_2026-08-28.json"

needs_run = pytest.mark.skipif(not REPORT_P.is_file(),
                               reason="run_cal_frames.py --execute has not produced "
                                      "data/cal2026-08-28/frames/ yet")


def _report() -> dict:
    return json.loads(REPORT_P.read_text(encoding="utf-8"))


def _rows(name: str) -> list[dict]:
    return list(csv.DictReader(open(cal_frame(name), encoding="utf-8")))


# ---------------------------------------------------------------------------------------------
# the staging layer's own invariants (green before the run — they pin the layer's constants)
# ---------------------------------------------------------------------------------------------

def test_the_five_and_their_events_match_the_signed_cal_tables():
    for field, ids in fs.FIVE.items():
        cal = list(csv.DictReader(open(CAL / f"events_{field}_cal.csv", encoding="utf-8")))
        frozen_n = {"chemistry": 35, "math_stats": 31}[field]
        assert [r["author_id"] for r in cal[frozen_n:]] == list(ids)
        assert [f"{r['author_id']}:{r['school']}" for r in cal[frozen_n:]] == \
            list(fs.NEW_EVENTS[field])


def test_the_pinned_legacy_code_is_still_the_audited_code():
    v2 = fs.real_v2()
    if not v2.is_dir():
        pytest.skip("legacy tree not on this machine")
    for rel, want in fs.PINNED_LEGACY_CODE.items():
        assert fs.sha(v2 / rel) == want, f"{rel} moved under the pin"


def test_the_econ_surgery_is_exact_and_byte_preserving():
    v2 = fs.real_v2()
    if not v2.is_dir():
        pytest.skip("legacy tree not on this machine")
    blob, removed = fs.surgery_new_events_econ(v2)
    assert removed == 1
    src = (v2 / "econ_fnfix_2026-08-15/data/new_events_econ.csv").read_bytes()
    # every surviving line is a literal line of the source, in order (byte-preserving removal)
    kept = [ln for ln in blob.split(b"\n") if ln]
    orig = [ln for ln in src.split(b"\n") if ln]
    it = iter(orig)
    assert all(any(ln == o for o in it) for ln in kept), "surgery reordered or edited a line"
    assert len(kept) == len(orig) - 1
    frame = v2 / ("econ_fnfix_2026-08-15/runs/econ_fnfix/data/"
                  "analysis_frame_p01_52ev_topicdose_2026-07-21.csv")
    blob2, kept_n, removed_n = fs.drop_event_lines(frame, AGE0_EVENT, 3)
    assert removed_n > 0 and AGE0_EVENT.encode() not in blob2


def test_the_t2_expectations_csv_is_the_one_the_accounting_evaluates():
    exp = fs.t2_expectations()
    assert len(exp) == 26
    assert {r["task3_expectation"] for r in exp} == {"removed", "persists"}


# ---------------------------------------------------------------------------------------------
# the run's controls and closure (need the frozen run report)
# ---------------------------------------------------------------------------------------------

@needs_run
def test_controls_prodlib_byte_equal_and_union_h1_characterised():
    r = _report()["controls"]
    assert r["prodlib_chemistry"] == "BYTE_EQUAL"
    assert r["prodlib_math_stats"] == "BYTE_EQUAL"
    for f in ("chemistry", "math_stats"):
        u = r[f"union_{f}"]
        assert u["relationships"] == "BYTE_EQUAL"
        assert u["frame"]["ok"] and u["frame"]["worst_ulp"] <= 8
        assert u["frame"]["unexpected_columns"] == []


@needs_run
def test_the_run_recorded_no_stop_and_every_accounting_closed():
    r = _report()
    assert r["stops"] == []
    acc = r["accounting"]
    for w in ("ledger", "p1_frame", "new37_vs_frozen_new38", "p2_becoming", "pairs_unified"):
        assert acc["econ"][w]["closed"], (w, acc["econ"][w])
    assert acc["econ"]["old79_byte_equal_to_frozen"] is True
    for field in ("chemistry", "math_stats"):
        for layer in ("prodlib_frame", "union_frame", "p1_frame", "p2_becoming"):
            assert acc[field][layer]["closed"], (field, layer)
        assert acc[field]["pairs"]["closed"], (field, acc[field]["pairs"])
        assert acc[field]["slim"]["consistent"]
        for ev, e in acc[field]["new_events"].items():
            assert e["ok"], (ev, e)
    assert acc["econ"]["slim"]["consistent"]


@needs_run
def test_econ_pins_hold_exactly_and_chemmath_deviations_are_the_dept_channel_class():
    """The T2-pin evaluation, verbatim: econ closes exactly; the chem/math colleague-side pins
    DEVIATE — and only in the direction the machinery's signed stars_excluded rule predicts
    (dept-channel colleague rows persist; 'both'-channel seats degrade to dept_only). The
    deviation is PINNED here so it cannot drift silently, and it is an OPEN item for the author,
    not an accepted new expectation."""
    r = _report()
    ev = {e["pin"]: e for e in r["t2_pin_evaluation"]}
    for pin in ("econ.p1_star_side_removed", "econ.p1_colleague_side_persists",
                "econ.p2_star_side_removed", "econ.p2_colleague_side_persists",
                "econ.pairs_event_side_removed", "econ.pairs_member_side_persists"):
        assert ev[pin]["status"] == "PASS", ev[pin]
    devs = {e["pin"] for e in r["pin_deviations"]}
    assert devs, "no deviations recorded — re-measure before trusting; the dept-channel "\
        "persistence was measured on the fnfix precedent and cannot silently vanish"
    assert all(p.split(".")[0] in ("chemistry", "math_stats", "econ") for p in devs)
    # every deviation must be SMALLER-than-pinned removal (persistence), never larger
    for e in r["pin_deviations"]:
        if e["pin"].endswith("_removed"):
            assert e["measured"] <= e["expected"], e


@needs_run
def test_new_event_counts_and_window_in_the_produced_frames():
    led = _rows("p1_events_ledger_econ.csv")
    assert len(led) == 116 and all(r["star_id"] != AGE0_STAR for r in led)
    for field, n_events in (("chemistry", 38), ("math_stats", 33)):
        p2 = _rows(f"p2_becoming_{field}.csv")
        events = {r["event_id"] for r in p2}
        assert len(events) == n_events, (field, len(events))
        for ev in fs.NEW_EVENTS[field]:
            assert ev in events, (field, ev)


@needs_run
def test_age0_star_left_the_econ_frames_star_side_and_stayed_colleague_side():
    p1 = _rows("p1_frame_econ.csv")
    assert sum(1 for r in p1 if r["event_id"] == AGE0_EVENT) == 0
    assert sum(1 for r in p1 if r["incumbent_person_id"] == f"P_{AGE0_STAR}") == 88
    assert len(p1) == 119405 - 1012
    p2 = _rows("p2_becoming_econ.csv")
    assert sum(1 for r in p2 if r["event_id"] == AGE0_EVENT) == 0
    assert sum(1 for r in p2 if r["pid"] == AGE0_STAR) == 136
    assert len(p2) == 181695 - 1547


@needs_run
def test_old79_is_byte_identical_and_new37_lost_exactly_one_event():
    """The cal old79 frame is byte-identical to the PRE-caliber frozen old79 (none of its 79 events
    moved under the 08-28 caliber). 2026-09-23: data/frames/p1_frame_econ_old79.csv is now the October
    caliber's (76 events), so the pre-caliber operand is (i) the sha256 data/frames/ carried for this file
    until the promotion — recorded as `old_sha256` in data/cal2026-10/expected_refreeze_2026-10.json, the
    freeze's own byte-identical copy — and (ii) the legacy pre-caliber frame itself where the tree is
    present (tools/import_frozen.py's pre-freeze mapping)."""
    import hashlib
    got = hashlib.sha256((OUT / "p1_frame_econ_old79.csv").read_bytes()).hexdigest()
    refreeze = json.loads((REPO / "data/cal2026-10/expected_refreeze_2026-10.json").read_text(encoding="utf-8"))
    assert got == refreeze["frames"]["p1_frame_econ_old79.csv"]["old_sha256"]
    assert got == "2a01c6b2de612a0827cbcf30c9645be55cf0f5cfa2aff69dfb9f12f9e24e79a5"      # tag pre-cal-freeze
    legacy = fs.real_v2() / "econ_fnfix_2026-08-15/data/analysis_frame_econ_fnfix_old79.csv"
    if legacy.is_file():
        assert hashlib.sha256(legacy.read_bytes()).hexdigest() == got
    new37 = _rows("p1_frame_econ_new37.csv")
    assert len(new37) == 43659 - 1012
    assert len({r["event_id"] for r in new37}) == 37


@needs_run
def test_the_manifest_covers_the_frames_products():
    manifest = (CAL / "MANIFEST.sha256").read_text(encoding="utf-8")
    for f in sorted(OUT.iterdir()):
        if f.is_file():
            line = f"{fs.sha(f)}  data/cal2026-08-28/frames/{f.name}"
            assert line in manifest, f"{f.name} not in (or stale in) MANIFEST.sha256"


@needs_run
def test_the_staging_manifest_records_every_cal_and_surgery_input():
    sm = json.loads((OUT / "staging_manifest_2026-08-28.json").read_text(encoding="utf-8"))
    ent = {e["rel"]: e for e in sm["entries"]}
    for rel in ("econ_fnfix_2026-08-15/data/new_events_econ.csv",
                "econ_fnfix_2026-08-15/data/relationships.csv",
                "econ_fnfix_2026-08-15/data/analysis_frame_dept_p01_econ920_2026-08-13.csv",
                "multidisc_gold_2026-08-10/data/events_chemistry_fnfix_2026-08-10.csv",
                "multidisc_gold_2026-08-10/data/events_math_stats_fnfix_2026-08-10.csv",
                "multidisc_gold_2026-08-10/data/stars_excluded_fnfix.parquet",
                "multidisc_gold_2026-08-10/data/edges_supplement_fnfix.jsonl"):
        assert rel in ent, rel
        assert not ent[rel]["origin"].startswith("frozen:"), (rel, ent[rel]["origin"])
    # and the frozen links really are frozen links
    assert ent["multidisc_2026-07-24/code/roster_lib.py"]["origin"].startswith("frozen:")
    assert ent["multidisc_2026-07-24/code/roster_lib.py"]["sha256"] == \
        fs.PINNED_LEGACY_CODE["multidisc_2026-07-24/code/roster_lib.py"]


# ---------------------------------------------------------------------------------------------
# measured pins (added after the run, per SDD discipline): the accounting numbers of the
# 2026-08-28 rebuild, pinned so a re-run that silently changes any of them fails here
# ---------------------------------------------------------------------------------------------

@needs_run
def test_measured_pins_econ_accounting():
    acc = _report()["accounting"]["econ"]
    assert (acc["p1_frame"]["rows_removed"], acc["p1_frame"]["rows_kept"]) == (1012, 118393)
    assert (acc["p2_becoming"]["rows_removed"], acc["p2_becoming"]["rows_kept"]) == (1547, 180148)
    assert (acc["pairs_unified"]["rows_removed"], acc["pairs_unified"]["rows_kept"]) == \
        (70028, 12108166)
    assert acc["slim"]["slim"] == {"rows": 12108166, "pairs": 719839, "ties": 15235,
                                   "events": 116}


@needs_run
def test_measured_pins_gold_accounting():
    acc = _report()["accounting"]
    chem, math = acc["chemistry"], acc["math_stats"]
    assert (chem["p1_frame"]["rows_frozen"], chem["p1_frame"]["rows_new"]) == (46552, 50193)
    assert chem["p1_frame"]["removed"]["five_member"] == 495
    assert chem["p1_frame"]["added"]["new_event"] == 4136
    assert (chem["p2_becoming"]["rows_frozen"], chem["p2_becoming"]["rows_new"]) == (70545, 76087)
    assert (chem["pairs"]["pairs_frozen"], chem["pairs"]["pairs_cal"]) == (269168, 286998)
    assert (chem["pairs"]["pairs_removed"], chem["pairs"]["pairs_added"]) == (5951, 23781)
    assert chem["pairs"]["pairs_rows_changed"] == 0
    assert chem["slim"]["slim"] == {"rows": 4805989, "pairs": 286998, "ties": 7907, "events": 38}
    assert (math["p1_frame"]["rows_frozen"], math["p1_frame"]["rows_new"]) == (23232, 24211)
    assert math["p1_frame"]["removed"]["five_member"] == 33
    assert math["p1_frame"]["added"]["new_event"] == 1012
    assert (math["pairs"]["pairs_frozen"], math["pairs"]["pairs_cal"]) == (78478, 80320)
    assert (math["pairs"]["pairs_removed"], math["pairs"]["pairs_added"]) == (236, 2078)
    assert math["slim"]["slim"] == {"rows": 1353396, "pairs": 80320, "ties": 1395, "events": 33}
    # new events' populations (no frozen counterpart — internal-consistency numbers, pinned)
    ne = {ev: (e["p1_persons"], e["pairs"]) for f in ("chemistry", "math_stats")
          for ev, e in acc[f]["new_events"].items()}
    assert ne == {"A5027778630:anu": (143, 10065), "A5091826237:anu": (96, 4483),
                  "A5062352558:melbourne": (137, 9233), "A5017222669:uq": (41, 818),
                  "A5090916445:unsw": (51, 1260)}


@needs_run
def test_measured_pins_the_dept_channel_deviation_table():
    """The T2-pin deviations, pinned VALUE BY VALUE: the five's colleague-side removal is partial
    (network channel only), and the persisting seats are exactly the dept-channel ones. This table
    is the author's decision material — pinning it keeps it from drifting, it does NOT accept it
    as the new expectation (the acceptance stays OPEN)."""
    r = _report()
    dev = {e["pin"]: (e["expected"], e["measured"]) for e in r["pin_deviations"]}
    assert dev == {
        "chemistry.A5027778630.rel_removed": (20, 16),
        "chemistry.A5027778630.p1_rows_removed": (220, 176),
        "chemistry.A5027778630.p2_rows_removed": (340, 272),
        "chemistry.A5027778630.pair_rows_removed": (43475, 35059),
        "chemistry.A5091826237.rel_removed": (18, 13),
        "chemistry.A5091826237.p1_rows_removed": (198, 143),
        "chemistry.A5091826237.p2_rows_removed": (306, 221),
        "chemistry.A5091826237.pair_rows_removed": (39250, 28040),
        "chemistry.A5062352558.rel_removed": (17, 15),
        "chemistry.A5062352558.p1_rows_removed": (187, 165),
        "chemistry.A5062352558.p2_rows_removed": (289, 255),
        "chemistry.A5062352558.pair_rows_removed": (39586, 35398),
        "math_stats.A5017222669.rel_removed": (5, 3),
        "math_stats.A5017222669.p1_rows_removed": (55, 33),
        "math_stats.A5017222669.p2_rows_removed": (85, 51),
        "math_stats.A5017222669.pair_rows_removed": (6169, 3959),
        "math_stats.A5090916445.rel_removed": (2, 0),
        "math_stats.A5090916445.p1_rows_removed": (22, 0),
        "math_stats.A5090916445.p2_rows_removed": (34, 0),
        "math_stats.A5090916445.pair_rows_removed": (2499, 0),
    }


@needs_run
def test_measured_pins_controls_and_incident_anchor():
    r = _report()
    assert r["accounting"]["incident_anchor_chem_pairs"]["incident_copy_sha16"] == \
        "3e63121882b9492c"
    # the econ A_far topic cut MOVED (H5: recomputed at build time) — the F1 86/23,830 arithmetic
    # therefore does not apply verbatim; the measured cell is pinned instead
    afar = r["accounting"]["afar_counts"]
    assert afar["econ|A_far"]["cut"] == {"frozen": "0.3332", "cal": "0.334"}
    assert afar["econ|A_far"]["events"] == {"frozen": "87", "cal": "86"}
    assert afar["econ|A_far"]["pairs"] == {"frozen": "23831", "cal": "23758"}
    assert afar["chemistry|A_far"]["pairs"] == {"frozen": "2385", "cal": "2466"}
    assert "econ_afar_cut_moved" in afar
