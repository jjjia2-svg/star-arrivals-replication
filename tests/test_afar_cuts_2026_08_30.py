# -*- coding: utf-8 -*-
"""2026-08-30 Panel 3 respecification (dose > 0) — registered as canonical, 2026-09-10.

The manuscript has printed the dose > 0 Panel 3 cell (econ +0.044, chem -0.466, math +0.041)
since 2026-08-30, but until 2026-09-10 the six golds, the seven derived frames and the date-shift
inputs behind it were untracked, unlisted in every MANIFEST, and partly read from the git-ignored
`output/` tree. `analysis/run_all.sh` still estimated only the retired median cut and
`tools/compare_all.py` reported six MISSING cells. This file pins the registration so that the
"one command reproduces everything" claim holds again, and records the DECISION taken on the
2026-08-30 open item in the build log: the cut frames stay in `data/frames/` (the ledger reads them there;
they ARE the main specification's panels) but are declared as DERIVED by analysis code
(`analysis/robustness/p3_afar_cuts/build_afar_cut.py`, whose `med` cut reproduces the frozen
`afar` stage frames exactly — that reproduction is the control) rather than by a frames-layer
stage, mirroring how the six `p3_slim_*` files are declared as `make_slim.py` outputs.

Each assert names the claim it pins. Written red-first on 2026-09-10.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))
from analysis.lib.compare_json import compare                         # noqa: E402

EXP = REPO / "analysis" / "expected"
FRAMES = REPO / "data" / "frames"
CUTS = REPO / "data" / "robustness_afar_cuts_2026-08-30"
FIELDS = ("econ", "chemistry", "math_stats")

#: the six golds of the 2026-08-30 respecification: `pos` = the paper's Panel 3 since 2026-08-30
#: (both incumbents share at least one subfield with the star), `med` = the former median cut,
#: kept as the robustness/control cell. Filenames are what the ledger and the sentinel read.
AFAR_CUT_CELLS = frozenset(f"P3{s}_{f}_A_far.json" for s in ("pos", "med") for f in FIELDS)
#: the seven data/frames files those cells and the ledger read, produced by build_afar_cut.py
DERIVED_FRAMES = frozenset({f"p3_afar_{s}_{f}.parquet" for s in ("pos", "med") for f in FIELDS}
                           | {"p3_afar_counts_by_spec.csv"})
BUILDER = "analysis/robustness/p3_afar_cuts/build_afar_cut.py"


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _manifest(p: pathlib.Path) -> dict[str, str]:
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            h, rel = line.split("  ", 1)
            out[rel] = h
    return out


# ---------------------------------------------------------------------------------------------
# 1. the golds are frozen, sourced, and listed
# ---------------------------------------------------------------------------------------------

def test_the_six_cut_golds_exist_and_are_byte_equal_to_their_frozen_sources():
    """analysis/expected/P3{pos,med}_*_A_far.json was a copy of the run JSON frozen under
    data/robustness_afar_cuts_2026-08-30/estimates/ (label P3cut_{spec}_{field}) until 2026-09-23, when
    analysis/expected/ was promoted to the October caliber (cal2026-10). Both halves are pinned: the 08-30
    frozen sources are exactly the bytes analysis/expected/ held until the promotion (`old_sha256` in
    data/cal2026-10/expected_refreeze_2026-10.json), and the gold now shipped is byte for byte the October
    run's cell data/cal2026-10/estimates/P3{spec}_{field}_A_far.json (`new_sha256` there; listed in
    data/cal2026-10/MANIFEST.sha256)."""
    refreeze = json.loads((REPO / "data/cal2026-10/expected_refreeze_2026-10.json").read_text(encoding="utf-8"))
    oct_manifest = _manifest(REPO / "data/cal2026-10/MANIFEST.sha256")
    for name in sorted(AFAR_CUT_CELLS):
        gold = EXP / name
        assert gold.is_file(), name
        m = re.fullmatch(r"P3(pos|med)_(\w+)_A_far\.json", name)
        src = CUTS / "estimates" / f"P3cut_{m.group(1)}_{m.group(2)}.json"
        assert src.is_file(), f"frozen source missing: {src.relative_to(REPO)}"
        rec = refreeze["expected"][name[:-len(".json")]]
        assert _sha(src) == rec["old_sha256"], f"{name}: the 08-30 frozen source is not what analysis/expected held until the promotion"
        # 2026-09-23 October pin
        oct_src = REPO / "data/cal2026-10/estimates" / name
        assert oct_src.is_file(), f"October source missing: {oct_src.relative_to(REPO)}"
        assert _sha(gold) == _sha(oct_src) == rec["new_sha256"], f"{name} is not the October run's cell byte for byte"
        assert oct_manifest.get(f"data/cal2026-10/estimates/{name}") == _sha(oct_src), f"{name}: October cell not pinned in data/cal2026-10/MANIFEST.sha256"


def test_the_expected_manifest_lists_all_29_golds_including_the_six():
    man = _manifest(EXP / "MANIFEST.sha256")
    assert len(man) == 29, sorted(man)
    for name in AFAR_CUT_CELLS:
        assert name in man, f"{name} not pinned in analysis/expected/MANIFEST.sha256"
        assert man[name] == _sha(EXP / name), f"{name}: manifest hash is stale"
    assert {p.name for p in EXP.glob("*.json")} == set(man), "expected/ and its manifest disagree"


def test_sources_md_names_the_six_and_their_frozen_directory():
    txt = (EXP / "SOURCES.md").read_text(encoding="utf-8")
    for name in AFAR_CUT_CELLS:
        assert name in txt, f"{name} absent from analysis/expected/SOURCES.md"
    assert "robustness_afar_cuts_2026-08-30/estimates/" in txt


def test_the_gold_labels_carry_the_cut_they_were_run_at():
    """The driver names the file after its label; the gold keeps the run label (P3cut_pos_econ)
    while the filename carries the paper's cell name — run_all.sh renames after estimating."""
    for name in AFAR_CUT_CELLS:
        m = re.fullmatch(r"P3(pos|med)_(\w+)_A_far\.json", name)
        j = json.loads((EXP / name).read_text(encoding="utf-8"))
        assert j["label"] == f"P3cut_{m.group(1)}_{m.group(2)}", (name, j["label"])
        assert j["events"] and j["grps"], name


