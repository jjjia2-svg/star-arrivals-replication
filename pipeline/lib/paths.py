"""Path resolution for the ported pipeline layer (M3).

The legacy `multiplex_pipeline/` tree hard-coded the author's machine in 17 places: the external
SSD's `openalex_pipeline` directory and one home-directory interpreter path. Those are the only
lines the verbatim port was allowed to change, and every one of them now comes from here.

Layering: this builds on `analysis/lib/paths.py` (the repo's single config reader), so
`config/paths.yaml` stays the one file that knows where things are. Environment variables override
config for machine-specific values; nothing here ever falls back to a silent wrong default —
a missing setting raises with the key name and the file to edit.

    from pipeline.lib.paths import derived_root, snapshot_root, require_mounted
"""
from __future__ import annotations

import contextlib
import functools
import os
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:  # lets the ported units import `pipeline.lib.paths`
    sys.path.append(str(REPO_ROOT))  # append, never insert: must not shadow a ported top-level module

from analysis.lib.paths import config_file as _config_file, load_paths  # noqa: E402

#: the config in force. Read through `analysis.lib.paths.config_file()` so `$SAR_PATHS_CONFIG` moves
#: BOTH halves of the repo at once - a pipeline layer that quietly kept reading `config/paths.yaml`
#: while the analysis layer followed the override is exactly the kind of half-applied switch that
#: makes a self-containment measurement lie (it did, on the first attempt at the T8-review fix).
CONFIG_FILE = _config_file()

#: env var -> config key, for the values that differ per machine.
#: `SAR_LEGACY_THESIS` was added in T8 for the FWCI `build` stage: the ported builder names its
#: NEWPOP input through the legacy thesis root, on a line that holds no absolute path and therefore
#: could not be resolved when the file was ported. That input is frozen, byte for byte, in
#: `data/fwci/` — so `run_fwci.py` builds a one-file shadow of the legacy layout in its scratch tree
#: and points this variable at it, which makes the stage runnable from the package alone.
ENV_OVERRIDES = {"SAR_SSD_ROOT": "ssd_root", "SAR_LEGACY_MULTIPLEX": "legacy_multiplex",
                 "SAR_LEGACY_THESIS": "legacy_thesis"}

#: `ssd_root`'s last component is not cosmetic - the ported u1 test
#: `units/u1_fetch/tests/test_capacity_gate.py:155` asserts the derived root ends with
#: "openalex_pipeline/derived/", and that assertion is part of the verbatim port. Guarding here turns
#: a confusing capacity-gate test failure into a path error that says what to fix (T1-review F4).
SSD_ROOT_LEAF = "openalex_pipeline"


class PathUnresolved(RuntimeError):
    """A required location is not configured, is malformed, or is not usable on this machine."""


@functools.lru_cache(maxsize=1)
def _config() -> dict:
    return load_paths(CONFIG_FILE)


def configured(key: str) -> tuple[pathlib.Path, str]:
    """One configured location plus where it came from ("$SAR_..." or "config/paths.yaml").

    `$SAR_<KEY>` wins over config/paths.yaml where an override exists.
    """
    for env, cfg_key in ENV_OVERRIDES.items():
        if cfg_key == key and os.environ.get(env, "").strip():
            return pathlib.Path(os.environ[env].strip()).expanduser(), "$" + env
    try:
        value = _config()[key]
    except KeyError:
        raise PathUnresolved(
            f"'{key}' is not set. Add it to {CONFIG_FILE}"
            + (f" or export ${[e for e, c in ENV_OVERRIDES.items() if c == key][0]}."
               if key in ENV_OVERRIDES.values() else ".")
        ) from None
    if not str(value).strip():
        raise PathUnresolved(f"'{key}' is empty in {CONFIG_FILE}.")
    return value, str(CONFIG_FILE)


