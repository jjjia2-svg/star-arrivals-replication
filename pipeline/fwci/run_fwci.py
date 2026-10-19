#!/usr/bin/env python3
"""The entry point for the two ported FWCI scripts — repo-authored, not part of the verbatim port.

Why this exists, and why it is not `drivers/run_driver.py`. Both FWCI scripts derive EVERY output
location from their own file:

    01_build_expected_full.py   BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    01_scan_full_snapshot.py    BASE = Path(__file__).resolve().parent.parent

Neither line holds an absolute path, so under M3's verbatim rule neither may be touched — the same
situation as `step3_run_u6.py`'s `U6_OUT` (see `drivers/run_driver.py`). `run_driver` solves its case
by resolving a driver's declared output CONSTANT before running it; that does not work here, because
the constant is computed from `__file__` at import and re-computing it changes nothing about where
the script will actually write. So this launcher moves the file instead of the constant: it
materialises a run directory in the repo's git-ignored `output/` scratch tree, links the ported
script into `<run dir>/code/` (byte-identity asserted, not assumed), and runs THAT. The script then
computes exactly the destinations it always did, one level below a location `output_target()`
approved, and not one ported byte differs.

    python3 pipeline/fwci/run_fwci.py --list
    python3 pipeline/fwci/run_fwci.py build
    python3 pipeline/fwci/run_fwci.py scan --execute      # 37.0 minutes, needs the 696 GB snapshot

`build` (~10 s) is the stage M3 actually runs and checks: it rebuilds the 130,061-cell expected
table that every frozen P1 frame's FWCI denominator comes from, and `tests/test_pipeline_rebuild.py`
compares it with `tools/content_equal.py` against the frozen copy in `data/fwci/`.

`scan` is DEFAULT OFF and is not run by M3 at all. It is the 37.0-minute, 510,372,821-record
full-snapshot pass that produced `build`'s input; the plan forbids expensive reruns, its output
survives and is frozen in `data/fwci/`, and its manifests are what the paper's funnel numbers cite.
Asking for it without `--execute` prints the cost and exits 2.

`$SAR_OUT_ROOT` works the same way it does for `run_driver.py`: it moves the scratch root, is itself
judged by the write barrier, and is single-use (the second run into the same root is refused, because
by then the destination exists and is non-empty). Without it the scratch root is `<repo>/output/fwci`,
which this launcher CLEARS before staging — `output/` is git-ignored and every other stage in the
repo overwrites it, so a stale run directory must not be able to fail the next run.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import os
import pathlib
import runpy
import shutil
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))
from pipeline.lib.paths import (OUT_ROOT_ENV, staged_run,  # noqa: E402
                                PathUnresolved, output_target)

FWCI_DIR = pathlib.Path(__file__).resolve().parent
#: the scratch root. Its BASENAME must stay "fwci": the ported preamble finds the repo by walking up
#: to the directory of that name, and `$SAR_OUT_ROOT` redirects to `<root>/<basename>`, so the
#: component survives the redirect and the staged script anchors correctly either way.
SCRATCH = REPO / "output" / "fwci"

#: the frozen run records the cost warning is BUILT from. T4 review NIT-1: the warning used to be a
#: literal, and the reviewer falsified six of its eight numbers - including two the paper cites as
#: funnel figures - while keeping the two substrings a test pinned, with the suite green and
#: REPIN_OK. A number that matters cannot live in prose beside its own source, so every figure below
#: is READ from `data/fwci/`, whose contents are sha256-pinned in `data/MANIFEST.sha256`.
FROZEN_FWCI = REPO / "data" / "fwci"
SCAN_MANIFEST = FROZEN_FWCI / "scan_manifest.json"
SCAN_LOG = FROZEN_FWCI / "scan_full_2026-08-09.log"


def _scan_cost() -> str:
    """The scan's cost, quoted from its own frozen record and console log."""
    import json                                                        # noqa: PLC0415
    import re                                                          # noqa: PLC0415
    m = json.loads(SCAN_MANIFEST.read_text())
    log = SCAN_LOG.read_text()

    def _one(pattern: str, what: str) -> str:
        found = re.findall(pattern, log)
        if not found:
            raise SystemExit(f"[run_fwci] {what} is not in {SCAN_LOG.name} - the cost warning "
                             f"cannot be built from a record that does not say it")
        return found[-1]

    minutes = float(_one(r"scan done in ([0-9.]+) min", "the measured runtime"))
    workers = int(_one(r"workers=(\d+)", "the worker count"))
    gz_bytes = int(_one(r"gz_bytes=([\d,]+)", "the streamed byte count").replace(",", ""))
    rate = _one(r"cum=[\d,]+ ([\d,]+) rec/s", "the throughput")
    return (
        f"{minutes:.1f} minutes wall clock with {workers} worker processes, plus "
        f"{m['merge_elapsed_min']} min to merge {m['n_partials']} partial tables; it streams all "
        f"{m['shards']:,} gzip works shards of the frozen {m['snapshot_manifest_date']} OpenAlex "
        f"snapshot - {gz_bytes / 1e9:.1f} GB of compressed works read at ~{rate} rec/s, "
        f"{m['total_lines_read']:,} records. No cloud cost, but the data disk must be mounted and "
        f"the machine is busy for over half an hour. Its output is already frozen in "
        f"data/fwci/fwci_baseline_pop_full.parquet ({m['n_cells']:,} cells, sha256 pinned in "
        f"data/MANIFEST.sha256) and its manifest is the source of the paper's funnel numbers "
        f"({m['sum_work_count']:,} cellable works, {m['sum_citation_sum']:,} citations, "
        f"{m['bad_lines']} bad lines), so re-running it proves nothing M3 has not already checked "
        f"from the surviving artifact. NOTE: the scanner needs `orjson`; without it every worker "
        f"raises SystemExit and you must pass `--json-lib stdlib` instead (about 3x slower)."
    )


