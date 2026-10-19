"""tests/test_nocentre_afar_pos_2026_09_10.py — the ± research-centre check on the dose>0 Panel 3 cell.

Pins what analysis/robustness/sensitivity/run_nocentre_afar_pos.{sh,py} froze under
data/robustness_2026-09-10_p3pos/nocentre/ on 2026-09-10: that every control it declares a STOP on
actually passed in the frozen report, that the two variant cells exist under the labels the
README cites, that the MANIFEST covers them, and that the one edit made to the canonical cut
builder for this check (an explicit `sources=` parameter on `build_afar_cut.build`) defaults to
the canon path. Read-only; needs neither the data disk nor R.
"""
from __future__ import annotations

import inspect
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
NC = REPO / "data/robustness_2026-09-10_p3pos/nocentre"
MANIFEST = REPO / "data/robustness_2026-09-10_p3pos/MANIFEST.sha256"
FIELDS = ("chemistry", "math_stats")


def _report() -> dict:
    return json.loads((NC / "nocentre_afar_pos_report.json").read_text(encoding="utf-8"))


def _manifest_paths() -> set[str]:
    return {line.split("  ", 1)[1] for line in MANIFEST.read_text(encoding="utf-8").splitlines()
            if line.strip()}


def test_every_declared_control_passed_in_the_frozen_report():
    r = _report()
    assert r["status"] == "OK", r["status"]
    assert r["spec"] == "pos" and r["fields"] == list(FIELDS)
    for f in FIELDS:
        assert r["control_checks"][f"relationships_{f}"] == "BYTE_EQUAL"
        assert r["control_checks"][f"becoming_{f}"] == "BYTE_EQUAL"
        assert r["control_checks"][f"p1_frame_{f}"]["ok"] is True
        assert r["control_afar_pos"][f]["verdict"] == "CONTENT_EQUAL", f
        assert r["control_afar_pos"][f]["frozen"] == f"data/frames/p3_afar_pos_{f}.parquet"
        assert r["control_estimates"][f"P3cut_pos_{f}"]["verdict"] == "EQUAL", f
        # the no-centre build is the 2026-08-29 variant: byte-stable files match its frozen sha256
        vs = r["variant_vs_2026-08-29"]["verdicts"]
        assert vs[f"relationships_{f}"] == "EQUAL" and vs[f"p2_{f}"] == "EQUAL", f


def test_the_two_variant_cells_exist_and_are_pinned():
    r = _report()
    paths = _manifest_paths()
    for f in FIELDS:
        cell = NC / "estimates" / f"P3nc_pos_{f}_A_far.json"
        assert cell.is_file(), cell
        j = json.loads(cell.read_text(encoding="utf-8"))
        assert j["label"] == f"P3nc_pos_{f}_A_far" and j["panel"] == "P3_topicpair"
        assert j["events"] == r["variant_afar_pos"][f]["events"]
        assert j["grps"] == r["variant_afar_pos"][f]["pairs"]
        assert j["rows"] == r["variant_afar_pos"][f]["rows"]
        assert cell.relative_to(REPO).as_posix() in paths, "variant cell not in the MANIFEST"
        ctl = NC / "estimates_control" / f"P3cut_pos_{f}.json"
        assert ctl.is_file() and ctl.relative_to(REPO).as_posix() in paths
    assert (NC / "nocentre_afar_pos_report.json").relative_to(REPO).as_posix() in paths


def test_variant_cells_are_not_the_with_centre_cells():
    """The check is only a check if the variant frames differ from canon: fewer pairs in both
    fields (−134 chem / −28 math centre people), and the estimate JSON is not the gold's."""
    r = _report()
    for f in FIELDS:
        assert r["variant_afar_pos"][f]["pairs"] < r["control_afar_pos"][f]["pairs"], f
        gold = json.loads((REPO / f"analysis/expected/P3pos_{f}_A_far.json").read_text())
        cell = json.loads((NC / "estimates" / f"P3nc_pos_{f}_A_far.json").read_text())
        assert cell["grps"] != gold["grps"], f


def test_build_afar_cut_sources_parameter_defaults_to_canon():
    sys.path.insert(0, str(REPO))
    from analysis.robustness.p3_afar_cuts import build_afar_cut as b   # noqa: PLC0415
    sig = inspect.signature(b.build)
    assert "sources" in sig.parameters and sig.parameters["sources"].default is None
    assert list(sig.parameters)[:3] == ["field", "cut_spec", "out_dir"], "positional API unchanged"
