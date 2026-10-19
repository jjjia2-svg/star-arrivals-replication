# -*- coding: utf-8 -*-
"""cal2026-08-28 Task 5 — the four cloud-only cells: custody chain, results, comparison.

Written red-first: the artifact tests skip until the cloud run has produced
`data/cal2026-08-28/cloud/custody_2026-08-28.json`. Three layers, each named at the assert:
  * invariants (green before the run) — the T5 cell set equals Task 4's registry cell for cell
    and payload-sha for payload-sha; the launcher runs no ported python and no aws command;
  * artifacts — the custody log is COMPLETE (every cell: payload-hash-before == cal MANIFEST ==
    T4 registry == what the instance md5-verified; result-hash-after == the fetched file == the
    frozen estimates/ copy; instance id, timestamps, billed cost), the run markers are the
    driver's own, the evcl point estimates match their mains, the comparison doc's Task-5 rows
    re-derive from the JSONs through the SAME extractor (`rows_for`), and the MANIFEST covers
    everything under cloud/ + the four results;
  * measured pins (added after the run, SDD discipline) — the four headline values old→new.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO / "tests") not in sys.path:
    sys.path.insert(0, str(REPO / "tests"))
from _cal_paths import cal_frame, cal_frame_rel, pinned_sha  # noqa: E402
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))
sys.path.insert(0, str(REPO / "pipeline/stars/caliber_2026-08-28"))

import run_cal_cloud as rcc                                           # noqa: E402
import run_cal_estimates as rce                                       # noqa: E402

CAL = REPO / "data" / "cal2026-08-28"
CLOUD = CAL / "cloud"
FETCH = CLOUD / "fetch"
EST = CAL / "estimates"
CUSTODY_P = CLOUD / "custody_2026-08-28.json"
DOC_P = REPO / "docs" / "reviews" / "2026-08-28_cal_vs_frozen_estimates.md"

needs_run = pytest.mark.skipif(not CUSTODY_P.is_file(),
                               reason="the T5 cloud run has not produced "
                                      "data/cal2026-08-28/cloud/custody_2026-08-28.json yet")


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _load(p: pathlib.Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------
# invariants — green before the run
# ---------------------------------------------------------------------------------------------

def test_t5_cell_set_equals_the_t4_registry_cell_for_cell_and_sha_for_sha():
    """The authoritative cell set is Task 4's registered_for_t5 (T4-review MINOR-1: NOT the
    plan's 'chem P3 A_far' phrase) — same four cells, same payloads, same sha256s, and the
    payloads still sit in the cal MANIFEST under those hashes."""
    registry = {r["cell"]: r for r in
                _load(EST / "estimates_run_report_2026-08-28.json")["registered_for_t5"]}
    ours = {c: p for c, _d, p, _g in rcc.CLOUD_CELLS}
    assert set(registry) == set(ours) == set(rce.CLOUD_T5)
    man = rce.cal_manifest()
    for cell, payload in ours.items():
        rel = f"data/cal2026-08-28/frames/{payload}"
        assert registry[cell]["payload"] == rel
        # the payload is the shipped caliber copy (tests/_cal_paths.py resolves its location)
        assert registry[cell]["payload_sha"] == pinned_sha(payload) == _sha(cal_frame(payload)), cell


def test_t5_launcher_runs_no_ported_code_and_no_aws_command():
    """The launcher proves custody around the cloud run; the money-spending commands are the
    operator's (pipeline/aws/ discipline) and ported code is never imported or exec'd."""
    src = (REPO / "pipeline/stars/caliber_2026-08-28/run_cal_cloud.py").read_text("utf-8")
    assert "runpy" not in src
    assert "subprocess" not in src, "the T5 launcher shells out to nothing — aws/ssh/scp are the operator's"
    from pipeline.lib.paths import LAUNCHERS
    assert "pipeline/stars/caliber_2026-08-28/run_cal_cloud.py" in LAUNCHERS


def test_t5_gold_sources_are_the_m1_arrangement():
    """Old side of the comparison as the T5 run RECORDED it: analysis/expected/ for the P3 mains,
    data/estimates/ for the evcl robustness — where the frozen chain held the pre-caliber golds
    when the launcher ran. Since the 2026-08-28 freeze, analysis/expected/ holds the CAL results,
    so the pre-caliber old side is read from `_old_gold` below (the frozen 2026-08-16 chain's own
    records, kept and manifest-pinned); the launcher's recorded mapping stays as history."""
    want = {"P3_fnfix_chemistry": "analysis/expected", "P3_econ_fnfix": "analysis/expected",
            "P3evcl_chemistry": "data/estimates", "P3evcl_econ": "data/estimates"}
    assert {c: g for c, _d, _p, g in rcc.CLOUD_CELLS} == want
    for cell, gold in want.items():
        assert (REPO / gold / f"{cell}.json").is_file(), cell
        assert _old_gold(cell).is_file(), cell