#: stage -> (ported script relative to this directory,
#:           the run directory's outputs, relative to it,
#:           modules to import from the REPO's ported units before the script runs,
#:           False for a stage M3 runs, or True for one gated behind --execute; the cost of a gated
#:           stage is built by _scan_cost() from the frozen record, never written out here)
STAGES: dict[str, tuple[str, tuple[str, ...], tuple[tuple[str, str], ...], bool]] = {
    "build": (
        "fwci_fullsnapshot_rebuild_2026-08-09/code/01_build_expected_full.py",
        ("data/fwci_expected_fullsnapshot_2026-08-09.parquet",
         "data/fwci_expected_oldpop_2026-08-09.parquet",
         "data/g_step1_expected.json"),
        (("u0_foundation", "common._redlines"), ("u4_output_star", "m5_output.fwci_baseline_build")),
        False,
    ),
    "scan": (
        "fwci_baseline_fullsnapshot_2026-08-09/code/01_scan_full_snapshot.py",
        ("data/fwci_baseline_pop_full.parquet", "data/scan_manifest.json"),
        (("u1_fetch", "m1_ingest.fwci_accumulator"), ("u1_fetch", "m1_ingest.schema_map")),
        True,
    ),
}


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def unregistered_scripts() -> list[str]:
    """Ported FWCI scripts on disk that no stage runs. Anything here would sit in the layer with no
    launcher, no cost gate and no staged output location; `tests/test_verbatim_pipeline.py` fails."""
    registered = {script for script, _o, _m, _c in STAGES.values()}
    me = pathlib.Path(__file__).resolve()
    found = sorted(f.relative_to(FWCI_DIR).as_posix() for f in FWCI_DIR.rglob("*.py")
                   if f.resolve() != me and "__pycache__" not in f.parts)
    return [f for f in found if f not in registered]


