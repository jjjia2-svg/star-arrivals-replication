# -*- coding: utf-8 -*-
"""tools/r1_classify_cal_tree.py (F2): config/r1/base_inputs.tsv and config/r1/read_allowlist_0828.txt."""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for p in (REPO / "tools", REPO / "pipeline" / "aws" / "r1"):
    sys.path.insert(0, str(p))
import r1_classify_cal_tree as cls  # noqa: E402
import sandbox as sb                # noqa: E402

R = cls.Rule
TOY_RULES = (
    R("data/cal2026-08-28/**", "base", "frozen canon", "toy: the 08-28 canon is custody material, never rebuilt"),
    R("data/cal2026-10/calls_*.csv", "base", "hand", "toy: signed calls are hand-made decision material"),
    R("data/frames/README.md", "base", "hand", "toy: the README beside the frames is written by hand"),
    R("data/cal2026-10/**", "product", "toy builder", "toy: every other October file is a program output"),
    R("data/frames/**", "product", "promote.py", "toy: the canon frames are promoted program outputs"),
    R("analysis/expected/**", "product", "promote.py", "toy: the frozen cell results are program outputs"),
)
TOY_INPUTS = (("data/cal2026-10r1/inputs/add_list_r1.json", "signed", "toy: the signed R1 add list, never rewritten"),)
TOY_FILES = ("data/cal2026-08-28/frames/p1.csv", "data/cal2026-08-28/MANIFEST.sha256", "data/cal2026-10/calls_2026-10.csv",
             "data/cal2026-10/frames/p1.csv", "data/cal2026-10/events_econ.csv", "data/frames/README.md",
             "data/frames/p1.csv", "analysis/expected/P1.json", "data/cal2026-10r1/inputs/add_list_r1.json",
             "pipeline/x.py", "data/cal2026-10r1/other.csv")


