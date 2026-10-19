import subprocess, sys, pathlib, os
import pytest
REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from analysis.lib.paths import load_paths

REQUIRED = ["repo_root", "legacy_v2_output", "legacy_thesis", "ssd_root",
            "frames", "raw_verified", "estimates", "expected", "output",
            # the October cal root, the paper inputs and the cal intermediates, so the paper
            # readers can be re-rooted through config alone (analysis/lib/canon.py reads them)
            "cal", "paper_inputs", "cal_intermediates"]

def test_paths_keys_and_resolution():
    p = load_paths()
    assert set(REQUIRED) <= set(p), set(REQUIRED) - set(p)
    assert p["repo_root"] == REPO
    assert p["cal"] == REPO / "data" / "cal2026-10"
    assert p["paper_inputs"] == REPO / "data" / "paper_inputs"
    assert p["cal_intermediates"] == REPO / "output" / "cal_intermediates" / "cal2026-10"
    for k in ["frames", "raw_verified", "estimates", "expected", "output", "cal", "paper_inputs",
              "cal_intermediates"]:
        assert p[k].is_absolute() and str(p[k]).startswith(str(REPO)), k
    if not p["legacy_v2_output"].is_dir(): pytest.skip("legacy tree not on this machine")

def test_r_paths_agree_with_python():
    p = load_paths()
    out = subprocess.run(["Rscript", "-e",
        f'source("{REPO}/analysis/lib/paths.R"); x <- sar_paths(); cat(x$frames, x$expected, sep="\\n")'],
        capture_output=True, text=True, check=True).stdout.strip().splitlines()
    assert out == [str(p["frames"]), str(p["expected"])]

# --- pipeline layer (M3) -------------------------------------------------------------------------
from pipeline.lib.paths import (  # noqa: E402
    PathUnresolved, WriteBarred, BarredWriteTarget, configured, derived_root,
    deferred_output_target, is_inside_legacy, legacy_thesis, openalex_api_key, output_target,
    require_readable, require_writable, snapshot_root, ssd_root, SSD_ROOT_LEAF)

PIPELINE_REQUIRED = ["legacy_multiplex", "pipeline_root", "ssd_root"]


def test_pipeline_keys_present_and_shaped():
    for k in PIPELINE_REQUIRED:
        assert configured(k)[0].is_absolute(), k
    # the ported u1 capacity gate asserts DATA_ROOT ends with "openalex_pipeline/derived/"
    assert derived_root().name == "derived" and derived_root().parent.name == "openalex_pipeline"
    assert snapshot_root().name == "snapshot"
    assert configured("pipeline_root")[0] == REPO / "pipeline"


def test_ssd_root_is_overridable_by_env(monkeypatch, tmp_path):
    root = tmp_path / SSD_ROOT_LEAF
    root.mkdir()
    monkeypatch.setenv("SAR_SSD_ROOT", str(root))
    assert derived_root() == root / "derived"
    assert snapshot_root() == root / "snapshot"


def test_missing_key_fails_loudly():
    from pipeline.lib.paths import CONFIG_FILE   # noqa: PLC0415  (the config in force; the error names it)
    with pytest.raises(PathUnresolved) as e:
        configured("no_such_key_at_all")
    assert "no_such_key_at_all" in str(e.value) and str(CONFIG_FILE) in str(e.value)


# --- T1-review F3: a wrongly-set override must not resolve silently to a WRITE root ---------------
def test_env_override_that_does_not_exist_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("SAR_SSD_ROOT", str(tmp_path / "not-mounted" / SSD_ROOT_LEAF))
    with pytest.raises(PathUnresolved) as e:
        derived_root()
    assert "SAR_SSD_ROOT" in str(e.value) and "does not exist" in str(e.value)


def test_env_override_that_is_a_file_raises(monkeypatch, tmp_path):
    f = tmp_path / SSD_ROOT_LEAF
    f.write_text("not a directory")
    monkeypatch.setenv("SAR_SSD_ROOT", str(f))
    with pytest.raises(PathUnresolved, match="not a directory"):
        derived_root()


def test_env_override_that_is_read_only_raises(monkeypatch, tmp_path):
    root = tmp_path / SSD_ROOT_LEAF
    root.mkdir()
    root.chmod(0o500)
    monkeypatch.setenv("SAR_SSD_ROOT", str(root))
    try:
        with pytest.raises(PathUnresolved, match="not writable"):
            derived_root()
    finally:
        root.chmod(0o700)


# --- T1-review F4: the suffix the ported capacity-gate test depends on is guarded, not just docd --
def test_ssd_root_leaf_is_guarded_on_the_env_override(monkeypatch, tmp_path):
    wrong = tmp_path / "openalex"
    wrong.mkdir()
    monkeypatch.setenv("SAR_SSD_ROOT", str(wrong))
    with pytest.raises(PathUnresolved) as e:
        ssd_root()
    assert SSD_ROOT_LEAF in str(e.value) and "capacity-gate" in str(e.value)