def ssd_root() -> pathlib.Path:
    """The pipeline's data root — the `openalex_pipeline` directory on the author's external SSD.

    Validation policy (T1-review F3/F4), chosen by measurement rather than by preference:

    * The **shape** is always checked: the last component must be `openalex_pipeline` (see
      `SSD_ROOT_LEAF`). This costs nothing and turns a baffling test failure into a path error.
    * An **`$SAR_SSD_ROOT` override is checked strictly** — it must exist, be a directory, and be
      writable. Setting that variable is a deliberate act, so a value pointing nowhere is a typo,
      and this is exactly the case where a ported write default would otherwise aim at the wrong
      directory.
    * A value coming from **`config/paths.yaml` is not required to exist.** The ported units compute
      module-level *defaults* from it at import time and open nothing; requiring existence there
      makes the whole ported suite uncollectable on any machine without the 696 GB disk (measured:
      15 collection errors). Drivers that actually read or write must call `require_readable()` /
      `require_writable()` at entry instead — that is the boundary where a wrong path must stop.
    """
    root, origin = configured("ssd_root")
    if root.name != SSD_ROOT_LEAF:
        raise PathUnresolved(
            f"ssd_root must end in '{SSD_ROOT_LEAF}', got {root} (from {origin}).\n"
            f"The ported u1 capacity-gate test asserts the derived root ends with "
            f"'{SSD_ROOT_LEAF}/derived/'. Point it at the directory that CONTAINS derived/ and "
            f"snapshot/, e.g. /my/disk/{SSD_ROOT_LEAF}."
        )
    if origin.startswith("$"):
        if not root.exists():
            raise PathUnresolved(
                f"{origin} points at a path that does not exist: {root}\n"
                f"Unset it to fall back to 'ssd_root' in {CONFIG_FILE}, or point it at the copy of "
                f"the pipeline data disk on this machine."
            )
        if not root.is_dir():
            raise PathUnresolved(f"{origin} is not a directory: {root}")
        if not os.access(root, os.W_OK):
            raise PathUnresolved(
                f"{origin} is not writable: {root}\n"
                f"The pipeline writes its derived tables under this root."
            )
    elif root.exists() and not root.is_dir():
        raise PathUnresolved(f"'ssd_root' in {CONFIG_FILE} is not a directory: {root}")
    return root


def derived_root() -> pathlib.Path:
    """Where every unit writes its derived tables (`<ssd_root>/derived`)."""
    return ssd_root() / "derived"


def snapshot_root() -> pathlib.Path:
    """The 696 GB OpenAlex snapshot U1 streams (`<ssd_root>/snapshot`)."""
    return ssd_root() / "snapshot"


def legacy_multiplex() -> pathlib.Path:
    """The read-only legacy tree this port is checked against (tests only; never written to)."""
    return configured("legacy_multiplex")[0]


def legacy_thesis() -> pathlib.Path:
    """The read-only legacy thesis tree (`v2_output/` hangs off it).

    Only one ported driver needs it: `drivers/final80_p10_2026-07-22/step4_export_r.py` wrote its R
    package into `<legacy_thesis>/v2_output/r_p10_80ev_2026-07-22`. Resolving it here keeps the
    record truthful about where the July artifact actually went; it also means step4 is
    documented-not-run, because re-running it would overwrite frozen legacy files.
    """
    return configured("legacy_thesis")[0]


def legacy_roots() -> tuple[pathlib.Path, ...]:
    """Every configured read-only legacy tree. Writing inside one of these is always a mistake."""
    out = []
    for key in ("legacy_multiplex", "legacy_v2_output", "legacy_thesis"):
        try:
            out.append(configured(key)[0])
        except PathUnresolved:
            pass
    return tuple(out)


def is_inside_legacy(path) -> pathlib.Path | None:
    """The legacy root that contains `path`, or None."""
    def _real(q: pathlib.Path) -> pathlib.Path:
        # resolve BOTH sides or neither: /var -> /private/var on macOS made the comparison miss
        return q.resolve() if q.exists() else q
    path = _real(pathlib.Path(path))
    for root in legacy_roots():
        try:
            path.relative_to(_real(root))
        except ValueError:
            continue
        return root
    return None


# --- the write barrier (T2-review F3) ------------------------------------------------------------
# A ported driver may name a destination that must never be written on a replicator's machine:
# `step4_export_r.py` targets the read-only legacy thesis tree, and the U3 driver targets a FROZEN
# artifact on the data disk. Both were protected by a sentence in a README; a plain
# `python3 …/step4_export_r.py` truncated and replaced four frozen files, exit 0.
#
# The barrier lives here, in the resolver, because the driver's own logic may not be edited. Two
# entry points, differing only in WHEN they refuse:
#
#   output_target(p)           raises immediately. For a standalone script, where refusing to start
#                              is the right answer.
#   deferred_output_target(p)  returns a path-shaped object that refuses at the moment of writing.
#                              For a destination declared in a SHARED module: `common80.R_PKG` is
#                              only used by step4, but step1/step2/step3 import the same module and
#                              must keep working.
#
# Either way `$SAR_OUT_ROOT` turns the driver back on, pointed somewhere safe.

OUT_ROOT_ENV = "SAR_OUT_ROOT"


class WriteBarred(PathUnresolved):
    """A ported driver's declared destination may not be written on this machine."""

    def __init__(self, message: str, target: pathlib.Path, reason: str):
        super().__init__(message)
        self.target = target        #: the destination as the legacy code declared it
        self.reason = reason        #: "legacy" | "frozen"


