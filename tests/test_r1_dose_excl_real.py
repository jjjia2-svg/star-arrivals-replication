# -*- coding: utf-8 -*-
"""R1 F13 (W1-DOSEECON): r1_dose_excl.py on October's real inputs (big host only, batch B4).

Reproduces the 2026-10-01 economics measurement (the pre-rerun check of 2026-10-01, not shipped, §B (1)
and (3), and its review): the calls on record are 1,138 distinct (author, work) pairs over 69 author
ids; on the October frame (6,643 relations) 1,560 relations change, 7 drop from positive to zero,
108 of the 1,560 change only on the colleague side; the rebuilt current dose equals the stored dose
exactly on every dept_only and prodlib-event relation. The counts come from 10-01 scratch code that
no longer exists: a mismatch here is to be explained, never loosened.

The union config is October's as recorded in data/cal2026-10/frames_econ/
staging_manifest_econ920_2026-10.json:
  SUP_FNFIX = the frozen fnfix supplement (data/raw_verified copy, = the pinned legacy file) followed by
              FIVE copies of the star-id supplement (sha 59a55097…: the legacy file had been overwritten
              through shadow hard links four times when the October run read it, 4,655 = 4,151 + 4x126
              lines, and the run appended a fifth copy; the 2026-09-23 review restored the legacy pin);
  PATCH_A   = the frozen 2026-08-13 API patch followed by the October patch supplement (sha 143855d0…);
  SUP11, PATCH_B = the frozen legacy files; NEW_EVENTS = the October provenance table.
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

import pytest

pytestmark = [pytest.mark.ssd, pytest.mark.legacy]

REPO = pathlib.Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "pipeline" / "aws" / "r1", REPO / "pipeline" / "stars" / "caliber_2026-10"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

CAL10 = REPO / "data" / "cal2026-10"
FRAME = CAL10 / "frames_econ" / "p1_frame_econ.csv"
PROV = CAL10 / "frames_econ" / "prodlib_events_econ.csv"
SUP_RAW = REPO / "data" / "raw_verified" / "edges_supplement_econ_fnfix.jsonl"
SUP_STAR_ID = CAL10 / "edges_supplement_star_id_corrections_2026-10.jsonl"
PATCH_EXTRA = CAL10 / "patch_supplement_2026-10" / "works_by_author_supplement_2026-10.jsonl"
SHA = {
    "frame": "a2cfabf7c36ae54fca554d6880b2b78ba475615aa8f54901026a8fecf067ec80",
    "prov": "e5c38df9ec37854489188ec5a78cc74f2c73a8a23936d5464db43a1e83407a1f",
    "sup_fnfix_october": "59a55097edeca862236820ae9f466cb42b225c7d5a9cb75c47f5d28d13e1f12c",
    "patch_a_october": "143855d0b543182d1dfdc874bb54e0cb88556ed7d32a28f81e1c751d0174ab38",
    "sup11": "254342df47f3f83b0044b0002a85545781a8ba3271e0cf598b5dfafe677b0a3d",
    "patch_b": "49e095efc427fe040a6676000c453aac7a03ee717e0efd15d594fd258df235d6",
}


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha(p: pathlib.Path) -> str:
    return _sha_bytes(p.read_bytes())


def _october_union_cfg(tmp: pathlib.Path) -> dict:
    from pipeline.lib.paths import configured, require_readable      # noqa: PLC0415
    # the REAL legacy v2_output (frames_stage.real_v2's rule), never a shadowed legacy_thesis()
    v2 = require_readable(pathlib.Path(configured("legacy_v2_output")[0]))
    sup11 = v2 / "netbase_supplement_2026-07-23" / "edges_supplement_stars11.jsonl"
    patch_frozen = v2 / "econ_final_2026-08-13" / "patch" / "works_by_author.jsonl"
    patch_b = v2 / "econ_final_2026-08-13" / "patch" / "works_meta.jsonl"
    assert _sha(sup11) == SHA["sup11"] and _sha(patch_b) == SHA["patch_b"]
    sup = SUP_RAW.read_bytes() + SUP_STAR_ID.read_bytes() * 5
    assert _sha_bytes(sup) == SHA["sup_fnfix_october"], "not October's SUP_FNFIX"
    patch = patch_frozen.read_bytes() + PATCH_EXTRA.read_bytes()
    assert _sha_bytes(patch) == SHA["patch_a_october"], "not October's PATCH_A"
    (tmp / "sup_fnfix.jsonl").write_bytes(sup)
    (tmp / "patch_a.jsonl").write_bytes(patch)
    assert _sha(PROV) == SHA["prov"]
    return {"SUP11": str(sup11), "SUP_FNFIX": str(tmp / "sup_fnfix.jsonl"),
            "PATCH_A": str(tmp / "patch_a.jsonl"), "PATCH_B": str(patch_b), "NEW_EVENTS": str(PROV)}


def test_october_inputs_reproduce_the_10_01_econ_counts(tmp_path):
    import r1_dose_excl as D                                          # noqa: PLC0415
    import run_caliber                                                # noqa: PLC0415
    assert _sha(FRAME) == SHA["frame"]
    calls = run_caliber.historical_calls()[0] | run_caliber.october_calls()[0]
    assert (len(calls), len({a for a, _ in calls})) == (1138, 69)
    cfg = _october_union_cfg(tmp_path)
    out = tmp_path / "p1_frame_econ_dose_fixed.csv"
    rep = D.apply_dose_exclusions(FRAME, out, union_cfg=cfg, excludes=frozenset(calls),
                                  addbacks=frozenset(), mode="delta")
    print({k: rep[k] for k in ("relations", "sides", "self_check", "calls", "delta_calls", "delta_rule")})
    assert rep["calls"]["pairs"] == 1138 and rep["calls"]["ids"] == 69
    assert rep["relations"]["total"] == 6643
    # the self-check ran (it raises DoseRuleMismatch otherwise) and covered relations
    assert rep["self_check"]["mismatches"] == 0 and rep["self_check"]["relations"] > 0
    assert rep["self_check"]["max_abs_diff"] <= 1e-12
    # 10-01 §(3): "1,560 of 6,643 relations change ... 7 drop from positive to zero"; review: "Of the
    # 1,560 changes, 108 come only from the colleague's side" (fixed vs current, before clipping)
    assert rep["relations"]["delta_nonzero"] == 1560
    assert rep["relations"]["current_positive_to_fixed_zero"] == 7
    assert rep["sides"]["delta_nonzero"]["colleague_only"] == 108
    # no excluded work dated <= T-1 is left in any rebuilt vector
    assert rep["excluded_left_in_fixed"] == 0
    # and the written file differs from the input only in the dose cell of affected relations
    proof = D.dose_rows_proof(FRAME, out, {tuple(x) for x in rep["affected"]})
    assert proof["closed"] is True, proof
    assert proof["rewritten_rows"] == rep["rows_changed"]
    assert _sha(FRAME) == SHA["frame"]                               # October file untouched
