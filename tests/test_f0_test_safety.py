# -*- coding: utf-8 -*-
"""R1 F0 - test safety (design v3 §4, §5.4; design_final.md §(f) F0)."""
from __future__ import annotations

import configparser
import importlib.util
import os
import pathlib
import re
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MARKERS = ("ssd", "estimate", "legacy", "live")
PRE_R1 = ("pre-R1 file: its data-touching tests skip when the legacy tree or the data disk is absent "
          "(needs_source / skipif); the root F0 plugin (sar_f0_plugin.py) blocks any Python-level open on the disk off ec2-r1")
#: files that name a RISK pattern but carry no module marker, each with the reason it is safe to
#: collect by default. A new test file is either marked (pytestmark = pytest.mark.ssd/...) or listed.
F0_REVIEWED: dict[str, str] = {
    "tests/test_cal2026_10_chemmath.py": PRE_R1,
    "tests/test_cal2026_10_econ920.py": PRE_R1,
    "tests/test_cal2026_10_piece_a.py": PRE_R1,
    "tests/test_cal2026_10_piece_b.py": PRE_R1,
    "tests/test_cal_frames_2026_08_28.py": PRE_R1,
    "tests/test_cal_ledger_2026_08_28.py": PRE_R1,
    "tests/test_env.py": PRE_R1,
    "tests/test_make_slim.py": PRE_R1,
    "tests/test_paths.py": PRE_R1,
    "tests/test_pipeline_rebuild.py": PRE_R1,
    "tests/test_supplement_2026_08_28.py": PRE_R1,
    "tests/test_verbatim_pipeline.py": PRE_R1,
    "tests/test_verified_pool_cal2026_10.py": PRE_R1,
    "tests/test_r1_rk6b.py": "sets $SAR_SSD_ROOT to an empty tmp stand-in only while importing run_screening "
                             "(it resolves its table at import); the tests use toy tables, never the disk",
    "tests/test_f0_test_safety.py": "the F0 tests themselves: they name the patterns and probe the guard, "
                                    "which raises before any filesystem access",
    "tests/test_r1_cells.py": "a fake Rscript (python) in tmp_path writes toy JSON; run_cells now hashes the toy "
                              "frames in tmp_path only; no R runs and no real frame is read",
    "tests/test_r1_env.py": "fake Rscript/pdflatex shell scripts in tmp_path check versions_check.py; no R runs",
    "tests/test_r1_input_inventory.py": "toy files in tmp_path whose text names derived_root and v2_output as scanner input; no disk is opened",
}

UNIT_TOY = ("ported unit test: names duckdb or the derived root but builds every table it reads in "
            "tmp_path; it opens no disk (checked 2026-10-13, P3b ruling R1)")
