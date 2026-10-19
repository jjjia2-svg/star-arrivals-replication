# -*- coding: utf-8 -*-
"""cal2026-08-28 Task 4 — local estimation on the caliber frames + old-vs-new comparison.

Written red-first: the artifact tests skip until `run_cal_estimates.py --execute` has produced
`data/cal2026-08-28/estimates/`. Three layers, each named at the assert:
  * invariants (green before the run) — the pinned cell inventory partitions the 23 frozen
    expected cells exactly (run-local / cloud-registered-for-T5), the drivers and cal frames the
    inventory names exist, and the driver runs no ported python;
  * artifacts — every local cell's JSON exists, SHAPE-matches its frozen counterpart (key tree +
    effect/placebo list lengths; values are the comparison table's business, not the shape's),
    the evcl self-checks read MATCH, the double-run determinism check is compare_json-EQUAL, and
    the old79 positive control (byte-identical frame) reproduces the frozen gold EXACTLY;
  * measured pins (added after the run, SDD discipline) — the headline numbers, so they cannot
    drift silently.
"""
from __future__ import annotations

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

import run_cal_estimates as rce                                       # noqa: E402
from analysis.lib.compare_json import compare                         # noqa: E402

CAL = REPO / "data" / "cal2026-08-28"
EST = CAL / "estimates"
EXP = REPO / "analysis" / "expected"
REPORT_P = EST / "estimates_run_report_2026-08-28.json"
DOC_P = REPO / "docs" / "reviews" / "2026-08-28_cal_vs_frozen_estimates.md"

needs_run = pytest.mark.skipif(not REPORT_P.is_file(),
                               reason="run_cal_estimates.py --execute has not produced "
                                      "data/cal2026-08-28/estimates/ yet")


def _report() -> dict:
    return json.loads(REPORT_P.read_text(encoding="utf-8"))