def _preimport(modules: tuple[tuple[str, str], ...]) -> list[str]:
    """Import the production modules from the REPO's ported units, before the ported script runs.

    The script's own `sys.path.insert(0, f"{ROOT}/multiplex_pipeline/units/…")` still executes and
    still names the legacy tree — that line holds no absolute path of its own, so the port could not
    touch it. Importing the modules here first means `sys.modules` already holds them and the
    script's `from common._redlines import …` binds the REPO's copy: the formula that runs is the
    one this repository ships. The two copies are byte-identical anyway (that is what
    `tests/test_verbatim_pipeline.py::test_units_verbatim` proves), so this changes which file is
    read, never what it says. Returns the files actually used, for the run record.
    """
    used = []
    for unit, module in modules:
        src = REPO / "pipeline" / "units" / unit / "src"
        if not src.is_dir():
            raise PathUnresolved(f"ported unit source missing: {src}")
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))
        used.append(f"{module} <- {getattr(importlib.import_module(module), '__file__', '?')}")
    return used


def _stage_run_dir(stage: str) -> pathlib.Path:
    """The run directory to execute in: `<scratch>/<legacy run directory name>`, approved by the
    write barrier. Clearing only applies to the repo's own git-ignored scratch tree."""
    if not os.environ.get(OUT_ROOT_ENV, "").strip():
        if SCRATCH.is_dir() and not SCRATCH.is_symlink() and SCRATCH.parent == REPO / "output":
            shutil.rmtree(SCRATCH)
    scratch = output_target(SCRATCH, f"fwci {stage}")
    script, _outputs, _modules, _cost = STAGES[stage]
    return scratch / script.split("/", 1)[0]