F0_REVIEWED.update({
    "tests/test_afar_cuts_2026_08_30.py": "reads analysis/run_all.sh as text to check its cell lines; runs no R or shell",
    "tests/test_aws_cal2026_10.py": "drives the October driver on a fake Rscript in tmp dirs; no R, no AWS, no disk",
    "tests/test_aws_cal2026_10_t5.py": "drives the October T5 batch on a fake Rscript in tmp dirs; no R, no AWS",
    "tests/test_cal_estimates_2026_08_28.py": "asserts that the 08-28 launcher source names Rscript; it runs nothing",
    "tests/test_verbatim.py": "pins file hashes and names run_all.sh only as text; reads no data and runs no R",
    **{f"pipeline/units/{p}": UNIT_TOY for p in (
        "u0_foundation/tests/test_derived_table.py", "u0_foundation/tests/test_snapshot_reader.py",
        "u0p5_dept_roster/tests/test_hist_phrases_config.py", "u0p5_dept_roster/tests/test_hist_step1_hits.py",
        "u0p5_dept_roster/tests/test_run_u0p5.py", "u1_fetch/tests/test_gz_filter.py",
        "u1_fetch/tests/test_reconcile_m1.py", "u3_panel/tests/test_panel.py",
        "u4_output_star/tests/test_m5_assemble_contrib.py", "u4_output_star/tests/test_m7a_discipline_gate.py",
        "u4_output_star/tests/test_m7a_stock_fold_diag.py", "u4_output_star/tests/test_m7a_stock_query.py",
        "u4_output_star/tests/test_run_u4_build_star_set.py", "u4_output_star/tests/test_run_u4_freeze_provenance.py",
        "u4_output_star/tests/test_run_u4_ship_fwci_baseline.py", "u4_output_star/tests/test_run_u4_ship_paper_contrib.py",
        "u4_output_star/tests/test_run_u4_signal_discards.py", "u5_dose/tests/test_io_real.py",
        "u5_dose/tests/test_run_dose.py", "u5_dose/tests/test_run_u5.py", "u5_dose/tests/test_zenou_gold.py")},
})
#: R1 wave 1 (2026-10-16 integration): the reasons are the units' own handoff texts
F0_REVIEWED.update({
    "tests/test_r1_econ920_controls_report.py": "real_v2 is monkeypatched to raise or to a tmp_path dir; every phase "
                                                "is a fake; no data disk or legacy file is opened",
    "tests/test_r1_dossier_pack.py": "names duckdb but builds toy aw_raw/work_text/pm tables in a tmp_path database and "
                                     "toy paper-check and RK4 files in tmp_path; it never opens the data disk, and "
                                     "main() is only called to check that it refuses off an R1 instance",
    "tests/test_r1_mem_probe.py": "a fake Rscript and a fake /usr/bin/time (python) in tmp_path, toy three-column "
                                  "parquet frames written in tmp_path; no R runs, no real frame or data disk is "
                                  "opened, no gold is read",
    "tests/test_r1_edge_table.py": "toy edge tables built in tmp_path (pyarrow) and read with an in-memory duckdb; names "
                                   "derived_root/ssd_root/SAR_SSD_ROOT only to probe the path resolvers in a subprocess "
                                   "against a toy paths file; never opens the data disk",
    "tests/test_r1_missing_persons.py": "builds every table it reads in tmp_path (duckdb writes the toy parquets, "
                                        "csv/jsonl written by hand) and opens no data disk; imports econ920_lib only "
                                        "for the October-equality test, with L.CAL10 monkeypatched to a tmp dir",
    "tests/test_r1_calls_lib.py": "builds a 13-row aw_raw in an in-memory duckdb and toy paper checks/merged/add-list "
                                  "files in tmp_path; reads only the committed dose_keep_r1.csv and paper_checks "
                                  "round1 paths as text; never opens the data disk or the legacy tree",
    "tests/test_r1_par_plan.py": "toy parquet/CSV frames and toy unit TSV / mem_probe / cells reports written in "
                                 "tmp_path only; no R, no real frame, no October gold read; CLI writes only under tmp_path",
    "tests/test_r1_network_freeze.py": "builds toy edge/works/person-map parquet and jsonl under tmp_path and classifies "
                                       "them in a tmp-file duckdb; reads the ported u5_dose code and the October driver "
                                       "sources as text only, and never opens the data disk",
    "tests/test_r1_afar_event_map.py": "builds toy p1/p2/pairs/p3_afar_pos tables in tmp_path and maps them with an "
                                       "in-memory duckdb; the default-call test reads only the tracked "
                                       "data/frames/p3_afar_pos_chemistry.parquet; it never opens the data disk",
    "tests/test_r1_robustness.py": "reads only small repo-tracked October products and the October scripts as text; "
                                   "'Rscript' appears only as parsed text, no R runs; duckdb only reads the committed "
                                   "3.4 MB afar_cuts frames in cut_grid; toy files in tmp_path; never opens the data disk; "
                                   "'SAR_SSD_ROOT' only as a token of the no-centre unit's parsed bash script and the "
                                   "canon-pack / restore_upstream run is on toy files in tmp_path (M review #7/#9)",
    "tests/test_r1_units.py": "a fake Rscript (python) in tmp_path writes toy JSON; no R runs, no frame and no disk is read",
    "tests/test_r1_tables_base_tree.py": "small tests read only git fixtures, analysis/expected and tmp dirs (the "
                                         "SAR_PATHS_CONFIG override points output at tmp); only "
                                         "test_all_13_base_tables_from_the_real_chain touches output/paper, the R gap "
                                         "scripts and the legacy tree, and it is marked legacy in F0_MARKS",
})
#: R1 wave 2 (2026-10-16 integration): the units' handoff texts, plus test_r1_table_j0.py, whose J0 review #4 docstring
#: (bc077d9) names ssd_root and so tripped the meta-test after the t-0023 fix pass
F0_REVIEWED.update({
    "tests/test_r1_table_j0.py": "reads only committed config files (the J0/JP stage tables, job specs, chain.json, "
                                 "input and env pins) and computes fingerprints with git; 'ssd_root' appears only in a "
                                 "docstring; --help probes run the stage scripts' argparse only; no data disk is opened",
    "tests/test_r1_table_j1a.py": "reads only committed config files (the J1a stage table, job spec, allowlist, cells TSVs, "
                                  "rankrepro job, pins); the RISK hit is the env name SAR_SSD_ROOT, asserted inline in the "
                                  "rank/calls rows and popped before the --help probes; bash probes run single rows on a toy "
                                  "WORK/REPO_DIR in tmp_path; no data disk, no derived table, no network",
    "tests/test_r1_kit.py": "kit tests on a fake aws CLI and a fake S3 tree in tmp dirs; the RISK hit is the string '/work/out' inside an assertion about a job spec's env value; nothing is run on an instance or written outside tmp",
    "tests/test_r1_chemmath_m.py": "toy tests only; the RISK match is two monkeypatch.delenv('SAR_SSD_ROOT') calls that remove "
                                   "the override; builder subprocesses, prodlib and the shadow builder are recorders writing "
                                   "tmp_path placeholders; real reads are small tracked files only; no data disk",
    "tests/test_r1_reverse_proof.py": "builds toy u1 tables, a toy person map and toy frame CSVs under tmp_path and reads them "
                                      "with an in-memory duckdb; the driver, the October compare and the roster check are "
                                      "monkeypatched recorders; it never opens the data disk or the legacy trees",
    "tests/test_r1_gaps_zenou_m.py": "names duckdb only to write a two-row star_set parquet into tmp_path; the generator "
                                     "subprocess runs on a toy M canon in tmp_path (SAR_PATHS_CONFIG, output re-rooted to "
                                     "tmp); the only repo data read is the tracked flips_r1.json; no data disk, no R",
    "tests/test_r1_v3net_oracle_spec.py": "the B4 spec builder on SimpleNamespace fakes of chemmath_m / econ920_m; the "
                                          "RISK hit is a fake stage.derived_root() returning a tmp_path dir; every file "
                                          "is a toy under tmp_path; no data disk, no driver, no subprocess",
    "tests/test_r1_star_origins_m.py": "builds a toy U2 person-map parquet with duckdb and toy snapshot manifests under "
                                       "tmp_path; October-mode tests read only pinned repo inputs; the one full-scan control "
                                       "carries @pytest.mark.ssd and runs only on the big host",
    "tests/test_run_all_stages.py": "runs a copy of analysis/run_all.sh in a tmp_path skeleton with python3/Rscript stubs that "
                                    "only log argv (the helper and, in two tests, compare_all.py run for real on toy canons); "
                                    "every canon, paths yaml and output root lives in tmp_path; ssd_root is a toy value; "
                                    "reads no real frame (only the R drivers' bytes) and writes nothing inside the clone; "
                                    "git check-ignore / ls-files only read the clone's ignore rules",
    "tests/test_r1_final.py": "names analysis/run_all.sh only as a stage-table string it asserts on; toy data in tmp_path "
                              "only (restore_upstream.py, r1_canon.py and verify_manifest.py on a three-file toy stage "
                              "set); no frames, no R, no LaTeX, no data disk",
})
#: R1 wave 3 early (2026-10-16): W3-B0EXP's handoff text
F0_REVIEWED["tests/test_r1_m_checks.py"] = (
    "unit tests of analysis/paper/_m_checks.py: toy csv/parquet/json files under tmp_path only, and reads of the "
    "repo's own source files; no data root, no subprocess")