# ---------------------------------------------------------------------------------------------
# 2. the control: the median cut reproduces the frozen `afar`-stage cells
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("field", FIELDS)
def test_the_median_cut_gold_equals_the_frozen_afar_gold_except_for_its_label(field):
    """P3med_{f}_A_far (built by build_afar_cut.py at the pinned full-precision median) is
    compare_json-EQUAL to P3lb_{f}_A_far (the frozen 2026-08-28 caliber cell) in every field but
    `label`. This is what licenses trusting the `pos` cell from the same builder."""
    med = json.loads((EXP / f"P3med_{field}_A_far.json").read_text(encoding="utf-8"))
    lb = json.loads((EXP / f"P3lb_{field}_A_far.json").read_text(encoding="utf-8"))
    diffs = compare(med, lb)
    assert diffs == [f"label: {med['label']!r} != {lb['label']!r}"], diffs


# ---------------------------------------------------------------------------------------------
# 3. the derived frames are present, pinned, and declared
# ---------------------------------------------------------------------------------------------

def test_the_seven_derived_frames_are_present_and_pinned_in_the_data_manifest():
    man = _manifest(REPO / "data" / "MANIFEST.sha256")
    for name in sorted(DERIVED_FRAMES):
        f = FRAMES / name
        assert f.is_file(), name
        rel = f"data/frames/{name}"
        assert rel in man, f"{rel} not pinned in data/MANIFEST.sha256"
        assert man[rel] == _sha(f), f"{rel}: manifest hash is stale"
    assert (REPO / BUILDER).is_file()


def test_the_counts_by_spec_table_agrees_with_the_golds():
    """p3_afar_counts_by_spec.csv (pairs/events per cut) must match the golds it describes."""
    import csv
    rows = {(r["spec"], r["field"]): r
            for r in csv.DictReader(open(FRAMES / "p3_afar_counts_by_spec.csv", encoding="utf-8"))}
    for s in ("pos", "med"):
        for f in FIELDS:
            j = json.loads((EXP / f"P3{s}_{f}_A_far.json").read_text(encoding="utf-8"))
            r = rows[(s, f)]
            assert int(r["pairs"]) == int(j["grps"]), (s, f, r["pairs"], j["grps"])
            assert int(r["events"]) == int(j["events"]), (s, f, r["events"], j["events"])