def _load(p: pathlib.Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------
# invariants — green before the run (they pin the inventory, so no cell can go unaccounted)
# ---------------------------------------------------------------------------------------------

def test_inventory_partitions_the_frozen_expected_cells_exactly():
    """Every frozen expected cell is either run-local or registered-for-T5 — no overlap, none
    unaccounted (the deliverable's pinned inventory).

    Since the 2026-08-28 freeze the golds in analysis/expected/ ARE the cal estimates, so the
    frozen names equal the cell names directly — `rce.FROZEN_NAME` (new37 -> the pre-caliber
    new38 gold) described the PRE-freeze expected directory and is kept only as the launcher's
    frozen run-record vocabulary."""
    # The six 2026-08-30 Panel 3 respecification golds (P3{pos,med}_*_A_far, registered 2026-09-10)
    # are NOT caliber cells: they are built by analysis/robustness/p3_afar_cuts/build_afar_cut.py and
    # pinned in tests/test_afar_cuts_2026_08_30.py, so they are set aside before the partition.
    afar_cuts = {f"P3{s}_{f}_A_far.json" for s in ("pos", "med") for f in ("econ", "chemistry", "math_stats")}
    frozen = {p.name for p in EXP.glob("*.json")} - afar_cuts
    assert len(frozen) == 23
    local_frozen = {c.name + ".json" for c in rce.LOCAL_CELLS}
    cloud = {c + ".json" for c in rce.CLOUD_T5}
    assert local_frozen & cloud == set()
    assert local_frozen | cloud == frozen
    assert len(rce.LOCAL_CELLS) == 19 and len(rce.CLOUD_T5) == 4
    assert rce.FROZEN_NAME == {"P1_econ_fnfix_new37": "P1_econ_fnfix_new38"}   # historical mapping


def test_inventory_names_real_drivers_and_real_cal_frames():
    man = rce.cal_manifest()
    for c in rce.LOCAL_CELLS:
        assert (REPO / "analysis/estimation" / c.driver).is_file(), c.driver
        assert cal_frame(c.frame).is_file(), c.frame
        assert pinned_sha(c.frame), f"{cal_frame_rel(c.frame)} is not covered by a MANIFEST"
    # the evcl refs point at cells that run earlier in the same inventory
    names = [c.name for c in rce.LOCAL_CELLS]
    for c in rce.LOCAL_CELLS:
        if c.ref is not None:
            assert c.ref in names and names.index(c.ref) < names.index(c.name), c.name


def test_the_driver_runs_no_ported_python():
    """Same guard-intent assertion as the launcher test: this launcher drives Rscript only."""
    src = (REPO / "pipeline/stars/caliber_2026-08-28/run_cal_estimates.py").read_text("utf-8")
    assert "runpy" not in src
    assert "Rscript" in src


# ---------------------------------------------------------------------------------------------
# artifacts — skip-red until the run has produced data/cal2026-08-28/estimates/
# ---------------------------------------------------------------------------------------------

def _shape_diffs(new, exp, path=""):
    """Key-tree + list-length shape comparison; scalar VALUES are ignored (the comparison table
    owns those). `label`/`file` differ for the honestly renamed new37 cell and are excluded."""
    diffs = []
    if isinstance(exp, dict):
        if not isinstance(new, dict):
            return [f"{path}: {type(new).__name__} != dict"]
        for k in exp:
            if k in ("label", "file"):
                continue
            p = f"{path}.{k}" if path else k
            if k not in new:
                diffs.append(f"{p}: missing in cal")
            else:
                diffs += _shape_diffs(new[k], exp[k], p)
        diffs += [f"{path}.{k}: extra in cal" for k in new
                  if k not in exp and k not in ("label", "file")]
        return diffs
    if isinstance(exp, list):
        if not isinstance(new, list):
            return [f"{path}: {type(new).__name__} != list"]
        if len(new) != len(exp):
            return [f"{path}: list length {len(new)} != {len(exp)}"]
        for i, (a, b) in enumerate(zip(new, exp)):
            diffs += _shape_diffs(a, b, f"{path}[{i}]")
        return diffs
    return []


@needs_run
def test_every_local_cell_json_exists_and_shape_matches_its_frozen_counterpart():
    # post-freeze the expected gold carries the cell's own name (new37 included) — see the
    # inventory test's note on rce.FROZEN_NAME
    for c in rce.LOCAL_CELLS:
        got = EST / f"{c.name}.json"
        assert got.is_file(), c.name
        j = _load(got)
        exp = _load(EXP / f"{c.name}.json")
        assert _shape_diffs(j, exp) == [], c.name
        assert j["label"] == c.name


@needs_run
def test_every_cell_estimated_ok_and_evcl_self_checks_match():
    for c in rce.LOCAL_CELLS:
        j = _load(EST / f"{c.name}.json")
        if "channels" in j:
            assert all(ch["status"] == "OK" for ch in j["channels"].values()), c.name
        elif "pair_cluster" in j:
            assert j["pair_cluster"]["ate"] is not None, c.name
            assert j["event_cluster"]["ate"] is not None, c.name
        else:
            assert j["status"] == "OK", c.name
        pec = j.get("point_estimate_check")
        if pec is not None:                       # the evcl cells: point estimates must MATCH
            vals = list(pec.values()) if isinstance(pec, dict) else [pec]
            assert all(v == "MATCH" for v in vals), (c.name, pec)


@needs_run
def test_determinism_double_run_of_econ_p1_is_compare_json_equal():
    run1 = _load(EST / "P1_econ_fnfix.json")
    run2 = _load(EST / "determinism" / "P1_econ_fnfix_run2.json")
    assert compare(run1, run2) == []
    assert _report()["determinism"]["compare"] == "EQUAL"


def _pre_caliber_gold(name: str) -> dict:
    """The PRE-caliber frozen gold `analysis/expected/<name>.json` as it stood before the 2026-08-28
    freeze. It exists nowhere on disk any more — analysis/expected/ has held the 08-28 golds since the
    freeze and the October golds since 2026-09-23 — so it is read from tag `pre-cal-freeze`."""
    import subprocess
    r = subprocess.run(["git", "show", f"pre-cal-freeze:analysis/expected/{name}.json"],
                       cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"the pre-caliber gold {name}.json lives only at git tag pre-cal-freeze and git "
                    f"cannot serve it here: {(r.stderr or r.stdout).strip()[-200:]}")
    return json.loads(r.stdout)


@needs_run
def test_old79_positive_control_reproduces_the_frozen_gold_exactly():
    """The cal old79 frame is byte-identical to the frozen frame (T3), so the estimate must be
    compare_json-EQUAL to the frozen gold — an estimator-environment control, not a comparison.
    2026-09-23: analysis/expected/ now holds the October golds (data/cal2026-10/expected_refreeze_2026-10.json),
    so the frozen operand is the PRE-caliber gold at tag pre-cal-freeze (the gold this control was written
    against), and the run report's own recorded verdict is asserted beside the live comparison."""
    assert _report()["old79_control"] == {"compare": "EQUAL", "diffs": []}
    assert compare(_load(EST / "P1_econ_fnfix_old79.json"),
                   _pre_caliber_gold("P1_econ_fnfix_old79")) == []


@needs_run
def test_report_registers_the_cloud_cells_and_the_out_of_scope_items():
    rep = _report()
    assert {r["cell"] for r in rep["registered_for_t5"]} == set(rce.CLOUD_T5)
    assert all(r["reason"] for r in rep["registered_for_t5"])
    assert {o["item"] for o in rep["out_of_scope"]} >= {
        "p3_afar_speed_bracket", "B0_null_test.R", "analysis/paper generators"}
    assert all(c["status"] == "OK" for c in rep["cells"])
    assert len(rep["cells"]) == len(rce.LOCAL_CELLS) + 1          # + the determinism re-run


@needs_run
def test_input_frames_were_hash_verified_against_the_cal_manifest():
    rep = _report()
    man = rce.cal_manifest()
    for rel, sha in rep["input_hashes"].items():
        assert pinned_sha(rel.rsplit("/", 1)[1]) == sha, rel
    assert {f"data/cal2026-08-28/frames/{c.frame}" for c in rce.LOCAL_CELLS} == \
        set(rep["input_hashes"])


@needs_run
def test_manifest_covers_every_estimates_file():
    manifest = (CAL / "MANIFEST.sha256").read_text(encoding="utf-8")
    files = [f for f in EST.rglob("*") if f.is_file()]
    assert len(files) >= len(rce.LOCAL_CELLS) + 2
    for f in files:
        line = f"{rce.sha(f)}  data/cal2026-08-28/{f.relative_to(CAL).as_posix()}"
        assert line in manifest, f"{f.name} not in (or stale in) MANIFEST.sha256"


@needs_run
def test_comparison_doc_exists_and_carries_the_headline_cell():
    text = DOC_P.read_text(encoding="utf-8")
    assert "P3lb_econ_A_far" in text
    # old = the PRE-caliber frozen gold the doc compared against, as the frozen run report recorded it
    # (2026-09-23: analysis/expected/ holds the October golds, so it is no longer that operand)
    old = next(r for r in _report()["comparison_rows"]
               if r["cell"] == "P3lb_econ_A_far" and r["variant"] == "pair_cluster")["old"]
    new = _load(EST / "P3lb_econ_A_far.json")["pair_cluster"]
    assert old["ate"] == -0.00132182 and new["ate"] == -0.00133257          # the doc's headline pair
    assert f"{old['ate']:.8f}" in text and f"{new['ate']:.8f}" in text
    # every local cell appears in the table
    for c in rce.LOCAL_CELLS:
        assert c.name in text, c.name


# ---------------------------------------------------------------------------------------------
# measured pins — added AFTER the run (SDD discipline): the headline numbers, value by value,
# so the frozen cal estimates cannot drift without a test saying so
# ---------------------------------------------------------------------------------------------

@needs_run
def test_pin_the_headline_econ_a_far_cell():
    j = _load(EST / "P3lb_econ_A_far.json")
    assert (j["pair_cluster"]["ate"], j["pair_cluster"]["se"]) == (-0.00133257, 0.00048869)
    assert j["event_cluster"]["se"] == 0.00043204
    assert (j["grps"], j["events"]) == (23758, 86)          # = T3's pinned cal A_far cell


@needs_run
def test_pin_the_other_a_far_cells():
    ch = _load(EST / "P3lb_chemistry_A_far.json")
    assert (ch["pair_cluster"]["ate"], ch["pair_cluster"]["se"]) == (-0.0060448, 0.0026377)
    assert (ch["grps"], ch["events"]) == (2466, 33)
    ms = _load(EST / "P3lb_math_stats_A_far.json")
    assert (ms["pair_cluster"]["ate"], ms["pair_cluster"]["se"]) == (-0.00042461, 0.00127813)
    assert (ms["grps"], ms["events"]) == (2770, 31)


@needs_run
def test_pin_the_p1_p2_p3_headline_atess():
    assert _load(EST / "P1_econ_fnfix.json")["channels"]["union"]["ate"] == -0.37821843
    assert _load(EST / "P1_fnfix_chemistry.json")["channels"]["union"]["ate"] == -0.23401506
    assert _load(EST / "P1_fnfix_math_stats.json")["channels"]["union"]["ate"] == -0.12710666
    assert _load(EST / "P1_econ_fnfix_new37.json")["channels"]["union"]["ate"] == -0.70449939
    assert _load(EST / "P2_econ_fnfix.json")["ate"] == 0.00271947
    assert _load(EST / "P2_fnfix_chemistry.json")["ate"] == 0.00415442
    assert _load(EST / "P2_fnfix_math_stats.json")["ate"] == 0.001481
    assert _load(EST / "P3_fnfix_math_stats.json")["ate"] == -7.783e-05


@needs_run
def test_pin_the_flag_summary():
    """No ATE sign change anywhere; exactly one p-boundary crossing (new37 dept through .01)
    and exactly one CI-zero-crossing change (the evcl math network robustness channel)."""
    rows = _report()["comparison_rows"]
    assert len(rows) == 38
    assert sum(1 for r in rows if r["flags"]) == 20
    assert [r for r in rows if "ATE_SIGN_CHANGE" in r["flags"]] == []
    crossings = [(r["cell"], r["variant"], f) for r in rows
                 for f in r["flags"] if "crosses" in f]
    assert crossings == [("P1_econ_fnfix_new37", "dept",
                          "p_effects_crosses_0.01(0.01793->0.006923)")]
    ci = [(r["cell"], r["variant"]) for r in rows
          for f in r["flags"] if f == "ATE_CI_zero_crossing_change"]
    assert ci == [("P1evcl_math_stats", "network")]