#: the ONLY place inside this repository a pipeline stage may create output. It is git-ignored, and
#: every other stage in the repo already treats it as scratch. Anything else under the repo root is
#: source: committing a rebuild into it is how a generated file becomes indistinguishable from a
#: frozen one (T4 review MAJOR-1 - a direct run of the ported scan created
#: `pipeline/fwci/<run dir>/{data,logs,partial}/`, untracked but NOT ignored, holding a second,
#: unhashed `fwci_baseline_pop_full.parquet` with the same basename as the manifest-pinned artifact).
REPO_OUTPUT_ROOTS: tuple[pathlib.Path, ...] = (REPO_ROOT / "output",)


def _inside(path: pathlib.Path, root: pathlib.Path) -> bool:
    def _real(q: pathlib.Path) -> pathlib.Path:
        return q.resolve() if q.exists() else q
    try:
        _real(path).relative_to(_real(root))
    except ValueError:
        return False
    return True


def _barred_reason(path: pathlib.Path) -> tuple[str, str] | None:
    """(reason, human explanation), or None when `path` is a safe place to create output."""
    root = is_inside_legacy(path)
    if root is not None:
        return "legacy", f"it is inside the read-only legacy tree {root}"
    if _inside(path, REPO_ROOT) and not any(_inside(path, r) for r in REPO_OUTPUT_ROOTS):
        return "repo", (
            f"it is inside the repository's own source tree ({REPO_ROOT}) and not under "
            f"{', '.join(str(r) for r in REPO_OUTPUT_ROOTS)}, the one output location this repo "
            f"treats as scratch. A pipeline stage that writes into the tracked tree puts generated "
            f"files next to frozen ones, where `git add -A` cannot tell them apart")
    if path.is_dir() and any(path.iterdir()):
        return "frozen", (f"it already exists and holds {sum(1 for _ in path.iterdir())} entries - "
                          f"on this machine that is a frozen artifact of the original run")
    return None


def _barrier_message(path: pathlib.Path, why: str, what: str | None) -> str:
    return (
        f"refusing to use {what or 'this driver'}'s original output location:\n"
        f"    {path}\n"
        f"  because {why}.\n"
        f"  Re-running the driver here would overwrite data that cannot be regenerated.\n"
        f"  Pass an output root instead:  export {OUT_ROOT_ENV}=/somewhere/writable\n"
        f"  (the driver then writes <{OUT_ROOT_ENV}>/{path.name} and touches nothing else)."
    )


def _redirected(path: pathlib.Path) -> pathlib.Path | None:
    """`$SAR_OUT_ROOT`/<name>, or None when the replicator has not set an output root.

    The redirect is subject to the SAME barrier it turns off (T2 re-review R1). Before this check,
    `SAR_OUT_ROOT=<legacy_thesis>/v2_output` handed step4 the real frozen destination with the
    barrier disabled - and a symlink to it did the same while not even looking like the legacy tree.
    Since the documented run block *requires* setting this variable, the obvious wrong value (the
    directory the artifact originally lived in) was exactly the one that restored the hazard.
    """
    override = os.environ.get(OUT_ROOT_ENV, "").strip()
    if not override:
        return None
    root = pathlib.Path(override).expanduser()
    if not root.is_absolute():
        # T2 final review N5: a relative value is resolved against the working directory, so the
        # same command writes to different places depending on where it is run from. Safe (the
        # barrier still judges the resolved path) but not reproducible, which is the point here.
        raise PathUnresolved(
            f"${OUT_ROOT_ENV} must be an absolute path, got {override!r}.\n"
            f"  A relative value resolves against the current working directory, so where the "
            f"driver writes would depend on where you ran it from.\n"
            f"  Did you mean: export {OUT_ROOT_ENV}={pathlib.Path(override).resolve()}")
    require_writable(root, f"${OUT_ROOT_ENV}")
    root = root.resolve()                      # follow symlinks before judging, then judge both
    dest = root / path.name
    barred = _barred_reason(root) or _barred_reason(dest)
    if barred:
        reason, why = barred
        raise WriteBarred(
            f"${OUT_ROOT_ENV} is not a safe output root:\n"
            f"    {root}\n"
            f"  because {why}.\n"
            f"  ${OUT_ROOT_ENV} exists to move a driver's output OUT of the frozen and read-only\n"
            f"  locations - pointing it at one of them puts the hazard back. Choose an empty or new\n"
            f"  directory outside the legacy trees and outside the data disk's dated run outputs.",
            dest, reason)
    return dest


def output_target(path, what: str | None = None) -> pathlib.Path:
    """A ported driver's write destination. Raises now if it is a legacy or frozen location."""
    path = pathlib.Path(path)
    redirect = _redirected(path)
    if redirect is not None:
        return redirect
    barred = _barred_reason(path)
    if barred is None:
        return path
    reason, why = barred
    raise WriteBarred(_barrier_message(path, why, what), path, reason)


