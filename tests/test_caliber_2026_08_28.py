# -*- coding: utf-8 -*-
"""The 2026-08-28 caliber layer (author-signed D-A / D-B + the five personnel rulings).

Authority: the author's 2026-08-28 caliber decision record (not shipped). The layer under test is
`pipeline/stars/caliber_2026-08-28/` and its frozen products in `data/cal2026-08-28/`. The OLD
caliber's artifacts and tests are untouched: both event sets stay derivable side by side.
"""
from __future__ import annotations

import csv
import hashlib
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
CAL_CODE = REPO / "pipeline" / "stars" / "caliber_2026-08-28"
if str(CAL_CODE) not in sys.path:
    sys.path.insert(0, str(CAL_CODE))

import caliber                                                           # noqa: E402
import cleaned_works                                                     # noqa: E402

from analysis.lib.paths import load_paths                                # noqa: E402

P = load_paths()
CAL = REPO / "data" / "cal2026-08-28"
GOLD = P["legacy_thesis"] / "v2_output" / "multidisc_gold_2026-08-10"

needs_legacy_thesis = pytest.mark.skipif(
    not (P["legacy_thesis"] / "v2_output").is_dir(),
    reason="byte-comparison against the frozen gold tables needs the read-only legacy tree")

#: the six people the 2026-08-28 caliber decisions name, by OpenAlex author id:
AGE0_STAR = "A5044432173"   # econ star admitted before the caliber with academic age 0; now out
CHEM_2003 = "A5062352558"   # chemistry star arriving 2003, excluded by the old chem/math window
CHEM_NEW1, CHEM_NEW2 = "A5027778630", "A5091826237"    # chemistry stars admitted by the caliber
MATH_NEW1, MATH_NEW2 = "A5017222669", "A5090916445"    # math-stats stars admitted by the caliber
#: restake columns dropped from the public copies (a person's name; a free-text note)
PRIVATE_COLS = ("name", "note")


def _rows(p: pathlib.Path) -> list[dict]:
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _by_id(p: pathlib.Path) -> dict[str, dict]:
    """author_id -> row, without the columns the public copies drop (PRIVATE_COLS)."""
    return {r["author_id"]: {k: v for k, v in r.items() if k not in PRIVATE_COLS}
            for r in _rows(p)}


def _lines(p: pathlib.Path) -> list[str]:
    """Raw data lines, byte-faithful: read BYTES (read_text's universal-newline mode would strip
    the \\r of the gold CSVs' \\r\\n endings and quietly weaken every byte comparison below)."""
    return [ln for ln in p.read_bytes().decode("utf-8").split("\n") if ln][1:]


# ------------------------------------------------------------------------------------------------
# D-A: the seniority gate
# ------------------------------------------------------------------------------------------------

def test_gate_age_is_the_signed_constant_not_a_retyped_number():
    sys.path.insert(0, str(REPO / "pipeline/stars/multidisc_2026-07-24/code/star_screening"))
    import screening_lib
    assert caliber.MIN_ACADEMIC_AGE is screening_lib.MIN_ACADEMIC_AGE
    assert caliber.MIN_ACADEMIC_AGE == 2


def test_gate_age_worked_examples_from_the_register():
    assert caliber.gate_age(0) is False          # AGE0_STAR — the D-A exit
    assert caliber.gate_age("0") is False        # as the CSV column carries it
    assert caliber.gate_age(1) is False          # A5105845982 (fails percentile anyway)
    assert caliber.gate_age(2) is True           # the threshold itself is inclusive
    assert caliber.gate_age(11) is True          # CHEM_2003
    assert caliber.gate_age(None) is False       # not_in_pool cannot pass a gate defined on aage


def test_gate_age_anchor_derived_ages_of_the_four_admissions_pass():
    # no hand math: each aage derives from the dossier's first_pub anchor work
    for aid, arrival, want in ((CHEM_NEW1, 2002, 16), (CHEM_NEW2, 2001, 17),
                               (MATH_NEW1, 2002, 8), (MATH_NEW2, 2002, 4)):
        got = cleaned_works.aage(aid, arrival)
        assert got == want, (aid, got)
        assert caliber.gate_age(got) is True


# ------------------------------------------------------------------------------------------------
# D-B: the uniform window — the four old paths and the one new rule
# ------------------------------------------------------------------------------------------------

