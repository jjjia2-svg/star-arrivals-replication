# -*- coding: utf-8 -*-
"""R1 J0-MEAS.3h (W2-ECONM): the union rung's G-DOSE draw measured and reported inside the M
economics build (pipeline/aws/r1/econ920_m.py), on toy inputs.

The override stays evidence-gated as in October (ruling h4, v3 §6 / v2 #16); M's record cites that
ruling instead of October's PENDING string, B0 keeps October's string byte for byte, a missing ruling
or an unexplained draw failure STOPs, and the stage report holds counts, codes and OpenAlex ids only.
The chemistry / mathematics advisory copy (never gated) is W2-CHEMM's helper and is tested there.
"""
from __future__ import annotations

import io
import json
import pathlib
import re
import sys
import types

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "pipeline" / "aws" / "r1"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import econ920_m as em            # noqa: E402

L, R = em.L, em.R
ID = re.compile(r"^A\d+(:\d{4})?$")
FAILING = {"pid": "A5047860864", "event_id": "A5046379417:2006", "frozen_dose": 0.3, "recomputed": 0.2303,
           "abs_diff": 0.0697}


def population_report() -> dict:
    return {"measurements": {"gdose_population": {
        "n": 10, "share_exact_1e-9": 0.8, "max_abs_diff": 0.0697, "n_gt_0.01": 2, "n_gt_0.05": 1,
        "frozen_0813_draw": {"max_abs_diff": 0.0019, "share_exact_1e-9": 0.93}}},
        "_gdose_residuals": {"A5047860864|A5046379417:2006": 0.0697, "A5050473533|A5018453582:2018": 0.0554}}


def prediction() -> dict:
    return {"predicted_gate": "FAIL", "predicted_max_abs_diff": 0.0697, "predicted_share_exact_1e-9": 0.885,
            "drawn": 200, "population_relations": 4293,
            "drawn_relations_gt_0.01": [["A5047860864", "A5046379417:2006", 0.0697]]}


def union_result(failing=(FAILING,), g_row_mismatches=0) -> dict:
    return {"gate_overridden": True, "exit": 0,
            "report": {"G_DOSE": {"n": 200, "missing_side": 0, "max_abs_diff": 0.0697, "share_exact_1e-9": 0.885},
                       "G_ROW": {"sampled_both": 5, "mismatches": g_row_mismatches, "dose_tolerated_le_0.01": 0,
                                 "fill_divergence": 0},
                       "G_SUM": {"ok": True}},
            "drawn_residuals_gt_1e-9": list(failing)}


@pytest.fixture
def report(monkeypatch):
    rep = population_report()
    monkeypatch.setattr(R, "REPORT", rep)
    return rep


def test_m_override_record_cites_h4_not_pending(report):
    october = R.OVERRIDE_RULING
    ok, rec = em.gdose_verdict("M", prediction(), union_result())
    assert ok is True
    assert "h4" in rec["ruling"] and "v2 #16" in rec["ruling"] and "PENDING" not in rec["ruling"]
    assert rec["ruling"] == em.M_OVERRIDE_RULING
    assert R.OVERRIDE_RULING == october                     # the module global is restored after the call


def test_b0_keeps_the_october_ruling_text_byte_for_byte(report):
    assert em.OCTOBER_OVERRIDE_RULING == R.OVERRIDE_RULING
    assert R.OVERRIDE_RULING.startswith("Author ruling pending at export time (2026-09-23)")
    ok, rec = em.gdose_verdict("B0", prediction(), union_result())
    assert ok is True and rec["ruling"] == R.OVERRIDE_RULING
    assert em.override_ruling("B0") == R.OVERRIDE_RULING != em.override_ruling("M")
    dev = L.CAL10 / "frames_econ" / "DEVIATION_gdose_gate_override_2026-09-23.md"
    assert R.OVERRIDE_RULING in dev.read_text(encoding="utf-8")          # October's file carries this exact text
    assert "frames_econ/DEVIATION_gdose_gate_override_2026-09-23.md" in \
        (L.CAL10 / "frames_econ" / "MANIFEST.sha256").read_text(encoding="utf-8")