def test_require_readable_and_writable_fail_loudly(tmp_path):
    """The boundary Task 2's drivers must call: a wrong root stops here, before anything is written."""
    with pytest.raises(PathUnresolved, match="not on this machine"):
        require_readable(tmp_path / "gone", "derived tables")
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        with pytest.raises(PathUnresolved, match="not writable"):
            require_writable(ro, "derived tables")
    finally:
        ro.chmod(0o700)
    assert require_writable(tmp_path, "tmp") == tmp_path


def test_openalex_key_required_error_is_explicit(monkeypatch):
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    assert openalex_api_key(required=False) is None
    with pytest.raises(PathUnresolved) as e:
        openalex_api_key()
    assert "OPENALEX_API_KEY" in str(e.value)


def test_ported_units_resolve_contracts_inside_the_repo():
    """H2: the port only works at pipeline/units/<u>/src/... — common._redlines walks parents[4]."""
    import subprocess
    src = REPO / "pipeline/units/u0_foundation/src"
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, sys.argv[1]);"
         "import common._redlines as R;"
         "print(R.REDLINES_YAML); print(R.sha256_of_red() == R.sha256_of_yaml_file())",
         str(src)], capture_output=True, text=True, check=True).stdout.split("\n")
    assert out[0] == str(REPO / "pipeline/contracts/redlines.yaml"), out[0]
    assert out[1] == "True", "redlines.yaml <-> RED sha gate must hold in the ported tree"


# --- T1 re-review F9 (cheap partial, kept in addition to normalise-and-compare) -------------------
# Every path the port rewrote is pinned here against the literal EXTRACTED FROM THE LEGACY FILE, so
# the report's "every resolved value equals its legacy literal" table has a test behind it. This
# alone kills a swapped dataset directory (NEW-2) and a swapped resolver (NEW-3): both change a
# runtime value while still looking like path resolution.
LEGACY_LITERAL = {                     # attribute -> regex capturing the legacy literal it replaced
    "preflight.DATA_ROOT":            (r'DATA_ROOT: str = "([^"]+)"', "u0_foundation/src/common/preflight.py"),
    "capacity_gate.DATA_ROOT":        (r'DATA_ROOT: str = "([^"]+)"', "u0_foundation/src/common/preflight.py"),
    "run_u0p5.SSD_DERIVED_DIR":       (r'SSD_DERIVED_DIR = pathlib\.Path\("([^"]+)"\)', "u0p5_dept_roster/src/roster/run_u0p5.py"),
    "run_u0p5.U1_FULL_DIR":           (r'U1_FULL_DIR = pathlib\.Path\("([^"]+)"\)', "u0p5_dept_roster/src/roster/run_u0p5.py"),
    "run_u0p5.person_map":            (r'    pm = "([^"]+)"', "u0p5_dept_roster/src/roster/run_u0p5.py"),
    "s3_sync.snapshot_arg":           (r'snapshot_root="([^"]+)"', "u1_fetch/tests/test_s3_sync.py"),
    "stream_build._REAL_SHARD":       (r'\n    "(/[^"]+part_0000\.gz)"', "u1_fetch/tests/test_stream_build.py"),
    "run_u4.measurement_artifact":    (r'"measurement_artifact": \("([^"]+)"', "u4_output_star/src/run_u4.py"),
    "roster_v3._SSD_V3":              (r'\n    "(/[^"]+registry_v3_2026-07-12)"\)', "u4_output_star/tests/test_roster_v3_wiring.py"),
    "run_u5.DEFAULT_DATA_ROOT":       (r'DEFAULT_DATA_ROOT = "([^"]+)"', "u5_dose/run_u5.py"),
    "run_u6.DEFAULT_DATA_ROOT":       (r'DEFAULT_DATA_ROOT = "([^"]+)"', "u6_assemble/run_u6.py"),
    "run_smoke.DEFAULT_SNAPSHOT_ROOT": (r'DEFAULT_SNAPSHOT_ROOT = "([^"]+)"', None),
}