def deferred_output_target(path, what: str | None = None):
    """Same rules as `output_target`, but the refusal happens on the first write, not on import."""
    path = pathlib.Path(path)
    redirect = _redirected(path)
    if redirect is not None:
        return redirect
    barred = _barred_reason(path)
    if barred is None:
        return path
    reason, why = barred
    return BarredWriteTarget(path, _barrier_message(path, why, what), reason)


class BarredWriteTarget(os.PathLike):
    """Reads like a path, refuses to be written.

    It deliberately does NOT implement `__fspath__` usefully: `open()`, `os.*` and every library that
    accepts a path-like object go through it, so all of them stop here. Read-only introspection
    (`str`, `name`, `parent`, `exists`) still works, which is what lets the value pins and the
    provenance documentation keep reporting the destination the legacy code declared.
    """

    __slots__ = ("_path", "_message", "reason")

    def __init__(self, path: pathlib.Path, message: str, reason: str):
        self._path, self._message, self.reason = path, message, reason

    # -- readable -------------------------------------------------------------------------------
    def __str__(self) -> str:
        return str(self._path)

    def __repr__(self) -> str:
        return f"<BarredWriteTarget {self._path} ({self.reason})>"

    def __eq__(self, other) -> bool:
        return str(self) == str(other)

    def __hash__(self) -> int:
        return hash(str(self._path))

    @property
    def name(self) -> str:
        return self._path.name

    @property
    def parent(self):
        return BarredWriteTarget(self._path.parent, self._message, self.reason)

    def exists(self) -> bool:
        return self._path.exists()

    def is_dir(self) -> bool:
        return self._path.is_dir()

    def is_file(self) -> bool:
        return self._path.is_file()

    def declared_target(self) -> pathlib.Path:
        return self._path

    # -- barred ---------------------------------------------------------------------------------
    def _refuse(self, *_a, **_k):
        raise WriteBarred(self._message, self._path, self.reason)

    __fspath__ = _refuse
    mkdir = open = touch = write_text = write_bytes = rename = replace = _refuse
    unlink = rmdir = symlink_to = hardlink_to = chmod = _refuse

    def __truediv__(self, other):
        return BarredWriteTarget(self._path / other, self._message, self.reason)

    def joinpath(self, *others):
        return BarredWriteTarget(self._path.joinpath(*others), self._message, self.reason)


# --- staging a relocated run directory (T5) ------------------------------------------------------
# A third shape, which neither existing mechanism could hold. `output_target()` moves a
# DESTINATION; `pipeline/fwci/run_fwci.py` moves the SCRIPT. Both fail for a ported script whose one
# absolute constant is at once its input root and its output root:
#
#   rosters/.../verify/merge_chemmath_verified_v2.py   BASE = "<v2_output>/multidisc_roster_..."
#   rosters/.../code/00c_prep_final_population.py      ROOT = "<thesis>"; OUT = f"{ROOT}/.../final"
#
# Every read and every write hangs off that single line. Pointing it at the legacy tree rewrites
# read-only evidence (the merge re-creates `_backup_pre_gapfill_2026-08-10` and overwrites
# `rejected_persons_chemmath.csv`); pointing it at a fresh empty directory removes the inputs. The
# only honest answer is to relocate the whole directory: a launcher builds a staging mirror with the
# inputs LINKED in, and this hands the ported constant that mirror.
#
# Why this is not `output_target()`, stated so the difference cannot be mistaken for an oversight:
# that function refuses an existing non-empty directory as a frozen artifact. Correct for a pure
# destination — and exactly wrong here, because a staging mirror MUST already hold the inputs when
# the script starts. That single rule is relaxed. Nothing else is: the staged root is still refused
# if it is inside a legacy tree or inside the repository's own source tree, it must be absolute and
# writable, and — the rule that matters — WITHOUT a staged root this raises rather than falling back
# to the legacy location. There is no configuration in which a ported roster script writes where the
# original run wrote.
STAGE_ROOT_ENV = "SAR_STAGE_ROOT"


#: the two anchors a legacy RUN DIRECTORY is a direct child of. A run directory is the unit the
#: launcher mirrors, so it is also the unit this resolver maps; naming the anchors explicitly is
#: what keeps the mapping from matching some incidental `data/` or `code/` component (T7).
def _legacy_run_dir_of(path: pathlib.Path) -> pathlib.Path | None:
    """The legacy run directory `path` lives in (or is), or None."""
    thesis = legacy_thesis()
    anchors = (thesis, thesis / "v2_output")
    for cand in (path, *path.parents):
        if cand == thesis or cand.parent in anchors:
            return cand
    return None