F0_REVIEWED["tests/test_r1_final_b0_expected.py"] = (
    "reads analysis/run_all.sh, tools/check_paper.py and analysis/paper/*.py as text only (ast/regex), plus the "
    "base-tree fixtures and the upload record; imports final_stage only for load_expected_b0/gate2 on toy inputs; "
    "runs nothing and opens no disk")
MARKED_FILES = ("tests/test_paper_p1p2.py", "tests/test_paper_ledgers.py",
                "pipeline/units/u4_output_star/tests/test_roster_v3_wiring.py",
                "tests/test_r1_tables_base_tree.py")


def _guard():
    spec = importlib.util.spec_from_file_location("sar_f0_guard_under_test", REPO / "tests" / "f0_guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_guard_hook_refuses_paths_under_a_root_and_nothing_else(tmp_path):
    g = _guard()
    root = tmp_path / "disk" / "openalex_pipeline"
    hook = g.make_guard((str(root),))
    with pytest.raises(PermissionError, match="F0 guard"):
        hook("open", (str(root / "derived" / "x.parquet"), "r", 0))
    with pytest.raises(PermissionError):
        hook("os.listdir", (str(root),))
    with pytest.raises(PermissionError):
        hook("open", (root / "derived", "r", 0))                       # a PathLike as well as a str
    assert hook("open", (str(tmp_path / "elsewhere.txt"), "r", 0)) is None
    assert hook("open", (str(tmp_path / "disk" / "openalex_pipeline_other"), "r", 0)) is None
    assert hook("open", (3, "r", 0)) is None                            # a file descriptor
    assert hook("socket.connect", (str(root),)) is None                 # not a guarded event


def test_configured_ssd_root_comes_from_paths_yaml_not_the_env(monkeypatch, tmp_path):
    g = _guard()
    cfg = tmp_path / "paths.yaml"
    cfg.write_text('ssd_root: "/mnt/disk/openalex_pipeline/"\n', encoding="utf-8")
    monkeypatch.setenv("SAR_SSD_ROOT", str(tmp_path))
    assert g.configured_ssd_root(cfg) == "/mnt/disk/openalex_pipeline"


def test_host_gate_accepts_only_the_two_aws_hosts():
    g = _guard()
    assert g.host_ok({"SAR_HOST": "ec2-r1-test"}) and g.host_ok({"SAR_HOST": "ec2-r1"})
    for bad in ({}, {"SAR_HOST": ""}, {"SAR_HOST": "mac"}, {"SAR_HOST": "EC2-R1"}):
        assert not g.host_ok(bad), bad


@pytest.mark.skip(reason="public copy: no host gate (the private repository runs its tests only on AWS)")
@pytest.mark.parametrize("target", ["tests/test_expected.py", "pipeline/units/u0_foundation/tests"])
def test_pytest_stops_off_aws(target):
    """The root suite AND the ported unit suite (`pytest -q pipeline/units`, a listed repo command)."""
    env = {k: v for k, v in os.environ.items() if k != "SAR_HOST"}
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", target],
                       cwd=REPO, env=env, capture_output=True, text=True)
    assert r.returncode == 4, r.stdout[-2000:] + r.stderr[-2000:]
    assert "tests run only on AWS" in (r.stdout + r.stderr)