_PORTED_VALUES = r'''
import json, pathlib, sys
P = pathlib.Path(sys.argv[1]) / "pipeline"
for u in ("u0_foundation","u1_fetch","u2_resolve","u3_panel","u4_output_star","u5_dose",
          "u6_assemble","u0p5_dept_roster"):
    sys.path.insert(0, str(P / "units" / u / "src"))
sys.path.insert(0, str(P)); sys.path.insert(0, str(P / "units/u5_dose"))
sys.path.insert(0, str(P / "units/u6_assemble"))
sys.path.insert(0, str(P / "units/u1_fetch/tests")); sys.path.insert(0, str(P / "units/u4_output_star/tests"))
import common.preflight as pf, m0_snapshot.capacity_gate as cg, roster.run_u0p5 as r5
import run_u4, run_u5, run_u6, run_smoke_m1, test_stream_build as tsb, test_roster_v3_wiring as trv
import inspect, re
pm = re.search(r'    pm = str\(_sar_derived_root\(\) / "([^"]+)"\)', inspect.getsource(r5)).group(1)
from pipeline.lib.paths import derived_root, snapshot_root
print(json.dumps({
  "preflight.DATA_ROOT": pf.DATA_ROOT,
  "capacity_gate.DATA_ROOT": cg.DATA_ROOT,
  "run_u0p5.SSD_DERIVED_DIR": str(r5.SSD_DERIVED_DIR),
  "run_u0p5.U1_FULL_DIR": str(r5.U1_FULL_DIR),
  "run_u0p5.person_map": str(derived_root() / pm),
  "s3_sync.snapshot_arg": str(snapshot_root()),
  "stream_build._REAL_SHARD": str(tsb._REAL_SHARD),
  "run_u4.measurement_artifact": run_u4.STOCK_ASOF_NOTE["measurement_artifact"],
  "roster_v3._SSD_V3": str(trv._SSD_V3),
  "run_u5.DEFAULT_DATA_ROOT": run_u5.DEFAULT_DATA_ROOT,
  "run_u6.DEFAULT_DATA_ROOT": run_u6.DEFAULT_DATA_ROOT,
  "run_smoke.DEFAULT_SNAPSHOT_ROOT": run_smoke_m1.DEFAULT_SNAPSHOT_ROOT,
}))
'''


def test_every_rewritten_path_still_resolves_to_its_legacy_literal():
    """Author-only: compares the ported path constants with the literals in the private original
    code, so it needs that tree (config key legacy_multiplex) and a data-disk root configured to
    the path those literals name."""
    import json, re, subprocess
    legacy_root = load_paths()["legacy_multiplex"]
    if not legacy_root.is_dir():
        pytest.skip("legacy tree not on this machine")
    got = json.loads(subprocess.run([sys.executable, "-c", _PORTED_VALUES, str(REPO)],
                                    capture_output=True, text=True, check=True).stdout)
    assert set(got) == set(LEGACY_LITERAL), set(got) ^ set(LEGACY_LITERAL)
    for name, (pattern, rel) in LEGACY_LITERAL.items():
        src = legacy_root / ("units/" + rel) if rel else legacy_root / "run_smoke_m1.py"
        m = re.search(pattern, src.read_text(encoding="utf-8"))
        assert m, f"{name}: legacy literal not found by {pattern!r} in {src.name}"
        want = m.group(1)
        if name == "run_u4.measurement_artifact":
            want = want + "f_measure_2026-07-16/asof_stock/ (summary.json + 明细 csv)"
        assert got[name] == want, f"{name}: ported resolves to {got[name]!r}, legacy literal is {want!r}"
    assert len(LEGACY_LITERAL) == 12


# --- T2: the same pin for the two patched DRIVER files -------------------------------------------
# `common80` is safe to import (constants + pure functions). The U3 driver is a top-level script -
# importing it would start an 18-minute panel build - so its three path constants are evaluated on
# their own, from the ported source, with the resolvers bound. Either way the value compared is the
# one the driver would actually use.
DRIVER_LITERAL = {
    "common80.SSD":       (r'SSD = pathlib\.Path\("([^"]+)"\)',
                           "scratchpad/final80_p10_2026-07-22/common80.py"),
    "common80.R_PKG":     (r'R_PKG = pathlib\.Path\(\n    "([^"]+)"\n    "([^"]+)"\)',
                           "scratchpad/final80_p10_2026-07-22/common80.py"),
    "u3.SNAPSHOT":        (r'SNAPSHOT = "([^"]+)"',
                           "scratchpad/u3_run/run_u3_rebuild_f123_2026-07-06.py"),
    "u3.DATA_ROOT":       (r'DATA_ROOT = "([^"]+)"',
                           "scratchpad/u3_run/run_u3_rebuild_f123_2026-07-06.py"),
    "u3.OUT":             (r'OUT = "([^"]+)"',
                           "scratchpad/u3_run/run_u3_rebuild_f123_2026-07-06.py"),
}

_DRIVER_VALUES = r'''
import json, pathlib, re, sys
R = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(R))
sys.path.insert(0, str(R / "pipeline/drivers/final80_p10_2026-07-22"))
import common80
from pipeline.lib.paths import (derived_root as _sar_derived_root, snapshot_root as _sar_snapshot_root,
                                ssd_root as _sar_ssd_root, legacy_thesis as _sar_legacy_thesis,
                                require_readable as _sar_rd, require_writable as _sar_rw,
                                output_target as _sar_out, deferred_output_target as _sar_lazyout)
u3 = (R / "pipeline/drivers/u3_run/run_u3_rebuild_f123_2026-07-06.py").read_text("utf-8")
ns = dict(_sar_derived_root=_sar_derived_root, _sar_snapshot_root=_sar_snapshot_root,
          _sar_ssd_root=_sar_ssd_root, _sar_legacy_thesis=_sar_legacy_thesis,
          _sar_rd=_sar_rd, _sar_rw=_sar_rw, _sar_out=_sar_out, _sar_lazyout=_sar_lazyout)
body = u3.split("from m3_panel.panel import build_panel", 1)[1]
lines, take = [], False
for ln in body.splitlines():
    if re.match(r"^(SNAPSHOT|DATA_ROOT|OUT) = ", ln):
        take = True
    elif take and not ln.startswith(" "):
        take = False
    if take:
        lines.append(ln)
assert sum(1 for ln in lines if re.match(r"^(SNAPSHOT|DATA_ROOT|OUT) = ", ln)) == 3, lines
src = "\n".join(lines)
# OUT goes through the write barrier and its declared destination is a FROZEN artifact, so it
# raises. The pin is then on the destination the exception carries - the same legacy literal.
from pipeline.lib.paths import WriteBarred
try:
    exec(src, ns)
    out_value, barred = ns["OUT"], False
except WriteBarred as exc:
    out_value, barred = str(exc.target), True
print(json.dumps({
  "common80.SSD": str(common80.SSD),
  "common80.R_PKG": str(common80.R_PKG),
  "u3.SNAPSHOT": ns["SNAPSHOT"],
  "u3.DATA_ROOT": ns["DATA_ROOT"],
  "u3.OUT": out_value,
  "_out_barred": barred,
  "_rpkg_barred": type(common80.R_PKG).__name__ == "BarredWriteTarget",
}))
'''


