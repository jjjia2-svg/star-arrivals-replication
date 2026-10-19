# -*- coding: utf-8 -*-
"""cal2026-08-28 Task 6 — the caliber p3afar ledger + the author report.

Written red-first: the artifact tests skip until `run_cal_ledger.py --execute` has frozen
`data/cal2026-08-28/data_numbers_cal_p3afar.json`. Three layers, each named at the assert:
  * invariants (green before the run) — the launcher is registered, drives ONLY the existing
    `analysis/paper/ledger_p3afar.py` machinery (no copy of the generator, no subprocess), and
    every input it names is frozen in the cal MANIFEST;
  * artifacts — every key quantity in the frozen cal ledger equals the cal estimate JSONs /
    the cal counts table it derives from (NO hand-typed number can hide in the ledger), the
    raw rates are re-derived here with INDEPENDENT SQL over the cal A_far panels, and the
    quantities with no cal builder (speed_bracket, null_simulation) are honestly ABSENT;
  * measured pins (added after the run, SDD discipline) — the author-report headline numbers,
    so neither the ledger nor the report can drift silently.
"""
from __future__ import annotations

import hashlib
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

CAL = REPO / "data" / "cal2026-08-28"
FRAMES = CAL / "frames"
EST = CAL / "estimates"
LED_P = CAL / "data_numbers_cal_p3afar.json"
FIG_P = CAL / "fig_p3_afar_cal.pdf"
REPORT_P = CAL / "ledger_run_report_2026-08-28.json"
LAUNCHER = REPO / "pipeline" / "stars" / "caliber_2026-08-28" / "run_cal_ledger.py"
GENERATOR = REPO / "analysis" / "paper" / "ledger_p3afar.py"

FIELDS = ("econ", "chemistry", "math_stats")