def test_in_window_worked_examples_three_2003_arrivals():
    """The stars-README worked example, healed: three people, same year 2003, one rule now."""
    assert caliber.in_window(2003) is True                          # all three 2003 arrivals in
    assert caliber.old_in_window_chemmath(2003) is False            # the rule that excluded CHEM_2003
    assert caliber.old_in_window_econ(2003) is True                 # the rule that admitted A5018518935
    assert caliber.old_in_window_econ_u4flagged9(2003) is True      # the literal that admitted A5006190609
    # A5006190609 is now in via a REAL year test, not a literal:
    assert caliber.in_window("2003") is True


def test_in_window_bounds_and_the_three_pre1999_rejects_stay_out():
    assert caliber.in_window(1999) is True and caliber.in_window(2024) is True
    assert caliber.in_window(1998) is False and caliber.in_window(2025) is False
    # the other three round-2 window-rejects (completeness report): out under D-B as well
    assert caliber.in_window(1996) is False     # round-2 window reject, true arrival 1996
    assert caliber.in_window(1993) is False     # round-2 window reject, true arrival 1993
    assert caliber.in_window(1995) is False     # round-2 window reject, true arrival 1995


# ------------------------------------------------------------------------------------------------
# the signed cleanups are DATA (the per-person evidence dossiers they cite are not published)
# ------------------------------------------------------------------------------------------------

def test_signed_exclusions_are_exactly_the_six_listed_works():
    assert cleaned_works.exclusions() == {
        (CHEM_NEW2, "W2010247246"), (CHEM_NEW2, "W4210338294"), (CHEM_NEW2, "W2043627473"), (CHEM_NEW2, "W2132883327"),
        (MATH_NEW1, "W2051022741"), (CHEM_2003, "W2002298104")}


def test_math_new1_merge_list_is_the_four_split_id_works_and_not_a_restake_drop():
    assert cleaned_works.merge_works(MATH_NEW1) == [
        "W1592870802", "W1214546200", "W2131510173", "W2167745157"]
    assert cleaned_works.MERGE_SOURCE_ID == "A5083852619"
    assert not (set(cleaned_works.merge_works(MATH_NEW1))
                & {w for _, w in cleaned_works.exclusions()})


def test_every_calls_row_has_a_known_action():
    """The public calls table keeps author_id, work_id, publication_year and action; the column
    citing each row's per-person evidence dossier is dropped (the dossiers are not published)."""
    for r in cleaned_works.load_calls():
        assert r["action"] in ("exclude", "merge_from_A5083852619", "first_pub_anchor"), r


def test_first_pub_anchors():
    assert cleaned_works.first_pub(CHEM_NEW1) == 1985      # snapshot agrees — zero change
    assert cleaned_works.first_pub(CHEM_NEW2) == 1983        # the injection (snapshot believes 1988)
    assert cleaned_works.first_pub(MATH_NEW1) == 1993      # after the 1992 contaminant is removed
    assert cleaned_works.first_pub(MATH_NEW2) == 1997      # snapshot agrees — zero change
    assert cleaned_works.first_pub("A5000000000") is None


# ------------------------------------------------------------------------------------------------
# the frozen products in data/cal2026-08-28/ — pinned after the machine run
# ------------------------------------------------------------------------------------------------

def test_restake_table_is_67_frozen_rows_plus_the_four_admissions():
    rows = _rows(CAL / "restake_2026-08-28.csv")
    assert len(rows) == 71
    assert [r["author_id"] for r in rows[-4:]] == [CHEM_NEW1, CHEM_NEW2, MATH_NEW1, MATH_NEW2]
    by = {r["author_id"]: r for r in rows}
    # F1 kept visible: AGE0_STAR's machine flag still says True; D-A is the caliber layer's verdict
    assert by[AGE0_STAR]["after_pass"] == "True" and by[AGE0_STAR]["aage"] == "0"
    assert caliber.event_verdict(after_pass=by[AGE0_STAR]["after_pass"], aage=by[AGE0_STAR]["aage"],
                                 arrival_true=by[AGE0_STAR]["arrival_true"]) is False


@needs_legacy_thesis
def test_restake_table_frozen_67_are_identical_to_the_gold_table():
    """Byte-identical in the private original; the public copy drops PRIVATE_COLS, so the check
    is row by row on every other column, in order."""
    frozen = _rows(GOLD / "data" / "fnfix_restake_2026-08-15.csv")
    ours = _rows(CAL / "restake_2026-08-28.csv")
    strip = lambda r: {k: v for k, v in r.items() if k not in PRIVATE_COLS}   # noqa: E731
    assert [strip(r) for r in ours[:67]] == [strip(r) for r in frozen]