def test_the_gate_is_a_root_plugin_not_a_conftest_and_not_in_the_port():
    """t-0001: a repo-root conftest.py answered the ported u6 tests' bare `import conftest`, so the gate
    is a repo-root module loaded by `-p sar_f0_plugin` (pytest.ini addopts) instead."""
    assert (REPO / "sar_f0_plugin.py").is_file()
    assert not (REPO / "conftest.py").exists() and not (REPO / "tests" / "conftest.py").exists()
    assert not (REPO / "pipeline" / "conftest.py").exists()   # the port carries no auto-executed file of ours


def test_a_bare_import_conftest_reaches_u6_even_with_the_repo_root_first():
    """t-0001 suite (rc 2): ten tests/ modules put the repo root first on sys.path at import time, then
    pipeline/units/u6_assemble/tests/test_run_u6.py does `from conftest import make_inputs`."""
    u6 = REPO / "pipeline" / "units" / "u6_assemble" / "tests"
    code = ("import sys, importlib.util as u; sys.path[:0] = sys.argv[1:3]; "
            "print(u.find_spec('conftest').origin)")
    r = subprocess.run([sys.executable, "-I", "-c", code, str(REPO), str(u6)],
                       capture_output=True, text=True, check=True)
    assert pathlib.Path(r.stdout.strip()) == u6 / "conftest.py"