def staged_run_dir(legacy_dir, what: str | None = None) -> pathlib.Path:
    """The staging mirror of a legacy run directory, or a refusal. See the block comment above.

    Returns `<$SAR_STAGE_ROOT>/<basename of legacy_dir>`, which must already exist — building it is
    the launcher's job, and a missing mirror means the launcher and the script disagree about where
    the run is, which must be an error rather than a directory quietly created next to nothing.

    **T7 generalisation: a path INSIDE a run directory.** The frame builders do not have one
    constant that is both root and destination; they have three to five FULLY EXPANDED absolute
    destinations, because `02_clone_chain.py` machine-generated them by textual substitution. Those
    are path-resolution hunks and therefore patchable, but `output_target()` cannot take them: its
    `$SAR_OUT_ROOT` redirect refuses a root that already holds entries, so the second of a script's
    writes fails on a root the script's own first write had just filled. The rule that a mirror must
    already exist is what makes this safe to relax: `<mirror>/<rest of the path>` is inside a
    directory the launcher built for exactly this run, so `<rest>`'s own parents are the script's
    business and are created on demand. Everything else — absolute, writable, not in a legacy tree,
    not in the repo source tree, and no fallback to the legacy location — is unchanged.
    """
    legacy_dir = pathlib.Path(legacy_dir)
    what = what or "a ported script"
    # first, and before any message about staging: is this a launcher-staged run at all? A ported
    # roster script executed where it sits in the tree must be told THAT, because it is the wider
    # mistake and the one whose fix is a different command.
    refuse_unstaged_in_place_run()
    override = os.environ.get(STAGE_ROOT_ENV, "").strip()
    if not override:
        inside = is_inside_legacy(legacy_dir)
        raise WriteBarred(
            f"refusing to give {what} its original run directory:\n"
            f"    {legacy_dir}\n"
            f"  because that one path is BOTH its input root and its output root"
            + (f", and it is inside the read-only legacy tree {inside}" if inside else "")
            + ".\n"
            f"  Re-running it there would overwrite the frozen artifacts of the original run.\n"
            f"  A launcher stages a mirror of it, links the inputs in, and points this constant at\n"
            f"  the mirror through ${STAGE_ROOT_ENV}:\n"
            f"      python3 pipeline/rosters/run_rosters.py --list\n"
            f"  Set $SAR_OUT_ROOT to an absolute path outside the repo to choose where it goes.",
            legacy_dir, "unstaged")

    root = pathlib.Path(override).expanduser()
    if not root.is_absolute():
        raise PathUnresolved(
            f"${STAGE_ROOT_ENV} must be an absolute path, got {override!r}.\n"
            f"  A relative value resolves against the current working directory, so where the "
            f"stage runs would depend on where you ran it from.")
    require_writable(root, f"${STAGE_ROOT_ENV}")
    root = root.resolve()                       # follow symlinks before judging, then judge both
    dest = root / legacy_dir.name

    def _judge(probe: pathlib.Path, target: pathlib.Path) -> None:
        inside = is_inside_legacy(probe)
        if inside is not None:
            raise WriteBarred(
                f"${STAGE_ROOT_ENV} is not a safe staging root:\n    {root}\n"
                f"  because {probe} is inside the read-only legacy tree {inside}. Staging exists to "
                f"move the run OUT of that tree; pointing it back in puts the hazard back.",
                target, "legacy")
        if _inside(probe, REPO_ROOT) and not any(_inside(probe, r) for r in REPO_OUTPUT_ROOTS):
            raise WriteBarred(
                f"${STAGE_ROOT_ENV} is not a safe staging root:\n    {root}\n"
                f"  because {probe} is inside the repository's own source tree ({REPO_ROOT}) and "
                f"not under {', '.join(str(r) for r in REPO_OUTPUT_ROOTS)}. A stage that writes "
                f"into the tracked tree puts generated files next to frozen ones.",
                target, "repo")

    def _judge_interior(path: pathlib.Path) -> pathlib.Path:
        """T5-review NIT-2 / T7 MINOR-3, closed in T8: judge what the returned path RESOLVES to.

        Everything above judges the staging ROOT and the name hung off it, all before any symlink
        inside the mirror is followed. A hand-built mirror whose run directory (or any component of
        it) is a symlink into the legacy tree therefore passed every check and then wrote through
        the link - the exact resolve-before-judge defect that was fixed for `$SAR_OUT_ROOT` in Task
        2's re-review and left standing here. The documented launchers never build such a mirror,
        which is why this was a registered blind spot rather than a live bug; it is closed the same
        way the root was, by resolving first and judging what comes back.
        """
        real = path.resolve() if path.exists() else path.parent.resolve() / path.name
        _judge(real, path)
        if not _inside(real, root):
            raise WriteBarred(
                f"the staging mirror escapes ${STAGE_ROOT_ENV}:\n    {path}\n"
                f"  resolves to {real}, which is outside {root}. A component of the mirror is a "
                f"symlink pointing elsewhere; the run would write through it. Rebuild the mirror "
                f"with real directories (the launchers do) instead of linking its interior.",
                path, "escaped")
        return path

    for probe in (root, dest):
        _judge(probe, dest)
    if dest.is_dir():
        return _judge_interior(dest)
    run = _legacy_run_dir_of(legacy_dir)
    if run is not None and run != legacy_dir and (root / run.name).is_dir():
        inside = (root / run.name) / legacy_dir.relative_to(run)
        _judge_interior(root / run.name)
        inside.parent.mkdir(parents=True, exist_ok=True)
        return _judge_interior(inside)
    raise PathUnresolved(
        f"${STAGE_ROOT_ENV} is set but the staging mirror does not exist:\n    {dest}\n"
        + (f"  (nor {root / run.name}, the mirror of the run directory {run.name} that\n"
           f"   {legacy_dir} belongs to)\n" if run is not None and run != legacy_dir else "")
        + f"  The launcher builds it (and links the stage's inputs into it) before the ported "
        f"script runs. Run the stage through pipeline/rosters/run_rosters.py or "
        f"pipeline/frames/run_frames.py.")