def _link(ported: pathlib.Path, dest: pathlib.Path) -> str:
    """Put the ported script at `dest` without changing a byte. A hard link keeps `__file__` inside
    the run directory (a SYMLINK would not: the scanner's `Path(__file__).resolve()` follows one and
    would land back in the repo). Falls back to a copy across filesystems; either way the bytes are
    checked, so 'the file that ran is the file that is committed' is asserted, not assumed."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    how = "hard link"
    try:
        os.link(ported, dest)
    except OSError:
        shutil.copyfile(ported, dest)
        how = "copy"
    want, got = _sha(ported), _sha(dest)
    if want != got:
        raise SystemExit(f"[run_fwci] staged file differs from the ported file: {want} != {got}")
    return f"{how}, sha256 {got}"


#: T4 carry, closed in T8. `01_build_expected_full.py:45` builds its NEWPOP input as
#: `f"{ROOT}/v2_output/.../fwci_baseline_pop_full.parquet"` — an f-string with no absolute path of
#: its own, so only `ROOT` was resolvable when the file was ported, and `build` therefore needed the
#: author's read-only thesis tree for a file this package already ships. `data/fwci/` holds that
#: exact parquet (sha256-pinned in `data/MANIFEST.sha256`), so the launcher builds the one directory
#: of the legacy layout the builder reaches into, links the FROZEN copy in, and points
#: `$SAR_LEGACY_THESIS` at it. The link is verified by hash, so the run record's `source_new_pop`
#: names a file whose bytes are checked rather than assumed.
NEWPOP_REL = "v2_output/fwci_baseline_fullsnapshot_2026-08-09/data/fwci_baseline_pop_full.parquet"


def _frozen_legacy_shim(scratch: pathlib.Path) -> pathlib.Path:
    """A one-file shadow of the legacy thesis tree, holding the frozen NEWPOP parquet."""
    frozen = FROZEN_FWCI / "fwci_baseline_pop_full.parquet"
    if not frozen.is_file():
        raise SystemExit(f"[run_fwci] the frozen population table is missing: {frozen}")
    manifest = (REPO / "data" / "MANIFEST.sha256").read_text(encoding="utf-8")
    want = _sha(frozen)
    if f"{want}  data/fwci/fwci_baseline_pop_full.parquet" not in manifest:
        raise SystemExit("[run_fwci] data/fwci/fwci_baseline_pop_full.parquet does not match its "
                         "line in data/MANIFEST.sha256 - refusing to feed it to the builder")
    shim = scratch / "_frozen_legacy_thesis"
    dest = shim / NEWPOP_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    try:
        os.link(frozen, dest)
    except OSError:
        shutil.copyfile(frozen, dest)
    if _sha(dest) != want:
        raise SystemExit(f"[run_fwci] the staged population table differs from {frozen}")
    return shim


def run(stage: str, execute: bool, rest: list[str]) -> int:
    script, outputs, modules, gated = STAGES[stage]
    if gated and not execute:
        print(f"[run_fwci] stage '{stage}' is OFF by default. Cost:\n\n  {_scan_cost()}\n\n"
              f"  Re-run with --execute if you really want it:\n"
              f"      python3 pipeline/fwci/run_fwci.py {stage} --execute", file=sys.stderr)
        return 2
    ported = FWCI_DIR / script
    if not ported.is_file():
        print(f"[run_fwci] ported script missing: {ported}", file=sys.stderr)
        return 2
    try:
        run_dir = _stage_run_dir(stage)
    except PathUnresolved as exc:
        print(f"[run_fwci] {exc}", file=sys.stderr)
        return 2

    target = run_dir / "code" / ported.name
    print(f"[run_fwci] {stage}: run directory -> {run_dir}")
    print(f"[run_fwci] staged {ported.relative_to(REPO)} ({_link(ported, target)})")
    if stage == "build":
        shim = _frozen_legacy_shim(run_dir.parent)
        os.environ["SAR_LEGACY_THESIS"] = str(shim)
        print(f"[run_fwci] NEWPOP <- data/fwci/fwci_baseline_pop_full.parquet (frozen, manifest-"
              f"pinned) via $SAR_LEGACY_THESIS={shim}")
    for rel in outputs:                      # DuckDB's COPY does not create directories
        (run_dir / rel).parent.mkdir(parents=True, exist_ok=True)
    for line in _preimport(modules):
        print(f"[run_fwci] production module {line}")

    sys.argv = [str(target), *rest]
    os.environ.setdefault("PYTHONHASHSEED", "0")
    t0 = time.time()
    try:
        # T4 review MAJOR-1: mark THIS staged file as the permitted entry point. The guard in
        # pipeline/lib/paths.py refuses a ported script run anywhere else under pipeline/. The mark
        # is in-process and scoped to the block (T8): an environment variable was settable by the
        # person the guard protects, and the refusal message named it.
        with staged_run(target):
            runpy.run_path(str(target), run_name="__main__")
    except PathUnresolved as exc:
        print(f"[run_fwci] {exc}", file=sys.stderr)
        return 2
    except SystemExit as exc:
        if int(exc.code or 0):
            return int(exc.code or 0)
    print(f"[run_fwci] {stage} finished in {time.time() - t0:.1f} s; outputs:")
    for rel in outputs:
        f = run_dir / rel
        print(f"    {'OK  ' if f.is_file() else 'MISSING'} {f}"
              + (f"  ({f.stat().st_size:,} B, sha256 {_sha(f)})" if f.is_file() else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run a ported FWCI stage in a staged run directory the write barrier approved.")
    ap.add_argument("stage", nargs="?", choices=sorted(STAGES), help="which stage to run")
    ap.add_argument("--execute", action="store_true",
                    help="required by the stages this plan keeps switched off")
    ap.add_argument("--list", action="store_true", help="list the stages, their cost and outputs")
    ap.add_argument("rest", nargs=argparse.REMAINDER, help="arguments passed to the ported script")
    args = ap.parse_args(argv)

    if args.list or not args.stage:
        print(f"fwci stages (set ${OUT_ROOT_ENV} to move the scratch root):\n")
        for name, (script, outputs, _modules, gated) in STAGES.items():
            print(f"  {name:6s} {script}")
            print("         " + ("** OFF BY DEFAULT - needs --execute: " + _scan_cost()
                                 if gated else "runs by default"))
            for rel in outputs:
                print(f"         -> <run dir>/{rel}")
        if unregistered_scripts():
            print(f"\n  !! ported script(s) with no stage: {unregistered_scripts()}")
        return 0 if args.stage else 1
    return run(args.stage, args.execute, [a for a in args.rest if a != "--"])


if __name__ == "__main__":
    raise SystemExit(main())