def _toy_network(p: pathlib.Path, prov: set[str]) -> pathlib.Path:
    lines = [",".join(L.FRAME_COLS)]
    events = [f"A{900 + k}:{2000 + k}" for k in range(6)] + sorted(prov)
    for k, ev in enumerate(events):
        star, year = ev.split(":")
        for i in range(70):
            pid = f"P_A{10000 + 100 * k + i}"
            for y in (int(year) - 1, int(year)):
                lines.append(",".join([pid, str(y), star, ev, "true", "true" if y >= int(year) else "false", "",
                                       f"0.{(i % 9) + 1}", "false", "3", "1.0", "2", "1.0", "2", "1.0", "1.0"]))
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_prediction_draws_no_provenance_event(tmp_path):
    prov = {"A5028731684:2008", "A5091326353:2009", "A5110738002:2009", "A9:2015", "A8:2016"}
    frame = _toy_network(tmp_path / "net1.csv", prov)
    drawn = em.gdose_draw(frame, prov)
    assert len(drawn) == 200 and not {e for _p, e in drawn} & prov
    resid = {(f"A{10000 + 100 * k + i}", ev): 0.5
             for k, ev in enumerate([f"A{900 + k}:{2000 + k}" for k in range(6)] + sorted(prov)) for i in range(70)}
    lib = L.predict_gdose_draw(frame, prov, resid)
    assert {(a, b) for a, b, _c in lib["drawn_relations_gt_0.01"]} == set(drawn)
    assert lib["drawn"] == len(drawn) and lib["population_relations"] == 6 * 70


def test_missing_gdose_ruling_stops():
    from pipeline.lib.r1_config import ConfigStop

    def missing(_rid):
        raise ConfigStop("MISSING_RULING", "gdose_override")
    for cfg in (types.SimpleNamespace(name="M", ruling=missing),
                types.SimpleNamespace(name="M", ruling=lambda rid: {}[rid])):
        with pytest.raises(em.MStop) as e:
            em.gdose_policy(cfg)
        assert e.value.code == "GDOSE_RULING_MISSING"
    with pytest.raises(em.MStop) as e:
        em.gdose_policy(types.SimpleNamespace(name="M", ruling=lambda rid: "pass_always"))
    assert e.value.code == "GDOSE_RULING_UNKNOWN"
    assert em.gdose_policy(types.SimpleNamespace(name="M", ruling=lambda rid: "pass_h4")) == "pass_h4"


@pytest.mark.parametrize("res, resid", [
    (union_result(), {}),                                              # the failing relation is no residual
    (union_result(g_row_mismatches=3), None),                          # G_ROW mismatches
])
def test_unexplained_draw_failure_stops_m(tmp_path, report, res, resid):
    if resid is not None:
        report["_gdose_residuals"] = resid
    out = tmp_path / "stage_out"
    with pytest.raises(em.MStop) as e:
        em.gdose_step(out, "M", prediction(), res, override=True)
    assert e.value.code == "GDOSE_UNEXPLAINED"
    assert e.value.ids and all(ID.match(i) for i in e.value.ids)
    body = json.loads((out / "stop_report_gdose.json").read_text(encoding="utf-8"))
    assert body["code"] == "GDOSE_UNEXPLAINED" and set(body["ids"]) == set(e.value.ids)
    assert not (out / em.GDOSE_REPORT).exists()
    em.check_report_ids_only(body)


def _walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v)


def test_report_holds_counts_codes_ids_only(tmp_path, report):
    out = tmp_path / "stage_out"
    body = em.gdose_step(out, "M", prediction(), union_result(), override=True)
    written = json.loads((out / em.GDOSE_REPORT).read_text(encoding="utf-8"))
    assert written == body and body["code"] == "OK_OVERRIDDEN"
    assert set(_walk_keys(body)) <= em.GDOSE_KEYS
    assert "name" not in set(_walk_keys(body))
    assert body["ids"] and all(ID.match(i) for i in body["ids"])
    assert body["population"]["n"] == 10 and body["population"]["n_gt_0.01"] == 2
    assert body["predicted"]["gate"] == "FAIL" and body["actual"]["G_ROW"]["mismatches"] == 0
    assert all(body["conditions"].values()) and "h4" in body["ruling"]
    with pytest.raises(ValueError):
        em.check_report_ids_only({**body, "name": "Somebody"})
    with pytest.raises(ValueError):
        em.check_report_ids_only({**body, "ids": ["Somebody"]})
    # a clean pass without the override is reported too, and needs no override
    passed = {**union_result(failing=()), "gate_overridden": False}
    body2 = em.gdose_step(tmp_path / "o2", "M", {**prediction(), "predicted_gate": "PASS"}, passed, override=False)
    assert body2["code"] == "OK" and body2["ids"] == []