def test_every_rewritten_driver_path_still_resolves_to_its_legacy_literal():
    """Author-only, for the same reason as the test above."""
    import json, re, subprocess
    legacy_root = load_paths()["legacy_multiplex"]
    if not legacy_root.is_dir():
        pytest.skip("legacy tree not on this machine")
    if not load_paths()["ssd_root"].is_dir():
        pytest.skip("pipeline data disk not mounted (the drivers guard their roots at import)")
    got = json.loads(subprocess.run([sys.executable, "-c", _DRIVER_VALUES, str(REPO)],
                                    capture_output=True, text=True, check=True).stdout)
    # T2-review F3: both write destinations are behind the barrier, and the pin still resolves.
    assert got.pop("_out_barred") is True, "the U3 driver's frozen output is no longer barred"
    assert got.pop("_rpkg_barred") is True, "step4's legacy destination is no longer barred"
    assert set(got) == set(DRIVER_LITERAL), set(got) ^ set(DRIVER_LITERAL)
    for name, (pattern, rel) in DRIVER_LITERAL.items():
        m = re.search(pattern, (legacy_root / rel).read_text(encoding="utf-8"))
        assert m, f"{name}: legacy literal not found by {pattern!r} in {rel}"
        want = "".join(m.groups())          # R_PKG's legacy literal is an implicit two-part concat
        assert got[name] == want, f"{name}: ported resolves to {got[name]!r}, legacy is {want!r}"
    assert len(DRIVER_LITERAL) == 5


# --- T2-review F3: the write barrier -------------------------------------------------------------
def test_output_target_allows_a_fresh_directory(tmp_path):
    fresh = tmp_path / "u6_ship_rebuild"
    assert output_target(fresh) == fresh                      # nothing there yet: safe
    (fresh / "sub").mkdir(parents=True)
    with pytest.raises(WriteBarred) as e:                     # now it holds a run's output
        output_target(fresh)
    assert e.value.reason == "frozen" and "SAR_OUT_ROOT" in str(e.value)
    assert e.value.target == fresh


def test_output_target_refuses_a_destination_inside_the_repo_source_tree(tmp_path):
    """T4 review MAJOR-1, half one. Legacy and "already non-empty" were the only two refusals, so a
    ported stage aiming at the repo's own tree was waved through: the FWCI scan created
    `pipeline/fwci/<run dir>/{data,logs,partial}/` - untracked but NOT git-ignored - holding a second,
    unhashed `fwci_baseline_pop_full.parquet` under the frozen artifact's own basename. `output/` is
    the one place inside the repo a stage may write, because it is git-ignored scratch."""
    for inside in (REPO / "pipeline" / "fwci" / "would_be_output",
                   REPO / "data" / "fwci" / "rebuild",
                   REPO / "analysis" / "scratch"):
        with pytest.raises(WriteBarred) as e:
            output_target(inside, what="a ported stage")
        assert e.value.reason == "repo", (inside, e.value.reason)
        assert "source tree" in str(e.value) and "output" in str(e.value)

    allowed = REPO / "output" / "fwci_barrier_probe"      # git-ignored scratch, and not yet there
    assert output_target(allowed) == allowed
    assert not allowed.exists(), "resolving a destination must not create it"

    outside = tmp_path / "somewhere_else"                 # nothing changes for paths off the repo
    assert output_target(outside) == outside


def test_out_root_pointing_into_the_repo_source_tree_is_refused(monkeypatch, tmp_path):
    """The redirect is judged by the same rule (T2 re-review R1's lesson, applied to the new one)."""
    monkeypatch.setenv("SAR_OUT_ROOT", str(REPO / "pipeline"))
    with pytest.raises(WriteBarred) as e:
        output_target(tmp_path / "anything")
    assert e.value.reason == "repo"