def _old_gold(cell: str) -> pathlib.Path:
    """The PRE-caliber result for `cell` — the 'old' side of the old-vs-new comparison. The
    pre-freeze tests read analysis/expected/ for the mains; post-freeze that directory holds the
    cal golds, so the old side comes from the frozen 2026-08-16 chain itself: the M1 fetch copies
    for the mains (byte-copies of the pre-caliber golds, still tracked and pinned in
    data/MANIFEST.sha256) and the untouched data/estimates/ archive for the evcl cells."""
    if "evcl" in cell:
        return REPO / "data/estimates" / f"{cell}.json"
    return REPO / "pipeline/aws/logs/p3_main_2026-08-16/fetch" / f"{cell}.json"


# ---------------------------------------------------------------------------------------------
# artifacts — the custody chain (skip until the run)
# ---------------------------------------------------------------------------------------------

@needs_run
def test_custody_log_is_complete_for_every_cell():
    """Task-brief TDD gate: every cell has payload-hash-before, result-hash-after, instance id
    — plus the remote md5 evidence and the timestamps/cost the runbook demands."""
    c = _load(CUSTODY_P)
    inst = c["instance"]
    assert re.fullmatch(r"i-[0-9a-f]{8,17}", inst["instance_id"])
    for k in ("instance_type", "region", "az", "market", "launch_time_utc",
              "terminate_time_utc", "termination_state", "rate_usd_per_h"):
        assert inst.get(k) not in (None, ""), k
    assert c["billed_minutes"] > 0 and c["cost_usd_actual"] > 0
    man = rce.cal_manifest()
    registry = {r["cell"]: r for r in
                _load(EST / "estimates_run_report_2026-08-28.json")["registered_for_t5"]}
    assert set(c["cells"]) == set(registry)
    for cell, rec in c["cells"].items():
        assert rec["payload_sha256_before"] == registry[cell]["payload_sha"] == \
            pinned_sha(rec["payload"]), cell
        assert rec["result_sha256_after"] == _sha(FETCH / f"{cell}.json"), cell
        assert rec["job_exit"] == 0, cell


@needs_run
def test_the_instance_saw_the_shipped_bytes_and_said_so():
    """The verify_cloud_custody pattern with the remote evidence kept: payload.md5 (written from
    the frames BEFORE upload) matches the frames on disk, and the instance's own `md5sum -c`
    OK lines are in the fetched driver.log."""
    payload_md5 = {}
    for line in (CLOUD / "payload.md5").read_text("utf-8").splitlines():
        h, name = line.split()[0], line.split()[-1]
        payload_md5[name] = h
    for _cell, _d, payload, _g in rcc.CLOUD_CELLS:
        got = hashlib.md5(cal_frame(payload).read_bytes()).hexdigest()
        assert payload_md5[payload] == got, payload
    dlog = (FETCH / "driver.log").read_text("utf-8")
    for name in payload_md5:
        assert re.search(rf"^{re.escape(name)}: OK$", dlog, re.M), name
    assert (FETCH / "RESULT.txt").read_text("utf-8").strip() == \
        f"ALL_DONE_MARKER_{rcc.MARKER}"