def test_a_gdose_stop_prints_the_union_checks(tmp_path, capsys):
    """j1a-08: GDOSE_UNEXPLAINED (G_ROW_zero_mismatches_and_G_SUM_ok) said which condition failed but not
    which rows; the union clone's own G_ROW examples and G_SUM go to the stage log (ids and numbers only)."""
    rep = {"G_DOSE": {"n": 10, "share_exact_1e-9": 0.8}, "G_SUM": {"total": 33, "old": 22, "new": 11, "ok": True},
           "G_ROW": {"sampled_both": 60, "mismatches": 1,
                     "examples": [["A5000000001", "A5000000002:2011", "2012", "pub_count_ex_star", "3.0", "2.0"]]},
           "G_ROW_fnfix_exstar_tolerated": {"n": 0, "examples": []}, "frame": {"rows": 33}, "GATE": "FAIL",
           "other": "not printed"}
    p = tmp_path / "build_report.json"
    p.write_text(json.dumps(rep), encoding="utf-8")
    em.log_union_checks(p)
    out = capsys.readouterr().out
    assert "pub_count_ex_star" in out and '"G_SUM"' in out and "not printed" not in out
    em.log_union_checks(tmp_path / "absent.json")                          # no report: says so, never raises
    assert "no union report" in capsys.readouterr().out


# ------------------------------------------------------------------------------------------------ M's G_ROW rule (j1a-09)
# j1a-09 stopped GDOSE_UNEXPLAINED on October's "G_ROW 0 mismatches" condition alone. M replaces it with
# "0 UNEXPLAINED G_ROW mismatches and G_SUM ok". Two classes are explained:
#   outcome_new_event_outside_u5  a y column 04_rebuild_y.py overwrites (fwci_frac/_ex_star, fwci_mean/_ex_star)
#                                 on a row of a provenance event (the clone's _NEW_EV), incumbent outside U5's
#                                 output table (the clone's need_outcomes)
#   dose_population_residual      dose_topic on a relation of October's residual table, the same difference
#                                 (1e-12) on every one of its 2W+1 rows
# Everything else stays unexplained. B0 keeps run_econ920's verdict byte for byte.
NEW_EV = "A5039825487:2015"          # a new M event (add-list ACCEPT)
OUTSIDE = "A5018993618"              # an incumbent outside U5's output table
INSIDE = "A5000000011"               # an incumbent inside it
OLD_EV = "A5000000020:2005"          # an event outside the clone's provenance set
RESID_PID, RESID_EV = "A5050473533", "A5018453582:2018"     # in population_report()'s residual table (0.0554)
EXPLAINED_C, EXPLAINED_A = "outcome_new_event_outside_u5", "dose_population_residual"


def clone_capture(mism, *, need_outcomes=(OUTSIDE,), new_events=(NEW_EV,), w=5, api_persons=(OUTSIDE,)) -> dict:
    """What em.clone_g_row_capture keeps of the clone's namespace at its json.dump(report, ...)."""
    return {"mism": list(mism), "need_outcomes": set(need_outcomes), "new_events": set(new_events), "W": w,
            "sample_both": sorted({(m[0], m[1]) for m in mism}), "api_persons": set(api_persons)}


def j1a09_cells() -> list[tuple]:
    """The j1a-09 examples: one relation, 2010-2015, fwci_frac and fwci_mean (old = the prodlib row, new = the clone)."""
    out = []
    for y in range(2010, 2016):
        out += [(OUTSIDE, NEW_EV, y, "fwci_frac", 0.0413, 0.9496), (OUTSIDE, NEW_EV, y, "fwci_mean", 5.21, 18.53)]
    return out