def pipeline_root() -> pathlib.Path:
    """`<repo>/pipeline` — the depth `contracts/`, `config/` and `units/` are anchored on."""
    return configured("pipeline_root")[0]


# --- the staged-run marker (T4 review carry, closed in T8) ---------------------------------------
# How a STAGED run of a ported script is told apart from someone running that script where it sits
# in the tree. Until Task 8 this was the environment variable `$SAR_STAGED_RUN`, and that was wrong
# in a way worth stating: an environment variable is settable by the person being protected. Anyone
# who hit the refusal below, read its message, and exported the variable it names got the hazard
# back — a 37-minute scan writing into the repository's source tree — with no warning at all.
#
# No launcher ever needed it. All five `runpy.run_path(...)` the staged script IN THIS PROCESS, so
# the marker can be a module-level variable of this very module: the ported script imports
# `pipeline.lib.paths`, gets the same module object, and sees the mark. It is set by a context
# manager, so it is restored on the way out and a crashed stage cannot leave the exemption standing
# for whatever runs next.
#
# The old variable name is kept ONLY as something to refuse: `tests/test_paths.py` proves that
# exporting it does not exempt anything.
STAGED_RUN_ENV = "SAR_STAGED_RUN"          # historical; read by nothing, honoured by nothing

#: the script a launcher is running right now, or None. Never read the environment for this.
_STAGED_RUN: pathlib.Path | None = None


@contextlib.contextmanager
def staged_run(script):
    """Mark `script` as launcher-staged for the duration of the block, then restore.

    Nested use is supported (`run_frames.py` and `run_stars.py` each runpy a second ported script
    inside the first stage), and the previous mark is restored rather than cleared.
    """
    global _STAGED_RUN
    previous = _STAGED_RUN
    _STAGED_RUN = pathlib.Path(script).resolve()
    try:
        yield _STAGED_RUN
    finally:
        _STAGED_RUN = previous


def staged_run_script() -> pathlib.Path | None:
    """The script the current launcher stage is running, for tests and for error messages."""
    return _STAGED_RUN

