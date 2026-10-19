"""Sentinel for the predate_cuts robustness group on the October caliber (2026-09-23).

Pins, from the frozen products under data/cal2026-10/robustness/{predate,predate_p1,afar_cuts}/:
  * every control the group ran is compare_json-EQUAL to its gold in analysis/expected/ (recomputed
    here, not read from the report);
  * every shifted cell sits on exactly its gold's panel (same row count — the shift changes D, not
    the frame);
  * the three product MANIFESTs verify and the report's own hashes agree with the files on disk.
Skips (does not fail) when the products are absent, e.g. on a checkout that does not carry them.
"""
import hashlib, json, pathlib
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
ROB = REPO / "data/cal2026-10/robustness"
X = REPO / "analysis/expected"
REPORT = ROB / "predate_cuts_report.json"
FIELDS = ("econ", "chemistry", "math_stats")

if not REPORT.is_file():
    pytest.skip("predate_cuts products not present", allow_module_level=True)

import sys
sys.path.insert(0, str(REPO))
from analysis.lib.compare_json import compare  # noqa: E402


def jl(p): return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


CONTROLS = [
    (ROB / "predate/control/P3lb_econ_A_far.json", X / "P3lb_econ_A_far.json"),
    (ROB / "predate/control/P2_econ_fnfix.json", X / "P2_econ_fnfix.json"),
    (ROB / "predate/control/P3_fnfix_math_stats.json", X / "P3_fnfix_math_stats.json"),
    (ROB / "predate_p1/control/P1_econ_fnfix.json", X / "P1_econ_fnfix.json"),
    (ROB / "predate_p1/control/P1_fnfix_chemistry.json", X / "P1_fnfix_chemistry.json"),
    (ROB / "predate_p1/control/P1_fnfix_math_stats.json", X / "P1_fnfix_math_stats.json"),
] + [(ROB / f"afar_cuts/estimates/P3cut_{s}_{f}.json", X / f"P3{s}_{f}_A_far.json") for f in FIELDS for s in ("pos", "med")] \
  + [(ROB / f"afar_cuts/predate/control/P3cut_pos_{f}.json", X / f"P3pos_{f}_A_far.json") for f in FIELDS]


@pytest.mark.parametrize("new,gold", CONTROLS, ids=[c[0].name + "~" + c[1].name for c in CONTROLS])
def test_every_control_is_equal_to_its_gold(new, gold):
    assert new.is_file(), new
    assert compare(jl(new), jl(gold)) == []


PANELS = [
    (ROB / "predate/P2pd2_econ.json", X / "P2_econ_fnfix.json", "rows"),
    (ROB / "predate/P2pd2_chemistry.json", X / "P2_fnfix_chemistry.json", "rows"),
    (ROB / "predate/P2pd2_math_stats.json", X / "P2_fnfix_math_stats.json", "rows"),
    (ROB / "predate/P3pd2_econ_A_far.json", X / "P3lb_econ_A_far.json", "rows"),
    (ROB / "predate/P3pd2_chemistry_A_far.json", X / "P3lb_chemistry_A_far.json", "rows"),
    (ROB / "predate/P3pd2_math_stats_A_far.json", X / "P3lb_math_stats_A_far.json", "rows"),
    (ROB / "predate/P3pd2_math_stats_full.json", X / "P3_fnfix_math_stats.json", "rows"),
    (ROB / "predate_p1/P1pd2_econ.json", X / "P1_econ_fnfix.json", "rows_kept"),
    (ROB / "predate_p1/P1pd2_chemistry.json", X / "P1_fnfix_chemistry.json", "rows_kept"),
    (ROB / "predate_p1/P1pd2_math_stats.json", X / "P1_fnfix_math_stats.json", "rows_kept"),
] + [(ROB / f"afar_cuts/predate/P3pos_s2_{f}.json", X / f"P3pos_{f}_A_far.json", "rows") for f in FIELDS]


@pytest.mark.parametrize("cell,gold,key", PANELS, ids=[p[0].name for p in PANELS])
def test_shifted_cell_sits_on_its_golds_panel(cell, gold, key):
    c, g = jl(cell), jl(gold)
    assert c[key] == g[key]
    assert c["predate"]["shift"] == 2


def test_report_controls_all_equal_and_hashes_match_disk():
    rep = jl(REPORT)
    assert rep["controls_summary"]["not_equal"] == []
    assert rep["controls_summary"]["n"] == len(CONTROLS) + 6          # + the six pos/med frame content controls
    for cell in rep["cells"].values():
        assert sha(REPO / cell["file"]) == cell["sha256"], cell["file"]
    for rel, h in rep["inputs"].items():
        if rel.startswith("output/"):
            continue                                                 # the econ pair table is not shipped
        assert sha(REPO / rel) == h, rel


@pytest.mark.parametrize("d", ["predate", "predate_p1", "afar_cuts"])
def test_product_manifest_verifies(d):
    man = ROB / d / "MANIFEST.sha256"
    listed = {}
    for line in man.read_text().splitlines():
        if line.strip():
            h, rel = line.split("  ", 1); listed[rel] = h
    on_disk = {p.relative_to(REPO).as_posix() for p in (ROB / d).rglob("*") if p.is_file() and p.name not in ("MANIFEST.sha256", ".DS_Store")}
    assert set(listed) == on_disk
    for rel, h in listed.items():
        assert sha(REPO / rel) == h, rel