def dose_cells(pid=RESID_PID, ev=RESID_EV, diff=0.0554) -> list[tuple]:
    arr = int(ev.split(":")[1])
    return [(pid, ev, y, "dose_topic", 0.3, 0.3 - diff) for y in range(arr - 5, arr + 6)]


def test_m_explains_y_cells_of_a_new_event_for_an_incumbent_outside_u5(tmp_path, report):
    import run_stages
    cells = j1a09_cells()
    res = union_result(g_row_mismatches=len(cells))
    ok, rec = em.gdose_verdict("M", prediction(), res, clone=clone_capture(cells))
    assert ok is True
    conds = rec["conditions"]
    assert list(conds) == [em.M_G_ROW_CONDITION if k == em.OCTOBER_G_ROW_CONDITION else k for k in em.GDOSE_CONDITIONS]
    assert conds[em.M_G_ROW_CONDITION] is True and all(conds.values())
    g = rec["g_row"]
    assert (g["n_reported"], g["n_mismatches"], g["n_explained"], g["n_unexplained"]) == (12, 12, 12, 0)
    assert g["captured"] is True and g["unexplained"] == {} and list(g["explained"]) == [EXPLAINED_C]
    blk = g["explained"][EXPLAINED_C]
    assert (blk["n_cells"], blk["n_relations"], blk["ids"]) == (12, 1, [OUTSIDE, NEW_EV])
    assert {"ids": [OUTSIDE, NEW_EV], "year": 2010, "columns": ["fwci_frac"], "old": 0.0413, "new": 0.9496} in blk["cells"]
    assert {"ids": [OUTSIDE, NEW_EV], "year": 2015, "columns": ["fwci_mean"], "old": 5.21, "new": 18.53} in blk["cells"]
    # the stage report carries every explained cell, keys from GDOSE_KEYS, ids only
    out = tmp_path / "stage_out"
    body = em.gdose_step(out, "M", prediction(), res, override=True, clone=clone_capture(cells))
    assert body["code"] == "OK_OVERRIDDEN" and body["g_row"] == g
    assert json.loads((out / em.GDOSE_REPORT).read_text(encoding="utf-8")) == body
    assert set(_walk_keys(body)) <= em.GDOSE_KEYS
    em.check_report_ids_only(body)
    # and it survives the name-free filter that feeds summary.json
    nf = run_stages.name_free(body)["g_row"]["explained"][EXPLAINED_C]
    assert nf["n_cells"] == 12 and nf["ids"] == [OUTSIDE, NEW_EV] and len(nf["cells"]) == 12
    assert nf["cells"][0]["columns"] and nf["cells"][0]["ids"] == [OUTSIDE, NEW_EV]


def test_m_explains_dose_cells_only_for_a_population_residual_on_all_its_rows(report):
    ok, rec = em.gdose_verdict("M", prediction(), union_result(g_row_mismatches=11), clone=clone_capture(dose_cells()))
    assert ok is True
    blk = rec["g_row"]["explained"][EXPLAINED_A]
    assert (blk["n_cells"], blk["n_relations"], blk["ids"]) == (11, 1, [RESID_PID, RESID_EV])
    bad = {"not_in_the_residual_table": (dose_cells(pid="A5000000099"), 5),
           "another_difference_on_one_row": (dose_cells()[:10] + dose_cells(diff=0.06)[10:], 5),
           "not_every_row": (dose_cells()[:10], 5),
           "no_window_captured": (dose_cells(), None)}
    for name, (cells, w) in bad.items():
        ok, rec = em.gdose_verdict("M", prediction(), union_result(g_row_mismatches=len(cells)),
                                   clone=clone_capture(cells, w=w))
        g = rec["g_row"]
        assert ok is False and rec["conditions"][em.M_G_ROW_CONDITION] is False, name
        assert g["explained"] == {} and list(g["unexplained"]) == ["dose_not_population_residual"], name
        assert g["n_unexplained"] == len(cells), name