@needs_run
def test_frozen_results_are_byte_copies_of_the_fetch_with_status_ok():
    for cell, *_ in rcc.CLOUD_CELLS:
        frozen, fetched = EST / f"{cell}.json", FETCH / f"{cell}.json"
        assert frozen.read_bytes() == fetched.read_bytes(), cell
        j = _load(frozen)
        assert j["status"] == "OK" and j["label"] == cell


@needs_run
def test_evcl_point_estimates_match_their_main_cells():
    """Same panel, other cluster — the frozen chain's own invariant, held by the new results."""
    for ev, main in rcc.EVCL_REF.items():
        je, jm = _load(EST / f"{ev}.json"), _load(EST / f"{main}.json")
        assert abs(je["ate"] - jm["ate"]) < 1e-8, ev
        ee, em = [x["est"] for x in je["effects"]], [x["est"] for x in jm["effects"]]
        assert len(ee) == len(em) and all(abs(a - b) < 1e-8 for a, b in zip(ee, em)), ev


@needs_run
def test_doc_t5_rows_re_derive_through_the_same_extractor():
    """The comparison-table extension is validated by the same extractor pattern (task brief):
    every ATE-table row in the Task-5 section is regenerated from the frozen JSONs through
    rce.rows_for/flags_for and must appear verbatim in the doc."""
    text = DOC_P.read_text("utf-8")
    assert "## Task 5 — the four cloud cells" in text
    t5 = text.split("## Task 5 — the four cloud cells", 1)[1]
    _f = rce._f
    n_rows = 0
    for cell, _d, _p, _gold_dir in rcc.CLOUD_CELLS:
        old = _load(_old_gold(cell))                    # the pre-caliber result (see _old_gold)
        new = _load(EST / f"{cell}.json")
        old_rows = {r["variant"]: r for r in rce.rows_for(cell, old)}
        new_rows = {r["variant"]: r for r in rce.rows_for(cell, new)}
        for var, o in old_rows.items():
            n = new_rows[var]
            flags = rce.flags_for(o, n)
            row = (f"| {cell} | {var} | {_f(o['ate'])} | {_f(n['ate'])} | "
                   f"{_f(o['se'])} | {_f(n['se'])} | {_f(o['p_je'], '.4g')} | "
                   f"{_f(n['p_je'], '.4g')} | {_f(o['p_pl'], '.4g')} | {_f(n['p_pl'], '.4g')} | "
                   f"{_f(o['n'], '')}→{_f(n['n'], '')} | {_f(o['events'], '')}→"
                   f"{_f(n['events'], '')} | {', '.join(flags) if flags else '' } |")
            assert row in t5, f"{cell}/{var} row not re-derivable:\n{row}"
            n_rows += 1
    # both JSON shapes fall into rows_for's 'main' branch (the evcl shape has no channels and
    # no pair_cluster key) -> exactly one ATE row per cell
    assert n_rows == 4