def test_guard_is_live_in_this_process():
    """On the test runner ($SAR_HOST=ec2-r1-test) the root F0 plugin installed the audit hook."""
    if os.environ.get("SAR_HOST", "").strip() == "ec2-r1" or os.environ.get("SAR_DISK_TESTS", "") == "1":
        pytest.skip("the data host reads the disk by design (public copy: also when SAR_DISK_TESTS=1)")
    root = _guard().configured_ssd_root()
    with pytest.raises(PermissionError, match="F0 guard"):
        open(os.path.join(root, "derived", "never_exists.parquet"), "rb")


def test_pytest_ini_declares_markers_deselects_them_and_keeps_pythonpath_last():
    cp = configparser.ConfigParser(interpolation=None)
    cp.read_string((REPO / "pytest.ini").read_text(encoding="utf-8"))
    sec = cp["pytest"]
    declared = {ln.split(":", 1)[0].strip() for ln in sec["markers"].splitlines() if ln.strip()}
    assert set(MARKERS) | {"depends_on_u", "slow"} <= declared
    assert "--strict-markers" in sec["addopts"] and "--import-mode=importlib" in sec["addopts"]
    assert '-m "not ssd and not estimate and not legacy and not live"' in sec["addopts"]
    assert re.search(r"(^|\s)-p sar_f0_plugin(\s|$)", sec["addopts"]), "the F0 gate is loaded as a -p plugin"
    assert list(sec)[-1] == "pythonpath"


def test_every_risky_test_file_is_marked_or_reviewed():
    g = _guard()
    bad = g.unreviewed(REPO, g.TEST_GLOBS, F0_REVIEWED, g.F0_MARKS)
    assert bad == [], f"mark these (tests/f0_guard.py F0_MARKS) or review them in F0_REVIEWED: {bad}"
    # public copy: entries for test files that are not shipped are skipped (the private suite checks them)
    stale = [rel for rel in F0_REVIEWED
             if (REPO / rel).is_file() and not g.RISK.search((REPO / rel).read_text(encoding="utf-8"))]
    assert stale == [], f"F0_REVIEWED entries that no longer match: {stale}"
    assert all(len(why) > 30 for why in F0_REVIEWED.values())
    for key, (marker, why) in g.F0_MARKS.items():
        assert marker in ("ssd", "estimate", "legacy") and len(why) > 30, key
        assert (REPO / key.split("::")[0]).is_file(), key