#: the repo-authored launchers, which ARE meant to be executed where they sit. Everything else under
#: `pipeline/` is ported code whose output location was written for the author's machine.
LAUNCHERS: tuple[str, ...] = ("pipeline/drivers/run_driver.py", "pipeline/fwci/run_fwci.py",
                              "pipeline/rosters/run_rosters.py", "pipeline/stars/run_stars.py",
                              "pipeline/frames/run_frames.py",
                              # M4/cal2026-08-28: the caliber driver — repo-authored, stages the
                              # ported 72 restake the same way run_stars.py does (Task 1 of the
                              # author-signed caliber rebuild)
                              "pipeline/stars/caliber_2026-08-28/run_caliber.py",
                              # cal2026-08-28 Task 2: the supplement-fetch driver — repo-authored,
                              # runs NO ported script (so it stages nothing); it is a launcher
                              # because it reads the legacy tree through require_readable while
                              # being an entry point under pipeline/
                              "pipeline/stars/caliber_2026-08-28/run_supplement.py",
                              # cal2026-10: the October re-rank driver (all 187 event stars, every
                              # per-paper cleanup, top-5% flag) — repo-authored, same machine
                              "pipeline/stars/caliber_2026-10/run_caliber.py",
                              # cal2026-10: the economics re-rank on the 11-school extraction
                              # (the table the July machine ranked on), with its July control
                              "pipeline/stars/caliber_2026-10/restake_econ11.py",
                              # cal2026-10: the local estimation driver (28 cells + pos/med cuts)
                              "pipeline/stars/caliber_2026-10/run_cal_estimates.py",
                              # cal2026-10: the Panel 3 sweep (verbatim afar stage over the October
                              # pair tables + pos/med cuts + counts-by-spec), with its 08-28 control
                              "pipeline/frames/cal2026-10/run_cal_afar.py",
                              # cal2026-10 piece B: economics through the chem/math gold chain —
                              # repo-authored; stages the three `_econ` clones beside it the way
                              # run_frames.py stages the originals (run dir + staged_run mark) and
                              # runs the R cells; the control against the 2026-09-13 verified-pool
                              # cells is mandatory before any new-input run
                              "pipeline/frames/cal2026-10/econ_gold/run_econ_gold.py",
                              # cal2026-10 econ920: economics through the CANONICAL econ chain —
                              # repo-authored; runs the path-wired clone of the un-ported union rung
                              # (00_build_frame_econ920_cal.py, DIFF.md) and piece A's prodlib
                              # staging in process inside staged_run marks, the ported ledger /
                              # p1-econ / split / p2-econ through run_frames.py subprocesses, and
                              # the verbatim R drivers; four controls (c1a/c1b/c2/c3) precede the
                              # October run and a failed control stops it
                              "pipeline/frames/cal2026-10/econ920/run_econ920.py",
                              # cal2026-10: the chemistry / math_stats frames driver — repo-authored;
                              # control chain (must reproduce the 08-28 frozen products) then the
                              # October chain with the D2 in-post stage, through run_frames.py
                              # subprocesses and stage.run_prodlib (staged_run mark inside it)
                              "pipeline/frames/cal2026-10/run_cal_frames_chemmath.py",
                              # cal2026-08-28 Task 3: the frames-rebuild driver — repo-authored;
                              # it drives the ported builders through run_frames.py subprocesses
                              # and runs ONE verbatim-staged legacy script (prodlib build_frame)
                              # inside a staged_run mark, sha-asserted against its pin
                              "pipeline/stars/caliber_2026-08-28/run_cal_frames.py",
                              # cal2026-08-28 Task 4: the local-estimation driver — repo-authored,
                              # runs NO ported python (Rscript subprocesses over the VERBATIM
                              # analysis/estimation drivers, their own argv+$SAR_OUT contract);
                              # a launcher because it is an entry point under pipeline/
                              "pipeline/stars/caliber_2026-08-28/run_cal_estimates.py",
                              # cal2026-08-28 Task 5: the cloud-cells custody driver —
                              # repo-authored, runs NO ported code and NO aws command (the
                              # money-spending commands are the operator's, per pipeline/aws/
                              # discipline); it hash-verifies the payloads before upload and the
                              # custody chain after the fetch, then freezes the four results
                              "pipeline/stars/caliber_2026-08-28/run_cal_cloud.py",
                              # cal2026-08-28 Task 6: the caliber-ledger driver — repo-authored;
                              # it runpy-runs the UNEDITED analysis/paper/ledger_p3afar.py (not
                              # ported pipeline code; the staged_run mark satisfies the guard's
                              # count identity) with load_paths() pointed at the cal artifacts
                              "pipeline/stars/caliber_2026-08-28/run_cal_ledger.py")


def _main_script() -> pathlib.Path | None:
    main = sys.modules.get("__main__")
    f = getattr(main, "__file__", None)
    return pathlib.Path(f).resolve() if f else None


