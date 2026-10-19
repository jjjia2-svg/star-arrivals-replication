#!/usr/bin/env python3
"""The entry point for every ported driver — repo-authored, not part of the verbatim port.

Why this exists. Three of the six ported drivers would overwrite something irreplaceable if run
carelessly, and two of them can be protected inside the port: `common80.R_PKG` and the U3 driver's
`OUT` are patched path constants, so the write barrier in `pipeline/lib/paths.py` attaches to them.
`step3_run_u6.py` cannot be: it writes to `common80.U6_OUT`, which is built by the legacy line
`U6_OUT = SSD / "u6_ship_11school_p10_80ev_2026-07-22"` — no absolute path, therefore not a
path-resolution hunk, therefore untouchable under the verbatim rule. Attaching the barrier to `SSD`
instead does not work either: `SSD` is also the parent of the READ anchors (`U4_16EV`, `REGISTRY_V5`,
`ROSTER_V4_PROJ8`, `ADELAIDE_MERGED`), all of them non-empty directories that must stay readable.

So the check moves one level out. This launcher reads each driver's OWN declared output constant —
it re-implements nothing and hard-codes no path — pushes it through `output_target()`, and only if
that returns does it hand the UNMODIFIED script to `runpy`. Zero ported bytes change, step3 is
mechanically barred rather than merely documented, and every driver added in Tasks 4-8 can be
registered here the same way.

    python3 pipeline/drivers/run_driver.py --list
    python3 pipeline/drivers/run_driver.py step1
    SAR_OUT_ROOT=/some/scratch python3 pipeline/drivers/run_driver.py step4

`$SAR_OUT_ROOT` redirects a driver's output; it must be an ABSOLUTE path, and it is itself checked
against the same barrier, so it cannot be pointed back at a legacy or frozen location. It is
single-use per driver: the second run into the same root is refused, because by then the destination
exists and is non-empty. Use a fresh root to re-run.

Coverage is not universal, and the gap is stated rather than implied: the launcher checks
destinations that a driver declares as MODULE-LEVEL constants. A future driver that builds its
destination inside `main()` would get no check here, and must guard itself the way the U3 driver does.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import runpy
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))
from pipeline.lib.paths import (BarredWriteTarget, OUT_ROOT_ENV, staged_run,  # noqa: E402
                                PathUnresolved, WriteBarred, output_target)

DRIVERS_DIR = pathlib.Path(__file__).resolve().parent
COMMON80_DIR = DRIVERS_DIR / "final80_p10_2026-07-22"

#: driver name -> (script relative to this directory, the constants in common80.py naming its output)
#: The output is never spelled out here; it is read from the driver's own module.
DRIVERS: dict[str, tuple[str, tuple[str, ...]]] = {
    "step1": ("final80_p10_2026-07-22/step1_freeze_ship_80ev.py", ("U4_OUT",)),
    "step2": ("final80_p10_2026-07-22/step2_run_u5_fast.py", ("U5_OUT",)),
    "step3": ("final80_p10_2026-07-22/step3_run_u6.py", ("U6_OUT",)),
    "step4": ("final80_p10_2026-07-22/step4_export_r.py", ("R_PKG",)),
    # The U3 driver declares its own OUT and is barred at import by the same helper; it shares no
    # constants module, so there is nothing for the launcher to check ahead of it.
    "u3": ("u3_run/run_u3_rebuild_f123_2026-07-06.py", ()),
}

#: the ONLY drivers allowed an empty constants tuple, and why. A driver missing from both DRIVERS'
#: constants and this map is unchecked, and `tests/test_verbatim_pipeline.py` fails.
SELF_GUARDED: dict[str, str] = {
    "u3": "it wraps its own OUT in output_target() at module level, so it refuses before main()",
}


def unregistered_scripts() -> list[str]:
    """Driver scripts present on disk but absent from `DRIVERS`. Used by the test that keeps this
    map honest as Tasks 4-8 add drivers; an unregistered script gets no launcher check at all."""
    registered = {script for script, _ in DRIVERS.values()}
    found = sorted(f.relative_to(DRIVERS_DIR).as_posix()
                   for f in DRIVERS_DIR.glob("*/*.py") if f.name != "common80.py")
    return [f for f in found if f not in registered]


def _declared_outputs(names: tuple[str, ...]) -> list[pathlib.Path]:
    """Read the driver's own output constants. Importing common80 is side-effect free."""
    if not names:
        return []
    if str(COMMON80_DIR) not in sys.path:
        sys.path.insert(0, str(COMMON80_DIR))
    import common80  # noqa: PLC0415  - deliberately late: it resolves paths at import
    out = []
    for name in names:
        value = getattr(common80, name)
        # R_PKG is already behind the deferred barrier; ask for the destination it declared so the
        # refusal is raised here, before the script runs, with the immediate message.
        out.append(value.declared_target() if isinstance(value, BarredWriteTarget)
                   else pathlib.Path(value))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run a ported pipeline driver with its output location checked first.")
    ap.add_argument("driver", nargs="?", choices=sorted(DRIVERS), help="which driver to run")
    ap.add_argument("--list", action="store_true", help="list the drivers and their destinations")
    ap.add_argument("rest", nargs=argparse.REMAINDER, help="arguments passed to the driver")
    args = ap.parse_args(argv)

    if args.list or not args.driver:
        print(f"drivers (set ${OUT_ROOT_ENV} to redirect output):\n")
        for name, (script, names) in DRIVERS.items():
            print(f"  {name:6s} {script}")
            if not names:
                # never blank: an empty spec must be visibly different from a checked one, or
                # deleting a driver's coverage looks exactly like a driver that needs none.
                print(f"         ** NO OUTPUT CONSTANT REGISTERED - "
                      f"{SELF_GUARDED.get(name, 'this driver is NOT checked by the launcher')}")
                continue
            for path in _declared_outputs(names):
                try:
                    resolved = output_target(path, name)
                    print(f"         -> {resolved}")
                except WriteBarred as exc:
                    print(f"         !! BARRED ({exc.reason}): {exc.target}")
        return 0 if args.driver else 1

    script, names = DRIVERS[args.driver]
    if not names and args.driver not in SELF_GUARDED:
        print(f"[run_driver] {args.driver} declares no output constant and is not listed in "
              f"SELF_GUARDED - refusing to run a driver the launcher cannot check.", file=sys.stderr)
        return 2
    try:
        paths = _declared_outputs(names)
    except PathUnresolved as exc:                  # e.g. a relative or unusable $SAR_OUT_ROOT
        print(f"[run_driver] {exc}", file=sys.stderr)
        return 2
    for path in paths:
        try:
            resolved = output_target(path, args.driver)
        except PathUnresolved as exc:              # WriteBarred is a PathUnresolved
            print(f"[run_driver] {exc}", file=sys.stderr)
            return 2
        print(f"[run_driver] {args.driver} output -> {resolved}", flush=True)

    target = DRIVERS_DIR / script
    sys.argv = [str(target), *args.rest]
    os.environ.setdefault("PYTHONHASHSEED", "0")
    try:
        # T4 review MAJOR-1: name the script this launcher is about to run, so the resolver guard
        # can tell a launched driver from someone running a ported script where it sits in the tree.
        # In-process and block-scoped since T8 - see pipeline/lib/paths.py::staged_run.
        with staged_run(target):
            runpy.run_path(str(target), run_name="__main__")
    except PathUnresolved as exc:              # a driver that guards its own destination
        print(f"[run_driver] {exc}", file=sys.stderr)
        return 2
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
