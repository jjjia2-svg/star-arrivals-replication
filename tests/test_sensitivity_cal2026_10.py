"""tests/test_sensitivity_cal2026_10.py — GROUP `sensitivity` on the October canon (2026-09-23).

Pins what analysis/robustness/sensitivity/run_sensitivity_cal2026_10.py froze under
data/cal2026-10/robustness/{sensitivity_controls,departure,doublestar,nocentre}/ and its report
sensitivity_report.json: every control the report calls EQUAL is compare_json-EQUAL to its gold on disk
(recomputed here, not trusted), every OK cell's JSON exists with the label and headline the report
records, every STOP is recorded with a reason and has no estimate JSON, the departure counts agree with
the builders' own reports, the MANIFESTs verify, and the seven script edits default to their old values.
Read-only; needs neither R nor the data disk.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
ROB = REPO / "data/cal2026-10/robustness"
REPORT = ROB / "sensitivity_report.json"
FIELDS = ("econ", "chemistry", "math_stats")
S = REPO / "analysis/robustness/sensitivity"

pytestmark = pytest.mark.skipif(not REPORT.is_file(), reason="sensitivity_report.json not frozen")


def _rep() -> dict:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _compare(new: pathlib.Path, gold: pathlib.Path) -> bool:
    proc = subprocess.run([sys.executable, "-m", "analysis.lib.compare_json", str(new), str(gold)],
                          cwd=REPO, capture_output=True, text=True)
    return proc.returncode == 0 and proc.stdout.strip().startswith("EQUAL")


def _manifest(d: pathlib.Path) -> dict[str, str]:
    lines = (d / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines()
    return {ln.split("  ", 1)[1]: ln.split("  ", 1)[0] for ln in lines if "  " in ln}


def test_report_status_and_inputs_are_the_promoted_canon():
    r = _rep()
    assert r["group"] == "sensitivity" and r["caliber"] == "cal2026-10"
    assert r["status"] in ("DONE", "DONE_WITH_STOPS")
    assert r["inputs"]["frames_match_data_MANIFEST"] and all(r["inputs"]["frames_match_data_MANIFEST"].values())
    for relp, h in r["inputs"]["sha256"].items():
        if relp.startswith(("data/frames/", "analysis/expected/", "analysis/estimation/")):
            assert _sha(REPO / relp) == h, f"input moved since the run: {relp}"


def test_every_frame_control_recomputes_equal():
    r = _rep()
    ctl = r["controls"]["frame_controls"]
    assert len(ctl) == 9 and r["controls"]["frame_controls_all_equal"] is True
    for label, c in ctl.items():
        assert c["compare"]["verdict"] == "EQUAL", label
        assert _compare(REPO / c["json"], REPO / c["compare"]["gold"]), label
    p3 = r["controls"]["p3_full_math_controls"]
    assert p3["pairs_oct"]["compare"]["verdict"] == "EQUAL"          # make_slim + run_p3.R reproduce the October gold
    assert _compare(REPO / p3["pairs_oct"]["cell"]["json"], REPO / "analysis/expected/P3_fnfix_math_stats.json")
    assert p3["pairs_0828"]["compare"]["verdict"] in ("EQUAL", "NOT_EQUAL")


def _cells(section: dict) -> dict:
    return section.get("cells", {})


@pytest.mark.parametrize("section", ["departure", "doublestar"])
def test_ok_cells_exist_with_label_and_headline_and_stops_have_none(section):
    r = _rep()
    sec = r[section]
    cells = _cells(sec)
    assert cells, section
    for label, c in cells.items():
        if c["status"] == "OK":
            js = REPO / c["json"]
            assert js.is_file() and _sha(js) == c["json_sha256"], label
            j = json.loads(js.read_text(encoding="utf-8"))
            assert j["label"] == label
            h = c["headline"]
            if "channels" in h:
                for ch, v in h["channels"].items():
                    assert j["channels"][ch]["ate"] == v["ate"] and j["channels"][ch]["se"] == v["se"], (label, ch)
            elif "pair_cluster" in h:
                assert j["pair_cluster"]["ate"] == h["pair_cluster"]["ate"], label
            else:
                assert j["ate"] == h["ate"] and j["se"] == h["se"], label
        else:
            assert c["status"].startswith("STOPPED") or c["status"].startswith("FAILED") or c["status"] == "DRIVER_ERROR", (label, c["status"])
            if c["status"].startswith("STOPPED"):
                assert c.get("reason"), label
                assert not (ROB / section / "estimates" / f"{label}.json").exists(), label


def test_departure_counts_agree_with_the_builders_reports_and_the_ledger():
    r = _rep()
    dep = r["departure"]
    assert dep["ledger"] == "data/departure_verification_2026-09-10/departure_verified_2026-09-10.csv"  # not shipped
    assert dep["ledger_rows"] == 187
    # public copy: the 187-row departure ledger carries names, destinations and quotes and is not
    # published (restricted-access deposit); its recorded sha256 is checked where the file exists
    if (REPO / dep["ledger"]).is_file():
        assert _sha(REPO / dep["ledger"]) == dep["ledger_sha256"]
    for f in FIELDS:
        d = dep["fields"][f]
        b = json.loads((REPO / d["build_report"]).read_text(encoding="utf-8"))
        assert d["rule_A_drops_events"] == len(b["A_dropped_in_frame"]) == len(d["rule_A_dropped_event_ids"])
        assert d["rule_B_recodes_events"] == len(b["B_recoded_in_frame"]) == len(d["rule_B_recode_years"])
        assert d["noop_control"] == "BYTE_EQUAL" and b["noop_control"] == "BYTE_EQUAL"
        assert d["frames_accounting"] == b["frames"]
        # rule A drops are a subset of rule B's dated departures or `left_within_window` verdicts: both non-empty here
        assert d["rule_A_drops_events"] >= 1 and d["rule_B_recodes_events"] >= d["rule_A_drops_events"] - len(
            [k for k in d["rule_A_dropped_event_ids"] if k not in d["rule_B_recode_years"]])
        expected_cells = {f"P1dep{v}_{f}" for v in "AB"} | {f"P2dep{v}_{f}" for v in "AB"} | {f"P3dep{v}_pos_{f}_A_far" for v in "AB"}
        assert expected_cells <= set(dep["cells"]), f
    # econ: the ledger is keyed on the 2026-08-28 event set — the October re-key is disclosed, not silently matched
    e = dep["fields"]["econ"]
    assert e["october_events_without_ledger_row"] == ["A5091326353:2009"]
    assert {x["event_id"] for x in e["ledger_rows_not_in_october_frame"]} == {
        "A5041849660:2003", "A5090515599:2009", "A5102739182:2010", "A5110738002:2009"}


def test_doublestar_counts_and_the_stopped_full_panel_cell():
    r = _rep()
    ds = r["doublestar"]
    for f in FIELDS:
        c = ds["counts"][f]
        assert c["dropped"] + c["kept"] == c["events"]
    assert ds["counts"]["chemistry"]["events"] == 38 and ds["counts"]["math_stats"]["events"] == 33
    assert ds["counts"]["econ"]["events"] == 113
    assert ds["event_tables"]["chemistry_byte_equal_check"] and ds["event_tables"]["math_stats_byte_equal_check"]
    for f in ("chemistry", "math_stats"):
        assert ds["drop_table_vs_2026-08-29"][f]["drop_table_identical_to_2026-08-29"], f
    full = ds["cells"]["P3ds_math_stats_full"]
    # 2026-09-23 re-pin: the cell now runs on the OCTOBER pairs table (SAR_PAIRS_MATH_STATS, the input
    # override note in the report); it is OK iff that table's positive control is EQUAL, and the 08-28 table's
    # control is recorded DIFF (the builder's original stop reason)
    p3_oct = r["controls"]["p3_full_math_controls"]["pairs_oct"]["compare"]["verdict"]
    p3_0828 = r["controls"]["p3_full_math_controls"]["pairs_0828"]["compare"]["verdict"]
    assert (full["status"] == "OK") == (p3_oct == "EQUAL") and p3_0828 == "NOT_EQUAL"
    assert "input_override_note_2026-09-23" in r
    assert ds["complement"]["status"] == "OK" and ds["complement"]["cell"]["label"] == "P1dsC_econ"
    assert not (ROB / "doublestar/complement/NOT_RUN.md").exists()


def test_nocentre_is_recorded_not_fixed():
    r = _rep()
    nc = r["nocentre"]
    if nc.get("status", "").startswith("SKIPPED"):
        pytest.skip("nocentre skipped in this run")
    for k in ("run_nocentre", "run_nocentre_afar_pos"):
        assert nc[k]["status"] in ("OK", "STOPPED_CONTROL_NOT_EQUAL", "STOPPED_PRECONDITION"), k
        if nc[k]["status"] == "OK":
            assert nc[k].get("cells"), k
        # (the 08-29 launchers' STOP left no cells of their own; the October launcher's cells live in
        #  nocentre/estimates/ since 2026-09-23, so their absence is no longer asserted here)
    # 2026-09-23 re-pin: the check was completed through the October chain (run_nocentre_cal2026_10.py);
    # the sensitivity report points at its report, NOT_RUN.md is gone and the estimates exist
    oct_ = nc["october_launcher_2026-09-23"]
    assert oct_["status"] == "OK" and (REPO / oct_["report"]).is_file()
    assert not (ROB / "nocentre/NOT_RUN.md").exists()
    assert len(list((ROB / "nocentre/estimates").glob("*.json"))) == 7


@pytest.mark.parametrize("d", ["sensitivity_controls", "departure", "doublestar", "nocentre"])
def test_manifests_pin_every_product(d):
    root = ROB / d
    if not root.is_dir():
        pytest.skip(f"{d} absent")
    man = _manifest(root)
    files = {p.relative_to(REPO).as_posix() for p in root.rglob("*")
             if p.is_file() and p.name not in ("MANIFEST.sha256", ".DS_Store")}
    assert set(man) == files, sorted(set(man) ^ files)[:10]
    for relp, h in man.items():
        assert _sha(REPO / relp) == h, relp


def test_script_edits_default_to_the_old_values():
    src = {p: (S / p).read_text(encoding="utf-8") for p in (
        "build_departure.py", "build_doublestar.py", "build_doublestar_complement.py", "run_doublestar_complement.sh",
        "run_nocentre.py", "run_nocentre_afar_pos.py", "run_nocentre_afar_pos.sh")}
    assert 'REPO / FREEZE_ROOT[spec] / "afar_event_map"' in src["build_departure.py"] and "SAR_AFAR_MAP_DIR" in src["build_departure.py"]
    assert 'f"{FREEZE_ROOT[args.spec]}/doublestar"' in src["build_doublestar.py"]
    assert '"data/robustness_2026-09-12_dscomp"' in src["build_doublestar_complement.py"]
    assert "${SAR_ROBUST_OUTDIR:-data/robustness_2026-09-12_dscomp}" in src["run_doublestar_complement.sh"]
    assert "${SAR_ROBUST_STAGE:-/private/tmp/sar_dscomp_2026-09-12}" in src["run_doublestar_complement.sh"]
    assert '"data/robustness_2026-08-29_b/nocentre"' in src["run_nocentre.py"]
    assert '"data/robustness_2026-09-10_p3pos/nocentre"' in src["run_nocentre_afar_pos.py"]
    assert "${SAR_ROBUST_MANIFEST_DIR:-data/robustness_2026-09-10_p3pos}" in src["run_nocentre_afar_pos.sh"]
    # no estimation line touched: the R drivers are the pinned verbatim copies
    for drv in ("run_p1.R", "run_p2.R", "run_p3_tp.R", "run_p3.R"):
        assert re.search(r"Verbatim copy of", (REPO / "analysis/estimation" / drv).read_text(encoding="utf-8"))