# ---------------------------------------------------------------------------------------------
# 4. nothing the manuscript prints is read from the git-ignored output/ tree
# ---------------------------------------------------------------------------------------------

def test_the_ledger_reads_no_gitignored_path():
    src = (REPO / "analysis/paper/ledger_p3afar.py").read_text(encoding="utf-8")
    assert "output/afar_cuts" not in src and '"output" / "afar_cuts"' not in src, (
        "ledger_p3afar.py still reads output/afar_cuts (git-ignored): the date-shift and cut-grid "
        "numbers in sec4_p3.tex would have no reproducible source")
    for f in FIELDS:
        for s in ("s0", "s2"):
            assert (CUTS / "predate" / f"P3pos_{s}_{f}.json").is_file(), (s, f)
        for c in ("pos", "med", "abs04", "p75"):
            assert (CUTS / "estimates" / f"P3cut_{c}_{f}.json").is_file(), (c, f)


def test_the_afar_cuts_directory_has_a_manifest_that_verifies():
    import subprocess
    man = CUTS / "MANIFEST.sha256"
    assert man.is_file(), "data/robustness_afar_cuts_2026-08-30/MANIFEST.sha256 missing"
    listed = _manifest(man)                      # repo-relative paths (tools/write_manifest.py)
    on_disk = {p.relative_to(REPO).as_posix() for p in CUTS.rglob("*")
               if p.is_file() and p.name not in ("MANIFEST.sha256", ".DS_Store")}
    assert set(listed) == on_disk, {"listed-not-on-disk": sorted(set(listed) - on_disk),
                                    "on-disk-not-listed": sorted(on_disk - set(listed))}
    r = subprocess.run([sys.executable, str(REPO / "tools/verify_manifest.py"), str(man)],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "MANIFEST_OK" in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize("d", ["data/null_sim_pos_2026-08-30", "data/inference_afar_pos_2026-08-30",
                               "data/predate_p1_2026-08-30", "data/sensitivity_2026-08-30",
                               "data/robustness_2026-08-31", "data/paper_inputs",
                               "data/cloud_custody_null_perm_2026-08-30"])
def test_every_2026_08_30_31_artifact_directory_the_ledgers_read_has_a_manifest(d):
    import subprocess
    man = REPO / d / "MANIFEST.sha256"
    assert man.is_file(), f"{d}/MANIFEST.sha256 missing"
    r = subprocess.run([sys.executable, str(REPO / "tools/verify_manifest.py"), str(man)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# ---------------------------------------------------------------------------------------------
# 5. the one-command reproduction estimates the current specification
# ---------------------------------------------------------------------------------------------

def test_run_all_estimates_both_cut_specs_for_every_field_and_renames_to_the_gold_name():
    """run_all.sh runs the canon's cell lists (config/r1/cells); each list must hold both cut specs for every
    field, called with the gold's own label and saved under the gold's filename (out_name)."""
    import csv
    sh = (REPO / "analysis/run_all.sh").read_text(encoding="utf-8")
    assert "run_all_stages.py cells" in sh, "run_all.sh does not run the canon's cell lists"
    assert '"$SAR_OUT/$out_name"' in sh, "run_all.sh must save each result under its row's out_name"
    for lists in (("oct29.tsv",), ("M.tsv", "M_evcl.tsv")):
        rows = []
        for name in lists:
            with open(REPO / "config" / "r1" / "cells" / name, encoding="utf-8", newline="") as fh:
                rows += list(csv.DictReader(fh, delimiter="\t"))
        cut = {(r["label"], r["driver"], r["frame"], r["out_name"], r["stack"]) for r in rows}
        for s in ("pos", "med"):
            for f in FIELDS:
                assert (f"P3cut_{s}_{f}", "analysis/estimation/run_p3_tp.R", f"p3_afar_{s}_{f}.parquet",
                        f"P3{s}_{f}_A_far.json", "rmac") in cut, (lists, s, f)


def test_the_stale_median_is_the_papers_cut_wording_is_gone():
    for rel in (BUILDER, "data/robustness_afar_cuts_2026-08-30/README.md"):
        txt = (REPO / rel).read_text(encoding="utf-8")
        assert "NOT A CHANGE TO THE PAPER'S SPECIFICATION" not in txt, rel
        assert "Not a change to the paper's specification" not in txt, rel
        assert "the paper's cut (control)" not in txt, rel
        assert "**the paper's cut**" not in txt, rel