def test_m_explains_pub_count_cells_of_a_new_event_for_an_incumbent_outside_u5(tmp_path, report):
    """j1a-15: after the 3i fetch the clone's dept rows count an out-of-U5 incumbent's papers from the R1 patch,
    prodlib's network rows from the snapshot (04 keeps pub_count; its note: prodlib rows' pub_count and U5 are
    different sources, as in October). Those cells are explained, in their own class."""
    cells = j1a09_cells() + [(OUTSIDE, NEW_EV, 2010, "pub_count", 8.0, 7.0),
                             (OUTSIDE, NEW_EV, 2011, "pub_count_ex_star", 11.0, 10.0)]
    res = union_result(g_row_mismatches=len(cells))
    ok, rec = em.gdose_verdict("M", prediction(), res, clone=clone_capture(cells))
    assert ok is True
    g = rec["g_row"]
    assert g["n_unexplained"] == 0 and g["explained"]["pub_count_source_new_event_outside_u5"]["n_cells"] == 2
    assert g["explained"][EXPLAINED_C]["n_cells"] == 12
    for c in ((INSIDE, NEW_EV, 2012, "pub_count", 2.0, 3.0), (OUTSIDE, OLD_EV, 2004, "pub_count", 2.0, 3.0)):
        ok2, rec2 = em.gdose_verdict("M", prediction(), union_result(g_row_mismatches=13),
                                     clone=clone_capture(j1a09_cells() + [c]))
        assert ok2 is False and rec2["g_row"]["n_unexplained"] == 1, c


@pytest.mark.parametrize("cell, cls", [
    ((OUTSIDE, NEW_EV, 2012, "age_gap", 3.0, 4.0), "age_gap"),
    ((OUTSIDE, NEW_EV, 2012, "dose_topic", "NA_mismatch", float("nan"), 0.4), "na_mismatch"),
    ((OUTSIDE, NEW_EV, 2012, "age_gap", "NA_mismatch", 3.0, None), "na_mismatch"),
    ((OUTSIDE, NEW_EV, 2016, "row_missing_in_old"), "row_missing_in_old"),
    ((OUTSIDE, OLD_EV, 2004, "fwci_frac", 0.0413, 0.9496), "outcome_old_event"),
    ((OUTSIDE, OLD_EV, 2004, "fwci_mean_ex_star", 1.0, 2.0), "outcome_old_event"),
    ((INSIDE, NEW_EV, 2012, "fwci_frac", 0.0413, 0.9496), "outcome_inside_u5"),
    ((OUTSIDE, NEW_EV, 2012, "something_else", 2.0, 3.0), "other"),
])
def test_m_g_row_mismatches_outside_the_two_classes_stop(tmp_path, report, cell, cls):
    cells = j1a09_cells() + [cell]
    res = union_result(g_row_mismatches=len(cells))
    out = tmp_path / "stage_out"
    with pytest.raises(em.MStop) as e:
        em.gdose_step(out, "M", prediction(), res, override=True, clone=clone_capture(cells))
    assert e.value.code == "GDOSE_UNEXPLAINED"
    assert not (out / em.GDOSE_REPORT).exists()
    body = json.loads((out / "stop_report_gdose.json").read_text(encoding="utf-8"))
    assert [k for k, v in body["conditions"].items() if not v] == [em.M_G_ROW_CONDITION]
    g = body["g_row"]
    assert (g["n_explained"], g["n_unexplained"]) == (12, 1) and list(g["unexplained"]) == [cls]
    assert set(g["unexplained"][cls]["ids"]) == {cell[0], cell[1]}
    assert g["explained"][EXPLAINED_C]["n_cells"] == 12
    assert set(_walk_keys(body)) <= em.GDOSE_KEYS
    em.check_report_ids_only(body)


def test_m_g_row_rule_ties_the_capture_to_the_clones_own_count(report):
    cells = j1a09_cells()
    # fewer captured cells than the clone counted: nothing counts as explained
    ok, rec = em.gdose_verdict("M", prediction(), union_result(g_row_mismatches=13), clone=clone_capture(cells))
    g = rec["g_row"]
    assert ok is False and g["n_explained"] == 0 and "capture_not_tied_to_clone_count" in g["unexplained"]
    # no capture: every reported mismatch is unexplained; 0 reported needs no capture (October's condition)
    ok, rec = em.gdose_verdict("M", prediction(), union_result(g_row_mismatches=3))
    assert ok is False and rec["g_row"]["n_unexplained"] == 3 and rec["g_row"]["captured"] is False
    ok, rec = em.gdose_verdict("M", prediction(), union_result())
    assert ok is True and rec["g_row"]["n_unexplained"] == 0
    # G_SUM must still be ok
    res = union_result(g_row_mismatches=12)
    res["report"]["G_SUM"]["ok"] = False
    ok, rec = em.gdose_verdict("M", prediction(), res, clone=clone_capture(cells))
    assert ok is False and rec["conditions"][em.M_G_ROW_CONDITION] is False and rec["g_row"]["n_unexplained"] == 0