def test_equivalence_proof_rows_are_byte_identical_to_the_frozen_rows():
    """The caliber machine reproduced the frozen restake bit-for-bit for the proof candidates
    (>=3 untouched by the 2026-08-28 cleanups: A5018518935, A5006190609, A5035138469, A5074090421;
    plus CHEM_2003). The frozen 67 rows are embedded in restake_2026-08-28.csv, so this holds
    in-repo (on every published column); the test above ties that embedding to the gold table
    itself when the legacy tree is present."""
    proof = _by_id(CAL / "restake_equiv_proof_2026-08-28.csv")
    table = dict(list(_by_id(CAL / "restake_2026-08-28.csv").items())[:67])
    untouched = {"A5018518935", "A5006190609", "A5035138469", "A5074090421"}
    assert untouched <= set(proof) and CHEM_2003 in proof
    for aid, row in proof.items():
        assert row == table[aid], aid


def test_ported_72_run_agrees_with_the_equivalence_machine():
    """The ported `72`, driven with the cal inputs, returns the same bytes as the caliber machine
    for every machine candidate except CHEM_NEW2's anchored bin (the one row `72` cannot produce),
    and CHEM_2003's row proves the 24th call is zero-effect at Y=2002 (compared on every published
    column)."""
    ported = _by_id(CAL / "restake_ported72_newcands_2026-08-28.csv")
    table = _by_id(CAL / "restake_2026-08-28.csv")
    for aid in (CHEM_NEW1, MATH_NEW1, MATH_NEW2):
        assert ported[aid] == table[aid], aid
    assert ported[CHEM_2003] == table[CHEM_2003]        # identical to the FROZEN row (zero effect)


@needs_legacy_thesis
def test_age0_star_exits_and_is_the_only_econ_change():
    # Since the 2026-08-28 freeze, data/frames/p1_events_ledger_econ.csv IS the caliber's 116-row
    # ledger, so the 117-row PRE-caliber side of this diff is read from its frozen legacy source
    # (the exact bytes data/frames held before the freeze; private repository tag pre-cal-freeze).
    # (the public event tables have their evidence-source URLs cleared, so the comparison is on the
    # event keys rather than on whole lines)
    old = [r["event_id"] for r in _rows(P["legacy_thesis"] / "v2_output" / "econ_fnfix_2026-08-15"
                                        / "data" / "event_ledger_fnfix.csv")]
    old_star = {r["event_id"]: r["star_id"] for r in _rows(
        P["legacy_thesis"] / "v2_output" / "econ_fnfix_2026-08-15" / "data" / "event_ledger_fnfix.csv")}
    new = [r["event_id"] for r in _rows(CAL / "events_econ_cal.csv")]
    assert len(old) == 117 and len(new) == 116
    removed = set(old) - set(new)
    assert len(removed) == 1 and old_star[next(iter(removed))] == AGE0_STAR
    assert set(new) - set(old) == set()         # no surprise econ entries
    assert new == [ln for ln in old if ln.split(",")[1] != AGE0_STAR]   # order preserved
    # and the 08-28 frames ledger is exactly the cal set (2026-09-23: data/frames/ was promoted to the
    # October caliber — 113 events, data/cal2026-10/events_decision_2026-10.json — so the 08-28 ledger is
    # read from its frozen copy data/cal2026-08-28/frames/, the bytes data/frames/ held until then)
    assert _lines(CAL / "frames" / "p1_events_ledger_econ.csv") == new


def test_verdicts_table_diff_is_exactly_the_signed_delta():
    rows = _rows(CAL / "verdicts_2026-08-28.csv")
    assert len(rows) == 71
    by = {r["author_id"]: r for r in rows}
    assert by[AGE0_STAR]["event_cal2026_08_28"] == "False"
    assert by[AGE0_STAR]["reason_if_out"] == "D-A gate_age fail (aage=0)"
    assert by[CHEM_2003]["event_cal2026_08_28"] == "True"
    news = [r for r in rows if r["new_candidate_2026_08_28"] == "True"]
    assert [r["author_id"] for r in news] == [CHEM_NEW1, CHEM_NEW2, MATH_NEW1, MATH_NEW2]
    # everyone else's verdict equals the old caliber's (the four frozen restake failures stay out)
    for r in rows:
        if r["author_id"] in (AGE0_STAR, CHEM_2003, CHEM_NEW1, CHEM_NEW2, MATH_NEW1, MATH_NEW2):
            continue
        assert r["event_cal2026_08_28"] == r["after_pass"], r["author_id"]