def _pipeline_dirs() -> list[str]:
    """Directories under `pipeline/`, EXCLUDING byte-code caches.

    MILESTONE REVIEW, cross-layer MAJOR: `__pycache__` counted as output, so the root suite was not
    green from a clean checkout — the first probe subprocess created one and the next snapshot read
    it as "a directory a refused run created". Byte-code is not output. Belt and braces, the probes
    also run with PYTHONDONTWRITEBYTECODE=1.
    """
    return sorted(d.as_posix() for d in (REPO / "pipeline").rglob("*")
                  if d.is_dir() and "__pycache__" not in d.parts and ".pytest_cache" not in d.parts)


def test_no_ported_script_can_be_run_where_it_sits():
    """T4 review MAJOR-1, half two - the half that actually stops the 37-minute scan.

    `output_target()` never sees the FWCI scan's destination: the script computes
    `BASE = Path(__file__).resolve().parent.parent` and writes there directly, and that line holds no
    absolute path so the verbatim rule forbids touching it. The reviewer therefore ran the ported
    script directly and reached `main()` with exit 0. The refusal now attaches to the resolver call
    the ported constants DO make at import, so every ported script that resolves a root stops before
    `main()` - and this test drives the scripts, not the launcher."""
    import subprocess
    scripts = [
        "pipeline/fwci/fwci_baseline_fullsnapshot_2026-08-09/code/01_scan_full_snapshot.py",
        "pipeline/fwci/fwci_fullsnapshot_rebuild_2026-08-09/code/01_build_expected_full.py",
        "pipeline/drivers/final80_p10_2026-07-22/step1_freeze_ship_80ev.py",
        "pipeline/drivers/final80_p10_2026-07-22/step4_export_r.py",
        "pipeline/drivers/u3_run/run_u3_rebuild_f123_2026-07-06.py",
        # T5: the roster scripts. Each has ONE constant that is both its input root and its output
        # root, so an in-place run rewrites the human-verification evidence in the legacy tree.
        "pipeline/rosters/multidisc_roster_econ_grade_2026-08-09/verify/merge_chemmath_verified_v2.py",
        "pipeline/rosters/multidisc_gold_2026-08-10/code/00b_prep_roster_variants.py",
        "pipeline/rosters/multidisc_gold_2026-08-10/code/00c_prep_final_population.py",
        # T6: the star/event scripts. 60/72/00_make_u4_aug resolve READ roots, so require_readable
        # fires the guard at import; run_screening's BASE goes through the DEFERRED barrier (it must
        # stay importable for _POOL_SQL) but its SSD constant is a require_readable, so it stops too.
        "pipeline/stars/multidisc_2026-07-24/code/star_screening/run_screening.py",
        "pipeline/stars/multidisc_gold_2026-08-10/code/60_poach_gate_false_negatives.py",
        "pipeline/stars/multidisc_gold_2026-08-10/code/72_restake_fnfix_stars.py",
        "pipeline/stars/econ_fnfix_2026-08-15/code/00_make_u4_aug.py",
    ]
    env = {k: v for k, v in os.environ.items()
           if k not in ("SAR_OUT_ROOT", "SAR_STAGED_RUN", "SAR_STAGE_ROOT")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    before = _pipeline_dirs()
    for rel in scripts:
        assert (REPO / rel).is_file(), rel
        r = subprocess.run([sys.executable, str(REPO / rel), "--shard-list", "999999"],
                           cwd=REPO, capture_output=True, text=True, env=env)
        assert r.returncode != 0, f"{rel} ran with no gate:\n{r.stdout[-2000:]}"
        assert "refusing to run a ported pipeline script where it sits" in r.stderr, \
            f"{rel} failed for some OTHER reason - the guard did not fire:\n{r.stderr[-2000:]}"
        assert "run_fwci.py --list" in r.stderr and "run_driver.py --list" in r.stderr, \
            f"{rel}: the refusal must say what to do instead"
    assert _pipeline_dirs() == before, \
        "a refused run still created directories under pipeline/"


def test_a_launcher_may_run_where_it_sits_and_marks_the_script_it_stages():
    """The exemption, asserted so it cannot silently widen: an exact list of launcher paths, all
    present, all repo-authored, and the marker names the staged file rather than switching the guard
    off. (The count moves with the layer - T6 added the fourth - so it is written out, not counted.)

    T8: the marker is a `with staged_run(...)` block in each launcher, not an environment
    assignment, so this asserts on the block."""
    from pipeline.lib.paths import LAUNCHERS, refuse_unstaged_in_place_run
    # 2026-09-23: the seven cal2026-10 launchers (star re-rank, econ11 re-rank, local estimates,
    # Panel 3 sweep, Piece B, econ920, chem/math frames) were appended to pipeline.lib.paths.LAUNCHERS
    # in the October work; the pin follows that tuple's own order.
    assert LAUNCHERS == ("pipeline/drivers/run_driver.py", "pipeline/fwci/run_fwci.py",
                         "pipeline/rosters/run_rosters.py",
                         "pipeline/stars/run_stars.py",
                         "pipeline/frames/run_frames.py",
                         "pipeline/stars/caliber_2026-08-28/run_caliber.py",
                         "pipeline/stars/caliber_2026-08-28/run_supplement.py",
                         "pipeline/stars/caliber_2026-10/run_caliber.py",
                         "pipeline/stars/caliber_2026-10/restake_econ11.py",
                         "pipeline/stars/caliber_2026-10/run_cal_estimates.py",
                         "pipeline/frames/cal2026-10/run_cal_afar.py",
                         "pipeline/frames/cal2026-10/econ_gold/run_econ_gold.py",
                         "pipeline/frames/cal2026-10/econ920/run_econ920.py",
                         "pipeline/frames/cal2026-10/run_cal_frames_chemmath.py",
                         "pipeline/stars/caliber_2026-08-28/run_cal_frames.py",
                         "pipeline/stars/caliber_2026-08-28/run_cal_estimates.py",
                         "pipeline/stars/caliber_2026-08-28/run_cal_cloud.py",
                         "pipeline/stars/caliber_2026-08-28/run_cal_ledger.py"), LAUNCHERS
    for rel in LAUNCHERS:
        assert (REPO / rel).is_file(), rel
    for rel in LAUNCHERS:
        src = (REPO / rel).read_text(encoding="utf-8")
        # cal2026-08-28 Task 2: a launcher that runs NO ported script (run_supplement.py — pure
        # live-API fetch + freeze) has nothing to stage; the guard's intent — every runpy call
        # sits inside a mark — is asserted for everyone by the count identity below.
        assert "with staged_run(" in src or "runpy" not in src, \
            f"{rel} does not mark its staged run"
        assert "os.environ[STAGED_RUN_ENV]" not in src, (
            f"{rel} marks its staged run through the environment again - a variable the person the "
            f"guard protects can export")
        # every runpy call must be inside a mark: a launcher that runs a ported script without one
        # would be refused, and one that runs it outside the block would be the old hazard back
        assert src.count("runpy.run_path(") == src.count("with staged_run("), rel
    refuse_unstaged_in_place_run()          # __main__ is pytest, which is not under pipeline/


def test_the_staged_marker_only_exempts_the_file_it_names(monkeypatch):
    """A marker set to something else must not be a blanket off-switch."""
    from pipeline.lib import paths as _paths
    from pipeline.lib.paths import refuse_unstaged_in_place_run, staged_run
    with staged_run(REPO / "pipeline" / "not_the_running_script.py"):
        refuse_unstaged_in_place_run()      # still fine here: __main__ is pytest
        monkeypatch.setattr(sys.modules["__main__"], "__file__",
                            str(REPO / "pipeline/fwci/fwci_baseline_fullsnapshot_2026-08-09/code/"
                                       "01_scan_full_snapshot.py"), raising=False)
        with pytest.raises(PathUnresolved, match="where it sits"):
            refuse_unstaged_in_place_run()
    with staged_run(sys.modules["__main__"].__file__):
        refuse_unstaged_in_place_run()      # the marker names THIS file: allowed
    # and it is restored on the way out of every block, so a stage cannot leak the exemption
    assert _paths.staged_run_script() is None
    with pytest.raises(PathUnresolved, match="where it sits"):
        refuse_unstaged_in_place_run()


def test_t8_exporting_the_old_environment_variable_no_longer_exempts_anything(monkeypatch):
    """The carried T4-review item, closed. `$SAR_STAGED_RUN` was the exemption AND was named in the
    refusal message, so the documented way out of the guard was to export the variable the error
    text handed you - and the hazard it guards is a 37-minute scan writing into the source tree.

    Two halves: exporting it does nothing in-process, and a real bare run of the ported scan with
    the variable exported still refuses, creates nothing, and does not mention the variable.
    """
    from pipeline.lib.paths import STAGED_RUN_ENV, refuse_unstaged_in_place_run
    scan = (REPO / "pipeline/fwci/fwci_baseline_fullsnapshot_2026-08-09/code/"
                   "01_scan_full_snapshot.py")
    monkeypatch.setattr(sys.modules["__main__"], "__file__", str(scan), raising=False)
    monkeypatch.setenv(STAGED_RUN_ENV, str(scan))
    with pytest.raises(PathUnresolved, match="where it sits"):
        refuse_unstaged_in_place_run()

    before = _pipeline_dirs()
    env = {**{k: v for k, v in os.environ.items()
              if k not in ("SAR_OUT_ROOT", "SAR_STAGE_ROOT")}, STAGED_RUN_ENV: str(scan),
           "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([sys.executable, str(scan), "--shard-list", "999999"],
                       cwd=REPO, capture_output=True, text=True, env=env)
    assert r.returncode != 0, r.stdout[-2000:]
    assert "refusing to run a ported pipeline script where it sits" in r.stderr, r.stderr[-2000:]
    assert STAGED_RUN_ENV not in r.stderr, (
        "the refusal still advertises an environment variable as the way past it")
    assert _pipeline_dirs() == before


def test_output_target_refuses_anything_inside_a_legacy_root():
    if not legacy_thesis().is_dir():
        pytest.skip("legacy tree not on this machine")
    dest = legacy_thesis() / "v2_output" / "r_p10_80ev_2026-07-22"
    assert is_inside_legacy(dest) is not None
    with pytest.raises(WriteBarred) as e:
        output_target(dest)
    assert e.value.reason == "legacy" and "read-only legacy tree" in str(e.value)


def test_out_root_override_redirects_instead_of_refusing(tmp_path, monkeypatch):
    if not legacy_thesis().is_dir():
        pytest.skip("legacy tree not on this machine")
    monkeypatch.setenv("SAR_OUT_ROOT", str(tmp_path))
    dest = legacy_thesis() / "v2_output" / "r_p10_80ev_2026-07-22"
    assert output_target(dest) == tmp_path / "r_p10_80ev_2026-07-22"
    assert deferred_output_target(dest) == tmp_path / "r_p10_80ev_2026-07-22"


def test_deferred_target_reads_like_a_path_and_refuses_every_write(tmp_path):
    frozen = tmp_path / "frozen"
    (frozen / "keep").mkdir(parents=True)
    barred = deferred_output_target(frozen)
    assert isinstance(barred, BarredWriteTarget)
    assert str(barred) == str(frozen) and barred.name == "frozen" and barred.exists()
    for do in (lambda: barred.mkdir(parents=True, exist_ok=True),
               lambda: (barred / "data").mkdir(parents=True, exist_ok=True),
               lambda: open(barred / "data" / "x.csv", "w"),
               lambda: barred.write_text("x"),
               lambda: os.fspath(barred)):
        with pytest.raises(WriteBarred):
            do()
    assert (frozen / "data").exists() is False                # nothing was created on the way


# ---------------------------------------------------------------------------
# M3 Task 8 — the two operator-named CLIs (T4 final review carry)
# ---------------------------------------------------------------------------

#: the two ported entry points whose output location comes from a command-line argument rather than
#: from an absolute constant. The T4 final review carried them to Task 8 as "require_writable on
#: run_m1_full.py / run_u3.py".
OPERATOR_NAMED_CLIS = {
    "pipeline/units/u1_fetch/src/m1_ingest/run_m1_full.py": "--out-root",
    "pipeline/units/u3_panel/run_u3.py": "--out-dir",
}


def test_t8_the_operator_named_clis_cannot_reach_a_write_and_that_is_pinned_not_argued(tmp_path):
    """The carried item, closed by measurement plus a tripwire rather than by patching the port.

    **Why the guard is not inside these two files.** `require_writable` would have to wrap
    `_args.out_root` / `args.out_dir`, and the port has two rules that forbid exactly that: a guard
    call must contain a RESOLVER call inside its own span (T6 final review MINOR-7 — a guard exists
    to make a resolved root safe, and wrapping anything else is invisible to normalisation), and a
    source hunk may only be rewritten if it carried an absolute path (the hunk sanity rule). Neither
    of these lines carries a path; both hold a parsed argument. Patching them would have meant
    weakening two rules that exist because both were defeated during review.

    **What is checked, exactly (corrected after the T8 review, MINOR-2).** The tripwire is an AST
    scan for a WRITE SURFACE, plus execution, plus the sha pins:

    1. AST: neither module calls anything on the write surface below — the layer's own writing entry
       point (`run_full`, `run_m1_streaming`), the parquet writers, or the filesystem verbs
       (`open(..., "w")`, `write_text`, `write_bytes`, `mkdir`, `makedirs`, `to_parquet`,
       `write_table`, `to_csv`). The first version of this test scanned for `run_full` alone, and the
       reviewer walked straight past it with four lines writing `SMUGGLED.txt` into `--out-root`.
    2. Execution: both are driven with their output argument aimed at `data/frames`, a TRACKED
       directory holding the frozen frames, and nothing under `data/` is created or modified. This
       covers only the argument vectors listed, so it is corroboration, not the guarantee.
    3. Both files are sha256-pinned in `tests/pipeline_ported.sha256`, so any edit at all — including
       one this scan does not model — is a diff line in review on every machine.

    The honest statement of the guarantee is therefore: **no call to a writing primitive, plus a sha
    pin that makes any other change visible** — not "these files can never write". `run_u3.main`
    raises `SystemExit` before it could, and `run_m1_full`'s `__main__` calls `build_plan`, whose own
    docstring says it neither reads the snapshot nor writes (its plan note: a dry run reads no full snapshot and writes nothing).
    """
    import ast
    import hashlib

    #: the write surface. Not "every way to write a file" — that is unbounded — but every way THESE
    #: two modules could plausibly reach one, named so that omitting a new one is a visible edit.
    #: `open` counts only with a mode containing w/a/x: a read is not a write.
    WRITERS = {"run_full", "run_m1_streaming", "to_parquet", "write_table", "to_csv",
               "write_text", "write_bytes", "mkdir", "makedirs", "open"}

    def _calls(node) -> set[str]:
        out = set()
        for n in ast.walk(node):
            if not isinstance(n, ast.Call):
                continue
            name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
            if name is None:
                continue
            if name == "open":
                modes = [a.value for a in n.args[1:2] if isinstance(a, ast.Constant)]
                modes += [k.value.value for k in n.keywords
                          if k.arg == "mode" and isinstance(k.value, ast.Constant)]
                if not any(set("wax") & set(m) for m in modes if isinstance(m, str)):
                    continue
            out.add(name)
        return out

    for rel in OPERATOR_NAMED_CLIS:
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        main_blocks = [n for n in tree.body if isinstance(n, ast.If)
                       and ast.dump(n.test).count("__name__") and ast.dump(n.test).count("__main__")]
        assert len(main_blocks) == 1, f"{rel}: expected exactly one __main__ block"
        # module-level functions, so the closure can follow a call into one of them
        defs = {n.name: n for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        # transitive closure of what `__main__` can reach INSIDE this module. `run_full` and
        # `run_m1_streaming` live in the module but are not reachable from `__main__`, which is the
        # whole claim - a module-wide scan would flag them and say nothing.
        reachable, frontier = set(), list(_calls(main_blocks[0]))
        while frontier:
            name = frontier.pop()
            if name in reachable:
                continue
            reachable.add(name)
            if name in defs:
                frontier += list(_calls(defs[name]))
        hits = reachable & WRITERS
        assert hits == set(), (
            f"{rel}: its `__main__` can now reach {sorted(hits)}. The output root comes from the "
            f"command line and is unguarded; add the guard (or move the entry point out of the "
            f"port) before this ships.")

    # --- (2)+(3) execution, with the argument aimed at the frozen frames -------------------------
    src_dirs = [REPO / "pipeline/units" / u / "src" for u in
                ("u0_foundation", "u1_fetch", "u2_resolve", "u3_panel", "u4_output_star")]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(d) for d in src_dirs)}
    frames = REPO / "data" / "frames"

    def _snapshot():
        return {p.relative_to(REPO).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted((REPO / "data").rglob("*")) if p.is_file()}

    before = _snapshot()
    runs = [
        ([str(REPO / "pipeline/units/u1_fetch/src/m1_ingest/run_m1_full.py"),
          "--snapshot-root", str(tmp_path), "--out-root", str(frames)], "executed"),
        ([str(REPO / "pipeline/units/u1_fetch/src/m1_ingest/run_m1_full.py"),
          "--snapshot-root", str(tmp_path), "--out-root", str(frames), "--execute"], "executed"),
        ([str(REPO / "pipeline/units/u3_panel/run_u3.py"),
          "--data-root", str(tmp_path), "--out-dir", str(frames)], None),
    ]
    for argv, expect in runs:
        r = subprocess.run([sys.executable, *argv], cwd=REPO, capture_output=True, text=True,
                           env=env)
        combined = r.stdout + r.stderr
        if expect:
            assert '"executed": false' in r.stdout, combined[-2000:]
        assert "Traceback" not in r.stderr or "SystemExit" not in r.stderr, combined[-2000:]
    assert _snapshot() == before, "an operator-named CLI wrote into the tracked data tree"