@needs_run
def test_manifest_covers_cloud_and_results_and_old_estimates_untouched():
    man = rce.cal_manifest()
    for f in CLOUD.rglob("*"):
        if f.is_file():
            rel = f"data/cal2026-08-28/{f.relative_to(CAL).as_posix()}"
            assert rel in man and man[rel] == _sha(f), rel
    for cell, *_ in rcc.CLOUD_CELLS:
        rel = f"data/cal2026-08-28/estimates/{cell}.json"
        assert rel in man and man[rel] == _sha(EST / f"{cell}.json"), rel
    # the frozen OLD (2026-08-16) chain must stay intact and reachable after the freeze: every
    # record still matches its data/MANIFEST.sha256 line, and each fetch copy still equals the
    # pre-caliber result it archived. (The mains' pre-caliber golds now live ONLY in that chain +
    # private repository tag pre-cal-freeze: analysis/expected holds the cal golds since 2026-08-28.)
    from analysis.lib.compare_json import compare
    data_man = (REPO / "data/MANIFEST.sha256").read_text(encoding="utf-8")
    for cell, *_ in rcc.CLOUD_CELLS:
        fetched_m1 = (REPO / "pipeline/aws/logs" /
                      ("p3_evcl_2026-08-16" if "evcl" in cell else "p3_main_2026-08-16") /
                      "fetch" / f"{cell}.json")
        line = f"{_sha(fetched_m1)}  {fetched_m1.relative_to(REPO).as_posix()}"
        assert line in data_man, f"{cell}: the M1 frozen chain record is no longer pinned"
        assert not compare(_load(fetched_m1), _load(_old_gold(cell))), \
            f"{cell}: the M1 frozen chain broke — the freeze may not touch it"


# ---------------------------------------------------------------------------------------------
# measured pins — added AFTER the run (SDD discipline), so the frozen cloud estimates cannot
# drift silently. Values are the fetched EC2 results of 2026-08-28 (instance i-0ec873f66546a0b87).
# ---------------------------------------------------------------------------------------------

#: cell -> (ate, se, p_joint_effects, rows, grps, clusters-or-None)
MEASURED = {
    "P3_fnfix_chemistry": (-0.00046583, 9.659e-05, 1.005e-05, 4805989, 286998, None),
    "P3_econ_fnfix":      (-0.00033916, 6.509e-05, 6.65391964e-10, 12108166, 719839, None),
    "P3evcl_chemistry":   (-0.00046583, 0.00023167, 0.26712608, 4805989, 286998, 38),
    "P3evcl_econ":        (-0.00033916, 0.00010152, 0.00027802, 12108166, 719839, 116),
}


@needs_run
def test_measured_pins_the_four_cloud_results():
    for cell, (ate, se, p_je, rows, grps, clusters) in MEASURED.items():
        j = _load(EST / f"{cell}.json")
        assert j["ate"] == ate, (cell, j["ate"])
        assert j["se"] == se, (cell, j["se"])
        assert j["p_joint_effects"] == p_je, (cell, j["p_joint_effects"])
        assert j["rows"] == rows and j["grps"] == grps, cell
        if clusters is not None:
            assert j["clusters"] == clusters, cell


@needs_run
def test_measured_pins_custody_and_environment():
    c = _load(CUSTODY_P)
    assert c["instance"]["instance_id"] == "i-0ec873f66546a0b87"
    assert c["instance"]["termination_state"] == "terminated"
    assert c["billed_minutes"] == 34.1 and c["cost_usd_actual"] == 2.29
    assert c["versions_remote"].splitlines()[0].split() == [
        "R", "4.6.1", "DIDmultiplegtDYN", "2.4.0", "polars", "1.14.0.9000",
        "data.table", "1.18.6.1", "jsonlite", "2.0.0"]
    # rows moved exactly as the T3 frame accounting says (econ -70,028 pair-rows net of the
    # slim's own shape: 12,178,194 -> 12,108,166; chem 4,507,601 -> 4,805,989), and the flag
    # summary on the four cloud rows is: no sign change, no p crossing, per-effect-only flags
    # on the chem cells' k=1 (small-|est| horizon).
    import run_cal_estimates as _rce
    for cell, *_ in rcc.CLOUD_CELLS:
        o = _rce.rows_for(cell, _load(_old_gold(cell)))[0]     # pre-caliber old side (see _old_gold)
        n = _rce.rows_for(cell, _load(EST / f"{cell}.json"))[0]
        flags = _rce.flags_for(o, n)
        want = ["effect_dATE>20%_k=1"] if "chemistry" in cell else []
        assert flags == want, (cell, flags)