def test_the_meta_test_logic_fails_on_a_planted_unmarked_file(tmp_path):
    g = _guard()
    t = tmp_path / "tests"
    t.mkdir()
    (t / "test_planted.py").write_text("import subprocess\n\ndef test_x():\n    subprocess.run(['Rscript', 'x.R'])\n")
    (t / "test_clean.py").write_text("def test_y():\n    assert 1\n")
    (t / "test_marked.py").write_text("import pytest\npytestmark = pytest.mark.estimate\n# Rscript\n")
    globs = ("tests/test_*.py",)
    assert g.unreviewed(tmp_path, globs, {}, {}) == ["tests/test_planted.py"]
    assert g.unreviewed(tmp_path, globs, {"tests/test_planted.py": "x" * 40}, {}) == []
    assert g.unreviewed(tmp_path, globs, {}, {"tests/test_planted.py::test_x": ("estimate", "y" * 40)}) == []


def test_marker_for_matches_a_node_its_parameters_and_a_whole_file():
    g = _guard()
    assert g.marker_for("tests/test_paper_p1p2.py::test_gaps_switchers_p1p2_r") == "estimate"
    assert g.marker_for("tests/test_paper_p1p2.py::test_gaps_switchers_p1p2_r[x]") == "estimate"
    assert g.marker_for("tests/test_paper_p1p2.py::test_p1p2_ledger_equals_thesis") is None
    assert g.marker_for("pipeline/units/u4_output_star/tests/test_roster_v3_wiring.py::test_a") == "ssd"


def _collect(*extra):
    r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                        *extra, *MARKED_FILES], cwd=REPO, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def test_a_default_collection_lists_no_marked_item():
    rc, out = _collect()
    assert rc == 0, out[-2000:]
    for key in _guard().F0_MARKS:
        assert key not in out, key
    m = re.search(r"(\d+) deselected", out)
    assert m and int(m.group(1)) >= 4, out[-500:]


def test_the_big_host_selection_collects_the_marked_items():
    rc, out = _collect("-m", "ssd or estimate or legacy")
    assert rc == 0, out[-2000:]
    for key in _guard().F0_MARKS:
        if key.startswith("tests/test_r1_tables_base_tree.py::") and not (REPO / "tests/fixtures/r1_paper/base_tree_2026-10-11").is_dir():
            continue  # The same not shipped fixture predicate used by that module at collection.
        assert key in out, key


def test_require_readable_refuses_the_disk_with_no_host_set(monkeypatch):
    from pipeline.lib import paths as P
    monkeypatch.delenv("SAR_HOST", raising=False)
    disk = pathlib.Path(str(P._config()["ssd_root"]))
    with pytest.raises(P.PathUnresolved, match="R1 rule"):
        P.require_readable(disk / "derived" / "u1_full_11school_2026-07-16", "the 11-school table")


def test_require_readable_refuses_the_configured_disk_off_the_data_host(monkeypatch):
    from pipeline.lib import paths as P
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    disk = pathlib.Path(str(P._config()["ssd_root"]))
    with pytest.raises(P.PathUnresolved, match="R1 rule"):
        P.require_readable(disk / "derived" / "u1_full_11school_2026-07-16", "the 11-school table")


def test_require_readable_still_allows_tmp_roots(monkeypatch, tmp_path):
    from pipeline.lib import paths as P
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    assert P.require_readable(tmp_path, "a tmp root") == tmp_path


def test_require_readable_lets_the_data_host_reach_the_existence_check(monkeypatch):
    from pipeline.lib import paths as P
    monkeypatch.setenv("SAR_HOST", "ec2-r1")
    disk = pathlib.Path(str(P._config()["ssd_root"]))
    with pytest.raises(P.PathUnresolved) as e:
        P.require_readable(disk / "derived" / "no_such_table_r1_probe", "a probe")
    assert "R1 rule" not in str(e.value)