def test_every_event_in_every_cal_table_is_inside_the_uniform_window():
    for name, col in (("events_econ_cal.csv", "arrival_year"),
                      ("events_chemistry_cal.csv", "arrival_corrected"),
                      ("events_math_stats_cal.csv", "arrival_corrected")):
        for r in _rows(CAL / name):
            assert caliber.in_window(r[col]), (name, r)


def test_math_stats_gains_exactly_the_two_new_stars():
    old = _lines(REPO / "data" / "raw_verified" / "events_math_stats_fnfix.csv")
    new = _lines(CAL / "events_math_stats_cal.csv")
    assert len(old) == 31 and len(new) == 33
    assert new[:31] == old                      # frozen rows byte-preserved, in order
    added = [ln.split(",")[2] for ln in new[31:]]
    assert added == [MATH_NEW1, MATH_NEW2]


def test_chemistry_gains_exactly_the_three_new_stars():
    old = _lines(REPO / "data" / "raw_verified" / "events_chemistry_fnfix.csv")
    new = _lines(CAL / "events_chemistry_cal.csv")
    assert len(old) == 35 and len(new) == 38
    assert new[:35] == old                      # frozen rows byte-preserved, in order
    added = [ln.split(",")[2] for ln in new[35:]]
    assert added == [CHEM_NEW1, CHEM_NEW2, CHEM_2003]       # register ruling order 1, 2, 5


def test_chem_new2_machine_outcome_is_pinned_either_way():
    """Register ruling 2: CHEM_NEW2 enters IFF the machine restake, on the cleaned works with the
    evidence-anchored first_pub=1983 (aage 17, bin 14-17), stays >= p90. The machine said PASS:
    stock 321 unchanged (none of the 4 contaminants carries snapshot citations), re-ranked in
    1605|14-17 (cell_n 3521) at pct .9122 — above the .90 line (the private original's note:
    first_pub_override=1983; rebinned 10-13->14-17). The native-bin row the ported `72` produced
    (1605|10-13, cell_n 4317, pct .9201) is pinned beside it."""
    cols = ("after_stock", "after_cell", "after_cell_n", "after_pct", "after_pass", "aage")
    row = _by_id(CAL / "restake_2026-08-28.csv")[CHEM_NEW2]
    assert [row[c] for c in cols] == ["321", "1605|14-17", "3521", "0.9122", "True", "17"]
    native = _by_id(CAL / "restake_ported72_newcands_2026-08-28.csv")[CHEM_NEW2]
    assert [native[c] for c in cols] == ["321", "1605|10-13", "4317", "0.9201", "True", "12"]


def test_new_admission_percentiles_match_the_frozen_suspects_table():
    """The four admissions' before-columns must equal the frozen `60` suspects screening (same
    machine, same snapshot): .9981, .9201, .9643 and .9057."""
    table = _by_id(CAL / "restake_2026-08-28.csv")
    want = {CHEM_NEW1: ("14414", "1312|14-17", "0.9981"), CHEM_NEW2: ("321", "1605|10-13", "0.9201"),
            MATH_NEW1: ("1454", "1312|6-9", "0.9643"), MATH_NEW2: ("157", "2610|2-5", "0.9057")}
    for aid, (stock, cell, pct) in want.items():
        row = table[aid]
        assert (row["before_stock"], row["before_cell"], row["before_pct"]) == (stock, cell, pct), aid


def test_math_new1_aage_derives_from_the_cleaned_list_not_hand_math():
    """B-1 (binding): the snapshot's rfp was the 1992 contaminant; dropping it moves the MACHINE's
    own recomputation to 1993 -> aage 8, same 6-9 bin, percentile untouched. The machine-native
    row and the anchored row coincide, which is why this row carries no override note."""
    row = _by_id(CAL / "restake_2026-08-28.csv")[MATH_NEW1]
    assert (row["after_cell"], row["after_pct"], row["aage"]) == ("1312|6-9", "0.9643", "8")
    assert cleaned_works.aage(MATH_NEW1, 2002) == 8


def test_manifest_covers_every_cal_file_and_verifies():
    man = (CAL / "MANIFEST.sha256").read_text(encoding="utf-8")
    listed = {}
    for ln in man.splitlines():
        h, rel = ln.split("  ", 1)
        listed[rel] = h
    # T3 grew the manifest a `frames/` subdirectory, so the walk is recursive now
    on_disk = {f"data/cal2026-08-28/{f.relative_to(CAL).as_posix()}" for f in CAL.rglob("*")
               if f.is_file() and f.name != "MANIFEST.sha256"}
    assert set(listed) == on_disk
    for rel, h in listed.items():
        assert hashlib.sha256((REPO / rel).read_bytes()).hexdigest() == h, rel