def refuse_unstaged_in_place_run() -> None:
    """T4 review MAJOR-1. Refuse when the process's entry point is a PORTED script sitting in the
    tree, rather than a run a launcher staged.

    Why here. The two FWCI scripts and `common80` build every output path from their own `__file__`
    (`BASE = Path(__file__).resolve().parent.parent`) or from a shared constants module — lines that
    hold no absolute path and therefore may not be touched under M3's verbatim rule. `output_target`
    cannot help, because nothing ever calls it with those paths: the script simply computes them and
    writes. So the refusal attaches to the resolver call the ported code DOES make on every
    invocation — the `require_readable` / `require_writable` guard wired into its path constants —
    and it fires at import, before `main()` can open anything.

    Exempt: the declared launchers (they are repo-authored and meant to run in place), a run a
    launcher marked with `staged_run()` IN THIS PROCESS, and anything whose entry point is not under
    `pipeline/` at all (pytest, a REPL, a replicator's own script).

    T8: the exemption used to be `$SAR_STAGED_RUN`, which the refusal message itself named, so the
    way out of the guard was to export the variable in the error text. All five launchers `runpy`
    the staged script in this process, so nothing was ever gained by putting the mark in the
    environment; it now lives in a module-level variable that only `staged_run()` can set.
    """
    script = _main_script()
    if script is None or not _inside(script, REPO_ROOT / "pipeline"):
        return
    if any(script == (REPO_ROOT / rel).resolve() for rel in LAUNCHERS):
        return
    if _STAGED_RUN is not None and _STAGED_RUN == script:
        return
    try:
        shown = script.relative_to(REPO_ROOT)
    except ValueError:                                   # pragma: no cover - _inside said otherwise
        shown = script
    raise PathUnresolved(
        f"refusing to run a ported pipeline script where it sits in the tree:\n"
        f"    {shown}\n"
        f"  Ported scripts derive their output directories from their own __file__, so running one\n"
        f"  here writes into the repository's source tree - and the full-snapshot scan would do that\n"
        f"  for 37 minutes before you noticed. Their output locations were written for the author's\n"
        f"  machine and cannot be edited (M3's verbatim rule), so a launcher stages the run instead:\n"
        f"      python3 pipeline/fwci/run_fwci.py --list        # FWCI stages, with their cost\n"
        f"      python3 pipeline/drivers/run_driver.py --list   # the ported drivers\n"
        f"      python3 pipeline/rosters/run_rosters.py --list  # the roster stages\n"
        f"      python3 pipeline/stars/run_stars.py --list      # the star and event-gate stages\n"
        f"  Set $SAR_OUT_ROOT to an absolute path outside the repo to choose where output goes.")


#: R1 F0 (2026-10-11): the data disk named in config/paths.yaml is read only on the EC2 rerun host.
#: Design v3 §4: every computation runs on AWS. A $SAR_SSD_ROOT override (a tmp dir in tests,
#: /data/openalex_pipeline on an instance) is not the configured disk and is not guarded here.
DATA_HOST = "ec2-r1"


def _refuse_data_disk_off_ec2(path: pathlib.Path, what: str) -> None:
    if os.environ.get("SAR_HOST", "").strip() == DATA_HOST:
        return
    disk = _config().get("ssd_root")
    if disk is None:
        return
    if _inside(pathlib.Path(path), pathlib.Path(str(disk))):
        raise PathUnresolved(
            f"R1 rule: refusing {what} at {path} - it is on the configured data disk ({disk}) and "
            f"$SAR_HOST is not {DATA_HOST!r}. Every computation runs on AWS (design v3 §4).")


def require_readable(path: pathlib.Path, what: str | None = None) -> pathlib.Path:
    """Return `path`, or fail loudly. Call at the entry of any stage that READS this location.

    `what` defaults to the path itself so the ported drivers can wire the guard into a single-token
    path expression (`_sar_rd(_sar_snapshot_root())`) that still normalises back to the legacy
    literal — see `tests/test_verbatim_pipeline.py`.
    """
    what = what or "a location the pipeline reads"
    refuse_unstaged_in_place_run()
    _refuse_data_disk_off_ec2(path, what)
    if not path.exists():
        # T8 review NIT-8: this message is reached by the $SAR_OUT_ROOT / $SAR_STAGE_ROOT guards too,
        # and telling someone to fix `ssd_root` when they mistyped an output root sends them to the
        # wrong file. Name the variable the caller was actually about.
        hint = (f"Create it, or point ${what.lstrip('$')} somewhere that exists."
                if what.startswith("$") else
                f"Mount the data disk, or point 'ssd_root' in {CONFIG_FILE} (or $SAR_SSD_ROOT) at "
                f"a copy.")
        raise PathUnresolved(f"{what} is not on this machine: {path}\n{hint}")
    if not path.is_dir():
        raise PathUnresolved(f"{what} is not a directory: {path}")
    return path


def require_writable(path: pathlib.Path, what: str | None = None) -> pathlib.Path:
    """Return `path`, or fail loudly. Call at the entry of any stage that WRITES this location.

    A driver that skips this can write a rebuild into the wrong directory instead of failing — the
    one path error that does not announce itself (T1-review F3, closed in T2).
    """
    what = what or "a location the pipeline writes"
    require_readable(path, what)
    if not os.access(path, os.W_OK):
        raise PathUnresolved(
            f"{what} is not writable: {path}\n"
            f"The pipeline writes its derived tables here; fix the permissions or repoint 'ssd_root'."
        )
    return path


#: kept as the old name so nothing that already calls it breaks; prefer the explicit pair above.
require_mounted = require_readable


def openalex_api_key(required: bool = True) -> str | None:
    """`$OPENALEX_API_KEY` — the one env var the ported units read (9 sites, all `os.environ`)."""
    key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if not key and required:
        raise PathUnresolved(
            "OPENALEX_API_KEY is not set. Export it before any stage that calls the OpenAlex API "
            "(u0.5 author alignment, and the preflight environment gate)."
        )
    return key or None