def test_b0_keeps_octobers_g_row_verdict_byte_for_byte(tmp_path, report):
    cells = j1a09_cells()
    res = union_result(g_row_mismatches=len(cells))
    want = R.override_is_justified(prediction(), res)
    got = em.gdose_verdict("B0", prediction(), res, clone=clone_capture(cells))
    assert json.dumps(got, sort_keys=True) == json.dumps(want, sort_keys=True)
    assert got[0] is False and got[1]["conditions"][em.OCTOBER_G_ROW_CONDITION] is False and "g_row" not in got[1]
    blobs = []
    for k, clone in enumerate((clone_capture(cells), None)):
        out = tmp_path / f"b0_{k}"
        with pytest.raises(em.MStop) as e:
            em.gdose_step(out, "B0", prediction(), res, override=True, clone=clone)
        assert e.value.code == "GDOSE_UNEXPLAINED"
        blobs.append((out / "stop_report_gdose.json").read_bytes())
    assert blobs[0] == blobs[1]                          # the capture changes no byte of B0's report
    body = json.loads(blobs[0])
    assert "g_row" not in body and body["conditions"][em.OCTOBER_G_ROW_CONDITION] is False


# A toy union clone: it keeps the real clone's names (report, mism, need_outcomes, _NEW_EV, sample_both, W, worst,
# diffs), dumps its report, exits 2 on a gate FAIL (run_union's override intercepts that) and then writes its files.
TOY_CLONE = '''
import json, os, sys
cfg = json.load(open(sys.argv[1]))
spec = json.load(open(os.environ["TOY_CLONE_SPEC"]))
W = 5
_NEW_EV = set(spec["new_events"])
need_outcomes = sorted(spec["need_outcomes"])
mism = [tuple(m) for m in spec["mism"]]
sample_both = sorted({(m[0], m[1]) for m in mism})
worst = [("A5047860864", "A5046379417:2006", 0.3, 0.2303)]
diffs = [0.0697, 0.0]
report = {"G_DOSE": {"n": 200, "missing_side": 0, "max_abs_diff": 0.0697, "share_exact_1e-9": 0.885},
          "G_ROW": {"sampled_both": len(sample_both), "mismatches": len(mism), "dose_tolerated_le_0.01": 0,
                    "fill_divergence": 0, "examples": [list(map(str, x)) for x in mism[:12]]},
          "G_SUM": {"total": 22, "old": 11, "new": 11, "ok": True},
          "frame": {"rows": 22, "relationships": 2, "by_channel": {"both": 11, "dept_only": 11}}, "GATE": "FAIL"}
json.dump(report, open(cfg["OUT_REPORT"], "w"), indent=1, default=str)
if report["GATE"] != "PASS":
    sys.exit(2)
for k in ("OUT_FRAME", "OUT_REL"):
    open(cfg[k], "w").write("toy\\n")
'''


def _toy_clone(tmp_path, monkeypatch, cells) -> pathlib.Path:
    clone = tmp_path / "toy_clone.py"
    clone.write_text(TOY_CLONE, encoding="utf-8")
    spec = tmp_path / "toy_clone_spec.json"
    spec.write_text(json.dumps({"mism": cells, "need_outcomes": [OUTSIDE], "new_events": [NEW_EV]}), encoding="utf-8")
    monkeypatch.setattr(L, "CLONE", clone)
    monkeypatch.setenv("TOY_CLONE_SPEC", str(spec))
    return clone


def _out_cfg(d: pathlib.Path) -> dict:
    return {k: str(d / "data" / n) for k, n in (("OUT_FRAME", "frame.csv"), ("OUT_REPORT", "build_report.json"),
                                                 ("OUT_REL", "relationships.csv"))}