# --- the October paths file and the test default ------------------------------------------------
OCTOBER_PATHS = REPO / "config" / "paths_october.yaml"


def test_paths_october_differs_from_paths_yaml_only_in_the_canon_keys():
    """config/paths_october.yaml selects the October 2026 version. It has the keys of config/paths.yaml and
    the same values, except the six canon keys, which hold the October roots."""
    import yaml
    from analysis.lib import canon
    main = yaml.safe_load((REPO / "config" / "paths.yaml").read_text(encoding="utf-8"))
    october = yaml.safe_load(OCTOBER_PATHS.read_text(encoding="utf-8"))
    assert set(october) == set(main), set(october) ^ set(main)
    assert {k: v for k, v in october.items() if k not in canon.KEYS} == \
        {k: v for k, v in main.items() if k not in canon.KEYS}
    assert {k: october[k] for k in canon.KEYS} == canon.OCTOBER


def test_the_test_plugin_defaults_the_paths_config_to_october(tmp_path):
    """sar_f0_plugin.py sets $SAR_PATHS_CONFIG to config/paths_october.yaml when it is unset or blank, so the
    tests read the October version whatever config/paths.yaml selects. A config already set is kept."""
    code = ("import os, sys; sys.path.insert(0, sys.argv[1]); import sar_f0_plugin; "
            "print(os.environ['SAR_PATHS_CONFIG'])")
    other = tmp_path / "paths_other.yaml"
    other.write_text('repo_root: "."\n', encoding="utf-8")
    base = {k: v for k, v in os.environ.items() if k != "SAR_PATHS_CONFIG"}
    for env, want in ((base, OCTOBER_PATHS), ({**base, "SAR_PATHS_CONFIG": " "}, OCTOBER_PATHS),
                      ({**base, "SAR_PATHS_CONFIG": str(other)}, other)):
        r = subprocess.run([sys.executable, "-c", code, str(REPO)], cwd=tmp_path, env=env,
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-2000:]
        assert r.stdout.strip() == str(want)
    assert OCTOBER_PATHS.is_file()