needs_run = pytest.mark.skipif(not LED_P.is_file(),
                               reason="run_cal_ledger.py --execute has not frozen "
                                      "data/cal2026-08-28/data_numbers_cal_p3afar.json yet")


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _manifest() -> dict[str, str]:
    out = {}
    for line in (CAL / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        if line.strip():
            h, rel = line.split("  ", 1)
            out[rel] = h
    return out


def _led() -> dict:
    return json.loads(LED_P.read_text(encoding="utf-8"))


def _est(f: str) -> dict:
    return json.loads((EST / f"P3lb_{f}_A_far.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------
# invariants — green before the run
# ---------------------------------------------------------------------------------------------

def test_launcher_registered_and_reuses_the_existing_generator():
    """The launcher is a declared launcher, and the ledger machinery is the EXISTING
    analysis/paper/ledger_p3afar.py — run in place via runpy, not copied, not edited."""
    from pipeline.lib.paths import LAUNCHERS
    assert "pipeline/stars/caliber_2026-08-28/run_cal_ledger.py" in LAUNCHERS
    src = LAUNCHER.read_text(encoding="utf-8")
    assert GENERATOR.is_file()
    assert "ledger_p3afar.py" in src, "the launcher must name the existing generator"
    assert "subprocess" not in src, "the ledger run is in-process (runpy), not a subprocess"
    assert src.count("runpy.run_path(") == src.count("with staged_run("), \
        "every runpy call sits inside a staged_run mark (the launcher-guard identity)"


def test_every_ledger_input_is_frozen_in_the_cal_manifest():
    man = _manifest()
    for name in [f"p3_afar_{f}.parquet" for f in FIELDS] + ["p3_afar_counts.csv"]:
        assert cal_frame(name).is_file(), name
        assert pinned_sha(name) == _sha(cal_frame(name)), f"{cal_frame_rel(name)}: disk != MANIFEST"
    for rel in [f"data/cal2026-08-28/estimates/P3lb_{f}_A_far.json" for f in FIELDS]:
        assert (REPO / rel).is_file(), rel
        assert man.get(rel) == _sha(REPO / rel), f"{rel}: disk != cal MANIFEST"


def test_speed_bracket_has_no_cal_builder_registered():
    """The one paper quantity with no cal counterpart: the speed-bracket cap cells
    (NOT_REPRODUCIBLE entry 9, re-registered in T3/T4). The cal frames must NOT contain a
    speed-bracket table — if one appears, it appeared from nowhere and the register is stale."""
    assert not (FRAMES / "p3_afar_speed_bracket.csv").exists()
    reg = (REPO / "pipeline" / "NOT_REPRODUCIBLE.md").read_text(encoding="utf-8")
    assert "speed_bracket" in reg


# ---------------------------------------------------------------------------------------------
# artifacts — the frozen cal ledger derives from the cal artifacts, nothing hand-typed
# ---------------------------------------------------------------------------------------------

@needs_run
def test_ledger_frozen_and_in_manifest():
    man = _manifest()
    for p in (LED_P, FIG_P, REPORT_P):
        rel = f"data/cal2026-08-28/{p.name}"
        assert p.is_file(), rel
        assert man.get(rel) == _sha(p), f"{rel}: disk != cal MANIFEST"
    led = _led()
    assert "_cal_note" in led, "the frozen copy must declare its true (cal) provenance"
    assert led["year_cap"] == 2024 and led["post_window_tau"] == [0, 5]


@needs_run
@pytest.mark.parametrize("f", FIELDS)
def test_estimate_quantities_equal_the_cal_estimate_jsons(f):
    """ate/se/CI/p/horizons/events/pairs/ties/rows: every one re-derived here from the cal
    estimate JSON with the generator's own rounding rule — a hand-typed value cannot match."""
    d, j = _led()[f], _est(f)
    pc, ec = j["pair_cluster"], j["event_cluster"]
    assert d["events_with_pairs"] == j["events"]
    assert d["pairs"] == j["grps"]
    assert d["first_ties"] == j["first_ties"]
    assert d["rows"] == j["rows"]
    assert d["ate_pp"] == round(100 * pc["ate"], 3)
    assert d["se_pair_pp"] == round(100 * pc["se"], 3)
    assert d["se_event_pp"] == round(100 * ec["se"], 3)
    assert d["ci95_pair_pp"] == [round(100 * pc["lb"], 3), round(100 * pc["ub"], 3)]
    assert d["p_joint_effects_pair"] == pc["p_joint_effects"]
    assert d["p_joint_effects_event"] == ec["p_joint_effects"]
    assert len(d["horizons_pp"]) == len(pc["effects"]) == 5
    for h, e, ee in zip(d["horizons_pp"], pc["effects"], ec["effects"]):
        assert h["ell"] == e["k"] - 1
        assert h["est"] == round(100 * e["est"], 3)
        assert h["se_pair"] == round(100 * e["se"], 3)
        assert h["se_event"] == round(100 * ee["se"], 3)
        assert h["n"] == e["n"] and h["switchers"] == e["switchers"]


@needs_run
@pytest.mark.parametrize("f", FIELDS)
def test_topic_cut_and_pooled_rates_equal_the_cal_counts_table(f):
    import csv
    with open(cal_frame("p3_afar_counts.csv"), encoding="utf-8") as fh:
        row = {r["cell"] + "|" + r["field"]: r for r in csv.DictReader(fh)}["A_far|" + f]
    d = _led()[f]
    assert d["topic_cut_median_positive_dose"] == float(row["cut"])
    assert d["lb_counts_pooled"]["rate_pre_pp"] == round(float(row["rate_pre_pp"]), 3)
    assert d["lb_counts_pooled"]["rate_post_pp_allyears"] == round(float(row["rate_post_pp"]), 3)


@needs_run
@pytest.mark.parametrize("f", FIELDS)
def test_raw_rates_rederived_independently_from_the_cal_panel(f):
    """Independent SQL (written here, not the generator's) over the frozen cal A_far panel."""
    import duckdb
    fp = str(cal_frame(f"p3_afar_{f}.parquet"))
    con = duckdb.connect()
    con.execute(f"""CREATE TEMP TABLE t AS
        SELECT p.grp, p.ev, p.year, p.y, p.year - a.a0 AS tau
        FROM read_parquet('{fp}') p
        JOIN (SELECT ev, min(year) AS a0 FROM read_parquet('{fp}') WHERE D = 1 GROUP BY ev) a
        USING (ev)""")
    n_pre, t_pre = con.execute(
        "SELECT count(*), sum(y) FROM t WHERE tau >= -6 AND tau <= -1").fetchone()
    n_post, t_post = con.execute(
        "SELECT count(*), sum(y) FROM t WHERE tau >= 0 AND tau <= 5 AND year <= 2024").fetchone()
    d = _led()[f]
    assert d["rate_pre_pp"] == round(100 * t_pre / n_pre, 3)
    assert (d["pre_rows"], d["pre_ties"]) == (n_pre, int(t_pre))
    assert d["rate_post_obs_pp"] == round(100 * t_post / n_post, 3)
    assert (d["post_obs_rows"], d["post_obs_ties"]) == (n_post, int(t_post))


@needs_run
def test_quantities_without_a_cal_builder_are_honestly_absent():
    """No cal speed bracket (cap cells have no builder) and no cal no-effect simulation
    (B0_null_test.R is not in this repository) — the frozen OLD values must NOT leak in."""
    led = _led()
    for f in FIELDS:
        assert "speed_bracket" not in led[f], f
        assert "null_simulation" not in led[f], f
    rep = json.loads(REPORT_P.read_text(encoding="utf-8"))
    assert rep["determinism"]["compare"] == "EQUAL"


@needs_run
def test_cal_manifest_still_covers_every_pre_existing_entry():
    """The Task-6 freeze is a pure addition: every entry in the regenerated cal MANIFEST
    still hashes to what sits on disk (T1–T5 artifacts untouched)."""
    man = _manifest()
    for rel, want in man.items():
        assert _sha(REPO / rel) == want, rel


# ---------------------------------------------------------------------------------------------
# measured pins — added after the run: the headline numbers
# ---------------------------------------------------------------------------------------------

@needs_run
def test_headline_pins_old_and_new():
    """The trio the thesis quotes, old (the pre-caliber 2026-08-22 thesis ledger) vs new (cal
    ledger) — pinned value by value.

    Freeze-wave Task 8: before the freeze the old side was read from the regenerated
    output/paper/data_numbers_p3afar.json, which then reproduced the pre-caliber numbers; since
    the freeze that file holds the CALIBER numbers by design, so the pre-caliber pins now read
    the thesis's kept 2026-08-22 ledger (the pre-caliber numbers),
    where the thesis tree is mounted."""
    from analysis.lib.paths import load_paths
    _old_p = (load_paths()["legacy_thesis"] / "thesis_report"
              / "data_numbers_2026-08-22_p3afar.json")
    old = json.loads(_old_p.read_text(encoding="utf-8")) if _old_p.is_file() else None
    led = _led()
    pins = {  # field: (ate_pp, se_pair_pp, p_pair, events, pairs, rate_pre_pp, rate_post_obs_pp)
        "econ":       (-0.133, 0.049, 0.00018724, 86, 23758, 0.396, 0.312),
        "chemistry":  (-0.604, 0.264, 0.24005184, 33, 2466, 0.938, 0.749),
        "math_stats": (-0.042, 0.128, 0.34308189, 31, 2770, 0.327, 0.261),
    }
    for f, (ate, se, p, ev, pr, rpre, rpost) in pins.items():
        d = led[f]
        assert d["ate_pp"] == ate and d["se_pair_pp"] == se, f
        assert d["p_joint_effects_pair"] == pytest.approx(p, abs=1e-8), f
        assert d["events_with_pairs"] == ev and d["pairs"] == pr, f
        assert d["rate_pre_pp"] == rpre and d["rate_post_obs_pp"] == rpost, f
    if old is not None:  # the frozen pre-caliber counterparts
        assert old["econ"]["ate_pp"] == -0.132 and old["econ"]["se_pair_pp"] == 0.049
        assert old["chemistry"]["ate_pp"] == -0.626 and old["math_stats"]["ate_pp"] == -0.015
        assert old["econ"]["rate_pre_pp"] == 0.396 and old["econ"]["rate_post_obs_pp"] == 0.312