def _git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def toy(tmp_path):
    repo = tmp_path / "repo"
    for i, rel in enumerate(TOY_FILES):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(f"{rel} {i}\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "toy")
    return repo


def _blobs(repo, *paths):
    return {ln.split("\t", 1)[1]: ln.split()[1] for ln in _git(repo, "ls-files", "-s", "--", *paths).splitlines()}


def test_every_tracked_file_under_the_roots_gets_exactly_one_class(toy, tmp_path):
    out = tmp_path / "base_inputs.tsv"
    assert cls.main(["--repo", str(toy), "--out", str(out)], rules=TOY_RULES, r1_inputs=TOY_INPUTS) == 0
    rows = sb.load_tsv(out)
    under = _blobs(toy, *cls.ROOTS)
    assert len(under) == 8
    tree = {r["path"]: r for r in rows if r["class"] != "r1_input"}
    assert set(tree) == set(under) and len(tree) == len([r for r in rows if r["class"] != "r1_input"])
    assert all(r["git_blob"] == under[p] for p, r in tree.items())
    assert {p: r["class"] for p, r in tree.items()} == {
        "data/cal2026-08-28/frames/p1.csv": "base", "data/cal2026-08-28/MANIFEST.sha256": "base",
        "data/cal2026-10/calls_2026-10.csv": "base", "data/frames/README.md": "base",
        "data/cal2026-10/frames/p1.csv": "product", "data/cal2026-10/events_econ.csv": "product",
        "data/frames/p1.csv": "product", "analysis/expected/P1.json": "product"}
    assert all(len(r["reason"]) > 30 and r["producer"] for r in rows)
    extra = [(r["path"], r["git_blob"]) for r in rows if r["class"] == "r1_input"]
    assert extra == [("data/cal2026-10r1/inputs/add_list_r1.json",
                      _blobs(toy, "data/cal2026-10r1/inputs/add_list_r1.json")["data/cal2026-10r1/inputs/add_list_r1.json"]),
                     ("s3:r1/patch_raw/", "pin:patch_raw")]
    # --check: equal now, different once a classified file changes
    assert cls.main(["--repo", str(toy), "--out", str(out), "--check"], rules=TOY_RULES, r1_inputs=TOY_INPUTS) == 0
    (toy / "data/cal2026-10/events_econ.csv").write_text("changed\n", encoding="utf-8")
    _git(toy, "commit", "-qam", "change")
    assert cls.main(["--repo", str(toy), "--out", str(out), "--check"], rules=TOY_RULES, r1_inputs=TOY_INPUTS) == 1


def test_an_unmatched_file_or_a_dead_rule_is_an_error(toy, tmp_path, capsys):
    out = tmp_path / "base_inputs.tsv"
    assert cls.main(["--repo", str(toy), "--out", str(out)], rules=TOY_RULES[:-1], r1_inputs=TOY_INPUTS) == 1
    assert "analysis/expected/P1.json" in capsys.readouterr().err
    assert not out.exists()
    dead = TOY_RULES + (R("data/frames/nothing_*.csv", "product", "x", "toy: a rule that no tracked file reaches"),)
    assert cls.main(["--repo", str(toy), "--out", str(out)], rules=dead, r1_inputs=TOY_INPUTS) == 1
    assert "data/frames/nothing_*.csv" in capsys.readouterr().err
    assert not out.exists()
    missing = TOY_INPUTS + (("data/cal2026-10r1/inputs/absent.json", "signed", "toy: an r1 input git does not track"),)
    assert cls.main(["--repo", str(toy), "--out", str(out)], rules=TOY_RULES, r1_inputs=missing) == 1
    assert "data/cal2026-10r1/inputs/absent.json" in capsys.readouterr().err


def test_committed_base_inputs_tsv_is_current():
    assert cls.main(["--check"]) == 0
    rows = sb.load_tsv(REPO / "config" / "r1" / "base_inputs.tsv")
    by = {r["path"]: r["class"] for r in rows}
    # spot checks of the classification principle (design_final 'The sandbox rule')
    assert by["data/cal2026-10/calls_2026-10.csv"] == "base"
    assert by["data/cal2026-10/_invalid_run2/restake_2026-10.csv"] == "base"
    assert by["data/frames/p3_afar_speed_bracket.csv"] == "base"
    assert by["data/cal2026-10/frames_econ/build_report_econ920_2026-10.json"] == "product"
    assert by["data/cal2026-10/controls_report_econ920_2026-09-23.json"] == "product"
    assert by["analysis/expected/MANIFEST.sha256"] == "product"
    assert by["data/cal2026-10r1/inputs/add_list_r1.json"] == "r1_input"
    assert all(c == "base" for p, c in by.items() if p.startswith("data/cal2026-08-28/"))
    # pre-J0 sandbox review 2026-10-16, finding 1: the fetched October EC2 outputs (fetch/out holds byte copies of
    # four golds) are products, moved to the reference copy; the run-2 quarantine stays base but is watched
    cloud = [p for p in by if p.startswith(("data/cal2026-10/cloud/", "data/cal2026-10/cloud_t5/"))]
    assert len(cloud) > 700 and {by[p] for p in cloud} == {"product"}
    assert by["data/cal2026-10/cloud/fetch/out/P3_econ_fnfix.json"] == "product"
    run2 = [p for p in by if p.startswith("data/cal2026-10/_invalid_run2/")]
    assert len(run2) == 11 and {by[p] for p in run2} == {"base"}
    assert "data/cal2026-10/_invalid_run2" in sb.WATCHED


def test_the_run2_quarantine_is_readable_only_by_write_events_and_only_its_verdicts():
    """Every file under data/cal2026-10/_invalid_run2 stays in the clone (base), so a read of it must be allowed by
    a row; the one row is write_events reading verdicts_2026-10.csv (pre-J0 sandbox review 2026-10-16)."""
    allow = sb.load_allowlist(REPO / "config" / "r1" / "read_allowlist_0828.txt")
    run2 = "data/cal2026-10/_invalid_run2/"
    ok = [("write_events", run2 + "verdicts_2026-10.csv")]
    assert sb.check({}, ok, allow, "B0", REPO)["verdict"] == "OK"
    for stage, name in (("write_events", "events_chemistry_cal2026-10.csv"), ("write_events", "restake_2026-10.csv"),
                        ("frames_chemmath", "verdicts_2026-10.csv"), ("cells_rmac", "events_econ_cal2026-10_p05.csv")):
        res = sb.check({}, [(stage, run2 + name)], allow, "B0", REPO)
        assert res["verdict"] == "G_READ_FAIL" and res["gread"] == [[stage, run2 + name]], (stage, name)
    assert sb.check({}, ok, allow, "M", REPO)["verdict"] == "G_READ_FAIL"          # a B0-only row


def test_the_08_28_reads_the_seed_grep_missed_are_allowed_to_their_stages_only():
    """Pre-J0 sandbox review 2026-10-16, finding 2: the calls table restake_econ11 reads through cleaned_works'
    CALLS_CSV constant, and the two 08-28 modules imported by a bare name after a sys.path insert."""
    allow = sb.load_allowlist(REPO / "config" / "r1" / "read_allowlist_0828.txt")
    calls = "data/cal2026-08-28/calls_2026-08-28.csv"
    rcf, ca08 = "pipeline/stars/caliber_2026-08-28/run_cal_frames.py", "pipeline/stars/caliber_2026-08-28/cal_accounting.py"
    ok = [("restake_econ11_aug", calls), ("restake_econ11_aug_all", calls), ("afar", rcf), ("frames_chemmath", ca08)]
    assert sb.check({}, ok, allow, "B0", REPO)["verdict"] == "OK"
    for read in (("frames_econ920", calls), ("cells_rmac", rcf), ("afar", ca08)):
        assert sb.check({}, [read], allow, "B0", REPO)["gread"] == [list(read)], read


def test_the_08_28_frames_and_golds_are_read_only_by_the_two_control_chains():
    """Pre-J0 sandbox review 2026-10-16, finding 5: only frames_econ920 and frames_chemmath read the 08-28 frames
    and golds, so a cells stage (or any other) reading them is reported."""
    allow = sb.load_allowlist(REPO / "config" / "r1" / "read_allowlist_0828.txt")
    paths = ("data/cal2026-08-28/frames/p1_frame_chemistry.csv", "data/cal2026-08-28/estimates/P1_fnfix_chemistry.json")
    for stage in ("frames_econ920", "frames_chemmath"):
        assert sb.check({}, [(stage, p) for p in paths], allow, "B0", REPO)["verdict"] == "OK", stage
    for stage in ("cells_rmac", "cells_rcloud", "afar", "p3_variants", "frames"):
        res = sb.check({}, [(stage, p) for p in paths], allow, "B0", REPO)
        assert res["gread"] == [[stage, p] for p in sorted(paths)], stage


def test_frames_chemmath_reads_only_the_canon_frames_its_phase_p_names():
    """Pre-J0 sandbox review 2026-10-16, finding 3: from the reference copy of data/frames the rebuild stage may
    read exactly what run_cal_frames_chemmath.october_ref_files names - not the econ, A_far or variant frames
    gate 1 compares against."""
    layer = REPO / "pipeline" / "frames" / "cal2026-10"
    for p in (str(layer / "econ920"), str(layer)):
        if p not in sys.path:
            sys.path.insert(0, p)
    if str(REPO) not in sys.path:
        sys.path.append(str(REPO))
    import run_cal_frames_chemmath as rc   # noqa: PLC0415
    named = {rel for f in rc.FIELDS for rel in rc.october_ref_files(f) if rel.startswith("data/frames/")}
    assert len(named) == 8
    allow = sb.load_allowlist(REPO / "config" / "r1" / "read_allowlist_0828.txt")
    canon = _git(REPO, "ls-files", "data/frames").splitlines()
    assert named < set(canon)
    for p in canon:
        res = sb.check({}, [("frames_chemmath", "ref:" + p)], allow, "B0", REPO)
        assert res["verdict"] == ("OK" if p in named else "G_READ_FAIL"), p


def test_allowlist_rows_name_existing_paths_and_have_reasons():
    rows = sb.load_allowlist(REPO / "config" / "r1" / "read_allowlist_0828.txt")
    assert rows
    tracked = _git(REPO, "ls-files").splitlines()
    products = [r["path"] for r in sb.load_tsv(REPO / "config" / "r1" / "base_inputs.tsv") if r["class"] == "product"]
    for row in rows:
        assert len(row.reason) > 30, row.glob
        assert set(row.configs) <= {"B0", "M", "*"}, row.glob
        pat = sb.glob_re(row.glob[len("ref:"):] if row.glob.startswith("ref:") else row.glob)
        if row.glob.startswith("ref:"):
            assert row.stages, f"{row.glob}: a reference-copy row names its stages"
            assert any(pat.fullmatch(p) for p in products), f"{row.glob} names no October product"
        else:
            assert row.glob.startswith(tuple(w + "/" for w in sb.WATCHED)), f"{row.glob} is outside the watched trees"
            assert any(pat.fullmatch(p) for p in tracked), f"{row.glob} matches no tracked path"