def test_the_capture_hook_reads_the_clones_lists_through_run_union(tmp_path, monkeypatch):
    cells = j1a09_cells()
    _toy_clone(tmp_path, monkeypatch, cells)
    real = json.dump
    d = tmp_path / "union"
    with em.clone_g_row_capture() as cap:
        res = L.run_union(_out_cfg(d), d, d / "union.log", override_gdose_gate=True)
    assert json.dump is real                                  # both wrappers are gone again
    assert res["gate_overridden"] is True and res["exit"] == 0
    assert res["drawn_residuals_gt_1e-9"][0]["pid"] == "A5047860864"      # run_union's own capture still works
    assert cap["mism"] == [tuple(c) for c in cells] and cap["W"] == 5
    assert cap["need_outcomes"] == {OUTSIDE} and cap["new_events"] == {NEW_EV}
    assert cap["sample_both"] == [(OUTSIDE, NEW_EV)]
    # without the override run_union does not wrap json.dump: the hook alone sees the clone
    d2 = tmp_path / "union2"
    with em.clone_g_row_capture() as cap2:
        res2 = L.run_union(_out_cfg(d2), d2, d2 / "union.log")
    assert json.dump is real and res2["exit"] == 2 and cap2["mism"] == cap["mism"]
    # a dump that is not the clone's report is not captured
    with em.clone_g_row_capture() as cap3:
        json.dump({"G_DOSE": {}, "G_ROW": {}}, io.StringIO())
    assert cap3 == {}


def _union_ctx(tmp_path, name: str) -> types.SimpleNamespace:
    sh = L.fs08.Shadow(tmp_path / name / "shadow" / "v2_output")
    sh.write(L.PATCH_A_REL, b'{"author_id": "A1"}\n', "toy patch")
    prov = tmp_path / name / "prov.csv"
    prov.write_text("author_id,name,school,arrival\nA5039825487,,anu,2015\n", encoding="utf-8")
    p = tmp_path / name
    return types.SimpleNamespace(cfg=types.SimpleNamespace(name=name, ruling=lambda rid: "pass_h4"), v2=p / "v2",
                                 net1=p / "net1.csv", roster=p / "roster.parquet", ledger=p / "ledger.csv",
                                 star_set=p / "star_set.parquet", sh=sh, prov=prov, work=p / "work",
                                 out=p / "stage_out", prediction=prediction(), report={})


def test_the_union_step_hands_the_clones_g_row_to_the_m_verdict_only(tmp_path, monkeypatch, report):
    _toy_clone(tmp_path, monkeypatch, j1a09_cells())
    ctx = _union_ctx(tmp_path, "M")
    em.Steps().union(ctx)
    g = ctx.report["gdose"]["g_row"]
    assert ctx.report["gdose"]["code"] == "OK_OVERRIDDEN" and g["explained"][EXPLAINED_C]["n_cells"] == 12
    assert json.loads((ctx.out / em.GDOSE_REPORT).read_text(encoding="utf-8"))["g_row"] == g
    # B0 keeps October's condition: the same 12 mismatches stop it
    b0 = _union_ctx(tmp_path, "B0")
    with pytest.raises(em.MStop) as e:
        em.Steps().union(b0)
    assert e.value.code == "GDOSE_UNEXPLAINED"
    body = json.loads((b0.out / "stop_report_gdose.json").read_text(encoding="utf-8"))
    assert "g_row" not in body and body["conditions"][em.OCTOBER_G_ROW_CONDITION] is False


def test_pub_count_source_needs_an_api_backed_incumbent(report):
    """Codex delta-3 #6: the class says the clone counts the incumbent's papers from the patch; an incumbent
    outside U5 whom the clone counts from the U1 edges (no patch rows) is not explained."""
    cells = j1a09_cells() + [(OUTSIDE, NEW_EV, 2010, "pub_count", 8.0, 7.0)]
    ok, rec = em.gdose_verdict("M", prediction(), union_result(g_row_mismatches=len(cells)),
                               clone=clone_capture(cells, api_persons=()))
    assert ok is False
    assert rec["g_row"]["n_unexplained"] == 1
